"""Common path constants for the topo package."""

from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATE_ROOT = ROOT_DIR / "configs" / "templates"


def resolve_run_dir(args: Any) -> Path:
    """Resolve and create the experiment output directory.

    Args:
        args: Parsed arguments with optional num, seed, output_dir,
              timestamp, and legacy_layout attributes.

    Returns:
        Path to the run directory. Returns current directory (".")
        for legacy layout or when neither num nor output_dir is specified.
    """
    if getattr(args, "legacy_layout", False):
        return Path(".")

    num = getattr(args, "num", None)
    output_dir = getattr(args, "output_dir", None)

    if num is None and not output_dir:
        return Path(".")

    seed = getattr(args, "seed", None)
    seed_label = "none" if seed is None else str(seed)

    base = output_dir or "logs"

    if num is not None:
        dir_name = f"ex{num}_seed{seed_label}"
    else:
        dir_name = f"seed{seed_label}"

    if getattr(args, "timestamp", False):
        dir_name += f"_{datetime.now().strftime('%Y%m%d-%H%M')}"

    run_dir = Path(base) / dir_name
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def ensure_within_run_dir(run_dir: Path, target: Path) -> Path:
    """Validate that target is inside run_dir and return absolute path.

    Args:
        run_dir: Root output directory.
        target: Target path to validate.

    Returns:
        Absolute resolved path.

    Raises:
        ValueError: If target is outside run_dir.
    """
    root = run_dir.resolve()
    resolved = target.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"path escapes run directory: {target}")
    return resolved


def resolve_run_path(
    run_dir: Path,
    raw_path: str | Path | None,
    default_name: str | None = None,
) -> Path:
    """Resolve a path under run_dir and create parent directories.

    Args:
        run_dir: Root output directory.
        raw_path: User-provided path.
        default_name: Fallback relative name when raw_path is empty.

    Returns:
        Absolute path under run_dir.

    Raises:
        ValueError: If path is outside run_dir or no path can be resolved.
    """
    if raw_path in (None, ""):
        if not default_name:
            raise ValueError("path is required")
        rel = Path(default_name)
    else:
        rel = Path(raw_path)

    root = run_dir.resolve()
    if rel.is_absolute():
        resolved = ensure_within_run_dir(root, rel)
    else:
        resolved = ensure_within_run_dir(root, root / rel)

    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved
