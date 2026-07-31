#!/usr/bin/env python3
"""Generate per-seed m5e timeline configs with offline-computed cache nodes.

Why per-seed: the m5e story needs specific ROLES on specific hosts --
  * warmup must land the control URI on the csmgrd (cache) nodes themselves
    (smoke evidence 2026-07-14: content fetched by a non-cache host is NOT
    re-served to anyone, including that host itself; only a cache node's own
    fetch populates a servable csmgrd copy),
  * the gap-fetch that "teaches" the network the fresh URI must be issued BY
    a cache node,
  * the protagonist / new-consumer / control hosts must NOT be cache nodes,
    or the test would be trivially local.
Cache placement (k_centers) is seed-dependent but fully deterministic and
reproducible offline: build the host adjacency from topo_fingerprint and run
src.core.graph.select_k_centers with the same exclude set (publisher h0).
Verified byte-identical to the runtime csmgrd placement on seed 1101.

Usage:
    .venv/bin/python3 tools/workshop/gen_m5e_config.py --seeds 1101 1102 ...
Writes config/workshop/m5e_static/m5e_s<seed>.yaml
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.core.graph import select_k_centers  # noqa: E402

BASE_CONFIG = ROOT / "config/workshop/m5e_pubdown_timeline.yaml"
OUT_DIR = ROOT / "config/workshop/m5e_static"
CACHE_COUNT = 5
PUBLISHER = 0


def topo_for(seed: int) -> tuple[dict[int, list[int]], list[int]]:
    """Offline host adjacency + runtime-identical k_centers csmgrd placement."""
    p = subprocess.run(
        [
            str(ROOT / ".venv/bin/python3"),
            str(ROOT / "tools/workshop/topo_fingerprint.py"),
            "--config",
            str(BASE_CONFIG),
            "--seed",
            str(seed),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    fp = json.loads(p.stdout)
    graph: dict[int, set[int]] = {}
    for link in fp["links"]:
        hosts = link["hosts"] if isinstance(link, dict) else link[2]
        for a in hosts:
            for b in hosts:
                if a != b:
                    graph.setdefault(a, set()).add(b)
    ordered = {k: sorted(v) for k, v in sorted(graph.items())}
    return ordered, sorted(select_k_centers(ordered, CACHE_COUNT, exclude={PUBLISHER}))


def _all_shortest_paths(graph: dict[int, list[int]], src: int, dst: int):
    from collections import deque

    dist = {src: 0}
    parents: dict[int, list[int]] = {}
    q = deque([src])
    while q:
        n = q.popleft()
        for m in graph.get(n, ()):  # noqa: B905
            if m not in dist:
                dist[m] = dist[n] + 1
                parents[m] = [n]
                q.append(m)
            elif dist[m] == dist[n] + 1:
                parents[m].append(n)
    paths: list[list[int]] = []

    def walk(node, acc):
        if node == src:
            paths.append([src] + list(reversed(acc)))
            return
        for pp in parents.get(node, []):
            walk(pp, acc + [node])

    if dst in dist:
        walk(dst, [])
    return paths


def pick_roles(
    graph: dict[int, list[int]], cache_nodes: list[int], host_count: int = 15
) -> dict[str, int] | None:
    """Role assignment driven by ON-PATH cache coverage (smoke3 finding).

    Empirical mechanism (seed 1101, 3 smokes): a consumer can fetch during a
    publisher outage IFF a csmgrd node sits on its consumer->publisher
    forwarding path AND that csmgrd already holds a replica. Non-cache hosts
    run CS_MODE=0 (no cache at all), so nothing else can answer.

    Therefore:
      protagonist / newcomer / control -> non-cache hosts whose EVERY
        shortest path to the publisher crosses a cache node (so the arc and
        the control line are structurally possible), with a shared on-path
        cache node between protagonist and newcomer (the replica planted by
        the protagonist's gap fetch must sit on the newcomer's path too);
      unlucky -> a non-cache host with NO cache node on any shortest path
        (the honest contrast line: never rescued during a window).
    Returns None when the seed's topology cannot cast all four roles.
    """
    cache_set = set(cache_nodes)
    covered: dict[int, set[int]] = {}
    uncovered: list[int] = []
    for h in range(1, host_count):
        if h in cache_set or h == PUBLISHER:
            continue
        paths = _all_shortest_paths(graph, h, PUBLISHER)
        if not paths:
            continue
        per_path = [set(p[1:-1]) & cache_set for p in paths]
        if all(per_path):
            covered[h] = set.intersection(*per_path) if len(per_path) > 1 else per_path[0]
            if not covered[h]:
                # every path crosses SOME cache node but no single node is
                # common to all paths; still usable for control, weaker for
                # the protagonist/newcomer pairing -- keep union for pairing
                covered[h] = set.union(*per_path)
        elif not any(per_path):
            uncovered.append(h)
    pairs = [
        (a, b)
        for a in covered
        for b in covered
        if a < b and covered[a] & covered[b]
    ]
    if not pairs or not uncovered:
        return None
    protagonist, newcomer = pairs[0]
    control_pool = [h for h in covered if h not in (protagonist, newcomer)]
    control = control_pool[0] if control_pool else newcomer
    return {
        "protagonist": protagonist,
        "newcomer": newcomer,
        "control": control,
        "unlucky": uncovered[0],
    }


def render(seed: int) -> str | None:
    graph, cache_nodes = topo_for(seed)
    roles = pick_roles(graph, cache_nodes)
    if roles is None:
        return None
    warmup = "\n".join(
        f'  - host: {h}\n    uri: "ccnx:/m5e/cached"' for h in cache_nodes
    )
    return f"""\
