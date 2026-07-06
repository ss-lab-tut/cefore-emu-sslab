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
