---
name: firnpack
description: Operate the firnpack single-file VCS — commit, branch, merge, amend, restore, verify, compact — with JSON output, rescue-first safety, and permission-gated history rewrites. Use when a project contains a .firn/ repository or the firnpack/firn commands are available.
---

# firnpack — operator skill

firnpack is a single-user, decentralized-ish VCS: every commit is one
compressed, checksummed, immutable layer file; `.firn/` contains
`glacier.db`, `config`, and `layers/`. No remotes, no staging
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
   commit it, or let `restore` rescue it (`merge --abort` also rescues
   while a merge is pending). Report the saved `rescue_layer` to the human.
2. **Compact only with human parameters.** `--keep N` and `--yes` must
   come from the human, per invocation. Always show `--dry-run` first.
   Report `branches_remapped` and `garbage_collected` afterwards.
3. **Never silent.** Surface these when present: `branches_remapped`,
   `off_chain_rewritten`, `garbage_collected`, `rescue_layer`,
   `history_reminder`, `maxpath_warning`, `flattened_pending`,
   `nested_gitignore`, `ignored_count`.
4. **Verify after external events** (copy, power loss, old clone):
   `verify`. Exit 3 = stop writing; follow Recovery below.
5. **Ids are opaque 40-hex content hashes.** Prefixes of at least 6
   hex characters resolve uniquely or error (`ambiguous` / `too
   short`); never construct or truncate one yourself.
6. **One process at a time per repository.** No parallel commands
   against one `.firn/` — the orphan sweep cannot tell another
   writer's in-progress layer from garbage.
7. **Never pass a content-override flag on your own.** `--allow-markers`,
   `--allow-binary-conflict`, `--allow-flattened`, `compact --yes` and a
   compact `--keep` value are human decisions, per invocation.

## Process contract

- `--json` on every command except `init`, `rename-branch` and
  `delete-branch`: on success, exactly one JSON object on stdout; human
  notes on stderr. The documented marker/binary refusals
  (`blocked_by_markers`, `blocked_by_binary_conflict`) also emit one
  JSON object; any other failure may leave stdout empty. Parse stdout
  only — never treat stderr as a schema.
- Exit codes: `0` success (incl. explicit no-ops), `1` refused/failed
  with a humane `firnpack: …` sentence, `2` CLI usage error, `3`
  integrity failure. Match on the exit code first, message second.
- Exit 1 alone does NOT mean nothing changed. Documented eligibility
  checks for `commit`, `amend`, `merge`, `switch` and `compact` precede
  those commands' data writes. But a `conflict` or marker-blocked
  `merge` leaves materialized files and durable pending state; failed
  `restore` and fast-forward `merge` attempt rollback and report its
  outcome; an I/O failure can leave partial writes. Database rebuild
  can initialize schema even when later integrity checks fail. Read
  the command's contract and recovery message.
- Read-only forms: `status`, `history`, `diff`, `verify` without
  `--rebuild-db`, `export`, `restore --to`, `list-branches`,
  `compact --dry-run`.
  Exports write only their (missing-or-empty) destination — pick one
  outside the worktree.

## Commands

### Daily loop

```
init [PATH]                 create .firn/ (seeds .gitignore "~$*" if absent)
commit [-m MSG] [--allow-markers] [--allow-binary-conflict]
                [--allow-flattened]
                            pack the worktree; auto-message without -m;
                            consumes a pending merge (records second parent)
status [--full] [--ignored] drift vs head (stat-cache fast path; --full
                            rehashes; always rehashes while a merge is
                            pending)
history [-n N] [--all] [BRANCH]
diff                        per-path line diffs vs head
```

JSON keys — commit: `{status: packed, layer_id, tree_id, files, size,
message, [maxpath_warning], [history_reminder]}` |
`{status: nothing_to_pack, layer_id, files}`; status:
`{head: {id, kind, [branch]}|null, clean, modified[], added[], missing[],
ignored_count, ignored[], nested_gitignore, merge_pending,
flattened_pending}`; history: `{commits: [{id, tree_id, parent,
second_parent, message, author, created_at, tips[]}], count}`; diff:
`{entries: [{path, status: added|modified|deleted, binary, hunks?|size?}]}`.

Tracking honors the root `.gitignore` only; nested ones are reported,
not applied. `.git/` directories and the top-level `.firn/` are never packed.

`commit` guards every commit that would write a layer (a no-op still
says `nothing_to_pack`):

- **Marker guard**: refuses (exit 1) while any tracked text file —
  including files unchanged since a marker was committed with
  `--allow-markers` — has a line starting `<<<<<<<` or `>>>>>>>` (a
  UTF-8 BOM before it is ignored; `=======`, mid-line markers, binary
  files and symlinks are not flagged). `--json` refusal:
  `{status: blocked_by_markers, blocked_by_markers: [paths]}`.
  Overrides are per-invocation `--allow-markers` (also on `amend`) or
  config `[merge] block_unresolved_markers = false`. The config
  override persists; both overrides warn on stderr when markers are packed.
