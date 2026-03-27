"""Priority-based URI configuration resolver.

This module implements URI pattern matching and automatic configuration
application for priority-based content distribution.
"""

import re
from copy import deepcopy
from typing import Any


class PriorityConfigManager:
    """Resolve URI priority levels and apply defaults to put/get operations."""

    def __init__(self, priority_config: dict[str, Any] | None = None):
        self.levels: dict[str, dict[str, Any]] = {}
        self.patterns: list[tuple[str, str, dict[str, Any]]] = []
        if priority_config:
            self._parse_config(priority_config)

    def _parse_config(self, config: dict[str, Any]) -> None:
        for level_name, level_config in config.items():
            if not isinstance(level_config, dict):
                continue

            patterns = level_config.get("patterns", [])
            if not isinstance(patterns, list):
                patterns = [patterns]

            self.levels[level_name] = {
                "mode": level_config.get("mode", "putget"),
                "expiry": level_config.get("expiry"),
                "cache_time": level_config.get("cache_time"),
                "rate": level_config.get("rate"),
                "block_size": level_config.get("block_size"),
                "valid_algo": level_config.get("valid_algo"),
                "port_num": level_config.get("port_num"),
                "lifetime": level_config.get("lifetime"),
                "retry_limit": level_config.get("retry_limit"),
                "target": level_config.get("target"),
                "pipeline": level_config.get("pipeline"),
                "ti_valid_algo": level_config.get("ti_valid_algo"),
                "rd_valid_algo": level_config.get("rd_valid_algo"),
                "ri_valid_algo": level_config.get("ri_valid_algo"),
                "td_valid_algo": level_config.get("td_valid_algo"),
            }

            for pattern in patterns:
                regex_pattern = self._wildcard_to_regex(pattern)
                self.patterns.append(
                    (regex_pattern, level_name, self.levels[level_name])
                )

    @staticmethod
    def _wildcard_to_regex(pattern: str) -> str:
        escaped = re.escape(pattern)
        regex = escaped.replace(r"\*", ".*")
        return f"^{regex}$"

    def resolve_priority(self, uri: str) -> tuple[str | None, dict[str, Any] | None]:
        for regex_pattern, level_name, config in self.patterns:
            if re.match(regex_pattern, uri):
                return level_name, config
        return None, None

    def apply_to_put(self, operation: dict[str, Any]) -> dict[str, Any]:
        uri = operation.get("uri")
        if not uri:
            return operation

        _, config = self.resolve_priority(uri)
        if not config:
            return operation

        modified = dict(operation)
        if isinstance(modified.get("pub_opts"), dict):
            modified["pub_opts"] = deepcopy(modified["pub_opts"])

        mode = modified.get("mode")
        if not mode:
            mode = config.get("mode")
            if mode:
                modified["mode"] = mode

        if mode == "pubsub":
            pub_opts = modified.get("pub_opts")
            if not isinstance(pub_opts, dict):
                pub_opts = {}
            if config.get("expiry") is not None and "expiry" not in pub_opts:
                pub_opts["expiry"] = config["expiry"]
            if config.get("cache_time") is not None and "cache_time" not in pub_opts:
                pub_opts["cache_time"] = config["cache_time"]
            if config.get("rate") is not None and "rate" not in pub_opts:
                pub_opts["rate"] = config["rate"]
            if config.get("block_size") is not None and "block_size" not in pub_opts:
                pub_opts["block_size"] = config["block_size"]
            if config.get("lifetime") is not None and "lifetime" not in pub_opts:
                pub_opts["lifetime"] = config["lifetime"]
            if (
                config.get("retry_limit") is not None
                and "retry_limit" not in pub_opts
            ):
                pub_opts["retry_limit"] = config["retry_limit"]
            if config.get("target") is not None and "target" not in pub_opts:
                pub_opts["target"] = config["target"]
            if (
                config.get("ti_valid_algo") is not None
                and "ti_valid_algo" not in pub_opts
            ):
                pub_opts["ti_valid_algo"] = config["ti_valid_algo"]
            if (
                config.get("rd_valid_algo") is not None
                and "rd_valid_algo" not in pub_opts
            ):
                pub_opts["rd_valid_algo"] = config["rd_valid_algo"]
            if config.get("port_num") is not None and "port_num" not in pub_opts:
                pub_opts["port_num"] = config["port_num"]
            if pub_opts:
                modified["pub_opts"] = pub_opts
        else:
            if config.get("expiry") is not None and "expiry" not in modified:
                modified["expiry"] = config["expiry"]
            if config.get("cache_time") is not None and "cache_time" not in modified:
                modified["cache_time"] = config["cache_time"]
            if config.get("rate") is not None and "rate" not in modified:
                modified["rate"] = config["rate"]
            if config.get("block_size") is not None and "block_size" not in modified:
                modified["block_size"] = config["block_size"]
            if config.get("valid_algo") is not None and "valid_algo" not in modified:
                modified["valid_algo"] = config["valid_algo"]
            if config.get("port_num") is not None and "port_num" not in modified:
                modified["port_num"] = config["port_num"]

        return modified

    def apply_to_get(self, operation: dict[str, Any]) -> dict[str, Any]:
        uri = operation.get("uri")
        if not uri:
            return operation

        _, config = self.resolve_priority(uri)
        if not config:
            return operation

        modified = dict(operation)
        if isinstance(modified.get("sub_opts"), dict):
            modified["sub_opts"] = deepcopy(modified["sub_opts"])

        mode = modified.get("mode")
        if not mode:
            mode = config.get("mode")
            if mode:
                modified["mode"] = mode

        if mode == "pubsub":
            sub_opts = modified.get("sub_opts")
            if not isinstance(sub_opts, dict):
                sub_opts = {}
            if config.get("pipeline") is not None and "pipeline" not in sub_opts:
                sub_opts["pipeline"] = config["pipeline"]
            if (
                config.get("ri_valid_algo") is not None
                and "ri_valid_algo" not in sub_opts
            ):
                sub_opts["ri_valid_algo"] = config["ri_valid_algo"]
            if (
                config.get("td_valid_algo") is not None
                and "td_valid_algo" not in sub_opts
            ):
                sub_opts["td_valid_algo"] = config["td_valid_algo"]
            if config.get("port_num") is not None and "port_num" not in sub_opts:
                sub_opts["port_num"] = config["port_num"]
            if sub_opts:
                modified["sub_opts"] = sub_opts
        else:
            if config.get("pipeline") is not None and "pipeline" not in modified:
                modified["pipeline"] = config["pipeline"]
            if config.get("valid_algo") is not None and "valid_algo" not in modified:
                modified["valid_algo"] = config["valid_algo"]
            if config.get("port_num") is not None and "port_num" not in modified:
                modified["port_num"] = config["port_num"]

        return modified
