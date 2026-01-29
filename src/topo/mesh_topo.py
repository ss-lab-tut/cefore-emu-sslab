#!/usr/bin/env python

"""
Mesh topology example using Cefore and Mininet.

Randomly creates a user-selected number of host-to-host links via switches.
"""

import argparse
import random
import sys
import time

from mininet.cli import CLI
from mininet.log import info, setLogLevel
from mininet.net import Mininet
from mininet.topo import Topo

from .cef_daemons import (
    run_cefgetfile,
    run_cefputfile,
    run_cefstatus_all,
    start_cefnetd,
    start_csmgrd,
    stop_cefnetd,
    stop_csmgrd,
    wait_for_cefnetd,
)
from .links import pick_publish_link
from .net_config import set_fib, set_ip_addr
from .templates import cleanup_node_dirs, ensure_node_dirs
from .viz import print_mesh_links, render_topology_png


def min_required_links(host_num):
    """Calculate minimum links to cover all hosts.

    Args:
        host_num: Number of hosts.

    Returns:
        Minimum number of links.
    """
    return max(2, (host_num + 1) // 2)


def max_possible_links(host_num):
    """Calculate maximum possible links (complete graph).

    Args:
        host_num: Number of hosts.

    Returns:
        Maximum number of links.
    """
    return host_num * (host_num - 1) // 2


class MeshTopo(Topo):
    """Simple topology with mesh links."""

    # pylint: disable=arguments-differ
    def build(self, hosts, swhich_num=2, rng=None, switch_pool=0, **_kwargs):
        """Build mesh topology.

        Args:
            hosts: Number of hosts.
            swhich_num: Number of links to create.
            rng: Random number generator.
            switch_pool: Number of switches to share (0 = one per link).
        """
        if rng is None:
            rng = random.Random()
        if swhich_num < 2:
            raise ValueError("swhich_num must be at least 2")
        max_links = max_possible_links(hosts)
        if swhich_num > max_links:
            raise ValueError(f"swhich_num must be at most {max_links}")
        min_links = min_required_links(hosts)
        if swhich_num < min_links:
            raise ValueError(
                f"swhich_num must be at least {min_links} to cover all hosts"
            )

        if switch_pool <= 0:
            switch_pool = swhich_num
        if switch_pool < 1:
            raise ValueError("switch_pool must be at least 1")

        host_nodes = [self.addHost(f"h{idx}") for idx in range(hosts)]
        host_ids = list(range(hosts))
        rng.shuffle(host_ids)
        selected_links = []
        used_links = set()
        for idx in range(0, hosts - 1, 2):
            host_a, host_b = sorted((host_ids[idx], host_ids[idx + 1]))
            selected_links.append((host_a, host_b))
            used_links.add((host_a, host_b))
        if hosts % 2 == 1:
            last_host = host_ids[-1]
            other_host = rng.choice(
                [host for host in range(hosts) if host != last_host]
            )
            host_a, host_b = sorted((last_host, other_host))
            if (host_a, host_b) not in used_links:
                selected_links.append((host_a, host_b))
                used_links.add((host_a, host_b))

        if len(selected_links) < swhich_num:
            link_pairs = [
                (a, b)
                for a in range(hosts)
                for b in range(a + 1, hosts)
                if (a, b) not in used_links
            ]
            rng.shuffle(link_pairs)
            selected_links.extend(link_pairs[: swhich_num - len(selected_links)])

        self.mesh_links = []
        host_ports = [0] * hosts
        publisher = hosts - 1
        if selected_links:
            for idx, link in enumerate(selected_links):
                if publisher in link:
                    selected_links[0], selected_links[idx] = (
                        selected_links[idx],
                        selected_links[0],
                    )
                    break

        switch_names = [f"s{idx}" for idx in range(switch_pool)]
        switch_nodes = [self.addSwitch(name) for name in switch_names]
        switch_hosts = {name: set() for name in switch_names}
        host_switches = {idx: set() for idx in range(hosts)}
        pair_switch = {}

        switch_cycle = list(switch_names)
        rng.shuffle(switch_cycle)
        cycle_idx = 0

        for host_a, host_b in selected_links:
            pair_key = (host_a, host_b)
            shared = host_switches[host_a].intersection(host_switches[host_b])
            if shared:
                pair_switch[pair_key] = sorted(shared)[0]
                continue
            if cycle_idx < len(switch_cycle):
                switch_name = switch_cycle[cycle_idx]
                cycle_idx += 1
            else:
                switch_name = rng.choice(switch_names)
            pair_switch[pair_key] = switch_name
            switch_hosts[switch_name].add(host_a)
            switch_hosts[switch_name].add(host_b)
            host_switches[host_a].add(switch_name)
            host_switches[host_b].add(switch_name)

        for idx, switch_name in enumerate(switch_names):
            hosts_for_switch = sorted(switch_hosts[switch_name])
            if not hosts_for_switch:
                continue
            host_eth = {}
            for host_idx in hosts_for_switch:
                host_eth[host_idx] = host_ports[host_idx]
                host_ports[host_idx] += 1
                self.addLink(host_nodes[host_idx], switch_nodes[idx])
            self.mesh_links.append(
                {
                    "subnet": idx + 1,
                    "switch": switch_name,
                    "hosts": hosts_for_switch,
                    "host_eth": host_eth,
                }
            )


def run_mesh_topology(
    host_num,
    swhich_num,
    seed,
    k_paths,
    topo_png=None,
    topo_layout="spring",
    switch_pool=0,
):
    """Run mesh topology simulation.

    Args:
        host_num: Number of hosts.
        swhich_num: Number of links.
        seed: Random seed for topology generation.
        k_paths: Number of shortest paths per destination.
        topo_png: Path to save topology PNG.
        topo_layout: Layout algorithm for PNG.
        switch_pool: Number of switches to share.
    """
    if host_num < 3:
        sys.exit("host count must be at least 3")
    if k_paths < 1:
        sys.exit("k must be at least 1")
    if swhich_num < 2:
        sys.exit("link count must be at least 2")
    max_links = max_possible_links(host_num)
    if swhich_num > max_links:
        sys.exit(f"link count must be at most {max_links}")
    min_links = min_required_links(host_num)
    if swhich_num < min_links:
        sys.exit(f"link count must be at least {min_links} to cover all hosts")

    rng = random.Random(seed)
    ensure_node_dirs(host_num, rng)

    topo = MeshTopo(
        hosts=host_num,
        swhich_num=swhich_num,
        rng=rng,
        switch_pool=switch_pool,
    )
    net = Mininet(topo=topo, waitConnected=True)
    net.start()

    set_ip_addr(net, topo.mesh_links)

    for idx in range(host_num):
        node_name = f"h{idx}"
        print(node_name, "command:", "ifconfig")
        info(net.hosts[idx].cmd("ifconfig"))

    for idx in range(host_num):
        if idx % 2 == 1:
            start_csmgrd(net, idx)

    for idx in range(host_num):
        start_cefnetd(net, idx)

    for idx in range(host_num):
        wait_for_cefnetd(net, idx)

    set_fib(net, topo.mesh_links, k_paths)
    run_cefstatus_all(net, host_num)
    print_mesh_links(topo.mesh_links)
    render_topology_png(topo.mesh_links, topo_png, seed=seed, layout=topo_layout)
    time.sleep(1)

    publisher = host_num - 1
    publish_link = pick_publish_link(topo.mesh_links, publisher)
    publish_uri = f"ccnx:/test/example{publisher + 1}/test.py"
    consumer = (
        publish_link["host_b"]
        if publish_link["host_a"] == publisher
        else publish_link["host_a"]
    )

    run_cefputfile(net, publisher, publish_uri)
    time.sleep(5)

    run_cefgetfile(net, consumer, publish_uri, f"./recvfile_at_h{consumer}")

    CLI(net)

    for idx in range(host_num):
        stop_cefnetd(net, idx)

    for idx in range(host_num):
        if idx % 2 == 1:
            stop_csmgrd(net, idx)
    net.stop()
    cleanup_node_dirs()


def main():
    """CLI entry point for mesh topology."""
    parser = argparse.ArgumentParser(
        description="Cefore mesh topology (random host links via switches)"
    )
    parser.add_argument(
        "--hosts",
        type=int,
        default=5,
        help="number of hosts",
    )
    parser.add_argument(
        "--switches",
        type=int,
        default=10,
        help="number of random links (min: 2, max: all pairs)",
    )
    parser.add_argument(
        "--switch-pool",
        type=int,
        default=0,
        help="number of switches to share across links (0 = one switch per link)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="random seed for deterministic topology",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=2,
        help="number of shortest paths per destination",
    )
    parser.add_argument(
        "--topo-png",
        type=str,
        default="",
        help="write topology PNG to this path (requires networkx/matplotlib)",
    )
    parser.add_argument(
        "--topo-layout",
        type=str,
        default="spring",
        help="topology layout: spring, kamada_kawai, or circular",
    )
    args = parser.parse_args()

    setLogLevel("info")
    run_mesh_topology(
        args.hosts,
        args.switches,
        args.seed,
        args.k,
        topo_png=args.topo_png,
        topo_layout=args.topo_layout,
        switch_pool=args.switch_pool,
    )


if __name__ == "__main__":
    main()
