"""Single owner of experiment artifact naming schema.

This module owns directory names and topology PNG defaults. Log-name
build/parse belongs to a later slice, and this file intentionally stays
stdlib-only without importing other ``src`` modules so artifact naming cannot
create configuration/path import cycles.
"""

from datetime import datetime
from typing import Any


def experiment_dir_name(num: int | None, seed: Any, *, timestamp: bool = False) -> str:
    """Return the canonical experiment directory name.

    Directory names are shared by CLI runs, path resolution, and autotest
    indexing; keeping the seed label and optional timestamp here prevents
    silent drift between producers and readers.
    """
    seed_label = "none" if seed is None else str(seed)
    if num is not None:
        dir_name = f"ex{num}_seed{seed_label}"
    else:
        dir_name = f"seed{seed_label}"

    if timestamp:
        dir_name += f"_{datetime.now().strftime('%Y%m%d-%H%M')}"
    return dir_name


def topo_png_default_name(num: int | None, seed: Any, hosts: int) -> str:
    """Return the default topology PNG name for an experiment.

    2026-07-03 artifact-layout fix: the old default used host count in the
    experiment-number position (``ex{hosts}_seed...``), which made PNG names
    read like a different experiment id. No repo code parses PNG names, so the
    default now records experiment identity first and host count as ``_h``.
    """
    return f"{experiment_dir_name(num, seed)}_h{hosts}.png"
