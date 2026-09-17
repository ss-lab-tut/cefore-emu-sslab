---
status: open
type: task
claimed-by:
blocked-by: []
---
## Task

**S9 — adjacency-graph builder 2 重複 unify**: `viz.py:35-47` build_host_graph (sparse — 0-edge host を含まない) と `fib.py:30-47` build_graph_and_subnets (dense — 全 host pre-populate) が同じ TopologyModel.edges() walk。しかも CacheContext.host_graph は viz 経由 (`scenario_setup.py:275`) で、cache 配置の graph 出所が可視化 module になっている。TopologyModel.adjacency() 等へ一本化。注意: dense/sparse の挙動差は実在 — 統一時に 0-edge host の扱いを明示的に決めること。

## Status (2026-08-23)

- 未着手。`viz.py:35-47` `build_host_graph` (sparse) と `fib.py:30-47` `build_graph_and_subnets` (dense) は現存。
- `CacheContext.host_graph` は `scenario_setup.py:275` で `build_host_graph` (viz) 経由のまま (元記述 :265 から更新)。
- `src/core/topology.py` `TopologyModel` (:33) に `adjacency()` は未実装 (grep 0 hits)。
