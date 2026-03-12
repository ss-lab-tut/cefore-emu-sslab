"""Event scheduler for timed network operations."""

import shlex
import threading
import time

from mininet.log import info

from .links import link_down, link_up
from .net_config import cefroute_del, cefroute_enable


def _cefroute_add(net, host_idx, prefix, protocol, next_hop):
    """Add a FIB entry via cefroute add."""
    node_name = f"h{host_idx}"
    node_dir = f"./{node_name}"
    command = f"cefroute add {shlex.quote(prefix)} {protocol} {next_hop} -d {node_dir}"
    print(node_name, "command:", command)
    info(net.hosts[host_idx].cmd(command))


_EVENT_HANDLERS = {
    "link_down": lambda net, ev, ml: link_down(net, ml, ev["nodes"][0], ev["nodes"][1]),
    "link_up": lambda net, ev, ml: link_up(net, ml, ev["nodes"][0], ev["nodes"][1]),
    "fib_add": lambda net, ev, _: _cefroute_add(
        net, ev["host"], ev["prefix"], ev.get("protocol", "udp"), ev["next_hop"]
    ),
    "fib_del": lambda net, ev, _: cefroute_del(
        net, ev["host"], ev["prefix"], ev.get("protocol", "udp"), ev["next_hop"]
    ),
    "fib_enable": lambda net, ev, _: cefroute_enable(
        net, ev["host"], ev["prefix"], ev.get("protocol", "udp"), ev["next_hop"]
    ),
}


class EventScheduler:
    """Execute timed events on a Mininet network.

    Events are dicts with at least ``at`` (seconds from start) and ``type``.

    Supported event types:
        - link_down: requires ``nodes: [a, b]``
        - link_up: requires ``nodes: [a, b]``
        - fib_add: requires ``host``, ``prefix``, ``next_hop`` (protocol defaults to udp)
        - fib_del: requires ``host``, ``prefix``, ``next_hop``
        - fib_enable: requires ``host``, ``prefix``, ``next_hop``
    """

    def __init__(self, net, events, mesh_links=None):
        self.net = net
        self.events = sorted(events, key=lambda e: e["at"])
        self.mesh_links = mesh_links
        self._stop_event = threading.Event()
        self._thread = None

    def _run(self):
        start = time.time()
        for event in self.events:
            if self._stop_event.is_set():
                break
            delay = event["at"] - (time.time() - start)
            if delay > 0:
                if self._stop_event.wait(timeout=delay):
                    break

            event_type = event.get("type")
            handler = _EVENT_HANDLERS.get(event_type)
            if handler is None:
                info(f"[scheduler] unknown event type: {event_type}\n")
                continue

            info(f"[scheduler] t={time.time() - start:.1f}s  {event_type} {event}\n")
            try:
                handler(self.net, event, self.mesh_links)
            except Exception as exc:
                info(f"[scheduler] error handling {event_type}: {exc}\n")

    def start(self):
        """Start background event execution thread."""
        if not self.events:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the scheduler and wait for the thread to finish."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
