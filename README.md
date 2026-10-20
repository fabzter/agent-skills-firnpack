# agent-skills-firnpack

The firnpack VCS as an installable agent skill: exactly two files —
`SKILL.md` (the operating contract) and `firnpack.py` (the engine,
pure standard library, zero dependencies).

The `firnpack/` submodule pins the engine to a tested release (the
`v1.0.0` tag); the root copy is what installs. CI guards two things on
every push: the root copy is byte-identical to the pinned engine, and
the engine's own test suite passes against that copy.

Install: copy `SKILL.md` and `firnpack.py` into your skill directory.

Engine source of truth: <https://github.com/fabzter/firnpack> —
upgrade by re-pinning the submodule to a newer tag and refreshing the
copy.
