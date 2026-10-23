# P46-5 stage 3: two worker packets (2026-10-23)

BASE is `59de6790` on `plan/phase-46-structure`. Every rule in
`.agents/handoffs/wave-120-worker-packets.md` applies (where you work, what you never touch,
rules, gates, return), with two changes:

- Read the P46-5 card, not a W120 card: `sed -n '/^### P46-5 /,/^## ◇ WAVE 120/p' TODO.md`.
- `adopt_kernel.py` and `test_adopt_kernel.py` belong to lane B alone. Lane A never edits them.

Another session owns the `DocketError` catcher at the CLI entry and in the HTTP handler. Neither
lane edits `__main__.py`, the `cli/__init__.py` entry, or the `except` blocks and error-to-status
mapping of `serve.py`'s request handler.

## Lane A: docket threads start in their spawner's context

**Why.** `current_home()` reads a `ContextVar`. A thread starts with an empty context, so a
thread docket starts falls back to the process default home, not the one `use_home()` set. After
the step 3 rules are applied, 39 serve tests fail for this reason, and the product would do the
same thing: a server started under one home would serve another from its handler threads. The
decision is on the card: a thread docket starts runs in its spawner's context.

**Work.**

1. A kernel module (for example `src/docket/kernel/threads.py`) with one helper that starts a
   thread whose target runs in `contextvars.copy_context()` taken at the call. It imports nothing
   from `docket` (`tests/guards/test_kernel_is_a_leaf.py`). Add it to the runtime build hook's
   kernel file list the way the other kernel files are listed.
2. Every `threading.Thread(...)` under `src/docket/` goes through the helper:
   `core/telemetry.py`, `edges/adapters/toolbox.py`, `cli/_mcp.py`, `cli/_progress.py`,
   `serve.py`. A `ThreadPoolExecutor.submit` in `serve.py` runs its callable through a context
   copied at submit, the way `core/orchestrator.py` already does.
3. `serve.py`'s `ThreadingHTTPServer`: each request thread runs in a copy of the context captured
   when the server was built. Change only the server class or its construction, not the handler.
4. A guard in `tests/guards/` (AST, no baseline: the count is 0) that no module under
   `src/docket/` outside the kernel helper calls `threading.Thread`, constructs a
   `ThreadingHTTPServer` other than the context-carrying one, or calls `.submit` without a
   copied context. See it fail on a planted call before you rely on it.
5. Tests (RED first): a thread started by the helper under `use_home(A)` sees `A`; one started
   with a bare `threading.Thread` does not (that is the RED). A request to a server built under
   `use_home(A)` is handled with `current_home()` equal to `A`, also when the request arrives
   from outside any `use_home`.
6. Evidence for the 39: in a scratch worktree at your branch head, run
   `env -u VIRTUAL_ENV uv run python scripts/maint/adopt_kernel.py config-reads --write`, then
   `repointers --write`, then the serve tests (`tests/unit/test_serve*.py`,
   `tests/integration/*serve*`). Report how many fail at BASE with the rules applied and how
   many at your head with the rules applied, and name every remaining failure with its cause.
   Do not commit the rewritten tree. Remove the scratch worktree after.

Spec: `specs/` has no thread requirement today; if `serve-read-api` or `operator-api` states
which home the server serves, make it say the server serves the home it was started with.

## Lane B: the third codemod rule, `config-patches`

**Why.** `config-reads` refuses 216 test sites of the shape
`monkeypatch.setattr(config, "NAME", value)` (also the `monkeypatch.setattr("docket.config.NAME",
value)` string form and import aliases of `config`). Once reads go through `current_home()`, a
patch of the module constant changes nothing, so each site must become a `Home` override.

**Work.** In `scripts/maint/adopt_kernel.py`, add the rule `config-patches`, registered in
`RULES`, with toy tests in `tests/guards/test_adopt_kernel.py` (RED first, as the existing rules
have them).

- A patch becomes `with use_home(dataclasses.replace(current_home(), <field>=<value>)):` around
  the rest of its scope, using the scope machinery `repointers` already has (where a scope ends,
  why it cannot be reproduced). Consecutive patches in one scope become one `replace` with every
  field.
- The field is the `Home` field the name maps to. A path constant whose `Home` attribute is a
  property backed by `<name>_override` is written as `<name>_override=`. Take the name map from
  where `config-reads` takes it; do not write a second table.
- Refuse, and list with the reason: a name with no `Home` field; a patch whose effect outlives its
  function (a non-generator fixture or helper); `monkeypatch.delattr`/`setattr` with
  `raising=False`; anything you cannot reproduce exactly.
- Toy tests for the order with the other two rules: a test that repoints, patches and reads must
  come out right after `config-reads`, `config-patches`, `repointers` run in that order. If
  another order is required, say which and why, and make `--write` with no rule names apply them
  in that order.
- Measure on the real tree with `--check` only: report rewritten and refused counts per reason.
  **Never `--write` the real tree**: the integrator runs every rule once over the merged tree.
- `measure_kernel_adoption.py` is not a counting claim here; if the rule needs a count that does
  not exist, add a rule there and report it, never change an existing rule's count.

No `src/` change in this lane.
