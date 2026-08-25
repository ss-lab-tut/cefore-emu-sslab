---
status: closed
type: grilling
claimed-by: claude-code
blocked-by: []
---
## Question

実装の PR 構成と担当割りをどうするか。

## Resolution (2026-08-01)

**PR 2 本 + ハイブリッド担当**。
- PR A `chore/ci-debt-payoff`: 負債返済（stubs/override + mypy ~30 件 +
  ruff F401×10 + examples テスト + CONTEXT.md 数値更新）。mypy 返済は
  codex-main へ agmsg 委譲（codex-review 付き）
- PR B `feat/ci-pipeline`: ci.yml + [tool.coverage] + ADR-0004 + README 1 段落。
  claude-code（本セッション）実装。A マージ後に提出し初回から green
- 機械的返済 30 件と CI 設計を同一 diff にするとレビューで本質が埋もれるため
  1 PR 案は却下。両 PR とも opencode/codex 外部レビュー（10 分 → codex MCP 代替）
- PR 作成は人間（gh 401 のため）。push は SSH
