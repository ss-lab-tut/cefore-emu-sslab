"""Guard test: every host/root command must go through the CommandRunner seam.

After the CommandRunner refactor (candidate B), ``src/`` must not contain any
direct ``Node.cmd()`` / ``Node.popen()`` / ``Node.pexec()`` /
``subprocess.run/Popen/call`` call outside the one place that owns execution
(``MininetCommandRunner`` in ``command_runner.py``). This test fails if a new
call site bypasses the seam, so the single-execution-point invariant cannot
silently regress.

Allowlist:
- ``runtime/command_runner.py`` — the seam itself (the only legitimate place a
  real subprocess / ``host.popen`` is spawned).
"""

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"

# Files permitted to contain raw command execution (see module docstring).
_ALLOWLIST = {
    "runtime/command_runner.py",
}

# Matches a direct host/root command execution that bypasses the seam. Covers
# the Mininet Node exec methods, the subprocess spawn/convenience functions, the
# os spawn helpers, and a bare ``from subprocess import ...`` (which would let a
# spawn function be called unqualified). Whitespace around ``.``/``(`` is allowed
# so ``host.cmd (...)`` cannot evade the check.
_FORBIDDEN = re.compile(
    r"\.\s*(cmd|cmdPrint|popen|pexec|sendCmd|waitOutput)\s*\("
    r"|\bsubprocess\s*\.\s*(run|Popen|call|check_call|check_output)\s*\("
    r"|\bos\s*\.\s*(system|popen)\s*\("
    r"|\bfrom\s+subprocess\s+import\b"
)


def _iter_violations():
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC).as_posix()
        if rel in _ALLOWLIST:
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            # Skip whole-line comments; inline code+comment still gets scanned.
            if line.lstrip().startswith("#"):
                continue
            if _FORBIDDEN.search(line):
                yield f"{rel}:{lineno}: {line.strip()}"


def test_no_raw_command_execution_outside_seam():
    violations = list(_iter_violations())
    assert not violations, (
        "Direct command execution found outside the CommandRunner seam. "
        "Route it through a CommandRunner (MininetCommandRunner) instead:\n"
        + "\n".join(violations)
    )


def test_allowlisted_files_exist():
    # Guard against the allowlist silently rotting if a file is renamed.
    for rel in _ALLOWLIST:
        assert (_SRC / rel).is_file(), f"allowlisted file missing: {rel}"
