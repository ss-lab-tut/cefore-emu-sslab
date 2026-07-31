"""External-NIC attach state machine (Linux bridge onto a Mininet host).

Owns attach_external_via_bridge() / cleanup_external_bridges() and their
transactional rollback machinery. Root-namespace bridging (BridgeManager,
setup_bridges) lives in bridge_root.py; argument parsing in bridge_args.py.
"""

from dataclasses import dataclass
from typing import Callable

from mininet.log import info
from mininet.net import Mininet

from .bridge_args import validate_static_ip
from .command_runner import ROOT_SENTINEL, MininetCommandRunner


# ---------------------------------------------------------------------------
# Linux bridge functions (attach physical NIC to Mininet host)
# ---------------------------------------------------------------------------

# Track created Linux bridges for cleanup (ownership-aware)
_created_bridges: dict[str, dict] = {}


class ExternalBridgeError(RuntimeError):
    """External bridge setup or cleanup failure with structured details.

    Attributes:
        setup_failure: Original setup failure message (if any).
        rollback_failures: List of (action, error) from rollback attempts.
    """

    def __init__(
        self,
        setup_failure: str | None = None,
        rollback_failures: list[tuple[str, str]] | None = None,
    ):
        self.setup_failure = setup_failure
        self.rollback_failures = rollback_failures or []
        msgs = [setup_failure] if setup_failure else []
        msgs.extend(f"rollback {a}: {e}" for a, e in self.rollback_failures)
        super().__init__("; ".join(msgs))


# ---------------------------------------------------------------------------
# Status-aware root command execution
# ---------------------------------------------------------------------------


def _run_root_cmd_vec(args: list[str]) -> tuple[int, str, str]:
    """Execute a command in the root namespace through the CommandRunner seam.

    Args:
        args: Command and arguments as a list (no shell).

    Returns:
        Tuple of (returncode, stdout, stderr).
    """
    result = MininetCommandRunner(None).run(
        ROOT_SENTINEL, list(args), capture_stderr=True
    )
    rc = result.returncode if result.returncode is not None else 0
    return rc, result.stdout, result.stderr


def _run_host_cmd_vec(runner, host_name: str, argv: list[str]) -> tuple[str, str, int]:
    """Execute a command inside a Mininet host namespace via the runner.

    Args:
        runner: CommandRunner used to execute the command.
        host_name: Target host node name (e.g. "h3").
        argv: Command and arguments as a list (no shell).

    Returns:
        Tuple of (stdout, stderr, returncode).
    """
    result = runner.run(host_name, argv, capture_stderr=True)
    rc = result.returncode if result.returncode is not None else 0
    return result.stdout, result.stderr, rc


# ---------------------------------------------------------------------------
# Physical interface inspection helpers
# ---------------------------------------------------------------------------


def _inspect_link(phy_intf: str) -> tuple[bool, dict | None, str]:
    """Inspect a physical interface via ip -j link show."""
    rc, out, err = _run_root_cmd_vec(["ip", "-j", "link", "show", "dev", phy_intf])
    if rc != 0:
        return False, None, f"ip link show {phy_intf} failed (rc={rc}): {err.strip()}"
    try:
        import json as _json

        data = _json.loads(out)
        if not isinstance(data, list) or not data:
            return False, None, f"ip link show {phy_intf} returned empty result"
        entry = data[0]
        if not isinstance(entry, dict):
            # 2026-08-01 review fix: `[null]` やスカラ要素の JSON を success で
            # 通すと、下流が dict を仮定したまま処理して型嘘になる。構造の検証は
            # この境界が唯一の責任者。
            return False, None, (
                f"ip link show {phy_intf} returned non-object entry: {entry!r}"
            )
        return True, entry, ""
    except (_json.JSONDecodeError, ValueError) as exc:
        return False, None, f"ip link show {phy_intf} parse error: {exc}"


def _inspect_addresses(phy_intf: str) -> tuple[bool, list[dict] | None, str]:
    """Inspect addresses on a physical interface via ip -j addr show."""
    rc, out, err = _run_root_cmd_vec(["ip", "-j", "addr", "show", "dev", phy_intf])
    if rc != 0:
        return False, None, f"ip addr show {phy_intf} failed (rc={rc}): {err.strip()}"
    try:
        import json as _json

        data = _json.loads(out)
        if not isinstance(data, list) or not data:
            return True, [], ""
        return True, data[0].get("addr_info", []), ""
    except (_json.JSONDecodeError, ValueError) as exc:
        return False, None, f"ip addr show {phy_intf} parse error: {exc}"


