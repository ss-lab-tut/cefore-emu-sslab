#!/usr/bin/env python
"""Unified CLI entry point for cefore-emu.

Usage:
    sudo python3 -m cli.main linear --hosts 5
    sudo python3 -m cli.main mesh --hosts 8 --switches 12
    sudo python3 -m cli.main disaster --config experiment.yaml
"""

import argparse
import json
import sys

from mininet.log import setLogLevel

from ..core.config.loader import load_config, merge_cli_and_config, validate_config, validate_merged_args
from ..core.debug import build_debug_config
from ..core.paths import resolve_run_dir, resolve_run_path
from ..core.tee import Tee
from .args import add_common_args, add_debug_args, add_disaster_args, add_mesh_args


def cmd_linear(args):
    """Run linear topology scenario."""
    from ..scenarios.linear import run_linear_scenario
    run_dir = resolve_run_dir(args)
    debug_config = build_debug_config(args)
    setLogLevel("info")
    run_linear_scenario(args.hosts, run_dir=run_dir, debug_config=debug_config)


def cmd_mesh(args):
    """Run mesh topology scenario."""
    from ..scenarios.mesh import run_mesh_scenario
    run_dir = resolve_run_dir(args)
    debug_config = build_debug_config(args)
    setLogLevel("info")
    run_mesh_scenario(
        host_num=args.hosts,
        swhich_num=args.switches,
        seed=args.seed,
        k_paths=args.k,
        topo_png=args.topo_png,
        topo_layout=args.topo_layout,
        node_per_switch=args.node_per_switch,
        host_degree_min=args.host_degree_min,
        host_degree_max=args.host_degree_max,
        switch_use_all=args.switch_use_all,
        run_dir=run_dir,
        debug_config=debug_config,
    )


def cmd_disaster(args):
    """Run disaster topology scenario."""
    from ..scenarios.disaster import run_disaster_scenario
    from pathlib import Path

    config_data = load_config(args.config)

    # Build parser for CLI-precedence merge
    cli_parser = argparse.ArgumentParser()
    add_common_args(cli_parser)
    add_mesh_args(cli_parser)
    add_disaster_args(cli_parser)
    # Merge first so CLI values take precedence, then validate the merged result
    merge_cli_and_config(args, config_data, cli_parser)
    errors = validate_merged_args(args)
    if errors:
        for error in errors:
            print(f"config error: {error}", file=sys.stderr)
        sys.exit(1)

    run_dir = resolve_run_dir(args)

    seed_label = "none" if args.seed is None else str(args.seed)
    if args.topo_png is None:
        args.topo_png = f"ex{args.hosts}_seed{seed_label}.png"

    if run_dir != Path("."):
        meta_data = {
            "num": getattr(args, "num", None),
            "hosts": args.hosts,
            "switches": args.switches,
            "seed": args.seed,
            "k": args.k,
            "down_interval": args.down_interval,
            "down_duration": args.down_duration,
            "down_count": args.down_count,
            "down_stagger": args.down_stagger,
            "down_exclude": args.down_exclude,
            "cache_count": args.cache_count,
            "get_interval": args.get_interval,
        }
        meta_path = run_dir / "meta.json"
        meta_path.write_text(json.dumps(meta_data, indent=2), encoding="utf-8")

    log_fp = None
    original_stdout = None
    original_stderr = None
    log_context = None
    if not args.no_script_log:
        log_name = args.script_log if args.script_log else "script.log"
        log_path = run_dir / log_name
        log_fp = open(log_path, "w")
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        tee_stdout = Tee(original_stdout, log_fp)
        tee_stderr = Tee(original_stderr, log_fp)
        sys.stdout = tee_stdout
        sys.stderr = tee_stderr
        log_context = {
            "original_stdout": original_stdout,
            "original_stderr": original_stderr,
            "tee_stdout": tee_stdout,
            "tee_stderr": tee_stderr,
        }

    debug_config = build_debug_config(args, config_data.get("debug"))

    try:
        setLogLevel("info")
        run_disaster_scenario(args, run_dir, log_context=log_context, debug_config=debug_config)
    finally:
        if log_fp:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            log_fp.close()


def main():
    """Main CLI entry point with subcommands."""
    parser = argparse.ArgumentParser(
        prog="ceforeemu",
        description="CeforeEmu - Network emulator for Cefore deployments",
    )
    subparsers = parser.add_subparsers(dest="command", help="topology type")

    # linear subcommand
    linear_parser = subparsers.add_parser(
        "linear", help="linear topology (h0-s0-h1-s1-...-sN-hN)"
    )
    linear_parser.add_argument("--hosts", type=int, default=5, help="number of hosts")
    linear_parser.add_argument(
        "--num", type=int, default=None,
        help="experiment number (enables log directory output)",
    )
    linear_parser.add_argument(
        "--output-dir", type=str, default="logs",
        help="base output directory (default: logs)",
    )
    linear_parser.add_argument(
        "--timestamp", action="store_true",
        help="add timestamp to output directory name",
    )
    add_debug_args(linear_parser)
    linear_parser.set_defaults(func=cmd_linear)

    # mesh subcommand
    mesh_parser = subparsers.add_parser(
        "mesh", help="random mesh topology"
    )
    add_common_args(mesh_parser)
    add_mesh_args(mesh_parser)
    add_debug_args(mesh_parser)
    mesh_parser.set_defaults(func=cmd_mesh)

    # disaster subcommand
    disaster_parser = subparsers.add_parser(
        "disaster", help="mesh topology with periodic host failures"
    )
    add_common_args(disaster_parser)
    add_mesh_args(disaster_parser)
    add_disaster_args(disaster_parser)
    add_debug_args(disaster_parser)
    disaster_parser.set_defaults(func=cmd_disaster)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
