"""ResultsSink: the single seam for producing and accumulating ResultsRecords.

See CONTEXT.md (ResultsSink). Owns record construction from (Verdict + op
context) — including ``ts`` and ``publisher_down`` derivation — thread-safe
accumulation, subscriber broadcast (webui dashboard), and the results.json
write. The Monitor observation stream stays outside this sink (docs/adr/0001).
"""

import json
import threading

from ..core.records import CcninfoRecord, ContentRecord, EventRecord
from .result_detect import timestamp_utc


class ResultsSink:
    """Production adapter: accumulate records and write results.json."""

    def __init__(self):
        self._records = []
        self._lock = threading.Lock()
        self._subscribers = []

    def subscribe(self, fn):
        """Register a callable that receives each serialized record dict."""
        self._subscribers.append(fn)

    def record_content(
        self,
        op_type,
        verdict,
        *,
        host,
        uri,
        phase,
        out_file,
        log_file,
        exit_code,
        down_hosts,
        publisher_host,
    ):
        """Record one put/get/pub/sub judgment from its Verdict and op context."""
        record = ContentRecord(
            op_type=op_type,
            ts=timestamp_utc(),
            phase=phase,
            host=host,
            uri=uri,
            out_file=out_file,
            log_file=log_file,
            exit_code=exit_code,
            down_hosts=down_hosts,
            publisher_host=publisher_host,
            publisher_down=(
                publisher_host in down_hosts if publisher_host is not None else False
            ),
            success=verdict.success,
            has_completed_log=verdict.has_completed_log,
            has_output_file=verdict.has_output_file,
        )
        self._append(record.to_dict())

    def record_ccninfo(
        self,
        verdict,
        reply,
        *,
        host,
        uri,
        phase,
        log_file,
        down_hosts,
        expected_responder=None,
        expected_route=None,
    ):
        """Record one ccninfo judgment from its CcninfoVerdict, CcninfoReply, and op context."""
        # Build route dicts from the parsed CcninfoReply hops (JSON-primitive
        # values only — index/node/delay_ms — so the wire format stays
        # deserializable without custom hooks).
        route = tuple(
            {"index": hop.index, "node": hop.node, "delay_ms": hop.delay_ms}
            for hop in reply.route
        )
        record = CcninfoRecord(
            op_type="ccninfo",
            ts=timestamp_utc(),
            phase=phase,
            host=host,
            uri=uri,
            log_file=log_file,
            down_hosts=down_hosts,
            exit_code=verdict.exit_code,
            timed_out=verdict.timed_out,
            cancelled=verdict.cancelled,
            success=verdict.success,
            reply_received=verdict.reply_received,
            responder=verdict.responder,
            result=reply.result,
            rtt_ms=reply.rtt_ms,
            route=route,
            cache_lines=reply.cache_lines,
            expected_responder=expected_responder,
            expected_route=expected_route,
            responder_matched=verdict.responder_matched,
            route_matched=verdict.route_matched,
        )
        self._append(record.to_dict())

    def record_event(
        self,
        event_type,
        *,
        success,
        error,
        scheduled_at=None,
        actual_at=None,
        event=None,
        host=None,
        outcome=None,
        detail=None,
    ):
        """Record one non-content outcome (scheduler event or host flap)."""
        record = EventRecord(
            event_type=event_type,
            ts=timestamp_utc(),
            success=success,
            error=error,
            scheduled_at=scheduled_at,
            actual_at=actual_at,
            event=event,
            host=host,
            outcome=outcome,
            detail=detail,
        )
        self._append(record.to_dict())

    def _append(self, record_dict):
        with self._lock:
            self._records.append(record_dict)
        for fn in self._subscribers:
            fn(record_dict)

    @property
    def records(self):
        """Snapshot of all recorded dicts (in emission order)."""
        with self._lock:
            return list(self._records)

    def write_json(self, path):
        """Write all records to ``path`` in the frozen results.json format."""
        path.write_text(
            json.dumps(self.records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class RecordingSink(ResultsSink):
    """Recording fake adapter: same construction rules, never writes files.

    Used by tests to assert emissions and by callers that discard records
    (ConnectScenario's seed phase).
    """

    def write_json(self, path):
        raise AssertionError("RecordingSink does not write files")

    def of_type(self, op_type):
        """Records whose ``op_type`` matches (test convenience)."""
        return [r for r in self.records if r.get("op_type") == op_type]
