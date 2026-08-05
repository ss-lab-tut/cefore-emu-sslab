# Orchestration ワークフロー実例

---

## 委任の基本形 — 単一コンテキストへの段階 REQ

cefore-emu の codex 系は **codex-main 1 体**に集約されている。
探索・実装・レビューは宛先を変えるのではなく、同じ codex-main に
`task=explore` → `task=implement` → `task=review` と順に送る。

**利点**: 2 通目以降は前段の調査結果を再送しなくてよい。
codex は会話履歴を持たないため初回はコンテキストを full に埋め込む必要があるが、
**同一コンテキストへの継続 REQ では引き継ぎが効く**。

**制約 1 — 直列運用**: 未応答の REQ を残したまま次を送らない。
codex-main は 1 回の inbox 読みで複数 REQ をまとめて受け取るため、
並行依頼は 1 つの文脈に混ざる。**in-flight は常に 1 通**。

**制約 2 — 引き継ぎは「たいてい」効くが保証ではない**: spawn.sh は既定で
直前セッションを resume するので再起動しても普通は文脈が残る。ただし `--fresh` 指定や
セッション記録の欠落・陳腐化では静かに fresh 起動になり、相手はそれを申告しない。
2 通目以降は前提を 1 行だけ再掲し（全文再送は不要）、
RESULT が取り違えていないか確認する。

**制約 3 — 送信は配送トリガを起こさない**: turn モードの check-inbox は
相手が何かを終えたときにしか走らない（codex は Stop、opencode は PostToolUse）。
待機に入った相手へ次フェーズの REQ を送っても、トリガが発火しなければ届かない。
フェーズを跨ぐたびに相手の状態を確認する。沈黙を完了と読み替えない。

> **以下のワークフロー例に出てくる `send.sh` は、すべて「相手が動いている」
> ことを前提にした短縮形である。** 前フェーズの RESULT を受けてから次を送るときは、
> その間に相手が待機に入っている可能性が常にある。実行前に毎回状態を確認し、
> 待機していれば **send.sh で入れてから対話的にトリガを引く**
> （同名 spawn は二重起動になるので使わない）。
> **monitor が実際に稼働している**相手にはこの注意は当たらないが、
> 「monitor 設定」だけでは足りない — watcher が落ちていたり、
> opencode で `sentinel_monitor` が無く PostToolUse に fallback していれば同じ制約を受ける。

**制約 4 — 自己レビューの限界（重要）**: codex-main が自分で書いたコードに対する
`task=review` は**自己チェック**であって独立レビューではない。
独立性のゲートは **opencode** が担う。実装を伴うパイプラインでは、
codex-main の自己レビューだけで完了扱いにしないこと。
高リスクな変更では、さらに**新しい codex コンテキストを別に立てて** `task=review` を出す
（codex-main の再利用では独立性が出ない）。
その spawn には **`--fresh` と一意なロール名が必須**。`--fresh` を省くと前セッションが
復帰して独立性が失われ、同一プロジェクトで codex が 2 体走ると
turn モードでは identity 衝突で片方が他方の inbox を読む。

---

## Workflow A — 探索（Research）

**目的**: 実装前にコードベースを調査し、変更影響範囲を確定する。

**例**: `apply_fib` の全呼び出し元を把握してからシグネチャを変更したい。

### 手順

**1. ロスター確認**

```bash
~/.agents/skills/agmsg/scripts/team.sh cefore-emu
```

`team.sh` は登録しか見ない。**実際に動いているか**は別に確かめる:

```bash
tmux list-panes -a -F '#{session_name} #{pane_id} #{pane_current_command}'
```

届け方は**実際に動いている配送ランタイム**で決まる（正典は `SKILL.md` ステップ B の表）:
不在なら spawn + `--boot-prompt`／monitor が実稼働なら send.sh だけでよい／
turn で待機中なら **send.sh で入れてから対話的に inbox チェックを走らせる**／
turn で稼働中なら send.sh。待機中に同名 spawn し直すと二重起動になる。

**2. codex-main へ探索 REQ**

並列化は codex 内部の subagent に任せるので、送るのは 1 通でよい。
**渡し方は相手の状態で変える:**

```bash
# (a) 未登録 / 未起動の場合のみ — spawn の --boot-prompt に載せる
~/.agents/skills/agmsg/scripts/spawn.sh codex codex-main \
  --project /home/lab_shared/cefore-emu-sslab --team cefore-emu --no-wait \
  --boot-prompt '[REQ id=research-fib-20260622 task=explore] Find all callers of apply_fib ...'
```

**「起動しているが待機中」に (a) を使わない。**
codex の actas は seat を記録するだけでロールの排他ロックを取らないため、
同名で spawn し直すと**既存を起こすのではなく同じロールの TUI が二重に立ち**、
placement 記録が上書きされて元のペインを despawn できなくなる。

