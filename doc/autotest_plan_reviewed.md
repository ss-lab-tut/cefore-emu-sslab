## Autotest基盤実装計画（Warmup-Prefetch / 非対話実行）—レビュー反映版

> 前提: `--no-cli` は feature/mesh ブランチで実装済み。  
> 今回追加するのは **`--duration` / `--results-json`** と **warmup(prefetch) フェーズ**、および **tools/autotest** 一式。  
> autotest は **bridge/ext を禁止**し、Mininet 内のみで完結させる。

---

### Summary

`src/topo/disaster.py` を中核に「put → warmup(get) → flap → eval(get) → 自動終了」を成立させる。  
さらに `results.json` を出力し、`tools/autotest/{run.py, analyze.py}` で複数回実行・集計できるようにする。

---

## 重要な指摘（このままだと破綻するポイント）

### A. “cache nodes” がキャッシュしていない可能性
現状コード（main ブランチ）では `select_k_centers()` の結果は表示されるだけで、**そのノードで csmgrd を起動している保証がない**（例: `idx % 2 == 1` のような固定条件で起動している）。  
warmup を cache nodes に投げても、csmgrd が動いていなければ “キャッシュ運用テスト” にならない。

**対策（必須）**
- cache nodes を決めたら、その集合で **csmgrd を起動**する（固定奇数起動を撤廃）。
- 併せて cache nodes で **CS_MODE が有効**になる設定（cefnetd.conf）を担保する（テンプレ選択 or 実行時上書き）。

### B. `--duration` の意味が曖昧だと、統計が崩れる
「eval が終わったあと残り時間を sleep」は無駄で、試行回数が増えない。  
自動テストの `--duration` は原則 **“eval フェーズを回し続ける上限時間”** として扱うべき。

**対策（推奨）**
- `--duration` は **eval ループ全体の締切**にする：
  - `deadline = start + duration`
  - `while time < deadline: gets を 1 サイクル実行 -> interval sleep`
- duration=0（未指定）は「1サイクルのみ」でよい。

### C. `exit_code` を取れないなら結果が信用できない
`run_cefgetfile()` が exit code を返さない実装の場合、disaster 側だけで正確な判定はできない。  
ログ文言だけに依存すると、成功/失敗のブレが出る。

**対策（推奨）**
- `run_cefgetfile()` を **戻り値あり**に変更する（exit_code / elapsed / log_path など）。
- どうしても触れないなら `host.popen(...).wait()` で exit_code を取得する（ただし既存 helper との整合を取る）。

### D. run 出力を `logs/` に混ぜるのは雑
`logs/ex...` を「正」として参照だけ残す運用は、run が増えるほど破綻する（掃除が難しく、混入する）。

**対策（強推奨）**
- `mesh-disaster-topology.py` に渡す `--output-dir` を **`out/run_XXXX/logs`** にする。
- これで run 1件が自己完結し、コピー不要・参照不要になる。

---

## Scope

1. `src/topo/disaster.py` のフェーズ化と非対話終了制御（duration）。
2. `results.json` の出力（warmup/eval区別、down_hosts記録、exit_code記録）。
3. `CACHE_DEFAULT_RCT` の固定有効化＋config上書き対応。
4. `tools/autotest/run.py` 新規作成。
5. `tools/autotest/analyze.py` 新規作成。
6. `config/examples/autotest_hot.yaml` 新規作成（bridge禁止）。
7. `README.md` に autotest 実行手順追記。

---

## Important API / Interface Changes

### CLI 追加（mesh-disaster-topology.py 経由で disaster.py に反映）
1. `--duration <sec>`: `--no-cli` 時に eval フェーズを回す上限時間（0 なら 1 サイクル）。
2. `--results-json <path>`: get結果配列を JSON 出力。
3. `--warmup-get-interval <sec>`: warmup get 間隔（default 0）。
4. `--warmup-only-cache-nodes`: warmup 対象 host を cache nodes に限定（default true 推奨）。
5. （推奨）`--warmup-uris <csv>`: warmup 対象 URI を明示（未指定なら puts 由来の hot URIs）。

### config キー追加
1. `cache_default_rct_ms`（int, 1000以上想定）
2. `warmup_gets`（list[op]。未指定時は uri ベースで自動生成）
3. `publisher_host`（任意。未指定なら puts から推定）
4. （推奨）`hot_uris`（list[str]。puts を自動生成できるように）

### tools/autotest/run.py CLI
- `--base-config, --runs, --out, --duration, --start-num, --seed-base`

### tools/autotest/analyze.py CLI
- `--inputs`（results.json複数 or ディレクトリ）, `--out-dir`

---

## Detailed Implementation Plan（改訂版）

### 1) disaster.py 側

1. 既存 `--no-cli` に加えて `--duration`, `--results-json` を実装。
2. **bridge/ext 禁止**：`--no-cli` かつ `--results-json` 指定時（= autotest 目的）に
   - `args.ext` / `args.bridge` / `args.bridges` が非空なら即エラー終了（メッセージ明確に）。
