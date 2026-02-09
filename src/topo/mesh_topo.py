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

from mininet.clean import cleanup as mn_cleanup
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
from .graph_algos import select_k_centers
from .graph_algos import UnionFind
from .links import pick_publish_link
from .net_config import set_fib, set_ip_addr
from .paths import resolve_run_dir, resolve_run_path
from .templates import apply_cache_node_settings, cleanup_node_dirs, ensure_node_dirs
from .viz import build_host_graph, print_mesh_links, render_topology_png


def min_required_switches(host_num, switch_capacity):
    """Minimum switches needed to connect all hosts (spanning tree assumption)."""
    if switch_capacity < 2:
        raise ValueError("switch_capacity must be at least 2")
    return max(1, (host_num + switch_capacity - 1) // switch_capacity)


class MeshTopo(Topo):
    """Simple topology with mesh links."""

    # pylint: disable=arguments-differ
    def build(
        self,
        hosts,
        swhich_num=0,
        rng=None,
        node_per_switch=2,
        host_degree_min=1,
        host_degree_max=2,
        switch_use_all=False,
        **_kwargs,
    ):
        """Build mesh topology.

        Args:
            hosts: Number of hosts.
            swhich_num: Maximum number of switches to create (0 = unlimited).
            rng: Random number generator.
            node_per_switch: Switch capacity (max hosts per switch; 0 = unlimited).
            host_degree_min: Minimum number of switches each host connects to (>=1).
            host_degree_max: Maximum number of switches each host connects to.
            switch_use_all: If True, create switches up to swhich_num and
                distribute extra host connections evenly (may exceed host_degree_max).
        """
        if rng is None:
            rng = random.Random()
        if host_degree_min < 1 or host_degree_max < host_degree_min:
            raise ValueError("host_degree_min/max must satisfy 1 <= min <= max")
        if node_per_switch == 1:
            raise ValueError("switch capacity must be >=2 to connect hosts")
        switch_capacity = node_per_switch if node_per_switch > 0 else hosts

        host_nodes = [self.addHost(f"h{idx}") for idx in range(hosts)]

        self.mesh_links = []
        host_ports = [0] * hosts

        # 1. ホスト度数をサンプリング
        degrees = [rng.randint(host_degree_min, host_degree_max) for _ in range(hosts)]
        if any(d < 1 for d in degrees):
            raise ValueError("all hosts must have degree >=1")

        # 2. 連結性を確保する spanning tree (ホスト間をスイッチ経由で接続)
        switch_hosts = {}  # switch_name -> set(host_id)
        switch_nodes = {}
        switch_count = 0

        def new_switch():
            nonlocal switch_count
            name = f"s{switch_count}"
            switch_count += 1
            switch_hosts[name] = set()
            switch_nodes[name] = self.addSwitch(name)
            return name

        host_order = list(range(hosts))
        rng.shuffle(host_order)
        # 度数降順でソート（同点はシャッフル順を維持 - Pythonのsortは安定ソート）
        host_order.sort(key=lambda h: degrees[h], reverse=True)
        connected = [host_order[0]]
        remaining = host_order[1:]

        for host in remaining:
            # partner選択: 残度数が最大のconnectedノードを選ぶ
            # 同点の場合はシャッフル順を維持（安定ソート）
            candidates = sorted(connected, key=lambda n: degrees[n], reverse=True)
            partner = None
            for cand in candidates:
                if degrees[cand] > 0 and degrees[host] > 0:
                    partner = cand
                    break
            if partner is None:
                raise ValueError("failed to build spanning tree under degree constraints")
            # choose switch with capacity or create new
            chosen_switch = None
            for sw, hs in switch_hosts.items():
                if len(hs) + 2 <= switch_capacity and partner in hs:
                    chosen_switch = sw
                    break
            if chosen_switch is None:
                chosen_switch = new_switch()
            switch_hosts[chosen_switch].update({host, partner})
            degrees[host] -= 1
            degrees[partner] -= 1
            connected.append(host)

        # 3. 残度数を埋めて冗長経路を追加
        # 集約的にスイッチを作ってホストを詰める
        hosts_with_deg = [i for i, d in enumerate(degrees) if d > 0]
        while hosts_with_deg:
            sw = new_switch()
            cap_left = switch_capacity
            rng.shuffle(hosts_with_deg)
            to_remove = []
            for host in hosts_with_deg:
                if degrees[host] > 0 and cap_left > 0:
                    switch_hosts[sw].add(host)
                    degrees[host] -= 1
                    cap_left -= 1
                    if degrees[host] == 0:
                        to_remove.append(host)
                if cap_left == 0:
                    break
            hosts_with_deg = [h for h in hosts_with_deg if degrees[h] > 0]

        # 4. スイッチ数制約チェック
        if swhich_num and switch_count > swhich_num:
            raise ValueError(
                f"switch count {switch_count} exceeds limit {swhich_num} "
                f"(increase switch capacity or host degree range)"
            )

        # 4.5. 余剰スイッチ枠の充填（switch_use_all が有効な場合）
        if switch_use_all and swhich_num:
            extra_switches = max(0, swhich_num - switch_count)
            if extra_switches > 0:
                import heapq

                info(
                    "switch_use_all enabled: distributing extra switches; host degrees may exceed host_degree_max\n"
                )

                # 現在の度数を算出（switch_hosts から集計）
                current_deg = [0] * hosts
                for hs in switch_hosts.values():
                    for h in hs:
                        current_deg[h] += 1

                # 最小度数優先 + ランダムタイブレーク。
                heap = [[deg, rng.random(), host_idx] for host_idx, deg in enumerate(current_deg)]
                heapq.heapify(heap)

                for _ in range(extra_switches):
                    if not heap:
                        info("warning: no hosts available to attach to extra switches\n")
                        break

                    sw = new_switch()
                    cap_left = min(switch_capacity, hosts)
                    used_hosts = set()
                    popped = []

                    while cap_left > 0 and heap:
                        deg, tie, host_idx = heapq.heappop(heap)
                        if host_idx in used_hosts:
                            popped.append([deg, tie, host_idx, False])
                            continue

                        used_hosts.add(host_idx)
                        popped.append([deg, tie, host_idx, True])
                        cap_left -= 1

                    # 戻し入れる（接続したホストは度数を+1してランダム値も更新）
                    for deg, tie, host_idx, used in popped:
                        if used:
                            deg += 1
                            current_deg[host_idx] += 1
                            switch_hosts[sw].add(host_idx)
                        heapq.heappush(heap, [deg, rng.random(), host_idx])

                if switch_count < swhich_num:
                    info(
                        "warning: could not reach requested switch count; capacity or host pool exhausted\n"
                    )

        # 5. スイッチノードを作成してリンクを追加（残度で空のスイッチはない）
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
    host_degree_min=1,
    host_degree_max=2,
    switch_use_all=False,
    cache_count=0,
    run_dir=None,
    no_cli=False,
):
    """Run mesh topology simulation.

    Args:
        host_num: Number of hosts.
        swhich_num: Number of links.
        seed: Random seed for topology generation.
        k_paths: Number of shortest paths per destination.
        topo_png: Path to save topology PNG.
        topo_layout: Layout algorithm for PNG.
        node_per_switch: Switch capacity (max hosts per switch; 0=unlimited, 2=default).
        host_degree_min: Minimum switches per host.
        host_degree_max: Maximum switches per host.
        switch_use_all: Use all switch slots up to swhich_num by adding extra links.
        run_dir: Output directory for logs and artifacts.
    """
    if run_dir is None:
        run_dir = Path("logs")
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    if host_num < 3:
        sys.exit("host count must be at least 3")
    if k_paths < 1:
        sys.exit("k must be at least 1")
    if swhich_num and swhich_num < 1:
        sys.exit("switch count must be at least 1 (or 0 for unlimited)")
    required_switches = min_required_switches(host_num, node_per_switch or host_num)
    if swhich_num and swhich_num < required_switches:
        sys.exit(
            f"switch count must be at least {required_switches} "
            f"to connect {host_num} hosts with capacity {node_per_switch}"
        )

    rng = random.Random(seed)
    publisher_ids = {host_num - 1}
    ensure_node_dirs(host_num, rng, publisher_ids)

    topo = MeshTopo(
        hosts=host_num,
        swhich_num=swhich_num,
        rng=rng,
        node_per_switch=node_per_switch,
        host_degree_min=host_degree_min,
        host_degree_max=host_degree_max,
        switch_use_all=switch_use_all,
    )
    net = Mininet(topo=topo, waitConnected=True)
    net.start()

    set_ip_addr(net, topo.mesh_links)

    for idx in range(host_num):
        node_name = f"h{idx}"
        print(node_name, "command:", "ifconfig")
        info(net.hosts[idx].cmd("ifconfig"))

    host_graph, _ = build_host_graph(topo.mesh_links)
    effective_cache_count = cache_count if cache_count > 0 else max(1, host_num // 2)
    cache_nodes = select_k_centers(host_graph, effective_cache_count)
    if not cache_nodes and host_num > 0:
        cache_nodes = [host_num - 1]
    cache_node_set = set(cache_nodes)
    apply_cache_node_settings(host_num, cache_node_set, None)
    if cache_nodes:
        info("cache nodes: " + ", ".join(f"h{idx}" for idx in cache_nodes) + "\n")
    # Daemon startup phase: csmgrd -> cefnetd -> wait ready
    for idx in sorted(cache_node_set):
        start_csmgrd(net, idx)

    for idx in range(host_num):
        start_cefnetd(net, idx)

    for idx in range(host_num):
        wait_for_cefnetd(net, idx)

    # FIB programming phase: run only after daemons are ready
    set_fib(net, topo.mesh_links, k_paths)
    run_cefstatus_all(net, host_num)
    print_mesh_links(topo.mesh_links)

    # Resolve topology PNG path with run_dir
    topo_png_path = str(
        resolve_run_path(
            run_dir,
            topo_png,
            f"ex{host_num}_seed{'none' if seed is None else seed}.png",
        )
    )
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

    recvfile_path = str(resolve_run_path(run_dir, None, f"recvfile_at_h{consumer}"))
    run_cefgetfile(net, consumer, publish_uri, recvfile_path)

    if not no_cli:
        CLI(net)

    # Teardown phase: cefnetd -> csmgrd
    for idx in range(host_num):
        stop_cefnetd(net, idx)

    for idx in sorted(cache_node_set):
        stop_csmgrd(net, idx)
    net.stop()
    mn_cleanup()
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
        help="maximum number of switches to create (0 = unlimited)",
    )
    parser.add_argument(
        "--node-per-switch",
        type=int,
        default=2,
        help="switch capacity: max hosts per switch (0=unlimited, 2=one switch per link)",
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
        "--cache-count",
        type=int,
        default=0,
        help="number of cache nodes for csmgrd startup (0: hosts//2)",
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
    parser.add_argument(
        "--no-cli",
        action="store_true",
        help="skip interactive CLI (flap output visible on stdout)",
    )
    args = parser.parse_args()

    if args.legacy_layout:
        sys.exit("--legacy is disabled for deterministic output isolation")

    # Resolve output directory
    run_dir = resolve_run_dir(args)
    run_dir = run_dir.resolve()

    setLogLevel("info")
    run_mesh_topology(
        args.hosts,
        args.switches,
        args.seed,
        args.k,
        topo_png=args.topo_png,
        topo_layout=args.topo_layout,
        node_per_switch=args.node_per_switch,
        host_degree_min=args.host_degree_min,
        host_degree_max=args.host_degree_max,
        switch_use_all=args.switch_use_all,
        cache_count=args.cache_count,
        run_dir=run_dir,
        no_cli=args.no_cli,
    )


if __name__ == "__main__":
    main()
