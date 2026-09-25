"""Shared building blocks for the compute_call ok-path synthetic tests.

Two tests share this scaffolding. The hermetic one serves the compute
endpoint from a second Mininet host; the HPC one points the same scenario at a
real machine through the root-namespace bridge. They differ only in where the
endpoint lives, so everything else — topology, scenario setup/teardown, the
HTTP readiness poll, the cefgetfile retry loop, the byte comparison, the log
level fixture — lives here rather than being copied and left to drift.

The module deliberately holds no test functions: ``_``-prefixed, it is not
collected by pytest and is imported only by the gated test modules, so the
non-root suite never builds a Mininet.
"""

from __future__ import annotations

import random
import time
import warnings
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from mininet.topo import Topo

from src.core.addressing import AddressingScheme
from src.core.roles import assign_roles
from src.runtime.bridge_root import BridgeManager
from src.runtime.cache_strategy import RolesCacheStrategy
from src.runtime.cefore import run_cefgetfile
from src.runtime.cleanup import kill_cef_processes
from src.runtime.command_runner import MininetCommandRunner
from src.runtime.result_detect import detect_get_success
from src.runtime.scenario_setup import (
    ScenarioSetupSpec,
    TeardownSpec,
    create_tclink_mininet,
    setup_scenario,
    teardown_scenario,
)
from src.runtime.template import cleanup_node_dirs, provision_node_dirs

HOST_COUNT = 2

# The canonical mesh_links form topology.py:43-45 accepts. Hand-written rather
# than produced by MeshTopo: MeshTopo's switch count is seed-fragile (seed 0
# yields two switches), and a second switch would add a hop that has nothing to
# do with what these tests prove.
MESH_LINKS: list[dict] = [
    {"subnet": 1, "switch": "s0", "hosts": [0, 1], "host_eth": {0: 0, 1: 0}}
]

# h0 = 192.168.1.1 (consumer + HTTP endpoint), h1 = 192.168.1.2 (compute caller
# and, per fib_uri_publishers, the ICN publisher).
SCHEME = AddressingScheme()


class OneSwitchTopo(Topo):
    """Two hosts on one switch: h0 - s0 - h1.

    One switch keeps the ICN path a single hop, so a failed get is a Cefore or
    FIB problem and never an unlucky topology.
    """

    def build(self, **_kwargs) -> None:
        # Fixed at HOST_COUNT rather than parameterised: MESH_LINKS, the FIB
        # expectation and the role assignment all hard-code two hosts, so a
        # third one would produce a topology nothing else agrees with.
        switch = self.addSwitch("s0")
        for idx in range(HOST_COUNT):
            # One link per host, so every host's data-plane interface is eth0,
            # which is what MESH_LINKS' host_eth claims.
            self.addLink(switch, self.addHost(f"h{idx}"))


@pytest.fixture
def mininet_info_logging():
    """Raise Mininet's log level to info for one test, then put it back.

    The default OUTPUT level hides every info() line — compute_call's curl
    argv, DaemonFleet readiness, cefroute and bridge failures. Without them a
    failure is undiagnosable once the namespaces are gone. setLogLevel writes
    process-global state, so the previous level is restored instead of being
    left raised for whatever runs next in the same session.

    It lives here so both synthetic modules get it from one definition; pytest
    resolves fixtures that a test module imported by name.
    """
    from mininet.log import LEVELS, lg, setLogLevel

    previous = next(
        (name for name, value in LEVELS.items() if value == lg.level), "output"
    )
    setLogLevel("info")
    yield
    setLogLevel(previous)


@dataclass
class OkPathHarness:
    """A started Mininet with the Cefore fleet up and the FIB applied."""

    net: Any
    runner: MininetCommandRunner
    result: Any
    node_dirs: list[Path]
    # Background processes (the echo server) that teardown must reap before
    # the host namespaces they run in disappear.
    handles: list = field(default_factory=list)

    def start_background(self, node: str, argv: list, log_path: Path):
        """Start a long-running process and register it for teardown.

        log_path is mandatory here: without it the child inherits pytest's
        stdout/stderr file descriptors and its diagnostics vanish
        (command_runner.py:187-196), which is exactly what one needs when the
        endpoint fails to come up.
        """
        handle = self.runner.start(node, argv, log_path=str(log_path))
        self.handles.append(handle)
        return handle


