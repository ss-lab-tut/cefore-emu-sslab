#!/usr/bin/env python

"""
Simple 3-node topology with WiFi bridge to external Cefore node.

Topology:
  h0 (consumer) --s0-- h1 (router) --s1-- h2 (publisher)
  10.0.0.1            10.0.0.2             10.1.0.3
                      10.1.0.2
         |
         s0 -- root (root ns)
                10.0.0.254
                |
           WiFi NIC (e.g. wlan0)
                |
      WiFi Cefore node (e.g. 192.168.11.5)
"""

import argparse
import time

from mininet.clean import cleanup as mn_cleanup
from mininet.cli import CLI
from mininet.log import info, setLogLevel
from mininet.net import Mininet
from mininet.topo import Topo
from mininet.util import irange

from .external_bridge import BridgeManager, cleanup_external_bridges
from .simple_three_nodes_two_switch import (
    ensure_node_dirs,
    cleanup_node_dirs,
    setIpAddr,
    startCsmgrd,
    stopCsmgrd,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Simple 3-node Cefore topology with WiFi bridge"
    )
    parser.add_argument(
        "--wifi-intf", required=True,
        help="WiFi interface name (e.g. wlan0)",
    )
    parser.add_argument(
        "--wifi-peer-ip", required=True,
        help="IP of the Cefore node on WiFi (e.g. 192.168.11.5)",
    )
    parser.add_argument(
        "--wifi-uri", default="ccnx:/test/wifi",
        help="Content URI on the WiFi node (default: ccnx:/test/wifi)",
    )
    parser.add_argument(
        "--no-cli", action="store_true",
        help="Skip Mininet CLI",
    )
    return parser.parse_args()


def wifi_subnet_from_ip(ip):
    """Derive /24 subnet from IP. e.g. 192.168.11.5 -> 192.168.11.0/24"""
    parts = ip.split(".")
    if len(parts) != 4:
        raise ValueError(f"invalid IPv4 address: {ip}")
    return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"


def setup_wifi_bridge(net, bridge_manager, wifi_intf, wifi_peer_ip):
    """Set up root namespace bridge, NAT, routing for WiFi access."""
    bridge_manager.connect_to_root_ns(net, "s0", "10.0.0.254/24", "10.0.0.0/24")
    bridge_manager.enable_normal_flow(net, "s0")
    bridge_manager.enable_ip_forwarding()
    bridge_manager.enable_nat("10.0.0.0/24", wifi_intf)
    bridge_manager.enable_proxy_arp()

    wifi_subnet = wifi_subnet_from_ip(wifi_peer_ip)
    bridge_manager.add_host_route(net, "h0", wifi_subnet, "10.0.0.254")
    bridge_manager.add_host_route(net, "h1", wifi_subnet, "10.0.0.254")


def setFib(net, hostNum, wifi_peer_ip, wifi_uri):
    """Set FIB for Mininet internal routes and WiFi URI."""
    # Internal FIB: h0 -> h1 -> h2
    for id in irange(0, (hostNum - 2)):
        nodeName = "h" + str(id)
        if nodeName == "h0":
            command = "cefroute add ccnx:/test udp 10.0.0.2 -d ./" + nodeName
            print(nodeName, "command:", command)
            info(net.hosts[id].cmd(command))
        else:  # h1
            command = "cefroute add ccnx:/test udp 10.1.0.3 -d ./" + nodeName
            print(nodeName, "command:", command)
            info(net.hosts[id].cmd(command))

    # WiFi URI: h0 -> WiFi peer directly
    command = f"cefroute add {wifi_uri} udp {wifi_peer_ip} -d ./h0"
    print("h0", "command:", command)
    info(net.hosts[0].cmd(command))


class simpleLinkTopo(Topo):
    """Simple topology with linear links."""

    def build(self, n, **_kwargs):
        hosts = [self.addHost("h%s" % h) for h in irange(0, (n - 1))]
        s0 = self.addSwitch("s0")
        s1 = self.addSwitch("s1")

        self.addLink(s0, hosts[0])
        self.addLink(s0, hosts[1])
        self.addLink(s1, hosts[1])
        self.addLink(s1, hosts[2])


def runSimpleLink():
    """Create and run simple link network with WiFi bridge."""
    args = parse_args()
    hostNum = 3
    bridge_manager = BridgeManager()

    ensure_node_dirs(hostNum)
    topo = simpleLinkTopo(n=hostNum)
    net = Mininet(topo=topo, waitConnected=True)
    net.start()

    try:
        setIpAddr(net, hostNum)

        for id in irange(0, (hostNum - 1)):
            nodeName = "h" + str(id)
            print(nodeName, "command:", "ifconfig")
            info(net.hosts[id].cmd("ifconfig"))

        startCsmgrd(net)

        for id in irange(0, (hostNum - 1)):
            nodeName = "h" + str(id)
            command = "cefnetdstart -d ./" + nodeName + " > " + nodeName + "-cefnetd-log"
            print(nodeName, "command:", command)
            info(net.hosts[id].cmd(command))
            time.sleep(1)

        setup_wifi_bridge(net, bridge_manager, args.wifi_intf, args.wifi_peer_ip)

        setFib(net, hostNum, args.wifi_peer_ip, args.wifi_uri)
        time.sleep(1)

        # Exec cefputfile at h2 (internal publisher)
        nodeName = "h2"
        command = (
            "cefputfile ccnx:/test -f ./sample-putfile -t 3000 -e 3000 -d ./"
            + nodeName
            + " > cefputfile-log"
        )
        print(nodeName, "command:", command)
        net.hosts[2].cmd(command)
        time.sleep(5)

        # Exec cefgetfile at h0 (internal content)
        nodeName = "h0"
        command = (
            "cefgetfile ccnx:/test -f ./recvfile_at_h0 -d ./"
            + nodeName
            + " > cefgetfile-log"
        )
        print(nodeName, "command:", command)
        net.hosts[0].cmd(command)

        if not args.no_cli:
            CLI(net)
    finally:
        bridge_manager.cleanup()
        cleanup_external_bridges()
        for id in irange(0, (hostNum - 1)):
            command = "cefnetdstop -d ./h" + str(id)
            info("hosts[", id, "]:", command, "\n")
            net.hosts[id].cmd(command)
        stopCsmgrd(net)
        net.stop()
        mn_cleanup()
        cleanup_node_dirs()


def main():
    setLogLevel("info")
    runSimpleLink()


if __name__ == "__main__":
    main()
