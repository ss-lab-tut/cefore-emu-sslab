"""Disaster topology scenario with periodic host failure simulation."""

import json
import random
import shlex
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import info

from ..core.addressing import AddressingScheme, DEFAULT_NETWORK_CIDR
from ..core.config.auto_gen import generate_operations
from ..core.config.priority_resolver import PriorityConfigManager
from ..core.flap_state import FlapState
from ..core.graph import select_k_centers
from ..core.paths import resolve_run_path

from ..runtime.bandwidth import parse_bw_args, set_link_bandwidth
from ..runtime.bridge import (
    BridgeManager,
    attach_external_interface,
    cleanup_external_bridges,
    parse_bridge_args,
    parse_ext_args,
    setup_bridges,
)
from ..runtime.content_ops import ContentOperationRunner
from ..runtime.result_detect import (
    detect_get_success,
    detect_sub_success,
    timestamp_utc,
    wait_pubsub_process,
)
from ..runtime.monitoring import Monitor
from ..runtime.scheduler import EventScheduler
from ..runtime.cleanup import cleanup_all
from ..runtime.cefore import (
    run_cefgetfile,
    run_cefpubfile,
    run_cefputfile,
    run_cefstatus_all,
    start_cefsubfile,
    start_cefnetd,
    start_csmgrd,
    stop_cefnetd,
    stop_csmgrd,
    wait_for_cefnetd,
)
from ..runtime.external_net import parse_int_list
from ..runtime.failure_manager import FlexibleFailureManager, periodic_host_flap
from ..runtime.net_config import apply_fib, apply_ip_addr
from ..runtime.template import (
    apply_cache_node_settings,
    cleanup_node_dirs,
    ensure_node_dirs,
)
from ..runtime.debug import archive_node_dirs
from ..runtime.topo import MeshTopo
from ..runtime.viz import build_host_graph, print_mesh_links, render_topology_png

from .base import BaseScenario


def _artifact_path(run_dir: Path, raw_path, default_name):
    """Resolve output file path under run_dir."""
    return resolve_run_path(run_dir, raw_path, default_name)


def _resolve_pubsub_wait_seconds(
    sub_opts: dict, uri: str, pub_lifetime_by_uri: dict
) -> float:
    """Resolve how long to wait for a cefsubfile process.

    Timing units follow the Cefore CLI: ``cefpubfile -l`` uses seconds.
    """
    if sub_opts.get("wait") is not None:
        return float(sub_opts["wait"])
    if uri in pub_lifetime_by_uri:
        return float(pub_lifetime_by_uri[uri]) + 5.0
    return 30.0


def _resolve_pubsub_publish_deadline_seconds(
    uri: str, pub_opts: dict, sub_wait_by_uri: dict
) -> float:
    """Resolve how long to wait before terminating cefpubfile."""
    lifetime_sec = float(pub_opts.get("lifetime", 3))
    resolved_sub_wait = float(sub_wait_by_uri.get(uri, 30.0))
    return max(resolved_sub_wait, lifetime_sec) + 5.0


def _resolve_results_path(args, run_dir: Path):
    """Resolve results.json path from args."""
    raw = getattr(args, "results_json", None)
    if not raw:
        return None
    return _artifact_path(run_dir, raw, "results.json")


