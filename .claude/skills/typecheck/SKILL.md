---
name: typecheck
description: Run Python type checking (mypy) and linting/formatting (ruff) using .venv/bin/python3. Use when user asks to check types, lint, format-check, or verify code quality. Invoked with /typecheck [target].
---

# Python Type Check & Lint

Run type checking and linting on Python code using the project's virtual environment.

## Target

Check: $ARGUMENTS

If no target is specified, default to `src/`.

## Steps

### 1. Ensure .venv exists

Check if `.venv/bin/python3` exists. If not, run `uv sync` to set up the environment:

```bash
test -x .venv/bin/python3 || uv sync
```

### 2. Run mypy (type checking)

```bash
.venv/bin/python3 -m mypy $ARGUMENTS
```

If `$ARGUMENTS` is empty, use `src/` as the target.

### 3. Run ruff check (lint)

```bash
.venv/bin/python3 -m ruff check $ARGUMENTS
```

### 4. Run ruff format --check (format check)

```bash
.venv/bin/python3 -m ruff format --check $ARGUMENTS
```

### 5. Report summary

After running all checks, report:
- mypy: passed / N errors
- ruff check: passed / N issues
- ruff format: passed / N files would be reformatted

If any check failed, list the specific errors/issues so the user can fix them.

## Notes

- Always use `.venv/bin/python3 -m <tool>` — never use bare `python3`, `mypy`, or `ruff` commands
- `mypy` and `ruff` must be installed in the dev group: `uv sync --group dev`
- If a tool is not installed (exit code indicates module not found), suggest running `uv sync --group dev`
