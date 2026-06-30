"""Tests for src.core.config.loader."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.config.loader import (
    _FLAT_SPECS,
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
    errors = validate_config({
        "monitoring": {"interval": -1}
    })
    assert any("interval" in e for e in errors)


def test_validate_monitoring_targets_invalid_type():
    errors = validate_config({
        "monitoring": {"targets": [{"type": "nonexistent"}]}
    })
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
    errors = validate_config({
        "events": [
            {"at": 5, "type": "link_down", "nodes": [1, 2]},
            {"at": 10, "type": "fib_del", "host": 3, "prefix": "ccnx:/test", "next_hop": "192.168.0.1"},
        ]
    })
    assert errors == []


def test_validate_failure_scenarios_simple_valid():
    errors = validate_config({
        "failure_scenarios": {
            "strategy": "simple",
            "simple": {"interval": 10, "duration": 5, "count": 2},
        }
    })
    assert errors == []


def test_validate_failure_scenarios_cyclic_valid():
    errors = validate_config({
        "failure_scenarios": {
            "strategy": "cyclic",
            "cycles": [{"interval": 10, "duration": 5, "count": 2}],
        }
    })
    assert errors == []


def test_validate_cache_config_nodes():
    errors = validate_config({
        "cache_config": {
            "nodes": [{"id": [1, 3], "capacity": 1000, "algorithm": "LRU"}]
        }
    })
    assert errors == []


def test_validate_cache_config_invalid_algorithm():
    errors = validate_config({
        "cache_config": {"default": {"algorithm": "RANDOM"}}
    })
    assert any("algorithm" in e for e in errors)


def test_validate_monitoring_valid():
    errors = validate_config({
        "monitoring": {
            "interval": 5,
            "targets": [{"type": "cefstatus"}],
        }
    })
    assert errors == []


def test_validate_bridges_valid():
    errors = validate_config({
        "bridges": [{"switch": 0, "root_ip": "10.0.0.1/24", "local_routes": "192.168.0.0/16"}]
    })
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
        "hosts": None, "switches": None, "seed": None, "k": None,
        "bw": "", "ext": "",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_merge_applies_config_values():
    args = _make_args()
    merge_cli_and_config(args, {"hosts": 10, "seed": 42})
    assert args.hosts == 10
    assert args.seed == 42


def test_merge_cli_precedence():
    args = _make_args(hosts=5)
    merge_cli_and_config(args, {"hosts": 10})
    # Without parser, config always overwrites
    assert args.hosts == 10


def test_merge_cli_precedence_with_parser():
    """When parser is provided, CLI values override config values."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--hosts", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--switches", type=int, default=None)
    parser.add_argument("--k", type=int, default=None)
    parser.add_argument("--bw", default="")
    parser.add_argument("--ext", default="")

    # CLI sets hosts=5, config has hosts=10 -> CLI wins
    args = parser.parse_args(["--hosts", "5"])
    merge_cli_and_config(args, {"hosts": 10, "seed": 42}, parser=parser)
    assert args.hosts == 5  # CLI wins
    assert args.seed == 42  # config applied (CLI was default)


