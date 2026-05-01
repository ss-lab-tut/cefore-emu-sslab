"""Network configuration application (Mininet-dependent)."""

import shlex

from mininet.log import info

from ..core.addressing import AddressingScheme
from ..core.fib import compute_fib, compute_fib_for_uris, get_routing_strategy
from ..core.protocols import normalize_route_protocol


def _route_protocol_arg(protocol: str | None) -> str:
    """Return a shell-safe route protocol argument."""
    return shlex.quote(normalize_route_protocol(protocol))


def apply_ip_addr(net, mesh_links, scheme=None):
    """Assign IP addresses to all host interfaces.

    Args:
        net: Mininet network instance.
        mesh_links: List of link definitions.
        scheme: AddressingScheme for IP generation (defaults to 192.168.0.0/16).
    """
    if scheme is None:
        scheme = AddressingScheme()
    for link in mesh_links:
        subnet = link["subnet"]
        if "hosts" in link:
            for host_idx in link["hosts"]:
                eth_idx = link["host_eth"][host_idx]
                node_name = f"h{host_idx}"
                ip = scheme.host_ip(subnet, host_idx)
                command = f"ifconfig {node_name}-eth{eth_idx} {ip}"
                print(node_name, "command:", command)
                net.hosts[host_idx].cmd(command)
            continue
        for host_idx, eth_idx in (
            (link["host_a"], link["host_a_eth"]),
            (link["host_b"], link["host_b_eth"]),
        ):
            node_name = f"h{host_idx}"
            ip = scheme.host_ip(subnet, host_idx)
            command = f"ifconfig {node_name}-eth{eth_idx} {ip}"
            print(node_name, "command:", command)
            net.hosts[host_idx].cmd(command)


def apply_fib(net, mesh_links, k_paths, strategy="dijkstra", uri_publishers=None, scheme=None):
    """Apply FIB entries using the specified routing strategy.

    Args:
        net: Mininet network instance.
        mesh_links: List of link definitions.
        k_paths: Number of best next hops per destination.
        strategy: Routing strategy name (dijkstra, shortest_path, ecmp).
        uri_publishers: Optional dict mapping URI prefix to publisher host ID.
        scheme: AddressingScheme for IP generation (defaults to 192.168.0.0/16).
    """
    strat = get_routing_strategy(strategy)
    routes = strat.compute_routes(mesh_links, k_paths, uri_publishers, scheme=scheme)
    for route in routes:
        node_name = f"h{route.source}"
        command = f"cefroute add {shlex.quote(route.prefix)} udp {shlex.quote(route.next_hop_ip)} -d ./{node_name}"
        print(node_name, "command:", command)
        info(net.hosts[route.source].cmd(command))


def cefroute_del(net, host_idx, prefix, protocol, next_hop, node_dir=None):
    """Delete a FIB entry via cefroute del.

    Args:
        net: Mininet network instance.
        host_idx: Host index.
        prefix: Content name prefix (e.g. "ccnx:/test/sample").
        protocol: Protocol (e.g. "udp").
        next_hop: Next hop IP address.
        node_dir: Node directory (defaults to ./h{host_idx}).
    """
    node_name = f"h{host_idx}"
    if node_dir is None:
        node_dir = f"./{node_name}"
    command = (
        f"cefroute del {shlex.quote(prefix)} {_route_protocol_arg(protocol)} "
        f"{shlex.quote(next_hop)} -d {node_dir}"
    )
    print(node_name, "command:", command)
    info(net.hosts[host_idx].cmd(command))


def cefroute_enable(net, host_idx, prefix, protocol, next_hop, node_dir=None):
    """Enable a FIB entry via cefroute enable.

    Args:
        net: Mininet network instance.
        host_idx: Host index.
        prefix: Content name prefix (e.g. "ccnx:/test/sample").
        protocol: Protocol (e.g. "udp").
        next_hop: Next hop IP address.
        node_dir: Node directory (defaults to ./h{host_idx}).
    """
    node_name = f"h{host_idx}"
    if node_dir is None:
        node_dir = f"./{node_name}"
    command = (
        f"cefroute enable {shlex.quote(prefix)} {_route_protocol_arg(protocol)} "
        f"{shlex.quote(next_hop)} -d {node_dir}"
    )
    print(node_name, "command:", command)
    info(net.hosts[host_idx].cmd(command))


def apply_fib_for_uris(net, mesh_links, k_paths, uri_publishers, scheme=None):
    """Apply FIB entries for multiple URIs (legacy wrapper).

    Args:
        net: Mininet network instance.
        mesh_links: List of link definitions.
        k_paths: Number of shortest paths per destination.
        uri_publishers: Dict mapping URI prefix to publisher host ID.
        scheme: AddressingScheme for IP generation (defaults to 192.168.0.0/16).
    """
    apply_fib(net, mesh_links, k_paths, uri_publishers=uri_publishers, scheme=scheme)
