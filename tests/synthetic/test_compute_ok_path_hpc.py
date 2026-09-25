"""Ok-path product test for compute_call against a real external endpoint.

The hermetic sibling proves the compute_call wiring with the endpoint on a
second Mininet host, which never leaves the emulated network. This one proves
the piece that cannot: a Mininet host reaching a *real* machine through the
root-namespace bridge — the veth into the root namespace, the host route via
the bridge's .254 gateway, ip_forward, and the MASQUERADE that makes the reply
come back. Everything after the HTTP response (output_file, cefputfile,
cefgetfile, byte equality) is the same contract as the hermetic test.

The endpoint comes from ``CEFEMU_COMPUTE_ENDPOINT``; without it the module
skips. The endpoint is expected to be the same stand-in, started on the other
machine by hand:

    python3 tools/compute_echo_server.py --bind 0.0.0.0 --port 18080 \\
        --payload-file <some file>

This test never ssh-es anywhere: it neither starts nor stops that server, and
it does not know what the payload is. The byte baseline is therefore taken by
GETting the endpoint twice from the root namespace and requiring the two
bodies to be identical and non-empty.

**Cannot run concurrently with the cefore-run-tests smoke**, for the same two
reasons as the hermetic test: cefnetd's ``/tmp/cef_{port}.{idx}`` sockets and
logs are fixed paths shared by any run using the same hN indices, and
teardown's ``kill_cef_processes`` runs ``pkill -9 -f cefnetd`` inside hosts
that share the machine's PID namespace, killing every Cefore process on the
box (src/runtime/cleanup.py).

**Assumes this machine's LAN does not overlap 192.168.0.0/16.** The bridge
adds a root-namespace route for that range and masquerades it out the default
interface (bridge_root.py), so on a 192.168.x LAN this test would hijack the
machine's real routing. It is written for a 133.15.70.0/24 LAN.

Skipped unless CEFEMU_SYNTHETIC_ROOT=1 AND root AND CEFEMU_COMPUTE_ENDPOINT.
"""

from __future__ import annotations

import ipaddress
import os
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from src.runtime.command_runner import ROOT_SENTINEL
from src.runtime.scheduler import _handle_compute_call

from ._compute_ok_path import (
    MESH_LINKS,
    assert_three_way_bytes,
    get_until_success,
    mininet_info_logging,  # noqa: F401 - imported so pytest can resolve it
    ok_path_scenario,
)

SYNTHETIC_GATE = os.environ.get("CEFEMU_SYNTHETIC_ROOT") == "1"
ENDPOINT_ENV = "CEFEMU_COMPUTE_ENDPOINT"
ENDPOINT = os.environ.get(ENDPOINT_ENV, "")

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
    pytest.mark.skipif(
        not ENDPOINT,
        reason=f"{ENDPOINT_ENV} not set (e.g. http://<host>:18080/api/process)",
    ),
]

URI = "ccnx:/test/compute"


def _endpoint_host_network(url: str) -> str:
    """Return the endpoint host as a single-address network, e.g. "1.2.3.4/32".

    This is what ``vm_host_network`` wants: a route to exactly the endpoint is
    added inside each Mininet host, so the bridge never becomes their default
    route and the rest of their traffic is untouched.

    The endpoint must therefore be an IPv4 literal; a hostname is rejected
    rather than resolved. The hosts have no DNS of their own (giving them one
    would mean overwriting this machine's /etc/resolv.conf, which
    ``external_routes`` does and this test refuses to use), so a name that
    resolved differently for them than for this process would silently route
    to the wrong machine.
    """
    host = urllib.parse.urlsplit(url).hostname
    assert host, f"{ENDPOINT_ENV}={url!r} has no host part"
    try:
        address = ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError:
        pytest.fail(f"{ENDPOINT_ENV} must use an IPv4 literal host, got {host!r}")
    return f"{address}/32"


def _fetch_baseline(url: str) -> bytes:
    """GET the endpoint twice from the root namespace and return the body.

    The test cannot read the file the other machine is serving, so "the bytes
    that were served" have to be established over HTTP. Fetching twice and
    demanding equality rules out the one thing that would quietly wreck the
    comparison: an endpoint whose answer varies per request.
    """
    bodies = []
    for _ in range(2):
        with urllib.request.urlopen(url, timeout=10) as response:
            assert response.status == 200, f"{url} answered {response.status}"
            bodies.append(response.read())
    assert bodies[0], f"{url} served an empty body"
    assert bodies[0] == bodies[1], (
        f"{url} served {len(bodies[0])} bytes then {len(bodies[1])} bytes; "
        "a varying endpoint cannot be used as a byte baseline"
    )
    return bodies[0]


