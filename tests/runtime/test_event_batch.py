"""Tests for the run_event_batch runtime seam."""

import time
from unittest.mock import MagicMock, patch

import pytest

from src.runtime.command_runner import FakeCommandRunner
from src.runtime.content_ops import ContentOperationRunner
from src.runtime.event_batch import (
    EventBatchSpec,
    EventBatchResult,
    run_event_batch,
)
from src.runtime.results_sink import RecordingSink
from src.runtime.scheduler import EventScheduler


def _spec(tmp_path, events, **overrides):
    flap_state = MagicMock()
    flap_state.snapshot.return_value = []
    values = {
        "events": events,
        "run_dir": tmp_path,
        "mesh_links": [],
        "sink": RecordingSink(),
        "flap_state": flap_state,
        "startup_grace": 0,
        **overrides,
    }
    return EventBatchSpec(**values)


def _put_event(at=0.0, uri="ccnx:/test/seed"):
    return {
        "at": at,
        "type": "put",
        "host": 1,
        "uri": uri,
        "file": "./sample-putfile",
    }


def _sub_event(at=0.0, uri="ccnx:/test/live"):
    return {"at": at, "type": "pubsub_sub", "host": 1, "uri": uri}


def _delayed_link_event(at=5.0):
    return {"at": at, "type": "link_down", "nodes": [0, 1]}


def test_deferred_events_start_runner_and_scheduler(tmp_path):
    fake = FakeCommandRunner()
    result = run_event_batch(
        MagicMock(),
        _spec(tmp_path, [_put_event(at=5)], command_runner=fake),
    )

    try:
        assert isinstance(result, EventBatchResult)
        assert result.content_runner is not None
        assert result.event_scheduler is not None
        assert result.completed is None
        assert result.failures == []
        assert result.content_runner._thread.is_alive()
        assert result.event_scheduler._thread is not None
        assert result.event_scheduler._thread.is_alive()
    finally:
        result.event_scheduler.stop()
        result.content_runner.stop()


def test_deferred_non_content_events_have_scheduler_without_runner(tmp_path):
    result = run_event_batch(MagicMock(), _spec(tmp_path, [_delayed_link_event()]))

    try:
        assert result.content_runner is None
        assert result.event_scheduler is not None
        assert result.completed is None
        assert result.failures == []
    finally:
        result.event_scheduler.stop()


def test_empty_events_return_without_handles(tmp_path):
    result = run_event_batch(MagicMock(), _spec(tmp_path, []))

    assert result.content_runner is None
    assert result.event_scheduler is None
    assert result.completed is None
    assert result.failures == []


def test_sync_warn_completed_batch_stops_both(tmp_path):
    fake = FakeCommandRunner()
    result = run_event_batch(
        MagicMock(),
        _spec(tmp_path, [_put_event()], command_runner=fake, wait_timeout=10),
    )

    assert result.completed is True
    assert result.failures == []
    assert fake.runs[0]["argv"][0] == "cefputfile"
    assert result.event_scheduler._thread is not None
    assert not result.event_scheduler._thread.is_alive()
    assert not result.content_runner._thread.is_alive()


def test_sync_warn_scheduler_miss_still_waits_runner(tmp_path):
    fake = FakeCommandRunner()
    messages = []

    with patch("src.runtime.event_batch.info", side_effect=messages.append):
        result = run_event_batch(
            MagicMock(),
            _spec(
                tmp_path,
                [_sub_event(), _delayed_link_event()],
                command_runner=fake,
                wait_timeout=0.2,
                scheduler_label="publication event scheduling",
                runner_label="publication seed operations",
            ),
        )

    assert result.completed is False
    assert result.failures == []
    assert messages == ["[warning] publication event scheduling exceeded 0s deadline\n"]
    assert fake.wait_calls
    assert fake.wait_calls[0]["deadline"] > time.monotonic()


