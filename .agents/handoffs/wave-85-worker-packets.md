# Wave 85–87 worker packets (Phase 38, D-55, ADR 0020)

Common contract for every Phase 38 worker. The card itself is extracted with
`python3 .agents/skills/docket-roadmap/scripts/card_packet.py <CARD-ID>`; this file does not copy it.

## Setup
1. You are in an isolated git worktree. First run `git reset --hard develop` and confirm
   `git log -1 --format=%h` matches `git log -1 --format=%h develop`. Diff only from
   `git merge-base HEAD develop`, never from a stale base.
2. Read, bounded: your card (`card_packet.py`), the named section of
   `docs/adr/0020-the-execution-envelope.md`, your owning spec section(s), and the
   neighbouring tests of the functions you own. Do not read ROADMAP.md, TODO.md or CLAUDE.md
   wholesale.

## Rules
- Spec first: amend the owning spec's requirement text, and add one line under an `Unreleased`
  heading in that spec's changelog (create the heading if absent). Do not bump the version; the
  integrator does.
- RED first: write a behavioural test, run it, and see it fail for the right reason before
  implementing. Drive real functions, not copies; never fabricate a data shape a real writer
  does not produce -- read the writer.
- Layering: `cli -> core -> edges`; `core/tools.py::dispatch_tool` is the only tool chokepoint;
  `edges/store.py` is the only writer of docket-owned JSON (JSONL logs are the D-12 exemption).
- Stay inside your allowed files/functions. If you need a forbidden one, stop and report the
  contention instead of editing it. Adjacent defects go in "Later follow-ups", not in your diff.
- **Real home:** `~/.docket` does not exist (wiped 2026-10-04). Every test must use the
  existing tmp `DOCKET_HOME` fixtures. Before and after your test runs, `ls -d ~/.docket` must
  fail. If it exists after your run, find what created it (`find ~/.docket -newer <marker>`),
  fix your test isolation, and remove only what your tests created.
- Never `git stash` (shared across worktrees); set work aside with a WIP commit. Never merge,
  push, rebase onto anything but develop, or edit `TODO.md`, `ROADMAP.md`, `CONTRIBUTING.md`,
  `README.md` metric counts, or `specs/README.md`.
- Comments and docstrings: match the surrounding density; docstrings at most 3 lines; no card
  ids in code comments or docstrings.
- Commit on your branch: subject `Type: description` (Add:/Fix:/Docs:/Refactor:/Test:), ASCII
  only, a body that says what and why, and **no AI or Co-Authored-By trailer**. Grep the diff for
  `/home/` paths and real names before committing.

## Phase 38 specifics
- **Shared spec:** `specs/functional/security-gates.spec.md` is edited by several cards at once.
  Touch only your own section, plus one line under `Unreleased` in its changelog.
- **Real backends:** this host has `bwrap` and a reachable docker daemon. A test that needs a real
  backend skips with a named reason when it is absent (see `tests/integration/test_sandboxed_exec.py`),
  and never fakes the jail it claims to prove.
- **Isolation default (Wave 85 onward):** after P38-3 merges, a home with no `fleet.json` is
  isolated. A test that needs no jail writes an explicit off in its own fixture. Never add an
  autouse fixture that turns isolation off for the whole suite.
- **No network in tests.** A network oracle is a failed socket creation or `ENETUNREACH`, never a
  completed connection to a real host.

## Gates (all must pass in your worktree; report each exit code)
```
uv run ruff check . && uv run ruff format --check .
uv run --extra mcp mypy src
uv run pytest -q                        # the FULL default suite, not a subset
env -u VIRTUAL_ENV bash tests/golden/run.sh verify-all
bash scripts/validate-specs.sh
uv run --extra mcp python scripts/gen_cli_docs.py --check
uv run python scripts/harness_schema.py --check
uv run python scripts/gen_operator_schemas.py --check
uv run python scripts/gen_evidence_schema.py --check
uv run python scripts/gen_config_schemas.py --check
uv run python scripts/gen_recipe_docs.py --check
uv run python scripts/maint/comment_lint.py --check <touched .py files>
ls -d ~/.docket                          # must fail
```
`scripts/metrics.py --check` is expected to fail on a card that adds tests; the integrator owns it.
A golden changes only when your card changes CLI output on purpose; explain every changed line.

## Return (a delta, 1,500–3,000 characters)
```
Card / commit (full sha) / branch:
Outcome: complete | partial | blocked
User-visible behaviour:
Changed paths and owned functions:
Spec text changed (file + section):
Acceptance oracles -> test node ids:
RED evidence: <test id> failed with <one line> before the fix
Gates: <each command> -> exit code
~/.docket after tests: absent | present (explain)
Missing / failed:
Later follow-ups:
```