3. put 実行後、flap開始前に **warmup フェーズ**を追加。
4. warmup の ops は `warmup_gets` があればそれを使う。
5. `warmup_gets` 未指定時は以下で生成：
   - 対象 URI: `puts` の URI を **重複排除**して使用（eval gets 由来だと冗長になりやすい）
   - 対象 host: `cache_nodes` をデフォルト（`--warmup-only-cache-nodes` true）
6. cache nodes の決定後に、その集合で **csmgrd を起動**し、CS_MODE を有効化しておく。
7. warmup 完了後に `periodic_host_flap()` を開始。
8. eval フェーズは `--duration` を締切として回す：
   - `deadline = now + duration`
   - `while now < deadline or duration==0 (1回だけ): ops_get を 1 サイクル実行`
9. 各 get 実行の直前/直後で `FlapState.snapshot()` を取得し、以下を record 化：
   - `phase, ts, host, uri, out_file, log_file, exit_code, down_hosts`
10. `--results-json` 指定時は終了処理直前に JSON 配列を書き出す（run_dir 配下推奨）。
11. 終了処理は **必ず実行**されるよう try/finally に寄せる：
   - `stop_event.set()`（flap）
   - cefnetd/csmgrd stop
   - `net.stop()`
   - `cleanup_node_dirs()`
   - （必要ならオプションで `mn -c`。デフォルトは実行しない）

### 2) CACHE_DEFAULT_RCT 反映

12. 段階1：`config/templates/h1/csmgrd.conf` に `CACHE_DEFAULT_RCT=<固定値>` を有効化。
13. 段階2：`cache_default_rct_ms` が指定されたら、生成された `hN/csmgrd.conf` を上書き編集する。
    - 書き換えは `src/topo/templates.py` に helper を追加し、`ensure_node_dirs()` 後に適用。

### 3) config loader 反映

14. `src/config/loader.py` の `validate_config` / `merge_cli_and_config` に新規キーを追加。
    - 未知キーは警告 or エラー（どちらかに統一）。

### 4) tools/autotest

15. `tools/autotest/run.py` を新規作成：
    - base config を読み、run ごとに `num/seed/duration/no_cli/results_json/output_dir` を付加した一時 config を生成
    - 子プロセスは **sudo を重ねない**（親が sudo 前提）
    - 出力は `out/run_XXXX/` に自己完結させる（推奨：`output_dir=out/run_XXXX/logs`）
16. `tools/autotest/analyze.py` を新規作成：
    - 全 run の results.json を集約し `summary.csv` / `summary.md` を生成
17. 集計指標（uri 単位）：
    - `warmup_total`, `warmup_success_rate`
    - `eval_total`, `eval_success_rate`
    - `eval_success_rate_when_publisher_down`（publisher_host を基準に down_hosts に含まれる場合をカウント）
18. 失敗理由（複数カウント可）：
    - `exit_code!=0`
    - success 文言不足（例：`Completed to get all the chunks.`）
    - out_file 欠損/0byte
19. config/examples/autotest_hot.yaml を追加：
    - bridge/ext なし（入ってたらエラーになる）
    - Hot URI 定義（puts）
    - warmup/eval gets（もしくは warmup_gets 省略で自動生成）
    - down 設定
    - `cache_default_rct_ms`

20. README.md に追記：
    - 単発実行（no-cli + duration + results-json）
    - 複数 run 実行（run.py）
    - 出力物（results.json / summary.csv / summary.md）の見方

---

## Test Cases and Scenarios

1. 静的検証：`python3 -m py_compile`（disaster/run/analyze）
2. analyze 単体：手製 results.json で集計値と失敗分類を検証
3. run 単体：`--runs 1 --duration 10`（config生成、出力整理、子プロセス起動）
4. 統合：`sudo python3 mesh-disaster-topology.py --config ... --no-cli --duration 120 --results-json ...` で停止せず終了
5. 受け入れ：results.json に warmup/eval 両方の phase が入り、down_hosts が埋まる
6. オーケストレーション：`sudo python3 tools/autotest/run.py --runs 5 ...` 後に summary が生成
7. 異常系：bridge/ext を入れた config で明示エラー終了

---

## Assumptions and Defaults

- run.py は sudo 起動前提。子プロセスに sudo は付けない。
- 出力は `out/run_XXXX/` で自己完結（推奨）。`logs/` 参照運用は避ける。
- bridge/ext は autotest では禁止（指定時エラー）。
- `cache_default_rct_ms` 未指定時はテンプレ固定値を使用。
- success 判定は **AND** を標準：
  - exit_code==0
  - success 文言あり
  - out_file 存在かつ 0byte でない

---

## Codex CLI に貼る「作業指示」短縮版

1. feature/mesh の `--no-cli` は維持しつつ、`--duration` と `--results-json` を追加して非対話で確実に終了させる  
2. put→warmup(prefetch)→flap→eval を実装し、各 get の record を `results.json` に吐く（phase/down_hosts/exit_code必須）  
3. cache nodes で csmgrd が動いていることを保証する（ここを外すとキャッシュ実験が成立しない）  
4. `cache_default_rct_ms` を `hN/csmgrd.conf` へ反映できるようにする（段階1: templates 固定、段階2: config 上書き）  
5. `tools/autotest/run.py` と `tools/autotest/analyze.py` を追加し、複数回実行と集計を自動化する  
6. `config/examples/autotest_hot.yaml` と README を追加する
