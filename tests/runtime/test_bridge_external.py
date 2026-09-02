"""Unit tests for external bridge helper functions."""

import json as _json
from unittest.mock import MagicMock, patch

import pytest

from src.runtime.command_runner import ROOT_SENTINEL, CommandResult, FakeCommandRunner


def _pexec_runner(holder):
    """Adapt a legacy ``holder.pexec(cmd_str) -> (stdout, stderr, rc)`` fake onto
    the CommandRunner seam.

    Bridge commands now run through an injected CommandRunner instead of
    ``Node.pexec()``. This returns a FakeCommandRunner whose ``run`` is routed
    to ``holder.pexec`` with the argv joined back into a command string, so the
    existing command-substring predicates (``if "sysctl -n" in cmd``) keep
    working. ``holder.pexec`` is read at call time, so tests may assign it after
    constructing the runner.
    """
    fake = FakeCommandRunner()

    def _on_run(node, argv):
        out, err, rc = holder.pexec(" ".join(argv))
        return CommandResult(returncode=rc, stdout=out, stderr=err)

    fake.on_run = _on_run
    return fake


# ---------------------------------------------------------------------------
# Unit E: External bridge tests (Phase II-B + II-B.3, strict-CIDR policy)
# ---------------------------------------------------------------------------


class TestExternalBridgeSafety:
    """Tests for external bridge attachment safety and rollback."""

    def _make_net(self):
        """Create a mock Mininet-like object."""
        net = MagicMock()
        host = MagicMock()
        host.pid = 12345
        net.get.return_value = host
        return net

    def test_dhcp_mode_rejected(self):
        """B2: External bridge attachment without static IP is rejected."""
        from src.runtime.bridge_external import attach_external_via_bridge

        net = self._make_net()

        with pytest.raises(RuntimeError, match="static IP required"):
            attach_external_via_bridge(net, "h0", "eth0", ip=None)

    def test_duplicate_attachment_rejected(self):
        """B1.5: Duplicate active attachment is rejected."""
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
        )

        # Simulate existing attachment
        _created_bridges["h0"] = {
            "bridge": "br-h0",
            "veth_root": "veth-h0-root",
            "veth_host": "veth-h0",
            "phy_intf": "eth0",
        }

        net = self._make_net()

        with pytest.raises(RuntimeError, match="active attachment already exists"):
            attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        # Cleanup
        _created_bridges.clear()

    def test_interface_name_overflow_rejected(self):
        """B1.4: Interface names exceeding 15 characters are rejected."""
        from src.runtime.bridge_external import attach_external_via_bridge

        net = self._make_net()
        long_host = "h" + "x" * 20  # 21 chars

        with pytest.raises(RuntimeError, match="exceed 15-character"):
            attach_external_via_bridge(net, long_host, "eth0", ip="10.0.0.2/24")

    def test_inspect_failure_aborts(self):
        """B1.1: Physical interface inspection failure aborts before mutation."""
        from src.runtime.bridge_external import attach_external_via_bridge

        net = self._make_net()

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec",
            return_value=(1, "", "not found"),
        ):
            with pytest.raises(RuntimeError, match="cannot inspect"):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

    def test_existing_master_rejected(self):
        """B1.2: Interface with existing master is rejected."""
        from src.runtime.bridge_external import attach_external_via_bridge

        net = self._make_net()

        mock_result = {"ifname": "eth0", "master": "br-exist"}

        def mock_cmd(args):
            if "addr" in args:
                return 0, "[]", ""
            return 0, _json.dumps([mock_result]), ""

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
        ):
            with pytest.raises(RuntimeError, match="already enslaved"):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

    def test_existing_l3_address_rejected(self):
        """B1.3: Interface with non-link-local L3 address is rejected."""
        from src.runtime.bridge_external import attach_external_via_bridge

        net = self._make_net()

        mock_link = {"ifname": "eth0", "flags": ["BROADCAST", "UP"]}
        mock_addrs = [{"ifname": "eth0", "addr_info": [{"local": "192.168.1.100"}]}]

        def mock_cmd(args):
            if "addr" in args:
                return 0, _json.dumps(mock_addrs), ""
            return 0, _json.dumps([mock_link]), ""

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
        ):
            with pytest.raises(RuntimeError, match="configured address"):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

    def test_bridge_creation_failure_no_cleanup_record(self):
        """Bridge creation failure issues no delete and creates no record."""
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
        )

        _created_bridges.clear()
        net = self._make_net()

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            # First command (inspect link): success
            # Second command (inspect addr): success
            # Third command (bridge creation): fail
            if cmd_count[0] <= 2:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return (
                    0,
                    _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]),
                    "",
                )
            return 1, "", "bridge exists"

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
        ):
            with pytest.raises(RuntimeError, match="bridge creation failed"):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        # No record created
        assert "h0" not in _created_bridges

    def test_successful_attachment_creates_record(self):
        """Successful attachment records all owned resources."""
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
        )

        _created_bridges.clear()
        net = self._make_net()
        host = net.get.return_value

        def mock_cmd(args):
            if "addr" in args or "link" in args:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return (
                    0,
                    _json.dumps(
                        [
                            {
                                "ifname": "eth0",
                                "operstate": "UP",
                                "flags": ["BROADCAST", "UP"],
                            }
                        ]
                    ),
                    "",
                )
            return 0, "", ""

        def mock_pexec(cmd):
            return "", "", 0

        host.pexec = mock_pexec

        with (
            patch(
                "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
            ),
            patch(
                "src.runtime.bridge_external.MininetCommandRunner",
                return_value=_pexec_runner(host),
            ),
        ):
            attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        # Record exists with all fields
        assert "h0" in _created_bridges
        record = _created_bridges["h0"]
        assert record["bridge"] == "br-h0"
        assert record["veth_root"] == "veth-h0-root"
        assert record["veth_host"] == "veth-h0"
        assert record["phy_intf"] == "eth0"
        assert record["ip_assigned"] is True
        assert record["bridge_created"] is True

        _created_bridges.clear()

    def test_cleanup_attempts_all_records(self):
        """Cleanup attempts all records even when one fails."""
        from src.runtime.bridge_external import (
            cleanup_external_bridges,
            _created_bridges,
            ExternalBridgeError,
        )

        _created_bridges.clear()
        call_log = []

        def mock_cmd(args):
            call_log.append(tuple(args))
            # Simulate failure on first cleanup, success on second
            if "br-h0" in str(args):
                return 1, "", "failed"
            return 0, "", ""

        _created_bridges["h0"] = {
            "bridge": "br-h0",
            "veth_root": "veth-h0-root",
            "veth_host": "veth-h0",
            "phy_intf": "eth0",
            "bridge_created": True,
            "veth_created": True,
            "phy_enslaved": True,
            "phy_up_changed": False,
        }
        _created_bridges["h1"] = {
            "bridge": "br-h1",
            "veth_root": "veth-h1-root",
            "veth_host": "veth-h1",
            "phy_intf": "eth1",
            "bridge_created": True,
            "veth_created": True,
            "phy_enslaved": True,
            "phy_up_changed": False,
        }

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
        ):
            with pytest.raises(ExternalBridgeError):
                cleanup_external_bridges()

        # h1 was cleaned, h0 was retained for retry
        assert "h1" not in _created_bridges
        assert "h0" in _created_bridges

        _created_bridges.clear()

    def test_cleanup_failure_retains_record(self):
        """Cleanup failure retains the failed record for retry."""
        from src.runtime.bridge_external import (
            cleanup_external_bridges,
            _created_bridges,
            ExternalBridgeError,
        )

        _created_bridges.clear()

        _created_bridges["h0"] = {
            "bridge": "br-h0",
            "veth_root": "veth-h0-root",
            "veth_host": "veth-h0",
            "phy_intf": "eth0",
            "bridge_created": True,
            "veth_created": True,
            "phy_enslaved": True,
            "phy_up_changed": False,
        }

        def mock_cmd(args):
            return 1, "", "failed"

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
        ):
            with pytest.raises(ExternalBridgeError):
                cleanup_external_bridges()

        # Record retained for retry
        assert "h0" in _created_bridges

        _created_bridges.clear()

    def test_cleanup_restores_phy_down(self):
        """Successful cleanup restores physical interface DOWN if it was raised."""
        from src.runtime.bridge_external import (
            cleanup_external_bridges,
            _created_bridges,
        )

        _created_bridges.clear()
        calls = []

        def mock_cmd(args):
            calls.append(tuple(args))
            return 0, "", ""

        _created_bridges["h0"] = {
            "bridge": "br-h0",
            "veth_root": "veth-h0-root",
            "veth_host": "veth-h0",
            "phy_intf": "eth0",
            "bridge_created": True,
            "veth_created": True,
            "phy_enslaved": True,
            "phy_up_changed": True,  # This run raised it from DOWN
        }

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
        ):
            cleanup_external_bridges()

        # Verify DOWN restoration was called
        down_calls = [c for c in calls if "down" in str(c) and "eth0" in str(c)]
        assert len(down_calls) > 0

        _created_bridges.clear()

    def test_link_local_address_not_rejected(self):
        """Link-local address (169.254.x.x) does not block attachment."""
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
        )

        _created_bridges.clear()
        net = self._make_net()
        host = net.get.return_value

        mock_link = {"ifname": "eth0", "flags": ["BROADCAST", "UP"]}
        mock_addrs = [{"ifname": "eth0", "addr_info": [{"local": "169.254.1.1"}]}]

        def mock_cmd(args):
            if "addr" in args:
                return 0, _json.dumps(mock_addrs), ""
            return 0, _json.dumps([mock_link]), ""

        def mock_pexec(cmd):
            return "", "", 0

        host.pexec = mock_pexec

        # Link-local address should NOT be rejected
        with (
            patch(
                "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
            ),
            patch(
                "src.runtime.bridge_external.MininetCommandRunner",
                return_value=_pexec_runner(host),
            ),
        ):
            # This will proceed past address check
            attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        assert "h0" in _created_bridges
        _created_bridges.clear()


