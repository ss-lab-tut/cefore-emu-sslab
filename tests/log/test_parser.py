"""Tests for src.log.parser."""

from src.log.parser import (
    PARSERS,
    _detect_success,
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


def test_detect_success_empty():
    assert _detect_success("") is False
    assert _detect_success("   ") is False


def test_detect_success_failure_pattern():
    assert _detect_success("Could not receive anything") is False
    assert _detect_success("Received frame ... NG") is False


def test_detect_success_normal():
    assert _detect_success("Transfer completed successfully") is True


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


# ── cefpubfile / cefsubfile ──


def test_parse_cefpubfile_dynamic_keys():
    text = (
        "2024-01-15 10:00:00.000 [cefpubfile] Start\n"
        "[cefpubfile] URI = ccnx:/test/pub1\n"
        "[cefpubfile] Tx Frames = 50\n"
        "[cefpubfile] Duration = 2.5 sec\n"
    )
    result = parse_cefpubfile(text)
    assert result["uri"] == "ccnx:/test/pub1"
    assert result["tx_frames"] == 50
    assert result["duration"] == 2.5
    assert result["success"] is True


def test_parse_cefsubfile_dynamic_keys():
    text = (
        "[cefsubfile] URI = ccnx:/test/sub1\n"
        "[cefsubfile] Rx Bytes = 1024 Bytes\n"
    )
    result = parse_cefsubfile(text)
    assert result["uri"] == "ccnx:/test/sub1"
    assert result["rx_bytes"] == 1024


# ── PARSERS dispatcher ──


def test_parsers_dispatch():
    assert PARSERS["cefputfile"] is parse_cefputfile
    assert PARSERS["cefgetfile"] is parse_cefgetfile
    assert PARSERS["cefpubfile"] is parse_cefpubfile
    assert PARSERS["cefsubfile"] is parse_cefsubfile
