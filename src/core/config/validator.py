"""Validation helpers for cefore-emu configuration dictionaries."""

import ipaddress
from dataclasses import dataclass
from typing import Any

from ..events import EVENT_SCHEMA, event_types, publication_event_types
from ..protocols import VALID_ROUTE_PROTOCOLS, normalize_route_protocol

VALID_ALGOS = ("crc32c", "rsa-sha256")


def _is_int(value: Any) -> bool:
    """Return True only for integer values, excluding booleans."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    """Return True only for numeric values, excluding booleans."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_number_option(
    errors, prefix, options, field, *, integer=False, minimum=0
):
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


@dataclass(frozen=True)
class OptionSpec:
    """Canonical option identity shared by config validation and merge code."""

    key: str
    kind: str
    default: Any = None
    minimum: int | float | None = None
    nullable: bool = False
    message: str | None = None
    flag: str | None = None
    action: Any = None
    choices: tuple[Any, ...] | None = None
    metavar: str | None = None
    help: str | None = None
    block: tuple[str, ...] = ()
    cli_order: int = 0
    config_allowed: bool = True
    cli_allowed: bool = True
    special_config_merge: bool = False


class _Spec:
    """Field validation spec for table-driven flat-key checking."""

    __slots__ = ("key", "kind", "nullable", "minimum", "message", "choices")

    def __init__(
        self, key, kind, nullable=False, minimum=None, message=None, choices=None
    ):
        self.key = key
        self.kind = kind
        self.nullable = nullable
        self.minimum = minimum
        self.message = message
        self.choices = choices


def _flat_key_error(spec):
    """Build the error message for a flat-key spec."""
    if spec.message:
        return spec.message
    k = spec.kind
    if k == "bool":
        return f"{spec.key} must be a boolean"
    if k == "str":
        if spec.nullable:
            return f"{spec.key} must be a string or null"
        return f"{spec.key} must be a string"
    suffix = ""
    if spec.nullable:
        suffix = " or null"
    if k == "int":
        if spec.minimum is not None:
            return f"{spec.key} must be an integer >= {spec.minimum}{suffix}"
        return f"{spec.key} must be an integer{suffix}"
    if k == "number":
        if spec.minimum is not None:
            return f"{spec.key} must be a number >= {spec.minimum}{suffix}"
        return f"{spec.key} must be a number{suffix}"
    if k == "enum":
        return f"{spec.key} must be one of: {', '.join(spec.choices)}"
    if k == "structured":
        return f"{spec.key} must be a list"
    return f"{spec.key} is invalid"


