# Orchestration ワークフロー実例

---

## Workflow A — 並列探索（Research）

**目的**: 実装前に複数のエージェントに並行してコードベースを調査させ、知見を集約する。

**例**: `apply_fib` の全呼び出し元を把握してからシグネチャを変更したい。

### 手順

**1. ロスター確認**

```bash
~/.agents/skills/agmsg/scripts/team.sh cefore-emu
```

`claude-explorer` が未登録なら spawn。`codex-explorer` も同様。

**2. 両エクスプローラーに同一ターンで並列送信**

```bash
~/.agents/skills/agmsg/scripts/send.sh cefore-emu claude-main claude-explorer \
  '[REQ id=research-fib-20260622 task=explore] Find all callers of apply_fib in src/. List file:line with 1-line context each. Also note the signature of apply_fib itself.'

~/.agents/skills/agmsg/scripts/send.sh cefore-emu claude-main codex-explorer \
  '[REQ id=research-fib-20260622 task=explore] Same goal: list all call sites of apply_fib in src/ with file:line. Also check if any test files import or call it.'
```

**3. 受信（Monitor ストリーム監視）**

Monitor に届く行の例:
```
2026-06-22T10:03:12Z | cefore-emu | claude-explorer → claude-main | [RESULT id=research-fib-20260622 status=done] 4 callers: src/core/fib.py:87, src/runtime/net_config.py:124, src/scenarios/mesh.py:203, src/scenarios/disaster.py:318. Signature: apply_fib(net, fib_entries, hosts)
2026-06-22T10:05:44Z | cefore-emu | codex-explorer → claude-main | [RESULT id=research-fib-20260622 status=done] 4 callers confirmed. Tests: tests/test_fib.py:55 calls apply_fib directly with mock net.
```

**4. 合成**

両エージェントの知見をマージし、変更影響範囲を確定してから実装方針を決定する。

---

## Workflow B — codex-main への実装委任

**目的**: 大きなリファクタリングや新機能実装を codex-main の 100%-confidence ループで行う。

**例**: `DaemonFleet.stop()` が複数ノードの失敗を集約して `CollectedStopError` を raise するよう変更。

### 手順

**1. ローカル事前チェック**

```bash
# タイプエラーなしを確認してから委任
/typecheck src/runtime/daemon_fleet.py
```

**2. コンテキストリッチな REQ を codex-main に送信**

```bash
~/.agents/skills/agmsg/scripts/send.sh cefore-emu claude-main codex-main \
  '[REQ id=impl-fleet-stop-20260622 task=implement] Refactor DaemonFleet.stop() in src/runtime/daemon_fleet.py to collect all node stop-failures and raise CollectedStopError(failed_nodes). CollectedStopError should be defined in same file. Interface: build_fleet(...) signature unchanged. Callers: only disaster.py:318 and mesh.py:203 catch StopError — update them too. Keep all type hints. Run 100%-confidence loop (gpt-5.5 reasoning high) before writing. Reply [RESULT ...] when done.'
```

**3. 非同期待機**

codex は Stop-hook でポーリングするため返信まで数分かかる。
その間、他のタスク（ドキュメント更新、ユーザーとの会話等）を進める。

**4. RESULT 受信後のゲートチェック**

```
2026-06-22T10:23:11Z | cefore-emu | codex-main → claude-main | [RESULT id=impl-fleet-stop-20260622 status=done] CollectedStopError added. DaemonFleet.stop() now collects failures. disaster.py and mesh.py updated. All existing tests pass.
```

```bash
# ゲート: テストスイートを実行して codex の主張を検証
/cefore-run-tests
```

**5. codex-review への送信（登録済みの場合）**

```bash
~/.agents/skills/agmsg/scripts/send.sh cefore-emu claude-main codex-review \
  '[REQ id=review-fleet-stop-20260622 task=review] Review the DaemonFleet.stop() refactor on branch feature/seam. Focus: CollectedStopError aggregation correctness, exception handling in callers, type safety. Tests: all pass (cefore-run-tests green). Reply [RESULT ...] with findings.'
```

