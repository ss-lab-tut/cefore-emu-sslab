# ReCefore (by sslab)

[![CI](https://github.com/ss-lab-tut/cefore-emu-sslab/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ss-lab-tut/cefore-emu-sslab/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/ss-lab-tut/cefore-emu-sslab)](LICENSE)
[![Release](https://img.shields.io/github/v/release/ss-lab-tut/cefore-emu-sslab)](https://github.com/ss-lab-tut/cefore-emu-sslab/releases/latest)
[![Python](https://img.shields.io/python/required-version-toml?tomlFilePath=https://raw.githubusercontent.com/ss-lab-tut/cefore-emu-sslab/main/pyproject.toml)](pyproject.toml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![mypy](https://img.shields.io/badge/types-mypy-blue)](https://mypy-lang.org/)

[README.md(en)](./README.md)

## 目次

- [概要](#概要)
- [前提条件](#前提条件)
- [クイックスタート](#クイックスタート)
  - [UDP バッファ設定](#udp-バッファ設定)
- [トポロジの種類](#トポロジの種類)
  - [linear](#linear)
  - [mesh](#mesh)
  - [disaster](#disaster)
- [設定ファイル](#設定ファイル)
  - [コンテンツ操作 (JSON)](#コンテンツ操作-json)
  - [タイムドイベント (YAML)](#タイムドイベント-yaml)
  - [compute_call イベント](#compute_call-イベント)
  - [ceforeemu-connect でのイベント](#ceforeemu-connect-でのイベント)
  - [モニタリング](#モニタリング)
  - [キャッシュ設定 (cache_config)](#キャッシュ設定-cache_config)
  - [障害シナリオ (failure_scenarios)](#障害シナリオ-failure_scenarios)
  - [ルーティング戦略 (routing)](#ルーティング戦略-routing)
  - [明示的トポロジ (links)](#明示的トポロジ-links)
  - [静的プレフィックスルート (prefix_routes)](#静的プレフィックスルート-prefix_routes)
  - [転送戦略設定 (forwarding_config)](#転送戦略設定-forwarding_config)
  - [ホストアプリ (host_apps)](#ホストアプリ-host_apps)
  - [ホストアプリの再起動 (host_app_restart)](#ホストアプリの再起動-host_app_restart)
- [外部機器接続時のアドレッシング](#外部機器接続時のアドレッシング)
- [ログ出力ディレクトリ](#ログ出力ディレクトリ)
- [ランタイム成果物](#ランタイム成果物)
- [自動テスト (非対話モード)](#自動テスト-非対話モード)
- [ログ集計](#ログ集計)
  - [ログファイル名のスキーマ](#ログファイル名のスキーマ)
  - [CSV のカラム構成](#csv-のカラム構成)
- [アーキテクチャ](#アーキテクチャ)
  - [トポロジスクリプトの構造](#トポロジスクリプトの構造)
  - [ノードロール](#ノードロール)
  - [ホスト設定テンプレート](#ホスト設定テンプレート)
  - [主要な関数](#主要な関数)
- [プロジェクト構成](#プロジェクト構成)
- [よくある変更](#よくある変更)
- [継続的インテグレーション (CI)](#継続的インテグレーション-ci)
- [セキュリティに関する注意](#セキュリティに関する注意)
- [ドキュメント](#ドキュメント)

## 概要

ReCefore は、Ubuntu 22.04 上で Cefore（コンテンツ指向ネットワーキングフレームワーク）の動作検証を行うための Mininet ベースのネットワークエミュレータです。Cefore デーモン（*cefnetd*）を実行する仮想ホストを持つ仮想ネットワークトポロジを構築し、コンテンツ配信シナリオをシミュレートします。

> **名前について:** ReCefore はツールの名前ですが、コードの改称はまだ済んでいません。リポジトリ（`cefore-emu-sslab`）、パッケージ（`cefore-emu`）、コマンド（`ceforeemu`、`ceforeemu-log`、`ceforeemu-connect`）は現在の名前のままなので、この先の記載どおりに使ってください。

統一 CLI から 3 種類のトポロジを利用できます：

| サブコマンド | 説明 |
|------------|------|
| `linear` | 線形トポロジ（コンシューマ−ルータ−パブリッシャの連鎖） |
| `mesh` | マルチパス FIB を持つランダムメッシュトポロジ |
| `disaster` | 定期的なホスト障害・帯域制御・外部インタフェース接続を持つメッシュトポロジ |

4 つ目のトポロジである、物理 Cefore 機器と接続する外部ネットワークメッシュはサブコマンドではなく、専用のエントリポイント `ceforeemu-connect` から使います。

## 前提条件

- Ubuntu 22.04 に Cefore がインストール済みであること
- Mininet バージョン 2.3.0 ([https://mininet.org/](https://mininet.org/))
- Python >= 3.12
- curl（`compute_call` イベントに必要）
- uv（Python のパッケージ管理に必要）

```bash
uv sync   # 依存パッケージのインストール
```

**Python の依存パッケージ**（`pyproject.toml` で管理）:

- `flask>=3.1.3`（WebUI のライブダッシュボード）
- `mininet>=2.3.0.dev6`
- `networkx>=3.6.1`（トポロジのアルゴリズムと PNG 出力）
- `matplotlib>=3.10.8`（PNG 出力）
- `pyyaml>=6.0`（YAML 設定のサポート）
- `scipy>=1.17.1`

`pyproject.toml` の `[project.scripts]` を変更したら、`uv pip install -e .` を実行して新しい CLI エントリポイントを登録してください。

## クイックスタート

```bash
# 線形トポロジ（デフォルト 5 ホスト）
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

スイッチで接続されたホストのランダムメッシュです。各宛先ホスト hX はプレフィックス `ccnx:/test/example{X+1}` にマッピングされ、k 最短パスを FIB に使用します。

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

定期的なホストの停止/復旧サイクル、帯域制御、外部インタフェースの接続、およびイベント駆動のコンテンツ操作を持つメッシュトポロジです。

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
| `--bridge switch,root_ip,local_routes[,ext_routes,gateway]` | ルート名前空間ブリッジ（繰り返し指定可） |
| `--config` | JSON/YAML 設定ファイル |
| `--no-cli` | 非対話モード |
| `--duration` | 評価時間（秒、`--no-cli` と併用） |
| `--results-json` | 取得結果を JSON に書き出す |

## 設定ファイル

`--config` で JSON または YAML から設定を読み込みます。YAML サポートには `pyyaml` が必要です。

トップレベルの `puts`、`gets`、`auto` は警告を出して無視されます。コンテンツ操作はすべて `events` に書いてください。

全パラメータは `config/examples/example.yaml` を参照してください。

### コンテンツ操作 (JSON)

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

> **既知の制約:** 上の pubsub ペアは例示です。15 ホスト / 48 スイッチの mesh では `cefpubfile`/`cefsubfile` が決定的に失敗します（publisher が Trigger Interest を受信できないまま deadline で終了）。同じトポロジで put/get は成功します。成功率は hop 距離とともに下がります（hop 1 は成功、hop 3 は一度も成功せず）。pubsub が検証済みなのは 3〜5 ホストの mesh だけなので、この失敗を意図的に再現する場合を除き、pubsub 実験はその範囲で行ってください。[docs/known-cefore-behaviors.md](docs/known-cefore-behaviors.md) の「pubsub が 15-host mesh で系統的に失敗」を参照してください。

### タイムドイベント (YAML)

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

サポートされるイベントタイプ: `link_down`, `link_up`, `fib_add`, `fib_del`, `fib_enable`, `bw_set`, `compute_call`, `put`, `get`, `pubsub_sub`, `pubsub_pub`, `ccninfo`, `host_app_restart`。

disaster の `put` イベントでは、`expiry` と `cache_time` の省略時にどちらも `3000` を Cefore コマンドへ渡し、events 移行前の挙動を保ちます。pub/sub の publication オプションは暗黙補完せず、`pub_opts.expiry` / `pub_opts.cache_time` の省略時は Cefore コマンドの既定値を使います。

### compute_call イベント

`compute_call` は edge-compute のオフロードを模擬します。ホストが HTTP リクエストを発行し、必要に応じてレスポンスを保存して ICN へ再発行します。

| オプション | 詳細 |
|---|---|
| `host` | リクエストを発行するホストのインデックス（必須） |
| `endpoint` | HTTP リクエストの URL（必須） |
| `method` | GET/POST、既定は GET |
| `payload` | 任意の文字列 |
| `headers` | 任意の str→str の dict |
| `timeout` | 秒で指定し、既定は 30。curl とコマンドの deadline の両方の上限になります |
| `output_file` | レスポンスの保存先（実行ディレクトリ配下） |
| `publish_uri` | 保存したレスポンスを cefputfile で ICN へ再発行します。`output_file` が必須です |
| `pub_opts` | put と同じ cefputfile のオプションを渡せます。未知のキーは拒否します |
| `publish_timeout` | cefputfile の実行には専用の deadline があります。正の数で、既定は 120 秒です。発行速度を決めるのは `rate` であって HTTP の timeout ではありません |

`pub_opts` のキー:

- `rate`（0.001 Mbps 以上）
- `block_size`（60 以上の整数）
- `expiry`/`cache_time`（1 以上、既定 `3000`）
- `valid_algo`（crc32c/rsa-sha256）
- `port_num`（1 以上の整数）

成功判定は厳密で、curl の exit が 0、HTTP が 2xx、さらに再発行する場合は cefputfile の exit が 0 でどちらの実行も timeout も cancel もしていないこと、をすべて満たしたときだけ成功です。

results.json のレコードは三値の `outcome` と `detail` dict（`http_status`、`curl_exit`、`publish_ok`、`output_file`）を持ちます：

- `ok`
- `not-ok`（HTTP の失敗、または再発行の失敗 / timeout / cancel）
- `skipped-no-result`（環境要因。endpoint に到達できない（curl exit 5/6/7/28）、または HTTP の実行が timeout / cancel した場合）

関連する挙動：

- `publish_uri` を持つ compute_call は disaster シナリオのパブリッシャ情報（publisher metadata）にも加わるので、事前設定される FIB によってコンシューマから再発行されたコンテンツへの経路が引かれます。
- `repeat` は `interval`/`count` のみをサポートします（restore 形式と未知のキーは拒否します）。
- ok 経路は `tests/synthetic/` の root 限定テスト（hermetic 版と HPC を使う版）で検証しています。手順は `docs/runbooks/compute-ok-path.md` を参照してください。

### ceforeemu-connect でのイベント

`ceforeemu-connect` は `put` と `pubsub_pub` イベントのみを、パブリッシャの判定、URI 別 FIB の設定、CLI 開始前の publication の seed に使います。`get`、`pubsub_sub`、`ccninfo` は自動実行せず警告を出します。トップレベルの legacy content key は復活しません。

### モニタリング

```yaml
monitoring:
  interval: 5
  output_json: "monitor.json"
  output_csv: "monitor.csv"
  targets:
    - {type: cefstatus, hosts: "all"}
    - {type: csmgrstatus, hosts: "cache"}
    - {type: ccninfo, hosts: [0], uri: "ccnx:/test/sample", cache_info: true}
```

### キャッシュ設定 (cache_config)

指定すると legacy の `cache_count`/`cache_default_rct_ms` より優先されます。

```yaml
cache_config:
  strategy: "k_centers"    # k_centers / manual / degree_based / random
  default:
    count: 3
    capacity: 819200
    default_rct_ms: 1800000
    algorithm: "LRU"       # LRU / LFU / FIFO / None
    type: "memory"         # memory / filesystem
```

### 障害シナリオ (failure_scenarios)

指定すると legacy の `down_interval`/`down_duration` 等より優先されます。

```yaml
failure_scenarios:
  strategy: "cyclic"       # simple / cyclic / random / manual
  cycles:
    - {interval: 30, duration: 10, count: 2}
```

### ルーティング戦略 (routing)

```yaml
routing:
  strategy: "dijkstra"     # dijkstra / shortest_path / ecmp
```

### 明示的トポロジ (links)

config ファイル専用（CLI オプションなし）で、`disaster` でのみ使えます。`connect` はトポロジ構築のコードを機械的に共有していますが、その config は `links` キーを無条件に拒否します。connect のブリッジ/k-centers によるキャッシュ配置の経路に、明示リンクのトポロジを対象にしたテストがないためです。seed から生成するランダムな MeshTopo の代わりに、メッシュの形をそのまま固定します。省略した場合のランダムメッシュの挙動は、このオプションの導入前と完全に同じです。

```yaml
links:
  - [0, 1]
  - [1, 2]
```

- 各ペアは 0 始まりのホストインデックスです。
- ペアごとにスイッチを 1 台作るので、`link_down`/`link_up` イベント（`nodes: [a, b]`）は必ずそのペアだけを指します。
- `links` はすべてのホスト `0..hosts-1` を含む連結グラフでなければならず、そうでない場合は config の検証が具体的な問題を示して拒否します：
  - インデックスが範囲内であること
  - 自己リンクがないこと
  - 重複ペアがないこと
  - 孤立したホストがないこと
  - リンクが 255 本以下であること
  - ホストインデックスが 253 以下であること（リンクごとに `/24` を 1 つ割り当て、`host_idx + 1` を第 4 オクテットにするアドレス体系では、これ以上の余地がありません）
- `switches`、`node_per_switch`、`host_degree_min`、`host_degree_max`、`switch_use_all` が制御するのはランダムメッシュの構築だけです。`links` と一緒にこれらのいずれかへ既定以外の値を指定すると、黙って無視せず config エラーとして拒否します（未指定か既定値のままにしてください）。
- `links` を指定すると、`bridges[i].switch` のインデックスは `switches` ではなく `len(links)` に対して検査されます。スイッチ数を実際に決めるのが `links` だからです。
- `link_down`/`link_up` サイクルを含む 3 ホストの線形構成の例は `config/examples/min_explicit_line.yaml` を参照してください。

### 静的プレフィックスルート (prefix_routes)

config ファイル専用（CLI オプションなし）で、`disaster` でのみ使えます。これを読むのは `DisasterScenario.configure` だけなので、`connect` は `links` と同じように拒否します。

```yaml
prefix_routes:
  "ccnx:/test/to-h2": 2
  "ccnx:/test/to-h0": 0
```

- 各エントリは、指定したホスト以外のすべてのホストにそのホストへ向かう FIB ルートを与えます。ルートの計算には他のルートと同じ最短経路/ネクストホップのロジック（`core.fib.compute_fib_for_uris`）を使います。
- put/pubsub_pub の publisher と違い、`prefix_routes` のエントリは片方向だけです（Reflexive-Forwarding の戻りルートを生成するものはありません）。
- 同じ config に publisher があるかどうかには依存しません。`put`/`pubsub_pub` イベントの有無にかかわらずルートは必ず計算されます（実際の publisher からのルートには影響せず、引き続き両方向が設定されます）。
- キーは空でない `ccnx:/` URI 文字列、値は範囲内の整数のホストインデックスでなければなりません。
- インストールされた FIB を `debug.artifacts: [fib_dump]` で取得する 3 ホストの線形構成の例は `config/examples/min_prefix_routes.yaml` を参照してください。

### 転送戦略設定 (forwarding_config)

config ファイル専用（CLI オプションなし）。`disaster` / `connect` ブロックで有効です。

```yaml
forwarding_config:
  default: "flooding"       # default / flooding / shortest_path
  nodes:
    - {id: [3, 5], strategy: "shortest_path"}
```

`cefnetd` 起動前に各 `hN/cefnetd.conf` の `FORWARDING_STRATEGY` として書き込まれます（起動後の書き換えは反映されません）。`nodes` の指定は該当ホスト ID について `default` を上書きします。`default` を省略した場合はテンプレートの初期値と同じ `"flooding"` になります。

### ホストアプリ (host_apps)

config ファイル専用（CLI オプションなし）。任意の常駐プロセスをホストごとに 1 つ以上、cefnetd/csmgrd の起動後に開始し、teardown が cefnetd/csmgrd を止める前に停止します（`DaemonFleet` の start/stop と同じ形で、各ホストの停止は独立しており、失敗があっても残りを中断せず集約します）。ReCefore はアプリの中身や目的を一切関知せず、4 つのプレースホルダを展開して `CommandRunner.start` で argv を起動・停止するだけです。

```yaml
host_apps:
  - hosts: [0, 1, 2]        # または "all"
    argv: ["sh", "-c", "echo {node} {t0_ms} > {node_dir}/marker"]
    cwd: "{node_dir}"                       # 任意
    env: {CEFORE_DIR: "{cefore_conf_dir}"}   # 任意
    log: "{node_dir}/{node}.log"             # 任意
```

- `env`: `CommandRunner.start` には env 引数がないので、`env K=V ...` という argv の接頭辞になります。
- `log`: `hosts` が `"all"` または複数ホストのときは `{node}`、`{node_dir}`、`{cefore_conf_dir}` のいずれかを含める必要があります。含めないと全ホストが同じファイルを上書きしてしまいます。

`argv`/`env`/`cwd`/`log` で展開されるプレースホルダ：

| プレースホルダ | 値 |
|---|---|
| `{node}` | ノード名（`h3`） |
| `{node_dir}` | そのホストのディレクトリの絶対パス |
| `{cefore_conf_dir}` | そのホストの `cefnetd.conf` があるディレクトリの絶対パス。cefpyco の `create_handle(ceforedir=...)` に渡す値です。今は `{node_dir}` と同じですが、意図して別の名前にしています |
| `{t0_ms}` | スケジューラが `at: 0` とみなす瞬間に取得した epoch ミリ秒。ホストアプリ自身の相対時刻の計算がスケジュールされたイベントと揃います |

実行できる例は `config/examples/min_host_apps.yaml` を参照してください。

### ホストアプリの再起動 (host_app_restart)

```yaml
events:
  - {at: 30, type: host_app_restart, host: 2, downtime_s: 5}
```

- `link_down`/`link_up` と並ぶスケジュールイベントで（`host_apps:` のフィールドではありません）、1 つのホストに設定されたすべての `host_apps:` プロセスを停止してから再起動します。「時刻 t にホスト N のアプリケーションがクラッシュ/再起動する」状況を YAML で記述するための汎用プリミティブです。
- `host` は必須です。`downtime_s`（停止から再起動までの間隔）は任意で、有限の値でなければならず、既定は 0 です。
- `host_apps:` のエントリが対象にしていない `host` は config の検証で拒否します。
- `failure_scenarios`（または legacy の `down_interval`/`down_duration`）による周期的なホスト停止/復旧のフラップとは無関係です。あちらはリンク状態を切り替えるだけで `host_apps:` のプロセスには触れません。その穴を埋めるのが `host_app_restart` です。
- 再起動したプロセスには、最初の起動時とまったく同じ `argv`/`cwd`/`env` と `{t0_ms}` が渡されます（再展開も再取得もしません）。違うのはログのパスだけで、`.lifeN` という接尾辞（`N` >= 2）が付くので、再起動後のログが前回の出力を上書きして消すことはありません。
- スケジューラのスレッドは `downtime_s` の間ずっとブロックするので、その間に発火する予定だった他のイベントはその分だけ遅れます。ReCefore のシングルスレッドの `EventScheduler` では、遅いハンドラならどれでも同じコストが生じます。
- `results.json` のレコードは `link_down`/`link_up` と同じ形の単純な成功/失敗のイベント行です（三値の `outcome` はありません）。
- 実行できる例は `config/examples/min_host_app_restart.yaml` を参照してください。

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

## ログ出力ディレクトリ

ログは `--output-dir`（デフォルト: `logs`）の下の専用ディレクトリに整理されます。ディレクトリ名は、`num` を指定した場合（設定ファイルまたは `--num`）は `ex{num}_seed{seed}`、それ以外は `seed{seed}` です：

```text
logs/ex{num}_seed{seed}/
├── script.log              # スクリプト実行ログ
├── ex{num}_seed{seed}_h{hosts}.png  # トポロジ図
├── meta.json               # 設定スナップショット
├── cefnetd_<port>_<sockid>.log  # /tmp から収集された cefnetd ログ
├── csmgrd_<port>_<sockid>.log   # /tmp から収集された csmgrd ログ
├── cefputfile_*.log        # cefputfile ログ
├── cefgetfile_*.log        # cefgetfile ログ
├── *recvfile_*             # 受信ファイル
└── results.json            # 取得結果（--results-json 使用時）
```

```bash
# 実験番号の付いたログディレクトリに出力
sudo .venv/bin/python3 -m src disaster --num 1 --hosts 10 --switches 15 --seed 42

# 出力ディレクトリをカスタム指定
sudo .venv/bin/python3 -m src disaster --config config.yaml --output-dir experiments

# ディレクトリ名にタイムスタンプを付加
sudo .venv/bin/python3 -m src disaster --config config.yaml --timestamp
```

## ランタイム成果物

スクリプトを実行すると、実行ディレクトリに次のファイルができます。`num` なしで `--output-dir ""` を指定するとカレントディレクトリで実行され、その場合 `/tmp` のデーモンログは収集されません。

- `cefnetd_<port>_<sockid>.log` — `/tmp` から収集された転送デーモンのログ
- `csmgrd_<port>_<sockid>.log` — `/tmp` から収集されたキャッシュマネージャのログ
- `cefputfile_*.log` — パブリッシャの操作ログ
- `cefgetfile_*.log` — コンシューマの操作ログ
- `recvfile_at_h0` / `recvfile_at_hN` — 取得したコンテンツファイル（linear、mesh）
- `{phase}_recvfile_h{host}_{label}` — 取得したコンテンツファイル（イベント駆動の実行）
- `ex{num}_seed{seed}_h{hosts}.png` — mesh、disaster、connect の実行で作られるトポロジの可視化画像（`num` なしでは `seed{seed}_h{hosts}.png`。`--topo-png` でパスを変更できます）

## 自動テスト (非対話モード)

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

自動テストモードのイベントの `at` は、実験開始時に確定する単一の絶対時計を基準にします。seed put、warmup、failure/evaluation の順は維持され、warmup 中に予定時刻を過ぎた evaluation イベントは、遅延の警告とともに直ちに実行されます。自動テストの `put` に repeat は指定できません。`duration` は failure/evaluation フェーズ開始後の観測時間のままで、evaluation イベントがなく `duration: 0` の場合は failure フェーズを開始しません。

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

### ログファイル名のスキーマ

すべてのコンテンツログは、`src/core/artifacts.py` が管理する単一の canonical パターンに従います（2026-07-03 の artifact-layout 変更により、以前の host+content / disaster / legacy パターンは書き出しも解析もされなくなりました）：

| パターン | 例 | 抽出されるフィールド |
|---------|---------|-----------------|
| canonical | `cefgetfile_eval_h4_test_sample.log` | command, phase, host, label |

ファイル名に含まれない操作の文脈（URI、成否、停止中のホスト）は、同じディレクトリの `results.json` から `log_file` キーで結合します。

### CSV のカラム構成

**共通メタデータカラム（meta.json + ファイル名 + results.json 由来）:**

| カラム | 取得元 |
|--------|--------|
| experiment_dir | ディレクトリ名 |
| num, hosts, switches, seed, k | meta.json |
| down_interval, down_duration, down_count, down_stagger, down_exclude, cache_count, forwarding_default | meta.json |
| filename, host_id, phase, label | ファイル名 |
| down_hosts, publisher_down | results.json との結合 |

**コマンド固有のカラム:**

| コマンド | カラム |
|---------|---------|
| `cefputfile` | timestamp, uri, file, rate_mbps, block_size_bytes, cache_time_sec, expiration_sec, tx_frames, tx_bytes, duration_sec, throughput_bps, success |
| `cefgetfile` | timestamp, uri, rx_frames_all, rx_frames_content, rx_bytes_all, rx_bytes_content, duration_sec, throughput_bps, goodput_bps, jitter_ave_us, jitter_max_us, jitter_var_us, success |
| `cefsubfile` | timestamp, uri, rx_frames_all, rx_frames_content, rx_bytes_all, rx_bytes_content, duration_sec, throughput_bps, goodput_bps, jitter_ave_us, jitter_max_us, jitter_var_us, success |
| `cefpubfile` | timestamp, uri, file, rate_mbps, block_size_bytes, cache_time_sec, expiration_sec, trigger_interest_sent, trigger_data_received, success |

カラムは `src/log/schema.py`（`COMMAND_SCHEMAS`）でコマンドごとにスキーマとして定義しており、動的には検出しません。

- `cefsubfile` のメトリクスは `cefgetfile` と同じです。
- `cefpubfile` は put 側の設定メトリクスに加えて、2 つの存在マーカー（`trigger_interest_sent`/`trigger_data_received`。"Send Trigger Interest." / "Receive Trigger Data, finish application." のログ行に由来）を持ちます。

`cefpubfile` と `cefsubfile` では、スキーマにない未知の `Key = Value` 行も解析され、stderr に警告を出したうえでスキーマのカラムの後ろに追加されます。

## アーキテクチャ

### トポロジスクリプトの構造

トポロジスクリプトはいずれも共通のパターンに沿っています：

1. **トポロジ定義** — Mininet の Topo サブクラスがネットワーク構造を定義します
2. **IP アドレス割り当て** — 各リンクに /24 サブネット（192.168.X.Y）を割り当てます
3. **Cefore デーモンの起動** — csmgrd（キャッシュマネージャ）と cefnetd（転送デーモン）を起動します
4. **FIB 設定** — `cefroute add` で転送ルールを設定します
5. **コンテンツ操作** — パブリッシャが `cefputfile` を、コンシューマが `cefgetfile` を実行します
6. **クリーンアップ** — デーモンを停止し、一時的なホストディレクトリを削除します

### ノードロール

| ロール | ホスト | テンプレートの CS_MODE | 説明 |
|------|-------|------------------|------|
| コンシューマ | h0（最初） | 0 | `cefgetfile` でコンテンツを要求します |
| ルータ | 奇数番号 | 2 | Interest/コンテンツを転送し、`csmgrd` を実行します |
| パブリッシャ | 最後のホスト | 1 | `cefputfile` でコンテンツを保存・配信します |

この表は一般的な場合を示したもので、厳密なルールは `assign_roles()`（`src/core/roles.py`）にあります。そのうえで `apply_cache_node_settings()`（`src/runtime/template.py`）がテンプレートの値を上書きします。キャッシュノードは `CS_MODE=2` に、キャッシュノードでないパブリッシャは `CS_MODE=1` に強制され、それ以外のキャッシュノードでないノードはテンプレートが 2 なら `CS_MODE=0` に下がります。

### ホスト設定テンプレート

テンプレートは `config/templates/` にあります：

- `h0/` — コンシューマのテンプレート（CS_MODE=0、キャッシュなし）
- `h1/` — ルータのテンプレート（CS_MODE=2、外部キャッシュマネージャ）
- `h2/` — パブリッシャのテンプレート（CS_MODE=1、ローカルキャッシュモード）

各ホストのディレクトリ（h0, h1, ...）はテンプレートのコピーで動的に生成され、スクリプト完了後に `cleanup_node_dirs()` で削除されます。

**ホストごとの設定ファイル:**

- `cefnetd.conf` — 転送デーモンの設定（LOCAL_SOCK_ID を含む）
- `cefnetd.fib` — 静的な転送テーブル
- `csmgrd.conf` — キャッシュマネージャの設定
- `conpubd.conf` — パブリッシャデーモンの設定
- `plugin.conf` — プラグインの設定
- `cefnetd.key` — 鍵の設定
- `default-private-key`, `default-public-key` — 暗号鍵（機密情報）

### 主要な関数

**IP アドレス割り当て:**

- 線形トポロジ: 連番の /24 サブネット（192.168.0.x, 192.168.1.x, ...）
- メッシュトポロジ: リンクごとに /24 を 1 つ割り当て、ホスト ID が最終オクテットを決めます

**FIB 設定（`src/core/fib.py`、`src/runtime/net_config.py`）:**

- 線形: すべての Interest をパブリッシャ方向（列の次ホップ）へ転送します
- メッシュ: 送信元ごとの Dijkstra で効率よくマルチパスルーティングします
  - `dijkstra_all()`: ある送信元からすべての宛先への最短距離を計算します（`src/core/graph.py`）
  - `shortest_path()`（`src/core/graph.py`）: エッジ/ノードの禁止に対応した Dijkstra アルゴリズム（制約付き経路探索）
  - `k_shortest_paths()`（`src/core/graph.py`）: k 本の代替経路を求める Yen のアルゴリズム
  - `compute_fib()`: 既定の URI パターン `ccnx:/test/exampleN` で、すべての宛先の FIB エントリを計算します
  - `compute_fib_for_uris()`: 特定の URI とパブリッシャの対応（publication イベント）について FIB エントリを計算します
  - `apply_fib()`: 計算した FIB エントリを `cefroute add` で稼働中の Mininet ホストに適用します（`src/runtime/net_config.py`）

**動的な設定（`src/runtime/template.py`、`src/core/roles.py`）:**

- `update_local_sock_id()`: ソケットの衝突を避けるため、設定ファイルの LOCAL_SOCK_ID を書き換えます
- `provision_node_dirs()`: 指定されたロールの対応からテンプレートをもとにホストディレクトリを作ります。失敗すると `NodeDirError` を送出し、途中までの作業を巻き戻します
- `assign_roles()`: ホストインデックスごとに `NodeRole`（CONSUMER/ROUTER/PUBLISHER）を決めます。各 `NodeRole` は `.template` 属性（`"h0"`、`"h1"`、`"h2"` のいずれか）を持ちます

**コンテンツ操作（`src/runtime/cefore.py` で定義）:**

- `run_cefputfile()`: オプションを指定して cefputfile でコンテンツを発行します
- `run_cefgetfile()`: オプションを指定して cefgetfile でコンテンツを取得します
- `run_cefpubfile()`: cefpubfile でコンテンツを発行します（pub/sub モデル、CommandHandle を返します）
- `start_cefsubfile()`: cefsubfile でコンテンツを購読します（pub/sub モデル、CommandHandle を返します）

**ステータス/情報コマンド:**

- `run_csmgrstatus()`: csmgrstatus でキャッシュマネージャの状態を問い合わせます
- `cefroute_del()`（`src/runtime/net_config.py`）: `cefroute del` で FIB エントリを削除します
- `cefroute_enable()`（`src/runtime/net_config.py`）: `cefroute enable` で FIB エントリを有効にします

## プロジェクト構成

```text
cefore-emu-sslab/
├── src/                 # メインソースコード（python -m src エントリポイント）
│   ├── cli/             # CLI インタフェースと引数解析
│   ├── core/            # コアロジックとアルゴリズム
│   │   └── config/      # JSON/YAML 設定の読み込みと検証
│   ├── log/             # ログ解析と CSV 集計
│   ├── runtime/         # 稼働中のホストとデーモンに対するランタイム操作
│   ├── scenarios/       # シナリオ実装（linear, mesh, disaster, connect）
│   └── webui/           # WebUI ライブダッシュボード
├── config/
│   ├── templates/       # ホストテンプレート（h0, h1, h2）
│   └── examples/        # 設定例（YAML/JSON）
├── tools/
│   ├── autotest/        # バッチ実験ランナーと結果解析
│   └── workshop/        # ワークショップの実験ランナー、プロット、レポート
├── tests/               # テストスイート
├── docs/                # ADR、runbook、Cefore の既知の挙動
├── sample-putfile       # テストデータ
├── buffer.sh            # UDP バッファ設定
└── pyproject.toml       # パッケージ設定
```

## よくある変更

**ホストロールを追加する:**

`src/core/roles.py` の `assign_roles()` を変更し、インデックスとホスト数に応じて適切な `NodeRole`（CONSUMER/ROUTER/PUBLISHER）を返すようにします。各 `NodeRole` は `config/templates/hN` ディレクトリに対応する `.template` 属性を持ちます。

**コンテンツ URI を変更する:**

`compute_fib()` / `compute_fib_for_uris()`（`src/core/fib.py`）の URI プレフィックスと、対応する `cefputfile`/`cefgetfile` コマンドを更新します。disaster トポロジでは、JSON/YAML の config に `events` でコンテンツ操作を定義してください。

**キャッシュの挙動を調整する:**

`config/templates/h1/csmgrd.conf` を編集します（すべてのルータノードに適用されます）。

**リンク障害を試す:**

- 基本: `src/runtime/links.py` の `link_down()` / `link_up()` を使います
- 応用: disaster トポロジで `--down-*` オプションか config ファイルの `failure_scenarios` を使います

## 継続的インテグレーション (CI)

`main` への PR と `main` への push ごとに、GitHub Actions（`.github/workflows/ci.yml`）が単体テストレベルのゲートを実行します。カバレッジ下限（`fail_under=85`）付き pytest、ruff、mypy（デフォルト設定でエラー 0 件）、`uv lock --check`、entry-points のインストール検査です。Mininet を実際に起動する E2E の検証は意図的に CI に含めておらず、ローカルの root スモークテスト一式（cefore-run-tests）が引き続きそのゲートを担います。決定の記録は [docs/adr/0004](docs/adr/0004-ci-guards-unit-surface-only.md) を参照してください。

## セキュリティに関する注意

- `config/templates/h*/default-private-key` ファイルには機密性の高い暗号鍵素材が含まれています
- Mininet のネットワーク名前空間操作のため、すべてのスクリプトは root 権限が必要です
- 信頼された隔離環境（VM 推奨）でのみ実行してください

## ドキュメント

- [CONTEXT.md](CONTEXT.md) - プロジェクト用語辞書（ドメイン言語）
