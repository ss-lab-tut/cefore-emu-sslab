"""External-bridge mesh scenario (ceforeemu-connect).

Runs a mesh topology with external bridge support on the shared
ConfigDrivenMeshScenario lifecycle so teardown/cleanup is staged and
aggregated.
"""

import random
from pathlib import Path

from mininet.log import info

from ..core.artifacts import topo_png_default_name
from ..core.events import extract_publications
from ..core.flap_state import FlapState
from ..core.paths import resolve_run_path
from ..runtime.cache_strategy import KCentersStrategy
from ..runtime.event_batch import EventBatchSpec, run_event_batch
from ..runtime.results_sink import RecordingSink
from ..runtime.scenario_setup import (
    ScenarioSetupSpec,
    TeardownSpec,
    setup_scenario,
    teardown_scenario,
)
from .base import _propagate_failures
from .config_driven_mesh import ConfigDrivenMeshScenario


class ConnectScenario(ConfigDrivenMeshScenario):
    """Mesh topology with external bridge support.

    Seeds publication-only events before the CLI (get/pubsub_sub/ccninfo
    events are warned about, not executed). Caching uses k-centers without
    excluding publishers (unlike DisasterScenario).
    """

    def __init__(
        self, args, run_dir: Path | None = None, log_context=None, debug_config=None
    ):
        super().__init__(args, run_dir=run_dir, log_context=log_context, debug_config=debug_config)

        self.rng = random.Random(args.seed) if args.seed is not None else None

        events = getattr(args, "events", None) or []
        (
            self.publication_events,
            self.uri_publishers,
            publisher_ids,
        ) = extract_publications(events)
        self.publisher_ids = set(publisher_ids)
        ignored_retrievals = [
            event
            for event in events
            if event.get("type") in ("get", "pubsub_sub", "ccninfo")
        ]
        if ignored_retrievals:
            info(
                "[warning] ceforeemu-connect does not execute get/pubsub_sub/ccninfo "
                "events; use disaster or interactive commands for retrieval\n"
            )

    def configure(self, net):
        args = self.args
        topo_png_path = str(
            resolve_run_path(
                self.run_dir,
                args.topo_png,
                topo_png_default_name(
                    getattr(args, "num", None), args.seed, args.hosts
                ),
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
            forwarding_config=getattr(args, "forwarding_config", None),
        )
        result = setup_scenario(net, spec)
        self.daemon_fleet = result.daemon_fleet
        self.cache_node_set = result.cache_node_set

    def run_experiment(self, net):
        if not self.publication_events:
            return
        spec = EventBatchSpec(
            events=self.publication_events,
            run_dir=self.run_dir,
            mesh_links=self.topo.mesh_links,
            sink=RecordingSink(),
            flap_state=FlapState(),
            uri_publishers=self.uri_publishers,
            phase="seed",
            start_time=None,
            wait_timeout=60,
            deadline_policy="warn",
            scheduler_label="publication event scheduling",
            runner_label="publication seed operations",
        )
        result = run_event_batch(net, spec)
        if result.failures:
            _propagate_failures(None, result.failures)

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
