"""Unit tests for ConfigDrivenMeshScenario intermediate base class."""

import random
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.scenarios.config_driven_mesh import ConfigDrivenMeshScenario


def _base_args(**overrides):
    """Minimal args namespace matching the config-driven mesh contract."""
    data = {
        "hosts": 3,
        "switches": 4,
        "seed": 42,
        "addressing": {},
        "bridges": None,
        "bridge": None,
        "node_per_switch": 2,
        "host_degree_min": 1,
        "host_degree_max": 2,
        "switch_use_all": False,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class ConcreteScenario(ConfigDrivenMeshScenario):
    """Minimal concrete subclass for testing the base class contract."""

    def __init__(self, args, **kwargs):
        super().__init__(args, **kwargs)
        self.rng = None
        self.publisher_ids = set()

    def configure(self, net):
        pass

    def run_experiment(self, net):
        pass

    def teardown(self, net):
        pass


# --- Seam 1: Constructor ---


@pytest.mark.parametrize(
    ("run_dir", "expected"),
    [(Path("logs"), True), (Path("."), False), (None, False)],
)
def test_daemon_log_collection_enabled_uses_unresolved_run_dir(run_dir, expected):
    scenario = ConcreteScenario(_base_args(), run_dir=run_dir)

    assert scenario.daemon_log_collection_enabled is expected


def test_run_dir_resolved_and_created(tmp_path):
    sub = tmp_path / "output"
    scenario = ConcreteScenario(_base_args(), run_dir=sub)

    assert scenario.run_dir == sub.resolve()
    assert scenario.run_dir.is_dir()


def test_run_dir_defaults_to_logs_when_none():
    scenario = ConcreteScenario(_base_args(), run_dir=None)

    assert scenario.run_dir == Path("logs").resolve()


def test_scheme_from_addressing(tmp_path):
    scenario = ConcreteScenario(
        _base_args(addressing={"network_cidr": "192.168.0.0/16"}),
        run_dir=tmp_path,
    )

    assert scenario.scheme.host_ip(0, 0) == "192.168.0.1"


def test_bridge_configs_from_bridges_attribute(tmp_path):
    bridges = [{"name": "br0", "host": 0}]
    scenario = ConcreteScenario(_base_args(bridges=bridges), run_dir=tmp_path)

    assert scenario.bridge_configs == bridges


def test_bridge_configs_fallback_to_bridge_parsing(tmp_path):
    scenario = ConcreteScenario(
        _base_args(bridges=None, bridge=None), run_dir=tmp_path
    )

    assert scenario.bridge_configs == []


def test_shared_state_initialized(tmp_path):
    scenario = ConcreteScenario(_base_args(), run_dir=tmp_path)

    assert scenario.topo is None
    assert scenario.daemon_fleet is None
    assert scenario.cache_node_set == set()
    assert scenario.generated_node_dirs == []
    assert scenario.bridge_manager is not None


def test_log_context_and_debug_config_stored(tmp_path):
    log_ctx = {"original_stdout": sys.stdout}
    from src.core.debug import DebugConfig

    debug_cfg = DebugConfig(node_dirs=True)
    scenario = ConcreteScenario(
        _base_args(), run_dir=tmp_path, log_context=log_ctx, debug_config=debug_cfg
    )

    assert scenario.log_context is log_ctx
    assert scenario.debug_config is debug_cfg


# --- Seam 2: build_topology ---


def test_build_topology_passes_args_to_mesh_build_spec(tmp_path):
    rng = random.Random(99)
    scenario = ConcreteScenario(_base_args(), run_dir=tmp_path)
    scenario.rng = rng
    scenario.publisher_ids = {0, 2}

    with patch(
        "src.scenarios.config_driven_mesh.build_mesh_scenario"
    ) as mock_build:
        fake_topo = MagicMock()
        fake_topo.mesh_links = []
        mock_build.return_value = MagicMock(
            node_dirs=[tmp_path / "h0", tmp_path / "h1", tmp_path / "h2"],
            topo=fake_topo,
        )

        result = scenario.build_topology()

    spec = mock_build.call_args[0][0]
    assert spec.host_count == 3
    assert spec.switch_limit == 4
    assert spec.node_per_switch == 2
    assert spec.host_degree_min == 1
    assert spec.host_degree_max == 2
    assert spec.switch_use_all is False
    assert spec.rng is rng
    assert spec.publisher_ids == frozenset({0, 2})
    assert scenario.generated_node_dirs == [tmp_path / f"h{i}" for i in range(3)]
    assert scenario.topo is fake_topo
    assert result is fake_topo


# --- Seam 3: create_mininet ---


def test_create_mininet_delegates_to_tclink(tmp_path):
    scenario = ConcreteScenario(_base_args(), run_dir=tmp_path)
    fake_topo = MagicMock()

    with patch(
        "src.scenarios.config_driven_mesh.create_tclink_mininet"
    ) as mock_tclink:
        mock_tclink.return_value = MagicMock()
        result = scenario.create_mininet(fake_topo, autoSetMacs=True)

    mock_tclink.assert_called_once_with(fake_topo, autoSetMacs=True)
    assert result is mock_tclink.return_value


# --- Seam 4: daemon_log_collection_scope ---


def test_daemon_log_collection_scope_uses_generated_dirs_and_cache_nodes(tmp_path):
    scenario = ConcreteScenario(_base_args(hosts=3), run_dir=tmp_path)
    scenario.generated_node_dirs = [tmp_path / "h0", tmp_path / "h1"]
    scenario.cache_node_set = {1}

    scopes = scenario.daemon_log_collection_scope()

    assert [(s.idx, s.node_dir, s.has_csmgrd) for s in scopes] == [
        (0, tmp_path / "h0", False),
        (1, tmp_path / "h1", True),
    ]


def test_daemon_log_collection_scope_empty_when_no_dirs(tmp_path):
    scenario = ConcreteScenario(_base_args(hosts=3), run_dir=tmp_path)

    assert scenario.daemon_log_collection_scope() == []


# --- Seam 5: should_run_cli ---


def test_should_run_cli_true_by_default(tmp_path):
    assert ConcreteScenario(_base_args(), run_dir=tmp_path).should_run_cli() is True


def test_should_run_cli_false_when_no_cli(tmp_path):
    scenario = ConcreteScenario(_base_args(no_cli=True), run_dir=tmp_path)

    assert scenario.should_run_cli() is False


# --- Seam 6: before_cli / after_cli tee-swap ---


def test_before_cli_restores_original_streams(tmp_path):
    original_out = MagicMock()
    original_err = MagicMock()
    tee_out = MagicMock()
    tee_err = MagicMock()
    log_context = {
        "original_stdout": original_out,
        "original_stderr": original_err,
        "tee_stdout": tee_out,
        "tee_stderr": tee_err,
    }
    scenario = ConcreteScenario(
        _base_args(), run_dir=tmp_path, log_context=log_context
    )

    old_stdout, old_stderr = sys.stdout, sys.stderr
    try:
        scenario.before_cli(None)
        assert sys.stdout is original_out
        assert sys.stderr is original_err
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr


def test_after_cli_restores_tee_streams(tmp_path):
    tee_out = MagicMock()
    tee_err = MagicMock()
    log_context = {
        "original_stdout": MagicMock(),
        "original_stderr": MagicMock(),
        "tee_stdout": tee_out,
        "tee_stderr": tee_err,
    }
    scenario = ConcreteScenario(
        _base_args(), run_dir=tmp_path, log_context=log_context
    )

    old_stdout, old_stderr = sys.stdout, sys.stderr
    try:
        scenario.after_cli(None)
        assert sys.stdout is tee_out
        assert sys.stderr is tee_err
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr


def test_before_cli_noop_without_log_context(tmp_path):
    scenario = ConcreteScenario(_base_args(), run_dir=tmp_path)

    old_stdout = sys.stdout
    scenario.before_cli(None)
    assert sys.stdout is old_stdout


# --- Seam 7: Disaster before_cli with monitor (tested via DisasterScenario) ---


def test_disaster_before_cli_enters_background_then_swaps(tmp_path):
    """Disaster's before_cli calls monitor.enter_background() then super()."""
    from src.scenarios.disaster import DisasterScenario

    original_out = MagicMock()
    original_err = MagicMock()
    log_context = {
        "original_stdout": original_out,
        "original_stderr": original_err,
        "tee_stdout": MagicMock(),
        "tee_stderr": MagicMock(),
    }
    args = _base_args(
        events=[], ext=[], no_cli=False, results_json=""
    )
    scenario = DisasterScenario(args, run_dir=tmp_path, log_context=log_context)

    monitor = MagicMock()
    call_order = []
    monitor.enter_background.side_effect = lambda: call_order.append("enter_background")
    scenario.monitor = monitor

    old_stdout, old_stderr = sys.stdout, sys.stderr
    try:
        # Patch to track tee-swap ordering
        real_before_cli = ConfigDrivenMeshScenario.before_cli

        def tracking_before_cli(self_inner, net):
            call_order.append("super_before_cli")
            real_before_cli(self_inner, net)

        with patch.object(
            ConfigDrivenMeshScenario, "before_cli", tracking_before_cli
        ):
            scenario.before_cli(None)

        assert call_order == ["enter_background", "super_before_cli"]
        assert sys.stdout is original_out
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
