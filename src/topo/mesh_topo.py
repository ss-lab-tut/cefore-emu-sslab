#!/usr/bin/env python

"""
Mesh topology example using Cefore and Mininet.

Randomly creates a user-selected number of host-to-host links via switches.
"""

import argparse
import random
import sys
import time
from pathlib import Path

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
from .graph_algos import UnionFind
from .links import pick_publish_link
from .net_config import set_fib, set_ip_addr
from .paths import resolve_run_dir
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
    def build(self, hosts, swhich_num=2, rng=None, node_per_switch=2, **_kwargs):
        """Build mesh topology.

        Args:
            hosts: Number of hosts.
            swhich_num: Number of links to create.
            rng: Random number generator.
            node_per_switch: Maximum number of hosts per switch
                            (0 = unlimited, 2 = one switch per link).
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

        host_nodes = [self.addHost(f"h{idx}") for idx in range(hosts)]

        # Union-Find による連結性保証
        uf = UnionFind(hosts)
        all_pairs = [(a, b) for a in range(hosts) for b in range(a + 1, hosts)]
        rng.shuffle(all_pairs)

        selected_links = []
        used_links = set()

        # フェーズ1: 連結化（N-1本でグラフが連結になる）
        for a, b in all_pairs:
            if uf.union(a, b):
                selected_links.append((a, b))
                used_links.add((a, b))
            if len(selected_links) >= hosts - 1:
                break

        # フェーズ2: 冗長リンク追加（経路多重化）
        for a, b in all_pairs:
            if len(selected_links) >= swhich_num:
                break
            if (a, b) not in used_links:
                selected_links.append((a, b))
                used_links.add((a, b))

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

        # スイッチ割り当て（容量ベース）
        switch_hosts = {}  # switch_name -> set of host_ids
        host_switches = {idx: set() for idx in range(hosts)}
        switch_count = 0

        for host_a, host_b in selected_links:
            # 両ホストが既に同じスイッチに接続していればそれを使用
            shared = host_switches[host_a].intersection(host_switches[host_b])
            if shared:
                switch_name = sorted(shared)[0]
            else:
                # 容量に空きがあるスイッチを探す
                switch_name = None
                for sw, sw_hosts in switch_hosts.items():
                    # このスイッチに両ホストを追加しても容量内か？
                    new_hosts = sw_hosts | {host_a, host_b}
                    if node_per_switch <= 0 or len(new_hosts) <= node_per_switch:
                        switch_name = sw
                        break

                # 空きがなければ新規スイッチを作成
                if switch_name is None:
                    switch_name = f"s{switch_count}"
                    switch_count += 1
                    switch_hosts[switch_name] = set()

            # スイッチにホストを登録
            switch_hosts[switch_name].update({host_a, host_b})
            host_switches[host_a].add(switch_name)
            host_switches[host_b].add(switch_name)

        # スイッチノードを作成してリンクを追加
        switch_nodes = {}
        for switch_name in switch_hosts:
            switch_nodes[switch_name] = self.addSwitch(switch_name)

        for idx, (switch_name, hosts_set) in enumerate(switch_hosts.items()):
            hosts_for_switch = sorted(hosts_set)
            host_eth = {}
            for host_idx in hosts_for_switch:
                host_eth[host_idx] = host_ports[host_idx]
                host_ports[host_idx] += 1
                self.addLink(host_nodes[host_idx], switch_nodes[switch_name])
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
    node_per_switch=2,
    run_dir=None,
):
    """Run mesh topology simulation.

    Args:
        host_num: Number of hosts.
        swhich_num: Number of links.
        seed: Random seed for topology generation.
        k_paths: Number of shortest paths per destination.
        topo_png: Path to save topology PNG.
        topo_layout: Layout algorithm for PNG.
        node_per_switch: Maximum hosts per switch (0=unlimited, 2=default).
        run_dir: Output directory for logs and artifacts.
    """
    if run_dir is None:
        run_dir = Path(".")
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
        node_per_switch=node_per_switch,
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

    # Resolve topology PNG path with run_dir
    topo_png_path = topo_png
    if topo_png_path:
        topo_png_path = str(run_dir / Path(topo_png_path).name)
    render_topology_png(topo.mesh_links, topo_png_path, seed=seed, layout=topo_layout)
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

    recvfile_path = str(run_dir / f"recvfile_at_h{consumer}")
    run_cefgetfile(net, consumer, publish_uri, recvfile_path)

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
        "--node-per-switch",
        type=int,
        default=2,
        help="max hosts per switch (0=unlimited, 2=one switch per link)",
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
    args = parser.parse_args()

    # Resolve output directory
    run_dir = resolve_run_dir(args)

    setLogLevel("info")
    run_mesh_topology(
        args.hosts,
        args.switches,
        args.seed,
        args.k,
        topo_png=args.topo_png,
        topo_layout=args.topo_layout,
        node_per_switch=args.node_per_switch,
        run_dir=run_dir,
    )


if __name__ == "__main__":
    main()
