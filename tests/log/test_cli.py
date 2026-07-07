"""Tests for src.log.cli: build_parser defaults and main()'s summarize/plot_all flow.

CONTEXT.md test-gap slice 10. `summarize`/`collect_records` are bound at
module import time (src/log/cli.py:6), so they are patched at
"src.log.cli.<name>". `plot_all` is imported lazily inside main() (cli.py:45),
so it must be patched at its defining module "src.log.plotter.plot_all" --
patching "src.log.cli.plot_all" would silently no-op since that name is never
bound in cli's module namespace.
"""

from pathlib import Path
from unittest.mock import patch

from src.log.cli import build_parser, main


class TestBuildParserDefaults:
    """build_parser() must expose the documented flags with correct defaults."""

    def test_directories_is_required_and_coerced_to_path(self):
        parser = build_parser()
        args = parser.parse_args(["dir1", "dir2"])
        assert args.directories == [Path("dir1"), Path("dir2")]

    def test_output_dir_defaults_to_none(self):
        parser = build_parser()
        args = parser.parse_args(["dir1"])
        assert args.output_dir is None

    def test_output_dir_flag_is_coerced_to_path(self):
        parser = build_parser()
        args = parser.parse_args(["dir1", "-o", "out"])
        assert args.output_dir == Path("out")

    def test_stdout_and_graph_default_to_false(self):
        parser = build_parser()
        args = parser.parse_args(["dir1"])
        assert args.stdout is False
        assert args.graph is False

    def test_stdout_and_graph_flags_set_true(self):
        parser = build_parser()
        args = parser.parse_args(["dir1", "--stdout", "--graph"])
        assert args.stdout is True
        assert args.graph is True


class TestMainSummarizeAndGraph:
    """main() always summarizes; it only calls plot_all when --graph is set
    and --stdout is not (cli.py:44, `if args.graph and not args.stdout`)."""

    def test_default_invocation_summarizes_without_plotting(self):
        with (
            patch("src.log.cli.summarize") as mock_summarize,
            patch("src.log.cli.collect_records") as mock_collect_records,
            patch("src.log.plotter.plot_all") as mock_plot_all,
        ):
            main(["dir1"])

        mock_summarize.assert_called_once_with(
            [Path("dir1")], output_dir=None, stdout=False
        )
        # No --graph -> plot_all's lazy import path is never reached.
        mock_collect_records.assert_not_called()
        mock_plot_all.assert_not_called()

    def test_stdout_flag_is_forwarded_and_suppresses_graph(self):
        with (
            patch("src.log.cli.summarize") as mock_summarize,
            patch("src.log.cli.collect_records") as mock_collect_records,
            patch("src.log.plotter.plot_all") as mock_plot_all,
        ):
            # --graph and --stdout together: the `not args.stdout` guard
            # must suppress plot_all even though --graph was requested.
            main(["dir1", "--stdout", "--graph"])

        mock_summarize.assert_called_once_with(
            [Path("dir1")], output_dir=None, stdout=True
        )
        mock_collect_records.assert_not_called()
        mock_plot_all.assert_not_called()

    def test_graph_flag_without_stdout_triggers_plot_all(self, tmp_path, capsys):
        experiment_dir = tmp_path / "run1"
        experiment_dir.mkdir()
        written_paths = [tmp_path / "put.png", tmp_path / "put.pdf"]
        grouped_records = {"cefputfile": [{"uri": "ccnx:/a"}]}

        with (
            patch("src.log.cli.summarize") as mock_summarize,
            patch(
                "src.log.cli.collect_records", return_value=grouped_records
            ) as mock_collect_records,
            patch(
                "src.log.plotter.plot_all", return_value=written_paths
            ) as mock_plot_all,
        ):
            main([str(experiment_dir), "--graph"])

        mock_summarize.assert_called_once_with(
            [experiment_dir], output_dir=None, stdout=False
        )
        # output_dir defaults to the parent of the first directory (cli.py:47).
        mock_collect_records.assert_called_once_with([experiment_dir])
        mock_plot_all.assert_called_once_with(grouped_records, tmp_path)

        captured = capsys.readouterr()
        for path in written_paths:
            assert f"{path}  (graph)" in captured.out

    def test_graph_flag_with_explicit_output_dir(self, tmp_path):
        experiment_dir = tmp_path / "run1"
        experiment_dir.mkdir()
        output_dir = tmp_path / "out"

        with (
            patch("src.log.cli.summarize"),
            patch(
                "src.log.cli.collect_records", return_value={}
            ) as mock_collect_records,
            patch("src.log.plotter.plot_all", return_value=[]) as mock_plot_all,
        ):
            main([str(experiment_dir), "--graph", "-o", str(output_dir)])

        # Explicit --output-dir must be used verbatim instead of the
        # first-directory-parent fallback (cli.py:47).
        mock_collect_records.assert_called_once_with([experiment_dir])
        mock_plot_all.assert_called_once_with({}, output_dir)
