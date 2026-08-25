---
status: closed
type: grilling
claimed-by: claude-code
blocked-by: []
---
## Question

e2e smoke（root + Mininet + Cefore 実機系）を CI にどう位置づけるか。

## Resolution (2026-08-01)

**v1 対象外 + prototype ticket 化**（ticket 11）。
- self-hosted runner（ラボ VM）は public repo では fork-PR が任意コードを runner
  上で実行できるため**恒久却下**（GitHub 公式も非推奨）
- hosted runner 案は技術的に可能（sudo 可・mininet apt 有・Cefore ソースビルドは
  キャッシュ可能）だが未実証。実証前に v1 のクリティカルパスへ入れると CI の
  信頼をスタート時点から毀損する
- smoke の gate 責務は当面 cefore-run-tests（ローカル・root）に残置
