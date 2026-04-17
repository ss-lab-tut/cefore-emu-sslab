"""Tests for src.core.roles."""

from dataclasses import FrozenInstanceError
from random import Random

import pytest

from src.core.roles import CONSUMER, PUBLISHER, ROUTER, NodeRole, assign_roles


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
