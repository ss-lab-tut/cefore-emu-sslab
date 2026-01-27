#!/usr/bin/env python

"""
Mesh topology example using Cefore and Mininet.

Randomly creates a user-selected number of host-to-host links via switches.
"""

import argparse
import heapq
import os
import random
import shutil
import sys
import time

from mininet.cli import CLI
from mininet.log import info, setLogLevel
from mininet.net import Mininet
from mininet.topo import Topo


def select_template(idx, host_num, rng):
    if idx < 3:
        return f"h{idx}"
    if idx % 2 == 1:
        return "h1"
    if idx == host_num - 1:
        return "h2"
    return rng.choice(["h0", "h2"])


def update_local_sock_id(node_dir, idx):
    for conf_name in ("cefnetd.conf", "csmgrd.conf"):
        conf_path = os.path.join(node_dir, conf_name)
        if not os.path.isfile(conf_path):
            continue
        with open(conf_path, "r", encoding="utf-8") as conf_file:
            lines = conf_file.readlines()
        updated = False
        new_lines = []
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith("LOCAL_SOCK_ID=") or stripped.startswith(
                "#LOCAL_SOCK_ID="
            ):
                leading = line[: len(line) - len(stripped)]
                new_lines.append(f"{leading}LOCAL_SOCK_ID={idx}\n")
                updated = True
            else:
                new_lines.append(line)
        if not updated:
            new_lines.append(f"LOCAL_SOCK_ID={idx}\n")
        with open(conf_path, "w", encoding="utf-8") as conf_file:
            conf_file.writelines(new_lines)


def update_node_name(node_dir, idx, base_uri="example.com/xxx/router-"):
    conf_path = os.path.join(node_dir, "cefnetd.conf")
    if not os.path.isfile(conf_path):
        return
    with open(conf_path, "r", encoding="utf-8") as conf_file:
        lines = conf_file.readlines()
    updated = False
    new_lines = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("NODE_NAME=") or stripped.startswith("#NODE_NAME="):
            leading = line[: len(line) - len(stripped)]
            new_lines.append(f'{leading}#NODE_NAME="{base_uri}{idx}"\n')
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f'#NODE_NAME="{base_uri}{idx}"\n')
    with open(conf_path, "w", encoding="utf-8") as conf_file:
        conf_file.writelines(new_lines)


def read_port_num(node_dir, default=9695):
    conf_path = os.path.join(node_dir, "cefnetd.conf")
    if not os.path.isfile(conf_path):
        return default
    with open(conf_path, "r", encoding="utf-8") as conf_file:
        for line in conf_file:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("PORT_NUM="):
                value = stripped.split("=", 1)[1].strip().split()[0]
                try:
                    return int(value)
                except ValueError:
                    break
    return default


def cleanup_cefnetd_socket(node_dir, idx):
    port = read_port_num(node_dir)
    sock_path = f"/tmp/cef_{port}.{idx}"
    if os.path.exists(sock_path):
        try:
            os.remove(sock_path)
            info(f"removed stale socket {sock_path}\n")
        except OSError:
            info(f"failed to remove stale socket {sock_path}\n")


def wait_for_cefnetd(net, idx, timeout=5, interval=0.25):
    node_name = f"h{idx}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = net.hosts[idx].cmd(
            f"sh -c 'cefstatus -d ./{node_name} >/dev/null 2>&1; echo $?'"
        )
        if result.strip().endswith("0"):
            return True
        time.sleep(interval)
    info(f"{node_name} cefnetd not ready; check {node_name}-cefnetd-log\n")
    return False


def ensure_node_dirs(host_num, rng):
    for idx in range(host_num):
        node_dir = f"h{idx}"
        template = select_template(idx, host_num, rng)
        if node_dir != template:
            if os.path.isdir(node_dir):
                shutil.rmtree(node_dir)
            shutil.copytree(template, node_dir)
        elif not os.path.isdir(node_dir):
            sys.exit(f"missing template directory: {template}")
        update_local_sock_id(node_dir, idx)


