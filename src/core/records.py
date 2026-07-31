"""ResultsRecord: the tagged union of judgment records written to results.json.

See CONTEXT.md (ResultsRecord / ResultsSink). The on-disk key sets are
frozen — every reader (autotest analyze, the smoke checker, the webui
dashboard) depends on them:

- ``ContentRecord`` always serializes its 14 keys (``None`` -> ``null``).
- ``CcninfoRecord`` always serializes its 21 keys (``None`` -> ``null``).
- ``EventRecord`` always serializes ``op_type``/``event_type``/``ts``/
  ``success``/``error`` and includes a variant field only when it is not
  ``None``: ``scheduled_at``/``actual_at``/``event`` for scheduler events,
  ``host`` for host-flap events, and ``outcome``/``detail`` for handlers
  that report a tri-state outcome (S7 vocabulary: ok / not-ok /
  skipped-no-result) with structured evidence. Records that do not set
  them serialize byte-identically to the pre-extension format.

This module is pure data; construction (``ts``/``publisher_down``
derivation) is owned by the ResultsSink (src/runtime/results_sink.py).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ContentRecord:
    """One put/get/pub/sub judgment row (14 fixed keys, Verdict Factors inline)."""

    op_type: str  # "put" | "get" | "pub" | "sub"
    ts: str
    phase: str
    host: int
    uri: str
    out_file: str | None
    log_file: str
    exit_code: int | None
    down_hosts: list[int]
    publisher_host: int | None
    publisher_down: bool
    success: bool | None
    has_completed_log: bool | None
    has_output_file: bool | None

    def to_dict(self) -> dict:
        """Serialize with all 14 keys present, in field order."""
        return asdict(self)


@dataclass(frozen=True)
class EventRecord:
    """One non-content outcome row (scheduler event or host flap)."""

    event_type: str
    ts: str
    success: bool
    error: str | None
    op_type: str = "event"
    # Scheduler-event variant only:
    scheduled_at: float | None = None
    actual_at: float | None = None
    event: dict | None = None
    # Host-flap variant only:
    host: int | None = None
    # Tri-state outcome variant (S7: ok / not-ok / skipped-no-result), with
    # handler-specific evidence in detail. skipped-no-result separates
    # environment problems (endpoint unreachable) from experiment failures.
    outcome: str | None = None
    detail: dict | None = None

    def to_dict(self) -> dict:
        """Serialize; variant fields are included only when not ``None``."""
        record: dict = {"op_type": self.op_type, "event_type": self.event_type, "ts": self.ts}
        if self.scheduled_at is not None:
            record["scheduled_at"] = self.scheduled_at
        if self.actual_at is not None:
            record["actual_at"] = self.actual_at
        if self.host is not None:
            record["host"] = self.host
        record["success"] = self.success
        record["error"] = self.error
        if self.outcome is not None:
            record["outcome"] = self.outcome
        if self.detail is not None:
            record["detail"] = self.detail
        if self.event is not None:
            record["event"] = self.event
        return record


@dataclass(frozen=True)
class CcninfoRecord:
    """One ccninfo judgment row (21 fixed keys, CcninfoVerdict factors inline).

    Kept separate from ContentRecord: ccninfo carries route/responder evidence
    and match factors that no put/get/pub/sub row has, and ContentRecord's
    publisher_down/has_completed_log/has_output_file factors are meaningless for
    a cache-discovery probe. Forcing both into one shape would mean always-None
    columns in every row of one or the other variant.
    """

    op_type: str  # always "ccninfo"
    ts: str
    phase: str
    host: int
    uri: str
    log_file: str | None
    down_hosts: list[int]
    exit_code: int | None
    timed_out: bool
    cancelled: bool
    success: bool
    reply_received: bool
    responder: str | None
    result: str | None
    rtt_ms: float | None
    route: tuple[dict, ...]
    cache_lines: tuple[str, ...]
    expected_responder: str | None
    expected_route: tuple[str, ...] | None
    responder_matched: bool | None
    route_matched: bool | None

    def to_dict(self) -> dict:
        """Serialize with all 21 keys present, in field order."""
        return asdict(self)


ResultsRecord = ContentRecord | CcninfoRecord | EventRecord
