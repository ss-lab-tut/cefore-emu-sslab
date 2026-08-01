"""Flexible per-node cache configuration manager."""

from pathlib import Path

from mininet.log import info

from ..core.graph import select_k_centers
from .template import _set_config_value, apply_cache_node_settings

_VALID_ALGORITHMS = frozenset({"LRU", "LFU", "FIFO", "None"})
_VALID_TYPES = frozenset({"memory", "filesystem"})
_VALID_STRATEGIES = frozenset({"k_centers", "manual", "degree_based"})
_ALGORITHM_LIB_NAMES = {
    "LRU": "libcsmgrd_lru",
    "LFU": "libcsmgrd_lfu",
    "FIFO": "libcsmgrd_fifo",
    "None": "None",
}


def _normalize_cache_algorithm(algorithm):
    if algorithm is None:
        return None
    return _ALGORITHM_LIB_NAMES.get(algorithm, algorithm)


def _select_k_centers(manager, exclude, rng):
    count = manager.default_config.get("count", 0)
    return select_k_centers(manager.graph, count, exclude=exclude)


def _select_manual(manager, exclude, rng):
    manual_ids = sorted(manager.node_overrides.keys())
    return [idx for idx in manual_ids if idx not in exclude]


def _select_degree_based(manager, exclude, rng):
    count = manager.default_config.get("count", 0)
    degree = {node: len(neighbors) for node, neighbors in manager.graph.items()}
    sorted_nodes = sorted(
        [n for n in degree if n not in exclude],
        key=lambda n: (-degree[n], n),
    )
    return sorted_nodes[:count]


_CACHE_STRATEGIES = {
    "k_centers": _select_k_centers,
    "manual": _select_manual,
    "degree_based": _select_degree_based,
}


class CacheConfigManager:
    """Manage per-node cache configuration from a cache_config dict.

    Supports three node-selection strategies:
    - k_centers: Greedy farthest-first selection (default)
    - manual: Nodes taken from the ``nodes`` section IDs
    - degree_based: Highest-degree nodes selected first

    Per-node overrides in the ``nodes`` section are applied after the
    default settings, allowing heterogeneous cache configurations.
    """

    def __init__(
        self,
        cache_config: dict,
        host_count: int,
        graph: dict,
        publisher_ids: set,
    ):
        self.strategy = cache_config.get("strategy", "k_centers")
        self.default_config = cache_config.get("default", {})
        self.node_overrides = self._parse_node_overrides(cache_config.get("nodes", []))
        self.host_count = host_count
        self.graph = graph
        self.publisher_ids = publisher_ids

    def _parse_node_overrides(self, nodes_list: list) -> dict:
        """Parse the nodes section into a per-node override mapping.

        Args:
            nodes_list: List of dicts with 'id' and override fields.

        Returns:
            Dict mapping host index -> override settings dict.
        """
        overrides = {}
        for entry in nodes_list or []:
            ids = entry.get("id", [])
            if isinstance(ids, int):
                ids = [ids]
            settings = {k: v for k, v in entry.items() if k != "id"}
            for node_id in ids:
                overrides[int(node_id)] = settings
        return overrides

    def select_cache_nodes(self, exclude: set | None = None, rng=None) -> list:
        """Select cache node indices based on the configured strategy.

        Args:
            exclude: Set of host IDs to exclude (e.g. publishers).
            rng: Random number generator (unused, reserved for future use).

        Returns:
            List of selected cache node IDs.
        """
        exclude = exclude or set()
        strategy_fn = _CACHE_STRATEGIES.get(self.strategy)
        if strategy_fn is None:
            raise ValueError(
                f"Unknown cache strategy: {self.strategy}. "
                f"Available: {list(_CACHE_STRATEGIES)}"
            )
        return strategy_fn(self, exclude, rng)

    def apply_configs(self, cache_nodes: set) -> None:
        """Apply default cache settings and per-node overrides to host configs.

        Steps:
        1. Write default CACHE_* values (and CS_MODE=2) to all cache nodes.
        2. For each node listed in the ``nodes`` section, overwrite with
           node-specific values.

        Args:
            cache_nodes: Set of host indices that are cache nodes.
        """
        default = self.default_config

        # Step 1: apply CS_MODE=2 + default settings to all cache nodes
        apply_cache_node_settings(
            self.host_count,
            cache_nodes,
            cache_default_rct_ms=default.get("default_rct_ms"),
            cache_capacity=default.get("capacity"),
            cache_algorithm=_normalize_cache_algorithm(default.get("algorithm")),
            cache_type=default.get("type"),
            publishers=self.publisher_ids,
        )

        # Step 2: apply per-node overrides
        _FIELD_MAP = {
            "default_rct_ms": "CACHE_DEFAULT_RCT",
            "capacity": "CACHE_CAPACITY",
            "algorithm": "CACHE_ALGORITHM",
            "type": "CACHE_TYPE",
        }
        for idx in sorted(cache_nodes):
            if idx not in self.node_overrides:
                continue
            overrides = self.node_overrides[idx]
            conf_path = Path(f"h{idx}") / "csmgrd.conf"
            for field, conf_key in _FIELD_MAP.items():
                if field in overrides:
                    value = overrides[field]
                    if field == "algorithm":
                        value = _normalize_cache_algorithm(value)
                    _set_config_value(conf_path, conf_key, str(value))


