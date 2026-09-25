# Wave 37 worker packets — defects found by running the product (opened 2026-09-25)

One start packet per card of `TODO.md` § "WAVE 37". The card is the contract (trigger, goal,
acceptance); this file is the map. Read **§0 once, then only your own packet.** Decisions: ROADMAP
D-41. Line numbers were measured at `594a753` and drift; the symbol name is the locator.

## 0. Rules for every worker

**Load your card, nothing else:**
`python3 .agents/skills/docket-roadmap/scripts/card_packet.py W37-C<N>`

**Isolation.** One card, one branch `w37-c<N>-<slug>`, one git worktree. Base = the commit that
opened this wave (`git log -1 --format=%h -- .agents/handoffs/wave-37-worker-packets.md` on
`main`). If your worktree was created from an older commit, rebase onto that base before starting
and compare with `git merge-base main HEAD`, never with `HEAD~N`.

**Never touch the operator's real state.** Every command that runs docket sets both variables to
a directory you created under your own temp root:

```bash
export W=$(mktemp -d) && export HOME=$W/home DOCKET_HOME=$W/home/.docket && mkdir -p $DOCKET_HOME
```

pytest already isolates `DOCKET_HOME` through autouse fixtures; use `repoint_docket_home` when a
test needs a second home. Never read or write `~/.docket`. Never call a real model endpoint: tests
use the fake drivers the neighboring tests already use.

**Order of work (AGENTS.md change contract).** 1. Read the owning spec *section* named in your
packet and the neighboring tests. 2. Amend the spec requirement text. 3. Write the RED test and
**see it fail on the base for the stated reason** (a test that fails for another reason is not
RED). 4. Implement the smallest change. 5. Focused gates, then worker gates.

**Layer rules.** `cli/ -> core/ -> edges/`, inward only. `core/` never imports `ui.py` and never
prints; it raises or returns typed results and `cli/`/`serve.py` render them. Docket-owned JSON is
written only through `edges/store.py`. Every shell-out lives in `edges/adapters/`. Every tool call
goes through `core/tools.py::dispatch_tool`.

**Integrator-owned this wave — do not edit, return the text instead:**

| Path | What you return instead |
| --- | --- |
| `TODO.md`, `ROADMAP.md` | nothing; report outcome |
| `README.md`, `CHANGELOG.md` | the exact sentence / `[Unreleased]` line you would add |
| `CONTRIBUTING.md` (test counts) | nothing; the integrator re-measures |
| `specs/README.md`, and every spec's `**Version**` / `**Last Updated**` header and `## Changelog` section | one changelog line per spec you edited |
| `scripts/maint/comment-baseline.json`, function-span baseline | the measured count if it moved |

You **do** edit the requirement text, examples and Status prose of the spec sections your packet
names. Several specs are shared between cards (`pod-dispatch`, `serve-read-api`, `cli-interface`);
the header/changelog rule above is what keeps those merges clean. Stay inside your named section.

`docs/commands.md` is generated. If you change a Typer docstring or help text, run
`uv run python scripts/gen_cli_docs.py` and commit the result; the integrator regenerates it on
any merge conflict, so never hand-merge that file.

**Goldens.** `bash tests/golden/run.sh verify-all` must stay byte-identical unless your packet
says a golden changes. If it does, regenerate only the named case and list every changed line
with the reason in your return. Never regenerate to make an unexpected diff go away.

**Never** edit counting logic in `scripts/metrics.py` or `scripts/validate-specs.sh`. Never use
`git stash`. Never widen scope: an adjacent defect becomes a locator under "Later follow-ups".
If you need a forbidden path, stop and return the contention.

**Test lanes** (`specs/test-framework.md` § "Lanes and placement"): unit = one file per `src/`
module under `tests/unit/` with a `SUBJECT`; integration = cross-module or subprocess behaviour
under `tests/integration/` with an importable `SUBJECT`; a test that reads prose or builds an
artifact is agent-lane and is not needed by any card here.

