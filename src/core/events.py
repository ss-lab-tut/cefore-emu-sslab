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
    is_content: a content operation (put/get/pub/sub) recorded by the
        ContentOperationRunner with its own Verdict, so the scheduler does not
        emit an outcome record for it.
    priority: same-timestamp execution order (lower fires first). The default 5
        means "no special ordering"; only the content ops carry an explicit
        priority so pubsub_sub precedes pubsub_pub and put precedes get.
    publication_uri_field: the event key holding the URI this event publishes
        under, or None for non-publishing types. For unconditional publishers
        (is_publication=True) this is "uri"; for *conditional* publishers
        (compute_call) the field is optional per event — the event publishes
        only when the key is present. Kept separate from is_publication so
        publication_event_types() (validator's uri/file requirements, seeding
        policies) is untouched by conditional types.
    """

    required_fields: tuple[str, ...]
    is_content: bool = False
    is_publication: bool = False
    priority: int = 5
    publication_uri_field: str | None = None


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
    "compute_call": EventSpec(("host", "endpoint"), publication_uri_field="publish_uri"),
    "put":          EventSpec(("host", "uri", "file"), is_content=True, is_publication=True, priority=1, publication_uri_field="uri"),
    "get":          EventSpec(("host", "uri"), is_content=True, priority=3),
    "pubsub_pub":   EventSpec(("host", "uri", "file"), is_content=True, is_publication=True, priority=2, publication_uri_field="uri"),
    "pubsub_sub":   EventSpec(("host", "uri"), is_content=True, priority=0),
}


def event_types() -> tuple[str, ...]:
    """All valid event type names, in canonical (error-message) order."""
    return tuple(EVENT_SCHEMA)


def content_event_types() -> frozenset[str]:
    """Event types recorded by the ContentOperationRunner (put/get/pub/sub)."""
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
    include_conditional: bool = False,
) -> tuple[list[dict], dict[str, int], frozenset[int]]:
    """Pure extraction of publisher metadata from a raw events list.

    Args:
        events: raw event dicts from config.
        include_conditional: also count conditional publishers — events whose
            spec carries a publication_uri_field without is_publication (a
            compute_call with publish_uri set). They join publishers_dict /
            publisher_ids (so FIB pre-programming routes consumers toward the
            publishing host) but never the publications list: that list is a
            seeding input (connect executes it as content ops), and a
            compute_call there would crash on the missing "uri". Opt-in per
            scenario — disaster passes True; connect keeps the default.

    Returns:
        publications: events whose type is in publication_event_types().
        publishers_dict: {uri: host_idx} for each (counted) publication event.
        publisher_ids: publisher host indices as ints, matching
            ScenarioSetupSpec.publisher_ids: set[int].
    """
    pub_types = publication_event_types()
    publications = [ev for ev in events if ev.get("type") in pub_types]
    counted = list(publications)
    if include_conditional:
        for ev in events:
            spec = EVENT_SCHEMA.get(ev.get("type", ""))
            if (
                spec is not None
                and not spec.is_publication
                and spec.publication_uri_field is not None
                and ev.get(spec.publication_uri_field)
            ):
                counted.append(ev)
    publishers_dict = {
        ev[EVENT_SCHEMA[ev["type"]].publication_uri_field]: ev["host"]
        for ev in counted
    }
    publisher_ids = frozenset(ev["host"] for ev in counted)
    return publications, publishers_dict, publisher_ids
