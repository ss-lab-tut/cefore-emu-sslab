#!/usr/bin/env python

"""
Periodic host failure emulator based on mesh topology.
Flexible variant with priority configuration and advanced failure scenarios.
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

from mininet.link import TCLink
from mininet.log import info, setLogLevel
from mininet.net import Mininet

from config.flexible_generator import generate_operations_with_priority
from config.loader import load_config, merge_cli_and_config, validate_config
from config.priority_resolver import PriorityConfigManager

from .external_bridge import BridgeManager, parse_bridge_args
from .failure_manager import FlexibleFailureManager
from .flap_state import FlapState
from .mesh_topo import MeshTopo
from .paths import Tee, resolve_run_dir
from .simulation import (
    artifact_path,
    build_warmup_ops,
    cleanup_all,
    health_check_publishers,
    program_fib,
    resolve_results_path,
    run_cli_or_duration,
    run_get_ops,
    run_pub_phase,
    run_put_phase,
    setup_cache_nodes,
    setup_network,
    start_daemons,
    wait_pub_procs,
    wait_pubsub_procs,
)
from .templates import ensure_node_dirs


def run_disaster_topology(args, run_dir: Path = None, log_context=None):
    """Run disaster topology simulation (flexible variant).

    Args:
        args: Parsed command-line arguments.
        run_dir: Output directory for logs and artifacts.
        log_context: Dict with original_stdout/stderr and tee_stdout/stderr for CLI.
    """
    if run_dir is None:
        run_dir = Path("logs")
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed) if args.seed is not None else random.Random()
    results = []
    net = None
    bridge_manager = BridgeManager()
    stop_event = None
    stop_thread = None
    started_csmgrd_hosts = set()

    bridge_configs = getattr(args, "bridges", None) or []
    if not bridge_configs:
        bridge_configs = parse_bridge_args(getattr(args, "bridge", None))

    # Flexible-specific: priority management
    config_data = load_config(getattr(args, "config", ""))
    priority_uris = config_data.get("priority_uris")
    priority_manager = PriorityConfigManager(priority_uris) if priority_uris else None

    results_path = resolve_results_path(args, run_dir)
    autotest_mode = bool(getattr(args, "no_cli", False) and results_path is not None)
    if autotest_mode and (args.ext or bridge_configs):
        sys.exit("autotest mode forbids ext/bridge configuration")

    # ops_put から publishers を抽出（auto 設定も展開）
    ops_put = args.puts or []
    if priority_manager:
        ops_put = [priority_manager.apply_to_put(op) for op in ops_put]
    auto_config = getattr(args, "auto", None)
    if auto_config and not ops_put:
        ops_put, _ = generate_operations_with_priority(
            auto_config, args.hosts, args.seed, run_dir, priority_manager
        )

    if not ops_put:
        publisher = args.hosts - 1
        publish_uri = f"ccnx:/test/example{publisher + 1}/test.py"
        ops_put = [
            {
                "host": publisher,
                "uri": publish_uri,
                "file": "./sample-putfile",
                "mode": "pubsub",
                "log": "cefputfile_default.log",
            }
        ]

    for op in ops_put:
        op["host"] = int(op["host"])

    publisher_ids = {int(op["host"]) for op in ops_put}
    pubsub_publisher_ids = {
        int(op["host"]) for op in ops_put if op.get("mode") == "pubsub"
    }
    hot_uris = list(dict.fromkeys(getattr(args, "hot_uris", []) or [op["uri"] for op in ops_put]))

    ensure_node_dirs(args.hosts, rng, publisher_ids)

    topo = MeshTopo(
        hosts=args.hosts,
        swhich_num=args.switches,
        rng=rng,
        node_per_switch=args.node_per_switch,
        host_degree_min=args.host_degree_min,
        host_degree_max=args.host_degree_max,
        switch_use_all=args.switch_use_all,
    )
    flap_state = FlapState()
    seed_label = "none" if args.seed is None else str(args.seed)

    try:
        net = Mininet(topo=topo, link=TCLink, waitConnected=True)
        net.start()

        setup_network(net, topo, args, bridge_manager, bridge_configs, seed_label, run_dir)
        cache_node_set, cache_nodes = setup_cache_nodes(
            args, topo, publisher_ids, pubsub_publisher_ids,
        )
        start_daemons(net, args, cache_node_set, started_csmgrd_hosts)

        # Build uri_publishers map
        uri_publishers = {}
        for op in ops_put:
            uri_publishers[op["uri"]] = op["host"]

        # Generate ops_get BEFORE FIB (needed for bidirectional FIB)
        ops_get = args.gets or []
        if priority_manager:
            ops_get = [priority_manager.apply_to_get(op) for op in ops_get]
        if auto_config and not ops_get:
            _, ops_get = generate_operations_with_priority(
                auto_config, args.hosts, args.seed, run_dir, priority_manager
            )
        if not ops_get:
            base_uri = ops_put[0]["uri"]
            base_mode = ops_put[0].get("mode")
            for idx in range(1, 6):
                candidates = [h for h in range(args.hosts) if h != ops_put[0]["host"]]
                consumer = rng.choice(candidates)
                get_op = {
                    "host": consumer,
                    "uri": base_uri,
                    "file": f"recvfile_at_h{consumer}",
                }
                if base_mode:
                    get_op["mode"] = base_mode
                ops_get.append(get_op)

        # Extract pubsub subscriber info for bidirectional FIB
        uri_subscribers = {}
        for op in ops_get:
            if op.get("mode") == "pubsub":
                uri_subscribers.setdefault(op["uri"], set()).add(int(op["host"]))

        # FIB programming (bidirectional for pubsub)
        program_fib(net, topo, args, uri_publishers,
                     uri_subscribers=uri_subscribers if uri_subscribers else None)
        health_check_publishers(net, publisher_ids)

        # Split operations
        ops_get_pubsub = [op for op in ops_get if op.get("mode") == "pubsub"]
        ops_get_putget = [op for op in ops_get if op.get("mode") != "pubsub"]
        info(f"\n=== Get operations: {len(ops_get_pubsub)} pubsub, {len(ops_get_putget)} putget ===\n")

        ops_put_putget = [op for op in ops_put if op.get("mode") != "pubsub"]
        ops_put_pubsub = [op for op in ops_put if op.get("mode") == "pubsub"]
        info(f"\n=== Put operations: {len(ops_put_pubsub)} pubsub, {len(ops_put_putget)} putget ===\n")

        # Filter hot_uris for warmup (flexible-specific)
        if priority_manager:
            hot_uris = [uri for uri in hot_uris if priority_manager.should_prefetch(uri)]

        # Phase 1: putget puts (SYNC)
        run_put_phase(net, run_dir, ops_put_putget, seed_label)

        # Warmup (after puts so content exists in caches)
        warmup_ops = build_warmup_ops(args, run_dir, hot_uris, cache_nodes)
        if warmup_ops:
            run_get_ops(
                net, run_dir, warmup_ops, "warmup",
                getattr(args, "warmup_get_interval", 0),
                seed_label, flap_state, uri_publishers, args, results,
                cycle_idx=0,
            )

        # Phase 2: pubsub subscribers (ASYNC)
        pubsub_sub_procs = []
        if ops_get_pubsub:
            info(f"\n=== Phase 2: Starting {len(ops_get_pubsub)} pubsub subscribers ===\n")
            pubsub_sub_procs = run_get_ops(
                net, run_dir, ops_get_pubsub, "eval", args.get_interval,
                seed_label, flap_state, uri_publishers, args, results,
                cycle_idx=0, return_procs=True,
            )
            info("Waiting 3 seconds for subscriber FIB registration...\n")
            time.sleep(3)

        # Phase 3: pubsub publishers (ASYNC)
        pubsub_pub_procs = run_pub_phase(net, run_dir, ops_put_pubsub, seed_label)

        # Phase 4: putget consumers (SYNC)
        if ops_get_putget:
            info(f"\n=== Phase 4: Running {len(ops_get_putget)} putget consumers ===\n")
            run_get_ops(
                net, run_dir, ops_get_putget, "eval", args.get_interval,
                seed_label, flap_state, uri_publishers, args, results,
                cycle_idx=0,
            )

        # Phase 5: Wait for pubsub processes
        if pubsub_sub_procs:
            wait_pubsub_procs(pubsub_sub_procs, uri_publishers, args, results)
        wait_pub_procs(pubsub_pub_procs)

        # Failure phase startup (flexible uses FlexibleFailureManager)
        use_cli = not getattr(args, "no_cli", False)
        scenario_config = getattr(args, "failure_scenarios", None)
        if scenario_config:
            should_start_failure = True
            if scenario_config.get("strategy", "simple") == "simple":
                simple = scenario_config.get("simple", {}) or {}
                if simple.get("interval", 0) <= 0 or simple.get("duration", 0) <= 0:
                    should_start_failure = False
            if should_start_failure:
                failure_manager = FlexibleFailureManager(
                    scenario_config=scenario_config,
                    host_count=args.hosts,
                    rng=rng,
                    publisher_ids=publisher_ids,
                )
                stop_event, stop_thread = failure_manager.start(net, flap_state, quiet=use_cli)

        # CLI or duration mode
        run_cli_or_duration(
            net, args, log_context, ops_get_putget, ops_put,
            ops_get_pubsub, run_dir, seed_label, flap_state,
            uri_publishers, results, args.get_interval,
        )

    finally:
        cleanup_all(
            net, args, started_csmgrd_hosts, bridge_manager,
            stop_event, results, results_path, stop_thread=stop_thread,
        )


def main():
    """CLI entry point for flexible disaster topology."""
    parser = argparse.ArgumentParser(
        description="Cefore mesh topology with periodic host down"
    )
    parser.add_argument("--hosts", type=int, default=5, help="number of hosts")
    parser.add_argument(
        "--switches", type=int, default=10,
        help="maximum number of switches to create (0 = unlimited)",
    )
    parser.add_argument(
        "--node-per-switch", type=int, default=2,
        help="max hosts per switch (0=unlimited, 2=one switch per link)",
    )
    parser.add_argument(
        "--host-degree-min", type=int, default=2,
        help="minimum number of switches per host (>=1)",
    )
    parser.add_argument(
        "--host-degree-max", type=int, default=2,
        help="maximum number of switches per host",
    )
    parser.add_argument(
        "--switch-use-all", action="store_true",
        help="create switches up to --switches and distribute extra links evenly",
    )
    parser.add_argument("--seed", type=int, default=None, help="random seed")
    parser.add_argument("--k", type=int, default=2, help="k shortest paths")
    parser.add_argument(
        "--cache-count", type=int, default=0,
        help="number of cache nodes (0 = down-count + 1)",
    )
    parser.add_argument(
        "--bw", action="append", default=[],
        help="set bandwidth: nodeA,nodeB,mbps (repeatable)",
    )
    parser.add_argument(
        "--ext", action="append", default=[],
        help="attach external intf: host,ifname[,ip][,mtu] (repeatable)",
    )
    parser.add_argument(
        "--bridge", action="append", default=[],
        help="root ns bridge: switch,root_ip,local_routes[,ext_routes,gateway] (repeatable)",
    )
    parser.add_argument(
        "--get-interval", type=int, default=10,
        help="seconds between cefgetfile runs",
    )
    parser.add_argument("--config", type=str, default="", help="JSON/YAML config file")
    parser.add_argument("--topo-png", type=str, default=None, help="topology PNG path")
    parser.add_argument("--script-log", type=str, default=None, help="script log path")
    parser.add_argument("--no-script-log", action="store_true", help="disable script log")
    parser.add_argument(
        "--topo-layout", type=str, default="spring",
        help="topology layout: spring, kamada_kawai, or circular",
    )
    parser.add_argument("--puts", type=str, default="", help="JSON list of put ops")
    parser.add_argument("--gets", type=str, default="", help="JSON list of get ops")
    parser.add_argument("--num", type=int, default=None, help="experiment number")
    parser.add_argument("--output-dir", type=str, default="logs", help="base output directory")
    parser.add_argument("--timestamp", action="store_true", help="add timestamp to dir name")
    parser.add_argument("--no-cli", action="store_true", help="skip interactive CLI")
    parser.add_argument("--duration", type=int, default=0, help="eval phase duration (sec)")
    parser.add_argument("--results-json", type=str, default="", help="results JSON path")
    parser.add_argument("--warmup-get-interval", type=int, default=0)
    parser.add_argument(
        "--warmup-only-cache-nodes", action="store_true", default=True,
        help="restrict warmup to cache nodes",
    )
    parser.add_argument(
        "--warmup-all-hosts", action="store_false", dest="warmup_only_cache_nodes",
    )
    parser.add_argument("--cache-default-rct-ms", type=int, default=None)
    parser.add_argument("--publisher-host", type=int, default=None)
    parser.add_argument("--hot-uris", type=str, default="")
    parser.add_argument("--warmup-gets", type=str, default="")
    args = parser.parse_args()

    config_data = load_config(args.config)
    errors = validate_config(config_data)
    if errors:
        for error in errors:
            print(f"config error: {error}", file=sys.stderr)
        sys.exit(1)
    merge_cli_and_config(args, config_data)

    if isinstance(args.hot_uris, str) and args.hot_uris:
        args.hot_uris = [u.strip() for u in args.hot_uris.split(",") if u.strip()]
    if isinstance(args.warmup_gets, str) and args.warmup_gets:
        args.warmup_gets = json.loads(args.warmup_gets)
    if args.warmup_gets in ("", None):
        args.warmup_gets = []

    run_dir = resolve_run_dir(args).resolve()

    seed_label = "none" if args.seed is None else str(args.seed)
    if args.topo_png is None:
        args.topo_png = f"ex{args.hosts}_seed{seed_label}.png"

    _fs = getattr(args, "failure_scenarios", None) or {}
    _simple = _fs.get("simple", {}) or {}
    meta_data = {
        "num": getattr(args, "num", None),
        "hosts": args.hosts,
        "switches": args.switches,
        "seed": args.seed,
        "k": args.k,
        "down_interval": _simple.get("interval", 0),
        "down_duration": _simple.get("duration", 0),
        "down_count": _simple.get("count", 0),
        "down_stagger": _simple.get("stagger", 0),
        "down_exclude": ",".join(str(x) for x in (_simple.get("exclude") or [])),
        "cache_count": args.cache_count,
        "cache_default_rct_ms": args.cache_default_rct_ms,
        "get_interval": args.get_interval,
        "warmup_get_interval": args.warmup_get_interval,
        "duration": args.duration,
        "output_dir": str(run_dir),
    }
    meta_path = artifact_path(run_dir, "meta.json", "meta.json")
    meta_path.write_text(json.dumps(meta_data, indent=2), encoding="utf-8")

    log_fp = None
    original_stdout = None
    original_stderr = None
    if not args.no_script_log:
        log_name = args.script_log if args.script_log else "script.log"
        log_path = artifact_path(run_dir, log_name, "script.log")
        log_fp = open(log_path, "w")
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        sys.stdout = Tee(original_stdout, log_fp)
        sys.stderr = Tee(original_stderr, log_fp)

    log_context = None
    if log_fp:
        log_context = {
            "original_stdout": original_stdout,
            "original_stderr": original_stderr,
            "tee_stdout": sys.stdout,
            "tee_stderr": sys.stderr,
        }

    try:
        setLogLevel("info")
        run_disaster_topology(args, run_dir, log_context=log_context)
    finally:
        if log_fp:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            log_fp.close()


if __name__ == "__main__":
    main()
