"""JSON/YAML configuration loader for cefore-emu."""

import json
import sys
from pathlib import Path
from typing import Any

from .validator import (
    _FLAT_SPECS as _FLAT_SPECS,
    validate_config as validate_config,
    validate_merged_args as validate_merged_args,
)

HAVE_YAML = True
try:
    import yaml
except ImportError:
    HAVE_YAML = False

LEGACY_CONTENT_KEYS = {"puts", "gets", "auto"}


def warn_ignored_legacy_content_keys(config: dict[str, Any], stream=None) -> bool:
    """Warn once when ignored legacy content-operation keys are present."""
    present = sorted(LEGACY_CONTENT_KEYS & set(config))
    if not present:
        return False
    if stream is None:
        stream = sys.stderr
    keys = ", ".join(present)
    print(
        "[warning] config keys ignored: "
        f"{keys}. Use events for content operations.",
        file=stream,
    )
    return True


def load_config(path: str | Path | None) -> dict[str, Any]:
    """Load configuration from a JSON or YAML file.

    Args:
        path: Path to the configuration file. If None or empty, returns {}.

    Returns:
        Configuration dictionary.
    """
    if not path:
        return {}

    config_path = Path(path)
    if not config_path.exists():
        sys.exit(f"config file not found: {config_path}")

    suffix = config_path.suffix.lower()
    content = config_path.read_text(encoding="utf-8")

    if suffix in (".yaml", ".yml"):
        if not HAVE_YAML:
            sys.exit("YAML config requires pyyaml: pip install pyyaml")
        try:
            return yaml.safe_load(content) or {}
        except yaml.YAMLError as exc:
            sys.exit(f"failed to parse YAML config: {exc}")
    else:
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            sys.exit(f"failed to parse JSON config: {exc}")


def merge_cli_and_config(args: Any, config: dict[str, Any], parser=None) -> None:
    """Merge config file values into argparse args, respecting CLI precedence.

    When parser is provided, config values are applied only if the
    corresponding CLI arg still holds its default value (i.e., the user
    did not explicitly set it on the command line).
    The args object is modified in place.
    """
    config_keys = (
        "hosts",
        "switches",
        "seed",
        "k",
        "down_interval",
        "down_duration",
        "down_exclude",
        "down_count",
        "down_stagger",
        "cache_count",
        "bw",
        "ext",
        "bridges",
        "topo_png",
        "topo_layout",
        "node_per_switch",
        "host_degree_min",
        "host_degree_max",
        "switch_use_all",
        "no_cli",
        "duration",
        "results_json",
        "cache_default_rct_ms",
        "publisher_host",
        "num",
        "output_dir",
        "timestamp",
        "no_cli",
        "duration",
        "results_json",
        "script_log",
        "no_script_log",
        "cache_default_rct_ms",
        "publisher_host",
        "failure_scenarios",
        "events",
        "monitoring",
        "routing",
        "cefnetd_timeout",
        "addressing",
        "pubsub_sub_startup_grace",
        "warmup_get_interval",
        "warmup_only_cache_nodes",
        "warmup_gets",
        "webui_port",
    )

    _NULL_MEANS_DEFAULT = {
        "seed",
        "results_json",
        "script_log",
        "cache_default_rct_ms",
        "publisher_host",
        "topo_png",
    }

    # Compute defaults for CLI-precedence check
    defaults = {}
    if parser is not None:
        defaults = vars(parser.parse_args([]))

    for key in config_keys:
        if key not in config:
            continue
        # If parser provided, only apply config when CLI value equals default
        if parser is not None:
            cli_val = getattr(args, key, None)
            default_val = defaults.get(key)
            if cli_val != default_val:
                continue
            if config[key] is None and key in _NULL_MEANS_DEFAULT:
                continue
        setattr(args, key, config[key])

    if "cache_config" in config:
        setattr(args, "cache_config", config["cache_config"])

    if isinstance(args.bw, str) and args.bw:
        args.bw = [args.bw]
    if isinstance(args.ext, str) and args.ext:
        args.ext = [args.ext]