**Worker gates** (all must pass before you return):

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run pytest -q                       # default lanes
uv run pytest -q tests/guards          # includes the 150-line function-span ratchet
bash tests/golden/run.sh verify-all
bash scripts/validate-specs.sh
uv run python scripts/gen_cli_docs.py --check
uv run python scripts/maint/comment_lint.py --check <every .py file you touched>
```

`scripts/metrics.py --check` is **expected to fail** on a branch that adds tests (the count lives
in integrator-owned `CONTRIBUTING.md`). Do not fix it; say so in the return.

**Commit.** One commit per card unless the packet says otherwise. Subject `Type: description`
(`Fix:`, `Add:`, `Remove:`, `Docs:`, `Test:`), ASCII only, a body that says what was false and
what is now true. **No AI mention and no `Co-Authored-By` trailer of any kind** — this repository
rule overrides any tool default. Before committing: `git diff --cached | command grep -nE
'/home/|/tmp/claude|@gmail'` must print nothing. Do not push.

**Return** (1,500–3,000 characters, a delta, no logs):

```text
Card / branch / commit:
Outcome: complete | partial | blocked
User-visible behavior:
Changed paths and owned functions:
Spec sections edited + one changelog line per spec:
README / CHANGELOG lines for the integrator:
RED evidence: <test node id> failed on base with <one-line reason>
Focused tests: <command> -> <result>
Worker gates: <pass | first failing gate>
Goldens changed: none | <case>: <line-by-line reason>
Missing / failed:
Pending in this card:
Later follow-ups (locators only):
Contention / merge note:
```


**Worktree environment (measured in Wave 36).** A worker worktree inherits `VIRTUAL_ENV` from the
parent shell; run every `uv run` and the goldens as `env -u VIRTUAL_ENV uv run ...` /
`env -u VIRTUAL_ENV bash tests/golden/run.sh verify-all`. `click` reaches the tree only through
the `mcp` extra, and `scripts/gen_cli_docs.py` imports it: run `uv sync --all-extras` once first.
Set work aside with a WIP commit, never with `git stash` (the stash stack is shared across
worktrees).

## 1. Batches and merge order

| Batch | Cards (parallel inside the batch) | Merge order |
| --- | --- | --- |
| 1 | C1, C2, C3, C4 | C4, C1, C3, C2 |
| 2 | C5, C6 | C5, C6 |

Ownership of shared files:

| File | Owner -> functions |
| --- | --- |
| `src/docket/serve.py` | C2 (batch 1) -> everything it names · C5 (batch 2) -> the approval-error status mapping only |
| `src/docket/cli/__init__.py` | C3 -> `cmd_help` · C6 -> nothing unless a hand-dispatched command's `ctx` handling lives there |
| `src/docket/cli/_policies.py` | C1 -> the `test` subcommand · C6 -> the unknown-flag check only |
| `docs/commands.md` | generated; any card that changes help text regenerates it; the integrator regenerates on conflict |
| `pyproject.toml` | C3 -> `[project.scripts]` · C4 -> dev dependency list only (`uv.lock` too) |

---

## W37-C1 — bash allowlist builtins + `policies test` parity

**Branch:** `w37-c1-allowlist` · **Where.** `src/docket/core/security.py::SAFE_BINS` and
`classify_command` (read how redirection `>`/`>>` is handled before adding `echo`: pin today's
verdict for `echo x > f` and `echo x > /etc/passwd` in a test *first*, on the base, so the change
provably does not weaken it). `src/docket/cli/_policies.py` `test` subcommand (`subcmd == "test"`)
and `core/tools.py::evaluate_tool_call` — **import** the function the chokepoint uses; do not
edit `core/tools.py` (forbidden). If parity is impossible without editing it, return the
contention. **Spec:** `specs/functional/security-gates.spec.md` "Tool-approval gates" item 1.
**Tests:** `tests/unit/core/test_security.py`, the policies CLI tests (`rg -l "policies" tests`).
**Forbidden:** `core/tools.py`, `core/policy.py` semantics, high-risk patterns.

## W37-C2 — exactly-once trace cursor + HTTP contract gaps

**Branch:** `w37-c2-serve-contract` · **Where.** `src/docket/serve.py::_traces_page`,
`_decode_trace_cursor`, `_trace_line_ts`; the handler's response-writing helper (find where
`Content-Type` is set for JSON and text responses — add `Cache-Control: no-store` in the one
place every response passes); `do_POST` prefix routing (`/approvals/`, `/tasks/`, `/dispatch/`) and
the dead "Missing ..." branches in `_handle_post_approvals`/`_handle_post_tasks`/
`_handle_post_dispatch`; every `rfile.read(int(...Content-Length...))`. Make the clock injectable
for the hold-back rule (module-level `_now` or a parameter) so tests are deterministic — check the
trace timestamp resolution first (`core/trace.py` writer) and state it in the spec. Name the body
cap as a constant (1 MiB unless an existing constant says otherwise) and return 413.
**Spec:** `specs/data/serve-read-api.spec.md` "Cursor semantics", the Cache-Control line, POST
validation. **Tests:** `tests/unit/test_serve__read_api.py` and neighbouring serve tests.
**Forbidden:** `core/trace.py`, `core/approval.py`, the approval status mapping (C5).
**Real server check:** after the unit tests, start `docket serve --port <random 18000-18999>` in a
throwaway home (never `--telegram`), `curl -sI` one route for the header, kill it.

## W37-C3 — installed entry point + `help <command>`

**Branch:** `w37-c3-entry-point` · **Where.** `pyproject.toml` `[project.scripts]`;
`src/docket/__main__.py` (`main()` at the bottom is unconditional — guard it; keep `python -m
docket` working); `tests/guards/test_removed_commands.py` (its docstring explains why it parses the
AST — once `main` no longer runs on import it may import the map directly; keep the AST path if
simpler). Aliases: `_ALIASES` has no test; add one. `cli/__init__.py::cmd_help` +
`cli/_help.py::run_help(topic)`: for a known command, print its Typer help (e.g. via
`typer.main.get_command(app)` and the sub-command's `get_help(ctx)`), unknown -> error exit 1.
Check `packages/docket-runtime/` and `install.sh` / `bin/docket` still work unchanged, and the
Homebrew formula (`rg -n "docket" Formula 2>/dev/null` or `packaging/`) — do not edit a formula,
report it. **Spec:** `specs/api/cli-interface.spec.md` "Installed Distribution", `docket help`.
**Forbidden:** the `_REMOVED`/`_ALIASES` contents.

## W37-C4 — harness-v1 schema references

**Branch:** `w37-c4-harness-schema` · **Where.** `scripts/harness_schema.py` (builds
`{"definitions": {...model_json_schema()}}`) — hoist each nested `$defs` into one root `$defs`
(refs already say `#/$defs/X`, so they resolve once hoisted; assert no name collides with a
different body). Regenerate `docs/contracts/harness-v1/schema.json`.
`tests/integration/test_harness_contract.py`: validate every fixture in
`tests/fixtures/harness-contract/v1/` with `jsonschema` (Draft 2020-12) against the committed
file, events vs `#/definitions/HarnessEvent`, results vs `#/definitions/HarnessResult`, plus one
negative case. Add `jsonschema` to the dev dependency group if missing, record the floor you
measured, update `uv.lock`. **Spec:** `specs/api/harness-mode.spec.md` §Output (the paragraph
about the committed schema). **Forbidden:** `core/harness.py` models, the contract version.

## W37-C5 — approval conflict vs not-found (batch 2)

**Branch:** `w37-c5-approval-conflict` · **Base:** `main` after batch 1 merges. Packet completed
by the integrator at batch 2.

## W37-C6 — `cost <id> --json`, unknown flags (batch 2)

**Branch:** `w37-c6-cli-flags` · **Base:** `main` after batch 1 merges. Packet completed by the
integrator at batch 2.
