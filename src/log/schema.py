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
    # 2026-07-07: cefpubfile emits some events as bare protocol marker lines
    # (e.g. "[cefpubfile] Send Trigger Interest.") rather than "KEY = value"
    # pairs. MARKER fields record presence/absence of the exact line as a
    # bool instead of parsing a captured value.
    MARKER = "marker"


@dataclass(frozen=True)
class Field:
    """One command log label and its canonical record field name.

    ``log_label`` means different things depending on ``kind``: for TEXT/
    NUMERIC fields it is the key half of a "KEY = value" line; for MARKER
    fields it is the entire literal line (there is no value half to parse).
    """

    name: str
    log_label: str
    kind: FieldKind

    def pattern(self, command: str) -> str:
        """Return the regex that detects or captures this field.

        Labels such as ``Rx Frames (All)`` contain regex metacharacters in the
        Cefore log itself, so escaping is part of the schema contract.

        MARKER fields have no "= value" suffix to require — Cefore prints
        them as standalone sentences — so the pattern only needs to prove the
        line occurred anywhere in the text; presence is the entire signal.
        """
        if self.kind is FieldKind.MARKER:
            return rf"\[{command}\]\s+{re.escape(self.log_label)}"
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
MARKER = FieldKind.MARKER


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
            # 2026-07-07: archived workshop campaign logs (logs/workshop_20260707/)
            # show these two literal lines appear in every SUCCESS run's
            # cefpubfile log and nowhere else; there is no KEY=value retry
            # counter or label to parse instead. FAILURE runs have a 0-byte
            # cefpubfile log (process killed by SIGTERM before any output), so
            # absence of these markers is NOT proof the trigger round-trip
            # failed — it is equally consistent with the log never being
            # flushed. Treat False as "not observed", never as "did not
            # happen".
            Field("trigger_interest_sent", "Send Trigger Interest.", MARKER),
            Field(
                "trigger_data_received",
                "Receive Trigger Data, finish application.",
                MARKER,
            ),
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
