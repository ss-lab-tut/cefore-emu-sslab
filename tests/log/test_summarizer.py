"""Tests for src.log.summarizer."""

import json

from src.log.summarizer import (
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
    (d / "cefputfile_eval_h9_test_ex1.log").write_text(
        "[cefputfile] URI = ccnx:/test/ex1\n"
        "[cefputfile] Tx Frames = 10\n"
        "[cefputfile] Tx Bytes = 5120 Bytes\n"
    )
    (d / "cefgetfile_eval_h0_test_ex1.log").write_text(
        "[cefgetfile] URI = ccnx:/test/ex1\n[cefgetfile] Rx Frames (All) = 12\n"
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


def test_collect_records_reads_canonical_names_and_enriches_from_results(tmp_path):
    d = tmp_path / "exp1"
    d.mkdir()
    log_name = "cefpubfile_eval_h2_test_example.log"
    (d / log_name).write_text("[cefpubfile] Tx Frames = 12\n")
    (d / "results.json").write_text(
        json.dumps(
            [
                {
                    "op_type": "pub",
                    "ts": "2026-07-03T00:00:00Z",
                    "phase": "eval",
                    "host": 2,
                    "uri": "ccnx:/test/example",
                    "out_file": None,
                    "log_file": f"/tmp/{log_name}",
                    "exit_code": 0,
                    "down_hosts": [1, 3],
                    "publisher_host": 1,
                    "publisher_down": True,
                    "success": True,
                    "has_completed_log": True,
                    "has_output_file": None,
                }
            ]
        )
    )

    row = collect_records([d])["cefpubfile"][0]
    assert row["host_id"] == 2
    assert row["phase"] == "eval"
    assert row["label"] == "test_example"
    assert row["uri"] == "ccnx:/test/example"
    assert row["success"] is True
    assert row["down_hosts"] == [1, 3]
    assert row["publisher_down"] is True


def test_collect_records_extracts_forwarding_default_from_nested_meta(tmp_path):
    d = tmp_path / "exp1"
    d.mkdir()
    (d / "meta.json").write_text(
        json.dumps({"forwarding": {"default": "shortest_path"}})
    )
    (d / "cefputfile_eval_h2_test_forwarding.log").write_text(
        "[cefputfile] URI = ccnx:/test/forwarding\n[cefputfile] Tx Frames = 10\n"
    )

    row = collect_records([d])["cefputfile"][0]

    assert row["forwarding_default"] == "shortest_path"
    assert "forwarding_default" in _build_fieldnames("cefputfile", [row])


def test_collect_records_results_join_uses_last_duplicate_log_file(tmp_path):
    d = tmp_path / "exp1"
    d.mkdir()
    log_name = "cefpubfile_eval_h2_test_example.log"
    (d / log_name).write_text("[cefpubfile] Tx Frames = 12\n")
    records = []
    for uri, success in (("ccnx:/first", False), ("ccnx:/last", True)):
        records.append(
            {
                "op_type": "pub",
                "ts": "2026-07-03T00:00:00Z",
                "phase": "eval",
                "host": 2,
                "uri": uri,
                "out_file": None,
                "log_file": log_name,
                "exit_code": 0,
                "down_hosts": [],
                "publisher_host": None,
                "publisher_down": False,
                "success": success,
                "has_completed_log": True,
                "has_output_file": None,
            }
        )
    (d / "results.json").write_text(json.dumps(records))

    row = collect_records([d])["cefpubfile"][0]
    assert row["uri"] == "ccnx:/last"
    assert row["success"] is True


def test_collect_records_keeps_text_parser_values_over_results_join(tmp_path):
    d = tmp_path / "exp1"
    d.mkdir()
    log_name = "cefgetfile_eval_h2_test_example.log"
    (d / log_name).write_text("[cefgetfile] URI = ccnx:/from-log\n")
    (d / "results.json").write_text(
        json.dumps(
            [
                {
                    "op_type": "get",
                    "ts": "2026-07-03T00:00:00Z",
                    "phase": "eval",
                    "host": 2,
                    "uri": "ccnx:/from-results",
                    "out_file": None,
                    "log_file": log_name,
                    "exit_code": 0,
                    "down_hosts": [],
                    "publisher_host": None,
                    "publisher_down": False,
                    "success": True,
                    "has_completed_log": True,
                    "has_output_file": None,
                }
            ]
        )
    )

    row = collect_records([d])["cefgetfile"][0]
    assert row["uri"] == "ccnx:/from-log"


def test_collect_records_skips_legacy_content_log_names(tmp_path):
    d = tmp_path / "exp1"
    d.mkdir()
    # 2026-07-03 artifact-layout contract: legacy content log names are no
    # longer parsed once all writers emit canonical command_phase_hN_label.log.
    (d / "cefputfile_h9.log").write_text("[cefputfile] URI = ccnx:/test/ex1\n")
    (d / "cefgetfile-h0.log").write_text("[cefgetfile] URI = ccnx:/test/ex1\n")

    assert collect_records([d]) == {}


def test_collect_records_missing_results_json_leaves_join_columns_empty(tmp_path):
    d = tmp_path / "exp1"
    d.mkdir()
    (d / "cefsubfile_eval_h3_test_topic.log").write_text("[cefsubfile] Topic = x\n")

    row = collect_records([d])["cefsubfile"][0]
    assert row["down_hosts"] is None
    assert row["publisher_down"] is None


def test_build_fieldnames_drops_legacy_filename_metadata_columns():
    fields = _build_fieldnames("cefgetfile", [])
    # 2026-07-03 artifact-layout fix: these filename-derived fields belonged
    # to legacy log names and are intentionally removed from the CSV schema.
    assert "content_id" not in fields
    assert "file_seed" not in fields
    assert "get_idx" not in fields
    assert "cycle" not in fields


# ── _build_fieldnames ──


def test_build_fieldnames_putfile():
    fields = _build_fieldnames("cefputfile", [])
    assert "uri" in fields
    assert "tx_frames" in fields
    assert "throughput_bps" in fields


def test_build_fieldnames_pubfile_uses_schema_columns_and_keeps_unknowns():
    records = [{"custom_key": 1, "another": 2}]
    fields = _build_fieldnames("cefpubfile", records)
    assert "rate_mbps" in fields
    assert "block_size_bytes" in fields
    assert "custom_key" in fields
    assert "another" in fields


def test_build_fieldnames_subfile_uses_schema_columns():
    fields = _build_fieldnames("cefsubfile", [])
    assert "throughput_bps" in fields
    assert "goodput_bps" in fields
    assert "jitter_ave_us" in fields


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
