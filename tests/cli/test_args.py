"""Tests for spec-derived CLI argument builders."""

import argparse

import pytest

from src.cli.args import (
    add_common_args,
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