# =============================================================================
# M5e per-seed timeline config (seed {seed}) -- GENERATED by
# tools/workshop/gen_m5e_config.py; edit the generator, not this file.
#
# Offline-computed csmgrd placement for this seed: {cache_nodes}
# Roles (chosen by on-path cache analysis; see pick_roles docstring):
#   protagonist h{roles['protagonist']} (cache ON path; first touch inside window1 ->
#     fails, gap fetch plants a replica in the on-path csmgrd -> survives
#     window2/3),
#   newcomer   h{roles['newcomer']} (shares an on-path cache node with the
#     protagonist; first touch inside window2 -> served by the network cache),
#   control    h{roles['control']} (cache ON path; polls the warmup-cached URI
#     end to end -> flat success line),
#   unlucky    h{roles['unlucky']} (NO cache on any path; honest contrast --
#     fails in every window no matter what).
# Windows (config-time): [20,45], [55,75], [85,105]; observed drift +6..9s.
# Actual times come from results.json host_down/host_up records.
# =============================================================================

hosts: 15
switches: 48
seed: {seed}
k: 2
host_degree_min: 2
host_degree_max: 6

num: 1                  # placeholder; overridden per job
output_dir: "logs"
no_cli: true
duration: 150
results_json: "results.json"
publisher_host: 0

cache_config:
  strategy: "k_centers"
  default:
    count: {CACHE_COUNT}
    capacity: 819200
    default_rct_ms: 1800000
    algorithm: "LRU"
    type: "memory"

# Warm the control URI onto the cache nodes THEMSELVES (per-seed list above).
# Only an on-path csmgrd replica can answer during an outage (CS_MODE=0
# everywhere else), and only a fetch that traverses/originates at the cache
# node plants one. The fresh URI deliberately never appears here.
warmup_gets:
{warmup}

# interval counts from the PREVIOUS cycle's down moment and a still-down
# target is skipped, so interval MUST exceed the previous duration.
# Window1 is the longest so the protagonist's first touch reliably lands
# inside it despite the +6..9s failure-manager start drift.
failure_scenarios:
  strategy: "manual"
  cycles:
    - interval: 20
      duration: 25
      target: [0]
      allow_publishers: true
    - interval: 35
      duration: 20
      target: [0]
      allow_publishers: true
    - interval: 30
      duration: 20
      target: [0]
      allow_publishers: true

events:
  # Both puts execute in the autotest seed phase regardless of `at`.
  - at: 0
    type: put
    host: 0
    uri: "ccnx:/m5e/cached"
    file: "./sample-putfile"
  - at: 1
    type: put
    host: 0
    uri: "ccnx:/m5e/fresh"
    file: "./sample-putfile"

  # Control line: warmup-cached URI polled by an on-path consumer all run.
  - at: 5
    type: get
    host: {roles['control']}
    uri: "ccnx:/m5e/cached"
    repeat:
      interval: 5
      count: 23

  # Protagonist: first touch INSIDE window1 (never before it -- an earlier
  # success would plant the replica early and erase the valley).
  - at: 35
    type: get
    host: {roles['protagonist']}
    uri: "ccnx:/m5e/fresh"
    repeat:
      interval: 4
      count: 22

  # Unlucky contrast: no cache on any path -> fails in every window.
  - at: 37
    type: get
    host: {roles['unlucky']}
    uri: "ccnx:/m5e/fresh"
    repeat:
      interval: 4
      count: 22

  # New consumer: first touch inside window2, after the protagonist's gap
  # fetch planted the replica on their shared cache node.
  - at: 68
    type: get
    host: {roles['newcomer']}
    uri: "ccnx:/m5e/fresh"
    repeat:
      interval: 4
      count: 14
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", required=True)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for seed in args.seeds:
        text = render(seed)
        if text is None:
            print(f"seed {seed}: cannot cast roles (no covered pair or no uncovered host); SKIP")
            continue
        path = OUT_DIR / f"m5e_s{seed}.yaml"
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
