"""IPv4 addressing scheme for Cefore emulator link assignment.

All generated Cefore link addresses derive from a single /16 base network.
The model is: one /24 per link, 3rd octet = link subnet id, 4th octet = host_idx + 1.
"""

import ipaddress

from .topology import TopologyModel

DEFAULT_NETWORK_CIDR = "192.168.0.0/16"

# Every Cefore link is a /24 (see module docstring). Interface assignments must
# carry this netmask explicitly: ``ifconfig <iface> <ip>`` with no netmask falls
# back to the classful default (/8 for 10.x, /16 for 172.x), which collapses
# every interface onto one flat network and breaks per-link routing. Only
# 192.168.x.x happens to default to /24, which is why the bug stayed hidden.
LINK_PREFIXLEN = 24
LINK_NETMASK = str(ipaddress.IPv4Network(f"0.0.0.0/{LINK_PREFIXLEN}").netmask)


class AddressingScheme:
    """Computes Cefore link addresses from a configurable IPv4 /16 base.

    The addressing model matches the existing hardcoded scheme:
      host_ip(subnet_id, host_idx) == "<base0>.<base1>.<base2+subnet_id>.<host_idx+1>"
    """

    def __init__(self, network_cidr: str = DEFAULT_NETWORK_CIDR) -> None:
        net = ipaddress.IPv4Network(network_cidr, strict=False)
        if net.prefixlen != 16:
            raise ValueError(
                f"network_cidr must be an IPv4 /16 network (got {network_cidr!r} which is /{net.prefixlen})"
            )
        self._octets: tuple[int, int, int, int] = tuple(net.network_address.packed)  # type: ignore[assignment]

    def host_ip(self, subnet_id: int, host_idx: int) -> str:
        """Return the host IP for the given link subnet and host index.

        Adds subnet_id to the 3rd octet and uses host_idx+1 as the 4th octet.

        Args:
            subnet_id: Link subnet identifier (added to base 3rd octet).
            host_idx:  0-based host index. Becomes host_idx+1 in 4th octet.

        Raises:
            ValueError: If the computed octets fall outside valid ranges.
        """
        o2 = self._octets[2] + subnet_id
        o3 = host_idx + 1
        if not (0 <= o2 <= 255):
            raise ValueError(
                f"subnet_id {subnet_id} causes 3rd octet {o2} to exceed 255 "
                f"(base 3rd octet is {self._octets[2]})"
            )
        if not (1 <= o3 <= 254):
            raise ValueError(
                f"host_idx {host_idx} yields 4th octet {o3} which is outside 1–254"
            )
        return f"{self._octets[0]}.{self._octets[1]}.{o2}.{o3}"

    def link_network(self, subnet_id: int) -> str:
        """Return the /24 network address for the given link subnet.

        Args:
            subnet_id: Link subnet identifier.

        Returns:
            CIDR string, e.g. "192.168.3.0/24".
        """
        o2 = self._octets[2] + subnet_id
        if not (0 <= o2 <= 255):
            raise ValueError(f"subnet_id {subnet_id} causes 3rd octet {o2} to exceed 255")
        return f"{self._octets[0]}.{self._octets[1]}.{o2}.0/24"

    def root_gateway(self, subnet_id: int) -> str:
        """Return the root-namespace gateway address for the given link subnet.

        Conventionally uses .254 as the root NS host address.

        Args:
            subnet_id: Link subnet identifier.

        Returns:
            CIDR string, e.g. "192.168.3.254/24".
        """
        o2 = self._octets[2] + subnet_id
        if not (0 <= o2 <= 255):
            raise ValueError(f"subnet_id {subnet_id} causes 3rd octet {o2} to exceed 255")
        return f"{self._octets[0]}.{self._octets[1]}.{o2}.254/24"

    def canonical_host_ip(self, host_idx: int, mesh_links: list) -> str:
        """Return the canonical Cefore data-plane IP for a host.

        Picks the link with the lowest subnet_id that this host is attached to,
        and returns host_ip(subnet, host_idx) for that link.

        Supports both multi-host link format {"hosts": [...], "host_eth": {...}}
        and point-to-point format {"host_a": int, "host_b": int}.

        Args:
            host_idx:   0-based host index.
            mesh_links: List of link definition dicts (from MeshTopo.mesh_links).

        Raises:
            ValueError: If host_idx is not attached to any link.
        """
        best_subnet: int | None = None
        for link in TopologyModel(mesh_links).links_for_host(host_idx):
            if link.subnet is None:
                continue
            if best_subnet is None or link.subnet < best_subnet:
                best_subnet = link.subnet

        if best_subnet is None:
            raise ValueError(f"host {host_idx} is not attached to any mesh link")
        return self.host_ip(best_subnet, host_idx)
