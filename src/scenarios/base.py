"""Base scenario with SIGINT/exception teardown guarantee."""

from abc import ABC, abstractmethod
from pathlib import Path

from mininet.cli import CLI
from mininet.log import info


class BaseScenario(ABC):
    """Abstract base for all Cefore emulation scenarios.

    Guarantees teardown runs even on SIGINT or exception.

    Subclasses should set:
        self.generated_node_dirs  -- list[Path] returned by ensure_node_dirs()
        self.debug_config         -- DebugConfig instance
        self.run_dir              -- Path for output artifacts
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
        """Stop daemons and bridges. Do NOT call cleanup_node_dirs here."""

    def create_mininet(self, topo, **kwargs):
        """Create Mininet instance. Override for custom options (e.g., TCLink)."""
        from mininet.net import Mininet
        return Mininet(topo=topo, waitConnected=True, **kwargs)

    def collect_debug_pre_teardown(self, net):
        """Collect debug artifacts while the network and daemons are alive.

        Override in subclasses to add pre-teardown collectors (e.g. fib_dump).
        Called before teardown(); net is still running.
        """

    def collect_debug_post_teardown(self):
        """Collect debug artifacts after daemons stop but before hN cleanup.

        Default implementation archives node_dirs if debug_config requests it.
        Override to add post-teardown collectors.
        """
        debug_config = getattr(self, "debug_config", None)
        if debug_config is None or not debug_config.node_dirs:
            return
        generated = getattr(self, "generated_node_dirs", [])
        if not generated:
            return
        run_dir = getattr(self, "run_dir", Path("."))
        from ..runtime.debug import archive_node_dirs
        archive_node_dirs(
            generated,
            run_dir / debug_config.output_subdir / "node_dirs",
        )

    def execute(self):
        """Run the full scenario lifecycle with guaranteed teardown."""
        from ..runtime.cleanup import cleanup_all
        from ..runtime.template import cleanup_node_dirs
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
                self.collect_debug_pre_teardown(net)
                try:
                    self.teardown(net)
                except Exception as exc:
                    info(f"Error during teardown: {exc}\n")
            self.collect_debug_post_teardown()
            generated_dirs = getattr(self, "generated_node_dirs", [])
            if net is not None:
                cleanup_all(net, generated_dirs)
            else:
                cleanup_node_dirs(generated_dirs)
