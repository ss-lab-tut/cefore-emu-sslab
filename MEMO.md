# Workshop 計測キャンペーン 進行メモ (2026-07-07 overnight)

Plan: ~/.claude/plans/icn-plan-plan-goal-vectorized-sloth.md
成果物: logs/workshop_20260707/ (report.html + 図 + CSV が最終形)

## タイムライン
- 01:42 開始。branch feature/workshop-measurements 作成
- 02:00 configs(31本) + tools(campaign.py / topo_fingerprint.py) を subagent 並列作成
- 02:15 オフライン prescreen: 全 (config,seed) を fingerprint で事前検証
  - M1: 21 seed 全部 build OK、fingerprint 21/21 相異 → 多様性主張の裏付け
  - m5d が 1/15 → topology を m5c と同型 (15h/48sw, degree2..6) に修正して 5/5
  - m5b(link[1,2]必要): 602,607,611,615,622 / m4(pair[0,1]必要): 903,906,907
- 02:20-03:10 smoke デバッグ (下記「発見した罠」)
- 03:10 smoke 完全 green (failures 0, flap 0, get 間隔正常, pubsub 成功)
- 03:15 ceiling probe (h20→h60) 実行中 / main manifest 165 jobs 生成済み

## 発見した罠（CONTEXT.md にも記録済み）
1. **down_* default 罠**: down_interval/count/duration 省略 = default 30/5/10 で
   flap 有効。no-failure config には明示ゼロ必須。
2. **repeat get のログ上書き**: 同一 host+uri の repeat は content log が同名 →
   失敗ログが後続成功で消える。判定は results.json を使う。
3. **pubsub 早期発火 (at<=2) で pub が 0B のまま死ぬ**。実証済みスロット at>=10。
   pub は grace+wait で content worker を ~20s 占有 → get の後ろに配置。
4. **switches: N は上限で実現数ではない** (M1 実測: 48 指定で realized 24-38)。

## 実行中/残り (03:55 更新)
- [x] probe 完了: h20〜h60 全部 OK、h60 ピーク 10.9GB — メモリは制約にならず。M3 は h60 まで完走可
- [x] 追加 smoke (m5b/m5d/m4/m2d) 全部 ok — m5b link_down/up 成功+get 15/15、m5d get 6/6
- [x] plots.py / report.py 完成 (smoke データで 4 図の実レンダリング検証済み)
- [x] **main campaign 150 jobs 起動 (03:52)** — M1 30 → M2 35 → M5 60 → M3 25
  - detached supervisor (tools/workshop/supervise.sh, setsid root) が journal-resume で守る
  - 進捗: logs/workshop_20260707/main/campaign_state.jsonl (1 job = 1 行)
- [ ] **M4 は設計不良を発見して作り直し中**: bw_set(t=1) は warmup 後で、eval get は
  cache 命中のため帯域制限が実測に出ない (10Mbps 設定で 45-87Mbps を実測)。
  → per-seed 静的 bw: 全 switch 一律制限 + warmup get(初回取得)を計測点に変更。
  eval get は「キャッシュ加速」系列として同じ図に載せる。subagent が生成中、
  完成後 manifest に m4st_* 15 jobs を追記 (supervisor が拾う)
- [ ] M1 30 jobs 完了時 (~05:30 見込): 3層検証を即実行 (fingerprint 一致 / 射影一致 / CV)
- [ ] m5a 完了時: eval_pubdown_total > 0 gate + cache/nocache 対比確認
- [ ] ~06:30: 部分データで一次 report.html 生成 → campaign 完了後に最終版 + コミット

