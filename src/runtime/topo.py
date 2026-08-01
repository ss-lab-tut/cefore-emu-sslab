"""Mininet Topo subclasses for Cefore topologies."""

import random

from mininet.log import info
from mininet.topo import Topo
from mininet.util import irange



def max_possible_links(host_num):
    """Maximum possible links (complete graph) for given number of hosts."""
    return host_num * (host_num - 1) // 2


def min_required_links(host_num):
    """Minimum links needed to connect all hosts (spanning tree)."""
    return host_num - 1


class SimpleLinkTopo(Topo):
    """Simple 3-node linear topology: h0-s0-h1-s1-h2."""

    def build(self, n=3, **_kwargs):
        hosts = [self.addHost(f"h{h}") for h in irange(0, n - 1)]
        s0 = self.addSwitch("s0")
        s1 = self.addSwitch("s1")
        self.addLink(s0, hosts[0])
        self.addLink(s0, hosts[1])
        self.addLink(s1, hosts[1])
        self.addLink(s1, hosts[2])


class LineTopo(Topo):
    """Linear topology: h0-s0-h1-s1-...-sN-hN."""

    def build(self, hosts, **_kwargs):
        switches = hosts - 1
        host_nodes = [self.addHost(f"h{idx}") for idx in range(hosts)]
        switch_nodes = [self.addSwitch(f"s{idx}") for idx in range(switches)]
        for idx in range(switches):
            self.addLink(switch_nodes[idx], host_nodes[idx])
            self.addLink(switch_nodes[idx], host_nodes[idx + 1])


def min_required_switches(host_num, switch_capacity):
    """Minimum switches needed to connect all hosts (spanning tree assumption)."""
    if switch_capacity < 2:
        raise ValueError("switch_capacity must be at least 2")
    return max(1, (host_num + switch_capacity - 1) // switch_capacity)


class MeshTopo(Topo):
    """Mesh topology with random host-to-host connections via switches."""

    def build(
        self,
        hosts,
        swhich_num=0,
        rng=None,
        node_per_switch=2,
        host_degree_min=1,
        host_degree_max=2,
        switch_use_all=False,
        **_kwargs,
    ):
        if rng is None:
            rng = random.Random()
        if host_degree_min < 1 or host_degree_max < host_degree_min:
            raise ValueError("host_degree_min/max must satisfy 1 <= min <= max")
        if node_per_switch == 1:
            raise ValueError("switch capacity must be >=2 to connect hosts")
        switch_capacity = node_per_switch if node_per_switch > 0 else hosts

        host_nodes = [self.addHost(f"h{idx}") for idx in range(hosts)]

        self.mesh_links = []
        host_ports = [0] * hosts

        degrees = [rng.randint(host_degree_min, host_degree_max) for _ in range(hosts)]
        initial_total = sum(degrees)
        if any(d < 1 for d in degrees):
            raise ValueError("all hosts must have degree >=1")

        switch_hosts = {}
        switch_nodes = {}
        switch_count = 0

        def new_switch():
            nonlocal switch_count
            name = f"s{switch_count}"
            switch_count += 1
            switch_hosts[name] = set()
            switch_nodes[name] = self.addSwitch(name)
            return name

        host_order = list(range(hosts))
        rng.shuffle(host_order)
        host_order.sort(key=lambda h: degrees[h], reverse=True)
        connected = [host_order[0]]
        remaining = host_order[1:]

        for host in remaining:
            candidates = sorted(connected, key=lambda n: degrees[n], reverse=True)
            partner = None
            for cand in candidates:
                if degrees[cand] > 0 and degrees[host] > 0:
                    partner = cand
                    break
            if partner is None:
                needed = 2 * (hosts - 1)
                raise ValueError(
                    f"failed to build spanning tree: degree budget exhausted "
                    f"(initial_total={initial_total}, needed>={needed}). "
                    f"Increase --host-degree-min/--host-degree-max or reduce --hosts"
                )
            chosen_switch = None
            for sw, hs in switch_hosts.items():
                if len(hs) + 2 <= switch_capacity and partner in hs:
                    chosen_switch = sw
                    break
            if chosen_switch is None:
                chosen_switch = new_switch()
            switch_hosts[chosen_switch].update({host, partner})
            degrees[host] -= 1
            degrees[partner] -= 1
            connected.append(host)

        hosts_with_deg = [i for i, d in enumerate(degrees) if d > 0]
        while hosts_with_deg:
            sw = new_switch()
            cap_left = switch_capacity
            rng.shuffle(hosts_with_deg)
            to_remove = []
            for host in hosts_with_deg:
                if degrees[host] > 0 and cap_left > 0:
                    switch_hosts[sw].add(host)
                    degrees[host] -= 1
                    cap_left -= 1
                    if degrees[host] == 0:
                        to_remove.append(host)
                if cap_left == 0:
                    break
            hosts_with_deg = [h for h in hosts_with_deg if degrees[h] > 0]

        if swhich_num and switch_count > swhich_num:
            raise ValueError(
                f"switch count {switch_count} exceeds limit {swhich_num} "
                f"(increase switch capacity or host degree range)"
            )

        if switch_use_all and swhich_num:
            extra_switches = max(0, swhich_num - switch_count)
            if extra_switches > 0:
                import heapq

                info(
                    "switch_use_all enabled: distributing extra switches; host degrees may exceed host_degree_max\n"
                )

                current_deg = [0] * hosts
                for hs in switch_hosts.values():
                    for h in hs:
                        current_deg[h] += 1

                heap = [[deg, rng.random(), host_idx] for host_idx, deg in enumerate(current_deg)]
                heapq.heapify(heap)

                for _ in range(extra_switches):
                    if not heap:
                        info("warning: no hosts available to attach to extra switches\n")
                        break

                    sw = new_switch()
                    cap_left = min(switch_capacity, hosts)
                    used_hosts = set()
                    popped = []

                    while cap_left > 0 and heap:
                        deg, tie, host_idx = heapq.heappop(heap)
                        if host_idx in used_hosts:
                            popped.append([deg, tie, host_idx, False])
                            continue
                        used_hosts.add(host_idx)
                        popped.append([deg, tie, host_idx, True])
                        cap_left -= 1

                    for deg, tie, host_idx, used in popped:
                        if used:
                            deg += 1
                            current_deg[host_idx] += 1
                            switch_hosts[sw].add(host_idx)
                        heapq.heappush(heap, [deg, rng.random(), host_idx])

                if switch_count < swhich_num:
                    info(
                        "warning: could not reach requested switch count; capacity or host pool exhausted\n"
                    )

        for idx, (switch_name, hosts_set) in enumerate(switch_hosts.items()):
            hosts_for_switch = sorted(hosts_set)
            host_eth = {}
            for host_idx in hosts_for_switch:
                host_eth[host_idx] = host_ports[host_idx]
                host_ports[host_idx] += 1
                self.addLink(host_nodes[host_idx], switch_nodes[switch_name])
            self.mesh_links.append(
                {
                    "subnet": idx + 1,
                    "switch": switch_name,
                    "hosts": hosts_for_switch,
                    "host_eth": host_eth,
                }
            )
