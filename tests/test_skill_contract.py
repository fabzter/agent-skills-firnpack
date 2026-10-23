"""Contract guard: SKILL.md's process contract must match the engine's
actual CLI surface, or the skill drifts silently.

Two layers of checking:

- Surface guards derive the `--json`/flag surface from the engine's own
  `--help` (`--help` exits before any command dispatch, so probing it is
  safe even for mutating commands) and compare it against SKILL.md.
- Behavioral probes run the pinned engine copy against a scratch repo in
  `tmp_path` and pin the corrected 1.0.1 contracts end-to-end: the
  marker/binary refusals and their JSON shapes, `previous_head` on
  restore, `kept_sides` on delete/modify conflicts, `--keep >= 1`, and
  `lost_branches: null` after a rebuild from layers alone.

Regression probes are expected to go red against pre-1.0.1 copies.
The compact lower-bound probe also pins an unchanged safety contract:
it is a deliberate control, not evidence that 1.0.0 accepted zero.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

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

# The complete long-option surface each command's --help must advertise,
# generic -h/--help excluded. Keeping this literal (not derived from
# SKILL.md) means a dropped or added engine flag trips the guard even if
# the skill was updated to match.
EXPECTED_FLAGS = {
    "init": set(),
    "commit": {
        "--message",
        "--allow-markers",
        "--allow-binary-conflict",
        "--allow-flattened",
        "--json",
    },
    "status": {"--full", "--ignored", "--json"},
    "history": {"--number", "--all", "--json"},
    "diff": {"--json"},
    "branch": {"--json"},
    "switch": {"--json"},
    "list-branches": {"--json"},
    "rename-branch": set(),
    "delete-branch": set(),
    "merge": {"--message", "--abort", "--json"},
    "amend": {"--message", "--allow-markers", "--json"},
    "restore": {"--to", "--json"},
    "export": {"--to", "--json"},
    "verify": {"--rebuild-db", "--json"},
    "compact": {"--keep", "--archive", "--dry-run", "--yes", "--json"},
}

# Flags documented globally (the `--json` bullet, `[-m MSG]`, `[-n N]`
# positionals) rather than inside a command's own synopsis line.
DOC_GENERIC_FLAGS = {"--help", "--json", "--message", "--number"}


def _help_text(cmd, engine=None):
    proc = subprocess.run(
        [sys.executable, str(engine or ENGINE), cmd, "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _flags(cmd, engine=None):
    return set(re.findall(r"--[a-z][a-z-]*", _help_text(cmd, engine))) - {"--help"}


def _skill_text(root=None):
    return ((root or ROOT) / "SKILL.md").read_text(encoding="utf-8")


def _json_exceptions():
    return {c for c in COMMANDS if "--json" not in _help_text(c)}


def _run(repo, *args, engine=None):
    return subprocess.run(
        [sys.executable, str(engine or ENGINE), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _init_repo(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    proc = _run(repo, "init")
    assert proc.returncode == 0, proc.stderr
    return repo


def _commit(repo, message, *extra):
    proc = _run(repo, "commit", "-m", message, "--json", *extra)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["layer_id"]


# ---------------------------------------------------------------- engine
# surface


def test_engine_json_surface_is_the_expected_one():
    assert _json_exceptions() == {"init", "rename-branch", "delete-branch"}


@pytest.mark.parametrize("cmd", COMMANDS)
def test_engine_flag_surface_is_the_documented_one(cmd):
    assert _flags(cmd) == EXPECTED_FLAGS[cmd], (
        f"{cmd} --help flags drifted from the 1.0.1 contract; update "
        f"SKILL.md and this pin together"
    )


# ---------------------------------------------------------------- SKILL.md
# coverage


def test_skill_contract_names_exactly_the_exceptions():
    skill = _skill_text()
    lines = skill.splitlines()
    start = next(
        i
        for i, line in enumerate(lines)
        if line.startswith("- `--json` on every command")
    )
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("- "))
    bullet = " ".join(lines[start:end])
    named = set(re.findall(r"`([a-z][a-z-]*)`", bullet))
    assert named == _json_exceptions(), (
        f"SKILL.md exception list {sorted(named)} does not match the "
        f"engine {sorted(_json_exceptions())}"
    )


@pytest.mark.parametrize("cmd", COMMANDS)
def test_skill_documents_every_engine_flag(cmd):
    """A flag the engine accepts but the skill never names is an
    undocumented override an operator could trigger blindly."""
    skill = _skill_text()
    missing = [f for f in sorted(_flags(cmd) - DOC_GENERIC_FLAGS) if f not in skill]
    assert not missing, f"SKILL.md does not document {cmd} flag(s) {missing}"


def test_skill_documents_short_options():
    skill = _skill_text()
    for usage in ("[-m MSG]", "[-n N]"):
        assert usage in skill, f"SKILL.md lost the {usage} synopsis"


def test_skill_documents_marker_and_binary_guards():
    """1.0.1 corrections: every layer-writing commit/amend is guarded, the
    refusal objects are machine-readable, overrides are per-invocation,
    and the binary override names the contract key."""
    skill = re.sub(r"\s+", " ", _skill_text())
    for needle in (
        "blocked_by_markers",
        "blocked_by_binary_conflict",
        "--allow-markers",
        "--allow-binary-conflict",
        "nothing_to_pack",
        "block_unresolved_markers",
    ):
        assert needle in skill, f"SKILL.md lost the {needle} contract"


def test_skill_documents_restore_rebuild_and_compact_contracts():
    skill = re.sub(r"\s+", " ", _skill_text())
    for needle in (
        "previous_head",  # restore moves the head; report it
        "kept_sides",  # delete/modify conflicts name the side
        "lost_branches[]|null",  # rebuild null-vs-[] semantics
        "at least 1",  # compact --keep lower bound, all modes
        "--rebuild-db",
    ):
        assert needle in skill, f"SKILL.md lost the {needle} contract"


def test_skill_makes_no_blanket_atomicity_claim():
    """1.0.1 removed the 'every refusal is atomic' promise: merges leave
    durable pending state on purpose and I/O failures can be partial. A
    reintroduced blanket claim must fail this guard."""
    skill = re.sub(r"\s+", " ", _skill_text())
    for stale in (
        "(atomic — nothing mutated",
        "Refusals (exit 1, atomic)",
        "A refusal always means the repository and worktree are untouched",
    ):
        assert stale not in skill, (
            f"SKILL.md reintroduced the debunked atomicity claim: {stale!r}"
        )
    assert "does NOT mean nothing changed" in skill, (
        "SKILL.md lost the caveat that exit 1 is not a blanket atomicity promise"
    )


def test_root_copy_is_the_submodule_engine():
    a = (ROOT / "firnpack.py").read_bytes()
    b = (ROOT / "firnpack" / "firnpack.py").read_bytes()
    assert a == b, "root copy drifted from the pinned engine"


# ---------------------------------------------------------------- engine
# behavior probes (the pinned copy must actually do what SKILL.md claims)


def test_marker_guard_blocks_every_layer_writing_commit(tmp_path):
    """Regression pinned: pre-1.0.1 only the merge-completing commit was
    checked; a standalone commit packed conflict markers into history."""
    repo = _init_repo(tmp_path)
    (repo / "notes.txt").write_text("draft\n", encoding="utf-8")
    _commit(repo, "one")
    (repo / "notes.txt").write_text("draft\n<<<<<<< left\n", encoding="utf-8")
    proc = _run(repo, "commit", "-m", "two", "--json")
    assert proc.returncode == 1
    assert json.loads(proc.stdout) == {
        "status": "blocked_by_markers",
        "blocked_by_markers": ["notes.txt"],
    }
    # the human override is per-invocation and still packs
    allowed = _run(repo, "commit", "-m", "two", "--allow-markers", "--json")
    assert allowed.returncode == 0
    assert json.loads(allowed.stdout)["status"] == "packed"


def test_amend_runs_the_marker_guard(tmp_path):
    """Regression pinned: pre-1.0.1 amend never checked markers and had
    no --allow-markers flag."""
    repo = _init_repo(tmp_path)
    (repo / "notes.txt").write_text("draft\n", encoding="utf-8")
    _commit(repo, "one")
    (repo / "notes.txt").write_text("draft\n>>>>>>> right\n", encoding="utf-8")
    proc = _run(repo, "amend", "--json")
    assert proc.returncode == 1
    assert json.loads(proc.stdout) == {
        "status": "blocked_by_markers",
        "blocked_by_markers": ["notes.txt"],
    }
    allowed = _run(repo, "amend", "--allow-markers", "--json")
    assert allowed.returncode == 0
    assert json.loads(allowed.stdout)["status"] == "amended"


def test_undecided_binary_conflict_blocks_the_merge_commit(tmp_path):
    """Regression pinned: pre-1.0.1 finished a merge while a binary file
    both sides changed still held our bytes — silently dropping theirs."""
    repo = _init_repo(tmp_path)
    (repo / "img.bin").write_bytes(b"\x00base")
    _commit(repo, "base")
    assert _run(repo, "branch", "side", "--json").returncode == 0
    assert _run(repo, "switch", "side", "--json").returncode == 0
    (repo / "img.bin").write_bytes(b"\x00theirs")
    _commit(repo, "theirs")
    assert _run(repo, "switch", "main", "--json").returncode == 0
    (repo / "img.bin").write_bytes(b"\x00ours2")
    _commit(repo, "ours")
    merge = _run(repo, "merge", "side", "--json")
    assert merge.returncode == 1
    assert json.loads(merge.stdout)["status"] == "conflict"
    proc = _run(repo, "commit", "-m", "merge side", "--json")
    assert proc.returncode == 1
    assert json.loads(proc.stdout) == {
        "status": "blocked_by_binary_conflict",
        "blocked_by_binary_conflict": ["img.bin"],
    }


def test_delete_modify_conflict_names_the_kept_side(tmp_path):
    """Regression pinned: conflict JSON gains optional kept_sides for
    delete/modify paths so the operator knows whose file survived."""
    repo = _init_repo(tmp_path)
    (repo / "shared.txt").write_text("v1\n", encoding="utf-8")
    _commit(repo, "base")
    assert _run(repo, "branch", "side", "--json").returncode == 0
    (repo / "shared.txt").write_text("v2 modified\n", encoding="utf-8")
    _commit(repo, "modify")
    assert _run(repo, "switch", "side", "--json").returncode == 0
    (repo / "shared.txt").unlink()
    _commit(repo, "delete")
    assert _run(repo, "switch", "main", "--json").returncode == 0
    merge = _run(repo, "merge", "side", "--json")
    assert merge.returncode == 1
    body = json.loads(merge.stdout)
    assert body["status"] == "conflict"
    assert body["kept_sides"] == {"shared.txt": "ours"}


def test_restore_reports_previous_head_and_rescue(tmp_path):
    """Regression pinned: restore moves the head and must name where it
    moved FROM, plus the rescue layer holding overwritten drift."""
    repo = _init_repo(tmp_path)
    (repo / "f.txt").write_text("v1\n", encoding="utf-8")
    first = _commit(repo, "one")
    (repo / "f.txt").write_text("v2\n", encoding="utf-8")
    second = _commit(repo, "two")
    (repo / "f.txt").write_text("uncommitted\n", encoding="utf-8")
    proc = _run(repo, "restore", first, "--json")
    assert proc.returncode == 0, proc.stderr
    body = json.loads(proc.stdout)
    assert body["status"] == "restored" and body["layer_id"] == first
    assert body["previous_head"] == second
    assert re.fullmatch(r"[0-9a-f]{40}", body["rescue_layer"]), (
        "drift must have been packed into a rescue layer"
    )


def test_compact_keep_must_be_at_least_one_in_every_mode(tmp_path):
    """--keep 0/negative refuse (exit 1) even in --dry-run; a non-number
    is a usage error (exit 2)."""
    repo = _init_repo(tmp_path)
    (repo / "f.txt").write_text("v1\n", encoding="utf-8")
    _commit(repo, "one")
    (repo / "f.txt").write_text("v2\n", encoding="utf-8")
    _commit(repo, "two")
    for bad in ("0", "-1"):
        proc = _run(repo, "compact", "--keep", bad, "--dry-run", "--json")
        assert proc.returncode == 1, (bad, proc.stdout, proc.stderr)
    proc = _run(repo, "compact", "--keep", "abc", "--dry-run")
    assert proc.returncode == 2


def test_rebuild_db_on_missing_database_reports_null_lost_branches(tmp_path):
    """Regression pinned: a missing glacier.db must be created and
    rebuilt; lost_branches is null (names unknowable), not []."""
    repo = _init_repo(tmp_path)
    (repo / "f.txt").write_text("v1\n", encoding="utf-8")
    head = _commit(repo, "one")
    assert _run(repo, "branch", "side", "--json").returncode == 0
    (repo / ".firn" / "glacier.db").unlink()
    proc = _run(repo, "verify", "--rebuild-db", "--json")
    assert proc.returncode == 0, proc.stderr
    body = json.loads(proc.stdout)
    assert body["status"] == "rebuilt"
    assert body["main_head"] == head
    assert body["lost_branches"] is None, (
        "no database to read branch names from: null, not []"
    )
    assert body["verify"]["status"] == "ok"


def test_skill_documents_noop_and_recovery_limits():
    """Pin the wording corrections found by cross-checking the operating
    contract: no-op payloads, reserved flattening and partial recovery."""
    skill = re.sub(r"\s+", " ", _skill_text())
    daily = skill.split("### Daily loop", 1)[1].split("### Branching", 1)[0]
    match = re.search(r"`\{status: nothing_to_pack, ([^}]+)\}`", daily)
    assert match, "SKILL.md must distinguish the no-op commit JSON shape"
    assert {key.strip() for key in match[1].split(",")} == {"layer_id", "files"}
    assert "no normal 1.0.1 command creates that pending state" in daily
    undo = skill.split("### Undo, rescue, explore", 1)[1].split(
        "### Integrity and recovery", 1
    )[0]
    assert "nothing_to_amend when tree unchanged and no -m" in undo
    assert "non-fast-forward merge leaves pending state" in undo
    recovery = skill.split("## Recovery", 1)[1].split("## Things", 1)[0]
    assert "`*.tmp` files are not" in recovery
    assert "No-op forms and eligibility refusals do not sweep" in recovery


def test_noop_payloads_and_explicit_amend_message(tmp_path):
    """A no-op has fewer keys; an explicit -m is not a no-op promise,
    even when it repeats the current message."""
    repo = _init_repo(tmp_path)
    (repo / "f.txt").write_text("v1\n", encoding="utf-8")
    head = _commit(repo, "one")
    unchanged = _run(repo, "commit", "--json")
    assert unchanged.returncode == 0, unchanged.stderr
    body = json.loads(unchanged.stdout)
    assert set(body) == {"status", "layer_id", "files"}
    assert body["status"] == "nothing_to_pack" and body["layer_id"] == head
    assert isinstance(body["files"], int) and body["files"] >= 1
    unchanged = _run(repo, "amend", "--json")
    assert unchanged.returncode == 0, unchanged.stderr
    assert json.loads(unchanged.stdout) == {
        "status": "nothing_to_amend",
        "layer_id": head,
    }
    explicit = _run(repo, "amend", "-m", "one", "--json")
    assert explicit.returncode == 0, explicit.stderr
    assert json.loads(explicit.stdout)["status"] == "amended"


def test_orphan_reporting_and_noop_sweep_limits(tmp_path):
    """Verify reports orphan layers, not temporary files. Only a command
    that writes a layer reaches the sweep; idle forms preserve leftovers."""
    repo = _init_repo(tmp_path)
    (repo / "f.txt").write_text("v1\n", encoding="utf-8")
    _commit(repo, "one")
    layers = repo / ".firn" / "layers"
    temporary = layers / "leftover.tmp"
    temporary.write_bytes(b"unfinished write")
    checked = _run(repo, "verify", "--json")
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["status"] == "ok"
    for args, status in (
        (("commit", "--json"), "nothing_to_pack"),
        (("amend", "--json"), "nothing_to_amend"),
        (("compact", "--keep", "1", "--yes", "--json"), "nothing_to_compact"),
    ):
        idle = _run(repo, *args)
        assert idle.returncode == 0, idle.stderr
        assert json.loads(idle.stdout)["status"] == status
        assert temporary.read_bytes() == b"unfinished write"
    orphan = layers / ("0" * 40 + ".firn")
    orphan.write_bytes(b"unreferenced layer")
    checked = _run(repo, "verify", "--json")
    assert checked.returncode == 3
    assert "orphan layer file" in checked.stderr
    assert "leftover.tmp" not in checked.stderr
    (repo / "f.txt").write_text("v2\n", encoding="utf-8")
    _commit(repo, "two")
    assert not temporary.exists() and not orphan.exists()
    assert _run(repo, "verify", "--json").returncode == 0
