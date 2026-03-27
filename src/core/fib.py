"""Pure FIB computation logic (no Mininet dependency)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .graph import dijkstra_all


@dataclass
class LinkSubnet:
    """Represents a link's subnet information."""

    node_a: int
    node_b: int
    subnet: int


@dataclass
class Route:
    """A single FIB route entry."""

    source: int
    prefix: str
    next_hop: int
    next_hop_ip: str


def build_graph_and_subnets(mesh_links):
    """Build adjacency graph and link subnet mapping from mesh_links.

    Args:
        mesh_links: List of link definitions.

    Returns:
        Tuple of (host_num, graph dict, link_subnets dict).
    """
    host_num = 0
    for link in mesh_links:
        if "hosts" in link:
            host_num = max(host_num, max(link["hosts"]) + 1)
        else:
            host_num = max(host_num, max(link["host_a"], link["host_b"]) + 1)
    graph = {idx: set() for idx in range(host_num)}
    link_subnets = {}
    for link in mesh_links:
        if "hosts" in link:
            hosts = link["hosts"]
            subnet = link["subnet"]
            for idx, host_a in enumerate(hosts):
                for host_b in hosts[idx + 1 :]:
                    graph[host_a].add(host_b)
                    graph[host_b].add(host_a)
                    key = tuple(sorted((host_a, host_b)))
                    link_subnets[key] = subnet
            continue
        host_a = link["host_a"]
        host_b = link["host_b"]
        graph[host_a].add(host_b)
        graph[host_b].add(host_a)
        key = tuple(sorted((host_a, host_b)))
        link_subnets[key] = link["subnet"]
    return host_num, graph, link_subnets


def compute_fib(mesh_links, k_paths):
    """Compute FIB routes for all destinations with multiple next hops.

    Args:
        mesh_links: List of link definitions.
        k_paths: Number of best next hops per destination.

    Returns:
        List of Route objects.
    """
    host_num, graph, link_subnets = build_graph_and_subnets(mesh_links)
    all_dist = []
    for src in range(host_num):
        distances, _parents = dijkstra_all(graph, src)
        all_dist.append(distances)

    routes = []
    for src in range(host_num):
        for dest in range(host_num):
            if src == dest:
                continue
            prefix = f"ccnx:/test/example{dest + 1}"
            candidates = []
            for neighbor in graph[src]:
                dist_to_dest = all_dist[neighbor].get(dest)
                if dist_to_dest is None:
                    continue
                cost = 1 + dist_to_dest
                candidates.append((cost, neighbor))
            if not candidates:
                continue
            candidates.sort()
            next_hops = [neighbor for _cost, neighbor in candidates[:k_paths]]
            for next_hop in next_hops:
                link_key = tuple(sorted((src, next_hop)))
                subnet = link_subnets[link_key]
                next_hop_ip = f"192.168.{subnet}.{next_hop + 1}"
                routes.append(Route(
                    source=src,
                    prefix=prefix,
                    next_hop=next_hop,
                    next_hop_ip=next_hop_ip,
                ))
    return routes


def compute_fib_for_uris(mesh_links, k_paths, uri_publishers):
    """Compute FIB routes for multiple URIs with their respective publishers.

    Args:
        mesh_links: List of link definitions.
        k_paths: Number of shortest paths per destination.
        uri_publishers: Dict mapping URI prefix to publisher host ID.

    Returns:
        List of Route objects.
    """
    host_num, graph, link_subnets = build_graph_and_subnets(mesh_links)
    all_dist = []
    for src in range(host_num):
        distances, _parents = dijkstra_all(graph, src)
        all_dist.append(distances)

    routes = []
    for uri_prefix, publisher in uri_publishers.items():
        dest = publisher
        for src in range(host_num):
            if src == dest:
                continue
            candidates = []
            for neighbor in graph[src]:
                dist_to_dest = all_dist[neighbor].get(dest)
                if dist_to_dest is None:
                    continue
                cost = 1 + dist_to_dest
                candidates.append((cost, neighbor))
            if not candidates:
                continue
            candidates.sort()
            next_hops = [neighbor for _cost, neighbor in candidates[:k_paths]]
            for next_hop in next_hops:
                link_key = tuple(sorted((src, next_hop)))
                subnet = link_subnets[link_key]
                next_hop_ip = f"192.168.{subnet}.{next_hop + 1}"
                routes.append(Route(
                    source=src,
                    prefix=uri_prefix,
                    next_hop=next_hop,
                    next_hop_ip=next_hop_ip,
                ))
    return routes


