"""Unit tests for event scheduler."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from src.runtime.scheduler import EventScheduler, _EVENT_PRIORITY


def _make_net(host_count=3):
    net = MagicMock()
    host = MagicMock()
    host.cmd.return_value = ""
    net.hosts = [host] * host_count
    net.get.return_value = host
    return net


class TestEventScheduler:
    def test_events_execute_in_time_order(self):
        fired = []
        net = _make_net()

        def record_handler(net, ev, ml, ctx):
            fired.append(ev["label"])

        events = [
            {"at": 0.2, "type": "test", "label": "second"},
            {"at": 0.1, "type": "test", "label": "first"},
        ]
        with patch.dict("src.runtime.scheduler._EVENT_HANDLERS", {"test": record_handler}):
            sched = EventScheduler(net, events)
            sched.start()
            sched.wait_all(timeout=3)
        assert fired == ["first", "second"]

    def test_same_time_priority_ordering(self):
        fired = []
        net = _make_net()

        def record_handler(net, ev, ml, ctx):
            fired.append(ev["type"])

        events = [
            {"at": 0.0, "type": "pubsub_pub"},
            {"at": 0.0, "type": "pubsub_sub"},
        ]
        with patch.dict(
            "src.runtime.scheduler._EVENT_HANDLERS",
            {"pubsub_sub": record_handler, "pubsub_pub": record_handler},
        ):
            sched = EventScheduler(net, events)
            sched.start()
            sched.wait_all(timeout=3)
        assert fired[0] == "pubsub_sub"
        assert fired[1] == "pubsub_pub"

    def test_stop_event_interrupts_waiting(self):
        net = _make_net()
        events = [{"at": 999, "type": "link_down", "nodes": [0, 1]}]
        with patch("src.runtime.scheduler.link_down"):
            sched = EventScheduler(net, events)
            sched.start()
            sched.stop()
            assert sched._thread is not None
            assert not sched._thread.is_alive()

    def test_unknown_event_type_logs_warning(self):
        net = _make_net()
        events = [{"at": 0.0, "type": "bogus_type"}]
        sched = EventScheduler(net, events)
        sched.start()
        sched.wait_all(timeout=3)

    def test_repeat_with_interval_reschedules(self):
        fired_count = []
        net = _make_net()

        def counting_handler(net, ev, ml, ctx):
            fired_count.append(1)

        events = [
            {
                "at": 0.0,
                "type": "test",
                "repeat": {"interval": 0.05, "count": 3},
            }
        ]
        with patch.dict("src.runtime.scheduler._EVENT_HANDLERS", {"test": counting_handler}):
            sched = EventScheduler(net, events)
            sched.start()
            sched.wait_all(timeout=5)
        assert len(fired_count) == 3

    def test_repeat_with_duration_generates_restore(self):
        fired_types = []
        net = _make_net()

        def record_handler(net, ev, ml, ctx):
            fired_types.append(ev["type"])

        events = [
            {
                "at": 0.0,
                "type": "test_down",
                "repeat": {"duration": 0.05, "restore_type": "test_up"},
            }
        ]
        with patch.dict(
            "src.runtime.scheduler._EVENT_HANDLERS",
            {"test_down": record_handler, "test_up": record_handler},
        ):
            sched = EventScheduler(net, events)
            sched.start()
            sched.wait_all(timeout=3)
        assert "test_down" in fired_types
        assert "test_up" in fired_types

    def test_empty_events_start_is_noop(self):
        net = _make_net()
        sched = EventScheduler(net, [])
        sched.start()
        assert sched._thread is None

    def test_wait_all_returns_after_completion(self):
        fired = []
        net = _make_net()

        def handler(net, ev, ml, ctx):
            fired.append(1)

        events = [{"at": 0.0, "type": "test"}]
        with patch.dict("src.runtime.scheduler._EVENT_HANDLERS", {"test": handler}):
            sched = EventScheduler(net, events)
            sched.start()
            start = time.monotonic()
            completed = sched.wait_all(timeout=5)
            elapsed = time.monotonic() - start
        assert len(fired) == 1
        assert completed is True
        assert elapsed < 3

    def test_wait_all_reports_unfired_event_deadline(self):
        sched = EventScheduler(
            _make_net(), [{"at": 30, "type": "link_down", "nodes": [0, 1]}]
        )
        sched.start()
        assert sched.wait_all(timeout=0.01) is False
        sched.stop()

    def test_shared_start_time_executes_late_event_immediately(self):
        fired = []
        net = _make_net()

        def handler(net, ev, ml, ctx):
            fired.append(time.monotonic())

        with patch.dict("src.runtime.scheduler._EVENT_HANDLERS", {"test": handler}):
            sched = EventScheduler(
                net,
                [{"at": 0.1, "type": "test"}],
                start_time=time.monotonic() - 1,
            )
            before = time.monotonic()
            sched.start()
            assert sched.wait_all(timeout=1) is True
        assert fired[0] - before < 0.2


class TestEventOutcomeRecords:
    """Non-content events emit outcome records into the results sink (K)."""

    def _run_one(self, event, handler, handlers_key="test"):
        records = []
        net = _make_net()
        with patch.dict(
            "src.runtime.scheduler._EVENT_HANDLERS", {handlers_key: handler}
        ):
            sched = EventScheduler(net, [event], result_callback=records.append)
            sched.start()
            sched.wait_all(timeout=3)
        return records

    def test_success_record(self):
        event = {"at": 0.0, "type": "test", "nodes": [0, 1]}
        records = self._run_one(event, lambda net, ev, ml, ctx: None)
        assert len(records) == 1
        rec = records[0]
        assert rec["op_type"] == "event"
        assert rec["event_type"] == "test"
        assert rec["success"] is True
        assert rec["error"] is None
        assert rec["scheduled_at"] == 0.0
        assert rec["event"]["nodes"] == [0, 1]

    def test_handler_false_is_failure(self):
        records = self._run_one(
            {"at": 0.0, "type": "test"}, lambda net, ev, ml, ctx: False
        )
        assert records[0]["success"] is False
        assert records[0]["error"] == "handler reported failure"

    def test_handler_exception_is_failure(self):
        def boom(net, ev, ml, ctx):
            raise ValueError("link not found")

        records = self._run_one({"at": 0.0, "type": "test"}, boom)
        assert records[0]["success"] is False
        assert "link not found" in records[0]["error"]

    def test_content_events_are_not_recorded(self):
        # Content ops get their own Verdict records from ContentOperationRunner.
        records = self._run_one(
            {"at": 0.0, "type": "get", "host": 0, "uri": "ccnx:/a"},
            lambda net, ev, ml, ctx: None,
            handlers_key="get",
        )
        assert records == []

    def test_repeat_key_excluded_from_record(self):
        event = {
            "at": 0.0,
            "type": "test",
            "repeat": {"interval": 0.05, "count": 1},
        }
        records = self._run_one(event, lambda net, ev, ml, ctx: None)
        assert "repeat" not in records[0]["event"]

    def test_no_callback_is_noop(self):
        net = _make_net()
        with patch.dict(
            "src.runtime.scheduler._EVENT_HANDLERS",
            {"test": lambda net, ev, ml, ctx: None},
        ):
            sched = EventScheduler(net, [{"at": 0.0, "type": "test"}])
            sched.start()
            assert sched.wait_all(timeout=3) is True
