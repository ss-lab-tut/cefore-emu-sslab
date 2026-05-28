"""Disaster topology scenario with periodic host failure simulation."""

import json
import random
import sys
import threading
import time
from pathlib import Path

from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import info

from ..core.addressing import AddressingScheme, DEFAULT_NETWORK_CIDR
from ..core.flap_state import FlapState
from ..core.graph import select_k_centers
from ..core.paths import ensure_within_run_dir, resolve_run_path

from ..runtime.bandwidth import parse_bw_args, set_link_bandwidth
from ..runtime.bridge import (
    BridgeManager,
    TeardownError,
    attach_external_interface,
    cleanup_external_bridges,
    parse_bridge_args,
    parse_ext_args,
    setup_bridges,
)
from ..runtime.content_ops import ContentOperationRunner
from ..runtime.monitoring import Monitor
from ..runtime.scheduler import EventScheduler
from ..runtime.cleanup import cleanup_all
from ..runtime.cefore import (
    run_cefstatus_all,
    run_csmgrstatus,
    start_cefnetd,
    start_csmgrd,
    stop_cefnetd,
    stop_csmgrd,
    wait_for_cefnetd,
)
from ..core.parsing import parse_int_list
from ..runtime.failure_manager import FlexibleFailureManager, periodic_host_flap
from ..runtime.net_config import apply_fib, apply_fib_routes, apply_ip_addr
from ..runtime.template import (
    apply_cache_node_settings,
    cleanup_node_dirs,
    ensure_node_dirs,
)
from ..runtime.topo import MeshTopo
from ..runtime.viz import build_host_graph, print_mesh_links, render_topology_png

from .base import BaseScenario, _propagate_failures


def _artifact_path(run_dir: Path, raw_path, default_name):
    """Resolve output file path under run_dir."""
    return resolve_run_path(run_dir, raw_path, default_name)



def _resolve_results_path(args, run_dir: Path):
    """Resolve results.json path from args."""
    raw = getattr(args, "results_json", None)
    if not raw:
        return None
    return _artifact_path(run_dir, raw, "results.json")


