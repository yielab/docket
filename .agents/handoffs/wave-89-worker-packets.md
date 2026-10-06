# Wave 89–90 worker packets (no phase: close the carried items)

Common contract for every Wave 89–90 worker. The card itself is extracted with
`python3 .agents/skills/docket-roadmap/scripts/card_packet.py <CARD-ID>`; this file does not copy it.

## Setup
1. You are in an isolated git worktree. First run `git reset --hard develop` and confirm
   `git log -1 --format=%h` matches `git log -1 --format=%h develop`. Diff only from
   `git merge-base HEAD develop`, never from a stale base.
2. Read, bounded: your card (`card_packet.py`), your owning spec section(s), and the
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
- **Real home:** `~/.docket` does not exist (wiped 2026-10-04; it must stay absent). Every test must use the
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

## Wave 89–90 specifics
- **The card is the design.** Its Goal fixes the shape (names, scope, refusals). If the code
  contradicts the card's "Today", stop and report rather than inventing a different design.
- **Shared specs** (`security-gates`, `pod-dispatch`, `operator-loop`, `cli-interface`,
  `cli-json-shapes`) are edited by several cards: touch only your own section, plus one line under
  `Unreleased` in the changelog.
- **Isolation is on by default.** A test that needs no jail calls
  `tests/conftest.py::record_isolation_off(home)` in its own fixture; never an autouse fixture.
  Run the full suite twice: normally **and** with `scripts/maint/pytest-without-sandbox.sh -q`
  (a host with no bwrap or docker; `DOCKET_SANDBOX_BACKEND=none` alone does not simulate one).
- **Real backends:** this host has `bwrap` and a reachable docker daemon. A test that needs one
  skips with a named reason when it is absent and never fakes the jail it claims to prove.
- **No network in tests**, except W89-6's one-time `apk add git` image build, which skips when it
  cannot build. A network oracle is a failed connect or `ENETUNREACH`.
- **No compatibility shims:** a replaced registry, field or flag is deleted outright.
- **CLI surface changes** regenerate `docs/commands.md` with `scripts/gen_cli_docs.py`; a changed
  golden is explained line by line.

## Gates (all must pass in your worktree; report each exit code)
```
uv run ruff check . && uv run ruff format --check .
uv run --extra mcp mypy src
uv run --extra mcp pytest -q                                   # the FULL default suite
bash scripts/maint/pytest-without-sandbox.sh -q                # as a host with no sandbox
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
