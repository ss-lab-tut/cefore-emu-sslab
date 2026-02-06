"""Root namespace bridging for cross-VM communication."""

from typing import Any

from mininet.log import info
from mininet.net import Mininet
from mininet.node import Node


class BridgeManager:
    """Manage root namespace bridges and route cleanup."""

    def __init__(self):
        self.root_node = None
        self.root_intf = None
        self.routes_to_cleanup = []  # List of (node, del_cmd)

    def get_or_create_root(self) -> Node:
        """Get or create the root namespace node.

        Returns:
            Node in root namespace.
        """
        if self.root_node is None:
            self.root_node = Node("root", inNamespace=False)
        return self.root_node

    def connect_to_root_ns(
        self,
        net: Mininet,
        switch_name: str,
        root_ip: str,
        local_routes: str,
    ) -> None:
        """Connect Mininet hosts to root namespace via switch.

        Args:
            net: Mininet network instance.
            switch_name: Switch name to connect to root namespace.
            root_ip: IP address for root namespace node (e.g., "192.168.100.1/24").
            local_routes: Local Mininet host networks to route to (e.g., "192.168.1.0/24").
        """
        root = self.get_or_create_root()
        switch = net.get(switch_name)
        if switch is None:
            info(f"*** Warning: switch {switch_name} not found\n")
            return

        # Create link between root node and switch
        link = net.addLink(root, switch)
        self.root_intf = link.intf1

        # Set IP on root interface
        root.setIP(root_ip, intf=self.root_intf)

        # Add route from root ns to local Mininet hosts
        cmd = f"route add -net {local_routes} dev {self.root_intf}"
        info(f"*** Adding route in root ns: {cmd}\n")
        root.cmd(cmd)
        self.routes_to_cleanup.append((root, f"route del -net {local_routes}"))

    def add_host_route(
        self,
        net: Mininet,
        host_name: str,
        dest_network: str,
        gateway: str,
    ) -> None:
        """Add route from Mininet host to external network.

        Args:
            net: Mininet network instance.
            host_name: Host name to add route to.
            dest_network: Destination network (e.g., "192.168.201.0/24" or "default").
            gateway: Gateway IP address.
        """
        host = net.get(host_name)
        if host is None:
            info(f"*** Warning: host {host_name} not found\n")
            return

        if dest_network in ("default", "0.0.0.0/0"):
            cmd = f"ip route replace default via {gateway}"
            del_cmd = "ip route del default"
        else:
            cmd = f"route add -net {dest_network} gw {gateway}"
            del_cmd = f"route del -net {dest_network}"
        info(f"*** Adding route in {host_name}: {cmd}\n")
        host.cmd(cmd)
        self.routes_to_cleanup.append((host, del_cmd))

    def add_root_route(self, dest_network: str, gateway: str) -> None:
        """Add route from root namespace to external network.

        Args:
            dest_network: Destination network (e.g., "192.168.201.0/24").
            gateway: Gateway IP address (e.g., another VM's IP).
        """
        root = self.get_or_create_root()
        cmd = f"route add -net {dest_network} gw {gateway}"
        info(f"*** Adding route in root ns: {cmd}\n")
        root.cmd(cmd)
        self.routes_to_cleanup.append((root, f"route del -net {dest_network}"))

    def enable_ip_forwarding(self) -> None:
        """Enable IP forwarding on root namespace node."""
        root = self.get_or_create_root()
        root.cmd("sysctl -w net.ipv4.ip_forward=1")

    def enable_nat(self, local_routes: str, out_intf: str = None) -> None:
        """Enable NAT (masquerade) for local routes via outbound interface.

        Args:
            local_routes: Source network to masquerade (e.g., "192.168.1.0/24").
            out_intf: Outbound interface name. If None, auto-detected from default route.
        """
        root = self.get_or_create_root()
        if out_intf is None:
            result = root.cmd("ip route show default")
            parts = result.split()
            if "dev" in parts:
                idx = parts.index("dev")
                if idx + 1 < len(parts):
                    out_intf = parts[idx + 1]
        if not out_intf:
            info("*** Warning: could not detect outbound interface for NAT\n")
            return

        root_intf_name = str(self.root_intf)
        cmds = [
            f"iptables -t nat -A POSTROUTING -s {local_routes} -o {out_intf} -j MASQUERADE",
            f"iptables -A FORWARD -i {root_intf_name} -o {out_intf} -s {local_routes} -j ACCEPT",
            f"iptables -A FORWARD -i {out_intf} -o {root_intf_name} -d {local_routes} -m state --state RELATED,ESTABLISHED -j ACCEPT",
        ]
        for cmd in cmds:
            info(f"*** NAT: {cmd}\n")
            root.cmd(cmd)
        for cmd in cmds:
            del_cmd = cmd.replace(" -A ", " -D ")
            self.routes_to_cleanup.append((root, del_cmd))

    def enable_proxy_arp(self) -> None:
        """Enable Proxy ARP on root namespace interface.

        This allows the root node to respond to ARP requests for
        hosts in different subnets, enabling L3 routing across
        subnet boundaries.
        """
        root = self.get_or_create_root()
        if self.root_intf is None:
            info("*** Warning: root interface not set, cannot enable proxy ARP\n")
            return

        root_intf_name = str(self.root_intf)
        cmds = [
            f"sysctl -w net.ipv4.conf.{root_intf_name}.proxy_arp=1",
            "sysctl -w net.ipv4.conf.all.proxy_arp=1",
        ]
        for cmd in cmds:
            info(f"*** Proxy ARP: {cmd}\n")
            root.cmd(cmd)
        # cleanup で restore
        self.routes_to_cleanup.append(
            (root, f"sysctl -w net.ipv4.conf.{root_intf_name}.proxy_arp=0")
        )
        self.routes_to_cleanup.append((root, "sysctl -w net.ipv4.conf.all.proxy_arp=0"))

    def cleanup(self) -> None:
        """Remove all created routes and NAT rules."""
        for node, del_cmd in reversed(self.routes_to_cleanup):
            info(f"*** Removing route: {del_cmd}\n")
            node.cmd(del_cmd)
        self.routes_to_cleanup.clear()