OPTION_SPECS = {
    "hosts": OptionSpec(
        "hosts",
        "int",
        default=5,
        minimum=3,
        flag="--hosts",
        help="number of hosts",
        block=("common", "linear", "connect"),
        cli_order=10,
    ),
    "switches": OptionSpec(
        "switches",
        "int",
        default=10,
        minimum=2,
        flag="--switches",
        help="number of switches (>= 2)",
        block=("mesh", "connect"),
        cli_order=10,
    ),
    "seed": OptionSpec(
        "seed",
        "int",
        nullable=True,
        flag="--seed",
        help="random seed",
        block=("common", "connect"),
        cli_order=20,
    ),
    "topo_png": OptionSpec(
        "topo_png",
        "str",
        nullable=True,
        flag="--topo-png",
        help="write topology PNG to this path",
        block=("common", "connect"),
        cli_order=30,
    ),
    "topo_layout": OptionSpec(
        "topo_layout",
        "enum",
        default="spring",
        choices=("spring", "kamada_kawai", "circular"),
        metavar="TOPO_LAYOUT",
        flag="--topo-layout",
        help="topology layout: spring, kamada_kawai, or circular",
        block=("common", "connect"),
        cli_order=40,
    ),
    "k": OptionSpec(
        "k",
        "int",
        default=2,
        minimum=1,
        flag="--k",
        help="number of shortest paths per destination",
        block=("mesh", "connect"),
        cli_order=60,
    ),
    "host_degree_min": OptionSpec(
        "host_degree_min",
        "int",
        default=1,
        minimum=1,
        flag="--host-degree-min",
        help="minimum number of switches per host (>=1)",
        block=("mesh", "connect"),
        cli_order=30,
    ),
    "host_degree_max": OptionSpec(
        "host_degree_max",
        "int",
        default=2,
        flag="--host-degree-max",
        help="maximum number of switches per host",
        block=("mesh", "connect"),
        cli_order=40,
    ),
    "node_per_switch": OptionSpec(
        "node_per_switch",
        "int",
        default=2,
        minimum=0,
        flag="--node-per-switch",
        help="max hosts per switch (0=unlimited, 2=one switch per link)",
        block=("mesh", "connect"),
        cli_order=20,
    ),
    "switch_use_all": OptionSpec(
        "switch_use_all",
        "bool",
        default=False,
        flag="--switch-use-all",
        action="store_true",
        help="create switches up to --switches and distribute extra links evenly",
        block=("mesh", "connect"),
        cli_order=50,
    ),
    "num": OptionSpec(
        "num",
        "int",
        minimum=1,
        # 2026-07-09 bug fix (audit follow-up to 73ca40b): num has no argparse
        # default (parser default is None, not a real experiment number), and
        # None is num's genuine "no numbered run" state throughout the
        # codebase (see experiment_dir_name/resolve_run_dir treating num=None
        # as omission). nullable=True documents that and is required by the
        # scalar-forwarding fix below: without it, a plain run with no --num
        # flag and no "num" key in config would forward None into
        # validate_config and be flagged as invalid, breaking every default
        # run. This was the one non-nullable-looking CLI scalar whose
        # argparse default was None; every other non-nullable cli_allowed=True
        # scalar key defaults to a real value, which is the invariant
        # validate_merged_args's scalar loop relies on (nullable scalars are
        # exempt — they tolerate None; cli_allowed=False scalars like
        # cefnetd_timeout never enter a parser, so presence on args already
        # means "was in the config").
        nullable=True,
        flag="--num",
        help="experiment number (enables log directory output)",
        block=("common", "linear", "connect"),
        cli_order=50,
    ),
    "output_dir": OptionSpec(
        "output_dir",
        "str",
        default="logs",
        flag="--output-dir",
        help="base output directory (default: logs)",
        block=("common", "linear", "connect"),
        cli_order=60,
    ),
    "results_json": OptionSpec(
        "results_json",
        "str",
        nullable=True,
        default="",
        flag="--results-json",
        help="write eval get results to JSON under output directory",
        block=("disaster",),
        cli_order=150,
    ),
    "timestamp": OptionSpec(
        "timestamp",
        "bool",
        default=False,
        flag="--timestamp",
        action="store_true",
        help="add timestamp to output directory name",
        block=("common", "linear", "connect"),
        cli_order=70,
    ),
    "no_cli": OptionSpec(
        "no_cli",
        "bool",
        default=False,
        flag="--no-cli",
        action="store_true",
        help="skip interactive CLI (flap output visible on stdout)",
        block=("disaster", "connect"),
        cli_order=120,
    ),
    "no_script_log": OptionSpec(
        "no_script_log",
        "bool",
        default=False,
        flag="--no-script-log",
        action="store_true",
        help="disable script log output",
        block=("disaster", "connect"),
        cli_order=110,
    ),
    "duration": OptionSpec(
        "duration",
        "int",
        default=0,
        minimum=0,
        flag="--duration",
        help="eval phase duration in seconds for --no-cli (0: single cycle)",
        block=("disaster",),
        cli_order=130,
    ),
    "cache_default_rct_ms": OptionSpec(
        "cache_default_rct_ms",
        "int",
        nullable=True,
        minimum=1000,
        flag="--cache-default-rct-ms",
        help="override CACHE_DEFAULT_RCT(ms) for cache nodes",
        block=("disaster",),
        cli_order=160,
    ),
    "publisher_host": OptionSpec(
        "publisher_host",
        "int",
        nullable=True,
        flag="--publisher-host",
        help="explicit publisher host used for publisher-down metric",
        block=("disaster",),
        cli_order=170,
    ),
    "pubsub_sub_startup_grace": OptionSpec(
        "pubsub_sub_startup_grace",
        "number",
        default=1.0,
        minimum=0,
        message="pubsub_sub_startup_grace must be a non-negative number",
        flag="--pubsub-sub-startup-grace",
        help="seconds to wait after starting cefsubfile before launching cefpubfile (default: 1.0)",
        block=("disaster",),
        cli_order=180,
    ),
    "warmup_get_interval": OptionSpec(
        "warmup_get_interval",
        "number",
        default=0,
        minimum=0,
        message="warmup_get_interval must be a non-negative number",
        flag="--warmup-get-interval",
        help="seconds between warmup gets (0=no delay)",
        block=("disaster",),
        cli_order=190,
    ),
    "warmup_only_cache_nodes": OptionSpec(
        "warmup_only_cache_nodes",
        "bool",
        default=True,
        flag="--warmup-only-cache-nodes",
        action="BooleanOptionalAction",
        help="restrict warmup gets to cache nodes (default: true)",
        block=("disaster",),
        cli_order=200,
    ),
    "down_interval": OptionSpec(
        "down_interval",
        "int",
        default=0,
        minimum=0,
        flag="--down-interval",
        help="seconds between down events (0 to disable)",
        block=("disaster", "connect"),
        cli_order=10,
    ),
    "down_duration": OptionSpec(
        "down_duration",
        "int",
        default=0,
        minimum=0,
        flag="--down-duration",
        help="seconds to keep host down",
        block=("disaster", "connect"),
        cli_order=20,
    ),
    "down_exclude": OptionSpec(
        "down_exclude",
        "str",
        default="",
        flag="--down-exclude",
        help="comma-separated host ids to exclude from flapping",
        block=("disaster", "connect"),
        cli_order=30,
    ),
    "down_count": OptionSpec(
        "down_count",
        "int",
        default=5,
        minimum=0,
        flag="--down-count",
        help="number of hosts to keep down per cycle",
        block=("disaster", "connect"),
        cli_order=40,
    ),
    "down_stagger": OptionSpec(
        "down_stagger",
        "int",
        default=2,
        minimum=0,
        flag="--down-stagger",
        help="seconds to stagger down events within a cycle",
        block=("disaster", "connect"),
        cli_order=50,
    ),
    "cache_count": OptionSpec(
        "cache_count",
        "int",
        default=0,
        minimum=0,
        flag="--cache-count",
        help="number of cache nodes (0 = down-count + 1)",
        block=("disaster", "connect"),
        cli_order=60,
    ),
    "bw": OptionSpec(
        "bw",
        "structured",
        default=[],
        flag="--bw",
        action="append",
        help="set bandwidth: nodeA,nodeB,mbps (repeatable)",
        block=("disaster", "connect"),
        cli_order=70,
    ),
    "ext": OptionSpec(
        "ext",
        "structured",
        default=[],
        flag="--ext",
        action="append",
        help="attach external intf: host,ifname,ip[,mtu]; ip required in CIDR form (repeatable)",
        block=("disaster", "connect"),
        cli_order=80,
    ),
    "bridge": OptionSpec(
        "bridge",
        "structured",
        default=[],
        flag="--bridge",
        action="append",
        help="root ns bridge: switch,root_ip,local_routes[,ext_routes,gateway] (repeatable)",
        block=("disaster", "connect"),
        cli_order=90,
        config_allowed=False,
    ),
    "bridges": OptionSpec("bridges", "structured", default=[], cli_allowed=False),
    "failure_scenarios": OptionSpec(
        "failure_scenarios", "structured", cli_allowed=False
    ),
    "events": OptionSpec("events", "structured", cli_allowed=False),
    "monitoring": OptionSpec("monitoring", "structured", cli_allowed=False),
    "routing": OptionSpec("routing", "structured", cli_allowed=False),
    "addressing": OptionSpec("addressing", "structured", cli_allowed=False),
    "cache_config": OptionSpec(
        "cache_config", "structured", cli_allowed=False, special_config_merge=True
    ),
    "forwarding_config": OptionSpec(
        "forwarding_config",
        "structured",
        default={"default": "flooding"},
        block=("disaster", "connect"),
        cli_allowed=False,
        special_config_merge=True,
    ),
    "cefnetd_timeout": OptionSpec("cefnetd_timeout", "number", cli_allowed=False),
    "warmup_gets": OptionSpec("warmup_gets", "structured", cli_allowed=False),
    "webui_port": OptionSpec(
        "webui_port",
        "int",
        nullable=True,
        minimum=1,
        message="webui_port must be a positive integer or null",
        flag="--webui-port",
        metavar="PORT",
        help="start live dashboard on this port (disabled by default; recommended: 5080)",
        block=("disaster",),
        cli_order=210,
    ),
    "script_log": OptionSpec(
        "script_log",
        "str",
        nullable=True,
        message="script_log must be a string",
        flag="--script-log",
        help="log script output to file",
        block=("disaster", "connect"),
        cli_order=100,
    ),
    "debug": OptionSpec(
        "debug",
        "structured",
        default=False,
        flag="--debug",
        action="store_true",
        help="enable all debug artifact collection (equivalent to all --debug-artifact choices)",
        block=("debug",),
        cli_order=10,
        special_config_merge=True,
    ),
    "debug_artifact": OptionSpec(
        "debug_artifact",
        "enum",
        default=[],
        config_allowed=False,
        flag="--debug-artifact",
        action="append",
        choices=("node_dirs", "fib_dump"),
        metavar="ARTIFACT",
        help=(
            "collect a specific debug artifact (repeatable): node_dirs, fib_dump; "
            "daemon logs are collected automatically when run_dir is specified"
        ),
        block=("debug",),
        cli_order=20,
    ),
    "config": OptionSpec(
        "config",
        "str",
        default="",
        config_allowed=False,
        flag="--config",
        help="JSON/YAML config file to override parameters",
        block=("disaster", "connect"),
        cli_order=95,
    ),
}


