"""External-bridge mesh scenario (ceforeemu-connect).

Runs a mesh topology with external bridge support on the shared BaseScenario
lifecycle so teardown/cleanup is staged and aggregated (the previous flat
run_connect() had no try/finally and leaked daemons on failure).
"""

import random
import sys
import time
from pathlib import Path

from mininet.link import TCLink
from mininet.log import info

from ..core.addressing import AddressingScheme, DEFAULT_NETWORK_CIDR
from ..core.flap_state import FlapState
from ..core.paths import resolve_run_path
from ..runtime.bandwidth import parse_bw_args, set_link_bandwidth
from ..runtime.bridge import (
    BridgeManager,
    attach_external_interface,
    parse_bridge_args,
    parse_ext_args,
    setup_bridges,
)
from ..runtime.cefore import run_cefstatus_all
from ..runtime.daemon_fleet import build_fleet
from ..runtime.command_runner import MininetCommandRunner
from ..runtime.content_ops import ContentOperationRunner
from ..runtime.net_config import apply_fib, apply_ip_addr
from ..runtime.results_sink import RecordingSink
from ..runtime.scheduler import EventScheduler
from ..runtime.cache_manager import CachePlacement
from ..core.roles import assign_roles
from ..runtime.template import provision_node_dirs
from ..runtime.topo import MeshTopo
from ..runtime.viz import build_host_graph, print_mesh_links, render_topology_png
from .base import BaseScenario, _propagate_failures


def _publication_metadata(events):
    """Return publication events and their URI-to-publisher mapping."""
    publications = [
        event for event in events if event.get("type") in ("put", "pubsub_pub")
    ]
    publishers = {event["uri"]: event["host"] for event in publications}
    return publications, publishers


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
        self.publication_events, self.uri_publishers = _publication_metadata(events)
        self.publisher_ids = set(self.uri_publishers.values())
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

        apply_ip_addr(net, self.topo.mesh_links, scheme=self.scheme)

        if self.bridge_configs:
            setup_bridges(
                net,
                self.bridge_manager,
                self.bridge_configs,
                args.hosts,
                self.topo.mesh_links,
                scheme=self.scheme,
            )

        ifconfig_runner = MininetCommandRunner(net)
        for idx in range(args.hosts):
            info(ifconfig_runner.run(f"h{idx}", ["ifconfig"]).stdout)

        host_graph, _ = build_host_graph(self.topo.mesh_links)
        self.cache_node_set = CachePlacement(
            host_count=args.hosts,
            host_graph=host_graph,
            publisher_ids=self.publisher_ids,
            cache_count=args.cache_count,
            down_count=args.down_count,
            exclude_publishers=False,
        ).place()

        self.daemon_fleet = build_fleet(
            net, args.hosts, self.cache_node_set, self.run_dir
        )
        self.daemon_fleet.start_all()
        self.daemon_fleet.wait_ready()

        apply_fib(
            net,
            self.topo.mesh_links,
            args.k,
            uri_publishers=self.uri_publishers or None,
            scheme=self.scheme,
        )

        run_cefstatus_all(net, args.hosts)
        print_mesh_links(self.topo.mesh_links)

        topo_png_path = str(
            resolve_run_path(
                self.run_dir,
                args.topo_png,
                f"ex{args.hosts}_seed{self.seed_label}.png",
            )
        )
        render_topology_png(
            self.topo.mesh_links,
            topo_png_path,
            seed=args.seed,
            layout=args.topo_layout,
        )
        time.sleep(1)

        for node_a, node_b, bandwidth in parse_bw_args(args.bw):
            set_link_bandwidth(net, node_a, node_b, bandwidth)

        for host_name, intf_name, ip, mtu in parse_ext_args(args.ext):
            attach_external_interface(net, host_name, intf_name, ip, mtu)

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
        """Stop daemons and clean up bridges.

        Each stage is attempted independently; failures are accumulated and
        raised as an aggregate so a single daemon-stop failure cannot skip
        bridge_manager.cleanup().
        """
        teardown_failures: list[tuple[str, BaseException]] = []

        fleet = self.daemon_fleet or build_fleet(
            net, self.args.hosts, self.cache_node_set, self.run_dir
        )
        teardown_failures.extend(fleet.stop_all())

        try:
            self.bridge_manager.cleanup()
        except BaseException as exc:
            teardown_failures.append(("bridge_manager.cleanup", exc))

        if teardown_failures:
            _propagate_failures(None, teardown_failures)
