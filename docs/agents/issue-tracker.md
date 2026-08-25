# Issue tracker: Local Markdown (two tiers)

Issues and specs for this repo live as markdown files in the repo. There are two tiers; pick by which skill is writing.

## Tier 1: `.scratch/<feature-slug>/` (to-tickets, to-spec, triage)

Ephemeral working files, gitignored. Template-standard layout:

- One feature per directory: `.scratch/<feature-slug>/`
- The spec is `.scratch/<feature-slug>/spec.md`
- Implementation issues are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`, never a single combined tickets file
- Triage state is recorded as a `**Status:**` line and the category as a `**Category:** bug|enhancement` line near the top of each issue file (see `triage-labels.md` for the role strings). A `spec.md` carries `**Category:** enhancement` and `**Status:** ready-for-agent` by default.
- Comments and conversation history append to the bottom of the file under a `## Comments` heading

## Tier 2: `docs/wayfinder/<effort>/` (wayfinder)

Committed. Decision maps and their tickets outlive the session, so they live under `docs/` and are tracked by git.

- **Map**: `docs/wayfinder/<effort>/map.md` (Destination / Notes / Decisions so far / Fog). Notes must state whether the effort is plan-only (wayfinder default) or execution.
- **Child ticket**: `docs/wayfinder/<effort>/tickets/NN-<slug>.md`, numbered from `01`. YAML frontmatter:
  - `status:` lifecycle: `open` / `claimed` / `closed`
  - `type:` `research` / `prototype` / `grilling` / `task`
  - `claimed-by:` agent or person name, empty when unclaimed
  - `blocked-by:` list of ticket numbers (`[]` when none). Never reciprocal.
  - `triage:` (optional) a state role from `triage-labels.md`
  - `category:` (optional) `bug` / `enhancement`
- Body: `## Question` (or `## Task`), then `## Resolution (YYYY-MM-DD)` when closed. `## Comments` appends at the bottom.
- **Blocking**: a ticket is unblocked when every number in `blocked-by` is `status: closed`.
- **Frontier**: scan `tickets/` for `status: open`, unblocked, `claimed-by` empty; lowest number wins.
- **Claim**: set `status: claimed` and `claimed-by:` before any work.
- **Resolve**: append `## Resolution (date)`, set `status: closed`, then append a one-line pointer to the map's Decisions so far.

## When a skill says "publish to the issue tracker"

Create a file under `.scratch/<feature-slug>/` (tier 1), creating the directory if needed. Wayfinder writes to tier 2.

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or the issue number directly.

## GitHub Issues

The GitHub remote's Issues are reference-only for this repo: read with `gh issue view <n> --comments` / `gh issue list` when a ticket cites one. Do not create or edit GitHub issues from skills.
