---
name: orchestration
description: |
  Orchestrate the cefore-emu team (codex-main, opencode, hermes, gemini-main)
  for complex tasks using agmsg. codex-main is the single codex context — pick a
  mode with task=explore|implement|review inside the REQ instead of routing to
  separate agents. Trigger when you need to delegate heavy implementation or
  long-running exploration to codex-main, request an independent second review
  via opencode, or run a full research→implement→review pipeline. Also trigger
  on: "delegate to codex", "ask codex-main", "second review via opencode",
  "ask hermes", "orchestrate the team", "send to review".
---

# Orchestration — cefore-emu チーム調整スキル

このスキルは claude-main（リード）が他エージェントに仕事を委任する「いつ・誰に・どう」を定める。
agmsg の基礎操作（send/inbox/join の構文）は `/agmsg` スキルに委ねる。

---

## 1. いつ委任するか（判断テーブル）

| 状況 | 手段 |
|------|------|
| セッション内クイックタスク（ファイル検索・1 回限りの解析） | Agent ツール subagent（haiku / sonnet） |
| 単発 Codex 調査・診断（長いセッション不要） | `/codex:rescue`（セッション内 Codex MCP） |
| 重実装・100%-confidence ループが必要 | agmsg → **codex-main** `task=implement` |
| 長時間・広域のコードベース探索 | agmsg → **codex-main** `task=explore`（codex 内部で subagent 並列化）/ **hermes**（手動運用） |
| ブランチ / PR のコードレビュー | agmsg → **codex-main** `task=review`（自己チェック）＋ **opencode**（独立レビュー） |
| GUI の整備・軽い実装 | agmsg → **gemini-main**（※現状未配線 — §3 ステップ D 参照） |
| 探索→実装→テスト→レビューのフルパイプライン | agmsg マルチエージェント調整 |

**判断の鍵**: agmsg を使うのは「大きい・時間がかかる・コンテキスト 1 窓では足りない」仕事。
それ以外は Agent ツールで済ませた方が速い。

---

## 2. チームのロール定義

| エージェント名 | タイプ | 責務 |
|---|---|---|
| **claude-main** | claude-code (リード) | 統括・ユーザー窓口・最終判断 |
| **codex-main** | codex (アドバイザー) | 探索 / 実装 / レビューを `task=` で切り替える**単一コンテキスト**（gpt-5.6-sol / reasoning high 想定だが、これは運用者設定であって spawn は強制しない） |
| **opencode** | opencode | **独立**第二レビュー（2026-07-26 から外部レビュアーとして運用） |
| **hermes** | hermes | 探索寄り（ハーネス側の長期記憶が強み）。**手動運用** — 自動配送なし |
| **gemini-main** | antigravity | 軽実装・GUI の整備。**現状未配線**（送っても届かない） |

チーム名: `cefore-emu` / プロジェクト: `/home/lab_shared/cefore-emu-sslab`

**上表はロールの既定値であって固定割り当てではない。**
「迷ったらここに投げる」の目安として使い、タスクの性質で読み替えてよい。

### なぜ codex 系を単一コンテキストにまとめたか

codex は native subagent 機能を持ち、モデルも自分で判断して選ぶ。
以前は codex-review / codex-explorer を別エージェントとして分けていたが、
探索もレビューも codex 側で内部並列化できるため、分割の利点が context 分離だけになった。
逆に単一コンテキストなら **探索 → 実装 の知見引き継ぎに再説明が要らない**。
よって送り先を分けず、REQ の `task=` でモードを指定する。

### 独立性の原則（重要）

**codex-main 自身が書いたコードに対する `task=review` は自己チェックであって、独立レビューではない。**
実装期のコンテキストがそのまま残っているため、「なぜそう書いたか」の記憶が
レビューの目を曇らせる。実装と同一コンテキストにレビューを任せきりにしないこと。

**統合で本当に失われたのは、探索能力ではなく「実装者の思考を見ていない新鮮な codex コンテキスト」**である。
旧 codex-review はそれを提供していた。この代償として:

