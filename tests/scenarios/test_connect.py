"""Unit tests for ConnectScenario lifecycle (ceforeemu-connect)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

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
    with patch("src.scenarios.connect.ContentOperationRunner") as runner_cls:
        scenario.run_experiment(MagicMock())
    runner_cls.assert_not_called()


def test_teardown_success_runs_all_stages(tmp_path):
    scenario = _make_scenario(tmp_path)
    scenario.cache_node_set = {1}
    scenario.bridge_manager.cleanup = MagicMock()
    net = MagicMock()

    with patch("src.scenarios.connect.stop_cefnetd") as stop_cefnetd:
        with patch("src.scenarios.connect.stop_csmgrd") as stop_csmgrd:
            scenario.teardown(net)

    assert stop_cefnetd.call_count == 3
    stop_csmgrd.assert_called_once()
    scenario.bridge_manager.cleanup.assert_called_once()


def test_teardown_daemon_stop_failure_still_runs_bridge_cleanup(tmp_path):
    """A stop_cefnetd failure must not skip bridge_manager.cleanup(), and the
    failure must surface as an aggregated exception."""
    scenario = _make_scenario(tmp_path)
    scenario.cache_node_set = {1}
    scenario.bridge_manager.cleanup = MagicMock()
    net = MagicMock()

    with patch(
        "src.scenarios.connect.stop_cefnetd",
        side_effect=RuntimeError("cefnetd stop failed"),
    ):
        with patch("src.scenarios.connect.stop_csmgrd"):
            with pytest.raises(BaseException):
                scenario.teardown(net)

    scenario.bridge_manager.cleanup.assert_called_once()
