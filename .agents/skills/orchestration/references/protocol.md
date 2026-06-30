# agmsg Protocol Reference — cefore-emu チーム

## 定数

```
TEAM=cefore-emu
PROJECT=/home/lab_shared/cefore-emu-sslab
SCRIPTS=~/.agents/skills/agmsg/scripts
```

---

## スクリプト引数一覧

```bash
# 送信
$SCRIPTS/send.sh <team> <from> <to> "<body>"

# 受信（未読を全件表示して既読にする）
$SCRIPTS/inbox.sh <team> <agent>

# チームメンバー確認
$SCRIPTS/team.sh <team>

# スポーン（claude-code: ブロッキング, codex: --no-wait）
$SCRIPTS/spawn.sh <type> <name> --project <path> --team <team> [--no-wait]

# デスポーン（codex は --force）
$SCRIPTS/despawn.sh <team> <name> [--force]
```

### body のクォートルール

body は **1 行のみ**（watch.sh が改行を `\n` エスケープするため、多段構造には不向き）。
シェルでシングルクォートを含める場合: `'text '\''escaped'\'' text'`

```bash
# 正: 1 行、シングルクォート囲み
send.sh cefore-emu claude-main codex-main \
  '[REQ id=impl-fib-20260622 task=implement] Refactor apply_fib in src/core/fib.py: ...'

# 誤: 複数行（改行が \n に変換される）
```

---

## メッセージヘッダー文法

全メッセージ先頭を `[<TYPE> id=<id> ...]` で始める。

| タイプ | 方向 | 意味 |
|--------|------|------|
| `REQ` | claude-main → 他 | タスク依頼 |
| `RESULT` | 他 → claude-main | タスク完了（成否含む） |
| `STATUS` | 他 → claude-main | 進捗中間報告 |
| `QUERY` | 他 → claude-main | タスク中の質問 |

### REQ フォーマット

```
[REQ id=<id> task=<type>] <指示本文（コンテキスト含む1行）>
```

`task` の値（慣習）:

| 値 | 用途 |
|----|------|
| `explore` | ファイル検索・シンボル探索 |
| `implement` | コード実装・リファクタリング |
| `review` | コードレビュー |
| `ping` | 疎通確認 |

### RESULT フォーマット

```
[RESULT id=<id> status=done|blocked|error] <1行サマリー>
```

blocked = 追加情報が必要。error = 実行失敗。
claude-main は `blocked` を受け取ったら `[QUERY id=<id>]` で情報を補足する。

---

## Correlation ID 命名規則

`<action>-<yyyymmdd>` 形式で claude-main が採番する。

```
impl-fleet-stop-20260622
research-fib-20260622
review-seam-pr-20260622
```

同日に同種タスクが複数ある場合は末尾に `-N` を付ける（例: `research-fib-20260622-2`）。

---

## 受信ループ

### claude-code エージェント（claude-explorer 等）

SessionStart フックが watch.sh を Monitor として起動済み。
agmsg メッセージは以下の形式で自動的に会話に届く:

```
<ts> | cefore-emu | claude-explorer → claude-main | [RESULT id=... status=done] ...
```

特別な操作は不要。Monitor の通知を待てばよい。

### codex エージェント（codex-main, codex-review, codex-explorer）

codex は Monitor ツールを持たず、Stop-hook（各ターン終了時）でポーリングする。
返信まで **数分〜10 分程度**かかる場合がある。

claude-main 側での待機方法:
1. REQ を送信後、他の作業を続ける（ブロックしない）
2. Monitor に agmsg の行が届いたら確認する
3. 5 分経っても RESULT がなければ `inbox.sh cefore-emu claude-main` で手動確認

---

## エージェントのライフサイクル

### スポーン

```bash
# claude-code（tmux 新ペイン、ready sentinel まで最大 90 秒ブロック）
~/.agents/skills/agmsg/scripts/spawn.sh claude-code claude-explorer \
  --project /home/lab_shared/cefore-emu-sslab --team cefore-emu

# codex（バックグラウンド、ブロックしない）
~/.agents/skills/agmsg/scripts/spawn.sh codex codex-main \
  --project /home/lab_shared/cefore-emu-sslab --team cefore-emu --no-wait
```

スポーン失敗（tmux なし / 権限なし）の場合:
- claude-code ロール → Agent ツール subagent（sonnet）で代替
- codex ロール → `/codex:rescue` で代替

### デスポーン

```bash
# claude-code: ctrl:despawn を送信（graceful shutdown）
~/.agents/skills/agmsg/scripts/despawn.sh cefore-emu claude-explorer

# codex: 強制終了
~/.agents/skills/agmsg/scripts/despawn.sh cefore-emu codex-main --force
```

---

## codex-main への依頼注意事項

codex-main は gpt-5.5 / reasoning high / summaries auto を使用する（CLAUDE.md に記載）。
依頼メッセージには以下を必ず含める:

1. **対象ファイルパス**（`src/runtime/daemon_fleet.py` など）
2. **変更前後の期待インターフェース**
3. **制約**（既存テストを壊さない、型ヒントを維持する等）
4. **100%-confidence ループの指示**（実装前に不明点を解消してから書くよう明示）

例:
```
[REQ id=impl-fleet-20260622 task=implement] Refactor DaemonFleet.stop() in
src/runtime/daemon_fleet.py to raise CollectedStopError aggregating all failed
nodes. Interface: build_fleet(...) stays unchanged. Constraints: keep type hints,
do not break existing pytest. Run 100%-confidence loop before writing code.
Reply [RESULT ...] when done and tests pass.
```
