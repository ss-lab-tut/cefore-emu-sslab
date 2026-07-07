#!/usr/bin/env python
"""Unified CLI entry point for cefore-emu.

Usage:
    sudo python3 -m cli.main linear --hosts 5
    sudo python3 -m cli.main mesh --hosts 8 --switches 12
    sudo python3 -m cli.main disaster --config experiment.yaml
"""

import argparse
import sys

from mininet.log import setLogLevel

from ..core.debug import build_debug_config
from ..core.paths import resolve_run_dir
from .args import (
    add_common_args,
    add_debug_args,
    add_disaster_args,
    add_linear_args,
    add_mesh_args,
)


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
    from ..cli.bootstrap import bootstrap_scenario
    from ..scenarios.disaster import run_disaster_scenario

    bootstrap_scenario(
        args,
        blocks=("common", "mesh", "disaster"),
        run_fn=run_disaster_scenario,
    )


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
    add_linear_args(linear_parser)
    add_debug_args(linear_parser)
    linear_parser.set_defaults(func=cmd_linear)

    # mesh subcommand
    mesh_parser = subparsers.add_parser("mesh", help="random mesh topology")
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
