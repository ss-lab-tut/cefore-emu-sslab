---
status: closed
type: task
claimed-by:
blocked-by: []
---
## Task

**compute_call ok 経路の自動テスト整備**:
`compute_call` イベント（edge-side HTTP モデル、ADR-0003、PR #17 で実装済み）の **ok 経路**
（HTTP 2xx → `output_file` 保存 → `publish_uri` を cefputfile → 別ホストの cefgetfile でバイト一致）は、
unit（FakeCommandRunner 上の判定ロジック 16 本）と smoke（`min_compute.yaml` の到達不能 →
`skipped-no-result` 一点）でしか守られておらず、ライブ証跡はコミット 6d02e84 の手動確認一回のみ。
`min_compute.yaml` コメント内の手動 runbook は書き直し後（44ca61d）の文面を実行した記録が無い。
ok / not-ok が実機で壊れても smoke は緑のまま通る。

2 段構えの root-gated pytest（`tests/synthetic/`、`CEFEMU_SYNTHETIC_ROOT=1` かつ root）で ok 経路を証明する:

1. **hermetic 版**（この機だけで完結）: 手書き 1 スイッチ・2 ホスト（h0=CONSUMER が echo サーバと cefgetfile、
   h1=PUBLISHER が compute_call と cefputfile = ICN publisher）。scheduler の handler を直接呼び
   `EventOutcome(outcome="ok", detail.publish_ok=True)` と、echo サーバが配った payload ==
   `output_file` == h0 の cefgetfile 出力、の三者バイト一致まで assert する。
2. **HPC 版**（`CEFEMU_COMPUTE_ENDPOINT` が設定された時だけ）: 研究室 HPC（`hpc-debian`）を
   Compute endpoint とし、bridges（`nat: true` + `vm_host_network`）の root ns MASQUERADE 経由で同じ到達点を取る。

同じ stdlib-only の echo サーバ `tools/compute_echo_server.py` を、hermetic 版では Mininet ホスト内で、
HPC 版では HPC 上で動かす。DisasterScenario / autotest mode は経由しない（autotest は bridges を禁止するため）。

_Avoid_: ICN-routed compute（ADR-0003 の model 2）へ育てること、GPU 推論を行う実サービスをテストの
endpoint にすること（決定性が成り立たない。参照アプリは [22](22-application-adapter-api.md) 側）、
`cleanup_all()` / `BaseScenario.execute()` をテストから呼ぶこと（`mn -c` を全システムに撃つ）、
bridge config に `external_routes` を使うこと（実機の `/etc/resolv.conf` を復元無しで上書きする）

計画の全文（決定事項 Q1〜Q13、レビュー記録）は作業セッションの一時ファイル `/tmp/explore-grill-build/dcfcedb8/compute-ok-path.md`
（消えている可能性あり。要点は本 ticket と PR 本文に写してある）。

## Status (2026-09-26)

- 2026-09-25 着手。map.md の優先順（frontier は [01](01-s4-pub-lifetime-by-uri.md)）を上書きして先行
  （研究室 HPC を実 Compute endpoint として使えるようになったため）。
- PR (1) docs 鏡写し（README_ja の compute_call 段落、CONTEXT.md「Event outcome」）: **merged**（PR #28, 1ff89e7）。
- PR (2) `feat/compute-ok-path-synthetic`: 本 ticket、map.md、CONTEXT.md「Compute endpoint」、
  `tools/compute_echo_server.py` + unit、hermetic 版テスト: **merged**（PR #29）。
- PR (3) `feat/compute-ok-path-hpc`: HPC 版テスト、`docs/runbooks/compute-ok-path.md`、cefore-run-tests skill への
  任意ステップ追記、README 両言語からの参照、`min_compute.yaml` コメント runbook の差し替え: **merged**（PR #30, 2026-09-26）。本 ticket は完了、Follow-up は下記のとおり残す。
  HPC 版の初回実行で `BridgeManager.add_host_route` の実バグを発見（2026-09-25）: 非 default 宛先に
  net-tools の `route add -net <dest>` を使っており `/32` は `SIOCADDRT: Invalid argument` で拒否される。
  戻り値を捨てていたため無言で経路無しになっていた（`vm_host_network` / `external_routes` に `/32` を書いた
  既存 config も同じ）。**host 側（`add_host_route`）のみ** iproute2（`ip route add`、既存経路は上書きせず
  warning、cleanup は成功時だけ登録）へ揃える修正を PR (3) に含める。root ns 側（`add_root_route` /
  `connect_to_root_ns`）は net-tools のまま（Follow-up）。
  NAT 経路そのもの（MASQUERADE + FORWARD + ip_forward + root ns 経路）は成立しており、plan の
  ssh -L fallback は不要だった。
- 計画レビュー（2026-09-25）: Workflow 3 体 + opencode 独立レビューが同じ blocker（bridge config の `nat: true`
  欠落。`setup_bridges` は opt-in、`bridge_root.py` の `use_nat = config.get("nat", False)`）と同じ major
  （`external_routes` の resolv.conf 上書き）を指摘、計画に反映済み。

## Follow-up（本 ticket の scope 外として記録）

- autotest mode が `ext`/`bridges` を禁止する理由（`disaster.py` の `sys.exit`）はコード・コミット・ADR の
  どこにも明文化されていない。ユーザーの記憶（未確認）: 初期の `--ext`（物理 NIC を Linux bridge で Mininet
  ホストに L2 直結）では NAT しているはずの応答が戻らず、相手側にも IP マスカレードが要ったのでテストしなかった。
  root ns + MASQUERADE の bridges とは別機構の話。
- `bridges.external_routes` が各ホスト経由で実機の `/etc/resolv.conf` を `nameserver 8.8.8.8` で復元無しに
  上書きする（`bridge_root.py` の resolv 書き込み、cleanup action 未登録）。disaster 本体の既存挙動。
- ROUTER（csmgrd）を挟む多段経路版（`SimpleLinkTopo` h0-s0-h1-s1-h2 で 2 ホップ get）。
- `tests/synthetic/` は cefore-run-tests skill の pytest フェーズ（非 root）では常に skip されるため CI では
  走らない。[ci-pipeline 12](../../ci-pipeline/tickets/12-smoke-release-integration.md) の hosted-runner smoke に
  載せるかは別途判断。
- `BridgeManager.add_root_route`（root ns 側、`external_routes` + `gateway` 指定時）と `connect_to_root_ns` は
  依然 net-tools `route add` + 戻り値未確認のまま（`/32` は無言で失敗する）。既存 config に該当指定は無く回帰は
  無いが、`add_host_route` と同じ iproute2 化 + rc の可視化を別 PR で揃える。`add_host_route` の warning は
  他のモジュール内メッセージと同じく `mininet.log.info` レベルなので、既定の OUTPUT レベルでは表示されない
  （disaster / connect は info を有効にしている）。
- `src/runtime/compute_client.py` の module docstring と ADR-0003 本文は glossary「Compute endpoint」の `_Avoid_` に挙げた
  旧語彙（edge node、compute resource、compute box）を使っている。本 PR は surgical change の原則で触っていない。別 PR で置換。
- テストが `_handle_compute_call`（private 名）を直接呼ぶ。scheduler 側に public な入口を切るかは、
  2 本目のテストが同じ呼び方を必要としたときに判断。
