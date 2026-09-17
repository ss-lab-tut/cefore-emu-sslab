---
status: closed
type: grilling
claimed-by: claude-code
blocked-by: []
---
## Question

この CI effort の destination はどこまでか — 設計計画のみ / 実装完了まで /
最小 CI 即実装+拡張 map 化。

## Resolution (2026-08-01)

**実装完了まで**。CI workflow が main にマージされ PR/push で実際に green に走る
ところまでがこの effort。理由: 規模が YAML+返済 commit 数個で「計画だけ渡す」
意味が薄く、unit suite 15s/hermetic 実測済みで実装リスクが低い。required checks
化のみ手順書 + 人間の GitHub UI 操作（API write 不可）。

## Status (2026-09-17)

- done: CI workflow は main にマージ済み（ci.yml 追加 832ffe3、PR #19 merge 8c346c5）。決定は [ADR-0004](../../../adr/0004-ci-guards-unit-surface-only.md) に記録。
