#!/usr/bin/env python3
"""Reproduce a disaster scenario's mesh topology + roles without Mininet/root.

`python -m src disaster --config X --seed S` builds its mesh topology and
host roles from a single shared ``random.Random(S)`` stream (see
``src/runtime/scenario_setup.py``'s ``build_mesh_scenario``/``MeshBuildSpec``
docstrings, which call this a documented invariant: ``assign_roles()`` draws
from the stream first, then ``MeshTopo(...)`` continues drawing from the same
object). Because that draw order is pure Python (no Mininet, no root, no
filesystem writes beyond reading the config), this tool replays it standalone
so an overnight measurement campaign can verify -- before spending wall-clock
time on an actual emulated run -- that two (config, seed) pairs would build
the identical topology, or that a re-run of the same pair is reproducible.

This is a read-only reproduction, not a substitute for running the scenario:
if disaster's argument wiring or RNG consumption order ever changes, this
tool must change with it (see ``resolve_topology_inputs`` and
``build_fingerprint`` below for the exact points that mirror scenario code).
"""

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cli.args import add_common_args, add_disaster_args, add_mesh_args  # noqa: E402
from src.core.config.loader import load_config, merge_cli_and_config  # noqa: E402
from src.core.events import extract_publications  # noqa: E402
from src.core.roles import assign_roles  # noqa: E402
from src.runtime.topo import MeshTopo  # noqa: E402


def _build_disaster_parser() -> argparse.ArgumentParser:
    """Build the exact CLI surface ``ceforeemu disaster`` registers.

    Mirrors ``src/cli/main.py``'s ``disaster_parser`` construction (common +
    mesh + disaster option blocks, in that order) so config-merge precedence
    and option defaults are byte-identical to a real CLI invocation. Any
    drift here (e.g. a missing block) would silently change which config
    keys are allowed to override which CLI defaults -- see
    ``src/core/config/loader.merge_cli_and_config``, which decides precedence
    by comparing against *this* parser's defaults.
    """
    parser = argparse.ArgumentParser()
    add_common_args(parser)
    add_mesh_args(parser)
    add_disaster_args(parser)
    return parser


def resolve_topology_inputs(config_path: str, seed: int) -> dict:
    """Resolve the exact topology-build inputs a real disaster run would use.

    Returns everything ``MeshBuildSpec`` needs (host/switch counts, degree
    bounds, publisher ids) after replaying the same config-load +
    CLI-precedence merge that ``bootstrap_scenario`` performs, without any of
    bootstrap's side effects (run-dir creation, meta.json, script-log
    tee'ing). Only the config file is read from disk; nothing is written.
    """
    config_data = load_config(config_path)

    # The explicit --seed here plays the same CLI-precedence role as a real
    # `disaster --config X --seed N` invocation: merge_cli_and_config only
    # lets a config value override an arg that still equals the parser's own
    # default, so an explicit --seed always wins over a config-file seed --
    # exactly like the run we are reproducing.
    parser = _build_disaster_parser()
    args = parser.parse_args(["--config", str(config_path), "--seed", str(seed)])

    # merge_cli_and_config needs a *fresh* parser instance to compute "what
    # would argparse default to" -- reusing `parser` above would make our own
    # --config/--seed argv look like the baseline default and defeat the
    # precedence check. See loader.merge_cli_and_config.
    precedence_parser = _build_disaster_parser()
    merge_cli_and_config(args, config_data, precedence_parser)

    # `events` is config-only (cli_allowed=False) but merge_cli_and_config
    # still sets it as an attribute from the config file; disaster.py's
    # __init__ reads it the same way (getattr(args, "events", None) or []).
    events = getattr(args, "events", None) or []
    _, _, publisher_ids = extract_publications(events)

    return {
        "host_count": args.hosts,
        "switch_limit": args.switches,
        "node_per_switch": args.node_per_switch,
        "host_degree_min": args.host_degree_min,
        "host_degree_max": args.host_degree_max,
        "switch_use_all": args.switch_use_all,
        "publisher_ids": frozenset(publisher_ids),
    }


