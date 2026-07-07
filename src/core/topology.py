"""TopologyModel: the single owner of the mesh_links schema.

Consumers query this model (find_link, links_for_host, edges, ...) instead
of branching on the link dict shape. This module is pure (no Mininet).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Link:
    """One switch-mediated link: every host in ``hosts`` shares the switch.

    ``switch`` may be ``None`` for addressing-only fixtures that carry no
    switch information.
    """

    switch: str | None
    subnet: int | None
    hosts: list[int] = field(default_factory=list)
    host_eth: dict[int, int] = field(default_factory=dict)

    def connects(self, host_a: int, host_b: int) -> bool:
        return host_a in self.hosts and host_b in self.hosts

    def eth_of(self, host: int) -> int:
        """The host's interface index on this link (``h{host}-eth<idx>``)."""
        return self.host_eth[host]


class TopologyModel:
    """Query interface over MeshTopo.mesh_links."""

    def __init__(self, mesh_links):
        self._links = [self._normalize(raw) for raw in mesh_links]

    @staticmethod
    def _normalize(raw: dict) -> Link:
        """Absorb both link dict shapes: multi-host (canonical, what MeshTopo
        emits) and legacy point-to-point (host_a/host_b)."""
        if "hosts" in raw:
            hosts = sorted(raw["hosts"])
            host_eth = dict(raw.get("host_eth", {}))
        else:
            hosts = sorted((raw["host_a"], raw["host_b"]))
            host_eth = {}
            if "host_a_eth" in raw:
                host_eth[raw["host_a"]] = raw["host_a_eth"]
            if "host_b_eth" in raw:
                host_eth[raw["host_b"]] = raw["host_b_eth"]
        return Link(
            switch=raw.get("switch"),
            subnet=raw.get("subnet"),
            hosts=hosts,
            host_eth=host_eth,
        )

    def edges(self) -> list[tuple[int, int, Link]]:
        """Every connected host pair as ``(a, b, link)`` with ``a < b``.

        Multi-host links expand to all pairs sharing the switch; pairs are
        yielded in mesh_links order. A pair connected by several links
        appears once per link (callers keep today's last-wins semantics).
        """
        result = []
        for link in self._links:
            hosts = link.hosts
            for idx, host_a in enumerate(hosts):
                for host_b in hosts[idx + 1:]:
                    result.append((host_a, host_b, link))
        return result

    def subnet_of_switch(self, switch: str) -> int | None:
        """The subnet of the link a switch mediates, or ``None`` if unknown."""
        for link in self._links:
            if link.switch == switch:
                return link.subnet
        return None

    def links_for_host(self, host: int) -> list[Link]:
        """Every link the host is attached to, in mesh_links order."""
        return [link for link in self._links if host in link.hosts]

    def find_link(self, host_a: int, host_b: int) -> Link | None:
        """The first link whose switch both hosts share, or ``None``."""
        for link in self._links:
            if link.connects(host_a, host_b):
                return link
        return None

    def peer_of(self, host: int) -> int:
        """Some host sharing a link with ``host`` (first in mesh_links order).

        Raises ``RuntimeError`` if the host has no links — the contract the
        publish-link picker has always had.
        """
        for link in self.links_for_host(host):
            for other in link.hosts:
                if other != host:
                    return other
        raise RuntimeError(f"publisher h{host} has no links")

    @property
    def links(self) -> list[Link]:
        """All links, normalized, in mesh_links order."""
        return list(self._links)

    @property
    def host_count(self) -> int:
        """Highest attached host index + 1 (0 for an empty topology)."""
        highest = -1
        for link in self._links:
            highest = max(highest, *link.hosts)
        return highest + 1
