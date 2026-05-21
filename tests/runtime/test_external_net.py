"""Unit tests for external network legacy content removal."""

import src.runtime.external_net as external_net


def test_legacy_content_helpers_removed():
    assert not hasattr(external_net, "_resolve_connect_content_ops")
    assert not hasattr(external_net, "_warn_if_no_content_operations")
