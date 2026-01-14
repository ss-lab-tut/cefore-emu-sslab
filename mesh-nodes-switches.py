#!/usr/bin/env python

"""
Mesh topology example using Cefore and Mininet.

Each host connects to every switch (>= 2 switches required).
"""

import argparse
import os
import shutil
import sys
import time

from mininet.cli import CLI
from mininet.log import info, setLogLevel
from mininet.net import Mininet
from mininet.topo import Topo


def ensure_node_dirs(host_num):
    for idx in range(host_num):
        node_dir = f"h{idx}"
        if os.path.isdir(node_dir):
            continue
        if idx == 0:
            template = "h0"
        elif idx == host_num - 1:
            template = "h2"
        else:
            template = "h1"
        shutil.copytree(template, node_dir)


def set_ip_addr(net, host_num, switch_num):
    # Assign one /24 per switch; host index selects the last octet.
    for host_idx in range(host_num):
        node_name = f"h{host_idx}"
        for switch_idx in range(switch_num):
            ip = f"192.168.{switch_idx}.{host_idx + 1}"
            command = f"ifconfig {node_name}-eth{switch_idx} {ip}"
            print(node_name, "command:", command)
            net.hosts[host_idx].cmd(command)


def set_fib(net, host_num):
    # Forward Interests along a host chain using the s0 subnet.
    for idx in range(host_num - 1):
        node_name = f"h{idx}"
        next_hop_ip = f"192.168.0.{idx + 2}"
        command = f"cefroute add ccnx:/test udp {next_hop_ip} -d ./{node_name}"
        print(node_name, "command:", command)
        info(net.hosts[idx].cmd(command))


def start_csmgrd(net, host_num):
    for idx in range(1, host_num):
        node_name = f"h{idx}"
        command = f"csmgrdstart -d ./{node_name} > {node_name}-csmgrd-log"
        print(node_name, "command:", command)
        info(net.hosts[idx].cmd(command))
        time.sleep(1)


def stop_csmgrd(net, host_num):
    for idx in range(1, host_num):
        command = f"csmgrdstop -d ./h{idx}"
        info("hosts[", idx, "]:", command, "\n")
        net.hosts[idx].cmd(command)


def run_mesh_topology(host_num, switch_num):
    if host_num < 3:
        sys.exit("host count must be at least 3")
    if switch_num < 2:
        sys.exit("mesh topology requires at least 2 switches")

    ensure_node_dirs(host_num)

    topo = MeshTopo(hosts=host_num, switches=switch_num)
    net = Mininet(topo=topo, waitConnected=True)
    net.start()

    set_ip_addr(net, host_num, switch_num)

    for idx in range(host_num):
        node_name = f"h{idx}"
        print(node_name, "command:", "ifconfig")
        info(net.hosts[idx].cmd("ifconfig"))

    start_csmgrd(net, host_num)

    for idx in range(host_num):
        node_name = f"h{idx}"
        command = f"cefnetdstart -d ./{node_name} > {node_name}-cefnetd-log"
        print(node_name, "command:", command)
        info(net.hosts[idx].cmd(command))
        time.sleep(1)

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
        command = f"cefnetdstop -d ./h{idx}"
        info("hosts[", idx, "]:", command, "\n")
        net.hosts[idx].cmd(command)

    stop_csmgrd(net, host_num)
    net.stop()


class MeshTopo(Topo):
    "Mesh topology where each host connects to every switch"

    # pylint: disable=arguments-differ
    def build(self, hosts, switches, **_kwargs):
        host_nodes = [self.addHost(f"h{idx}") for idx in range(hosts)]
        switch_nodes = [self.addSwitch(f"s{idx}") for idx in range(switches)]

        for host_idx, host in enumerate(host_nodes):
            for switch in switch_nodes:
                self.addLink(host, switch)


def main():
    parser = argparse.ArgumentParser(
        description="Cefore mesh topology (hosts connect to all switches)"
    )
    parser.add_argument("--hosts", type=int, default=3, help="number of hosts")
    parser.add_argument("--switches", type=int, default=2, help="number of switches")
    args = parser.parse_args()

    setLogLevel("info")
    run_mesh_topology(args.hosts, args.switches)


if __name__ == "__main__":
    main()
