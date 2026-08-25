---
status: open
type: task
claimed-by:
blocked-by: []
---
## Task

**W6 — campaign.py/supervise.sh の job-done semantics 統一**: `supervise.sh:32` は ok/failed/skipped_memory を done 扱い、`campaign.py:287-306` _load_completed_job_ids は ok のみ — 2 プロセスが campaign 完了判定で食い違う。単純に ok-only へ寄せると deterministically-broken job で infinite-relaunch になるため、per-job give-up status の永続化とセットで `campaign.py --check-done` 等の単一判定点を作る。

## Status (2026-08-23)

- 未着手。`supervise.sh:32` は ok/failed/skipped_memory を done 扱いのまま。`_load_completed_job_ids` は `campaign.py:287-306` (元記述 :303-304 から更新)。
- :288-292 の docstring は「ok のみ done、failed/timeout/skipped_memory は再試行」と ok-only を正当化しているが、supervise.sh 側との食い違いは reconcile されていない。
- `--check-done` は未実装 (grep 0 hits)。
