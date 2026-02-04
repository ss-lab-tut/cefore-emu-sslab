#!/usr/bin/env python

"""
Periodic host failure emulator based on mesh topology.
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

from config.auto_generator import generate_operations
from config.loader import load_config, merge_cli_and_config, validate_config

from .cef_daemons import (
    run_cefgetfile,
    run_cefstatus_all,
    start_cefnetd,
    start_csmgrd,
    stop_cefnetd,
    stop_csmgrd,
    wait_for_cefnetd,
)
from .external_bridge import BridgeManager, parse_bridge_args, setup_bridges
from .flap_state import FlapState
from .graph_algos import select_k_centers
from .links import pick_publish_link, set_node_links_state
from .mesh_topo import MeshTopo
from .net_config import set_fib, set_fib_for_uris, set_ip_addr
from .paths import resolve_run_dir
from .templates import cleanup_node_dirs, ensure_node_dirs
from .viz import build_host_graph, print_mesh_links, render_topology_png


class Tee:
    """Write to multiple streams simultaneously."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            s.write(data)
            s.flush()
        return len(data)

    def flush(self):
        for s in self.streams:
            s.flush()

    def fileno(self):
        return self.streams[0].fileno()

    def isatty(self):
        return self.streams[0].isatty()

    @property
    def encoding(self):
        return self.streams[0].encoding


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

    Returns:
        threading.Event to stop flapping.
    """
    host_ids = [idx for idx in range(host_num) if idx not in exclude]
    if not host_ids:
        info("no hosts available for flapping\n")
        return threading.Event()
    stop_event = threading.Event()

    # Check if state is a FlapState object or legacy dict
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


def set_link_bandwidth(net, node_a, node_b, bandwidth):
    """Set bandwidth on link between two nodes.

    Args:
        net: Mininet network instance.
        node_a: First node name.
        node_b: Second node name.
        bandwidth: Bandwidth in Mbps.
    """
    for link in net.linksBetween(net.get(node_a), net.get(node_b)):
        link.intf1.config(bw=bandwidth)
        link.intf2.config(bw=bandwidth)
        info(f"set bw {bandwidth} Mbps between {node_a} and {node_b}\n")


def attach_external_interface(net, host_name, intf_name, ip=None, mtu=None):
    """Attach external interface to a host.

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
        host.cmd(f"ifconfig {intf_name} mtu {mtu}")
    if ip:
        host.cmd(f"ifconfig {intf_name} {ip}")
    info(f"attached {intf_name} to {host_name}\n")


def parse_bw_args(values):
    """Parse bandwidth arguments.

    Args:
        values: List of "nodeA,nodeB,mbps" strings.

    Returns:
        List of (node_a, node_b, bandwidth) tuples.
    """
    entries = []
    for value in values or []:
        parts = [part.strip() for part in value.split(",")]
        if len(parts) != 3:
            raise ValueError("bw format is nodeA,nodeB,mbps")
        entries.append((parts[0], parts[1], float(parts[2])))
    return entries


def parse_ext_args(values):
    """Parse external interface arguments.

    Args:
        values: List of "host,ifname[,ip][,mtu]" strings.

    Returns:
        List of (host_name, intf_name, ip, mtu) tuples.
    """
    entries = []
    for value in values or []:
        parts = [part.strip() for part in value.split(",")]
        if len(parts) not in (2, 3, 4):
            raise ValueError("ext format is host,ifname[,ip][,mtu]")
        host_name = parts[0]
        intf_name = parts[1]
        ip = parts[2] if len(parts) >= 3 and parts[2] else None
        mtu = int(parts[3]) if len(parts) == 4 and parts[3] else None
        entries.append((host_name, intf_name, ip, mtu))
    return entries


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


