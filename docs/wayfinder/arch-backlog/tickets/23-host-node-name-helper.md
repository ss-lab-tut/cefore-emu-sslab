---
status: open
type: task
claimed-by:
blocked-by: []
---
## Task

**host 番号 → ノード名変換の集約 (trigger 待ち)**:
config / event の `host` は整数 (`host: 3`) で受け、実行直前に各所で `f"h{idx}"` を組み立ててノード名にしている。変換を 1 つの helper に集約し、名前規則 (`h` + 番号) の定義点を 1 か所にする。
利用者向けの `host` を整数からノード名 (`host: "h3"`) へ変える破壊的変更は **見送り** (2026-09-17 決定)。ノード名は `topo.py` の `addHost(f"h{idx}")` で番号から機械的に決まり整数と 1 対 1 なので、名前指定にしても表現力は増えず、既存 config (`config/examples/`, `config/workshop/`) と archived run の `host` 欄を読む summarizer / plots が使えなくなる代償だけが残る。
着手条件: 番号と名前の 1 対 1 が崩れるとき — 番号で表せないノード (外部ノード、switch 等) を event 対象にする、または [21](21-recefore-rename-implementation.md) / [22](22-application-adapter-api.md) でノード識別子を設計し直すとき。その時点で集約を先に行い、利用者向け表現の変更はそのうえで判断する。
_Avoid_: 着手条件なしに集約だけ単独で進めること (規則が変わらない限り 54 か所は食い違わず、得るものが少ない)、互換変換層なしに `host` の型を変えること

## Status (2026-09-17)

- 未着手。`src/` に名前 helper は無い (`def node_name` 等 0 hits)。`f"h{...}"` は 18 ファイル 54 か所 (main 7fd319e で `git grep -nE 'f"h\{' -- src` 実測)。
- CONTEXT.md「DaemonFleet」の「`build_fleet` がノード名を導出する唯一の場所」は daemon 群の名前リスト (`daemon_fleet.py:45-46`) に限った話で、コマンド宛先・パス・表示は対象外。
- 内訳 (目安):
  - ノード生成 = 名前規則の定義点: `topo.py:25/39/75` (3)
  - daemon 群の名前リスト (集約済み): `daemon_fleet.py:45-46` (2)
  - コマンド実行先: `cefore.py` 13、`net_config.py` 4、`failure_manager.py` 4、`bridge_root.py` 4、`linear.py` 2、`bandwidth.py` / `compute_client.py` / `debug.py` / `monitoring.py` / `links.py` (約 35)
  - ホスト別設定ディレクトリ・パス: `template.py` 5、`cache_manager.py:153`、`forwarding.py:49`、`cefore.py:49` (約 8)
  - 表示・ログ: `viz.py` 5、`webui/state.py:55`、`cache_manager.py:235`、`scenario_setup.py:226` (約 8)
- 経緯: CommandRunner seam 移行 (bfc48cd) のコミットメッセージに「破壊的変更 (host int→node名) は別フォローのため未着手」とだけ残っていた。仕様・動機の記録は無かったため、本 ticket で判断を記録する。