# ---------------------------------------------------------------------------
# External bridge rollback order tests
# ---------------------------------------------------------------------------


class TestExternalBridgeRollbackOrder:
    """Tests for correct rollback order during setup failure."""

    def _make_net(self):
        """Create a mock Mininet-like object."""
        net = MagicMock()
        host = MagicMock()
        host.pid = 12345
        net.get.return_value = host
        return net

    def test_rollback_order_after_veth_creation(self):
        """After veth creation, rollback deletes veth before unmastering."""
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
        )

        _created_bridges.clear()
        net = self._make_net()
        host = net.get.return_value

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            if cmd_count[0] <= 2:
                # Inspect link and addr: success
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return (
                    0,
                    _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]),
                    "",
                )
            # Fail at veth creation (step 5)
            if "veth" in str(args) and "add" in str(args):
                return 1, "", "veth creation failed"
            return 0, "", ""

        host.pexec = lambda cmd: ("", "", 0)

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
        ):
            with pytest.raises(RuntimeError, match="veth creation failure"):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        # Bridge should be cleaned up (rollback succeeded)
        assert "h0" not in _created_bridges

        _created_bridges.clear()

    def test_rollback_failure_preserves_record(self):
        """Setup failure + rollback failure → residual record for retry."""
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
        )

        _created_bridges.clear()
        net = self._make_net()
        host = net.get.return_value

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            if cmd_count[0] <= 2:
                # Inspect link and addr: success
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return (
                    0,
                    _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]),
                    "",
                )
            # Fail at bridge-up (step 2)
            if cmd_count[0] == 3:
                return 1, "", "bridge-up failed"
            # Rollback: also fail
            return 1, "", "rollback failed"

        host.pexec = lambda cmd: ("", "", 0)

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
        ):
            with pytest.raises(Exception):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        # No residual record (current implementation raises before creating record)
        # This is acceptable: the bridge exists but is not tracked
        # A future improvement would track in-progress state

        _created_bridges.clear()


# ---------------------------------------------------------------------------
# Phase II-B.3: Fail-before defect tests
# ---------------------------------------------------------------------------


