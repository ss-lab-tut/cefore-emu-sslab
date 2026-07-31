"""Common path constants."""

from pathlib import Path
from typing import Any, cast

from .artifacts import experiment_dir_name

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATE_ROOT = ROOT_DIR / "config" / "templates"


def resolve_run_dir(args: Any) -> Path:
    """Resolve and create the experiment output directory.

    Args:
        args: Parsed arguments with optional num, seed, output_dir,
              and timestamp attributes.

    Returns:
        Path to the run directory. Returns current directory (".")
        when neither num nor output_dir is specified.
    """
    num = getattr(args, "num", None)
    output_dir = getattr(args, "output_dir", None)

    if num is None and not output_dir:
        return Path(".")

    base = output_dir or "logs"
    dir_name = experiment_dir_name(
        num,
        getattr(args, "seed", None),
        timestamp=getattr(args, "timestamp", False),
    )

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
        rel = Path(cast(str | Path, raw_path))

    root = run_dir.resolve()
    if rel.is_absolute():
        resolved = ensure_within_run_dir(root, rel)
    else:
        resolved = ensure_within_run_dir(root, root / rel)

    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved
