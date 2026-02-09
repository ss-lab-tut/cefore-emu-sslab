#!/usr/bin/env python

"""
Periodic host failure emulator based on mesh topology.
"""

import argparse
from datetime import datetime, timezone
import json
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

from mininet.clean import cleanup as mn_cleanup
from mininet.cli import CLI
from mininet.link import Intf, TCLink
from mininet.log import info, setLogLevel
from mininet.net import Mininet
from mininet.node import Node

from config.auto_generator import generate_operations
from config.loader import load_config, merge_cli_and_config, validate_config

from .cef_daemons import (
    run_cefgetfile,
    run_cefpubfile,
    run_cefputfile,
    run_cefsubfile,
    run_cefstatus_all,
    start_cefnetd,
    start_conpubd,
    start_csmgrd,
    stop_cefnetd,
    stop_conpubd,
    stop_csmgrd,
    wait_for_cefnetd,
)
from .external_bridge import BridgeManager, parse_bridge_args, setup_bridges
from .flap_state import FlapState
from .graph_algos import select_k_centers
from .links import pick_publish_link, set_node_links_state
from .mesh_topo import MeshTopo
from .net_config import set_fib, set_fib_for_uris, set_ip_addr
from .paths import resolve_run_dir, resolve_run_path
from .templates import (
    apply_cache_node_settings,
    apply_pubsub_node_settings,
    cleanup_node_dirs,
    ensure_node_dirs,
)
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
    net,
    host_num,
    interval,
    down_time,
    rng,
    exclude,
    state,
    down_count,
    stagger,
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


# Track created bridges for cleanup
_created_bridges = {}


