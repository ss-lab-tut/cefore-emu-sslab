#!/usr/bin/env python

"""
Mesh topology example using Cefore and Mininet.

Randomly creates a user-selected number of host-to-host links via switches.
"""

import argparse
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


def set_fib(net, mesh_links):
    # Add FIB entries toward the last host using next-hop routing.
    host_num = max(
        max(link["host_a"], link["host_b"]) for link in mesh_links
    ) + 1
    target = host_num - 1
    graph = {idx: set() for idx in range(host_num)}
    link_subnets = {}
    for link in mesh_links:
        host_a = link["host_a"]
        host_b = link["host_b"]
        graph[host_a].add(host_b)
        graph[host_b].add(host_a)
        key = tuple(sorted((host_a, host_b)))
        link_subnets[key] = link["subnet"]

    parents = {target: None}
    queue = [target]
    for node in queue:
        for neighbor in graph[node]:
            if neighbor not in parents:
                parents[neighbor] = node
                queue.append(neighbor)

    prefixes = [
        f"ccnx:/test/example{subnet}"
        for subnet in sorted({link["subnet"] for link in mesh_links})
    ]

    for host_idx in range(host_num):
        if host_idx == target:
            continue
        next_hop = parents.get(host_idx)
        if next_hop is None:
            info(f"host h{host_idx} has no path to h{target}\n")
            continue
        link_key = tuple(sorted((host_idx, next_hop)))
        subnet = link_subnets[link_key]
        next_hop_ip = f"192.168.{subnet}.{next_hop + 1}"
        node_name = f"h{host_idx}"
        for prefix in prefixes:
            command = f"cefroute add {prefix} udp {next_hop_ip} -d ./{node_name}"
            print(node_name, "command:", command)
            info(net.hosts[host_idx].cmd(command))


def print_mesh_links(mesh_links):
    info("\nMesh links (host-switch-host):\n")
    for link in sorted(mesh_links, key=lambda item: item["subnet"]):
        host_a = link["host_a"]
        host_b = link["host_b"]
        host_a_name = f"h{host_a}"
        host_b_name = f"h{host_b}"
        host_a_eth = link["host_a_eth"]
        host_b_eth = link["host_b_eth"]
        switch_name = link["switch"]
        line = (
            f"{host_a_name}-eth{host_a_eth} -- {switch_name} -- "
            f"{host_b_name}-eth{host_b_eth} (subnet {link['subnet']})"
        )
        info(line + "\n")


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
    command = f"csmgrdstart -d ./{node_name} > {node_name}-csmgrd-log"
    print(node_name, "command:", command)
    info(net.hosts[idx].cmd(command))
    time.sleep(1)


def stop_csmgrd(net, idx):
    command = f"csmgrdstop -d ./h{idx}"
    info("hosts[", idx, "]:", command, "\n")
    net.hosts[idx].cmd(command)


def start_cefnetd(net, idx):
    node_name = f"h{idx}"
    command = f"cefnetdstart -d ./{node_name} > {node_name}-cefnetd-log"
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


def run_mesh_topology(host_num, swhich_num, seed):
    if host_num < 3:
        sys.exit("host count must be at least 3")
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

    set_fib(net, topo.mesh_links)
    run_cefstatus_all(net, host_num)
    print_mesh_links(topo.mesh_links)
    time.sleep(1)

    publisher = host_num - 1
    publish_link = pick_publish_link(topo.mesh_links, publisher)
    publish_uri = "ccnx:/test/example1/test.py"
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
    args = parser.parse_args()

    setLogLevel("info")
    run_mesh_topology(args.hosts, args.switches, args.seed)


if __name__ == "__main__":
    main()
