"""Stdlib-only leaf shared by the bridge modules.

This module owns CLI-shape parsing and strict static-IP validation for bridge
features, plus the one fail-closed reading of a finished command result
(``fail_closed_rc``) that both external attach and root-namespace bridge code
use. It intentionally depends only on stdlib modules so the two siblings can
share it without creating runtime cycles, pulling Mininet into pure argument
tests, or importing the CommandRunner seam. Import direction is one-way:
``bridge_args`` imports nobody from either sibling.
"""

import ipaddress as _ipaddress
from typing import Any


def validate_static_ip(ip_str: str) -> None:
    """Validate static IP string under the strict-CIDR contract.

    Requires address + prefix length in CIDR form (e.g., '10.0.0.2/24').
    Rejects bare addresses, empty strings, and malformed input.
    """
    if not ip_str or not isinstance(ip_str, str):
        raise RuntimeError(
            "static IP must be a non-empty CIDR string (e.g., '10.0.0.2/24')"
        )
    # Strict-CIDR policy: explicit prefix length is required. A bare IP
    # would be silently treated as /32 by ipaddress.ip_interface(); the
    # published `--ext host,ifname,ip[,mtu] (ip required in CIDR form)`
    # contract forbids that.
    if "/" not in ip_str:
        raise RuntimeError(
            f"static IP must be CIDR form, e.g. '10.0.0.2/24'; got '{ip_str}'"
        )
    try:
        _ipaddress.ip_interface(ip_str)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"invalid static IP '{ip_str}': {exc}")


def parse_ext_args(values):
    """Parse external interface arguments.

    Static IP is required in CIDR form. DHCP mode is not supported.

    Args:
        values: List of "host,ifname,ip[,mtu]" strings.

    Returns:
        List of (host_name, intf_name, ip, mtu) tuples.

    Raises:
        ValueError: If IP is missing or format is invalid.
    """
    entries = []
    for value in values or []:
        parts = [part.strip() for part in value.split(",")]
        if len(parts) not in (3, 4):
            raise ValueError(
                "ext format is host,ifname,ip[,mtu]; "
                "static IP is required in CIDR form (DHCP unsupported)"
            )
        host_name = parts[0]
        intf_name = parts[1]
        ip = parts[2]
        if not ip:
            raise ValueError(
                f"static IP required for {host_name},{intf_name}; "
                "DHCP mode is not supported"
            )
        mtu = int(parts[3]) if len(parts) == 4 and parts[3] else None
        entries.append((host_name, intf_name, ip, mtu))
    return entries


def fail_closed_rc(result: Any) -> tuple[int, str]:
    """Map a finished command result to ``(rc, detail)`` without ever letting
    an unfinished run read as success.

    ``result`` is read by attribute only (``timed_out``, ``cancelled``,
    ``returncode``, ``stderr``) and is loosely annotated on purpose: this leaf
    must stay stdlib-only, so it must not import ``CommandResult`` or anything
    from ``command_runner``. Any object exposing those four attributes works.

    Fail-closed ladder (same criteria as monitoring._collect_ccninfo and
    verdict.from_runtime_ccninfo: flags outrank the exit status):
    1. timed_out            -> rc=-1, stderr += "command timed out"
    2. cancelled            -> rc=-1, stderr += "command cancelled"
    3. returncode is None   -> rc=-1, stderr += "no exit status"
    4. otherwise            -> rc=returncode, stderr unchanged

    ``rc=-1`` is a bridge-local convention, deliberately not part of the
    CommandResult seam: ``CommandResult`` expresses deadlines through
    ``timed_out``/``cancelled`` and never through a sentinel ``returncode``.
    The sentinel exists only so callers can keep the uniform ``rc != 0``
    test that the ``(rc, detail)`` cleanup contract already uses.
    """
    # 2026-09-02 fail-closed fix: None was coerced to 0 and the timed_out /
    # cancelled flags were ignored, so a killed ``ip link`` passed as success
    # and the bridge state machine kept going on a half-applied network.
    # -1 is a nonzero sentinel; every caller only tests ``rc != 0``. The
    # appended reason lets the rollback log explain *why* the step failed.
    if result.timed_out:
        reason = "command timed out"
    elif result.cancelled:
        reason = "command cancelled"
    elif result.returncode is None:
        reason = "no exit status"
    else:
        return result.returncode, result.stderr
    stderr = result.stderr or ""
    if stderr and not stderr.endswith("\n"):
        stderr += "\n"
    return -1, stderr + reason


def parse_bridge_args(values: list[str] | None) -> list[dict[str, Any]]:
    """Parse --bridge CLI arguments.

    Format: switch,root_ip,local_routes[,external_routes,gateway]

    Args:
        values: List of bridge argument strings.

    Returns:
        List of bridge configuration dictionaries.
    """
    entries = []
    for value in values or []:
        parts = [part.strip() for part in value.split(",")]
        if len(parts) < 3:
            raise ValueError(
                "bridge format is switch,root_ip,local_routes[,external_routes,gateway]"
            )
        entry = {
            "switch": parts[0],
            "root_ip": parts[1],
            "local_routes": parts[2],
        }
        if len(parts) >= 5:
            entry["external_routes"] = parts[3]
            entry["gateway"] = parts[4]
        entries.append(entry)
    return entries
