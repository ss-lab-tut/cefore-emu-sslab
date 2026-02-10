"""Flexible auto-generation with priority-based configuration.

This module extends auto_generator.py with priority URI support,
automatically applying mode and configuration based on URI patterns.
"""

import random
from pathlib import Path
from typing import Any, Optional

from .priority_resolver import PriorityConfigManager


def _error(msg: str) -> None:
    raise ValueError(msg)


def parse_consumer_spec(spec: str | list[int], host_count: int, rng: random.Random) -> list[int]:
    """Parse consumer specification: 'random:N' or list."""
    if isinstance(spec, list):
        return [int(h) for h in spec]
    if isinstance(spec, str) and spec.startswith("random"):
        # allow both "random:N" and "randomN"
        num = spec.split(":")[1] if ":" in spec else spec.replace("random", "", 1)
        try:
            count = int(num)
        except (ValueError, IndexError):
            return []
        available = list(range(host_count))
        count = min(count, len(available))
        return rng.sample(available, count)
    return []


def _parse_publishers(entry: dict[str, Any], host_count: int, rng: random.Random) -> list[int]:
    pubs = entry.get("publishers")
    if pubs is None:
        return rng.sample(list(range(host_count)), 1)
    if isinstance(pubs, list):
        pubs = [int(p) for p in pubs]
    elif isinstance(pubs, str) and pubs.startswith("random"):
        pubs = parse_consumer_spec(pubs, host_count, rng)
    else:
        _error("publishers must be list or 'random:N'")
    if any(p < 0 or p >= host_count for p in pubs):
        _error("publisher id out of range")
    if not pubs:
        _error("no publishers resolved")
    return pubs


def _parse_consumers(
    entry: dict[str, Any],
    host_count: int,
    rng: random.Random,
    publishers: list[int],
) -> list[int]:
    cons = entry.get("consumers")
    if cons is None:
        return []
    cons_list = (
        parse_consumer_spec(cons, host_count, rng)
        if isinstance(cons, str)
        else [int(c) for c in cons]
    )
    cons_list = [c for c in cons_list if c not in publishers]
    for c in cons_list:
        if c < 0 or c >= host_count:
            _error("consumer id out of range")
    return cons_list


def _normalize_auto(auto_config: Any) -> list[dict[str, Any]]:
    """Accept list or single dict; return list of entries."""
    if isinstance(auto_config, list):
        return auto_config
    if isinstance(auto_config, dict):
        return [auto_config]
    _error("auto must be a dict or list of dicts")


