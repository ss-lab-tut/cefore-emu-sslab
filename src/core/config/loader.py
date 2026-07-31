"""JSON/YAML configuration loader for cefore-emu."""

import json
import sys
from pathlib import Path
from typing import Any

from .validator import (
    _FLAT_SPECS as _FLAT_SPECS,
    OPTION_SPECS as OPTION_SPECS,
    config_option_keys,
    nullable_option_keys,
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
        f"[warning] config keys ignored: {keys}. Use events for content operations.",
        file=stream,
    )
    return True


# Runtime default applied by Monitor callers (e.g. DisasterScenario) when
# monitoring.interval is absent from config -- see
# src/scenarios/disaster.py `monitoring_config.get("interval", 5)`. Kept
# here as the fallback this warning compares against so the two defaults
# cannot silently drift apart.
_MONITOR_INTERVAL_RUNTIME_DEFAULT = 5


def warn_ccninfo_monitor_interval(config: dict[str, Any], stream=None) -> bool:
    """Warn once when monitoring.interval is too low for a ccninfo target.

    A ccninfo probe self-terminates on reply or on CCNINFO_REPLY_TIMEOUT+1
    (cefnetd.conf default 4s + 1s grace = ~5s, see
    src/runtime/cefore.py CCNINFO_GUARD_TIMEOUT comment) -- so it costs ~5s
    per call *even on success*. Monitor._run sleeps `interval` seconds after
    each full collection pass (a fixed post-cycle delay, not a minimum
    spacing enforced between probes), so an interval shorter than that
    per-probe cost means collection immediately falls behind schedule for
    every ccninfo target.

    This runs over the RAW config, before validate_config, so it must never
    raise regardless of what shape the YAML/JSON handed it -- every branch
    below degrades to "no warning" rather than crashing on a malformed
    monitoring/targets/interval value.

    Returns:
        True iff the warning was printed.
    """
    monitoring = config.get("monitoring")
    if not isinstance(monitoring, dict):
        return False
    targets = monitoring.get("targets")
    if not isinstance(targets, list):
        return False
    has_ccninfo = any(
        isinstance(t, dict) and t.get("type") == "ccninfo" for t in targets
    )
    if not has_ccninfo:
        return False

    interval = monitoring.get("interval")
    # bool is an int subclass -- check it FIRST so a stray `interval: true`
    # isn't silently treated as interval=1. Any other non-numeric shape
    # (missing key, string, None, ...) also falls back to the runtime
    # default rather than being treated as an (incorrectly) low interval.
    if isinstance(interval, bool) or not isinstance(interval, (int, float)):
        interval = _MONITOR_INTERVAL_RUNTIME_DEFAULT

    if interval >= _MONITOR_INTERVAL_RUNTIME_DEFAULT:
        return False

    if stream is None:
        stream = sys.stderr
    print(
        f"[warning] monitoring.interval ({interval}) is below "
        f"~{_MONITOR_INTERVAL_RUNTIME_DEFAULT}s but a ccninfo target takes "
        "~5s per probe (REPLY_TIMEOUT+1) even on success, and "
        "monitoring.interval is a fixed post-cycle delay, not a minimum "
        "spacing between probes -- expect ccninfo collection to fall "
        "behind schedule.",
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


def merge_cli_and_config(args: Any, config: dict[str, Any], parser) -> None:
    """Merge config file values into argparse args, respecting CLI precedence.

    parser is mandatory because config values must never override explicit CLI
    flags. 2026-07-03 precedence bug fix: the old parser-less merge mode caused
    ceforeemu-connect config values to overwrite user-provided CLI flags.
    The args object is modified in place.
    """
    config_keys = config_option_keys()
    _NULL_MEANS_DEFAULT = nullable_option_keys()

    defaults = vars(parser.parse_args([]))

    for key in config_keys:
        if key not in config:
            continue
        cli_val = getattr(args, key, None)
        default_val = defaults.get(key)
        if cli_val != default_val:
            continue
        if config[key] is None and key in _NULL_MEANS_DEFAULT:
            continue
        setattr(args, key, config[key])

    for key, spec in OPTION_SPECS.items():
        if not spec.special_config_merge or key == "debug":
            continue
        if key in config:
            setattr(args, key, config[key])
        elif spec.default is not None:
            setattr(args, key, spec.default)

    if isinstance(args.bw, str) and args.bw:
        args.bw = [args.bw]
    if isinstance(args.ext, str) and args.ext:
        args.ext = [args.ext]
