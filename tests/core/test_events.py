"""Cross-file invariants for the canonical event schema.

These tests are the test surface for EVENT_SCHEMA: they pin the contract
(required fields, content classification, same-time priority, canonical order)
and assert that the scheduler and the config validator stay in lock-step with
the schema. A drift that previously hid across three files now fails one test.
"""

from src.core.events import (
    EVENT_SCHEMA,
    content_event_types,
    event_priorities,
    event_types,
)


# --- golden contract -------------------------------------------------------

def test_canonical_order_matches_loader_error_message_order():
    # Insertion order is load-bearing: the "must be one of: ..." validator
    # message joins the types in this exact order.
    assert event_types() == (
        "link_down", "link_up", "fib_add", "fib_del", "fib_enable",
        "bw_set", "compute_call", "put", "get", "pubsub_pub", "pubsub_sub",
    )


def test_required_fields_pin_the_contract_including_file_drift():
    req = {t: spec.required_fields for t, spec in EVENT_SCHEMA.items()}
    assert req == {
        "link_down": ("nodes",),
        "link_up": ("nodes",),
        "fib_add": ("host", "prefix", "next_hop"),
        "fib_del": ("host", "prefix", "next_hop"),
        "fib_enable": ("host", "prefix", "next_hop"),
        "bw_set": ("nodes", "bandwidth"),
        "compute_call": ("host", "endpoint"),
        # "file" is required here to preserve current loader behavior; the
        # handler's event.get("file", default) makes its default dead for
        # config-driven events. Resolving that drift is a separate follow-up.
        "put": ("host", "uri", "file"),
        "get": ("host", "uri"),
        "pubsub_pub": ("host", "uri", "file"),
        "pubsub_sub": ("host", "uri"),
    }


def test_content_event_types_are_put_get_pub_sub():
    assert content_event_types() == frozenset(
        {"put", "get", "pubsub_pub", "pubsub_sub"}
    )


def test_priorities_only_for_content_ordering():
    # pubsub_sub must precede pubsub_pub; put must precede get.
    assert event_priorities() == {
        "pubsub_sub": 0, "put": 1, "pubsub_pub": 2, "get": 3,
    }


# --- cross-file lock-step ---------------------------------------------------

def test_every_schema_type_has_a_scheduler_handler_and_vice_versa():
    from src.runtime.scheduler import _EVENT_HANDLERS
    assert set(EVENT_SCHEMA) == set(_EVENT_HANDLERS), (
        "orphan handler or schema entry: a type with a handler but no schema "
        "(or vice versa) is exactly the cross-file drift this schema prevents."
    )


def test_scheduler_content_classification_matches_schema():
    from src.runtime.scheduler import _CONTENT_EVENT_TYPES
    assert set(_CONTENT_EVENT_TYPES) == content_event_types()


def test_scheduler_priority_table_matches_schema():
    from src.runtime.scheduler import _EVENT_PRIORITY
    assert dict(_EVENT_PRIORITY) == event_priorities()


# --- loader integration -----------------------------------------------------

def test_loader_rejects_unknown_type_listing_all_schema_types_in_order():
    from src.core.config.loader import validate_config
    errors = validate_config({"events": [{"at": 0, "type": "bogus"}]})
    expected = "events[0].type must be one of: " + ", ".join(event_types())
    assert expected in errors


def test_loader_accepts_exactly_the_schema_types():
    from src.core.config.loader import validate_config
    for etype in event_types():
        errors = validate_config({"events": [{"at": 0, "type": etype}]})
        # Other field errors may appear, but never the "must be one of" one.
        assert not any("must be one of" in e for e in errors), (
            f"loader rejected schema type {etype!r} as unknown"
        )
