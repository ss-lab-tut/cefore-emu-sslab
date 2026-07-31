"""Tests for content operation dispatch wiring."""

from pathlib import Path
from unittest.mock import MagicMock

from src.core.events import content_event_types
from src.core.flap_state import FlapState
from src.runtime.command_runner import FakeCommandRunner
from src.runtime.content_ops import ContentOperationRunner
from src.runtime.results_sink import RecordingSink


def test_dispatch_handler_keys_match_content_event_types():
    assert set(ContentOperationRunner._HANDLERS.keys()) == content_event_types()


# ---------------------------------------------------------------------------
# FakeCommandRunner E2E: ccninfo happy path
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "ccninfo"


def _make_runner(tmp_path, *, fake=None, sink=None, flap_state=None):
    """Build a ContentOperationRunner wired to a FakeCommandRunner."""
    fake = fake or FakeCommandRunner()
    sink = sink or RecordingSink()
    flap = flap_state or FlapState()
    net = MagicMock()
    runner = ContentOperationRunner(
        net,
        run_dir=str(tmp_path),
        sink=sink,
        flap_state=flap,
        # No seed_label: the parameter was a dead thread through
        # content_ops/event_batch/scenarios and was removed. This file arrived
        # on the ccninfo branch, which still had it — a merge-time adaptation,
        # not a change in what these tests assert.
        phase="event",
        runner=fake,
    )
    return runner, fake, sink


class TestCcninfoE2EHappyPath:
    """FakeCommandRunner E2E: pre-write fixture text to the predictable log
    path, submit a ccninfo event with expectations, drain, and assert the
    sink row matches the full wire-contract key set with success=True.
    """

    def test_success_records_one_row_with_full_wire_contract(self, tmp_path):
        from tests.core.test_records import CCNINFO_KEYS

        runner, fake, sink = _make_runner(tmp_path)

        # FakeCommandRunner records log_path but writes nothing — we pre-write
        # the fixture content to the path the runner will produce.
        fixture_text = (FIXTURE_DIR / "reply_named_cache.out").read_text()
        # The log path is content_log_name("ccninfo", "event", 0, uri)
        log_path = tmp_path / "ccninfo_event_h0_test_event_sample.log"
        log_path.write_text(fixture_text)

        event = {
            "at": 0.0,
            "type": "ccninfo",
            "host": 0,
            "uri": "ccnx:/test/event_sample",
            "expected_responder": "h1",
            "expected_route": ["h1"],
        }

        runner.start()
        runner.submit("ccninfo", event)
        runner.wait_all(timeout=5)
        runner.stop()

        records = sink.of_type("ccninfo")
        assert len(records) == 1, f"expected exactly one ccninfo record, got {len(records)}"

        rec = records[0]
        assert list(rec.keys()) == CCNINFO_KEYS
        assert rec["success"] is True
        assert rec["reply_received"] is True
        assert rec["responder"] == "h1"
        assert rec["responder_matched"] is True
        assert rec["route_matched"] is True
        assert rec["expected_responder"] == "h1"
        assert rec["expected_route"] == ("h1",)
        # Route must be JSON-primitive dicts.
        assert isinstance(rec["route"][0], dict)
        assert rec["route"][0]["node"] == "h1"


class TestCcninfoQueuedDiscard:
    """Pin that a ccninfo item still queued when the runner is cancelled/stopped
    produces NO record (existing runner semantics — _run's cancel branch does
    task_done without dispatching)."""

    def test_queued_ccninfo_discarded_produces_no_record(self, tmp_path):
        runner, fake, sink = _make_runner(tmp_path)

        event = {
            "at": 0.0,
            "type": "ccninfo",
            "host": 0,
            "uri": "ccnx:/test/event_sample",
            "expected_responder": "h1",
            "expected_route": ["h1"],
        }

        # Set cancel BEFORE start so the worker loop never dispatches.
        runner._cancel_event.set()
        runner.start()
        runner.submit("ccninfo", event)
        runner.wait_all(timeout=5)
        runner.stop()

        records = sink.of_type("ccninfo")
        assert len(records) == 0, (
            f"queued-discard should produce no record, got {len(records)}"
        )


class TestCcninfoE2EExceptionPath:
    """FakeCommandRunner E2E: make the fake raise during execution, assert
    exactly one failure row is recorded (EVERY-DISPATCH-ONE-RECORD contract).
    """

    def test_exception_records_exactly_one_failure_row(self, tmp_path):
        from tests.core.test_records import CCNINFO_KEYS

        fake = FakeCommandRunner()

        # Make the fake raise on any run() call.
        def _boom(node, argv):
            raise RuntimeError("simulated ccninfo crash")

        fake.on_run = _boom

        runner, _, sink = _make_runner(tmp_path, fake=fake)

        # Supply expectations so the exception path exercises the
        # from_runtime_ccninfo factory and yields matched=False (known
        # failure), not matched=None (assertion-absent).
        event = {
            "at": 0.0,
            "type": "ccninfo",
            "host": 0,
            "uri": "ccnx:/test/event_sample",
            "expected_responder": "h1",
            "expected_route": ["h1"],
        }

        runner.start()
        runner.submit("ccninfo", event)
        runner.wait_all(timeout=5)
        runner.stop()

        records = sink.of_type("ccninfo")
        assert len(records) == 1, (
            f"EVERY-DISPATCH-ONE-RECORD: expected exactly one ccninfo record "
            f"on exception, got {len(records)}"
        )
        rec = records[0]
        assert list(rec.keys()) == CCNINFO_KEYS
        assert rec["success"] is False
        assert rec["reply_received"] is False
        # With expectations set, the exception path must produce
        # matched=False (known failure), not matched=None.
        assert rec["responder_matched"] is False
        assert rec["route_matched"] is False
