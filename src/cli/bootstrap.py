"""Scenario bootstrap shared by CLI entry points."""

import argparse
import json
import sys
from pathlib import Path
from typing import Callable

from mininet.log import setLogLevel

from ..core.config.loader import (
    load_config,
    merge_cli_and_config,
    validate_merged_args,
    warn_ignored_legacy_content_keys,
)
from ..core.debug import build_debug_config
from ..core.paths import resolve_run_dir, resolve_run_path
from ..core.tee import Tee
from .args import (
    add_common_args,
    add_connect_args,
    add_debug_args,
    add_disaster_args,
    add_linear_args,
    add_mesh_args,
)

_ARG_BUILDERS = {
    "common": add_common_args,
    "mesh": add_mesh_args,
    "disaster": add_disaster_args,
    "connect": add_connect_args,
    "linear": add_linear_args,
    "debug": add_debug_args,
}


def _build_cli_precedence_parser(blocks: tuple[str, ...]) -> argparse.ArgumentParser:
    """Build the parser used only to identify explicit CLI values."""
    parser = argparse.ArgumentParser()
    for block in blocks:
        _ARG_BUILDERS[block](parser)
    return parser


def bootstrap_scenario(
    args,
    *,
    blocks: tuple[str, ...],
    run_fn: Callable,
) -> None:
    """Load config, merge CLI precedence, prepare run files, then execute.

    The disaster and connect entry points historically duplicated this
    sequence. Keeping the bootstrap in one place lets each caller choose its
    argument blocks and scenario runner without reimplementing precedence,
    metadata, tee logging, and debug-config handling.
    """
    config_data = load_config(args.config)
    warn_ignored_legacy_content_keys(config_data)

    # This parser is not used to parse argv; it tells the config merger which
    # values were argparse defaults so config may fill them without overriding
    # explicit user flags.
    cli_parser = _build_cli_precedence_parser(blocks)
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
        }
        meta_path = run_dir / "meta.json"
        meta_path.write_text(json.dumps(meta_data, indent=2), encoding="utf-8")

    log_fp = None
    original_stdout = None
    original_stderr = None
    log_context = None
    if not args.no_script_log:
        log_name = args.script_log if args.script_log else "script.log"
        log_path = resolve_run_path(run_dir, log_name, "script.log")
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
        run_fn(args, run_dir, log_context=log_context, debug_config=debug_config)
    finally:
        if log_fp:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            log_fp.close()
