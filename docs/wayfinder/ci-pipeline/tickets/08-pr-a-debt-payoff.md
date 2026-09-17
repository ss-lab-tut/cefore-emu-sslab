---
status: closed
type: task
claimed-by: claude-code
blocked-by: []
---
<!-- Resolution 2026-08-01: main へマージ済み (373a9b9..63608b7)。6 commits、
     codex-review + opencode 両 approve、mypy 0 / ruff 0 / pytest 1516+6skip /
     min_putget smoke OK。bootstrap exception としてローカル証跡を PR 本文に添付 -->

<!-- 進捗 2026-08-01: 6 commits (b2fc5d1/2cb815b/a940011/f021c81/a45b456/b63b516)。
     レビュー対応 b63b516 (checked narrowing 2件 + manifest 20件固定 + 根拠コメント)
     まで完了、codex-review approve (findings 0) + opencode approve。
     branch push 済み。残: ユーザーの PR 作成 → merge 確認で close -->

## Question

PR A（負債返済）を実装しマージする — 当時の ephemeral な PLAN.md（未コミット）の第 3 節の 6 項目:
stubs 追加 / mypy 設定 / mypy ~30 件返済（codex-main 委譲）/ ruff F401 autofix /
config examples pytest テスト（全 20 examples の clean 通過を先に実測）/
CONTEXT.md の mypy/ruff 負債数値更新（a45b456）。

受け入れ条件: `mypy src`=0、`ruff check src tests`=0、full pytest green、
挙動変更ゼロ（型注釈・ignore・import 削除のみ）。

## Status (2026-09-17)

- done: PR #18 merge 63608b7（6 commits: b2fc5d1 / 2cb815b / a940011 / f021c81 / a45b456 / b63b516）。
