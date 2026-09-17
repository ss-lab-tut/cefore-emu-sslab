---
status: closed
type: task
claimed-by: claude-code
blocked-by: [08]
---
<!-- Resolution 2026-08-01: PR #19 として main へマージ (8c346c5)。4 commits、
     opencode approve (P1 setup-uv@v9 不在→v9.0.0 pin) + codex-review P2×3
     (2採用/1根拠付き不採用: python pin は .python-version が唯一の源)。
     runtime 証明: CI #1 (PR event) 42s green / CI #2 (push event) 41s green -->

## Question

PR B（CI 本体）を実装しマージする — 当時の ephemeral な PLAN.md（未コミット）の第 4 節（恒久記録は
[ADR-0004](../../../adr/0004-ci-guards-unit-surface-only.md)）:
.github/workflows/ci.yml（test/lint/typecheck/packaging の 4 jobs）/
[tool.coverage.report] fail_under=85 / ADR-0004 / README 1 段落 /
actions 最新 major の確認と固定。

受け入れ条件: PR B 自身の CI 実行が 4 jobs 全 green、マージ後 push でも green。

## Status (2026-09-17)

- done: PR #19 merge 8c346c5（832ffe3 ci.yml / b41938c ADR-0004 + README / b335f1d setup-uv v9.0.0 pin / c9255ee comment 整理）。CI 実行結果（green）は GitHub Actions 側の記録で git からは検証不能。後続: 0430afa で `workflow_call` 追加（release.yml が再利用）。
