"""External network connection scenario with mesh topology.

Provides run_connect() for mesh topology with external bridge support and
delegates CLI bootstrapping to src.cli.bootstrap.bootstrap_scenario.
"""

import argparse
from pathlib import Path

from ..cli.args import add_connect_args
from ..cli.bootstrap import bootstrap_scenario
from ..core.tee import Tee  # noqa: F401 (re-export for backward compat)
from ..core.events import extract_publications  # noqa: F401 (re-export)
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


def _run_connect_adapter(args, run_dir, *, log_context=None, debug_config=None):
    """Adapt bootstrap_scenario's runner contract to run_connect().

    Connect does not consume DebugConfig yet. The parameter remains accepted so
    connect can share the bootstrap contract without changing ConnectScenario in
    this slice.
    """
    run_connect(args, run_dir, log_context=log_context)


def main():
    """CLI entry point for external network connection topology."""
    parser = argparse.ArgumentParser(
        description="Cefore mesh topology with external bridge"
    )
    add_connect_args(parser)
    args = parser.parse_args()

    bootstrap_scenario(args, blocks=("connect",), run_fn=_run_connect_adapter)


if __name__ == "__main__":
    main()