@contextmanager
def ok_path_scenario(
    run_dir: Path, publish_uri: str, bridge_configs: list | None = None
):
    """Provision, start and tear down the two-host ok-path scenario.

    The caller must already have chdir'd into a scratch directory: node
    directories are created as ``./hN`` and cefnetd is launched with
    ``-d ./hN`` (template.py:76,102; cef_argv.py:36; cefore.py:172-179), and
    Mininet host processes inherit the pytest process's CWD through mnexec.
    Provisioning before the chdir would litter the repository root.

    The ICN publisher is h1 — the host that runs compute_call — because
    compute_client runs curl and cefputfile on the same host index
    (compute_client.py:151-173). h0 serves HTTP and consumes over ICN.

    Teardown never calls ``cleanup_all()`` or ``BaseScenario.execute()``: both
    run ``mn -c``, which would tear down every Mininet on this machine,
    including someone else's.

    ``bridge_configs`` (None for the hermetic test, which needs no external
    connectivity) goes through the same ScenarioSetupSpec fields disaster uses.
    The BridgeManager is created here rather than by the caller because setup
    and teardown must share one instance: the manager accumulates the cleanup
    actions — the root-ns route, the ip_forward value, the iptables rules —
    and a second instance would tear down nothing while leaving those behind.
    """
    net = None
    result = None
    node_dirs: list[Path] = []
    harness = None
    body_failed = False
    bridge_manager = BridgeManager() if bridge_configs else None
    try:
        roles = assign_roles(HOST_COUNT, random.Random(0))
        node_dirs = provision_node_dirs(roles)
        net = create_tclink_mininet(OneSwitchTopo())
        net.start()
        result = setup_scenario(
            net,
            ScenarioSetupSpec(
                mesh_links=MESH_LINKS,
                scheme=SCHEME,
                host_count=HOST_COUNT,
                publisher_ids={1},
                cache_strategy=RolesCacheStrategy(roles=roles),
                fleet_run_dir=run_dir,
                fib_k=1,
                fib_uri_publishers={publish_uri: 1},
                bridge_manager=bridge_manager,
                bridge_configs=bridge_configs,
                # The default "warn" swallows a dead cefnetd and leaves the
                # test to fail much later with an unexplained empty get.
                fleet_readiness_policy="raise",
            ),
        )
        harness = OkPathHarness(
            net=net,
            runner=MininetCommandRunner(net),
            result=result,
            node_dirs=node_dirs,
        )
        yield harness
    except BaseException:
        body_failed = True
        raise
    finally:
        failures = _teardown(net, result, node_dirs, harness, run_dir, bridge_manager)
        if failures and body_failed:
            # Raising here would replace the real failure with a cleanup one,
            # but staying silent hides leaked namespaces and switches that the
            # next run will trip over — so warn instead.
            warnings.warn(
                f"teardown stages failed after test failure: {failures}", stacklevel=2
            )
        elif failures:
            raise AssertionError(f"teardown stages failed: {failures}")


def _teardown(
    net, result, node_dirs, harness, run_dir: Path, bridge_manager=None
) -> list[str]:
    """Run every teardown stage independently; return the stage failures.

    Each stage is guarded on its own so that one broken stage (a host whose
    shell is wedged, say) still lets the remaining resources go back.
    """
    failures: list[str] = []
    for handle in list(harness.handles if harness else []):
        try:
            # terminate() only sends SIGTERM and returns (command_runner.py:323),
            # and kill_cef_processes' pkill patterns do not cover python, so the
            # echo server has to be reaped here or it outlives the namespace.
            # wait() escalates to SIGKILL itself once the deadline passes
            # (command_runner.py:130-143, :300-305), so no manual kill follows.
            harness.runner.terminate(handle)
            harness.runner.wait(handle, deadline=time.monotonic() + 5)
        except BaseException as exc:  # noqa: BLE001 - stage isolation
            failures.append(f"terminate background process: {exc!r}")
    if net is not None:
        try:
            teardown = teardown_scenario(
                net,
                TeardownSpec(
                    host_count=HOST_COUNT,
                    # No host runs csmgrd in the 2-host role assignment
                    # (h0 CONSUMER CS_MODE=0, h1 PUBLISHER CS_MODE=1).
                    csmgrd_host_ids=set(),
                    fleet_run_dir=run_dir,
                    # Falls back to rebuilding the fleet when setup died before
                    # binding `result` (scenario_setup.py:200-207).
                    daemon_fleet=result.daemon_fleet if result else None,
                    # teardown_scenario runs the manager's cleanup, and it has
                    # to happen before net.stop() below: removing the root-ns
                    # route and the iptables rules needs root-eth0 to still
                    # exist. Never call bridge_manager.cleanup() as well —
                    # not because the actions would run twice (cleanup() drops
                    # the ones that succeeded and keeps only failed mandatory
                    # ones) but because teardown_scenario owns that call and
                    # collects what it raises. A second call here would retry
                    # those retained actions outside TeardownResult, hiding
                    # the failure the first call reported.
                    bridge_manager=bridge_manager,
                ),
            )
            failures.extend(
                f"teardown_scenario {stage}: {exc!r}"
                for stage, exc in teardown.failures
            )
        except BaseException as exc:  # noqa: BLE001 - stage isolation
            failures.append(f"teardown_scenario: {exc!r}")
        try:
            kill_cef_processes(net)
        except BaseException as exc:  # noqa: BLE001 - stage isolation
            failures.append(f"kill_cef_processes: {exc!r}")
        try:
            net.stop()
        except BaseException as exc:  # noqa: BLE001 - stage isolation
            failures.append(f"net.stop: {exc!r}")
    try:
        cleanup_node_dirs(node_dirs)
    except BaseException as exc:  # noqa: BLE001 - stage isolation
        failures.append(f"cleanup_node_dirs: {exc!r}")
    return failures


