# ADR 0031 (D-71): end-to-end tests that run the product

**Question:** docket has about 4,900 tests, and almost every one that looks end to end runs
in-process with a seam replaced: the sweep, the driver, git, the jail or the model wire. Which
whole flows must a test run the way an operator or Tack runs them, what may such a test fake,
and where do those tests live?

**Where decided:** 2026-10-25, by the maintainer, after a test-architecture audit of
`plan/phase-46-structure` at `57ff41ae`. Phase 50 on `TODO.md` is the card list.

## What was measured

- **One real end-to-end test runs in the default suite:**
  `tests/integration/product/smoke/test_oracle_and_approval.py::test_full_workflow_smoke_is_observable_and_preserves_state`.
  - It runs `scripts/smoke_workflow.py`: `docket` subprocesses and a scripted model over HTTP,
    across four roles, a verify gate, verdicts, a step approval and resume, and `log verify`.
  - It runs with no git repository (the basic scenario writes only a README), so no worktree or
    diff is exercised.
  - It runs with `setup sandbox off` and dispatches through foreground `docket run`, not
    `docket start --dispatch`.
  - It runs about nine subprocesses under the 10 s `integration/` ceiling.
  - Its pipeline declares `on: {REQUEST-CHANGES: {goto: implement}}`, but the scripted reviewer
    always approves, so that branch never runs.
- **The production path has no whole-flow test.** That path is Tack → HTTP API 6 → the service
  sweep → the pipeline → an approval over HTTP → the diff.
  - `test_serve_tasks_endpoint.py` patches `_submit_pod_sweep`.
  - `test_sweep__scheduled_and_webhook_dispatch.py` patches `dispatch_pod`.
  - `test_serve_stop_signals.py` stubs the sweep inside its subprocess.
- **The default configuration has no whole-flow test.** Since D-67, `docket init` turns isolation
  on where Landlock or Seatbelt is detected. `test_escape_matrix.py` runs the jail with no model
  turn, and the smoke runs the model turn with the jail off.
- **No test has the model attempt anything hostile inside a turn.** The 2026-10-12 security audit
  found its defects by running hostile repositories by hand.
- **Scripted models exist four times, plus the transport test's patched `urlopen`:**
  - `tests/support/llm.py::_ScriptedLLMServer`: an ordered list, always 200, repeats its last
    reply.
  - `scripts/smoke_workflow.py::_ScriptedModel`: by ordinal, validates each request.
  - The recorders in `scripts/release_journey.py` and `examples/starter/starter.py`.

  None of them routes by role, injects a failure through a real turn, or enforces a context
  window. The 400 from a 16k local window is the failure real runs hit.
- **`specs/test-framework.md` rule 13 already names `tests/e2e/`** ("named whole flows"), but the
  directory does not exist.

## Decision

1. **An end-to-end test runs the product the way a person or Tack runs it.** It meets five
   conditions:
   - It enters through a `docket` subprocess, or over HTTP to a `docket start` subprocess.
   - It works on a real `DOCKET_HOME` and a real git repository.
   - It replaces nothing inside docket. The only fake is the model, reached through the real
     OpenAI-compatible wire.
   - It judges by what an operator sees: task state, `task diff`, files, `log verify` and the
     trace.
   - It runs a named journey to its end: `done`, `failed` with the expected reason, or parked
     with a token.

   A test that needs to patch docket is an integration test.
2. **The tests live in `tests/e2e/`, one file per journey.**
   - They are collected only by `uv run pytest tests/e2e`, like `tests/agent`.
   - The per-test ceiling is 60 s.
   - A CI job named `e2e` runs them on Ubuntu, with `-n auto`.
3. **One fake model serves every Python test: `tests/support/model_server.py`.**
   - It routes by the role line every pod member's system prompt carries
     (``the **<role>** of the **``, from `teams/builtin_roles.py`).
   - Replies may be functions of the request.
   - It can fail the way providers fail: 400, 429 with `Retry-After`, 5xx, a hang, non-JSON, and
     `finish_reason: length`.
   - It can enforce a context window and can hold a reply until the test releases it.
   - `_ScriptedLLMServer` is deleted.
   - The release journey and the starter keep their own recorders, because they run an installed
     wheel and must not import the checkout.
4. **Oracles are shared, in `tests/support/e2e_oracles.py`:**
   - a trace skeleton, with ids and times masked;
   - every tool call in the trace has its decision in the audit log;
   - task status changes are legal per `tasks/domain/state.py`;
   - the base checkout is untouched;
   - a sentinel under the fake `$HOME` is untouched.

   An expected skeleton is reviewed like a golden and is never regenerated to hide a change.
5. **The deterministic smoke moves into the lane.** Its basic scenario and its scripted
   operator-loop scenario become e2e tests, and `_ScriptedModel` and `_OperatorLoopModel` are
   deleted. `scripts/smoke_workflow.py` keeps only what needs a real endpoint.
6. **A real model never gates CI.** Repeated real-model runs, compared by skeleton, are a manual
   evaluation against the operator's endpoint. Tokens are reported as measured; no dollar figure
   is reported as spent.

## Consequences

- An e2e test that fails on a product defect is not weakened, skipped or marked xfail. The card
  parks with the reproduction, and the fix is its own card.
- The default suite keeps its budget, because the lane is outside `testpaths`.
- The lane adds one CI job of a few minutes.

## Not now, with triggers

- **Telegram to dispatch end to end.** `interfaces/telegram/client.py::API_ROOT` has no override,
  so a subprocess cannot reach a fake Bot API. Trigger: a Telegram defect that the in-process
  tests missed.
- **MCP tools and OTLP export inside a whole flow.** Integration tests cover both. Trigger: a
  defect at the seam with dispatch.
- **Parallel tasks inside one pod.** Two pods in one service are covered: one is parked while the
  other finishes. Trigger: ADR 0027's parallel-tasks trigger.
- **Lanes as pytest markers** (`specs/test-framework.md` rule 12). The directory lane is enough for
  one new lane.
