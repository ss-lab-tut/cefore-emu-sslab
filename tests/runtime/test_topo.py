"""Behavior tests for src.runtime.topo.

Slice 1 covers only the pure combinatorial helpers (max_possible_links,
min_required_links, min_required_switches) that back CLI validation of
--hosts/--switch-capacity combinations. Slice 2 (below) adds classes
covering SimpleLinkTopo/LineTopo/MeshTopo instantiation.

Mininet's Topo.__init__(*args, **params) only does MultiGraph bookkeeping
before delegating to build(*args, **params) -- addHost/addSwitch/addLink
mutate an in-memory graph and never touch the network namespace, so these
subclasses instantiate and build in-process without root or a running
Mininet instance.

MeshTopo.build is RNG-driven and its degree-budget bookkeeping makes many
(hosts, swhich_num, degree_min/max, node_per_switch) combinations
infeasible (raises ValueError). Every fixture tuple below was hand-verified
by running it directly against random.Random(<seed>) before being written
into a test -- do not assume a new tuple works without the same check.

Two MeshTopo branches are intentionally NOT covered here (see
peppy-zooming-bee.md's exclusion list, Codex-verified unreachable with
real RNG): switch_use_all's "no hosts available" (topo.py:172) and "could
not reach requested switch count" (topo.py:196/198) warnings -- the heap
is seeded from every host and each extra-switch iteration always manages
to place at least one host, so the target switch count is always reached
when extra_switches > 0. Also "all hosts must have degree >=1"
(topo.py:83-84) -- the host_degree_min/max validation above it (topo.py
:70-71) already rejects any range that could produce a zero degree, so
that guard can only be reached via a hand-crafted fake rng, which is not
worth the complexity for a defensive check that can never fire in
practice.
"""

import random
from unittest.mock import patch

import pytest

from src.runtime.topo import (
    LineTopo,
    MeshTopo,
    SimpleLinkTopo,
    max_possible_links,
    min_required_links,
    min_required_switches,
)


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


class TestMaxPossibleLinks:
    def test_returns_complete_graph_edge_count(self):
        # Complete graph on 4 nodes has 4*3/2 = 6 edges.
        assert max_possible_links(4) == 6

    def test_single_host_has_zero_possible_links(self):
        assert max_possible_links(1) == 0


class TestMinRequiredLinks:
    def test_returns_spanning_tree_edge_count(self):
        assert min_required_links(4) == 3

    def test_single_host_needs_zero_links(self):
        assert min_required_links(1) == 0


class TestMinRequiredSwitches:
    def test_divides_hosts_across_switch_capacity_rounding_up(self):
        # 5 hosts at capacity 2 need 3 switches (2+2+1), not floor(5/2)=2.
        assert min_required_switches(5, 2) == 3

    def test_hosts_evenly_divisible_by_capacity_needs_no_extra_switch(self):
        assert min_required_switches(6, 2) == 3

    def test_returns_at_least_one_switch_even_for_zero_hosts(self):
        assert min_required_switches(0, 2) == 1

    def test_switch_capacity_below_two_raises_value_error(self):
        with pytest.raises(ValueError, match="switch_capacity must be at least 2"):
            min_required_switches(5, 1)


# ---------------------------------------------------------------------------
# SimpleLinkTopo / LineTopo -- fixed-shape topologies, no RNG involved
# ---------------------------------------------------------------------------


