"""Tests for path containment in CLI and scenario code."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from src.core.debug import DebugConfig
from src.runtime.monitoring import Monitor
from src.scenarios.base import BaseScenario


# ---------------------------------------------------------------------------
# A1. cmd_disaster script_log containment
# ---------------------------------------------------------------------------


def test_cmd_disaster_script_log_escape_rejected(tmp_path, monkeypatch):
    """cmd_disaster() must reject script_log paths that escape run_dir.

    Fail-before: current code does simple Path concatenation (run_dir / log_name),
    which does not validate containment. The escape_file is truncated by open("w").

    Pass-after: resolve_run_path() raises ValueError before open().
    """
    from src.cli.main import cmd_disaster

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    escape_file = tmp_path / "escape.log"
    escape_file.write_text("SENTINEL")

    # Write minimal config
    config_path = tmp_path / "config.yaml"
    config_path.write_text("hosts: 3\nswitches: 4\nseed: 42\n")

    args = SimpleNamespace(
        config=str(config_path),
        script_log="../escape.log",
        no_script_log=False,
        no_cli=True,
        results_json="",
        # Common args
        hosts=3,
        seed=42,
        topo_png=None,
        topo_layout="spring",
        num=None,
        output_dir=str(run_dir),
        timestamp=False,
        # Mesh args
        switches=4,
        node_per_switch=2,
        host_degree_min=1,
        host_degree_max=2,
        switch_use_all=False,
        k=2,
        # Disaster args
        down_interval=0,
        down_duration=0,
        down_count=0,
        down_stagger=0,
        down_exclude="",
        cache_count=0,
        bw=[],
        ext=[],
        bridge=[],
        duration=0,
        cache_default_rct_ms=None,
        publisher_host=None,
        pubsub_sub_startup_grace=1.0,
        warmup_get_interval=0,
        warmup_only_cache_nodes=True,
        webui_port=None,
        # Debug args
        debug=False,
        debug_artifact=[],
    )

    # Fix resolve_run_dir to return our run_dir
    monkeypatch.setattr(
        "src.cli.main.resolve_run_dir",
        lambda *a, **kw: run_dir,
    )

    # Mock scenario execution to avoid Mininet
    # run_disaster_scenario is imported inside cmd_disaster(), so patch at its module
    monkeypatch.setattr(
        "src.scenarios.disaster.run_disaster_scenario",
        lambda *a, **k: None,
    )

    try:
        cmd_disaster(args)
        # Before fix: no ValueError raised; escape_file truncated
        assert escape_file.read_text() == "SENTINEL", (
            "escape_file was modified — containment not enforced"
        )
        pytest.fail("Expected ValueError for path traversal")
    except ValueError as e:
        assert "escapes run directory" in str(e)
        assert escape_file.read_text() == "SENTINEL"


# ---------------------------------------------------------------------------
# A2. Monitor output path containment
# ---------------------------------------------------------------------------


def _make_net(host_count=3):
    """Return a fake Mininet-like object."""
    net = Mock()
    net.hosts = [Mock() for _ in range(host_count)]
    for h in net.hosts:
        h.cmd.return_value = "status output"
    return net


def test_monitor_output_json_escape_rejected(tmp_path):
    """Monitor must reject output_json paths that escape output_dir.

    Fail-before: current __init__ stores output_json without validation.
    Pass-after: __init__ raises ValueError.
    """
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    sentinel = tmp_path / "escape.json"
    sentinel.write_text("SENTINEL")

    with pytest.raises(ValueError, match="escapes run directory"):
        Monitor(
            net=_make_net(),
            targets=[],
            interval=5,
            output_dir=output_dir,
            output_json="../escape.json",
        )

    assert sentinel.read_text() == "SENTINEL"


def test_monitor_output_csv_escape_rejected(tmp_path):
    """Monitor must reject output_csv paths that escape output_dir."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    sentinel = tmp_path / "escape.csv"
    sentinel.write_text("SENTINEL")

    with pytest.raises(ValueError, match="escapes run directory"):
        Monitor(
            net=_make_net(),
            targets=[],
            interval=5,
            output_dir=output_dir,
            output_csv="../escape.csv",
        )

    assert sentinel.read_text() == "SENTINEL"


# ---------------------------------------------------------------------------
# A3. Debug artifact destination containment
# ---------------------------------------------------------------------------


