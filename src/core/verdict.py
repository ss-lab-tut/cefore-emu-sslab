"""Verdict: single source of truth for content-operation success judgment.

See CONTEXT.md (Verdict / Factor). A Factor is tri-state: ``True``, ``False``,
or ``None`` meaning unknown *or* not-applicable for the op type. ``None`` is
never a failure reason. This module is pure (no Mininet, no file IO) so the
runtime adapter (src/runtime/result_detect), the log-only CSV pipeline
(src/log/parser), and the stored-factors consumer (tools/autotest/analyze)
can all depend on it.

Pinned semantics:
- sub: a subscriber killed by the outer deadline/cancellation after content
  was delivered (``timed_out``/``cancelled``) still counts as success when a
  non-empty ``RNP0x*.out`` artifact exists.
- log-only: an empty/whitespace log means the command produced nothing and is
  judged ``False`` for every op type; a failure pattern anywhere is ``False``;
  otherwise the op's definitive Factor decides (get: completed marker,
  put: parsed result fields, pub: trigger-data-received marker on the
  success side only), and sub (and pub without the marker) stay unknown
  (``None``).
- pub delivery marker: 2026-07-07 workshop campaign logs show
  ``PUB_DELIVERED_MARKER`` in every SUCCESS run's cefpubfile log and in no
  FAILURE run. Presence is therefore treated as definitive success. Its
  absence is deliberately NOT treated as definitive failure — FAILURE runs
  produce a 0-byte cefpubfile log (process killed before any output), which
  is indistinguishable from a lost/partial log. That asymmetry is
  structural, not a gap to be closed here.
"""

from __future__ import annotations

from dataclasses import dataclass

COMPLETED_MARKER = "Completed to get all the chunks."
# Kept as its own literal (like COMPLETED_MARKER above) rather than importing
# src/log/schema.py's cefpubfile "trigger_data_received" Field: verdict.py is
# a pure judgment module with no dependency on the log-parsing package, and
# both call sites need to stay in lockstep only if Cefore's own wording
# changes, which is exactly the kind of drift a dated comment (not an import)
# is meant to catch.
PUB_DELIVERED_MARKER = "Receive Trigger Data, finish application."
FAILURE_PATTERNS = (
    "Could not receive anything",
    "Received frame ... NG",
)

# Maps cefore command names (log filenames) to Verdict op types.
COMMAND_OP_TYPES = {
    "cefputfile": "put",
    "cefgetfile": "get",
    "cefpubfile": "pub",
    "cefsubfile": "sub",
}

FactorValue = bool | None


@dataclass(frozen=True)
class Verdict:
    """Judgment of one content operation's outcome."""

    op_type: str  # "get" | "put" | "sub" | "pub"
    success: bool | None
    has_completed_log: FactorValue
    has_output_file: FactorValue
    exit_code: int | None = None
    artifact_path: str | None = None


def from_runtime_get(exit_code: int, log_text: str, output_nonempty: bool) -> Verdict:
    """Judge a cefgetfile run from exit code, log text, and output presence."""
    has_completed = COMPLETED_MARKER in log_text
    return Verdict(
        op_type="get",
        success=exit_code == 0 and has_completed and output_nonempty,
        has_completed_log=has_completed,
        has_output_file=output_nonempty,
        exit_code=exit_code,
    )


def from_runtime_put(exit_code: int) -> Verdict:
    """Judge a cefputfile run; the exit code is the only runtime evidence."""
    return Verdict(
        op_type="put",
        success=exit_code == 0,
        has_completed_log=None,
        has_output_file=None,
        exit_code=exit_code,
    )


def from_runtime_sub(
    returncode: int | None,
    timed_out: bool,
    cancelled: bool,
    output_nonempty: bool,
    artifact_path: str | None = None,
) -> Verdict:
    """Judge a cefsubfile run.

    Success requires a non-empty output artifact AND the process having either
    exited cleanly (returncode 0) or been killed by the outer
    deadline/cancellation after content was already delivered.
    """
    delivered_ok = returncode == 0 or timed_out or cancelled
    return Verdict(
        op_type="sub",
        success=output_nonempty and delivered_ok,
        has_completed_log=None,
        has_output_file=output_nonempty,
        exit_code=returncode,
        artifact_path=artifact_path,
    )


def from_runtime_pub(exit_code: int, timed_out: bool) -> Verdict:
    """Judge a cefpubfile run from exit code and the publish deadline."""
    return Verdict(
        op_type="pub",
        success=exit_code == 0 and not timed_out,
        has_completed_log=None,
        has_output_file=None,
        exit_code=exit_code,
    )


def from_log(command: str, text: str, fields_present: bool | None = None) -> Verdict:
    """Judge an operation from post-hoc log text alone (definitive-factor rule).

    Exit codes and output artifacts are not visible here, so those Factors
    stay ``None``. ``fields_present`` tells the put branch whether any
    ``[cefputfile]`` result field was parsed from the log.
    """
    op_type = COMMAND_OP_TYPES.get(command, command)
    has_completed = (COMPLETED_MARKER in text) if op_type == "get" else None

    success: bool | None
    if not text.strip():
        success = False
    elif any(pat in text for pat in FAILURE_PATTERNS):
        success = False
    elif op_type == "get":
        success = has_completed
    elif op_type == "put":
        success = None if fields_present is None else bool(fields_present)
    elif op_type == "pub":
        # Success side only (see module docstring): the marker's presence is
        # definitive, but its absence must not be read as definitive failure,
        # so unmatched pub logs fall through to the same unknown verdict sub
        # gets below.
        success = True if PUB_DELIVERED_MARKER in text else None
    else:  # sub: no in-log definitive Factor
        success = None

    return Verdict(
        op_type=op_type,
        success=success,
        has_completed_log=has_completed,
        has_output_file=None,
        exit_code=None,
    )


def from_record(record: dict) -> Verdict:
    """Rehydrate a Verdict from a stored results.json record.

    Stored Factors are authoritative; anything that is not a bool (missing or
    ``null``) is unknown. No file probing happens here — legacy records that
    predate stored Factors are the caller's concern.
    """

    def _factor(key: str) -> FactorValue:
        value = record.get(key)
        return value if isinstance(value, bool) else None

    exit_code = record.get("exit_code")
    return Verdict(
        op_type=record.get("op_type") or "get",
        success=_factor("success"),
        has_completed_log=_factor("has_completed_log"),
        has_output_file=_factor("has_output_file"),
        exit_code=exit_code if isinstance(exit_code, int) else None,
        artifact_path=None,
    )


def failure_reasons(verdict: Verdict) -> dict[str, bool]:
    """Known-False Factors only; ``None`` (unknown/not-applicable) never counts."""
    return {
        "exit_code_nonzero": verdict.exit_code is not None and verdict.exit_code != 0,
        "missing_completed_log": verdict.has_completed_log is False,
        "missing_output_file": verdict.has_output_file is False,
    }
