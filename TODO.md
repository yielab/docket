# TODO — active task board

> **This is docket's single standing TODO file.** It holds the executable cards for whatever phase is
> currently active in [ROADMAP.md](ROADMAP.md). Do **not** create per-phase task files — when a phase
> finishes, clear its cards (the phase record stays in ROADMAP) and append the next phase's cards here.
>
> **History lives elsewhere.** Every closed wave and phase section that used to sit in this file is
> archived verbatim in [docs/cycles-ended/](docs/cycles-ended/README.md) (`todo-waves.md`, with a
> SHA-256 manifest). This file holds only the usage rules, the active section and planned sections.
> Do not mine the archive for work.
>
> ---
>
> ## ◆ WAVE 37 ACTIVE (opened 2026-09-25) — defects found by running the product
>
> Board was clear after Wave 36. A bounded triage on 2026-09-25 (six read-only workers, one
> surface each, base `594a753`) found twelve reproducible defects; ROADMAP **D-41** records the
> three design decisions. Cards below; worker packets in
> [.agents/handoffs/wave-37-worker-packets.md](.agents/handoffs/wave-37-worker-packets.md).
> Batch 1 (C1–C4) runs in parallel; batch 2 (C5, C6) starts after batch 1 merges.
> `v0.2.0-beta.3` (2026-09-18) is the latest release; the next beta stays a maintainer action.
> Still open as maintainer decisions, not cards: wiring or retiring `docket gates
> enable/disable` (`specs/functional/security-gates.spec.md`).
>
> **Scheduling rule:** schedule by **file contention**, not phase number, and state ownership at
> **function** level when a file is hot (`core/tools.py` is the recurring hotspot: give one card a
> single lambda, forbid the file to another, let a third import it unchanged). A conflict is
> resolved by keeping both blocks and *importing the module* to assert nothing was lost, never by
> reading the diff and assuming.

## How to use this board (read before claiming a task)

1. **Claim:** set Status → `IN-PROGRESS (@you)`. One agent per task.
2. **Read first (bounded):** use `$docket-roadmap` to load the active card, its named ROADMAP
   decision/section, the owning spec, and the card's own "Read" list. Do not ingest all of
   `ROADMAP.md`, `TODO.md`, or local `CLAUDE.md` as startup context.
3. **Layer rule (non-negotiable):** `cli/ → core/ → edges/`, inward only. docket-owned JSON goes
   **only** through `edges/store.py` (JSONL append logs are the one D-12 exemption), external
   protocols terminate in `edges/adapters/`, and there is no compatibility layer for the retired
   daemon. Every shell-out goes through `edges/adapters/`. `core/`/`edges/` never import `ui.py` or
   print (D-3 from Phase 12).
4. **No-behavior-change rule, except where a card says otherwise:** the golden suite
   (`bash tests/golden/run.sh verify-all`) must stay byte-identical unless a card explicitly adds new
   CLI surface — those cards say so and require regenerated goldens with the diff explained.
   **Regenerating a golden to paper over an unintended behaviour change is never acceptable**; W-6 in
   particular must prove the four legacy roles still emit byte-identical workspaces.
5. **Definition of done (per task):** acceptance criteria pass · a pytest covers it (add/refresh a
   golden case if output changes) · `uv run ruff check . && uv run ruff format --check . && uv run
   mypy src && uv run pytest` green · `bash tests/golden/run.sh verify-all` green ·
   `bash scripts/validate-specs.sh` green · `uv run python scripts/gen_cli_docs.py --check` green
   (regenerate `docs/commands.md` whenever a Typer docstring or help text changes) · `uv run pytest
   tests/agent` green when prose or an artifact moved · the integrator re-measures
   `scripts/metrics.py --check` per batch (card branches that add tests fail it by design) · the
   card's own spec updated with a version bump + changelog entry (integrator-applied in a
   multi-agent wave), **Status line matching what actually shipped** · committed `Type: description`
   (no Claude/Co-Authored-By trailer) · public-repo privacy scrubbed (grep the diff for real names /
   `/home/<user>` paths before committing).
6. **Central files:** `ROADMAP.md`, `TODO.md` and `README.md`'s metric counts are maintained by the
   integrator, **not** by card branches. Phase 14 lost time to roll-up checkboxes and README test
   counts conflicting on nearly every merge; cards now report what they shipped instead of editing
   the board.

**Status legend:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs X)` · `DONE`
**Size:** S ≈ ½ day · M ≈ 1–2 days · L ≈ 3–5 days (split before claiming if L)
**Branch model:** **`main`** is the canonical public/default and release lineage (D-31). Use one
short-lived card branch or isolated worktree per task and integrate it into `main` without rewriting
history. `platform` may remain as a synchronized historical/integration ref, but it is not a second
release source.

---

---

## ◆ WAVE 37 — defects found by running the product (D-41)

Every card: spec section first, RED test seen failing on the wave base for the stated reason,
smallest change, the §"How to use this board" definition of done. Board, ROADMAP, README,
CHANGELOG, spec headers/changelogs and `specs/README.md` are integrator-owned.

### W37-C1 — a `cd` prefix must not turn an allowed command into an approval

**Status:** TODO · **Size:** S · **Batch:** 1

**Trigger (deterministic, live):** `core/security.py::classify_command("cd /x && git status")`
returns `ask` ("'cd' is not on the curated allowlist") while `git status` returns `allow`; `pwd`
and `echo` ask too. On the 2026-09-25 journey run the implementer's five `cd <worktree> && ...`
calls each timed out (120s) with no channel and the hop died on the consecutive-denial limit,
after the fix was already written. `docket policies test pre_tool_call implementer 'cd x && git
status'` reports `allow` for the same command, because it dry-runs only the declarative hook.

