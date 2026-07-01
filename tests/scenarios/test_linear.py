"""Behavior tests for the linear scenario FIB programming."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.runtime.command_runner import CommandResult, FakeCommandRunner
from src.runtime.daemon_fleet import DaemonFleet
from src.scenarios.linear import LinearScenario


class TestSetIpAddr:
    def test_assigns_each_interface_with_explicit_slash24_netmask(self):
        """Every ifconfig must carry netmask 255.255.255.0.

        Without it ifconfig applies the classful default (/8 for 10.x), which
        collapses interfaces onto one flat network and breaks routing.
        """
        scenario = LinearScenario(3)
        fake = FakeCommandRunner()
        scenario._set_ip_addr(None, runner=fake)
        s = scenario.scheme
        assert [run["node"] for run in fake.runs] == ["h0", "h1", "h1", "h2"]
        assert [run["argv"] for run in fake.runs] == [
            ["ifconfig", "h0-eth0", str(s.host_ip(0, 0)), "netmask", "255.255.255.0"],
            ["ifconfig", "h1-eth0", str(s.host_ip(0, 1)), "netmask", "255.255.255.0"],
            ["ifconfig", "h1-eth1", str(s.host_ip(1, 1)), "netmask", "255.255.255.0"],
            ["ifconfig", "h2-eth0", str(s.host_ip(1, 2)), "netmask", "255.255.255.0"],
        ]


class TestSetFib:
    def test_routes_every_non_publisher_toward_the_publisher(self):
        scenario = LinearScenario(3)
        fake = FakeCommandRunner()
        scenario._set_fib(None, runner=fake)
        assert [run["node"] for run in fake.runs] == ["h0", "h1"]
        for idx, run in enumerate(fake.runs):
            assert run["argv"] == [
                "cefroute", "add", "ccnx:/test", "udp",
                str(scenario.scheme.host_ip(idx, idx + 1)),
                "-d", f"./h{idx}",
            ]

    def test_failed_add_does_not_abort_remaining_hosts(self):
        scenario = LinearScenario(3)
        fake = FakeCommandRunner()
        fake.on_run = lambda node, argv: (
            CommandResult(returncode=1) if node == "h0" else None
        )
        scenario._set_fib(None, runner=fake)
        assert [run["node"] for run in fake.runs] == ["h0", "h1"]


# -- teardown ---------------------------------------------------------------

def _seed_fleet(scenario, net):
    """Give the scenario a DaemonFleet that has started csmgrd on h1."""
    scenario.roles = {1: SimpleNamespace(runs_csmgrd=True)}
    fleet = DaemonFleet(net, node_names=["h0", "h1", "h2"], csmgrd_nodes={"h1"})
    fleet.started_csmgrd = {"h1"}
    scenario.daemon_fleet = fleet


def test_teardown_success_runs_all_stages(tmp_path):
    scenario = LinearScenario(3, run_dir=tmp_path)
    net = MagicMock()
    _seed_fleet(scenario, net)

    with patch("src.runtime.daemon_fleet.stop_cefnetd") as stop_cefnetd:
        with patch("src.runtime.daemon_fleet.stop_csmgrd") as stop_csmgrd:
            scenario.teardown(net)

    assert stop_cefnetd.call_count == 3
    stop_csmgrd.assert_called_once()


def test_teardown_daemon_stop_failure_raises(tmp_path):
    scenario = LinearScenario(3, run_dir=tmp_path)
    net = MagicMock()
    _seed_fleet(scenario, net)

    with patch(
        "src.runtime.daemon_fleet.stop_cefnetd",
        side_effect=RuntimeError("cefnetd stop failed"),
    ):
        with patch("src.runtime.daemon_fleet.stop_csmgrd"):
            with pytest.raises(BaseException):
                scenario.teardown(net)