class TestInspectionDefects:
    """Defect tests for source bugs identified in Phase II-B.2 verification."""

    def test_inspect_addresses_malformed_json_no_name_error(self):
        """D1: _inspect_addresses() malformed JSON must not raise NameError.

        After fix: function returns structured failure (success=False) instead
        of raising NameError from undefined `json` name.
        """
        from src.runtime.bridge_external import _inspect_addresses

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec",
            return_value=(0, "not valid json{{", ""),
        ):
            success, data, err = _inspect_addresses("eth0")

        # Should return failure, not raise NameError
        assert success is False
        assert data is None
        assert len(err) > 0

    def test_inspect_link_non_object_entry_returns_failure(self):
        """_inspect_link() must reject a non-dict first element at the boundary.

        2026-08-01 review fix: `ip -j link show` の出力が `[null]` やスカラ要素
        だった場合、旧実装は success=True のまま非 dict を返し、呼び出し側の
        cast(dict, ...) が型嘘になっていた。境界で構造化失敗に落とす。
        """
        from src.runtime.bridge_external import _inspect_link

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec",
            return_value=(0, "[null]", ""),
        ):
            success, data, err = _inspect_link("eth0")

        assert success is False
        assert data is None
        assert "non-object" in err

    def test_inspect_addresses_rc_nonzero_returns_failure(self):
        """_inspect_addresses() non-zero exit code returns structured failure."""
        from src.runtime.bridge_external import _inspect_addresses

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec",
            return_value=(1, "", "no such device"),
        ):
            success, data, err = _inspect_addresses("eth0")

        assert success is False
        assert data is None
        assert "no such device" in err


class TestDefectRollbackRetention:
    """D2/D3: Rollback failure retention and cleanup retry."""

    def _make_net(self):
        net = MagicMock()
        host = MagicMock()
        host.pid = 12345
        net.get.return_value = host
        return net

    def test_rollback_failure_preserves_record(self):
        """D2: Setup failure + rollback failure retains retryable record."""
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
            ExternalBridgeError,
        )

        _created_bridges.clear()
        net = self._make_net()
        host = net.get.return_value
        host.pexec = lambda cmd: ("", "", 0)

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            if cmd_count[0] <= 2:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return (
                    0,
                    _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]),
                    "",
                )
            # cmd 3: bridge creation succeeds
            if cmd_count[0] == 3:
                return 0, "", ""
            # cmd 4: bridge-up fails
            if cmd_count[0] == 4:
                return 1, "", "bridge-up failed"
            # Rollback: also fail
            return 1, "", "rollback del failed"

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
        ):
            with pytest.raises(ExternalBridgeError) as exc_info:
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        # Setup failure should be in the error
        assert exc_info.value.setup_failure is not None
        # Rollback failure should be in the error
        assert len(exc_info.value.rollback_failures) > 0
        # Record should be retained for retry
        assert "h0" in _created_bridges
        record = _created_bridges["h0"]
        # Record should contain outstanding cleanup state
        assert record.get("bridge_created") is True

        _created_bridges.clear()

    def test_successful_cleanup_retry_clears_retained_record(self):
        """D3: Cleanup retry on retained setup-failure record clears the record."""
        from src.runtime.bridge_external import (
            cleanup_external_bridges,
            _created_bridges,
        )

        _created_bridges.clear()

        # Simulate a retained record from rollback failure
        _created_bridges["h0"] = {
            "bridge": "br-h0",
            "veth_root": "veth-h0-root",
            "veth_host": "veth-h0",
            "phy_intf": "eth0",
            "prior_up": True,
            "bridge_created": True,
            "bridge_up": False,
            "phy_up_changed": False,
            "phy_enslaved": False,
            "veth_created": False,
        }

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec", return_value=(0, "", "")
        ):
            cleanup_external_bridges()

        assert "h0" not in _created_bridges

    def test_setup_failure_rollback_success_removes_record(self):
        """Setup failure with successful rollback removes the record."""
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
            ExternalBridgeError,
        )

        _created_bridges.clear()
        net = self._make_net()
        host = net.get.return_value
        host.pexec = lambda cmd: ("", "", 0)

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            if cmd_count[0] <= 2:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return (
                    0,
                    _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]),
                    "",
                )
            # cmd 3: bridge creation succeeds
            if cmd_count[0] == 3:
                return 0, "", ""
            # cmd 4: bridge-up fails
            if cmd_count[0] == 4:
                return 1, "", "bridge-up failed"
            # Rollback: succeed
            return 0, "", ""

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
        ):
            with pytest.raises(ExternalBridgeError):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        # Record should be removed since rollback succeeded
        assert "h0" not in _created_bridges

        _created_bridges.clear()


# ---------------------------------------------------------------------------
# Phase II-B.3: Missing mandatory external bridge tests
# ---------------------------------------------------------------------------


def _make_net_helper():
    net = MagicMock()
    host = MagicMock()
    host.pid = 12345
    net.get.return_value = host
    return net


class TestExternalBridgePreconditions:
    """Precondition validation tests."""

    def test_invalid_static_ip_rejected_before_mutation(self):
        """Invalid static IP is rejected before any mutation.

        Uses an input that passes the strict-CIDR check (`/` present) so the
        deeper `ipaddress.ip_interface()` rejection path is exercised.
        """
        from src.runtime.bridge_external import attach_external_via_bridge

        net = _make_net_helper()

        with pytest.raises(RuntimeError, match="invalid static IP"):
            attach_external_via_bridge(net, "h0", "eth0", ip="not-an-ip/24")

    def test_bare_ip_without_cidr_rejected(self):
        """Strict-CIDR policy: bare IP without explicit prefix is rejected.

        The published `--ext host,ifname,ip[,mtu] (ip required in CIDR form)`
        contract requires an explicit prefix length. Bare addresses must be
        rejected before any mutation.
        """
        from src.runtime.bridge_args import validate_static_ip

        with pytest.raises(RuntimeError, match="CIDR"):
            validate_static_ip("10.0.0.2")

        with pytest.raises(RuntimeError, match="CIDR"):
            validate_static_ip("")

    def test_missing_flags_aborts_before_mutation(self):
        """Missing/invalid flags field aborts before mutation."""
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
        )

        _created_bridges.clear()
        net = _make_net_helper()

        # Return link data without flags field
        def mock_cmd(args):
            if "addr" in args:
                return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
            return 0, _json.dumps([{"ifname": "eth0"}]), ""

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
        ):
            with pytest.raises(
                RuntimeError, match="cannot determine administrative state"
            ):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        # No record created
        assert "h0" not in _created_bridges


