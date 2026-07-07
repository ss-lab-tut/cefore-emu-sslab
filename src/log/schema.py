"""Canonical command-specific schema for parsed Cefore content logs.

The log record field names are a public interface shared by the parser,
summarizer, and plotter.  Keeping the command tables here makes spelling,
column order, and log labels a single owned decision instead of a coincidence
repeated across those consumers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class FieldKind(Enum):
    """How a parsed log value should be represented in a record."""

    TEXT = "text"
    NUMERIC = "numeric"


@dataclass(frozen=True)
class Field:
    """One command log label and its canonical record field name."""

    name: str
    log_label: str
    kind: FieldKind

    def pattern(self, command: str) -> str:
        """Return the regex that captures this field's raw value.

        Labels such as ``Rx Frames (All)`` contain regex metacharacters in the
        Cefore log itself, so escaping is part of the schema contract.
        """
        return rf"\[{command}\]\s+{re.escape(self.log_label)}\s*=\s*(.+)"


@dataclass(frozen=True)
class LogRecordSchema:
    """Schema for one command's parser fields and CSV column order."""

    command: str
    fields: tuple[Field, ...]

    @property
    def field_names(self) -> tuple[str, ...]:
        """Canonical parser keys in the order they should appear in CSV."""
        return tuple(field.name for field in self.fields)

    @property
    def csv_columns(self) -> tuple[str, ...]:
        """Command-specific CSV columns around the parser-owned fields."""
        return ("timestamp", *self.field_names, "success")


TEXT = FieldKind.TEXT
NUMERIC = FieldKind.NUMERIC


COMMAND_SCHEMAS: dict[str, LogRecordSchema] = {
    "cefputfile": LogRecordSchema(
        command="cefputfile",
        fields=(
            Field("uri", "URI", TEXT),
            Field("file", "File", TEXT),
            Field("rate_mbps", "Rate", NUMERIC),
            Field("block_size_bytes", "Block Size", NUMERIC),
            Field("cache_time_sec", "Cache Time", NUMERIC),
            Field("expiration_sec", "Expiration", NUMERIC),
            Field("tx_frames", "Tx Frames", NUMERIC),
            Field("tx_bytes", "Tx Bytes", NUMERIC),
            Field("duration_sec", "Duration", NUMERIC),
            Field("throughput_bps", "Throughput", NUMERIC),
        ),
    ),
    "cefgetfile": LogRecordSchema(
        command="cefgetfile",
        fields=(
            Field("uri", "URI", TEXT),
            Field("rx_frames_all", "Rx Frames (All)", NUMERIC),
            Field("rx_frames_content", "Rx Frames (ContentObject)", NUMERIC),
            Field("rx_bytes_all", "Rx Bytes (All)", NUMERIC),
            Field("rx_bytes_content", "Rx Bytes (ContentObject)", NUMERIC),
            Field("duration_sec", "Duration", NUMERIC),
            Field("throughput_bps", "Throughput", NUMERIC),
            Field("goodput_bps", "Goodput", NUMERIC),
            Field("jitter_ave_us", "Jitter (Ave)", NUMERIC),
            Field("jitter_max_us", "Jitter (Max)", NUMERIC),
            Field("jitter_var_us", "Jitter (Var)", NUMERIC),
        ),
    ),
    "cefpubfile": LogRecordSchema(
        command="cefpubfile",
        fields=(
            Field("uri", "URI", TEXT),
            Field("file", "File", TEXT),
            Field("rate_mbps", "Rate", NUMERIC),
            Field("block_size_bytes", "Block Size", NUMERIC),
            Field("cache_time_sec", "Cache Time", NUMERIC),
            Field("expiration_sec", "Expiration", NUMERIC),
        ),
    ),
    "cefsubfile": LogRecordSchema(
        command="cefsubfile",
        fields=(
            Field("uri", "URI", TEXT),
            Field("rx_frames_all", "Rx Frames (All)", NUMERIC),
            Field("rx_frames_content", "Rx Frames (ContentObject)", NUMERIC),
            Field("rx_bytes_all", "Rx Bytes (All)", NUMERIC),
            Field("rx_bytes_content", "Rx Bytes (ContentObject)", NUMERIC),
            Field("duration_sec", "Duration", NUMERIC),
            Field("throughput_bps", "Throughput", NUMERIC),
            Field("goodput_bps", "Goodput", NUMERIC),
            Field("jitter_ave_us", "Jitter (Ave)", NUMERIC),
            Field("jitter_max_us", "Jitter (Max)", NUMERIC),
            Field("jitter_var_us", "Jitter (Var)", NUMERIC),
        ),
    ),
}
