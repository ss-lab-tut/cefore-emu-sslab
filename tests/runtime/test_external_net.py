"""Unit tests for external network legacy content removal."""

import json
import sys

import pytest

from src.core.debug import DebugConfig
import src.runtime.external_net as external_net


def _write_config(tmp_path, text):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(text, encoding="utf-8")
    return config_path


def _run_connect_main(monkeypatch, tmp_path, config_text, argv):
    config_path = _write_config(tmp_path, config_text)
    output_dir = tmp_path / "out"
    record = {}

    def fake_run_connect(args, run_dir=None, log_context=None, debug_config=None):
        record["args"] = args
        record["run_dir"] = run_dir
        record["log_context"] = log_context
        record["debug_config"] = debug_config

    monkeypatch.setattr(external_net, "run_connect", fake_run_connect)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ceforeemu-connect",
            "--config",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--no-script-log",
            *argv,
        ],
    )

    external_net.main()
    return record


def test_legacy_content_helpers_removed():
    assert not hasattr(external_net, "_resolve_connect_content_ops")
    assert not hasattr(external_net, "_warn_if_no_content_operations")


def test_publication_events_drive_connect_publisher_metadata():
    events = [
        {"at": 1, "type": "put", "host": 4, "uri": "ccnx:/test/data"},
        {"at": 2, "type": "pubsub_pub", "host": 3, "uri": "ccnx:/test/live"},
        {"at": 3, "type": "get", "host": 0, "uri": "ccnx:/test/data"},
    ]
    publications, publishers, _ = external_net.extract_publications(events)
    assert [event["type"] for event in publications] == ["put", "pubsub_pub"]
    assert publishers == {"ccnx:/test/data": 4, "ccnx:/test/live": 3}


def test_connect_main_cli_flag_beats_config_value(monkeypatch, tmp_path):
    record = _run_connect_main(
        monkeypatch,
        tmp_path,
        "hosts: 12\nswitches: 8\n",
        ["--hosts", "20"],
    )

    assert record["args"].hosts == 20


def test_connect_main_config_fills_defaulted_flag(monkeypatch, tmp_path):
    record = _run_connect_main(
        monkeypatch,
        tmp_path,
        "hosts: 12\nswitches: 8\nseed: 77\n",
        [],
    )

    assert record["args"].hosts == 12
    assert record["args"].switches == 8
    assert record["args"].seed == 77


def test_connect_main_meta_json_uses_bootstrap_schema(monkeypatch, tmp_path):
    record = _run_connect_main(
        monkeypatch,
        tmp_path,
        "hosts: 5\nswitches: 6\nseed: 33\nk: 4\ncache_count: 2\n",
        [],
    )

    meta = json.loads((record["run_dir"] / "meta.json").read_text(encoding="utf-8"))
    assert meta == {
        "num": None,
        "hosts": 5,
        "switches": 6,
        "seed": 33,
        "k": 4,
        "down_interval": 30,
        "down_duration": 10,
        "down_count": 5,
        "down_stagger": 2,
        "down_exclude": "",
        "cache_count": 2,
    }
    assert "output_dir" not in meta


def test_connect_main_skips_meta_json_when_run_dir_is_current_directory(
    monkeypatch, tmp_path
):
    config_path = _write_config(tmp_path, "hosts: 5\nswitches: 6\n")
    record = {}

    def fake_run_connect(args, run_dir=None, log_context=None, debug_config=None):
        record["run_dir"] = run_dir

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(external_net, "run_connect", fake_run_connect)
    monkeypatch.setattr(
        sys,
        "argv",
        ["ceforeemu-connect", "--config", str(config_path), "--output-dir", ""],
    )

    external_net.main()

    assert record["run_dir"].as_posix() == "."
    assert not (tmp_path / "meta.json").exists()


def test_connect_main_invalid_config_exits_after_merge(monkeypatch, tmp_path, capsys):
    config_path = _write_config(tmp_path, "hosts: 0\nswitches: 6\n")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ceforeemu-connect",
            "--config",
            str(config_path),
            "--output-dir",
            str(tmp_path / "out"),
            "--no-script-log",
        ],
    )
    monkeypatch.setattr(external_net, "run_connect", lambda *args, **kwargs: None)

    with pytest.raises(SystemExit) as exc_info:
        external_net.main()

    assert exc_info.value.code == 1
    assert "config error:" in capsys.readouterr().err


def test_connect_main_rejects_malformed_debug_section(monkeypatch, tmp_path, capsys):
    config_path = _write_config(
        tmp_path,
        "hosts: 5\nswitches: 6\ndebug:\n  artifacts: bad\n",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ceforeemu-connect",
            "--config",
            str(config_path),
            "--output-dir",
            str(tmp_path / "out"),
            "--no-script-log",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        external_net.main()

    assert exc_info.value.code == 1
    assert "config error: debug.artifacts must be a list\n" in capsys.readouterr().err


def test_connect_main_cli_override_can_make_invalid_config_valid(monkeypatch, tmp_path):
    record = _run_connect_main(
        monkeypatch,
        tmp_path,
        "hosts: 0\nswitches: 6\n",
        ["--hosts", "20"],
    )

    assert record["args"].hosts == 20


def test_connect_main_passes_cli_debug_config_to_run_connect(monkeypatch, tmp_path):
    record = _run_connect_main(
        monkeypatch,
        tmp_path,
        "hosts: 5\nswitches: 6\n",
        ["--debug-artifact", "fib_dump"],
    )

    assert record["debug_config"].fib_dump is True
    assert record["debug_config"].node_dirs is False


def test_connect_main_passes_config_debug_config_to_run_connect(monkeypatch, tmp_path):
    record = _run_connect_main(
        monkeypatch,
        tmp_path,
        "hosts: 5\nswitches: 6\ndebug:\n  artifacts: [node_dirs]\n",
        [],
    )

    assert record["debug_config"].node_dirs is True
    assert record["debug_config"].fib_dump is False


def test_connect_main_adapter_passes_debug_config(monkeypatch, tmp_path):
    calls = {}

    def fake_run_connect(args, run_dir=None, log_context=None, debug_config=None):
        calls["received"] = {
            "args": args,
            "run_dir": run_dir,
            "log_context": log_context,
            "debug_config": debug_config,
        }

    debug_config = DebugConfig(node_dirs=True)
    monkeypatch.setattr(external_net, "run_connect", fake_run_connect)
    external_net._run_connect_adapter(
        object(),
        tmp_path,
        log_context={"tee": True},
        debug_config=debug_config,
    )

    assert calls["received"]["run_dir"] == tmp_path
    assert calls["received"]["log_context"] == {"tee": True}
    assert calls["received"]["debug_config"] is debug_config
