"""Parse cefputfile / cefgetfile / cefpubfile / cefsubfile log text."""

import re
from typing import Any

from ..core.verdict import from_log


# ---------- timestamp extraction ----------

_RE_TIMESTAMP = re.compile(
    r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+\[cef"
)


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


# ---------- cefputfile ----------

_PUT_FIELDS = {
    "uri": (r"\[cefputfile\]\s+URI\s*=\s*(.+)", str),
    "file": (r"\[cefputfile\]\s+File\s*=\s*(.+)", str),
    "rate_mbps": (r"\[cefputfile\]\s+Rate\s*=\s*(.+)", None),
    "block_size_bytes": (r"\[cefputfile\]\s+Block Size\s*=\s*(.+)", None),
    "cache_time_sec": (r"\[cefputfile\]\s+Cache Time\s*=\s*(.+)", None),
    "expiration_sec": (r"\[cefputfile\]\s+Expiration\s*=\s*(.+)", None),
    "tx_frames": (r"\[cefputfile\]\s+Tx Frames\s*=\s*(.+)", None),
    "tx_bytes": (r"\[cefputfile\]\s+Tx Bytes\s*=\s*(.+)", None),
    "duration_sec": (r"\[cefputfile\]\s+Duration\s*=\s*(.+)", None),
    "throughput_bps": (r"\[cefputfile\]\s+Throughput\s*=\s*(.+)", None),
}


def parse_cefputfile(text: str) -> dict[str, Any]:
    """Parse a cefputfile log and return a flat dict."""
    record: dict[str, Any] = {}
    record["timestamp"] = _extract_timestamp(text)

    for key, (pattern, conv) in _PUT_FIELDS.items():
        m = re.search(pattern, text)
        if m:
            raw = m.group(1).strip()
            if conv is str:
                record[key] = raw
            else:
                record[key] = _parse_numeric(_strip_unit(raw))
        else:
            record[key] = None

    fields_present = any(
        v is not None for k, v in record.items() if k not in ("timestamp", "success")
    )
    record["success"] = from_log("cefputfile", text, fields_present=fields_present).success
    return record


# ---------- cefgetfile ----------

_GET_FIELDS = {
    "uri": (r"\[cefgetfile\]\s+URI\s*=\s*(.+)", str),
    "rx_frames_all": (r"\[cefgetfile\]\s+Rx Frames \(All\)\s*=\s*(.+)", None),
    "rx_frames_content": (
        r"\[cefgetfile\]\s+Rx Frames \(ContentObject\)\s*=\s*(.+)",
        None,
    ),
    "rx_bytes_all": (r"\[cefgetfile\]\s+Rx Bytes \(All\)\s*=\s*(.+)", None),
    "rx_bytes_content": (
        r"\[cefgetfile\]\s+Rx Bytes \(ContentObject\)\s*=\s*(.+)",
        None,
    ),
    "duration_sec": (r"\[cefgetfile\]\s+Duration\s*=\s*(.+)", None),
    "throughput_bps": (r"\[cefgetfile\]\s+Throughput\s*=\s*(.+)", None),
    "goodput_bps": (r"\[cefgetfile\]\s+Goodput\s*=\s*(.+)", None),
    "jitter_ave_us": (r"\[cefgetfile\]\s+Jitter \(Ave\)\s*=\s*(.+)", None),
    "jitter_max_us": (r"\[cefgetfile\]\s+Jitter \(Max\)\s*=\s*(.+)", None),
    "jitter_var_us": (r"\[cefgetfile\]\s+Jitter \(Var\)\s*=\s*(.+)", None),
}


def parse_cefgetfile(text: str) -> dict[str, Any]:
    """Parse a cefgetfile log and return a flat dict."""
    record: dict[str, Any] = {}
    record["timestamp"] = _extract_timestamp(text)

    for key, (pattern, conv) in _GET_FIELDS.items():
        m = re.search(pattern, text)
        if m:
            raw = m.group(1).strip()
            if conv is str:
                record[key] = raw
            else:
                record[key] = _parse_numeric(_strip_unit(raw))
        else:
            record[key] = None

    record["success"] = from_log("cefgetfile", text).success
    return record


# ---------- generic cefpubfile / cefsubfile ----------

_RE_GENERIC_KV = re.compile(
    r"\[(cef(?:pub|sub)file)\]\s+([A-Za-z][A-Za-z0-9 ()]+?)\s*=\s*(.+)"
)


def _normalise_key(raw: str) -> str:
    """Normalise a raw key like 'Tx Frames' to 'tx_frames'."""
    return re.sub(r"\s+", "_", raw.strip().lower()).replace("(", "").replace(")", "")


def parse_cefpubfile(text: str) -> dict[str, Any]:
    """Parse a cefpubfile log dynamically."""
    return _parse_generic(text, "cefpubfile")


def parse_cefsubfile(text: str) -> dict[str, Any]:
    """Parse a cefsubfile log dynamically."""
    return _parse_generic(text, "cefsubfile")


def _parse_generic(text: str, command: str) -> dict[str, Any]:
    record: dict[str, Any] = {}
    record["timestamp"] = _extract_timestamp(text)

    uri_m = re.search(rf"\[{command}\]\s+URI\s*=\s*(.+)", text)
    record["uri"] = uri_m.group(1).strip() if uri_m else None

    for m in _RE_GENERIC_KV.finditer(text):
        if m.group(1) != command:
            continue
        key = _normalise_key(m.group(2))
        if key == "uri":
            continue
        raw = m.group(3).strip()
        stripped = _strip_unit(raw)
        try:
            record[key] = _parse_numeric(stripped)
        except ValueError:
            record[key] = raw

    record["success"] = from_log(command, text).success
    return record


# ---------- dispatcher ----------

PARSERS: dict[str, callable] = {
    "cefputfile": parse_cefputfile,
    "cefgetfile": parse_cefgetfile,
    "cefpubfile": parse_cefpubfile,
    "cefsubfile": parse_cefsubfile,
}
