"""Tests for the ResultsSink seam (CONTEXT.md: ResultsSink)."""

import json
import threading

import pytest

from src.core.verdict import Verdict
from src.runtime.results_sink import RecordingSink, ResultsSink


def _get_verdict(success=True):
    return Verdict(
        op_type="get",
        success=success,
        has_completed_log=success,
        has_output_file=success,
        exit_code=0 if success else 1,
    )


def _record_one(sink, *, down_hosts=None, publisher_host=9, host=0):
    sink.record_content(
        "get",
        _get_verdict(),
        host=host,
        uri="ccnx:/test/a",
        phase="eval",
        out_file="/tmp/out",
        log_file="/tmp/log",
        exit_code=0,
        down_hosts=down_hosts if down_hosts is not None else [],
        publisher_host=publisher_host,
    )


class TestRecordContent:
    def test_verdict_factors_are_unpacked(self):
        sink = ResultsSink()
        _record_one(sink)
        rec = sink.records[0]
        assert rec["op_type"] == "get"
        assert rec["success"] is True
        assert rec["has_completed_log"] is True
        assert rec["has_output_file"] is True

    def test_ts_is_derived_by_the_sink(self):
        sink = ResultsSink()
        _record_one(sink)
        # ISO-8601 UTC timestamp, same shape as result_detect.timestamp_utc().
        assert "T" in sink.records[0]["ts"]
        assert "+00:00" in sink.records[0]["ts"]

    def test_publisher_down_derived_from_down_hosts(self):
        sink = ResultsSink()
        _record_one(sink, down_hosts=[9], publisher_host=9)
        _record_one(sink, down_hosts=[1], publisher_host=9)
        _record_one(sink, down_hosts=[1], publisher_host=None)
        downs = [r["publisher_down"] for r in sink.records]
        assert downs == [True, False, False]


class TestRecordEvent:
    def test_scheduler_event_record(self):
        sink = ResultsSink()
        sink.record_event(
            "link_down",
            success=True,
            error=None,
            scheduled_at=5.0,
            actual_at=5.001,
            event={"type": "link_down", "nodes": [1, 2]},
        )
        rec = sink.records[0]
        assert rec["op_type"] == "event"
        assert rec["scheduled_at"] == 5.0
        assert "host" not in rec

    def test_flap_event_record(self):
        sink = ResultsSink()
        sink.record_event("host_down", success=False, error="veth gone", host=3)
        rec = sink.records[0]
        assert rec["host"] == 3
        assert rec["error"] == "veth gone"
        assert "scheduled_at" not in rec
        assert "event" not in rec


class TestSinkOwnership:
    def test_subscribe_broadcasts_serialized_dicts(self):
        sink = ResultsSink()
        seen = []
        sink.subscribe(seen.append)
        _record_one(sink)
        sink.record_event("host_up", success=True, error=None, host=1)
        assert len(seen) == 2
        assert seen[0]["op_type"] == "get"
        assert seen[1]["op_type"] == "event"

    def test_write_json_round_trip(self, tmp_path):
        sink = ResultsSink()
        _record_one(sink)
        sink.record_event("host_down", success=True, error=None, host=2)
        path = tmp_path / "results.json"
        sink.write_json(path)
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded == sink.records

    def test_concurrent_recording_loses_nothing(self):
        sink = ResultsSink()
        threads = [
            threading.Thread(target=lambda: [_record_one(sink) for _ in range(50)])
            for _ in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(sink.records) == 200


class TestRecordingSink:
    def test_never_writes_files(self, tmp_path):
        sink = RecordingSink()
        _record_one(sink)
        with pytest.raises(AssertionError):
            sink.write_json(tmp_path / "results.json")

    def test_of_type_filters(self):
        sink = RecordingSink()
        _record_one(sink)
        sink.record_event("host_up", success=True, error=None, host=1)
        assert len(sink.of_type("get")) == 1
        assert len(sink.of_type("event")) == 1
