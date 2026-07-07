"""Tests for src.log.parser."""

from src.log.parser import (
    PARSERS,
    _extract_timestamp,
    _parse_numeric,
    _strip_unit,
    parse_cefgetfile,
    parse_cefpubfile,
    parse_cefputfile,
    parse_cefsubfile,
)


# ── helpers ──


def test_extract_timestamp_valid():
    text = "2024-01-15 10:30:45.123456 [cefputfile] Start"
    assert _extract_timestamp(text) == "2024-01-15 10:30:45.123456"


def test_extract_timestamp_missing():
    assert _extract_timestamp("no timestamp here") is None


def test_parse_numeric_int():
    assert _parse_numeric("42") == 42
    assert isinstance(_parse_numeric("42"), int)


def test_parse_numeric_float():
    assert _parse_numeric("3.14") == 3.14
    assert isinstance(_parse_numeric("3.14"), float)


def test_strip_unit_mbps():
    assert _strip_unit("10.5 Mbps") == "10.5"


def test_strip_unit_no_unit():
    assert _strip_unit("42") == "42"


# Success judgment itself is pinned in tests/core/test_verdict.py; the tests
# below pin how the parsers feed the log-only Verdict adapter.


# ── cefputfile ──


def test_parse_cefputfile_full(sample_putfile_log):
    result = parse_cefputfile(sample_putfile_log)
    assert result["timestamp"] == "2024-01-15 10:30:45.123456"
    assert result["uri"] == "ccnx:/test/example1"
    assert result["file"] == "./sample-putfile"
    assert result["rate_mbps"] == 10
    assert result["block_size_bytes"] == 1024
    assert result["cache_time_sec"] == 3000
    assert result["expiration_sec"] == 5000
    assert result["tx_frames"] == 100
    assert result["tx_bytes"] == 51200
    assert result["duration_sec"] == 5.123
    assert result["throughput_bps"] == 80000
    assert result["success"] is True


def test_parse_cefputfile_empty():
    result = parse_cefputfile("")
    assert result["success"] is False
    assert result["uri"] is None


# ── cefgetfile ──


def test_parse_cefgetfile_full(sample_getfile_log):
    result = parse_cefgetfile(sample_getfile_log)
    assert result["timestamp"] == "2024-01-15 10:31:00.654321"
    assert result["uri"] == "ccnx:/test/example1"
    assert result["rx_frames_all"] == 120
    assert result["rx_frames_content"] == 100
    assert result["rx_bytes_all"] == 61440
    assert result["rx_bytes_content"] == 51200
    assert result["duration_sec"] == 4.567
    assert result["throughput_bps"] == 90000
    assert result["goodput_bps"] == 85000
    assert result["jitter_ave_us"] == 150
    assert result["jitter_max_us"] == 500
    assert result["jitter_var_us"] == 75
    assert result["success"] is True


def test_parse_cefgetfile_failure():
    text = "[cefgetfile] URI = ccnx:/test/fail\nCould not receive anything"
    result = parse_cefgetfile(text)
    assert result["success"] is False
    assert result["uri"] == "ccnx:/test/fail"


def test_parse_cefgetfile_partial_without_marker_is_failure():
    # Fields parsed but no completed marker: the definitive Factor decides.
    text = "[cefgetfile] URI = ccnx:/test/partial\n[cefgetfile] Duration = 1.234 sec\n"
    result = parse_cefgetfile(text)
    assert result["success"] is False
    assert result["duration_sec"] == 1.234


# ── cefpubfile / cefsubfile ──


def test_parse_cefpubfile_uses_schema_fields():
    text = (
        "2024-01-15 10:00:00.000 [cefpubfile] Start\n"
        "[cefpubfile] URI = ccnx:/test/pub1\n"
        "[cefpubfile] File = ./publisher.bin\n"
        "[cefpubfile] Rate = 10 Mbps\n"
        "[cefpubfile] Block Size = 1024 Bytes\n"
        "[cefpubfile] Cache Time = 3000 sec\n"
        "[cefpubfile] Expiration = 5000 sec\n"
    )
    result = parse_cefpubfile(text)
    assert result["uri"] == "ccnx:/test/pub1"
    assert result["file"] == "./publisher.bin"
    assert result["rate_mbps"] == 10
    assert result["block_size_bytes"] == 1024
    assert result["cache_time_sec"] == 3000
    assert result["expiration_sec"] == 5000
    # pub has no in-log definitive Factor: success stays unknown.
    assert result["success"] is None


def test_parse_cefsubfile_uses_canonical_unit_fields():
    text = (
        "[cefsubfile] URI = ccnx:/test/sub1\n"
        "[cefsubfile] Rx Frames (All) = 12\n"
        "[cefsubfile] Rx Frames (ContentObject) = 10\n"
        "[cefsubfile] Rx Bytes (All) = 6144 Bytes\n"
        "[cefsubfile] Rx Bytes (ContentObject) = 5120 Bytes\n"
        "[cefsubfile] Duration = 2.5 sec\n"
        "[cefsubfile] Throughput = 90000 bps\n"
        "[cefsubfile] Goodput = 85000 bps\n"
        "[cefsubfile] Jitter (Ave) = 150 us\n"
        "[cefsubfile] Jitter (Max) = 500 us\n"
        "[cefsubfile] Jitter (Var) = 75 us\n"
    )
    result = parse_cefsubfile(text)
    assert result["uri"] == "ccnx:/test/sub1"
    assert result["rx_frames_all"] == 12
    assert result["rx_frames_content"] == 10
    assert result["rx_bytes_all"] == 6144
    assert result["rx_bytes_content"] == 5120
    assert result["duration_sec"] == 2.5
    assert result["throughput_bps"] == 90000
    assert result["goodput_bps"] == 85000
    assert result["jitter_ave_us"] == 150
    assert result["jitter_max_us"] == 500
    assert result["jitter_var_us"] == 75
    assert result["success"] is None


def test_parse_pubsub_unknown_fields_are_kept_with_warning(capsys):
    text = (
        "[cefpubfile] URI = ccnx:/test/pub1\n[cefpubfile] Surprise Value = 12 Bytes\n"
    )
    result = parse_cefpubfile(text)
    assert result["surprise_value"] == 12
    captured = capsys.readouterr()
    assert (
        "warning: cefpubfile: unknown log field 'Surprise Value' "
        "(add to src/log/schema.py)"
    ) in captured.err


# ── PARSERS dispatcher ──


def test_parsers_dispatch():
    assert PARSERS["cefputfile"] is parse_cefputfile
    assert PARSERS["cefgetfile"] is parse_cefgetfile
    assert PARSERS["cefpubfile"] is parse_cefpubfile
    assert PARSERS["cefsubfile"] is parse_cefsubfile
