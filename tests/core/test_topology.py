"""Behavior tests for the TopologyModel query interface.

TopologyModel owns the mesh_links schema; consumers query it instead of
branching on the link dict shape. Fixtures use the canonical multi-host
format that MeshTopo produces.
"""

import pytest

from src.core.topology import TopologyModel

# Two switches: s0 joins h0-h1, s1 joins h1-h2-h3 (as MeshTopo would emit).
MESH = [
    {"subnet": 1, "switch": "s0", "hosts": [0, 1], "host_eth": {0: 0, 1: 0}},
    {"subnet": 2, "switch": "s1", "hosts": [1, 2, 3], "host_eth": {1: 1, 2: 0, 3: 0}},
]


class TestHostCount:
    def test_host_count_is_max_attached_index_plus_one(self):
        assert TopologyModel(MESH).host_count == 4

    def test_empty_topology_has_zero_hosts(self):
        assert TopologyModel([]).host_count == 0


class TestFindLink:
    def test_hosts_sharing_a_switch_have_a_link(self):
        link = TopologyModel(MESH).find_link(2, 3)
        assert link.switch == "s1"
        assert link.subnet == 2
        assert link.hosts == [1, 2, 3]

    def test_hosts_without_shared_switch_have_none(self):
        assert TopologyModel(MESH).find_link(0, 3) is None


class TestPairwiseNormalization:
    """The legacy point-to-point dict shape is absorbed at construction."""

    PAIRWISE = [
        {"subnet": 4, "switch": "s2", "host_a": 5, "host_b": 0,
         "host_a_eth": 1, "host_b_eth": 2},
    ]

    def test_pairwise_link_is_queryable_like_hosts_variant(self):
        link = TopologyModel(self.PAIRWISE).find_link(0, 5)
        assert link.switch == "s2"
        assert link.subnet == 4
        assert link.hosts == [0, 5]

    def test_pairwise_links_count_toward_host_count(self):
        assert TopologyModel(self.PAIRWISE).host_count == 6

    def test_link_without_switch_is_still_queryable(self):
        """Addressing-only fixtures omit the switch key entirely."""
        model = TopologyModel([{"subnet": 3, "host_a": 1, "host_b": 0}])
        link = model.find_link(0, 1)
        assert link.subnet == 3
        assert link.switch is None


class TestLinksForHost:
    def test_returns_every_link_attached_to_the_host_in_order(self):
        links = TopologyModel(MESH).links_for_host(1)
        assert [link.switch for link in links] == ["s0", "s1"]

    def test_unattached_host_has_no_links(self):
        assert TopologyModel(MESH).links_for_host(9) == []


class TestEthOf:
    def test_hosts_variant_maps_host_to_interface_index(self):
        link = TopologyModel(MESH).find_link(1, 2)
        assert link.eth_of(1) == 1
        assert link.eth_of(2) == 0

    def test_pairwise_variant_maps_host_a_and_host_b_eth(self):
        link = TopologyModel(TestPairwiseNormalization.PAIRWISE).find_link(0, 5)
        assert link.eth_of(5) == 1
        assert link.eth_of(0) == 2


class TestEdges:
    def test_multi_host_link_expands_to_all_pairs(self):
        edges = TopologyModel(MESH).edges()
        pairs = [(a, b) for a, b, _ in edges]
        assert pairs == [(0, 1), (1, 2), (1, 3), (2, 3)]

    def test_each_pair_carries_its_link(self):
        edges = TopologyModel(MESH).edges()
        by_pair = {(a, b): link for a, b, link in edges}
        assert by_pair[(0, 1)].switch == "s0"
        assert by_pair[(2, 3)].subnet == 2


class TestSubnetOfSwitch:
    def test_returns_the_switch_link_subnet(self):
        assert TopologyModel(MESH).subnet_of_switch("s1") == 2

    def test_unknown_switch_returns_none(self):
        assert TopologyModel(MESH).subnet_of_switch("s9") is None


class TestLinks:
    def test_links_returns_normalized_links_in_order(self):
        links = TopologyModel(MESH).links
        assert [link.switch for link in links] == ["s0", "s1"]
        assert links[1].hosts == [1, 2, 3]


class TestPeerOf:
    def test_returns_a_host_sharing_a_link(self):
        assert TopologyModel(MESH).peer_of(0) == 1
        assert TopologyModel(MESH).peer_of(3) in (1, 2)

    def test_isolated_host_raises(self):
        with pytest.raises(RuntimeError, match="h9 has no links"):
            TopologyModel(MESH).peer_of(9)
