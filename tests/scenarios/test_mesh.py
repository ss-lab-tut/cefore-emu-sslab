"""Unit tests for MeshScenario lifecycle."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.runtime.daemon_fleet import DaemonFleet
from src.scenarios.mesh import MeshScenario


def _make_scenario(tmp_path):
    scenario = MeshScenario(
        host_num=3,
        swhich_num=2,
        seed=1,
        k_paths=1,
        run_dir=tmp_path,
    )
    scenario.roles = {1: SimpleNamespace(runs_csmgrd=True)}
    return scenario


def _seed_fleet(scenario, net):
    """Give the scenario a DaemonFleet that has started csmgrd on h1."""
    fleet = DaemonFleet(net, node_names=["h0", "h1", "h2"], csmgrd_nodes={"h1"})
    fleet.started_csmgrd = {"h1"}
    scenario.daemon_fleet = fleet


def test_teardown_success_runs_all_stages(tmp_path):
    scenario = _make_scenario(tmp_path)
    net = MagicMock()
    _seed_fleet(scenario, net)

    with patch("src.runtime.daemon_fleet.stop_cefnetd") as stop_cefnetd:
        with patch("src.runtime.daemon_fleet.stop_csmgrd") as stop_csmgrd:
            scenario.teardown(net)

    assert stop_cefnetd.call_count == 3
    stop_csmgrd.assert_called_once()


def test_teardown_daemon_stop_failure_raises(tmp_path):
    scenario = _make_scenario(tmp_path)
    net = MagicMock()
    _seed_fleet(scenario, net)

    with patch(
        "src.runtime.daemon_fleet.stop_cefnetd",
        side_effect=RuntimeError("cefnetd stop failed"),
    ):
        with patch("src.runtime.daemon_fleet.stop_csmgrd"):
            with pytest.raises(BaseException):
                scenario.teardown(net)
