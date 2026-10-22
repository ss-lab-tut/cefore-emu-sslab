"""Unit tests for event scheduler."""

import time
from unittest.mock import MagicMock, patch


from src.runtime.results_sink import RecordingSink
from src.runtime.scheduler import EventScheduler


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


class TestFibAddDelegation:
    """fib_add delegates to net_config.cefroute_add (Q: single argv owner)."""

    def _run_fib_add(self, returncode):
        from src.runtime.command_runner import CommandResult

        sink = RecordingSink()
        net = _make_net()
        event = {
            "at": 0.0,
            "type": "fib_add",
            "host": 1,
            "prefix": "ccnx:/test/a",
            "next_hop": "192.168.1.2",
        }
        with patch(
            "src.runtime.scheduler.cefroute_add",
            return_value=CommandResult(returncode=returncode),
        ) as add:
            sched = EventScheduler(net, [event], sink=sink)
            sched.start()
            sched.wait_all(timeout=3)
        add.assert_called_once_with(net, 1, "ccnx:/test/a", None, "192.168.1.2")
        return sink.records

    def test_successful_add_records_success(self):
        records = self._run_fib_add(returncode=0)
        assert records[0]["success"] is True

    def test_failed_add_records_failure(self):
        records = self._run_fib_add(returncode=1)
        assert records[0]["success"] is False


class TestComputeCallOutcomeMapping:
    """compute_call records separate skipped-vs-failed tri-state outcomes.

    An unreachable endpoint (env_failure) is an environment problem, not an
    experiment result — it must be distinguishable in results.json from an
    HTTP/publish failure.
    """

    def _run_compute(self, compute_result):
        from src.runtime.compute_client import ComputeResult

        sink = RecordingSink()
        net = _make_net()
        event = {
            "at": 0.0,
            "type": "compute_call",
            "host": 1,
            "endpoint": "http://edge.local/process",
        }
        with patch(
            "src.runtime.scheduler._do_compute_call",
            return_value=ComputeResult(**compute_result),
        ):
            sched = EventScheduler(net, [event], sink=sink)
            sched.start()
            sched.wait_all(timeout=3)
        return sink.records[0]

    def test_event_fields_are_forwarded_to_compute_client(self):
        """The handler forwards every optional compute field — including the
        publish_timeout deadline (2026-07-16 audit fix) — to compute_call."""
        from src.runtime.compute_client import ComputeResult

        sink = RecordingSink()
        net = _make_net()
        event = {
            "at": 0.0,
            "type": "compute_call",
            "host": 1,
            "endpoint": "http://edge.local/process",
            "method": "POST",
            "payload": "{}",
            "headers": {"Content-Type": "application/json"},
            "output_file": "out.json",
            "publish_uri": "ccnx:/compute/r1",
            "pub_opts": {"expiry": 5000},
            "timeout": 7,
            "publish_timeout": 300,
        }
        result = ComputeResult(
            ok=True, http_status=200, curl_exit=0, publish_ok=True,
            output_file="out.json", stdout="", env_failure=False,
        )
        with patch(
            "src.runtime.scheduler._do_compute_call", return_value=result
        ) as call:
            sched = EventScheduler(net, [event], run_dir="logs/run-x", sink=sink)
            sched.start()
            sched.wait_all(timeout=3)
        args = call.call_args.args
        assert args[1] == 1
        assert args[2] == "http://edge.local/process"
        kwargs = call.call_args.kwargs
        assert kwargs["run_dir"] == "logs/run-x"
        assert kwargs["method"] == "POST"
        assert kwargs["payload"] == "{}"
        assert kwargs["headers"] == {"Content-Type": "application/json"}
        assert kwargs["output_file"] == "out.json"
        assert kwargs["publish_uri"] == "ccnx:/compute/r1"
        assert kwargs["pub_opts"] == {"expiry": 5000}
        assert kwargs["timeout"] == 7
        assert kwargs["publish_timeout"] == 300

    def test_env_failure_records_skipped_no_result(self):
        rec = self._run_compute(
            dict(
                ok=False, http_status=None, curl_exit=7, publish_ok=None,
                output_file=None, stdout="", env_failure=True,
            )
        )
        assert rec["success"] is False
        assert rec["outcome"] == "skipped-no-result"
        assert rec["detail"]["curl_exit"] == 7

    def test_http_failure_records_not_ok_with_detail(self):
        rec = self._run_compute(
            dict(
                ok=False, http_status=500, curl_exit=0, publish_ok=None,
                output_file=None, stdout="oops", env_failure=False,
            )
        )
        assert rec["success"] is False
        assert rec["outcome"] == "not-ok"
        assert rec["detail"]["http_status"] == 500

    def test_success_records_ok_with_publish_detail(self):
        rec = self._run_compute(
            dict(
                ok=True, http_status=200, curl_exit=0, publish_ok=True,
                output_file="logs/run/out.json", stdout="", env_failure=False,
            )
        )
        assert rec["success"] is True
        assert rec["outcome"] == "ok"
        assert rec["detail"] == {
            "http_status": 200,
            "curl_exit": 0,
            "publish_ok": True,
            "output_file": "logs/run/out.json",
        }


