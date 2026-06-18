"""Behavior tests for FIB route application (net_config)."""

import pytest

from src.core.addressing import AddressingScheme
from src.core.fib import Route
from src.runtime.command_runner import CommandResult, FakeCommandRunner
from src.runtime.net_config import (
    apply_fib,
    apply_fib_routes,
    apply_ip_addr,
    cefroute_add,
    cefroute_del,
    cefroute_enable,
)

# Two switches: s0 joins h0-h1, s1 joins h1-h2 (MeshTopo canonical shape).
MESH = [
    {"subnet": 1, "switch": "s0", "hosts": [0, 1], "host_eth": {0: 0, 1: 0}},
    {"subnet": 2, "switch": "s1", "hosts": [1, 2], "host_eth": {1: 1, 2: 0}},
]


def _routes():
    return [
        Route(source=0, prefix="ccnx:/test/a", next_hop=1, next_hop_ip="192.168.1.2"),
        Route(source=1, prefix="ccnx:/test/a", next_hop=2, next_hop_ip="192.168.2.3"),
    ]


class TestApplyIpAddr:
    """Interface addressing must carry an explicit /24 netmask.

    Note: this asserts the argv apply_ip_addr constructs, not the netmask the
    kernel ends up applying. The classful-default fallback is a net-tools
    ``ifconfig`` behavior that only manifests in a real netns; proving the
    kernel assigns /24 needs the Class-A end-to-end smoke run.
    """

    @pytest.mark.parametrize(
        "cidr", ["192.168.0.0/16", "10.0.0.0/16", "100.64.0.0/16", "172.20.0.0/16"]
    )
    def test_every_interface_gets_explicit_slash24_netmask(self, cidr):
        fake = FakeCommandRunner()
        apply_ip_addr(None, MESH, scheme=AddressingScheme(cidr), runner=fake)
        assert len(fake.runs) == 4
        for run in fake.runs:
            argv = run["argv"]
            assert argv[0] == "ifconfig"
            # Without this the kernel would apply a classful default (/8 for
            # 10.x, /16 for 172.x) and break per-link routing.
            assert argv[-2:] == ["netmask", "255.255.255.0"]

    def test_class_a_scheme_assigns_expected_addresses(self):
        fake = FakeCommandRunner()
        apply_ip_addr(None, MESH, scheme=AddressingScheme("10.0.0.0/16"), runner=fake)
        seen = {(run["node"], tuple(run["argv"])) for run in fake.runs}
        assert (
            "h0",
            ("ifconfig", "h0-eth0", "10.0.1.1", "netmask", "255.255.255.0"),
        ) in seen
        assert (
            "h2",
            ("ifconfig", "h2-eth0", "10.0.2.3", "netmask", "255.255.255.0"),
        ) in seen


class TestCefrouteAdd:
    def test_runs_cefroute_add_on_the_host_and_returns_the_result(self):
        fake = FakeCommandRunner()
        result = cefroute_add(
            None, 3, "ccnx:/test/a", "udp", "192.168.1.2", runner=fake
        )
        assert result.returncode == 0
        assert len(fake.runs) == 1
        run = fake.runs[0]
        assert run["node"] == "h3"
        assert run["argv"] == [
            "cefroute", "add", "ccnx:/test/a", "udp", "192.168.1.2",
            "-d", "./h3",
        ]

class TestCefrouteDelEnable:
    def test_del_runs_through_an_injected_runner(self):
        fake = FakeCommandRunner()
        ok = cefroute_del(None, 2, "ccnx:/test/a", None, "192.168.1.2", runner=fake)
        assert ok is True
        run = fake.runs[0]
        assert run["node"] == "h2"
        assert run["argv"][:3] == ["cefroute", "del", "ccnx:/test/a"]

    def test_enable_runs_through_an_injected_runner(self):
        fake = FakeCommandRunner()
        fake.script_run(returncode=1)
        ok = cefroute_enable(None, 2, "ccnx:/test/a", None, "192.168.1.2", runner=fake)
        assert ok is False
        assert fake.runs[0]["argv"][:2] == ["cefroute", "enable"]


class TestApplyFibRoutes:
    def test_successful_application_reports_no_failures(self):
        fake = FakeCommandRunner()
        failures = apply_fib_routes(None, _routes(), runner=fake)
        assert failures == []
        assert [run["node"] for run in fake.runs] == ["h0", "h1"]
        assert fake.runs[0]["argv"][:3] == ["cefroute", "add", "ccnx:/test/a"]

    def test_source_filter_applies_only_that_hosts_routes(self):
        fake = FakeCommandRunner()
        failures = apply_fib_routes(None, _routes(), source=1, runner=fake)
        assert failures == []
        assert [run["node"] for run in fake.runs] == ["h1"]

    def test_failed_add_is_reported_with_route_identity(self):
        fake = FakeCommandRunner()
        fake.on_run = lambda node, argv: (
            CommandResult(returncode=1) if node == "h1" else None
        )
        failures = apply_fib_routes(None, _routes(), runner=fake)
        assert len(failures) == 1
        failure = failures[0]
        assert failure.source == 1
        assert failure.prefix == "ccnx:/test/a"
        assert failure.next_hop_ip == "192.168.2.3"
        assert failure.returncode == 1


    def test_none_returncode_counts_as_failure(self):
        """A killed/cancelled cefroute add (returncode None) is not a success."""
        fake = FakeCommandRunner()
        fake.script_run(returncode=None)
        failures = apply_fib_routes(None, _routes()[:1], runner=fake)
        assert len(failures) == 1
        assert failures[0].returncode is None


class TestApplyFib:
    def test_computes_routes_and_applies_them_through_the_runner(self):
        fake = FakeCommandRunner()
        routes = apply_fib(None, MESH, k_paths=1, runner=fake)
        assert routes
        assert len(fake.runs) == len(routes)
        assert all(run["argv"][0] == "cefroute" for run in fake.runs)
