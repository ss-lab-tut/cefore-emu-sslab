"""Config-driven TCLink mesh scenario base.

Intermediate base between BaseScenario and DisasterScenario/ConnectScenario.
Hoists shared mesh lifecycle glue: constructor prologue, build_topology,
create_mininet (TCLink), daemon_log_collection_scope, CLI gate, and tee-swap.

Subclasses must set ``self.rng`` and ``self.publisher_ids`` in their own
``__init__`` after calling ``super().__init__()``.  These attributes are
consumed by ``build_topology()`` which is called later by ``execute()``,
never during construction.
"""

import sys
from pathlib import Path

from ..core.addressing import AddressingScheme, DEFAULT_NETWORK_CIDR
from ..runtime.bridge_args import parse_bridge_args
from ..runtime.bridge_root import BridgeManager
from ..runtime.daemon_logs import HostLogScope
from ..runtime.scenario_setup import (
    MeshBuildSpec,
    build_mesh_scenario,
    create_tclink_mininet,
)
from .base import BaseScenario


class ConfigDrivenMeshScenario(BaseScenario):
    """Shared lifecycle glue for config-driven TCLink mesh scenarios.

    Provides the common constructor prologue, mesh topology construction,
    TCLink Mininet creation, daemon-log scope, CLI gate, and stdout/stderr
    tee-swap that Disaster and Connect share identically.

    Subclass contract:
        - Set ``self.rng`` (Random instance or None) after super().__init__().
        - Set ``self.publisher_ids`` (set[int]) after super().__init__().
        - Override ``configure()``, ``run_experiment()``, ``teardown()``.
    """

    def __init__(
        self, args, run_dir: Path | None = None, log_context=None, debug_config=None
    ):
        self.args = args
        # Sentinel must be evaluated before resolve(): Path(".").resolve()
        # produces a real directory that would incorrectly enable collection.
        self.daemon_log_collection_enabled = run_dir is not None and Path(
            run_dir
        ) != Path(".")
        self.run_dir = (run_dir or Path("logs")).resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.log_context = log_context
        self.debug_config = debug_config

        addr_cfg = getattr(args, "addressing", {}) or {}
        self.scheme = AddressingScheme(
            addr_cfg.get("network_cidr", DEFAULT_NETWORK_CIDR)
        )

        self.bridge_configs = getattr(args, "bridges", None) or []
        if not self.bridge_configs:
            self.bridge_configs = parse_bridge_args(getattr(args, "bridge", None))

        self.bridge_manager = BridgeManager()
        # Early init: execute()'s finally block references these fields even
        # after partial construction or setup failure.
        self.topo = None
        self.daemon_fleet = None
        self.cache_node_set: set[int] = set()
        self.generated_node_dirs: list[Path] = []

    def build_topology(self):
        """Create mesh topology from args, rng, and publisher_ids."""
        args = self.args
        spec = MeshBuildSpec(
            host_count=args.hosts,
            switch_limit=args.switches,
            node_per_switch=args.node_per_switch,
            host_degree_min=args.host_degree_min,
            host_degree_max=args.host_degree_max,
            switch_use_all=args.switch_use_all,
            rng=self.rng,
            publisher_ids=frozenset(self.publisher_ids),
        )
        result = build_mesh_scenario(spec)
        self.generated_node_dirs = result.node_dirs
        self.topo = result.topo
        return self.topo

    def create_mininet(self, topo, **kwargs):
        """Create Mininet with TCLink for bandwidth-capable links."""
        return create_tclink_mininet(topo, **kwargs)

    def daemon_log_collection_scope(self):
        """Describe daemon logs from generated hN directories for this run."""
        return [
            HostLogScope(
                idx=i,
                node_dir=self.generated_node_dirs[i],
                has_csmgrd=i in self.cache_node_set,
            )
            for i in range(self.args.hosts)
            if i < len(self.generated_node_dirs)
        ]

    def should_run_cli(self):
        """Skip the interactive CLI when --no-cli is set."""
        return not getattr(self.args, "no_cli", False)

    def before_cli(self, net):
        """Restore original stdout/stderr for the interactive CLI."""
        if self.log_context:
            sys.stdout = self.log_context["original_stdout"]
            sys.stderr = self.log_context["original_stderr"]

    def after_cli(self, net):
        """Restore tee'd stdout/stderr after the CLI returns."""
        if self.log_context:
            sys.stdout = self.log_context["tee_stdout"]
            sys.stderr = self.log_context["tee_stderr"]