class TestHostAppRestartHandler:
    """host_app_restart delegates to HostAppFleet.restart_host() and must
    produce the same EventRecord shape as link_down/link_up -- a plain
    success bool, no outcome/detail keys (unlike compute_call's tri-state).
    """

    def test_delegates_to_fleet_restart_host_with_host_and_downtime_s(self):
        """The handler is a thin forward to ctx["host_app_fleet"].restart_host()."""
        sink = RecordingSink()
        net = _make_net()
        fleet = MagicMock()
        fleet.restart_host.return_value = True
        event = {
            "at": 0.0,
            "type": "host_app_restart",
            "host": 1,
            "downtime_s": 3,
        }
        sched = EventScheduler(net, [event], sink=sink, host_app_fleet=fleet)
        sched.start()
        sched.wait_all(timeout=3)

        fleet.restart_host.assert_called_once_with(1, 3)
        rec = sink.records[0]
        assert rec["success"] is True
        assert rec["event_type"] == "host_app_restart"
        assert "outcome" not in rec
        assert "detail" not in rec

    def test_downtime_s_defaults_to_zero_when_omitted(self):
        """downtime_s is optional in the event schema; the handler's
        default must match (event.get("downtime_s", 0))."""
        net = _make_net()
        fleet = MagicMock()
        fleet.restart_host.return_value = True
        event = {"at": 0.0, "type": "host_app_restart", "host": 0}
        sched = EventScheduler(net, [event], host_app_fleet=fleet)
        sched.start()
        sched.wait_all(timeout=3)

        fleet.restart_host.assert_called_once_with(0, 0)

    def test_fleet_returning_false_records_failure(self):
        """restart_host() returns False when shutdown won the race (see
        HostAppFleet.restart_host); that must be recorded as a failed event,
        not silently treated as success."""
        sink = RecordingSink()
        net = _make_net()
        fleet = MagicMock()
        fleet.restart_host.return_value = False
        event = {"at": 0.0, "type": "host_app_restart", "host": 0}
        sched = EventScheduler(net, [event], sink=sink, host_app_fleet=fleet)
        sched.start()
        sched.wait_all(timeout=3)

        rec = sink.records[0]
        assert rec["success"] is False
        assert rec["error"] == "handler reported failure"

    def test_fleet_raising_records_the_exception_message(self):
        """restart_host() raising (e.g. a stop failure) is caught by the
        scheduler's own generic exception handling, same as any handler."""
        sink = RecordingSink()
        net = _make_net()
        fleet = MagicMock()
        fleet.restart_host.side_effect = RuntimeError("stop_host_app h0 vanished")
        event = {"at": 0.0, "type": "host_app_restart", "host": 0}
        sched = EventScheduler(net, [event], sink=sink, host_app_fleet=fleet)
        sched.start()
        sched.wait_all(timeout=3)

        rec = sink.records[0]
        assert rec["success"] is False
        assert rec["error"] == "stop_host_app h0 vanished"

    def test_no_fleet_in_context_records_failure_without_crashing(self):
        """connect/mesh/linear construct an EventScheduler with no
        host_app_fleet; a host_app_restart event there must fail cleanly,
        not raise."""
        sink = RecordingSink()
        net = _make_net()
        event = {"at": 0.0, "type": "host_app_restart", "host": 0}
        sched = EventScheduler(net, [event], sink=sink)
        sched.start()
        sched.wait_all(timeout=3)

        rec = sink.records[0]
        assert rec["success"] is False

    def test_actual_at_is_sampled_before_a_blocking_handler_not_after(self):
        """2026-10-22 fix (review finding): host_app_restart's handler
        blocks the scheduler thread for stop + downtime_s + start (several
        real seconds). actual_at must record WHEN the event fired -- right
        before the handler was invoked -- not resample time.monotonic()
        after the handler returns, or that blocking time would be added
        on top of the real fire time.

        time.monotonic() is scripted (not the real clock) so the test
        fails loudly, with the wrong number, if the implementation ever
        goes back to resampling: _run() needs exactly two calls per event
        under the fix (the pre-dispatch delay check, then the fire-time
        capture used below); a third call would consume the trap value
        1009.0 and the assertion below would see 9.0, not 4.0.
        """
        sink = RecordingSink()
        net = _make_net()

        def blocking_handler(net, ev, ml, ctx):
            # Stands in for restart_host()'s real stop+downtime_s+start
            # block. A short real sleep is enough to prove "time passed
            # during the handler" without slowing the test down; the
            # scripted monotonic() sequence below, not the wall clock, is
            # what the assertion actually checks.
            time.sleep(0.05)
            return True

        # [call 1 (delay check): 1004.0 -> elapsed=4.0, delay=at_sec-elapsed=0,
        #  so _run() dispatches immediately instead of really waiting 4s;
        #  call 2 (fire_at capture): 1004.0 -> fire_at=4.0, the correct
        #  actual_at; call 3 (trap, must never be consumed): 1009.0 -- the
        #  wrong, post-handler-blocking value a resampling bug would record]
        monotonic_values = iter([1004.0, 1004.0, 1009.0])
        with patch.dict(
            "src.runtime.scheduler._EVENT_HANDLERS", {"test": blocking_handler}
        ), patch(
            "src.runtime.scheduler.time.monotonic",
            side_effect=lambda: next(monotonic_values),
        ):
            sched = EventScheduler(
                net,
                [{"at": 4.0, "type": "test"}],
                sink=sink,
                start_time=1000.0,
            )
            sched.start()
            sched.wait_all(timeout=3)

        assert sink.records[0]["actual_at"] == 4.0