- 独立ゲートは実質 **opencode 1 本**（単一障害点）。opencode が落ちていれば独立性は担保されない
- 降格先の `/review` / code-reviewer subagent は **claude-main のハーネス内**で動くため、
  claude-main の判断からは独立していない。「別のモデルに見せた」とは言えるが
  「独立した第三者に見せた」とは言えない
- **高リスクな変更では、codex-main を再利用せず新しい codex コンテキストを立てて
  `task=review` を投げる**。これが旧 codex-review の代替になる。
  ただし `--fresh` と一意なロール名が必須（付けないと前セッションが復帰して
  独立性が出ず、identity 衝突で他人の inbox を読む恐れもある。`references/protocol.md` 参照）

低リスクなら opencode 1 本で十分。リスクに応じてゲートの層を選ぶこと。

**2026-08-05 の実例（この節が存在する理由）**: codex-main がこのスキルをレビューした際、
所見の末尾に「2 名の独立したレビュアーが同じ結論に達した」と書いてきた。
実体は**同じ codex ハーネス内で走らせた並列 subagent 2 体**で、
agmsg の RESULT を返してもおらず、外部の独立ゲートではなかった。
指摘したところ本人も撤回している。

つまり **「複数体が同意した」と「独立に検証された」は別物**であり、
その取り違えは注意深いレビュアーにも起きる。
ゲートの成立は「同意の数」ではなく「**別ハーネスから RESULT が返ったこと**」で判定する。
自分の内部 subagent 群の一致を独立性の根拠にしないこと（claude-main 自身も同じ罠を踏みうる）。

**ゲートは「送ったら成立する」ものではない。** レビュアーがアイドルのままだと
依頼は inbox に滞留し続ける。ゲートとして扱う前に、相手が実際にターンを回したか
（＝ RESULT が返ったか）を確認すること。無反応をレビュー通過と読み替えない。

### 将来候補

`pi`（`~/.npm/bin/pi`, @earendil-works/pi-coding-agent）はインストール済みだが、
agmsg の driver type が未対応のため未登録。
`~/.agents/skills/agmsg/scripts/drivers/types/pi/type.conf` が用意されれば `join.sh` できる。

---

## 3. 委任フローの基本ステップ

### ステップ A — ロスター確認（必ず最初にやること）

```bash
~/.agents/skills/agmsg/scripts/team.sh cefore-emu
```

登録済みエージェントを確認する。
**登録は「送れる」ことしか意味しない。届くかどうかは配送機構次第**（§3 ステップ D の表）。
hermes は自動配送が無く、gemini-main は未配線なので、登録済みでも放っておいて届くことはない。

`team.sh` は登録しか見ない。実際に生きているかは別に確かめる:

```bash
tmux list-panes -a -F '#{session_name} #{pane_id} #{pane_current_command}'
pgrep -a -f 'codex|opencode|hermes'
```

**`delivery.sh status` を生存確認に使わないこと。**
あれが答えるのは「配送ランタイムの状態」であって「相手が生きているか」ではない。
watch プロセス数は project/type/session で絞られていない全体値だし、
codex については CLI 本体ではなく bridge の状態を報告する
（実際、bridge が not running でも codex-main は応答する）。
配送側の設定確認には有用だが、相手の生死は tmux / プロセスで見ること。

spawn.sh は起動前にロスターへ登録するため、**起動に失敗すると
「登録されているのに存在しない」幽霊エントリが残る**。
ロスターに見覚えのない名前があったら、実体を確認してから使うこと
（不要と分かったら `leave.sh`、特定 project の登録だけなら `reset.sh`）。

### ステップ B — 依頼の届け方を相手の状態で決める

**これがこのスキルで一番間違えやすいところ。**
分岐は「相手が起きているか」ではなく「**実際に動いている配送ランタイムは何か**」で決まる:

