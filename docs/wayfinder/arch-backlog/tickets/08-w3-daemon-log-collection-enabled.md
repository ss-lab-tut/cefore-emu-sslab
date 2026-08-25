---
status: open
type: task
claimed-by:
blocked-by: []
---
## Task

**W3 — daemon_log_collection_enabled の 4 __init__ copy hoist**: 同一 3-line 式が disaster/connect/mesh/linear の __init__ に copy、対応 test も 4 重複。base.py の helper へ。注意: mesh/linear は run_dir を resolve しないので、constraint の実体は「raw param のうちに計算」(disaster/connect のみ resolve 前後の話)。

## Status (2026-08-23)

- **部分的に解消** (S3 b94eb97 の ConfigDrivenMeshScenario 抽出で disaster/connect 分が 1 つに統合)。src 側 copy は 4 → 3: `config_driven_mesh.py:47-49`、`mesh.py:59-61`、`linear.py:33-35`。
- `base.py:223` は `getattr(self, "daemon_log_collection_enabled", True)` で読むだけで helper は無い。
- テストは逆に 5 copy に増加 (`test_daemon_log_collection_enabled_uses_unresolved_run_dir`): `test_disaster_ops.py:41`、`test_connect.py:54`、`test_config_driven_mesh.py:57`、`test_mesh.py:29`、`test_linear.py:38`。
- 自然な置き場は `ConfigDrivenMeshScenario` または `BaseScenario`。