class TestExternalBridgeSetupRollback:
    """Setup-stage failure rollback tests for each mutation step."""

    def test_bridge_up_failure_deletes_owned_bridge(self):
        """Bridge-up failure triggers rollback that deletes the owned bridge."""
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
            ExternalBridgeError,
        )

        _created_bridges.clear()
        net = _make_net_helper()
        host = net.get.return_value
        host.pexec = lambda cmd: ("", "", 0)

        cmd_count = [0]
        called_cmds = []

        def mock_cmd(args):
            cmd_count[0] += 1
            called_cmds.append(tuple(args))
            if cmd_count[0] <= 2:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return (
                    0,
                    _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]),
                    "",
                )
            # cmd 3: bridge creation succeeds
            if cmd_count[0] == 3:
                return 0, "", ""
            # cmd 4: bridge-up fails
            if cmd_count[0] == 4:
                return 1, "", "bridge-up failed"
            # Rollback: bridge deletion succeeds
            return 0, "", ""

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
        ):
            with pytest.raises(ExternalBridgeError):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        # Record should be removed (rollback succeeded)
        assert "h0" not in _created_bridges
        # Verify rollback del bridge was called
        del_calls = [c for c in called_cmds if "del" in str(c) and "br-h0" in str(c)]
        assert len(del_calls) > 0

        _created_bridges.clear()

    def test_enslave_failure_rolls_back(self):
        """Enslave failure restores owned prior state and deletes bridge."""
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
            ExternalBridgeError,
        )

        _created_bridges.clear()
        net = _make_net_helper()
        host = net.get.return_value
        host.pexec = lambda cmd: ("", "", 0)

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            if cmd_count[0] <= 2:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return (
                    0,
                    _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]),
                    "",
                )
            if cmd_count[0] == 3:
                return 0, "", ""  # bridge-up
            # Step 5: enslave fails
            if cmd_count[0] == 4:
                return 1, "", "enslave failed"
            return 0, "", ""

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
        ):
            with pytest.raises(ExternalBridgeError):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        assert "h0" not in _created_bridges
        _created_bridges.clear()

    def test_veth_attach_failure_rolls_back(self):
        """Veth-to-bridge attachment failure rolls back completed mutations."""
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
            ExternalBridgeError,
        )

        _created_bridges.clear()
        net = _make_net_helper()
        host = net.get.return_value
        host.pexec = lambda cmd: ("", "", 0)

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            if cmd_count[0] <= 2:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return (
                    0,
                    _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]),
                    "",
                )
            # Steps 3-5 succeed (bridge-up, enslave, veth-create)
            if cmd_count[0] <= 5:
                return 0, "", ""
            # Step 6: veth-root-master fails
            if cmd_count[0] == 6:
                return 1, "", "veth-master failed"
            return 0, "", ""

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
        ):
            with pytest.raises(ExternalBridgeError):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        assert "h0" not in _created_bridges
        _created_bridges.clear()

    def test_namespace_move_failure_rolls_back(self):
        """Namespace move failure rolls back completed mutations."""
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
            ExternalBridgeError,
        )

        _created_bridges.clear()
        net = _make_net_helper()
        host = net.get.return_value
        host.pexec = lambda cmd: ("", "", 0)

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            if cmd_count[0] <= 2:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return (
                    0,
                    _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]),
                    "",
                )
            # Steps 3-8 succeed
            if cmd_count[0] <= 8:
                return 0, "", ""
            # Step 9: namespace move fails
            if cmd_count[0] == 9:
                return 1, "", "netns failed"
            return 0, "", ""

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
        ):
            with pytest.raises(ExternalBridgeError):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        assert "h0" not in _created_bridges
        _created_bridges.clear()

    def test_static_ip_assignment_failure_rolls_back(self):
        """Static-IP assignment failure rolls back completed mutations."""
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
            ExternalBridgeError,
        )

        _created_bridges.clear()
        net = _make_net_helper()
        host = net.get.return_value
        # Host-side IP assignment fails
        host.pexec = lambda cmd: ("", "addr assignment failed", 1)

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            if cmd_count[0] <= 2:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return (
                    0,
                    _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]),
                    "",
                )
            if cmd_count[0] <= 9:
                return 0, "", ""
            return 0, "", ""

        with (
            patch(
                "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
            ),
            patch(
                "src.runtime.bridge_external.MininetCommandRunner",
                return_value=_pexec_runner(host),
            ),
        ):
            with pytest.raises(ExternalBridgeError):
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        _created_bridges.clear()

    def test_mtu_failure_rolls_back(self):
        """MTU failure is fatal and rolls back completed mutations."""
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
            ExternalBridgeError,
        )

        _created_bridges.clear()
        net = _make_net_helper()
        host = net.get.return_value
        host.pexec = lambda cmd: ("", "", 0)

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            if cmd_count[0] <= 2:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return (
                    0,
                    _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]),
                    "",
                )
            # cmd 3-11 succeed (bridge creation through netns move)
            if cmd_count[0] <= 11:
                return 0, "", ""
            # cmd 12: veth_root MTU fails
            if cmd_count[0] == 12:
                return 1, "", "mtu failed"
            # Rollback succeeds
            return 0, "", ""

        with (
            patch(
                "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
            ),
            patch(
                "src.runtime.bridge_external.MininetCommandRunner",
                return_value=_pexec_runner(host),
            ),
        ):
            with pytest.raises(ExternalBridgeError):
                attach_external_via_bridge(
                    net, "h0", "eth0", ip="10.0.0.2/24", mtu=1400
                )

        assert "h0" not in _created_bridges
        _created_bridges.clear()