| 相手の状態 / 配送 | やること |
|---|---|
| **不在**（未登録 / プロセスが無い） | spawnable なら `spawn.sh --boot-prompt '<依頼>'` |
| **monitor / bridge が実際に稼働中** | `send.sh` だけでよい（**待機中でも届く**） |
| **turn（または monitor の fallback）で待機中** | **① `send.sh` で先にキューへ入れる → ② 対話的に inbox チェックを走らせる**。順序を逆にしない |
| **turn でターンを回している** | `send.sh` |
| 意図的に置き換えたい | placement 記録があれば `despawn.sh` → spawn。記録が無い（OS 端末起動）なら手でプロセス/ウィンドウを閉じ、`reset.sh` で登録を外してから spawn |

**「起こしてから送る」をやらない。** `check-inbox.sh` は起動時に未読行を 1 回 SELECT するだけで、
待ち受けない。先に起こすと、フックが走り終わった後にメッセージが入ることになり、
**相手はそのまま待機に戻る**。必ず「送ってから起こす」。

「monitor が設定されている」ではなく「**monitor が実際に走っている**」かで判断すること
（設定と稼働は別物。§ステップ D 参照）。

```bash
# 不在のとき — 最初の依頼を --boot-prompt に載せる
~/.agents/skills/agmsg/scripts/spawn.sh codex codex-main \
  --project /home/lab_shared/cefore-emu-sslab --team cefore-emu --no-wait \
  --boot-prompt '[REQ id=... task=explore] ...'

# opencode（tmux 内なら新ペイン、外なら端末を開く。turn モードでは --no-wait 必須）
~/.agents/skills/agmsg/scripts/spawn.sh opencode opencode \
  --project /home/lab_shared/cefore-emu-sslab --team cefore-emu --no-wait \
  --boot-prompt '[REQ id=... task=review] ...'
```

**待機中の相手を spawn し直さない。**
codex の actas は seat を記録するだけで排他ロックを取らないため、
同名 spawn は既存を起こさず**同じロールの TUI を二重に立て**、
placement 記録を上書きして元のペインを despawn 不能にする。
`--fresh` を付けても防げない（あれは resume 対象を変えるだけ）。

登録があっても、この表を飛ばして送信に進まないこと。
**登録は「送れる」であって「届く」ではない。**
どうしても起こせない場合は代替手段（Agent ツール / `/codex:rescue`）に降格する。

**hermes は spawn できない。** driver に `spawnable` が無い — hermes CLI に
「初期プロンプトを与えて対話セッションを開始する」呼び出し方が存在しないため。
既に起動しているプロセスへ send.sh で送るだけにする。

tmux が使えない / ヘッドレス環境では spawn.sh が失敗する場合がある。
その場合は降格戦略（Agent ツール or `/codex:rescue`）を使う。

### ステップ C — 送信

```bash
~/.agents/skills/agmsg/scripts/send.sh cefore-emu claude-main <to_agent> \
  '[REQ id=<correlation-id> task=<type>] <1行の指示>'
```

メッセージ書式の完全仕様は `references/protocol.md` を参照。

### ステップ D — 受信

エージェントごとに配送機構が違う。**同じ待ち方をしないこと。**

| 宛先 | 配送機構 | 待ち方 |
|---|---|---|
| claude-code エージェント | SessionStart は Monitor 起動を**指示するだけ**。実際に Monitor が走っていて初めて届く | 走っていれば自動で会話に届く |
| **codex-main** | turn: Stop フック / monitor: 常駐 bridge | turn かつ待機中は**届かない**。無反応は「遅い」でなく「トリガ未発火」を疑う |
| **opencode** | turn: PostToolUse / monitor: 常駐（`sentinel_monitor` 不在時は PostToolUse に fallback） | ツールを呼んでいる間は速い。待機中は届かない |
| **hermes** | **なし**（`delivery_modes=off`） | inbox に滞留する。hermes 側が手動で見るまで返信は来ない |
| **gemini-main** | 現状**未配線**（`.agent/rules/agmsg.md` 未設置） | 使う前に配線が要る（`references/protocol.md` 参照） |

