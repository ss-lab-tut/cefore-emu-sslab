"""Unit tests for src/core/addressing.py."""

import pytest

from src.core.addressing import AddressingScheme, DEFAULT_NETWORK_CIDR


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

class TestDefaultScheme:
    def setup_method(self):
        self.scheme = AddressingScheme()

    def test_default_cidr_constant(self):
        assert DEFAULT_NETWORK_CIDR == "192.168.0.0/16"

    def test_host_ip_subnet1_host0(self):
        assert self.scheme.host_ip(1, 0) == "192.168.1.1"

    def test_host_ip_subnet3_host4(self):
        assert self.scheme.host_ip(3, 4) == "192.168.3.5"

    def test_host_ip_subnet0_host0(self):
        assert self.scheme.host_ip(0, 0) == "192.168.0.1"

    def test_link_network_subnet1(self):
        assert self.scheme.link_network(1) == "192.168.1.0/24"

    def test_root_gateway_subnet5(self):
        assert self.scheme.root_gateway(5) == "192.168.5.254/24"


# ---------------------------------------------------------------------------
# Custom base
# ---------------------------------------------------------------------------

class TestCustomBase:
    def setup_method(self):
        self.scheme = AddressingScheme("172.20.0.0/16")

    def test_host_ip_subnet1_host0(self):
        assert self.scheme.host_ip(1, 0) == "172.20.1.1"

    def test_host_ip_subnet3_host4(self):
        assert self.scheme.host_ip(3, 4) == "172.20.3.5"

    def test_link_network(self):
        assert self.scheme.link_network(2) == "172.20.2.0/24"

    def test_root_gateway(self):
        assert self.scheme.root_gateway(1) == "172.20.1.254/24"

    def test_non_zero_third_octet_base(self):
        scheme = AddressingScheme("10.1.0.0/16")
        assert scheme.host_ip(1, 0) == "10.1.1.1"


# ---------------------------------------------------------------------------
# Invalid CIDR
# ---------------------------------------------------------------------------

class TestInvalidCIDR:
    def test_not_slash16_slash8(self):
        with pytest.raises(ValueError, match="/16"):
            AddressingScheme("10.0.0.0/8")

    def test_not_slash16_slash24(self):
        with pytest.raises(ValueError, match="/16"):
            AddressingScheme("192.168.0.0/24")

    def test_not_slash16_slash32(self):
        with pytest.raises(ValueError, match="/16"):
            AddressingScheme("1.2.3.4/32")

    def test_invalid_string(self):
        with pytest.raises((ValueError, Exception)):
            AddressingScheme("not-a-cidr")

    def test_empty_string(self):
        with pytest.raises((ValueError, Exception)):
            AddressingScheme("")


# ---------------------------------------------------------------------------
# Overflow / boundary
# ---------------------------------------------------------------------------

class TestBoundary:
    def setup_method(self):
        self.scheme = AddressingScheme()

    def test_host_idx_max_valid(self):
        # host_idx=253 yields 4th octet 254 — within 1-254
        assert self.scheme.host_ip(0, 253).endswith(".254")

    def test_host_idx_254_overflow(self):
        # host_idx=254 yields 4th octet 255 — invalid
        with pytest.raises(ValueError):
            self.scheme.host_ip(0, 254)

    def test_subnet_max_valid(self):
        # base 3rd=0, subnet_id=255 → o2=255 — valid
        assert self.scheme.host_ip(255, 0).startswith("192.168.255.")

    def test_subnet_overflow(self):
        # base 3rd=0, subnet_id=256 → o2=256 — invalid
        with pytest.raises(ValueError):
            self.scheme.host_ip(256, 0)

    def test_subnet_overflow_non_zero_base(self):
        scheme = AddressingScheme("172.20.0.0/16")  # 3rd base = 0, same as default
        with pytest.raises(ValueError):
            scheme.host_ip(256, 0)

    def test_negative_host_idx(self):
        with pytest.raises(ValueError):
            self.scheme.host_ip(1, -1)


# ---------------------------------------------------------------------------
# canonical_host_ip
# ---------------------------------------------------------------------------

class TestCanonicalHostIP:
    def setup_method(self):
        self.scheme = AddressingScheme()

    # multi-host link format
    def test_multi_host_single_link(self):
        mesh_links = [
            {"subnet": 3, "hosts": [0, 1, 2], "host_eth": {0: 0, 1: 0, 2: 0}},
        ]
        assert self.scheme.canonical_host_ip(0, mesh_links) == "192.168.3.1"
        assert self.scheme.canonical_host_ip(1, mesh_links) == "192.168.3.2"

    def test_multi_host_picks_minimum_subnet(self):
        mesh_links = [
            {"subnet": 5, "hosts": [0, 3], "host_eth": {0: 1, 3: 0}},
            {"subnet": 2, "hosts": [0, 1], "host_eth": {0: 0, 1: 0}},
        ]
        # host 0 is on both links; subnet 2 is smaller → should win
        assert self.scheme.canonical_host_ip(0, mesh_links) == "192.168.2.1"

    # point-to-point link format (host_a / host_b)
    def test_point_to_point_link(self):
        mesh_links = [
            {"subnet": 4, "host_a": 0, "host_b": 1, "host_a_eth": 0, "host_b_eth": 0},
        ]
        assert self.scheme.canonical_host_ip(0, mesh_links) == "192.168.4.1"
        assert self.scheme.canonical_host_ip(1, mesh_links) == "192.168.4.2"

    def test_mixed_formats_picks_minimum(self):
        mesh_links = [
            {"subnet": 7, "host_a": 0, "host_b": 2},
            {"subnet": 1, "hosts": [0, 1]},
        ]
        # host 0 appears in both; subnet 1 < 7
        assert self.scheme.canonical_host_ip(0, mesh_links) == "192.168.1.1"

    def test_host_not_in_any_link(self):
        mesh_links = [
            {"subnet": 1, "hosts": [1, 2]},
        ]
        with pytest.raises(ValueError, match="host 0"):
            self.scheme.canonical_host_ip(0, mesh_links)

    def test_empty_mesh_links(self):
        with pytest.raises(ValueError):
            self.scheme.canonical_host_ip(0, [])

    def test_custom_scheme_canonical(self):
        scheme = AddressingScheme("172.20.0.0/16")
        mesh_links = [{"subnet": 3, "hosts": [0, 1]}]
        assert scheme.canonical_host_ip(0, mesh_links) == "172.20.3.1"
