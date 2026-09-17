---
status: open
type: task
claimed-by:
blocked-by: []
---
## Task

**W3 — daemon_log_collection_enabled の 3 __init__ copy hoist (低優先)**: 同一 3-line 式が config_driven_mesh/mesh/linear の __init__ に copy (disaster/connect 分は S3 で config_driven_mesh に統合済み、2026-09-02 訂正)。base.py の helper へ。注意: mesh/linear は run_dir を resolve しないので、constraint の実体は「raw param のうちに計算」。ConfigDriven の default logs / resolve 前 sentinel と Mesh/Linear の raw Path(.) は policy が違うため、3 行 helper は shallow になりがち。現状維持か pure predicate 化かの二案。

## Status (2026-08-23)

- **部分的に解消** (S3 b94eb97 の ConfigDrivenMeshScenario 抽出で disaster/connect 分が 1 つに統合)。src 側 copy は 4 → 3: `config_driven_mesh.py:47-49`、`mesh.py:59-61`、`linear.py:33-35`。
- `base.py:223` は `getattr(self, "daemon_log_collection_enabled", True)` で読むだけで helper は無い。
- テストは逆に 5 copy に増加 (`test_daemon_log_collection_enabled_uses_unresolved_run_dir`): `test_disaster_ops.py:41`、`test_connect.py:54`、`test_config_driven_mesh.py:57`、`test_mesh.py:29`、`test_linear.py:38`。
- (2026-09-17 訂正) 旧記述「自然な置き場は `ConfigDrivenMeshScenario` または `BaseScenario`」は撤回。Mesh/Linear は `ConfigDrivenMeshScenario` を継承せず、そこへ寄せるのは別再設計 (95f175a)。`BaseScenario` に 3 行 helper を置いても上記 policy 差で shallow になりがちなので、選択肢は現状維持か pure predicate 化の二案。
