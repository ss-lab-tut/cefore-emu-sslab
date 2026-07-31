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

CcninfoVerdict (below) judges cefinfo/ccninfo runs and is deliberately kept
separate from Verdict: ccninfo has no log-CSV pipeline membership (no
from_log/from_record variant, no COMMAND_OP_TYPES entry) — its evidence is
runtime-only (reply/responder/route), so there is nothing for the log-only
path to parse.
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


@dataclass(frozen=True)
class CcninfoVerdict:
    """Judgment of one cefinfo (ccninfo) run.

    Kept as its own dataclass rather than a Verdict op_type variant: ccninfo
    carries evidence (responder identity, hop route) that no other op type
    has a slot for, and its two match Factors (responder_matched,
    route_matched) are each conditioned on an *expected* value the caller
    supplies per-run, not on a fixed per-op-type rule the way get/put/pub/sub
    are. Matching is exact equality (``==``), not substring. Forcing it into
    Verdict's shape would mean bolting on fields every other op_type carries
    as always-None.
    """

    success: bool
    reply_received: bool
    responder_matched: bool | None
    route_matched: bool | None
    exit_code: int | None
    timed_out: bool
    cancelled: bool
    responder: str | None
    route_nodes: tuple[str, ...]


def _route_is_ordered_subsequence(
    expected: tuple[str, ...], observed: tuple[str, ...]
) -> bool:
    """True iff each ``expected`` token equals an ``observed`` hop's node
    string exactly, in order, with gaps allowed (an ordered-subsequence
    check with exact per-hop equality, not substring matching).

    # 2026-07-27 external review: NODE_NAME=hN is guaranteed by provisioning
    # (template.py _set_config_value), so exact equality is unambiguous;
    # bare substring false-greened "h1" against "h10". Changed from `in` to
    # `==`.

    A greedy left-to-right two-pointer scan is sufficient here: for
    subsequence existence, matching a token to the *earliest* remaining
    observed hop can never make a later token harder to match than matching
    it to a later hop would (matching later only removes options for tokens
    still to come). This is why we advance ``pos`` past a matched hop and
    never backtrack.
    """
    pos = 0
    for token in expected:
        while pos < len(observed) and token != observed[pos]:
            pos += 1
        if pos == len(observed):
            return False
        pos += 1  # this hop is consumed by `token`; later tokens must match after it
    return True


def from_runtime_ccninfo(
    exit_code: int | None,
    timed_out: bool,
    cancelled: bool,
    reply_received: bool,
    responder: str | None,
    route_nodes: tuple[str, ...],
    expected_responder: str | None,
    expected_route: tuple[str, ...] | None,
) -> CcninfoVerdict:
    """Judge a cefinfo (ccninfo) run from runtime evidence and (optional) expectations.

    ``expected_responder``/``expected_route`` are ``None`` when the caller made
    no claim about them — in that case the corresponding match Factor stays
    ``None`` (unknown/not-applicable) and, per the tri-state rule shared with
    Verdict, never drags ``success`` down. When an expectation *is* given,
    matching is exact equality (``==``), not substring: NODE_NAME=hN is
    guaranteed by provisioning, so exact equality is unambiguous. Only an
    explicit mismatch (``False``) can fail the run; a ``None`` match factor
    from the *other* expectation still can't.
    """
    responder_matched: bool | None
    if expected_responder is None:
        responder_matched = None
    else:
        # 2026-07-27 external review: exact equality replaces substring
        # matching (NODE_NAME=hN is guaranteed by provisioning, so exact
        # equality is unambiguous; bare substring false-greened "h1" against
        # "h10"). A None responder (no reply attributed) is a definite
        # mismatch (False), not an open question.
        responder_matched = (responder == expected_responder)

    route_matched: bool | None
    if expected_route is None:
        route_matched = None
    else:
        # An empty expected_route (()) is trivially a subsequence of anything
        # — the ordered-subsequence loop below simply never runs and returns
        # True. We don't special-case or reject it here: the caller-facing
        # validator is responsible for rejecting a meaningless empty
        # expectation before it reaches this pure judgment function, and
        # duplicating that guard here would just be two places to keep in
        # sync for no judgment-logic benefit.
        route_matched = _route_is_ordered_subsequence(expected_route, route_nodes)

    success = (
        exit_code == 0
        and not timed_out
        and not cancelled
        and reply_received
        and responder_matched is not False
        and route_matched is not False
    )

    return CcninfoVerdict(
        success=success,
        reply_received=reply_received,
        responder_matched=responder_matched,
        route_matched=route_matched,
        exit_code=exit_code,
        timed_out=timed_out,
        cancelled=cancelled,
        responder=responder,
        route_nodes=route_nodes,
    )


def ccninfo_failure_reasons(v: CcninfoVerdict) -> dict[str, bool]:
    """Known-bad factors only; a key appears iff that factor actually failed.

    Unlike ``failure_reasons()`` above (which always emits all its keys, with
    ``False`` standing in for "not this reason"), ccninfo has six independent
    judgment inputs rather than three, so a verdict that failed for one
    reason would otherwise force callers to filter a wall of ``False``s to
    find it. ``None`` (unset expectation) still never counts as bad, matching
    the tri-state rule shared with ``failure_reasons()``.
    """
    reasons: dict[str, bool] = {}
    if v.exit_code is not None and v.exit_code != 0:
        reasons["exit_code_nonzero"] = True
    if v.timed_out:
        reasons["timed_out"] = True
    if v.cancelled:
        reasons["cancelled"] = True
    if not v.reply_received:
        reasons["no_reply"] = True
    if v.responder_matched is False:
        reasons["responder_mismatch"] = True
    if v.route_matched is False:
        reasons["route_mismatch"] = True
    return reasons