class TestSimpleLinkTopo:
    """SimpleLinkTopo always wires a fixed h0-s0-h1-s1-h2 dumbbell.

    build()'s `n` parameter only controls how many host nodes are added
    (via irange(0, n-1)); the four addLink calls are hardcoded to
    hosts[0..2], so n only ever changes whether extra, unlinked hosts
    exist -- it never changes the wiring.
    """

    def test_default_construction_wires_dumbbell_topology(self):
        # Topo.__init__ forwards constructor kwargs straight into build(),
        # so SimpleLinkTopo() alone already exercises the default n=3 path.
        topo = SimpleLinkTopo()
        assert sorted(topo.nodes()) == ["h0", "h1", "h2", "s0", "s1"]
        assert topo.links() == [
            ("s0", "h0"),
            ("s0", "h1"),
            ("s1", "h1"),
            ("s1", "h2"),
        ]

    def test_larger_n_adds_extra_unlinked_hosts(self):
        # n=4 creates h3 but the hardcoded addLink calls never reference
        # it, so h3 is present in the graph with zero links.
        topo = SimpleLinkTopo(n=4)
        assert sorted(topo.nodes()) == ["h0", "h1", "h2", "h3", "s0", "s1"]
        linked_nodes = {node for link in topo.links() for node in link}
        assert "h3" not in linked_nodes


class TestLineTopo:
    """LineTopo chains hosts and switches: h0-s0-h1-s1-...-sN-hN."""

    def test_four_hosts_produce_three_switches_in_a_line(self):
        topo = LineTopo(hosts=4)
        assert sorted(topo.nodes()) == [
            "h0",
            "h1",
            "h2",
            "h3",
            "s0",
            "s1",
            "s2",
        ]
        assert topo.links() == [
            ("s0", "h0"),
            ("s0", "h1"),
            ("s1", "h1"),
            ("s1", "h2"),
            ("s2", "h2"),
            ("s2", "h3"),
        ]

    def test_single_host_needs_no_switches_or_links(self):
        # hosts=1 -> switches = hosts - 1 = 0, so the build loop never runs.
        topo = LineTopo(hosts=1)
        assert sorted(topo.nodes()) == ["h0"]
        assert topo.links() == []


# ---------------------------------------------------------------------------
# MeshTopo -- RNG-driven, so every fixture tuple below was hand-verified
# against a fixed random.Random(seed) before being committed to a test.
# ---------------------------------------------------------------------------


class TestMeshTopoHappyPath:
    def test_build_produces_mesh_links_with_expected_keys_covering_all_hosts(self):
        # hosts=4, degree fixed at 2 for every host, capacity 2 per switch,
        # seed=0 -- hand-verified to build 4 switches without raising.
        topo = MeshTopo(
            hosts=4,
            swhich_num=6,
            node_per_switch=2,
            host_degree_min=2,
            host_degree_max=2,
            rng=random.Random(0),
        )
        assert len(topo.mesh_links) == 4
        covered_hosts = set()
        for entry in topo.mesh_links:
            assert set(entry.keys()) == {"subnet", "switch", "hosts", "host_eth"}
            # host_eth assigns a private per-host port counter, so its key
            # set must exactly match the hosts attached to that switch.
            assert set(entry["host_eth"].keys()) == set(entry["hosts"])
            covered_hosts.update(entry["hosts"])
        assert covered_hosts == {0, 1, 2, 3}

    def test_nodes_and_links_reflect_switch_host_connections(self):
        topo = MeshTopo(
            hosts=4,
            swhich_num=6,
            node_per_switch=2,
            host_degree_min=2,
            host_degree_max=2,
            rng=random.Random(0),
        )
        assert sorted(topo.nodes()) == [
            "h0",
            "h1",
            "h2",
            "h3",
            "s0",
            "s1",
            "s2",
            "s3",
        ]
        # Every mesh_links entry corresponds 1:1 with an addLink call
        # between that switch and each of its attached hosts.
        expected_link_count = sum(len(entry["hosts"]) for entry in topo.mesh_links)
        assert len(topo.links()) == expected_link_count

    def test_same_seed_produces_identical_mesh_links(self):
        # Determinism matters because scenario configs replay a fixed
        # --seed to get reproducible topologies across runs.
        topo_a = MeshTopo(hosts=5, swhich_num=6, node_per_switch=2, rng=random.Random(0))
        topo_b = MeshTopo(hosts=5, swhich_num=6, node_per_switch=2, rng=random.Random(0))
        assert topo_a.mesh_links == topo_b.mesh_links

    def test_node_per_switch_zero_falls_back_to_host_count_as_capacity(self):
        # node_per_switch=0 hits the "switch_capacity = ... else hosts"
        # branch (topo.py:74) instead of raising -- only node_per_switch
        # == 1 is rejected explicitly.
        topo = MeshTopo(
            hosts=4,
            node_per_switch=0,
            host_degree_min=2,
            host_degree_max=2,
            rng=random.Random(0),
        )
        assert len(topo.mesh_links) == 3
        covered_hosts = {host for entry in topo.mesh_links for host in entry["hosts"]}
        assert covered_hosts == {0, 1, 2, 3}


