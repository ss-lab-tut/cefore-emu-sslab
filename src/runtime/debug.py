"""Debug artifact collectors for Cefore emulation scenarios.

Each public function in this module collects one type of debug artifact.
Add new collectors here as new DebugConfig fields are introduced.

Collection phases (see scenarios/base.py):
- pre_teardown:  network and daemons are still alive  (e.g. fib_dump)
- post_teardown: daemons stopped, ./hN dirs still present  (e.g. node_dirs)
"""

import shutil
from pathlib import Path

from .command_runner import MininetCommandRunner


def archive_node_dirs(generated_dirs: list[Path], dest_dir: Path) -> None:
    """Copy generated hN directories to dest_dir/hN/.

    Args:
        generated_dirs: List of hN Path objects returned by provision_node_dirs().
        dest_dir: Destination directory (created if absent).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    for node_dir in generated_dirs:
        if not node_dir.is_dir():
            continue
        dst = dest_dir / node_dir.name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(node_dir, dst)


def dump_fib(net, host_ids: list[int], dest_dir: Path) -> None:
    """Dump FIB tables for the given hosts to dest_dir/fib_hN.txt."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    runner = MininetCommandRunner(net)
    for idx in host_ids:
        node_name = f"h{idx}"
        output = runner.run(node_name, ["cefstatus", "-d", f"./{node_name}"]).stdout
        (dest_dir / f"fib_{node_name}.txt").write_text(output, encoding="utf-8")
