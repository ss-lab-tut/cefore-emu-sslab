---
status: open
type: grilling
claimed-by:
blocked-by: [11]
---
## Question

[11](11-smoke-prototype.md) で成立した hosted-runner smoke（`min_putget`、
`ci/smoke-prototype` の `.github/workflows/smoke.yml`）を、release 時のみ起動する形で
main に入れるにはどう組むか。

前提（ユーザー決定 2026-09-17）: PR / push では走らせない。release.yml から呼ぶ。
required check にはしない（ADR-0004 の non-required 方針）。

## 論点

- **呼び出し形**: release.yml に `smoke: uses: ./.github/workflows/smoke.yml` を足す。smoke.yml からは試作用の `push: branches: [ci/smoke-prototype]` を外し、`workflow_call` だけにする。
- **release を止めるか**: `release` job の `needs` を `[ci, smoke]` にするか `[ci]` のままにするか。
  - 止める場合: smoke が落ちると Release が作られない。6/6 green の実績だけで gate にしてよいか。
  - 止めない場合: smoke の失敗は Actions の run に残るだけで、Release 本文からは見えない。
- **flakiness 許容度**: matrix を 1 本にするか。落ちたときに再実行で済ませるか、原因調査を必須にするか。
- **ADR-0004 の更新**: 「smoke はローカルのみ」から「release 時に hosted runner でも実行」へ Decision を改訂するか、新しい ADR を切るか。run_cefore_checks.py を smoke 判定器として CI で使う点（unit gate 経由案の却下とは別物）もあわせて記録する。
- **試作からの削除**: 空振りしていた `systemctl stop/disable openvswitch-testcontroller`（Ubuntu 24.04 に unit が無い）。
- **controller 差分**: CI は `ovs-testcontroller`、ラボはパッチ版 openflow `controller`。smoke を 17 switch 以上の config に広げない限り影響しない、という前提を ADR にも書くか。

## 判断材料

- 計測値は [11](11-smoke-prototype.md) の Resolution。job 全体で 69–109 秒、キャッシュ効果は job あたり約 20 秒。