_FLAT_SPECS = [
    _Spec(spec.key, spec.kind, spec.nullable, spec.minimum, spec.message, spec.choices)
    for spec in OPTION_SPECS.values()
    if spec.config_allowed
    and spec.kind in ("bool", "str", "int", "number", "enum")
    and spec.key not in {"debug", "cefnetd_timeout"}
]
_FLAT_SPECS.extend(
    _Spec(spec.key, spec.kind, spec.nullable, spec.minimum, spec.message, spec.choices)
    for spec in (OPTION_SPECS["bw"], OPTION_SPECS["ext"])
)


def _validate_flat_keys(errors, config):
    """Validate flat (non-structured) config keys via the spec table."""
    for spec in _FLAT_SPECS:
        if spec.key not in config:
            continue
        value = config[spec.key]
        if spec.nullable and value is None:
            continue
        msg = _flat_key_error(spec)
        if spec.kind == "bool":
            if not isinstance(value, bool):
                errors.append(msg)
        elif spec.kind == "str":
            if not isinstance(value, str):
                errors.append(msg)
        elif spec.kind == "int":
            if not _is_int(value) or (
                spec.minimum is not None and value < spec.minimum
            ):
                errors.append(msg)
        elif spec.kind == "number":
            if not _is_number(value) or (
                spec.minimum is not None and value < spec.minimum
            ):
                errors.append(msg)
        elif spec.kind == "enum":
            if value not in spec.choices:
                errors.append(msg)
        elif spec.kind == "structured":
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                errors.append(msg)


