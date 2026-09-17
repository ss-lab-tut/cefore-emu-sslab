---
status: open
type: task
claimed-by:
blocked-by: []
---
## Task

**future work (2026-08-07 教員feedback) — ツール名 CeforeEmu → ReCefore 改称**:
「CeforeEmu」は Cefore Emulator の略称と受け取られうるため、固有名 ReCefore
(a reproducible Cefore experimentation framework) への改称提案を採用。第33回 ICN
研究会ワークショップのポスター (projects/poster-a0-icn33/) は ReCefore 表記で発表済み。
コード側は未改称: リポ名 cefore-emu-sslab / パッケージ名 cefore-emu / CLI
(ceforeemu, ceforeemu-log, ceforeemu-connect) / `python -m src` に名称が波及するため、
改称するなら repo rename (GitHub は旧 URL から自動リダイレクト) + pyproject
[project.scripts] + README を一括で行う。ポスター QR は現リポ URL を指しており、
リダイレクトが効くため後追い改称でも壊れない。
あわせて教員提案の Application Adapter API 構想 (ReCefore Core → Adapter API →
Reference Applications; 火災シミュレータ = ss-lab-tut/heterosense-fl-testbed を最初の
参照アプリとし、網障害がアプリ性能へ与える影響を評価) をポスター Future Work 帯に採録。
_Avoid_: ポスター・論文だけ改称してコード実体 (CLI 名) との対応を文書化しないこと

## Status (2026-08-23)

- 未着手。`pyproject.toml:2` は `name = "cefore-emu"` (version は :3 `0.2.1`、2026-09-17 時点)、`[project.scripts]` :20-23 (`ceforeemu` / `ceforeemu-log` / `ceforeemu-connect`) 未変更。
- (2026-09-17 訂正) 旧記述「`ReCefore` は CONTEXT.md 以外に 0 hits」は誤り: main (defeeb4) では `ReCefore` は repo 全体で 0 hits。記述はこの移設ブランチで初めて入る (CONTEXT.md の Backlog 案内段落、本 ticket、[22](22-application-adapter-api.md))。
- このチケットの範囲は改称の実装部分: repo rename (GitHub 旧 URL 自動リダイレクト) + pyproject `[project.scripts]` + README を一括。ポスター QR は現リポ URL を指しており、リダイレクトが効くため後追いでも壊れない。
- Adapter API 構想は [22](22-application-adapter-api.md) に分離。
