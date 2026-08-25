---
status: open
type: task
claimed-by:
blocked-by: []
---
## Task

**W8 — plots.py の job-discovery layer 分離**: 1095 LOC に dataviz chrome + Job/discovery layer (:158-310、加えて _m1_jobs_by_seed/_m1_groups は fig セクション内に混在) + 10 fig_* が同居。`report.py:37` は discovery 到達のためだけに matplotlib ごと import し、underscore 4 関数 × 12 call sites が実質 interface。matplotlib-free な campaign_jobs.py へ抽出。

## Status (2026-08-23)

- 未着手。`tools/workshop/plots.py` は 1354 LOC に増加 (元記述 1095)。`class Job` :158 から discovery layer :158-310 (`eval_success` :311 が境界; 元記述 :153-310 から更新)。`_m1_jobs_by_seed` :321 / `_m1_groups` :342 は依然 fig セクション側。
- `report.py:37` `import plots` のまま。`campaign_jobs.py` は未作成。
