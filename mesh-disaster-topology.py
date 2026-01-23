#!/usr/bin/env python

"""
Periodic host failure emulator based on mesh-nodes-switches.py.
"""

import argparse
import importlib.util
import os
import random
import threading
import time

from mininet.link import Intf, TCLink
from mininet.log import info, setLogLevel
from mininet.net import Mininet


def load_mesh_module():
    script_path = os.path.join(os.path.dirname(__file__), "mesh-nodes-switches.py")
    spec = importlib.util.spec_from_file_location("mesh_nodes_switches", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_int_list(value):
    if not value:
        return []
    return [int(item) for item in value.split(",") if item.strip() != ""]


def set_node_links_state(net, node_name, state):
    node = net.get(node_name)
    for link in net.links:
        if link.intf1.node == node:
            net.configLinkStatus(node.name, link.intf2.node.name, state)
        elif link.intf2.node == node:
            net.configLinkStatus(node.name, link.intf1.node.name, state)


def periodic_host_flap(net, host_num, interval, down_time, rng, exclude, state):
    host_ids = [idx for idx in range(host_num) if idx not in exclude]
    if not host_ids:
        info("no hosts available for flapping\n")
        return threading.Event()
    stop_event = threading.Event()

    def worker():
        position = 0
        while not stop_event.is_set():
            host_idx = host_ids[position % len(host_ids)]
            position += 1
            if rng is not None:
                host_idx = rng.choice(host_ids)
            host_name = f"h{host_idx}"
            state["last_down_host"] = host_idx
            info(f"\n[flap] down {host_name}\n")
            set_node_links_state(net, host_name, "down")
            stop_event.wait(down_time)
            info(f"\n[flap] up {host_name}\n")
            set_node_links_state(net, host_name, "up")
            stop_event.wait(interval)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return stop_event


def set_link_bandwidth(net, node_a, node_b, bandwidth):
    for link in net.linksBetween(net.get(node_a), net.get(node_b)):
        link.intf1.config(bw=bandwidth)
        link.intf2.config(bw=bandwidth)
        info(f"set bw {bandwidth} Mbps between {node_a} and {node_b}\n")


def attach_external_interface(net, host_name, intf_name, ip=None, mtu=None):
    host = net.get(host_name)
    Intf(intf_name, node=host)
    if mtu:
        host.cmd(f"ifconfig {intf_name} mtu {mtu}")
    if ip:
        host.cmd(f"ifconfig {intf_name} {ip}")
    info(f"attached {intf_name} to {host_name}\n")


def parse_bw_args(values):
    entries = []
    for value in values or []:
        parts = [part.strip() for part in value.split(",")]
        if len(parts) != 3:
            raise ValueError("bw format is nodeA,nodeB,mbps")
        entries.append((parts[0], parts[1], float(parts[2])))
    return entries


def parse_ext_args(values):
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


def run_disaster_topology(args):
    mesh = load_mesh_module()

    rng = random.Random(args.seed) if args.seed is not None else None
    mesh.ensure_node_dirs(args.hosts, rng or random.Random())

    topo = mesh.MeshTopo(hosts=args.hosts, swhich_num=args.switches, rng=rng)
    net = Mininet(topo=topo, link=TCLink, waitConnected=True)
    net.start()

    mesh.set_ip_addr(net, topo.mesh_links)

    for idx in range(args.hosts):
        node_name = f"h{idx}"
        info(net.hosts[idx].cmd("ifconfig"))

    for idx in range(args.hosts):
        if idx % 2 == 1:
            mesh.start_csmgrd(net, idx)

    for idx in range(args.hosts):
        mesh.start_cefnetd(net, idx)

    mesh.set_fib(net, topo.mesh_links, args.k)
    mesh.run_cefstatus_all(net, args.hosts)
    mesh.print_mesh_links(topo.mesh_links)
    time.sleep(1)

    for node_a, node_b, bandwidth in parse_bw_args(args.bw):
        set_link_bandwidth(net, node_a, node_b, bandwidth)

    for host_name, intf_name, ip, mtu in parse_ext_args(args.ext):
        attach_external_interface(net, host_name, intf_name, ip, mtu)

    publisher = args.hosts - 1
    publish_link = mesh.pick_publish_link(topo.mesh_links, publisher)
    publish_uri = f"ccnx:/test/example{publisher + 1}/test.py"
    consumer = (
        publish_link["host_b"]
        if publish_link["host_a"] == publisher
        else publish_link["host_a"]
    )

    seed_label = "none" if args.seed is None else str(args.seed)
    down_host_label = "none"
    log_name = (
        f"cefputfile_{args.hosts}_{args.switches}_{seed_label}_"
        f"{args.down_interval}_{args.down_duration}_{down_host_label}.log"
    )
    command = (
        f"cefputfile {publish_uri} -f ./sample-putfile -t 3000 -e 3000 "
        f"-d ./h{publisher} > {log_name}"
    )
    print(f"h{publisher}", "command:", command)
    net.hosts[publisher].cmd(command)
    time.sleep(5)

    stop_event = None
    flap_state = {"last_down_host": None}
    if args.down_interval > 0 and args.down_duration > 0:
        stop_event = periodic_host_flap(
            net,
            args.hosts,
            args.down_interval,
            args.down_duration,
            rng,
            parse_int_list(args.down_exclude),
            flap_state,
        )

    rng = rng or random.Random()
    for idx in range(1, 6):
        candidates = [h for h in range(args.hosts) if h != publisher]
        consumer = rng.choice(candidates)
        down_host = flap_state["last_down_host"]
        down_host_label = "none" if down_host is None else str(down_host)
        seed_label = "none" if args.seed is None else str(args.seed)
        log_name = (
            f"cefgetfile_{args.hosts}_{args.switches}_{seed_label}_"
            f"{args.down_interval}_{args.down_duration}_{down_host_label}_"
            f"h{consumer}.log"
        )
        command = (
            f"cefgetfile {publish_uri} -f ./recvfile_at_h{consumer} "
            f"-d ./h{consumer} > {log_name}"
        )
        print(f"h{consumer}", "command:", command)
        net.hosts[consumer].cmd(command)
        if idx < 5 and args.get_interval > 0:
            time.sleep(args.get_interval)

    # CLI(net)

    if stop_event is not None:
        stop_event.set()

    for idx in range(args.hosts):
        mesh.stop_cefnetd(net, idx)

    for idx in range(args.hosts):
        if idx % 2 == 1:
            mesh.stop_csmgrd(net, idx)
    net.stop()
    mesh.cleanup_node_dirs()


def main():
    parser = argparse.ArgumentParser(
        description="Cefore mesh topology with periodic host down"
    )
    parser.add_argument("--hosts", type=int, default=5, help="number of hosts")
    parser.add_argument(
        "--switches",
        type=int,
        default=10,
        help="number of random links (min: 2, max: all pairs)",
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
        help="comma-separated host ids to exclude from flapping",
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
        "--get-interval",
        type=int,
        default=10,
        help="seconds between cefgetfile runs",
    )
    args = parser.parse_args()

    setLogLevel("info")
    run_disaster_topology(args)


if __name__ == "__main__":
    main()
