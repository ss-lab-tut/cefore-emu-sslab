"""Canonical schema for scheduler/config event types.

Single source of truth for the per-type facts that were previously scattered
across ``core/config/loader.py`` (valid types + required fields),
``runtime/scheduler.py`` (priority + content classification), and
``runtime/content_ops.py`` (content dispatch).

This module is intentionally pure (dataclass + constant only): it is imported
by both ``core`` (the config validator) and ``runtime`` (the scheduler), so it
must never import from ``runtime`` or the core->runtime layering would break.

Scope note: the publisher/content event-type sets still embedded in
``scenarios/disaster.py`` and ``scenarios/connect.py`` are intentionally NOT
consolidated here yet (tracked as a follow-up); the single source of truth this
module establishes covers the loader / scheduler / content_ops triangle.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EventSpec:
    """The per-type facts a scheduler event carries.

    required_fields: the keys a handler reads non-optionally (``ev["X"]``); the
        config validator uses these to emit "missing required field" errors.
    is_content: a content operation (put/get/pub/sub) recorded by the
        ContentOperationRunner with its own Verdict, so the scheduler does not
        emit an outcome record for it.
    priority: same-timestamp execution order (lower fires first). The default 5
        means "no special ordering"; only the content ops carry an explicit
        priority so pubsub_sub precedes pubsub_pub and put precedes get.
    """

    required_fields: tuple[str, ...]
    is_content: bool = False
    priority: int = 5


# Insertion order is load-bearing: ``loader`` derives its valid-type tuple from
# this mapping, and the "events[i].type must be one of: ..." error message joins
# the types in this order. Do not reorder without updating that expectation.
EVENT_SCHEMA: dict[str, EventSpec] = {
    "link_down":    EventSpec(("nodes",)),
    "link_up":      EventSpec(("nodes",)),
    "fib_add":      EventSpec(("host", "prefix", "next_hop")),
    "fib_del":      EventSpec(("host", "prefix", "next_hop")),
    "fib_enable":   EventSpec(("host", "prefix", "next_hop")),
    "bw_set":       EventSpec(("nodes", "bandwidth")),
    "compute_call": EventSpec(("host", "endpoint")),
    "put":          EventSpec(("host", "uri", "file"), is_content=True, priority=1),
    "get":          EventSpec(("host", "uri"), is_content=True, priority=3),
    "pubsub_pub":   EventSpec(("host", "uri", "file"), is_content=True, priority=2),
    "pubsub_sub":   EventSpec(("host", "uri"), is_content=True, priority=0),
}


def event_types() -> tuple[str, ...]:
    """All valid event type names, in canonical (error-message) order."""
    return tuple(EVENT_SCHEMA)


def content_event_types() -> frozenset[str]:
    """Event types recorded by the ContentOperationRunner (put/get/pub/sub)."""
    return frozenset(t for t, spec in EVENT_SCHEMA.items() if spec.is_content)


def event_priorities() -> dict[str, int]:
    """Same-timestamp ordering, only for types with a non-default priority."""
    return {t: spec.priority for t, spec in EVENT_SCHEMA.items() if spec.priority != 5}
