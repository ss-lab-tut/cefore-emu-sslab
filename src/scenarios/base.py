"""Base scenario with SIGINT/exception teardown guarantee."""

from abc import ABC, abstractmethod
from pathlib import Path

from mininet.cli import CLI
from mininet.log import info

from ..runtime.cleanup import cleanup_all
from ..runtime.template import cleanup_node_dirs


def _propagate_failures(
    primary_exc: BaseException | None,
    cleanup_failures: list[tuple[str, BaseException]],
) -> None:
    """Aggregate and re-raise primary and cleanup failures.

    Rules:
    - No failures: return silently.
    - Primary only: re-raise primary directly.
    - Single cleanup failure with no primary: re-raise it directly
      (preserves single-raise rule even when the failure is
      `KeyboardInterrupt` / `SystemExit`).
    - Multiple cleanup failures with no primary: raise
      `BaseExceptionGroup` if any member is a non-`Exception`
      `BaseException`; otherwise raise `ExceptionGroup`.
    - Primary plus any cleanup failures: raise `BaseExceptionGroup`
      so non-`Exception` primaries (e.g. `SystemExit`) are accepted.
    """
    if not cleanup_failures:
        if primary_exc is not None:
            raise primary_exc
        return
    if primary_exc is not None:
        all_exceptions: list[BaseException] = [primary_exc]
        all_exceptions.extend(f[1] for f in cleanup_failures)
        raise BaseExceptionGroup("lifecycle failures", all_exceptions)
    if len(cleanup_failures) == 1:
        raise cleanup_failures[0][1]
    excs = [f[1] for f in cleanup_failures]
    if any(not isinstance(e, Exception) for e in excs):
        raise BaseExceptionGroup("cleanup failures", excs)
    raise ExceptionGroup("cleanup failures", excs)


class BaseScenario(ABC):
    """Abstract base for all Cefore emulation scenarios.

    Guarantees teardown runs even on SIGINT or exception.

    Subclasses should set:
        self.generated_node_dirs  -- list[Path] returned by provision_node_dirs()
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

    def run_main(self, net):
        """Run the foreground stage after run_experiment() completes.

        Default: enter an interactive CLI when should_run_cli() is True.
        Subclasses gate the CLI (e.g. autotest) via should_run_cli() and wrap
        it via before_cli()/after_cli() instead of overriding execute().
        """
        if self.should_run_cli():
            self.before_cli(net)
            self.run_cli(net)
            self.after_cli(net)

    def should_run_cli(self):
        """Whether run_main() enters the interactive CLI. Default True."""
        return True

    def before_cli(self, net):
        """Hook run immediately before the CLI (e.g. monitor background)."""

    def after_cli(self, net):
        """Hook run immediately after the CLI returns."""

    def run_cli(self, net):
        """Enter the interactive CLI. Override only to change the CLI itself."""
        CLI(net)

    def shutdown_runtime_resources(self):
        """Stop background runtime resources before teardown.

        Called first in the cleanup phase, while net is still up. Each resource
        must be stopped independently; return a list of (stage, exception) for
        any failures so they are aggregated with the teardown failures. Default
        has no runtime resources and returns an empty list.
        """
        return []

    def write_results(self):
        """Persist results after all operational cleanup, before propagation.

        Return a list of (stage, exception) for any failure. Default no-op.
        """
        return []

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
        from ..core.paths import ensure_within_run_dir
        from ..runtime.debug import archive_node_dirs
        dest = run_dir / debug_config.output_subdir / "node_dirs"
        ensure_within_run_dir(run_dir, dest)
        archive_node_dirs(generated, dest)

    def execute(self):
        """Run the full scenario lifecycle with guaranteed teardown.

        Staged cleanup: every stage is attempted independently. Failures
        are accumulated and re-raised after all cleanup completes.
        """
        import sys
        net = None
        try:
            topo = self.build_topology()
            net = self.create_mininet(topo)
            net.start()
            self.configure(net)
            self.run_experiment(net)
            self.run_main(net)
        except KeyboardInterrupt:
            info("\nInterrupted by user.\n")
        finally:
            primary_exc = sys.exc_info()[1]
            if isinstance(primary_exc, KeyboardInterrupt):
                primary_exc = None

            cleanup_failures: list[tuple[str, BaseException]] = []

            # Stop background runtime resources first, while net is still up.
            # The hook returns per-resource failures; guard the call itself so a
            # hook that raises cannot skip teardown/cleanup_all.
            try:
                cleanup_failures.extend(self.shutdown_runtime_resources())
            except BaseException as exc:
                cleanup_failures.append(("shutdown_runtime_resources", exc))

            if net is not None:
                try:
                    self.collect_debug_pre_teardown(net)
                except BaseException as exc:
                    cleanup_failures.append(("debug_pre_teardown", exc))

                try:
                    self.teardown(net)
                except BaseException as exc:
                    cleanup_failures.append(("teardown", exc))
                    info(f"Error during teardown: {exc}\n")

                try:
                    self.collect_debug_post_teardown()
                except BaseException as exc:
                    cleanup_failures.append(("debug_post_teardown", exc))

                try:
                    cleanup_all(net, getattr(self, "generated_node_dirs", []))
                except BaseException as exc:
                    cleanup_failures.append(("cleanup_all", exc))
            else:
                try:
                    cleanup_node_dirs(getattr(self, "generated_node_dirs", []))
                except BaseException as exc:
                    cleanup_failures.append(("cleanup_node_dirs", exc))

            # Persist results after all operational cleanup. Guard the hook
            # call itself so a raising hook still reaches propagation.
            try:
                cleanup_failures.extend(self.write_results())
            except BaseException as exc:
                cleanup_failures.append(("write_results", exc))

            # Propagate failures after all cleanup
            _propagate_failures(primary_exc, cleanup_failures)
