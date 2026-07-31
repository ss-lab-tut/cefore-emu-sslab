"""Unit tests for ConnectScenario lifecycle (ceforeemu-connect)."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.runtime.daemon_fleet import DaemonFleet
from src.runtime.event_batch import EventBatchResult
from src.core.debug import DebugConfig
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


def test_debug_config_defaults_to_none(tmp_path):
    assert _make_scenario(tmp_path).debug_config is None


def test_debug_config_is_stored(tmp_path):
    debug_config = DebugConfig(node_dirs=True)

    scenario = ConnectScenario(
        _make_scenario(tmp_path).args,
        run_dir=tmp_path,
        debug_config=debug_config,
    )

    assert scenario.debug_config is debug_config


@pytest.mark.parametrize(
    ("run_dir", "expected"),
    [(Path("logs"), True), (Path("."), False), (None, False)],
)
def test_daemon_log_collection_enabled_uses_unresolved_run_dir(run_dir, expected):
    scenario = ConnectScenario(_make_scenario(Path(".")).args, run_dir=run_dir)

    assert scenario.daemon_log_collection_enabled is expected


def test_daemon_log_collection_scope_uses_generated_dirs_and_cache_nodes(tmp_path):
    scenario = _make_scenario(tmp_path)
    scenario.generated_node_dirs = [tmp_path / "h0", tmp_path / "h1"]
    scenario.cache_node_set = {1}

    scopes = scenario.daemon_log_collection_scope()

    assert [(s.idx, s.node_dir, s.has_csmgrd) for s in scopes] == [
        (0, tmp_path / "h0", False),
        (1, tmp_path / "h1", True),
    ]


def test_fib_debug_collection_uses_connect_host_count(tmp_path):
    scenario = _make_scenario(tmp_path)
    scenario.debug_config = DebugConfig(fib_dump=True, output_subdir="debug-out")
    net = MagicMock()

    with patch("src.runtime.debug.dump_fib") as dump_fib:
        scenario.collect_debug_pre_teardown(net)

    dump_fib.assert_called_once_with(
        net,
        [0, 1, 2],
        tmp_path / "debug-out" / "fib",
    )


def test_ignored_retrieval_warning_includes_ccninfo(tmp_path):
    """ConnectScenario does not execute ccninfo events (no CLI/thread runs
    content ops for it), so it must join get/pubsub_sub in the
    ignored-events warning rather than silently dropping the event."""
    event = {"at": 0, "type": "ccninfo", "host": 0, "uri": "ccnx:/x"}
    with patch("src.scenarios.connect.info") as mock_info:
        _make_scenario(tmp_path, events=[event])
    mock_info.assert_called_once()
    assert "ccninfo" in mock_info.call_args.args[0]


def test_run_experiment_without_events_is_noop(tmp_path):
    scenario = _make_scenario(tmp_path)
    with patch("src.scenarios.connect.run_event_batch") as run_batch:
        scenario.run_experiment(MagicMock())
    run_batch.assert_not_called()


def test_configure_passes_forwarding_config_to_setup(tmp_path):
    forwarding_config = {
        "default": "shortest_path",
        "nodes": [{"id": [1], "strategy": "flooding"}],
    }
    scenario = _make_scenario(
        tmp_path,
        hosts=3,
        k=2,
        topo_png=None,
        topo_layout="spring",
        cache_count=0,
        down_count=5,
        bw=[],
        ext=[],
        forwarding_config=forwarding_config,
    )
    scenario.topo = SimpleNamespace(mesh_links=[])

    with patch("src.scenarios.connect.setup_scenario") as setup:
        scenario.configure(MagicMock())

    spec = setup.call_args.args[1]
    assert spec.forwarding_config is forwarding_config


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