class DisasterScenario(BaseScenario):
    """Mesh topology with periodic host failure simulation.

    Extends BaseScenario with:
    - BridgeManager for root namespace bridging
    - Periodic host flapping
    - Autotest mode (--no-cli + results-json)
    - Per-URI FIB routing
    """

    def __init__(self, args, run_dir: Path = None, log_context=None, debug_config=None):
        self.args = args
        self.run_dir = (run_dir or Path("logs")).resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.log_context = log_context
        self.debug_config = debug_config

        addr_cfg = getattr(args, "addressing", {}) or {}
        self.scheme = AddressingScheme(
            addr_cfg.get("network_cidr", DEFAULT_NETWORK_CIDR)
        )

        self.rng = (
            random.Random(args.seed) if args.seed is not None else random.Random()
        )
        self.results = []
        self._results_lock = threading.Lock()
        self._host_cmd_locks: dict[int, threading.Lock] = {}
        self.bridge_manager = BridgeManager()
        self.stop_event = None
        self.started_csmgrd_hosts = set()
        self.cache_node_set = set()
        self.flap_state = FlapState()
        self.uri_publishers = {}
        self.publisher_ids = set()
        self.topo = None
        self.seed_label = "none" if args.seed is None else str(args.seed)
        self.stop_thread = None
        self.event_scheduler = None
        self.content_runner = None
        self.monitor = None
        self.dashboard = None
        self.webui = None
        self.generated_node_dirs = []
        self._fib_routes = []

        # Parse bridge configs
        self.bridge_configs = getattr(args, "bridges", None) or []
        if not self.bridge_configs:
            self.bridge_configs = parse_bridge_args(getattr(args, "bridge", None))

        self.results_path = _resolve_results_path(args, self.run_dir)
        self.autotest_mode = bool(
            getattr(args, "no_cli", False) and self.results_path is not None
        )
        if self.autotest_mode and (args.ext or self.bridge_configs):
            sys.exit("autotest mode forbids ext/bridge configuration")

        self._prepare_event_publishers()

    def _host_lock(self, host_idx: int) -> threading.Lock:
        if host_idx not in self._host_cmd_locks:
            self._host_cmd_locks[host_idx] = threading.Lock()
        return self._host_cmd_locks[host_idx]

    def _prepare_event_publishers(self):
        """Collect publisher metadata from event-driven content operations."""
        args = self.args
        for ev in getattr(args, "events", None) or []:
            if ev.get("type") in ("put", "pubsub_pub"):
                self.publisher_ids.add(ev["host"])
                self.uri_publishers[ev["uri"]] = ev["host"]

    def _warn_event_diagnostics(self, events_config):
        """Warn about event sets that cannot produce observable retrievals."""
        puts = {ev["uri"] for ev in events_config if ev.get("type") == "put"}
        gets = {ev["uri"] for ev in events_config if ev.get("type") == "get"}
        pubs = {ev["uri"] for ev in events_config if ev.get("type") == "pubsub_pub"}
        subs = {ev["uri"] for ev in events_config if ev.get("type") == "pubsub_sub"}
        for uri in sorted(puts - gets):
            info(f"[warning] put event for {uri} has no matching get event\n")
        for uri in sorted(pubs - subs):
            info(f"[warning] pubsub_pub event for {uri} has no matching pubsub_sub event\n")

    def build_topology(self):
        """Create mesh topology."""
        args = self.args
        self.generated_node_dirs = ensure_node_dirs(
            args.hosts, self.rng, self.publisher_ids
        )

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
        """Create Mininet with TCLink."""
        from mininet.net import Mininet

        return Mininet(topo=topo, link=TCLink, waitConnected=True, **kwargs)

    def configure(self, net):
        """Configure network: IP, bridges, bandwidth, daemons, FIB."""
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

        for idx in range(args.hosts):
            info(net.hosts[idx].cmd("ifconfig"))

        for node_a, node_b, bandwidth in parse_bw_args(args.bw):
            set_link_bandwidth(net, node_a, node_b, bandwidth)

        for host_name, intf_name, ip, mtu in parse_ext_args(args.ext):
            attach_external_interface(net, host_name, intf_name, ip, mtu)

        # Topology visualization
        topo_png = _artifact_path(
            self.run_dir,
            args.topo_png,
            f"ex{args.hosts}_seed{self.seed_label}.png",
        )
        render_topology_png(
            self.topo.mesh_links,
            str(topo_png),
            seed=args.seed,
            layout=args.topo_layout,
        )

        # Cache node selection
        host_graph, _ = build_host_graph(self.topo.mesh_links)
        cache_config = getattr(args, "cache_config", None) or {}
        if cache_config:
            from ..runtime.cache_manager import CacheConfigManager

            manager = CacheConfigManager(
                cache_config, args.hosts, host_graph, self.publisher_ids
            )
            cache_nodes = manager.select_cache_nodes(exclude=self.publisher_ids)
            if not cache_nodes and args.hosts > 0:
                cache_nodes = [args.hosts - 1]
            self.cache_node_set = set(cache_nodes)
            if cache_nodes:
                info(
                    "cache nodes: " + ", ".join(f"h{idx}" for idx in cache_nodes) + "\n"
                )
            manager.apply_configs(self.cache_node_set)
        else:
            cache_count = (
                args.cache_count if args.cache_count > 0 else args.down_count + 1
            )
            cache_nodes = select_k_centers(
                host_graph, cache_count, exclude=self.publisher_ids
            )
            if not cache_nodes and args.hosts > 0:
                cache_nodes = [args.hosts - 1]
            self.cache_node_set = set(cache_nodes)
            if cache_nodes:
                info(
                    "cache nodes: " + ", ".join(f"h{idx}" for idx in cache_nodes) + "\n"
                )
            apply_cache_node_settings(
                args.hosts,
                self.cache_node_set,
                getattr(args, "cache_default_rct_ms", None),
                publishers=self.publisher_ids,
            )

        # Daemon startup: csmgrd -> cefnetd -> wait ready
        for idx in sorted(self.cache_node_set):
            start_csmgrd(net, idx)
            self.started_csmgrd_hosts.add(idx)

        for idx in range(args.hosts):
            start_cefnetd(net, idx)
        cefnetd_timeout = getattr(args, "cefnetd_timeout", None) or 10
        not_ready = []
        for idx in range(args.hosts):
            if not wait_for_cefnetd(net, idx, timeout=cefnetd_timeout):
                not_ready.append(idx)
        if not_ready:
            hosts = ", ".join(f"h{idx}" for idx in not_ready)
            raise RuntimeError(
                f"cefnetd not ready on {hosts}; aborting before FIB programming"
            )

        # FIB programming
        routing_config = getattr(args, "routing", None) or {}
        routing_strategy = routing_config.get("strategy", "dijkstra")
        routing_k = routing_config.get("k", args.k)
        self._fib_routes = apply_fib(
            net,
            self.topo.mesh_links,
            routing_k,
            strategy=routing_strategy,
            uri_publishers=self.uri_publishers or None,
            scheme=self.scheme,
        )

        run_cefstatus_all(net, args.hosts)
        print_mesh_links(self.topo.mesh_links)

        webui_port = getattr(args, "webui_port", None)
        if webui_port:
            import time as _time
            from ..webui.state import DashboardState
            from ..webui.server import WebUIServer
            self.dashboard = DashboardState(
                host_count=args.hosts,
                cache_nodes=self.cache_node_set,
                seed=args.seed,
                started_at=_time.time(),
                flap_state_getter=self.flap_state.snapshot,
            )
            self.dashboard.set_topology(self.topo.mesh_links)
            self.webui = WebUIServer(self.dashboard, port=webui_port)
            self.webui.start()
            info(f"[webui] dashboard: http://0.0.0.0:{webui_port}/\n")
            # Pre-populate initial host state before Monitor starts polling
            for idx in range(args.hosts):
                output = net.hosts[idx].cmd(f"cefstatus -d ./h{idx}")
                self.dashboard.record_monitor({
                    "elapsed_sec": 0.0, "type": "cefstatus", "host": idx, "output": output,
                })
            for idx in sorted(self.cache_node_set):
                output = run_csmgrstatus(net, idx, host="127.0.0.1")
                self.dashboard.record_monitor({
                    "elapsed_sec": 0.0, "type": "csmgrstatus", "host": idx, "output": output,
                })

    def _append_result(self, record):
        """Thread-safe append to results list."""
        with self._results_lock:
            self.results.append(record)
        if self.dashboard is not None:
            self.dashboard.record_operation(record)

    def _restore_fib_for_host(self, net, host_idx: int):
        """Re-apply dynamic FIB routes for a host after it comes back up."""
        if not self._fib_routes:
            return
        timeout = getattr(self.args, "cefnetd_timeout", None) or 10
        with self._host_lock(host_idx):
            if not wait_for_cefnetd(net, host_idx, timeout=timeout):
                info(f"[failure] h{host_idx} cefnetd not ready; skipping FIB restore\n")
                return
            apply_fib_routes(net, self._fib_routes, source=host_idx)
            info(f"[failure] restored dynamic FIB entries for h{host_idx}\n")

    def _make_content_runner(self, net, events_config, phase="event"):
        """Create a ContentOperationRunner for the given phase."""
        startup_grace = float(getattr(self.args, "pubsub_sub_startup_grace", 1.0))
        pub_lifetime_by_uri = {}
        for ev in events_config:
            if ev.get("type") == "pubsub_pub":
                pub_opts = ev.get("pub_opts") or {}
                lifetime = pub_opts.get("lifetime")
                if lifetime is not None:
                    pub_lifetime_by_uri[ev["uri"]] = lifetime
        return ContentOperationRunner(
            net,
            run_dir=self.run_dir,
            result_callback=self._append_result,
            flap_state=self.flap_state,
            seed_label=self.seed_label,
            uri_publishers=self.uri_publishers,
            startup_grace=startup_grace,
            pub_lifetime_by_uri=pub_lifetime_by_uri,
            phase=phase,
        )

    def _start_failure_manager(self, net, use_cli):
        """Start host flapping via failure_scenarios or legacy --down-* args."""
        args = self.args
        scenario_config = getattr(args, "failure_scenarios", None)
        if scenario_config:
            failure_manager = FlexibleFailureManager(
                scenario_config=scenario_config,
                host_count=args.hosts,
                rng=self.rng,
                publisher_ids=self.publisher_ids,
                on_host_up=lambda host_idx: self._restore_fib_for_host(net, host_idx),
            )
            self.stop_event, self.stop_thread = failure_manager.start(
                net, self.flap_state, quiet=use_cli
            )
        elif args.down_interval > 0 and args.down_duration > 0:
            exclude_ids = parse_int_list(args.down_exclude)
            if self.publisher_ids:
                exclude_ids = list(set(exclude_ids) | self.publisher_ids)
            self.stop_event = periodic_host_flap(
                net,
                args.hosts,
                args.down_interval,
                args.down_duration,
                self.rng,
                exclude_ids,
                self.flap_state,
                args.down_count,
                args.down_stagger,
                quiet=use_cli,
                on_host_up=lambda host_idx: self._restore_fib_for_host(net, host_idx),
            )

    def _run_warmup(self, net, events_config):
        """Execute warmup prefetch phase: get hot content into cache nodes."""
        args = self.args
        warmup_gets = getattr(args, "warmup_gets", None)
        warmup_interval = float(getattr(args, "warmup_get_interval", 0))
        warmup_cache_only = getattr(args, "warmup_only_cache_nodes", True)

        if warmup_gets:
            warmup_ops = warmup_gets
        else:
            put_uris = {
                ev["uri"] for ev in events_config if ev.get("type") == "put"
            }
            if not put_uris:
                return True
            if warmup_cache_only:
                warmup_hosts = sorted(self.cache_node_set)
            else:
                warmup_hosts = [
                    i for i in range(args.hosts) if i not in self.publisher_ids
                ]
            if not warmup_hosts:
                return True
            warmup_ops = [
                {"host": h, "uri": u}
                for u in sorted(put_uris)
                for h in warmup_hosts
            ]

        if not warmup_ops:
            return True

        info(f"[warmup] starting warmup phase: {len(warmup_ops)} gets\n")
        warmup_runner = self._make_content_runner(net, events_config, phase="warmup")
        warmup_runner.start()
        try:
            for op in warmup_ops:
                warmup_runner.submit("get", op)
                if warmup_interval > 0:
                    time.sleep(warmup_interval)
            completed = warmup_runner.wait_all(timeout=300)
            if not completed:
                info("[warning] warmup content operations exceeded 300s deadline\n")
                return False
            info("[warmup] warmup phase complete\n")
            return True
        finally:
            warmup_runner.stop()

    def _start_monitoring(self, net):
        """Start monitoring if configured."""
        args = self.args
        monitoring_config = dict(getattr(args, "monitoring", None) or {})
        if self.dashboard is not None and not monitoring_config.get("targets"):
            monitoring_config["targets"] = [
                {"type": "cefstatus",   "hosts": "all"},
                {"type": "csmgrstatus", "hosts": "cache"},
            ]
            monitoring_config.setdefault("interval", 5)
        if monitoring_config.get("targets"):
            self.monitor = Monitor(
                net,
                targets=monitoring_config["targets"],
                interval=monitoring_config.get("interval", 5),
                output_dir=self.run_dir,
                host_count=args.hosts,
                cache_nodes=self.cache_node_set,
                output_json=monitoring_config.get("output_json"),
                output_csv=monitoring_config.get("output_csv"),
                down_hosts_getter=self.flap_state.snapshot,
                on_record=self.dashboard.record_monitor if self.dashboard else None,
            )
            self.monitor.start()

    def _run_normal_experiment(self, net, events_config, origin, use_cli):
        """Run interactive or non-autotest execution with all events together."""
        content_event_types = {"put", "get", "pubsub_pub", "pubsub_sub"}
        has_content_events = any(
            e.get("type") in content_event_types for e in events_config
        )
        self._start_failure_manager(net, use_cli)

        if has_content_events:
            self.content_runner = self._make_content_runner(net, events_config)
            self.content_runner.start()
        if events_config:
            self.event_scheduler = EventScheduler(
                net, events_config,
                mesh_links=self.topo.mesh_links,
                run_dir=self.run_dir,
                content_runner=self.content_runner,
                start_time=origin,
            )
            self.event_scheduler.start()

    def _run_autotest_experiment(self, net, events_config, origin, use_cli):
        """Run seed, warmup, failure and evaluation phases in order."""
        put_events = [ev for ev in events_config if ev.get("type") == "put"]
        eval_events = [ev for ev in events_config if ev.get("type") != "put"]

        if any(ev.get("repeat") for ev in put_events):
            raise ValueError("autotest does not support repeat on put events")

        if put_events:
            put_runner = self._make_content_runner(net, put_events, phase="event")
            put_scheduler = EventScheduler(
                net, put_events,
                mesh_links=self.topo.mesh_links,
                run_dir=self.run_dir,
                content_runner=put_runner,
                start_time=origin,
            )
            put_runner.start()
            try:
                put_scheduler.start()
                if not put_scheduler.wait_all(timeout=300):
                    raise RuntimeError("seed event scheduling exceeded 300s deadline")
                if not put_runner.wait_all(timeout=300):
                    raise RuntimeError("seed content operations exceeded 300s deadline")
            finally:
                put_scheduler.stop()
                put_runner.stop()

        if not self._run_warmup(net, events_config):
            raise RuntimeError("warmup content operations did not complete")

        duration = max(0, int(getattr(self.args, "duration", 0)))
        if not eval_events and duration == 0:
            info(
                "[warning] no evaluation events configured; "
                "failure phase will not run after seed/warmup\n"
            )
            return
        if not eval_events:
            info(
                "[warning] no evaluation events configured; "
                "running failure/monitoring observation for configured duration\n"
            )

        self._start_failure_manager(net, use_cli)
        content_event_types = {"get", "pubsub_pub", "pubsub_sub"}
        if any(ev.get("type") in content_event_types for ev in eval_events):
            self.content_runner = self._make_content_runner(
                net, eval_events, phase="eval"
            )
            self.content_runner.start()
        if eval_events:
            self.event_scheduler = EventScheduler(
                net, eval_events,
                mesh_links=self.topo.mesh_links,
                run_dir=self.run_dir,
                content_runner=self.content_runner,
                start_time=origin,
            )
            self.event_scheduler.start()

    def run_experiment(self, net):
        """Run the disaster experiment with event-driven content operations."""
        args = self.args
        use_cli = not getattr(args, "no_cli", False)
        events_config = getattr(args, "events", None) or []
        origin = time.monotonic()

        if not events_config:
            info("[warning] no events configured; no content operations will run\n")
        self._warn_event_diagnostics(events_config)

        if self.autotest_mode:
            self._run_autotest_experiment(net, events_config, origin, use_cli)
        else:
            self._run_normal_experiment(net, events_config, origin, use_cli)

        self._start_monitoring(net)

        duration = max(0, int(getattr(args, "duration", 0)))
        if not use_cli and duration > 0:
            time.sleep(duration)
        elif not use_cli and self.event_scheduler is not None:
            self.event_scheduler.wait_all()

    def execute(self):
        """Override BaseScenario.execute() for CLI and autotest control.

        Staged cleanup: every stage is attempted independently. Failures
        are accumulated and re-raised after all cleanup completes.
        """
        net = None
        try:
            topo = self.build_topology()
            net = self.create_mininet(topo)
            net.start()
            self.configure(net)
            self.run_experiment(net)

            use_cli = not getattr(self.args, "no_cli", False)
            if use_cli:
                if self.log_context:
                    sys.stdout = self.log_context["original_stdout"]
                    sys.stderr = self.log_context["original_stderr"]
                CLI(net)
                if self.log_context:
                    sys.stdout = self.log_context["tee_stdout"]
                    sys.stderr = self.log_context["tee_stderr"]
        except KeyboardInterrupt:
            info("\nInterrupted by user.\n")
        finally:
            # Front-end shutdown — each stage attempted independently.
            # BaseException (not just Exception) is caught so that SystemExit,
            # KeyboardInterrupt, etc. during shutdown do not abort cleanup.
            cleanup_failures: list[tuple[str, BaseException]] = []

            if self.monitor is not None:
                try:
                    self.monitor.stop()
                except BaseException as exc:
                    cleanup_failures.append(("monitor.stop", exc))
            if self.webui is not None:
                try:
                    self.webui.stop()
                except BaseException as exc:
                    cleanup_failures.append(("webui.stop", exc))
            if self.event_scheduler is not None:
                try:
                    self.event_scheduler.stop()
                except BaseException as exc:
                    cleanup_failures.append(("event_scheduler.stop", exc))
            if self.content_runner is not None:
                # Stage A: wait_all() may raise; capture independently so a
                # failure here does NOT skip stop(). (Defect 4.)
                try:
                    if not self.content_runner.wait_all(timeout=60):
                        info("[warning] content operation shutdown exceeded 60s deadline\n")
                except BaseException as exc:
                    cleanup_failures.append(("content_runner.wait_all", exc))
                # Stage B: stop() is always attempted.
                try:
                    self.content_runner.stop()
                except BaseException as exc:
                    cleanup_failures.append(("content_runner.stop", exc))
            if self.stop_event is not None:
                try:
                    self.stop_event.set()
                except BaseException as exc:
                    cleanup_failures.append(("stop_event.set", exc))

            # Capture any in-flight primary exception
            primary_exc = sys.exc_info()[1]
            if isinstance(primary_exc, KeyboardInterrupt):
                primary_exc = None

            if net is not None:
                # Stage 1: Debug pre-teardown (best-effort, never blocks cleanup)
                try:
                    self.collect_debug_pre_teardown(net)
                except BaseException as exc:
                    cleanup_failures.append(("debug_pre_teardown", exc))

                # Stage 2: Teardown (daemon stop, bridge cleanup, external bridges)
                try:
                    self.teardown(net)
                except BaseException as exc:
                    cleanup_failures.append(("teardown", exc))
                    info(f"Error during teardown: {exc}\n")

                # Stage 3: Debug post-teardown (best-effort, never blocks cleanup)
                try:
                    self.collect_debug_post_teardown()
                except BaseException as exc:
                    cleanup_failures.append(("debug_post_teardown", exc))

                # Stage 4: Generic cleanup
                try:
                    cleanup_all(net, self.generated_node_dirs)
                except BaseException as exc:
                    cleanup_failures.append(("cleanup_all", exc))
            else:
                try:
                    cleanup_node_dirs(self.generated_node_dirs)
                except BaseException as exc:
                    cleanup_failures.append(("cleanup_node_dirs", exc))

            # Results write — after all operational cleanup
            if self.results_path is not None:
                try:
                    self.results_path.write_text(
                        json.dumps(self.results, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except BaseException as exc:
                    cleanup_failures.append(("results_write", exc))

            # Final exception propagation
            _propagate_failures(primary_exc, cleanup_failures)

    def collect_debug_pre_teardown(self, net):
        if self.debug_config is None or not self.debug_config.fib_dump:
            return
        from ..runtime.debug import dump_fib

        dest = self.run_dir / self.debug_config.output_subdir / "fib"
        ensure_within_run_dir(self.run_dir, dest)
        dump_fib(net, list(range(self.args.hosts)), dest)

    def collect_debug_post_teardown(self):
        super().collect_debug_post_teardown()
        if self.debug_config is None or not self.debug_config.daemon_logs:
            return
        from ..runtime.debug import archive_daemon_logs

        dest = self.run_dir / self.debug_config.output_subdir / "daemon_logs"
        ensure_within_run_dir(self.run_dir, dest)
        archive_daemon_logs(self.args.hosts, dest)

    def teardown(self, net):
        """Stop daemons and clean up bridges.

        All cleanup stages are attempted independently. Failures are
        accumulated and raised as an aggregate after all stages complete.
        BaseException (not just Exception) is caught so that SystemExit,
        KeyboardInterrupt, etc. during teardown do not abort remaining cleanup.
        """
        teardown_failures: list[tuple[str, BaseException]] = []

        # Daemon stops — each host attempted independently
        for idx in range(self.args.hosts):
            try:
                stop_cefnetd(net, idx)
            except BaseException as exc:
                teardown_failures.append((f"stop_cefnetd h{idx}", exc))
        for idx in sorted(self.started_csmgrd_hosts):
            try:
                stop_csmgrd(net, idx)
            except BaseException as exc:
                teardown_failures.append((f"stop_csmgrd h{idx}", exc))

        # BridgeManager cleanup
        try:
            self.bridge_manager.cleanup()
        except BaseException as exc:
            teardown_failures.append(("bridge_manager.cleanup", exc))

        # External bridge cleanup — always attempted
        try:
            cleanup_external_bridges()
        except BaseException as exc:
            teardown_failures.append(("cleanup_external_bridges", exc))

        # Aggregate and raise
        if teardown_failures:
            _propagate_failures(None, teardown_failures)


def run_disaster_scenario(args, run_dir=None, log_context=None, debug_config=None):
    """Convenience function to run disaster scenario."""
    scenario = DisasterScenario(args, run_dir, log_context, debug_config)
    scenario.execute()
