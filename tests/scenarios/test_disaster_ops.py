"""Unit tests for event-only disaster operation metadata."""

from argparse import Namespace
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.runtime.event_batch import EventBatchResult
from src.scenarios.disaster import DisasterScenario


def _make_args(**overrides):
    data = {
        "hosts": 3,
        "seed": 42,
        "events": [],
        "bridges": [],
        "bridge": [],
        "ext": [],
        "no_cli": False,
        "results_json": "",
        "addressing": {},
    }
    data.update(overrides)
    return Namespace(**data)


def test_no_events_yields_no_publishers(tmp_path):
    scenario = DisasterScenario(_make_args(), run_dir=tmp_path)
    assert scenario.publisher_ids == set()
    assert scenario.uri_publishers == {}


@pytest.mark.parametrize(
    ("run_dir", "expected"),
    [(Path("logs"), True), (Path("."), False), (None, False)],
)
def test_daemon_log_collection_enabled_uses_unresolved_run_dir(run_dir, expected):
    scenario = DisasterScenario(_make_args(), run_dir=run_dir)

    assert scenario.daemon_log_collection_enabled is expected


def test_daemon_log_collection_scope_uses_generated_dirs_and_cache_nodes(tmp_path):
    scenario = DisasterScenario(_make_args(hosts=3), run_dir=tmp_path)
    scenario.generated_node_dirs = [tmp_path / "h0", tmp_path / "h1"]
    scenario.cache_node_set = {1}

    scopes = scenario.daemon_log_collection_scope()

    assert [(s.idx, s.node_dir, s.has_csmgrd) for s in scopes] == [
        (0, tmp_path / "h0", False),
        (1, tmp_path / "h1", True),
    ]


def test_event_publishers_drive_uri_metadata(tmp_path):
    events = [
        {
            "at": 1,
            "type": "put",
            "host": 2,
            "uri": "ccnx:/test/sample",
            "file": "./sample-putfile",
        },
        {
            "at": 2,
            "type": "pubsub_pub",
            "host": 1,
            "uri": "ccnx:/test/live",
            "file": "./sample-putfile",
        },
    ]
    scenario = DisasterScenario(_make_args(events=events), run_dir=tmp_path)
    assert scenario.publisher_ids == {1, 2}
    assert scenario.uri_publishers == {
        "ccnx:/test/sample": 2,
        "ccnx:/test/live": 1,
    }


def test_legacy_content_keys_do_not_drive_publishers(tmp_path):
    scenario = DisasterScenario(
        _make_args(
            puts=[{"host": 2, "uri": "ccnx:/test/ignored"}],
            gets=[{"host": 0, "uri": "ccnx:/test/ignored"}],
            auto={"publishers": [2], "uri_prefix": "ccnx:/test"},
        ),
        run_dir=tmp_path,
    )
    assert scenario.publisher_ids == set()
    assert scenario.uri_publishers == {}


def test_random_cache_config_yields_random_cs_mode_strategy(tmp_path):
    from src.runtime.cache_strategy import RandomCSModeStrategy

    scenario = DisasterScenario(
        _make_args(
            cache_config={"strategy": "random"},
            seed=42,
            cache_count=0,
            down_count=0,
        ),
        run_dir=tmp_path,
    )
    strategy = scenario._build_cache_strategy()
    assert isinstance(strategy, RandomCSModeStrategy)
    assert strategy.seed == 42


def test_non_random_cache_config_yields_kcenters_strategy(tmp_path):
    from src.runtime.cache_strategy import KCentersStrategy

    cfg = {"strategy": "manual", "nodes": [{"id": 1}]}
    scenario = DisasterScenario(
        _make_args(
            cache_config=cfg,
            cache_count=2,
            down_count=1,
            cache_default_rct_ms=750,
        ),
        run_dir=tmp_path,
    )
    strategy = scenario._build_cache_strategy()
    assert isinstance(strategy, KCentersStrategy)
    # disaster excludes publishers from cache eligibility.
    assert strategy.exclude_publishers is True
    assert strategy.cache_config is cfg
    assert strategy.cache_count == 2
    assert strategy.down_count == 1
    assert strategy.cache_default_rct_ms == 750


