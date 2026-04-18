"""External network connection scenario with mesh topology.

Provides run_connect() for mesh topology with external bridge support,
plus shared utilities (Tee, parse_int_list, periodic_host_flap, run_host_command)
used by both this module and scenarios/disaster.py.
"""

import argparse
import json
import random
import shlex
import sys
import threading
import time
from pathlib import Path

from mininet.clean import cleanup as mn_cleanup
from mininet.cli import CLI
from mininet.link import Intf, TCLink
from mininet.log import info, setLogLevel
from mininet.net import Mininet

from ..core.addressing import AddressingScheme, DEFAULT_NETWORK_CIDR
from ..core.tee import Tee  # noqa: F401 (re-export for backward compat)
from ..core.config.auto_gen import generate_operations
from ..core.config.loader import load_config, merge_cli_and_config, validate_config
from ..core.flap_state import FlapState
from ..core.graph import select_k_centers
from ..core.paths import resolve_run_dir, resolve_run_path

from .bandwidth import parse_bw_args, set_link_bandwidth
from .bridge import (
    BridgeManager,
    parse_bridge_args,
    parse_ext_args,
    setup_bridges,
)
from .cefore import (
    run_cefgetfile,
    run_cefstatus_all,
    start_cefnetd,
    start_csmgrd,
    stop_cefnetd,
    stop_csmgrd,
    wait_for_cefnetd,
)
from .links import pick_publish_link, set_node_links_state
from .net_config import apply_fib, apply_fib_for_uris, apply_ip_addr
from .template import apply_cache_node_settings, cleanup_node_dirs, ensure_node_dirs
from .topo import MeshTopo
from .viz import build_host_graph, print_mesh_links, render_topology_png



def parse_int_list(value):
    """Parse integer list from string or list input.

    Args:
        value: Comma-separated string or list of integers/strings.

    Returns:
        List of integers.
    """
    if value is None or value == "":
        return []
    items = []
    if isinstance(value, (list, tuple, set)):
        for item in value:
            if item is None or item == "":
                continue
            if isinstance(item, str):
                parts = [part for part in item.split(",") if part.strip() != ""]
                items.extend(parts)
            else:
                items.append(item)
    elif isinstance(value, str):
        items = [part for part in value.split(",") if part.strip() != ""]
    else:
        items = [value]
    try:
        return [int(item) for item in items]
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"expected list of ints or comma-separated string, got {value!r}"
        ) from exc


def periodic_host_flap(
    net, host_num, interval, down_time, rng, exclude, state, down_count, stagger,
    quiet=False,
):
    """Start periodic host flapping in background thread.

    Args:
        net: Mininet network instance.
        host_num: Total number of hosts.
        interval: Seconds between down events.
        down_time: Seconds to keep hosts down.
        rng: Random number generator (None for round-robin).
        exclude: Set of host IDs to exclude from flapping.
        state: FlapState instance or dict to track current down hosts.
        down_count: Number of hosts to down per cycle.
        stagger: Seconds between individual host downs.
        quiet: If True, suppress flap log messages.

    Returns:
        threading.Event to stop flapping.
    """
    host_ids = [idx for idx in range(host_num) if idx not in exclude]
    if not host_ids:
        info("no hosts available for flapping\n")
        return threading.Event()
    stop_event = threading.Event()

    use_flap_state = hasattr(state, "update") and hasattr(state, "snapshot")

    def worker():
        position = 0
        active_down = set()

        def update_state(last_down=None):
            if use_flap_state:
                state.update(active_down, last_down)
            else:
                state["down_hosts"] = sorted(active_down)
                if last_down is not None:
                    state["last_down_host"] = last_down

        def schedule_up(host_idx):
            def do_up():
                if stop_event.is_set():
                    return
                host_name = f"h{host_idx}"
                if not quiet:
                    info(f"\n[flap] up {host_name}\n")
                try:
                    set_node_links_state(net, host_name, "up")
                except (AssertionError, OSError) as exc:
                    if not quiet:
                        info(f"\n[flap] failed to up {host_name}: {exc}\n")
                active_down.discard(host_idx)
                update_state()

            timer = threading.Timer(down_time, do_up)
            timer.daemon = True
            timer.start()

        while not stop_event.is_set():
            available = [idx for idx in host_ids if idx not in active_down]
            if not available:
                stop_event.wait(interval)
                continue
            count = min(down_count, len(available))
            if rng is not None:
                chosen = rng.sample(available, count)
            else:
                chosen = [
                    available[(position + offset) % len(available)]
                    for offset in range(count)
                ]
                position += count

            for offset, host_idx in enumerate(chosen):
                if stop_event.wait(stagger if offset > 0 else 0):
                    return
                host_name = f"h{host_idx}"
                active_down.add(host_idx)
                update_state(last_down=host_idx)
                if not quiet:
                    info(f"\n[flap] down {host_name}\n")
                try:
                    set_node_links_state(net, host_name, "down")
                except (AssertionError, OSError) as exc:
                    if not quiet:
                        info(f"\n[flap] failed to down {host_name}: {exc}\n")
                schedule_up(host_idx)

            stop_event.wait(interval)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return stop_event