def config_option_keys() -> tuple[str, ...]:
    """Return config-merge keys from the canonical option table."""
    return tuple(
        spec.key
        for spec in OPTION_SPECS.values()
        if spec.config_allowed and not spec.special_config_merge
    )


def nullable_option_keys() -> set[str]:
    """Return options where config null preserves parser defaults."""
    return {
        spec.key
        for spec in OPTION_SPECS.values()
        if spec.config_allowed and spec.nullable
    }


def scalar_option_keys() -> tuple[str, ...]:
    """Return scalar keys copied from argparse Namespace for merged validation."""
    return tuple(
        spec.key
        for spec in OPTION_SPECS.values()
        if spec.config_allowed
        and spec.kind in ("bool", "str", "int", "number", "enum")
        and spec.key not in {"debug", "cefnetd_timeout"}
    ) + ("cefnetd_timeout",)


def structured_option_keys() -> tuple[str, ...]:
    """Return structured keys copied from argparse Namespace for merged validation."""
    return tuple(
        spec.key
        for spec in OPTION_SPECS.values()
        if spec.config_allowed
        and spec.kind == "structured"
        and not spec.special_config_merge
    )


def _validate_cache_config(errors, config, host_count):
    _ = host_count
    if "cache_config" in config:
        cc = config["cache_config"]
        if not isinstance(cc, dict):
            errors.append("cache_config must be a dict")
        else:
            valid_strategies = ("k_centers", "manual", "degree_based", "random")
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
                        errors.append(
                            "cache_config.default.count must be an integer >= 0"
                        )
                if "capacity" in default:
                    if not _is_int(default["capacity"]) or default["capacity"] < 0:
                        errors.append(
                            "cache_config.default.capacity must be an integer >= 0"
                        )
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


FORWARDING_STRATEGY_CHOICES = ("default", "flooding", "shortest_path")


def _validate_forwarding_config(errors, config):
    if "forwarding_config" not in config:
        return

    fc = config["forwarding_config"]
    if not isinstance(fc, dict):
        errors.append("forwarding_config must be a dict")
        return
    if not fc:
        errors.append("forwarding_config must not be empty")
        return

    if "default" in fc and fc["default"] not in FORWARDING_STRATEGY_CHOICES:
        errors.append(
            "forwarding_config.default must be one of: "
            + ", ".join(FORWARDING_STRATEGY_CHOICES)
        )

    nodes = fc.get("nodes", [])
    if not isinstance(nodes, list):
        errors.append("forwarding_config.nodes must be a list")
        return
    for node_idx, node_entry in enumerate(nodes):
        if not isinstance(node_entry, dict):
            errors.append(f"forwarding_config.nodes[{node_idx}] must be a dict")
            continue
        ids = node_entry.get("id", [])
        if not isinstance(ids, list) or not all(_is_int(i) for i in ids):
            errors.append(
                f"forwarding_config.nodes[{node_idx}].id must be a list of integers"
            )
        if "strategy" not in node_entry:
            # 2026-07-08 silent-ignore fix: ForwardingConfigManager._parse_node_overrides
            # skips any node entry without "strategy" (src/runtime/forwarding.py), so an
            # override missing this key previously passed validation and then did nothing
            # at runtime with no error surfaced to the user.
            errors.append(
                f"forwarding_config.nodes[{node_idx}].strategy is required"
            )
        elif node_entry["strategy"] not in FORWARDING_STRATEGY_CHOICES:
            errors.append(
                f"forwarding_config.nodes[{node_idx}].strategy must be one of: "
                + ", ".join(FORWARDING_STRATEGY_CHOICES)
            )


