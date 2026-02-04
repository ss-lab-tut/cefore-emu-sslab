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
            dest_network: Destination network (e.g., "192.168.201.0/24").
            gateway: Gateway IP address.
        """
        host = net.get(host_name)
        if host is None:
            info(f"*** Warning: host {host_name} not found\n")
            return

        cmd = f"route add -net {dest_network} gw {gateway}"
        info(f"*** Adding route in {host_name}: {cmd}\n")
        host.cmd(cmd)
        self.routes_to_cleanup.append((host, f"route del -net {dest_network}"))

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

    def cleanup(self) -> None:
        """Remove all created routes."""
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

        # Add routes from hosts to VM host network (192.168.201.0/24 pattern)
        vm_host_network = config.get("vm_host_network")
        if vm_host_network:
            for host_idx in hosts:
                host_name = f"h{host_idx}"
                bridge_manager.add_host_route(net, host_name, vm_host_network, gateway)