def generate_operations_with_priority(
    auto_config: dict[str, Any] | list[dict[str, Any]],
    host_count: int,
    seed: int | None,
    run_dir: Path = None,
    priority_manager: Optional[PriorityConfigManager] = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Generate operations with priority-based configuration.

    Args:
        auto_config: Auto configuration dict or list of dicts.
        host_count: Total number of hosts.
        seed: Random seed.
        run_dir: Output directory for received files.
        priority_manager: PriorityConfigManager for URI-based config.

    Returns:
        Tuple of (puts_list, gets_list) with priority settings applied.
    """
    if run_dir is None:
        run_dir = Path(".")
    rng = random.Random(seed)

    entries = _normalize_auto(auto_config)
    puts_list: list[dict[str, Any]] = []
    gets_list: list[dict[str, Any]] = []

    for entry in entries:
        if not isinstance(entry, dict):
            _error("auto entry must be a dict")

        uri = entry.get("uri")
        if not uri or not isinstance(uri, str):
            _error("auto entry requires 'uri' (string)")

        content_count = int(entry.get("content_count", 1))
        if content_count < 1:
            _error("content_count must be >=1")

        publishers = _parse_publishers(entry, host_count, rng)
        consumers = _parse_consumers(entry, host_count, rng, publishers)

        file_path = entry.get("file", "./sample-putfile")

        # Extract explicit pub/sub opts from entry (override priority defaults)
        explicit_pub_opts = entry.get("pub_opts", {}) or {}
        explicit_sub_opts = entry.get("sub_opts", {}) or {}

        # Backward compatibility: allow consumer_per_content in sub_opts.
        consumer_per_content_value = entry.get("consumer_per_content")
        if consumer_per_content_value is None:
            consumer_per_content_value = explicit_sub_opts.get("consumer_per_content", 1)
        consumer_per_content = int(consumer_per_content_value)

        # Keep explicit mode only. If priority is disabled, preserve legacy default.
        entry_mode = entry.get("mode")
        if entry_mode is None and not priority_manager:
            entry_mode = "pubsub"

        # Create contents
        for idx in range(content_count):
            uri_full = f"{uri}/content{idx+1}" if content_count > 1 else uri
            pub_host = rng.choice(publishers)

            # Create base put operation
            put_op = {
                "host": pub_host,
                "uri": uri_full,
                "file": file_path,
            }
            if entry_mode is not None:
                put_op["mode"] = entry_mode

            # Add explicit opts
            if entry_mode == "pubsub":
                if explicit_pub_opts:
                    put_op["pub_opts"] = dict(explicit_pub_opts)
            elif entry_mode == "putget":
                # putget mode: merge explicit opts into top level
                for key in ("rate", "block_size", "expiry", "cache_time", "valid_algo", "port_num"):
                    if key in explicit_pub_opts:
                        put_op[key] = explicit_pub_opts[key]
            else:
                # Mode will be resolved from full URI later; preserve explicit opts for both mode shapes.
                if explicit_pub_opts:
                    put_op["pub_opts"] = dict(explicit_pub_opts)
                for key in ("rate", "block_size", "expiry", "cache_time", "valid_algo", "port_num"):
                    if key in explicit_pub_opts:
                        put_op[key] = explicit_pub_opts[key]

            # Apply priority configuration (won't override explicit settings)
            if priority_manager:
                put_op = priority_manager.apply_to_put(put_op)

            puts_list.append(put_op)

            # Create get operations
            if consumers:
                for _ in range(consumer_per_content):
                    cons = rng.choice(consumers)

                    # Create base get operation
                    get_op = {
                        "host": cons,
                        "uri": uri_full,
                        "file": str(run_dir / f"recv_{cons}_{uri_full.split('/')[-1]}"),
                    }
                    if entry_mode is not None:
                        get_op["mode"] = entry_mode

                    # Add explicit opts
                    if entry_mode == "pubsub":
                        if explicit_sub_opts:
                            get_op["sub_opts"] = dict(explicit_sub_opts)
                        if "wait" in explicit_sub_opts:
                            get_op["wait"] = explicit_sub_opts["wait"]
                    elif entry_mode == "putget":
                        # putget mode: merge explicit opts into top level
                        for key in ("owner_only", "chunk", "pipeline", "valid_algo", "port_num", "sg"):
                            if key in explicit_sub_opts:
                                get_op[key] = explicit_sub_opts[key]
                    else:
                        # Mode will be resolved from full URI later; preserve explicit opts for both mode shapes.
                        if explicit_sub_opts:
                            get_op["sub_opts"] = dict(explicit_sub_opts)
                        if "wait" in explicit_sub_opts:
                            get_op["wait"] = explicit_sub_opts["wait"]
                        for key in ("owner_only", "chunk", "pipeline", "valid_algo", "port_num", "sg"):
                            if key in explicit_sub_opts:
                                get_op[key] = explicit_sub_opts[key]

                    # Apply priority configuration (won't override explicit settings)
                    if priority_manager:
                        get_op = priority_manager.apply_to_get(get_op)

                    gets_list.append(get_op)

    return puts_list, gets_list


def generate_operations(
    auto_config: dict[str, Any] | list[dict[str, Any]],
    host_count: int,
    seed: int | None,
    run_dir: Path = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Generate operations without priority support (backward compatible).

    This function maintains backward compatibility with the original
    auto_generator.py behavior (pubsub mode only).

    Args:
        auto_config: Auto configuration dict or list of dicts.
        host_count: Total number of hosts.
        seed: Random seed.
        run_dir: Output directory for received files.

    Returns:
        Tuple of (puts_list, gets_list).
    """
    return generate_operations_with_priority(
        auto_config, host_count, seed, run_dir, priority_manager=None
    )