---

## Workflow C — フルパイプライン（Research → Implement → Test → Review）

**目的**: 新機能追加のフルサイクルをチーム全体で回す。

**例**: monitoring.py に新しいメトリクスタイプ `link_quality` のサポートを追加。

### 手順

**1. ロスター確認 + 必要に応じてスポーン**

```bash
~/.agents/skills/agmsg/scripts/team.sh cefore-emu
# claude-explorer, codex-main, codex-review が未登録なら spawn
```

**2. Phase 1: 並列探索**

同一ターンで explorer 2 名に送信:

```bash
~/.agents/skills/agmsg/scripts/send.sh cefore-emu claude-main claude-explorer \
  '[REQ id=research-linkq-20260622 task=explore] Explore src/runtime/monitoring.py. List all supported metric types, how targets are dispatched, and the output schema for monitor.json.'

~/.agents/skills/agmsg/scripts/send.sh cefore-emu claude-main codex-explorer \
  '[REQ id=research-linkq-20260622 task=explore] In src/runtime/monitoring.py, find where new metric types would be added. Also check config/examples/ for monitoring YAML examples.'
```

**3. Phase 1: 知見受信・合成**

両 RESULT を受信後、実装ブリーフを作成する（claude-main がまとめる）。

**4. Phase 2: codex-main 実装委任**

```bash
~/.agents/skills/agmsg/scripts/send.sh cefore-emu claude-main codex-main \
  '[REQ id=impl-linkq-20260622 task=implement] Add link_quality metric type to src/runtime/monitoring.py. Based on research: metrics are dispatched in _collect_metrics() at line ~85. New type reads cefstatus output and extracts loss rate per link. Output schema: {"type":"link_quality","host":N,"loss_rate":0.0-1.0}. Add to MonitoringConfig.targets validation. Write unit test in tests/. Run 100%-confidence loop. Reply [RESULT ...] when done.'
```

**5. Phase 2: ゲートチェック**

```bash
/cefore-run-tests   # テスト全件 green を確認
/typecheck src/runtime/monitoring.py
```

**6. Phase 3: codex-review へ送信**

```bash
~/.agents/skills/agmsg/scripts/send.sh cefore-emu claude-main codex-review \
  '[REQ id=review-linkq-20260622 task=review] Review link_quality metric addition in src/runtime/monitoring.py on branch feature/seam. Concerns: dispatch correctness, output schema completeness, edge cases (no cefstatus output). Tests: all pass. Reply [RESULT ...] with findings.'
```

**7. レビュー結果をユーザーに提示**

RESULT 受信後、レビュー所見と対応方針をユーザーに提示して判断を仰ぐ。

---

## Workflow D — QUERY への応答（補足情報提供）

codex-main が実装中に情報不足で詰まった場合:

```
[QUERY id=impl-linkq-20260622] Where is cefstatus output format documented? Is loss rate already parsed anywhere in the codebase?
```

claude-main は追加情報を送信:

```bash
~/.agents/skills/agmsg/scripts/send.sh cefore-emu claude-main codex-main \
  '[REQ id=impl-linkq-20260622 task=clarify] cefstatus format: see src/runtime/cefore.py run_cefstatus(). Loss rate not yet parsed — you need to extract it from raw text. Format example: "Loss rate: 0.02 (2/100 pkts)".'
```

---

## 降格戦略（spawn できない場合）

| 本来のロール | 代替手段 |
|---|---|
| claude-explorer | `Agent(subagent_type="Explore", ...)` |
| codex-explorer | `Agent(subagent_type="Explore", ...)` |
| codex-main (単発) | `/codex:rescue` |
| codex-review | `Agent(subagent_type="code-reviewer", ...)` または `/review` |
