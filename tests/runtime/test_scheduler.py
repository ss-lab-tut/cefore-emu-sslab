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
