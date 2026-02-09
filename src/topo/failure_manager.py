"""Flexible failure scenario manager for disaster topology.

This module implements flexible host failure scenarios with per-cycle configuration.
"""

import threading
import time
from typing import Any, Dict, Optional, Set

from mininet.log import info

from .flap_state import FlapState
from .links import set_node_links_state


class FlexibleFailureManager:
    """Manages flexible host failure scenarios with per-cycle configuration.

    Supports three strategies:
    - simple: Single interval/duration/count configuration (backward compatible)
    - cyclic: List of cycles with different configurations
    - random: Random selection with configurable parameters per cycle
    - manual: Explicit host selection per cycle
    """

    def __init__(
        self,
        scenario_config: dict,
        host_count: int,
        rng: Any,
        publisher_ids: Set[int],
    ):
        """Initialize failure manager.

        Args:
            scenario_config: failure_scenarios section from config.
            host_count: Total number of hosts in the topology.
            rng: Random number generator.
            publisher_ids: Set of publisher host IDs.
        """
        self.strategy = scenario_config.get("strategy", "simple")
        self.cycles = scenario_config.get("cycles", [])
        self.simple = scenario_config.get("simple")
        self.host_count = host_count
        self.rng = rng
        self.publisher_ids = publisher_ids

    def start(self, net, state: FlapState, quiet: bool = False) -> threading.Event:
        """Start failure scenario based on strategy.

        Args:
            net: Mininet network instance.
            state: FlapState instance for tracking down hosts.
            quiet: Suppress flap log output.

        Returns:
            threading.Event to stop the failure scenario.
        """
        if self.strategy == "simple":
            return self._start_simple_mode(net, state, quiet)
        elif self.strategy in ("cyclic", "random", "manual"):
            return self._start_cycle_mode(net, state, quiet)
        else:
            info(f"[failure] unknown strategy '{self.strategy}', no flapping\n")
            return threading.Event()

    def _start_simple_mode(
        self, net, state: FlapState, quiet: bool
    ) -> threading.Event:
        """Start simple mode (backward compatible single configuration)."""
        if not self.simple:
            info("[failure] simple mode requires 'simple' config section\n")
            return threading.Event()

        interval = self.simple.get("interval", 30)
        duration = self.simple.get("duration", 10)
        count = self.simple.get("count", 2)
        stagger = self.simple.get("stagger", 0)
        exclude_list = self.simple.get("exclude", [])

        if interval <= 0 or duration <= 0:
            info("[failure] simple mode: interval/duration must be > 0\n")
            return threading.Event()

        exclude_set = set(exclude_list) | self.publisher_ids
        return self._periodic_flap(
            net,
            state,
            interval,
            duration,
            count,
            stagger,
            exclude_set,
            quiet,
        )

    def _start_cycle_mode(
        self, net, state: FlapState, quiet: bool
    ) -> threading.Event:
        """Start cycle mode with per-cycle configurations."""
        if not self.cycles:
            info("[failure] cycle mode requires 'cycles' list\n")
            return threading.Event()

        stop_event = threading.Event()
        state_lock = threading.Lock()
        shared_down: Set[int] = set()
        cycle_timers: Dict[int, threading.Timer] = {}

        def worker():
            for cycle_idx, cycle_config in enumerate(self.cycles):
                if stop_event.is_set():
                    break

                interval = cycle_config.get("interval", 30)
                duration = cycle_config.get("duration", 10)
                count = cycle_config.get("count", 2)
                stagger = cycle_config.get("stagger", 0)
                exclude_list = cycle_config.get("exclude", [])
                target_list = cycle_config.get("target")
                allow_publishers = cycle_config.get("allow_publishers", False)

                if interval <= 0 or duration <= 0:
                    if not quiet:
                        info(
                            f"[failure] cycle {cycle_idx}: skipping invalid config\n"
                        )
                    continue

                # Build exclude set
                exclude_set = set(exclude_list)
                if not allow_publishers:
                    exclude_set |= self.publisher_ids

                # Wait for interval
                if not quiet:
                    info(
                        f"[failure] cycle {cycle_idx}: waiting {interval}s before down\n"
                    )
                if stop_event.wait(interval):
                    return

                with state_lock:
                    down_snapshot = set(shared_down)

                # Select hosts to down
                if target_list is not None and self.strategy == "manual":
                    # Manual selection
                    chosen = [
                        h
                        for h in target_list
                        if h not in exclude_set and h not in down_snapshot
                    ]
                    if len(chosen) < len(target_list):
                        if not quiet:
                            info(
                                f"[failure] cycle {cycle_idx}: some targets excluded\n"
                            )
                else:
                    # Random or cyclic selection
                    available = [
                        h
                        for h in range(self.host_count)
                        if h not in exclude_set and h not in down_snapshot
                    ]
                    if not available:
                        if not quiet:
                            info(
                                f"[failure] cycle {cycle_idx}: no hosts available\n"
                            )
                        continue

                    count = min(count, len(available))
                    if self.strategy == "random" and self.rng is not None:
                        chosen = self.rng.sample(available, count)
                    else:
                        chosen = available[:count]

                # Down hosts
                cycle_down = set()
                for offset, host_idx in enumerate(chosen):
                    if stop_event.wait(stagger if offset > 0 else 0):
                        return

                    host_name = f"h{host_idx}"
                    with state_lock:
                        if host_idx in shared_down:
                            continue
                        shared_down.add(host_idx)
                        cycle_down.add(host_idx)
                        state.update(set(shared_down), last_down=host_idx)

                    if not quiet:
                        info(
                            f"[failure] cycle {cycle_idx}: down {host_name}\n"
                        )

                    try:
                        set_node_links_state(net, host_name, "down")
                    except (AssertionError, OSError) as exc:
                        if not quiet:
                            info(
                                f"[failure] cycle {cycle_idx}: failed to down {host_name}: {exc}\n"
                            )

                # Schedule up after duration
                def schedule_up(down_set: Set[int], cycle_num: int):
                    timer: Optional[threading.Timer] = None

                    def do_up():
                        if stop_event.is_set():
                            return
                        with state_lock:
                            # Ignore stale callbacks if timer was replaced/cancelled.
                            if cycle_timers.get(cycle_num) is not timer:
                                return
                            cycle_timers.pop(cycle_num, None)
                        restored_hosts = []
                        for h_idx in down_set:
                            h_name = f"h{h_idx}"
                            if not quiet:
                                info(
                                    f"[failure] cycle {cycle_num}: up {h_name}\n"
                                )
                            try:
                                set_node_links_state(net, h_name, "up")
                                restored_hosts.append(h_idx)
                            except (AssertionError, OSError) as exc:
                                if not quiet:
                                    info(
                                        f"[failure] cycle {cycle_num}: failed to up {h_name}: {exc}\n"
                                    )
                        with state_lock:
                            for h_idx in restored_hosts:
                                shared_down.discard(h_idx)
                            state.update(set(shared_down))

                    timer = threading.Timer(duration, do_up)
                    timer.daemon = True
                    with state_lock:
                        cycle_timers[cycle_num] = timer
                    timer.start()

                if cycle_down:
                    schedule_up(cycle_down, cycle_idx)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return stop_event

    def _periodic_flap(
        self,
        net,
        state: FlapState,
        interval: int,
        down_time: int,
        down_count: int,
        stagger: int,
        exclude: Set[int],
        quiet: bool,
    ) -> threading.Event:
        """Run periodic host flapping (simple mode implementation).

        Args:
            net: Mininet network instance.
            state: FlapState instance.
            interval: Seconds between down events.
            down_time: Seconds to keep hosts down.
            down_count: Number of hosts to down per cycle.
            stagger: Seconds between individual host downs.
            exclude: Set of host IDs to exclude.
            quiet: Suppress log output.

        Returns:
            threading.Event to stop flapping.
        """
        host_ids = [idx for idx in range(self.host_count) if idx not in exclude]
        if not host_ids:
            info("[failure] no hosts available for flapping\n")
            return threading.Event()

        stop_event = threading.Event()

        def worker():
            position = 0
            active_down = set()
            active_down_lock = threading.Lock()

            def schedule_up(host_idx):
                def do_up():
                    if stop_event.is_set():
                        return
                    host_name = f"h{host_idx}"
                    if not quiet:
                        info(f"[failure] up {host_name}\n")
                    try:
                        set_node_links_state(net, host_name, "up")
                    except (AssertionError, OSError) as exc:
                        if not quiet:
                            info(
                                f"[failure] failed to up {host_name}: {exc}\n"
                            )
                    with active_down_lock:
                        active_down.discard(host_idx)
                        state.update(set(active_down))

                timer = threading.Timer(down_time, do_up)
                timer.daemon = True
                timer.start()

            while not stop_event.is_set():
                with active_down_lock:
                    available = [
                        idx for idx in host_ids if idx not in active_down
                    ]
                if not available:
                    stop_event.wait(interval)
                    continue

                count = min(down_count, len(available))
                if self.rng is not None:
                    chosen = self.rng.sample(available, count)
                else:
                    chosen = [
                        available[(position + offset) % len(available)]
                        for offset in range(count)
                    ]
                    position += count

                for offset, host_idx in enumerate(chosen):
                    if stop_event.wait(stagger if offset > 0 else 0):
                        return

                    host_name = f"h{host_idx}"
                    with active_down_lock:
                        if host_idx in active_down:
                            continue
                        active_down.add(host_idx)
                        state.update(set(active_down), last_down=host_idx)

                    if not quiet:
                        info(f"[failure] down {host_name}\n")

                    try:
                        set_node_links_state(net, host_name, "down")
                    except (AssertionError, OSError) as exc:
                        if not quiet:
                            info(
                                f"[failure] failed to down {host_name}: {exc}\n"
                            )

                    schedule_up(host_idx)

                stop_event.wait(interval)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return stop_event
