---
status: open
type: task
claimed-by:
blocked-by: []
---
## Task

**W4 — cefroute_add/del/enable の boilerplate collapse**: `net_config.py:51-85` / `:154-177` / `:180-203` が verb 以外同形の 12 行 (drift 実在: add のみ非ゼロ returncode の failure logging を持つ)。verb-parametrized private helper へ。

## Status (2026-08-23)

- 未着手。`net_config.py` `cefroute_add` :51-85 / `cefroute_del` :154-177 / `cefroute_enable` :180-203 (行番号は 2026-08-23 に再検証、元記述と同一)。
- drift 現存: add のみ非ゼロ returncode の failure logging (:79-84) を持ち、add は `CommandResult` を返すが del/enable は `bool` を返す。