def _validate_failure_scenarios(errors, config):
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
                    for field in ("interval", "duration"):
                        if field in simple and simple[field] is None:
                            errors.append(
                                f"failure_scenarios.simple.{field} must not be null"
                            )
                    for field in ("interval", "duration", "count", "stagger"):
                        if (
                            field in simple
                            and simple[field] is not None
                            and not _is_int(simple[field])
                        ):
                            errors.append(
                                f"failure_scenarios.simple.{field} must be an integer"
                            )
                        elif (
                            field in simple
                            and simple[field] is not None
                            and simple[field] < 0
                        ):
                            errors.append(
                                f"failure_scenarios.simple.{field} must be an integer >= 0"
                            )
                    if (
                        "count" in simple
                        and _is_int(simple.get("count"))
                        and simple["count"] < 0
                    ):
                        errors.append(
                            "failure_scenarios.simple.count must be an integer >= 0"
                        )
                    if (
                        "stagger" in simple
                        and _is_int(simple.get("stagger"))
                        and simple["stagger"] < 0
                    ):
                        errors.append(
                            "failure_scenarios.simple.stagger must be an integer >= 0"
                        )
                    if "exclude" in simple and simple["exclude"] is not None:
                        ex = simple["exclude"]
                        if not isinstance(ex, list) or not all(
                            _is_int(host) for host in ex
                        ):
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
                            errors.append(
                                f"failure_scenarios.cycles[{idx}] must be a dict"
                            )
                            continue
                        for field in ("interval", "duration"):
                            if field in cycle and cycle[field] is None:
                                errors.append(
                                    f"failure_scenarios.cycles[{idx}].{field} must not be null"
                                )
                        for field in ("interval", "duration", "count", "stagger"):
                            if (
                                field in cycle
                                and cycle[field] is not None
                                and not _is_int(cycle[field])
                            ):
                                errors.append(
                                    f"failure_scenarios.cycles[{idx}].{field} must be an integer"
                                )
                            elif (
                                field in cycle
                                and cycle[field] is not None
                                and cycle[field] < 0
                            ):
                                errors.append(
                                    f"failure_scenarios.cycles[{idx}].{field} must be an integer >= 0"
                                )
                        if (
                            "count" in cycle
                            and _is_int(cycle.get("count"))
                            and cycle["count"] < 0
                        ):
                            errors.append(
                                f"failure_scenarios.cycles[{idx}].count must be an integer >= 0"
                            )
                        if (
                            "stagger" in cycle
                            and _is_int(cycle.get("stagger"))
                            and cycle["stagger"] < 0
                        ):
                            errors.append(
                                f"failure_scenarios.cycles[{idx}].stagger must be an integer >= 0"
                            )
                        if "exclude" in cycle and cycle["exclude"] is not None:
                            ex = cycle["exclude"]
                            if not isinstance(ex, list) or not all(
                                _is_int(host) for host in ex
                            ):
                                errors.append(
                                    f"failure_scenarios.cycles[{idx}].exclude must be a list of integers"
                                )
                        if "target" in cycle and cycle["target"] is not None:
                            tgt = cycle["target"]
                            if not isinstance(tgt, list) or not all(
                                _is_int(host) for host in tgt
                            ):
                                errors.append(
                                    f"failure_scenarios.cycles[{idx}].target must be a list of integers"
                                )
                        if (
                            "allow_publishers" in cycle
                            and cycle["allow_publishers"] is not None
                        ):
                            if not isinstance(cycle["allow_publishers"], bool):
                                errors.append(
                                    f"failure_scenarios.cycles[{idx}].allow_publishers must be a boolean"
                                )


