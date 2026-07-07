"""Unit tests for cache configuration manager."""

from unittest.mock import patch

import pytest

from src.runtime.cache_manager import CacheConfigManager, CachePlacement


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

    @pytest.mark.parametrize(
        ("algorithm", "expected"),
        [
            ("LRU", "libcsmgrd_lru"),
            ("LFU", "libcsmgrd_lfu"),
            ("FIFO", "libcsmgrd_fifo"),
            ("None", "None"),
        ],
    )
    def test_apply_configs_normalizes_default_algorithm(
        self, triangle_graph, algorithm, expected
    ):
        config = {"strategy": "manual", "default": {"algorithm": algorithm}}
        mgr = CacheConfigManager(config, 3, triangle_graph, publisher_ids=set())
        with patch("src.runtime.cache_manager.apply_cache_node_settings") as mock_apply:
            mgr.apply_configs({1})

        assert mock_apply.call_args.kwargs["cache_algorithm"] == expected

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

    def test_apply_configs_normalizes_node_override_algorithm(
        self, tmp_path, monkeypatch, triangle_graph
    ):
        monkeypatch.chdir(tmp_path)
        for idx in range(3):
            node_dir = tmp_path / f"h{idx}"
            node_dir.mkdir()
            (node_dir / "cefnetd.conf").write_text("CS_MODE=0\n")
            (node_dir / "csmgrd.conf").write_text("CACHE_ALGORITHM=None\n")

        config = {
            "strategy": "manual",
            "default": {"algorithm": "LRU"},
            "nodes": [{"id": 1, "algorithm": "LFU"}],
        }
        mgr = CacheConfigManager(config, 3, triangle_graph, publisher_ids=set())
        mgr.apply_configs({1})

        assert "CACHE_ALGORITHM=libcsmgrd_lfu" in (
            tmp_path / "h1" / "csmgrd.conf"
        ).read_text()


class TestCachePlacement:
    """One placement decision for disaster (exclusion) and connect (no exclusion)."""

    def test_legacy_path_excludes_publishers_by_default(self, linear_graph):
        placement = CachePlacement(
            host_count=5,
            host_graph=linear_graph,
            publisher_ids={4},
            cache_count=2,
        )
        nodes = placement.decide()
        assert len(nodes) == 2
        assert 4 not in nodes

    def test_legacy_path_can_keep_publishers(self, linear_graph):
        # connect: publishers stay eligible for caching
        with_pub = CachePlacement(
            host_count=5,
            host_graph=linear_graph,
            publisher_ids={0, 4},
            cache_count=5,
            exclude_publishers=False,
        )
        assert sorted(with_pub.decide()) == [0, 1, 2, 3, 4]

    def test_cache_count_zero_falls_back_to_down_count_plus_one(self, linear_graph):
        placement = CachePlacement(
            host_count=5,
            host_graph=linear_graph,
            publisher_ids=set(),
            cache_count=0,
            down_count=2,
        )
        assert len(placement.decide()) == 3

    def test_empty_selection_falls_back_to_last_host(self, triangle_graph):
        placement = CachePlacement(
            host_count=3,
            host_graph=triangle_graph,
            publisher_ids={0, 1, 2},
            cache_count=2,
        )
        assert placement.decide() == [2]

    def test_cache_config_path_uses_configured_strategy(self, triangle_graph):
        placement = CachePlacement(
            host_count=3,
            host_graph=triangle_graph,
            publisher_ids={0},
            cache_config={"strategy": "manual", "nodes": [{"id": [0, 1]}]},
        )
        assert placement.decide() == [1]  # 0 excluded as publisher

    def test_place_applies_legacy_settings_and_returns_set(self, linear_graph):
        placement = CachePlacement(
            host_count=5,
            host_graph=linear_graph,
            publisher_ids={4},
            cache_count=2,
            cache_default_rct_ms=1234,
        )
        with patch("src.runtime.cache_manager.apply_cache_node_settings") as mock_apply:
            cache_set = placement.place()
        assert cache_set == set(placement.decide())
        args, kwargs = mock_apply.call_args
        assert args[0] == 5
        assert args[1] == cache_set
        assert args[2] == 1234
        assert kwargs["publishers"] == {4}

    def test_place_applies_cache_config_through_the_manager(self, triangle_graph):
        placement = CachePlacement(
            host_count=3,
            host_graph=triangle_graph,
            publisher_ids=set(),
            cache_config={
                "strategy": "manual",
                "nodes": [{"id": 1}],
                "default": {"capacity": 512},
            },
        )
        with patch("src.runtime.cache_manager.apply_cache_node_settings") as mock_apply:
            cache_set = placement.place()
        assert cache_set == {1}
        assert mock_apply.call_args.kwargs["cache_capacity"] == 512
