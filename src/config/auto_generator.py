"""Auto-generate put/get operations from auto configuration."""

import random
from typing import Any


def parse_consumer_spec(spec: str | list[int], host_count: int, rng: random.Random) -> list[int]:
    """Parse consumer specification.

    Args:
        spec: Either "random:N" string or list of host IDs.
        host_count: Total number of hosts.
        rng: Random number generator.

    Returns:
        List of consumer host IDs.
    """
    if isinstance(spec, list):
        return [int(h) for h in spec]

    if isinstance(spec, str) and spec.startswith("random:"):
        try:
            count = int(spec.split(":")[1])
        except (ValueError, IndexError):
            return []
        available = list(range(host_count))
        count = min(count, len(available))
        return rng.sample(available, count)

    return []


def generate_operations(
    auto_config: dict[str, Any],
    host_count: int,
    seed: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Generate put/get operations from auto configuration.

    Args:
        auto_config: Auto configuration dict with:
            - publishers: list of publisher host IDs
            - consumers: "random:N" string or list of host IDs
            - content_count: number of contents per publisher (default 1)
            - uri_prefix: URI prefix (default "ccnx:/test")
            - consumer_per_content: number of get ops per content (default 1)
        host_count: Total number of hosts.
        seed: Random seed.

    Returns:
        Tuple of (puts_list, gets_list).

    Example auto_config:
        {
            "publishers": [9],
            "consumers": "random:5",
            "content_count": 3,
            "uri_prefix": "ccnx:/test",
            "consumer_per_content": 2
        }
    """
    rng = random.Random(seed)

    publishers = auto_config.get("publishers", [host_count - 1])
    if not publishers:
        publishers = [host_count - 1]

    consumers_spec = auto_config.get("consumers", "random:3")
    consumers = parse_consumer_spec(consumers_spec, host_count, rng)
    consumers = [c for c in consumers if c not in publishers]

    content_count = auto_config.get("content_count", 1)
    uri_prefix = auto_config.get("uri_prefix", "ccnx:/test")
    consumer_per_content = auto_config.get("consumer_per_content", 1)

    puts_list = []
    gets_list = []

    content_idx = 0
    for publisher in publishers:
        for _ in range(content_count):
            content_idx += 1
            uri = f"{uri_prefix}/content{content_idx}"

            puts_list.append({
                "host": publisher,
                "uri": uri,
                "file": "./sample-putfile",
                "log": f"cefputfile_h{publisher}_c{content_idx}.log",
            })

            for _ in range(consumer_per_content):
                if not consumers:
                    break
                consumer = rng.choice(consumers)
                gets_list.append({
                    "host": consumer,
                    "uri": uri,
                    "file": f"./recvfile_h{consumer}_c{content_idx}",
                    "log": f"cefgetfile_h{consumer}_c{content_idx}.log",
                })

    return puts_list, gets_list
