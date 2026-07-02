"""Unit tests for ConnectScenario lifecycle (ceforeemu-connect)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.runtime.daemon_fleet import DaemonFleet
from src.runtime.event_batch import EventBatchResult
from src.scenarios.connect import ConnectScenario


def _make_scenario(tmp_path, **overrides):
    args = SimpleNamespace(
        hosts=3,
        seed=42,
        addressing={},
        events=[],
        bridges=None,
        bridge=None,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return ConnectScenario(args, run_dir=tmp_path)


def test_should_run_cli_reflects_no_cli(tmp_path):
    assert _make_scenario(tmp_path).should_run_cli() is True
    assert _make_scenario(tmp_path, no_cli=True).should_run_cli() is False


def test_run_experiment_without_events_is_noop(tmp_path):
    scenario = _make_scenario(tmp_path)
    with patch("src.scenarios.connect.run_event_batch") as run_batch:
        scenario.run_experiment(MagicMock())
    run_batch.assert_not_called()


def test_run_experiment_delegates_publications_to_event_batch(tmp_path):
    event = {
        "at": 0,
        "type": "put",
        "host": 1,
        "uri": "ccnx:/test/seed",
        "file": "./sample-putfile",
    }
    scenario = _make_scenario(tmp_path, events=[event])
    scenario.topo = SimpleNamespace(mesh_links=[{"switch": 0, "hosts": [0, 1]}])
    net = MagicMock()

    with patch(
        "src.scenarios.connect.run_event_batch",
        return_value=EventBatchResult(None, None, True, []),
    ) as run_batch:
        scenario.run_experiment(net)

    run_batch.assert_called_once()
    assert run_batch.call_args.args[0] is net
    spec = run_batch.call_args.args[1]
    assert spec.events == [event]
    assert spec.run_dir == tmp_path
    assert spec.mesh_links == scenario.topo.mesh_links
    assert spec.uri_publishers == {"ccnx:/test/seed": 1}
    assert spec.phase == "seed"
    assert spec.start_time is None
    assert spec.wait_timeout == 60
    assert spec.deadline_policy == "warn"
    assert spec.scheduler_label == "publication event scheduling"
    assert spec.runner_label == "publication seed operations"


def _seed_fleet(scenario, net):
    """Give the scenario a DaemonFleet that has started csmgrd on h1."""
    fleet = DaemonFleet(net, node_names=["h0", "h1", "h2"], csmgrd_nodes={"h1"})
    fleet.started_csmgrd = {"h1"}
    scenario.daemon_fleet = fleet


def test_teardown_success_runs_all_stages(tmp_path):
    scenario = _make_scenario(tmp_path)
    scenario.bridge_manager.cleanup = MagicMock()
    net = MagicMock()
    _seed_fleet(scenario, net)

    with patch("src.runtime.daemon_fleet.stop_cefnetd") as stop_cefnetd:
        with patch("src.runtime.daemon_fleet.stop_csmgrd") as stop_csmgrd:
            scenario.teardown(net)

    assert stop_cefnetd.call_count == 3
    stop_csmgrd.assert_called_once()
    scenario.bridge_manager.cleanup.assert_called_once()


def test_teardown_daemon_stop_failure_still_runs_bridge_cleanup(tmp_path):
    """A stop_cefnetd failure must not skip bridge_manager.cleanup(), and the
    failure must surface as an aggregated exception."""
    scenario = _make_scenario(tmp_path)
    scenario.bridge_manager.cleanup = MagicMock()
    net = MagicMock()
    _seed_fleet(scenario, net)

    with patch(
        "src.runtime.daemon_fleet.stop_cefnetd",
        side_effect=RuntimeError("cefnetd stop failed"),
    ):
        with patch("src.runtime.daemon_fleet.stop_csmgrd"):
            with pytest.raises(BaseException):
                scenario.teardown(net)

    scenario.bridge_manager.cleanup.assert_called_once()