def _warn_if_no_content_operations(ops_put, ops_get) -> bool:
    """Print a warning when no content operations are configured."""
    if ops_put or ops_get:
        return False
    print("[warning] no content operations configured; skipping publish/retrieve phase")
    return True


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
        self.bridge_manager = BridgeManager()
        self.stop_event = None
        self.started_csmgrd_hosts = set()
        self.cache_node_set = set()
        self.flap_state = FlapState()
        self.uri_publishers = {}
        self.ops_put = []
        self.ops_get = []
        self.publisher_ids = set()
        self.topo = None
        self.seed_label = "none" if args.seed is None else str(args.seed)
        self.stop_thread = None
        self.priority_manager = None
        self.event_scheduler = None
        self.content_runner = None
        self.monitor = None
        self.generated_node_dirs = []

        priority_uris = getattr(args, "priority_uris", None)
        if isinstance(priority_uris, dict) and priority_uris:
            self.priority_manager = PriorityConfigManager(priority_uris)

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

        self._prepare_ops()

    def _prepare_ops(self):
        """Prepare put/get operations from args and auto config."""
        args = self.args
        self.ops_put = args.puts or []
        auto_config = getattr(args, "auto", None)
        if auto_config:
            auto_puts, _ = generate_operations(
                auto_config, args.hosts, args.seed, self.run_dir
            )
            self.ops_put = self.ops_put + auto_puts
        if self.priority_manager:
            self.ops_put = [
                self.priority_manager.apply_to_put(op) for op in self.ops_put
            ]

        self.publisher_ids = set(op["host"] for op in self.ops_put)
        for op in self.ops_put:
            self.uri_publishers[op["uri"]] = op["host"]

        for ev in getattr(args, "events", None) or []:
            if ev.get("type") in ("put", "pubsub_pub"):
                self.publisher_ids.add(ev["host"])
                self.uri_publishers[ev["uri"]] = ev["host"]

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
        apply_fib(
            net,
            self.topo.mesh_links,
            routing_k,
            strategy=routing_strategy,
            uri_publishers=self.uri_publishers or None,
            scheme=self.scheme,
        )

        run_cefstatus_all(net, args.hosts)
        print_mesh_links(self.topo.mesh_links)

    def _run_put_ops(self, net, ops=None):
        """Execute normal (cefputfile) put operations."""
        for op in ops if ops is not None else self.ops_put:
            host = int(op["host"])
            uri = op["uri"]
            infile = op.get("file", "./sample-putfile")
            log_path = _artifact_path(
                self.run_dir, op.get("log"), f"cefputfile_h{host}.log"
            )
            exit_code = run_cefputfile(
                net,
                host,
                uri,
                file_path=infile,
                rate=op.get("rate"),
                block_size=op.get("block_size"),
                expiry=op.get("expiry", 3000),
                cache_time=op.get("cache_time", 3000),
                valid_algo=op.get("valid_algo"),
                port_num=op.get("port_num"),
                log_name=str(log_path),
            )
            if exit_code != 0:
                info(f"[ERROR] cefputfile failed on h{host} (exit_code={exit_code})\n")
                sys.exit(1)
            time.sleep(1)

    def _record_get_result(
        self, op, phase, exit_code, artifact_ref, log_path, down_hosts
    ):
        """Append a single get/sub result to self.results.

        artifact_ref is the output file for normal gets and the output directory
        for pubsub gets (cefsubfile -f takes a directory).
        """
        uri = op["uri"]
        consumer = int(op["host"])
        if op.get("mode") == "pubsub":
            verdict = detect_sub_success(exit_code, artifact_ref, log_path)
            out_file = verdict.get("artifact_path") or str(artifact_ref)
        else:
            verdict = detect_get_success(log_path, artifact_ref, exit_code)
            out_file = str(artifact_ref)
        publisher_host = op.get("publisher_host")
        if publisher_host is None:
            publisher_host = getattr(self.args, "publisher_host", None)
        if publisher_host is None:
            publisher_host = self.uri_publishers.get(uri)
        publisher_down = (
            publisher_host in down_hosts if publisher_host is not None else False
        )
        self._append_result(
            {
                "ts": timestamp_utc(),
                "phase": phase,
                "host": consumer,
                "uri": uri,
                "out_file": out_file,
                "log_file": str(log_path),
                "exit_code": exit_code,
                "down_hosts": down_hosts,
                "publisher_host": publisher_host,
                "publisher_down": publisher_down,
                "success": verdict["success"],
                "has_completed_log": verdict["has_completed_log"],
                "has_output_file": verdict["has_output_file"],
            }
        )

    def _append_result(self, record):
        """Thread-safe append to results list."""
        with self._results_lock:
            self.results.append(record)

    def _run_get_ops(self, net, ops, phase, per_get_interval, cycle_idx=0):
        """Execute normal (non-pubsub) get operations with flap state tracking."""
        for idx, op in enumerate(ops):
            consumer = int(op["host"])
            uri = op["uri"]
            outfile_path = _artifact_path(
                self.run_dir,
                op.get("file"),
                f"{phase}_recvfile_h{consumer}_idx{idx}",
            )
            down_hosts = self.flap_state.snapshot()
            if op.get("log"):
                log_path = _artifact_path(
                    self.run_dir,
                    op["log"],
                    f"{phase}_cefgetfile_h{consumer}_idx{idx}.log",
                )
            else:
                down_label = (
                    "none"
                    if not down_hosts
                    else ",".join(str(h) for h in sorted(down_hosts))
                )
                log_path = _artifact_path(
                    self.run_dir,
                    None,
                    (
                        f"cefgetfile_seed{self.seed_label}_downhosts{down_label}_"
                        f"phase{phase}_cycle{cycle_idx}_idx{idx}_h{consumer}.log"
                    ),
                )

            exit_code = run_cefgetfile(
                net,
                consumer,
                uri,
                str(outfile_path),
                owner_only=op.get("owner_only", False),
                chunk=op.get("chunk"),
                pipeline=op.get("pipeline"),
                valid_algo=op.get("valid_algo"),
                port_num=op.get("port_num"),
                sg=op.get("sg"),
                log_name=str(log_path),
            )

            self._record_get_result(
                op, phase, exit_code, outfile_path, log_path, down_hosts
            )

            if idx < len(ops) - 1 and per_get_interval > 0:
                time.sleep(per_get_interval)

    def _start_pubsub_get_ops(
        self, net, pubsub_gets, phase, cycle_idx, pubsub_puts=None
    ):
        """Start cefsubfile processes in background.

        Returns a list of pending dicts with proc, paths, context, and absolute
        deadline (time.monotonic()) needed for result recording after waiting,
        plus the resolved per-URI subscriber waits for publisher deadlines.
        """
        # Build URI → pub_opts map for per-subscriber deadline calculation.
        pub_lifetime_by_uri: dict = {}
        for put_op in pubsub_puts or []:
            pub_opts = put_op.get("pub_opts", {}) or {}
            lifetime = pub_opts.get("lifetime")
            if lifetime is not None:
                pub_lifetime_by_uri[put_op["uri"]] = float(lifetime)

        pending = []
        sub_wait_by_uri: dict = {}
        for idx, op in enumerate(pubsub_gets):
            consumer = int(op["host"])
            uri = op["uri"]
            output_dir = _artifact_path(
                self.run_dir,
                op.get("file"),
                f"{phase}_recvdir_h{consumer}_cycle{cycle_idx}_idx{idx}",
            )
            output_dir.mkdir(parents=True, exist_ok=True)
            down_hosts = self.flap_state.snapshot()
            if op.get("log"):
                log_path = _artifact_path(
                    self.run_dir,
                    op["log"],
                    f"{phase}_cefsubfile_h{consumer}_idx{idx}.log",
                )
            else:
                down_label = (
                    "none"
                    if not down_hosts
                    else ",".join(str(h) for h in sorted(down_hosts))
                )
                log_path = _artifact_path(
                    self.run_dir,
                    None,
                    (
                        f"cefsubfile_seed{self.seed_label}_downhosts{down_label}_"
                        f"phase{phase}_cycle{cycle_idx}_idx{idx}_h{consumer}.log"
                    ),
                )
            sub_opts = op.get("sub_opts", {}) or {}
            wait_sec = _resolve_pubsub_wait_seconds(sub_opts, uri, pub_lifetime_by_uri)
            sub_wait_by_uri[uri] = max(sub_wait_by_uri.get(uri, 0.0), wait_sec)
            started_at = time.monotonic()
            proc = start_cefsubfile(
                net,
                consumer,
                uri,
                output_path=str(output_dir),
                pipeline=sub_opts.get("pipeline"),
                ri_valid_algo=sub_opts.get("ri_valid_algo"),
                td_valid_algo=sub_opts.get("td_valid_algo"),
                port_num=sub_opts.get("port_num"),
                log_name=str(log_path),
            )
            deadline = started_at + wait_sec
            info(
                f"[pubsub] started cefsubfile h{consumer} uri={uri} "
                f"pid={proc.pid} output_dir={output_dir} wait={wait_sec:.1f}s "
                f"deadline={deadline:.1f}\n"
            )
            pending.append(
                {
                    "op": op,
                    "proc": proc,
                    "output_dir": output_dir,
                    "log_path": log_path,
                    "down_hosts": down_hosts,
                    "phase": phase,
                    "deadline": deadline,
                }
            )
        return pending, sub_wait_by_uri

    def _run_pubsub_put_ops(
        self, net, pubsub_puts, phase="eval", cycle_idx=0, sub_wait_by_uri=None
    ):
        """Execute pubsub put operations (cefpubfile), parallelising across hosts.

        Publishers on different hosts run concurrently so that all subscriber PIT
        entries are still fresh when each publisher starts.  Publishers on the same
        host run sequentially to avoid cefnetd contention.
        """
        sub_wait_by_uri = sub_wait_by_uri or {}

        def _run_one(idx, op):
            host = int(op["host"])
            uri = op["uri"]
            infile = op.get("file", "./sample-putfile")
            if op.get("log"):
                log_path = _artifact_path(self.run_dir, op["log"], None)
            else:
                down_hosts = self.flap_state.snapshot()
                down_label = (
                    "none"
                    if not down_hosts
                    else ",".join(str(h) for h in sorted(down_hosts))
                )
                log_path = _artifact_path(
                    self.run_dir,
                    None,
                    (
                        f"cefpubfile_seed{self.seed_label}_downhosts{down_label}_"
                        f"phase{phase}_cycle{cycle_idx}_idx{idx}_h{host}.log"
                    ),
                )
            pub_opts = op.get("pub_opts", {}) or {}
            proc = run_cefpubfile(
                net,
                host,
                uri,
                file_path=infile,
                rate=pub_opts.get("rate"),
                block_size=pub_opts.get("block_size"),
                expiry=pub_opts.get("expiry"),
                cache_time=pub_opts.get("cache_time"),
                lifetime=pub_opts.get("lifetime"),
                retry_limit=pub_opts.get("retry_limit"),
                target=pub_opts.get("target"),
                ti_valid_algo=pub_opts.get("ti_valid_algo"),
                rd_valid_algo=pub_opts.get("rd_valid_algo"),
                port_num=pub_opts.get("port_num"),
                log_name=str(log_path),
            )
            pub_deadline = _resolve_pubsub_publish_deadline_seconds(
                uri, pub_opts, sub_wait_by_uri
            )
            info(
                f"[pubsub] waiting for cefpubfile h{host} uri={uri} deadline={pub_deadline:.1f}s\n"
            )
            try:
                pub_exit = proc.wait(timeout=pub_deadline)
                info(f"[pubsub] cefpubfile h{host} uri={uri} exit_code={pub_exit}\n")
            except subprocess.TimeoutExpired:
                info(
                    f"[WARN] cefpubfile on h{host} (uri={uri}) exceeded {pub_deadline:.1f}s; terminating\n"
                )
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

        # Group ops by host; preserve insertion order within each group.
        host_groups: dict[int, list] = {}
        for idx, op in enumerate(pubsub_puts):
            host_groups.setdefault(int(op["host"]), []).append((idx, op))

        def _run_host_group(ops):
            for idx, op in ops:
                _run_one(idx, op)
                time.sleep(1)

        if len(host_groups) <= 1:
            for ops in host_groups.values():
                _run_host_group(ops)
        else:
            with ThreadPoolExecutor(max_workers=len(host_groups)) as exe:
                futures = [
                    exe.submit(_run_host_group, ops) for ops in host_groups.values()
                ]
                for f in as_completed(futures):
                    f.result()

    def _wait_pubsub_get_ops(self, pending):
        """Wait for cefsubfile processes and record results."""
        for item in pending:
            sub_host = int(item["op"]["host"])
            uri = item["op"]["uri"]
            exit_code = wait_pubsub_process(item["proc"], item["deadline"])
            if exit_code is None:
                info(
                    f"[WARN] cefsubfile on h{sub_host} (uri={uri}) timed out; terminating\n"
                )
            else:
                info(
                    f"[pubsub] cefsubfile h{sub_host} uri={uri} exit_code={exit_code}\n"
                )
            artifacts = (
                sorted(item["output_dir"].glob("RNP0x*.out"))
                if item["output_dir"].is_dir()
                else []
            )
            non_empty = [p for p in artifacts if p.stat().st_size > 0]
            info(
                f"[pubsub] h{sub_host} uri={uri} artifacts={len(artifacts)} "
                f"non_empty={len(non_empty)} "
                f"first={non_empty[0] if non_empty else None}\n"
            )
            self._record_get_result(
                op=item["op"],
                phase=item["phase"],
                exit_code=exit_code,
                artifact_ref=item["output_dir"],
                log_path=item["log_path"],
                down_hosts=item["down_hosts"],
            )

    def _run_eval_cycle(
        self, net, normal_gets, pubsub_gets, pubsub_puts, phase, cycle_idx
    ):
        """Execute one evaluation cycle.

        For pubsub: subscriber starts first, then publisher, then subscriber
        results are collected.  Normal gets follow in sequence.
        """
        if pubsub_gets:
            pending, sub_wait_by_uri = self._start_pubsub_get_ops(
                net, pubsub_gets, phase, cycle_idx, pubsub_puts
            )
            grace = float(getattr(self.args, "pubsub_sub_startup_grace", 1.0))
            if grace > 0:
                info(f"[pubsub] waiting {grace:.1f}s for subscribers to become ready\n")
                time.sleep(grace)
            self._run_pubsub_put_ops(
                net,
                pubsub_puts,
                phase=phase,
                cycle_idx=cycle_idx,
                sub_wait_by_uri=sub_wait_by_uri,
            )
            self._wait_pubsub_get_ops(pending)
        if normal_gets:
            self._run_get_ops(
                net, normal_gets, phase, self.args.get_interval, cycle_idx=cycle_idx
            )

    def _prepare_get_ops(self):
        """Prepare and return get operations list."""
        args = self.args
        ops_get = args.gets or []
        if self.priority_manager:
            ops_get = [self.priority_manager.apply_to_get(op) for op in ops_get]
        auto_config = getattr(args, "auto", None)
        if auto_config:
            _, auto_gets = generate_operations(
                auto_config, args.hosts, args.seed, self.run_dir
            )
            if self.priority_manager:
                auto_gets = [self.priority_manager.apply_to_get(op) for op in auto_gets]
            ops_get = ops_get + auto_gets
        normal_get_uris = {op["uri"] for op in ops_get if op.get("mode") != "pubsub"}
        pubsub_get_uris = {op["uri"] for op in ops_get if op.get("mode") == "pubsub"}
        for put_op in self.ops_put:
            mode = put_op.get("mode", "putget")
            if mode == "pubsub" and put_op["uri"] not in pubsub_get_uris:
                print(
                    f"[warning] pubsub put has no matching subscriber: "
                    f"host={put_op['host']} uri={put_op['uri']}"
                )
            elif mode != "pubsub" and put_op["uri"] not in normal_get_uris:
                print(
                    f"[warning] no matching get for normal put: "
                    f"host={put_op['host']} uri={put_op['uri']}"
                )
        return ops_get

    def run_experiment(self, net):
        """Run the disaster experiment: puts, flapping, gets."""
        args = self.args

        self.ops_get = self._prepare_get_ops()

        normal_puts = [op for op in self.ops_put if op.get("mode") != "pubsub"]
        pubsub_puts = [op for op in self.ops_put if op.get("mode") == "pubsub"]
        normal_gets = [op for op in self.ops_get if op.get("mode") != "pubsub"]
        pubsub_gets = [op for op in self.ops_get if op.get("mode") == "pubsub"]

        _warn_if_no_content_operations(self.ops_put, self.ops_get)
        self._run_put_ops(net, normal_puts)

        # Start host flapping
        use_cli = not getattr(args, "no_cli", False)
        scenario_config = getattr(args, "failure_scenarios", None)
        if scenario_config:
            failure_manager = FlexibleFailureManager(
                scenario_config=scenario_config,
                host_count=args.hosts,
                rng=self.rng,
                publisher_ids=self.publisher_ids,
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
            )

        # Start event scheduler (with content runner for put/get/pubsub events)
        events_config = getattr(args, "events", None) or []
        content_event_types = {"put", "get", "pubsub_pub", "pubsub_sub"}
        has_content_events = any(
            e.get("type") in content_event_types for e in events_config
        )
        if has_content_events:
            startup_grace = float(getattr(args, "pubsub_sub_startup_grace", 1.0))
            self.content_runner = ContentOperationRunner(
                net,
                run_dir=self.run_dir,
                result_callback=self._append_result,
                flap_state=self.flap_state,
                seed_label=self.seed_label,
                uri_publishers=self.uri_publishers,
                startup_grace=startup_grace,
            )
            self.content_runner.start()
        if events_config:
            self.event_scheduler = EventScheduler(
                net,
                events_config,
                mesh_links=self.topo.mesh_links,
                run_dir=self.run_dir,
                content_runner=self.content_runner,
            )
            self.event_scheduler.start()

        # Start monitoring
        monitoring_config = getattr(args, "monitoring", None) or {}
        if monitoring_config and monitoring_config.get("targets"):
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
            )
            self.monitor.start()

        # Evaluation phase
        duration = max(0, int(getattr(args, "duration", 0)))
        if use_cli or duration == 0:
            self._run_eval_cycle(
                net, normal_gets, pubsub_gets, pubsub_puts, "eval", cycle_idx=0
            )
        else:
            deadline = time.time() + duration
            cycle_idx = 0
            while time.time() < deadline:
                self._run_eval_cycle(
                    net,
                    normal_gets,
                    pubsub_gets,
                    pubsub_puts,
                    "eval",
                    cycle_idx=cycle_idx,
                )
                cycle_idx += 1
                if time.time() >= deadline:
                    break

    def execute(self):
        """Override BaseScenario.execute() for CLI and autotest control."""
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
            if self.monitor is not None:
                self.monitor.stop()
            if self.event_scheduler is not None:
                self.event_scheduler.stop()
            if self.content_runner is not None:
                self.content_runner.wait_all(timeout=60)
                self.content_runner.stop()
            if self.stop_event is not None:
                self.stop_event.set()

            if net is not None:
                self.collect_debug_pre_teardown(net)
                try:
                    self.teardown(net)
                except Exception as exc:
                    info(f"Error during teardown: {exc}\n")

            self.collect_debug_post_teardown()
            if net is not None:
                cleanup_all(net, self.generated_node_dirs)
            else:
                cleanup_node_dirs(self.generated_node_dirs)

            if self.results_path is not None:
                self.results_path.write_text(
                    json.dumps(self.results, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

    def teardown(self, net):
        """Stop daemons and clean up bridges."""
        for idx in range(self.args.hosts):
            stop_cefnetd(net, idx)
        for idx in sorted(self.started_csmgrd_hosts):
            stop_csmgrd(net, idx)
        self.bridge_manager.cleanup()
        cleanup_external_bridges()


def run_disaster_scenario(args, run_dir=None, log_context=None, debug_config=None):
    """Convenience function to run disaster scenario."""
    scenario = DisasterScenario(args, run_dir, log_context, debug_config)
    scenario.execute()
