"""Single owner of experiment artifact naming schema.

This module owns directory names, topology PNG defaults, and canonical content
log names. It intentionally stays stdlib-only without importing other ``src``
modules so artifact naming cannot create configuration/path import cycles.
"""

from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

_CONTENT_LOG_RE = re.compile(
    r"^(cefputfile|cefgetfile|cefpubfile|cefsubfile)_([a-z]+)_h(\d+)_(.+)\.log$"
)


@dataclass(frozen=True)
class ContentLogMeta:
    """Canonical metadata encoded in a content operation log filename."""

    command: str
    phase: str
    host: int
    label: str


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


def safe_uri_label(uri: str) -> str:
    """Convert a Cefore URI into the canonical filesystem-safe log label."""
    return uri.replace("ccnx:/", "").replace("/", "_")


def content_log_name(cmd: str, phase: str, host: int, uri: str) -> str:
    """Return the canonical content-operation log filename.

    Content logs are the join key between text logs and results.json records,
    so command, phase, host, and URI label live in one parseable filename.
    """
    return f"{cmd}_{phase}_h{host}_{safe_uri_label(uri)}.log"


def parse_content_log_name(name: str | Path) -> ContentLogMeta | None:
    """Parse a canonical content log name, returning None for legacy shapes."""
    match = _CONTENT_LOG_RE.match(Path(name).name)
    if match is None:
        return None
    return ContentLogMeta(
        command=match.group(1),
        phase=match.group(2),
        host=int(match.group(3)),
        label=match.group(4),
    )
