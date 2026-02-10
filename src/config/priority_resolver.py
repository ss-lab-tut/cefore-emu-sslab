"""Priority-based URI configuration resolver.

This module implements URI pattern matching and automatic configuration
application for priority-based content distribution.
"""

import re
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple


class PriorityConfigManager:
    """Manages URI priority levels and automatic configuration application.

    Supports wildcard patterns (ccnx:/emergency/*) and automatic mode/expiry
    configuration based on matched priority level.
    """

    def __init__(self, priority_config: Optional[Dict[str, Any]] = None):
        """Initialize priority configuration manager.

        Args:
            priority_config: priority_uris section from config (optional).
        """
        self.levels: Dict[str, Dict[str, Any]] = {}
        self.patterns: List[Tuple[str, str, Dict[str, Any]]] = []

        if priority_config:
            self._parse_config(priority_config)

    def _parse_config(self, config: Dict[str, Any]) -> None:
        """Parse priority_uris configuration.

        Args:
            config: priority_uris dictionary with level definitions.
        """
        for level_name, level_config in config.items():
            if not isinstance(level_config, dict):
                continue

            patterns = level_config.get("patterns", [])
            if not isinstance(patterns, list):
                patterns = [patterns]

            # Store level configuration
            self.levels[level_name] = {
                "mode": level_config.get("mode", "putget"),
                "expiry": level_config.get("expiry"),
                "cache_time": level_config.get("cache_time"),
                "prefetch_to_cache": level_config.get("prefetch_to_cache", False),
                "rate": level_config.get("rate"),
                "block_size": level_config.get("block_size"),
                "valid_algo": level_config.get("valid_algo"),
                "port_num": level_config.get("port_num"),
                # pubsub-specific options
                "lifetime": level_config.get("lifetime"),
                "retry_limit": level_config.get("retry_limit"),
                "target": level_config.get("target"),
                "pipeline": level_config.get("pipeline"),
                # validation algorithms
                "ti_valid_algo": level_config.get("ti_valid_algo"),
                "rd_valid_algo": level_config.get("rd_valid_algo"),
                "ri_valid_algo": level_config.get("ri_valid_algo"),
                "td_valid_algo": level_config.get("td_valid_algo"),
            }

            # Convert wildcard patterns to regex
            for pattern in patterns:
                # Convert ccnx:/emergency/* to regex
                regex_pattern = self._wildcard_to_regex(pattern)
                self.patterns.append((regex_pattern, level_name, self.levels[level_name]))

    def _wildcard_to_regex(self, pattern: str) -> str:
        """Convert wildcard pattern to regex.

        Args:
            pattern: Wildcard pattern (e.g., "ccnx:/emergency/*")

        Returns:
            Regex pattern string.
        """
        # Escape special regex characters except *
        escaped = re.escape(pattern)
        # Replace escaped \* with .* for wildcard matching
        regex = escaped.replace(r"\*", ".*")
        # Anchor to start and end
        return f"^{regex}$"

    def resolve_priority(self, uri: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Resolve URI to priority level and configuration.

        Args:
            uri: Content URI to resolve.

        Returns:
            Tuple of (level_name, config_dict) or (None, None) if no match.
        """
        for regex_pattern, level_name, config in self.patterns:
            if re.match(regex_pattern, uri):
                return level_name, config

        return None, None

    def apply_to_put(self, operation: dict) -> dict:
        """Apply priority configuration to put operation.

        Args:
            operation: Put operation dictionary.

        Returns:
            Modified operation with priority settings applied.
        """
        uri = operation.get("uri")
        if not uri:
            return operation

        level_name, config = self.resolve_priority(uri)
        if not config:
            return operation

        # Create a copy to avoid modifying original
        modified = dict(operation)
        if isinstance(modified.get("pub_opts"), dict):
            modified["pub_opts"] = deepcopy(modified["pub_opts"])

        # Resolve effective mode:
        # explicit operation mode takes precedence over priority defaults.
        mode = modified.get("mode")
        if not mode:
            mode = config.get("mode")
            if mode:
                modified["mode"] = mode

        # Apply common fields
        if mode == "pubsub":
            # pubsub mode: use pub_opts
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
            if config.get("retry_limit") is not None and "retry_limit" not in pub_opts:
                pub_opts["retry_limit"] = config["retry_limit"]
            if config.get("target") is not None and "target" not in pub_opts:
                pub_opts["target"] = config["target"]
            if config.get("ti_valid_algo") is not None and "ti_valid_algo" not in pub_opts:
                pub_opts["ti_valid_algo"] = config["ti_valid_algo"]
            if config.get("rd_valid_algo") is not None and "rd_valid_algo" not in pub_opts:
                pub_opts["rd_valid_algo"] = config["rd_valid_algo"]
            if config.get("port_num") is not None and "port_num" not in pub_opts:
                pub_opts["port_num"] = config["port_num"]
            if pub_opts:
                modified["pub_opts"] = pub_opts
        else:
            # putget mode: apply directly
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

    def apply_to_get(self, operation: dict) -> dict:
        """Apply priority configuration to get operation.

        Args:
            operation: Get operation dictionary.

        Returns:
            Modified operation with priority settings applied.
        """
        uri = operation.get("uri")
        if not uri:
            return operation

        level_name, config = self.resolve_priority(uri)
        if not config:
            return operation

        # Create a copy to avoid modifying original
        modified = dict(operation)
        if isinstance(modified.get("sub_opts"), dict):
            modified["sub_opts"] = deepcopy(modified["sub_opts"])

        # Resolve effective mode:
        # explicit operation mode takes precedence over priority defaults.
        mode = modified.get("mode")
        if not mode:
            mode = config.get("mode")
            if mode:
                modified["mode"] = mode

        # Apply get-specific fields
        if mode == "pubsub":
            # pubsub mode: use sub_opts
            sub_opts = modified.get("sub_opts")
            if not isinstance(sub_opts, dict):
                sub_opts = {}
            if config.get("pipeline") is not None and "pipeline" not in sub_opts:
                sub_opts["pipeline"] = config["pipeline"]
            if config.get("ri_valid_algo") is not None and "ri_valid_algo" not in sub_opts:
                sub_opts["ri_valid_algo"] = config["ri_valid_algo"]
            if config.get("td_valid_algo") is not None and "td_valid_algo" not in sub_opts:
                sub_opts["td_valid_algo"] = config["td_valid_algo"]
            if config.get("port_num") is not None and "port_num" not in sub_opts:
                sub_opts["port_num"] = config["port_num"]
            if sub_opts:
                modified["sub_opts"] = sub_opts
        else:
            # putget mode: apply directly
            if config.get("pipeline") is not None and "pipeline" not in modified:
                modified["pipeline"] = config["pipeline"]
            if config.get("valid_algo") is not None and "valid_algo" not in modified:
                modified["valid_algo"] = config["valid_algo"]
            if config.get("port_num") is not None and "port_num" not in modified:
                modified["port_num"] = config["port_num"]

        return modified

    def should_prefetch(self, uri: str) -> bool:
        """Check if URI should be prefetched to cache nodes.

        Args:
            uri: Content URI to check.

        Returns:
            True if prefetch_to_cache is enabled for this URI.
        """
        level_name, config = self.resolve_priority(uri)
        if not config:
            return False

        return config.get("prefetch_to_cache", False)
