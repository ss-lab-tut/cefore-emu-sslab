# Wayfinder Map — CI パイプライン導入 [wayfinder:map]

> tracker: local-markdown tier 2（docs/agents/issue-tracker.md）。
> 2026-08-23 ルール変更: `docs/wayfinder/**` は **常にコミット**（旧注記「PLAN.md
> と同じ ephemeral 扱い、コミットしない」は廃止。恒久成果は ADR-0004 / CONTEXT.md /
> .github/workflows に昇格済み、この map は履歴として残す）。
> ticket 規約: tickets/NN-slug.md、frontmatter に status / type / claimed-by /
> blocked-by。frontier = open ∧ blocked-by 全 closed ∧ claimed-by 空。

## Destination

PR→main と push→main で発動する CI workflow（pytest+coverage / ruff check /
mypy / uv lock --check / entry-points 検査）が main にマージされ、実際に green で
走っている状態。required checks 化は手順書を渡して人間が GitHub UI で実施。

## Notes

- **execution 込み**（wayfinder デフォルトの plan-only を override。2026-08-01 決定）
- 言語: 日本語。実装計画の全文は repo ルートの PLAN.md（レビュアー向け単一文書）
- 外部レビュー: agmsg の opencode + codex。**10 分無応答なら codex MCP
  (gpt-5.6-sol, reasoning max) に切替**（ユーザー指定フォールバック）
- 重い機械実装（mypy 返済）は codex-main へ agmsg 委譲、per-phase codex-review、
  完了報告前に advisor gate（feedback memory 準拠）
- 制約: main は branch protection 有効（2026-08-01〜）。全変更 PR 経由。
  `gh` CLI は PAT 401 → push は SSH、PR 作成は人間が Web UI
- 参照 skills: cefore-run-tests / typecheck / orchestration
- 一次資料: issue 16（mutation round 1 報告、CI 不在の前提訂正と round 2 候補）

## Decisions so far

- [01 Destination は実装完了まで](tickets/01-destination.md) — plan-only でなく CI 稼働まで
- [02 v1 ジョブ構成](tickets/02-job-composition.md) — pytest+coverage/ruff check/mypy/lock check/entry-points。format gate と mutation dispatch は不採用
- [03 mypy は fix-first → zero-error gate](tickets/03-mypy-policy.md) — default 設定で 0 errors を gate（--strict mode 不採用）、baseline 機構なし
- [04 coverage は fail_under=85 + artifact](tickets/04-coverage-policy.md) — cov-context 付き、round 2 の covering-set 材料を毎回保存
- [05 e2e smoke は v1 対象外](tickets/05-smoke-scope.md) — hosted-runner 実現性は ticket 11 の prototype へ、self-hosted は恒久却下
- [06 CI は素コマンド直接実行](tickets/06-ci-entry-shape.md) — runner 単一エントリ案却下、examples 検証は pytest テスト化
- [07 PR 2 本 + ハイブリッド担当](tickets/07-implementation-structure.md) — A=負債返済(codex-main)、B=CI 本体(claude-code)
- [08 PR A 負債返済](tickets/08-pr-a-debt-payoff.md) — マージ済み: mypy/ruff 0 化 + examples 検証 (6 commits、両レビュアー approve、min_putget smoke OK)
- [09 PR B CI 本体](tickets/09-pr-b-ci-workflow.md) — PR #19 マージ済み (8c346c5): 4 jobs 41秒、PR/push 両イベントで green を runtime 証明。setup-uv floating tag 不在 (P1) をレビューで捕捉
- [10 required checks 設定](tickets/10-required-checks-handoff.md) — 2026-08-01 ユーザーが UI 設定完了 → **destination 到達**。残 open は [11 smoke prototype](tickets/11-smoke-prototype.md) (post-v1) のみ

## Not yet specified

- ADR-0004 の Consequences に載せる却下理由の最終文面（PR B 実装時に確定）
- actions（checkout / setup-uv / upload-artifact）の実装時点の最新 major 確認

## Out of scope

- ruff format gate — 54 files 大整形 + blame 汚れとの引き換えで却下（[02](tickets/02-job-composition.md)）。再訪可
- mutation round 2 の workflow_dispatch ジョブ — round 2 planning の別 effort として仕切り直し（[02](tickets/02-job-composition.md)）
- self-hosted runner — public repo で fork-PR 任意コード実行リスク。恒久却下（[05](tickets/05-smoke-scope.md)）
- Python 3.13 matrix — ラボ 3.12 固定
