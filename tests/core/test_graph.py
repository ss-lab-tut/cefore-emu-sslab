"""Tests for src.core.graph."""


from src.core.graph import (
    UnionFind,
    compute_distances,
    dijkstra_all,
    k_shortest_paths,
    path_cost,
    select_k_centers,
    shortest_path,
)


# ── UnionFind ──


class TestUnionFind:
    def test_initially_disconnected(self):
        uf = UnionFind(3)
        assert not uf.connected(0, 1)
        assert not uf.connected(1, 2)

    def test_union_connects(self):
        uf = UnionFind(3)
        assert uf.union(0, 1) is True
        assert uf.connected(0, 1)

    def test_transitivity(self):
        uf = UnionFind(3)
        uf.union(0, 1)
        uf.union(1, 2)
        assert uf.connected(0, 2)

    def test_union_already_connected_returns_false(self):
        uf = UnionFind(2)
        uf.union(0, 1)
        assert uf.union(0, 1) is False

    def test_path_compression(self):
        uf = UnionFind(5)
        uf.union(0, 1)
        uf.union(1, 2)
        uf.union(2, 3)
        uf.union(3, 4)
        # After find, all should point closer to root
        root = uf.find(4)
        assert uf.find(0) == root
        assert uf.find(2) == root


# ── shortest_path ──


class TestShortestPath:
    def test_source_equals_target(self, triangle_graph):
        assert shortest_path(triangle_graph, 0, 0) == [0]

    def test_linear_path(self, linear_graph):
        path = shortest_path(linear_graph, 0, 4)
        assert path == [0, 1, 2, 3, 4]

    def test_no_path_returns_none(self, disconnected_graph):
        assert shortest_path(disconnected_graph, 0, 2) is None

    def test_banned_edges(self, triangle_graph):
        # Ban edge 0-1, must go 0->2->1
        path = shortest_path(
            triangle_graph, 0, 1, banned_edges={frozenset((0, 1))}
        )
        assert path == [0, 2, 1]

    def test_banned_nodes(self, diamond_graph):
        # Ban node 1, must go 0->2->3
        path = shortest_path(diamond_graph, 0, 3, banned_nodes={1})
        assert path == [0, 2, 3]

    def test_custom_weight_fn(self, diamond_graph):
        # Make path through node 2 expensive
        def weight(a, b):
            if {a, b} == {0, 2}:
                return 10
            return 1

        path = shortest_path(diamond_graph, 0, 3, weight_fn=weight)
        assert path == [0, 1, 3]

    def test_banned_node_still_allows_target(self, triangle_graph):
        # Target node should not be banned even if in banned_nodes
        path = shortest_path(triangle_graph, 0, 2, banned_nodes={2})
        assert path is not None
        assert path[-1] == 2


# ── dijkstra_all ──


class TestDijkstraAll:
    def test_distances_triangle(self, triangle_graph):
        distances, parents = dijkstra_all(triangle_graph, 0)
        assert distances == {0: 0, 1: 1, 2: 1}

    def test_parents_chain(self, linear_graph):
        distances, parents = dijkstra_all(linear_graph, 0)
        assert distances[4] == 4
        assert parents[0] is None
        assert parents[1] == 0
        assert parents[4] == 3


# ── path_cost ──


class TestPathCost:
    def test_single_node_zero(self):
        assert path_cost([0], lambda a, b: 1) == 0

    def test_multi_node_sum(self):
        assert path_cost([0, 1, 2], lambda a, b: 1) == 2

    def test_weighted_sum(self):
        def w(a, b):
            return abs(b - a) * 10

        assert path_cost([0, 1, 3], w) == 10 + 20


# ── k_shortest_paths ──


class TestKShortestPaths:
    def test_single_path_linear(self, linear_graph):
        paths = k_shortest_paths(linear_graph, 0, 4, 3)
        assert len(paths) == 1
        assert paths[0] == [0, 1, 2, 3, 4]

    def test_two_paths_diamond(self, diamond_graph):
        paths = k_shortest_paths(diamond_graph, 0, 3, 2)
        assert len(paths) == 2
        assert [0, 1, 3] in paths
        assert [0, 2, 3] in paths

    def test_no_path_returns_empty(self, disconnected_graph):
        paths = k_shortest_paths(disconnected_graph, 0, 2, 3)
        assert paths == []

    def test_k_paths_zero_returns_empty(self, triangle_graph):
        paths = k_shortest_paths(triangle_graph, 0, 1, 0)
        assert paths == []


# ── compute_distances ──


class TestComputeDistances:
    def test_bfs_mode(self, linear_graph):
        dists = compute_distances(linear_graph, 0)
        assert dists == {0: 0, 1: 1, 2: 2, 3: 3, 4: 4}

    def test_weighted_mode(self, linear_graph):
        dists = compute_distances(linear_graph, 0, weight_fn=lambda a, b: 2)
        assert dists == {0: 0, 1: 2, 2: 4, 3: 6, 4: 8}

    def test_disconnected_unreachable(self, disconnected_graph):
        dists = compute_distances(disconnected_graph, 0)
        assert 0 in dists
        assert 1 in dists
        assert 2 not in dists


# ── select_k_centers ──


class TestSelectKCenters:
    def test_k_one(self, triangle_graph):
        centers = select_k_centers(triangle_graph, 1)
        assert len(centers) == 1
        assert centers[0] == 0  # first node

    def test_k_greater_than_nodes(self, triangle_graph):
        centers = select_k_centers(triangle_graph, 10)
        assert len(centers) == 3

    def test_empty_graph(self):
        centers = select_k_centers({}, 3)
        assert centers == []

    def test_k_zero(self, triangle_graph):
        centers = select_k_centers(triangle_graph, 0)
        assert centers == []

    def test_exclude_nodes_not_selected(self):
        # 4-node line: 0-1-2-3. Exclude node 0 (would normally be first center).
        graph = {0: {1}, 1: {0, 2}, 2: {1, 3}, 3: {2}}
        centers = select_k_centers(graph, 2, exclude={0})
        assert 0 not in centers
        assert len(centers) == 2

    def test_exclude_guarantees_count(self):
        # 5-node graph where node 4 would be selected by farthest-first.
        # Excluding it must still yield count=2 from the remaining nodes.
        graph = {0: {1}, 1: {0, 2}, 2: {1, 3}, 3: {2, 4}, 4: {3}}
        centers = select_k_centers(graph, 2, exclude={4})
        assert 4 not in centers
        assert len(centers) == 2