待機中の相手には **(b) の send.sh で先にキューへ入れてから、対話的にトリガを引く**。
順序を逆にすると、フックが走り終わった後にメッセージが入って取り残される。

意図して置き換える場合のみ、先に古いものを落としてから spawn する
（placement 記録があれば `despawn.sh`、OS 端末起動で記録が無ければ手で閉じて `reset.sh`）。

```bash
# (b) 既に起動していてターンを回している場合のみ — send.sh
~/.agents/skills/agmsg/scripts/send.sh cefore-emu claude-main codex-main \
  '[REQ id=research-fib-20260622 task=explore] Find all callers of apply_fib in src/ and tests/. List file:line with 1-line context each. Also note the signature of apply_fib itself and whether any test calls it with a mock net. Use subagents to parallelize if useful. Reply [RESULT ...] with the list.'
```

**3. 別視点が欲しい場合のみ hermes にも送る**

hermes はハーネス側の長期記憶が強く、過去の経緯を含む調査に向く。
ただし**自動配送がないため返信を当てにしない**（届いても数十分後、あるいは来ない）。

```bash
~/.agents/skills/agmsg/scripts/send.sh cefore-emu claude-main hermes \
  '[REQ id=research-fib-20260622-2 task=explore] Historical angle on apply_fib: has its signature changed before, and were there past incidents around FIB application? Reply [RESULT ...] when you next check your inbox.'
```

**4. 受信（Monitor ストリーム監視）**

Monitor に届く行の例:
```
2026-06-22T10:05:44Z | cefore-emu | codex-main → claude-main | [RESULT id=research-fib-20260622 status=done] 4 callers: src/core/fib.py:87, src/runtime/net_config.py:124, src/scenarios/mesh.py:203, src/scenarios/disaster.py:318. Signature: apply_fib(net, fib_entries, hosts). tests/test_fib.py:55 calls it directly with mock net.
```

**5. 合成**

知見をマージし、変更影響範囲を確定してから実装方針を決定する。
hermes の返信が来ていなくても先に進んでよい（後から届いたら反映する）。

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
  '[REQ id=impl-fleet-stop-20260622 task=implement] Refactor DaemonFleet.stop() in src/runtime/daemon_fleet.py to collect all node stop-failures and raise CollectedStopError(failed_nodes). CollectedStopError should be defined in same file. Interface: build_fleet(...) signature unchanged. Callers: only disaster.py:318 and mesh.py:203 catch StopError — update them too. Keep all type hints. Run 100%-confidence loop before writing. Reply [RESULT ...] when done.'
```

Workflow A から続けている場合、調査結果を再掲する必要はない
（`[REQ id=impl-fleet-stop-20260622 task=implement] Based on your earlier exploration of apply_fib callers, ...` で通じる）。

**3. 非同期待機**

turn モードの codex は Stop フックでポーリングするため返信まで数分かかる
（本プロジェクトの現行設定。monitor モードなら常駐受信）。
その間、他のタスク（ドキュメント更新、ユーザーとの会話等）を進める。

**4. RESULT 受信後のゲートチェック**

```
2026-06-22T10:23:11Z | cefore-emu | codex-main → claude-main | [RESULT id=impl-fleet-stop-20260622 status=done] CollectedStopError added. DaemonFleet.stop() now collects failures. disaster.py and mesh.py updated. All existing tests pass.
```

```bash
# ゲート: テストスイートを実行して codex の主張を検証
/cefore-run-tests
```

**5. 自己レビュー（任意）+ 独立レビュー（必須）**

まず codex-main 自身に見直させる（安価で、明らかな取りこぼしを拾える）:

```bash
~/.agents/skills/agmsg/scripts/send.sh cefore-emu claude-main codex-main \
  '[REQ id=review-fleet-stop-20260622 task=review] Self-review the DaemonFleet.stop() change you just made. Focus: CollectedStopError aggregation correctness, exception handling in the two updated callers, type safety. Report concrete findings with file:line, or state no findings.'
```

そのうえで **opencode に独立レビューを出す**。こちらが本番のゲート:

turn モードの opencode は PostToolUse で受信するので、
**待機中（ツールを呼んでいない）opencode には送っても届かない**
（monitor モードでも `sentinel_monitor` 不在時は同じ挙動にフォールバックする）。
不在なら `--boot-prompt`、既存が待機していれば send.sh で入れてから対話的にトリガを引くこと。
RESULT が返って初めてゲートを通過したと言える。

```bash
~/.agents/skills/agmsg/scripts/send.sh cefore-emu claude-main opencode \
  '[REQ id=review-fleet-stop-20260622-2 task=review] Independent review of the DaemonFleet.stop() refactor on branch feature/seam (src/runtime/daemon_fleet.py + callers in disaster.py/mesh.py). It was implemented by codex-main, so review it as an outsider. Focus: aggregation correctness, exception handling, scope creep, test adequacy. Tests currently pass (cefore-run-tests green). Report findings with file:line and severity, or state no findings.'
