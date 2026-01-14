#!/usr/bin/env python

"""
Line topology example using Cefore and Mininet.

Defaults to 3 hosts and 2 switches: h0-s0-h1-s1-h2.
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
from mininet.util import irange


def ensure_node_dirs(host_num):
    for idx in range(host_num):
        if idx % 2 == 1:
            node_dir = "h1"
            template = node_dir
        elif idx % 2 == 0:
            node_dir = "h0"
            template = node_dir
        else:
            node_dir = f"h{idx}"
            template = node_dir
        shutil.copytree(template, node_dir)


def set_ip_addr(net, host_num):
    # Assign a /24 per switch (link index) in the line.
    for idx in irange(0, host_num - 1):
        node_name = f"h{idx}"
        right_ip = f"192.168.{idx}.{idx + 1}"
        left_ip = f"192.168.{idx - 1}.{idx}"
        if idx == 0:
            command = f"ifconfig {node_name}-eth1 {right_ip}"
            print(node_name, "command:", command)
            net.hosts[idx].cmd(command)
        elif idx == host_num - 1:
            command = f"ifconfig {node_name}-eth0 {left_ip}"
            print(node_name, "command:", command)
            net.hosts[idx].cmd(command)
        else:
            command = f"ifconfig {node_name}-eth0 {left_ip}"
            print(node_name, "command:", command)
            net.hosts[idx].cmd(command)
            command = f"ifconfig {node_name}-eth1 {right_ip}"
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


def stop_csmgrd(net, host_num):
    for idx in range(0, host_num - 1):
        command = f"csmgrdstop -d ./h{idx}"
        info("hosts[", idx, "]:", command, "\n")
        net.hosts[idx].cmd(command)


def start_cefnetd(net, host_num):
    for idx in range(0, host_num - 1):
        node_name = f"h{idx}"
        command = f"cefnetdstart -d ./{node_name} > {node_name}-cefnetd-log"
        print(node_name, "command:", command)
        info(net.hosts[idx].cmd(command))
        time.sleep(1)


def stop_cefnetd(net, host_num):
    for idx in range(0, host_num - 1):
        command = f"cefnetdstop -F -d ./h{idx}"
        info("hosts[", idx, "]:", command, "\n")
        net.hosts[idx].cmd(command)


def run_line_topology(host_num, switch_num):
    if host_num < 3:
        sys.exit("host count must be at least 3")
    if switch_num != host_num - 1:
        sys.exit("for a line topology, switches must equal hosts - 1")

    ensure_node_dirs(host_num)

    topo = LineTopo(hosts=host_num, switches=switch_num)
    net = Mininet(topo=topo, waitConnected=True)
    net.start()

    set_ip_addr(net, host_num)

    for idx in irange(0, host_num - 1):
        node_name = f"h{idx}"
        print(node_name, "command:", "ifconfig")
        info(net.hosts[idx].cmd("ifconfig"))

    start_csmgrd(net, host_num)

    start_cefnetd(net, host_num)

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

    stop_cefnetd(net, host_num)

    stop_csmgrd(net, host_num)
    net.stop()


class LineTopo(Topo):
    "Simple topology with linear links"

    # pylint: disable=arguments-differ
    def build(self, hosts, switches, **_kwargs):
        host_nodes = [self.addHost(f"h{idx}") for idx in range(hosts)]
        switch_nodes = [self.addSwitch(f"s{idx}") for idx in range(switches)]

        for idx in range(switches):
            self.addLink(switch_nodes[idx], host_nodes[idx])
            self.addLink(switch_nodes[idx], host_nodes[idx + 1])


def main():
    parser = argparse.ArgumentParser(
        description="Cefore line topology (default: 3 hosts, 2 switches)"
    )
    parser.add_argument("--hosts", type=int, default=3, help="number of hosts")
    parser.add_argument("--switches", type=int, default=2, help="number of switches")
    args = parser.parse_args()

    setLogLevel("info")
    run_line_topology(args.hosts, args.switches)


if __name__ == "__main__":
    main()