class TestEventOutcomeRecords:
    """Non-content events emit outcome records into the results sink (K)."""

    def _run_one(self, event, handler, handlers_key="test"):
        sink = RecordingSink()
        net = _make_net()
        with patch.dict(
            "src.runtime.scheduler._EVENT_HANDLERS", {handlers_key: handler}
        ):
            sched = EventScheduler(net, [event], sink=sink)
            sched.start()
            sched.wait_all(timeout=3)
        return sink.records

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

    def test_ccninfo_routes_to_content_runner_and_emits_no_outcome_record(self):
        """ccninfo is a content event: the scheduler delegates to the
        ContentOperationRunner and does NOT emit its own outcome record.
        """
        submitted = []
        mock_runner = MagicMock()
        mock_runner.submit = lambda op, ev: submitted.append((op, ev))

        sink = RecordingSink()
        net = _make_net()
        event = {"at": 0.0, "type": "ccninfo", "host": 0, "uri": "ccnx:/test/a"}
        sched = EventScheduler(
            net, [event], sink=sink, content_runner=mock_runner
        )
        sched.start()
        sched.wait_all(timeout=3)

        # The event was submitted to the content runner.
        assert len(submitted) == 1
        assert submitted[0][0] == "ccninfo"
        # No outcome record from the scheduler itself.
        assert sink.records == []

    def test_repeat_key_excluded_from_record(self):
        event = {
            "at": 0.0,
            "type": "test",
            "repeat": {"interval": 0.05, "count": 1},
        }
        records = self._run_one(event, lambda net, ev, ml, ctx: None)
        assert "repeat" not in records[0]["event"]

    def test_handler_event_outcome_maps_to_record_fields(self):
        from src.runtime.scheduler import EventOutcome

        records = self._run_one(
            {"at": 0.0, "type": "test"},
            lambda net, ev, ml, ctx: EventOutcome(
                success=False,
                outcome="skipped-no-result",
                detail={"reason": "no-external-connectivity", "curl_exit": 7},
                error="endpoint unreachable",
            ),
        )
        rec = records[0]
        assert rec["success"] is False
        assert rec["outcome"] == "skipped-no-result"
        assert rec["detail"]["curl_exit"] == 7
        assert rec["error"] == "endpoint unreachable"

    def test_handler_event_outcome_success(self):
        from src.runtime.scheduler import EventOutcome

        records = self._run_one(
            {"at": 0.0, "type": "test"},
            lambda net, ev, ml, ctx: EventOutcome(
                success=True, outcome="ok", detail={"http_status": 200}
            ),
        )
        rec = records[0]
        assert rec["success"] is True
        assert rec["outcome"] == "ok"
        assert rec["error"] is None

    def test_no_callback_is_noop(self):
        net = _make_net()
        with patch.dict(
            "src.runtime.scheduler._EVENT_HANDLERS",
            {"test": lambda net, ev, ml, ctx: None},
        ):
            sched = EventScheduler(net, [{"at": 0.0, "type": "test"}])
            sched.start()
            assert sched.wait_all(timeout=3) is True
