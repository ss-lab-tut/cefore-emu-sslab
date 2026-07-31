"""Resolve and apply per-node cefnetd forwarding strategy settings."""

from pathlib import Path
from typing import Any

from .template import _set_config_value

DEFAULT_FORWARDING_CONFIG = {"default": "flooding"}


def resolve_forwarding_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Return the concrete forwarding policy used for this run."""
    if config is None:
        return dict(DEFAULT_FORWARDING_CONFIG)

    resolved: dict[str, Any] = {"default": config.get("default", "flooding")}
    nodes = config.get("nodes", [])
    if nodes:
        resolved["nodes"] = nodes
    return resolved


class ForwardingConfigManager:
    """Apply a resolved forwarding policy to every generated host config."""

    def __init__(self, config: dict[str, Any] | None):
        self.config = resolve_forwarding_config(config)
        self.default_strategy = self.config["default"]
        self.node_overrides = self._parse_node_overrides(self.config.get("nodes", []))

    def _parse_node_overrides(self, nodes_list: list[dict[str, Any]]) -> dict[int, str]:
        """Map host index to its configured forwarding strategy override."""
        overrides: dict[int, str] = {}
        for entry in nodes_list or []:
            strategy = entry.get("strategy")
            if strategy is None:
                continue
            for node_id in entry.get("id", []):
                overrides[int(node_id)] = strategy
        return overrides

    def strategy_for(self, host_idx: int) -> str:
        """Return the effective strategy for one host."""
        return self.node_overrides.get(host_idx, self.default_strategy)

    def apply_configs(self, host_count: int) -> None:
        """Write FORWARDING_STRATEGY before cefnetd starts."""
        for idx in range(host_count):
            conf_path = Path(f"h{idx}") / "cefnetd.conf"
            _set_config_value(conf_path, "FORWARDING_STRATEGY", self.strategy_for(idx))
