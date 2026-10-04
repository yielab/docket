# ADR 0017 (D-51): docket inside a harness-agnostic factory — the harness contract becomes the product surface, evidence is kept, and certification belongs to someone else

**Question:** The plan of record (Tack) no longer polls docket's HTTP API. It runs coding agents
through four interchangeable harnesses (claude-code, codex, opencode and docket), and docket is
the poorest of the four: its decisions are `Unsupported`, its artifacts and cancellation are
`Advisory`, and Tack passes it neither the permission policy nor the budgets. At the same time
the target workflow (structured agentic engineering: a brief, a declared loop, structured
escalation, a merge-readiness evidence pack, and autonomy that grows domain by domain) needs
docket to do three things it does not do today:
- ask a human through whatever runs it;
- run its declared pipeline, not one agent, for an external caller;
- keep the evidence it produces instead of discarding it.

What does docket become in that factory, and which earlier decisions does that reverse?

**Where decided:** 2026-09-29, as Phase 35. The maintainer asked for docket's changes to be
architected into the roadmap and explicitly set aside the existing ADR limits for this plan.
Every reversal is therefore recorded here, not silently absorbed. Analysis:
`internal-docs/analisis-se3-ingenieria-agentica-2026-09-29.es.md` and
`internal-docs/plan-fabrica-agentica-l3-l5-2026-09-29.es.md` (gitignored, local).
**Activation gate:** Phase 34 closed at `b5d3991`; the board was clear.

**Evidence** (read at `6525b52`; every locator is a symbol name, re-locate with `rg -n`):

| Fact | Locator |
| --- | --- |
| Tack deleted its docket HTTP bridge; nothing polls `/inbox`, `/approvals`, `/runs` or `/traces` | Tack `CHANGELOG.md` (the bridge removal), no caller in `crates/` |
| Tack spawns `docket harness run --task-file /dev/stdin` and reads only the final result line | Tack `crates/tack-runner/src/harness/docket.rs` |
| Tack declares docket `decisions: Unsupported`, `artifacts: Advisory`, `cancel: Advisory`, and does not pass the policy or budgets | same file, `capabilities()` |
| Tack's U8 (docket cancel, artifacts, asks) is blocked: M3 found no `harness-v1.1` on 2026-09-20. It needs a process-group event, a stdout question answered on stdin, a written-path list, and the token on stderr or `--token-file` | Tack `docs/plans/phase-65.md`, M3 and U8 |
| ADR 0016 and D-50 still describe "Tack polls `GET /inbox`" | `docs/adr/0016-operator-loop-and-interop-standards.md` §6 |
| Harness mode fixes `approval_mode = "refuse"` and runs one agent | `cli/_harness.py::_run` (`env = {DOCKET_APPROVAL_MODE: "refuse"}`), ADR 0001 decision 11 |
| `approval_create` already emits `approval_requested` to the trace, and harness mode already streams every trace record to stdout | `core/approval.py::approval_create`, `cli/_harness.py::_run` (`trace.subscribe(_emit)`) |
| `bash` already runs in its own session (process group), and runs already carry a pid list that `runs cancel` kills | `edges/adapters/toolbox.py::run_bash` (`start_new_session=True`), `core/runs.py::add_hop_pid`, `cancel_run` |
| A passing verify's output is discarded; only `{"verification":"passed","cmd"}` is traced | `core/dispatch.py::_evaluate_mechanical_gate` |
| A missing `verifyCmd` advances the task | same function, the `not verify_cmd` branch |
| `diff_ref` is a branch name, never a commit | `core/dispatch.py::_implementer_diff_probe` |
| `HandoffArtifact.notes` is reserved and never written | `core/handoff.py` |
| `guardrail_block` writes the policy id into `action` | `core/dispatch.py::_enqueue_pre_input_gate`, `_apply_output_guardrails` |
| `budget_for_role` resolves the registry with no project, so a pod-scoped role's `tokenBudget` never applies | `core/context.py::budget_for_role`; callers `core/dispatch.py::_hop_message`, `core/session.py` |

## Decision

**docket is the governed harness of a harness-agnostic factory.** It executes, gates and records.
It does not plan (the plan of record does) and it does not certify its own work (an independent
verifier does). Its product surface toward the factory is the harness contract, so that contract
grows first.

