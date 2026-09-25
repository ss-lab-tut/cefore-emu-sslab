"""Hermetic ok-path product test for the compute_call event.

What it proves, end to end and on real Mininet hosts with real Cefore
daemons: a compute_call event whose endpoint answers HTTP 200 produces
EventOutcome(success=True, outcome="ok"), the response body lands in
``output_file``, cefputfile republishes it under ``publish_uri``, and another
host retrieves those exact bytes with cefgetfile. Until this test existed the
ok path was covered only by FakeCommandRunner units and one manual run; the
smoke scenario asserts the *unreachable* path.

It drives the scheduler handler ``_handle_compute_call`` rather than
``compute_call()`` directly, because the handler is what a scenario actually
executes: it builds the runner, reads ``ctx["run_dir"]`` (without which curl
gets no ``-o`` and publish_ok is False), and maps the ComputeResult onto the
tri-state EventOutcome. Calling the client would leave that mapping untested.

The compute endpoint is a second Mininet host running
``tools/compute_echo_server.py``, so nothing outside this machine is needed.
The HPC variant swaps that host for a real endpoint.

**Cannot run concurrently with the cefore-run-tests smoke**, for two separate
reasons. cefnetd's unix sockets ``/tmp/cef_{port}.{idx}`` and the daemon logs
live at fixed /tmp paths (cefore.py:53-62), so two runs using the same hN
indices fight over them. And teardown's ``kill_cef_processes`` runs
``pkill -9 -f cefnetd`` (and csmgrd, cefputfile, cefgetfile, ...) inside hosts
that share the machine's PID namespace, so it kills every Cefore process on
the box, not only this test's (src/runtime/cleanup.py).

Run:

    sudo env CEFEMU_SYNTHETIC_ROOT=1 PYTHONDONTWRITEBYTECODE=1 \
        .venv/bin/python3 -m pytest -p no:cacheprovider -x -s \
        tests/synthetic/test_compute_ok_path_synthetic.py

Skipped unless CEFEMU_SYNTHETIC_ROOT=1 AND running as root.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from src.core.fib import Route
from src.runtime.scheduler import _handle_compute_call

from ._compute_ok_path import (
    MESH_LINKS,
    SCHEME,
    assert_three_way_bytes,
    get_until_success,
    ok_path_scenario,
    wait_http_ready,
)

# Synthetic tests are env-gated. Skip the entire module if the gate is closed
# or if not running as root, so the default non-root suite ignores it.
SYNTHETIC_GATE = os.environ.get("CEFEMU_SYNTHETIC_ROOT") == "1"

pytestmark = [
    pytest.mark.synthetic,
    pytest.mark.skipif(
        not SYNTHETIC_GATE,
        reason="CEFEMU_SYNTHETIC_ROOT=1 not set",
    ),
    pytest.mark.skipif(
        SYNTHETIC_GATE and os.geteuid() != 0,
        reason="synthetic tests require root",
    ),
]

URI = "ccnx:/test/compute"
ECHO_PORT = 18080
REPO_ROOT = Path(__file__).resolve().parents[2]
ECHO_SERVER = REPO_ROOT / "tools" / "compute_echo_server.py"

# A few KB with NUL and 0xff bytes: large enough to span more than one Cefore
# chunk, and binary enough that any text-mode mangling on the way through
# curl, the file system or ICN shows up as a mismatch.
PAYLOAD = bytes(range(256)) * 16


@pytest.fixture
def mininet_info_logging():
    """Raise Mininet's log level to info for one test, then put it back.

    The default OUTPUT level hides every info() line — compute_call's curl
    argv, DaemonFleet readiness, cefroute failures. Without them a failure
    here is undiagnosable once the namespaces are gone. setLogLevel writes
    process-global state, so the previous level is restored rather than left
    raised for whatever runs next in the same session.
    """
    from mininet.log import LEVELS, lg, setLogLevel

    previous = next(
        (name for name, value in LEVELS.items() if value == lg.level), "output"
    )
    setLogLevel("info")
    yield
    setLogLevel(previous)


def test_compute_call_ok_path_publishes_served_bytes(
    mininet_info_logging, monkeypatch, tmp_path
):
    """compute_call ok: HTTP 200 -> output_file -> cefputfile -> cefgetfile."""
    # Must precede provisioning: see ok_path_scenario's docstring.
    monkeypatch.chdir(tmp_path)

    served = tmp_path / "served" / "payload.bin"
    served.parent.mkdir()
    served.write_bytes(PAYLOAD)

    endpoint_ip = SCHEME.canonical_host_ip(0, MESH_LINKS)

    with ok_path_scenario(tmp_path, URI) as harness:
        # result.fib_routes is the pure computation's output: apply_fib
        # returns the computed routes and drops apply_fib_routes' failures,
        # so this pins that the FIB computation produced the h0->h1 route for
        # this URI. Whether `cefroute add` accepted it is not visible here —
        # that only shows up later, as a cefgetfile that never succeeds.
        expected = Route(
            source=0,
            prefix=URI,
            next_hop=1,
            next_hop_ip=SCHEME.canonical_host_ip(1, MESH_LINKS),
        )
        assert expected in list(harness.result.fib_routes), (
            f"no h0->h1 route for {URI}; got {harness.result.fib_routes}"
        )

        echo_log = tmp_path / "echo_server.log"
        handle = harness.start_background(
            "h0",
            [
                sys.executable,
                str(ECHO_SERVER),
                "--bind",
                endpoint_ip,
                "--port",
                str(ECHO_PORT),
                "--payload-file",
                str(served),
            ],
            echo_log,
        )
        endpoint = f"http://{endpoint_ip}:{ECHO_PORT}/api/process"
        wait_http_ready(harness.runner, "h1", endpoint, handle, echo_log)

        outcome = _handle_compute_call(
            harness.net,
            {
                "host": 1,
                "endpoint": endpoint,
                "method": "POST",
                "payload": '{"query": "analyze"}',
                "headers": {"Content-Type": "application/json"},
                "output_file": "compute_result.bin",
                "publish_uri": URI,
                "timeout": 10,
            },
            MESH_LINKS,
            {"run_dir": tmp_path},
        )
        assert outcome.success is True, f"compute_call failed: {outcome}"
        assert outcome.outcome == "ok"
        assert outcome.detail["http_status"] == 200
        assert outcome.detail["publish_ok"] is True
        # Pin the resolved path (run_dir containment is what makes -o work),
        # then compare the very file the handler says it wrote rather than a
        # second guess at where it landed.
        assert outcome.detail["output_file"] == str(tmp_path / "compute_result.bin")

        received = tmp_path / "recv.bin"
        get_until_success(
            harness.runner,
            0,
            URI,
            received,
            tmp_path / "get.log",
        )
        assert_three_way_bytes(served, Path(outcome.detail["output_file"]), received)
