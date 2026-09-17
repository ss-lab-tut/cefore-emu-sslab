---
status: open
type: task
claimed-by:
blocked-by: []
---
## Task

**P2 (保留) — campaign.py retry policy の injectable seam**: `_run_job_attempts` が _mem_available_fraction/_run_job_subprocess を hardwire、tools/ 配下は現状テストゼロ。seam 欠如がテスト不在の blocker とは未立証 — tools/ のテスト方針決定とセットで。

## Status (2026-08-23)

- 保留のまま。`_run_job_attempts` は `tools/workshop/campaign.py:370-380` (signature) で `_mem_available_fraction` / `_run_job_subprocess` を hardwire。
- `tests/tools/` には `test_run_cefore_checks.py` のみ。`tools/workshop` のテストはゼロ。tools/ のテスト方針が先。
