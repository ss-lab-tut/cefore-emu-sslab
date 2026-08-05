# agmsg Protocol Reference — cefore-emu チーム

## 定数

```
TEAM=cefore-emu
PROJECT=/home/lab_shared/cefore-emu-sslab
SCRIPTS=~/.agents/skills/agmsg/scripts
```

## この文書の権威範囲（先に読むこと）

agmsg は活発に更新されている。**配送機構の詳細（どの hook が発火するか、
どの type が monitor を持つか）は upstream の変更で変わる**。
実際、2026-08-01 に `monitor=no` だった opencode は翌日の更新で `monitor=yes` になった。

したがって:

- **機構の権威は常に現物**。`$SCRIPTS/drivers/types/<type>/type.conf` と
  `$SCRIPTS/delivery.sh status <type> <project>` を見る。この文書ではない
- この文書に書いてある機構の記述は **agmsg v1.1.12 系（2026-08-05 確認）時点の観測**
- 記述と現物が食い違ったら**現物が正しい**。この文書を直す

一方、**運用の原則は機構が変わっても変わらない**。そちらは信頼してよい:

- 送信は相手のターンを起こすとは限らない → 沈黙を完了・承認と読み替えない
- 登録は「送れる」ことしか意味しない → 生存は別途確かめる
- 実装したコンテキストによるレビューは自己チェックであって独立レビューではない

---

## スクリプト引数一覧

```bash
# 送信
$SCRIPTS/send.sh <team> <from> <to> "<body>"

# 受信（未読を全件表示して既読にする）
$SCRIPTS/inbox.sh <team> <agent>

# 履歴閲覧（非破壊 — 既読化しない。滞留の確認に使う）
$SCRIPTS/history.sh <team> [agent] [limit]

# チームメンバー確認
$SCRIPTS/team.sh <team>

# 登録 / 登録解除（レジストリ操作。config.json を直接編集しないこと）
$SCRIPTS/join.sh <team> <agent> <type> <project>
$SCRIPTS/leave.sh <team> <agent>                    # agent オブジェクトごと削除
$SCRIPTS/reset.sh <project> <type> <agent>          # 該当 project+type の登録だけ削除

# スポーン（claude-code: ブロッキング, codex: --no-wait）
$SCRIPTS/spawn.sh <type> <name> --project <path> --team <team> [--no-wait] \
  [--boot-prompt "<最初の依頼>"] [--fresh]

# デスポーン（<from> = 自分の agent 名が必須）
$SCRIPTS/despawn.sh <team> <from> <name> [--force] [--timeout <secs>]
```

**`despawn.sh` の `<from>` を省くと黙って壊れる。**
`despawn.sh cefore-emu codex-main --force` と書くと `codex-main` が `<from>`、
`--force` が `<name>` として解釈され、**対象を止めないまま成功扱いで返る**ことがある。
正しくは `despawn.sh cefore-emu claude-main codex-main --force`。

**`leave.sh` は agent オブジェクトを丸ごと消す。**
1 つの agent が複数 project / type に登録されている場合、その全部が消える
（チームの最後の 1 人だった場合はチームごと消える）。
特定の project の登録だけ外したいなら `reset.sh <project> <type> <agent>` を使う。

`inbox.sh` は**破壊的読み取り**（表示した未読を既読にする）。
「届いているか」を確認したいだけなら `history.sh` を使う。

`despawn.sh` は spawn 時に記録された placement を指す。
記録されるのは **tmux**（ペイン `%N` / ウィンドウ `@N` の両方）と **herdr** で、
**OS の端末エミュレータを開いて起動した場合は placement が残らない**。
その場合 `despawn.sh --force` は対象を落とせず、**ウィンドウを手で閉じるしかない**。

placement 記録は古くなっている場合もあり、`--force` が既に死んだ
（あるいは別用途に再利用された）ペインを狙う危険がある。
**レジストリから外すだけなら `leave.sh` を使い、`despawn.sh` は
自分が spawn した直後のセッションに限定する。**

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
| `RESPONSE` | claude-main → 他 | 指摘への採否回答（レビュー往復で使う） |
| `ACK` | 双方向 | 受領確認・スレッド close |

