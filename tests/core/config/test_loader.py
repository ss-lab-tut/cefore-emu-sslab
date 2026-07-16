"""Tests for src.core.config.loader."""

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.cli.args import (
    add_common_args,
    add_connect_args,
    add_debug_args,
    add_disaster_args,
    add_mesh_args,
)
from src.core.config.validator import config_option_keys
from src.core.config.loader import (
    _FLAT_SPECS,
    OPTION_SPECS,
    load_config,
    merge_cli_and_config,
    validate_config,
    validate_merged_args,
    warn_ignored_legacy_content_keys,
)


# ── load_config ──


def test_load_none_returns_empty():
    assert load_config(None) == {}


def test_load_empty_string_returns_empty():
    assert load_config("") == {}


def test_load_json_file(tmp_path):
    p = tmp_path / "test.json"
    p.write_text('{"hosts": 5}')
    assert load_config(p) == {"hosts": 5}


def test_load_yaml_file(tmp_path):
    p = tmp_path / "test.yaml"
    p.write_text("hosts: 5\nseed: 42\n")
    cfg = load_config(p)
    assert cfg["hosts"] == 5
    assert cfg["seed"] == 42


def test_load_missing_file_exits():
    with pytest.raises(SystemExit, match="config file not found"):
        load_config("/nonexistent/path.json")


