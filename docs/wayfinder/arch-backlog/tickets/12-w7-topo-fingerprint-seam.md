---
status: open
type: task
claimed-by:
blocked-by: []
---
## Task

**W7 — topo_fingerprint.py を MeshBuildSpec seam 経由に**: `topo_fingerprint.py:118-126` が rng→assign_roles→MeshTopo の RNG-order invariant を手写し (docstring 自身が fragility を明記)。scenario_setup.py に filesystem-free な rng-only sub-step (または provision skip flag) を作り両者が呼ぶ。

## Status (2026-08-23)

- 未着手。`tools/workshop/topo_fingerprint.py` :103-114 の docstring が RNG-order invariant の fragility を明記し、:118-126 で `MeshTopo(...)` を直接構築 (元記述 :116-126 から更新)。
- `MeshBuildSpec` (`scenario_setup.py:124`) は docstring で言及されるだけで import されていない (`from src.runtime.topo import MeshTopo` :36 のみ)。