def set_ip_addr(net, mesh_links):
    # Assign one /24 per link; host index selects the last octet.
    for link in mesh_links:
        subnet = link["subnet"]
        for host_idx, eth_idx in (
            (link["host_a"], link["host_a_eth"]),
            (link["host_b"], link["host_b_eth"]),
        ):
            node_name = f"h{host_idx}"
            ip = f"192.168.{subnet}.{host_idx + 1}"
            command = f"ifconfig {node_name}-eth{eth_idx} {ip}"
            print(node_name, "command:", command)
            net.hosts[host_idx].cmd(command)


def shortest_path(
    graph, source, target, banned_edges=None, banned_nodes=None, weight_fn=None
):
    if source == target:
        return [source]
    banned_edges = banned_edges or set()
    banned_nodes = banned_nodes or set()
    weight_fn = weight_fn or (lambda _a, _b: 1)
    distances = {source: 0}
    parents = {source: None}
    heap = [(0, source)]
    while heap:
        dist, node = heapq.heappop(heap)
        if node == target:
            break
        if dist != distances.get(node):
            continue
        for neighbor in sorted(graph[node]):
            edge = frozenset((node, neighbor))
            if edge in banned_edges:
                continue
            if neighbor in banned_nodes and neighbor != target:
                continue
            new_dist = dist + weight_fn(node, neighbor)
            if new_dist < distances.get(neighbor, float("inf")):
                distances[neighbor] = new_dist
                parents[neighbor] = node
                heapq.heappush(heap, (new_dist, neighbor))
    if target not in parents:
        return None
    path = []
    node = target
    while node is not None:
        path.append(node)
        node = parents[node]
    return list(reversed(path))


def dijkstra_all(graph, source, weight_fn=None):
    weight_fn = weight_fn or (lambda _a, _b: 1)
    distances = {source: 0}
    parents = {source: None}
    heap = [(0, source)]
    while heap:
        dist, node = heapq.heappop(heap)
        if dist != distances.get(node):
            continue
        for neighbor in sorted(graph[node]):
            new_dist = dist + weight_fn(node, neighbor)
            if new_dist < distances.get(neighbor, float("inf")):
                distances[neighbor] = new_dist
                parents[neighbor] = node
                heapq.heappush(heap, (new_dist, neighbor))
    return distances, parents


def path_cost(path, weight_fn):
    if len(path) < 2:
        return 0
    return sum(weight_fn(path[idx], path[idx + 1]) for idx in range(len(path) - 1))


def k_shortest_paths(graph, source, target, k_paths, weight_fn=None):
    weight_fn = weight_fn or (lambda _a, _b: 1)
    first = shortest_path(graph, source, target, weight_fn=weight_fn)
    if not first:
        return []
    paths = [first]
    candidates = []
    for _ in range(1, k_paths):
        previous = paths[-1]
        for i in range(len(previous) - 1):
            spur_node = previous[i]
            root_path = previous[: i + 1]
            banned_edges = set()
            banned_nodes = set(root_path[:-1])
            for path in paths:
                if len(path) > i and path[: i + 1] == root_path:
                    banned_edges.add(frozenset((path[i], path[i + 1])))
            spur_path = shortest_path(
                graph,
                spur_node,
                target,
                banned_edges,
                banned_nodes,
                weight_fn=weight_fn,
            )
            if not spur_path:
                continue
            total_path = root_path[:-1] + spur_path
            candidates.append(total_path)
        if not candidates:
            break
        candidates.sort(key=lambda p: (path_cost(p, weight_fn), p))
        next_path = candidates.pop(0)
        if next_path not in paths:
            paths.append(next_path)
    return paths[:k_paths]


