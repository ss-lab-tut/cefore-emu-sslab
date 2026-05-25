"""External network connection scenario with mesh topology.

Provides run_connect() for mesh topology with external bridge support.
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

from mininet.clean import cleanup as mn_cleanup
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import info, setLogLevel
from mininet.net import Mininet

from ..core.addressing import AddressingScheme, DEFAULT_NETWORK_CIDR
from ..core.tee import Tee  # noqa: F401 (re-export for backward compat)
from ..core.config.loader import (
    load_config,
    merge_cli_and_config,
    validate_config,
    warn_ignored_legacy_content_keys,
)
from ..core.graph import select_k_centers
from ..core.flap_state import FlapState
from ..core.paths import resolve_run_dir, resolve_run_path

from .bandwidth import parse_bw_args, set_link_bandwidth
from .bridge import (
    BridgeManager,
    attach_external_interface,
    parse_bridge_args,
    parse_ext_args,
    setup_bridges,
)
from .cefore import (
    run_cefstatus_all,
    start_cefnetd,
    start_csmgrd,
    stop_cefnetd,
    stop_csmgrd,
    wait_for_cefnetd,
)
from .content_ops import ContentOperationRunner
from .net_config import apply_fib, apply_ip_addr
from .scheduler import EventScheduler
from .template import apply_cache_node_settings, cleanup_node_dirs, ensure_node_dirs
from .topo import MeshTopo
from .viz import build_host_graph, print_mesh_links, render_topology_png
def _publication_metadata(events):
    """Return publication events and their URI-to-publisher mapping."""
    publications = [
        event for event in events
        if event.get("type") in ("put", "pubsub_pub")
    ]
    publishers = {event["uri"]: event["host"] for event in publications}
    return publications, publishers


def run_connect(args, run_dir: Path = None, log_context=None):
    """Run mesh topology with external bridge support.

    Args:
        args: Parsed command-line arguments.
        run_dir: Output directory for logs and artifacts.
        log_context: Dict with original_stdout/stderr and tee_stdout/stderr for CLI.
    """
    if run_dir is None:
        run_dir = Path("logs")
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed) if args.seed is not None else None

    addr_cfg = getattr(args, "addressing", {}) or {}
    scheme = AddressingScheme(addr_cfg.get("network_cidr", DEFAULT_NETWORK_CIDR))
    events = getattr(args, "events", None) or []
    publication_events, uri_publishers = _publication_metadata(events)
    publisher_ids = set(uri_publishers.values())
    ignored_retrievals = [
        event for event in events if event.get("type") in ("get", "pubsub_sub")
    ]
    if ignored_retrievals:
        info(
            "[warning] ceforeemu-connect does not execute get/pubsub_sub events; "
            "use disaster or interactive commands for retrieval\n"
        )

    generated_node_dirs = ensure_node_dirs(
        args.hosts, rng or random.Random(), publisher_ids
    )

    topo = MeshTopo(
        hosts=args.hosts,
        swhich_num=args.switches,
        rng=rng,
        node_per_switch=args.node_per_switch,
        host_degree_min=args.host_degree_min,
        host_degree_max=args.host_degree_max,
        switch_use_all=args.switch_use_all,
    )
    net = Mininet(topo=topo, link=TCLink, waitConnected=True)
    net.start()

    apply_ip_addr(net, topo.mesh_links, scheme=scheme)

    bridge_manager = BridgeManager()
    bridge_configs = getattr(args, "bridges", None) or []
    if not bridge_configs:
        bridge_configs = parse_bridge_args(getattr(args, "bridge", None))
    if bridge_configs:
        setup_bridges(net, bridge_manager, bridge_configs, args.hosts, topo.mesh_links, scheme=scheme)

    for idx in range(args.hosts):
        info(net.hosts[idx].cmd("ifconfig"))

    host_graph, _ = build_host_graph(topo.mesh_links)
    cache_count = args.cache_count if args.cache_count > 0 else args.down_count + 1
    cache_nodes = select_k_centers(host_graph, cache_count)
    if not cache_nodes and args.hosts > 0:
        cache_nodes = [args.hosts - 1]
    cache_node_set = set(cache_nodes)
    apply_cache_node_settings(
        args.hosts, cache_node_set, None, publishers=publisher_ids
    )

    for idx in sorted(cache_node_set):
        start_csmgrd(net, idx)

    for idx in range(args.hosts):
        start_cefnetd(net, idx)

    for idx in range(args.hosts):
        if not wait_for_cefnetd(net, idx):
            info(f"WARNING: h{idx} cefnetd not ready\n")

    apply_fib(
        net,
        topo.mesh_links,
        args.k,
        uri_publishers=uri_publishers or None,
        scheme=scheme,
    )

    run_cefstatus_all(net, args.hosts)
    print_mesh_links(topo.mesh_links)

    topo_png_path = str(
        resolve_run_path(
            run_dir,
            args.topo_png,
            f"ex{args.hosts}_seed{'none' if args.seed is None else args.seed}.png",
        )
    )
    render_topology_png(
        topo.mesh_links,
        topo_png_path,
        seed=args.seed,
        layout=args.topo_layout,
    )
    if cache_nodes:
        info("cache nodes: " + ", ".join(f"h{idx}" for idx in cache_nodes) + "\n")
    time.sleep(1)

    for node_a, node_b, bandwidth in parse_bw_args(args.bw):
        set_link_bandwidth(net, node_a, node_b, bandwidth)

    for host_name, intf_name, ip, mtu in parse_ext_args(args.ext):
        attach_external_interface(net, host_name, intf_name, ip, mtu)

    use_cli = not getattr(args, "no_cli", False)
    stop_event = None
    if publication_events:
        runner = ContentOperationRunner(
            net,
            run_dir=run_dir,
            result_callback=lambda _record: None,
            flap_state=FlapState(),
            seed_label="none" if args.seed is None else str(args.seed),
            uri_publishers=uri_publishers,
            phase="seed",
        )
        scheduler = EventScheduler(
            net,
            publication_events,
            mesh_links=topo.mesh_links,
            run_dir=run_dir,
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
            scheduler.stop()
            runner.stop()

    if use_cli:
        if log_context:
            sys.stdout = log_context["original_stdout"]
            sys.stderr = log_context["original_stderr"]
        CLI(net)
        if log_context:
            sys.stdout = log_context["tee_stdout"]
            sys.stderr = log_context["tee_stderr"]

    if stop_event is not None:
        stop_event.set()

    for idx in range(args.hosts):
        stop_cefnetd(net, idx)

    for idx in sorted(cache_node_set):
        stop_csmgrd(net, idx)

    bridge_manager.cleanup()

    net.stop()
    mn_cleanup()
    cleanup_node_dirs(generated_node_dirs)


def main():
    """CLI entry point for external network connection topology."""
    parser = argparse.ArgumentParser(
        description="Cefore mesh topology with external bridge"
    )
    parser.add_argument("--hosts", type=int, default=5)
    parser.add_argument("--switches", type=int, default=10)
    parser.add_argument("--node-per-switch", type=int, default=2)
    parser.add_argument("--host-degree-min", type=int, default=1)
    parser.add_argument("--host-degree-max", type=int, default=2)
    parser.add_argument("--switch-use-all", action="store_true")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--k", type=int, default=2)
    parser.add_argument("--down-interval", type=int, default=30)
    parser.add_argument("--down-duration", type=int, default=10)
    parser.add_argument("--down-exclude", type=str, default="")
    parser.add_argument("--down-count", type=int, default=5)
    parser.add_argument("--down-stagger", type=int, default=2)
    parser.add_argument("--cache-count", type=int, default=0)
    parser.add_argument("--bw", action="append", default=[])
    parser.add_argument("--ext", action="append", default=[])
    parser.add_argument("--bridge", action="append", default=[])
    parser.add_argument("--config", type=str, default="")
    parser.add_argument("--topo-png", type=str, default=None)
    parser.add_argument("--script-log", type=str, default=None)
    parser.add_argument("--no-script-log", action="store_true")
    parser.add_argument("--topo-layout", type=str, default="spring")
    parser.add_argument("--num", type=int, default=None)
    parser.add_argument("--output-dir", type=str, default="logs")
    parser.add_argument("--timestamp", action="store_true")
    parser.add_argument("--no-cli", action="store_true")
    args = parser.parse_args()

    config_data = load_config(args.config)
    warn_ignored_legacy_content_keys(config_data)
    errors = validate_config(config_data)
    if errors:
        for error in errors:
            print(f"config error: {error}", file=sys.stderr)
        sys.exit(1)
    merge_cli_and_config(args, config_data)

    run_dir = resolve_run_dir(args)
    run_dir = run_dir.resolve()

    seed_label = "none" if args.seed is None else str(args.seed)
    if args.topo_png is None:
        args.topo_png = f"ex{args.hosts}_seed{seed_label}.png"

    meta_data = {
        "num": getattr(args, "num", None),
        "hosts": args.hosts,
        "switches": args.switches,
        "seed": args.seed,
        "k": args.k,
        "down_interval": args.down_interval,
        "down_duration": args.down_duration,
        "down_count": args.down_count,
        "down_stagger": args.down_stagger,
        "down_exclude": args.down_exclude,
        "cache_count": args.cache_count,
        "output_dir": str(run_dir),
    }
    meta_path = resolve_run_path(run_dir, "meta.json", "meta.json")
    meta_path.write_text(json.dumps(meta_data, indent=2), encoding="utf-8")

    log_fp = None
    original_stdout = None
    original_stderr = None
    if not args.no_script_log:
        log_name = args.script_log if args.script_log else "script.log"
        log_path = resolve_run_path(run_dir, log_name, "script.log")
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
        run_connect(args, run_dir, log_context=log_context)
    finally:
        if log_fp:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            log_fp.close()


if __name__ == "__main__":
    main()
