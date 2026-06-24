---
name: orchestration
description: |
  Orchestrate the cefore-emu team (codex-main, codex-review, claude-explorer,
  codex-explorer) for complex tasks using agmsg. Trigger when you need to delegate
  heavy implementation to codex-main, request a code review via codex-review,
  fan out parallel research to explorers, or run a full research→implement→review
  pipeline. Also trigger on: "delegate to codex", "ask codex-main", "have the
  explorers check", "orchestrate the team", "send to review".
---

# Orchestration — cefore-emu チーム調整スキル

このスキルは claude-main（リード）が他エージェントに仕事を委任する「いつ・誰に・どう」を定める。
agmsg の基礎操作（send/inbox/join の構文）は `/agmsg` スキルに委ねる。

---

## 1. いつ委任するか（3 択判断テーブル）

| 状況 | 手段 |
|------|------|
| セッション内クイックタスク（ファイル検索・1 回限りの解析） | Agent ツール subagent（haiku / sonnet） |
| 単発 Codex 調査・診断（長いセッション不要） | `/codex:rescue`（セッション内 Codex MCP） |
| 重実装・100%-confidence ループが必要 | agmsg → **codex-main** |
| GUIの整備，軽い実装のレビュー | agmsg → **gemini-main** |
| ブランチ / PR のコードレビュー | agmsg → **codex-review** |
| 並列コードベース探索 | agmsg → **claude-explorer** + **codex-explorer** |
| 探索→実装→テスト→レビューのフルパイプライン | agmsg マルチエージェント調整 |

**判断の鍵**: agmsg を使うのは「大きい・時間がかかる・コンテキスト 1 窓では足りない」仕事。
それ以外は Agent ツールで済ませた方が速い。

---

## 2. チームのロール定義

| エージェント名 | タイプ | 責務 |
|---|---|---|
| **claude-main** | claude-code (リード) | 統括・ユーザー窓口・最終判断 |
| **codex-main** | codex (アドバイザー) | 重実装・100%-confidence ループ（model: gpt-5.5, reasoning high） |
| **gemini-main** | antigravityCLI (アドバイザー) | 軽実装/GUIの整備 |
| **codex-review** | codex (レビュアー) | コードレビュー・品質チェック |
| **claude-explorer** | claude-code (sonnet) | 読み取り専用のコードベース探索 |
| **codex-explorer** | codex | 読み取り専用のコードベース探索 |


チーム名: `cefore-emu` / プロジェクト: `/home/lab_shared/cefore-emu-sslab`

---

## 3. 委任フローの基本ステップ

### ステップ A — ロスター確認（必ず最初にやること）

```bash
~/.agents/skills/agmsg/scripts/team.sh cefore-emu
```

登録済みエージェントを確認する。**登録 = 起動済みとは限らない**が、
送信先が登録されていれば次回 Stop-hook または Monitor でメッセージを受け取る。

- **登録あり** → そのまま送信
- **登録なし** → スポーンするか、代替手段（Agent ツール / `/codex:rescue` / `codex mcp` ）に降格

### ステップ B — スポーン（必要な場合）

```bash
# claude-code エージェント（ブロッキング、ready まで待機）
~/.agents/skills/agmsg/scripts/spawn.sh claude-code claude-explorer \
  --project /home/lab_shared/cefore-emu-sslab --team cefore-emu

# codex エージェント（ノンブロッキング、--no-wait）
~/.agents/skills/agmsg/scripts/spawn.sh codex codex-main \
  --project /home/lab_shared/cefore-emu-sslab --team cefore-emu --no-wait
```

tmux が使えない / ヘッドレス環境では spawn.sh が失敗する場合がある。
その場合は降格戦略（Agent ツール or `/codex:rescue`）を使う。

### ステップ C — 送信

```bash
~/.agents/skills/agmsg/scripts/send.sh cefore-emu claude-main <to_agent> \
  '[REQ id=<correlation-id> task=<type>] <1行の指示>'
```

メッセージ書式の完全仕様は `references/protocol.md` を参照。

### ステップ D — 受信

- **claude-code エージェント（claude-explorer 等）**: Monitor ツールが watch.sh ストリームを
  受信中（SessionStart フックで起動済み）。`<ts> | cefore-emu | <from> → claude-main | ...`
  の行が届いたら処理する。
- **codex エージェント（codex-main 等）**: Stop-hook で非同期ポーリング。返信まで数分かかる。
  ブロックせず他の作業を続け、Monitor に届いた agmsg 行を確認する。

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

完全文法は `references/protocol.md`、実例は `references/workflows.md` 参照。

---

## 5. 既存スキルとの連携

| スキル | タイミング |
|--------|-----------|
| `/cefore-run-tests` | codex-main 実装完了後 → codex-review 送信前のゲート |
| `/typecheck` | codex-review 送信前のローカルゲート |
| `/codex:rescue` | 単発調査（agmsg セッション不要な場合） |
| `/review` | Agent ツール並列レビュー（軽量・セッション内） |

---

## 6. ワークフロースケッチ

詳細な手順・完全メッセージ body は `references/workflows.md` を参照。

### A. 並列探索（Research）

1. `team.sh` でロスター確認
2. `send.sh` を同一ターンで 2 回呼び出し（explorer 2 名に同時送信）
3. Monitor でそれぞれの RESULT を受信
4. 知見を合成して次のアクションを決定

### B. codex-main への実装委任

1. `/typecheck` ローカル実行
2. コンテキスト埋め込み REQ を codex-main に送信（100%-confidence ループ指示込み）
3. 返信を待つ間、他作業を進める（codex は非同期）
4. RESULT 受信 → `/cefore-run-tests` → codex-review（登録済みなら）

### C. フルパイプライン

探索 → 知見合成 → codex-main 実装 → テスト → codex-review → ユーザーへ提示