def build_fingerprint(config_path: str, seed: int) -> dict:
    """Reproduce roles + mesh_links for (config, seed) and return a fingerprint dict.

    CRITICAL RNG-order invariant (see build_mesh_scenario in
    src/runtime/scenario_setup.py): a single ``random.Random(seed)`` is
    shared by ``assign_roles()`` (called first) and ``MeshTopo(...)``
    (called second, continuing to draw from the *same* rng object). Calling
    them out of order, or with separate rng instances, silently reproduces a
    different topology than the real run built.

    ``build_mesh_scenario`` also calls ``provision_node_dirs(roles)`` between
    those two steps. That call is a pure filesystem side effect -- verified
    by grepping src/runtime/template.py for `random` usage (none found) --
    so skipping it here does not desync the shared rng stream.
    """
    inputs = resolve_topology_inputs(config_path, seed)
    rng = random.Random(seed)
    roles = assign_roles(inputs["host_count"], rng, inputs["publisher_ids"])
    topo = MeshTopo(
        hosts=inputs["host_count"],
        swhich_num=inputs["switch_limit"],
        rng=rng,
        node_per_switch=inputs["node_per_switch"],
        host_degree_min=inputs["host_degree_min"],
        host_degree_max=inputs["host_degree_max"],
        switch_use_all=inputs["switch_use_all"],
    )

    # mesh_links entries come from iterating a plain dict (`switch_hosts` in
    # MeshTopo.build); insertion order happens to be deterministic per build
    # but is not itself part of the semantic topology. Sort switches and each
    # switch's host list so two structurally identical builds always hash to
    # the same fingerprint.
    links = sorted(
        (entry["switch"], entry["subnet"], sorted(entry["hosts"]))
        for entry in topo.mesh_links
    )

    payload = {
        "hosts": inputs["host_count"],
        "switches_configured": inputs["switch_limit"],
        "switches_realized": len({entry["switch"] for entry in topo.mesh_links}),
        "links": [list(link) for link in links],
        "roles": {str(idx): role.name for idx, role in sorted(roles.items())},
    }
    canonical_json = json.dumps(payload, sort_keys=True)
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    result = dict(payload)
    result["fingerprint"] = digest
    return result


def _compare(paths: list[str]) -> int:
    """Compare the ``fingerprint`` field of previously written JSON files.

    Returns 0 and prints a MATCH line if every file's fingerprint is
    identical, else returns 1 and prints which files differ.
    """
    fingerprints: dict[str, str] = {}
    for raw_path in paths:
        data = json.loads(Path(raw_path).read_text(encoding="utf-8"))
        fingerprints[raw_path] = data.get("fingerprint")

    unique = set(fingerprints.values())
    if len(unique) <= 1:
        print("MATCH: all fingerprints identical")
        return 0

    print("MISMATCH: fingerprints differ")
    for raw_path, fingerprint in fingerprints.items():
        print(f"  {raw_path}: {fingerprint}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reproduce a disaster scenario's mesh topology + roles without "
            "Mininet/root, and print a canonical fingerprint."
        )
    )
    parser.add_argument("--config", help="disaster scenario config (yaml/json)")
    parser.add_argument("--seed", type=int, help="seed to reproduce")
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the full canonical JSON object (compact, one line) "
        "instead of just the fingerprint hash",
    )
    parser.add_argument(
        "--compare",
        nargs="+",
        metavar="FP_JSON",
        help="compare fingerprint JSON files previously written by this "
        "tool (via --json, redirected to a file); exit 0 if all identical, "
        "1 otherwise",
    )
    args = parser.parse_args()

    if args.compare:
        return _compare(args.compare)

    if not args.config or args.seed is None:
        parser.error("--config and --seed are required unless --compare is used")

    result = build_fingerprint(args.config, args.seed)
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(result["fingerprint"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