def _make_disaster_args():
    """Return a SimpleNamespace with all required disaster args."""
    return SimpleNamespace(
        hosts=3,
        seed=42,
        results_json="",
        no_cli=False,
        bridges=None,
        bridge=None,
        events=[],
        ext=None,
        bw=None,
        topo_png=None,
        topo_layout="spring",
        cache_count=0,
        cache_config=None,
        down_interval=0,
        down_duration=0,
        down_count=0,
        down_stagger=0,
        down_exclude=None,
        pubsub_sub_startup_grace=1.0,
        failure_scenarios=None,
        warmup_gets=None,
        warmup_get_interval=0,
        warmup_only_cache_nodes=True,
        duration=0,
        addressing=None,
        routing=None,
        cefnetd_timeout=10,
        webui_port=None,
        node_per_switch=None,
        host_degree_min=None,
        host_degree_max=None,
        switch_use_all=None,
    )


def test_debug_fib_escape_rejected(tmp_path):
    """DisasterScenario.collect_debug_pre_teardown() must reject escape paths.

    Fail-before: current code does not validate output_subdir.
    Pass-after: ensure_within_run_dir raises ValueError before dump_fib().
    """
    from src.scenarios.disaster import DisasterScenario

    scenario = DisasterScenario(
        args=_make_disaster_args(),
        run_dir=tmp_path,
        debug_config=DebugConfig(fib_dump=True, output_subdir="../escape"),
    )
    net = Mock()
    net.hosts = [Mock() for _ in range(3)]

    # Mock dump_fib to catch the call — but ValueError should prevent it
    with patch("src.runtime.debug.dump_fib") as mock_dump:
        with pytest.raises(ValueError, match="escapes run directory"):
            scenario.collect_debug_pre_teardown(net)
        mock_dump.assert_not_called()


def test_debug_daemon_logs_escape_rejected(tmp_path):
    """DisasterScenario.collect_debug_post_teardown() must reject escape paths."""
    from src.scenarios.disaster import DisasterScenario

    scenario = DisasterScenario(
        args=_make_disaster_args(),
        run_dir=tmp_path,
        debug_config=DebugConfig(
            daemon_logs=True,
            node_dirs=False,
            output_subdir="../escape",
        ),
    )

    # super() returns early because node_dirs=False
    # Mock archive_daemon_logs to catch the call — but ValueError should prevent it
    with patch("src.runtime.debug.archive_daemon_logs") as mock_archive:
        with pytest.raises(ValueError, match="escapes run directory"):
            scenario.collect_debug_post_teardown()
        mock_archive.assert_not_called()


# ---------------------------------------------------------------------------
# A4. BaseScenario node_dirs containment
# ---------------------------------------------------------------------------


class _TestScenario(BaseScenario):
    """Minimal concrete scenario for testing BaseScenario methods."""

    def build_topology(self):
        pass

    def configure(self, net):
        pass

    def run_experiment(self, net):
        pass

    def teardown(self, net):
        pass


def test_base_node_dirs_escape_rejected(tmp_path):
    """BaseScenario.collect_debug_post_teardown() must reject escape paths.

    Fail-before: current code passes escaped path to archive_node_dirs().
    Pass-after: ensure_within_run_dir raises ValueError before archive_node_dirs().
    """
    scenario = _TestScenario()
    scenario.run_dir = tmp_path
    scenario.generated_node_dirs = [tmp_path / "h0"]
    (tmp_path / "h0").mkdir()
    scenario.debug_config = DebugConfig(
        node_dirs=True,
        output_subdir="../escape",
    )

    # Patch the import used inside the function
    with patch("src.runtime.debug.archive_node_dirs") as mock_archive:
        with pytest.raises(ValueError, match="escapes run directory"):
            scenario.collect_debug_post_teardown()
        mock_archive.assert_not_called()


def test_base_fib_debug_without_args_namespace_is_noop(tmp_path):
    """Scenarios without args.hosts opt out of host-count debug collectors."""
    scenario = _TestScenario()
    scenario.run_dir = tmp_path
    scenario.debug_config = DebugConfig(fib_dump=True)

    with patch("src.runtime.debug.dump_fib") as mock_dump:
        scenario.collect_debug_pre_teardown(Mock())

    mock_dump.assert_not_called()
