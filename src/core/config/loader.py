"""JSON/YAML configuration loader for cefore-emu."""

import ipaddress
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

LEGACY_CONTENT_KEYS = {"puts", "gets", "auto"}
VALID_ALGOS = ("crc32c", "rsa-sha256")


def _is_int(value: Any) -> bool:
    """Return True only for integer values, excluding booleans."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    """Return True only for numeric values, excluding booleans."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_number_option(errors, prefix, options, field, *, integer=False, minimum=0):
    if field not in options:
        return
    value = options[field]
    valid = _is_int(value) if integer else _is_number(value)
    if not valid or value < minimum:
        kind = "integer" if integer else "number"
        errors.append(f"{prefix}.{field} must be a {kind} >= {minimum}")


def _validate_algo_option(errors, prefix, options, field):
    if field in options and options[field] not in VALID_ALGOS:
        errors.append(f"{prefix}.{field} must be one of: {', '.join(VALID_ALGOS)}")


def _validate_put_options(errors, prefix, event):
    _validate_number_option(errors, prefix, event, "rate", minimum=0.001)
    for field in ("expiry", "cache_time"):
        _validate_number_option(errors, prefix, event, field, minimum=1)
    _validate_number_option(errors, prefix, event, "block_size", integer=True, minimum=60)
    _validate_number_option(errors, prefix, event, "port_num", integer=True, minimum=1)
    _validate_algo_option(errors, prefix, event, "valid_algo")


def _validate_get_options(errors, prefix, event):
    if "owner_only" in event and not isinstance(event["owner_only"], bool):
        errors.append(f"{prefix}.owner_only must be a boolean")
    for field in ("chunk", "pipeline", "port_num"):
        _validate_number_option(errors, prefix, event, field, integer=True, minimum=1)
    _validate_number_option(errors, prefix, event, "sg", integer=True, minimum=0)
    _validate_algo_option(errors, prefix, event, "valid_algo")


def _validate_pubsub_options(errors, prefix, event, op_type):
    options_key = "pub_opts" if op_type == "pubsub_pub" else "sub_opts"
    options = event.get(options_key) or {}
    if not isinstance(options, dict):
        errors.append(f"{prefix}.{options_key} must be a dict")
        return
    option_prefix = f"{prefix}.{options_key}"
    if op_type == "pubsub_pub":
        _validate_number_option(errors, option_prefix, options, "rate", minimum=0.001)
        for field in ("expiry", "cache_time"):
            _validate_number_option(errors, option_prefix, options, field, minimum=1)
        _validate_number_option(errors, option_prefix, options, "lifetime", minimum=0)
        for field in ("block_size", "port_num"):
            _validate_number_option(
                errors, option_prefix, options, field, integer=True, minimum=1
            )
        _validate_number_option(
            errors, option_prefix, options, "retry_limit", integer=True, minimum=0
        )
        if "target" in options and options["target"] not in ("trg", "ref", "both"):
            errors.append(f"{option_prefix}.target must be one of: trg, ref, both")
        for field in ("ti_valid_algo", "rd_valid_algo"):
            _validate_algo_option(errors, option_prefix, options, field)
    else:
        _validate_number_option(errors, option_prefix, options, "wait", minimum=0)
        for field in ("pipeline", "port_num"):
            _validate_number_option(
                errors, option_prefix, options, field, integer=True, minimum=1
            )
        for field in ("ri_valid_algo", "td_valid_algo"):
            _validate_algo_option(errors, option_prefix, options, field)


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


