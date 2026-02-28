"""Base scenario with SIGINT/exception teardown guarantee."""

from abc import ABC, abstractmethod

from mininet.cli import CLI
from mininet.log import info


class BaseScenario(ABC):
    """Abstract base for all Cefore emulation scenarios.

    Guarantees teardown runs even on SIGINT or exception.
    """

    @abstractmethod
    def build_topology(self):
        """Create and return a Mininet Topo instance."""

    @abstractmethod
    def configure(self, net):
        """Configure the network (IP, FIB, daemons)."""

    @abstractmethod
    def run_experiment(self, net):
        """Run the main experiment (put/get operations)."""

    @abstractmethod
    def teardown(self, net):
        """Clean up daemons, bridges, and temp directories."""

    def create_mininet(self, topo, **kwargs):
        """Create Mininet instance. Override for custom options (e.g., TCLink)."""
        from mininet.net import Mininet
        return Mininet(topo=topo, waitConnected=True, **kwargs)

    def execute(self):
        """Run the full scenario lifecycle with guaranteed teardown."""
        net = None
        try:
            topo = self.build_topology()
            net = self.create_mininet(topo)
            net.start()
            self.configure(net)
            self.run_experiment(net)
            CLI(net)
        except KeyboardInterrupt:
            info("\nInterrupted by user.\n")
        finally:
            if net is not None:
                try:
                    self.teardown(net)
                except Exception as exc:
                    info(f"Error during teardown: {exc}\n")
                net.stop()
