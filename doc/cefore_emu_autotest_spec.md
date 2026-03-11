# cefore-emu 自動テスト基盤（AIなし / Warmup-Prefetch 方式）仕様書 & Codex CLI 指示

> 方針: **AIは今回スコープ外**。Hotコンテンツを事前定義し、**prefetch（warmup get）**でキャッシュに載せてから、host down/up（disaster）中の取得成功率を測る。  
> **bridge は使用しない**（Mininet 内のみ）。  
> pub/sub（cefpubfile/cefsubfile）は後回し。

---

## 0. 背景（現状の前提）

- 本リポジトリは Mininet 上で Cefore（cefnetd/csmgrd）を起動し、トポロジ/FIB/put-get を再現するエミュレータ。
- `mesh-disaster-topology.py` は実体 `src/topo/disaster.py` を呼ぶ薄いラッパ。
- 現状 `disaster.py` は最後に **`CLI(net)` に入って停止**するため、自動実行できない。ここを直すのが最優先。

---

## 1. 今回の「キャッシュヒット率」定義（観測可能な代理指標）

真の CS hit（csmgrd/cefnetd 内部統計）を直接取るのは今回やらない。代わりに以下を採用する：

- **Cache-hit(代理)** = 「publisher が down 状態のタイミングでも `cefgetfile` が成功した割合」
  - down 状態は disaster の flap 状態（down hosts）から取得する。
  - 成功/失敗は `cefgetfile` の終了コードとログパターンで判定する。

この定義なら、既存の host down/up と put/get の枠内で機械的に集計でき、比較実験が成立する。

---

## 2. Hotコンテンツ（事前定義）

### 2.1 目的
- 実験間で比較可能にするため、Hot対象を固定する（URI 名と投入ファイルを固定）。

### 2.2 仕様（例）
- URI: `ccnx:/test/hot/content1` 〜 `ccnx:/test/hot/contentK`
- publisher: 例として `h{hosts-1}`（もしくは config 指定）
- file: `./sample-putfile`（固定）

### 2.3 config での表現（puts/gets）
- puts: Hotコンテンツを publisher に投入
- gets: 本番の取得（評価）用 consumers を指定（または auto 生成）

> ※ warmup（prefetch）用 gets は **本番 gets とは別に**扱う（次章）。

---

## 3. キャッシュ保持時間の延長（RCT）

### 3.1 要件
- 「キャッシュさせる時間」を延長するため、`csmgrd.conf` の `CACHE_DEFAULT_RCT` を設定できること。

### 3.2 実装方針（段階）
**段階1（最速で成立）**
- `config/templates/h1/csmgrd.conf` に `CACHE_DEFAULT_RCT=<ms>` を有効化して固定値で延長。

**段階2（実験パラメータ化：推奨）**
- config（json/yaml）に `cache_default_rct_ms` を追加し、`ensure_node_dirs()` で生成された `hN/csmgrd.conf` に反映する。
- 将来の RL で `CACHE_CAPACITY` と合わせて最適化できるようにする。

---

## 4. Warmup-Prefetch（今回の 핵）

### 4.1 目的
- 本番の評価（disaster 中の取得）を始める前に、指定ノードに Hotコンテンツを **prefetch**してキャッシュに載せる。

### 4.2 仕様
- warmup フェーズで、Hotコンテンツに対して以下を実行する：
  - 対象ノード: cache nodes（既存の `select_k_centers()` 結果）**または** config 指定ノード
  - 操作: `cefgetfile`（取得してキャッシュに格納させる）
- warmup 中は host flap を開始しない（=安定時に載せる）。
- warmup 完了後に flap を開始し、本番 gets を走らせる。

> pub/sub は使わない。prefetch のみで成立させる。

---

## 5. 自動実行（非対話）の必須改修

### 5.1 追加 CLI 引数（必須）
`src/topo/disaster.py` に以下を追加する：

- `--no-cli` : true の場合 `CLI(net)` を呼ばない
- `--duration <sec>` : no-cli 時に実験を何秒走らせて終了するか
- `--results-json <path>` : get 実行の結果レコードを書き出す

### 5.2 no-cli の挙動（必須）
- 起動 → put（Hot投入） → warmup(get) → flap開始 → 本番get → duration 経過 → 終了
- 終了時に必ず実施：
  - flap thread stop
  - cefnetd/csmgrd stop
  - `net.stop()`
  - `cleanup_node_dirs()`（h3 以降掃除）
  - stale socket cleanup が必要なら実施

---

## 6. results.json（必須）

### 6.1 目的
- cache-hit(代理) を計算するため、**各 get の時点の down hosts**と成否を記録する。