# ---------------------------------------------------------------------------
# External bridge attachment with transactional safety
# ---------------------------------------------------------------------------


def _get_admin_up(link_data: dict) -> bool | None:
    """Determine administrative UP/DOWN state from interface flags."""
    flags = link_data.get("flags")
    if flags is None:
        return None
    if not isinstance(flags, list):
        return None
    return "UP" in flags


def attach_external_via_bridge(
    net: Mininet,
    host_name: str,
    phy_intf: str,
    ip: str | None = None,
    mtu: int | None = None,
) -> None:
    """Attach host to external network via Linux bridge.

    Transactional: if any mutation fails, previously-completed mutations
    are rolled back in reverse order. DHCP is not supported; a static
    IP is required in CIDR form.
    """
    if not ip:
        raise RuntimeError(
            f"static IP required for external bridge attachment of {host_name}; "
            "DHCP mode is not supported"
        )

    validate_static_ip(ip)

    bridge_name = f"br-{host_name}"
    veth_root = f"veth-{host_name}-root"
    veth_host = f"veth-{host_name}"

    if len(bridge_name) > 15 or len(veth_root) > 15 or len(veth_host) > 15:
        raise RuntimeError(
            f"generated interface names exceed 15-character limit: "
            f"bridge={bridge_name!r}({len(bridge_name)}), "
            f"veth_root={veth_root!r}({len(veth_root)}), "
            f"veth_host={veth_host!r}({len(veth_host)})"
        )

    if host_name in _created_bridges:
        raise RuntimeError(
            f"active attachment already exists for {host_name}; "
            f"run cleanup_external_bridges() first"
        )

    # Reject pre-mutation if any existing record (including rollback-failed
    # retained records) already owns the requested physical interface.
    for existing_host, existing_record in _created_bridges.items():
        if existing_record.get("phy_intf") == phy_intf and existing_host != host_name:
            raise RuntimeError(
                f"physical interface {phy_intf} is already attached via active "
                f"external bridge for host {existing_host}; "
                f"run cleanup_external_bridges() first"
            )

    host = net.get(host_name)
    if host is None:
        info(f"[bridge] host {host_name} not found\n")
        return
    host_runner = MininetCommandRunner(net)

    success, link_data, err = _inspect_link(phy_intf)
    if not success or link_data is None:
        # link_data is None は success=False と同値 (_inspect_link の契約)。
        # mypy が tuple 相関を追えないため、挙動を変えずに narrowing する形で
        # 条件に含める (2026-08-01 review fix: 旧 cast(dict, ...) を置換)。
        raise RuntimeError(f"cannot inspect {phy_intf}: {err}")

    master = link_data.get("master") or link_data.get("bridge")
    if master:
        raise RuntimeError(
            f"{phy_intf} already enslaved to {master}; cannot reassign to new bridge"
        )

    addr_success, addrs, addr_err = _inspect_addresses(phy_intf)
    if not addr_success:
        raise RuntimeError(f"cannot inspect addresses on {phy_intf}: {addr_err}")
    for addr_info in addrs or []:
        addr = addr_info.get("local", "")
        if addr and not addr.startswith("169.254."):
            raise RuntimeError(
                f"{phy_intf} has configured address {addr}; "
                f"refusing to mutate non-clean interface"
            )

    prior_up = _get_admin_up(link_data)
    if prior_up is None:
        raise RuntimeError(
            f"cannot determine administrative state of {phy_intf}; "
            f"flags field missing or invalid"
        )

    record: dict = {
        "bridge": bridge_name,
        "veth_root": veth_root,
        "veth_host": veth_host,
        "phy_intf": phy_intf,
        "prior_up": prior_up,
        "bridge_created": False,
        "bridge_up": False,
        "phy_up_changed": False,
        "phy_enslaved": False,
        "veth_created": False,
        "veth_root_mastered": False,
        "veth_root_up": False,
        "veth_host_ns_moved": False,
        "veth_host_up": False,
        "mtu_set": False,
        "ip_assigned": False,
    }
    _created_bridges[host_name] = record

    rollback_actions: list[_RollbackAction] = []

    def _commit_record() -> None:
        record["rollback_actions"] = list(rollback_actions)

    def _abort(reason: str) -> "list[tuple[str, str]]":
        """Run rollback for `reason` and pop the record iff fully discharged."""
        rb_failures = _rollback(rollback_actions, record, reason)
        if not _record_has_outstanding_state(record):
            _created_bridges.pop(host_name, None)
        return rb_failures

    info(f"[bridge] creating bridge {bridge_name} for {host_name} via {phy_intf}\n")

    rc, _, err = _run_root_cmd_vec(["ip", "link", "add", bridge_name, "type", "bridge"])
    if rc != 0:
        _created_bridges.pop(host_name, None)
        raise RuntimeError(f"bridge creation failed (rc={rc}): {err.strip()}")
    record["bridge_created"] = True
    rollback_actions.append(
        _RollbackAction(
            "delete bridge",
            lambda: _rollback_del_link(bridge_name),
            ("bridge_created", "bridge_up"),
        )
    )

    rc, _, err = _run_root_cmd_vec(["ip", "link", "set", bridge_name, "up"])
    if rc != 0:
        rb_failures = _abort("bridge-up failure")
        raise ExternalBridgeError("bridge-up failure", rb_failures)
    record["bridge_up"] = True

    if not prior_up:
        rc, _, err = _run_root_cmd_vec(["ip", "link", "set", phy_intf, "up"])
        if rc != 0:
            rb_failures = _abort("phy-up failure")
            raise ExternalBridgeError("phy-up failure", rb_failures)
        record["phy_up_changed"] = True
        # Register restore-DOWN immediately after phy-up succeeds, BEFORE the
        # enslave attempt, so an enslave failure still triggers DOWN
        # restoration via rollback. (Defect 2.)
        rollback_actions.append(
            _RollbackAction(
                "restore phy DOWN",
                lambda: _rollback_set_link(phy_intf, "down"),
                ("phy_up_changed",),
            )
        )

    rc, _, err = _run_root_cmd_vec(
        ["ip", "link", "set", phy_intf, "master", bridge_name]
    )
    if rc != 0:
        rb_failures = _abort("phy-enslave failure")
        raise ExternalBridgeError("phy-enslave failure", rb_failures)
    record["phy_enslaved"] = True
    rollback_actions.append(
        _RollbackAction(
            "unmaster phy",
            lambda: _rollback_unmaster(phy_intf),
            ("phy_enslaved",),
        )
    )

    rc, _, err = _run_root_cmd_vec(
        ["ip", "link", "add", veth_root, "type", "veth", "peer", "name", veth_host]
    )
    if rc != 0:
        rb_failures = _abort("veth creation failure")
        raise ExternalBridgeError("veth creation failure", rb_failures)
    record["veth_created"] = True
    rollback_actions.append(
        _RollbackAction(
            "delete veth",
            lambda: _rollback_del_link(veth_root),
            (
                "veth_created",
                "veth_root_mastered",
                "veth_root_up",
                "veth_host_ns_moved",
                "veth_host_up",
                "mtu_set",
                "ip_assigned",
            ),
        )
    )

    rc, _, err = _run_root_cmd_vec(
        ["ip", "link", "set", veth_root, "master", bridge_name]
    )
    if rc != 0:
        rb_failures = _abort("veth-root-master failure")
        raise ExternalBridgeError("veth-root-master failure", rb_failures)
    record["veth_root_mastered"] = True

    rc, _, err = _run_root_cmd_vec(["ip", "link", "set", veth_root, "up"])
    if rc != 0:
        rb_failures = _abort("veth-root-up failure")
        raise ExternalBridgeError("veth-root-up failure", rb_failures)
    record["veth_root_up"] = True

    rc, _, err = _run_root_cmd_vec(["ip", "link", "set", veth_host, "up"])
    if rc != 0:
        rb_failures = _abort("veth-host-up failure")
        raise ExternalBridgeError("veth-host-up failure", rb_failures)

    host_pid = host.pid
    rc, _, err = _run_root_cmd_vec(
        ["ip", "link", "set", veth_host, "netns", str(host_pid)]
    )
    if rc != 0:
        rb_failures = _abort("veth-host-ns-move failure")
        raise ExternalBridgeError("veth-host-ns-move failure", rb_failures)
    record["veth_host_ns_moved"] = True

    out, err, rc = _run_host_cmd_vec(
        host_runner, host_name, ["ip", "link", "set", veth_host, "up"]
    )
    if rc != 0:
        record["veth_host_up_failed"] = True
        rb_failures = _abort("veth-host-up-in-ns failure")
        raise ExternalBridgeError("veth-host-up-in-ns failure", rb_failures)
    record["veth_host_up"] = True

    if mtu:
        rc, _, err = _run_root_cmd_vec(
            ["ip", "link", "set", bridge_name, "mtu", str(mtu)]
        )
        if rc != 0:
            rb_failures = _abort("bridge-mtu failure")
            raise ExternalBridgeError("bridge-mtu failure", rb_failures)
        rc, _, err = _run_root_cmd_vec(
            ["ip", "link", "set", veth_root, "mtu", str(mtu)]
        )
        if rc != 0:
            rb_failures = _abort("veth-root-mtu failure")
            raise ExternalBridgeError("veth-root-mtu failure", rb_failures)
        out, err, rc = _run_host_cmd_vec(
            host_runner, host_name, ["ip", "link", "set", veth_host, "mtu", str(mtu)]
        )
        if rc != 0:
            rb_failures = _abort("veth-host-mtu failure")
            raise ExternalBridgeError("veth-host-mtu failure", rb_failures)
        record["mtu_set"] = True

    out, err, rc = _run_host_cmd_vec(
        host_runner, host_name, ["ip", "addr", "add", ip, "dev", veth_host]
    )
    if rc != 0:
        rb_failures = _abort("static-ip failure")
        raise ExternalBridgeError("static-ip failure", rb_failures)
    record["ip_assigned"] = True
    info(f"[bridge] {host_name}: static IP {ip} on {veth_host}\n")

    _commit_record()
    info(f"[bridge] attached {host_name} to {phy_intf} via bridge {bridge_name}\n")


