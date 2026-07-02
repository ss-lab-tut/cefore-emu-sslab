"""Common argparse definitions for cefore-emu CLI."""

import argparse

from ..core.config.validator import OPTION_SPECS


def _argparse_type(spec):
    """Map OptionSpec scalar kind to argparse's conversion callable."""
    if spec.kind == "int":
        return int
    if spec.kind == "number":
        return float
    if spec.kind in ("str", "enum"):
        return str
    return None


def _argparse_action(spec):
    """Resolve the action names stored in OptionSpec to argparse objects."""
    if spec.action == "BooleanOptionalAction":
        return argparse.BooleanOptionalAction
    return spec.action


def _add_args_for_block(parser, block):
    """Add all CLI options whose canonical spec belongs to a CLI block."""
    specs = sorted(
        (
            spec
            for spec in OPTION_SPECS.values()
            if spec.cli_allowed and block in spec.block
        ),
        key=lambda spec: spec.cli_order,
    )
    for spec in specs:
        kwargs = {
            "default": spec.default,
            "help": spec.help,
        }
        action = _argparse_action(spec)
        if action is not None:
            kwargs["action"] = action
        arg_type = _argparse_type(spec)
        if action is None and arg_type is not None:
            kwargs["type"] = arg_type
        if spec.choices is not None:
            kwargs["choices"] = spec.choices
        if spec.metavar is not None:
            kwargs["metavar"] = spec.metavar
        parser.add_argument(spec.flag, **kwargs)


def add_debug_args(parser):
    """Add debug artifact collection arguments."""
    _add_args_for_block(parser, "debug")


def add_linear_args(parser):
    """Add arguments for linear topology."""
    _add_args_for_block(parser, "linear")


def add_common_args(parser):
    """Add arguments common to all topology types."""
    _add_args_for_block(parser, "common")


def add_mesh_args(parser):
    """Add arguments for mesh topology types."""
    _add_args_for_block(parser, "mesh")


def add_disaster_args(parser):
    """Add arguments for disaster topology."""
    _add_args_for_block(parser, "disaster")
