# ccninfo characterization fixtures

実機採取した `ccninfo` (Cefore 0.12.0 系, `/usr/local/bin/ccninfo`) の stdout+stderr 生キャプチャ。
採取日: 2026-07-27。採取環境: 本リポジトリの disaster シナリオ (3 hosts mesh k=1,
put→get 済み)。各ファイル末尾の `EXIT=<rc> ELAPSED_MS=<ms>` 行は採取スクリプトが追記した
メタ情報で、ccninfo 自身の出力ではない (パーサは未知行として無視する耐性契約の検証を兼ねる)。

## 採取時の重要な実測知見

- **上流バグ2 (multi-hop 無応答の真因)**: 発信ノードの cefnetd が csmgrd キャッシュヒット
  (CS_MODE=2) かつ `-c` なしのとき、`cefnetd_external_cache_seek` の else 分岐
  (cef_netd.c:5487, Cefore 0.12.0) が `pkt_len` にネットワークバイトオーダ値を読み戻し、
  壊れた reply を送ってクライアント側検証で棄却される。回避: 発信ノードを非キャッシュ
  (CS_MODE=0) にするか `-s 1` 以上を使う。reply_multihop.out はこの回避構成で採取。

- **CEFORE_DIR workaround 必須**: ccninfo クライアントは `-d` を `cef_client_init()` より後に
  解釈する上流バグがあり、既定では `/usr/local/cefore/cefnetd.conf` の LOCAL_SOCK_ID で
  ソケットを決めてしまう。マルチノード環境では
  `env CEFORE_DIR=<dir>` (`<dir>/cefore/cefnetd.conf` に対象ノードの conf を配置) で回避。
- reply があっても即終了せず CCNINFO_REPLY_TIMEOUT+1 (~5s) 走り切る (ELAPSED_MS 参照)。
- 引数エラー (`-s 0`, `-s >= -r`) は usage を出して **exit 0**。
- responder/route のノード表記は cefnetd.conf の NODE_NAME 依存:
  未設定なら IP (reply_basic/reply_cache_info)、設定時はその名前 (reply_named_cache)。

## ファイル一覧

| file | 内容 | 採取コマンド |
|---|---|---|
| reply_basic.out | reply あり・route のみ (IP 表記) | `ccninfo ccnx:/test/event_sample -d ./h1` (self-query) |
| reply_cache_info.out | reply あり・`-c` cache ブロック付き (IP 表記) | 同上 + `-c` |
| reply_named_cache.out | reply あり・`-c`・NODE_NAME=h1 設定時 (名前表記) | 同上 (NODE_NAME 設定後) |
| reply_multihop.out | reply あり・route 2 hops (h0→h2, NODE_NAME 表記) | `ccninfo ccnx:/test/event_sample -d ./h0` (h0 を CS_MODE=0 にした構成) |
| no_reply_timeout.out | 応答なしタイムアウト (ヘッダのみ) | `ccninfo ccnx:/no/such/prefix -d ./h0` |
| s0_rejected.out | `-s 0` 拒否 (usage + exit 0) | `... -s 0` |
| skip_ge_hop.out | `-s >= -r` 拒否 (usage + exit 0) | `... -r 3 -s 5` |

**注意**: reply_basic, reply_cache_info, reply_multihop は ELAPSED_MS 採取レシピ
導入前に採取されたため EXIT= のみ持つ (ELAPSED_MS= は含まない)。テストで
タイミング値を参照する場合はこの点に注意すること。
