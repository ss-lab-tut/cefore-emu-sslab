"""Tests for tools.autotest.analyze."""

import sys
from pathlib import Path

# analyze.py is not a package module, import via path manipulation
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "autotest"))
from analyze import _fmt_rate, classify, discover_results, summarize  # noqa: E402


# ── classify ──


def test_classify_success():
    record = {
        "op_type": "get",
        "exit_code": 0,
        "success": True,
        "has_completed_log": True,
        "has_output_file": True,
    }
    success, reasons = classify(record)
    assert success is True
    assert reasons["exit_code_nonzero"] == 0


def test_classify_exit_code_nonzero():
    record = {
        "op_type": "get",
        "exit_code": 1,
        "success": False,
        "has_completed_log": True,
        "has_output_file": True,
    }
    success, reasons = classify(record)
    assert success is False
    assert reasons["exit_code_nonzero"] == 1


def test_classify_record_without_success_is_never_success():
    """Pre-Factor records classify as unknown — no disk probing fallback."""
    record = {
        "exit_code": 0,
        "has_completed_log": True,
        "has_output_file": True,
    }
    success, _ = classify(record)
    assert success is False


def test_classify_explicit_success_field():
    record = {
        "exit_code": 1,
        "success": True,
        "has_completed_log": False,
        "has_output_file": False,
    }
    success, _ = classify(record)
    assert success is True


def test_classify_successful_record_counts_no_reasons():
    """Failure reasons must not be charged to successful records."""
    record = {
        "op_type": "pub",
        "exit_code": 0,
        "success": True,
        "has_completed_log": None,
        "has_output_file": None,
    }
    success, reasons = classify(record)
    assert success is True
    assert reasons == {
        "exit_code_nonzero": 0,
        "missing_completed_log": 0,
        "missing_output_file": 0,
    }


def test_classify_null_factors_never_count_as_reasons():
    """Tri-state None (unknown / not-applicable) is not a failure reason."""
    record = {
        "op_type": "pub",
        "exit_code": 1,
        "success": False,
        "has_completed_log": None,
        "has_output_file": None,
    }
    success, reasons = classify(record)
    assert success is False
    assert reasons["exit_code_nonzero"] == 1
    assert reasons["missing_completed_log"] == 0
    assert reasons["missing_output_file"] == 0


def test_classify_known_false_factors_count_on_failure():
    record = {
        "op_type": "get",
        "exit_code": 0,
        "success": False,
        "has_completed_log": False,
        "has_output_file": False,
    }
    success, reasons = classify(record)
    assert success is False
    assert reasons["missing_completed_log"] == 1
    assert reasons["missing_output_file"] == 1
    assert reasons["exit_code_nonzero"] == 0


# ── summarize ──


def test_summarize_groups_by_uri():
    records = [
        {"uri": "ccnx:/a", "exit_code": 0, "success": True, "has_completed_log": True, "has_output_file": True},
        {"uri": "ccnx:/a", "exit_code": 0, "success": True, "has_completed_log": True, "has_output_file": True},
        {"uri": "ccnx:/b", "exit_code": 0, "success": True, "has_completed_log": True, "has_output_file": True},
    ]
    rows = summarize(records)
    uris = [r["uri"] for r in rows]
    assert "ccnx:/a" in uris
    assert "ccnx:/b" in uris


def test_summarize_publisher_down():
    records = [
        {
            "uri": "ccnx:/a", "exit_code": 0, "success": True,
            "has_completed_log": True, "has_output_file": True,
            "publisher_host": 5, "down_hosts": [5],
        },
    ]
    rows = summarize(records)
    assert rows[0]["eval_pubdown_total"] == 1


def test_summarize_success_rate():
    records = [
        {"uri": "ccnx:/a", "exit_code": 0, "success": True, "has_completed_log": True, "has_output_file": True},
        {"uri": "ccnx:/a", "exit_code": 1, "success": False, "has_completed_log": False, "has_output_file": False},
        {"uri": "ccnx:/a", "exit_code": 0, "success": True, "has_completed_log": True, "has_output_file": True},
        {"uri": "ccnx:/a", "exit_code": 1, "success": False, "has_completed_log": False, "has_output_file": False},
    ]
    rows = summarize(records)
    assert rows[0]["eval_success_rate"] == 0.5


def test_summarize_pubdown_total_zero_returns_none():
    """publisher-downイベントなしの場合、rateはNoneであること。"""
    records = [
        {"uri": "ccnx:/a", "exit_code": 0, "success": True, "has_completed_log": True, "has_output_file": True},
    ]
    rows = summarize(records)
    assert rows[0]["eval_pubdown_total"] == 0
    assert rows[0]["eval_success_rate_when_publisher_down"] is None


def test_summarize_eval_total_zero_returns_none():
    """evalレコードなしの場合、eval_success_rateはNoneであること。"""
    records = [
        {"uri": "ccnx:/a", "phase": "warmup", "exit_code": 0, "success": True, "has_completed_log": True, "has_output_file": True},
    ]
    rows = summarize(records)
    assert rows[0]["eval_total"] == 0
    assert rows[0]["eval_success_rate"] is None


def test_summarize_excludes_put_and_pub_from_eval():
    """Publisher-side rows must not inflate consumer eval denominators."""
    records = [
        {"uri": "ccnx:/a", "op_type": "put", "exit_code": 0, "success": True,
         "has_completed_log": None, "has_output_file": None},
        {"uri": "ccnx:/a", "op_type": "pub", "exit_code": 0, "success": True,
         "has_completed_log": None, "has_output_file": None},
        {"uri": "ccnx:/a", "op_type": "get", "exit_code": 0, "success": True,
         "has_completed_log": True, "has_output_file": True},
        {"uri": "ccnx:/a", "op_type": "sub", "exit_code": 0, "success": True,
         "has_completed_log": None, "has_output_file": True},
    ]
    rows = summarize(records)
    assert rows[0]["eval_total"] == 2
    assert rows[0]["eval_success"] == 2
    assert rows[0]["fail_missing_completed_log"] == 0
    assert rows[0]["fail_missing_output_file"] == 0


def test_summarize_put_only_uri_produces_no_row():
    records = [
        {"uri": "ccnx:/seed", "op_type": "put", "exit_code": 0, "success": True,
         "has_completed_log": None, "has_output_file": None},
    ]
    assert summarize(records) == []


def test_fmt_rate_none():
    assert _fmt_rate(None) == "N/A"


def test_fmt_rate_value():
    assert _fmt_rate(0.5) == "0.500"


# ── discover_results ──


def test_discover_results_file(tmp_path):
    r = tmp_path / "results.json"
    r.write_text("[]")
    found = discover_results([r])
    assert len(found) == 1
    assert found[0].name == "results.json"


def test_discover_results_directory(tmp_path):
    sub = tmp_path / "run_0001"
    sub.mkdir()
    (sub / "results.json").write_text("[]")
    found = discover_results([tmp_path])
    assert len(found) == 1
