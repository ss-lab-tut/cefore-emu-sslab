"""Disaster topology scenario with periodic host failure simulation."""

import random
import sys
import threading
import time
from pathlib import Path

from mininet.link import TCLink
from mininet.log import info

from ..core.addressing import AddressingScheme, DEFAULT_NETWORK_CIDR
from ..core.events import extract_publications
from ..core.flap_state import FlapState
from ..core.paths import resolve_run_path

from ..runtime.bridge import (
    BridgeManager,
    parse_bridge_args,
)
from ..runtime.cache_strategy import KCentersStrategy, RandomCSModeStrategy
from ..runtime.command_runner import MininetCommandRunner
from ..runtime.content_ops import ContentOperationRunner
from ..runtime.event_batch import EventBatchSpec, run_event_batch
from ..runtime.monitoring import Monitor
from ..runtime.results_sink import ResultsSink
from ..runtime.scenario_setup import (
    ScenarioSetupSpec,
    TeardownSpec,
    setup_scenario,
    teardown_scenario,
)
from ..runtime.cefore import run_csmgrstatus, wait_for_cefnetd
from ..core.parsing import parse_int_list
from ..runtime.failure_manager import FlexibleFailureManager, periodic_host_flap
from ..runtime.net_config import apply_fib_routes
from ..core.roles import assign_roles
from ..runtime.template import provision_node_dirs
from ..runtime.topo import MeshTopo

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
        self.results_sink = ResultsSink()
        self._host_cmd_locks: dict[int, threading.Lock] = {}
        self.bridge_manager = BridgeManager()
        self.stop_event = None
        self.daemon_fleet = None
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

        events = getattr(args, "events", None) or []
        _, self.uri_publishers, publisher_ids = extract_publications(events)
        self.publisher_ids = set(publisher_ids)

    def _host_lock(self, host_idx: int) -> threading.Lock:
        if host_idx not in self._host_cmd_locks:
            self._host_cmd_locks[host_idx] = threading.Lock()
        return self._host_cmd_locks[host_idx]

    def _warn_event_diagnostics(self, events_config):
        """Warn about event sets that cannot produce observable retrievals."""
        puts = {ev["uri"] for ev in events_config if ev.get("type") == "put"}
        gets = {ev["uri"] for ev in events_config if ev.get("type") == "get"}
        pubs = {ev["uri"] for ev in events_config if ev.get("type") == "pubsub_pub"}
        subs = {ev["uri"] for ev in events_config if ev.get("type") == "pubsub_sub"}
        for uri in sorted(puts - gets):
            info(f"[warning] put event for {uri} has no matching get event\n")
        for uri in sorted(pubs - subs):
            info(
                f"[warning] pubsub_pub event for {uri} has no matching pubsub_sub event\n"
            )

    def build_topology(self):
        """Create mesh topology."""
        args = self.args
        roles = assign_roles(args.hosts, self.rng, self.publisher_ids)
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
        """Create Mininet with TCLink."""
        from mininet.net import Mininet

        return Mininet(topo=topo, link=TCLink, waitConnected=True, **kwargs)

    def configure(self, net):
        """Configure network: IP, bridges, bandwidth, daemons, FIB."""
        args = self.args
        routing_config = getattr(args, "routing", None) or {}
        topo_png = _artifact_path(
            self.run_dir,
            args.topo_png,
            f"ex{args.hosts}_seed{self.seed_label}.png",
        )
        spec = ScenarioSetupSpec(
            mesh_links=self.topo.mesh_links,
            scheme=self.scheme,
            host_count=args.hosts,
            publisher_ids=set(self.publisher_ids),
            cache_strategy=self._build_cache_strategy(),
            fleet_run_dir=self.run_dir,
            fib_k=routing_config.get("k", args.k),
            bridge_manager=self.bridge_manager,
            bridge_configs=self.bridge_configs,
            bw_args=args.bw,
            ext_args=args.ext,
            topo_png_path=str(topo_png),
            topo_seed=args.seed,
            topo_layout=args.topo_layout,
            fleet_cefnetd_timeout=getattr(args, "cefnetd_timeout", None) or 10,
            fleet_readiness_policy="raise",
            fib_strategy=routing_config.get("strategy", "dijkstra"),
            fib_uri_publishers=self.uri_publishers or None,
        )
        result = setup_scenario(net, spec)
        self.daemon_fleet = result.daemon_fleet
        self.cache_node_set = result.cache_node_set
        self._fib_routes = result.fib_routes

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
            self.results_sink.subscribe(self.dashboard.record_operation)
            info(f"[webui] dashboard: http://0.0.0.0:{webui_port}/\n")
            # Pre-populate initial host state before Monitor starts polling
            webui_runner = MininetCommandRunner(net)
            for idx in range(args.hosts):
                output = webui_runner.run(
                    f"h{idx}", ["cefstatus", "-d", f"./h{idx}"]
                ).stdout
                self.dashboard.record_monitor(
                    {
                        "elapsed_sec": 0.0,
                        "type": "cefstatus",
                        "host": idx,
                        "output": output,
                    }
                )
            for idx in sorted(self.cache_node_set):
                output = run_csmgrstatus(net, idx, host="127.0.0.1")
                self.dashboard.record_monitor(
                    {
                        "elapsed_sec": 0.0,
                        "type": "csmgrstatus",
                        "host": idx,
                        "output": output,
                    }
                )

    def _build_cache_strategy(self):
        """Choose the CacheStrategy that matches ``args.cache_config.strategy``."""
        args = self.args
        cache_config = getattr(args, "cache_config", None) or None
        strategy_name = (cache_config or {}).get("strategy", "k_centers")
        if strategy_name == "random":
            return RandomCSModeStrategy(seed=args.seed)
        return KCentersStrategy(
            cache_config=cache_config,
            cache_count=args.cache_count,
            down_count=args.down_count,
            exclude_publishers=True,
            cache_default_rct_ms=getattr(args, "cache_default_rct_ms", None),
        )

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
        """Create the warmup-only ContentOperationRunner.

        Batch event paths are constructed by run_event_batch; warmup stays
        runner-only because it submits cache-prefetch gets directly.
        """
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
            sink=self.results_sink,
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
                sink=self.results_sink,
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
                sink=self.results_sink,
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
            put_uris = {ev["uri"] for ev in events_config if ev.get("type") == "put"}
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
                {"host": h, "uri": u} for u in sorted(put_uris) for h in warmup_hosts
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
                {"type": "cefstatus", "hosts": "all"},
                {"type": "csmgrstatus", "hosts": "cache"},
            ]
            monitoring_config.setdefault("interval", 5)
        if monitoring_config.get("targets"):
            # Interactive CLI runs start the monitor in background mode so it
            # keeps collecting (WebUI/flapping observability) without leaking
            # output to the terminal or contending with the CLI host shells.
            use_cli = not getattr(args, "no_cli", False)
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
                background=use_cli,
                command_timeout=monitoring_config.get("command_timeout", 10),
            )
            self.monitor.start()

    def _run_normal_experiment(self, net, events_config, origin, use_cli):
        """Run interactive or non-autotest execution with all events together."""
        self._start_failure_manager(net, use_cli)
        result = run_event_batch(
            net,
            EventBatchSpec(
                events=events_config,
                run_dir=self.run_dir,
                mesh_links=self.topo.mesh_links,
                sink=self.results_sink,
                flap_state=self.flap_state,
                seed_label=self.seed_label,
                uri_publishers=self.uri_publishers,
                startup_grace=float(
                    getattr(self.args, "pubsub_sub_startup_grace", 1.0)
                ),
                phase="event",
                start_time=origin,
                wait_timeout=None,
            ),
        )
        self.content_runner = result.content_runner
        self.event_scheduler = result.event_scheduler

    def _run_autotest_experiment(self, net, events_config, origin, use_cli):
        """Run seed, warmup, failure and evaluation phases in order."""
        put_events = [ev for ev in events_config if ev.get("type") == "put"]
        eval_events = [ev for ev in events_config if ev.get("type") != "put"]

        if any(ev.get("repeat") for ev in put_events):
            raise ValueError("autotest does not support repeat on put events")

        if put_events:
            run_event_batch(
                net,
                EventBatchSpec(
                    events=put_events,
                    run_dir=self.run_dir,
                    mesh_links=self.topo.mesh_links,
                    sink=self.results_sink,
                    flap_state=self.flap_state,
                    seed_label=self.seed_label,
                    uri_publishers=self.uri_publishers,
                    startup_grace=float(
                        getattr(self.args, "pubsub_sub_startup_grace", 1.0)
                    ),
                    phase="event",
                    start_time=origin,
                    wait_timeout=300,
                    deadline_policy="raise",
                    scheduler_label="seed event scheduling",
                    runner_label="seed content operations",
                ),
            )

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
        result = run_event_batch(
            net,
            EventBatchSpec(
                events=eval_events,
                run_dir=self.run_dir,
                mesh_links=self.topo.mesh_links,
                sink=self.results_sink,
                flap_state=self.flap_state,
                seed_label=self.seed_label,
                uri_publishers=self.uri_publishers,
                startup_grace=float(
                    getattr(self.args, "pubsub_sub_startup_grace", 1.0)
                ),
                phase="eval",
                start_time=origin,
                wait_timeout=None,
            ),
        )
        self.content_runner = result.content_runner
        self.event_scheduler = result.event_scheduler

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

    def should_run_cli(self):
        """Skip the interactive CLI in autotest mode (--no-cli)."""
        return not getattr(self.args, "no_cli", False)

    def before_cli(self, net):
        """Switch monitoring to background and restore real stdout for the CLI.

        The monitor stays running through the CLI but in background mode (quiet
        + popen) so it neither prints to the terminal nor contends with the CLI
        host shells. Idempotent: the monitor is already constructed in
        background mode here.
        """
        if self.monitor is not None:
            self.monitor.enter_background()
        if self.log_context:
            sys.stdout = self.log_context["original_stdout"]
            sys.stderr = self.log_context["original_stderr"]

    def after_cli(self, net):
        """Restore tee'd stdout/stderr after the CLI returns."""
        if self.log_context:
            sys.stdout = self.log_context["tee_stdout"]
            sys.stderr = self.log_context["tee_stderr"]

    def shutdown_runtime_resources(self):
        """Stop monitor/webui/scheduler/content runner before teardown.

        Each stage is attempted independently. BaseException (not just
        Exception) is caught so that SystemExit, KeyboardInterrupt, etc. during
        shutdown do not abort cleanup.
        """
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

        return cleanup_failures

    def write_results(self):
        """Write autotest results JSON after all operational cleanup."""
        if self.results_path is None:
            return []
        try:
            self.results_sink.write_json(self.results_path)
        except BaseException as exc:
            return [("results_write", exc)]
        return []

    def teardown(self, net):
        """Stop daemons and clean up bridges via the teardown seam."""
        spec = TeardownSpec(
            host_count=self.args.hosts,
            csmgrd_host_ids=self.cache_node_set,
            fleet_run_dir=self.run_dir,
            daemon_fleet=self.daemon_fleet,
            fleet_cefnetd_timeout=getattr(self.args, "cefnetd_timeout", None) or 10,
            fleet_readiness_policy="raise",
            bridge_manager=self.bridge_manager,
            cleanup_external_bridges=True,
        )
        result = teardown_scenario(net, spec)
        if result.failures:
            _propagate_failures(None, result.failures)


def run_disaster_scenario(args, run_dir=None, log_context=None, debug_config=None):
    """Convenience function to run disaster scenario."""
    scenario = DisasterScenario(args, run_dir, log_context, debug_config)
    scenario.execute()
