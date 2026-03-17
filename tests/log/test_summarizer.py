"""Tests for src.log.summarizer."""

import json
from pathlib import Path

from src.log.summarizer import (
    COMMAND_COLS,
    _build_fieldnames,
    _load_meta,
    collect_records,
    summarize,
    write_csv,
)


# ── _load_meta ──


def test_load_meta_valid(tmp_path):
    meta = {"hosts": 5, "seed": 42}
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    result = _load_meta(tmp_path)
    assert result["hosts"] == 5
    assert result["seed"] == 42


def test_load_meta_missing(tmp_path):
    result = _load_meta(tmp_path)
    assert result == {}


def test_load_meta_invalid_json(tmp_path):
    (tmp_path / "meta.json").write_text("{bad json")
    result = _load_meta(tmp_path)
    assert result == {}


# ── collect_records ──


def _create_log_dir(tmp_path, name="exp1"):
    d = tmp_path / name
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"hosts": 4, "seed": 42}))
    (d / "cefputfile_h9.log").write_text(
        "[cefputfile] URI = ccnx:/test/ex1\n"
        "[cefputfile] Tx Frames = 10\n"
        "[cefputfile] Tx Bytes = 5120 Bytes\n"
    )
    (d / "cefgetfile_h0.log").write_text(
        "[cefgetfile] URI = ccnx:/test/ex1\n"
        "[cefgetfile] Rx Frames (All) = 12\n"
    )
    (d / "random.log").write_text("not a cefore log")
    return d


def test_collect_records_groups_by_command(tmp_path):
    d = _create_log_dir(tmp_path)
    grouped = collect_records([d])
    assert "cefputfile" in grouped
    assert "cefgetfile" in grouped
    assert len(grouped["cefputfile"]) == 1
    assert len(grouped["cefgetfile"]) == 1


def test_collect_records_skips_non_matching(tmp_path):
    d = _create_log_dir(tmp_path)
    grouped = collect_records([d])
    # random.log should not appear in any command group
    all_filenames = []
    for records in grouped.values():
        all_filenames.extend(r["filename"] for r in records)
    assert "random.log" not in all_filenames


def test_collect_records_non_directory(tmp_path, capsys):
    f = tmp_path / "not_a_dir.txt"
    f.write_text("file")
    grouped = collect_records([f])
    assert grouped == {}
    captured = capsys.readouterr()
    assert "skipping" in captured.err


# ── _build_fieldnames ──


def test_build_fieldnames_putfile():
    fields = _build_fieldnames("cefputfile", [])
    assert "uri" in fields
    assert "tx_frames" in fields
    assert "throughput_bps" in fields


def test_build_fieldnames_dynamic():
    records = [{"custom_key": 1, "another": 2}]
    fields = _build_fieldnames("cefpubfile", records)
    assert "custom_key" in fields
    assert "another" in fields


# ── write_csv ──


def test_write_csv_empty_returns_none():
    assert write_csv([], "cefputfile") is None


def test_write_csv_stdout(capsys):
    records = [{"uri": "ccnx:/test", "tx_frames": 10, "success": True}]
    result = write_csv(records, "cefputfile", stdout=True)
    assert result is None
    captured = capsys.readouterr()
    assert "uri" in captured.out
    assert "ccnx:/test" in captured.out


# ── summarize ──


def test_summarize_writes_csv(tmp_path):
    d = _create_log_dir(tmp_path)
    out = tmp_path / "output"
    out.mkdir()
    written = summarize([d], output_dir=out)
    assert len(written) >= 1
    assert any(p.suffix == ".csv" for p in written)


def test_summarize_no_logs(tmp_path, capsys):
    d = tmp_path / "empty"
    d.mkdir()
    written = summarize([d], output_dir=tmp_path)
    assert written == []
    captured = capsys.readouterr()
    assert "No log files" in captured.err