`QUERY` は**エージェント発**であってリーダーが送るものではない。
リーダー側から情報を補うときは `[REQ id=<同じ id> task=clarify]` を使う。

制御メッセージ（`ctrl:despawn` 等）はこの文法の外にある。
despawn.sh が内部で送るものなので、手で組み立てないこと。

### REQ フォーマット

```
[REQ id=<id> task=<type>] <指示本文（コンテキスト含む1行）>
```

`task` の値（慣習）:

| 値 | 用途 |
|----|------|
| `explore` | ファイル検索・シンボル探索・広域調査 |
| `implement` | コード実装・リファクタリング |
| `review` | コードレビュー |
| `clarify` | QUERY への回答・情報補足（進行中タスクへの追送） |
| `ping` | 疎通確認 |

**`task` は宛先ではなくモードを指定する。**
codex-main は単一コンテキストで 3 モードすべてを担うため、
「探索役に送る／レビュー役に送る」ではなく「同じ相手に task を変えて送る」と考える。

### RESULT フォーマット

```
[RESULT id=<id> status=done|blocked|error] <1行サマリー>
```

blocked = 追加情報が必要。error = 実行失敗。
claude-main は `blocked` を受け取ったら `[REQ id=<同じ id> task=clarify]` で情報を補足する。

---

## Correlation ID 命名規則

`<action>-<yyyymmdd>` 形式で claude-main が採番する。

```
impl-fleet-stop-20260622
research-fib-20260622
review-seam-pr-20260622
```

同日に同種タスクが複数ある場合は末尾に `-N` を付ける（例: `research-fib-20260622-2`）。

**同一コンテキスト（codex-main）へ段階的に送る場合もフェーズごとに id を変える。**
`research-linkq-20260622` → `impl-linkq-20260622` → `review-linkq-20260622` のように、
同じ話題であることは接尾辞で示し、id 自体は共有しない。
RESULT の対応付けが曖昧になるのを防ぐため。

---

## 受信ループ

配送機構はエージェントタイプごとに異なる。**待ち方を間違えると「壊れている」と誤診する。**

### claude-code エージェント

SessionStart フックは watch.sh を Monitor として起動する**よう指示を出す**だけで、
起動そのものを保証しない（エージェントが Monitor ツールを呼んで初めて成立する）。
稼働の確認と復旧:

```bash
$SCRIPTS/delivery.sh status claude-code /home/lab_shared/cefore-emu-sslab
# → "watch processes: N alive, M stale pidfiles"
```

**この N は全体の watch プロセス数で、project / type / session で絞られていない。**
0 なら確実に受信していないが、1 以上でも「このセッションの Monitor が生きている」
証明にはならない（他プロジェクトの watcher かもしれない）。
自分の Monitor が動いているかは、自分が Monitor ツールを起動したかで判断する。

成立していれば、agmsg メッセージは以下の形式で自動的に会話に届く:

```
<ts> | cefore-emu | codex-main → claude-main | [RESULT id=... status=done] ...
```

特別な操作は不要。Monitor の通知を待てばよい。

### codex エージェント（codex-main）

codex は monitor / turn / off に対応する。**設定モードで挙動がまるで違う**ので、
まず現在のモードを確認する:

```bash
$SCRIPTS/delivery.sh status codex /home/lab_shared/cefore-emu-sslab
```

- **turn モード**（本プロジェクトの現行設定）: 配送は `Stop` フックのみ。
  **相手がターンを終えたときにしか走らない**。待機に入った codex には届かない
- **monitor モード**: bridge が常駐して受信する。待機中でも届く。
  ただし role-session（seat）が記録されているロールに限る。
  seat は spawn 経由に限らず、手で立てて actas を通した codex にも記録される