class TestMeshTopoErrors:
    """Reachable ValueError branches in MeshTopo.build, each confirmed by
    running the exact constructor args below before writing the assertion.
    """

    def test_host_degree_min_below_one_raises_value_error(self):
        with pytest.raises(ValueError, match="host_degree_min/max must satisfy 1 <= min <= max"):
            MeshTopo(hosts=3, host_degree_min=0, rng=random.Random(0))

    def test_host_degree_max_below_min_raises_value_error(self):
        with pytest.raises(ValueError, match="host_degree_min/max must satisfy 1 <= min <= max"):
            MeshTopo(hosts=3, host_degree_min=2, host_degree_max=1, rng=random.Random(0))

    def test_node_per_switch_of_one_raises_value_error(self):
        # A switch with capacity 1 could never connect two hosts to each
        # other, so this is rejected outright rather than producing an
        # unusable topology.
        with pytest.raises(ValueError, match="switch capacity must be >=2 to connect hosts"):
            MeshTopo(hosts=3, node_per_switch=1, rng=random.Random(0))

    def test_degree_budget_exhausted_raises_value_error_when_spanning_tree_infeasible(self):
        # Same (hosts=5, swhich_num=6, node_per_switch=2) shape as the
        # happy-path fixture but seed=1 draws a degree sequence that
        # cannot cover a spanning tree (initial_total=7 < needed=8).
        with pytest.raises(ValueError, match="failed to build spanning tree: degree budget exhausted"):
            MeshTopo(hosts=5, swhich_num=6, node_per_switch=2, rng=random.Random(1))

    def test_switch_count_exceeding_swhich_num_limit_raises_value_error(self):
        # Same fixture as the happy path (needs 5 switches at seed=0) but
        # swhich_num is capped below that, so the post-build limit check
        # (topo.py:147) fires instead of switch_use_all redistribution.
        with pytest.raises(ValueError, match="switch count 5 exceeds limit 2"):
            MeshTopo(hosts=5, swhich_num=2, node_per_switch=2, rng=random.Random(0))


class TestMeshTopoSwitchUseAll:
    """switch_use_all redistributes hosts onto extra switches once the
    plain build falls short of swhich_num. Only the enabled/success path is
    tested -- see the module docstring for why the two warning branches
    are excluded.
    """

    def test_switch_use_all_logs_enabled_message_and_reaches_requested_switch_count(self):
        # Natural build with this seed produces 5 switches; swhich_num=8
        # requests 3 more, which the heap-based redistribution always
        # manages to place (one extra switch created per iteration).
        with patch("src.runtime.topo.info") as mock_info:
            topo = MeshTopo(
                hosts=5,
                swhich_num=8,
                node_per_switch=2,
                switch_use_all=True,
                rng=random.Random(0),
            )
        assert len(topo.mesh_links) == 8
        mock_info.assert_called_once_with(
            "switch_use_all enabled: distributing extra switches; "
            "host degrees may exceed host_degree_max\n"
        )

    def test_switch_use_all_does_not_log_when_natural_count_already_meets_target(self):
        # Same seed/shape naturally yields 5 switches; requesting exactly
        # 5 leaves extra_switches at 0, so the redistribution block (and
        # its info() call) is never entered.
        with patch("src.runtime.topo.info") as mock_info:
            topo = MeshTopo(
                hosts=5,
                swhich_num=5,
                node_per_switch=2,
                switch_use_all=True,
                rng=random.Random(0),
            )
        assert len(topo.mesh_links) == 5
        mock_info.assert_not_called()
