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
    extract_publications,
    publication_event_types,
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


def test_publication_event_types_are_put_and_pubsub_pub():
    # publication = ops that introduce content into the network (producer side);
    # consumption (get/pubsub_sub) is the deliberately-excluded counterpart.
    # The scenarios' publisher-metadata builders read this set; if a new
    # producer-side content type is added to EVENT_SCHEMA without flagging
    # is_publication, the scenario's publisher map silently drops it -- this
    # test is the cross-file pin that catches that drift.
    assert publication_event_types() == frozenset({"put", "pubsub_pub"})


def test_extract_publications_returns_three_tuple():
    events = [
        {"type": "put", "host": 1, "uri": "ccnx:/a", "file": "f1"},
        {"type": "get", "host": 2, "uri": "ccnx:/a"},
        {"type": "pubsub_pub", "host": 3, "uri": "ccnx:/b", "file": "f2"},
    ]
    pubs, pub_dict, pub_ids = extract_publications(events)
    assert len(pubs) == 2
    assert pub_dict == {"ccnx:/a": 1, "ccnx:/b": 3}
    assert pub_ids == frozenset({1, 3})


def test_extract_publications_empty():
    pubs, pub_dict, pub_ids = extract_publications([])
    assert pubs == []
    assert pub_dict == {}
    assert pub_ids == frozenset()


def test_extract_publications_conditional_compute_call_opt_in():
    """compute_call with publish_uri is a *conditional* publication.

    Opt-in (include_conditional=True, used by disaster): its publish_uri
    joins publishers_dict/publisher_ids so FIB pre-programming can route
    consumers toward the compute host — without it, the republished result
    is unreachable and the offload experiment cannot succeed. The
    publications list (connect's seeding input) must NOT grow: seeding a
    compute_call as a content op would crash on the missing "uri".
    """
    events = [
        {"type": "put", "host": 1, "uri": "ccnx:/a", "file": "f1"},
        {
            "type": "compute_call", "host": 2,
            "endpoint": "http://edge.local/process",
            "output_file": "out.json", "publish_uri": "ccnx:/compute/r1",
        },
    ]
    pubs, pub_dict, pub_ids = extract_publications(events, include_conditional=True)
    assert [ev["type"] for ev in pubs] == ["put"]
    assert pub_dict == {"ccnx:/a": 1, "ccnx:/compute/r1": 2}
    assert pub_ids == frozenset({1, 2})


def test_extract_publications_default_excludes_conditional():
    # connect keeps its exact pre-extension behavior: conditional publishers
    # are an explicit per-scenario policy, not a silent global change.
    events = [
        {
            "type": "compute_call", "host": 2,
            "endpoint": "http://edge.local/process",
            "publish_uri": "ccnx:/compute/r1",
        },
    ]
    pubs, pub_dict, pub_ids = extract_publications(events)
    assert pubs == []
    assert pub_dict == {}
    assert pub_ids == frozenset()


def test_extract_publications_conditional_without_publish_uri_is_ignored():
    events = [
        {"type": "compute_call", "host": 2, "endpoint": "http://edge.local/x"},
    ]
    pubs, pub_dict, pub_ids = extract_publications(events, include_conditional=True)
    assert pubs == []
    assert pub_dict == {}
    assert pub_ids == frozenset()


def test_publication_uri_field_pins_per_type_uri_key():
    fields = {
        t: spec.publication_uri_field
        for t, spec in EVENT_SCHEMA.items()
        if spec.publication_uri_field is not None
    }
    assert fields == {
        "put": "uri",
        "pubsub_pub": "uri",
        "compute_call": "publish_uri",
    }


def test_publication_is_strict_subset_of_content():
    # Every publication is also a content op; the converse is not true
    # (get/pubsub_sub are content but not publication).
    assert publication_event_types() < content_event_types()


def test_is_publication_flag_set_on_producer_specs():
    pubs = {t for t, spec in EVENT_SCHEMA.items() if spec.is_publication}
    assert pubs == {"put", "pubsub_pub"}


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