turn モードでの待機方法:
1. REQ を送信後、他の作業を続ける（ブロックしない）
2. Monitor に agmsg の行が届いたら確認する
3. **数分経っても RESULT が無ければ「遅い」ではなく「ターンを終えていない」を疑う**。
   `history.sh` で既読になっているか見て、未読のままなら起こす

### opencode

opencode は monitor / turn の両方に対応する（`type.conf` は `monitor=yes`）。
**どちらで動いているかで待ち方が変わる**ので、まず現在のモードを確認する:

```bash
$SCRIPTS/delivery.sh status opencode /home/lab_shared/cefore-emu-sslab
```

- **turn モード**（本プロジェクトの現行設定）: 配送は `.opencode/rules/agmsg.md` の
  **PostToolUse**。ツール呼び出しのたびに check-inbox が走るので、
  作業中は codex より速い。逆に**プロンプトで待機している opencode は
  ツールを呼ばないので届かない**
- **monitor モード**: 常駐 watcher で受信するので待機中でも届く。
  ただし `sentinel_monitor` ツールが使えない環境では **PostToolUse ポーリングに
  フォールバックする**ため、実質 turn モードと同じ挙動になる

待機中の相手にレビューを頼むときの手順はステップ B の表に従う
（不在なら `--boot-prompt`、待機中なら send.sh で入れてから対話的にトリガを引く、spawn し直さない）。
**「送った」だけではゲートは進まない。**

### hermes

**自動配送が存在しない**（type manifest が `delivery_modes=off` / `monitor=no`）。
送ったメッセージは inbox に滞留し、hermes 側が自分で見に行くまで届かない。

- 送信は通常どおり `send.sh` でよい
- 到達確認は `history.sh cefore-emu hermes` で滞留を見る（`inbox.sh` は既読化するので使わない）
- **返信を待ってブロックしない。** 返ってこないのが既定の挙動
- spawn 不可（後述）。既に起動しているプロセスへ送るだけ
- REQ 本文に **「次に inbox を見たときでよい」と明記する**のを慣習にする。
  期限を切った依頼を投げると、届かないこと自体が失敗のように見えてしまう

### gemini-main（antigravity）

**現状このプロジェクトでは未配線。** antigravity 型は `.agent/rules/agmsg.md` を
配送フックとして使うが、このファイルが存在しないため送っても届かない。
使う前に一度だけ:

```bash
$SCRIPTS/delivery.sh set turn antigravity /home/lab_shared/cefore-emu-sslab
```

（プロジェクト直下に `.agent/rules/agmsg.md` が生成される。コミット要否は要判断。）

---

## エージェントのライフサイクル

### スポーン

```bash
# codex（バックグラウンド、ブロックしない）— 最初の依頼は --boot-prompt で渡す
~/.agents/skills/agmsg/scripts/spawn.sh codex codex-main \
  --project /home/lab_shared/cefore-emu-sslab --team cefore-emu --no-wait \
  --boot-prompt '[REQ id=... task=explore] ...'

# opencode（tmux 内なら新ペイン、そうでなければ端末を開く）
~/.agents/skills/agmsg/scripts/spawn.sh opencode opencode \
  --project /home/lab_shared/cefore-emu-sslab --team cefore-emu --no-wait \
  --boot-prompt '[REQ id=... task=review] ...'
```

**opencode の spawn には基本的に `--no-wait` を付ける。**
opencode の manifest は `monitor=yes` なので、spawn.sh は ready sentinel を待つ。
だが sentinel が出るのは monitor が実際に成立したときだけで、
**turn モードでも、monitor 設定でも `sentinel_monitor` が使えない環境でも現れない**。
付け忘れると、opencode 自体は起動しているのに spawn が 90 秒待って失敗扱いになる。

**spawn した直後に send.sh で送る、をやらない。**
`turn` モードの発火点は type によって違うが（codex は `Stop`、opencode は `PostToolUse`）、
**どちらも「相手が何かを終えたとき」にしか走らない**という点は同じ。
起動してプロンプトで待っているだけのエージェントは、ターンもツール呼び出しも発生させないので
check-inbox が一度も走らず、送ったメッセージは滞留したままになる。
最初の依頼は `--boot-prompt` に載せて、起動と同時に 1 ターン回させること。

