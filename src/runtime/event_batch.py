"""Runtime seam for one batch of scheduled events and content operations."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mininet.log import info

from ..core.events import content_event_types
from .content_ops import ContentOperationRunner
from .scheduler import EventScheduler


@dataclass(frozen=True)
class EventBatchSpec:
    """Policy bundle for constructing and running one scheduler/runner pair.

    The seam owns construction order and deadline policy; callers provide only
    the scenario-specific resources and labels whose wording is user-visible.
    """

    events: list
    run_dir: Path | str
    mesh_links: Any
    sink: Any
    flap_state: Any

    uri_publishers: dict | None = None
    startup_grace: float = 1.0
    phase: str = "event"
    start_time: float | None = None
    wait_timeout: float | None = None
    deadline_policy: str = "warn"
    command_runner: Any = None
    scheduler_label: str = "event scheduling"
    runner_label: str = "content operations"


@dataclass(frozen=True)
class EventBatchResult:
    """Handles and outcomes returned from ``run_event_batch``.

    Deferred callers retain the handles for later shutdown. Sync callers read
    ``completed`` and propagate ``failures`` after the seam has attempted all
    stop stages independently.
    """

    content_runner: ContentOperationRunner | None
    event_scheduler: EventScheduler | None
    completed: bool | None
    failures: list[tuple[str, BaseException]]


def _pub_lifetime_by_uri(events: list) -> dict:
    """Derive pub/sub subscriber wait fallbacks from publication lifetimes."""
    lifetimes = {}
    for event in events:
        if event.get("type") != "pubsub_pub":
            continue
        lifetime = (event.get("pub_opts") or {}).get("lifetime")
        if lifetime is not None:
            lifetimes[event["uri"]] = lifetime
    return lifetimes


def _raise_failures(failures: list[tuple[str, BaseException]]) -> None:
    """Raise stop failures using BaseScenario-compatible aggregation rules."""
    if not failures:
        return
    if len(failures) == 1:
        raise failures[0][1]
    excs = [failure[1] for failure in failures]
    if any(not isinstance(exc, Exception) for exc in excs):
        raise BaseExceptionGroup("event batch stop failures", excs)
    # The guard above established every exc is an Exception; the comprehension
    # only narrows the list type for ExceptionGroup's Exception-bound members.
    raise ExceptionGroup(
        "event batch stop failures",
        [exc for exc in excs if isinstance(exc, Exception)],
    )


def _deadline_message(label: str, timeout: float) -> str:
    return f"{label} exceeded {int(timeout)}s deadline"


def _log_stop_failures(failures: list[tuple[str, BaseException]]) -> None:
    for stage, exc in failures:
        info(f"[warning] {stage} failed during event batch stop: {exc}\n")


def run_event_batch(net, spec: EventBatchSpec) -> EventBatchResult:
    """Construct, start, optionally wait, and stop one event batch.

    Both collaborators are fully constructed before either thread is started.
    This prevents a scheduler construction error, such as a malformed event,
    from leaking a running content worker.
    """
    if spec.deadline_policy not in {"warn", "raise"}:
        raise ValueError("deadline_policy must be 'warn' or 'raise'")

    content_runner = None
    content_types = content_event_types()
    if any(event.get("type") in content_types for event in spec.events):
        content_runner = ContentOperationRunner(
            net,
            run_dir=spec.run_dir,
            sink=spec.sink,
            flap_state=spec.flap_state,
            uri_publishers=spec.uri_publishers,
            startup_grace=spec.startup_grace,
            pub_lifetime_by_uri=_pub_lifetime_by_uri(spec.events),
            phase=spec.phase,
            runner=spec.command_runner,
        )

    event_scheduler = None
    if spec.events:
        event_scheduler = EventScheduler(
            net,
            spec.events,
            mesh_links=spec.mesh_links,
            run_dir=spec.run_dir,
            content_runner=content_runner,
            start_time=spec.start_time,
            sink=spec.sink,
        )

    if spec.wait_timeout is None:
        if content_runner is not None:
            content_runner.start()
        if event_scheduler is not None:
            event_scheduler.start()
        return EventBatchResult(content_runner, event_scheduler, None, [])

    scheduler_completed = True
    runner_completed = True
    failures: list[tuple[str, BaseException]] = []
    try:
        if content_runner is not None:
            content_runner.start()
        if event_scheduler is not None:
            event_scheduler.start()

        if event_scheduler is not None:
            scheduler_completed = event_scheduler.wait_all(timeout=spec.wait_timeout)
        if content_runner is not None:
            if spec.deadline_policy == "warn" or scheduler_completed:
                runner_completed = content_runner.wait_all(timeout=spec.wait_timeout)
    finally:
        if event_scheduler is not None:
            try:
                event_scheduler.stop()
            except BaseException as exc:
                failures.append(("scheduler.stop", exc))
        if content_runner is not None:
            try:
                content_runner.stop()
            except BaseException as exc:
                failures.append(("runner.stop", exc))

    completed = scheduler_completed and runner_completed

    if spec.deadline_policy == "warn":
        if not scheduler_completed:
            info(
                f"[warning] {_deadline_message(spec.scheduler_label, spec.wait_timeout)}\n"
            )
        if not runner_completed:
            info(
                f"[warning] {_deadline_message(spec.runner_label, spec.wait_timeout)}\n"
            )
        return EventBatchResult(content_runner, event_scheduler, completed, failures)

    if not scheduler_completed:
        _log_stop_failures(failures)
        raise RuntimeError(_deadline_message(spec.scheduler_label, spec.wait_timeout))
    if not runner_completed:
        _log_stop_failures(failures)
        raise RuntimeError(_deadline_message(spec.runner_label, spec.wait_timeout))

    _raise_failures(failures)
    return EventBatchResult(content_runner, event_scheduler, completed, failures)
