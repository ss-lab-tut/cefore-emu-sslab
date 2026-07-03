"""Temporary cmd_disaster migration gate.

Delete this file after the branch merges. A CONTEXT.md note is added in Slice4.
The expected values below are literals captured from the pre-extraction
cmd_disaster behavior so the bootstrap seam stays behavior-preserving.
"""

import argparse
import json
from pathlib import Path

import pytest

from src.cli.args import (
    add_common_args,
    add_debug_args,
    add_disaster_args,
    add_mesh_args,
)
from src.cli.main import cmd_disaster

# 2026-07-03 artifact-layout fix: topo_png defaults deliberately changed from
# ex{hosts}_seed{seed}.png to {experiment_dir}_h{hosts}.png because host count
# was being displayed in the experiment-number position.


def _parse_args(tmp_path: Path, config_text: str, argv: list[str]):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(config_text, encoding="utf-8")

    parser = argparse.ArgumentParser()
    add_common_args(parser)
    add_mesh_args(parser)
    add_disaster_args(parser)
    add_debug_args(parser)
    return parser.parse_args(["--config", str(config_path), *argv])


@pytest.mark.parametrize(
    ("config_text", "argv", "expected"),
    [
        (
            (
                "hosts: 7\nswitches: 9\nseed: 123\nk: 4\n"
                "down_interval: 25\ndown_duration: 15\ndown_count: 3\n"
                "down_stagger: 2\ndown_exclude: h1,h2\ncache_count: 2\n"
            ),
            ["--output-dir", "{out}", "--no-script-log"],
            {
                "subset": {
                    "hosts": 7,
                    "switches": 9,
                    "seed": 123,
                    "k": 4,
                    "topo_png": "seed123_h7.png",
                    "down_interval": 25,
                    "down_duration": 15,
                    "down_count": 3,
                    "down_stagger": 2,
                    "down_exclude": "h1,h2",
                    "cache_count": 2,
                    "num": None,
                    "no_script_log": True,
                },
                "meta": {
                    "num": None,
                    "hosts": 7,
                    "switches": 9,
                    "seed": 123,
                    "k": 4,
                    "down_interval": 25,
                    "down_duration": 15,
                    "down_count": 3,
                    "down_stagger": 2,
                    "down_exclude": "h1,h2",
                    "cache_count": 2,
                },
                "debug": {
                    "node_dirs": False,
                    "fib_dump": False,
                    "daemon_logs": False,
                    "output_subdir": "debug",
                },
            },
        ),
        (
            "hosts: 7\nswitches: 9\nseed: 123\nk: 4\ndown_count: 3\ncache_count: 2\n",
            [
                "--output-dir",
                "{out}",
                "--no-script-log",
                "--hosts",
                "11",
                "--seed",
                "99",
                "--k",
                "6",
                "--down-count",
                "8",
            ],
            {
                "subset": {
                    "hosts": 11,
                    "switches": 9,
                    "seed": 99,
                    "k": 6,
                    "topo_png": "seed99_h11.png",
                    "down_interval": 30,
                    "down_duration": 10,
                    "down_count": 8,
                    "down_stagger": 2,
                    "down_exclude": "",
                    "cache_count": 2,
                    "num": None,
                    "no_script_log": True,
                },
                "meta": {
                    "num": None,
                    "hosts": 11,
                    "switches": 9,
                    "seed": 99,
                    "k": 6,
                    "down_interval": 30,
                    "down_duration": 10,
                    "down_count": 8,
                    "down_stagger": 2,
                    "down_exclude": "",
                    "cache_count": 2,
                },
                "debug": {
                    "node_dirs": False,
                    "fib_dump": False,
                    "daemon_logs": False,
                    "output_subdir": "debug",
                },
            },
        ),
        (
            (
                "hosts: 3\nswitches: 4\n"
                "debug:\n  artifacts: [fib_dump]\n  output_subdir: cfgdbg\n"
            ),
            [
                "--output-dir",
                "{out}",
                "--no-script-log",
                "--debug-artifact",
                "node_dirs",
            ],
            {
                "subset": {
                    "hosts": 3,
                    "switches": 4,
                    "seed": None,
                    "k": 2,
                    "topo_png": "seednone_h3.png",
                    "down_interval": 30,
                    "down_duration": 10,
                    "down_count": 5,
                    "down_stagger": 2,
                    "down_exclude": "",
                    "cache_count": 0,
                    "num": None,
                    "no_script_log": True,
                },
                "meta": {
                    "num": None,
                    "hosts": 3,
                    "switches": 4,
                    "seed": None,
                    "k": 2,
                    "down_interval": 30,
                    "down_duration": 10,
                    "down_count": 5,
                    "down_stagger": 2,
                    "down_exclude": "",
                    "cache_count": 0,
                },
                "debug": {
                    "node_dirs": True,
                    "fib_dump": True,
                    "daemon_logs": False,
                    "output_subdir": "cfgdbg",
                },
            },
        ),
        (
            "hosts: 3\nswitches: 4\n",
            ["--output-dir", "", "--no-script-log"],
            {
                "subset": {
                    "hosts": 3,
                    "switches": 4,
                    "seed": None,
                    "k": 2,
                    "topo_png": "seednone_h3.png",
                    "down_interval": 30,
                    "down_duration": 10,
                    "down_count": 5,
                    "down_stagger": 2,
                    "down_exclude": "",
                    "cache_count": 0,
                    "num": None,
                    "no_script_log": True,
                },
                "meta": None,
                "debug": {
                    "node_dirs": False,
                    "fib_dump": False,
                    "daemon_logs": False,
                    "output_subdir": "debug",
                },
            },
        ),
    ],
)
def test_cmd_disaster_matches_captured_bootstrap_behavior(
    tmp_path, monkeypatch, config_text, argv, expected
):
    out_dir = tmp_path / "out"
    args = _parse_args(
        tmp_path,
        config_text,
        [str(out_dir) if value == "{out}" else value for value in argv],
    )
    record = {}

    def fake_run(args, run_dir, *, log_context=None, debug_config=None):
        record["subset"] = {
            key: getattr(args, key)
            for key in (
                "hosts",
                "switches",
                "seed",
                "k",
                "topo_png",
                "down_interval",
                "down_duration",
                "down_count",
                "down_stagger",
                "down_exclude",
                "cache_count",
                "num",
                "no_script_log",
            )
        }
        record["debug"] = {
            "node_dirs": debug_config.node_dirs,
            "fib_dump": debug_config.fib_dump,
            "daemon_logs": debug_config.daemon_logs,
            "output_subdir": debug_config.output_subdir,
        }
        record["run_dir"] = run_dir
        record["log_context"] = log_context

    monkeypatch.setattr("src.scenarios.disaster.run_disaster_scenario", fake_run)

    cmd_disaster(args)

    assert record["subset"] == expected["subset"]
    assert record["debug"] == expected["debug"]
    assert record["log_context"] is None
    meta_path = record["run_dir"] / "meta.json"
    meta = (
        json.loads(meta_path.read_text(encoding="utf-8"))
        if meta_path.exists()
        else None
    )
    assert meta == expected["meta"]


def test_cmd_disaster_malformed_config_matches_captured_error(tmp_path, capsys):
    args = _parse_args(
        tmp_path,
        "hosts: 0\nswitches: 4\n",
        ["--output-dir", str(tmp_path / "out"), "--no-script-log"],
    )

    with pytest.raises(SystemExit) as exc_info:
        cmd_disaster(args)

    assert exc_info.value.code == 1
    assert capsys.readouterr().err == "config error: hosts must be an integer >= 3\n"