def _curl_status(runner, host: str, url: str) -> str:
    """Return the HTTP status `host` gets for `url`, as a string.

    Body and errors are discarded on purpose: the caller only wants to know
    whether the endpoint is answering from inside this namespace, and a large
    body would be captured into memory for nothing.
    """
    probe = runner.run(
        host,
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "2", url],
        timeout=5,
    )
    return probe.stdout.strip()


def wait_http_ready(
    runner, host: str, url: str, handle, log_path: Path, timeout: float = 10.0
) -> None:
    """Poll `url` from inside `host` until it answers 200, or fail.

    The probe runs in the Mininet host, not in the test process: what matters
    is that the *host* can reach the endpoint, which is a different question
    from whether the root namespace can. Polling beats a fixed sleep — the
    server is usually up in well under a second, and a wedged one must fail
    loudly rather than surface later as a confusing HTTP error.

    `handle` is the endpoint process. A server that died on startup (a bad
    bind address, a missing payload file) would otherwise cost the full
    timeout and report only "no 200", so its exit status and log are turned
    into the failure the moment it is seen to be gone.
    """
    deadline = time.monotonic() + timeout
    last = "<no probe>"
    while True:
        exited = runner.poll(handle)
        if exited is not None:
            raise AssertionError(
                f"the endpoint process exited with status {exited} before "
                f"{url} answered; log tail ({log_path}):\n{_log_tail(log_path)}"
            )
        last = _curl_status(runner, host, url)
        if last == "200":
            return
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"{url} never answered 200 from {host} within {timeout}s "
                f"(last status {last!r}); log tail ({log_path}):\n{_log_tail(log_path)}"
            )
        time.sleep(0.5)


def _log_tail(log_path: Path, lines: int = 20) -> str:
    """Return the last `lines` lines of a log, or a note saying why not.

    The endpoint's own log is the only account of why it refused to start, and
    it is gone with the namespace once teardown runs.
    """
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"<unreadable: {exc}>"
    tail = text.splitlines()[-lines:]
    return "\n".join(tail) if tail else "<empty>"


def get_until_success(
    runner,
    host_idx: int,
    uri: str,
    out: Path,
    log: Path,
    attempts: int = 5,
    interval: float = 2.0,
    timeout: float = 15.0,
):
    """Run cefgetfile until its Verdict says success, then return the Verdict.

    detect_get_success returns a Verdict, not a bool, and a Verdict is always
    truthy (verdict.py:64-84) — testing it for truthiness would make every
    first attempt look successful and the retry pointless, so `.success is
    True` is the only correct check.

    Retrying is not a workaround for flakiness: cefputfile has just finished on
    the publisher and the content needs a moment to be answerable, which the
    rest of the codebase handles with a blind ``time.sleep(5)``.
    """
    verdict = None
    for attempt in range(1, attempts + 1):
        # A partial file from a previous attempt would make the next Verdict's
        # "output non-empty" evidence a leftover rather than this run's.
        out.unlink(missing_ok=True)
        rc = run_cefgetfile(
            runner, host_idx, uri, str(out), log_name=str(log), timeout=timeout
        )
        verdict = detect_get_success(log, out, rc)
        if verdict.success is True:
            return verdict
        if attempt < attempts:
            time.sleep(interval)
    raise AssertionError(
        f"cefgetfile {uri} on h{host_idx} never succeeded in {attempts} attempts; "
        f"last verdict={verdict}"
    )


def assert_three_way_bytes(served: Path, output_file: Path, received: Path) -> None:
    """Assert the payload survived HTTP, the file system and ICN unchanged.

    This is the point of the whole test: the bytes the endpoint served, the
    bytes compute_call wrote, and the bytes the other host got back over ICN
    must be one and the same object.
    """
    served_bytes = served.read_bytes()
    output_bytes = output_file.read_bytes()
    received_bytes = received.read_bytes()
    assert output_bytes == served_bytes, (
        f"compute_call output {output_file} ({len(output_bytes)} bytes) differs from "
        f"served payload {served} ({len(served_bytes)} bytes)"
    )
    assert received_bytes == served_bytes, (
        f"cefgetfile output {received} ({len(received_bytes)} bytes) differs from "
        f"served payload {served} ({len(served_bytes)} bytes)"
    )
