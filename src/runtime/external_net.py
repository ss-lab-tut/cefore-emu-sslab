"""External network connection scenario with mesh topology.

Provides run_connect() for mesh topology with external bridge support.
"""

import argparse
import json
import sys
from pathlib import Path

from mininet.log import setLogLevel

from ..core.tee import Tee  # noqa: F401 (re-export for backward compat)
from ..core.config.loader import (
    load_config,
    merge_cli_and_config,
    validate_config,
    warn_ignored_legacy_content_keys,
)
from ..core.events import extract_publications  # noqa: F401 (re-export)
from ..core.paths import resolve_run_dir, resolve_run_path
from ..scenarios.connect import ConnectScenario


def run_connect(args, run_dir: Path = None, log_context=None):
    """Run mesh topology with external bridge support.

    Thin wrapper over ConnectScenario; the lifecycle (build/configure/run/CLI/
    staged teardown) lives in src/scenarios/connect.py.

    Args:
        args: Parsed command-line arguments.
        run_dir: Output directory for logs and artifacts.
        log_context: Dict with original_stdout/stderr and tee_stdout/stderr for CLI.
    """
    ConnectScenario(args, run_dir=run_dir, log_context=log_context).execute()


def main():
    """CLI entry point for external network connection topology."""
    parser = argparse.ArgumentParser(
        description="Cefore mesh topology with external bridge"
    )
    parser.add_argument("--hosts", type=int, default=5)
    parser.add_argument("--switches", type=int, default=10)
    parser.add_argument("--node-per-switch", type=int, default=2)
    parser.add_argument("--host-degree-min", type=int, default=1)
    parser.add_argument("--host-degree-max", type=int, default=2)
    parser.add_argument("--switch-use-all", action="store_true")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--k", type=int, default=2)
    parser.add_argument("--down-interval", type=int, default=30)
    parser.add_argument("--down-duration", type=int, default=10)
    parser.add_argument("--down-exclude", type=str, default="")
    parser.add_argument("--down-count", type=int, default=5)
    parser.add_argument("--down-stagger", type=int, default=2)
    parser.add_argument("--cache-count", type=int, default=0)
    parser.add_argument("--bw", action="append", default=[])
    parser.add_argument("--ext", action="append", default=[])
    parser.add_argument("--bridge", action="append", default=[])
    parser.add_argument("--config", type=str, default="")
    parser.add_argument("--topo-png", type=str, default=None)
    parser.add_argument("--script-log", type=str, default=None)
    parser.add_argument("--no-script-log", action="store_true")
    parser.add_argument("--topo-layout", type=str, default="spring")
    parser.add_argument("--num", type=int, default=None)
    parser.add_argument("--output-dir", type=str, default="logs")
    parser.add_argument("--timestamp", action="store_true")
    parser.add_argument("--no-cli", action="store_true")
    args = parser.parse_args()

    config_data = load_config(args.config)
    warn_ignored_legacy_content_keys(config_data)
    errors = validate_config(config_data)
    if errors:
        for error in errors:
            print(f"config error: {error}", file=sys.stderr)
        sys.exit(1)
    merge_cli_and_config(args, config_data)

    run_dir = resolve_run_dir(args)
    run_dir = run_dir.resolve()

    seed_label = "none" if args.seed is None else str(args.seed)
    if args.topo_png is None:
        args.topo_png = f"ex{args.hosts}_seed{seed_label}.png"

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
        "output_dir": str(run_dir),
    }
    meta_path = resolve_run_path(run_dir, "meta.json", "meta.json")
    meta_path.write_text(json.dumps(meta_data, indent=2), encoding="utf-8")

    log_fp = None
    original_stdout = None
    original_stderr = None
    if not args.no_script_log:
        log_name = args.script_log if args.script_log else "script.log"
        log_path = resolve_run_path(run_dir, log_name, "script.log")
        log_fp = open(log_path, "w")
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        sys.stdout = Tee(original_stdout, log_fp)
        sys.stderr = Tee(original_stderr, log_fp)

    log_context = None
    if log_fp:
        log_context = {
            "original_stdout": original_stdout,
            "original_stderr": original_stderr,
            "tee_stdout": sys.stdout,
            "tee_stderr": sys.stderr,
        }

    try:
        setLogLevel("info")
        run_connect(args, run_dir, log_context=log_context)
    finally:
        if log_fp:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            log_fp.close()


if __name__ == "__main__":
    main()