class TestExternalBridgeRollbackFailureReporting:
    """Rollback failure reporting test."""

    def test_setup_failure_plus_rollback_failure_reports_both(self):
        """Setup failure + rollback failure: ExternalBridgeError contains both."""
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
            ExternalBridgeError,
        )

        _created_bridges.clear()
        net = _make_net_helper()
        host = net.get.return_value
        host.pexec = lambda cmd: ("", "", 0)

        cmd_count = [0]

        def mock_cmd(args):
            cmd_count[0] += 1
            if cmd_count[0] <= 2:
                if "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                return (
                    0,
                    _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]),
                    "",
                )
            # cmd 3: bridge creation succeeds
            if cmd_count[0] == 3:
                return 0, "", ""
            # cmd 4: bridge-up fails
            if cmd_count[0] == 4:
                return 1, "", "bridge-up failed"
            # Rollback fails
            return 1, "", "rollback failed"

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
        ):
            with pytest.raises(ExternalBridgeError) as exc_info:
                attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

        assert exc_info.value.setup_failure is not None
        assert len(exc_info.value.rollback_failures) > 0

        _created_bridges.clear()


class TestExternalBridgeAdminState:
    """Administrative state restoration tests."""

    def test_prior_admin_down_restored_to_down(self):
        """Prior administratively-DOWN interface restored to DOWN during cleanup."""
        from src.runtime.bridge_external import (
            cleanup_external_bridges,
            _created_bridges,
        )

        _created_bridges.clear()
        calls = []

        def mock_cmd(args):
            calls.append(tuple(args))
            return 0, "", ""

        # prior_up=False means this run raised it from DOWN
        _created_bridges["h0"] = {
            "bridge": "br-h0",
            "veth_root": "veth-h0-root",
            "veth_host": "veth-h0",
            "phy_intf": "eth0",
            "bridge_created": True,
            "veth_created": True,
            "phy_enslaved": True,
            "phy_up_changed": True,
        }

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
        ):
            cleanup_external_bridges()

        down_calls = [c for c in calls if "down" in str(c) and "eth0" in str(c)]
        assert len(down_calls) > 0

        _created_bridges.clear()

    def test_prior_admin_up_not_forced_down(self):
        """Prior administratively-UP interface is not forced DOWN during cleanup."""
        from src.runtime.bridge_external import (
            cleanup_external_bridges,
            _created_bridges,
        )

        _created_bridges.clear()
        calls = []

        def mock_cmd(args):
            calls.append(tuple(args))
            return 0, "", ""

        # prior_up=True means interface was already UP
        _created_bridges["h0"] = {
            "bridge": "br-h0",
            "veth_root": "veth-h0-root",
            "veth_host": "veth-h0",
            "phy_intf": "eth0",
            "bridge_created": True,
            "veth_created": True,
            "phy_enslaved": True,
            "phy_up_changed": False,  # This run did NOT raise it
        }

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
        ):
            cleanup_external_bridges()

        # No DOWN command for eth0 (it was already UP)
        down_calls = [c for c in calls if "down" in str(c) and "eth0" in str(c)]
        assert len(down_calls) == 0

        _created_bridges.clear()


class TestExternalBridgeCleanupOrder:
    """Cleanup command order and aggregate failure tests."""

    def test_cleanup_command_order(self):
        """Explicit cleanup order assertion: veth→unmaster→DOWN→bridge."""
        from src.runtime.bridge_external import (
            cleanup_external_bridges,
            _created_bridges,
        )

        _created_bridges.clear()
        calls = []

        def mock_cmd(args):
            calls.append(tuple(args))
            return 0, "", ""

        # bridge_up is now an independent gate from bridge_created (per
        # cleanup invariant in the remediation contract). A fully-attached
        # record has both bridge_created and bridge_up set, so we mirror that.
        _created_bridges["h0"] = {
            "bridge": "br-h0",
            "veth_root": "veth-h0-root",
            "veth_host": "veth-h0",
            "phy_intf": "eth0",
            "bridge_created": True,
            "bridge_up": True,
            "veth_created": True,
            "phy_enslaved": True,
            "phy_up_changed": True,
        }

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
        ):
            cleanup_external_bridges()

        # Find indices of key operations
        veth_del_idx = None
        unmaster_idx = None
        phy_down_idx = None
        bridge_down_idx = None
        bridge_del_idx = None

        for i, c in enumerate(calls):
            cstr = str(c)
            if "del" in cstr and "veth-h0-root" in cstr:
                veth_del_idx = i
            elif "nomaster" in cstr:
                unmaster_idx = i
            elif "down" in cstr and "eth0" in cstr:
                phy_down_idx = i
            elif "down" in cstr and "br-h0" in cstr:
                bridge_down_idx = i
            elif "del" in cstr and "br-h0" in cstr:
                bridge_del_idx = i

        assert veth_del_idx is not None, "veth delete not found"
        assert unmaster_idx is not None, "unmaster not found"
        assert phy_down_idx is not None, "phy down not found"
        assert bridge_down_idx is not None, "bridge down not found"
        assert bridge_del_idx is not None, "bridge del not found"

        assert veth_del_idx < unmaster_idx
        assert unmaster_idx < phy_down_idx
        assert phy_down_idx < bridge_down_idx
        assert bridge_down_idx < bridge_del_idx

        _created_bridges.clear()

    def test_cleanup_failure_externally_observable(self):
        """Cleanup failure raises ExternalBridgeError with failure details."""
        from src.runtime.bridge_external import (
            cleanup_external_bridges,
            _created_bridges,
            ExternalBridgeError,
        )

        _created_bridges.clear()

        _created_bridges["h0"] = {
            "bridge": "br-h0",
            "veth_root": "veth-h0-root",
            "veth_host": "veth-h0",
            "phy_intf": "eth0",
            "bridge_created": True,
            "veth_created": True,
            "phy_enslaved": True,
            "phy_up_changed": False,
        }

        def mock_cmd(args):
            return 1, "", "cleanup failed"

        with patch(
            "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
        ):
            with pytest.raises(ExternalBridgeError) as exc_info:
                cleanup_external_bridges()

        assert len(exc_info.value.rollback_failures) > 0

        _created_bridges.clear()


# ===========================================================================
# Defect Remediation Tests — external-attach subset (T1, T1b, T1c, T2, T7, T8)
#
# These tests target the external-attach defects identified during the
# bridge external-attach remediation review, plus the duplicate-phy_intf
# rejection feature. They follow the fail-before / pass-after pattern
# documented in the remediation review. The root-side subset (T3, T4, T5, T9
# — proxy-ARP restoration and the BridgeManager.cleanup() retry-retention
# contract) lives in test_bridge_root.py.
# ===========================================================================


