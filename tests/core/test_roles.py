"""Tests for src.core.roles."""

from dataclasses import FrozenInstanceError
from random import Random

import pytest

from src.core.roles import (
    CONSUMER, PUBLISHER, ROUTER,
    assign_roles, assign_random_cs_modes, derive_seed,
)


def test_three_hosts_default():
    roles = assign_roles(3, Random(0))
    assert roles[0] is CONSUMER
    assert roles[1] is ROUTER
    assert roles[2] is PUBLISHER


def test_five_hosts_pattern():
    roles = assign_roles(5, Random(0))
    assert roles[0] is CONSUMER
    assert roles[1] is ROUTER
    assert roles[3] is ROUTER  # odd index
    assert roles[4] is PUBLISHER  # last host


def test_publisher_override():
    roles = assign_roles(5, Random(0), publishers={1, 3})
    assert roles[1] is PUBLISHER
    assert roles[3] is PUBLISHER


def test_deterministic_with_seed():
    roles_a = assign_roles(8, Random(42))
    roles_b = assign_roles(8, Random(42))
    assert roles_a == roles_b


def test_consumer_at_zero_always():
    roles = assign_roles(5, Random(0), publishers={0, 4})
    # publishers override, but idx 0 check comes after publishers check
    assert roles[0] is PUBLISHER  # publishers takes precedence


def test_node_role_frozen():
    with pytest.raises(FrozenInstanceError):
        CONSUMER.name = "modified"


def test_host_num_one():
    roles = assign_roles(1, Random(0))
    assert roles[0] is CONSUMER


def test_host_num_two():
    # Minimal 2-host setup: no router needed, FIB alone handles forwarding
    roles = assign_roles(2, Random(0))
    assert roles[0] is CONSUMER
    assert roles[1] is PUBLISHER


# ---------------------------------------------------------------------------
# assign_random_cs_modes
# ---------------------------------------------------------------------------


class TestAssignRandomCsModes:

    def test_publisher_always_mode_1_or_2(self):
        rng = Random(42)
        for _ in range(200):
            cs = assign_random_cs_modes(range(5), {2, 4}, rng)
            assert cs[2] in (1, 2)
            assert cs[4] in (1, 2)

    def test_non_publisher_can_be_any_mode(self):
        modes_seen = set()
        for seed in range(500):
            cs = assign_random_cs_modes(range(3), {2}, Random(seed))
            modes_seen.update({cs[0], cs[1]})
        assert modes_seen == {0, 1, 2}

    def test_deterministic_with_seed(self):
        a = assign_random_cs_modes(range(10), {4}, Random(42))
        b = assign_random_cs_modes(range(10), {4}, Random(42))
        assert a == b

    def test_input_order_irrelevant(self):
        a = assign_random_cs_modes([0, 1, 2, 3], {2}, Random(42))
        b = assign_random_cs_modes([3, 1, 0, 2], {2}, Random(42))
        assert a == b

    def test_empty_publishers(self):
        cs = assign_random_cs_modes(range(3), set(), Random(0))
        assert all(m in (0, 1, 2) for m in cs.values())
        assert len(cs) == 3

    def test_all_hosts_present_in_output(self):
        cs = assign_random_cs_modes(range(8), {3, 7}, Random(0))
        assert set(cs.keys()) == set(range(8))


# ---------------------------------------------------------------------------
# derive_seed
# ---------------------------------------------------------------------------


class TestDeriveSeed:

    def test_none_returns_none(self):
        assert derive_seed(None, "cs-mode") is None

    def test_deterministic(self):
        a = derive_seed(42, "cs-mode")
        b = derive_seed(42, "cs-mode")
        assert a == b

    def test_different_namespace_different_seed(self):
        a = derive_seed(42, "cs-mode")
        b = derive_seed(42, "topology")
        assert a != b

    def test_negative_seed_stable(self):
        a = derive_seed(-1, "cs-mode")
        b = derive_seed(-1, "cs-mode")
        assert a == b
