"""Node role definitions for Cefore hosts."""

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class NodeRole:
    """Defines a Cefore node's role and configuration."""

    name: str
    template: str
    cs_mode: int
    runs_csmgrd: bool


CONSUMER = NodeRole("consumer", "h0", cs_mode=0, runs_csmgrd=False)
ROUTER = NodeRole("router", "h1", cs_mode=2, runs_csmgrd=True)
PUBLISHER = NodeRole("publisher", "h2", cs_mode=1, runs_csmgrd=False)

# Template mapping from name to role
_TEMPLATE_TO_ROLE = {"h0": CONSUMER, "h1": ROUTER, "h2": PUBLISHER}


def assign_roles(host_num, rng, publishers=None):
    """Assign roles to hosts based on experiment definition.

    Args:
        host_num: Total number of hosts.
        rng: Random number generator.
        publishers: Set of host IDs designated as publishers.

    Returns:
        Dict mapping host index to NodeRole.
    """
    roles = {}
    for idx in range(host_num):
        if publishers and idx in publishers:
            roles[idx] = PUBLISHER
        elif idx == 0:
            roles[idx] = CONSUMER
        elif host_num == 2 and idx == 1:
            # Minimal 2-host setup: no router needed, h1 is publisher
            roles[idx] = PUBLISHER
        elif idx == 1:
            roles[idx] = ROUTER
        elif idx == 2:
            roles[idx] = PUBLISHER
        elif idx % 2 == 1:
            roles[idx] = ROUTER
        elif idx == host_num - 1:
            roles[idx] = PUBLISHER
        else:
            roles[idx] = rng.choice([CONSUMER, PUBLISHER])
    return roles


def derive_seed(base_seed, namespace):
    """Derive a deterministic sub-seed from a root seed and namespace.

    Keeps RNG streams independent so adding a new randomization domain
    does not shift existing topology or failure sequences.
    """
    if base_seed is None:
        return None
    payload = f"ceforeemu:v1:{namespace}:{base_seed}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest, "big")


def assign_random_cs_modes(host_ids, publisher_ids, rng):
    """Assign random CS_MODE to each host.

    Put/pub nodes need at least local cache (mode 1 or 2) so published
    content remains available. Other nodes may also use mode 0.
    """
    publisher_ids = set(publisher_ids or ())
    cs_modes = {}
    for idx in sorted(host_ids):
        if idx in publisher_ids:
            cs_modes[idx] = rng.choice([1, 2])
        else:
            cs_modes[idx] = rng.choice([0, 1, 2])
    return cs_modes
