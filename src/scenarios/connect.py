"""External-bridge mesh scenario (ceforeemu-connect).

Runs a mesh topology with external bridge support on the shared BaseScenario
lifecycle so teardown/cleanup is staged and aggregated (the previous flat
run_connect() had no try/finally and leaked daemons on failure).
"""

import random
import sys
from pathlib import Path

from mininet.link import TCLink
from mininet.log import info

from ..core.addressing import AddressingScheme, DEFAULT_NETWORK_CIDR
from ..core.events import extract_publications
from ..core.flap_state import FlapState
from ..core.paths import resolve_run_path
from ..runtime.bridge import BridgeManager, parse_bridge_args
from ..runtime.cache_strategy import KCentersStrategy
from ..runtime.content_ops import ContentOperationRunner
from ..runtime.results_sink import RecordingSink
from ..runtime.scenario_setup import (
    ScenarioSetupSpec,
    TeardownSpec,
    setup_scenario,
    teardown_scenario,
)
from ..runtime.scheduler import EventScheduler
from ..core.roles import assign_roles
from ..runtime.template import provision_node_dirs
from ..runtime.topo import MeshTopo
from .base import BaseScenario, _propagate_failures


class ConnectScenario(BaseScenario):
    """Mesh topology with external bridge support.

    Seeds publication-only events before the CLI (get/pubsub_sub events are
    warned about, not executed). Caching uses k-centers without excluding
    publishers (unlike DisasterScenario).
    """

    def __init__(self, args, run_dir: Path | None = None, log_context=None):
        self.args = args
        self.run_dir = (run_dir or Path("logs")).resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.log_context = log_context
        self.debug_config = None

        self.rng = random.Random(args.seed) if args.seed is not None else None
        self.seed_label = "none" if args.seed is None else str(args.seed)

        addr_cfg = getattr(args, "addressing", {}) or {}
        self.scheme = AddressingScheme(
            addr_cfg.get("network_cidr", DEFAULT_NETWORK_CIDR)
        )

        events = getattr(args, "events", None) or []
        (
            self.publication_events,
            self.uri_publishers,
            publisher_ids,
        ) = extract_publications(events)
        self.publisher_ids = set(publisher_ids)
        ignored_retrievals = [
            event for event in events if event.get("type") in ("get", "pubsub_sub")
        ]
        if ignored_retrievals:
            info(
                "[warning] ceforeemu-connect does not execute get/pubsub_sub events; "
                "use disaster or interactive commands for retrieval\n"
            )

        self.bridge_configs = getattr(args, "bridges", None) or []
        if not self.bridge_configs:
            self.bridge_configs = parse_bridge_args(getattr(args, "bridge", None))

        self.bridge_manager = BridgeManager()
        self.topo = None
        self.daemon_fleet = None
        self.cache_node_set: set[int] = set()
        self.generated_node_dirs: list[Path] = []

    def build_topology(self):
        args = self.args
        roles = assign_roles(
            args.hosts, self.rng or random.Random(), self.publisher_ids
        )
        self.generated_node_dirs = provision_node_dirs(roles)
        self.topo = MeshTopo(
            hosts=args.hosts,
            swhich_num=args.switches,
            rng=self.rng,
            node_per_switch=args.node_per_switch,
            host_degree_min=args.host_degree_min,
            host_degree_max=args.host_degree_max,
            switch_use_all=args.switch_use_all,
        )
        return self.topo

    def create_mininet(self, topo, **kwargs):
        from mininet.net import Mininet

        return Mininet(topo=topo, link=TCLink, waitConnected=True, **kwargs)

    def configure(self, net):
        args = self.args
        topo_png_path = str(
            resolve_run_path(
                self.run_dir,
                args.topo_png,
                f"ex{args.hosts}_seed{self.seed_label}.png",
            )
        )
        spec = ScenarioSetupSpec(
            mesh_links=self.topo.mesh_links,
            scheme=self.scheme,
            host_count=args.hosts,
            publisher_ids=set(self.publisher_ids),
            cache_strategy=KCentersStrategy(
                cache_count=args.cache_count,
                down_count=args.down_count,
                exclude_publishers=False,
            ),
            fleet_run_dir=self.run_dir,
            fib_k=args.k,
            bridge_manager=self.bridge_manager,
            bridge_configs=self.bridge_configs,
            bw_args=args.bw,
            ext_args=args.ext,
            topo_png_path=topo_png_path,
            topo_seed=args.seed,
            topo_layout=args.topo_layout,
            fib_uri_publishers=self.uri_publishers or None,
        )
        result = setup_scenario(net, spec)
        self.daemon_fleet = result.daemon_fleet
        self.cache_node_set = result.cache_node_set

    def run_experiment(self, net):
        if not self.publication_events:
            return
        runner = ContentOperationRunner(
            net,
            run_dir=self.run_dir,
            sink=RecordingSink(),
            flap_state=FlapState(),
            seed_label=self.seed_label,
            uri_publishers=self.uri_publishers,
            phase="seed",
        )
        scheduler = EventScheduler(
            net,
            self.publication_events,
            mesh_links=self.topo.mesh_links,
            run_dir=self.run_dir,
            content_runner=runner,
        )
        runner.start()
        try:
            scheduler.start()
            if not scheduler.wait_all(timeout=60):
                info("[warning] publication event scheduling exceeded 60s deadline\n")
            if not runner.wait_all(timeout=60):
                info("[warning] publication seed operations exceeded 60s deadline\n")
        finally:
            # Stop both independently so a scheduler.stop() failure cannot leak
            # the runner; aggregate any failures.
            stop_failures: list[tuple[str, BaseException]] = []
            try:
                scheduler.stop()
            except BaseException as exc:
                stop_failures.append(("scheduler.stop", exc))
            try:
                runner.stop()
            except BaseException as exc:
                stop_failures.append(("runner.stop", exc))
            if stop_failures:
                _propagate_failures(None, stop_failures)

    def should_run_cli(self):
        return not getattr(self.args, "no_cli", False)

    def before_cli(self, net):
        if self.log_context:
            sys.stdout = self.log_context["original_stdout"]
            sys.stderr = self.log_context["original_stderr"]

    def after_cli(self, net):
        if self.log_context:
            sys.stdout = self.log_context["tee_stdout"]
            sys.stderr = self.log_context["tee_stderr"]

    def teardown(self, net):
        """Stop daemons and clean up bridges via the teardown seam."""
        spec = TeardownSpec(
            host_count=self.args.hosts,
            csmgrd_host_ids=self.cache_node_set,
            fleet_run_dir=self.run_dir,
            daemon_fleet=self.daemon_fleet,
            bridge_manager=self.bridge_manager,
            cleanup_external_bridges=False,
        )
        result = teardown_scenario(net, spec)
        if result.failures:
            _propagate_failures(None, result.failures)