- **Binary-conflict guard** (only while a merge is pending): refuses
  (exit 1, `blocked_by_binary_conflict`) while a binary file both
  branches changed still holds exactly your version — finishing would
  silently drop theirs. Put other content in it (e.g. `export` their
  branch head and copy it), pass `--allow-binary-conflict` to keep
  yours on purpose (warns, naming the paths), or `merge --abort`.
- **Storable-name guard**: refuses names the read side would reject —
  a file literally named `__firnpack_meta__`, path separators the
  layer format forbids, Windows device names.

Symlink flattening is deferred past 1.0. The `flattened_pending` status
field, `--allow-flattened` flag and `core.allow_flattened` setting are
reserved; no normal 1.0.1 command creates that pending state.

### Branching

```
branch NAME [FROM]          create at HEAD or FROM (stays put)
switch REF                  branch name, or layer-id prefix => pin
list-branches / rename-branch OLD NEW / delete-branch NAME
merge BRANCH [-m MSG] | merge --abort
```

Pins are heads: commits while pinned advance the pin (`status.head.kind`
tells you which world you are in). `delete-branch` refuses the current
branch and warns on stderr when the deleted tip is left unreachable
from every branch and from where you are — it stays on disk until a
compact; re-attach with `branch NAME <id>`. Merge refuses on drift or
pending merge; clean merge = one layer with two parents; conflict =
git-style markers in text files + durable pending state
(`status.merge_pending`).

JSON — branch: `{name, head, created}`; switch: `{ref, kind: branch|pin,
head}`; list-branches: `{branches: [{name, head, created_at, current}]}`;
merge: `{status: merged, layer_id, conflicts: []}` | `{status:
fast_forwarded, head, kind}` | `{status: already_up_to_date, head}` |
`{status: conflict, head, theirs, conflicts: [paths], [kept_sides:
{path: ours|theirs}]}` (exit 1) | `{status: blocked_by_markers,
blocked_by_markers: [paths]}` (exit 1 — the automatic commit was
blocked; merged files and pending state remain for resolution or
abort); `--abort`: `{status: aborted, head, rescue_layer}`.

Conflict protocol: for each path in `conflicts`, read the file. Text
conflicts carry `<<<<<<<`/`=======`/`>>>>>>>` blocks — resolve them.
Delete/modify conflicts keep the modified side and the JSON names it
in `kept_sides`; binary conflicts hold your bytes with no markers —
decide the content with the human (`export` `theirs` to a scratch dir
and copy it in, or `merge --abort`; `--allow-binary-conflict` only
when the human says keep ours). `head` and `theirs` are the two source
layer ids for inspection. Then `commit` — the pending state supplies
the second parent. Giving up: `merge --abort` (rescues partial
resolutions; `rescue_layer` may be null when there was nothing to
save).

### Undo, rescue, explore

```
amend [-m MSG] [--allow-markers]
                            replace the head layer (same parents);
                            nothing_to_amend when tree unchanged and no -m;
                            same marker refusal as commit (never mid-merge)
restore REF [--to DIR]      rescue-first: drift is packed before overwrite;
                            --to extracts without touching head/worktree
                            (destination must be missing or empty)
export REF --to DIR         missing-or-empty destination; worktree unchanged
```

**`restore` moves the head** (branch head or pin) — a later commit
builds on that older layer. Report `previous_head` to the human; "to
come back" is `restore <previous_head>`. If the file rewrite fails,
restore attempts to put the previous head and files back and the error
says whether rollback succeeded or files may be partly written; a
rescue layer already saved is still named with its export command.
A failed `export`/`restore --to` can leave a partially extracted
destination. Symlinks a platform cannot create (e.g. Windows without
Developer Mode) stop `restore`, `export` and `merge` at the first link
with a plain exit 1. Restore and fast-forward merge attempt rollback;
a non-fast-forward merge leaves pending state and possibly partial files
for `merge --abort`. The designed `--flatten-symlinks` opt-in is deferred
past 1.0.

JSON — amend: `{status: amended, layer_id, replaced}` |
`{status: nothing_to_amend, layer_id}` | `{status: blocked_by_markers,
blocked_by_markers: [paths]}` (exit 1); restore: `{status: restored,
layer_id, rescue_layer, previous_head}` | `{status: exported, layer_id,
to}`; export: `{status: exported, layer_id, to}`.

### Integrity and recovery

```
verify                      re-hash every layer vs its filename; DB cross-check
verify --rebuild-db         reconstruct the DB from in-band layer meta
```

`verify` JSON: `{status: ok, layers}`; any problem = exit 3 with the full
list. `--rebuild-db` JSON: `{status: rebuilt, layers, main_head,
lost_branches[]|null, verify}`. Branch names and pins live only in the
database: rebuild recreates `main` at the newest tip layer (a layer no
other layer descends from; newest `created_at`, ties by id) — report
them; never present a rebuild as lossless. `lost_branches` is `null`
(not `[]`) when the old database was missing, empty or unreadable —
the names are then unknowable, which is not "none were lost". Rebuild
refuses (exit 3) on a layer failing its self-hash or a missing parent
file: restore those files (from a `compact --archive` zip or backup)
first. The SQLite `config` and reserved `refs` tables survive a
readable database's rebuild; they cannot be recovered from layers.

