# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

For architecture, project structure, command usage, and configuration reference, see [README.md](README.md).

# Write a program based on the Unix philosophy
* Write programs that do one thing and do it well.
* Write programs to work together.
* Write programs to handle text streams, because that is a universal interface.

# Interaction contract
- If requirements are ambiguous or underspecified, stop and ask 1–3 targeted questions before proceeding.
- Before making any irreversible change (deletes, migrations, dependency upgrades, infra changes), ask for explicit confirmation.
- Never assume environment details (OS, shell, package manager, project conventions). Ask or infer only from repo evidence.
- Start each task by restating: Goal, Non-goals, Constraints, Success criteria (brief).
- When multiple approaches exist, present 2 options with tradeoffs, then ask which to take.

## Comment & Context Policy

Write comments generously — treat them as first-class documentation, not noise.
Current AI models benefit from heavy inline context; so do human readers six months later.

In addition to comments, write function and class descriptions and intentions in docstring.

- **Always comment intent, not mechanics.** Explain *why* a block exists, what invariant it protects, or what would break without it. Don't restate what the code does — explain what it *means*.
- **Record fix provenance inline.** When code exists because of a specific bug or incident, leave a dated note: `# 2026-05-12 crash fix: bare ifconfig omits netmask → classful /8 on Class A`. This is the kind of context that git blame buries and developers lose.
- **Keep context close to code.** A comment explaining a constraint belongs next to the line it constrains, not in a separate design doc. If someone reads the function, they should see the warning without leaving the file.
- **Don't write comments that rot.** Avoid referencing ticket numbers, PR links, or caller names ("used by X") — those change. Describe the *constraint* the code enforces; that outlives the ticket.

## Notice

Separate functions into separate files by type, and do not recreate existing functions in the execution script. If you need to edit them, edit the existing function and check that the modifications have been made.
Make functions as flexible as possible by using variables.

## Development

**Running scripts — always use the venv path:**

`sudo` drops the virtual environment; `sudo -E` does not reliably propagate `PATH` to the venv. Always invoke the venv Python directly:

```bash
sudo .venv/bin/python3 -m src ...    # correct: project deps are available
sudo python3 -m src ...              # wrong: system python lacks yaml, networkx, etc.
```

**CLI entry points** (`pyproject.toml [project.scripts]`):
- `ceforeemu` — main CLI (`src.cli.main:main`)
- `ceforeemu-log` — log summarization (`src.log.cli:main`)
- `ceforeemu-connect` — external network (`src.runtime.external_net:main`)

After modifying `[project.scripts]`, run `uv pip install -e .` to register new entry points.

## Security Notes

- `config/templates/h*/default-private-key` files contain sensitive cryptographic material — do not commit changes or share.
- All scripts require root privileges due to Mininet's network namespace manipulation.
- Only run in trusted/isolated environments (VMs recommended).

## MCP Tool Settings

When using Codex MCP, specify model `gpt-5.5` (reasoning high, summaries auto).
