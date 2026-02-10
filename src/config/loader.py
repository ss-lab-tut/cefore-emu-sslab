"""JSON/YAML configuration loader for cefore-emu."""

import json
import sys
from pathlib import Path
from typing import Any

HAVE_YAML = True
try:
    import yaml
except ImportError:
    HAVE_YAML = False


def load_config(path: str | Path | None) -> dict[str, Any]:
    """Load configuration from a JSON or YAML file.

    Args:
        path: Path to the configuration file. If None or empty, returns {}.

    Returns:
        Configuration dictionary.

    Raises:
        SystemExit: If file not found or parse error.
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


def validate_config(config: dict[str, Any]) -> list[str]:
    """Validate configuration and return list of errors.

    Args:
        config: Configuration dictionary to validate.

    Returns:
        List of error messages. Empty if valid.
    """
    errors = []

    if "hosts" in config:
        if not isinstance(config["hosts"], int) or config["hosts"] < 3:
            errors.append("hosts must be an integer >= 3")

    if "switches" in config:
        if not isinstance(config["switches"], int) or config["switches"] < 2:
            errors.append("switches must be an integer >= 2")

    if "seed" in config:
        if config["seed"] is not None and not isinstance(config["seed"], int):
            errors.append("seed must be an integer or null")

    if "k" in config:
        if not isinstance(config["k"], int) or config["k"] < 1:
            errors.append("k must be an integer >= 1")

    if "host_degree_min" in config:
        if not isinstance(config["host_degree_min"], int) or config["host_degree_min"] < 1:
            errors.append("host_degree_min must be an integer >= 1")

    if "host_degree_max" in config:
        if not isinstance(config["host_degree_max"], int):
            errors.append("host_degree_max must be an integer")
        else:
            min_val = config.get("host_degree_min", 1)
            if not isinstance(min_val, int):
                min_val = 1
            if config["host_degree_max"] < min_val:
                errors.append("host_degree_max must be >= host_degree_min")

    if "switch_use_all" in config:
        if not isinstance(config["switch_use_all"], bool):
            errors.append("switch_use_all must be a boolean")

    if "num" in config:
        if not isinstance(config["num"], int) or config["num"] < 1:
            errors.append("num must be an integer >= 1")

    if "output_dir" in config:
        if not isinstance(config["output_dir"], str):
            errors.append("output_dir must be a string")

    if "results_json" in config:
        if config["results_json"] is not None and not isinstance(
            config["results_json"], str
        ):
            errors.append("results_json must be a string or null")

    if "timestamp" in config:
        if not isinstance(config["timestamp"], bool):
            errors.append("timestamp must be a boolean")

    if "legacy_layout" in config:
        if not isinstance(config["legacy_layout"], bool):
            errors.append("legacy_layout must be a boolean")

    if "no_cli" in config:
        if not isinstance(config["no_cli"], bool):
            errors.append("no_cli must be a boolean")

    if "duration" in config:
        if not isinstance(config["duration"], int) or config["duration"] < 0:
            errors.append("duration must be an integer >= 0")

    if "warmup_get_interval" in config:
        if (
            not isinstance(config["warmup_get_interval"], int)
            or config["warmup_get_interval"] < 0
        ):
            errors.append("warmup_get_interval must be an integer >= 0")

    if "warmup_only_cache_nodes" in config:
        if not isinstance(config["warmup_only_cache_nodes"], bool):
            errors.append("warmup_only_cache_nodes must be a boolean")

    if "cache_default_rct_ms" in config:
        if (
            not isinstance(config["cache_default_rct_ms"], int)
            or config["cache_default_rct_ms"] < 1000
        ):
            errors.append("cache_default_rct_ms must be an integer >= 1000")

    if "publisher_host" in config:
        if config["publisher_host"] is not None and not isinstance(
            config["publisher_host"], int
        ):
            errors.append("publisher_host must be an integer or null")

    if "hot_uris" in config:
        if not isinstance(config["hot_uris"], list) or not all(
            isinstance(uri, str) for uri in config["hot_uris"]
        ):
            errors.append("hot_uris must be a list of strings")

    if "warmup_gets" in config:
        if not isinstance(config["warmup_gets"], list):
            errors.append("warmup_gets must be a list")
        else:
            for idx, op in enumerate(config["warmup_gets"]):
                if not isinstance(op, dict):
                    errors.append(f"warmup_gets[{idx}] must be a dict")
                    continue
                if "host" not in op:
                    errors.append(f"warmup_gets[{idx}] missing required field 'host'")
                if "uri" not in op:
                    errors.append(f"warmup_gets[{idx}] missing required field 'uri'")

    if "puts" in config:
        if not isinstance(config["puts"], list):
            errors.append("puts must be a list")
        else:
            for idx, op in enumerate(config["puts"]):
                if not isinstance(op, dict):
                    errors.append(f"puts[{idx}] must be a dict")
                    continue
                if "host" not in op:
                    errors.append(f"puts[{idx}] missing required field 'host'")
                if "uri" not in op:
                    errors.append(f"puts[{idx}] missing required field 'uri'")
                for field in ("rate", "block_size", "expiry", "cache_time"):
                    if field in op and not isinstance(op[field], (int, float)):
                        errors.append(f"puts[{idx}].{field} must be a number")
                if "valid_algo" in op and not isinstance(op["valid_algo"], str):
                    errors.append(f"puts[{idx}].valid_algo must be a string")
                if "port_num" in op and not isinstance(op["port_num"], int):
                    errors.append(f"puts[{idx}].port_num must be an integer")

    if "gets" in config:
        if not isinstance(config["gets"], list):
            errors.append("gets must be a list")
        else:
            for idx, op in enumerate(config["gets"]):
                if not isinstance(op, dict):
                    errors.append(f"gets[{idx}] must be a dict")
                    continue
                if "host" not in op:
                    errors.append(f"gets[{idx}] missing required field 'host'")
                if "uri" not in op:
                    errors.append(f"gets[{idx}] missing required field 'uri'")
                if "owner_only" in op and not isinstance(op["owner_only"], bool):
                    errors.append(f"gets[{idx}].owner_only must be a boolean")
                for field in ("chunk", "pipeline", "sg"):
                    if field in op and not isinstance(op[field], int):
                        errors.append(f"gets[{idx}].{field} must be an integer")
                if "valid_algo" in op and not isinstance(op["valid_algo"], str):
                    errors.append(f"gets[{idx}].valid_algo must be a string")
                if "port_num" in op and not isinstance(op["port_num"], int):
                    errors.append(f"gets[{idx}].port_num must be an integer")

    if "auto" in config:
        auto = config["auto"]
        auto_entries: list[tuple[str, Any]] = []
        if isinstance(auto, dict):
            auto_entries.append(("auto", auto))
        elif isinstance(auto, list):
            for idx, auto_entry in enumerate(auto):
                if not isinstance(auto_entry, dict):
                    errors.append(f"auto[{idx}] must be a dict")
                    continue
                auto_entries.append((f"auto[{idx}]", auto_entry))
        else:
            errors.append("auto must be a dict or list of dicts")

        for entry_name, auto_entry in auto_entries:
            if "publishers" in auto_entry:
                val = auto_entry["publishers"]
                if not (
                    isinstance(val, list)
                    or (isinstance(val, str) and val.startswith("random"))
                ):
                    errors.append(
                        f"{entry_name}.publishers must be 'random:N' string or list of host IDs"
                    )
            if "consumers" in auto_entry:
                val = auto_entry["consumers"]
                if not isinstance(val, (str, list)):
                    errors.append(
                        f"{entry_name}.consumers must be 'random:N' string or list of host IDs"
                    )

    if "bridges" in config:
        if not isinstance(config["bridges"], list):
            errors.append("bridges must be a list")
        else:
            for idx, bridge in enumerate(config["bridges"]):
                if not isinstance(bridge, dict):
                    errors.append(f"bridges[{idx}] must be a dict")
                    continue
                if "switch" not in bridge:
                    errors.append(f"bridges[{idx}] missing required field 'switch'")
                if "root_ip" not in bridge:
                    errors.append(f"bridges[{idx}] missing required field 'root_ip'")
                if "local_routes" not in bridge:
                    errors.append(f"bridges[{idx}] missing required field 'local_routes'")
                if "nat" in bridge and not isinstance(bridge["nat"], bool):
                    errors.append(f"bridges[{idx}].nat must be a boolean")
                if "nat_out" in bridge and not isinstance(bridge["nat_out"], str):
                    errors.append(f"bridges[{idx}].nat_out must be a string")

    if "failure_scenarios" in config:
        fs = config["failure_scenarios"]
        if not isinstance(fs, dict):
            errors.append("failure_scenarios must be a dict")
        else:
            strategy = fs.get("strategy", "simple")
            if strategy not in ("simple", "cyclic", "random", "manual"):
                errors.append(
                    f"failure_scenarios.strategy must be one of: simple, cyclic, random, manual"
                )

            if strategy == "simple":
                if "simple" not in fs:
                    errors.append(
                        "failure_scenarios with strategy 'simple' requires 'simple' block"
                    )
                else:
                    simple = fs["simple"]
                    if not isinstance(simple, dict):
                        errors.append("failure_scenarios.simple must be a dict")
                    else:
                        for field in ("interval", "duration", "count", "stagger"):
                            if field in simple and not isinstance(simple[field], int):
                                errors.append(
                                    f"failure_scenarios.simple.{field} must be an integer"
                                )
                        if (
                            "count" in simple
                            and isinstance(simple["count"], int)
                            and simple["count"] < 0
                        ):
                            errors.append(
                                "failure_scenarios.simple.count must be an integer >= 0"
                            )
                        if (
                            "stagger" in simple
                            and isinstance(simple["stagger"], int)
                            and simple["stagger"] < 0
                        ):
                            errors.append(
                                "failure_scenarios.simple.stagger must be an integer >= 0"
                            )
                        if "exclude" in simple:
                            if not isinstance(simple["exclude"], list) or not all(
                                isinstance(x, int) for x in simple["exclude"]
                            ):
                                errors.append(
                                    "failure_scenarios.simple.exclude must be a list of integers"
                                )
            else:
                if "cycles" not in fs:
                    errors.append(
                        f"failure_scenarios with strategy '{strategy}' requires 'cycles' list"
                    )
                elif not isinstance(fs["cycles"], list):
                    errors.append("failure_scenarios.cycles must be a list")
                else:
                    if len(fs["cycles"]) == 0:
                        errors.append(
                            f"failure_scenarios with strategy '{strategy}' requires at least one cycle"
                        )
                    for idx, cycle in enumerate(fs["cycles"]):
                        if not isinstance(cycle, dict):
                            errors.append(f"failure_scenarios.cycles[{idx}] must be a dict")
                            continue
                        for field in ("interval", "duration", "count", "stagger"):
                            if field in cycle and not isinstance(cycle[field], int):
                                errors.append(
                                    f"failure_scenarios.cycles[{idx}].{field} must be an integer"
                                )
                        if (
                            "count" in cycle
                            and isinstance(cycle["count"], int)
                            and cycle["count"] < 0
                        ):
                            errors.append(
                                f"failure_scenarios.cycles[{idx}].count must be an integer >= 0"
                            )
                        if (
                            "stagger" in cycle
                            and isinstance(cycle["stagger"], int)
                            and cycle["stagger"] < 0
                        ):
                            errors.append(
                                f"failure_scenarios.cycles[{idx}].stagger must be an integer >= 0"
                            )
                        if "exclude" in cycle:
                            if not isinstance(cycle["exclude"], list) or not all(
                                isinstance(x, int) for x in cycle["exclude"]
                            ):
                                errors.append(
                                    f"failure_scenarios.cycles[{idx}].exclude must be a list of integers"
                                )
                        if "target" in cycle:
                            if not isinstance(cycle["target"], list) or not all(
                                isinstance(x, int) for x in cycle["target"]
                            ):
                                errors.append(
                                    f"failure_scenarios.cycles[{idx}].target must be a list of integers"
                                )
                        if "allow_publishers" in cycle:
                            if not isinstance(cycle["allow_publishers"], bool):
                                errors.append(
                                    f"failure_scenarios.cycles[{idx}].allow_publishers must be a boolean"
                                )

    if "priority_uris" in config:
        priority_uris = config["priority_uris"]
        if not isinstance(priority_uris, dict):
            errors.append("priority_uris must be a dict")
        else:
            mode_values = ("putget", "pubsub")
            string_fields = (
                "valid_algo",
                "target",
                "ti_valid_algo",
                "rd_valid_algo",
                "ri_valid_algo",
                "td_valid_algo",
            )
            number_fields = ("expiry", "cache_time", "rate", "lifetime")
            integer_fields = ("block_size", "port_num", "retry_limit", "pipeline")

            for level_name, level_cfg in priority_uris.items():
                if not isinstance(level_cfg, dict):
                    errors.append(f"priority_uris.{level_name} must be a dict")
                    continue

                patterns = level_cfg.get("patterns")
                if isinstance(patterns, str):
                    if not patterns.strip():
                        errors.append(
                            f"priority_uris.{level_name}.patterns must not be empty"
                        )
                elif isinstance(patterns, list):
                    if not patterns:
                        errors.append(
                            f"priority_uris.{level_name}.patterns must not be empty"
                        )
                    elif not all(isinstance(pat, str) for pat in patterns):
                        errors.append(
                            f"priority_uris.{level_name}.patterns must be a list of strings or a string"
                        )
                    elif any(not pat.strip() for pat in patterns):
                        errors.append(
                            f"priority_uris.{level_name}.patterns must not contain empty strings"
                        )
                else:
                    errors.append(
                        f"priority_uris.{level_name}.patterns must be a list of strings or a string"
                    )

                if "mode" in level_cfg and level_cfg["mode"] not in mode_values:
                    errors.append(
                        f"priority_uris.{level_name}.mode must be 'putget' or 'pubsub'"
                    )

                if (
                    "prefetch_to_cache" in level_cfg
                    and not isinstance(level_cfg["prefetch_to_cache"], bool)
                ):
                    errors.append(
                        f"priority_uris.{level_name}.prefetch_to_cache must be a boolean"
                    )

                for field in number_fields:
                    if field in level_cfg and (
                        not isinstance(level_cfg[field], (int, float))
                        or isinstance(level_cfg[field], bool)
                    ):
                        errors.append(
                            f"priority_uris.{level_name}.{field} must be a number"
                        )

                for field in integer_fields:
                    if field in level_cfg and (
                        not isinstance(level_cfg[field], int)
                        or isinstance(level_cfg[field], bool)
                    ):
                        errors.append(
                            f"priority_uris.{level_name}.{field} must be an integer"
                        )

                for field in string_fields:
                    if field in level_cfg and not isinstance(level_cfg[field], str):
                        errors.append(
                            f"priority_uris.{level_name}.{field} must be a string"
                        )

    return errors


def merge_cli_and_config(args: Any, config: dict[str, Any]) -> None:
    """Merge config file values into argparse args.

    The args object is modified in place.

    Args:
        args: argparse.Namespace with CLI arguments.
        config: Configuration dictionary from load_config().
    """
    # NOTE:
    # argparse.Namespace does not tell us whether a value came from an explicit CLI
    # flag or from the parser default, so we cannot reliably enforce "CLI always wins"
    # in this shared helper. For backward compatibility with disaster.py and related
    # scripts, legacy fields below keep the historical behavior: config overwrites args.
    # flexible_disaster.py uses failure_scenarios for failure control, so that field is
    # merged separately only when it exists in the config.
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
        "get_interval",
        "topo_png",
        "topo_layout",
        "node_per_switch",
        "host_degree_min",
        "host_degree_max",
        "switch_use_all",
        "puts",
        "gets",
        "auto",
        "no_cli",
        "duration",
        "results_json",
        "warmup_get_interval",
        "warmup_only_cache_nodes",
        "warmup_gets",
        "cache_default_rct_ms",
        "publisher_host",
        "hot_uris",
        "priority_uris",
        "num",
        "output_dir",
        "timestamp",
        "legacy_layout",
    )

    for key in config_keys:
        if key in config:
            setattr(args, key, config[key])

    if "failure_scenarios" in config:
        setattr(args, "failure_scenarios", config["failure_scenarios"])

    # Parse puts/gets if passed as JSON strings
    if isinstance(args.puts, str) and args.puts:
        args.puts = json.loads(args.puts)
    if isinstance(args.gets, str) and args.gets:
        args.gets = json.loads(args.gets)
    if isinstance(args.bw, str) and args.bw:
        args.bw = [args.bw]
    if isinstance(args.ext, str) and args.ext:
        args.ext = [args.ext]

    # Ensure puts/gets are lists
    if not hasattr(args, "puts") or args.puts is None or args.puts == "":
        args.puts = []
    if not hasattr(args, "gets") or args.gets is None or args.gets == "":
        args.gets = []
