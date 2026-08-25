---
status: closed
type: task
claimed-by: user
blocked-by: [09]
---
<!-- Resolution 2026-08-01: ユーザーが GitHub UI で設定完了を確認
     (required checks: test/lint/typecheck/packaging + strict up-to-date)。
     これで map の destination 到達 — 残 open は ticket 11 (post-v1) のみ -->

## Question

（HITL — 人間の GitHub UI 操作）main の branch protection に required status
checks `test` / `lint` / `typecheck` / `packaging` を追加する。初回 CI 実行後に
候補へ出現する。API write 不可のためここだけ手動。

受け入れ条件: 4 checks が required になった main protection rule のスクショ or
口頭確認。
