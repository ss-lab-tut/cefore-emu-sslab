"""Runtime abstraction for Mininet operations."""

from abc import ABC, abstractmethod


class Runtime(ABC):
    """Abstract interface for network runtime operations.

    Enables testability by decoupling scenario logic from Mininet.
    """

    @abstractmethod
    def link_down(self, node_a: str, node_b: str) -> None:
        """Bring down link between two nodes."""

    @abstractmethod
    def link_up(self, node_a: str, node_b: str) -> None:
        """Bring up link between two nodes."""

    @abstractmethod
    def run_cmd(self, node: str, cmd: str) -> str:
        """Run command on a node and return output."""

    @abstractmethod
    def config_link_status(self, node_a: str, node_b: str, status: str) -> None:
        """Configure link status between two nodes."""

    @abstractmethod
    def get_host(self, name: str):
        """Get host object by name."""

    @abstractmethod
    def get_links(self):
        """Get all network links."""


class MininetRuntime(Runtime):
    """Runtime implementation using real Mininet network."""

    def __init__(self, net):
        self._net = net

    @property
    def net(self):
        return self._net

    def link_down(self, node_a, node_b):
        self._net.configLinkStatus(node_a, node_b, "down")

    def link_up(self, node_a, node_b):
        self._net.configLinkStatus(node_a, node_b, "up")

    def run_cmd(self, node, cmd):
        host = self._net.get(node)
        return host.cmd(cmd)

    def config_link_status(self, node_a, node_b, status):
        self._net.configLinkStatus(node_a, node_b, status)

    def get_host(self, name):
        return self._net.get(name)

    def get_links(self):
        return self._net.links


class FakeRuntime(Runtime):
    """Test stub for Runtime. Records all operations."""

    def __init__(self):
        self.events = []
        self.commands = []

    def link_down(self, node_a, node_b):
        self.events.append(("link_down", node_a, node_b))

    def link_up(self, node_a, node_b):
        self.events.append(("link_up", node_a, node_b))

    def run_cmd(self, node, cmd):
        self.commands.append((node, cmd))
        return ""

    def config_link_status(self, node_a, node_b, status):
        self.events.append(("config_link_status", node_a, node_b, status))

    def get_host(self, name):
        return None

    def get_links(self):
        return []
