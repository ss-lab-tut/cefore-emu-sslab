---
status: open
type: task
claimed-by:
blocked-by: []
---
## Task

**S4 — pub_lifetime_by_uri 二重導出**: `event_batch.py:54-63` の module-private helper を public 化し、`disaster.py:221-227` (_make_content_runner 内の inline 再実装) を置換。warmup 経路が seam 外なのは意図 (CONTEXT の EventBatchSpec 項) — 導出関数だけ共有する。

## Status (2026-08-23)

- 未着手。`event_batch.py:54` `_pub_lifetime_by_uri` は依然 module-private。
- `disaster.py:221-227` (`_make_content_runner` 内、:214 開始) に inline 再導出が残存。
- 行番号は 2026-08-23 の main で再検証済み (元記述 :55-64 / :274-280 から更新)。
