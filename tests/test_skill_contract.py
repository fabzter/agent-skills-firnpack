"""Contract guard: SKILL.md's process contract must match the engine's
actual CLI surface, or the skill drifts silently.

`--help` exits before any command dispatch, so probing it is safe even
for mutating commands. The guard derives which commands accept `--json`
from the engine itself and checks SKILL.md's exception sentence names
exactly that set.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "firnpack.py"

COMMANDS = [
    "init",
    "commit",
    "status",
    "history",
    "diff",
    "branch",
    "switch",
    "list-branches",
    "rename-branch",
    "delete-branch",
    "merge",
    "amend",
    "restore",
    "export",
    "verify",
    "compact",
]


def _help_text(cmd):
    proc = subprocess.run(
        [sys.executable, str(ENGINE), cmd, "--help"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _json_exceptions():
    return {c for c in COMMANDS if "--json" not in _help_text(c)}


def test_engine_json_surface_is_the_expected_one():
    assert _json_exceptions() == {"init", "rename-branch", "delete-branch"}


def test_skill_contract_names_exactly_the_exceptions():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    lines = skill.splitlines()
    start = next(
        i for i, l in enumerate(lines) if l.startswith("- `--json` on every command")
    )
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("- "))
    bullet = " ".join(lines[start:end])
    named = set(re.findall(r"`([a-z][a-z-]*)`", bullet))
    assert named == _json_exceptions(), (
        f"SKILL.md exception list {sorted(named)} does not match the "
        f"engine {sorted(_json_exceptions())}"
    )


def test_root_copy_is_the_submodule_engine():
    a = (ROOT / "firnpack.py").read_bytes()
    b = (ROOT / "firnpack" / "firnpack.py").read_bytes()
    assert a == b, "root copy drifted from the pinned engine"
