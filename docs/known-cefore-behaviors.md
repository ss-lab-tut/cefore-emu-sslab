# Known Cefore behaviors (実験で確定した観測事実)

CONTEXT.md から 2026-08-23 に移設。glossary ではなく、実験設計を縛る Cefore 側の挙動と罠を記録する。新しい観測は日付付きで追記すること。

## pubsub が 15-host mesh で系統的に失敗 (2026-07-07 workshop 計測)

cefpubfile/cefsubfile ペアは 3〜5 host mesh では成功するが、15h/48sw では pub が
Trigger Interest を受信できないまま deadline (lifetime+15s) で terminate する
(exit -15, stdout 0B)。sub が publisher に隣接していても再現 (m2_disaster seed401)。
同一 seed で 10/10 決定的に再現 (m1_repro seed42)。put/get は同一 topology で全成功
のため FIB/接続性の問題ではなく、pubsub の Trigger 経路固有。cefnetd は
FwdStr:flooding で起動している点も関連候補。hop距離相関 (M1 20-topology 分析): hop=1で5/5成功, hop=2で5/7, hop=3で0/8 — 距離依存を定量確認。ワークショップ計測では pubsub 行を
5-host に縮小して測定し、15-host の失敗は「エミュレータによる再現性つき問題検出」
として報告する。恒久対応は Cefore 側 pubsub の hop/スケール挙動の調査が必要。
追記 (2026-07-07 Commit 4): archived campaign artifact 全件を grep しても
Trigger-Interest retry 回数を示すラベルは存在しない (0-byte FAILURE ログ + SUCCESS
ログの固定2行のみ)。この2行 (`Send Trigger Interest.` / `Receive Trigger Data,
finish application.`) を `trigger_interest_sent`/`trigger_data_received` として
schema 化した (src/log/schema.py)。`from_log` は marker 存在時のみ pub success を
definitive True と判定するよう更新済み (src/core/verdict.py) — marker 不在側
(0-byte FAILURE ログ) の log-only 判定は依然 unknown のままで、これはログ欠損と
区別不能という構造的限界であり today の fix では解消しない。
_Avoid_: 実験 config の pubsub を無検証で 10+ hosts に置くこと

## 障害窓中の get 可用性は「FIB 経路上の csmgrd」で決まる (2026-07-14 M5e 時系列実験)

機構を対照実験で確定: (1) 非cacheノードは CS_MODE=0 (テンプレ既定) で一切キャッシュを
持たず、他ホストの取得は誰にも再供給されない (2) csmgrd が複製を持つのは「そのノード
自身が取得した場合」または「consumer→publisher の FIB 経路上にいて取得が通過した場合」
のみ (3) publisher 停止中に get が成功する必要十分条件 ≒ 経路上の csmgrd に複製がある
こと。flooding (FwdStr) は実質 FIB 経路のみで、経路外の csmgrd 複製は救わない。
m5a の 85〜96% の正体もこれ (5秒間隔ポーリングの直近複製が経路上に生きていた)。
オフライン再現: k_centers 配置は topo_fingerprint の隣接 + src/core/graph.select_k_centers
で実行時と完全一致 (seed 1101 で実測検証済) → per-seed の役割選定
(tools/workshop/gen_m5e_config.py) が可能になった。
failure_scenarios cycles の罠: interval は前 cycle の down 時点起点で、down 中の
target は skip される → **interval > 前 cycle の duration が必須** (でないと後続窓が
無言で消える)。
_Avoid_: 「一度取得した content は網内キャッシュに乗る」と仮定した実験設計
(非cacheノードの取得は乗らない)。cycles の interval ≤ duration。