1. **The harness contract gains an opt-in version 1.1.** `docket harness run --contract 1.1`
   selects it; without the flag every byte of v1.0 output is unchanged. A v1.1 line carries
   `"v": "1.1.0"`. The v1.0 fail-closed rule stays exact per version. Schema at
   `docs/contracts/harness-v1.1/schema.json`, fixtures at
   `tests/fixtures/harness-contract/v1.1/`. Both are generated or validated the way v1 is.
2. **v1.1 carries exactly what Tack's M3 names, and nothing speculative:**
   - `process_started` / `process_exited` trace events for every process group a tool starts
     (`pgid`, `tool`, `callId`, and on exit `exitCode` or `signal`). The pgid is also registered
     on the run, so `docket runs cancel` and the harness's own SIGTERM kill it.
   - **Questions on stdout, answers on stdin** (`--answers stdin`). A gated call waits instead
     of refusing. The `approval_requested` event names the approval token, tool and call. The
     caller answers with one JSON line `{"v":"1.1.0","token":<run>,"answer":{"approvalToken":
     <t>,"action":"accept"|"decline"|"cancel","content":{}}}` (the MCP elicitation result
     shape). Every answer passes `pre_input` as untrusted text, and every resolution is audited
     with channel `harness`. An unanswered question denies at its deadline (fail closed).
     `--answers stdin` together with a task read from stdin is refused (exit 2): stdin cannot be
     both.
   - **A written-path list** in the result (`files: [{path, op}]`), taken from the chokepoint's
     own write/edit calls plus `git status --porcelain` when the workspace is a repository.
   - **`--token-file PATH`**, written atomically (0600) before the turn starts. The existing
     stderr line becomes a pinned format.
   - **The caller's limits:** `--max-tokens N` bounds the turn's measured tokens, and
     `--policy FILE` (repeatable `kind: policy` documents, validated) installs caller-scoped
     policies into the caller's `DOCKET_HOME` before the turn.
3. **Harness mode may run a pipeline** (`--recipe <name|dir>`, v1.1 only). This reverses ADR
   0001's "one agent, not a pod". The mechanism reuses what exists, with no second executor:
   - an ephemeral pod is provisioned in the caller's `DOCKET_HOME`;
   - its members work **in place** on the caller's workspace (no worktree; the caller owns
     isolation, which ADR 0001 already states);
   - the recipe is applied, one task is enqueued, and `core/dispatch.py::dispatch_task` runs it
     synchronously;
   - the result gains a `task` block with the hops, verdicts and evidence.
4. **docket keeps its evidence.** Every mechanical gate records `{cmd, exitCode, outputTail,
   durationS}` on the hop, pass or fail (redacted, tail-bounded). Every Implementer hop records
   `commit` (HEAD SHA), `baseCommit` (merge-base) and a diffstat beside the branch name.
   `requireVerify` (pod setting, default `false`; `true` under `--recipe`) turns a missing
   `verifyCmd` into a failure (`verification_missing`) instead of a skipped advance.
