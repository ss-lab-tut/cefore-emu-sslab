"""Parse cefputfile / cefgetfile / cefpubfile / cefsubfile log text."""

import re
import sys
from typing import Any

from ..core.verdict import from_log
from .schema import COMMAND_SCHEMAS, FieldKind


# ---------- timestamp extraction ----------

_RE_TIMESTAMP = re.compile(r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+\[cef")


def _extract_timestamp(text: str) -> str | None:
    m = _RE_TIMESTAMP.search(text)
    return m.group(1) if m else None


# ---------- value helpers ----------


def _parse_numeric(raw: str) -> int | float:
    """Convert a numeric string to int or float."""
    try:
        return int(raw)
    except ValueError:
        return float(raw)


def _strip_unit(raw: str) -> str:
    """Strip trailing unit (Mbps, Bytes, sec, bps, us) from a value."""
    return re.sub(r"\s+(Mbps|Bytes|bytes|sec|bps|us)\s*$", "", raw.strip())


# Success judgment is the Verdict module's job (src/core/verdict.py); the
# log-only adapter `from_log` is used below. Factors invisible in log text
# (exit code, output artifacts) stay unknown, so success can be None.


def _parse_schema_fields(text: str, command: str) -> dict[str, Any]:
    """Parse all schema-owned fields for a command.

    Missing schema fields are represented as ``None`` so CSV output remains
    rectangular even when a command log is partial or failed before printing
    its statistics block.
    """
    record: dict[str, Any] = {}
    record["timestamp"] = _extract_timestamp(text)

    for field in COMMAND_SCHEMAS[command].fields:
        m = re.search(field.pattern(command), text)
        if m:
            raw = m.group(1).strip()
            if field.kind is FieldKind.TEXT:
                record[field.name] = raw
            else:
                record[field.name] = _parse_numeric(_strip_unit(raw))
        else:
            record[field.name] = None

    return record


# ---------- cefputfile ----------


def parse_cefputfile(text: str) -> dict[str, Any]:
    """Parse a cefputfile log and return a flat dict."""
    record = _parse_schema_fields(text, "cefputfile")

    fields_present = any(
        v is not None for k, v in record.items() if k not in ("timestamp", "success")
    )
    record["success"] = from_log(
        "cefputfile", text, fields_present=fields_present
    ).success
    return record


def parse_cefgetfile(text: str) -> dict[str, Any]:
    """Parse a cefgetfile log and return a flat dict."""
    record = _parse_schema_fields(text, "cefgetfile")
    record["success"] = from_log("cefgetfile", text).success
    return record


# ---------- cefpubfile / cefsubfile ----------

_RE_GENERIC_KV = re.compile(
    r"\[(cef(?:pub|sub)file)\]\s+([A-Za-z][A-Za-z0-9 ()]+?)\s*=\s*(.+)"
)


def _normalise_key(raw: str) -> str:
    """Normalise a raw key like 'Tx Frames' to 'tx_frames'."""
    return re.sub(r"\s+", "_", raw.strip().lower()).replace("(", "").replace(")", "")


def parse_cefpubfile(text: str) -> dict[str, Any]:
    """Parse a cefpubfile log and preserve schema-unknown fields."""
    return _parse_pubsub(text, "cefpubfile")


def parse_cefsubfile(text: str) -> dict[str, Any]:
    """Parse a cefsubfile log and preserve schema-unknown fields."""
    return _parse_pubsub(text, "cefsubfile")


def _parse_pubsub(text: str, command: str) -> dict[str, Any]:
    record = _parse_schema_fields(text, command)
    known_labels = {field.log_label for field in COMMAND_SCHEMAS[command].fields}

    for m in _RE_GENERIC_KV.finditer(text):
        if m.group(1) != command:
            continue
        raw_label = m.group(2)
        if raw_label in known_labels:
            continue
        key = _normalise_key(raw_label)
        raw = m.group(3).strip()
        stripped = _strip_unit(raw)
        try:
            record[key] = _parse_numeric(stripped)
        except ValueError:
            record[key] = raw
        print(
            f"warning: {command}: unknown log field '{raw_label}' "
            "(add to src/log/schema.py)",
            file=sys.stderr,
        )

    record["success"] = from_log(command, text).success
    return record


# ---------- dispatcher ----------

PARSERS: dict[str, callable] = {
    "cefputfile": parse_cefputfile,
    "cefgetfile": parse_cefgetfile,
    "cefpubfile": parse_cefpubfile,
    "cefsubfile": parse_cefsubfile,
}
