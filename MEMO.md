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

## 実行中/残り
- [ ] probe 完了 → M3 の実行上限確定 (RAM 80% guard は campaign.py 内蔵)
- [ ] main campaign 165 jobs 起動 (M1 30 → M2 35 → M5 60 → M3 25 → M4 15)
  - 見積 ~10h。優先順で並べてあるので途中でも M1/M2/M5 から成立する
- [ ] plots.py / report.py 作成（campaign 並走中に subagent へ委譲）
- [ ] 06:30 頃に部分データで一次レポート生成 → 完了後に最終版
- [ ] M1 検証: fingerprint 10/10 一致 + results.json 射影一致 + CV
- [ ] m5a gate: eval_pubdown_total > 0 (smoke では 14, 全部成功=cache 効果)