def _bridge_diagnostics(runner) -> str:
    """Collect the NAT/forwarding/routing state behind an unreachable endpoint.

    connect_to_root_ns and add_root_route still discard the return code of
    their net-tools commands (bridge_root.py), and add_host_route's 2026-09-25
    warning goes only to the info log — so the routing table, not the setup
    output, is the ground truth for what actually got installed. These five
    facts separate "no route in the host" from "no MASQUERADE" from
    "forwarding off", and they are gone the moment teardown runs, so they are
    gathered here while the network is still up.
    """
    probes = [
        (
            "root: iptables -t nat -S POSTROUTING",
            ROOT_SENTINEL,
            ["iptables", "-t", "nat", "-S", "POSTROUTING"],
        ),
        (
            "root: iptables -S FORWARD (policy + root-eth0 rules)",
            ROOT_SENTINEL,
            ["iptables", "-S", "FORWARD"],
        ),
        (
            "root: sysctl net.ipv4.ip_forward",
            ROOT_SENTINEL,
            ["sysctl", "net.ipv4.ip_forward"],
        ),
        ("root: ip route", ROOT_SENTINEL, ["ip", "route"]),
        ("h1: ip route", "h1", ["ip", "route"]),
    ]
    lines = []
    for label, node, argv in probes:
        try:
            out = runner.run(node, argv, timeout=10).stdout.strip()
        except BaseException as exc:  # noqa: BLE001 - diagnostics must not raise
            out = f"<failed: {exc!r}>"
        if label.endswith("(policy + root-eth0 rules)"):
            # The chain can be long and mostly irrelevant, but the policy alone
            # does not decide reachability: enable_nat installs an explicit
            # ACCEPT and a RELATED,ESTABLISHED return rule on root-eth0, and
            # their absence is exactly what a missing NAT looks like.
            kept = [
                line
                for line in out.splitlines()
                if line.startswith("-P ") or "root-eth0" in line
            ]
            out = "\n".join(kept) if kept else "<empty>"
        lines.append(f"--- {label} ---\n{out}")
    return "\n".join(lines)


# usefixtures rather than an argument: the fixture is imported into this
# module's namespace, and naming it as a parameter too would shadow the import.
@pytest.mark.usefixtures("mininet_info_logging")
def test_compute_call_ok_path_over_bridge_to_external_endpoint(monkeypatch, tmp_path):
    """compute_call ok against a real endpoint reached through the root bridge."""
    # Must precede provisioning: see ok_path_scenario's docstring.
    monkeypatch.chdir(tmp_path)

    served = tmp_path / "served" / "payload.bin"
    served.parent.mkdir()
    served.write_bytes(_fetch_baseline(ENDPOINT))

    bridge_configs = [
        {
            "switch": 0,
            # "auto" resolves to the .254 gateway of this switch's subnet.
            "root_ip": "auto",
            "local_routes": "192.168.0.0/16",
            "vm_host_network": _endpoint_host_network(ENDPOINT),
            # Opt-in (bridge_root.py: use_nat = config.get("nat", False)).
            # Without it there is no ip_forward, no MASQUERADE and no FORWARD
            # ACCEPT, so the reply from the endpoint can never come back and
            # the whole point of this test is unprovable.
            "nat": True,
            # Deliberately no "external_routes": it would rewrite this
            # machine's real /etc/resolv.conf with no way back, because the
            # Mininet hosts share its mount namespace.
        }
    ]

    with ok_path_scenario(tmp_path, URI, bridge_configs=bridge_configs) as harness:
        # No readiness probe before this call. The handler's own curl is the
        # connectivity test, and routing it through the handler is what makes a
        # broken bridge report itself as the tri-state the product would record
        # (skipped-no-result / no-external-connectivity) rather than as a test
        # helper's complaint.
        outcome = _handle_compute_call(
            harness.net,
            {
                "host": 1,
                "endpoint": ENDPOINT,
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
        # Assertion order matters: a missing NAT surfaces here, as
        # skipped-no-result from an unreachable endpoint, long before the byte
        # comparison would have anything to say. The bridge state is attached
        # because it is unrecoverable once teardown has run.
        assert outcome.success is True, (
            f"compute_call failed: {outcome}\n{_bridge_diagnostics(harness.runner)}"
        )
        assert outcome.outcome == "ok"
        assert outcome.detail["http_status"] == 200
        assert outcome.detail["publish_ok"] is True
        assert outcome.detail["output_file"] == str(tmp_path / "compute_result.bin")

        received = tmp_path / "recv.bin"
        get_until_success(harness.runner, 0, URI, received, tmp_path / "get.log")
        assert_three_way_bytes(served, Path(outcome.detail["output_file"]), received)
