"""Tests for content operation dispatch wiring."""

from src.core.events import content_event_types
from src.runtime.content_ops import ContentOperationRunner


def test_dispatch_handler_keys_match_content_event_types():
    assert set(ContentOperationRunner._HANDLERS.keys()) == content_event_types()