**Goal:** add the builtins `cd`, `pwd`, `echo`, `true`, `false`, `test` and `[` to `SAFE_BINS`;
make `docket policies test pre_tool_call` report the same verdict the live gate would, by
evaluating through the same function the chokepoint uses (`core/tools.py::evaluate_tool_call` or
the piece of it that combines `classify_command` with the policy hook) rather than a copy.

**Non-goals:** `export`, `source`, `.`, `eval`, `exec` stay off the allowlist (they change what
later segments run). No change to high-risk class patterns or to `core/tools.py::dispatch_tool`.

**Owns:** `core/security.py::SAFE_BINS` (+ docstring), `cli/_policies.py` test subcommand, their
unit tests, `security-gates.spec.md` "Tool-approval gates" item 1 text.

**Acceptance / oracle:** `cd /x && git status`, `pwd`, `echo hi` -> allow; `cd /x && git push
origin production` still asks with the prod-deploy class; `echo x > /etc/passwd` and `echo x >
f` are classified exactly as before the change (prove redirect handling is not weakened with a
test that pins the base verdict); `export X=1 && ls` still asks; `policies test` output for a
`cd`-prefixed ask-class command names the classifier verdict.

**RED:** the three allow assertions and the `policies test` parity assertion fail on the base.

### W37-C2 — HTTP control plane: exactly-once trace cursor and small contract gaps

**Status:** TODO · **Size:** M · **Batch:** 1

**Trigger (deterministic):** `serve.py::_traces_page` — deliver `b.jsonl` line at second S, then
append a line at S to `a.jsonl`: the next poll with the returned `next` re-delivers the `b` line
and never delivers the `a` line (spec `serve-read-api` "Cursor semantics" promises exactly-once
across a same-second boundary). Also: `Cache-Control: no-store` is promised
(`serve-read-api.spec.md:68`) and never sent; POST to bare `/approvals`, `/tasks`, `/dispatch`
returns 404 before auth, so their "Missing ..." 400 branches are dead; `Content-Length` is read
uncapped with no timeout (a lying client pins a handler thread).

**Goal (D-41):** a page never includes events from a second that is not yet closed (`ts >= now -
1s` is held back), so a late same-second line in any file is delivered in its own later poll;
the `(ts, n)` wire format is unchanged. Send `Cache-Control: no-store` on every response. Bare
POST paths go through auth then return the documented 400. Reject a body over a named cap
(413) and bound the read with a socket timeout.

**Non-goals:** a new cursor format, streaming/push, `core/trace.py` retention, approval status
mapping (that is C5).

**Owns:** `serve.py` only (`_traces_page`, response header helper, `do_POST` routing, body read)
plus `tests/unit/test_serve__read_api.py` / neighbouring serve tests and `serve-read-api.spec.md`
"Cursor semantics" and the POST/validation sections.

**Acceptance / oracle:** the two-file same-second fixture (with an injectable clock) delivers
every line exactly once across three polls; a poll whose newest events are in the open second
returns them on a later poll, never twice; every route's response carries `Cache-Control:
no-store`; `POST /approvals` without a token -> 401, with a token -> 400 "Missing ..."; a
`Content-Length` above the cap -> 413 without reading the body.

**RED:** the two-file test duplicates/drops on the base; the header and bare-POST tests fail.

### W37-C3 — the installed `docket` command honours aliases, removed-command notices and `help <command>`

**Status:** TODO · **Size:** S · **Batch:** 1

**Trigger (deterministic, sixth unwired-machinery instance):** `pyproject.toml` `[project.scripts]
docket = "docket.cli:app"` bypasses `docket/__main__.py::main`, so on every pip/uv/Homebrew
install `docket team` prints "No such command" (exit 2) instead of the retirement notice (exit 1)
and the 13 `_ALIASES` do not resolve; `tests/guards/test_removed_commands.py` only runs `python -m
docket`. Separately `cli/__init__.py::cmd_help` accepts `topic` and calls `run_help()` without it
(`cli-interface.spec.md` `docket help [command]` promises per-command usage).

**Goal:** point the console script at an importable `main` that does not run on import (move the
unconditional `main()` call under `if __name__ == "__main__":`); `packages/docket-runtime` is
unaffected. `docket help <command>` prints that command's usage (its Typer help) and exits 0, or
names the unknown command and exits 1; bare `docket help` is unchanged.

**Non-goals:** new aliases, changing the removed-command map, rewriting `_help.py`'s reference.

**Owns:** `pyproject.toml` `[project.scripts]`, `__main__.py`, `cli/__init__.py::cmd_help`,
`cli/_help.py::run_help`, `tests/guards/test_removed_commands.py`, alias tests,
`cli-interface.spec.md` "Installed Distribution" + `docket help` sections, `docs/commands.md`
(regenerated).

**Acceptance / oracle:** a test invokes the *console-script entry point* (the object named in
`pyproject.toml`, resolved via `importlib.metadata` or by import path) for one removed command and
one alias and gets the notice / the aliased command; `docket help doctor` differs from `docket
help` and contains `doctor`'s usage; goldens byte-identical except any case the card explains.

**RED:** the entry-point test gets "No such command" on the base; `help doctor` equals `help`.

### W37-C4 — the published harness-v1 schema validates real results

**Status:** TODO · **Size:** S · **Batch:** 1

**Trigger (deterministic):** `docs/contracts/harness-v1/schema.json` nests
`HarnessResult.model_json_schema()` under `definitions.HarnessResult`, whose `$ref`s point at
`#/$defs/BlockedInfo` etc.; the document has no root `$defs`, so a standard validator given
`$ref: #/definitions/HarnessResult` raises `PointerToNowhere`. The contract test compares bytes
and validates through pydantic, never through the file as JSON Schema.

