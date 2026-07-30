"""Tests for src.core.fib."""

from src.core.fib import (
    LinkSubnet,
    Route,
    build_graph_and_subnets,
    compute_fib,
    compute_fib_for_uris,
    EqualCostMultiPathStrategy,
    ShortestPathOnlyStrategy,
)


# ── dataclass tests ──


def test_link_subnet_creation():
    ls = LinkSubnet(node_a=0, node_b=1, subnet=5)
    assert ls.node_a == 0
    assert ls.node_b == 1
    assert ls.subnet == 5
    assert ls == LinkSubnet(0, 1, 5)


def test_route_creation():
    r = Route(source=0, prefix="ccnx:/test/example1", next_hop=1, next_hop_ip="192.168.0.2")
    assert r.source == 0
    assert r.prefix == "ccnx:/test/example1"
    assert r.next_hop == 1
    assert r.next_hop_ip == "192.168.0.2"
    assert r == Route(0, "ccnx:/test/example1", 1, "192.168.0.2")


# ── build_graph_and_subnets ──


def test_build_graph_point_to_point(sample_mesh_links):
    host_num, graph, link_subnets = build_graph_and_subnets(sample_mesh_links)
    assert host_num == 3
    assert 1 in graph[0]
    assert 2 in graph[0]
    assert 0 in graph[1]


def test_build_graph_hosts_array():
    links = [{"hosts": [0, 1, 2], "subnet": 10}]
    host_num, graph, link_subnets = build_graph_and_subnets(links)
    assert host_num == 3
    # Full mesh among 0, 1, 2
    assert graph[0] == {1, 2}
    assert graph[1] == {0, 2}
    assert graph[2] == {0, 1}


def test_build_graph_subnet_keys(sample_mesh_links):
    _, _, link_subnets = build_graph_and_subnets(sample_mesh_links)
    # Keys should be sorted tuples
    assert (0, 1) in link_subnets
    assert (1, 2) in link_subnets
    assert (0, 2) in link_subnets
    assert link_subnets[(0, 1)] == 0


# ── compute_fib ──


def test_compute_fib_triangle_k1(sample_mesh_links):
    routes = compute_fib(sample_mesh_links, k_paths=1)
    # 3 nodes, each has 2 destinations, k=1 -> 6 routes
    assert len(routes) == 6
    # No self-routes
    for r in routes:
        assert r.source != r.next_hop


def test_compute_fib_triangle_k2(sample_mesh_links):
    routes = compute_fib(sample_mesh_links, k_paths=2)
    # 3 nodes, each has 2 destinations, each dest has up to 2 next hops
    # Node 0 to dest 1: can go via 1 (direct, cost=1) or via 2 (cost=2)
    # Node 0 to dest 2: can go via 2 (direct, cost=1) or via 1 (cost=2)
    # Each node has 2 neighbors, so up to 2 next hops per dest
    assert len(routes) == 12  # 3 sources * 2 dests * 2 next_hops


def test_compute_fib_ip_format(sample_mesh_links):
    routes = compute_fib(sample_mesh_links, k_paths=1)
    for r in routes:
        assert r.next_hop_ip.startswith("192.168.")
        parts = r.next_hop_ip.split(".")
        assert int(parts[3]) == r.next_hop + 1


def test_compute_fib_prefix_format(sample_mesh_links):
    routes = compute_fib(sample_mesh_links, k_paths=1)
    prefixes = {r.prefix for r in routes}
    assert "ccnx:/test/example1" in prefixes
    assert "ccnx:/test/example2" in prefixes
    assert "ccnx:/test/example3" in prefixes


def test_compute_fib_no_self_routes(sample_mesh_links):
    routes = compute_fib(sample_mesh_links, k_paths=1)
    for r in routes:
        # prefix encodes dest as dest+1
        dest = int(r.prefix.split("example")[1]) - 1
        assert r.source != dest


# ── compute_fib_for_uris ──


def test_compute_fib_for_uris_single(sample_mesh_links):
    uri_pubs = {"ccnx:/test/video": 2}
    routes = compute_fib_for_uris(sample_mesh_links, 1, uri_pubs)
    # bidirectional: 2 non-publisher → publisher + 2 publisher → others
    assert len(routes) == 4
    assert all(r.prefix == "ccnx:/test/video" for r in routes)


def test_compute_fib_for_uris_multi(sample_mesh_links):
    uri_pubs = {"ccnx:/a": 0, "ccnx:/b": 2}
    routes = compute_fib_for_uris(sample_mesh_links, 1, uri_pubs)
    a_routes = [r for r in routes if r.prefix == "ccnx:/a"]
    b_routes = [r for r in routes if r.prefix == "ccnx:/b"]
    assert len(a_routes) == 4  # 2 toward pub 0 + 2 from pub 0
    assert len(b_routes) == 4  # 2 toward pub 2 + 2 from pub 2


def test_compute_fib_for_uris_bidirectional(sample_mesh_links):
    uri_pubs = {"ccnx:/test/data": 1}
    routes = compute_fib_for_uris(sample_mesh_links, 1, uri_pubs)
    sources = {r.source for r in routes}
    # publisher (1) is also a source for TI routing (Reflexive Forwarding)
    assert 1 in sources
    # publisher routes only to other nodes, never to itself
    for r in routes:
        if r.source == 1:
            assert r.next_hop != 1
    # no duplicate (source, prefix, next_hop_ip) entries
    keys = [(r.source, r.prefix, r.next_hop_ip) for r in routes]
    assert len(keys) == len(set(keys))
    # all routes use the same URI prefix
    assert all(r.prefix == "ccnx:/test/data" for r in routes)


def test_compute_fib_for_uris_no_duplicates_multi_publisher(sample_mesh_links):
    # two publishers sharing all 3 nodes: no route should appear twice
    uri_pubs = {"ccnx:/x": 0, "ccnx:/y": 1}
    routes = compute_fib_for_uris(sample_mesh_links, 2, uri_pubs)
    keys = [(r.source, r.prefix, r.next_hop_ip) for r in routes]
    assert len(keys) == len(set(keys))


def test_ecmp_strategy_bidirectional(sample_mesh_links):
    strat = EqualCostMultiPathStrategy()
    uri_pubs = {"ccnx:/test/stream": 2}
    routes = strat.compute_routes(sample_mesh_links, 1, uri_publishers=uri_pubs)
    sources = {r.source for r in routes}
    # publisher (2) must appear as a source
    assert 2 in sources
    # no duplicate entries
    keys = [(r.source, r.prefix, r.next_hop_ip) for r in routes]
    assert len(keys) == len(set(keys))


def test_shortest_path_strategy_bidirectional(sample_mesh_links):
    strat = ShortestPathOnlyStrategy()
    uri_pubs = {"ccnx:/test/stream": 0}
    routes = strat.compute_routes(sample_mesh_links, 1, uri_publishers=uri_pubs)
    sources = {r.source for r in routes}
    # publisher (0) must appear as a source (k=1 forced)
    assert 0 in sources
