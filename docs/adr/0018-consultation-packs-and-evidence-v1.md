# ADR 0018 (D-53): consultation packs and evidence-v1 — docket asks with options and publishes what it kept

**Question:** Phase 35 made docket's harness contract good enough for Tack to spawn it, and made
pod dispatch keep its evidence (ADR 0017 §4). Two gaps remain from the same plan:
- **docket asks badly.** A gated call reaches a human as a tool name and an argument digest. It
  carries no reason and no choices. A question exists only for the Lead under the `intake`
  recipe, as a free-form field in its brief. No other role can ask, so an agent that is unsure
  guesses.
- **docket's evidence has no published shape.** P35-4 records verify output, commits and a
  diffstat on each hop, but nothing documents that record. It has no per-hop tokens or trace
  link. The only way to read it is the raw task list. ADR 0017 §5 gives scoring to an
  independent verifier, which needs a stable shape to read.

What does docket add so that every escalation is a decision with options, and every hop's
evidence is a published document?

**Where decided:** 2026-10-04, as Phase 36. It is the outline ADR 0017 left in `TODO.md`
("Planned — Phases 36–38"), opened when Phase 35 closed at `184e02e`.

**Evidence** (read at `184e02e`; locators are symbol names, re-locate with `rg -n`):

| Fact | Locator |
| --- | --- |
| `Question` has `message` and `requestedSchema` only: no kind, no options, no recommendation | `core/operator_contract.py::Question` |
| The answer result is `action` plus `content`, with no option id | `core/operator_contract.py::AnswerResult` |
| `approval_grant` / `approval_deny` take `token` and `channel` only. ADR 0016 §8 promised an `actor` that never shipped | `core/approval.py::approval_grant`, `approval_deny` |
| A parked call records `tool`, `callId` and `argsDigest`, and no rationale | `core/tools.py::_park_call` |
| Only the Lead under `intake` can ask, through its brief's `questions` | `templates/recipes/intake/pipeline.yaml`, `core/dispatch.py::_run_input_step` |
| A hop record carries `verify` and `evidence` (`commit`, `baseCommit`, `diffStat`), but no tokens and no trace link | `core/dispatch.py::_hop_record`, `HopResult` |
| Deny reasons, `REQUEST-CHANGES` texts and declined answers are scattered (or, for deny reasons, not recorded at all) | `core/answers.py` (`answers[]`), `HopResult.output` |
| No metric counts questions, or how long a decision took | `serve.py::render_metrics` |

## Decision

1. **operator-v1.1, opt-in and additive.** `Question` gains `kind`
   (`approval|clarification|decision`), `options[]` (`id`, `label`, `description`, `risks`,
   `estimatedTokens`) and `recommendation` (`optionId`, `rationale`, `evidenceRefs[]`).
   `AnswerResult` gains `optionId`. The schemas are generated into
   `docs/contracts/operator-v1.1/`. Every v1 schema byte and every v1 output stays the same.
2. **Approval grant and deny gain `reason` and `actor`**, both optional, and both audited. This
   closes the ADR 0016 §8 drift. A deny reason is untrusted text: it passes `pre_input` before
   anything stores it.
3. **Approval packs.** A gated call carries a pack:
   - the model's stated rationale: the assistant text of the message that made the call,
     screened as untrusted and truncated to a fixed bound;
   - exactly three options: `approve_once`, `approve_task` (a single-task pre-grant through the
     existing pre-grant path), and `deny` (with a reason).

   The pack rides on the approval record, on `approval_requested`, and in harness v1.1, as
   additive fields.
4. **A `consult` built-in tool for every role**, kind `read`, so a read-only role keeps it. The
   tool requires at least two options and a recommendation, and is refused without them.
   The outcome follows the posture:
   - harness `--answers stdin`: a question line, answered by `questionId` on stdin;
   - `park`: the task goes `waiting_input`, and the answer re-enters the same role;
   - `refuse`: the run ends `blocked`, with the pack in the result.

   Consultations are capped per task by the new pod setting `maxConsultationsPerTask`
   (default 3), the attention budget. Past the cap the tool returns an error result and the
   agent decides on its own.
5. **A corrections ledger.** Three kinds of correction go append-only to a per-pod
   `corrections.jsonl`, written directly under the D-12 exemption: deny reasons,
   `REQUEST-CHANGES` texts, and declined answers. `docket pod <p> corrections [--json]` reads
   it. docket only records corrections: proposing a directive from them belongs to the external
   verifier (ADR 0017 §5).