def set_fib(net, mesh_links, k_paths):
    # Add FIB entries for all destinations with multiple next hops.
    host_num = max(
        max(link["host_a"], link["host_b"]) for link in mesh_links
    ) + 1
    graph = {idx: set() for idx in range(host_num)}
    link_subnets = {}
    for link in mesh_links:
        host_a = link["host_a"]
        host_b = link["host_b"]
        graph[host_a].add(host_b)
        graph[host_b].add(host_a)
        key = tuple(sorted((host_a, host_b)))
        link_subnets[key] = link["subnet"]

    all_dist = []
    for src in range(host_num):
        distances, _parents = dijkstra_all(graph, src)
        all_dist.append(distances)

    for src in range(host_num):
        node_name = f"h{src}"
        for dest in range(host_num):
            if src == dest:
                continue
            prefix = f"ccnx:/test/example{dest + 1}"
            candidates = []
            for neighbor in graph[src]:
                dist_to_dest = all_dist[neighbor].get(dest)
                if dist_to_dest is None:
                    continue
                cost = 1 + dist_to_dest
                candidates.append((cost, neighbor))
            if not candidates:
                info(f"host h{src} has no path to h{dest}\n")
                continue
            candidates.sort()
            next_hops = [neighbor for _cost, neighbor in candidates[:k_paths]]
            for next_hop in next_hops:
                link_key = tuple(sorted((src, next_hop)))
                subnet = link_subnets[link_key]
                next_hop_ip = f"192.168.{subnet}.{next_hop + 1}"
                command = f"cefroute add {prefix} udp {next_hop_ip} -d ./{node_name}"
                print(node_name, "command:", command)
                info(net.hosts[src].cmd(command))


def build_host_graph(mesh_links):
    graph = {}
    link_switch = {}
    for link in mesh_links:
        host_a = link["host_a"]
        host_b = link["host_b"]
        graph.setdefault(host_a, set()).add(host_b)
        graph.setdefault(host_b, set()).add(host_a)
        key = tuple(sorted((host_a, host_b)))
        link_switch[key] = link["switch"]
    return graph, link_switch


def build_tree(graph, root):
    parent = {root: None}
    queue = [root]
    for node in queue:
        for neighbor in sorted(graph.get(node, [])):
            if neighbor not in parent:
                parent[neighbor] = node
                queue.append(neighbor)
    children = {node: [] for node in parent}
    for node, ancestor in parent.items():
        if ancestor is not None:
            children[ancestor].append(node)
    for node in children:
        children[node].sort()
    return children


def print_mesh_links(mesh_links):
    graph, link_switch = build_host_graph(mesh_links)
    info("\nMesh topology (per-host tree view):\n")
    for root in sorted(graph.keys()):
        info(f"h{root}\n")
        children = build_tree(graph, root)

        def walk(node, prefix):
            kids = children.get(node, [])
            for idx, child in enumerate(kids):
                last = idx == len(kids) - 1
                branch = "`-- " if last else "|-- "
                link_key = tuple(sorted((node, child)))
                switch_name = link_switch.get(link_key, "?")
                label = f"h{child} (via {switch_name})"
                info(f"{prefix}{branch}{label}\n")
                walk(child, prefix + ("    " if last else "|   "))

        walk(root, "")
        info("\n")

    info("> - Topology view as a single figure (adjacency matrix)\n")
    nodes = sorted(graph.keys())
    host_labels = [f"h{node}" for node in nodes]
    switch_labels = list(link_switch.values())
    cell_width = max(
        2,
        max((len(label) for label in host_labels), default=2),
        max((len(label) for label in switch_labels), default=2),
    )

    info("Mesh topology (adjacency matrix; cell = switch):\n")
    header = " " * (cell_width + 1) + " ".join(
        label.ljust(cell_width) for label in host_labels
    )
    info(f"{header}\n")

    for row_idx, node in enumerate(nodes):
        row = [host_labels[row_idx].ljust(cell_width)]
        for col_idx, other in enumerate(nodes):
            if row_idx == col_idx:
                row.append(".".ljust(cell_width))
                continue
            link_key = tuple(sorted((node, other)))
            switch_name = link_switch.get(link_key, ".")
            row.append(str(switch_name).ljust(cell_width))
        info(" ".join(row) + "\n")
    info("\n")