# ---------------------------------------------------------------------------
# Pluggable routing strategies
# ---------------------------------------------------------------------------

class RoutingStrategy(ABC):
    """Abstract base class for FIB route computation strategies."""

    @abstractmethod
    def compute_routes(
        self,
        mesh_links,
        k_paths,
        uri_publishers=None,
    ) -> list[Route]:
        """Compute FIB routes.

        Args:
            mesh_links: List of link definitions (topology).
            k_paths: Number of best next hops per destination.
            uri_publishers: Optional dict mapping URI prefix to publisher host ID.
                If None, default prefixes (ccnx:/test/exampleN) are used.

        Returns:
            List of Route objects.
        """
        ...


class DijkstraStrategy(RoutingStrategy):
    """Default: per-source Dijkstra with k best next hops."""

    def compute_routes(self, mesh_links, k_paths, uri_publishers=None):
        if uri_publishers:
            return compute_fib_for_uris(mesh_links, k_paths, uri_publishers)
        return compute_fib(mesh_links, k_paths)


class ShortestPathOnlyStrategy(RoutingStrategy):
    """Single shortest path per destination (k=1 fixed)."""

    def compute_routes(self, mesh_links, k_paths, uri_publishers=None):
        if uri_publishers:
            return compute_fib_for_uris(mesh_links, 1, uri_publishers)
        return compute_fib(mesh_links, 1)


class EqualCostMultiPathStrategy(RoutingStrategy):
    """ECMP: all equal-cost next hops, k_paths is ignored."""

    def compute_routes(self, mesh_links, k_paths, uri_publishers=None):
        host_num, graph, link_subnets = build_graph_and_subnets(mesh_links)
        all_dist = [dijkstra_all(graph, src)[0] for src in range(host_num)]
        routes = []
        if uri_publishers:
            destinations = list(uri_publishers.items())
        else:
            destinations = [
                (f"ccnx:/test/example{d + 1}", d) for d in range(host_num)
            ]
        for prefix, dest in destinations:
            for src in range(host_num):
                if src == dest:
                    continue
                candidates = []
                for neighbor in graph[src]:
                    dist = all_dist[neighbor].get(dest)
                    if dist is not None:
                        candidates.append((1 + dist, neighbor))
                if not candidates:
                    continue
                candidates.sort()
                min_cost = candidates[0][0]
                for cost, neighbor in candidates:
                    if cost > min_cost:
                        break
                    key = tuple(sorted((src, neighbor)))
                    subnet = link_subnets[key]
                    routes.append(Route(
                        src, prefix, neighbor,
                        f"192.168.{subnet}.{neighbor + 1}",
                    ))
        return routes


_ROUTING_STRATEGIES = {
    "dijkstra": DijkstraStrategy,
    "shortest_path": ShortestPathOnlyStrategy,
    "ecmp": EqualCostMultiPathStrategy,
}


def get_routing_strategy(name="dijkstra"):
    """Get a routing strategy instance by name.

    Args:
        name: Strategy name (dijkstra, shortest_path, ecmp).

    Returns:
        RoutingStrategy instance.

    Raises:
        ValueError: If the strategy name is unknown.
    """
    cls = _ROUTING_STRATEGIES.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown routing strategy: {name}. "
            f"Available: {list(_ROUTING_STRATEGIES)}"
        )
    return cls()
