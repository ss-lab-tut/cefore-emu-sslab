#!/usr/bin/env python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topo.mesh_disaster_topology import main  # noqa: E402

if __name__ == "__main__":
    main()