def test_missing_cache_config_defaults_to_kcenters_strategy(tmp_path):
    from src.runtime.cache_strategy import KCentersStrategy

    scenario = DisasterScenario(
        _make_args(cache_config=None, cache_count=0, down_count=0),
        run_dir=tmp_path,
    )
    strategy = scenario._build_cache_strategy()
    assert isinstance(strategy, KCentersStrategy)
    assert strategy.cache_config is None


def test_configure_passes_forwarding_config_to_setup(tmp_path):
    forwarding_config = {
        "default": "shortest_path",
        "nodes": [{"id": [1], "strategy": "flooding"}],
    }
    scenario = DisasterScenario(
        _make_args(
            hosts=3,
            k=2,
            topo_png=None,
            topo_layout="spring",
            cache_config=None,
            cache_count=0,
            down_count=5,
            bw=[],
            ext=[],
            cefnetd_timeout=10,
            forwarding_config=forwarding_config,
        ),
        run_dir=tmp_path,
    )
    scenario.topo = SimpleNamespace(mesh_links=[])

    with patch("src.scenarios.disaster.setup_scenario") as setup:
        scenario.configure(MagicMock())

    spec = setup.call_args.args[1]
    assert spec.forwarding_config is forwarding_config


@patch("src.scenarios.disaster.periodic_host_flap")
def test_default_down_values_skip_legacy_failure_manager(mock_flap, tmp_path):
    scenario = DisasterScenario(
        _make_args(
            down_interval=0,
            down_duration=0,
            down_count=5,
            down_stagger=2,
            down_exclude="",
            failure_scenarios=None,
        ),
        run_dir=tmp_path,
    )

    scenario._start_failure_manager(MagicMock(), use_cli=True)

    mock_flap.assert_not_called()
    assert scenario.stop_event is None
    assert scenario.stop_thread is None


@patch("src.scenarios.disaster.info")
def test_event_diagnostics_warn_for_unobserved_publications(mock_info, tmp_path):
    scenario = DisasterScenario(_make_args(), run_dir=tmp_path)
    scenario._warn_event_diagnostics(
        [
            {"type": "put", "uri": "ccnx:/test/unread"},
            {"type": "pubsub_pub", "uri": "ccnx:/test/orphan"},
        ]
    )
    messages = "".join(call.args[0] for call in mock_info.call_args_list)
    assert "no matching get" in messages
    assert "no matching pubsub_sub" in messages


def test_autotest_put_only_duration_zero_skips_failure_phase(tmp_path):
    event = {
        "at": 0,
        "type": "put",
        "host": 2,
        "uri": "ccnx:/test/sample",
        "file": "./sample-putfile",
    }
    scenario = DisasterScenario(
        _make_args(
            no_cli=True, results_json="results.json", duration=0, events=[event]
        ),
        run_dir=tmp_path,
    )
    scenario.topo = SimpleNamespace(mesh_links=[])
    net = MagicMock()
    with (
        patch.object(scenario, "_run_warmup", return_value=True),
        patch.object(scenario, "_start_failure_manager") as start_failure,
        patch(
            "src.scenarios.disaster.run_event_batch",
            return_value=EventBatchResult(None, None, True, []),
        ) as run_batch,
    ):
        scenario._run_autotest_experiment(net, [event], time.monotonic(), False)
    run_batch.assert_called_once()
    assert run_batch.call_args.args[0] is net
    spec = run_batch.call_args.args[1]
    assert spec.events == [event]
    assert spec.run_dir == tmp_path
    assert spec.mesh_links == scenario.topo.mesh_links
    assert spec.sink is scenario.results_sink
    assert spec.flap_state is scenario.flap_state
    assert spec.uri_publishers == {"ccnx:/test/sample": 2}
    assert spec.startup_grace == 1.0
    assert spec.phase == "event"
    assert spec.wait_timeout == 300
    assert spec.deadline_policy == "raise"
    assert spec.scheduler_label == "seed event scheduling"
    assert spec.runner_label == "seed content operations"
    start_failure.assert_not_called()


