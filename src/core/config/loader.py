"""JSON/YAML configuration loader for cefore-emu."""

import json
import sys
from pathlib import Path
from typing import Any

from ..protocols import VALID_ROUTE_PROTOCOLS, normalize_route_protocol

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

    if "cache_default_rct_ms" in config:
        value = config["cache_default_rct_ms"]
        if value is not None and (not isinstance(value, int) or value < 1000):
            errors.append("cache_default_rct_ms must be an integer >= 1000 or null")

    if "publisher_host" in config:
        if config["publisher_host"] is not None and not isinstance(
            config["publisher_host"], int
        ):
            errors.append("publisher_host must be an integer or null")

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
                if op.get("mode") == "pubsub" and "pub_opts" in op:
                    pub_opts = op["pub_opts"]
                    if not isinstance(pub_opts, dict):
                        errors.append(f"puts[{idx}].pub_opts must be a dict")
                    else:
                        _PUB_OPTS_ALLOWED = {
                            "lifetime", "retry_limit", "target",
                            "ti_valid_algo", "rd_valid_algo",
                            "rate", "block_size", "expiry", "cache_time", "port_num",
                        }
                        unknown = set(pub_opts.keys()) - _PUB_OPTS_ALLOWED
                        if unknown:
                            errors.append(
                                f"puts[{idx}].pub_opts has unknown keys: {', '.join(sorted(unknown))}"
                            )
                        for field in ("lifetime", "retry_limit"):
                            if field in pub_opts and not isinstance(pub_opts[field], (int, float)):
                                errors.append(f"puts[{idx}].pub_opts.{field} must be a number")
                        if "target" in pub_opts and pub_opts["target"] not in ("trg", "ref", "both"):
                            errors.append(
                                f"puts[{idx}].pub_opts.target must be 'trg', 'ref', or 'both'"
                            )
                        for field in ("ti_valid_algo", "rd_valid_algo"):
                            if field in pub_opts and pub_opts[field] not in ("crc32c", "rsa-sha256"):
                                errors.append(
                                    f"puts[{idx}].pub_opts.{field} must be 'crc32c' or 'rsa-sha256'"
                                )

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
                if op.get("mode") == "pubsub" and "sub_opts" in op:
                    sub_opts = op["sub_opts"]
                    if not isinstance(sub_opts, dict):
                        errors.append(f"gets[{idx}].sub_opts must be a dict")
                    else:
                        _SUB_OPTS_ALLOWED = {
                            "pipeline", "ri_valid_algo", "td_valid_algo",
                            "consumer_per_content", "port_num", "wait",
                        }
                        unknown = set(sub_opts.keys()) - _SUB_OPTS_ALLOWED
                        if unknown:
                            errors.append(
                                f"gets[{idx}].sub_opts has unknown keys: {', '.join(sorted(unknown))}"
                            )
                        for field in ("pipeline", "consumer_per_content"):
                            if field in sub_opts and not isinstance(sub_opts[field], int):
                                errors.append(f"gets[{idx}].sub_opts.{field} must be an integer")
                        for field in ("ri_valid_algo", "td_valid_algo"):
                            if field in sub_opts and sub_opts[field] not in ("crc32c", "rsa-sha256"):
                                errors.append(
                                    f"gets[{idx}].sub_opts.{field} must be 'crc32c' or 'rsa-sha256'"
                                )
                        if "wait" in sub_opts and not isinstance(sub_opts["wait"], (int, float)):
                            errors.append(f"gets[{idx}].sub_opts.wait must be a number")

    if "auto" in config:
        auto = config["auto"]
        entries: list[Any] | None = None
        if isinstance(auto, dict):
            entries = [auto]
        elif isinstance(auto, list):
            entries = auto
        else:
            errors.append("auto must be a dict or list of dicts")

        if entries is not None:
            for idx, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    errors.append(f"auto[{idx}] must be a dict")
                    continue
                if "publishers" in entry:
                    if not isinstance(entry["publishers"], list):
                        errors.append(
                            f"auto[{idx}].publishers must be a list of host IDs"
                        )
                if "consumers" in entry:
                    val = entry["consumers"]
                    if not isinstance(val, (str, list)):
                        errors.append(
                            f"auto[{idx}].consumers must be 'random:N' string or list of host IDs"
                        )
                if "sub_opts" in entry:
                    sub_opts = entry["sub_opts"]
                    if not isinstance(sub_opts, dict):
                        errors.append(f"auto[{idx}].sub_opts must be a dict")
                    else:
                        if "wait" in sub_opts and not isinstance(sub_opts["wait"], (int, float)):
                            errors.append(f"auto[{idx}].sub_opts.wait must be a number")

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

    if "failure_scenarios" in config:
        fs = config["failure_scenarios"]
        if not isinstance(fs, dict):
            errors.append("failure_scenarios must be a dict")
        else:
            strategy = fs.get("strategy", "simple")
            valid_strategies = ("simple", "cyclic", "random", "manual")
            if strategy not in valid_strategies:
                errors.append(
                    "failure_scenarios.strategy must be one of: simple, cyclic, random, manual"
                )

            if strategy == "simple":
                simple = fs.get("simple")
                if simple is None:
                    errors.append(
                        "failure_scenarios with strategy 'simple' requires 'simple' block"
                    )
                elif not isinstance(simple, dict):
                    errors.append("failure_scenarios.simple must be a dict")
                else:
                    for field in ("interval", "duration", "count", "stagger"):
                        if field in simple and simple[field] is not None and not isinstance(simple[field], int):
                            errors.append(f"failure_scenarios.simple.{field} must be an integer")
                    if "count" in simple and isinstance(simple.get("count"), int) and simple["count"] < 0:
                        errors.append("failure_scenarios.simple.count must be an integer >= 0")
                    if "stagger" in simple and isinstance(simple.get("stagger"), int) and simple["stagger"] < 0:
                        errors.append("failure_scenarios.simple.stagger must be an integer >= 0")
                    if "exclude" in simple and simple["exclude"] is not None:
                        ex = simple["exclude"]
                        if not isinstance(ex, list) or not all(isinstance(host, int) for host in ex):
                            errors.append(
                                "failure_scenarios.simple.exclude must be a list of integers"
                            )
            else:
                cycles = fs.get("cycles")
                if cycles is None:
                    errors.append(
                        f"failure_scenarios with strategy '{strategy}' requires 'cycles' list"
                    )
                elif not isinstance(cycles, list):
                    errors.append("failure_scenarios.cycles must be a list")
                elif len(cycles) == 0:
                    errors.append(
                        f"failure_scenarios with strategy '{strategy}' requires at least one cycle"
                    )
                else:
                    for idx, cycle in enumerate(cycles):
                        if not isinstance(cycle, dict):
                            errors.append(f"failure_scenarios.cycles[{idx}] must be a dict")
                            continue
                        for field in ("interval", "duration", "count", "stagger"):
                            if field in cycle and cycle[field] is not None and not isinstance(cycle[field], int):
                                errors.append(
                                    f"failure_scenarios.cycles[{idx}].{field} must be an integer"
                                )
                        if "count" in cycle and isinstance(cycle.get("count"), int) and cycle["count"] < 0:
                            errors.append(
                                f"failure_scenarios.cycles[{idx}].count must be an integer >= 0"
                            )
                        if "stagger" in cycle and isinstance(cycle.get("stagger"), int) and cycle["stagger"] < 0:
                            errors.append(
                                f"failure_scenarios.cycles[{idx}].stagger must be an integer >= 0"
                            )
                        if "exclude" in cycle and cycle["exclude"] is not None:
                            ex = cycle["exclude"]
                            if not isinstance(ex, list) or not all(isinstance(host, int) for host in ex):
                                errors.append(
                                    f"failure_scenarios.cycles[{idx}].exclude must be a list of integers"
                                )
                        if "target" in cycle and cycle["target"] is not None:
                            tgt = cycle["target"]
                            if not isinstance(tgt, list) or not all(isinstance(host, int) for host in tgt):
                                errors.append(
                                    f"failure_scenarios.cycles[{idx}].target must be a list of integers"
                                )
                        if "allow_publishers" in cycle and cycle["allow_publishers"] is not None:
                            if not isinstance(cycle["allow_publishers"], bool):
                                errors.append(
                                    f"failure_scenarios.cycles[{idx}].allow_publishers must be a boolean"
                                )

    if "priority_uris" in config:
        priority_uris = config["priority_uris"]
        if not isinstance(priority_uris, dict):
            errors.append("priority_uris must be a dict")
        else:
            valid_modes = ("putget", "pubsub")
            valid_target = ("trg", "ref", "both")
            for level_name, level_cfg in priority_uris.items():
                if not isinstance(level_cfg, dict):
                    errors.append(f"priority_uris.{level_name} must be a dict")
                    continue

                patterns = level_cfg.get("patterns")
                if isinstance(patterns, str):
                    if not patterns.strip():
                        errors.append(f"priority_uris.{level_name}.patterns must not be empty")
                elif isinstance(patterns, list):
                    if not patterns:
                        errors.append(f"priority_uris.{level_name}.patterns must not be empty")
                    elif not all(isinstance(pattern, str) for pattern in patterns):
                        errors.append(
                            f"priority_uris.{level_name}.patterns must be a list of strings or a string"
                        )
                    elif any(not pattern.strip() for pattern in patterns):
                        errors.append(
                            f"priority_uris.{level_name}.patterns must not contain empty strings"
                        )
                else:
                    errors.append(
                        f"priority_uris.{level_name}.patterns must be a list of strings or a string"
                    )

                mode = level_cfg.get("mode")
                if mode is not None and mode not in valid_modes:
                    errors.append(f"priority_uris.{level_name}.mode must be 'putget' or 'pubsub'")

                for field in ("expiry", "cache_time", "rate"):
                    if field in level_cfg and level_cfg[field] is not None:
                        if not isinstance(level_cfg[field], (int, float)):
                            errors.append(
                                f"priority_uris.{level_name}.{field} must be a number"
                            )

                for field in ("block_size", "port_num", "lifetime", "retry_limit", "pipeline"):
                    if field in level_cfg and level_cfg[field] is not None:
                        if not isinstance(level_cfg[field], int):
                            errors.append(
                                f"priority_uris.{level_name}.{field} must be an integer"
                            )

                for field in ("valid_algo", "ti_valid_algo", "rd_valid_algo", "ri_valid_algo", "td_valid_algo"):
                    if field in level_cfg and level_cfg[field] is not None:
                        if not isinstance(level_cfg[field], str):
                            errors.append(
                                f"priority_uris.{level_name}.{field} must be a string"
                            )

                if "target" in level_cfg and level_cfg["target"] is not None:
                    if level_cfg["target"] not in valid_target:
                        errors.append(
                            f"priority_uris.{level_name}.target must be 'trg', 'ref', or 'both', got '{level_cfg['target']}'"
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
                elif not isinstance(bridge["local_routes"], str):
                    errors.append(
                        f"bridges[{idx}].local_routes must be a string"
                        " (e.g. '192.168.0.0/16')"
                    )
                if "nat" in bridge and not isinstance(bridge["nat"], bool):
                    errors.append(f"bridges[{idx}].nat must be a boolean")
                if "nat_out" in bridge and not isinstance(bridge["nat_out"], str):
                    errors.append(f"bridges[{idx}].nat_out must be a string")

    if "events" in config:
        if not isinstance(config["events"], list):
            errors.append("events must be a list")
        else:
            valid_event_types = ("link_down", "link_up", "fib_add", "fib_del", "fib_enable")
            for idx, event in enumerate(config["events"]):
                if not isinstance(event, dict):
                    errors.append(f"events[{idx}] must be a dict")
                    continue
                if "at" not in event:
                    errors.append(f"events[{idx}] missing required field 'at'")
                elif not isinstance(event["at"], (int, float)) or event["at"] < 0:
                    errors.append(f"events[{idx}].at must be a non-negative number")
                if "type" not in event:
                    errors.append(f"events[{idx}] missing required field 'type'")
                elif event["type"] not in valid_event_types:
                    errors.append(
                        f"events[{idx}].type must be one of: {', '.join(valid_event_types)}"
                    )
                else:
                    etype = event["type"]
                    if etype in ("link_down", "link_up"):
                        nodes = event.get("nodes")
                        if not isinstance(nodes, list) or len(nodes) != 2:
                            errors.append(f"events[{idx}].nodes must be a list of 2 elements")
                    elif etype in ("fib_add", "fib_del", "fib_enable"):
                        for field in ("host", "prefix", "next_hop"):
                            if field not in event:
                                errors.append(f"events[{idx}] missing required field '{field}'")
                        if "protocol" in event:
                            try:
                                normalize_route_protocol(event["protocol"])
                            except (TypeError, ValueError):
                                errors.append(
                                    f"events[{idx}].protocol must be one of: "
                                    f"{', '.join(VALID_ROUTE_PROTOCOLS)}"
                                )

    if "monitoring" in config:
        mon = config["monitoring"]
        if not isinstance(mon, dict):
            errors.append("monitoring must be a dict")
        else:
            if "interval" in mon:
                if not isinstance(mon["interval"], (int, float)) or mon["interval"] <= 0:
                    errors.append("monitoring.interval must be a positive number")
            valid_monitor_types = ("cefstatus", "csmgrstatus", "cefinfo")
            targets = mon.get("targets", [])
            if not isinstance(targets, list):
                errors.append("monitoring.targets must be a list")
            else:
                for idx, target in enumerate(targets):
                    if not isinstance(target, dict):
                        errors.append(f"monitoring.targets[{idx}] must be a dict")
                        continue
                    if "type" not in target:
                        errors.append(f"monitoring.targets[{idx}] missing required field 'type'")
                    elif target["type"] not in valid_monitor_types:
                        errors.append(
                            f"monitoring.targets[{idx}].type must be one of: "
                            f"{', '.join(valid_monitor_types)}"
                        )

    # Boolean keys
    for key in ("no_cli", "no_script_log"):
        if key in config and not isinstance(config[key], bool):
            errors.append(f"{key} must be a boolean")

    # Non-negative integer keys
    for key in ("duration",):
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
        if key in config and config[key] is not None and not isinstance(config[key], str):
            errors.append(f"{key} must be a string")

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
        "cache_default_rct_ms",
        "publisher_host",
        "num",
        "output_dir",
        "timestamp",
        "legacy_layout",
        "no_cli",
        "duration",
        "results_json",
        "script_log",
        "no_script_log",
        "cache_default_rct_ms",
        "publisher_host",
        "failure_scenarios",
        "priority_uris",
        "events",
        "monitoring",
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
