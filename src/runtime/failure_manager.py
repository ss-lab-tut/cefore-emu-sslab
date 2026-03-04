"""Failure scenario managers for disaster topology."""

import threading
from typing import Any

from mininet.log import info

from ..core.flap_state import FlapState
from .links import set_node_links_state


def periodic_host_flap(
    net,
    host_num: int,
    interval: int,
    down_time: int,
    rng,
    exclude,
    state,
    down_count: int,
    stagger: int,
    quiet: bool = False,
):
    """Start periodic host flapping in background thread."""
    host_ids = [idx for idx in range(host_num) if idx not in exclude]
    if not host_ids:
        info("no hosts available for flapping\n")
        return threading.Event()
    stop_event = threading.Event()

    use_flap_state = hasattr(state, "update") and hasattr(state, "snapshot")

    def worker():
        position = 0
        active_down = set()

        def update_state(last_down=None):
            if use_flap_state:
                state.update(active_down, last_down)
            else:
                state["down_hosts"] = sorted(active_down)
                if last_down is not None:
                    state["last_down_host"] = last_down

        def schedule_up(host_idx):
            def do_up():
                if stop_event.is_set():
                    return
                host_name = f"h{host_idx}"
                if not quiet:
                    info(f"\n[flap] up {host_name}\n")
                try:
                    set_node_links_state(net, host_name, "up")
                except (AssertionError, OSError) as exc:
                    if not quiet:
                        info(f"\n[flap] failed to up {host_name}: {exc}\n")
                active_down.discard(host_idx)
                update_state()

            timer = threading.Timer(down_time, do_up)
            timer.daemon = True
            timer.start()

        while not stop_event.is_set():
            available = [idx for idx in host_ids if idx not in active_down]
            if not available:
                stop_event.wait(interval)
                continue
            count = min(down_count, len(available))
            if rng is not None:
                chosen = rng.sample(available, count)
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
                active_down.add(host_idx)
                update_state(last_down=host_idx)
                if not quiet:
                    info(f"\n[flap] down {host_name}\n")
                try:
                    set_node_links_state(net, host_name, "down")
                except (AssertionError, OSError) as exc:
                    if not quiet:
                        info(f"\n[flap] failed to down {host_name}: {exc}\n")
                schedule_up(host_idx)

            stop_event.wait(interval)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return stop_event


class FlexibleFailureManager:
    """Manage per-cycle host failure scenarios."""

    def __init__(
        self,
        scenario_config: dict[str, Any],
        host_count: int,
        rng,
        publisher_ids: set[int],
    ):
        self.strategy = scenario_config.get("strategy", "simple")
        self.cycles = scenario_config.get("cycles", [])
        self.simple = scenario_config.get("simple")
        self.host_count = host_count
        self.rng = rng
        self.publisher_ids = publisher_ids

    def start(self, net, state: FlapState, quiet: bool = False):
        if self.strategy == "simple":
            return self._start_simple_mode(net, state, quiet)
        if self.strategy in ("cyclic", "random", "manual"):
            return self._start_cycle_mode(net, state, quiet)
        info(f"[failure] unknown strategy '{self.strategy}', no flapping\n")
        return threading.Event(), None

    def _start_simple_mode(self, net, state: FlapState, quiet: bool):
        if not self.simple:
            info("[failure] simple mode requires 'simple' config section\n")
            return threading.Event(), None

        interval = self.simple.get("interval") or 30
        duration = self.simple.get("duration") or 10
        count = self.simple.get("count") if self.simple.get("count") is not None else 2
        stagger = self.simple.get("stagger") if self.simple.get("stagger") is not None else 0
        exclude_list = self.simple.get("exclude") or []

        if interval <= 0 or duration <= 0:
            info("[failure] simple mode: interval/duration must be > 0\n")
            return threading.Event(), None

        exclude_set = set(exclude_list) | self.publisher_ids
        stop_event = periodic_host_flap(
            net,
            self.host_count,
            interval,
            duration,
            self.rng,
            exclude_set,
            state,
            count,
            stagger,
            quiet=quiet,
        )
        return stop_event, None

    def _start_cycle_mode(self, net, state: FlapState, quiet: bool):
        if not self.cycles:
            info("[failure] cycle mode requires 'cycles' list\n")
            return threading.Event(), None

        stop_event = threading.Event()
        state_lock = threading.Lock()
        shared_down: set[int] = set()
        cycle_timers: dict[int, threading.Timer] = {}

        def worker():
            for cycle_idx, cycle_config in enumerate(self.cycles):
                if stop_event.is_set():
                    break

                interval = cycle_config.get("interval") or 30
                duration = cycle_config.get("duration") or 10
                count = cycle_config.get("count") if cycle_config.get("count") is not None else 2
                stagger = cycle_config.get("stagger") if cycle_config.get("stagger") is not None else 0
                exclude_list = cycle_config.get("exclude") or []
                target_list = cycle_config.get("target")
                allow_publishers = cycle_config.get("allow_publishers", False)

                if interval <= 0 or duration <= 0:
                    if not quiet:
                        info(f"[failure] cycle {cycle_idx}: skipping invalid config\n")
                    continue

                exclude_set = set(exclude_list)
                if not allow_publishers:
                    exclude_set |= self.publisher_ids

                if not quiet:
                    info(f"[failure] cycle {cycle_idx}: waiting {interval}s before down\n")
                if stop_event.wait(interval):
                    return

                with state_lock:
                    down_snapshot = set(shared_down)

                if target_list is not None and self.strategy == "manual":
                    chosen = [
                        host for host in target_list
                        if host not in exclude_set and host not in down_snapshot
                    ]
                    if len(chosen) < len(target_list) and not quiet:
                        info(f"[failure] cycle {cycle_idx}: some targets excluded\n")
                else:
                    available = [
                        host for host in range(self.host_count)
                        if host not in exclude_set and host not in down_snapshot
                    ]
                    if not available:
                        if not quiet:
                            info(f"[failure] cycle {cycle_idx}: no hosts available\n")
                        continue
                    count = min(count, len(available))
                    if self.strategy == "random" and self.rng is not None:
                        chosen = self.rng.sample(available, count)
                    else:
                        chosen = available[:count]

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
                        info(f"[failure] cycle {cycle_idx}: down {host_name}\n")

                    try:
                        set_node_links_state(net, host_name, "down")
                    except (AssertionError, OSError) as exc:
                        if not quiet:
                            info(
                                f"[failure] cycle {cycle_idx}: failed to down {host_name}: {exc}\n"
                            )

                def schedule_up(down_set: set[int], cycle_num: int):
                    timer = None

                    def do_up():
                        if stop_event.is_set():
                            return
                        with state_lock:
                            if cycle_timers.get(cycle_num) is not timer:
                                return
                            cycle_timers.pop(cycle_num, None)
                        restored_hosts = []
                        for host_idx in down_set:
                            host_name = f"h{host_idx}"
                            if not quiet:
                                info(f"[failure] cycle {cycle_num}: up {host_name}\n")
                            try:
                                set_node_links_state(net, host_name, "up")
                                restored_hosts.append(host_idx)
                            except (AssertionError, OSError) as exc:
                                if not quiet:
                                    info(
                                        f"[failure] cycle {cycle_num}: failed to up {host_name}: {exc}\n"
                                    )
                        with state_lock:
                            for host_idx in restored_hosts:
                                shared_down.discard(host_idx)
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
        return stop_event, thread
