"""Behavior tests for FIB route application (net_config)."""

from src.core.fib import Route
from src.runtime.command_runner import CommandResult, FakeCommandRunner
from src.runtime.net_config import apply_fib, apply_fib_routes

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
