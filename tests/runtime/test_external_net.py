"""Unit tests for external network legacy content removal."""

import src.runtime.external_net as external_net


def test_legacy_content_helpers_removed():
    assert not hasattr(external_net, "_resolve_connect_content_ops")
    assert not hasattr(external_net, "_warn_if_no_content_operations")


def test_publication_events_drive_connect_publisher_metadata():
    events = [
        {"at": 1, "type": "put", "host": 4, "uri": "ccnx:/test/data"},
        {"at": 2, "type": "pubsub_pub", "host": 3, "uri": "ccnx:/test/live"},
        {"at": 3, "type": "get", "host": 0, "uri": "ccnx:/test/data"},
    ]
    publications, publishers, _ = external_net.extract_publications(events)
    assert [event["type"] for event in publications] == ["put", "pubsub_pub"]
    assert publishers == {"ccnx:/test/data": 4, "ccnx:/test/live": 3}
