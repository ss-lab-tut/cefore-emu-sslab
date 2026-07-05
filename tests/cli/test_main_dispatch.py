"""Tests for src.cli.main: cmd_linear/cmd_mesh forwarding and main() dispatch.

CONTEXT.md test-gap slice 10: cmd_linear/cmd_mesh/main() were previously only
indirectly exercised via cmd_disaster's path-containment tests. These tests
build argparse Namespaces through the *real* parser builders (mirroring
tests/cli/test_args.py's `_parser_for` helper) rather than hand-rolled
SimpleNamespace objects, so a drifted flag name or default would be caught
here the same way a real CLI invocation would catch it.
"""

import argparse
import sys
from unittest.mock import patch

import pytest

from src.cli.args import add_common_args, add_debug_args, add_linear_args, add_mesh_args
from src.cli.main import cmd_linear, cmd_mesh, main
from src.core.debug import DebugConfig


def _parser_for(*builders):
    """Build a bare parser from the given add_*_args builders.

    Mirrors tests/cli/test_args.py's _parser_for helper: cmd_linear/cmd_mesh
    are only correct against argparse Namespaces produced by the same
    builder functions main() actually wires up for each subcommand.
    """
    parser = argparse.ArgumentParser()
    for builder in builders:
        builder(parser)
    return parser


class TestCmdLinearForwarding:
    """cmd_linear() must forward parsed args to run_linear_scenario unchanged."""

    def test_forwards_hosts_run_dir_and_default_debug_config(self, tmp_path):
        # main() wires the linear subcommand as add_linear_args + add_debug_args
        # only (no add_common_args) -- see src/cli/main.py:83-85.
        parser = _parser_for(add_linear_args, add_debug_args)
        args = parser.parse_args(["--hosts", "7"])

        with (
            patch("src.cli.main.resolve_run_dir", return_value=tmp_path) as mock_resolve,
            patch("src.scenarios.linear.run_linear_scenario") as mock_run,
            patch("src.cli.main.setLogLevel") as mock_set_log_level,
        ):
            cmd_linear(args)

        mock_resolve.assert_called_once_with(args)
        mock_set_log_level.assert_called_once_with("info")
        mock_run.assert_called_once_with(
            7, run_dir=tmp_path, debug_config=DebugConfig()
        )

    def test_forwards_debug_flag_as_all_artifacts_enabled(self, tmp_path):
        parser = _parser_for(add_linear_args, add_debug_args)
        args = parser.parse_args(["--hosts", "4", "--debug"])

        with (
            patch("src.cli.main.resolve_run_dir", return_value=tmp_path),
            patch("src.scenarios.linear.run_linear_scenario") as mock_run,
            patch("src.cli.main.setLogLevel"),
        ):
            cmd_linear(args)

        _, kwargs = mock_run.call_args
        assert kwargs["debug_config"].enabled() is True
        assert kwargs["debug_config"].node_dirs is True
        assert kwargs["debug_config"].fib_dump is True
        assert kwargs["debug_config"].daemon_logs is True


class TestCmdMeshForwarding:
    """cmd_mesh() must forward every parsed mesh option by keyword."""

    def test_forwards_all_mesh_options(self, tmp_path):
        # main() wires the mesh subcommand as add_common_args + add_mesh_args
        # + add_debug_args -- see src/cli/main.py:88-92.
        parser = _parser_for(add_common_args, add_mesh_args, add_debug_args)
        args = parser.parse_args(
            [
                "--hosts",
                "8",
                "--switches",
                "12",
                "--seed",
                "5",
                "--k",
                "3",
                "--topo-png",
                "/tmp/topo.png",
                "--topo-layout",
                "circular",
                "--node-per-switch",
                "1",
                "--host-degree-min",
                "1",
                "--host-degree-max",
                "3",
                "--switch-use-all",
            ]
        )

        with (
            patch("src.cli.main.resolve_run_dir", return_value=tmp_path) as mock_resolve,
            patch("src.scenarios.mesh.run_mesh_scenario") as mock_run,
            patch("src.cli.main.setLogLevel") as mock_set_log_level,
        ):
            cmd_mesh(args)

        mock_resolve.assert_called_once_with(args)
        mock_set_log_level.assert_called_once_with("info")
        mock_run.assert_called_once_with(
            host_num=8,
            swhich_num=12,
            seed=5,
            k_paths=3,
            topo_png="/tmp/topo.png",
            topo_layout="circular",
            node_per_switch=1,
            host_degree_min=1,
            host_degree_max=3,
            switch_use_all=True,
            run_dir=tmp_path,
            debug_config=DebugConfig(),
        )

    def test_forwards_mesh_defaults_when_no_flags_given(self, tmp_path):
        parser = _parser_for(add_common_args, add_mesh_args, add_debug_args)
        args = parser.parse_args([])

        with (
            patch("src.cli.main.resolve_run_dir", return_value=tmp_path),
            patch("src.scenarios.mesh.run_mesh_scenario") as mock_run,
            patch("src.cli.main.setLogLevel"),
        ):
            cmd_mesh(args)

        _, kwargs = mock_run.call_args
        # Defaults come from OPTION_SPECS, not from cmd_mesh itself; assert the
        # forwarded values match what an un-flagged invocation actually produces.
        assert kwargs["host_num"] == 5
        assert kwargs["swhich_num"] == 10
        assert kwargs["seed"] is None
        assert kwargs["switch_use_all"] is False


class TestMainDispatch:
    """main() must route each subcommand to its cmd_* handler and enforce
    the no-subcommand help+exit(1) contract."""

    def test_dispatches_linear_subcommand_with_parsed_args(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ceforeemu", "linear", "--hosts", "6"])

        with patch("src.cli.main.cmd_linear") as mock_cmd_linear:
            main()

        mock_cmd_linear.assert_called_once()
        called_args = mock_cmd_linear.call_args[0][0]
        assert called_args.hosts == 6

    def test_dispatches_mesh_subcommand_with_parsed_args(self, monkeypatch):
        monkeypatch.setattr(
            sys, "argv", ["ceforeemu", "mesh", "--hosts", "9", "--switches", "4"]
        )

        with patch("src.cli.main.cmd_mesh") as mock_cmd_mesh:
            main()

        mock_cmd_mesh.assert_called_once()
        called_args = mock_cmd_mesh.call_args[0][0]
        assert called_args.hosts == 9
        assert called_args.switches == 4

    def test_dispatches_disaster_subcommand_with_parsed_args(self, monkeypatch, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("hosts: 3\nswitches: 4\nseed: 1\n")
        monkeypatch.setattr(
            sys, "argv", ["ceforeemu", "disaster", "--config", str(config_path)]
        )

        with patch("src.cli.main.cmd_disaster") as mock_cmd_disaster:
            main()

        mock_cmd_disaster.assert_called_once()
        called_args = mock_cmd_disaster.call_args[0][0]
        assert called_args.config == str(config_path)

    def test_no_subcommand_prints_help_and_exits_with_status_one(
        self, monkeypatch, capsys
    ):
        # No positional subcommand -> args has no "func" attribute, which is
        # the branch main() uses to print help and exit(1) (src/cli/main.py:105-107).
        monkeypatch.setattr(sys, "argv", ["ceforeemu"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "usage:" in captured.out
        assert "ceforeemu" in captured.out
