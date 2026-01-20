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
    # Add FIB entries for each linked host pair.
    for link in mesh_links:
        subnet = link["subnet"]
        host_a = link["host_a"]
        host_b = link["host_b"]
        host_a_name = f"h{host_a}"
        host_b_name = f"h{host_b}"
        prefix = f"ccnx:/{host_a_name}-{host_b_name}"
        host_b_ip = f"192.168.{subnet}.{host_b + 1}"
        host_a_ip = f"192.168.{subnet}.{host_a + 1}"

        command = f"cefroute add {prefix} udp {host_b_ip} -d ./{host_a_name}"
        print(host_a_name, "command:", command)
        info(net.hosts[host_a].cmd(command))

        command = f"cefroute add {prefix} udp {host_a_ip} -d ./{host_b_name}"
        print(host_b_name, "command:", command)
        info(net.hosts[host_b].cmd(command))


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


def run_mesh_topology(host_num, link_num, seed):
    if host_num < 3:
        sys.exit("host count must be at least 3")
    if link_num < 2:
        sys.exit("link count must be at least 2")
    max_links = max_possible_links(host_num)
    if link_num > max_links:
        sys.exit(f"link count must be at most {max_links}")
    min_links = min_required_links(host_num)
    if link_num < min_links:
        sys.exit(f"link count must be at least {min_links} to cover all hosts")

    rng = random.Random(seed)
    ensure_node_dirs(host_num, rng)

    topo = MeshTopo(hosts=host_num, link_num=link_num, rng=rng)
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
    time.sleep(1)

    publisher = host_num - 1
    node_name = f"h{publisher}"
    command = (
        "cefputfile ccnx:/test -f ./sample-putfile -t 3000 -e 3000 -d ./"
        + node_name
        + " > cefputfile-log"
    )
    print(node_name, "command:", command)
    net.hosts[publisher].cmd(command)
    time.sleep(5)

    node_name = "h0"
    command = (
        "cefgetfile ccnx:/test -f ./recvfile_at_h0 -d ./"
        + node_name
        + " > cefgetfile-log"
    )
    print(node_name, "command:", command)
    net.hosts[0].cmd(command)

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
    def build(self, hosts, link_num=2, rng=None, **_kwargs):
        if rng is None:
            rng = random.Random()
        if link_num < 2:
            raise ValueError("link_num must be at least 2")
        max_links = max_possible_links(hosts)
        if link_num > max_links:
            raise ValueError(f"link_num must be at most {max_links}")
        min_links = min_required_links(hosts)
        if link_num < min_links:
            raise ValueError(f"link_num must be at least {min_links} to cover all hosts")

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
            other_host = rng.choice([host for host in range(hosts) if host != last_host])
            host_a, host_b = sorted((last_host, other_host))
            if (host_a, host_b) not in used_links:
                selected_links.append((host_a, host_b))
                used_links.add((host_a, host_b))

        if len(selected_links) < link_num:
            link_pairs = [
                (a, b)
                for a in range(hosts)
                for b in range(a + 1, hosts)
                if (a, b) not in used_links
            ]
            rng.shuffle(link_pairs)
            selected_links.extend(link_pairs[: link_num - len(selected_links)])

        self.mesh_links = []
        host_ports = [0] * hosts
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
                    "subnet": idx,
                    "host_a": host_a,
                    "host_b": host_b,
                    "host_a_eth": host_a_eth,
                    "host_b_eth": host_b_eth,
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
        "--links",
        type=int,
        default=2,
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
    run_mesh_topology(args.hosts, args.links, args.seed)


if __name__ == "__main__":
    main()