def test_autotest_rejects_repeated_put(tmp_path):
    event = {
        "at": 0,
        "type": "put",
        "host": 2,
        "uri": "ccnx:/test/sample",
        "file": "./sample-putfile",
        "repeat": {"interval": 1},
    }
    scenario = DisasterScenario(
        _make_args(
            no_cli=True, results_json="results.json", duration=1, events=[event]
        ),
        run_dir=tmp_path,
    )
    with pytest.raises(ValueError, match="repeat"):
        scenario._run_autotest_experiment(MagicMock(), [event], time.monotonic(), False)


@patch("src.scenarios.disaster.info")
def test_empty_events_warn_in_interactive_execution(mock_info, tmp_path):
    scenario = DisasterScenario(_make_args(no_cli=False), run_dir=tmp_path)
    scenario.topo = SimpleNamespace(mesh_links=[])
    with (
        patch.object(scenario, "_start_failure_manager"),
        patch.object(scenario, "_start_monitoring"),
    ):
        scenario.run_experiment(MagicMock())
    messages = "".join(call.args[0] for call in mock_info.call_args_list)
    assert "no events configured" in messages


# ---------------------------------------------------------------------------
# Monitor background wiring (interactive CLI keeps monitoring, no terminal output)
# ---------------------------------------------------------------------------

_MONITORING = {"interval": 5, "targets": [{"type": "cefstatus", "hosts": "all"}]}


def test_start_monitoring_background_true_in_interactive(tmp_path):
    scenario = DisasterScenario(
        _make_args(no_cli=False, monitoring=_MONITORING), run_dir=tmp_path
    )
    with patch("src.scenarios.disaster.Monitor") as MockMonitor:
        scenario._start_monitoring(MagicMock())
    assert MockMonitor.call_args.kwargs["background"] is True
    MockMonitor.return_value.start.assert_called_once()


def test_start_monitoring_background_false_in_autotest(tmp_path):
    scenario = DisasterScenario(
        _make_args(no_cli=True, monitoring=_MONITORING), run_dir=tmp_path
    )
    with patch("src.scenarios.disaster.Monitor") as MockMonitor:
        scenario._start_monitoring(MagicMock())
    assert MockMonitor.call_args.kwargs["background"] is False


def test_execute_interactive_enters_background_then_stops_after_cli(tmp_path):
    scenario = DisasterScenario(_make_args(no_cli=False), run_dir=tmp_path)
    mock_monitor = MagicMock()
    order = []
    mock_monitor.enter_background.side_effect = lambda: order.append("enter_background")
    mock_monitor.stop.side_effect = lambda: order.append("monitor.stop")

    def _set_monitor(net):
        scenario.monitor = mock_monitor

    with (
        patch.object(scenario, "build_topology"),
        patch.object(scenario, "create_mininet", return_value=MagicMock()),
        patch.object(scenario, "configure"),
        patch.object(scenario, "run_experiment", side_effect=_set_monitor),
        patch("src.scenarios.base.CLI", side_effect=lambda net: order.append("CLI")),
        patch.object(scenario, "collect_debug_pre_teardown"),
        patch.object(scenario, "teardown"),
        patch.object(scenario, "collect_debug_post_teardown"),
        patch("src.scenarios.base.cleanup_all"),
    ):
        scenario.execute()

    assert order == ["enter_background", "CLI", "monitor.stop"]
    mock_monitor.enter_background.assert_called_once()
    mock_monitor.stop.assert_called_once()
