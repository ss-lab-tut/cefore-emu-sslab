"""Helpers for validating route protocols."""

DEFAULT_ROUTE_PROTOCOL = "udp"
VALID_ROUTE_PROTOCOLS = (DEFAULT_ROUTE_PROTOCOL,)


def normalize_route_protocol(protocol: str | None) -> str:
    """Return a normalized route protocol or raise for unsupported values."""
    if protocol is None:
        return DEFAULT_ROUTE_PROTOCOL
    if not isinstance(protocol, str):
        raise TypeError("protocol must be a string")

    normalized = protocol.strip().lower()
    if normalized not in VALID_ROUTE_PROTOCOLS:
        allowed = ", ".join(VALID_ROUTE_PROTOCOLS)
        raise ValueError(f"protocol must be one of: {allowed}")
    return normalized
