"""Pure bridge argument parsing and validation leaf helpers.

This module owns CLI-shape parsing and strict static-IP validation for bridge
features. It intentionally depends only on stdlib modules so external attach
and root-namespace bridge code can share it without creating runtime cycles or
pulling Mininet into pure argument tests.
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
