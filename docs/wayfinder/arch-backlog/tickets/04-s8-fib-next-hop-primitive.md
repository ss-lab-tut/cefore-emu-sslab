---
status: open
type: task
claimed-by:
blocked-by: []
---
## Task

**S8 — fib.py の next-hop selection 3 重複 collapse**: `:70-95` (compute_fib inline) / `:125-151` (_add_routes closure) / `:227-248` (_add_ecmp closure) が同一の candidate-build + sort + next_hop_ip 解決。共有 primitive へ。variation 軸は 2 つ: k-selection 規則 (top-k slice vs all-tied-minimum) と `seen` cross-call dedup (compute_fib のみ持たない)。

## Status (2026-08-23)

- 未着手。`src/core/fib.py`: `compute_fib` :50 の inline loop :70-95、`_add_routes` closure :125-151、`_add_ecmp` closure :227-248 の 3 重複が現存 (`seen` は :123 / :225 の 2 箇所)。
- 行番号は 2026-08-23 に再検証 (元記述 :75-95 / :125-150 / :227-247 から更新)。
