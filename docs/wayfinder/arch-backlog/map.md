# Wayfinder Map — Architecture review backlog 消化 [wayfinder:map]

> tracker: local-markdown tier 2（docs/agents/issue-tracker.md）。
> `docs/wayfinder/**` は **常にコミット**（2026-08-23 ルール）。
> ticket 規約: tickets/NN-slug.md、frontmatter に status / type / claimed-by /
> blocked-by。frontier = open ∧ blocked-by 全 closed ∧ claimed-by 空。
> 各 ticket の `## Task` は CONTEXT.md 由来の原文段落を verbatim で保持し
> （file:line のみ 2026-08-23 の main で再検証・更新）、`## Status (2026-08-23)`
> に現状を付す。2026-09-17: main defeeb4 で再検証し、95f175a の backlog 台帳訂正
> と 7a545f8 / 420ef1e / 3c30cd0 / 9740a80 / a455bc7 の反映を ticket 側へ移植
> （訂正箇所は「2026-09-17 訂正」または commit hash で明示）。

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
  → [17](tickets/17-r8-failure-policy.md)–[19](tickets/19-kouho7-rename-topo-module.md) housekeeping pass
    （[16](tickets/16-kouho6-result-detect-into-verdict.md) 候補6 は 2026-09-02 撤回済みのため順序から除外）
  → [20](tickets/20-deferred-ccninfo-monitoring-gaps.md) deferred
  → [21](tickets/21-recefore-rename-implementation.md)/[22](tickets/22-application-adapter-api.md) naming
  → [23](tickets/23-host-node-name-helper.md) host 番号 → ノード名変換の集約（着手条件付き。21/22 でノード識別子を見直すとき）
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
- 参照 skills: cefore-run-tests / typecheck（いずれも repo 内 `.agents/skills`）/ codebase-design
  （外部 skill pack mattpocock/skills 由来で repo には vendoring していない。CLAUDE.md の Agent skills 節参照）

## Decisions so far

- S1 run_cefstatus deepening（2026-07-12 実装完了）
- S2 dead per-content label param 削除（2026-07-12 実装完了）
- S3 Disaster/Connect wiring 重複 collapse（2026-07-16, b94eb97、`ConfigDrivenMeshScenario` 抽出）
  （W3 [08](tickets/08-w3-daemon-log-collection-enabled.md) を部分的に解消）。
  Mesh/Linear まで `ConfigDrivenMeshScenario` に寄せるのは別再設計（95f175a, 2026-09-02 再確認）
- S7 Monitor outcome tri-state（2026-07-16, f93245a。ok / not-ok / skipped — monitor 語彙の
  skipped は EventOutcome の skipped-no-result とは別。webui/state.py は outcome を
  authoritative に利用、run_csmgrstatus は full CommandResult を返す。Monitor.stop の残余問題と
  webui の ccninfo 非表示は [20](tickets/20-deferred-ccninfo-monitoring-gaps.md) に分離、95f175a で再確認）
- B1 validate_merged_args present-but-empty structured config（73ca40b。
  残課題 `failure_scenarios: "none"` は [17](tickets/17-r8-failure-policy.md) へ）
- B3 validate_merged_args scalar explicit-null（d2680b1）
- B2 failure_manager cycle-mode host 恒久除外（7716a93）
- S5 flap descriptor 検証の単一化（7a545f8, 2026-08-25、[02](tickets/02-s5-validate-flap-descriptor.md)。
  `_validate_flap_descriptor` へ抽出し重複診断を解消、R8 前のゼロ値・simple/cycles 非対称契約は維持。
  duration/interval >= 1 の tightening は R8 [17](tickets/17-r8-failure-policy.md) の scope）
- 候補6 result_detect → Verdict 吸収は **撤回**（2026-09-02, 95f175a、
  [16](tickets/16-kouho6-result-detect-into-verdict.md)）: core/verdict.py の pure 契約
  (no Mininet, no file IO) に反する。result_detect.py は runtime adapter として維持
- S6 bridge_external の fail-open（returncode None → 0、timed_out/cancelled 無視）は修正済み
  （2026-09-02, 420ef1e、`_fail_closed_rc` で rc=-1）。runner seam 本体
  [03](tickets/03-s6-bridge-external-runner-seam.md) は未着手のまま open
- monitoring.interval の inf/nan は validator isfinite + Monitor ctor guard で拒否
  （2026-09-02, 3c30cd0、[20](tickets/20-deferred-ccninfo-monitoring-gaps.md) の 1 項目）
- ccninfo monitor の outcome が returncode/cancelled を反映（2026-09-02, 9740a80、
  event 側 from_runtime_ccninfo と基準一致。[20](tickets/20-deferred-ccninfo-monitoring-gaps.md) の 1 項目）
- 利用者向け `host` を整数からノード名へ変える破壊的変更は **見送り**（2026-09-17）。
  番号と名前が 1 対 1 で表現力が増えず、既存 config と archived run の読み手が使えなくなるため。
  変換箇所の集約は [23](tickets/23-host-node-name-helper.md) に着手条件付きで残す

## Fog

- [22](tickets/22-application-adapter-api.md) Adapter API は概念段階。形が決まるまで
  [21](tickets/21-recefore-rename-implementation.md) の改称実装とは切り離す