def test_merge_null_means_default():
    """_NULL_MEANS_DEFAULT keys: config null should not override."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--results_json", default=None)
    parser.add_argument("--bw", default="")
    parser.add_argument("--ext", default="")

    args = parser.parse_args([])
    merge_cli_and_config(args, {"seed": None, "results_json": None}, parser=parser)
    assert args.seed is None  # null in _NULL_MEANS_DEFAULT -> skip
    assert args.results_json is None


def test_merge_bw_string_to_list():
    args = _make_args(bw="1,2,10")
    merge_cli_and_config(args, {})
    assert args.bw == ["1,2,10"]


def test_merge_ext_string_to_list():
    args = _make_args(ext="h0,eth1")
    merge_cli_and_config(args, {})
    assert args.ext == ["h0,eth1"]


def test_merge_cache_config_applied():
    args = _make_args()
    merge_cli_and_config(args, {"cache_config": {"strategy": "manual"}})
    assert args.cache_config == {"strategy": "manual"}


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


def test_validate_host_degree_max_with_non_int_min():
    """When host_degree_min is non-int, host_degree_max uses default min=1."""
    errors = validate_config({"host_degree_min": "bad", "host_degree_max": 2})
    assert any("host_degree_min" in e for e in errors)
    assert not any("host_degree_max" in e and ">=" in e for e in errors)


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
    errors = validate_config({"events": [{"at": -1, "type": "link_down", "nodes": [1, 2]}]})
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
    errors = validate_config({
        "events": [{"at": 5, "type": "fib_add", "host": 0, "prefix": "ccnx:/test", "next_hop": "10.0.0.1", "protocol": "tcp"}]
    })
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
    errors = validate_config({"cache_config": {"nodes": [{"id": 1, "default_rct_ms": 500}]}})
    assert any("default_rct_ms" in e for e in errors)


def test_validate_cache_config_nodes_algorithm_invalid():
    errors = validate_config({"cache_config": {"nodes": [{"id": 1, "algorithm": "RANDOM"}]}})
    assert any("algorithm" in e for e in errors)


def test_validate_cache_config_nodes_type_invalid():
    errors = validate_config({"cache_config": {"nodes": [{"id": 1, "type": "redis"}]}})
    assert any("type" in e for e in errors)


def test_validate_failure_scenarios_non_dict():
    errors = validate_config({"failure_scenarios": "bad"})
    assert any("failure_scenarios" in e for e in errors)


def test_validate_failure_scenarios_invalid_strategy():
    errors = validate_config({"failure_scenarios": {"strategy": "invalid"}})
    assert any("strategy" in e for e in errors)


def test_validate_failure_scenarios_simple_non_dict():
    errors = validate_config({"failure_scenarios": {"strategy": "simple", "simple": "bad"}})
    assert any("simple" in e and "dict" in e for e in errors)


def test_validate_failure_scenarios_simple_count_negative():
    errors = validate_config({
        "failure_scenarios": {"strategy": "simple", "simple": {"count": -1}}
    })
    assert any("count" in e for e in errors)


def test_validate_failure_scenarios_simple_stagger_negative():
    errors = validate_config({
        "failure_scenarios": {"strategy": "simple", "simple": {"stagger": -1}}
    })
    assert any("stagger" in e for e in errors)


def test_validate_failure_scenarios_simple_exclude_invalid():
    errors = validate_config({
        "failure_scenarios": {"strategy": "simple", "simple": {"exclude": "bad"}}
    })
    assert any("exclude" in e for e in errors)


def test_validate_failure_scenarios_simple_interval_non_integer():
    errors = validate_config({
        "failure_scenarios": {"strategy": "simple", "simple": {"interval": "slow"}}
    })
    assert any("interval" in e for e in errors)


def test_validate_failure_scenarios_cyclic_non_list():
    errors = validate_config({"failure_scenarios": {"strategy": "cyclic", "cycles": "bad"}})
    assert any("cycles" in e and "list" in e for e in errors)


def test_validate_failure_scenarios_cyclic_empty():
    errors = validate_config({"failure_scenarios": {"strategy": "cyclic", "cycles": []}})
    assert any("at least one cycle" in e for e in errors)


def test_validate_failure_scenarios_cyclic_entry_non_dict():
    errors = validate_config({"failure_scenarios": {"strategy": "cyclic", "cycles": ["bad"]}})
    assert any("cycles[0]" in e for e in errors)


def test_validate_failure_scenarios_cyclic_entry_fields():
    errors = validate_config({
        "failure_scenarios": {
            "strategy": "cyclic",
            "cycles": [{
                "interval": "slow", "count": -1, "stagger": -1,
                "exclude": "bad", "target": "bad", "allow_publishers": "yes",
            }]
        }
    })
    assert any("interval" in e for e in errors)
    assert any("count" in e for e in errors)
    assert any("stagger" in e for e in errors)
    assert any("exclude" in e for e in errors)
    assert any("target" in e for e in errors)
    assert any("allow_publishers" in e for e in errors)


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
    errors = validate_config({
        "bridges": [{"switch": 0, "root_ip": "10.0.0.1/24", "local_routes": 123}]
    })
    assert any("local_routes" in e for e in errors)


def test_validate_bridges_nat_non_boolean():
    errors = validate_config({
        "bridges": [{"switch": 0, "root_ip": "10.0.0.1/24", "local_routes": "192.168.0.0/16", "nat": "yes"}]
    })
    assert any("nat" in e for e in errors)


def test_validate_bridges_nat_out_non_string():
    errors = validate_config({
        "bridges": [{"switch": 0, "root_ip": "10.0.0.1/24", "local_routes": "192.168.0.0/16", "nat_out": 123}]
    })
    assert any("nat_out" in e for e in errors)


def test_validate_bridges_root_ip_bare_rejected():
    errors = validate_config({
        "bridges": [{"switch": 0, "root_ip": "10.0.0.1", "local_routes": "192.168.0.0/16"}]
    })
    assert any("root_ip" in e and "CIDR" in e for e in errors)


def test_validate_bridges_root_ip_auto_accepted():
    errors = validate_config({
        "bridges": [{"switch": 0, "root_ip": "auto", "local_routes": "192.168.0.0/16"}]
    })
    assert not any("root_ip" in e for e in errors)


def test_validate_bridges_root_ip_cidr_accepted():
    errors = validate_config({
        "bridges": [{"switch": 0, "root_ip": "10.0.0.1/24", "local_routes": "192.168.0.0/16"}]
    })
    assert not any("root_ip" in e for e in errors)


def test_validate_bridges_root_ip_invalid_cidr_rejected():
    errors = validate_config({
        "bridges": [{"switch": 0, "root_ip": "999.999.999.999/24", "local_routes": "192.168.0.0/16"}]
    })
    assert any("root_ip" in e for e in errors)


def test_validate_bridges_root_ip_non_string_rejected():
    errors = validate_config({
        "bridges": [{"switch": 0, "root_ip": None, "local_routes": "192.168.0.0/16"}]
    })
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
# monitoring.targets.target_host validation
# ---------------------------------------------------------------------------

def test_validate_monitoring_target_host_valid():
    errors = validate_config({
        "monitoring": {
            "targets": [{"type": "csmgrstatus", "target_host": "192.168.1.1"}]
        }
    })
    assert errors == []


def test_validate_monitoring_target_host_empty_string():
    errors = validate_config({
        "monitoring": {
            "targets": [{"type": "csmgrstatus", "target_host": ""}]
        }
    })
    assert any("target_host" in e for e in errors)


def test_validate_monitoring_target_host_non_string():
    errors = validate_config({
        "monitoring": {
            "targets": [{"type": "csmgrstatus", "target_host": 12345}]
        }
    })
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
        {"events": [{"at": 0, "type": "get", "host": 0, "uri": "ccnx:/x", "pipeline": True}]},
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


_SPECS_WITH_MIN = [s for s in _FLAT_SPECS if s.minimum is not None and s.kind in ("int", "number")]
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
    assert not any(spec.key in e for e in errors), f"unexpected error for {spec.key}={at_min}"


@pytest.mark.parametrize("spec", _NULLABLE_SPECS, ids=[s.key for s in _NULLABLE_SPECS])
def test_flat_spec_accepts_null(spec):
    errors = validate_config({spec.key: None})
    assert not any(spec.key in e for e in errors), f"unexpected error for {spec.key}=None"