**Goal (D-41):** `scripts/harness_schema.py` hoists every nested `$defs` to the document root
(rewriting nothing else); the contract stays `1.0.0` with a spec changelog line; a test validates
every fixture under `tests/fixtures/harness-contract/v1/` against the committed file with
`jsonschema` (add it as a dev dependency if absent, respecting the floors job).

**Non-goals:** changing any field, the contract version, or the pydantic models.

**Owns:** `scripts/harness_schema.py`, `docs/contracts/harness-v1/schema.json` (regenerated),
`tests/integration/test_harness_contract.py`, `harness-mode.spec.md` §Output text, dev deps.

**Acceptance / oracle:** each fixture event/result validates against `#/definitions/HarnessEvent`
/ `#/definitions/HarnessResult` of the committed file; a deliberately invalid result (bad
`status`) fails validation; regenerating the file is byte-stable.

**RED:** the fixture validation raises `PointerToNowhere` on the base.

### W37-C5 — resolving an already-resolved approval the other way is a conflict, not "not found"

**Status:** TODO · **Size:** S · **Batch:** 2 (after C2 merges; both touch `serve.py`)

**Trigger:** `core/approval.py` raises plain `ApprovalError` for grant-after-deny and
deny-after-grant, the same type as an unknown token, so `POST /approvals/<token>` answers 404 for
a token that exists. The same seam is the measured flake
`tests/integration/test_agent_loop.py::TestCooperativeRunCancellation::test_cancellation_after_concurrent_approval_grant_never_runs_handler`:
the test's grant loses the race to the cancellation self-deny (forced race: 117/117 raise; natural
rate 0 in ~1300 runs under load, 1 in 3 full-suite runs historically).

**Goal:** a distinct `ApprovalConflict` (subclass of `ApprovalError`, so existing callers still
catch it) for opposite-action-on-resolved; HTTP maps it to 409; CLI `approve`/`deny` print which
decision won; the test accepts either winner and asserts the invariant (`handler_calls == []`,
`stop_reason == "run_cancelled"`).

**Owns:** `core/approval.py::_set_state` and its exception types, serve's approval error mapping,
`cli/_approve.py`/`cli/_deny.py` messages, the named test, approval spec section.

**Acceptance / oracle:** grant then deny -> 409 with the winning state named; unknown token ->
404 unchanged; same-action repeat -> 409 unchanged; the barrier-forced race test passes 50/50.

**RED:** deny-after-grant returns 404 on the base.

### W37-C6 — `cost <id> --json` scopes to the id; manual-dispatch commands reject unknown flags

**Status:** TODO · **Size:** S · **Batch:** 2 (after C3 merges; both may touch `cli/__init__.py`)

**Trigger:** `cli/_cost.py::run_cost` returns the fleet snapshot for `--json` before reading
`agent_id`, so `docket cost <id> --json` returns every agent and a bogus id exits 0 (sibling
commands exit 1). `docket roles list --json` prints the table and exits 0: commands that dispatch
`ctx.args` by hand never reject unknown options.

**Goal:** `cost <id> --json` emits that agent's row in the documented shape (amend
`cli-json-shapes.spec.md`), unknown id -> stderr error, exit 1. Hand-dispatched commands (`roles`,
`pod`, `maintain`, `gates`, `keys`, `policies`) reject an unrecognised `--flag` with exit 2 and
the usage line, through one shared helper.

**Owns:** `cli/_cost.py`, the `ctx.args` parsers in those modules, a shared helper in `cli/`,
their tests, `cli-json-shapes.spec.md`, `docs/commands.md` (regenerated).

**Acceptance / oracle:** `cost <real> --json` has exactly one agent; `cost bogus --json` exit 1,
nothing on stdout; `roles list --json` exit 2; every documented flag of those commands still
works (goldens unchanged).

**RED:** the three assertions fail on the base.