def run_connect(args, run_dir: Path = None, log_context=None):
    """Run disaster topology simulation.

    Args:
        args: Parsed command-line arguments.
        run_dir: Output directory for logs and artifacts.
        log_context: Dict with original_stdout/stderr and tee_stdout/stderr for CLI.
    """
    if run_dir is None:
        run_dir = Path(".")

    rng = random.Random(args.seed) if args.seed is not None else None

    # ops_put から publishers を抽出（auto 設定も展開）
    ops_put = args.puts or []
    auto_config = getattr(args, "auto", None)
    if auto_config and not ops_put:
        ops_put, _ = generate_operations(auto_config, args.hosts, args.seed, run_dir)

    publisher_ids = set(op["host"] for op in ops_put) if ops_put else None

    ensure_node_dirs(args.hosts, rng or random.Random(), publisher_ids)

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

    set_ip_addr(net, topo.mesh_links)

    # Set up root namespace bridges for cross-VM communication
    bridge_manager = BridgeManager()
    bridge_configs = getattr(args, "bridges", None) or []
    if not bridge_configs:
        bridge_configs = parse_bridge_args(getattr(args, "bridge", None))
    if bridge_configs:
        setup_bridges(net, bridge_manager, bridge_configs, args.hosts)

    for idx in range(args.hosts):
        info(net.hosts[idx].cmd("ifconfig"))

    for idx in range(args.hosts):
        if idx % 2 == 1:
            start_csmgrd(net, idx)

    for idx in range(args.hosts):
        start_cefnetd(net, idx)

    for idx in range(args.hosts):
        wait_for_cefnetd(net, idx)

    # ops_put は ensure_node_dirs の前に既に抽出済み
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
                "log": str(run_dir / log_name),
            }
        ]

    uri_publishers = {}
    for op in ops_put:
        uri_publishers[op["uri"]] = op["host"]

    if uri_publishers:
        set_fib_for_uris(net, topo.mesh_links, args.k, uri_publishers)
    else:
        set_fib(net, topo.mesh_links, args.k)

    run_cefstatus_all(net, args.hosts)
    print_mesh_links(topo.mesh_links)

    # Resolve topology PNG path with run_dir
    topo_png_path = args.topo_png
    if topo_png_path:
        topo_png_path = str(run_dir / Path(topo_png_path).name)
    render_topology_png(
        topo.mesh_links,
        topo_png_path,
        seed=args.seed,
        layout=args.topo_layout,
    )
    host_graph, _ = build_host_graph(topo.mesh_links)
    cache_count = args.cache_count if args.cache_count > 0 else args.down_count + 1
    cache_nodes = select_k_centers(host_graph, cache_count)
    if cache_nodes:
        info("cache nodes: " + ", ".join(f"h{idx}" for idx in cache_nodes) + "\n")
    time.sleep(1)

    for node_a, node_b, bandwidth in parse_bw_args(args.bw):
        set_link_bandwidth(net, node_a, node_b, bandwidth)

    for host_name, intf_name, ip, mtu in parse_ext_args(args.ext):
        attach_external_interface(net, host_name, intf_name, ip, mtu)

    for op in ops_put:
        host = op["host"]
        uri = op["uri"]
        infile = op.get("file", "./sample-putfile")
        log_name = op.get("log", f"cefputfile_h{host}.log")
        # If log_name doesn't already contain run_dir, prepend it
        if not Path(log_name).is_absolute() and not str(log_name).startswith(
            str(run_dir)
        ):
            log_path = str(run_dir / log_name)
        else:
            log_path = log_name
        command = (
            f"cefputfile {uri} -f {shlex.quote(infile)} -t 3000 -e 3000 -d ./h{host} > {log_path}"
        )
        print(f"h{host}", "command:", command)
        run_host_command(net, host, command)
        time.sleep(1)

    use_cli = not getattr(args, "no_cli", False)

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

    for idx in range(args.hosts):
        if idx % 2 == 1:
            stop_csmgrd(net, idx)

    # Cleanup bridge routes before stopping network
    bridge_manager.cleanup()

    net.stop()
    mn_cleanup()
    cleanup_node_dirs()