def test_load_invalid_json_exits(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{invalid json")
    with pytest.raises(SystemExit, match="failed to parse JSON"):
        load_config(p)


# ── validate_config ──


def test_validate_minimal_valid():
    errors = validate_config({"hosts": 5, "switches": 3})
    assert errors == []


def test_validate_empty_config():
    errors = validate_config({})
    assert errors == []


def test_validate_hosts_below_min():
    errors = validate_config({"hosts": 2})
    assert any("hosts" in e for e in errors)


def test_validate_hosts_non_integer():
    errors = validate_config({"hosts": "five"})
    assert any("hosts" in e for e in errors)


def test_validate_switches_below_min():
    errors = validate_config({"switches": 1})
    assert any("switches" in e for e in errors)


def test_legacy_content_keys_are_not_validated():
    errors = validate_config(
        {
            "puts": "not-a-list",
            "gets": [{"host": "bad", "sub_opts": "bad"}],
            "auto": {"consumers": object()},
        }
    )
    assert not any("puts" in e or "gets" in e or "auto" in e for e in errors)


def test_warn_ignored_legacy_content_keys(capsys):
    warned = warn_ignored_legacy_content_keys(
        {"puts": "bad", "gets": [], "auto": {"bad": object()}}
    )
    captured = capsys.readouterr()
    assert warned is True
    assert "auto" in captured.err
    assert "gets" in captured.err
    assert "puts" in captured.err
    assert "Use events" in captured.err


def test_warn_ignored_legacy_content_keys_noop(capsys):
    warned = warn_ignored_legacy_content_keys({"events": []})
    captured = capsys.readouterr()
    assert warned is False
    assert captured.err == ""


def test_validate_events_invalid_type():
    errors = validate_config({"events": [{"at": 5, "type": "explode"}]})
    assert any("type" in e for e in errors)


def test_validate_events_link_down_nodes():
    errors = validate_config({"events": [{"at": 5, "type": "link_down", "nodes": [1]}]})
    assert any("nodes" in e and "2 elements" in e for e in errors)


def test_validate_events_fib_del_missing_fields():
    errors = validate_config({"events": [{"at": 5, "type": "fib_del"}]})
    assert any("host" in e for e in errors)
    assert any("prefix" in e for e in errors)


def test_validate_cache_config_invalid_strategy():
    errors = validate_config({"cache_config": {"strategy": "nonexistent"}})
    assert any("strategy" in e for e in errors)


def test_validate_cache_config_default_rct_ms():
    errors = validate_config({"cache_config": {"default": {"default_rct_ms": 500}}})
    assert any("default_rct_ms" in e for e in errors)


def test_validate_failure_scenarios_simple():
    errors = validate_config({"failure_scenarios": {"strategy": "simple"}})
    assert any("simple" in e for e in errors)


def test_validate_failure_scenarios_cyclic_no_cycles():
    errors = validate_config({"failure_scenarios": {"strategy": "cyclic"}})
    assert any("cycles" in e for e in errors)


def test_validate_monitoring():
    errors = validate_config({"monitoring": {"interval": -1}})
    assert any("interval" in e for e in errors)


def test_validate_monitoring_targets_invalid_type():
    errors = validate_config({"monitoring": {"targets": [{"type": "nonexistent"}]}})
    assert any("type" in e for e in errors)


def test_validate_bridges_missing_fields():
    errors = validate_config({"bridges": [{}]})
    assert any("switch" in e for e in errors)
    assert any("root_ip" in e for e in errors)
    assert any("local_routes" in e for e in errors)


def test_validate_seed_non_integer():
    errors = validate_config({"seed": "abc"})
    assert any("seed" in e for e in errors)


def test_validate_seed_null_valid():
    errors = validate_config({"seed": None})
    assert not any("seed" in e for e in errors)


def test_validate_k_below_min():
    errors = validate_config({"k": 0})
    assert any("k" in e for e in errors)


def test_validate_host_degree_max_less_than_min():
    errors = validate_config({"host_degree_min": 3, "host_degree_max": 1})
    assert any("host_degree_max" in e for e in errors)


def test_validate_duration_negative():
    errors = validate_config({"duration": -1})
    assert any("duration" in e for e in errors)


def test_validate_no_cli_non_boolean():
    errors = validate_config({"no_cli": "yes"})
    assert any("no_cli" in e for e in errors)


def test_validate_results_json_non_string():
    errors = validate_config({"results_json": 123})
    assert any("results_json" in e for e in errors)


def test_validate_cache_default_rct_ms_too_low():
    errors = validate_config({"cache_default_rct_ms": 500})
    assert any("cache_default_rct_ms" in e for e in errors)


def test_validate_events_valid():
    errors = validate_config(
        {
            "events": [
                {"at": 5, "type": "link_down", "nodes": [1, 2]},
                {
                    "at": 10,
                    "type": "fib_del",
                    "host": 3,
                    "prefix": "ccnx:/test",
                    "next_hop": "192.168.0.1",
                },
            ]
        }
    )
    assert errors == []


def test_validate_failure_scenarios_simple_valid():
    errors = validate_config(
        {
            "failure_scenarios": {
                "strategy": "simple",
                "simple": {"interval": 10, "duration": 5, "count": 2},
            }
        }
    )
    assert errors == []


def test_validate_failure_scenarios_cyclic_valid():
    errors = validate_config(
        {
            "failure_scenarios": {
                "strategy": "cyclic",
                "cycles": [{"interval": 10, "duration": 5, "count": 2}],
            }
        }
    )
    assert errors == []


def test_validate_cache_config_nodes():
    errors = validate_config(
        {
            "cache_config": {
                "nodes": [{"id": [1, 3], "capacity": 1000, "algorithm": "LRU"}]
            }
        }
    )
    assert errors == []


def test_validate_cache_config_invalid_algorithm():
    errors = validate_config({"cache_config": {"default": {"algorithm": "RANDOM"}}})
    assert any("algorithm" in e for e in errors)


def test_validate_monitoring_valid():
    errors = validate_config(
        {
            "monitoring": {
                "interval": 5,
                "targets": [{"type": "cefstatus"}],
            }
        }
    )
    assert errors == []


def test_validate_bridges_valid():
    errors = validate_config(
        {
            "bridges": [
                {
                    "switch": 0,
                    "root_ip": "10.0.0.1/24",
                    "local_routes": "192.168.0.0/16",
                }
            ]
        }
    )
    assert errors == []


def test_validate_example_json():
    example = Path("config/examples/example.json")
    if example.exists():
        cfg = load_config(example)
        errors = validate_config(cfg)
        assert errors == [], f"example.json validation errors: {errors}"


# ── merge_cli_and_config ──


def _make_args(**kwargs):
    defaults = {
        "hosts": None,
        "switches": None,
        "seed": None,
        "k": None,
        "bw": "",
        "ext": "",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_merge_parser():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--hosts", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--switches", type=int, default=None)
    parser.add_argument("--k", type=int, default=None)
    parser.add_argument("--results_json", default=None)
    parser.add_argument("--topo_png", default="default.png")
    parser.add_argument("--bw", default="")
    parser.add_argument("--ext", default="")
    return parser


def test_merge_applies_config_values():
    parser = _make_merge_parser()
    args = parser.parse_args([])
    merge_cli_and_config(args, {"hosts": 10, "seed": 42}, parser)
    assert args.hosts == 10
    assert args.seed == 42


def test_merge_cli_precedence():
    parser = _make_merge_parser()
    args = parser.parse_args(["--hosts", "5"])
    merge_cli_and_config(args, {"hosts": 10}, parser)
    assert args.hosts == 5


def test_merge_cli_precedence_with_parser():
    """When parser is provided, CLI values override config values."""
    parser = _make_merge_parser()

    # CLI sets hosts=5, config has hosts=10 -> CLI wins
    args = parser.parse_args(["--hosts", "5"])
    merge_cli_and_config(args, {"hosts": 10, "seed": 42}, parser=parser)
    assert args.hosts == 5  # CLI wins
    assert args.seed == 42  # config applied (CLI was default)


def test_merge_null_means_default():
    """_NULL_MEANS_DEFAULT keys: config null should not override."""
    parser = _make_merge_parser()

    args = parser.parse_args([])
    merge_cli_and_config(args, {"seed": None, "results_json": None}, parser=parser)
    assert args.seed is None  # null in _NULL_MEANS_DEFAULT -> skip
    assert args.results_json is None


def test_merge_null_means_default_includes_topo_png_from_spec():
    """Nullable OptionSpec entries drive config-null-as-default behavior."""
    parser = _make_merge_parser()

    args = parser.parse_args([])
    merge_cli_and_config(args, {"topo_png": None}, parser=parser)
    assert args.topo_png == "default.png"


def test_merge_bw_string_to_list():
    parser = _make_merge_parser()
    args = _make_args(bw="1,2,10")
    merge_cli_and_config(args, {}, parser)
    assert args.bw == ["1,2,10"]


def test_merge_ext_string_to_list():
    parser = _make_merge_parser()
    args = _make_args(ext="h0,eth1")
    merge_cli_and_config(args, {}, parser)
    assert args.ext == ["h0,eth1"]


def test_merge_cache_config_applied():
    parser = _make_merge_parser()
    args = _make_args()
    merge_cli_and_config(args, {"cache_config": {"strategy": "manual"}}, parser)
    assert args.cache_config == {"strategy": "manual"}


def test_merge_forwarding_config_defaults_to_flooding():
    parser = _make_merge_parser()
    args = _make_args()
    merge_cli_and_config(args, {}, parser)
    assert args.forwarding_config == {"default": "flooding"}


def test_merge_forwarding_config_applied():
    parser = _make_merge_parser()
    args = _make_args()
    config = {
        "forwarding_config": {
            "default": "shortest_path",
            "nodes": [{"id": [1], "strategy": "flooding"}],
        }
    }
    merge_cli_and_config(args, config, parser)
    assert args.forwarding_config == config["forwarding_config"]


# ── additional validate_config coverage ──


def test_validate_host_degree_min_invalid():
    errors = validate_config({"host_degree_min": "three"})
    assert any("host_degree_min" in e for e in errors)


def test_validate_host_degree_min_below_one():
    errors = validate_config({"host_degree_min": 0})
    assert any("host_degree_min" in e for e in errors)


def test_validate_host_degree_max_non_integer():
    errors = validate_config({"host_degree_max": "five"})
    assert any("host_degree_max" in e for e in errors)


def test_validate_host_degree_max_non_integer_emits_once():
    errors = validate_config({"host_degree_max": "two"})
    assert errors.count("host_degree_max must be an integer") == 1


def test_option_specs_are_canonical_source_for_flat_view():
    """The old _FLAT_SPECS view must be derived from the canonical table."""
    flat_keys = [spec.key for spec in _FLAT_SPECS]

    assert "host_degree_max" in flat_keys
    assert "topo_png" in flat_keys
    assert "topo_layout" in flat_keys
    assert OPTION_SPECS["topo_layout"].choices == ("spring", "kamada_kawai", "circular")
    assert OPTION_SPECS["cache_config"].kind == "structured"


def test_forwarding_config_option_spec_excludes_special_merge():
    spec = OPTION_SPECS["forwarding_config"]
    assert spec.kind == "structured"
    assert spec.config_allowed
    assert not spec.cli_allowed
    assert spec.block == ("disaster", "connect")
    assert spec.default == {"default": "flooding"}
    assert spec.special_config_merge
    assert "forwarding_config" not in config_option_keys()


def test_debug_option_specs_match_argparse_identity():
    parser = argparse.ArgumentParser()
    add_debug_args(parser)
    actions = {action.dest: action for action in parser._actions}

    debug_spec = OPTION_SPECS["debug"]
    assert debug_spec.flag == "--debug"
    assert debug_spec.action == "store_true"
    assert debug_spec.cli_allowed
    assert debug_spec.block == ("debug",)
    assert debug_spec.help == actions["debug"].help

    artifact_spec = OPTION_SPECS["debug_artifact"]
    artifact_action = actions["debug_artifact"]
    assert artifact_spec.flag == "--debug-artifact"
    assert artifact_spec.action == "append"
    assert artifact_spec.choices == tuple(artifact_action.choices)
    assert artifact_spec.metavar == artifact_action.metavar
    assert artifact_spec.help == artifact_action.help


def test_config_option_keys_preserves_current_order_and_excludes_special_merge():
    assert config_option_keys() == (
        "hosts",
        "switches",
        "seed",
        "topo_png",
        "topo_layout",
        "k",
        "host_degree_min",
        "host_degree_max",
        "node_per_switch",
        "switch_use_all",
        "num",
        "output_dir",
        "results_json",
        "timestamp",
        "no_cli",
        "no_script_log",
        "duration",
        "cache_default_rct_ms",
        "publisher_host",
        "pubsub_sub_startup_grace",
        "warmup_get_interval",
        "warmup_only_cache_nodes",
        "down_interval",
        "down_duration",
        "down_exclude",
        "down_count",
        "down_stagger",
        "cache_count",
        "bw",
        "ext",
        "bridges",
        "failure_scenarios",
        "events",
        "monitoring",
        "routing",
        "addressing",
        "cefnetd_timeout",
        "warmup_gets",
        "webui_port",
        "script_log",
    )


def test_validate_newly_table_driven_flat_keys():
    cases = [
        ("down_exclude", 123, "down_exclude must be a string"),
        ("topo_png", 123, "topo_png must be a string or null"),
        ("bw", "h1,h2,10", "bw must be a list"),
        ("ext", "h1,eth1,10.0.0.1/24", "ext must be a list"),
        (
            "topo_layout",
            "typo",
            "topo_layout must be one of: spring, kamada_kawai, circular",
        ),
    ]

    for key, value, message in cases:
        assert message in validate_config({key: value})


def test_validate_merged_args_includes_spec_derived_flat_keys():
    args = SimpleNamespace(topo_png=None, topo_layout="typo", bw="bad", ext="bad")

    errors = validate_merged_args(args)

    assert "topo_layout must be one of: spring, kamada_kawai, circular" in errors
    assert "bw must be a list" in errors
    assert "ext must be a list" in errors
    assert not any(error.startswith("topo_png ") for error in errors)


def test_validate_host_degree_max_with_non_int_min():
    """When host_degree_min is non-int, host_degree_max uses default min=1."""
    errors = validate_config({"host_degree_min": "bad", "host_degree_max": 2})
    assert any("host_degree_min" in e for e in errors)
    assert not any("host_degree_max" in e and ">=" in e for e in errors)


def test_validate_host_degree_max_falls_back_when_min_is_not_int():
    errors = validate_config({"host_degree_min": "bad", "host_degree_max": 0})
    assert "host_degree_min must be an integer >= 1" in errors
    assert "host_degree_max must be >= host_degree_min" in errors


def test_validate_switch_use_all_non_boolean():
    errors = validate_config({"switch_use_all": "yes"})
    assert any("switch_use_all" in e for e in errors)


def test_validate_num_below_min():
    errors = validate_config({"num": 0})
    assert any("num" in e for e in errors)


def test_validate_num_non_integer():
    errors = validate_config({"num": "one"})
    assert any("num" in e for e in errors)


def test_validate_output_dir_non_string():
    errors = validate_config({"output_dir": 123})
    assert any("output_dir" in e for e in errors)


def test_validate_timestamp_non_boolean():
    errors = validate_config({"timestamp": "yes"})
    assert any("timestamp" in e for e in errors)


def test_validate_legacy_layout_removed():
    errors = validate_config({"legacy_layout": False})
    assert any("legacy_layout" in e for e in errors)


def test_validate_cache_default_rct_ms_non_integer():
    errors = validate_config({"cache_default_rct_ms": "fast"})
    assert any("cache_default_rct_ms" in e for e in errors)


def test_validate_publisher_host_non_integer():
    errors = validate_config({"publisher_host": "h0"})
    assert any("publisher_host" in e for e in errors)


def test_validate_events_missing_at():
    errors = validate_config({"events": [{"type": "link_down", "nodes": [1, 2]}]})
    assert any("at" in e for e in errors)


def test_validate_events_negative_at():
    errors = validate_config(
        {"events": [{"at": -1, "type": "link_down", "nodes": [1, 2]}]}
    )
    assert any("at" in e for e in errors)


def test_validate_events_missing_type():
    errors = validate_config({"events": [{"at": 5}]})
    assert any("type" in e for e in errors)


def test_validate_events_non_list():
    errors = validate_config({"events": "not_a_list"})
    assert any("events" in e for e in errors)


def test_validate_events_non_dict_entry():
    errors = validate_config({"events": ["not_a_dict"]})
    assert any("events[0]" in e for e in errors)


def test_validate_events_protocol_invalid():
    errors = validate_config(
        {
            "events": [
                {
                    "at": 5,
                    "type": "fib_add",
                    "host": 0,
                    "prefix": "ccnx:/test",
                    "next_hop": "10.0.0.1",
                    "protocol": "tcp",
                }
            ]
        }
    )
    assert any("protocol" in e for e in errors)


def test_validate_cache_config_non_dict():
    errors = validate_config({"cache_config": "bad"})
    assert any("cache_config" in e for e in errors)


def test_validate_cache_config_default_non_dict():
    errors = validate_config({"cache_config": {"default": "bad"}})
    assert any("default" in e and "dict" in e for e in errors)


def test_validate_cache_config_default_count_negative():
    errors = validate_config({"cache_config": {"default": {"count": -1}}})
    assert any("count" in e for e in errors)


def test_validate_cache_config_default_capacity_negative():
    errors = validate_config({"cache_config": {"default": {"capacity": -1}}})
    assert any("capacity" in e for e in errors)


def test_validate_cache_config_default_type_invalid():
    errors = validate_config({"cache_config": {"default": {"type": "redis"}}})
    assert any("type" in e for e in errors)


def test_validate_cache_config_nodes_non_list():
    errors = validate_config({"cache_config": {"nodes": "bad"}})
    assert any("nodes" in e for e in errors)


def test_validate_cache_config_nodes_non_dict_entry():
    errors = validate_config({"cache_config": {"nodes": ["bad"]}})
    assert any("nodes[0]" in e for e in errors)


def test_validate_cache_config_nodes_id_invalid():
    errors = validate_config({"cache_config": {"nodes": [{"id": "bad"}]}})
    assert any("id" in e for e in errors)


def test_validate_cache_config_nodes_capacity_negative():
    errors = validate_config({"cache_config": {"nodes": [{"id": 1, "capacity": -1}]}})
    assert any("capacity" in e for e in errors)


def test_validate_cache_config_nodes_rct_ms_low():
    errors = validate_config(
        {"cache_config": {"nodes": [{"id": 1, "default_rct_ms": 500}]}}
    )
    assert any("default_rct_ms" in e for e in errors)


def test_validate_cache_config_nodes_algorithm_invalid():
    errors = validate_config(
        {"cache_config": {"nodes": [{"id": 1, "algorithm": "RANDOM"}]}}
    )
    assert any("algorithm" in e for e in errors)


def test_validate_cache_config_nodes_type_invalid():
    errors = validate_config({"cache_config": {"nodes": [{"id": 1, "type": "redis"}]}})
    assert any("type" in e for e in errors)


@pytest.mark.parametrize(
    ("config", "expected_error"),
    [
        ({"forwarding_config": None}, "forwarding_config must be a dict"),
        ({"forwarding_config": {}}, "forwarding_config must not be empty"),
        (
            {"forwarding_config": {"default": "invalid"}},
            "forwarding_config.default must be one of: default, flooding, shortest_path",
        ),
        (
            {"forwarding_config": {"nodes": [{"id": "h1", "strategy": "flooding"}]}},
            "forwarding_config.nodes[0].id must be a list of integers",
        ),
        (
            {"forwarding_config": {"nodes": [{"id": [1]}]}},
            "forwarding_config.nodes[0].strategy is required",
        ),
    ],
)
def test_validate_forwarding_config(config, expected_error):
    assert expected_error in validate_config(config)


def test_validate_forwarding_config_valid():
    assert (
        validate_config(
            {
                "forwarding_config": {
                    "default": "flooding",
                    "nodes": [{"id": [1, 2], "strategy": "shortest_path"}],
                }
            }
        )
        == []
    )


def test_validate_failure_scenarios_non_dict():
    errors = validate_config({"failure_scenarios": "bad"})
    assert any("failure_scenarios" in e for e in errors)


def test_validate_failure_scenarios_invalid_strategy():
    errors = validate_config({"failure_scenarios": {"strategy": "invalid"}})
    assert any("strategy" in e for e in errors)


def test_validate_failure_scenarios_simple_non_dict():
    errors = validate_config(
        {"failure_scenarios": {"strategy": "simple", "simple": "bad"}}
    )
    assert any("simple" in e and "dict" in e for e in errors)


def test_validate_failure_scenarios_simple_count_negative():
    errors = validate_config(
        {"failure_scenarios": {"strategy": "simple", "simple": {"count": -1}}}
    )
    assert any("count" in e for e in errors)


def test_validate_failure_scenarios_simple_stagger_negative():
    errors = validate_config(
        {"failure_scenarios": {"strategy": "simple", "simple": {"stagger": -1}}}
    )
    assert any("stagger" in e for e in errors)


def test_validate_failure_scenarios_simple_exclude_invalid():
    errors = validate_config(
        {"failure_scenarios": {"strategy": "simple", "simple": {"exclude": "bad"}}}
    )
    assert any("exclude" in e for e in errors)


def test_validate_failure_scenarios_simple_interval_non_integer():
    errors = validate_config(
        {"failure_scenarios": {"strategy": "simple", "simple": {"interval": "slow"}}}
    )
    assert any("interval" in e for e in errors)


def test_validate_failure_scenarios_simple_duration_null():
    errors = validate_config(
        {"failure_scenarios": {"strategy": "simple", "simple": {"duration": None}}}
    )
    assert any("duration" in e and "must not be null" in e for e in errors)


def test_validate_failure_scenarios_cyclic_non_list():
    errors = validate_config(
        {"failure_scenarios": {"strategy": "cyclic", "cycles": "bad"}}
    )
    assert any("cycles" in e and "list" in e for e in errors)


def test_validate_failure_scenarios_cyclic_empty():
    errors = validate_config(
        {"failure_scenarios": {"strategy": "cyclic", "cycles": []}}
    )
    assert any("at least one cycle" in e for e in errors)


def test_validate_failure_scenarios_cyclic_entry_non_dict():
    errors = validate_config(
        {"failure_scenarios": {"strategy": "cyclic", "cycles": ["bad"]}}
    )
    assert any("cycles[0]" in e for e in errors)


def test_validate_failure_scenarios_cyclic_entry_fields():
    errors = validate_config(
        {
            "failure_scenarios": {
                "strategy": "cyclic",
                "cycles": [
                    {
                        "interval": "slow",
                        "count": -1,
                        "stagger": -1,
                        "exclude": "bad",
                        "target": "bad",
                        "allow_publishers": "yes",
                    }
                ],
            }
        }
    )
    assert any("interval" in e for e in errors)
    assert any("count" in e for e in errors)
    assert any("stagger" in e for e in errors)
    assert any("exclude" in e for e in errors)
    assert any("target" in e for e in errors)
    assert any("allow_publishers" in e for e in errors)


def test_validate_failure_scenarios_cyclic_interval_duration_null():
    errors = validate_config(
        {
            "failure_scenarios": {
                "strategy": "cyclic",
                "cycles": [{"interval": None, "duration": None}],
            }
        }
    )

    assert errors == [
        "failure_scenarios.cycles[0].interval must not be null",
        "failure_scenarios.cycles[0].duration must not be null",
    ]


def test_validate_monitoring_non_dict():
    errors = validate_config({"monitoring": "bad"})
    assert any("monitoring" in e for e in errors)


def test_validate_monitoring_targets_non_list():
    errors = validate_config({"monitoring": {"targets": "bad"}})
    assert any("targets" in e for e in errors)


def test_validate_monitoring_targets_non_dict_entry():
    errors = validate_config({"monitoring": {"targets": ["bad"]}})
    assert any("targets[0]" in e for e in errors)


def test_validate_monitoring_targets_missing_type():
    errors = validate_config({"monitoring": {"targets": [{}]}})
    assert any("type" in e for e in errors)


def test_validate_bridges_non_list():
    errors = validate_config({"bridges": "bad"})
    assert any("bridges" in e for e in errors)


def test_validate_bridges_non_dict_entry():
    errors = validate_config({"bridges": ["bad"]})
    assert any("bridges[0]" in e for e in errors)


def test_validate_bridges_local_routes_non_string():
    errors = validate_config(
        {"bridges": [{"switch": 0, "root_ip": "10.0.0.1/24", "local_routes": 123}]}
    )
    assert any("local_routes" in e for e in errors)


def test_validate_bridges_nat_non_boolean():
    errors = validate_config(
        {
            "bridges": [
                {
                    "switch": 0,
                    "root_ip": "10.0.0.1/24",
                    "local_routes": "192.168.0.0/16",
                    "nat": "yes",
                }
            ]
        }
    )
    assert any("nat" in e for e in errors)


def test_validate_bridges_nat_out_non_string():
    errors = validate_config(
        {
            "bridges": [
                {
                    "switch": 0,
                    "root_ip": "10.0.0.1/24",
                    "local_routes": "192.168.0.0/16",
                    "nat_out": 123,
                }
            ]
        }
    )
    assert any("nat_out" in e for e in errors)


def test_validate_bridges_root_ip_bare_rejected():
    errors = validate_config(
        {
            "bridges": [
                {"switch": 0, "root_ip": "10.0.0.1", "local_routes": "192.168.0.0/16"}
            ]
        }
    )
    assert any("root_ip" in e and "CIDR" in e for e in errors)


def test_validate_bridges_root_ip_auto_accepted():
    errors = validate_config(
        {
            "bridges": [
                {"switch": 0, "root_ip": "auto", "local_routes": "192.168.0.0/16"}
            ]
        }
    )
    assert not any("root_ip" in e for e in errors)


def test_validate_bridges_root_ip_cidr_accepted():
    errors = validate_config(
        {
            "bridges": [
                {
                    "switch": 0,
                    "root_ip": "10.0.0.1/24",
                    "local_routes": "192.168.0.0/16",
                }
            ]
        }
    )
    assert not any("root_ip" in e for e in errors)


def test_validate_bridges_root_ip_invalid_cidr_rejected():
    errors = validate_config(
        {
            "bridges": [
                {
                    "switch": 0,
                    "root_ip": "999.999.999.999/24",
                    "local_routes": "192.168.0.0/16",
                }
            ]
        }
    )
    assert any("root_ip" in e for e in errors)


def test_validate_bridges_root_ip_non_string_rejected():
    errors = validate_config(
        {"bridges": [{"switch": 0, "root_ip": None, "local_routes": "192.168.0.0/16"}]}
    )
    assert any("root_ip" in e for e in errors)


def test_validate_merged_args_bridges_bare_root_ip_rejected():
    args = SimpleNamespace(
        bridges=[{"switch": 0, "root_ip": "10.0.0.1", "local_routes": "192.168.0.0/16"}]
    )
    errors = validate_merged_args(args)
    assert any("root_ip" in e and "CIDR" in e for e in errors)


def test_validate_script_log_non_string():
    errors = validate_config({"script_log": 123})
    assert any("script_log" in e for e in errors)


def test_validate_no_script_log_non_boolean():
    errors = validate_config({"no_script_log": "yes"})
    assert any("no_script_log" in e for e in errors)


# ---------------------------------------------------------------------------
# addressing block validation
# ---------------------------------------------------------------------------


def test_validate_addressing_valid():
    errors = validate_config({"addressing": {"network_cidr": "192.168.0.0/16"}})
    assert errors == []


def test_validate_addressing_custom_base():
    errors = validate_config({"addressing": {"network_cidr": "172.20.0.0/16"}})
    assert errors == []


def test_validate_addressing_not_dict():
    errors = validate_config({"addressing": "192.168.0.0/16"})
    assert any("addressing" in e and "dict" in e for e in errors)


def test_validate_addressing_network_cidr_not_string():
    errors = validate_config({"addressing": {"network_cidr": 123}})
    assert any("network_cidr" in e and "string" in e for e in errors)


def test_validate_addressing_invalid_cidr():
    errors = validate_config({"addressing": {"network_cidr": "not-a-cidr"}})
    assert any("network_cidr" in e for e in errors)


def test_validate_addressing_wrong_prefix_slash8():
    errors = validate_config({"addressing": {"network_cidr": "10.0.0.0/8"}})
    assert any("network_cidr" in e and "/16" in e for e in errors)


def test_validate_addressing_wrong_prefix_slash24():
    errors = validate_config({"addressing": {"network_cidr": "192.168.1.0/24"}})
    assert any("network_cidr" in e and "/16" in e for e in errors)


def test_validate_addressing_empty_dict():
    # No network_cidr specified — valid (optional field)
    errors = validate_config({"addressing": {}})
    assert errors == []


# ---------------------------------------------------------------------------
# cache_config.strategy=random validation
# ---------------------------------------------------------------------------


def test_validate_cache_config_strategy_random_accepted():
    errors = validate_config({"cache_config": {"strategy": "random"}})
    assert not any("strategy" in e for e in errors)


def test_validate_cache_config_strategy_k_centers_accepted():
    errors = validate_config({"cache_config": {"strategy": "k_centers"}})
    assert not any("strategy" in e for e in errors)


def test_validate_cache_config_strategy_invalid_rejected():
    errors = validate_config({"cache_config": {"strategy": "invalid"}})
    assert any("strategy" in e for e in errors)


def test_validate_merged_args_cache_config_strategy_random():
    args = SimpleNamespace(cache_config={"strategy": "random"})
    errors = validate_merged_args(args)
    assert not any("strategy" in e for e in errors)


# ---------------------------------------------------------------------------
# validate_merged_args structured-key presence vs. truthiness (B1)
#
# 2026-07-09 bug fix: validate_merged_args used to gate structured-key
# inclusion on truthiness (`if val:`), so a present-but-empty block ({} /
# null / []) was silently dropped before ever reaching validate_config.
# ADR-0002 requires failure_scenarios: {} and failure_scenarios: null to be
# validation errors (they look like unfinished config), while omission and
# present-but-empty events/bridges lists must stay clean.
# ---------------------------------------------------------------------------


def test_validate_merged_args_failure_scenarios_omitted_no_error():
    """Genuinely omitted failure_scenarios (attribute absent on args) is inert."""
    args = SimpleNamespace(hosts=3)
    assert validate_merged_args(args) == []


def test_validate_merged_args_failure_scenarios_empty_dict_is_error():
    """Regression test for the B1 bug: {} must reach _validate_failure_scenarios.

    Before the fix this was silently dropped by the `if val:` truthiness
    check (empty dict is falsy), so bootstrap exited 0 despite an unfinished
    failure_scenarios block.
    """
    args = SimpleNamespace(failure_scenarios={})
    errors = validate_merged_args(args)
    assert "failure_scenarios with strategy 'simple' requires 'simple' block" in errors


def test_validate_merged_args_failure_scenarios_null_is_error():
    """null is likewise present-but-empty and must be rejected, not dropped."""
    args = SimpleNamespace(failure_scenarios=None)
    errors = validate_merged_args(args)
    assert "failure_scenarios must be a dict" in errors


def test_validate_merged_args_events_empty_list_not_newly_flagged():
    """events: [] is a legitimate present-but-empty value, not an error.

    _validate_events treats an empty list as zero events to iterate over, so
    presence-based inclusion must not manufacture a new false positive here.
    """
    args = SimpleNamespace(events=[])
    assert validate_merged_args(args) == []


def test_validate_merged_args_bridges_empty_list_not_newly_flagged():
    """bridges: [] is likewise a no-op for _validate_bridges, not an error."""
    args = SimpleNamespace(bridges=[])
    assert validate_merged_args(args) == []


def test_validate_merged_args_debug_excluded_from_structured_presence_fix():
    """debug has its own special_config_merge carve-out (loader.py skips it
    entirely during merge) and is excluded from both scalar_option_keys() and
    structured_option_keys(), so the B1 presence fix must not start pulling
    the CLI-only args.debug attribute into merged-args validation.
    """
    args = SimpleNamespace(debug=False)
    assert validate_merged_args(args) == []


# ---------------------------------------------------------------------------
# validate_merged_args scalar-key presence vs. truthiness (B3)
#
# 2026-07-09 bug fix (audit follow-up to 73ca40b): validate_merged_args's
# scalar loop gated inclusion on `val is not None or key in nullable_keys`,
# so a present None for a NON-nullable scalar (e.g. "hosts: null" in YAML)
# was silently dropped before validate_config ever saw it — bootstrap exited
# 0 on a config validate_config({"hosts": None}) rejects outright. Fixing
# this required first clearing a false-positive trap: unlike structured
# keys, most scalar keys are argparse CLI options whose attribute always
# exists post-parse, so None can also mean "never touched" rather than
# "explicit config null". "num" was the one non-nullable scalar with an
# argparse default of None; it is now marked nullable=True (None is its
# genuine "no experiment number" state) so the loop's forwarding invariant
# holds for every other non-nullable scalar.
# ---------------------------------------------------------------------------


def test_validate_merged_args_hosts_omitted_no_error():
    """Genuinely omitted hosts (attribute absent on args) is inert."""
    args = SimpleNamespace(switches=4)
    assert validate_merged_args(args) == []


def test_validate_merged_args_hosts_null_is_error():
    """Regression test for the B3 bug: a present None for a non-nullable
    scalar must reach validate_config, not be silently dropped.

    Before the fix this was gated out by `val is not None`, so bootstrap
    exited 0 despite "hosts: null" — a config validate_config itself rejects.
    """
    args = SimpleNamespace(hosts=None)
    errors = validate_merged_args(args)
    assert "hosts must be an integer >= 3" in errors


def test_validate_merged_args_switches_null_is_error():
    """Second non-nullable scalar pin, distinct from hosts."""
    args = SimpleNamespace(switches=None)
    errors = validate_merged_args(args)
    assert "switches must be an integer >= 2" in errors


def test_validate_merged_args_seed_null_not_newly_flagged():
    """seed is a genuinely nullable scalar; null must stay error-free.

    Pins that nullable scalars are unaffected by dropping the old
    `or key in nullable_keys` clause — validate_config already tolerates
    None for every nullable key, so unconditional forwarding is a no-op.
    """
    args = SimpleNamespace(seed=None)
    assert validate_merged_args(args) == []


def test_validate_merged_args_num_null_not_newly_flagged():
    """num is the one non-nullable-looking scalar with an argparse default
    of None (no --num flag ever produces args.num=None). It is marked
    nullable=True precisely so this loop's forwarding does not manufacture
    a false positive for the ordinary "no experiment number" run.
    """
    args = SimpleNamespace(num=None)
    assert validate_merged_args(args) == []


@pytest.mark.parametrize(
    "build_parser",
    [
        lambda p: (add_common_args(p), add_mesh_args(p), add_disaster_args(p)),
        lambda p: add_connect_args(p),
    ],
    ids=["disaster", "connect"],
)
def test_validate_merged_args_no_flags_no_config_is_clean(build_parser):
    """The most important regression guard: a plain CLI parse with no flags
    merged against an empty config must validate cleanly for every scalar
    key.  This is the false-positive trap the B3 fix had to avoid — if any
    non-nullable scalar had an argparse default of None (as "num" did before
    being marked nullable), unconditional forwarding here would break every
    default run across both CLI entry points.
    """
    parser = argparse.ArgumentParser()
    add_debug_args(parser)
    build_parser(parser)
    args = parser.parse_args([])

    assert validate_merged_args(args) == []


# ---------------------------------------------------------------------------
# monitoring.targets.target_host validation
# ---------------------------------------------------------------------------


def test_validate_monitoring_target_host_valid():
    errors = validate_config(
        {
            "monitoring": {
                "targets": [{"type": "csmgrstatus", "target_host": "192.168.1.1"}]
            }
        }
    )
    assert errors == []


def test_validate_monitoring_target_host_empty_string():
    errors = validate_config(
        {"monitoring": {"targets": [{"type": "csmgrstatus", "target_host": ""}]}}
    )
    assert any("target_host" in e for e in errors)


def test_validate_monitoring_target_host_non_string():
    errors = validate_config(
        {"monitoring": {"targets": [{"type": "csmgrstatus", "target_host": 12345}]}}
    )
    assert any("target_host" in e for e in errors)


@pytest.mark.parametrize(
    "config",
    [
        {"hosts": True},
        {"duration": False},
        {"cefnetd_timeout": True},
        {"monitoring": {"interval": True}},
        {"events": [{"at": True, "type": "get", "host": 0, "uri": "ccnx:/x"}]},
        {"events": [{"at": 0, "type": "bw_set", "nodes": [0, 1], "bandwidth": True}]},
        {"events": [{"at": 0, "type": "get", "host": True, "uri": "ccnx:/x"}]},
        {
            "events": [
                {"at": 0, "type": "get", "host": 0, "uri": "ccnx:/x", "pipeline": True}
            ]
        },
    ],
)
def test_validate_numeric_fields_reject_booleans(config):
    assert validate_config(config)


def test_validate_event_content_options():
    errors = validate_config(
        {
            "events": [
                {
                    "at": 0,
                    "type": "put",
                    "host": 2,
                    "uri": "ccnx:/put",
                    "file": "./sample-putfile",
                    "valid_algo": "sha1",
                    "expiry": True,
                },
                {
                    "at": 0,
                    "type": "get",
                    "host": 0,
                    "uri": "ccnx:/put",
                    "owner_only": "yes",
                    "sg": 1,
                },
                {
                    "at": 0,
                    "type": "pubsub_pub",
                    "host": 2,
                    "uri": "ccnx:/live",
                    "file": "./sample-putfile",
                    "pub_opts": {"lifetime": True, "target": "wrong"},
                },
                {
                    "at": 0,
                    "type": "pubsub_sub",
                    "host": 0,
                    "uri": "ccnx:/live",
                    "sub_opts": {"wait": False, "ri_valid_algo": "sha1"},
                },
            ]
        }
    )
    assert any("valid_algo" in error for error in errors)
    assert any("expiry" in error for error in errors)
    assert any("owner_only" in error for error in errors)
    assert any("sg" in error for error in errors)
    assert any("lifetime" in error for error in errors)
    assert any("target" in error for error in errors)
    assert any("wait" in error for error in errors)


def test_validate_autotest_rejects_repeated_put_event():
    errors = validate_config(
        {
            "no_cli": True,
            "results_json": "results.json",
            "events": [
                {
                    "at": 0,
                    "type": "put",
                    "host": 2,
                    "uri": "ccnx:/test",
                    "file": "./sample-putfile",
                    "repeat": {"interval": 1},
                }
            ],
        }
    )
    assert any("not supported for autotest put" in error for error in errors)


# ── table-driven flat-key boundary tests ──


def test_cefnetd_timeout_zero_rejected():
    errors = validate_config({"cefnetd_timeout": 0})
    assert any("cefnetd_timeout" in e for e in errors)


def test_cefnetd_timeout_none_rejected():
    errors = validate_config({"cefnetd_timeout": None})
    assert any("cefnetd_timeout" in e for e in errors)


def test_seed_null_accepted():
    errors = validate_config({"seed": None})
    assert not any("seed" in e for e in errors)


def test_hosts_bool_rejected():
    errors = validate_config({"hosts": True})
    assert any("hosts" in e for e in errors)


# ── parametrized invalid-value test from _FLAT_SPECS ──


@pytest.mark.parametrize(
    "spec",
    _FLAT_SPECS,
    ids=[s.key for s in _FLAT_SPECS],
)
def test_flat_spec_rejects_invalid_value(spec):
    if spec.kind == "int":
        bad = "not_an_int"
    elif spec.kind == "number":
        bad = "not_a_number"
    elif spec.kind == "bool":
        bad = "not_a_bool"
    elif spec.kind == "str":
        bad = 12345
    else:
        bad = object()
    errors = validate_config({spec.key: bad})
    assert any(spec.key in e for e in errors), f"no error for {spec.key}={bad!r}"


def test_flat_key_message_int_with_min():
    errors = validate_config({"hosts": "bad"})
    assert "hosts must be an integer >= 3" in errors


def test_flat_key_message_nullable_int():
    errors = validate_config({"seed": "bad"})
    assert "seed must be an integer or null" in errors


def test_flat_key_message_nullable_int_with_min():
    errors = validate_config({"cache_default_rct_ms": 500})
    assert "cache_default_rct_ms must be an integer >= 1000 or null" in errors


def test_flat_key_message_bool():
    errors = validate_config({"timestamp": "bad"})
    assert "timestamp must be a boolean" in errors


def test_flat_key_message_nullable_str():
    errors = validate_config({"results_json": 123})
    assert "results_json must be a string or null" in errors


def test_flat_key_message_int_no_min():
    errors = validate_config({"host_degree_min": "bad"})
    assert "host_degree_min must be an integer >= 1" in errors


_SPECS_WITH_MIN = [
    s for s in _FLAT_SPECS if s.minimum is not None and s.kind in ("int", "number")
]
_NULLABLE_SPECS = [s for s in _FLAT_SPECS if s.nullable]


@pytest.mark.parametrize("spec", _SPECS_WITH_MIN, ids=[s.key for s in _SPECS_WITH_MIN])
def test_flat_spec_rejects_below_minimum(spec):
    below = spec.minimum - 1 if spec.kind == "int" else spec.minimum - 0.001
    errors = validate_config({spec.key: below})
    assert any(spec.key in e for e in errors), f"no error for {spec.key}={below}"


@pytest.mark.parametrize("spec", _SPECS_WITH_MIN, ids=[s.key for s in _SPECS_WITH_MIN])
def test_flat_spec_accepts_at_minimum(spec):
    at_min = spec.minimum if spec.kind == "int" else float(spec.minimum)
    errors = validate_config({spec.key: at_min})
    assert not any(spec.key in e for e in errors), (
        f"unexpected error for {spec.key}={at_min}"
    )


@pytest.mark.parametrize("spec", _NULLABLE_SPECS, ids=[s.key for s in _NULLABLE_SPECS])
def test_flat_spec_accepts_null(spec):
    errors = validate_config({spec.key: None})
    assert not any(spec.key in e for e in errors), (
        f"unexpected error for {spec.key}=None"
    )


def test_no_scalar_spec_reintroduces_argparse_none_default_trap():
    """Pin the invariant validate_merged_args's scalar presence-forwarding relies on.

    A scalar OptionSpec that is config_allowed + cli_allowed + non-nullable
    with default None would make args.<key> None on every plain no-flag run,
    indistinguishable from an explicit config null — and the scalar loop
    would flag every default run as invalid. "num" was the one historical
    violation (fixed by nullable=True in d2680b1); this test keeps the
    combination from ever coming back.
    """
    from src.core.config.validator import OPTION_SPECS, scalar_option_keys

    offenders = [
        key
        for key in scalar_option_keys()
        if OPTION_SPECS[key].config_allowed
        and OPTION_SPECS[key].cli_allowed
        and not OPTION_SPECS[key].nullable
        and OPTION_SPECS[key].default is None
    ]
    assert offenders == [], (
        f"scalar OptionSpecs reintroduce the argparse-None-default trap: {offenders}"
    )


# ── compute_call event validation ──


def _compute_event(**overrides):
    """Minimal valid compute_call event, with overrides applied on top."""
    event = {
        "at": 0,
        "type": "compute_call",
        "host": 0,
        "endpoint": "http://edge.local/process",
    }
    event.update(overrides)
    return event


def _compute_errors(**overrides):
    """validate_config errors for one compute_call event built by _compute_event."""
    return validate_config({"hosts": 5, "events": [_compute_event(**overrides)]})


def test_compute_call_minimal_is_valid():
    """host+endpoint alone is a complete, valid compute_call."""
    assert _compute_errors() == []


def test_compute_call_payload_must_be_string():
    """payload passes to curl -d verbatim; non-strings fail at config time."""
    assert any(".payload" in e for e in _compute_errors(payload=123))


def test_compute_call_output_file_must_be_string():
    """output_file resolves under run_dir; non-strings fail at config time."""
    assert any(".output_file" in e for e in _compute_errors(output_file=1))


def test_compute_call_publish_uri_must_be_string():
    """publish_uri names the republish target; non-strings fail early."""
    assert any(
        ".publish_uri" in e
        for e in _compute_errors(publish_uri=5, output_file="out.json")
    )


def test_compute_call_headers_must_be_str_to_str_dict():
    """headers expand to curl -H \"k: v\"; both keys and values must be str."""
    assert any(".headers" in e for e in _compute_errors(headers="Accept: x"))
    assert any(".headers" in e for e in _compute_errors(headers={1: "x"}))
    assert any(".headers" in e for e in _compute_errors(headers={"Accept": 2}))
    assert _compute_errors(headers={"Accept": "application/json"}) == []


def test_compute_call_publish_uri_requires_output_file():
    """cefputfile needs a saved response body; publish_uri without
    output_file can never publish anything and must fail at config time."""
    errors = _compute_errors(publish_uri="ccnx:/compute/r1")
    assert any("publish_uri" in e and "output_file" in e for e in errors)
    assert _compute_errors(
        publish_uri="ccnx:/compute/r1", output_file="out.json"
    ) == []


def test_compute_call_pub_opts_validated_like_pubsub_pub():
    """pub_opts carries cefputfile options and is bound-checked as such."""
    assert any(".pub_opts" in e for e in _compute_errors(pub_opts="bad"))
    assert any(
        ".pub_opts.expiry" in e
        for e in _compute_errors(pub_opts={"expiry": 0})
    )
    assert any(
        ".pub_opts.valid_algo" in e
        for e in _compute_errors(pub_opts={"valid_algo": "bogus"})
    )
    assert _compute_errors(
        pub_opts={"expiry": 5000, "cache_time": 2500, "block_size": 1024}
    ) == []


def test_compute_call_pub_opts_block_size_shares_put_minimum():
    """cefputfile requires block_size >= 60; compute's republish uses the
    same binary, so the same boundary must hold (review fix 2026-07-16)."""
    assert any(
        ".pub_opts.block_size" in e
        for e in _compute_errors(pub_opts={"block_size": 59})
    )
    assert _compute_errors(pub_opts={"block_size": 60}) == []


def test_compute_call_pub_opts_rejects_unknown_and_cefpubfile_keys():
    """Keys compute_client never forwards (cefpubfile-only or typos) must
    fail at config time instead of being silently dropped."""
    for key in ("lifetime", "retry_limit", "target", "bogus"):
        assert any(
            ".pub_opts" in e and key in e
            for e in _compute_errors(pub_opts={key: 1})
        ), f"unknown pub_opts key {key!r} was accepted"


def test_compute_call_pub_opts_falsy_non_dict_rejected():
    """A falsy non-dict ([], false, 0, \"\") must not coerce to {} and
    bypass the dict type check."""
    for bad in ([], False, 0, ""):
        assert any(
            ".pub_opts must be a dict" in e
            for e in _compute_errors(pub_opts=bad)
        ), f"pub_opts={bad!r} was accepted"


def test_compute_call_repeat_forbids_restore_forms():
    """compute_call repeat allows interval/count only: a restore/restore_type
    event is synthesized at runtime by merging dicts, bypassing both this
    validator and the pre-run conditional-publication (FIB) extraction — a
    restored publish_uri would publish content no consumer can reach. Compute
    has no natural "restore" semantics, so the forms are rejected outright
    (2026-07-16 audit fix)."""
    ok = {"interval": 5, "count": 2}
    assert _compute_errors(repeat=ok) == []
    for bad in (
        {"interval": 5, "duration": 10},
        {"interval": 5, "duration": 10, "restore": {"host": 2}},
        {"interval": 5, "duration": 10, "restore_type": "compute_call"},
    ):
        errors = _compute_errors(repeat=bad)
        assert any(
            ".repeat" in e and "compute_call" in e for e in errors
        ), f"repeat={bad!r} was accepted"


def test_compute_call_pub_opts_mixed_type_unknown_keys_report_not_crash():
    """A pub_opts dict with non-string keys must produce a validation error,
    not a TypeError from sorting mixed key types (2026-07-16 audit fix)."""
    errors = _compute_errors(pub_opts={1: 2, "bogus": 3})
    assert any(".pub_opts" in e and "unsupported keys" in e for e in errors)


def test_compute_call_repeat_rejects_unknown_keys():
    """compute_call repeat is an interval/count allowlist; unknown keys
    (typos or unsupported forms) must fail rather than be silently ignored
    (2026-07-16 audit fix)."""
    errors = _compute_errors(repeat={"interval": 5, "bogus": 1})
    assert any(".repeat" in e and "bogus" in e for e in errors)


def test_compute_call_publish_timeout_must_be_positive_number():
    """publish_timeout bounds the cefputfile run independently of the HTTP
    timeout (2026-07-16 audit fix: slow-rate publications outlive it)."""
    assert any(".publish_timeout" in e for e in _compute_errors(publish_timeout=0))
    assert any(".publish_timeout" in e for e in _compute_errors(publish_timeout="x"))
    assert _compute_errors(publish_timeout=300) == []