def _validate_bridges(errors, config):
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
                elif not isinstance(bridge["root_ip"], str):
                    errors.append(f"bridges[{idx}].root_ip must be a string")
                elif bridge["root_ip"] != "auto":
                    root_ip_val = bridge["root_ip"]
                    if "/" not in root_ip_val:
                        errors.append(
                            f"bridges[{idx}].root_ip must be CIDR form"
                            f" (e.g. '10.0.0.1/24') or 'auto';"
                            f" got {root_ip_val!r}"
                        )
                    else:
                        try:
                            ipaddress.ip_interface(root_ip_val)
                        except (ValueError, TypeError):
                            errors.append(
                                f"bridges[{idx}].root_ip is not a valid CIDR"
                                f" address: {root_ip_val!r}"
                            )
                if "local_routes" not in bridge:
                    errors.append(
                        f"bridges[{idx}] missing required field 'local_routes'"
                    )
                elif not isinstance(bridge["local_routes"], str):
                    errors.append(
                        f"bridges[{idx}].local_routes must be a string"
                        " (e.g. '192.168.0.0/16')"
                    )
                if "nat" in bridge and not isinstance(bridge["nat"], bool):
                    errors.append(f"bridges[{idx}].nat must be a boolean")
                if "nat_out" in bridge and not isinstance(bridge["nat_out"], str):
                    errors.append(f"bridges[{idx}].nat_out must be a string")


def _validate_put_options(errors, prefix, event):
    _validate_number_option(errors, prefix, event, "rate", minimum=0.001)
    for field in ("expiry", "cache_time"):
        _validate_number_option(errors, prefix, event, field, minimum=1)
    _validate_number_option(
        errors, prefix, event, "block_size", integer=True, minimum=60
    )
    _validate_number_option(errors, prefix, event, "port_num", integer=True, minimum=1)
    _validate_algo_option(errors, prefix, event, "valid_algo")


def _validate_get_options(errors, prefix, event):
    if "owner_only" in event and not isinstance(event["owner_only"], bool):
        errors.append(f"{prefix}.owner_only must be a boolean")
    for field in ("chunk", "pipeline", "port_num"):
        _validate_number_option(errors, prefix, event, field, integer=True, minimum=1)
    if "sg" in event and not isinstance(event["sg"], bool):
        errors.append(
            f"{prefix}.sg must be a boolean (true to send Long Life Interest)"
        )
    _validate_algo_option(errors, prefix, event, "valid_algo")


# The exact option keys cefputfile republishing forwards; anything else is
# either cefpubfile-only (lifetime/retry_limit/target) or a typo, and a key
# that would be silently dropped at runtime must fail at config time instead.
_PUTFILE_OPTION_KEYS = frozenset(
    {"rate", "block_size", "expiry", "cache_time", "valid_algo", "port_num"}
)


def _validate_putfile_options(errors, prefix, event):
    """Validate a ``pub_opts`` dict holding cefputfile options.

    The option set and its bounds are exactly the put event's cefputfile
    flags — delegated to ``_validate_put_options`` so the two can never
    diverge (e.g. block_size >= 60 is the cefputfile minimum). Unknown keys
    are rejected, and a falsy non-dict ([]/false/0/"") must not coerce to
    an empty dict and bypass the type check.
    """
    if "pub_opts" not in event:
        return
    options = event["pub_opts"]
    if not isinstance(options, dict):
        errors.append(f"{prefix}.pub_opts must be a dict")
        return
    option_prefix = f"{prefix}.pub_opts"
    # 2026-07-16 audit fix: keys may be arbitrary YAML scalars; sorting a
    # mixed-type key set raises TypeError, so normalize to str before sorting.
    unknown = sorted(str(k) for k in set(options) - _PUTFILE_OPTION_KEYS)
    if unknown:
        errors.append(
            f"{option_prefix} has unsupported keys: {', '.join(map(str, unknown))} "
            f"(allowed: {', '.join(sorted(_PUTFILE_OPTION_KEYS))})"
        )
    _validate_put_options(errors, option_prefix, options)


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