**「設定されている」と「走っている」は違う。**
monitor 設定でも watcher が起動していなければ届かないし、
opencode は monitor 設定でも sentinel が無ければ実質 turn として振る舞う。
判断は**実際に動いている配送ランタイム**に対して行うこと。

現在どのモードで動いているかは設定次第で、upstream 更新でも変わる。
表を信じる前に現物を見ること:

```bash
~/.agents/skills/agmsg/scripts/delivery.sh status <type> /home/lab_shared/cefore-emu-sslab
```

いずれの場合も、**宛先プロセスが起動していなければ返信は来ない**。
そして turn モードでは**起動していても待機中なら届かない**。
無反応が続くときは「壊れている」と判断する前に、相手が起きてターンを回しているかを確認する。

---

## 4. メッセージ書式（概要）

送信:
```
[REQ id=<correlation-id> task=<type>] <1 行の指示（コンテキスト含む）>
```

受信期待値:
```
[RESULT id=<correlation-id> status=done|blocked|error] <サマリー>
```

**codex-main への依頼には必ずコンテキストを埋め込む**。
codex は会話履歴を持たないため、ファイルパス・制約・期待インターフェースを
1 メッセージ内に完結させる必要がある。
ただし**同一コンテキストへの 2 通目以降は前段の知見を引き継げる**ので、
探索 → 実装と繋ぐ場合は調査結果を再送しなくてよい。

### 単一コンテキストの運用規律（重要）

宛先を 1 本に絞った代償として、以下を守らないと引き継ぎが壊れる。

- **未応答の REQ を残したまま次を送らない。** codex-main は 1 回の inbox 読みで
  溜まった複数 REQ をまとめて受け取る。並行依頼は混線し、どちらの id への
  RESULT かも曖昧になる。**in-flight は常に 1 通**にする。
  独立した 2 件を同時に走らせたいなら、片方は Agent ツール subagent に出す。
- **引き継ぎは「たいてい」効くが保証ではない。** spawn.sh は既定で直前セッションを
  resume するため再起動しても普通は文脈が残る。ただし `--fresh` 指定や
  セッション記録の欠落・陳腐化では静かに fresh 起動になり、
  **相手はそれを申告しない**。2 通目以降は「前段の要点を 1 行で再掲 + それを踏まえて」
  の形にして（全文再送は不要）、RESULT が前提を取り違えていないかを確認する。

完全文法は `references/protocol.md`、実例は `references/workflows.md` 参照。

---

## 5. 既存スキルとの連携

| スキル | タイミング |
|--------|-----------|
| `/cefore-run-tests` | codex-main 実装完了後 → レビュー送信前のゲート |
| `/typecheck` | レビュー送信前のローカルゲート |
| `/codex:rescue` | 単発調査（agmsg セッション不要な場合） |
| `/review` | Agent ツール並列レビュー（軽量・セッション内） |

---

## 6. ワークフロースケッチ

詳細な手順・完全メッセージ body は `references/workflows.md` を参照。

### A. 探索（Research）

1. `team.sh` でロスター確認
2. codex-main へ `task=explore` の REQ を 1 通（並列化は codex 内部の subagent に任せる）
3. 別視点が欲しければ hermes にも送る（返信は非同期・手動なので当てにしない）
4. 知見を合成して次のアクションを決定

### B. codex-main への実装委任

1. `/typecheck` ローカル実行
2. コンテキスト埋め込み REQ を codex-main に送信（100%-confidence ループ指示込み）
3. 返信を待つ間、他作業を進める（codex は非同期）
4. RESULT 受信 → `/cefore-run-tests` → codex-main `task=review`（自己チェック）→ opencode（独立レビュー）

### C. フルパイプライン

探索 → 知見合成 → codex-main 実装 → テスト → 自己レビュー → **opencode 独立レビュー** → ユーザーへ提示

探索・実装・レビューはいずれも同じ codex-main に順次送る（id はフェーズごとに変える）。
独立性を担保する最後のゲートだけ opencode に出す。