**これは 2 通目以降にも効く。** 相手が動き続けている間は send.sh で届くが、
前フェーズの RESULT を返した後そのまま待機に入った相手には、次の REQ を送っても
配送トリガ（codex は Stop、opencode は PostToolUse）が発火しない。
check-inbox には 60 秒のクールダウンもあり、条件次第で直後のイベントを 1 回飛ばす。

したがって（**turn モード、および monitor が実稼働していない場合**に限る。
monitor / bridge が現に走っているなら待機中でも届くので以下は当たらない）:

- 数分待って RESULT が来なければ **「遅い」ではなく「トリガが発火していない」を疑う**
- **起こす順序を間違えない。** 正しくは
  **① `send.sh` でキューに入れる → ② 対話的にトリガを引かせる**。
  `check-inbox.sh` は起動時に未読行を 1 回 SELECT するだけで待ち受けないため、
  先に起こすとフック終了後にメッセージが入り、**相手はそのまま待機に戻る**
- **spawn し直してはいけない**（下記「待機中を spawn し直さない」）
- **沈黙を「完了」「レビュー通過」と読み替えない**（§ゲートの扱い）

### 待機中を spawn し直さない

`--boot-prompt` が使えるのは**相手が不在のとき**だけ。
起動済みで待機しているだけの相手に同名 spawn をかけると、既存を起こすのではなく
**同じロールの TUI が二重に立つ**。placement 記録も上書きされ、
元のペインは `despawn --force` で落とせなくなる。

`--fresh` は防止にならない。あれが変えるのは resume 対象の選び方だけで、
二重起動を防ぐのは actas の live-role ロックだが、
**codex の actas は seat を記録するだけでロックを取らない**。

意図して置き換えるときは、**先に古いものを落としてから** spawn する:

- **placement 記録がある**（tmux ペイン `%N` / ウィンドウ `@N` / herdr）→ `despawn.sh` で落とす
- **記録が無い**（OS 端末で起動した場合）→ `despawn --force` は使えない。
  手でプロセスかウィンドウを閉じ、`reset.sh` で登録を外してから spawn する

**`--fresh` を付けないと前回セッションが再開される。**
codex の manifest は `resume_arg=resume` を持ち、spawn.sh は既定で
そのロールの直前セッションを復帰させる（記録が無い・古い場合のみ fresh になる）。
**独立レビュー用に新しい codex を立てるときは `--fresh` が必須。**
付け忘れると実装時のコンテキストがそのまま戻ってきて、独立性が得られない。

**hermes は spawn できない。** type manifest に `spawnable` が無く、spawn.sh は
明示的に拒否する。hermes CLI の prompt 受付フラグ（`-z/--oneshot`, `chat -q/--query`）は
いずれも非対話で 1 ターンして終了するため、「初期プロンプト付きで対話セッションを開始する」
呼び出し方が確立していないことによる。

スポーン失敗（tmux なし / 権限なし）の場合:
- 探索ロール → Agent ツール subagent（`Explore`）で代替
- codex ロール → `/codex:rescue` で代替
- レビューロール → `/review` または code-reviewer subagent で代替

### デスポーン

```bash
# codex: 強制終了（第2引数は自分の agent 名。省くと黙って失敗する）
~/.agents/skills/agmsg/scripts/despawn.sh cefore-emu claude-main codex-main --force
```

自分が spawn していないエージェントに `despawn.sh --force` を使わないこと。
tmux ペインの記録が古い場合、無関係なペインを落とす危険がある。
レジストリから外したいだけなら `leave.sh` を使う。

なお強制 despawn は role-session の記録を消さないため、
同名で spawn し直すと**前のセッションが復帰する**（`--fresh` で回避）。

---

## codex-main への依頼注意事項

