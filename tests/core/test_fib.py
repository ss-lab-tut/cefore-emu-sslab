"""Tests for src.core.fib."""

import pytest

from src.core.fib import (
    LinkSubnet,
    Route,
    build_graph_and_subnets,
    compute_fib,
    compute_fib_for_uris,
    DijkstraStrategy,
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


# ── prefix_routes: static route announcement, no publisher behind it ──
#
# A 3-host line (h0-h1-h2): links [[0, 1], [1, 2]]. Unlike sample_mesh_links (triangle,
# every pair directly connected), a line forces a real multi-hop path for
# the (0, 2) pair, which is what distinguishes "every other host routes
# toward the named one" (prefix_routes, one direction) from "publisher
# routes back to everyone too" (uri_publishers, two directions): on this
# topology the two produce different route counts, not just different
# prefixes.


@pytest.fixture
def line_mesh_links():
    """3-host line: h0-h1 (subnet 0), h1-h2 (subnet 1). No h0-h2 edge."""
    return [
        {"host_a": 0, "host_b": 1, "subnet": 0},
        {"host_a": 1, "host_b": 2, "subnet": 1},
    ]


def test_compute_fib_for_uris_prefix_routes_pass1_only_without_publishers(
    line_mesh_links,
):
    """No uri_publishers at all: prefix_routes must still produce routes.

    Each entry gets ONLY non-owner -> owner routes (Pass 1): the owning
    host is never a route source for its own prefix, because there is no
    publisher behind it to originate a Reflexive-Forwarding route back.
    """
    prefix_routes = {"ccnx:/test/a": 2, "ccnx:/test/b": 0}
    routes = compute_fib_for_uris(
        line_mesh_links, 1, {}, prefix_routes=prefix_routes
    )
    actual = {(r.source, r.prefix, r.next_hop, r.next_hop_ip) for r in routes}
    assert actual == {
        (0, "ccnx:/test/a", 1, "192.168.0.2"),
        (1, "ccnx:/test/a", 2, "192.168.1.3"),
        (1, "ccnx:/test/b", 0, "192.168.0.1"),
        (2, "ccnx:/test/b", 1, "192.168.1.2"),
    }
    assert len(routes) == len(actual)  # no accidental duplicate Route objects
    assert 2 not in {r.source for r in routes if r.prefix == "ccnx:/test/a"}
    assert 0 not in {r.source for r in routes if r.prefix == "ccnx:/test/b"}
    assert {r.source for r in routes} == {0, 1, 2}  # every other host is covered


def test_compute_fib_for_uris_prefix_routes_merge_with_publisher(line_mesh_links):
    """prefix_routes entries land in the FIB alongside a real publisher.

    uri_publishers (the "b" entry's host 1 here) still gets its normal
    bidirectional Pass 1 + Pass 2 routes; prefix_routes routes merge in on
    top, Pass 1 only, independent of and unaffected by the publisher.
    """
    uri_publishers = {"ccnx:/test/pub": 1}
    prefix_routes = {"ccnx:/test/a": 2, "ccnx:/test/b": 0}
    routes = compute_fib_for_uris(
        line_mesh_links, 1, uri_publishers, prefix_routes=prefix_routes
    )
    actual = {(r.source, r.prefix, r.next_hop, r.next_hop_ip) for r in routes}
    assert actual == {
        # uri_publishers "pub" (host 1): bidirectional, unchanged by prefix_routes
        (0, "ccnx:/test/pub", 1, "192.168.0.2"),
        (2, "ccnx:/test/pub", 1, "192.168.1.2"),
        (1, "ccnx:/test/pub", 0, "192.168.0.1"),
        (1, "ccnx:/test/pub", 2, "192.168.1.3"),
        # prefix_routes "a"/"b": one direction only, present alongside "pub"
        (0, "ccnx:/test/a", 1, "192.168.0.2"),
        (1, "ccnx:/test/a", 2, "192.168.1.3"),
        (1, "ccnx:/test/b", 0, "192.168.0.1"),
        (2, "ccnx:/test/b", 1, "192.168.1.2"),
    }
    assert len(routes) == len(actual)


def test_compute_fib_for_uris_prefix_routes_default_is_backward_compatible(
    line_mesh_links,
):
    """Omitting prefix_routes must reproduce the pre-existing output exactly.

    Pins the ticket's "must not change the existing output when
    prefix_routes is absent" requirement at the compute_fib_for_uris layer:
    a call that never mentions prefix_routes (as every caller before this
    feature existed) must be unaffected by the new parameter's default.
    """
    uri_publishers = {"ccnx:/test/pub": 1}
    routes = compute_fib_for_uris(line_mesh_links, 1, uri_publishers)
    actual = {(r.source, r.prefix, r.next_hop, r.next_hop_ip) for r in routes}
    assert actual == {
        (0, "ccnx:/test/pub", 1, "192.168.0.2"),
        (2, "ccnx:/test/pub", 1, "192.168.1.2"),
        (1, "ccnx:/test/pub", 0, "192.168.0.1"),
        (1, "ccnx:/test/pub", 2, "192.168.1.3"),
    }


def test_dijkstra_strategy_prefix_routes_used_even_when_uri_publishers_absent(
    line_mesh_links,
):
    """prefix_routes alone (uri_publishers=None) must not fall back to the
    default ccnx:/test/exampleN routes -- it must still resolve through
    compute_fib_for_uris, independent of whether any publisher exists."""
    strat = DijkstraStrategy()
    prefix_routes = {"ccnx:/test/a": 2, "ccnx:/test/b": 0}
    routes = strat.compute_routes(
        line_mesh_links, 1, uri_publishers=None, prefix_routes=prefix_routes
    )
    actual = {(r.source, r.prefix, r.next_hop, r.next_hop_ip) for r in routes}
    assert actual == {
        (0, "ccnx:/test/a", 1, "192.168.0.2"),
        (1, "ccnx:/test/a", 2, "192.168.1.3"),
        (1, "ccnx:/test/b", 0, "192.168.0.1"),
        (2, "ccnx:/test/b", 1, "192.168.1.2"),
    }


def test_dijkstra_strategy_absent_both_matches_compute_fib(line_mesh_links):
    """Neither uri_publishers nor prefix_routes: byte-identical to the
    pre-existing compute_fib() default-prefix path (pin, by comparing
    against that real function rather than hand-typed expectations)."""
    strat = DijkstraStrategy()
    assert strat.compute_routes(line_mesh_links, 1) == compute_fib(
        line_mesh_links, 1
    )


def test_ecmp_strategy_prefix_routes_pass1_only(line_mesh_links):
    """ECMP ties into the same prefix_routes pass, Pass 1 only.

    The line has no cost ties, so ECMP's "all equal-cost next hops"
    produces exactly the k=1 Dijkstra set here -- this test is about the
    branch selecting compute at all for prefix_routes, not about ties.
    """
    strat = EqualCostMultiPathStrategy()
    prefix_routes = {"ccnx:/test/a": 2, "ccnx:/test/b": 0}
    routes = strat.compute_routes(line_mesh_links, 1, prefix_routes=prefix_routes)
    actual = {(r.source, r.prefix, r.next_hop, r.next_hop_ip) for r in routes}
    assert actual == {
        (0, "ccnx:/test/a", 1, "192.168.0.2"),
        (1, "ccnx:/test/a", 2, "192.168.1.3"),
        (1, "ccnx:/test/b", 0, "192.168.0.1"),
        (2, "ccnx:/test/b", 1, "192.168.1.2"),
    }


def test_shortest_path_strategy_prefix_routes_pass1_only(line_mesh_links):
    """ShortestPathOnlyStrategy forces k=1 for the prefix_routes path too
    (the 99 passed in must be ignored, exactly like it is for
    uri_publishers)."""
    strat = ShortestPathOnlyStrategy()
    prefix_routes = {"ccnx:/test/a": 2, "ccnx:/test/b": 0}
    routes = strat.compute_routes(line_mesh_links, 99, prefix_routes=prefix_routes)
    actual = {(r.source, r.prefix, r.next_hop, r.next_hop_ip) for r in routes}
    assert actual == {
        (0, "ccnx:/test/a", 1, "192.168.0.2"),
        (1, "ccnx:/test/a", 2, "192.168.1.3"),
        (1, "ccnx:/test/b", 0, "192.168.0.1"),
        (2, "ccnx:/test/b", 1, "192.168.1.2"),
    }
