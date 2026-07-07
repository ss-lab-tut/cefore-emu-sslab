"""Pure bridge argument parsing and validation helpers."""

import pytest

from src.runtime.bridge_args import (
    parse_bridge_args,
    parse_ext_args,
    validate_static_ip,
)


class TestParseBridgeArgs:
    def test_valid_entry_with_optional_routes_and_gateway(self):
        assert parse_bridge_args(
            ["s1,10.0.0.1/24,10.0.1.0/24,0.0.0.0/0,10.0.0.254"]
        ) == [
            {
                "switch": "s1",
                "root_ip": "10.0.0.1/24",
                "local_routes": "10.0.1.0/24",
                "external_routes": "0.0.0.0/0",
                "gateway": "10.0.0.254",
            }
        ]

    def test_none_or_empty_defaults_to_no_entries(self):
        assert parse_bridge_args(None) == []
        assert parse_bridge_args([]) == []

    def test_malformed_entry_rejected(self):
        with pytest.raises(ValueError, match="bridge format"):
            parse_bridge_args(["s1,10.0.0.1/24"])


class TestParseExtArgs:
    def test_valid_entry_with_optional_mtu(self):
        assert parse_ext_args(["h1,eth1,10.0.0.2/24,1450"]) == [
            ("h1", "eth1", "10.0.0.2/24", 1450)
        ]

    def test_wrong_field_count_rejected(self):
        with pytest.raises(ValueError, match="ext format"):
            parse_ext_args(["h1,eth1"])

    def test_missing_ip_rejected(self):
        with pytest.raises(ValueError, match="static IP required"):
            parse_ext_args(["h1,eth1,"])

    def test_malformed_cidr_string_is_not_validated_here(self):
        assert parse_ext_args(["h1,eth1,not-a-cidr"]) == [
            ("h1", "eth1", "not-a-cidr", None)
        ]


class TestValidateStaticIp:
    def test_valid_cidr_returns_none(self):
        assert validate_static_ip("10.0.0.2/24") is None

    def test_missing_prefix_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="CIDR"):
            validate_static_ip("10.0.0.2")

    def test_bad_ip_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="invalid static IP"):
            validate_static_ip("not-an-ip/24")