def _run_root_cmd(cmd):
    """Run command in root namespace."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0 and result.stderr:
        info(f"[bridge] cmd failed: {cmd}\n  stderr: {result.stderr}\n")
    return result.returncode == 0


def attach_external_via_bridge(net, host_name, phy_intf, ip=None, mtu=None):
    """Attach host to external network via Linux bridge (does not hijack NIC).

    Creates a Linux bridge, enslaves the physical interface, and connects
    the Mininet host via a veth pair. Optionally runs DHCP to get an IP.

    Args:
        net: Mininet network instance.
        host_name: Host name to attach (e.g., "h0").
        phy_intf: Physical interface name on host machine (e.g., "eth0").
        ip: Optional static IP (CIDR format). If None, runs dhclient.
        mtu: Optional MTU to set on bridge and veth.
    """
    bridge_name = f"br-{host_name}"
    veth_root = f"veth-{host_name}-root"
    veth_host = f"veth-{host_name}"

    host = net.get(host_name)
    if host is None:
        info(f"[bridge] host {host_name} not found\n")
        return

    info(f"[bridge] creating bridge {bridge_name} for {host_name} via {phy_intf}\n")

    # 1. Create Linux bridge
    _run_root_cmd(f"ip link add {bridge_name} type bridge")
    _run_root_cmd(f"ip link set {bridge_name} up")

    # 2. Enslave physical interface to bridge (keep it in root namespace)
    _run_root_cmd(f"ip link set {phy_intf} up")
    _run_root_cmd(f"ip link set {phy_intf} master {bridge_name}")

    # 3. Create veth pair
    _run_root_cmd(f"ip link add {veth_root} type veth peer name {veth_host}")
    _run_root_cmd(f"ip link set {veth_root} master {bridge_name}")
    _run_root_cmd(f"ip link set {veth_root} up")
    _run_root_cmd(f"ip link set {veth_host} up")

    # 4. Move veth-host end into Mininet host's namespace
    # Get the PID of the Mininet host
    host_pid = host.pid
    _run_root_cmd(f"ip link set {veth_host} netns {host_pid}")

    # 5. Configure the interface inside Mininet host
    host.cmd(f"ip link set {veth_host} up")

    # 6. Apply MTU if specified
    if mtu:
        _run_root_cmd(f"ip link set {bridge_name} mtu {mtu}")
        _run_root_cmd(f"ip link set {veth_root} mtu {mtu}")
        host.cmd(f"ip link set {veth_host} mtu {mtu}")

    # 7. IP configuration
    if ip:
        # Static IP
        host.cmd(f"ip addr add {ip} dev {veth_host}")
        info(f"[bridge] {host_name}: static IP {ip} on {veth_host}\n")
    else:
        # DHCP - run dhclient in background
        info(f"[bridge] {host_name}: starting dhclient on {veth_host}\n")
        host.cmd(f"dhclient -v {veth_host} &")

    # Track for cleanup
    _created_bridges[host_name] = {
        "bridge": bridge_name,
        "veth_root": veth_root,
        "veth_host": veth_host,
        "phy_intf": phy_intf,
    }

    info(f"[bridge] attached {host_name} to {phy_intf} via bridge {bridge_name}\n")


def cleanup_external_bridges():
    """Clean up all created bridges and veth pairs."""
    for host_name, info_dict in list(_created_bridges.items()):
        bridge_name = info_dict["bridge"]
        veth_root = info_dict["veth_root"]
        phy_intf = info_dict["phy_intf"]

        info(f"[bridge] cleaning up {bridge_name}\n")

        # Release physical interface from bridge
        _run_root_cmd(f"ip link set {phy_intf} nomaster")

        # Delete veth pair (deleting one end removes both)
        _run_root_cmd(f"ip link del {veth_root} 2>/dev/null")

        # Delete bridge
        _run_root_cmd(f"ip link set {bridge_name} down")
        _run_root_cmd(f"ip link del {bridge_name}")

    _created_bridges.clear()


def attach_external_interface(net, host_name, intf_name, ip=None, mtu=None):
    """Attach external interface to a host via bridge (backward compatible).

    This function now uses the bridge approach instead of directly attaching
    the physical interface to avoid hijacking the NIC from the host machine.

    Args:
        net: Mininet network instance.
        host_name: Host name to attach interface to.
        intf_name: External interface name.
        ip: Optional IP address to assign. If None, uses DHCP.
        mtu: Optional MTU to set.
    """
    attach_external_via_bridge(net, host_name, intf_name, ip, mtu)


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


def _artifact_path(run_dir: Path, raw_path, default_name):
    """Resolve output file path under run_dir."""
    return resolve_run_path(run_dir, raw_path, default_name)


def _timestamp_utc():
    return datetime.now(timezone.utc).isoformat()


def _detect_get_success(log_path: Path, out_path: Path, exit_code: int) -> dict:
    """Evaluate cefgetfile success using exit code, log, and output file."""
    log_text = ""
    if log_path.exists():
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
    has_completed = "Completed to get all the chunks." in log_text
    has_out = out_path.exists() and out_path.stat().st_size > 0
    success = exit_code == 0 and has_completed and has_out
    return {
        "success": success,
        "has_completed_log": has_completed,
        "has_output_file": has_out,
    }


def _build_warmup_ops(args, run_dir: Path, hot_uris, cache_nodes):
    """Build warmup operations when not explicitly configured."""
    explicit = getattr(args, "warmup_gets", None) or []
    if explicit:
        return explicit

    if not hot_uris:
        return []

    warmup_nodes = list(cache_nodes) if getattr(args, "warmup_only_cache_nodes", True) else []
    if not warmup_nodes:
        warmup_nodes = [idx for idx in range(args.hosts)]

    warmup_ops = []
    for host_idx in warmup_nodes:
        for uri_idx, uri in enumerate(hot_uris):
            warmup_ops.append(
                {
                    "host": host_idx,
                    "uri": uri,
                    "file": str(run_dir / f"warmup_recv_h{host_idx}_u{uri_idx}"),
                }
            )
    return warmup_ops


def _resolve_results_path(args, run_dir: Path):
    raw = getattr(args, "results_json", None)
    if not raw:
        return None
    return _artifact_path(run_dir, raw, "results.json")


def run_disaster_topology(args, run_dir: Path = None, log_context=None):
    """Run disaster topology simulation.

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
    started_csmgrd_hosts = set()
    started_conpubd_hosts = set()

    bridge_configs = getattr(args, "bridges", None) or []
    if not bridge_configs:
        bridge_configs = parse_bridge_args(getattr(args, "bridge", None))

    results_path = _resolve_results_path(args, run_dir)
    autotest_mode = bool(getattr(args, "no_cli", False) and results_path is not None)
    if autotest_mode and (args.ext or bridge_configs):
        sys.exit("autotest mode forbids ext/bridge configuration")

    # ops_put から publishers を抽出（auto 設定も展開）
    ops_put = args.puts or []
    auto_config = getattr(args, "auto", None)
    if auto_config and not ops_put:
        ops_put, _ = generate_operations(auto_config, args.hosts, args.seed, run_dir)

    if not ops_put:
        publisher = args.hosts - 1
        publish_uri = f"ccnx:/test/example{publisher + 1}/test.py"
        ops_put = [
            {
                "host": publisher,
                "uri": publish_uri,
                "file": "./sample-putfile",
                "log": "cefputfile_default.log",
            }
        ]

    publisher_ids = set(op["host"] for op in ops_put)
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

    def run_get_ops(ops, phase, per_get_interval, cycle_idx=0):
        for idx, op in enumerate(ops):
            consumer = int(op["host"])
            uri = op["uri"]
            outfile_path = _artifact_path(
                run_dir,
                op.get("file"),
                f"{phase}_recvfile_h{consumer}_idx{idx}",
            )
            down_hosts = flap_state.snapshot()
            if op.get("log"):
                log_path = _artifact_path(
                    run_dir,
                    op["log"],
                    f"{phase}_cefgetfile_h{consumer}_idx{idx}.log",
                )
            else:
                down_label = "none" if not down_hosts else ",".join(
                    str(h) for h in sorted(down_hosts)
                )
                log_path = _artifact_path(
                    run_dir,
                    None,
                    (
                        f"cefgetfile_seed{seed_label}_downhosts{down_label}_"
                        f"phase{phase}_cycle{cycle_idx}_idx{idx}_h{consumer}.log"
                    ),
                )

            if op.get("mode") == "pubsub":
                sub_opts = op.get("sub_opts", {}) or {}
                run_cefsubfile(
                    net,
                    consumer,
                    uri,
                    output_path=str(outfile_path),
                    pipeline=sub_opts.get("pipeline"),
                    ri_valid_algo=sub_opts.get("ri_valid_algo"),
                    td_valid_algo=sub_opts.get("td_valid_algo"),
                    port_num=sub_opts.get("port_num"),
                    log_name=str(log_path),
                )
                exit_code = 0
            else:
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

            verdict = _detect_get_success(log_path, outfile_path, exit_code)
            publisher_host = op.get("publisher_host")
            if publisher_host is None:
                publisher_host = getattr(args, "publisher_host", None)
            if publisher_host is None:
                publisher_host = uri_publishers.get(uri)
            publisher_down = (
                publisher_host in down_hosts if publisher_host is not None else False
            )
            results.append(
                {
                    "ts": _timestamp_utc(),
                    "phase": phase,
                    "host": consumer,
                    "uri": uri,
                    "out_file": str(outfile_path),
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

            if idx < len(ops) - 1 and per_get_interval > 0:
                time.sleep(per_get_interval)

    try:
        net = Mininet(topo=topo, link=TCLink, waitConnected=True)
        net.start()

        set_ip_addr(net, topo.mesh_links)
        if bridge_configs:
            setup_bridges(net, bridge_manager, bridge_configs, args.hosts, topo.mesh_links)

        for idx in range(args.hosts):
            info(net.hosts[idx].cmd("ifconfig"))

        for node_a, node_b, bandwidth in parse_bw_args(args.bw):
            set_link_bandwidth(net, node_a, node_b, bandwidth)

        for host_name, intf_name, ip, mtu in parse_ext_args(args.ext):
            attach_external_interface(net, host_name, intf_name, ip, mtu)

        topo_png = _artifact_path(
            run_dir,
            args.topo_png,
            f"ex{args.hosts}_seed{seed_label}.png",
        )
        render_topology_png(
            topo.mesh_links,
            str(topo_png),
            seed=args.seed,
            layout=args.topo_layout,
        )

        host_graph, _ = build_host_graph(topo.mesh_links)
        cache_count = args.cache_count if args.cache_count > 0 else args.down_count + 1
        cache_nodes = select_k_centers(host_graph, cache_count)
        cache_nodes = [
            idx
            for idx in cache_nodes
            if idx not in publisher_ids and idx not in pubsub_publisher_ids
        ]
        if not cache_nodes and args.hosts > 0:
            candidates = [idx for idx in range(args.hosts) if idx not in publisher_ids]
            if candidates:
                cache_nodes = [candidates[-1]]
        cache_node_set = set(cache_nodes)
        if cache_nodes:
            info("cache nodes: " + ", ".join(f"h{idx}" for idx in cache_nodes) + "\n")

        apply_cache_node_settings(
            args.hosts,
            cache_node_set,
            getattr(args, "cache_default_rct_ms", None),
        )
        if pubsub_publisher_ids:
            apply_pubsub_node_settings(args.hosts, pubsub_publisher_ids)

        # Daemon startup phase: csmgrd -> conpubd -> cefnetd -> wait ready
        for idx in sorted(cache_node_set):
            start_csmgrd(net, idx)
            started_csmgrd_hosts.add(idx)

        for idx in sorted(pubsub_publisher_ids):
            start_conpubd(net, idx)
            started_conpubd_hosts.add(idx)

        for idx in range(args.hosts):
            start_cefnetd(net, idx)
        for idx in range(args.hosts):
            wait_for_cefnetd(net, idx)

        # FIB programming phase: run only after daemons are ready
        uri_publishers = {}
        for op in ops_put:
            uri_publishers[op["uri"]] = op["host"]

        if uri_publishers:
            set_fib_for_uris(net, topo.mesh_links, args.k, uri_publishers)
        else:
            set_fib(net, topo.mesh_links, args.k)

        run_cefstatus_all(net, args.hosts)
        print_mesh_links(topo.mesh_links)

        for op in ops_put:
            host = int(op["host"])
            uri = op["uri"]
            infile = op.get("file", "./sample-putfile")
            log_path = _artifact_path(
                run_dir,
                op.get("log"),
                f"cefputfile_h{host}.log",
            )
            if op.get("mode") == "pubsub":
                pub_opts = op.get("pub_opts", {}) or {}
                run_cefpubfile(
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
            else:
                run_cefputfile(
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
            time.sleep(1)

        ops_get = args.gets or []
        if auto_config and not ops_get:
            _, ops_get = generate_operations(auto_config, args.hosts, args.seed, run_dir)
        if not ops_get:
            base_uri = ops_put[0]["uri"]
            for idx in range(1, 6):
                candidates = [h for h in range(args.hosts) if h != ops_put[0]["host"]]
                consumer = rng.choice(candidates)
                ops_get.append(
                    {
                        "host": consumer,
                        "uri": base_uri,
                        "file": f"recvfile_at_h{consumer}",
                    }
                )

        warmup_ops = _build_warmup_ops(args, run_dir, hot_uris, cache_nodes)
        if warmup_ops:
            run_get_ops(
                warmup_ops,
                "warmup",
                getattr(args, "warmup_get_interval", 0),
                cycle_idx=0,
            )

        use_cli = not getattr(args, "no_cli", False)
        if args.down_interval > 0 and args.down_duration > 0:
            exclude_ids = parse_int_list(args.down_exclude)
            if publisher_ids:
                exclude_ids = list(set(exclude_ids) | publisher_ids)
            stop_event = periodic_host_flap(
                net,
                args.hosts,
                args.down_interval,
                args.down_duration,
                rng,
                exclude_ids,
                flap_state,
                args.down_count,
                args.down_stagger,
                quiet=use_cli,
            )

        if use_cli:
            run_get_ops(ops_get, "eval", args.get_interval, cycle_idx=0)
            if log_context:
                sys.stdout = log_context["original_stdout"]
                sys.stderr = log_context["original_stderr"]
            CLI(net)
            if log_context:
                sys.stdout = log_context["tee_stdout"]
                sys.stderr = log_context["tee_stderr"]
        else:
            duration = max(0, int(getattr(args, "duration", 0)))
            if duration == 0:
                run_get_ops(ops_get, "eval", args.get_interval, cycle_idx=0)
            else:
                deadline = time.time() + duration
                cycle_idx = 0
                while time.time() < deadline:
                    run_get_ops(ops_get, "eval", args.get_interval, cycle_idx=cycle_idx)
                    cycle_idx += 1
                    if time.time() >= deadline:
                        break

    finally:
        if stop_event is not None:
            stop_event.set()

        if net is not None:
            # Teardown phase: cefnetd -> conpubd -> csmgrd
            for idx in range(args.hosts):
                stop_cefnetd(net, idx)
            for idx in sorted(started_conpubd_hosts):
                stop_conpubd(net, idx)
            for idx in sorted(started_csmgrd_hosts):
                stop_csmgrd(net, idx)
            bridge_manager.cleanup()
            cleanup_external_bridges()
            net.stop()
            mn_cleanup()

        cleanup_node_dirs()

        if results_path is not None:
            results_path.write_text(
                json.dumps(results, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )


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
        help="root ns bridge: switch,root_ip,local_routes[,ext_routes,gateway] (repeatable; root_ip can be 'auto')",
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
    parser.add_argument(
        "--duration",
        type=int,
        default=0,
        help="eval phase duration in seconds for --no-cli (0: single cycle)",
    )
    parser.add_argument(
        "--results-json",
        type=str,
        default="",
        help="write warmup/eval get results to JSON under output directory",
    )
    parser.add_argument(
        "--warmup-get-interval",
        type=int,
        default=0,
        help="seconds between warmup get operations",
    )
    parser.add_argument(
        "--warmup-only-cache-nodes",
        action="store_true",
        default=True,
        help="restrict warmup prefetch to selected cache nodes",
    )
    parser.add_argument(
        "--warmup-all-hosts",
        action="store_false",
        dest="warmup_only_cache_nodes",
        help="run warmup prefetch on all hosts instead of cache nodes only",
    )
    parser.add_argument(
        "--cache-default-rct-ms",
        type=int,
        default=None,
        help="override CACHE_DEFAULT_RCT(ms) for cache nodes",
    )
    parser.add_argument(
        "--publisher-host",
        type=int,
        default=None,
        help="explicit publisher host used for publisher-down metric",
    )
    parser.add_argument(
        "--hot-uris",
        type=str,
        default="",
        help="comma-separated hot URIs for warmup generation",
    )
    parser.add_argument(
        "--warmup-gets",
        type=str,
        default="",
        help="JSON list of warmup get ops (host,uri,file,log)",
    )
    args = parser.parse_args()

    config_data = load_config(args.config)
    errors = validate_config(config_data)
    if errors:
        for error in errors:
            print(f"config error: {error}", file=sys.stderr)
        sys.exit(1)
    merge_cli_and_config(args, config_data)

    if args.legacy_layout:
        sys.exit("--legacy is disabled for deterministic output isolation")

    if isinstance(args.hot_uris, str) and args.hot_uris:
        args.hot_uris = [u.strip() for u in args.hot_uris.split(",") if u.strip()]
    if isinstance(args.warmup_gets, str) and args.warmup_gets:
        args.warmup_gets = json.loads(args.warmup_gets)
    if args.warmup_gets in ("", None):
        args.warmup_gets = []

    # Resolve output directory
    run_dir = resolve_run_dir(args)
    run_dir = run_dir.resolve()

    # Set dynamic default for topo_png
    seed_label = "none" if args.seed is None else str(args.seed)
    if args.topo_png is None:
        args.topo_png = f"ex{args.hosts}_seed{seed_label}.png"

    # Write meta.json with experiment configuration
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
        "cache_default_rct_ms": args.cache_default_rct_ms,
        "get_interval": args.get_interval,
        "warmup_get_interval": args.warmup_get_interval,
        "duration": args.duration,
        "output_dir": str(run_dir),
    }
    meta_path = _artifact_path(run_dir, "meta.json", "meta.json")
    meta_path.write_text(json.dumps(meta_data, indent=2), encoding="utf-8")

    # Set up script logging
    log_fp = None
    original_stdout = None
    original_stderr = None
    if not args.no_script_log:
        log_name = args.script_log if args.script_log else "script.log"
        log_path = _artifact_path(run_dir, log_name, "script.log")
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
