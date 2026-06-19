"""Unit tests for event-only disaster operation metadata."""

from argparse import Namespace
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

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


def test_random_cache_strategy_assigns_cs_modes_without_cache_placement(tmp_path):
    scenario = DisasterScenario(
        _make_args(
            cache_config={"strategy": "random"},
            cache_count=0,
            down_count=0,
        ),
        run_dir=tmp_path,
    )
    scenario.publisher_ids = {2}
    with (
        patch(
            "src.scenarios.disaster.assign_random_cs_modes",
            return_value={0: 0, 1: 2, 2: 1},
        ) as assign_modes,
        patch("src.scenarios.disaster.apply_cs_modes") as apply_modes,
        patch("src.scenarios.disaster.CachePlacement") as cache_placement,
    ):
        scenario._configure_cache_nodes()

    assert scenario.cache_node_set == {1}
    assert assign_modes.call_args.args[:2] == (range(3), {2})
    apply_modes.assert_called_once_with({0: 0, 1: 2, 2: 1})
    cache_placement.assert_not_called()


def test_non_random_cache_strategy_uses_cache_placement(tmp_path):
    scenario = DisasterScenario(
        _make_args(
            cache_config={"strategy": "manual", "nodes": [{"id": 1}]},
            cache_count=0,
            down_count=0,
        ),
        run_dir=tmp_path,
    )
    scenario.topo = SimpleNamespace(mesh_links=[])
    with (
        patch("src.scenarios.disaster.build_host_graph", return_value=({}, None)),
        patch("src.scenarios.disaster.CachePlacement") as cache_placement,
        patch("src.scenarios.disaster.apply_cs_modes") as apply_modes,
    ):
        cache_placement.return_value.place.return_value = {1}
        scenario._configure_cache_nodes()

    assert scenario.cache_node_set == {1}
    assert cache_placement.call_args.kwargs["cache_config"]["strategy"] == "manual"
    apply_modes.assert_not_called()


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
        _make_args(no_cli=True, results_json="results.json", duration=0, events=[event]),
        run_dir=tmp_path,
    )
    scenario.topo = SimpleNamespace(mesh_links=[])
    runner = MagicMock()
    runner.wait_all.return_value = True
    scheduler = MagicMock()
    scheduler.wait_all.return_value = True
    with (
        patch.object(scenario, "_make_content_runner", return_value=runner),
        patch.object(scenario, "_run_warmup", return_value=True),
        patch.object(scenario, "_start_failure_manager") as start_failure,
        patch("src.scenarios.disaster.EventScheduler", return_value=scheduler),
    ):
        scenario._run_autotest_experiment(MagicMock(), [event], time.monotonic(), False)
    scheduler.stop.assert_called_once()
    runner.stop.assert_called_once()
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
        _make_args(no_cli=True, results_json="results.json", duration=1, events=[event]),
        run_dir=tmp_path,
    )
    with pytest.raises(ValueError, match="repeat"):
        scenario._run_autotest_experiment(MagicMock(), [event], time.monotonic(), False)


@patch("src.scenarios.disaster.info")
def test_empty_events_warn_in_interactive_execution(mock_info, tmp_path):
    scenario = DisasterScenario(_make_args(no_cli=False), run_dir=tmp_path)
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
