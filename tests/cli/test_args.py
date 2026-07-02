"""Tests for spec-derived CLI argument builders."""

import argparse

import pytest

from src.cli.args import (
    add_common_args,
    add_connect_args,
    add_debug_args,
    add_disaster_args,
    add_linear_args,
    add_mesh_args,
)
from src.core.config.validator import OPTION_SPECS


def _parser_for(*builders):
    parser = argparse.ArgumentParser()
    for builder in builders:
        builder(parser)
    return parser


def _actions_by_dest(parser):
    return {action.dest: action for action in parser._actions if action.dest != "help"}


def _specs_for_blocks(*blocks):
    block_set = set(blocks)
    return {
        spec.key: spec
        for spec in OPTION_SPECS.values()
        if spec.cli_allowed and block_set.intersection(spec.block)
    }


def _expected_type(spec):
    if spec.kind == "int":
        return int
    if spec.kind == "number":
        return float
    if spec.kind in ("str", "enum", "structured"):
        return str
    return None


def _assert_parser_matches_blocks(parser, *blocks):
    actions = _actions_by_dest(parser)
    specs = _specs_for_blocks(*blocks)

    assert set(actions) == set(specs)
    for key, spec in specs.items():
        action = actions[key]
        if spec.action == "BooleanOptionalAction":
            assert action.option_strings == [
                spec.flag,
                "--no-" + spec.flag.removeprefix("--"),
            ]
        else:
            assert action.option_strings == [spec.flag]
        assert action.required is False
        assert action.default == spec.default
        assert action.choices == spec.choices
        assert action.metavar == spec.metavar
        assert action.help == spec.help
        if spec.action == "store_true":
            assert isinstance(action, argparse._StoreTrueAction)
        elif spec.action == "append":
            assert isinstance(action, argparse._AppendAction)
        elif spec.action == "BooleanOptionalAction":
            assert isinstance(action, argparse.BooleanOptionalAction)
        elif spec.action is None:
            assert action.type is _expected_type(spec)


def test_common_builder_matches_option_specs():
    _assert_parser_matches_blocks(_parser_for(add_common_args), "common")


def test_mesh_builder_matches_option_specs():
    _assert_parser_matches_blocks(_parser_for(add_mesh_args), "mesh")


def test_disaster_builder_matches_option_specs():
    _assert_parser_matches_blocks(_parser_for(add_disaster_args), "disaster")


def test_debug_builder_matches_option_specs():
    _assert_parser_matches_blocks(_parser_for(add_debug_args), "debug")


def test_linear_parser_shape_matches_option_specs():
    _assert_parser_matches_blocks(
        _parser_for(add_linear_args, add_debug_args), "linear", "debug"
    )


def test_topo_layout_rejects_unknown_choice():
    parser = _parser_for(add_common_args)

    with pytest.raises(SystemExit):
        parser.parse_args(["--topo-layout", "typo"])


def test_warmup_only_cache_nodes_boolean_optional_action():
    parser = _parser_for(add_disaster_args)

    assert parser.parse_args([]).warmup_only_cache_nodes is True
    assert (
        parser.parse_args(["--warmup-only-cache-nodes"]).warmup_only_cache_nodes is True
    )
    assert (
        parser.parse_args(["--no-warmup-only-cache-nodes"]).warmup_only_cache_nodes
        is False
    )


def test_debug_artifact_appends_and_rejects_unknown_choice():
    parser = _parser_for(add_debug_args)

    args = parser.parse_args(
        ["--debug-artifact", "node_dirs", "--debug-artifact", "fib_dump"]
    )
    assert args.debug_artifact == ["node_dirs", "fib_dump"]
    with pytest.raises(SystemExit):
        parser.parse_args(["--debug-artifact", "bad"])


# The 26 dests the external_net.py connect parser hand-declared before this
# ledger existed (R7-1 Slice3). Kept as a literal list, not derived from
# OPTION_SPECS, so this test fails loudly if a future spec edit accidentally
# widens or narrows the "connect" block membership.
_CONNECT_DESTS = {
    "hosts",
    "switches",
    "node_per_switch",
    "host_degree_min",
    "host_degree_max",
    "switch_use_all",
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
    "bridge",
    "config",
    "topo_png",
    "script_log",
    "no_script_log",
    "topo_layout",
    "num",
    "output_dir",
    "timestamp",
    "no_cli",
}

# Options that must stay out of the connect parser: disaster-only knobs
# (down-cycle metrics, warmup, cache RCT override, webui) that never had a
# hand-written --flag in external_net.py's main().
_CONNECT_FORBIDDEN_DESTS = {
    "debug",
    "debug_artifact",
    "duration",
    "results_json",
    "cache_default_rct_ms",
    "publisher_host",
    "pubsub_sub_startup_grace",
    "warmup_get_interval",
    "warmup_only_cache_nodes",
    "webui_port",
}


def test_connect_builder_matches_option_specs():
    _assert_parser_matches_blocks(_parser_for(add_connect_args), "connect")


def test_connect_parser_dest_set_matches_hand_written_ledger():
    parser = _parser_for(add_connect_args)
    assert set(_actions_by_dest(parser)) == _CONNECT_DESTS


def test_connect_parser_excludes_forbidden_dests():
    parser = _parser_for(add_connect_args)
    dests = set(_actions_by_dest(parser))
    assert dests.isdisjoint(_CONNECT_FORBIDDEN_DESTS)