def main():
    """CLI entry point for disaster topology."""
    parser = argparse.ArgumentParser(
        description="Cefore mesh topology with periodic host down"
    )
    parser.add_argument("--hosts", type=int, default=5, help="number of hosts")
    parser.add_argument(
        "--switches",
        type=int,
        default=10,
        help="maximum number of switches to create (0 = unlimited)",
    )
    parser.add_argument(
        "--node-per-switch",
        type=int,
        default=2,
        help="max hosts per switch (0=unlimited, 2=one switch per link)",
    )
    parser.add_argument(
        "--host-degree-min",
        type=int,
        default=1,
        help="minimum number of switches per host (>=1)",
    )
    parser.add_argument(
        "--host-degree-max",
        type=int,
        default=2,
        help="maximum number of switches per host",
    )
    parser.add_argument(
        "--switch-use-all",
        action="store_true",
        help="create switches up to --switches and distribute extra links evenly (may exceed host_degree_max)",
    )
    parser.add_argument("--seed", type=int, default=None, help="random seed")
    parser.add_argument("--k", type=int, default=2, help="k shortest paths")
    parser.add_argument(
        "--down-interval",
        type=int,
        default=30,
        help="seconds between down events (0 to disable)",
    )
    parser.add_argument(
        "--down-duration",
        type=int,
        default=10,
        help="seconds to keep host down",
    )
    parser.add_argument(
        "--down-exclude",
        type=str,
        default="",
        help="comma-separated host ids to exclude from flapping (config can use list)",
    )
    parser.add_argument(
        "--down-count",
        type=int,
        default=5,
        help="number of hosts to keep down per cycle",
    )
    parser.add_argument(
        "--down-stagger",
        type=int,
        default=2,
        help="seconds to stagger down events within a cycle",
    )
    parser.add_argument(
        "--cache-count",
        type=int,
        default=0,
        help="number of cache nodes (0 = down-count + 1)",
    )
    parser.add_argument(
        "--bw",
        action="append",
        default=[],
        help="set bandwidth: nodeA,nodeB,mbps (repeatable)",
    )
    parser.add_argument(
        "--ext",
        action="append",
        default=[],
        help="attach external intf: host,ifname[,ip][,mtu] (repeatable)",
    )
    parser.add_argument(
        "--bridge",
        action="append",
        default=[],
        help="root ns bridge: switch,root_ip,local_routes[,ext_routes,gateway] (repeatable)",
    )
    parser.add_argument(
        "--get-interval",
        type=int,
        default=10,
        help="seconds between cefgetfile runs",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="",
        help="JSON config file to override parameters and define put/get ops",
    )
    parser.add_argument(
        "--topo-png",
        type=str,
        default=None,
        help="write topology PNG to this path (default: ex{hosts}_seed{seed}.png)",
    )
    parser.add_argument(
        "--script-log",
        type=str,
        default=None,
        help="log script output to file (default: ex{hosts}_seed{seed}.log)",
    )
    parser.add_argument(
        "--no-script-log",
        action="store_true",
        help="disable script log output",
    )
    parser.add_argument(
        "--topo-layout",
        type=str,
        default="spring",
        help="topology layout: spring, kamada_kawai, or circular",
    )
    parser.add_argument(
        "--puts",
        type=str,
        default="",
        help="JSON list of put ops (host,uri,file,log)",
    )
    parser.add_argument(
        "--gets",
        type=str,
        default="",
        help="JSON list of get ops (host,uri,file,log)",
    )
    parser.add_argument(
        "--num",
        type=int,
        default=None,
        help="experiment number (enables log directory output)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="logs",
        help="base output directory (default: logs)",
    )
    parser.add_argument(
        "--timestamp",
        action="store_true",
        help="add timestamp to output directory name",
    )
    parser.add_argument(
        "--legacy",
        action="store_true",
        dest="legacy_layout",
        help="use legacy layout (output to current directory)",
    )
    parser.add_argument(
        "--no-cli",
        action="store_true",
        help="skip interactive CLI (flap output visible on stdout)",
    )
    args = parser.parse_args()

    config_data = load_config(args.config)
    errors = validate_config(config_data)
    if errors:
        for error in errors:
            print(f"config error: {error}", file=sys.stderr)
        sys.exit(1)
    merge_cli_and_config(args, config_data)

    # Resolve output directory
    run_dir = resolve_run_dir(args)

    # Set dynamic default for topo_png
    seed_label = "none" if args.seed is None else str(args.seed)
    if args.topo_png is None:
        args.topo_png = f"ex{args.hosts}_seed{seed_label}.png"

    # Write meta.json with experiment configuration
    if run_dir != Path("."):
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
        }
        meta_path = run_dir / "meta.json"
        meta_path.write_text(json.dumps(meta_data, indent=2), encoding="utf-8")

    # Set up script logging
    log_fp = None
    original_stdout = None
    original_stderr = None
    if not args.no_script_log:
        log_name = args.script_log if args.script_log else "script.log"
        log_path = run_dir / log_name
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
