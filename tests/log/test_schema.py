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
