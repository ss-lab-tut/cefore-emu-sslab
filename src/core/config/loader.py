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
        if not isinstance(auto, dict):
            errors.append("auto must be a dict")
        else:
            if "publishers" in auto:
                if not isinstance(auto["publishers"], list):
                    errors.append("auto.publishers must be a list of host IDs")
            if "consumers" in auto:
                val = auto["consumers"]
                if not isinstance(val, (str, list)):
                    errors.append(
                        "auto.consumers must be 'random:N' string or list of host IDs"
                    )

    if "cache_config" in config:
        cc = config["cache_config"]
        if not isinstance(cc, dict):
            errors.append("cache_config must be a dict")
        else:
            valid_strategies = ("k_centers", "manual", "degree_based")
            strategy = cc.get("strategy", "k_centers")
            if strategy not in valid_strategies:
                errors.append(
                    f"cache_config.strategy must be one of: {', '.join(valid_strategies)}"
                )

            default = cc.get("default", {})
            if not isinstance(default, dict):
                errors.append("cache_config.default must be a dict")
            else:
                if "count" in default:
                    if not isinstance(default["count"], int) or default["count"] < 0:
                        errors.append("cache_config.default.count must be an integer >= 0")
                if "capacity" in default:
                    if not isinstance(default["capacity"], int) or default["capacity"] < 0:
                        errors.append("cache_config.default.capacity must be an integer >= 0")
                if "default_rct_ms" in default:
                    if (
                        not isinstance(default["default_rct_ms"], int)
                        or default["default_rct_ms"] < 1000
                    ):
                        errors.append(
                            "cache_config.default.default_rct_ms must be an integer >= 1000"
                        )
                if "algorithm" in default:
                    valid_algos = ("LRU", "LFU", "FIFO", "None")
                    if default["algorithm"] not in valid_algos:
                        errors.append(
                            f"cache_config.default.algorithm must be one of: {', '.join(valid_algos)}"
                        )
                if "type" in default:
                    valid_types = ("memory", "filesystem")
                    if default["type"] not in valid_types:
                        errors.append(
                            f"cache_config.default.type must be one of: {', '.join(valid_types)}"
                        )

            nodes = cc.get("nodes", [])
            if not isinstance(nodes, list):
                errors.append("cache_config.nodes must be a list")
            else:
                for node_idx, node_entry in enumerate(nodes):
                    if not isinstance(node_entry, dict):
                        errors.append(f"cache_config.nodes[{node_idx}] must be a dict")
                        continue
                    ids = node_entry.get("id", [])
                    if isinstance(ids, int):
                        ids = [ids]
                    if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
                        errors.append(
                            f"cache_config.nodes[{node_idx}].id must be an integer or list of integers"
                        )
                    if "capacity" in node_entry:
                        if (
                            not isinstance(node_entry["capacity"], int)
                            or node_entry["capacity"] < 0
                        ):
                            errors.append(
                                f"cache_config.nodes[{node_idx}].capacity must be an integer >= 0"
                            )
                    if "default_rct_ms" in node_entry:
                        if (
                            not isinstance(node_entry["default_rct_ms"], int)
                            or node_entry["default_rct_ms"] < 1000
                        ):
                            errors.append(
                                f"cache_config.nodes[{node_idx}].default_rct_ms must be an integer >= 1000"
                            )
                    if "algorithm" in node_entry:
                        valid_algos = ("LRU", "LFU", "FIFO", "None")
                        if node_entry["algorithm"] not in valid_algos:
                            errors.append(
                                f"cache_config.nodes[{node_idx}].algorithm must be one of: {', '.join(valid_algos)}"
                            )
                    if "type" in node_entry:
                        valid_types = ("memory", "filesystem")
                        if node_entry["type"] not in valid_types:
                            errors.append(
                                f"cache_config.nodes[{node_idx}].type must be one of: {', '.join(valid_types)}"
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

    # Boolean keys
    for key in ("no_cli", "no_script_log", "warmup_only_cache_nodes"):
        if key in config and not isinstance(config[key], bool):
            errors.append(f"{key} must be a boolean")

    # Non-negative integer keys
    for key in ("duration", "warmup_get_interval"):
        if key in config:
            if not isinstance(config[key], int) or config[key] < 0:
                errors.append(f"{key} must be an integer >= 0")

    # Nullable integer keys
    for key in ("cache_default_rct_ms", "publisher_host"):
        if key in config and config[key] is not None:
            if not isinstance(config[key], int):
                errors.append(f"{key} must be an integer or null")

    # String keys
    for key in ("results_json", "script_log"):
        if key in config and not isinstance(config[key], str):
            errors.append(f"{key} must be a string")

    if "hot_uris" in config:
        val = config["hot_uris"]
        if not isinstance(val, (str, list)):
            errors.append("hot_uris must be a string or list of strings")

    if "warmup_gets" in config:
        if not isinstance(config["warmup_gets"], list):
            errors.append("warmup_gets must be a list")

    return errors


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
        "num",
        "output_dir",
        "timestamp",
        "legacy_layout",
        "no_cli",
        "duration",
        "results_json",
        "script_log",
        "no_script_log",
        "warmup_get_interval",
        "warmup_only_cache_nodes",
        "warmup_gets",
        "hot_uris",
        "cache_default_rct_ms",
        "publisher_host",
    )

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
        setattr(args, key, config[key])

    if "cache_config" in config:
        setattr(args, "cache_config", config["cache_config"])

    # Parse puts/gets if passed as JSON strings
    if isinstance(args.puts, str) and args.puts:
        args.puts = json.loads(args.puts)
    if isinstance(args.gets, str) and args.gets:
        args.gets = json.loads(args.gets)
    if isinstance(args.bw, str) and args.bw:
        args.bw = [args.bw]
    if isinstance(args.ext, str) and args.ext:
        args.ext = [args.ext]

    # Parse warmup_gets / hot_uris
    warmup_gets = getattr(args, "warmup_gets", "")
    if isinstance(warmup_gets, str) and warmup_gets:
        args.warmup_gets = json.loads(warmup_gets)
    elif not warmup_gets:
        args.warmup_gets = []

    hot_uris = getattr(args, "hot_uris", "")
    if isinstance(hot_uris, str) and hot_uris:
        args.hot_uris = [u.strip() for u in hot_uris.split(",") if u.strip()]
    elif isinstance(hot_uris, list):
        pass  # Already a list from YAML
    else:
        args.hot_uris = []

    # Ensure puts/gets are lists
    if not hasattr(args, "puts") or args.puts is None or args.puts == "":
        args.puts = []
    if not hasattr(args, "gets") or args.gets is None or args.gets == "":
        args.gets = []
