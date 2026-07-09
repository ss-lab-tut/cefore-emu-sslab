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


@pytest.mark.parametrize(
    ("debug_yaml", "expected_error"),
    [
        ("debug:\n  artifacts: fib_dump\n", "debug.artifacts must be a list"),
        (
            "debug:\n  artifacts: [node_dirs, bad]\n",
            "debug.artifacts contains unknown artifact: 'bad'",
        ),
        (
            "debug:\n  output_subdir: 123\n",
            "debug.output_subdir must be a string",
        ),
    ],
)
def test_malformed_debug_config_exits_with_raw_debug_error(
    tmp_path, capsys, debug_yaml, expected_error
):
    args = _parse_disaster_args(
        tmp_path,
        f"hosts: 3\nswitches: 4\n{debug_yaml}",
        ["--output-dir", str(tmp_path / "out"), "--no-script-log"],
    )

    with pytest.raises(SystemExit) as exc_info:
        _run_bootstrap(args)

    assert exc_info.value.code == 1
    assert f"config error: {expected_error}\n" in capsys.readouterr().err


def test_malformed_forwarding_config_exits_with_raw_config_error(tmp_path, capsys):
    args = _parse_disaster_args(
        tmp_path,
        "hosts: 3\nswitches: 4\nforwarding_config: null\n",
        ["--output-dir", str(tmp_path / "out"), "--no-script-log"],
    )

    with pytest.raises(SystemExit) as exc_info:
        _run_bootstrap(args)

    assert exc_info.value.code == 1
    assert "config error: forwarding_config must be a dict\n" in capsys.readouterr().err


def test_forwarding_config_empty_dict_error_reported_exactly_once(tmp_path, capsys):
    """forwarding_config keeps special_config_merge (excluded from
    structured_option_keys()), so bootstrap's raw special-key revalidation
    loop stays its only validation path even after the B1 presence fix in
    validate_merged_args — confirm that path fires once, not twice.
    """
    args = _parse_disaster_args(
        tmp_path,
        "hosts: 3\nswitches: 4\nforwarding_config: {}\n",
        ["--output-dir", str(tmp_path / "out"), "--no-script-log"],
    )

    with pytest.raises(SystemExit):
        _run_bootstrap(args)

    stderr = capsys.readouterr().err
    assert stderr.count("config error: forwarding_config must not be empty") == 1


def test_malformed_cache_config_exits_with_raw_config_error_exactly_once(
    tmp_path, capsys
):
    """cache_config is likewise special_config_merge and only raw-validated
    by bootstrap's dedicated loop; pin single-occurrence reporting the same
    way as forwarding_config above.
    """
    args = _parse_disaster_args(
        tmp_path,
        "hosts: 3\nswitches: 4\ncache_config:\n  strategy: invalid\n",
        ["--output-dir", str(tmp_path / "out"), "--no-script-log"],
    )

    with pytest.raises(SystemExit):
        _run_bootstrap(args)

    stderr = capsys.readouterr().err
    expected = (
        "cache_config.strategy must be one of: k_centers, manual, degree_based, random"
    )
    assert stderr.count(f"config error: {expected}") == 1


@pytest.mark.parametrize(
    ("failure_yaml", "expected_error"),
    [
        (
            "failure_scenarios: {}\n",
            "failure_scenarios with strategy 'simple' requires 'simple' block",
        ),
        (
            "failure_scenarios: null\n",
            "failure_scenarios must be a dict",
        ),
    ],
)
def test_malformed_failure_scenarios_exits_with_config_error(
    tmp_path, capsys, failure_yaml, expected_error
):
    """2026-07-09 regression test for B1: present-but-empty failure_scenarios
    ({} / null) previously reached validate_merged_args and got silently
    dropped by its truthiness check, so bootstrap exited 0 despite an
    unfinished failure_scenarios block (ADR-0002 requires both to error).
    """
    args = _parse_disaster_args(
        tmp_path,
        f"hosts: 3\nswitches: 4\n{failure_yaml}",
        ["--output-dir", str(tmp_path / "out"), "--no-script-log"],
    )

    with pytest.raises(SystemExit) as exc_info:
        _run_bootstrap(args)

    assert exc_info.value.code == 1
    assert f"config error: {expected_error}\n" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# validate_merged_args scalar-key presence vs. truthiness (B3)
#
# 2026-07-09 bug fix (audit follow-up to 73ca40b): the scalar sibling of the
# B1 structured-key fix above. A present None for a non-nullable scalar
# (e.g. "hosts: null") used to be dropped by validate_merged_args's old
# `val is not None` gate, so bootstrap exited 0 on a config validate_config
# itself rejects. "num" is the false-positive trap this fix had to clear
# first: its argparse default is None (not a real experiment number), so it
# is now nullable=True to keep the ordinary no-flag run error-free.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "expected_error"),
    [
        ("hosts", "hosts must be an integer >= 3"),
        ("switches", "switches must be an integer >= 2"),
    ],
)
def test_null_non_nullable_scalar_exits_with_config_error(
    tmp_path, capsys, key, expected_error
):
    """Regression test for the B3 bug: an explicit config null for a
    non-nullable scalar must surface as a validate_config error at the
    bootstrap level, not be silently dropped.
    """
    config_yaml = {"hosts": 3, "switches": 4}
    config_yaml[key] = None
    yaml_lines = "".join(
        f"{k}: {'null' if v is None else v}\n" for k, v in config_yaml.items()
    )
    args = _parse_disaster_args(
        tmp_path,
        yaml_lines,
        ["--output-dir", str(tmp_path / "out"), "--no-script-log"],
    )

    with pytest.raises(SystemExit) as exc_info:
        _run_bootstrap(args)

    assert exc_info.value.code == 1
    assert f"config error: {expected_error}\n" in capsys.readouterr().err


def test_num_null_in_config_does_not_error(tmp_path):
    """num is nullable (its argparse default is already None, meaning "no
    experiment number"), so an explicit "num: null" in config must behave
    identically to omitting it entirely — no validation error, no crash.
    """
    args = _parse_disaster_args(
        tmp_path,
        "hosts: 3\nswitches: 4\nnum: null\n",
        ["--output-dir", str(tmp_path / "out"), "--no-script-log"],
    )

    record = _run_bootstrap(args)

    assert record["args"].num is None


def test_no_flags_empty_config_validates_cleanly(tmp_path):
    """The false-positive guard at the bootstrap level: a plain run with no
    CLI flags and an empty config file must not trip any scalar key,
    including "num" whose argparse default of None could otherwise be
    mistaken for an explicit config null.
    """
    args = _parse_disaster_args(
        tmp_path,
        "",
        ["--output-dir", str(tmp_path / "out"), "--no-script-log"],
    )

    record = _run_bootstrap(args)

    assert record["args"].num is None
    assert record["args"].hosts == 5
    assert record["args"].switches == 10


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
        "down_interval": 0,
        "down_duration": 0,
        "down_count": 5,
        "down_stagger": 2,
        "down_exclude": "",
        "cache_count": 2,
        "forwarding": {"default": "flooding"},
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
    assert debug_config.output_subdir == "cfgdbg"