def cleanup_external_bridges() -> None:
    """Clean up all created Linux bridges and veth pairs.

    Cleanup invariant: attempts every cleanup step whose outstanding flag is
    still True. Each successful step clears only the flag(s) for the state
    it actually removes. A failed step records a failure but does NOT
    prevent later independent cleanup steps from being attempted. The host
    record is retained iff `_record_has_outstanding_state(record)` is True.

    Raises ``ExternalBridgeError`` if any cleanup step failed.
    """
    failures: list[tuple[str, str]] = []

    for host_name, record in list(_created_bridges.items()):
        host_name = str(host_name)
        bridge_name = record.get("bridge", f"br-{host_name}")
        veth_root = record.get("veth_root", f"veth-{host_name}-root")
        phy_intf = record.get("phy_intf", "")

        info(f"[bridge] cleaning up {bridge_name}\n")

        # veth deletion cascades — clears all veth-pair-dependent flags
        if record.get("veth_created"):
            rc, _, err = _run_root_cmd_vec(["ip", "link", "del", veth_root])
            if rc != 0:
                failures.append((f"del {veth_root}", err.strip()))
            else:
                for flag in (
                    "veth_created",
                    "veth_root_mastered",
                    "veth_root_up",
                    "veth_host_ns_moved",
                    "veth_host_up",
                    "mtu_set",
                    "ip_assigned",
                ):
                    record[flag] = False

        # unmaster — clears only phy_enslaved
        if record.get("phy_enslaved"):
            rc, _, err = _run_root_cmd_vec(["ip", "link", "set", phy_intf, "nomaster"])
            if rc != 0:
                failures.append((f"unmaster {phy_intf}", err.strip()))
            else:
                record["phy_enslaved"] = False

        # phy down — clears only phy_up_changed
        if record.get("phy_up_changed"):
            rc, _, err = _run_root_cmd_vec(["ip", "link", "set", phy_intf, "down"])
            if rc != 0:
                failures.append((f"down {phy_intf}", err.strip()))
            else:
                record["phy_up_changed"] = False

        # bridge down — independent gate, clears only bridge_up
        if record.get("bridge_up"):
            rc, _, err = _run_root_cmd_vec(["ip", "link", "set", bridge_name, "down"])
            if rc != 0:
                failures.append((f"down {bridge_name}", err.strip()))
            else:
                record["bridge_up"] = False

        # bridge del — clears bridge_created (and bridge_up defensively)
        if record.get("bridge_created"):
            rc, _, err = _run_root_cmd_vec(["ip", "link", "del", bridge_name])
            if rc != 0:
                failures.append((f"del {bridge_name}", err.strip()))
            else:
                record["bridge_created"] = False
                record["bridge_up"] = False  # del implies down

        if not _record_has_outstanding_state(record):
            _created_bridges.pop(host_name, None)

    if failures:
        raise ExternalBridgeError(rollback_failures=failures)


