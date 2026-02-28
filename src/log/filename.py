"""Parse log filenames into structured metadata."""

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FilenameMeta:
    """Metadata extracted from a log filename."""

    command: str
    host_id: int
    content_id: int | None = None
    seed: int | None = None
    down_hosts: str | None = None
    idx: int | None = None


# Pattern A: host + content  e.g. cefputfile_h13_c10.log
_PAT_HOST_CONTENT = re.compile(
    r"^(cef(?:put|get|pub|sub)file)_h(\d+)_c(\d+)\.log$"
)

# Pattern B: host only  e.g. cefputfile_h9.log
_PAT_HOST_ONLY = re.compile(
    r"^(cef(?:put|get|pub|sub)file)_h(\d+)\.log$"
)

# Pattern C: disaster  e.g. cefgetfile_seed42_downhosts0,1_idx16_h4.log
_PAT_DISASTER = re.compile(
    r"^(cef(?:put|get|pub|sub)file)_seed(\d+)_downhosts([\d,]+)_idx(\d+)_h(\d+)\.log$"
)

# Pattern D: legacy  e.g. cefgetfile-h0.log
_PAT_LEGACY = re.compile(
    r"^(cef(?:put|get|pub|sub)file)-h(\d+)\.log$"
)


def parse_filename(path: str | Path) -> FilenameMeta | None:
    """Extract metadata from a log filename.

    Returns None if the filename does not match any known pattern.
    """
    name = Path(path).name

    m = _PAT_HOST_CONTENT.match(name)
    if m:
        return FilenameMeta(
            command=m.group(1),
            host_id=int(m.group(2)),
            content_id=int(m.group(3)),
        )

    m = _PAT_DISASTER.match(name)
    if m:
        return FilenameMeta(
            command=m.group(1),
            host_id=int(m.group(5)),
            seed=int(m.group(2)),
            down_hosts=m.group(3),
            idx=int(m.group(4)),
        )

    m = _PAT_HOST_ONLY.match(name)
    if m:
        return FilenameMeta(
            command=m.group(1),
            host_id=int(m.group(2)),
        )

    m = _PAT_LEGACY.match(name)
    if m:
        return FilenameMeta(
            command=m.group(1),
            host_id=int(m.group(2)),
        )

    return None