5. **docket never scores its own work.** Merge readiness, risk tiers, mutation scores,
   cross-model judgment and autonomy promotion belong to an independent verifier. The working
   name is Assay, a separate tool that the plan of record runs after any harness. docket
   supplies raw evidence in a published shape (Phase 36's `evidence-v1`) and does not grow a
   verdict about it.
6. **The two measured defects are fixed in this phase**, because Phase 35 touches the same
   functions: `guardrail_block.action`, and `budget_for_role(..., project=)` for both callers
   (the Phase 30 `resolve_role_model` defect, second instance).
7. **ADR 0016 §6 is corrected**, not deleted. Nothing polls `/inbox` today. The inbox, channels
   and HTTP routes stay: they serve the operator and any future poller. Tack integrates through
   the harness contract.

## What this reverses or amends

| Earlier decision | Now |
| --- | --- |
| ADR 0001 decision 11: harness is non-interactive, `refuse` only | Amended: `refuse` stays the v1.0 default; v1.1 `--answers stdin` waits and asks. |
| ADR 0001: harness runs one agent, not a pod | Amended: v1.1 `--recipe` runs a pipeline over an ephemeral, in-place pod. |
| ADR 0016 §6 / D-50: "Tack polls; nothing is pushed to it" | Corrected: Tack spawns the harness; stdio is the channel. |
| Pod dispatch: a missing `verifyCmd` advances | Amended: still advances by default; fails under `requireVerify`. |
| The Phase 36–38 reversals (ADR 0012/0013 auto-apply, ADR 0004 egress, opt-in isolation, operator-only rules) | **Not decided here.** Each is re-examined when its phase opens (TODO.md "Planned"). |

## Standards

- Answers use the MCP elicitation result shape (`action`, `content`), the same as operator-v1.
  There is no second answer vocabulary.
- Contract JSON Schema is 2020-12, generated from `core.harness` Pydantic models.
- Event names stay in docket's closed trace vocabulary (`core/trace.py::EVENT_TYPES`). Process
  events are docket events, not a new envelope.

## Cut and deferred

| Item | Status | Why |
| --- | --- | --- |
| An HTTP decision channel for Tack | Cut | Tack decided stdio; a second channel is two contracts. |
| docket computing merge readiness, risk or autonomy | Cut | Decision 5: independence of the verifier. |
| Resuming a harness run after the caller dies | Deferred | Tack declares `resume: Unsupported` for every harness. Trigger: a caller that needs reattachment. |
| Worktrees in harness `--recipe` mode | Deferred | The caller owns isolation. Trigger: a caller that cannot provide a disposable workspace. |
| Per-hop token usage in the evidence | Phase 36 | Needs the evidence-v1 schema first. |

## Verdict table

| Tack capability (its own words) | Before (v1.0) | After Phase 35 (v1.1) |
| --- | --- | --- |
| cancel | Advisory | Supported: process events plus registered pgids |
| decisions | Unsupported | Supported: `--answers stdin` |
| artifacts | Advisory | Supported: `files` in the result (a diff is still the caller's to capture) |
| usage | Advisory (measured tokens, no dollars) | Unchanged: dollars are never fabricated |
| permission policy and budgets | not passed | `--policy`, `--max-tokens` |
| multi-role loop | absent | `--recipe` |

## Test discipline

The contract card (P35-2) owns the models. Every later card builds its values through them, so
no second hand-built dict exists. The integrator owns one consumer test that crosses the seam:
it drives the real `docket harness run --contract 1.1` subprocess the way Tack does:
- task from a file;
- a stdin answer;
- process events read;
- a file list read;
- a recipe run.

It asserts each against the committed schema. Two green cards with one broken seam is the Wave
30 failure; this test is the guard.

## Live run (P35-10, 2026-10-04)

Run against the local llama.cpp endpoint at `127.0.0.1:8081` (Qwen3.6-35B-A3B GGUF, `--ctx-size
16384`) with `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`. Each run used a throwaway `DOCKET_HOME` and a
scratch workspace, never the operator's `~/.docket`. Everything below is from the stdout and
stderr of those runs.

- **`--recipe software`: not runnable.** `software` is a pod blueprint, not a recipe. The run
  was refused before any turn, exit 2: `unknown recipe 'software'`, listing the shipped recipes.
  Recorded as the honest result of the requested command. The shipped recipes are `tdd`,
  `spec-first`, `reflexion`, `dual-review`, `frugal`, `intake` and others.
- **`--recipe tdd --verify "python3 -m compileall -q ."`, task from a file (`--contract 1.1`).**
  Exit 1, `status` `failed`, `task.status` `failed`. The implementer hop wrote `test_add.py` and
  edited `calc.py`, and its verify passed (exit 0). The `check-red` gate then found the test
  already passing and routed to fail: `step 'check-red' outcome PASS routed to fail`. The gate
  caught it. The local model wrote the implementation along with the test, so the red check
  failed the task, as designed.
  `files` also listed `__pycache__/*.pyc` written by the verify command, so `files` reports
  verify-generated artifacts as well as the model's own writes. Usage 24,233 input and 638
  output tokens over 8 turns.
- **`--answers stdin`, one `bash` approval, answered `decline`.** Exit 0, `status` `ok`. The model
  requested `git push origin production`, the harness emitted `approval_requested`, the consumer
  wrote one `decline` line, and the run emitted `approval_denied`, then `session_end`.
  `approvals` read `[{tool: "bash", outcome: "declined"}]`. `files` was `[]`. This is the P35-5
  caveat, observed live: a denied approval ends `status` `ok` with exit 0, so a caller must read
  `approvals`.
- **A `bash` process lifecycle run** (`process_started`/`process_exited`) and the stdin accept path
  are covered by the seam test, not repeated live.

Verdict for the live check: the two requested runs produced the result lines above. The
`software` run is a refusal, not a run. The `tdd` run ended `failed` at a real gate, which is
correct behaviour and not a harness defect.