def attach_external_interface(net, host_name, intf_name, ip=None, mtu=None):
    """Attach external interface to a host via bridge (backward compatible)."""
    attach_external_via_bridge(net, host_name, intf_name, ip, mtu)


# ---------------------------------------------------------------------------
# Rollback helpers
# ---------------------------------------------------------------------------


def _rollback_del_link(name: str) -> None:
    """Delete a network link."""
    rc, _, err = _run_root_cmd_vec(["ip", "link", "del", name])
    if rc != 0:
        raise RuntimeError(f"rollback del {name} failed (rc={rc}): {err.strip()}")


def _rollback_unmaster(phy_intf: str) -> None:
    """Remove physical interface from bridge master."""
    rc, _, err = _run_root_cmd_vec(["ip", "link", "set", phy_intf, "nomaster"])
    if rc != 0:
        raise RuntimeError(
            f"rollback unmaster {phy_intf} failed (rc={rc}): {err.strip()}"
        )


def _rollback_set_link(name: str, state: str) -> None:
    """Set link administrative state."""
    rc, _, err = _run_root_cmd_vec(["ip", "link", "set", name, state])
    if rc != 0:
        raise RuntimeError(
            f"rollback set {name} {state} failed (rc={rc}): {err.strip()}"
        )


# Outstanding-state flags for _created_bridges records. The record is retained
# while any of these is True; cleared as their corresponding cleanup or
# rollback action succeeds (cleanup invariant / setup rollback invariant —
# see docs in the remediation plan).
_OUTSTANDING_FLAGS = (
    "bridge_created",
    "bridge_up",
    "phy_up_changed",
    "phy_enslaved",
    "veth_created",
    "veth_root_mastered",
    "veth_root_up",
    "veth_host_ns_moved",
    "veth_host_up",
    "mtu_set",
    "ip_assigned",
)