## M1 同一seed 10本 検証結果 (04:45)
- (a) 構造: runtime adjacency matrix 10/10 一致 (オフライン fingerprint 不変とも整合)
- (b) 判定: 射影 (op_type,host,uri,success) 10/10 一致。pubsub 2 op の失敗まで決定的
- (c) 性能: eval get throughput CV 14.6〜18.6% (h1:60.8 / h2:82.8 / h3:7.8 / h4:27.5 Mbps)
- **発見: pubsub は 15-host で系統的失敗** (5-host では成功)。M1 config は不変のまま
  維持 (比較均質性優先)。m2_mesh_pubsub は 5-host へ縮小済み。CONTEXT.md 記録済み

## M1 異seed 20本 検証結果 (05:40) — Phase 1 完了
- 多様性: runtime adjacency 20/20 全相異 (オフライン fingerprint 21/21 相異と整合)
- put/get: 20 topology 全部で 8/8 成功
- **pubsub の失敗は topology 依存と判明**: 20 seed 中 9 成功 / 11 失敗 (+seed42 失敗)。
  スケールそのものではなく sub(h5)→pub(h0) の経路/hop 距離依存の可能性が高い。
  失敗 seed でも同一 seed 内では決定的 (M1 の決定性主張はそのまま成立)

## pubsub × hop 距離の相関 (05:45, M1 の 20 topology から)
sub(h5)→pub(h0) hop 距離 vs pubsub 成否: **hop=1: 5/5 OK / hop=2: 5/7 OK / hop=3: 0/8 FAIL**
→ 「pubsub Trigger 到達性は hop 距離で急減、3 hop で全滅」。seed 制御 + オフライン
fingerprint により 20 topology の相関分析が root 権限なしで即完了 — エミュレータの
分析力の実証例としてレポートに載せる。(cefnetd は FwdStr:flooding、k=2 ECMP)

## M5a 結果 (08:25) — 読み替えあり
- cache(k_centers×3): pub-DOWN中 82/96 (85%) / UP中 290/294 (99%)
- nocache(最小1node):  pub-DOWN中 149/156 (96%) / UP中 233/234 (100%)
- **ヘッドライン**: publisher down 中でも get 85〜96% 成功 (自動 down/up は本家に無い機能)
- **caveat**: cefnetd local CS (capacity 32768) が全ホストで有効なため、csmgrd 配置
  (cache/nocache) の対比は交絡して分離不能。アーム間の pubdown 母数差 (96 vs 156) は
  down window タイミングのドリフト。レポートに正直に記載

## m5c 結果 (10:20): 強度カーブはフラット
down_count 1/2/3/4 → 97.8/93.3/100/100% — 劣化せず。local CS + k=2 ECMP が
host 障害を吸収する耐性実証として報告 (「劣化カーブ」ではない)。

## M5 完了 (11:40)
- m5b: link_down/up 5 seed 全部で outcome 記録成功 (時系列図は plots.py が生成)
- m5c: フラット (97.8/93.3/100/100%) — 耐性実証として報告
- m5d: kcenters/degree/manual 全部 30/30 (100%) — 戦略差は出ず、capability 実証として報告

## 🏁 キャンペーン完了 (11:45 JST) — 165/165 jobs 全成功・リトライゼロ
- 総所要: 03:52〜11:44 (~7h52m)。failed/timeout/skipped_memory = 0
- 最終成果物: logs/workshop_20260707/main/
  - report.html (統合レポート、図 base64 埋め込み、caveats 7項目付き)
  - figures/*.png+pdf (スライド用 10 図)
  - analysis/*.json (全図の生数値)
  - campaign_state.jsonl (全 job 実行記録)
- M4 最終結果: warmup throughput は 5/10/20Mbps 設定に忠実 (~90%)、50Mbps 以上は
  Cefore デーモン処理律速で ~20Mbps 飽和。eval (cache hit) は帯域制限を超えて加速
- M3 最終結果: put/get は h5〜h60 全スケール 100%。setup 時間は hosts に線形
  (165s→343s)、peak memory 5.8→20GB
- 再現: sudo .venv/bin/python3 tools/workshop/campaign.py --manifest logs/workshop_20260707/manifests/main.json --out <dir>