def render_topology_png(mesh_links, output_path, seed=None, layout="spring"):
    if not output_path:
        return
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import networkx as nx
    except Exception as exc:
        info(f"topology PNG skipped (missing deps): {exc}\n")
        return
    if not mesh_links:
        info("topology PNG skipped (no links)\n")
        return

    host_num = max(max(link["host_a"], link["host_b"]) for link in mesh_links) + 1
    graph = nx.Graph()
    host_nodes = {f"h{idx}" for idx in range(host_num)}
    switch_nodes = set()

    for link in mesh_links:
        host_a = f"h{link['host_a']}"
        host_b = f"h{link['host_b']}"
        switch = str(link["switch"])
        switch_nodes.add(switch)
        graph.add_edge(host_a, switch)
        graph.add_edge(host_b, switch)

    graph.add_nodes_from(host_nodes)
    graph.add_nodes_from(switch_nodes)

    if layout == "kamada_kawai":
        pos = nx.kamada_kawai_layout(graph)
    elif layout == "circular":
        pos = nx.circular_layout(graph)
    else:
        pos = nx.spring_layout(graph, seed=seed)

    fig, ax = plt.subplots(figsize=(10, 8))
    nx.draw_networkx_edges(graph, pos, ax=ax, width=1.2, alpha=0.6)
    nx.draw_networkx_nodes(
        graph,
        pos,
        nodelist=sorted(host_nodes),
        node_color="#8ecae6",
        node_size=800,
        ax=ax,
    )
    nx.draw_networkx_nodes(
        graph,
        pos,
        nodelist=sorted(switch_nodes),
        node_color="#b0bec5",
        node_shape="s",
        node_size=700,
        ax=ax,
    )
    nx.draw_networkx_labels(graph, pos, font_size=9, ax=ax)
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    info(f"topology PNG saved to {output_path}\n")


def find_link(mesh_links, host_a, host_b):
    for link in mesh_links:
        if {link["host_a"], link["host_b"]} == {host_a, host_b}:
            return link
    return None


def set_link_state(net, mesh_links, host_a, host_b, state):
    link = find_link(mesh_links, host_a, host_b)
    if link is None:
        sys.exit(f"link not found between h{host_a} and h{host_b}")
    switch_name = link["switch"]
    host_a_name = f"h{host_a}"
    host_b_name = f"h{host_b}"
    info("link", host_a_name, host_b_name, state, "\n")
    # Equivalent to Mininet CLI: link hX hY up/down
    net.configLinkStatus(host_a_name, switch_name, state)
    net.configLinkStatus(host_b_name, switch_name, state)


def link_down(net, mesh_links, host_a, host_b):
    set_link_state(net, mesh_links, host_a, host_b, "down")


def link_up(net, mesh_links, host_a, host_b):
    set_link_state(net, mesh_links, host_a, host_b, "up")


def pick_publish_link(mesh_links, publisher):
    for link in mesh_links:
        if publisher in (link["host_a"], link["host_b"]):
            return link
    sys.exit(f"publisher h{publisher} has no links")


def run_cefputfile(net, host_idx, uri):
    node_name = f"h{host_idx}"
    command = (
        f"cefputfile {uri} -f ./sample-putfile -t 3000 -e 3000 -d ./{node_name} "
        "> cefputfile-log"
    )
    print(node_name, "command:", command)
    net.hosts[host_idx].cmd(command)


def run_cefgetfile(net, host_idx, uri, output_path):
    node_name = f"h{host_idx}"
    command = f"cefgetfile {uri} -f {output_path} -d ./{node_name} > cefgetfile-log"
    print(node_name, "command:", command)
    net.hosts[host_idx].cmd(command)


