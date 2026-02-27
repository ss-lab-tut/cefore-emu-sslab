"""Common path constants."""

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
        for legacy layout or when num is not specified.
    """
    if getattr(args, "legacy_layout", False):
        return Path(".")

    num = getattr(args, "num", None)
    if num is None:
        return Path(".")

    seed = getattr(args, "seed", None)
    seed_label = "none" if seed is None else str(seed)

    base = getattr(args, "output_dir", "logs") or "logs"
    dir_name = f"ex{num}_seed{seed_label}"

    if getattr(args, "timestamp", False):
        dir_name += f"_{datetime.now().strftime('%Y%m%d-%H%M')}"

    run_dir = Path(base) / dir_name
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir
