---
name: firnpack
description: Operate the firnpack single-file VCS — commit, branch, merge, amend, restore, verify, compact — with JSON output, rescue-first safety, and permission-gated history rewrites. Use when a project contains a .firn/ repository or the firnpack/firn commands are available.
---

# firnpack — operator skill

firnpack is a single-user, decentralized-ish VCS: every commit is one
compressed, checksummed, immutable layer file; the repository is
`.firn/` (one SQLite metadata file + `layers/`). No remotes, no staging
area, no daemons. This file is the complete operating contract; the
engine is the adjacent `firnpack.py` (byte-identical to the submodule
pinned at a tested release).

Run it either way:

```
firnpack <command> …        # installed (pip install firnpack; alias: firn)
python firnpack.py <command> …   # this skill's copy, zero dependencies
```

Requires Python 3.13.16+.

## Golden rules

1. **Never destroy uncommitted work.** Check `status --json` (`clean`)
   before `merge`, `switch`, or `restore` without `--to`. On drift:
   commit it, or let `restore`/`merge --abort` rescue it (they pack the
   drift first and report `rescue_layer` — tell the human where it went).
2. **Compact only with human parameters.** `--keep N` and `--yes` must
   come from the human, per invocation. Always show `--dry-run` first.
   Report `branches_remapped` and `garbage_collected` afterwards.
3. **Never silent.** Surface these when present: `branches_remapped`,
   `off_chain_rewritten`, `garbage_collected`, `rescue_layer`,
   `history_reminder`, `maxpath_warning`, `flattened_pending`,
   `nested_gitignore`, `ignored_count`.
4. **Verify after external events** (copy, power loss, old clone):
   `verify`. Exit 3 = stop writing; follow Recovery below.
5. **Ids are opaque 40-hex content hashes.** Prefixes resolve uniquely
   or error; never construct or truncate one yourself.
6. One process at a time per repository. No parallel commands.

## Process contract

- `--json` on every command except `rename-branch`/`delete-branch`:
  exactly one JSON object on stdout; human notes on stderr. Parse
  stdout only.
- Exit codes: `0` success (incl. explicit no-ops), `1` refused/failed
  (atomic — nothing mutated; merge conflict included), `2` CLI usage
  error, `3` integrity failure.
- Read-only anywhere, anytime: `status`, `history`, `diff`, `verify`,
  `export`, `list-branches`, `compact --dry-run`.

## Commands

### Daily loop

```
init [PATH]                 create .firn/ (seeds .gitignore "~$*" if absent)
commit [-m MSG] [--allow-markers] [--allow-flattened]
                            pack the worktree; auto-message without -m;
                            consumes a pending merge (records second parent)
status [--full] [--ignored] drift vs head (stat-cache fast path; --full rehashes)
history [-n N] [--all] [BRANCH]
diff                        per-path line diffs vs head
```

JSON keys — commit: `{status: packed|nothing_to_pack, layer_id, tree_id,
files, size, message, [maxpath_warning], [history_reminder]}`; status:
`{head: {id, kind, [branch]}|null, clean, modified[], added[], missing[],
ignored_count, ignored[], nested_gitignore, merge_pending,
flattened_pending}`; history: `{commits: [{id, tree_id, parent,
second_parent, message, author, created_at, tips[]}], count}`; diff:
`{entries: [{path, status: added|modified|deleted, binary, hunks?|size?}]}`.

### Branching

```
branch NAME [FROM]          create at HEAD or FROM (stays put)
switch REF                  branch name, or layer-id prefix => pin
list-branches / rename-branch OLD NEW / delete-branch NAME
merge BRANCH [-m MSG] | merge --abort
```

Pins are heads: commits while pinned advance the pin (`status.head.kind`
tells you which world you are in). `delete-branch` refuses the current
branch. Merge refuses on drift or pending merge; clean merge = one layer
with two parents; conflict = git-style markers in files + durable pending
state (`status.merge_pending`).

JSON — branch: `{name, head, created}`; switch: `{ref, kind: branch|pin,
head}`; list-branches: `{branches: [{name, head, created_at, current}]}`;
merge: `{status: merged, layer_id, conflicts: []}` | `{status:
fast_forwarded, head, kind}` | `{status: already_up_to_date, head}` |
`{status: conflict, head, theirs, conflicts: [paths]}` (exit 1);
`--abort`: `{status: aborted, head, rescue_layer}`.

Conflict protocol: resolve `<<<<<<<`/`=======`/`>>>>>>>` blocks in each
listed path, then `commit` (the pending state supplies the second
parent). Giving up: `merge --abort` (rescues partial resolutions).
`commit` refuses leftover markers unless the human passes
`--allow-markers`.

### Undo, rescue, explore

```
amend [-m MSG]              replace the head layer (same parents);
                            nothing_to_amend when tree+message unchanged
restore REF [--to DIR]      rescue-first: drift is packed before overwrite;
                            --to extracts without touching head/worktree
export REF --to DIR         fresh-directory-only extraction (zero risk)
```

JSON — amend: `{status: amended, layer_id, replaced}` |
`{status: nothing_to_amend, layer_id}`; restore: `{status: restored,
layer_id, rescue_layer}` | `{status: exported, layer_id, to}`; export:
`{status: exported, layer_id, to}`.

### Integrity and recovery

```
verify                      re-hash every layer vs its filename; DB cross-check
verify --rebuild-db         reconstruct the DB from in-band layer meta
```

`verify` JSON: `{status: ok, layers}`; any problem = exit 3 with the full
list. `--rebuild-db` JSON: `{status: rebuilt, layers, main_head,
lost_branches[], verify}`. Branch names and pins live only in the
database: rebuild recreates `main` at the newest tip layer (newest
`created_at`, ties by id) and names every lost branch — report them;
never present a rebuild as lossless. Rebuild refuses (exit 3) on a layer
failing its self-hash or a missing parent file: restore those files
(from a `compact --archive` zip or backup) first.

### History management — compact

```
compact --keep N [--archive DIR] [--dry-run] [--yes]
```

Squashes everything below the newest N layers of the head's first-parent
chain into one foundation layer. Kept layers AND reachable off-chain
survivors (forks on the kept range, stacked branches, merge stubs) are
rewritten with new ids; branch heads follow via remap. Unreachable
layers referencing the rewritten set (amend orphans, collapsed-merge
stubs) are garbage-collected and archived with the dropped range.

Refusals (exit 1, atomic): pending merge; another branch head or the pin
inside the collapsed range; any reachable layer whose ancestry passes
through collapsed layers (the message names the branch — raise `--keep`
or merge/delete it); a kept merge whose second parent falls below the
cut. Peak-disk need is checked up front.

Agent procedure: (1) `--dry-run --json`; present the plan; (2) obtain
human `--keep`/`--yes`/optional `--archive`; (3) execute; (4) report
`kept`, `dropped`, `off_chain_rewritten`, `garbage_collected`,
`branches_remapped` (`{name, from}` in the plan; `{name, from, to}`
after), `archive`.

JSON — plan: `{status: plan, keep, layers_total, layers_dropped,
layers_rewritten, off_chain_rewritten, layers_garbage_collected,
branches_remapped, bytes_reclaimed, peak_disk_needed}`; executed:
`{status: compacted, kept, dropped, off_chain_rewritten,
garbage_collected, branches_remapped, new_head, archive}`; idle:
`{status: nothing_to_compact, layers}`.

## Error taxonomy

| Exit | Recognize | Response |
|---|---|---|
| 1 | drift / "uncommitted" | commit or rescue the drift; never discard for the user |
| 1 | "merge is pending" | resolve + commit, or `merge --abort` |
| 1 | `status: "conflict"` | conflict protocol above |
| 1 | compact refusal naming a branch/pin | raise `--keep` or merge/delete; re-plan |
| 1 | "pass --yes" / "--keep must be" | stop; ask the human |
| 3 | `firnpack: integrity failure:` | stop writes; Recovery below |
| 2 | argparse text | fix the invocation |

## Recovery

1. `verify` — read the problem list.
2. Missing layer file: drop a copy (backup, archive zip, other machine)
   into `layers/` under its id; `verify` confirms.
3. Orphan files: swept by the next mutating command; `verify` lists them
   first.
4. Lost/corrupt database: `verify --rebuild-db` (see above). Missing or
   unopenable db file: replace with an empty file first.
5. The repository is the project folder including `.firn/` — copy it
   whole to move it; `verify` on arrival.

## Things firnpack never does

No network, no remotes, no daemons, no auto-compaction, no silent
history rewrite, no staging area, no force flags. A refusal always
means the repository and worktree are untouched (rescue layers
excepted — and reported).
