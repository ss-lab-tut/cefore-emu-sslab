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

## Status (2026-09-17)

- done（ユーザー口頭確認、2026-08-01）: 4 required checks（test / lint / typecheck / packaging, strict）は [ADR-0004](../../../adr/0004-ci-guards-unit-surface-only.md) Branch protection 節に記録。branch protection は GitHub 側の設定で git からは検証不能。