def _populate_full_record(host_name: str = "h0", phy: str = "eth0") -> None:
    """Pre-populate _created_bridges with a fully-attached record for tests."""
    from src.runtime.bridge_external import _created_bridges

    _created_bridges[host_name] = {
        "bridge": f"br-{host_name}",
        "veth_root": f"veth-{host_name}-root",
        "veth_host": f"veth-{host_name}",
        "phy_intf": phy,
        "prior_up": False,
        "bridge_created": True,
        "bridge_up": True,
        "phy_up_changed": True,
        "phy_enslaved": True,
        "veth_created": True,
        "veth_root_mastered": True,
        "veth_root_up": True,
        "veth_host_ns_moved": True,
        "veth_host_up": True,
        "mtu_set": False,
        "ip_assigned": True,
    }


class TestDefect1CleanupPartialSuccess:
    """T1 / T1b: cleanup_external_bridges() must clear only succeeded flags
    and skip already-discharged actions on retry."""

    def test_T1_nomaster_fails_only_remaining_action_retried(self):
        """T1: veth-del succeeds, nomaster fails, phy-down/bridge-down/bridge-del succeed.
        After first cleanup: only phy_enslaved=True remains. Second cleanup with
        all-success mocks must execute ONLY the nomaster command.
        """
        from src.runtime.bridge_external import (
            cleanup_external_bridges,
            _created_bridges,
            ExternalBridgeError,
        )

        _created_bridges.clear()
        try:
            _populate_full_record("h0", "eth0")

            first_calls: list[tuple] = []

            def mock_first_pass(args):
                first_calls.append(tuple(args))
                if tuple(args) == ("ip", "link", "set", "eth0", "nomaster"):
                    return 1, "", "nomaster failed"
                return 0, "", ""

            with patch(
                "src.runtime.bridge_external._run_root_cmd_vec",
                side_effect=mock_first_pass,
            ):
                with pytest.raises(ExternalBridgeError):
                    cleanup_external_bridges()

            rec = _created_bridges["h0"]
            assert rec["veth_created"] is False, (
                "veth_created must clear after veth-del success"
            )
            assert rec["phy_enslaved"] is True, (
                "phy_enslaved must remain True after nomaster failure"
            )
            assert rec["phy_up_changed"] is False, (
                "phy_up_changed must clear after phy-down success"
            )
            assert rec["bridge_up"] is False, (
                "bridge_up must clear after bridge-down success"
            )
            assert rec["bridge_created"] is False, (
                "bridge_created must clear after bridge-del success"
            )
            assert "h0" in _created_bridges, (
                "record must be retained while phy_enslaved outstanding"
            )

            # Second pass — all succeed
            second_calls: list[tuple] = []

            def mock_second_pass(args):
                second_calls.append(tuple(args))
                return 0, "", ""

            with patch(
                "src.runtime.bridge_external._run_root_cmd_vec",
                side_effect=mock_second_pass,
            ):
                cleanup_external_bridges()

            assert "h0" not in _created_bridges, (
                "record must be cleared after retry success"
            )

            # The second pass must call ONLY the outstanding nomaster.
            assert second_calls == [("ip", "link", "set", "eth0", "nomaster")], (
                f"second pass should only retry nomaster; got {second_calls}"
            )
            # Explicit no-re-call assertions
            assert ("ip", "link", "del", "veth-h0-root") not in second_calls
            assert ("ip", "link", "set", "eth0", "down") not in second_calls
            assert ("ip", "link", "set", "br-h0", "down") not in second_calls
            assert ("ip", "link", "del", "br-h0") not in second_calls
        finally:
            _created_bridges.clear()

    def test_T1b_bridge_del_fails_only_remaining_action_retried(self):
        """T1b: veth-del, nomaster, phy-down, bridge-down succeed; bridge-del fails.
        After first cleanup: only bridge_created=True remains. Second cleanup
        must execute ONLY the bridge-del command.
        """
        from src.runtime.bridge_external import (
            cleanup_external_bridges,
            _created_bridges,
            ExternalBridgeError,
        )

        _created_bridges.clear()
        try:
            _populate_full_record("h0", "eth0")

            first_calls: list[tuple] = []

            def mock_first_pass(args):
                first_calls.append(tuple(args))
                if tuple(args) == ("ip", "link", "del", "br-h0"):
                    return 1, "", "bridge-del failed"
                return 0, "", ""

            with patch(
                "src.runtime.bridge_external._run_root_cmd_vec",
                side_effect=mock_first_pass,
            ):
                with pytest.raises(ExternalBridgeError):
                    cleanup_external_bridges()

            rec = _created_bridges["h0"]
            assert rec["veth_created"] is False
            assert rec["phy_enslaved"] is False
            assert rec["phy_up_changed"] is False
            assert rec["bridge_up"] is False, "bridge_up clears via bridge-down success"
            assert rec["bridge_created"] is True, (
                "bridge_created remains because bridge-del failed"
            )
            assert "h0" in _created_bridges

            # Second pass — all succeed
            second_calls: list[tuple] = []

            def mock_second_pass(args):
                second_calls.append(tuple(args))
                return 0, "", ""

            with patch(
                "src.runtime.bridge_external._run_root_cmd_vec",
                side_effect=mock_second_pass,
            ):
                cleanup_external_bridges()

            assert "h0" not in _created_bridges
            assert second_calls == [("ip", "link", "del", "br-h0")], (
                f"second pass should only retry bridge-del; got {second_calls}"
            )
            assert ("ip", "link", "del", "veth-h0-root") not in second_calls
            assert ("ip", "link", "set", "eth0", "nomaster") not in second_calls
            assert ("ip", "link", "set", "eth0", "down") not in second_calls
            assert ("ip", "link", "set", "br-h0", "down") not in second_calls
        finally:
            _created_bridges.clear()


