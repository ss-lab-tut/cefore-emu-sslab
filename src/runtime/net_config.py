"""Network configuration application (Mininet-dependent)."""

from mininet.log import info

from ..core.addressing import AddressingScheme
from ..core.fib import get_routing_strategy
from ..core.protocols import normalize_route_protocol
from ..core.topology import TopologyModel
from .command_runner import MininetCommandRunner


def apply_ip_addr(net, mesh_links, scheme=None):
    """Assign IP addresses to all host interfaces.

    Args:
        net: Mininet network instance.
        mesh_links: List of link definitions.
        scheme: AddressingScheme for IP generation (defaults to 192.168.0.0/16).
    """
    if scheme is None:
        scheme = AddressingScheme()
    runner = MininetCommandRunner(net)
    for link in TopologyModel(mesh_links).links:
        for host_idx in link.hosts:
            eth_idx = link.eth_of(host_idx)
            node_name = f"h{host_idx}"
            ip = scheme.host_ip(link.subnet, host_idx)
            argv = ["ifconfig", f"{node_name}-eth{eth_idx}", str(ip)]
            print(node_name, "command:", argv)
            runner.run(node_name, argv)


def apply_fib_routes(net, routes, source: int | None = None):
    """Apply precomputed FIB route entries.

    Args:
        net: Mininet network instance.
        routes: Iterable of Route objects.
        source: Optional host index filter. When provided, only routes for that
            source host are applied.
    """
    runner = MininetCommandRunner(net)
    for route in routes:
        if source is not None and route.source != source:
            continue
        node_name = f"h{route.source}"
        argv = [
            "cefroute", "add", route.prefix, "udp", route.next_hop_ip,
            "-d", f"./{node_name}",
        ]
        print(node_name, "command:", argv)
        info(runner.run(node_name, argv).stdout)


def apply_fib(
    net, mesh_links, k_paths, strategy="dijkstra", uri_publishers=None, scheme=None
):
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
    apply_fib_routes(net, routes)
    return routes


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
    argv = [
        "cefroute", "del", prefix, normalize_route_protocol(protocol), next_hop,
        "-d", node_dir,
    ]
    print(node_name, "command:", argv)
    result = MininetCommandRunner(net).run(node_name, argv)
    info(result.stdout)
    return result.returncode == 0


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
    argv = [
        "cefroute", "enable", prefix, normalize_route_protocol(protocol), next_hop,
        "-d", node_dir,
    ]
    print(node_name, "command:", argv)
    result = MininetCommandRunner(net).run(node_name, argv)
    info(result.stdout)
    return result.returncode == 0