def run_host_command(net, host_idx, command):
    """Run command on host and wait for completion.

    Args:
        net: Mininet network instance.
        host_idx: Host index.
        command: Shell command string.

    Returns:
        Exit code.
    """
    proc = net.hosts[host_idx].popen(command, shell=True)
    return proc.wait()


def attach_external_interface_intf(net, host_name, intf_name, ip=None, mtu=None):
    """Attach external interface directly to a host (Intf-based).

    Args:
        net: Mininet network instance.
        host_name: Host name to attach interface to.
        intf_name: External interface name.
        ip: Optional IP address to assign.
        mtu: Optional MTU to set.
    """
    host = net.get(host_name)
    Intf(intf_name, node=host)
    if mtu:
        host.cmd(f"ifconfig {shlex.quote(intf_name)} mtu {mtu}")
    if ip:
        host.cmd(f"ifconfig {shlex.quote(intf_name)} {shlex.quote(ip)}")
    info(f"attached {intf_name} to {host_name}\n")


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

    ops_put = args.puts or []
    auto_config = getattr(args, "auto", None)
    if auto_config and not ops_put:
        ops_put, _ = generate_operations(auto_config, args.hosts, args.seed, run_dir)

    publisher_ids = set(op["host"] for op in ops_put) if ops_put else None

    generated_node_dirs = ensure_node_dirs(args.hosts, rng or random.Random(), publisher_ids)

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
    apply_cache_node_settings(args.hosts, cache_node_set, None, publishers=publisher_ids)

    for idx in sorted(cache_node_set):
        start_csmgrd(net, idx)

    for idx in range(args.hosts):
        start_cefnetd(net, idx)

    for idx in range(args.hosts):
        if not wait_for_cefnetd(net, idx):
            info(f"WARNING: h{idx} cefnetd not ready\n")

    ops_get = args.gets or []

    if auto_config and not ops_get:
        _, ops_get = generate_operations(auto_config, args.hosts, args.seed, run_dir)

    if not ops_put:
        publisher = args.hosts - 1
        publish_link = pick_publish_link(topo.mesh_links, publisher)
        publish_uri = f"ccnx:/test/example{publisher + 1}/test.py"
        seed_label = "none" if args.seed is None else str(args.seed)
        down_host_label = "none"
        log_name = (
            f"cefputfile_{args.hosts}_{args.switches}_{seed_label}_"
            f"{args.down_interval}_{args.down_duration}_{down_host_label}.log"
        )
        ops_put = [
            {
                "host": publisher,
                "uri": publish_uri,
                "file": "./sample-putfile",
                "log": log_name,
            }
        ]

    uri_publishers = {}
    for op in ops_put:
        uri_publishers[op["uri"]] = op["host"]

    if uri_publishers:
        apply_fib_for_uris(net, topo.mesh_links, args.k, uri_publishers, scheme=scheme)
    else:
        apply_fib(net, topo.mesh_links, args.k, scheme=scheme)

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
        attach_external_interface_intf(net, host_name, intf_name, ip, mtu)

    for op in ops_put:
        host = op["host"]
        uri = op["uri"]
        infile = op.get("file", "./sample-putfile")
        log_path = str(
            resolve_run_path(run_dir, op.get("log"), f"cefputfile_h{host}.log")
        )
        command = (
            f"cefputfile {shlex.quote(uri)} -f {shlex.quote(infile)} -t 3000 -e 3000 -d ./h{host} > {shlex.quote(log_path)}"
        )
        print(f"h{host}", "command:", command)
        run_host_command(net, host, command)
        time.sleep(1)

    use_cli = not getattr(args, "no_cli", False)
    stop_event = None

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
    parser.add_argument("--get-interval", type=int, default=10)
    parser.add_argument("--config", type=str, default="")
    parser.add_argument("--topo-png", type=str, default=None)
    parser.add_argument("--script-log", type=str, default=None)
    parser.add_argument("--no-script-log", action="store_true")
    parser.add_argument("--topo-layout", type=str, default="spring")
    parser.add_argument("--puts", type=str, default="")
    parser.add_argument("--gets", type=str, default="")
    parser.add_argument("--num", type=int, default=None)
    parser.add_argument("--output-dir", type=str, default="logs")
    parser.add_argument("--timestamp", action="store_true")
    parser.add_argument("--no-cli", action="store_true")
    args = parser.parse_args()

    config_data = load_config(args.config)
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
        "get_interval": args.get_interval,
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
