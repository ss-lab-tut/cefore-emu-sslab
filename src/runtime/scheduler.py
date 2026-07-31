"""Event scheduler for timed network operations."""

import heapq
import threading
import time
from dataclasses import dataclass
from typing import Optional

from mininet.log import info

from ..core.events import content_event_types, event_priorities
from .bandwidth import set_switch_bandwidth
from .command_runner import MininetCommandRunner
from .compute_client import compute_call as _do_compute_call
from .links import link_down, link_up
from .net_config import cefroute_add, cefroute_del, cefroute_enable


@dataclass(frozen=True)
class EventOutcome:
    """Rich handler verdict: tri-state outcome + evidence for the sink.

    Handlers that only know pass/fail keep returning bool (or None); handlers
    with more to say return this so the EventRecord carries the S7 tri-state
    (ok / not-ok / skipped-no-result) and a structured detail dict instead of
    flattening everything into success=False.
    """

    success: bool
    outcome: str
    detail: Optional[dict] = None
    error: Optional[str] = None


def _handle_compute_call(net, event, mesh_links, ctx):
    """Handle a compute_call event through the injected-runner client.

    No pre-flight connectivity probe: the real request's curl exit code
    already distinguishes an unreachable endpoint (env_failure) from an HTTP
    failure, and a probe would double-hit the endpoint (a POST-only API
    answers the probe GET with 405). Unreachable maps to skipped-no-result —
    an environment problem, not an experiment result.
    """
    host_idx = event["host"]

    result = _do_compute_call(
        MininetCommandRunner(net),
        host_idx,
        event["endpoint"],
        method=event.get("method", "GET"),
        payload=event.get("payload"),
        headers=event.get("headers"),
        output_file=event.get("output_file"),
        publish_uri=event.get("publish_uri"),
        pub_opts=event.get("pub_opts"),
        run_dir=ctx.get("run_dir"),
        timeout=event.get("timeout", 30),
        # 2026-07-16 audit fix: the cefputfile deadline is its own field —
        # publish speed is governed by pub_opts rate, not the HTTP timeout.
        publish_timeout=event.get("publish_timeout"),
    )
    detail = {
        "http_status": result.http_status,
        "curl_exit": result.curl_exit,
        "publish_ok": result.publish_ok,
        "output_file": result.output_file,
    }
    if result.env_failure:
        info(
            f"[scheduler] compute_call: h{host_idx} cannot reach "
            f"{event['endpoint']} (curl exit={result.curl_exit}). "
            f"Ensure ext/bridges are configured for this host.\n"
        )
        return EventOutcome(
            success=False,
            outcome="skipped-no-result",
            detail={**detail, "reason": "no-external-connectivity"},
            error="endpoint unreachable",
        )
    if not result.ok:
        info(
            f"[scheduler] compute_call failed for h{host_idx}: "
            f"exit={result.curl_exit} http={result.http_status} "
            f"publish={result.publish_ok}\n"
        )
        return EventOutcome(
            success=False,
            outcome="not-ok",
            detail=detail,
            error="compute call failed",
        )
    return EventOutcome(success=True, outcome="ok", detail=detail)


def _handle_content_op(op_type):
    """Return a scheduler handler that delegates to the ContentOperationRunner."""

    def _handler(net, ev, ml, ctx):
        runner = ctx.get("content_runner")
        if runner is None:
            info(
                f"[scheduler] no content_runner in context; ignoring {op_type} event\n"
            )
            return
        runner.submit(op_type, ev)

    return _handler


_EVENT_HANDLERS = {
    "link_down": lambda net, ev, ml, ctx: link_down(
        net, ml, ev["nodes"][0], ev["nodes"][1]
    ),
    "link_up": lambda net, ev, ml, ctx: link_up(
        net, ml, ev["nodes"][0], ev["nodes"][1]
    ),
    "fib_add": lambda net, ev, _, ctx: cefroute_add(
        net, ev["host"], ev["prefix"], ev.get("protocol"), ev["next_hop"]
    ).returncode == 0,
    "fib_del": lambda net, ev, _, ctx: cefroute_del(
        net, ev["host"], ev["prefix"], ev.get("protocol"), ev["next_hop"]
    ),
    "fib_enable": lambda net, ev, _, ctx: cefroute_enable(
        net, ev["host"], ev["prefix"], ev.get("protocol"), ev["next_hop"]
    ),
    "bw_set": lambda net, ev, ml, ctx: set_switch_bandwidth(
        net, ml, ev["nodes"][0], ev["nodes"][1], ev["bandwidth"]
    ),
    "compute_call": _handle_compute_call,
    "put": _handle_content_op("put"),
    "get": _handle_content_op("get"),
    "pubsub_sub": _handle_content_op("pubsub_sub"),
    "pubsub_pub": _handle_content_op("pubsub_pub"),
    "ccninfo": _handle_content_op("ccninfo"),
}

# Same-time priority (lower value fires first; pubsub_sub before pubsub_pub,
# put before get) and content classification are derived from EVENT_SCHEMA so
# this module and the config validator cannot drift. Content events are recorded
# by the ContentOperationRunner with their own Verdicts; the scheduler emits
# outcome records only for the rest.
_EVENT_PRIORITY = event_priorities()
_CONTENT_EVENT_TYPES = content_event_types()


