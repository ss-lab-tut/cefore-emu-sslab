---
status: open
type: task
claimed-by: claude-main
blocked-by: []
---
## Task

**復元イベント（Restore event）を、トップレベルのイベントと同じ検証に通す**:
`repeat.restore` / `repeat.restore_type` から scheduler が実行時に合成する復元イベント
（`scheduler.py` の `_handle_repeat`、`{**event, **restore}` または `{**event, "type": restore_type}`）は、
validator では「`restore` が dict か」「`restore_type` が既知の型名か」しか検査されない。
そのため `link_down` に `restore_type: fib_add` を付けた config や、`put` に `restore: {host: 99, rate: -1}` を
付けた config が `validate_config(...) == []` で通り、実行時に `KeyError('prefix')` などの失敗レコードになる
（2026-10-20 再現）。同じ `rate: -1` をトップレベルに書けば検証で拒否される。
内容系の復元イベントが publisher になる場合、`extract_publications` は元の events しか走査しないため FIB 事前
設定からも漏れる。2026-07-16 の audit fix（ba56d65 / 38ffcca）は compute_call だけを塞いでいた。

決定事項（2026-10-20 architecture review の grilling）:

1. 復元イベントを作る pure な関数を `src/core/events.py` に置き、scheduler と validator の両方が呼ぶ。
   合成規則（`restore` で上書き、`repeat` を外す）はここ 1 か所が持つ。
2. restore 形式（`duration` に伴う `restore` / `restore_type`）を許すのは非内容系（`link_*` / `fib_*` / `bw_set`）のみ。
   内容系と compute_call は `interval` / `count` 以外を拒否する。compute_call の既存規則と 1 本にまとめ、
   compute_call のメッセージは byte 一致のまま。これで復元イベントが publisher になる経路自体が消え、
   `extract_publications` は変更しない。
   （2026-10-20 訂正: 元のイベントの型だけを制限しても、`link_down` を `restore_type: put` や
   `restore: {type: pubsub_pub}` で内容系へ復元する経路が残っていた。advisor review で発見し、復元先の型にも
   同じ集合を当てて塞いだ。両方を制限して初めて「経路自体が消える」が成り立つ。）
3. 復元後のイベントは、トップレベルと同じ型ごとの規則で検証する。メッセージには
   `events[i].repeat.restore` 接頭辞を付けて区別する。
4. `restore` と `restore_type` の同時指定は検証エラー（現状は scheduler の if/elif で `restore` が黙って優先される）。
5. `duration` だけで復元先を書かない repeat は **有効のまま**。復旧しない変化を表す意図された書き方として、
   validator のコメント・CONTEXT.md「Restore event」・config 例のコメントに明文化する。
6. その前提として `_validate_events`（313 行の if/elif）を「型名 → 検証関数」の表に作り直す。
   表と `event_types()` の一致を import 時に assert し（`content_ops.py` と同じ流儀）、`required_fields` に
   結び付いた型の共通検査（必須フィールド・`host` 整数）は 1 回だけ行う。`link_*` / `bw_set` の独自の形の検査
   という EventSchema の非対称は保つ。

コミットの切り方: (a) 作り直し（メッセージ 1 文字も変えず、既存テスト無変更で全 pass）→
(b) 文言のずれの統一（テストも合わせて直す）→ (c) 新規則を TDD で 1 つずつ。

テストの seam: `validate_config`（公開 interface）と `build_restore_event`（pure）。scheduler の既存 repeat テストは残す。

_Avoid_: `duration` だけの repeat を検証エラーにすること（意図された書き方）、`bw_set` の元の帯域を覚えて自動で戻す機能
（逆操作の表と状態が新しく要る。欲しくなったら別 ticket）、`extract_publications` に復元イベントを走査させること
（決定 2 で経路自体を消した）

## Status (2026-10-20)

- 2026-10-20 着手（branch `feat/restore-event-validation`）。architecture review の Top recommendation。
- (a) `_validate_events` の作り直し: 85a7741（メッセージ無変更、作り直し前との差分 fuzz で一致）。
- (b) `bw_set` の nodes の形の誤りの文言を `link_*` にそろえた: 9e005d1。
- (c) 新規則: `build_restore_event` 新設と scheduler の置き換え 1d352c0、復元イベントの型ごとの検証 e4cbe64、
  内容系の repeat allowlist 化 fcec455、同時指定の拒否と duration だけの repeat の明文化 50648a8。
- 検証（2026-10-20）: unit 1585 passed / 8 skipped、ruff・mypy 0。`config/` 配下 78 config を変更前後の validator に
  通して検証結果の差 0。cefore-run-tests の smoke 14 本 PASS。smoke に repeat を使う config が無いため、
  `min_event_link` を改変した repeat restore 版（bw_set の `restore`、link_down の `restore_type`）を実機で 1 回走らせ、
  復元イベントが予定時刻に発火し `restore` の値で実行されることを確認。

## Follow-up（本 ticket の scope 外として記録）

- 検証エラーに config ファイル名と行番号を付ける（例: `example.yaml:42: events[0].nodes ...`）。現状は
  `config error: events[0].nodes ...` だけ。loader が `yaml.safe_load` で位置情報を捨てるため、ノード位置を
  保持する Loader と、`events[i].field` パスから行を引く対応表が要る。JSON config（`config/examples/example.json`）
  をどう扱うかも別に決める。2026-10-20 ユーザー提案。
