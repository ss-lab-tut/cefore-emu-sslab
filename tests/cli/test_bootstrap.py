"""Behavior tests for the shared scenario bootstrap."""

import argparse
import json
import sys
from pathlib import Path

import pytest

from src.cli.args import (
    add_common_args,
    add_debug_args,
    add_disaster_args,
    add_mesh_args,
)
from src.cli.bootstrap import bootstrap_scenario


def _parse_disaster_args(
    tmp_path: Path, config_text: str, argv: list[str] | None = None
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(config_text, encoding="utf-8")

    parser = argparse.ArgumentParser()
    add_common_args(parser)
    add_mesh_args(parser)
    add_disaster_args(parser)
    add_debug_args(parser)
    return parser.parse_args(["--config", str(config_path), *(argv or [])])


def _run_bootstrap(args):
    record = {}

    def fake_run_fn(args, run_dir, *, log_context=None, debug_config=None):
        record["args"] = args
        record["run_dir"] = run_dir
        record["log_context"] = log_context
        record["debug_config"] = debug_config

    bootstrap_scenario(
        args,
        blocks=("common", "mesh", "disaster", "debug"),
        run_fn=fake_run_fn,
    )
    return record


def test_explicit_cli_flag_beats_config_value(tmp_path):
    args = _parse_disaster_args(
        tmp_path,
        "hosts: 3\nswitches: 4\nseed: 1\n",
        ["--output-dir", str(tmp_path / "out"), "--hosts", "9", "--no-script-log"],
    )

    record = _run_bootstrap(args)

    assert record["args"].hosts == 9
    assert record["args"].switches == 4


def test_config_fills_argparse_default(tmp_path):
    args = _parse_disaster_args(
        tmp_path,
        "hosts: 8\nswitches: 10\nseed: 44\nk: 5\n",
        ["--no-script-log"],
    )

    record = _run_bootstrap(args)

    assert record["args"].hosts == 8
    assert record["args"].switches == 10
    assert record["args"].seed == 44
    assert record["args"].k == 5


def test_validation_error_exits_with_config_error_lines(tmp_path, capsys):
    args = _parse_disaster_args(
        tmp_path,
        "hosts: 0\nswitches: 4\n",
        ["--no-script-log"],
    )

    with pytest.raises(SystemExit) as exc_info:
        _run_bootstrap(args)

    assert exc_info.value.code == 1
    assert "config error:" in capsys.readouterr().err


def test_meta_json_written_with_exact_disaster_keys(tmp_path):
    args = _parse_disaster_args(
        tmp_path,
        "hosts: 7\nswitches: 9\nseed: 123\nk: 4\ncache_count: 2\n",
        ["--output-dir", str(tmp_path / "out"), "--no-script-log"],
    )

    record = _run_bootstrap(args)

    meta_path = record["run_dir"] / "meta.json"
    assert json.loads(meta_path.read_text(encoding="utf-8")) == {
        "num": None,
        "hosts": 7,
        "switches": 9,
        "seed": 123,
        "k": 4,
        "down_interval": 30,
        "down_duration": 10,
        "down_count": 5,
        "down_stagger": 2,
        "down_exclude": "",
        "cache_count": 2,
    }


def test_meta_json_skipped_when_run_dir_is_current_directory(tmp_path):
    args = _parse_disaster_args(
        tmp_path,
        "hosts: 3\nswitches: 4\n",
        ["--output-dir", "", "--no-script-log"],
    )

    record = _run_bootstrap(args)

    assert record["run_dir"] == Path(".")
    assert not (tmp_path / "meta.json").exists()


def test_script_log_created_and_streams_restored_when_run_fn_raises(tmp_path):
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    args = _parse_disaster_args(
        tmp_path,
        "hosts: 3\nswitches: 4\n",
        ["--output-dir", str(tmp_path / "out")],
    )

    def failing_run_fn(args, run_dir, *, log_context=None, debug_config=None):
        print("stdout marker")
        print("stderr marker", file=sys.stderr)
        assert log_context is not None
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        bootstrap_scenario(
            args,
            blocks=("common", "mesh", "disaster", "debug"),
            run_fn=failing_run_fn,
        )

    assert sys.stdout is original_stdout
    assert sys.stderr is original_stderr
    log_path = next((tmp_path / "out").glob("*/script.log"))
    assert "stdout marker" in log_path.read_text(encoding="utf-8")
    assert "stderr marker" in log_path.read_text(encoding="utf-8")


def test_no_script_log_skips_file_and_log_context(tmp_path):
    args = _parse_disaster_args(
        tmp_path,
        "hosts: 3\nswitches: 4\n",
        ["--output-dir", str(tmp_path / "out"), "--no-script-log"],
    )

    record = _run_bootstrap(args)

    assert record["log_context"] is None
    assert not list((tmp_path / "out").glob("*/script.log"))


def test_debug_config_unions_cli_artifacts_with_config_debug_section(tmp_path):
    args = _parse_disaster_args(
        tmp_path,
        "hosts: 3\nswitches: 4\ndebug:\n  artifacts: [fib_dump]\n  output_subdir: cfgdbg\n",
        [
            "--output-dir",
            str(tmp_path / "out"),
            "--no-script-log",
            "--debug-artifact",
            "node_dirs",
        ],
    )

    record = _run_bootstrap(args)

    debug_config = record["debug_config"]
    assert debug_config.node_dirs is True
    assert debug_config.fib_dump is True
    assert debug_config.daemon_logs is False
    assert debug_config.output_subdir == "cfgdbg"
