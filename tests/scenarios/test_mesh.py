"""Unit tests for MeshScenario lifecycle."""

from pathlib import Path
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


@pytest.mark.parametrize(
    ("run_dir", "expected"),
    [(Path("out/exp1"), True), (None, False), (Path("."), False)],
)
def test_daemon_log_collection_enabled_uses_unresolved_run_dir(run_dir, expected):
    scenario = MeshScenario(
        host_num=3,
        swhich_num=2,
        seed=1,
        k_paths=1,
        run_dir=run_dir,
    )

    assert scenario.daemon_log_collection_enabled is expected


def test_daemon_log_collection_scope_uses_generated_dirs_and_roles(tmp_path):
    scenario = _make_scenario(tmp_path)
    scenario.generated_node_dirs = [tmp_path / "h0", tmp_path / "h1"]
    scenario.roles = {1: SimpleNamespace(runs_csmgrd=True)}

    scopes = scenario.daemon_log_collection_scope()

    assert [(s.idx, s.node_dir, s.has_csmgrd) for s in scopes] == [
        (0, tmp_path / "h0", False),
        (1, tmp_path / "h1", True),
    ]


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
