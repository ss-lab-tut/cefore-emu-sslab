"""Unit tests for cache configuration manager."""

from unittest.mock import patch

import pytest

from src.runtime.cache_manager import CacheConfigManager


@pytest.fixture
def star_graph():
    """5-node star: node 2 is the hub."""
    return {0: {2}, 1: {2}, 2: {0, 1, 3, 4}, 3: {2}, 4: {2}}


class TestCacheConfigManager:
    def test_k_centers_strategy_selects_nodes(self, linear_graph):
        config = {"strategy": "k_centers", "default": {"count": 2}}
        mgr = CacheConfigManager(config, 5, linear_graph, publisher_ids={4})
        nodes = mgr.select_cache_nodes(exclude={4})
        assert len(nodes) == 2
        assert 4 not in nodes

    def test_manual_strategy_uses_node_ids(self, triangle_graph):
        config = {
            "strategy": "manual",
            "nodes": [{"id": 1}, {"id": 2}],
        }
        mgr = CacheConfigManager(config, 3, triangle_graph, publisher_ids=set())
        nodes = mgr.select_cache_nodes()
        assert nodes == [1, 2]

    def test_degree_based_strategy_selects_highest(self, star_graph):
        config = {"strategy": "degree_based", "default": {"count": 1}}
        mgr = CacheConfigManager(config, 5, star_graph, publisher_ids=set())
        nodes = mgr.select_cache_nodes()
        assert nodes == [2]

    def test_exclude_filters_publishers(self, linear_graph):
        config = {"strategy": "k_centers", "default": {"count": 2}}
        mgr = CacheConfigManager(config, 5, linear_graph, publisher_ids={2})
        nodes = mgr.select_cache_nodes(exclude={2})
        assert 2 not in nodes

    def test_unknown_strategy_raises_valueerror(self, triangle_graph):
        config = {"strategy": "bogus"}
        mgr = CacheConfigManager(config, 3, triangle_graph, publisher_ids=set())
        with pytest.raises(ValueError, match="Unknown cache strategy"):
            mgr.select_cache_nodes()

    def test_apply_configs_calls_settings(self, triangle_graph):
        config = {"strategy": "manual", "default": {"default_rct_ms": 5000}}
        mgr = CacheConfigManager(config, 3, triangle_graph, publisher_ids=set())
        with patch("src.runtime.cache_manager.apply_cache_node_settings") as mock_apply:
            mgr.apply_configs({1, 2})
            mock_apply.assert_called_once()
            call_kwargs = mock_apply.call_args
            assert call_kwargs[1].get("cache_default_rct_ms") == 5000 or \
                   (len(call_kwargs[0]) > 2 and call_kwargs[0][2] == 5000)

    def test_parse_node_overrides_single_id(self, triangle_graph):
        config = {"strategy": "manual", "nodes": [{"id": 5, "capacity": 100}]}
        mgr = CacheConfigManager(config, 6, triangle_graph, publisher_ids=set())
        assert 5 in mgr.node_overrides
        assert mgr.node_overrides[5]["capacity"] == 100

    def test_parse_node_overrides_list_id(self, triangle_graph):
        config = {
            "strategy": "manual",
            "nodes": [{"id": [1, 2], "algorithm": "LFU"}],
        }
        mgr = CacheConfigManager(config, 3, triangle_graph, publisher_ids=set())
        assert mgr.node_overrides[1]["algorithm"] == "LFU"
        assert mgr.node_overrides[2]["algorithm"] == "LFU"
