"""Contract tests for the frozen ResultsRecord wire format (CONTEXT.md)."""

from src.core.records import ContentRecord, EventRecord

# The frozen on-disk key sets. Every results.json reader (autotest analyze,
# the smoke checker, the webui dashboard) depends on these.
CONTENT_KEYS = [
    "op_type",
    "ts",
    "phase",
    "host",
    "uri",
    "out_file",
    "log_file",
    "exit_code",
    "down_hosts",
    "publisher_host",
    "publisher_down",
    "success",
    "has_completed_log",
    "has_output_file",
]
SCHEDULER_EVENT_KEYS = {
    "op_type",
    "event_type",
    "ts",
    "scheduled_at",
    "actual_at",
    "success",
    "error",
    "event",
}
FLAP_EVENT_KEYS = {"op_type", "event_type", "ts", "host", "success", "error"}


def _content_record(**overrides):
    fields = dict(
        op_type="get",
        ts="2026-06-12T00:00:00+00:00",
        phase="eval",
        host=0,
        uri="ccnx:/test/a",
        out_file="/tmp/out",
        log_file="/tmp/log",
        exit_code=0,
        down_hosts=[],
        publisher_host=9,
        publisher_down=False,
        success=True,
        has_completed_log=True,
        has_output_file=True,
    )
    fields.update(overrides)
    return ContentRecord(**fields)


class TestContentRecordWireFormat:
    def test_serializes_exactly_fourteen_keys_in_order(self):
        assert list(_content_record().to_dict().keys()) == CONTENT_KEYS

    def test_none_values_stay_present(self):
        """put/pub rows keep out_file/Factor keys with null values."""
        record = _content_record(
            op_type="put",
            out_file=None,
            success=None,
            has_completed_log=None,
            has_output_file=None,
        )
        d = record.to_dict()
        assert list(d.keys()) == CONTENT_KEYS
        assert d["out_file"] is None
        assert d["has_completed_log"] is None


class TestEventRecordWireFormat:
    def test_scheduler_variant_key_set(self):
        record = EventRecord(
            event_type="link_down",
            ts="2026-06-12T00:00:00+00:00",
            success=True,
            error=None,
            scheduled_at=5.0,
            actual_at=5.003,
            event={"at": 5, "type": "link_down", "nodes": [1, 2]},
        )
        assert set(record.to_dict().keys()) == SCHEDULER_EVENT_KEYS

    def test_flap_variant_key_set(self):
        record = EventRecord(
            event_type="host_down",
            ts="2026-06-12T00:00:00+00:00",
            success=True,
            error=None,
            host=3,
        )
        assert set(record.to_dict().keys()) == FLAP_EVENT_KEYS

    def test_op_type_is_always_event(self):
        record = EventRecord(
            event_type="host_up", ts="t", success=False, error="boom", host=1
        )
        assert record.to_dict()["op_type"] == "event"

    def test_error_is_present_even_when_none(self):
        record = EventRecord(event_type="host_up", ts="t", success=True, error=None, host=1)
        d = record.to_dict()
        assert "error" in d
        assert d["error"] is None

    def test_outcome_and_detail_serialize_when_set(self):
        """Deliberate wire-format extension: optional tri-state outcome.

        ``outcome`` uses the S7 vocabulary (ok / not-ok / skipped-no-result)
        and ``detail`` carries handler-specific evidence. Both are variant
        fields in the None-suppressed style, so records that do not set them
        stay byte-identical (covered by the key-set tests above).
        """
        record = EventRecord(
            event_type="compute_call",
            ts="t",
            success=False,
            error=None,
            scheduled_at=1.0,
            actual_at=1.001,
            event={"at": 1, "type": "compute_call"},
            outcome="skipped-no-result",
            detail={"reason": "no-external-connectivity", "curl_exit": 7},
        )
        d = record.to_dict()
        assert set(d.keys()) == SCHEDULER_EVENT_KEYS | {"outcome", "detail"}
        assert d["outcome"] == "skipped-no-result"
        assert d["detail"]["curl_exit"] == 7

    def test_outcome_and_detail_absent_by_default(self):
        record = EventRecord(event_type="link_down", ts="t", success=True, error=None)
        d = record.to_dict()
        assert "outcome" not in d
        assert "detail" not in d
