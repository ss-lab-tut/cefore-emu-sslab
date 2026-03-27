"""Tests for src.core.protocols."""

import pytest

from src.core.protocols import DEFAULT_ROUTE_PROTOCOL, normalize_route_protocol


def test_normalize_none_returns_udp():
    assert normalize_route_protocol(None) == "udp"


def test_normalize_uppercase():
    assert normalize_route_protocol("UDP") == "udp"


def test_normalize_with_whitespace():
    assert normalize_route_protocol("  udp  ") == "udp"


def test_normalize_invalid_raises_value_error():
    with pytest.raises(ValueError, match="protocol must be one of"):
        normalize_route_protocol("tcp")


def test_normalize_non_string_raises_type_error():
    with pytest.raises(TypeError, match="protocol must be a string"):
        normalize_route_protocol(123)


def test_default_protocol_constant():
    assert DEFAULT_ROUTE_PROTOCOL == "udp"