def validate_config(config: dict[str, Any]) -> list[str]:
    """Validate configuration and return list of errors.

    Args:
        config: Configuration dictionary to validate.

    Returns:
        List of error messages. Empty if valid.
    """
    errors = []

    if "hosts" in config:
        if not _is_int(config["hosts"]) or config["hosts"] < 3:
            errors.append("hosts must be an integer >= 3")

    if "switches" in config:
        if not _is_int(config["switches"]) or config["switches"] < 2:
            errors.append("switches must be an integer >= 2")

    if "seed" in config:
        if config["seed"] is not None and not _is_int(config["seed"]):
            errors.append("seed must be an integer or null")

    if "k" in config:
        if not _is_int(config["k"]) or config["k"] < 1:
            errors.append("k must be an integer >= 1")

    if "host_degree_min" in config:
        if not _is_int(config["host_degree_min"]) or config["host_degree_min"] < 1:
            errors.append("host_degree_min must be an integer >= 1")

    if "host_degree_max" in config:
        if not _is_int(config["host_degree_max"]):
            errors.append("host_degree_max must be an integer")
        else:
            min_val = config.get("host_degree_min", 1)
            if not _is_int(min_val):
                min_val = 1
            if config["host_degree_max"] < min_val:
                errors.append("host_degree_max must be >= host_degree_min")

    if "node_per_switch" in config:
        if not _is_int(config["node_per_switch"]) or config["node_per_switch"] < 0:
            errors.append("node_per_switch must be an integer >= 0")

    if "switch_use_all" in config:
        if not isinstance(config["switch_use_all"], bool):
            errors.append("switch_use_all must be a boolean")

    if "num" in config:
        if not _is_int(config["num"]) or config["num"] < 1:
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
        errors.append("legacy_layout has been removed; use output_dir and num instead")

    if "no_cli" in config:
        if not isinstance(config["no_cli"], bool):
            errors.append("no_cli must be a boolean")

    if "duration" in config:
        if not _is_int(config["duration"]) or config["duration"] < 0:
            errors.append("duration must be an integer >= 0")

    if "cache_default_rct_ms" in config:
        value = config["cache_default_rct_ms"]
        if value is not None and (not _is_int(value) or value < 1000):
            errors.append("cache_default_rct_ms must be an integer >= 1000 or null")

    if "cefnetd_timeout" in config:
        value = config["cefnetd_timeout"]
        if not _is_number(value) or value <= 0:
            errors.append("cefnetd_timeout must be a positive number")

    if "publisher_host" in config:
        if config["publisher_host"] is not None and not _is_int(config["publisher_host"]):
            errors.append("publisher_host must be an integer or null")

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
                    if not _is_int(default["count"]) or default["count"] < 0:
                        errors.append("cache_config.default.count must be an integer >= 0")
                if "capacity" in default:
                    if not _is_int(default["capacity"]) or default["capacity"] < 0:
                        errors.append("cache_config.default.capacity must be an integer >= 0")
                if "default_rct_ms" in default:
                    if (
                        not _is_int(default["default_rct_ms"])
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
                    if _is_int(ids):
                        ids = [ids]
                    if not isinstance(ids, list) or not all(_is_int(i) for i in ids):
                        errors.append(
                            f"cache_config.nodes[{node_idx}].id must be an integer or list of integers"
                        )
                    if "capacity" in node_entry:
                        if (
                            not _is_int(node_entry["capacity"])
                            or node_entry["capacity"] < 0
                        ):
                            errors.append(
                                f"cache_config.nodes[{node_idx}].capacity must be an integer >= 0"
                            )
                    if "default_rct_ms" in node_entry:
                        if (
                            not _is_int(node_entry["default_rct_ms"])
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
                        if field in simple and simple[field] is not None and not _is_int(simple[field]):
                            errors.append(f"failure_scenarios.simple.{field} must be an integer")
                        elif field in simple and simple[field] is not None and simple[field] < 0:
                            errors.append(f"failure_scenarios.simple.{field} must be an integer >= 0")
                    if "count" in simple and _is_int(simple.get("count")) and simple["count"] < 0:
                        errors.append("failure_scenarios.simple.count must be an integer >= 0")
                    if "stagger" in simple and _is_int(simple.get("stagger")) and simple["stagger"] < 0:
                        errors.append("failure_scenarios.simple.stagger must be an integer >= 0")
                    if "exclude" in simple and simple["exclude"] is not None:
                        ex = simple["exclude"]
                        if not isinstance(ex, list) or not all(_is_int(host) for host in ex):
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
                            if field in cycle and cycle[field] is not None and not _is_int(cycle[field]):
                                errors.append(
                                    f"failure_scenarios.cycles[{idx}].{field} must be an integer"
                                )
                            elif field in cycle and cycle[field] is not None and cycle[field] < 0:
                                errors.append(
                                    f"failure_scenarios.cycles[{idx}].{field} must be an integer >= 0"
                                )
                        if "count" in cycle and _is_int(cycle.get("count")) and cycle["count"] < 0:
                            errors.append(
                                f"failure_scenarios.cycles[{idx}].count must be an integer >= 0"
                            )
                        if "stagger" in cycle and _is_int(cycle.get("stagger")) and cycle["stagger"] < 0:
                            errors.append(
                                f"failure_scenarios.cycles[{idx}].stagger must be an integer >= 0"
                            )
                        if "exclude" in cycle and cycle["exclude"] is not None:
                            ex = cycle["exclude"]
                            if not isinstance(ex, list) or not all(_is_int(host) for host in ex):
                                errors.append(
                                    f"failure_scenarios.cycles[{idx}].exclude must be a list of integers"
                                )
                        if "target" in cycle and cycle["target"] is not None:
                            tgt = cycle["target"]
                            if not isinstance(tgt, list) or not all(_is_int(host) for host in tgt):
                                errors.append(
                                    f"failure_scenarios.cycles[{idx}].target must be a list of integers"
                                )
                        if "allow_publishers" in cycle and cycle["allow_publishers"] is not None:
                            if not isinstance(cycle["allow_publishers"], bool):
                                errors.append(
                                    f"failure_scenarios.cycles[{idx}].allow_publishers must be a boolean"
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
                elif not _is_int(bridge["switch"]):
                    errors.append(f"bridges[{idx}].switch must be an integer")
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

    if "pubsub_sub_startup_grace" in config:
        v = config["pubsub_sub_startup_grace"]
        if not _is_number(v) or v < 0:
            errors.append("pubsub_sub_startup_grace must be a non-negative number")

    if "warmup_get_interval" in config:
        v = config["warmup_get_interval"]
        if not _is_number(v) or v < 0:
            errors.append("warmup_get_interval must be a non-negative number")

    if "warmup_only_cache_nodes" in config:
        if not isinstance(config["warmup_only_cache_nodes"], bool):
            errors.append("warmup_only_cache_nodes must be a boolean")

    if "warmup_gets" in config:
        wg = config["warmup_gets"]
        if not isinstance(wg, list):
            errors.append("warmup_gets must be a list")
        else:
            for idx, entry in enumerate(wg):
                if not isinstance(entry, dict):
                    errors.append(f"warmup_gets[{idx}] must be a dict")
                    continue
                if "host" not in entry or not _is_int(entry["host"]):
                    errors.append(f"warmup_gets[{idx}].host must be an integer")
                if "uri" not in entry or not isinstance(entry["uri"], str):
                    errors.append(f"warmup_gets[{idx}].uri must be a string")

    if "events" in config:
        if not isinstance(config["events"], list):
            errors.append("events must be a list")
        else:
            valid_event_types = (
                "link_down", "link_up", "fib_add", "fib_del", "fib_enable",
                "bw_set", "compute_call",
                "put", "get", "pubsub_pub", "pubsub_sub",
            )
            host_count = config.get("hosts")
            for idx, event in enumerate(config["events"]):
                if not isinstance(event, dict):
                    errors.append(f"events[{idx}] must be a dict")
                    continue
                if "at" not in event:
                    errors.append(f"events[{idx}] missing required field 'at'")
                elif not _is_number(event["at"]) or event["at"] < 0:
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
                        elif not all(_is_int(n) for n in nodes):
                            errors.append(f"events[{idx}].nodes must be a list of 2 host indices")
                        elif _is_int(host_count):
                            for n in nodes:
                                if n < 0 or n >= host_count:
                                    errors.append(
                                        f"events[{idx}].nodes contains out-of-range host index {n}"
                                    )
                    elif etype == "bw_set":
                        nodes = event.get("nodes")
                        if not isinstance(nodes, list) or len(nodes) != 2:
                            errors.append(f"events[{idx}].nodes must be a list of 2 host indices")
                        elif not all(_is_int(n) for n in nodes):
                            errors.append(f"events[{idx}].nodes must be a list of 2 host indices")
                        elif _is_int(host_count):
                            for n in nodes:
                                if n < 0 or n >= host_count:
                                    errors.append(
                                        f"events[{idx}].nodes contains out-of-range host index {n}"
                                    )
                        if "bandwidth" not in event:
                            errors.append(f"events[{idx}] missing required field 'bandwidth'")
                        elif not _is_number(event["bandwidth"]) or event["bandwidth"] < 0:
                            errors.append(f"events[{idx}].bandwidth must be a non-negative number")
                    elif etype == "compute_call":
                        for field in ("host", "endpoint"):
                            if field not in event:
                                errors.append(f"events[{idx}] missing required field '{field}'")
                        if "host" in event and not _is_int(event["host"]):
                            errors.append(f"events[{idx}].host must be an integer")
                        if "endpoint" in event and not isinstance(event["endpoint"], str):
                            errors.append(f"events[{idx}].endpoint must be a string")
                        if "method" in event and event["method"] not in ("GET", "POST"):
                            errors.append(f"events[{idx}].method must be 'GET' or 'POST'")
                        if "timeout" in event:
                            if not _is_number(event["timeout"]) or event["timeout"] <= 0:
                                errors.append(f"events[{idx}].timeout must be a positive number")
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
                        if "host" in event and not _is_int(event["host"]):
                            errors.append(f"events[{idx}].host must be an integer")

                    elif etype in ("put", "pubsub_pub"):
                        for field in ("host", "uri", "file"):
                            if field not in event:
                                errors.append(f"events[{idx}] missing required field '{field}'")
                        if "host" in event and not _is_int(event["host"]):
                            errors.append(f"events[{idx}].host must be an integer")
                        if "uri" in event and not isinstance(event["uri"], str):
                            errors.append(f"events[{idx}].uri must be a string")
                        if "file" in event and not isinstance(event["file"], str):
                            errors.append(f"events[{idx}].file must be a string")
                        if etype == "put":
                            _validate_put_options(errors, f"events[{idx}]", event)
                            if (
                                event.get("repeat")
                                and config.get("no_cli") is True
                                and config.get("results_json")
                            ):
                                errors.append(
                                    f"events[{idx}].repeat is not supported for autotest put events"
                                )
                        else:
                            _validate_pubsub_options(
                                errors, f"events[{idx}]", event, etype
                            )
                    elif etype in ("get", "pubsub_sub"):
                        for field in ("host", "uri"):
                            if field not in event:
                                errors.append(f"events[{idx}] missing required field '{field}'")
                        if "host" in event and not _is_int(event["host"]):
                            errors.append(f"events[{idx}].host must be an integer")
                        if "uri" in event and not isinstance(event["uri"], str):
                            errors.append(f"events[{idx}].uri must be a string")
                        if etype == "get":
                            _validate_get_options(errors, f"events[{idx}]", event)
                        else:
                            _validate_pubsub_options(
                                errors, f"events[{idx}]", event, etype
                            )

                    # host range check for fib/compute_call events
                    if "host" in event and _is_int(event["host"]) and _is_int(host_count):
                        if event["host"] < 0 or event["host"] >= host_count:
                            errors.append(
                                f"events[{idx}].host is out of range (0..{host_count - 1})"
                            )

                # repeat validation (all event types)
                if "repeat" in event:
                    rep = event["repeat"]
                    if not isinstance(rep, dict):
                        errors.append(f"events[{idx}].repeat must be a dict")
                    else:
                        if "interval" in rep:
                            if not _is_number(rep["interval"]) or rep["interval"] <= 0:
                                errors.append(f"events[{idx}].repeat.interval must be a positive number")
                        if "duration" in rep:
                            if not _is_number(rep["duration"]) or rep["duration"] < 0:
                                errors.append(f"events[{idx}].repeat.duration must be a non-negative number")
                        if "count" in rep and rep["count"] is not None:
                            if not _is_int(rep["count"]) or rep["count"] < 1:
                                errors.append(f"events[{idx}].repeat.count must be a positive integer or null")
                        if "restore" in rep and not isinstance(rep["restore"], dict):
                            errors.append(f"events[{idx}].repeat.restore must be a dict")
                        if "restore_type" in rep and rep["restore_type"] not in valid_event_types:
                            errors.append(f"events[{idx}].repeat.restore_type must be a valid event type")

    if "monitoring" in config:
        mon = config["monitoring"]
        if not isinstance(mon, dict):
            errors.append("monitoring must be a dict")
        else:
            if "interval" in mon:
                if not _is_number(mon["interval"]) or mon["interval"] <= 0:
                    errors.append("monitoring.interval must be a positive number")
            valid_monitor_types = ("cefstatus", "csmgrstatus")
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
                    if "target_host" in target:
                        th = target["target_host"]
                        if not isinstance(th, str) or not th:
                            errors.append(
                                f"monitoring.targets[{idx}].target_host must be a non-empty string"
                            )

    if "addressing" in config:
        addr = config["addressing"]
        if not isinstance(addr, dict):
            errors.append("addressing must be a dict")
        else:
            if "network_cidr" in addr:
                val = addr["network_cidr"]
                if not isinstance(val, str):
                    errors.append("addressing.network_cidr must be a string")
                else:
                    try:
                        net = ipaddress.ip_network(val, strict=False)
                        if net.prefixlen != 16:
                            errors.append(
                                f"addressing.network_cidr must be an IPv4 /16 network "
                                f"(got /{net.prefixlen})"
                            )
                    except ValueError:
                        errors.append(
                            f"addressing.network_cidr must be a valid CIDR (got {val!r})"
                        )

    if "routing" in config:
        routing = config["routing"]
        if not isinstance(routing, dict):
            errors.append("routing must be a dict")
        else:
            strategy = routing.get("strategy", "dijkstra")
            valid_routing = ("dijkstra", "shortest_path", "ecmp")
            if strategy not in valid_routing:
                errors.append(f"routing.strategy must be one of {valid_routing}")
            if "k" in routing:
                if not _is_int(routing["k"]) or routing["k"] < 1:
                    errors.append("routing.k must be a positive integer")

    if "debug" in config:
        debug = config["debug"]
        if not isinstance(debug, (bool, dict)):
            errors.append("debug must be a boolean or dict")
        elif isinstance(debug, dict):
            artifacts = debug.get("artifacts", [])
            if not isinstance(artifacts, list):
                errors.append("debug.artifacts must be a list")
            else:
                _valid_artifacts = {"node_dirs", "fib_dump", "daemon_logs"}
                for art in artifacts:
                    if art not in _valid_artifacts:
                        errors.append(
                            f"debug.artifacts contains unknown artifact: {art!r}"
                        )
            if "output_subdir" in debug and not isinstance(debug["output_subdir"], str):
                errors.append("debug.output_subdir must be a string")

    # Boolean keys
    for key in ("no_cli", "no_script_log"):
        if key in config and not isinstance(config[key], bool):
            errors.append(f"{key} must be a boolean")

    # Non-negative integer keys
    for key in ("duration",):
        if key in config:
            if not _is_int(config[key]) or config[key] < 0:
                errors.append(f"{key} must be an integer >= 0")

    # Nullable integer keys
    for key in ("cache_default_rct_ms", "publisher_host"):
        if key in config and config[key] is not None:
            if not _is_int(config[key]):
                errors.append(f"{key} must be an integer or null")

    # Numeric CLI/config keys merged into runtime args.
    for key in ("node_per_switch", "down_interval", "down_duration", "down_count", "down_stagger", "cache_count"):
        if key in config and (not _is_int(config[key]) or config[key] < 0):
            errors.append(f"{key} must be an integer >= 0")
    if "webui_port" in config and (
        config["webui_port"] is not None
        and (not _is_int(config["webui_port"]) or config["webui_port"] <= 0)
    ):
        errors.append("webui_port must be a positive integer or null")

    # String keys
    for key in ("results_json", "script_log"):
        if key in config and config[key] is not None and not isinstance(config[key], str):
            errors.append(f"{key} must be a string")

    return errors


def validate_merged_args(args: Any) -> list[str]:
    """Validate the merged args namespace (after CLI overrides applied).

    Builds a config-like dict from the args namespace and delegates to
    validate_config.  Only includes keys that are present on args to avoid
    false positives for optional parameters.

    Args:
        args: argparse Namespace object after merge_cli_and_config.

    Returns:
        List of error messages. Empty if valid.
    """
    scalar_keys = (
        "hosts", "switches", "seed", "k", "num", "duration",
        "cache_default_rct_ms", "cefnetd_timeout", "publisher_host",
        "output_dir", "results_json", "script_log", "timestamp",
        "no_cli", "no_script_log", "host_degree_min", "host_degree_max",
        "node_per_switch", "switch_use_all", "pubsub_sub_startup_grace",
        "warmup_get_interval", "warmup_only_cache_nodes",
        "down_interval", "down_duration", "down_count", "down_stagger",
        "cache_count", "webui_port",
    )
    structured_keys = (
        "events", "monitoring", "routing",
        "cache_config", "failure_scenarios", "addressing",
        "warmup_gets",
    )
    nullable_keys = {"seed", "results_json", "script_log", "cache_default_rct_ms", "publisher_host"}

    config: dict[str, Any] = {}
    for key in scalar_keys:
        if hasattr(args, key):
            val = getattr(args, key)
            if val is not None or key in nullable_keys:
                config[key] = val
    for key in structured_keys:
        if hasattr(args, key):
            val = getattr(args, key)
            if val:
                config[key] = val

    return validate_config(config)


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
