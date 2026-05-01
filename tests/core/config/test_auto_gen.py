"""Tests for src.core.config.auto_gen."""

from pathlib import Path
from random import Random

import pytest

from src.core.config.auto_gen import generate_operations, parse_consumer_spec


# ── parse_consumer_spec ──


def test_parse_consumer_random():
    result = parse_consumer_spec("random:3", 10, Random(42))
    assert len(result) == 3
    assert len(set(result)) == 3  # unique
    assert all(0 <= x < 10 for x in result)


def test_parse_consumer_list():
    result = parse_consumer_spec([0, 2, 4], 10, Random(42))
    assert result == [0, 2, 4]


def test_parse_consumer_invalid_returns_empty():
    result = parse_consumer_spec("garbage", 10, Random(42))
    assert result == []


def test_parse_consumer_random_exceeds():
    result = parse_consumer_spec("random:100", 5, Random(42))
    assert len(result) == 5


# ── generate_operations ──


def test_generate_simple():
    auto = {
        "uri_prefix": "ccnx:/test",
        "publishers": [2],
        "consumers": [0, 1],
        "content_count": 2,
        "consumer_per_content": 1,
    }
    puts, gets = generate_operations(auto, 3, seed=42)
    assert len(puts) == 2
    assert all(p["host"] == 2 for p in puts)
    assert len(gets) == 2


def test_generate_pubsub_mode():
    auto = {
        "uri": "ccnx:/test/live",
        "publishers": [3],
        "consumers": [0],
        "content_count": 1,
        "pub_opts": {"lifetime": 5},
        "sub_opts": {"consumer_per_content": 1},
    }
    puts, gets = generate_operations(auto, 5, seed=42)
    assert puts[0].get("mode") == "pubsub"
    assert puts[0]["pub_opts"]["lifetime"] == 5


def test_generate_excludes_publishers():
    auto = {
        "uri_prefix": "ccnx:/test",
        "publishers": [0],
        "consumers": [0, 1, 2],
        "content_count": 1,
        "consumer_per_content": 1,
    }
    _, gets = generate_operations(auto, 3, seed=42)
    consumer_hosts = [g["host"] for g in gets]
    assert 0 not in consumer_hosts


def test_generate_deterministic():
    auto = {
        "uri_prefix": "ccnx:/test",
        "publishers": [2],
        "consumers": "random:2",
        "content_count": 2,
        "consumer_per_content": 1,
    }
    p1, g1 = generate_operations(auto, 5, seed=42)
    p2, g2 = generate_operations(auto, 5, seed=42)
    assert p1 == p2
    assert g1 == g2


def test_generate_content_count_zero_raises():
    auto = {
        "uri_prefix": "ccnx:/test",
        "publishers": [0],
        "content_count": 0,
    }
    with pytest.raises(ValueError, match="content_count"):
        generate_operations(auto, 3, seed=42)
