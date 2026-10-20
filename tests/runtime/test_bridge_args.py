"""Pure bridge argument parsing and validation helpers."""

import pytest

from src.runtime.command_runner import CommandResult

from src.runtime.bridge_args import (
    fail_closed_rc,
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


class TestFailClosedRc:
    """Both bridge modules read a finished command through this one ladder:
    only a run that actually exited 0 reads as success."""

    @pytest.mark.parametrize(
        "result, expected",
        [
            (CommandResult(0, stderr="warn"), (0, "warn")),
            (CommandResult(2, stderr="boom"), (2, "boom")),
            (CommandResult(0, stderr="partial", timed_out=True),
             (-1, "partial\ncommand timed out")),
            (CommandResult(0, cancelled=True), (-1, "command cancelled")),
            (CommandResult(None, stderr="x\n"), (-1, "x\nno exit status")),
            (CommandResult(0, timed_out=True, cancelled=True), (-1, "command timed out")),
        ],
        ids=["exit-0", "exit-nonzero", "timed-out", "cancelled", "no-exit-status",
             "timed-out-outranks-cancelled"],
    )
    def test_only_a_completed_zero_exit_reads_as_success(self, result, expected):
        assert fail_closed_rc(result) == expected
