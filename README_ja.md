# CeforeEmu

[README.md(en)](./README.md)

## 概要

CeforeEmu は、Ubuntu 22.04 上で Cefore（コンテンツ指向ネットワーキングフレームワーク）の動作検証を行うための Mininet ベースのネットワークエミュレータです。Cefore デーモン（*cefnetd*）を実行する仮想ホストを持つ仮想ネットワークトポロジを構築し、コンテンツ配信シナリオをシミュレートします。

統一 CLI から 3 種類のトポロジを利用できます：

| サブコマンド | 説明 |
|------------|------|
| `linear` | 線形トポロジ（コンシューマ−ルータ−パブリッシャの連鎖） |
| `mesh` | マルチパス FIB を持つランダムメッシュトポロジ |
| `disaster` | 定期的なホスト障害・帯域制御・外部インタフェース接続を持つメッシュトポロジ |

## 前提条件

* Ubuntu 22.04 に Cefore がインストール済みであること
* Mininet バージョン 2.3.0 ([https://mininet.org/](https://mininet.org/))
* Python >= 3.12
* curl（`compute_call` イベントに必要）
* uv (pythonのパッケージ管理に必要)

```bash
uv sync   # 依存パッケージのインストール
```

## クイックスタート

```bash
# 線形トポロジ（デフォルト 3 ノード）
sudo .venv/bin/python3 -m src linear

# 7 ホストの線形トポロジ
sudo .venv/bin/python3 -m src linear --hosts 7

# メッシュトポロジ
sudo .venv/bin/python3 -m src mesh --hosts 8 --switches 12 --seed 42 --k 3

# 設定ファイルを使ったディザスタートポロジ
sudo .venv/bin/python3 -m src disaster --config config/examples/example.yaml

# Mininet CLI の終了
mininet> exit
```

`uv` / `pip install -e .` でインストール済みの場合は `ceforeemu` コマンドも使用できます：

```bash
sudo ceforeemu linear --hosts 5
sudo ceforeemu disaster --config config/examples/example.yaml
```

### UDP バッファ設定

```bash
./buffer.sh   # Cefore 向けに UDP バッファサイズを拡張する
```

## トポロジの種類

### linear

単純な線形チェーン：h0（コンシューマ）- s0 - h1（ルータ）- s1 - ... - hN（パブリッシャ）。

```bash
sudo .venv/bin/python3 -m src linear --hosts 5
```

### mesh

スイッチで接続されたホストのランダムメッシュ。各宛先ホスト hX はプレフィックス `ccnx:/test/example{X+1}` にマッピングされ、k 最短パスを FIB に使用します。

```bash
sudo .venv/bin/python3 -m src mesh --hosts 8 --switches 12 --seed 42 --k 3
```

主なオプション：

| オプション | 説明 |
|----------|------|
| `--hosts` | ホスト数 |
| `--switches` | スイッチ数（2 以上） |
| `--seed` | 再現性のあるトポロジ生成用乱数シード |
| `--k` | 宛先ごとの最短パス数（デフォルト: 2） |
| `--node-per-switch` | スイッチあたりの最大ホスト数（0=無制限、デフォルト: 2） |
| `--host-degree-min` | ホストあたりの最小スイッチ接続数（デフォルト: 1） |
| `--host-degree-max` | ホストあたりの最大スイッチ接続数（デフォルト: 2） |
| `--topo-png` | トポロジ PNG の出力パス |
| `--topo-layout` | レイアウト: spring, kamada_kawai, circular |

### disaster

定期的なホストの停止/復旧サイクル、帯域制御、外部インタフェースの接続、およびイベント駆動のコンテンツ操作を持つメッシュトポロジ。

```bash
sudo .venv/bin/python3 -m src disaster --hosts 10 --switches 15 --seed 42 \
  --down-interval 30 --down-duration 10 --down-count 2
```

主なオプション：

| オプション | 説明 |
|----------|------|
| `--down-interval` | 停止イベントの間隔（秒、0 で無効） |
| `--down-duration` | ホストを停止し続ける時間（秒） |
| `--down-count` | 1 サイクルで停止するホスト数 |
| `--down-stagger` | サイクル内の停止イベントをずらす秒数 |
| `--down-exclude` | 除外するホスト ID（カンマ区切り） |
| `--cache-count` | キャッシュノード数（0 = down-count + 1） |
| `--bw nodeA,nodeB,mbps` | リンク帯域を設定（繰り返し指定可） |
| `--ext host,ifname,ip[,mtu]` | 外部インタフェースを接続; ipはCIDR形式で必須（DHCPは未サポート、繰り返し指定可） |
| `--bridge switch,root_ip,local_routes[,ext,gw]` | ルート名前空間ブリッジ（繰り返し指定可） |
| `--config` | JSON/YAML 設定ファイル |
| `--no-cli` | 非対話モード |
| `--duration` | 評価時間（秒、`--no-cli` と併用） |
| `--results-json` | 取得結果を JSON に書き出す |

## 設定ファイル

`--config` で JSON または YAML から設定を読み込みます。YAML サポートには `pyyaml` が必要です。

トップレベルの `puts`、`gets`、`auto` は警告を出して無視されます。コンテンツ操作は
すべて `events` に書いてください。

**コンテンツ操作（JSON）:**
```json
{
  "hosts": 10,
  "switches": 15,
  "seed": 42,
  "events": [
    {"at": 5, "type": "put", "host": 9, "uri": "ccnx:/test/video1", "file": "./video.bin", "rate": 10, "expiry": 5000, "cache_time": 5000},
    {"at": 10, "type": "get", "host": 0, "uri": "ccnx:/test/video1"},
    {"at": 15, "type": "pubsub_sub", "host": 1, "uri": "ccnx:/test/live", "sub_opts": {"wait": 20}},
    {"at": 15, "type": "pubsub_pub", "host": 7, "uri": "ccnx:/test/live", "file": "./data.bin", "pub_opts": {"lifetime": 8}}
  ]
}
```

**タイムドイベント（YAML）:**
```yaml
hosts: 10
switches: 15
seed: 42
events:
  - {at: 5, type: put, host: 9, uri: "ccnx:/test/sample", file: "./sample-putfile"}
  - {at: 10, type: get, host: 0, uri: "ccnx:/test/sample"}
  - {at: 15, type: link_down, nodes: [1, 2]}
  - {at: 25, type: link_up, nodes: [1, 2]}
  - {at: 30, type: fib_del, host: 3, prefix: "ccnx:/test/sample", next_hop: "192.168.1.1"}
```

サポートされるイベントタイプ: `link_down`, `link_up`, `fib_add`, `fib_del`,
`fib_enable`, `bw_set`, `compute_call`, `put`, `get`, `pubsub_sub`,
`pubsub_pub`。

disaster の通常 `put` event では、`expiry` と `cache_time` の省略時に
どちらも `3000` を Cefore コマンドへ渡し、events 移行前の挙動を保ちます。
`pubsub_pub` の `pub_opts.expiry` / `pub_opts.cache_time` は暗黙補完せず、
省略時は Cefore コマンドの既定値を使います。

`ceforeemu-connect` は `put` と `pubsub_pub` event のみを publisher 判定、
URI 別 FIB 設定、CLI 開始前の publication seed に使います。`get` と
`pubsub_sub` は自動実行せず warning を出します。トップレベルの legacy
content key は復活しません。

**モニタリング:**
```yaml
monitoring:
  interval: 5
  output_json: "monitor.json"
  output_csv: "monitor.csv"
  targets:
    - {type: cefstatus, hosts: "all"}
    - {type: csmgrstatus, hosts: "cache"}
```

## ログ出力ディレクトリ

`num` を指定した場合（設定ファイルまたは `--num`）、ログは専用ディレクトリに整理されます：

```
logs/ex{num}_seed{seed}/
├── script.log              # スクリプト実行ログ
├── topology.png            # トポロジ図
├── meta.json               # 設定スナップショット
├── cefputfile_*.log        # cefputfile ログ
├── cefgetfile_*.log        # cefgetfile ログ
├── recvfile_*              # 受信ファイル
└── results.json            # 取得結果（--results-json 使用時）
```

```bash
# ログディレクトリ出力を有効化
sudo .venv/bin/python3 -m src disaster --num 1 --hosts 10 --switches 15 --seed 42

# 出力ディレクトリをカスタム指定
sudo .venv/bin/python3 -m src disaster --config config.yaml --output-dir experiments

# ディレクトリ名にタイムスタンプを付加
sudo .venv/bin/python3 -m src disaster --config config.yaml --timestamp
```

## 自動テスト（非対話モード）

単発実行:
```bash
sudo .venv/bin/python3 -m src disaster \
  --config config/examples/example.yaml \
  --no-cli \
  --duration 120 \
  --results-json results.json \
  --num 1
```

バッチ実行:
```bash
sudo .venv/bin/python3 tools/autotest/run.py \
  --base-config config/examples/example.yaml \
  --runs 5 \
  --duration 120 \
  --out out
```

出力:
- `out/run_XXXX/logs/ex{num}_seed{seed}/`: 実行ごとのログ、`meta.json`、`results.json`
- `out/summary.csv`: URI レベルの集計メトリクス
- `out/summary.md`: 人が読めるサマリ

autotest mode の `events[].at` は、実験開始時に確定する単一の絶対時計を
基準にします。seed put、warmup、failure/evaluation の順は維持され、
warmup 中に予定時刻を過ぎた evaluation event は late warning とともに
直ちに実行されます。autotest の `put` に `repeat` は指定できません。
`duration` は failure/evaluation phase 開始後の観測時間のままで、
evaluation event がなく `duration: 0` の場合は failure phase を開始しません。

## ログ集計

cefputfile/cefgetfile/cefpubfile/cefsubfile のログを収集し、コマンドごとの CSV ファイルを出力します：

```bash
# 単一ディレクトリ
ceforeemu-log logs/ex1_seed42/

# 複数ディレクトリ（実験間の比較）
ceforeemu-log logs/ex1_seed42/ logs/ex5_seed42/ -o results/

# パイプ対応の標準出力
ceforeemu-log logs/ex1_seed42/ --stdout | head -20
```

インストールされていない場合は `uv run ceforeemu-log` を使用してください。

## プロジェクト構成

```
cefore-emu/
├── src/                           # メインソースコード
│   ├── __init__.py
│   ├── __main__.py                # python -m src エントリポイント
│   ├── cli/                       # CLI インタフェース
│   │   ├── main.py                # サブコマンドディスパッチャ
│   │   └── args.py                # 引数パーサ定義
│   ├── core/                      # コアロジックとアルゴリズム
│   │   ├── config/                # 設定ユーティリティ
│   │   │   ├── loader.py          # JSON/YAML 設定ローダ
│   │   │   └── priority_resolver.py  # 設定優先度解決
│   │   ├── fib.py                 # FIB ルート計算
│   │   ├── flap_state.py          # ホストフラップ状態追跡
│   │   ├── graph.py               # グラフアルゴリズム（Dijkstra、k-center）
│   │   ├── paths.py               # 出力パス解決
│   │   ├── roles.py               # ノードロール割り当て
│   │   └── tee.py                 # stdout/stderr をファイルに tee
│   ├── log/                       # ログ解析と CSV 集計
│   │   ├── filename.py            # ファイル名パターン → メタデータ抽出
│   │   ├── parser.py              # ログテキスト → dict パーサ
│   │   ├── plotter.py             # ログデータのプロット
│   │   ├── summarizer.py          # ディレクトリ走査 + CSV 出力
│   │   └── cli.py                 # argparse CLI
│   ├── runtime/                   # ランタイム操作
│   │   ├── bandwidth.py           # リンク帯域制御
│   │   ├── base.py                # ベースランタイムユーティリティ
│   │   ├── bridge.py              # Linux ブリッジ & ルート NS ブリッジング
│   │   ├── cache_manager.py       # キャッシュマネージャ操作
│   │   ├── cefore.py              # Cefore デーモンの起動/停止/待機
│   │   ├── external_net.py        # 外部ネットワークメッシュシナリオ
│   │   ├── failure_manager.py     # ホスト障害シミュレーション
│   │   ├── links.py               # リンク状態制御（up/down）
│   │   ├── monitoring.py          # 定期的なステータス収集
│   │   ├── net_config.py          # IP アドレス & FIB 適用
│   │   ├── scheduler.py           # タイムドイベントスケジューラ
│   │   ├── template.py            # ホストディレクトリテンプレート管理
│   │   ├── topo.py                # Mininet Topo サブクラス（MeshTopo）
│   │   └── viz.py                 # トポロジ可視化 & PNG 出力
│   └── scenarios/                 # シナリオ実装
│       ├── base.py                # 共通シナリオユーティリティ
│       ├── linear.py              # 線形トポロジシナリオ
│       ├── mesh.py                # メッシュトポロジシナリオ
│       └── disaster.py            # ディザスタシミュレーション付きメッシュ
│
├── config/                        # 設定ファイル
│   ├── templates/                 # ホストテンプレート（h0, h1, h2）
│   └── examples/                  # 設定例（YAML/JSON）
├── doc/                           # 設計ドキュメント
├── tools/
│   └── autotest/                  # バッチ実験ランナー
│       ├── run.py                 # バッチ実行スクリプト
│       └── analyze.py             # 結果解析
│
├── sample-putfile                 # テストデータ（root 例外）
├── buffer.sh                      # UDP バッファ設定（root 例外）
├── pyproject.toml                 # パッケージ設定
└── CLAUDE.md                      # 開発ガイダンス
```

## ドキュメント

- [doc/autotest_plan_reviewed.md](doc/autotest_plan_reviewed.md) - 自動テスト実装計画
- [doc/cefore_emu_autotest_spec.md](doc/cefore_emu_autotest_spec.md) - 自動テスト仕様
- [doc/branch-retirement-feature-test.md](doc/branch-retirement-feature-test.md) - ブランチ廃止ノート

## ノードロール

| ロール | ホスト | CS_MODE | 説明 |
|------|-------|---------|------|
| コンシューマ | h0（最初） | 0 | `cefgetfile` でコンテンツを要求する |
| ルータ | 奇数番号 | 2 | Interest/コンテンツを転送し、`csmgrd` を実行する |
| パブリッシャ | 最後のホスト | 0 | `cefputfile` でコンテンツを保存・配信する |

3 ホストを超えるトポロジでは、追加ホストディレクトリがテンプレートから動的に生成され、スクリプト完了後に削除されます。

## 外部機器接続時のアドレッシング

Mininet ホストを `--ext` や `bridges` で外部の物理 Cefore 機器に接続する場合、デフォルトの内部アドレス空間 `192.168.0.0/16` は物理 LAN と衝突しやすくなります。外部機器に Mininet 内部 IP への明示的なルートがなければパケットはドロップされ、Class C Ethernet 環境で他の機器も `192.168.x.x` を使用している場合、応答が誤った機器に返送されるリスクもあります。

設定ファイルの `addressing.network_cidr` で内部アドレス帯を変更してください：

| アドレス帯 | 推奨度 | 理由 |
|-----------|--------|------|
| `100.64.0.0/16` | 第一推奨 | RFC 6598 Shared Address Space (CGNAT) — 一般 LAN で使われることがほぼなく、衝突リスクが最も低い |
| `172.20.0.0/16` | 代替 | RFC 1918 Class B プライベート — 192.168.x.x より衝突リスクは低いが、大規模企業 LAN で使われる場合あり |

> **注意:** `network_cidr` は `/16` のみ指定可能です。CGNAT 全体の `100.64.0.0/10` ではなく `100.64.0.0/16` を指定してください。

```yaml
addressing:
  network_cidr: "100.64.0.0/16"
```

外部機器側にも Mininet 内部アドレス帯へのスタティックルートを追加する必要があります：

```bash
ip route add 100.64.0.0/16 via <ブリッジのルートNS側IP>
```

詳細は `config/examples/example.yaml` を参照してください。

## セキュリティに関する注意

- `config/templates/h*/default-private-key` ファイルには機密性の高い暗号鍵素材が含まれています
- Mininet のネットワーク名前空間操作のため、すべてのスクリプトは root 権限が必要です
- 信頼された隔離環境（VM 推奨）でのみ実行してください