def _validate_events(errors, config):
    if "events" in config:
        if not isinstance(config["events"], list):
            errors.append("events must be a list")
        else:
            valid_event_types = event_types()
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
                            errors.append(
                                f"events[{idx}].nodes must be a list of 2 elements"
                            )
                        elif not all(_is_int(n) for n in nodes):
                            errors.append(
                                f"events[{idx}].nodes must be a list of 2 host indices"
                            )
                        elif _is_int(host_count):
                            for n in nodes:
                                if n < 0 or n >= host_count:
                                    errors.append(
                                        f"events[{idx}].nodes contains out-of-range host index {n}"
                                    )
                    elif etype == "bw_set":
                        nodes = event.get("nodes")
                        if not isinstance(nodes, list) or len(nodes) != 2:
                            errors.append(
                                f"events[{idx}].nodes must be a list of 2 host indices"
                            )
                        elif not all(_is_int(n) for n in nodes):
                            errors.append(
                                f"events[{idx}].nodes must be a list of 2 host indices"
                            )
                        elif _is_int(host_count):
                            for n in nodes:
                                if n < 0 or n >= host_count:
                                    errors.append(
                                        f"events[{idx}].nodes contains out-of-range host index {n}"
                                    )
                        if "bandwidth" not in event:
                            errors.append(
                                f"events[{idx}] missing required field 'bandwidth'"
                            )
                        elif (
                            not _is_number(event["bandwidth"]) or event["bandwidth"] < 0
                        ):
                            errors.append(
                                f"events[{idx}].bandwidth must be a non-negative number"
                            )
                    elif etype == "compute_call":
                        for field in EVENT_SCHEMA[etype].required_fields:
                            if field not in event:
                                errors.append(
                                    f"events[{idx}] missing required field '{field}'"
                                )
                        if "host" in event and not _is_int(event["host"]):
                            errors.append(f"events[{idx}].host must be an integer")
                        if "endpoint" in event and not isinstance(
                            event["endpoint"], str
                        ):
                            errors.append(f"events[{idx}].endpoint must be a string")
                        if "method" in event and event["method"] not in ("GET", "POST"):
                            errors.append(
                                f"events[{idx}].method must be 'GET' or 'POST'"
                            )
                        if "timeout" in event:
                            if (
                                not _is_number(event["timeout"])
                                or event["timeout"] <= 0
                            ):
                                errors.append(
                                    f"events[{idx}].timeout must be a positive number"
                                )
                        for field in ("payload", "output_file", "publish_uri"):
                            if field in event and not isinstance(
                                event[field], str
                            ):
                                errors.append(
                                    f"events[{idx}].{field} must be a string"
                                )
                        if "headers" in event:
                            headers = event["headers"]
                            if not isinstance(headers, dict) or not all(
                                isinstance(k, str) and isinstance(v, str)
                                for k, v in headers.items()
                            ):
                                errors.append(
                                    f"events[{idx}].headers must be a dict of "
                                    f"string keys to string values"
                                )
                        # cefputfile needs a saved response body to publish;
                        # publish_uri without output_file can never publish.
                        if event.get("publish_uri") and not event.get(
                            "output_file"
                        ):
                            errors.append(
                                f"events[{idx}].publish_uri requires "
                                f"output_file to be set"
                            )
                        # 2026-07-16 audit fix: repeat restore forms merge a
                        # synthesized event at runtime, bypassing this
                        # validator and the pre-run conditional-publication
                        # (FIB) extraction — a restored publish_uri would
                        # publish content no consumer can reach. compute has
                        # no natural "restore", so repeat is an allowlist:
                        # anything but interval/count (restore forms, typos)
                        # is rejected rather than silently ignored.
                        repeat = event.get("repeat")
                        if isinstance(repeat, dict):
                            extra = sorted(
                                str(k) for k in set(repeat) - {"interval", "count"}
                            )
                            if extra:
                                errors.append(
                                    f"events[{idx}].repeat for compute_call "
                                    f"allows only interval/count; got: "
                                    f"{', '.join(extra)}"
                                )
                        # 2026-07-16 audit fix: publishing speed is governed
                        # by pub_opts rate, not the HTTP request, so the
                        # cefputfile deadline is its own field.
                        if "publish_timeout" in event:
                            if (
                                not _is_number(event["publish_timeout"])
                                or event["publish_timeout"] <= 0
                            ):
                                errors.append(
                                    f"events[{idx}].publish_timeout must be "
                                    f"a positive number"
                                )
                        _validate_putfile_options(
                            errors, f"events[{idx}]", event
                        )
                    elif etype in ("fib_add", "fib_del", "fib_enable"):
                        for field in EVENT_SCHEMA[etype].required_fields:
                            if field not in event:
                                errors.append(
                                    f"events[{idx}] missing required field '{field}'"
                                )
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

                    elif etype in publication_event_types():
                        for field in EVENT_SCHEMA[etype].required_fields:
                            if field not in event:
                                errors.append(
                                    f"events[{idx}] missing required field '{field}'"
                                )
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
                        for field in EVENT_SCHEMA[etype].required_fields:
                            if field not in event:
                                errors.append(
                                    f"events[{idx}] missing required field '{field}'"
                                )
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
                    if (
                        "host" in event
                        and _is_int(event["host"])
                        and _is_int(host_count)
                    ):
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
                                errors.append(
                                    f"events[{idx}].repeat.interval must be a positive number"
                                )
                        if "duration" in rep:
                            if not _is_number(rep["duration"]) or rep["duration"] < 0:
                                errors.append(
                                    f"events[{idx}].repeat.duration must be a non-negative number"
                                )
                        if "count" in rep and rep["count"] is not None:
                            if not _is_int(rep["count"]) or rep["count"] < 1:
                                errors.append(
                                    f"events[{idx}].repeat.count must be a positive integer or null"
                                )
                        if "restore" in rep and not isinstance(rep["restore"], dict):
                            errors.append(
                                f"events[{idx}].repeat.restore must be a dict"
                            )
                        if (
                            "restore_type" in rep
                            and rep["restore_type"] not in valid_event_types
                        ):
                            errors.append(
                                f"events[{idx}].repeat.restore_type must be a valid event type"
                            )


