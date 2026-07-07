"""Tests for the command-owned log record schema."""

from src.log.parser import PARSERS
from src.log.schema import COMMAND_SCHEMAS, FieldKind


def test_schema_field_names_are_unique_per_command():
    for schema in COMMAND_SCHEMAS.values():
        names = [field.name for field in schema.fields]
        assert len(names) == len(set(names))


def test_schema_log_labels_round_trip_through_public_parsers():
    for command, schema in COMMAND_SCHEMAS.items():
        for field in schema.fields:
            if field.kind is FieldKind.MARKER:
                # MARKER fields are bare lines with no "= value" suffix to
                # append; presence alone is the parsed result.
                line = f"[{command}] {field.log_label}\n"
                record = PARSERS[command](line)
                assert record[field.name] is True
                continue
            line = f"[{command}] {field.log_label} = 123\n"
            record = PARSERS[command](line)
            assert record[field.name] == (
                "123" if field.kind is FieldKind.TEXT else 123
            )


def test_put_schema_preserves_existing_parser_field_order():
    assert COMMAND_SCHEMAS["cefputfile"].field_names == (
        "uri",
        "file",
        "rate_mbps",
        "block_size_bytes",
        "cache_time_sec",
        "expiration_sec",
        "tx_frames",
        "tx_bytes",
        "duration_sec",
        "throughput_bps",
    )


def test_pub_schema_preserves_canonical_field_order():
    assert COMMAND_SCHEMAS["cefpubfile"].field_names == (
        "uri",
        "file",
        "rate_mbps",
        "block_size_bytes",
        "cache_time_sec",
        "expiration_sec",
        "trigger_interest_sent",
        "trigger_data_received",
    )


def test_get_schema_preserves_existing_parser_field_order():
    assert COMMAND_SCHEMAS["cefgetfile"].field_names == (
        "uri",
        "rx_frames_all",
        "rx_frames_content",
        "rx_bytes_all",
        "rx_bytes_content",
        "duration_sec",
        "throughput_bps",
        "goodput_bps",
        "jitter_ave_us",
        "jitter_max_us",
        "jitter_var_us",
    )


def test_schema_csv_columns_wrap_fields_with_timestamp_and_success():
    assert COMMAND_SCHEMAS["cefsubfile"].csv_columns == (
        "timestamp",
        "uri",
        "rx_frames_all",
        "rx_frames_content",
        "rx_bytes_all",
        "rx_bytes_content",
        "duration_sec",
        "throughput_bps",
        "goodput_bps",
        "jitter_ave_us",
        "jitter_max_us",
        "jitter_var_us",
        "success",
    )


def test_text_fields_are_declared_explicitly():
    text_fields = {
        field.name
        for schema in COMMAND_SCHEMAS.values()
        for field in schema.fields
        if field.kind is FieldKind.TEXT
    }
    assert text_fields == {"uri", "file"}


def test_only_cefpubfile_declares_marker_fields():
    # Other commands' schemas are untouched by the cefpubfile marker addition.
    marker_commands = {
        command
        for command, schema in COMMAND_SCHEMAS.items()
        for field in schema.fields
        if field.kind is FieldKind.MARKER
    }
    assert marker_commands == {"cefpubfile"}


# ── cefpubfile trigger markers ──
#
# Archived workshop campaign logs (logs/workshop_20260707/main/) show these
# two literal lines appear in every SUCCESS run's cefpubfile log and in no
# FAILURE run (FAILURE runs have a 0-byte cefpubfile log, SIGTERM before any
# output). Fixture strings below are copied verbatim from that evidence.

PUB_SUCCESS_LOG = (
    "2024-01-15 10:00:00.000 [cefpubfile] Start\n"
    "[cefpubfile] Send Trigger Interest.\n"
    "[cefpubfile] Receive Trigger Data, finish application.\n"
)


def test_pub_success_log_parses_both_markers_true():
    record = PARSERS["cefpubfile"](PUB_SUCCESS_LOG)
    assert record["trigger_interest_sent"] is True
    assert record["trigger_data_received"] is True


def test_pub_empty_log_parses_both_markers_false():
    record = PARSERS["cefpubfile"]("")
    assert record["trigger_interest_sent"] is False
    assert record["trigger_data_received"] is False


def test_pub_unrelated_lines_leave_markers_false():
    record = PARSERS["cefpubfile"]("[cefpubfile] URI = ccnx:/test/pub1\n")
    assert record["trigger_interest_sent"] is False
    assert record["trigger_data_received"] is False
