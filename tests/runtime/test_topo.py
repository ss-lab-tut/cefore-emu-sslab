"""Behavior tests for src.runtime.topo.

Slice 1 covers only the pure combinatorial helpers (max_possible_links,
min_required_links, min_required_switches) that back CLI validation of
--hosts/--switch-capacity combinations. A later slice adds classes
covering SimpleLinkTopo/LineTopo/MeshTopo instantiation to this same
file (mininet.topo.Topo subclasses, root not required to build them).
"""

import pytest

from src.runtime.topo import (
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