### History management — compact

```
compact --keep N [--archive DIR] [--dry-run] [--yes]
```

Squashes everything below the newest N layers of the head's first-parent
chain into one foundation layer. `--keep` is required (no default) and
N must be at least 1 — zero and negative values refuse (exit 1) in
every mode including `--dry-run`; a non-number is a usage error (exit
2). Kept layers AND reachable off-chain survivors (forks on the kept
range, stacked branches, merge stubs) are rewritten with new ids;
branch heads follow via remap. Unreachable layers referencing the
rewritten set (amend orphans, collapsed-merge stubs) are
garbage-collected and archived with the dropped range.

Refusals (exit 1, checked before anything is written — `.firn/layers/`
stays byte-identical, stray leftovers included, and a refused compact
never sweeps): pending merge; `--keep` below 1; another branch head or
the pin inside the collapsed range; any reachable layer whose ancestry
passes through collapsed layers (the message names the branch when one
points there — raise `--keep` or merge/delete it; a bare merge edge is
cleared only by a higher `--keep`); a kept merge whose second parent
falls below the cut. Peak-disk need is checked up front.

Agent procedure: (1) `--dry-run --json`; present the plan; (2) obtain
human `--keep`/`--yes`/optional `--archive`; (3) execute; (4) report
`kept`, `dropped`, `off_chain_rewritten`, `garbage_collected`,
`branches_remapped` (`{name, from}` in the plan; `{name, from, to}`
after), `archive`.
Executed `kept` counts the N retained layers plus the new foundation;
the plan's `keep` is the requested N.

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
| 1 | `status: "blocked_by_markers"` | remove the markers and commit again; `--allow-markers` only when the human insists |
| 1 | `status: "blocked_by_binary_conflict"` | decide content with the human, `merge --abort`, or `--allow-binary-conflict` when the human says keep ours |
| 1 | compact refusal naming a branch/pin | raise `--keep` or merge/delete; re-plan (a "still referenced" edge = raise `--keep` only) |
| 1 | "pass --yes" / "--keep must be" | stop; ask the human |
| 1 | `firnpack: file system error:` | full disk, read-only folder, file held by OneDrive/antivirus; free it and `verify` before retrying |
| 1 | `firnpack: the database could not be used` | another process or a sync client has `glacier.db` open; wait and retry |
| 1 | `firnpack: cannot read …/config` | invalid INI/UTF-8 blocks every command — fix or delete the file (defaults apply) |
| 1 | `firnpack: cannot use …/config` | wrong-typed value names the key; blocks `commit`/`amend`/`merge` only — status/verify/export still work |
| 3 | `firnpack: integrity failure:` | stop writes; Recovery below |
| 2 | argparse text | fix the invocation |

## Config file

`.firn/config` (INI, UTF-8, `%` is literal). Wrong-typed values in
`history.reminder_threshold` (int), `merge.block_unresolved_markers`,
`core.autoname`, `core.allow_flattened` (booleans) refuse `commit`,
`amend` and `merge` before any write; inspection, `export` and `verify`
stay usable. Invalid INI syntax or non-UTF-8 fails every command that
opens the repository — fix or delete the file (defaults apply). An
existing but unopenable file warns on stderr and falls back to
defaults. `user.name` is the author; `history.reminder_threshold`
(default 50) paces `history_reminder`.

## Recovery

1. `verify` — read the problem list.
2. Missing layer file: drop a copy (backup, archive zip, other machine)
   into `layers/` under its id; `verify` confirms.
3. Orphan `.firn` files with no DB row are listed by `verify`; stray
   `*.tmp` files are not. A commit that packs, amend that writes, or
   compact that executes sweeps both kinds. No-op forms and eligibility
   refusals do not sweep; locked leftovers are reported on stderr and
   retried later.
4. Lost/corrupt database: `verify --rebuild-db` (see above). A missing
   `glacier.db` is created; an empty or table-less one is re-schematized
   in place; a file unreadable as SQLite must be backed up and replaced
   with an empty file first. Report `lost_branches`; `null` means the
   names were unknowable.
5. The repository is the project folder including `.firn/` — copy it
   whole to move it; `verify` on arrival.

## Things firnpack never does

No network, no remotes, no daemons, no auto-compaction, no automatic
garbage collection outside an explicit `compact`, no silent history
rewrite, no staging area, no force flags. The documented eligibility
refusals of `commit`, `amend`, `merge`, `switch` and `compact` precede
those commands' data writes — not a blanket atomicity promise: merges
deliberately leave durable pending state and merged files, restore/abort
can leave reported rescue layers, rebuild can initialize schema before
an integrity refusal, and I/O failure can leave partial writes. Read the
error's account of what was written and what it put back.