```

---

## Workflow C — フルパイプライン（Research → Implement → Test → Review）

**目的**: 新機能追加のフルサイクルを回す。

**例**: monitoring.py に新しいメトリクスタイプ `link_quality` のサポートを追加。

### 手順

**1. ロスター確認 + 必要に応じてスポーン**

```bash
~/.agents/skills/agmsg/scripts/team.sh cefore-emu
tmux list-panes -a -F '#{session_name} #{pane_id} #{pane_current_command}'
```

各フェーズの送信前に、そのつど相手の状態を見て届け方を選ぶ
（`SKILL.md` ステップ B の表）。以下の例は send.sh で書いてあるが、
それは**相手がターンを回している場合の形**。不在なら spawn + `--boot-prompt`、
待機中なら send.sh で入れてから対話的にトリガを引く。

**2. Phase 1: 探索**

```bash
~/.agents/skills/agmsg/scripts/send.sh cefore-emu claude-main codex-main \
  '[REQ id=research-linkq-20260622 task=explore] Explore src/runtime/monitoring.py. List all supported metric types, how targets are dispatched, the output schema for monitor.json, and where a new metric type would need to be registered. Also check config/examples/ for monitoring YAML examples. Reply [RESULT ...] with file:line references.'
```

**3. Phase 1: 知見受信・合成**

RESULT を受信後、実装ブリーフを作成する（claude-main がまとめる）。
不足があれば同じ id で追加質問してよい。

**4. Phase 2: codex-main 実装委任（同一コンテキスト）**

```bash
~/.agents/skills/agmsg/scripts/send.sh cefore-emu claude-main codex-main \
  '[REQ id=impl-linkq-20260622 task=implement] Add link_quality metric type to src/runtime/monitoring.py, using the dispatch structure you just mapped. New type reads cefstatus output and extracts loss rate per link. Output schema: {"type":"link_quality","host":N,"loss_rate":0.0-1.0}. Add to MonitoringConfig.targets validation. Write unit test in tests/. Run 100%-confidence loop. Reply [RESULT ...] when done.'
```

探索と同じコンテキストなので、調査結果の再送は不要。

**5. Phase 2: ゲートチェック**

```bash
/cefore-run-tests   # テスト全件 green を確認
/typecheck src/runtime/monitoring.py
```

**6. Phase 3: 独立レビュー（opencode）**

送信前に opencode が動いているか確認する。
**待機中なら send.sh で入れてから対話的にトリガを引く**（spawn し直さない）。不在なら `--boot-prompt` で立てる。
送っただけではゲートは進まない。

```bash
~/.agents/skills/agmsg/scripts/send.sh cefore-emu claude-main opencode \
  '[REQ id=review-linkq-20260622 task=review] Independent review of the link_quality metric addition in src/runtime/monitoring.py on branch feature/seam. Implemented by codex-main — review as an outsider. Concerns: dispatch correctness, output schema completeness, edge cases (no cefstatus output), test adequacy. Tests pass. Report findings with file:line and severity.'
```

**7. Phase 4: findings の決着（省略しない）**

レビュー所見は受け取って終わりではない。**1 件ずつ決着させる**:

| 判断 | やること |
|---|---|
| 採用 | codex-main へ `task=implement` で修正依頼（in-flight 1 通の原則を守る） |
| 不採用 | **根拠を明記して**レビュアーへ返す（`[RESPONSE id=...]`）。黙って落とさない |
| ユーザー判断 | 設計方針・commit 構成に関わるものは AskUserQuestion で聞く |

修正を入れたら **同じレビュアーへ再レビューを出して approve を取る**。
「テストが通ったから対応済み」で閉じない — 指摘した側の確認までが 1 ループ。

**8. ユーザーへ提示**

全 findings が決着し再レビューが approve された時点で、
所見と対応内容をユーザーに提示して最終判断を仰ぐ。

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

## 降格戦略（spawn できない / 相手が起動していない場合）

| 本来のロール | 代替手段 |
|---|---|
| codex-main `task=explore` | `Agent(subagent_type="Explore", ...)` |
| codex-main `task=implement` | `/codex:rescue`（単発） |
| codex-main `task=review` | `Agent(subagent_type="code-reviewer", ...)` または `/review` |
| opencode（独立レビュー） | `/review` または `Agent(subagent_type="code-reviewer", ...)` — **独立性は必ずどこかで確保する** |
| hermes（探索） | `Agent(subagent_type="Explore", ...)` |
| gemini-main | Agent ツール subagent |

**降格の判断前に、相手が起動しているかを必ず確認する。**
登録済みでもプロセスが落ちていれば返信は来ない。
無反応 = 故障ではなく、無反応 = 大抵は未起動。