def validate_config(config: dict[str, Any]) -> list[str]:
    """Validate configuration and return list of errors.

    Args:
        config: Configuration dictionary to validate.

    Returns:
        List of error messages. Empty if valid.
    """
    errors: list[str] = []

    _validate_flat_keys(errors, config)

    if "host_degree_max" in config:
        min_val = config.get("host_degree_min", 1)
        if not _is_int(min_val):
            min_val = 1
        if _is_int(config["host_degree_max"]):
            if config["host_degree_max"] < min_val:
                errors.append("host_degree_max must be >= host_degree_min")

    if "legacy_layout" in config:
        errors.append("legacy_layout has been removed; use output_dir and num instead")

    if "cefnetd_timeout" in config:
        value = config["cefnetd_timeout"]
        if not _is_number(value) or value <= 0:
            errors.append("cefnetd_timeout must be a positive number")

    _validate_cache_config(errors, config, config.get("hosts"))
    _validate_forwarding_config(errors, config)

    _validate_failure_scenarios(errors, config)

    _validate_bridges(errors, config)

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

    _validate_events(errors, config)

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
                        errors.append(
                            f"monitoring.targets[{idx}] missing required field 'type'"
                        )
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
                _valid_artifacts = {"node_dirs", "fib_dump"}
                for art in artifacts:
                    if art not in _valid_artifacts:
                        errors.append(
                            f"debug.artifacts contains unknown artifact: {art!r}"
                        )
            if "output_subdir" in debug and not isinstance(debug["output_subdir"], str):
                errors.append("debug.output_subdir must be a string")

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
    scalar_keys = scalar_option_keys()
    structured_keys = structured_option_keys()

    config: dict[str, Any] = {}
    for key in scalar_keys:
        # 2026-07-09 bug fix (audit follow-up to 73ca40b): this loop used to
        # gate on `val is not None or key in nullable_keys`, so a present
        # None for a NON-nullable scalar (e.g. "hosts: null" in YAML) was
        # silently dropped before validate_config ever saw it — bootstrap
        # exited 0 on a config that validate_config({"hosts": None}) rejects
        # outright. Scalar keys can't use B1's plain hasattr-is-presence
        # reasoning directly: most are argparse CLI options (cli_allowed=True)
        # whose attribute always exists post-parse regardless of whether the
        # value came from CLI, config, or the parser's own default, so
        # hasattr alone doesn't distinguish "provided" from "never touched".
        # What makes forwarding safe here is a table invariant, verified
        # empirically across every CLI block (linear/mesh/disaster/connect):
        # every non-nullable cli_allowed=True scalar OptionSpec has a real
        # (non-None) argparse default, so args.<key> can be None post-merge
        # only if merge_cli_and_config copied an explicit config null onto
        # it. The one violation was "num" (argparse default None, not marked
        # nullable), fixed above by marking it nullable=True — None is num's
        # genuine "no experiment number" state, not a validation error.
        # cli_allowed=False scalars (e.g. cefnetd_timeout) never enter any
        # parser, so for them hasattr IS genuine config-presence evidence —
        # the same mechanism the structured loop below relies on.
        # Nullable keys already tolerate None in validate_config, so
        # forwarding is a no-op for them; non-nullable keys now correctly
        # surface an explicit config null as an error instead of losing it.
        if hasattr(args, key):
            config[key] = getattr(args, key)
    for key in structured_keys:
        # 2026-07-09 bug fix: present-but-empty structured blocks ({} / null /
        # []) must reach validate_config — ADR-0002 requires rejecting
        # failure_scenarios: {} and failure_scenarios: null because they look
        # like unfinished configuration blocks. The old `if val:` truthiness
        # check silently dropped every falsy-but-present value (empty dict,
        # None, empty list) before validate_config ever saw it, so bootstrap
        # exited 0 on a config that should have failed. Presence on args
        # (hasattr) is the correct gate: for the config-only, cli_allowed=False
        # keys, merge_cli_and_config only sets the attribute when the key is
        # actually present in the loaded config file, so hasattr is genuine
        # evidence of presence. The exceptions are bw/ext (CLI append options
        # whose argparse default [] makes the attribute always exist); their
        # empty list validates vacuously, so forwarding it is harmless.
        if hasattr(args, key):
            config[key] = getattr(args, key)

    return validate_config(config)