### 6.2 スキーマ（最小）
`results.json` は配列で、各要素は最低限これを含む：

```json
{
  "ts": "ISO8601",
  "phase": "warmup|eval",
  "host": 3,
  "uri": "ccnx:/test/hot/content1",
  "out_file": "logs/ex1_seed42/recvfile_h3_c1",
  "log_file": "logs/ex1_seed42/cefgetfile_....log",
  "exit_code": 0,
  "down_hosts": [9]
}
```

- phase は warmup と eval（本番）の区別に必須。
- down_hosts は `FlapState.snapshot()` で取得。
- exit_code が取れない場合はログ解析で補完するが、理想は `run_cefgetfile` 側で取る。

---

## 7. 自動テスト runner（新規作成）

### 7.1 追加ディレクトリ
- `tools/autotest/`

### 7.2 `tools/autotest/run.py`（必須）
**入力**
- `--base-config <yaml/json>`（テンプレ）
- `--runs <N>`
- `--out <dir>`（例: `autotest_runs/`）
- `--duration <sec>`（disaster に渡す）

**動作**
1. base config を読み込み
2. run ごとに `num` と `seed` を付与した一時 config を生成
3. `sudo python3 mesh-disaster-topology.py --config <tmp> --no-cli --duration <sec> --results-json <path>` を実行
4. 出力ディレクトリ（`logs/ex{num}_seed{seed}...`）と `results.json` を out 配下に整理
5. `analyze.py` を呼び、`summary.csv` と `summary.md` を生成

### 7.3 `tools/autotest/analyze.py`（必須）
`results.json` から以下を出す：

- URI 別
  - eval_total
  - eval_success_rate
  - **eval_success_rate_when_publisher_down**（= cache-hit proxy）
  - warmup_success_rate（warmup が失敗してるなら評価する価値がない）
- 失敗理由分類（最低限）
  - exit_code != 0
  - ログに `Completed to get all the chunks.` が無い
  - out_file が無い/0 bytes

出力：
- `summary.csv`
- `summary.md`（人間向け要約）

---

## 8. 最低1本のテストシナリオ（受け入れ条件）

### シナリオA: Hot耐障害取得率（prefetch有り）
- Hot を publisher で put
- warmup(get) を cache nodes で実施（prefetch）
- flap 開始（publisher が down になるケースを含める）
- eval(get) を consumers で複数回実施
- `publisher_down` 時の成功率を cache-hit proxy として算出

**受け入れ条件（最低ライン）**
1) `--no-cli` で止まらずに終了する  
2) `results.json` が生成される  
3) `summary.csv` / `summary.md` が生成される  
4) warmup と eval が区別されて集計される  

---

## 9. Codex CLI への作業指示（順序固定）

1. `src/topo/disaster.py` に `--no-cli`, `--duration`, `--results-json` を追加し、no-cli 時は `CLI(net)` に入らずに自動終了させる  
2. put → warmup(get) → flap → eval(get) のフェーズ構造を追加し、`phase` を付けて `results.json` に記録する  
3. `CACHE_DEFAULT_RCT` を延長できるようにする（段階1: templates 直書き、段階2: config で上書き）  
4. `tools/autotest/run.py` を新規作成し、N回実験を回してログ/結果を out 配下に整理する  
5. `tools/autotest/analyze.py` を新規作成し、results から `summary.csv` と `summary.md` を生成する  
6. `config/examples/` に autotest 用 base config を追加（bridge 無し、Hot定義、down 設定あり）  
7. README に自動テストの実行方法を追記する  

---

## 10. 実行例（目標）

```bash
# 1回実行（非対話）
sudo python3 mesh-disaster-topology.py \
  --config config/examples/autotest_hot.yaml \
  --no-cli --duration 120 \
  --results-json logs/ex1_seed42/results.json

# 複数回オーケストレーション
sudo python3 tools/autotest/run.py \
  --base-config config/examples/autotest_hot.yaml \
  --runs 5 --duration 120 --out autotest_runs
```

---

## 11. 将来（RL）へ向けた注意（今回やらないが、今の設計に残すべき）

- RL はローカル実行前提で良いが、**観測量（state）と報酬（reward）の設計が全て**。
- 今回の proxy 指標（publisher down 時成功率）は RL の報酬候補になるが、代理指標最適化の罠に注意。
- 今のうちに、少なくとも以下を logs/results に残すと後が楽：
  - get の duration / throughput（ログから抽出可能）
  - flap の down_hosts とタイムスタンプ
  - cache パラメータ（capacity, rct）と seed