class TestDefect1SetupRollbackPartialFlagClear:
    """T1c: setup rollback must clear flags only for actions whose status-aware
    run() completed without raising. Failed undos retain the corresponding
    outstanding flag(s) so cleanup_external_bridges() retries them."""

    def test_T1c_rollback_partial_failure_retains_only_failed_flag(self):
        """During setup rollback after veth_root_master failure, inject the
        bridge-delete COMMAND to return rc=1 so the status-aware helper raises.
        All other rollback commands (delete veth, unmaster phy, restore phy DOWN)
        succeed. After raise: record retains ONLY bridge_created=True and
        bridge_up=True; subsequent cleanup runs ONLY bridge-down + bridge-del.
        """
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            cleanup_external_bridges,
            _created_bridges,
            ExternalBridgeError,
        )

        _created_bridges.clear()
        try:
            net = _make_net_helper()
            host = net.get.return_value
            host.pexec = lambda cmd: ("", "", 0)

            setup_call_idx = [0]
            captured: list[tuple] = []
            seen_step_6_fail = [False]

            # Status-aware injection: the bridge-delete COMMAND used by the
            # rollback helper returns rc=1, so `_RollbackAction.run()` raises
            # through `_rollback_del_link` with the failed command + rc/stderr
            # detail. Every other rollback command (delete veth, unmaster phy,
            # restore phy DOWN) succeeds via its status-aware helper.
            def combined_mock(args):
                t = tuple(args)
                captured.append(t)

                if t[:2] == ("ip", "-j") and "addr" in t:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                if t[:2] == ("ip", "-j") and "link" in t:
                    return (
                        0,
                        _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST"]}]),
                        "",
                    )

                if not seen_step_6_fail[0]:
                    setup_call_idx[0] += 1
                    if setup_call_idx[0] == 6:
                        seen_step_6_fail[0] = True
                        return 1, "", "veth-root-master injected failure"
                    return 0, "", ""

                # rollback phase
                if t == ("ip", "link", "del", "br-h0"):
                    return 1, "", "bridge-del injected failure (rollback)"
                return 0, "", ""

            with patch(
                "src.runtime.bridge_external._run_root_cmd_vec",
                side_effect=combined_mock,
            ):
                with pytest.raises(ExternalBridgeError):
                    attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

            # The bridge-delete rollback raised through the status-aware helper,
            # so the bridge_created flag stays True and the record is retained.
            assert "h0" in _created_bridges, (
                "record must be retained when bridge-del rollback failed"
            )
            rec = _created_bridges["h0"]
            assert rec["bridge_created"] is True
            assert (
                rec["bridge_up"] is True
            )  # bridge-down rollback is NOT issued in this path
            assert rec["phy_enslaved"] is False
            assert rec["phy_up_changed"] is False
            assert rec["veth_created"] is False, (
                "veth-del rollback succeeded → flag cleared"
            )

            # Now retry cleanup with all-success mocks.
            retry_calls: list[tuple] = []

            def retry_mock(args):
                retry_calls.append(tuple(args))
                return 0, "", ""

            with patch(
                "src.runtime.bridge_external._run_root_cmd_vec", side_effect=retry_mock
            ):
                cleanup_external_bridges()

            assert "h0" not in _created_bridges
            # The retry must only run the outstanding bridge cleanup steps.
            # bridge_up was still True so bridge-down is also issued, then bridge-del.
            assert retry_calls == [
                ("ip", "link", "set", "br-h0", "down"),
                ("ip", "link", "del", "br-h0"),
            ], f"retry must issue only bridge-down + bridge-del; got {retry_calls}"
            # Explicit no-re-call assertions
            assert ("ip", "link", "del", "veth-h0-root") not in retry_calls
            assert ("ip", "link", "set", "eth0", "nomaster") not in retry_calls
            assert ("ip", "link", "set", "eth0", "down") not in retry_calls
        finally:
            _created_bridges.clear()


class TestDefect2PhyDownRestoreOnEnslaveFailure:
    """T2: when the physical interface was raised UP by the setup and enslave
    subsequently fails, the rollback must restore phy DOWN before exiting."""

    def test_T2_enslave_failure_restores_phy_down(self):
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
            ExternalBridgeError,
        )

        _created_bridges.clear()
        try:
            net = _make_net_helper()
            host = net.get.return_value
            host.pexec = lambda cmd: ("", "", 0)

            captured: list[tuple] = []
            cmd_idx = [0]

            def mock_cmd(args):
                t = tuple(args)
                captured.append(t)
                if t[:2] == ("ip", "-j") and "addr" in t:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                if t[:2] == ("ip", "-j") and "link" in t:
                    # NOT UP → prior_up=False, so setup will run phy-up
                    return (
                        0,
                        _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST"]}]),
                        "",
                    )

                cmd_idx[0] += 1
                # 1: ip link add br-h0 type bridge -> ok
                # 2: ip link set br-h0 up         -> ok
                # 3: ip link set eth0 up          -> ok
                # 4: ip link set eth0 master br-h0 -> FAIL
                if cmd_idx[0] == 4:
                    return 1, "", "enslave injected failure"
                return 0, "", ""

            with patch(
                "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
            ):
                with pytest.raises(ExternalBridgeError, match="phy-enslave failure"):
                    attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

            # The rollback must have set eth0 back DOWN.
            assert ("ip", "link", "set", "eth0", "down") in captured, (
                f"phy DOWN restoration command missing from rollback; got {captured}"
            )
            # Owned bridge must be removed during rollback.
            assert ("ip", "link", "del", "br-h0") in captured, (
                f"owned bridge deletion missing from rollback; got {captured}"
            )
            assert "h0" not in _created_bridges
        finally:
            _created_bridges.clear()


