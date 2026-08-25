# Wayfinder Map — Architecture review backlog 消化 [wayfinder:map]

> tracker: local-markdown tier 2（docs/agents/issue-tracker.md）。
> `docs/wayfinder/**` は **常にコミット**（2026-08-23 ルール）。
> ticket 規約: tickets/NN-slug.md、frontmatter に status / type / claimed-by /
> blocked-by。frontier = open ∧ blocked-by 全 closed ∧ claimed-by 空。
> 各 ticket の `## Task` は CONTEXT.md 由来の原文段落を verbatim で保持し
> （file:line のみ 2026-08-23 の main で再検証・更新）、`## Status (2026-08-23)`
> に現状を付す。

## Destination

2026-06-26 architecture review round（および 2026-07-09 R10 review）backlog の
未着手 deepening 候補を消化し、完了ごとに CONTEXT.md の glossary に正式名を
追記する。

## Notes

- **execution 込み**（wayfinder デフォルトの plan-only を override）
- 出典: CONTEXT.md「次回実装候補 — Architecture review backlog」セクション
  （2026-08-23 にこの map へ移設。CONTEXT.md 側は glossary のみ残す）
- 優先順: Strong [01](tickets/01-s4-pub-lifetime-by-uri.md)–[05](tickets/05-s9-topology-adjacency.md)
  → Worth [06](tickets/06-w1-read-conf-value.md)–[13](tickets/13-w8-campaign-jobs-split.md)
  → Speculative [14](tickets/14-p1-set-config-value-underscore.md)/[15](tickets/15-p2-campaign-retry-seam.md) は保留
  → [16](tickets/16-kouho6-result-detect-into-verdict.md)–[19](tickets/19-kouho7-rename-topo-module.md) housekeeping pass
  → [20](tickets/20-deferred-ccninfo-monitoring-gaps.md) deferred
  → [21](tickets/21-recefore-rename-implementation.md)/[22](tickets/22-application-adapter-api.md) naming
- R10 backlog (2026-07-09 review 完了) の経緯: feature/seam (= main, PR#13 マージ後)
  を対象に 8 subsystem 並列探索 + 候補ごと adversarial 検証を実施、21 raw 候補中
  20 生存。bug 級 B1・B2 は 2026-07-09 に解消済み。Strong S1 (run_cefstatus
  deepening)・S2 (dead per-content label param 削除) は 2026-07-12 に実装完了。
  独立 housekeeping 負債は解消済み (2026-08-01 PR A fix-first): `mypy src`
  **0 errors**・`ruff check src tests` **0 errors** (いずれも fresh-cache 実測。
  stubs 追加 + mininet.* override + 実負債 30 件を type:ignore 0 件で本修正返済)。
  以後この 2 つは CI の zero-error gate が守る (ADR-0004)。mypy 計測は従来どおり
  fresh-cache (--no-incremental) 必須。
- 関連 ADR: ADR-0002（R8 FailurePolicy、[17](tickets/17-r8-failure-policy.md)）、
  ADR-0004（CI zero-error gate）
- 参照 skills: cefore-run-tests / typecheck / codebase-design

## Decisions so far

- S1 run_cefstatus deepening（2026-07-12 実装完了）
- S2 dead per-content label param 削除（2026-07-12 実装完了）
- S3 Disaster/Connect wiring 重複 collapse（b94eb97、`ConfigDrivenMeshScenario` 抽出）
  （W3 [08](tickets/08-w3-daemon-log-collection-enabled.md) を部分的に解消）
- S7 Monitor outcome tri-state（f93245a。[20](tickets/20-deferred-ccninfo-monitoring-gaps.md)
  の webui/ccninfo 側は未着手）
- B1 validate_merged_args present-but-empty structured config（73ca40b。
  残課題 `failure_scenarios: "none"` は [17](tickets/17-r8-failure-policy.md) へ）
- B3 validate_merged_args scalar explicit-null（d2680b1）
- B2 failure_manager cycle-mode host 恒久除外（7716a93）
- S5 flap descriptor 検証の単一化（2026-08-24、[02](tickets/02-s5-validate-flap-descriptor.md)。
  重複診断を解消し、R8 前のゼロ値・simple/cycles 非対称契約は維持）

## Fog

- [22](tickets/22-application-adapter-api.md) Adapter API は概念段階。形が決まるまで
  [21](tickets/21-recefore-rename-implementation.md) の改称実装とは切り離す