def _record_has_outstanding_state(record: dict) -> bool:
    """True iff at least one outstanding cleanup obligation remains."""
    return any(record.get(flag) for flag in _OUTSTANDING_FLAGS)


@dataclass(frozen=True)
class _RollbackAction:
    """A single setup-rollback action paired with the outstanding flags it
    clears when its undo command runs successfully.

    `run` MUST go through a status-aware command helper (e.g.,
    `_rollback_del_link`, `_rollback_unmaster`, `_rollback_set_link`) so that
    a non-zero undo rc raises `RuntimeError` carrying the failed command and
    rc/stderr detail. `_rollback()` clears `clear_flags` on the record only
    when `run` completes without raising; a non-zero undo rc therefore leaves
    the corresponding outstanding-state flag(s) set, and the record is
    retained for retry via `_record_has_outstanding_state(record)`.
    """

    description: str
    run: Callable[[], None]
    clear_flags: tuple[str, ...]


def _rollback(
    actions: list[_RollbackAction],
    record: dict,
    reason: str,
) -> list[tuple[str, str]]:
    """Execute rollback actions in reverse order, clearing outstanding-state
    flags only for actions whose `run()` completed without raising.

    Returns list of (description, error) for any rollback failures so the
    caller can include them in `ExternalBridgeError(rollback_failures=...)`.
    """
    rollback_failures: list[tuple[str, str]] = []
    for action in reversed(actions):
        try:
            action.run()
        except Exception as exc:
            rollback_failures.append((action.description, str(exc)))
            continue
        for flag in action.clear_flags:
            record[flag] = False
    if rollback_failures:
        info(f"[bridge] rollback for {reason} had failures: {rollback_failures}\n")
    return rollback_failures
