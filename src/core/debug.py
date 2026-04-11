"""Debug configuration and artifact collection settings."""

from dataclasses import dataclass
from typing import Any

DEBUG_ARTIFACT_CHOICES = ("node_dirs", "fib_dump", "daemon_logs")


@dataclass(frozen=True, slots=True)
class DebugConfig:
    """Immutable configuration describing which debug artifacts to collect.

    Fields correspond to artifact types. Add new fields here when new
    artifact collectors are introduced in src/runtime/debug.py.
    """

    node_dirs: bool = False
    fib_dump: bool = False
    daemon_logs: bool = False
    output_subdir: str = "debug"

    def enabled(self) -> bool:
        """Return True if any artifact collection is enabled."""
        return self.node_dirs or self.fib_dump or self.daemon_logs


def build_debug_config(args: Any, raw_debug: Any = None) -> DebugConfig:
    """Build DebugConfig from CLI args and optional YAML/JSON debug block.

    Resolution order (union):
    - ``--debug`` flag on args → all artifacts ON
    - ``--debug-artifact`` list on args → specific artifacts ON
    - raw_debug=True → all artifacts ON
    - raw_debug={"artifacts": [...]} → specific artifacts ON

    Args:
        args: Parsed argparse namespace.
        raw_debug: Value of the ``debug`` key from a config file, or None.

    Returns:
        Resolved DebugConfig instance.
    """
    active: set[str] = set()
    output_subdir = "debug"

    # CLI --debug master flag
    if getattr(args, "debug", False):
        active.update(DEBUG_ARTIFACT_CHOICES)

    # CLI --debug-artifact individual flags
    for artifact in (getattr(args, "debug_artifact", None) or []):
        active.add(artifact)

    # YAML/JSON debug block
    if isinstance(raw_debug, bool):
        if raw_debug:
            active.update(DEBUG_ARTIFACT_CHOICES)
    elif isinstance(raw_debug, dict):
        artifacts = raw_debug.get("artifacts", [])
        if isinstance(artifacts, list):
            active.update(a for a in artifacts if isinstance(a, str))
        subdir = raw_debug.get("output_subdir")
        if isinstance(subdir, str) and subdir:
            output_subdir = subdir

    return DebugConfig(
        node_dirs="node_dirs" in active,
        fib_dump="fib_dump" in active,
        daemon_logs="daemon_logs" in active,
        output_subdir=output_subdir,
    )
