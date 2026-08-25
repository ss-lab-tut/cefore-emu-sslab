---
status: open
type: task
claimed-by:
blocked-by: []
---
## Task

**候補7 — `runtime/topo.py` を `runtime/mesh_topo.py` にリネーム**:
`runtime/topo.py` (Mininet Topo subclasses) と `core/topology.py` (TopologyModel pure query) の名前近接 (4文字+1ディレクトリ差) が読者を混乱させる純 housekeeping。Speculative — 上記候補が片付いた後の cleanup pass で。
_Avoid_: 単独でこのリネームに取り掛かること (他の deepening が optimal の後でまとめて)

## Status (2026-08-23)

- 未着手。`src/runtime/topo.py` 現存、`src/runtime/mesh_topo.py` は存在しない。
- 01-13 の deepening が片付いた後の cleanup pass で、[18](18-swhich-num-legacy-chain-rename.md) と同時に行う。
