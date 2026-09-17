---
status: closed
type: grilling
claimed-by: claude-code
blocked-by: []
---
## Question

mypy 赤字（stubs/override 返済後に残る実質 ~30 errors）を fix-first / baseline
ratchet / 非ブロッキング観測のどれで扱うか。gate の意味は default 設定での
zero-error か mypy --strict mode か。

## Resolution (2026-08-01)

**fix-first → zero-error gate**。stubs（types-PyYAML, types-networkx）+ `mininet.*`
override で 68→~30、残り 30 を codex-main 委譲で返済してから CI は素の
`mypy src`=0 を gate にする。default 設定であり mypy `--strict` mode ではない
（--strict は実測 826 errors / 56 files で別次元 — codex review QUESTION cx-1 で
曖昧語を摘出、2026-08-01 に A 案確定）。baseline 機構は導入しない — 当時の CONTEXT.md backlog 節（現在は
[arch-backlog map](../../arch-backlog/map.md) の Notes「mypy 計測は従来どおり fresh-cache 必須」）に
「baseline は fresh-cache 必須（incremental は過小計数）」のヤケド記録があり、
count-based 運用の脆さは実証済み。手強い個所のみ `# type: ignore[code]` +
理由コメント（mypy 標準の作法で個別明示、基盤不要）。
逃げ ignore が 10 を超えたら本決定を map に差し戻す（当時の ephemeral な PLAN.md（未コミット）の A3 項。恒久記録は
[ADR-0004](../../../adr/0004-ci-guards-unit-surface-only.md) mypy 節の Tripwire）。

## Status (2026-09-17)

- done: mypy 返済は PR A（merge 63608b7、b2fc5d1 / f021c81 / b63b516）、zero-error gate は ci.yml typecheck job（832ffe3）。default 設定・`--strict` 不採用・baseline 不採用・ignore tripwire は [ADR-0004](../../../adr/0004-ci-guards-unit-surface-only.md) に記録。
