# Wave 120 and Phase 46 stage 1: worker packet (2026-10-22)

One worker owns **one card**. The card text is the spec of the work; this file holds the rules
every worker follows. Base commit: the one your prompt names as BASE (on `plan/phase-46-structure`).

## Your card

Read only your card and the rules block above it, never `TODO.md` whole:

```bash
sed -n '/^### W120-3 /,/^### /p' TODO.md          # your card (use your id)
sed -n '/^## ◇ WAVE 120/,/^### W120-1 /p' TODO.md  # the Wave 120 rules (W120 cards only)
```

A P46 card reads `sed -n '/^### P46-2 /,/^### /p' TODO.md` and ADR 0030 (`docs/adr/0030-*.md`)
for the sections it cites. Before editing behaviour, read `.agents/skills/docket-spec-work/SKILL.md`.

## Where you work

- Only in the worktree you were given, on its branch. Never `cd` into the main checkout
  the repository root or another worktree, never check out another branch.
- Run `env -u VIRTUAL_ENV uv sync` once, then every command as `env -u VIRTUAL_ENV uv run ...`.
  The `docket` on `PATH` runs the main checkout's code, not yours: probe with
  `env -u VIRTUAL_ENV uv run docket ...`.
- Diff against the base: `git diff BASE`, never `HEAD~`.

## What you never touch

- `TODO.md`, `ROADMAP.md`, `CHANGELOG.md`, `README.md` metric counts, `specs/README.md`, spec
  `**Version**` lines: the integrator owns them. Report what changed instead.
- `scripts/maint/adopt_kernel.py` and `tests/guards/test_adopt_kernel.py`: another session is
  writing the P46-5 `errors` rule there.
- Functions your card does not name, even in a file it owns.

## Rules

- **RED first.** Write the failing test, see it fail for the stated reason, then fix. A defect
  marked *unverified* that does not reproduce is dropped and reported, not fixed.
- **The spec changes with the code.** Rewrite the requirement you change in the owning spec, keep
  its number, add nothing to `## Implementation` but the names you add or remove. No history in a
  spec ("was", "since", "fixed", card ids).
- **No compatibility shims** (D-57). A deleted function, flag or field goes with its tests, spec
  text and docs.
- **Kernel.** New raises use `docket.kernel.errors` kinds (`InvalidInput`, `NotFound`, `Conflict`,
  `Refused`, `Unavailable`, `DocumentError`). Clock, ids and text go through `kernel.clock`,
  `kernel.ids`, `kernel.text`. If your change moves a count of
  `uv run python scripts/maint/measure_kernel_adoption.py --check`, run it with `--write` and
  report the before and after.
- **Probes.** `d=$(mktemp -d); cd "$d"`, run, then `rm -rf "$d"`: that one directory, never a
  glob. Never touch `~/.docket`. Never contact a hosted service; use `http://127.0.0.1:9/v1`.
- **Goldens.** A golden changes only when your card says that output changes; explain each line.
- **Commits.** On your branch only, explicit paths (`git add <file>`), never `git add -A`, never
  `git stash`. Subject `Type: description` (`Fix:`, `Add:`, `Docs:`, `Refactor:`), ASCII only, a
  body that says what and why, and no AI or Co-Authored-By trailer.

## Gates before you return

```bash
env -u VIRTUAL_ENV uv run ruff check . && env -u VIRTUAL_ENV uv run ruff format --check .
env -u VIRTUAL_ENV uv run mypy src
env -u VIRTUAL_ENV uv run pytest -q              # the default lanes
env -u VIRTUAL_ENV bash tests/golden/run.sh verify-all
bash scripts/validate-specs.sh
env -u VIRTUAL_ENV uv run python scripts/gen_cli_docs.py --check
env -u VIRTUAL_ENV uv run python scripts/maint/comment_lint.py --check <files you touched>
```

A failure you believe is not yours: prove it on the base commit in a scratch worktree
(`git worktree add <scratch> BASE`, remove it after), never with a stash.

## Return (short; no logs)

- **Branch / commits** (ids and subjects).
- **Defects:** per number, fixed / deleted / dropped (did not reproduce), with the RED test name.
- **Specs changed:** file and requirement numbers; MAJOR or PATCH and why.
- **Goldens / kernel counts / CLI docs** changed, with the reason.
- **Gates:** pass, or which failed and why.
- **Seams:** any value your change exchanges with a function another card owns.
- **Not done / risks.**
