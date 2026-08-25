---
status: closed
type: task
claimed-by: codex-main
blocked-by: []
---
## Task

**S5 — _validate_failure_scenarios の simple/cycles 重複検査 collapse**: `validator.py:747-897` が同一 flap-descriptor 検査を simple 用と cycles[idx] 用に 2 実装し、negative count/stagger は同一エラー文字列が 2 回返る (実測: 2 violation で 4 errors)。`_validate_flap_descriptor(errors, prefix, descriptor, *, allow_target=, allow_publishers=)` へ抽出。R8 が同関数の schema を変える予定 (duration/interval >= 1) なので R8 着手前に済ませるか R8 に同梱するかは着手時に判断。

## Status (2026-08-23)

- 未着手。`_validate_failure_scenarios` は `validator.py:747-897` (次の def `_validate_bridges` が :898)。
- simple 用 / cycles[idx] 用の重複検査は現存し、negative count/stagger の同一エラー文字列は依然 2 回 emit される。
- 着手時に決めること: 単独で先に済ませるか、R8 ([17](17-r8-failure-policy.md)) に同梱するか。

## Resolution (2026-08-24)

- S5 を R8 から分離して実装し、simple と cycles の共通フィールド検証を `_validate_flap_descriptor` に集約した。
- negative `count` / `stagger` は違反ごとに同一診断を 1 回だけ返す。exact-match テストで simple と cycles の診断全文・順序を固定した。
- R8 のポリシー変更は先取りせず、`interval=0` / `duration=0` を許容する現行契約と、simple が cycle 専用の `target` / `allow_publishers` を検証しない非対称性を維持した。
- 完全ゲートを通過: pytest 1517 passed / 6 skipped、mypy 73 files、ruff check、変更範囲の ruff format check、全 Mininet/Cefore smoke（connect を含む）。
