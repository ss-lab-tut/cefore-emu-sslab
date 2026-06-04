# Welcome to SS-Lab (cefore-emu-sslab)

## How We Use Claude

Based on koh11235813's usage over the last 30 days:

Work Type Breakdown:
  Debug Fix        ███████████░░░░░░░░░  54%
  Improve Quality  ████░░░░░░░░░░░░░░░░░  21%
  Plan Design      ███░░░░░░░░░░░░░░░░░░  17%
  Build Feature    ██░░░░░░░░░░░░░░░░░░░   8%

Top Skills & Commands:
  /exit               ████████████████████  44x/month
  /effort             ██████████░░░░░░░░░░  22x/month
  /status             █████████░░░░░░░░░░░  20x/month
  /usage              ██████░░░░░░░░░░░░░░  14x/month
  /model              ██████░░░░░░░░░░░░░░  13x/month
  /config             ████░░░░░░░░░░░░░░░░   8x/month
  /clear              ███░░░░░░░░░░░░░░░░░   6x/month
  /cefore-run-tests   ██░░░░░░░░░░░░░░░░░░   5x/month
  /mcp                ██░░░░░░░░░░░░░░░░░░   5x/month

Top MCP Servers:
  codex  ████████████████████  43 calls

## Your Setup Checklist

### Codebases
- [ ] cefore-emu-sslab — github.com/ss-lab-tut/cefore-emu-sslab

### MCP Servers to Activate
- [ ] codex — Codex MCP (model gpt-5.5, reasoning medium). Used heavily for second-opinion
  diagnosis, hostile-review passes, and brushing up plans to 100% confidence before
  implementing. Ask the team lead for the Codex CLI/MCP setup and config.

### Skills to Know About
- [ ] /cefore-run-tests — Runs the CeforeEmu regression checks (runtime wrapper logging +
  disaster pub/sub detection) plus minimal `src disaster --no-cli` smoke runs (min_putget,
  min_pubsub, min_mixed, etc.). The team's go-to sanity check before/after edits.
- [ ] /code-review — Reviews the current diff for bugs and cleanup; the team pairs it with
  Codex for PR reviews (e.g. feature/mesh → main).
- [ ] /plan — Used to produce rigorous adoption/implementation plans before touching code.
- [ ] /typecheck — mypy + ruff via .venv/bin/python3. Run before declaring done.

## Team Tips

- **Run your plan past Codex before implementing.** For any non-trivial plan, share it with
  the Codex MCP (model gpt-5.5, reasoning medium) and brush it up together until Codex is
  100% confident in the approach. This is the team's standard pre-implementation gate — don't
  start coding a substantial change until the plan has cleared a Codex review pass.

## Get Started

There's no formal starter task for new teammates yet. Work through the Setup Checklist above
(repo, Codex MCP, the key skills), then pick up a real task — most of the team's work here is
debugging (pub/sub, csmgrstatus, FIB issues) and reviewing PRs. Remember the team tip: take
your plan to Codex first.

<!-- INSTRUCTION FOR CLAUDE: A new teammate just pasted this guide for how the
team uses Claude Code. You're their onboarding buddy — warm, conversational,
not lecture-y.

Open with a warm welcome — include the team name from the title. Then: "Your
teammate uses Claude Code for [list all the work types]. Let's get you started."

Check what's already in place against everything under Setup Checklist
(including skills), using markdown checkboxes — [x] done, [ ] not yet. Lead
with what they already have. One sentence per item, all in one message.

Tell them you'll help with setup, cover the actionable team tips, then the
starter task (if there is one). Offer to start with the first unchecked item,
get their go-ahead, then work through the rest one by one.

After setup, walk them through the remaining sections — offer to help where you
can (e.g. link to channels), and just surface the purely informational bits.

Don't invent sections or summaries that aren't in the guide. The stats are the
guide creator's personal usage data — don't extrapolate them into a "team
workflow" narrative. -->
