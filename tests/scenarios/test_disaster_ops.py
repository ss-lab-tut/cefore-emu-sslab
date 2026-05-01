"""Unit tests for disaster operation preparation."""

from argparse import Namespace

from src.scenarios.disaster import DisasterScenario, _warn_if_no_content_operations


def _make_args(**overrides):
    data = {
        "hosts": 3,
        "seed": 42,
        "puts": [],
        "auto": None,
        "priority_uris": None,
        "bridges": [],
        "bridge": [],
        "ext": [],
        "no_cli": False,
        "results_json": "",
        "addressing": {},
    }
    data.update(overrides)
    return Namespace(**data)


def test_prepare_ops_keeps_empty_puts_when_not_configured(tmp_path):
    scenario = DisasterScenario(_make_args(), run_dir=tmp_path)
    assert scenario.ops_put == []
    assert scenario.publisher_ids == set()
    assert scenario.uri_publishers == {}


def test_prepare_ops_uses_explicit_puts(tmp_path):
    puts = [{"host": 2, "uri": "ccnx:/test/sample", "file": "./sample-putfile"}]
    scenario = DisasterScenario(_make_args(puts=puts), run_dir=tmp_path)
    assert scenario.ops_put == puts
    assert scenario.publisher_ids == {2}
    assert scenario.uri_publishers == {"ccnx:/test/sample": 2}


def test_warn_if_no_content_operations(capsys):
    warned = _warn_if_no_content_operations([], [])
    captured = capsys.readouterr()
    assert warned is True
    assert "no content operations configured" in captured.out


def test_warn_if_no_content_operations_suppressed_when_ops_exist(capsys):
    warned = _warn_if_no_content_operations([{"host": 2, "uri": "x"}], [])
    captured = capsys.readouterr()
    assert warned is False
    assert captured.out == ""