def test_sync_raise_scheduler_miss_skips_runner_wait_but_stops(tmp_path):
    fake = FakeCommandRunner()

    with pytest.raises(RuntimeError) as excinfo:
        run_event_batch(
            MagicMock(),
            _spec(
                tmp_path,
                [_sub_event(), _delayed_link_event()],
                command_runner=fake,
                wait_timeout=0.2,
                deadline_policy="raise",
                scheduler_label="seed event scheduling",
                runner_label="seed content operations",
            ),
        )

    assert str(excinfo.value) == "seed event scheduling exceeded 0s deadline"
    assert fake.wait_calls
    assert fake.wait_calls[0]["deadline"] <= time.monotonic()


def test_stop_failures_are_independent_and_aggregated(monkeypatch, tmp_path):
    original_scheduler_stop = EventScheduler.stop
    original_runner_stop = ContentOperationRunner.stop

    def scheduler_stop_then_raise(self):
        original_scheduler_stop(self)
        raise RuntimeError("scheduler stop failed")

    def runner_stop_then_raise(self):
        original_runner_stop(self)
        raise ValueError("runner stop failed")

    monkeypatch.setattr(EventScheduler, "stop", scheduler_stop_then_raise)
    monkeypatch.setattr(ContentOperationRunner, "stop", runner_stop_then_raise)

    result = run_event_batch(
        MagicMock(),
        _spec(
            tmp_path,
            [_put_event()],
            command_runner=FakeCommandRunner(),
            wait_timeout=10,
        ),
    )

    assert result.completed is True
    assert [stage for stage, _ in result.failures] == [
        "scheduler.stop",
        "runner.stop",
    ]
    assert [str(exc) for _, exc in result.failures] == [
        "scheduler stop failed",
        "runner stop failed",
    ]


def test_wait_exception_still_stops_both(monkeypatch, tmp_path):
    stops = {"scheduler": False, "runner": False}
    original_scheduler_stop = EventScheduler.stop
    original_runner_stop = ContentOperationRunner.stop

    def scheduler_wait_raises(self, timeout=None):
        raise RuntimeError("scheduler wait failed")

    def record_scheduler_stop(self):
        stops["scheduler"] = True
        original_scheduler_stop(self)

    def record_runner_stop(self):
        stops["runner"] = True
        original_runner_stop(self)

    monkeypatch.setattr(EventScheduler, "wait_all", scheduler_wait_raises)
    monkeypatch.setattr(EventScheduler, "stop", record_scheduler_stop)
    monkeypatch.setattr(ContentOperationRunner, "stop", record_runner_stop)

    with pytest.raises(RuntimeError, match="scheduler wait failed"):
        run_event_batch(
            MagicMock(),
            _spec(
                tmp_path,
                [_put_event()],
                command_runner=FakeCommandRunner(),
                wait_timeout=10,
            ),
        )

    assert stops == {"scheduler": True, "runner": True}


def test_pub_lifetime_by_uri_is_derived_from_pubsub_pub_events(tmp_path):
    result = run_event_batch(
        MagicMock(),
        _spec(
            tmp_path,
            [
                {
                    "at": 5,
                    "type": "pubsub_pub",
                    "host": 2,
                    "uri": "ccnx:/test/live",
                    "file": "./sample-putfile",
                    "pub_opts": {"lifetime": 7},
                }
            ],
            command_runner=FakeCommandRunner(),
        ),
    )

    try:
        assert result.content_runner._pub_lifetime_by_uri == {"ccnx:/test/live": 7}
    finally:
        result.event_scheduler.stop()
        result.content_runner.stop()


def test_phase_and_start_time_pass_through_to_collaborators(tmp_path):
    origin = time.monotonic()
    result = run_event_batch(
        MagicMock(),
        _spec(
            tmp_path,
            [_put_event(at=5)],
            command_runner=FakeCommandRunner(),
            phase="eval",
            start_time=origin,
        ),
    )

    try:
        assert result.content_runner._phase == "eval"
        assert result.event_scheduler._start_time == origin
        assert result.event_scheduler._shared_start_time is True
    finally:
        result.event_scheduler.stop()
        result.content_runner.stop()