codex-main は gpt-5.6-sol / reasoning high / summaries auto で動かす想定。
ただしこれは**運用者側の設定であって spawn.sh が保証するものではない**。
manifest が持つのは `model_arg` の綴りだけで、`--model` を明示しない spawn は
モデルを指定しない。設定に依存する依頼をするなら、相手に現在の設定を答えさせて確かめる。

codex は **native subagent 機能**を持ち、モデルも自分で判断して選ぶ。
そのため探索の並列化やレビュー観点の分割は codex 側に任せてよく、
claude-main が宛先を分ける必要はない。REQ の `task=` でモードを指定する。

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

上の例は読みやすさのため折り返して表示しているが、
**実際に send.sh へ渡す body は改行を含まない 1 行**であること（冒頭のクォートルール参照）。

### 同時依頼の禁止

codex-main は 1 回の inbox 読みで**溜まった複数 REQ をまとめて受け取る**。
未応答の REQ を残したまま次を送ると、両者が 1 つの文脈に混ざり、
どちらの id への RESULT なのかも曖昧になる。**in-flight は常に 1 通**に保つ。

独立した 2 件を並行させたい場合は、片方を Agent ツール subagent か
別の codex コンテキストに出す。単一コンテキストは直列運用が前提。

### 引き継ぎが効く条件

spawn.sh は既定で直前セッションを resume するため、
codex-main を再起動しても**通常はコンテキストが戻る**。
ただし引き継ぎが失われる経路がある:

- `--fresh` を付けて spawn した
- role-session の記録が無い / transcript が古いか欠けている（fail-open で fresh 起動になる）
- 別マシン・別 project として起動した

**そして相手は「文脈を失った」と申告しない。**
2 通目以降で前段に依存する依頼を出すときは、前提を 1 行だけ再掲し
（調査結果の全文再送は不要）、RESULT がそれを取り違えていないか確認する。
「前回の調査どおり」だけで済ませない。

### 複数の codex identity を同時に走らせない（turn モード）

`check-inbox.sh` は identity が複数見つかった場合、**先頭の agent 名**を使って inbox を引く。
actas で名乗ったロールではない。
そのため同一プロジェクトで 2 つ以上の codex を turn モードで動かすと、
**片方が他方の inbox を読んでしまう**。

独立レビュー用に 2 体目の codex を立てるときは:
- **既存と重ならない新しいロール名を使う**（既存名で spawn すると二重起動になる）
- `--boot-prompt` で依頼を直接渡し、inbox ポーリングに依存しない
- そのロールに過去のセッション記録があるなら `--fresh` も付ける
  （独立性のため。ただし `--fresh` は二重起動の防止にはならない）
- 依頼はその 1 通で完結させる（往復が要るなら対話的に扱う）

**この危険は turn モード固有**。monitor モードなら複数ロールを扱える:
codex の session-start は記録済み seat（project + thread）でロールを絞ったうえで、
bridge に複数 pair を渡す。したがって 2 体目を恒久的に置きたいなら monitor が正解。

ただし monitor には別の条件がある — **seat の記録が無いロールは inbox を読まれない**。
seat は spawn 経由に限らず、**手で立てた codex でも actas を実行して
thread の解決に成功していれば記録される**。読まれないのは
「actas を通していない」か「thread 解決に失敗した」ロール。

### 自己レビューの限界

codex-main に `task=review` を送ると、**同じコンテキストが自分の書いたコードを見る**。
実装期の文脈がそのまま残っているため、「なぜそう書いたか」の記憶が目を曇らせる。
有用な自己チェックではあるが、独立レビューではない。

独立性の担保先には序列がある:

1. **opencode** — 別プロセス・別ハーネス。既定の独立ゲート
2. **新しい codex コンテキスト**（codex-main の再利用ではなく別 spawn）—
   旧 codex-review 相当。高リスク変更ではこれを足す
3. `/review` / code-reviewer subagent — **claude-main のハーネス内**で動くため、
   claude-main の判断からは独立していない。opencode 不在時の次善策であって等価ではない