def run_cefstatus(net, host_idx):
    node_name = f"h{host_idx}"
    command = f"cefstatus -d ./{node_name}"
    print(node_name, "command:", command)
    info(net.hosts[host_idx].cmd(command))


def run_cefstatus_all(net, host_num):
    info("\nFIB status per host:\n")
    for host_idx in range(host_num):
        run_cefstatus(net, host_idx)


def start_csmgrd(net, idx):
    node_name = f"h{idx}"
    command = f"csmgrdstart -d ./{node_name} > /dev/null 2>&1"
    print(node_name, "command:", command)
    info(net.hosts[idx].cmd(command))
    time.sleep(1)


def stop_csmgrd(net, idx):
    command = f"csmgrdstop -d ./h{idx}"
    info("hosts[", idx, "]:", command, "\n")
    net.hosts[idx].cmd(command)


def start_cefnetd(net, idx):
    node_name = f"h{idx}"
    cleanup_cefnetd_socket(node_name, idx)
    command = f"cefnetdstart -d ./{node_name} > /dev/null 2>&1"
    print(node_name, "command:", command)
    info(net.hosts[idx].cmd(command))
    time.sleep(1)


def stop_cefnetd(net, idx):
    command = f"cefnetdstop -F -d ./h{idx}"
    info("hosts[", idx, "]:", command, "\n")
    net.hosts[idx].cmd(command)


def cleanup_node_dirs():
    for name in os.listdir("."):
        if not name.startswith("h"):
            continue
        suffix = name[1:]
        if not suffix.isdigit():
            continue
        idx = int(suffix)
        if idx >= 3 and os.path.isdir(name):
            shutil.rmtree(name)


def min_required_links(host_num):
    return max(2, (host_num + 1) // 2)


def max_possible_links(host_num):
    return host_num * (host_num - 1) // 2


def run_mesh_topology(host_num, swhich_num, seed, k_paths, topo_png=None, topo_layout="spring"):
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

    topo = MeshTopo(hosts=host_num, swhich_num=swhich_num, rng=rng)
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

#    link_down(net, topo.mesh_links, 0, 7)
#    link_down(net, topo.mesh_links, 1, 5)
#    link_down(net, topo.mesh_links, 2, 4)
#    link_down(net, topo.mesh_links, 3, 6)
#    link_down(net, topo.mesh_links, 4, 7)
#    link_down(net, topo.mesh_links, 5, 6)
#    link_down(net, topo.mesh_links, 6, 7)

    run_cefgetfile(net, consumer, publish_uri, f"./recvfile_at_h{consumer}")

    CLI(net)

    for idx in range(host_num):
        stop_cefnetd(net, idx)

    for idx in range(host_num):
        if idx % 2 == 1:
            stop_csmgrd(net, idx)
    net.stop()
    cleanup_node_dirs()


class MeshTopo(Topo):
    "Simple topology with mesh links"

    # pylint: disable=arguments-differ
    def build(self, hosts, swhich_num=2, rng=None, **_kwargs):
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

        for idx, (host_a, host_b) in enumerate(selected_links):
            switch_name = f"s{idx}"
            switch_node = self.addSwitch(switch_name)

            host_a_eth = host_ports[host_a]
            host_ports[host_a] += 1
            host_b_eth = host_ports[host_b]
            host_ports[host_b] += 1

            self.addLink(host_nodes[host_a], switch_node)
            self.addLink(host_nodes[host_b], switch_node)
            self.mesh_links.append(
                {
                    "subnet": idx + 1,
                    "host_a": host_a,
                    "host_b": host_b,
                    "host_a_eth": host_a_eth,
                    "host_b_eth": host_b_eth,
                    "switch": switch_name,
                }
            )


def main():
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
    )


if __name__ == "__main__":
    main()