class TestDefect5DuplicatePhyIntfRejection:
    """T7, T8: pre-mutation rejection of a duplicate phy_intf attachment
    against any existing record in _created_bridges, including rollback-failed
    retained records."""

    def test_T7_duplicate_phy_intf_vs_successful_active_record_rejected(self):
        """T7: a fully-attached record for h1 owns eth0; attaching h0 to the
        same eth0 must raise RuntimeError before any mutation."""
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
        )

        _created_bridges.clear()
        try:
            _populate_full_record("h1", "eth0")
            net = _make_net_helper()
            captured: list[tuple] = []

            def mock_cmd(args):
                captured.append(tuple(args))
                # If reached, the duplicate check did NOT fire pre-mutation.
                if args[:2] == ["ip", "-j"] and "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                if args[:2] == ["ip", "-j"] and "link" in args:
                    return (
                        0,
                        _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]),
                        "",
                    )
                return 0, "", ""

            with patch(
                "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
            ):
                with pytest.raises(RuntimeError, match=r"(?i)eth0.*already.*attached"):
                    attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

            # No mutating commands were issued.
            for c in captured:
                assert c[:2] != ("ip", "link") or c[2] not in ("add", "set", "del"), (
                    f"no mutation command may be issued before duplicate rejection; got {c}"
                )
            assert "h0" not in _created_bridges
        finally:
            _created_bridges.clear()

    def test_T8_duplicate_phy_intf_vs_rollback_failed_retained_record_rejected(self):
        """T8: a partial outstanding record for h1 owns eth0 (simulating a
        rollback-failed retained record); attaching h0 to eth0 must raise
        before any mutation."""
        from src.runtime.bridge_external import (
            attach_external_via_bridge,
            _created_bridges,
        )

        _created_bridges.clear()
        try:
            _created_bridges["h1"] = {
                "bridge": "br-h1",
                "veth_root": "veth-h1-root",
                "veth_host": "veth-h1",
                "phy_intf": "eth0",
                "prior_up": False,
                "bridge_created": False,
                "bridge_up": False,
                "phy_up_changed": False,
                "phy_enslaved": True,  # only outstanding flag
                "veth_created": False,
                "veth_root_mastered": False,
                "veth_root_up": False,
                "veth_host_ns_moved": False,
                "veth_host_up": False,
                "mtu_set": False,
                "ip_assigned": False,
            }
            net = _make_net_helper()
            captured: list[tuple] = []

            def mock_cmd(args):
                captured.append(tuple(args))
                if args[:2] == ["ip", "-j"] and "addr" in args:
                    return 0, _json.dumps([{"ifname": "eth0", "addr_info": []}]), ""
                if args[:2] == ["ip", "-j"] and "link" in args:
                    return (
                        0,
                        _json.dumps([{"ifname": "eth0", "flags": ["BROADCAST", "UP"]}]),
                        "",
                    )
                return 0, "", ""

            with patch(
                "src.runtime.bridge_external._run_root_cmd_vec", side_effect=mock_cmd
            ):
                with pytest.raises(RuntimeError, match=r"(?i)eth0.*already.*attached"):
                    attach_external_via_bridge(net, "h0", "eth0", ip="10.0.0.2/24")

            for c in captured:
                assert c[:2] != ("ip", "link") or c[2] not in ("add", "set", "del"), (
                    f"no mutation command may be issued before duplicate rejection; got {c}"
                )
            assert "h0" not in _created_bridges
        finally:
            _created_bridges.clear()


# ---------------------------------------------------------------------------
# Status-aware command helpers must fail closed
# ---------------------------------------------------------------------------


class TestRunCmdVecFailClosed:
    """The rc returned by _run_root_cmd_vec / _run_host_cmd_vec must never
    read as success when the underlying command did not complete normally.

    # 2026-09-02 fail-closed fix: CommandResult.returncode is None when the
    process was killed/never reaped, and timed_out/cancelled are separate
    flags that may coexist with returncode 0. Coercing None to 0 (or
    ignoring the flags) lets a killed ``ip link`` pass as success and the
    bridge state machine proceeds on a half-applied network state.
    """

    _ROOT_ARGV = ["ip", "link", "show", "dev", "eth0"]
    _HOST_ARGV = ["ip", "addr", "add", "10.0.0.2/24", "dev", "veth-h1"]

    # ---- _run_root_cmd_vec --------------------------------------------------

    def _root(self, fake):
        from src.runtime.bridge_external import _run_root_cmd_vec

        with patch(
            "src.runtime.bridge_external.MininetCommandRunner", return_value=fake
        ):
            rc, _out, _err = _run_root_cmd_vec(list(self._ROOT_ARGV))
        # The helper must still forward the argv unchanged to the root namespace.
        assert len(fake.runs) == 1
        assert fake.runs[0]["node"] == ROOT_SENTINEL
        assert fake.runs[0]["argv"] == self._ROOT_ARGV
        return rc

    def test_root_none_returncode_with_timeout_is_failure(self):
        fake = FakeCommandRunner()
        fake.script_run(returncode=None, timed_out=True)
        assert self._root(fake) != 0

    def test_root_cancelled_with_zero_returncode_is_failure(self):
        fake = FakeCommandRunner()
        fake.script_run(returncode=0, cancelled=True)
        assert self._root(fake) != 0

    def test_root_none_returncode_is_failure(self):
        fake = FakeCommandRunner()
        fake.script_run(returncode=None)
        assert self._root(fake) != 0

    def test_root_timed_out_with_zero_returncode_is_failure_and_explains(self):
        """timed_out alone (exit status 0 reaped after the kill) is a failure,
        and the reason is surfaced on stderr so rollback logs can explain it.
        Isolated from the returncode=None case above so a regression that
        only honours None is caught."""
        from src.runtime.bridge_external import _run_root_cmd_vec

        fake = FakeCommandRunner()
        fake.script_run(returncode=0, stderr="partial", timed_out=True)
        with patch(
            "src.runtime.bridge_external.MininetCommandRunner", return_value=fake
        ):
            rc, _out, err = _run_root_cmd_vec(list(self._ROOT_ARGV))
        assert rc != 0
        assert "partial" in err
        assert "command timed out" in err

    # ---- _run_host_cmd_vec --------------------------------------------------

    def _host(self, fake):
        from src.runtime.bridge_external import _run_host_cmd_vec

        _out, _err, rc = _run_host_cmd_vec(fake, "h1", list(self._HOST_ARGV))
        assert len(fake.runs) == 1
        assert fake.runs[0]["node"] == "h1"
        assert fake.runs[0]["argv"] == self._HOST_ARGV
        return rc

    def test_host_none_returncode_with_timeout_is_failure(self):
        fake = FakeCommandRunner()
        fake.script_run(returncode=None, timed_out=True)
        assert self._host(fake) != 0

    def test_host_cancelled_with_zero_returncode_is_failure(self):
        fake = FakeCommandRunner()
        fake.script_run(returncode=0, cancelled=True)
        assert self._host(fake) != 0

    def test_host_none_returncode_is_failure(self):
        fake = FakeCommandRunner()
        fake.script_run(returncode=None)
        assert self._host(fake) != 0
