"""Tests for src.log.filename."""

from pathlib import Path

from src.log.filename import FilenameMeta, parse_filename


def test_host_content_pattern():
    meta = parse_filename("cefputfile_h13_c10.log")
    assert meta == FilenameMeta(command="cefputfile", host_id=13, content_id=10)


def test_host_only_pattern():
    meta = parse_filename("cefputfile_h9.log")
    assert meta == FilenameMeta(command="cefputfile", host_id=9)
    assert meta.content_id is None


def test_disaster_new_pattern():
    meta = parse_filename(
        "cefgetfile_seed42_downhostsnone_phaseeval_cycle0_idx0_h1.log"
    )
    assert meta.command == "cefgetfile"
    assert meta.host_id == 1
    assert meta.seed == "42"
    assert meta.down_hosts == "none"
    assert meta.phase == "eval"
    assert meta.cycle == 0
    assert meta.idx == 0


def test_disaster_legacy_pattern():
    meta = parse_filename("cefgetfile_seed42_downhosts0,1_idx16_h4.log")
    assert meta.command == "cefgetfile"
    assert meta.host_id == 4
    assert meta.seed == 42
    assert meta.down_hosts == "0,1"
    assert meta.idx == 16


def test_legacy_dash_pattern():
    meta = parse_filename("cefgetfile-h0.log")
    assert meta == FilenameMeta(command="cefgetfile", host_id=0)


def test_cefpubfile_host_content():
    meta = parse_filename("cefpubfile_h5_c3.log")
    assert meta.command == "cefpubfile"
    assert meta.host_id == 5
    assert meta.content_id == 3


def test_cefsubfile_host_only():
    meta = parse_filename("cefsubfile_h2.log")
    assert meta.command == "cefsubfile"
    assert meta.host_id == 2


def test_unrecognized_returns_none():
    assert parse_filename("random.log") is None
    assert parse_filename("some_other_file.txt") is None


def test_path_object_input():
    meta = parse_filename(Path("some/dir/cefputfile_h1.log"))
    assert meta.command == "cefputfile"
    assert meta.host_id == 1


def test_disaster_new_with_numeric_downhosts():
    meta = parse_filename(
        "cefgetfile_seed10_downhosts3,5_phaseeval_cycle1_idx2_h7.log"
    )
    assert meta.down_hosts == "3,5"
    assert meta.cycle == 1
    assert meta.idx == 2
    assert meta.host_id == 7