def extract_gateway_from_ip(ip_with_prefix: str) -> str:
    """Extract gateway IP from IP/prefix notation.

    For "192.168.100.1/24", returns "192.168.100.1".

    Args:
        ip_with_prefix: IP address with optional prefix (e.g., "192.168.100.1/24").

    Returns:
        IP address without prefix.
    """
    return ip_with_prefix.split("/")[0]


def parse_bridge_args(values: list[str] | None) -> list[dict[str, Any]]:
    """Parse --bridge CLI arguments.

    Format: switch,root_ip,local_routes[,external_routes,gateway]

    Args:
        values: List of bridge argument strings.

    Returns:
        List of bridge configuration dictionaries.
    """
    entries = []
    for value in values or []:
        parts = [part.strip() for part in value.split(",")]
        if len(parts) < 3:
            raise ValueError(
                "bridge format is switch,root_ip,local_routes[,external_routes,gateway]"
            )
        entry = {
            "switch": parts[0],
            "root_ip": parts[1],
            "local_routes": parts[2],
        }
        if len(parts) >= 5:
            entry["external_routes"] = parts[3]
            entry["gateway"] = parts[4]
        entries.append(entry)
    return entries


def setup_bridges(
    net: Mininet,
    bridge_manager: BridgeManager,
    bridge_configs: list[dict[str, Any]],
    host_num: int,
) -> None:
    """Set up all bridge configurations.

    Args:
        net: Mininet network instance.
        bridge_manager: BridgeManager instance to use.
        bridge_configs: List of bridge configuration dicts.
        host_num: Total number of hosts in the network.
    """
    for config in bridge_configs:
        switch = config["switch"]
        root_ip = config["root_ip"]
        local_routes = config["local_routes"]

        # Connect root namespace to switch
        bridge_manager.connect_to_root_ns(net, switch, root_ip, local_routes)

        # Extract gateway from root_ip for host routes
        gateway = extract_gateway_from_ip(root_ip)

        # Get list of hosts to configure (default: all hosts)
        hosts = config.get("hosts")
        if hosts is None:
            hosts = list(range(host_num))

        # Add routes to external network for each host
        external_routes = config.get("external_routes")
        ext_gateway = config.get("gateway")

        if external_routes:
            # Add route from root ns to external network via gateway
            if ext_gateway:
                bridge_manager.add_root_route(external_routes, ext_gateway)

            # Add routes from hosts to external network via root node
            for host_idx in hosts:
                host_name = f"h{host_idx}"
                bridge_manager.add_host_route(net, host_name, external_routes, gateway)

        # NAT enablement
        use_nat = config.get("nat", False)
        if use_nat:
            bridge_manager.enable_ip_forwarding()
            nat_out = config.get("nat_out")
            bridge_manager.enable_nat(local_routes, nat_out)

        # Proxy ARP enablement (for cross-subnet L2 resolution)
        use_proxy_arp = config.get("proxy_arp", False)
        if use_proxy_arp:
            bridge_manager.enable_proxy_arp()

        # Add routes from hosts to VM host network (192.168.201.0/24 pattern)
        vm_host_network = config.get("vm_host_network")
        if vm_host_network:
            for host_idx in hosts:
                host_name = f"h{host_idx}"
                bridge_manager.add_host_route(net, host_name, vm_host_network, gateway)