6. **evidence-v1.** A Pydantic model in `core/evidence.py` describes what a hop keeps:
   - verify, commits and diffstat (P35-4's record);
   - measured per-hop tokens (`TokenUsage`, never dollars);
   - the trace link that `GET /traces` accepts.

   The schema is generated into `docs/contracts/evidence-v1/`. The same document is served
   three ways, built by one function: `docket pod <p> evidence <task> [--json]`,
   `GET /tasks/<p>/<id>/evidence`, and the harness v1.1 `task.evidence` block.
7. **Escalation metrics.** `docket_tasks_started_total`, `docket_questions_total{kind,outcome}`,
   `docket_decision_latency_seconds` (from inbox transitions), and `docket metrics
   --escalation`. These are in measured units: counts and seconds, never dollars.

## What this reverses or amends

| Earlier decision | Now |
| --- | --- |
| Only the `intake` Lead asks (Phase 34) | Amended: every role can `consult`, bounded per task. `intake` is unchanged. |
| ADR 0016 §8: `actor` on grant and deny | Delivered, with `reason`. |
| ADR 0017 §5: evidence in a published shape | Delivered as evidence-v1. docket still computes no verdict. |

## Cut and deferred

| Item | Status | Why |
| --- | --- | --- |
| docket proposing directives from corrections | Cut | ADR 0017 §5: the verifier proposes; docket records. |
| Scoring evidence (risk, readiness) | Cut | Same. |
| Free-form `consult` without options | Cut | A question without choices is the thing this phase removes. |
| Notifying channels rendering options as buttons | Done as text (Waves 89–90) | The operator asked: a `conversation`-level event lists the options and Telegram `/answer <task> <id>` picks one; buttons stay out (Telegram is inbound-only). ADR 0020 "Closed by Waves 89–90". |

## Test discipline

The contract card (P36-1) owns every operator-v1.1 model, and P36-3 owns every evidence-v1 model.
Later cards build their values through those models, never through a second dict. The
integrator owns two tests that cross the seams:
- **consult over harness stdio**, validated against the committed operator-v1.1 and harness v1.1
  schemas;
- **one task's evidence**, read through the CLI `--json`, HTTP and the harness, compared byte for
  byte.

### Live run (2026-10-04)

Run against the local llama.cpp endpoint (`127.0.0.1:8081`, `/health` ok, 16k context,
`DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`), a throwaway `DOCKET_HOME`, `docket harness run --contract 1.1
--answers stdin`, model `local/local-model` (Qwen3.6-35B-A3B).

- **consult.** Task: choose between an in-memory dict and a SQLite file and call `consult` first.
  The model called `consult` (one `question_asked` event, kind `decision`), the question was answered
  by `questionId` with the first option, the `consult` tool result was `ok`, and the run ended exit 0,
  status `ok`, two model turns. `question.taskId` was `agent:<harness-project>:default`, the session
  key, as recorded under the carried items below.
- **approval pack.** Task: run `git push origin production`. The bash call was gated
  (`prod-deploy`) and the `approval_requested` payload carried the three options (`approve_once`,
  `approve_task`, `deny`). With no instruction the model wrote no text before the call and the
  rationale was empty (length 0). When told to explain first, the rationale was 130 characters of
  model prose (an invented justification, which is why it is shown as the model's claim and not as a
  fact). Both runs were accepted on stdin: exit 0, status `ok`, one approval `accepted`.
- **Pod-dispatch park and re-entry (P36-8), run the same day.** A default `docket init` pod
  (Lead, Implementer), `approvalMode park`, verify `fib(30) == 832040`, task: make the exponential
  `calc.fib` fast, choosing `lru_cache` or an iterative loop through `consult` first. Dispatch 1:
  the Lead called `consult` (kind `decision`, two options with risks, recommendation `lru_cache`),
  the hop parked and the task went `waiting_input` (inbox: needsYou). `docket pod myapp answer
  <task> --field optionId=iterative` chose the option the model had **not** recommended. Dispatch 2
  (2m05s): the Lead re-entered, its reply opened "The operator chose the **iterative loop**
  approach", it briefed the Implementer, which rewrote `fib` as a loop; verify exit 0, task `done`,
  3 hops. The earlier `REFUSED [approval_parked]` tool result in the Lead's history did not confuse
  it. `docket pod myapp evidence` listed the parked hop as `ok: no` with its measured tokens. Found
  and fixed in the run: the CLI rendered `waiting_input` as an error (`✗`), now a warning like
  `waiting_approval`.
