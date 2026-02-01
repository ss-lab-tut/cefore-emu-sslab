#!/usr/bin/env python

"""
Line topology example using Cefore and Mininet.

Defaults to 3 hosts and 2 switches: h0-s0-h1-s1-h2.
"""

import argparse
import os
import random
import shutil
import sys
import time
from pathlib import Path

from mininet.cli import CLI
from mininet.log import info, setLogLevel
from mininet.net import Mininet
from mininet.topo import Topo
from mininet.util import irange


ROOT_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATE_ROOT = ROOT_DIR / "configs" / "templates"


def select_template(idx, host_num, rng):
    if idx < 3:
        return TEMPLATE_ROOT / f"h{idx}"
    if idx % 2 == 1:
        return TEMPLATE_ROOT / "h1"
    if idx == host_num - 1:
        return TEMPLATE_ROOT / "h2"
    return rng.choice([TEMPLATE_ROOT / "h0", TEMPLATE_ROOT / "h2"])


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
        if not template.exists():
            sys.exit(f"missing template directory: {template}")
        if node_dir != str(template):
            if os.path.isdir(node_dir):
                shutil.rmtree(node_dir)
            shutil.copytree(template, node_dir)
        update_local_sock_id(node_dir, idx)


def set_ip_addr(net, host_num):
    # eth0 = left link, eth1 = right link
    for idx in irange(0, host_num - 1):
        node_name = f"h{idx}"
        if idx > 0:
            left_ip = f"192.168.{idx - 1}.{idx + 1}"
            command = f"ifconfig {node_name}-eth0 {left_ip}"
            print(node_name, "command:", command)
            net.hosts[idx].cmd(command)
        if idx < host_num - 1:
            right_ip = f"192.168.{idx}.{idx + 1}"
            eth_name = "eth1" if idx > 0 else "eth0"
            command = f"ifconfig {node_name}-{eth_name} {right_ip}"
            print(node_name, "command:", command)
            net.hosts[idx].cmd(command)


def set_fib(net, host_num):
    # Forward Interests along the line toward the publisher.
    for idx in irange(0, host_num - 2):
        node_name = f"h{idx}"
        next_hop_ip = f"192.168.{idx}.{idx + 2}"
        command = f"cefroute add ccnx:/test udp {next_hop_ip} -d ./{node_name}"
        print(node_name, "command:", command)
        info(net.hosts[idx].cmd(command))


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


def run_line_topology(host_num):
    if host_num < 2:
        sys.exit("host count must be at least 3")

    rng = random.Random()
    ensure_node_dirs(host_num, rng)

    topo = LineTopo(hosts=host_num)
    net = Mininet(topo=topo, waitConnected=True)
    net.start()

    set_ip_addr(net, host_num)

    for idx in irange(0, host_num - 1):
        node_name = f"h{idx}"
        print(node_name, "command:", "ifconfig")
        info(net.hosts[idx].cmd("ifconfig"))

    for idx in range(host_num):
        if idx % 2 == 1:
            start_csmgrd(net, idx)

    for idx in range(host_num):
        start_cefnetd(net, idx)

    set_fib(net, host_num)
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


class LineTopo(Topo):
    "Simple topology with linear links"

    # pylint: disable=arguments-differ
    def build(self, hosts, **_kwargs):
        switches = hosts - 1
        host_nodes = [self.addHost(f"h{idx}") for idx in range(hosts)]
        switch_nodes = [self.addSwitch(f"s{idx}") for idx in range(switches)]

        for idx in range(switches):
            self.addLink(switch_nodes[idx], host_nodes[idx])
            self.addLink(switch_nodes[idx], host_nodes[idx + 1])


def main():
    parser = argparse.ArgumentParser(
        description="Cefore line topology (default: 3 hosts, 2 switches)"
    )
    parser.add_argument("--hosts", type=int, default=5, help="number of hosts")
    args = parser.parse_args()

    setLogLevel("info")
    run_line_topology(args.hosts)


if __name__ == "__main__":
    main()
