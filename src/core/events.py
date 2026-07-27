"""Canonical schema for scheduler/config event types.

Single source of truth for the per-type facts that were previously scattered
across ``core/config/loader.py`` (valid types + required fields),
``runtime/scheduler.py`` (priority + content classification), and
``runtime/content_ops.py`` (content dispatch).

This module is intentionally pure (dataclass + constant only): it is imported
by both ``core`` (the config validator) and ``runtime`` (the scheduler), so it
must never import from ``runtime`` or the core->runtime layering would break.

Scope: the canonical source for valid types, required fields, content
classification, publication classification, and same-timestamp priority.
Loader, scheduler, content_ops, and the scenario publisher-metadata builders
(``disaster.py``/``connect.py``) all derive from this module.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EventSpec:
    """The per-type facts a scheduler event carries.

    required_fields: the keys a handler reads non-optionally (``ev["X"]``); the
        config validator uses these to emit "missing required field" errors.
    is_content: operations executed and recorded by the ContentOperationRunner
        with their own Verdict/CcninfoVerdict, so the scheduler does not emit
        an outcome record for them.
    priority: same-timestamp execution order (lower fires first). The default 5
        means "no special ordering"; the ordering-sensitive content ops carry
        explicit priorities so pubsub_sub precedes pubsub_pub and put precedes
        get. Other content ops (ccninfo) take the default.
    """

    required_fields: tuple[str, ...]
    is_content: bool = False
    is_publication: bool = False
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
    "put":          EventSpec(("host", "uri", "file"), is_content=True, is_publication=True, priority=1),
    "get":          EventSpec(("host", "uri"), is_content=True, priority=3),
    "pubsub_pub":   EventSpec(("host", "uri", "file"), is_content=True, is_publication=True, priority=2),
    "pubsub_sub":   EventSpec(("host", "uri"), is_content=True, priority=0),
    "ccninfo":      EventSpec(("host", "uri"), is_content=True),
}


def event_types() -> tuple[str, ...]:
    """All valid event type names, in canonical (error-message) order."""
    return tuple(EVENT_SCHEMA)


def content_event_types() -> frozenset[str]:
    """Event types recorded by the ContentOperationRunner.

    Includes all operations the runner executes and records itself
    (put/get/pub/sub/ccninfo), so the scheduler does not emit a separate
    outcome record for them.
    """
    return frozenset(t for t, spec in EVENT_SCHEMA.items() if spec.is_content)


def publication_event_types() -> frozenset[str]:
    """Producer-side content ops that introduce content into the network.

    Currently {"put", "pubsub_pub"}. The disaster and connect scenarios use
    this set to build their URI-to-publisher maps; if a new producer type is
    added to EVENT_SCHEMA, marking ``is_publication=True`` is enough -- the
    scenarios pick it up without edits.
    """
    return frozenset(t for t, spec in EVENT_SCHEMA.items() if spec.is_publication)


def event_priorities() -> dict[str, int]:
    """Same-timestamp ordering, only for types with a non-default priority."""
    return {t: spec.priority for t, spec in EVENT_SCHEMA.items() if spec.priority != 5}


def extract_publications(
    events: list[dict],
) -> tuple[list[dict], dict[str, int], frozenset[int]]:
    """Pure extraction of publisher metadata from a raw events list.

    Returns:
        publications: events whose type is in publication_event_types().
        publishers_dict: {uri: host_idx} for each publication event.
        publisher_ids: publisher host indices as ints, matching
            ScenarioSetupSpec.publisher_ids: set[int].
    """
    pub_types = publication_event_types()
    publications = [ev for ev in events if ev.get("type") in pub_types]
    publishers_dict = {ev["uri"]: ev["host"] for ev in publications}
    publisher_ids = frozenset(ev["host"] for ev in publications)
    return publications, publishers_dict, publisher_ids
