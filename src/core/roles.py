"""Node role definitions for Cefore hosts."""

from dataclasses import dataclass
from random import Random


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
