"""Auto-generate put/get or pub/sub operations from auto configuration."""

import random
from pathlib import Path
from typing import Any


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


def _parse_consumers(entry: dict[str, Any], host_count: int, rng: random.Random, publishers: list[int]) -> list[int]:
    cons = entry.get("consumers")
    if cons is None:
        return []
    cons_list = parse_consumer_spec(cons, host_count, rng) if isinstance(cons, str) else [int(c) for c in cons]
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


def generate_operations(
    auto_config: dict[str, Any] | list[dict[str, Any]],
    host_count: int,
    seed: int | None,
    run_dir: Path = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Generate operations from auto configuration with pub/sub support."""
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
        pub_opts = entry.get("pub_opts", {}) or {}
        sub_opts = entry.get("sub_opts", {}) or {}
        wait = sub_opts.get("wait")

        # Create contents
        for idx in range(content_count):
            uri_full = f"{uri}/content{idx+1}" if content_count > 1 else uri
            pub_host = rng.choice(publishers)
            puts_list.append(
                {
                    "mode": "pubsub",
                    "host": pub_host,
                    "uri": uri_full,
                    "file": file_path,
                    "pub_opts": pub_opts,
                }
            )
            for _ in range(sub_opts.get("consumer_per_content", 1) if consumers else 0):
                if not consumers:
                    break
                cons = rng.choice(consumers)
                gets_list.append(
                    {
                        "mode": "pubsub",
                        "host": cons,
                        "uri": uri_full,
                        "file": str(run_dir / f"recv_{cons}_{uri_full.split('/')[-1]}"),
                        "sub_opts": sub_opts,
                        "wait": wait,
                    }
                )

    return puts_list, gets_list
