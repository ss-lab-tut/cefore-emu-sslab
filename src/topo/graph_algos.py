"""Graph algorithms for topology routing (pure functions)."""

import heapq
from collections import deque


class UnionFind:
    """Union-Find data structure for connectivity tracking."""

    def __init__(self, n):
        """Initialize Union-Find with n elements.

        Args:
            n: Number of elements (0 to n-1).
        """
        self.parent = list(range(n))
        self.size = [1] * n

    def find(self, x):
        """Find root of element with path compression.

        Args:
            x: Element to find root of.

        Returns:
            Root element.
        """
        while x != self.parent[x]:
            self.parent[x] = self.parent[self.parent[x]]  # path compression
            x = self.parent[x]
        return x

    def connected(self, a, b):
        """Check if two elements are in the same set.

        Args:
            a: First element.
            b: Second element.

        Returns:
            True if connected, False otherwise.
        """
        return self.find(a) == self.find(b)

    def union(self, a, b):
        """Unite two elements into the same set.

        Args:
            a: First element.
            b: Second element.

        Returns:
            True if elements were in different sets and are now united,
            False if they were already in the same set.
        """
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self.size[ra] < self.size[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.size[ra] += self.size[rb]
        return True


def shortest_path(
    graph, source, target, banned_edges=None, banned_nodes=None, weight_fn=None
):
    """Compute shortest path using Dijkstra's algorithm.

    Args:
        graph: Dict mapping node to set of neighbors.
        source: Starting node.
        target: Destination node.
        banned_edges: Set of frozenset edges to exclude.
        banned_nodes: Set of nodes to exclude (except target).
        weight_fn: Optional function (a, b) -> cost. Defaults to 1.

    Returns:
        List of nodes from source to target, or None if no path.
    """
    if source == target:
        return [source]
    banned_edges = banned_edges or set()
    banned_nodes = banned_nodes or set()
    weight_fn = weight_fn or (lambda _a, _b: 1)
    distances = {source: 0}
    parents = {source: None}
    heap = [(0, source)]
    while heap:
        dist, node = heapq.heappop(heap)
        if node == target:
            break
        if dist != distances.get(node):
            continue
        for neighbor in sorted(graph[node]):
            edge = frozenset((node, neighbor))
            if edge in banned_edges:
                continue
            if neighbor in banned_nodes and neighbor != target:
                continue
            new_dist = dist + weight_fn(node, neighbor)
            if new_dist < distances.get(neighbor, float("inf")):
                distances[neighbor] = new_dist
                parents[neighbor] = node
                heapq.heappush(heap, (new_dist, neighbor))
    if target not in parents:
        return None
    path = []
    node = target
    while node is not None:
        path.append(node)
        node = parents[node]
    return list(reversed(path))


def dijkstra_all(graph, source, weight_fn=None):
    """Compute shortest distances from source to all reachable nodes.

    Args:
        graph: Dict mapping node to set of neighbors.
        source: Starting node.
        weight_fn: Optional function (a, b) -> cost. Defaults to 1.

    Returns:
        Tuple of (distances dict, parents dict).
    """
    weight_fn = weight_fn or (lambda _a, _b: 1)
    distances = {source: 0}
    parents = {source: None}
    heap = [(0, source)]
    while heap:
        dist, node = heapq.heappop(heap)
        if dist != distances.get(node):
            continue
        for neighbor in sorted(graph[node]):
            new_dist = dist + weight_fn(node, neighbor)
            if new_dist < distances.get(neighbor, float("inf")):
                distances[neighbor] = new_dist
                parents[neighbor] = node
                heapq.heappush(heap, (new_dist, neighbor))
    return distances, parents


def path_cost(path, weight_fn):
    """Compute total cost of a path.

    Args:
        path: List of nodes.
        weight_fn: Function (a, b) -> cost.

    Returns:
        Total cost as sum of edge weights.
    """
    if len(path) < 2:
        return 0
    return sum(weight_fn(path[idx], path[idx + 1]) for idx in range(len(path) - 1))


def k_shortest_paths(graph, source, target, k_paths, weight_fn=None):
    """Compute k shortest paths using Yen's algorithm.

    Args:
        graph: Dict mapping node to set of neighbors.
        source: Starting node.
        target: Destination node.
        k_paths: Maximum number of paths to find.
        weight_fn: Optional function (a, b) -> cost. Defaults to 1.

    Returns:
        List of paths (each path is a list of nodes).
    """
    weight_fn = weight_fn or (lambda _a, _b: 1)
    first = shortest_path(graph, source, target, weight_fn=weight_fn)
    if not first:
        return []
    paths = [first]
    candidates = []
    for _ in range(1, k_paths):
        previous = paths[-1]
        for i in range(len(previous) - 1):
            spur_node = previous[i]
            root_path = previous[: i + 1]
            banned_edges = set()
            banned_nodes = set(root_path[:-1])
            for path in paths:
                if len(path) > i and path[: i + 1] == root_path:
                    banned_edges.add(frozenset((path[i], path[i + 1])))
            spur_path = shortest_path(
                graph,
                spur_node,
                target,
                banned_edges,
                banned_nodes,
                weight_fn=weight_fn,
            )
            if not spur_path:
                continue
            total_path = root_path[:-1] + spur_path
            candidates.append(total_path)
        if not candidates:
            break
        candidates.sort(key=lambda p: (path_cost(p, weight_fn), p))
        next_path = candidates.pop(0)
        if next_path not in paths:
            paths.append(next_path)
    return paths[:k_paths]


def compute_distances(graph, source, weight_fn=None):
    """Compute distances from source using BFS or Dijkstra.

    Args:
        graph: Dict mapping node to set/list of neighbors.
        source: Starting node.
        weight_fn: Optional function (a, b) -> cost. If None, uses BFS (unit weight).

    Returns:
        Dict mapping node to distance from source.
    """
    if weight_fn is None:
        distances = {source: 0}
        queue = deque([source])
        while queue:
            node = queue.popleft()
            for neighbor in sorted(graph.get(node, [])):
                if neighbor not in distances:
                    distances[neighbor] = distances[node] + 1
                    queue.append(neighbor)
        return distances
    distances = {source: 0}
    heap = [(0, source)]
    while heap:
        dist, node = heapq.heappop(heap)
        if dist != distances.get(node):
            continue
        for neighbor in sorted(graph.get(node, [])):
            new_dist = dist + weight_fn(node, neighbor)
            if new_dist < distances.get(neighbor, float("inf")):
                distances[neighbor] = new_dist
                heapq.heappush(heap, (new_dist, neighbor))
    return distances


def select_k_centers(graph, k, weight_fn=None):
    """Select k center nodes using greedy farthest-first algorithm.

    Args:
        graph: Dict mapping node to set/list of neighbors.
        k: Number of centers to select.
        weight_fn: Optional function (a, b) -> cost.

    Returns:
        List of selected center node IDs.
    """
    nodes = sorted(graph.keys())
    if not nodes or k <= 0:
        return []
    centers = [nodes[0]]
    min_dist = compute_distances(graph, centers[0], weight_fn)
    while len(centers) < k:
        farthest = max(
            nodes,
            key=lambda node: (min_dist.get(node, float("inf")), -node),
        )
        if farthest in centers:
            break
        centers.append(farthest)
        dist_map = compute_distances(graph, farthest, weight_fn)
        for node in nodes:
            min_dist[node] = min(
                min_dist.get(node, float("inf")), dist_map.get(node, float("inf"))
            )
    return centers