class CachePlacement:
    """Decide which hosts are cache nodes and apply their cache settings.

    Owns strategy resolution (cache_config vs legacy k-centers), the
    publisher-exclusion policy, the cache-count fallback, the last-host
    fallback, the cache-node log, and settings application — one module
    instead of per-scenario copies.

    Args:
        host_count: Total number of hosts.
        host_graph: Host adjacency graph (as built by build_host_graph).
        publisher_ids: Host indices acting as publishers.
        cache_config: Optional cache_config dict; selects the
            CacheConfigManager path when given.
        cache_count: Number of cache nodes (legacy path; 0 = down_count + 1).
        down_count: Hosts downed per cycle (legacy count fallback).
        exclude_publishers: Whether publishers are ineligible for caching
            (disaster excludes them; connect keeps them eligible).
        cache_default_rct_ms: CACHE_DEFAULT_RCT override (legacy path only).
    """

    def __init__(
        self,
        *,
        host_count,
        host_graph,
        publisher_ids,
        cache_config=None,
        cache_count=0,
        down_count=0,
        exclude_publishers=True,
        cache_default_rct_ms=None,
    ):
        self._host_count = host_count
        self._graph = host_graph
        self._publisher_ids = set(publisher_ids or ())
        self._cache_count = cache_count
        self._down_count = down_count
        self._exclude = self._publisher_ids if exclude_publishers else set()
        self._cache_default_rct_ms = cache_default_rct_ms
        self._manager = (
            CacheConfigManager(
                cache_config, host_count, host_graph, self._publisher_ids
            )
            if cache_config
            else None
        )

    def decide(self):
        """Placement decision (selection + fallbacks); no side effects.

        Returns:
            List of selected cache node indices.
        """
        if self._manager is not None:
            nodes = self._manager.select_cache_nodes(exclude=self._exclude)
        else:
            count = (
                self._cache_count if self._cache_count > 0 else self._down_count + 1
            )
            nodes = select_k_centers(self._graph, count, exclude=self._exclude)
        if not nodes and self._host_count > 0:
            nodes = [self._host_count - 1]
        return list(nodes)

    def place(self):
        """Decide, log, and apply cache settings.

        Returns:
            The cache node set.
        """
        nodes = self.decide()
        if nodes:
            info("cache nodes: " + ", ".join(f"h{idx}" for idx in nodes) + "\n")
        cache_node_set = set(nodes)
        if self._manager is not None:
            self._manager.apply_configs(cache_node_set)
        else:
            apply_cache_node_settings(
                self._host_count,
                cache_node_set,
                self._cache_default_rct_ms,
                publishers=self._publisher_ids,
            )
        return cache_node_set