class EventScheduler:
    """Execute timed events on a Mininet network.

    Events are dicts with at least ``at`` (seconds from start) and ``type``.

    Supported event types:
        - link_down: requires ``nodes: [a, b]``
        - link_up: requires ``nodes: [a, b]``
        - fib_add: requires ``host``, ``prefix``, ``next_hop`` (protocol defaults to udp)
        - fib_del: requires ``host``, ``prefix``, ``next_hop``
        - fib_enable: requires ``host``, ``prefix``, ``next_hop``
        - bw_set: requires ``nodes: [a, b]``, ``bandwidth``
        - compute_call: requires ``host``, ``endpoint``

    Events may include a ``repeat`` dict for periodic execution:
        - interval: seconds between repetitions
        - duration: seconds before restore event fires
        - restore: dict of fields to override in the restore event
        - restore_type: event type for the restore event
        - count: number of repetitions (null = infinite)
    """

    def __init__(
        self,
        net,
        events,
        mesh_links=None,
        run_dir=None,
        content_runner=None,
        start_time=None,
        sink=None,
    ):
        self.net = net
        self.mesh_links = mesh_links
        self._context = {"run_dir": run_dir, "content_runner": content_runner}
        self._sink = sink
        self._stop_event = threading.Event()
        self._thread = None

        self._heap = []
        self._seq = 0
        self._start_time = start_time
        self._shared_start_time = start_time is not None

        for event in events:
            self._push_event(event["at"], event)

    def _push_event(self, at_sec, event):
        """Push event into the priority queue.

        Heap entry is (at_sec, priority, seq, event).  Same-time events are
        ordered by priority first (lower = sooner), then insertion order.
        This guarantees pubsub_sub fires before pubsub_pub at equal timestamps.
        """
        priority = _EVENT_PRIORITY.get(event.get("type", ""), 5)
        heapq.heappush(self._heap, (at_sec, priority, self._seq, event))
        self._seq += 1

    def _handle_repeat(self, event, scheduled_at):
        """Schedule restore and next repetition if repeat is configured.

        Args:
            event: The event dict that was just executed.
            scheduled_at: The SCHEDULED time (at_sec from heap), not actual
                execution time. This ensures periodic events maintain a stable
                cadence even if handler execution is slow.
        """
        repeat = event.get("repeat")
        if not repeat:
            return

        interval = repeat.get("interval", 0)
        duration = repeat.get("duration")
        count = repeat.get("count")

        if duration is not None and duration > 0:
            restore_at = scheduled_at + duration
            if "restore" in repeat:
                restore_event = {**event, **repeat["restore"]}
                restore_event.pop("repeat", None)
                self._push_event(restore_at, restore_event)
            elif "restore_type" in repeat:
                restore_event = {**event, "type": repeat["restore_type"]}
                restore_event.pop("repeat", None)
                self._push_event(restore_at, restore_event)

        if interval > 0:
            if count is not None:
                remaining = count - 1
                if remaining <= 0:
                    return
                new_repeat = {**repeat, "count": remaining}
            else:
                new_repeat = repeat
            next_at = scheduled_at + interval
            next_event = {**event, "repeat": new_repeat}
            self._push_event(next_at, next_event)

    def _run(self):
        if self._start_time is None:
            self._start_time = time.monotonic()
        while self._heap and not self._stop_event.is_set():
            at_sec, _priority, _seq, event = self._heap[0]
            elapsed = time.monotonic() - self._start_time
            delay = at_sec - elapsed
            if delay > 0:
                if self._stop_event.wait(timeout=delay):
                    break

            heapq.heappop(self._heap)
            event_type = event.get("type")
            handler = _EVENT_HANDLERS.get(event_type)
            if handler is None:
                info(f"[scheduler] unknown event type: {event_type}\n")
                continue

            elapsed = time.monotonic() - self._start_time
            late_by = elapsed - at_sec
            if self._shared_start_time and late_by > 0.05:
                info(
                    f"[warning] scheduler event {event_type} scheduled at "
                    f"t={at_sec:.1f}s executed at t={elapsed:.1f}s "
                    f"({late_by:.1f}s late)\n"
                )
            info(f"[scheduler] t={elapsed:.1f}s  {event_type} {event}\n")
            success = True
            error = None
            outcome = None
            detail = None
            try:
                verdict = handler(self.net, event, self.mesh_links, self._context)
                if isinstance(verdict, EventOutcome):
                    success = verdict.success
                    error = verdict.error
                    outcome = verdict.outcome
                    detail = verdict.detail
                elif verdict is False:
                    success = False
                    error = "handler reported failure"
            except Exception as exc:
                info(f"[scheduler] error handling {event_type}: {exc}\n")
                success = False
                error = str(exc)
            except BaseException as exc:
                info(
                    f"[scheduler] fatal error handling {event_type}: {exc}; stopping\n"
                )
                break

            self._record_event_outcome(
                event, event_type, at_sec, success, error, outcome, detail
            )
            self._handle_repeat(event, at_sec)

    def _record_event_outcome(
        self, event, event_type, at_sec, success, error, outcome=None, detail=None
    ):
        """Emit an outcome record for a non-content event into the ResultsSink."""
        if self._sink is None or event_type in _CONTENT_EVENT_TYPES:
            return
        actual_at = time.monotonic() - self._start_time
        self._sink.record_event(
            event_type,
            success=success,
            error=error,
            scheduled_at=at_sec,
            actual_at=round(actual_at, 3),
            event={k: v for k, v in event.items() if k != "repeat"},
            outcome=outcome,
            detail=detail,
        )

    def start(self):
        """Start background event execution thread."""
        if not self._heap:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def wait_all(self, timeout=None):
        """Wait until all scheduled events have fired or timeout expires."""
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            return not self._thread.is_alive()
        return True

    def stop(self):
        """Stop the scheduler and wait for the thread to finish."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
