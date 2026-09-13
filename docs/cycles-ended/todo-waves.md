# Closed board sections (archived from TODO.md)

Every section below was moved here **verbatim** from `TODO.md` when the board was cut to its active
and planned sections. Nothing here is outstanding. Waves and phases are in the order they sat in
the board file, which was not chronological. `manifest.json` in this directory holds each section's
byte length and SHA-256; `scripts/maint/split_board.py check docs/cycles-ended/manifest.json`
proves the archive is complete and the board no longer carries it.

## ☑ WAVE 25 COMPLETE (2026-08-30) — live-model request and outcome truth

**Integration state (2026-08-30):** all 11 behavior/acceptance cards are DONE. Commit `6b925f0`
owns the complete 45-path Wave 25 tree. Its commit-level gates passed: 2,377 tests with five
contract-labelled skips, Ruff, format, strict mypy, 24 specs, 18 goldens, metrics, and deterministic
smoke. Wave 26 subsequently closed after its own release/governance and public-truth gates passed.

### W25-C1 — preserve the complete delegated task text

**Status:** DONE (2026-08-20) · **Size:** S · **Owner:** @codex

**Measured trigger:** the public CLI received ten task words after `delegate`, but the persisted
`TASK_LIST.json` description was exactly `"create"`. `_pod_delegate` collects every non-priority
argument into `rest` and then discards all but `rest[0]`.

**Goal:** preserve the operator's complete task description whether the shell supplies it as one
quoted argument or several ordinary positional words.

**Non-goals:** no mandatory-quotation rule, shell parser, change to the 500-character limit,
priority grammar, input-policy trust, queue schema, or dispatch retry behavior. Quoting remains
recommended when a task contains shell metacharacters; by the time Typer receives argv, ordinary
quote delimiters are gone and cannot be treated as durable task metadata.

**Live path / files:** `cli/__init__.py::cmd_pod` forwards `ctx.args` →
`cli/_pod.py::dispatch` → `_pod_delegate` → `core/dispatch.py::enqueue_task` →
`edges/store.py` queue write. Own `_pod_delegate`, a focused CLI test, the delegation contract in
`specs/functional/pod-dispatch.spec.md`, and command/troubleshooting text only if it currently
implies quotes are required.

**RED test:** invoke the real `cmd_pod`/Typer boundary in hermetic state with both
`delegate "create a file called test.md"` and the equivalent split argv; assert the exact same
description reaches the real queue. It fails today because the split form persists only
`"create"`.

**Acceptance:** join every task positional after removing a well-formed priority option; reject an
empty description and invalid/missing priority without enqueueing; apply the length check to the
reconstructed text; preserve the existing quoted form and output/exit behavior. Focused CLI pytest,
`uv run ruff check src/docket/cli/_pod.py <test>`, spec validation, full pytest/static/golden gates
all pass.

**Contention:** owns only `_pod_delegate`, its focused test, and the pod-dispatch delegation clause.
It does not depend on W25-C2 and may run in parallel if central spec/board rollups remain integrator-
owned.

**Shipped:** the public Typer boundary now reconstructs the complete free-form description from all
task positionals after removing a valid priority option. Quoted and split argv persist identical
text; empty input, missing/invalid priority, and reconstructed descriptions over 500 characters
fail before enqueue. The focused six-case CLI suite, 2,262-test full collection, 18 goldens, 24
specs, Ruff, format, mypy, metrics, and development-harness validation all pass (five expected
environment/opt-in skips).

### W25-C2 — fit every imminent model request to the selected endpoint

**Status:** DONE (2026-08-22) · **Size:** M · **Owner:** @codex

**Measured trigger:** the failing fifth `/v1/chat/completions` request was 17,643 tokenizer tokens
for a registered 16,384-token endpoint: about 1.6K tokens of always-on system context and roughly
13K tokens of active conversation/tool results, including one 30,035-character read. The
100,000-token turn budget measures cumulative backend usage and does not bound the next request;
pre-turn session compaction ran before this initially empty session grew.

**Goal:** before every task or compaction completion, prove the prospective request—including
messages, tool schemas, protocol overhead, and output reserve—fits the selected model's registered
context window; deterministically reduce complete low-priority history units and fail locally when
the irreducible request cannot fit.

**Non-goals:** no blanket 32K requirement, exact-tokenizer dependency, silent slicing of a tool
call/result, higher loop/token limits, model-specific prompt branch, raw-history plus typed-handoff
duplication, or global lowering of `DOCKET_TOOL_MAX_OUTPUT_CHARS` as the final fix. The separately
observed run-registry success-on-task-failure defect needs its own measured card and is not hidden
inside context management.

**Live path / files:** `core/dispatch.py` resolves a hop →
`edges/adapters/docket_runtime.py::DocketDriver.run_turn` selects the model →
`edges/adapters/llm.py::resolve_endpoint/client_for` currently drops the provider model's
`contextWindow`/`maxTokens` → `core/agent_loop.py::run_agent_turn` calls `backend.complete` once for
each compaction round and loop iteration. Request encoding lives in
`edges/adapters/llm.py::build_payload`; atomic history and fail-closed hierarchical reduction live
in `core/session.py`; estimates live in `core/context.py`. Own those exact seams, agent-loop tests,
and `specs/functional/agent-loop.spec.md`.

**RED test:** through the default `DocketDriver`, use a deliberately small registered context
window and a scripted tool response large enough that iteration two would overflow. Assert no
oversized backend call occurs, the assistant/tool-result unit is never split, and the turn either
continues from a bounded compacted history or returns a distinct local context-fit failure. The
current path makes the oversized second call.

**Acceptance:** resolve limits for the exact provider/model at call time, including explicit
environment-override behavior; estimate the same wire components the adapter will send and label
the value as an estimate; reserve configured completion capacity; preflight every summarizer and
task completion, not only iteration one; reduce only whole atomic units with visible, traced
compaction and reload the resulting history before retrying fit; never discard the current task,
a tool decision/result, or an unresolved action silently; if the minimum request cannot fit, make
no HTTP call and return an actionable non-retryable context-fit result. Tests cover no-op, bounded
reduction, irreducible failure, summarizer recursion/atomicity, unknown hosted-window fallback, and
the 16,384-token incident shape. Focused loop/driver/adapter/session tests, spec validation, full
pytest/static/golden gates, and the opt-in live small-context canary pass without raising the
endpoint window.

**Shipped:** the exact selected provider/model now carries its registered context window and output
limit into the loop. Every task and summarizer request estimates the adapter's complete wire payload,
reserves output capacity, traces privacy-safe fit evidence, compacts only complete durable ranges,
reloads them before retry, and returns `context_fit` before transport when irreducible. Deterministic
tests cover the 16,384-token incident and all fail-closed branches. The real 16k basic canary passed;
the realistic maintenance canary kept every observed request within the same window and preserved
MONEY-104/META-202, then exposed only W25-C3's already-scoped terminal-verdict convergence defect.

**Contention:** owns the loop/request-limit/session-compaction seams and the mutable local endpoint.
No parallel context/session/MCP-output lane may touch those functions or run the same live canary.

### W25-C3 — reserve a truthful terminal response inside the turn budget

**Status:** DONE (2026-08-25) · **Size:** M · **Owner:** @codex

**Measured trigger:** the repeated real `memory-maintenance` canary reached the correct product
result: the Implementer repaired the module and the four regressions plus hidden acceptance passed.
The agent then made three further tool-enabled rounds instead of returning a tool-free final
response. After 13 assistant turns and 18 tool results, cumulative usage reached 100,724 tokens
against the normal 100,000-token budget; `run_agent_turn` failed the task at the start of the next
iteration. No individual request exceeded the endpoint's 16,384-token context window in this run.

**Goal:** preserve the hard cumulative turn budget while reserving a bounded opportunity to
finalize: when another tool-enabled round no longer fits the remaining budget, make at most one
explicit tool-free finalization request if that request and its output reserve fit; otherwise fail
locally before another backend call. A model must not be able to spend the final usable budget on
another optional tool round and strand already-correct work without a terminal response.

**Non-goals:** no higher token/iteration limits, inference that a task is complete merely because a
shell command passed, filename/test-wording heuristic, model-specific branch, silent truncation of
history, splitting an assistant tool-call/result unit, or bypass of mechanical, Reviewer, Tester,
policy, or approval gates. W25-C2 still owns per-request context-window fit; this card owns only
cumulative turn convergence after that request-fit seam exists.

**Live path / files:** `core/dispatch.py` calls
`edges/adapters/docket_runtime.py::DocketDriver.run_turn` →
`core/agent_loop.py::run_agent_turn`. Own `LoopConfig.token_budget`, cumulative usage accounting,
the decision immediately before `backend.complete`, the tool-free terminal-response path, focused
agent-loop/driver tests, and `specs/functional/agent-loop.spec.md`. Reuse W25-C2's prospective
request estimate and selected-endpoint limits rather than introducing a second estimator.

**RED test:** through the default driver, script a correct edit and validation followed by a model
attempt to request another tool when the remaining cumulative budget cannot fund another normal
tool-enabled completion but can fund one bounded finalization. Assert the next backend call carries
no tools, explicitly requests the terminal response, persists that response, and returns success
without exceeding the budget. The current loop sends the next ordinary tool-enabled request or
fails on the following iteration. A second case leaves too little budget even for finalization and
asserts no backend call is made and the existing actionable `token_budget` failure is returned.

**Acceptance:** preflight cumulative usage before every completion using measured prior usage plus
the same request/output reserve established by W25-C2; enter finalization at most once; offer no
tools during that call; preserve complete atomic history; trace why finalization was entered and
the remaining estimate without raw content; keep cancellation and backend errors fail-closed. A
focused deterministic test covers normal continuation, successful forced finalization,
irreducible-budget failure, and a finalization reply that still attempts a tool call. The repeated
real `memory-maintenance` canary completes under the existing 100,000-token budget without weakening
its public/hidden acceptance, followed by the full static/pytest/golden/spec/metrics gates.

**Contention:** shipped. Its live evidence used the mutable local endpoint exclusively; no active
lane shares the agent-loop seam or that preserved world.

**Shipped:** the loop now combines measured prior usage with the
prospective request estimate and output reserve before transport. When an ordinary round no longer
fits, it offers exactly one explicit tool-free terminal response; irreducible requests, hallucinated
finalization tool calls, and measured overruns fail without dispatching or persisting an incomplete
unit. Successive summary calls see earlier summary usage without nesting the session-store lock.
Invalid, truncated, timed-out, and over-budget responses retain their specific failure shape and
persist only measured usage. Budget-first finalization preserves raw complete units; a later budget
decision after legitimate window compaction uses the exact reloaded durable summary. The
default-driver edit/validate fixture finishes at 91,000/100,000 tokens; 79 focused loop/driver
tests, the 2,360-test collection (2,355 passed, five expected environment/opt-in skips), 18 goldens,
24 specs, Ruff, format, mypy, metrics, and the deterministic whole-workflow smoke pass. The preserved
un-scripted world `/tmp/docket-w25-c3-live-Ey3u1M` reached task `done`, completed all five hops, and
passed public plus hidden checkout acceptance. Its largest measured turn was the Implementer's
27,701 tokens; all 16 prospective requests fit the registered 16,384-token endpoint window and no
role approached the 100,000-token turn budget. That run separately exposed private-file probes in
the canary task wording, now owned by W25-C7 rather than conflated with this budget outcome. A
separate preserved confirmation at `/tmp/docket-w25-c7-confirm-M073cp` drove the Reviewer to 90,358
measured tokens: the loop emitted `budget_warning` and refused a terminal completion locally because
5,919 estimated input plus the 8,192 output reserve could not fit the 9,642 remaining tokens. That
run is supplementary C3 refusal evidence, not C7 privacy evidence.

### W25-C4 — make run records reflect returned task failures

**Status:** DONE (2026-08-25) · **Size:** S · **Owner:** @codex

**Measured trigger:** the realistic canary returned a normal `TaskResult` with
`status="failed"` and reason `exceeded token_budget=100000 (used 100724)`, while its persisted run
record ended `state="succeeded"` with an empty `error`. `core.runs.execute` currently marks every
non-throwing result list successful; focused coverage proves exceptions and `status="done"` but not
a returned failed task.

**Goal:** make the run registry report the result of the dispatch invocation, not merely whether
Python raised: any returned failed task makes the run failed, preserves every returned task id, and
records a bounded actionable reason. All dispatch sources must observe the same truth through the
existing `runs.execute` chokepoint.

**Non-goals:** no new run state or persisted-shape migration, change to `TaskResult` statuses,
dispatch retry/rework semantics, task-state mutation, exception propagation, or conversion of
`waiting_approval`/`blocked` into failures. Concurrent cancellation remains terminal and wins over a
later returned result.

**Live path / files:** CLI, webhook, schedule, sweep, and MCP dispatch already converge on
`core/runs.py::execute`; `dispatch.TaskResult` exposes `task_id`, `status`, and `reason` for
duck-typed folding. Own that outcome fold, `tests/python/test_dispatch_run_records.py`, the run
semantics in `specs/data/serve-read-api.spec.md`, and the existing state/error description in
`specs/data/cli-json-shapes.spec.md` only if clarification is required; no writer bypasses
`edges/store.py`.

**RED test:** have the real `runs.execute` wrapper receive a normal list containing
`TaskResult(task_id="task-failed", status="failed", reason="turn budget exhausted")`. Assert the
persisted run is `failed`, retains the task id, carries the reason, and emits the same error trace
class as an exception failure. The current path records `succeeded`. Cover a mixed result list,
`done`, `waiting_approval`, `blocked`, and a concurrent cancellation that must not be clobbered.

**Acceptance:** fold the returned list once after `fn` completes; `failed` wins if any item has that
status, with a deterministic bounded summary of failing task ids/reasons and no raw model/tool
content; otherwise preserve current successful invocation semantics. Keep the result list return
value and exception behavior unchanged. Focused tests exercise the shared wrapper rather than five
source-specific copies; the run specs receive a truthful version/status/changelog update; full
pytest/static/golden/spec/metrics gates pass.

**Contention:** owns only `core/runs.py::execute`, its focused run-record tests, and run-semantics
spec clauses. It is independent of C2/C3/C5 and may run in parallel if central board/spec-index
rollups remain integrator-owned.

**Shipped:** `runs.execute` folds returned outcomes once, preserves every task id, and records any
returned `failed` task with a deterministic summary bounded to 1,024 characters and an `error`
trace. `done`, `waiting_approval`, and `blocked` remain successful invocation outcomes. Atomic
queued-to-running and terminal transitions ensure a cancellation before start, during dispatch, or
between fold and write cannot be revived or overwritten. Thirteen direct outcome/cancellation
cases, all owning run suites, the full pytest/static/golden/spec/metrics gates, and the deterministic
whole-workflow smoke pass.

### W25-C5 — make the basic live gate enforce its byte-exact artifact contract

**Status:** DONE (2026-08-22) · **Size:** S · **Owner:** @codex

**Measured trigger:** the repeated real basic canary completed all five hops and reached task state
`done`, but the final harness rejected `smoke-artifact.txt`: it contained the 15 bytes
`docket smoke ok` with no terminal LF instead of the asserted 16 bytes `docket smoke ok\n`.
The mechanical command `test "$(cat smoke-artifact.txt)" = "docket smoke ok"` strips trailing
newlines by shell command substitution, so it accepts both files and cannot enforce the final
contract Reviewer and Tester rely on.

**Goal:** state one byte-exact artifact contract and enforce it at the Implementer's mechanical
gate, before review/approval/task completion, while retaining the independent final harness
assertion as defense in depth.

**Non-goals:** no product-wide newline policy, global prompt change, model-specific instruction,
pipeline-engine change, weakening of the final exact assertion, or replacement of the real tool and
gate path with direct harness writes.

**Live path / files:** `scripts/smoke_workflow.py::_write_inputs` creates the basic scenario's task
description and `verify_command`; the final artifact assertion is in the same harness.
`tests/python/test_workflow_smoke.py` and the Full-workflow smoke section of
`specs/test-framework.md` own acceptance.

**RED test:** generate the real basic mechanical command, run it against a 15-byte no-newline
artifact, and assert non-zero; then run it against the exact 16-byte artifact and assert success.
The current command passes both. Keep a separate assertion that the delegated task text explicitly
requires one terminal LF and an end-to-end deterministic smoke case that reaches `done` only for
the exact artifact.

**Acceptance:** use a portable mechanical check that compares exact bytes including the single
terminal LF and rejects missing/extra bytes or lines; make the delegated task wording unambiguous;
leave the hidden final `read_text() == "docket smoke ok\n"` check intact. Deterministic smoke and
focused pytest pass; the opt-in real `--live-model --scenario basic` canary completes without a
post-`done` artifact mismatch; full static/pytest/golden/spec/metrics gates pass.

**Contention:** owns the basic fixture/gate/assertion in `scripts/smoke_workflow.py`, its focused
workflow-smoke tests, and the test-framework smoke clause. It does not overlap C2–C4, but no second
live canary may share the mutable local endpoint while its acceptance run is in progress.

**Shipped:** the basic task now states the exact UTF-8 artifact bytes and one terminal LF, while its
mechanical gate compares `read_bytes()` with `b"docket smoke ok\n"`. Focused tests prove missing,
extra, and exact newline behavior through the generated command; the independent final assertion
remains intact. The opt-in real basic workflow completed all five hops, reached `done`, and passed
the byte-exact final harness in `/tmp/docket-w25-c5-live-0w3Qtv`.

### W25-C6 — stop request-fit from recompacting the same logical history

**Status:** DONE (2026-08-25) · **Size:** S · **Owner:** @codex

**Measured trigger:** a caller-level `DocketDriver.run_turn` reproduction transports one ordinary
task request, then repeatedly summarizes the same already-compacted suffix when its first accepted
summary still cannot fit the registered window. The current loop emits nine prospective fit checks,
four successful compactions, and five transports (`task` plus four summaries). The truthful bounded
sequence is four fit checks and two transports: initial task, oversized raw retry, one compaction,
and one recheck that fails locally.

**Goal:** treat accepted request-fit compaction as progress only once per logical source segment and
revision. Within one `_fit_task_request` evaluation, compact the current-turn suffix and historical
prefix at most once each, reload and recheck after every accepted summary, then fail `context_fit`
locally if no untried segment can reduce the request. A later tool result starts a new evaluation
and may legitimately make the suffix eligible again.

**Non-goals:** no restriction on the compactor's bounded internal summary rounds, no loss of the
valid suffix-then-prefix path, no larger context/token limits, no retry or model-specific behavior,
and no new public trace ordinal/revision fields.

**Live path / files:** `edges/adapters/docket_runtime.py::DocketDriver.run_turn` →
`core/agent_loop.py::run_agent_turn::_fit_task_request` → the existing durable
`core/session.py::compact_session` path. Own the request-fit convergence clause in
`specs/functional/agent-loop.spec.md` and caller-level regressions in
`tests/python/test_docket_driver.py`; do not change the `request_fit` payload shape.

**RED test:** through `DocketDriver.run_turn`, make the first task request fit, return a real tool
call/result, estimate the grown raw retry over-window, accept one tool-free compaction, and keep the
reloaded summary irreducibly over-window. Assert exactly one task and one summary transport, one
successful compaction trace, no second task transport, no orphaned tool unit, and a local
`context_fit` result. The current loop repeatedly transports summaries. A second focused case proves
an independent historical prefix may still compact after the suffix was accepted.

**Acceptance:** each accepted suffix/prefix segment is marked before reload; every accepted summary
gets exactly one task recheck; an already-marked segment is never selected again in that evaluation;
distinct segments and internal hierarchical rounds remain available; the failed request retains the
actionable window/estimate/reserve error and valid durable summary; `request_fit` keeps its exact
privacy-safe key set. Caller-level RED, focused context suites, full pytest/static/golden/spec/metrics
gates, and deterministic workflow smoke pass.

**Contention:** shipped after C3's hermetic fixes because both cards own `_fit_task_request` and the
agent-loop spec. It does not require the blocked live endpoint.

**Shipped:** request-fit now protects each accepted suffix/prefix replacement by a private
content-derived revision, reloads and rechecks it exactly once, and permits only a newly appended
tail or the independent segment to compact next. A post-preflight durable check prevents transport
of a stale revision; an atomic positional task anchor remains correct even when a concurrent append
has identical text. A fixed convergence cap fails closed with privacy-safe input/reserve/window
evidence, while summary failures retain their original stop classification. Caller-level tests
cover irreducible rechecks, suffix-then-prefix, post-reload appends, identical task text, and
continuous churn without changing the public `request_fit` payload. The 79 focused loop/driver
tests and full pytest/static/golden/spec/metrics/smoke gates pass.

### W25-C7 — make the live maintenance task enforce the private-context boundary

**Status:** DONE (2026-08-30) · **Size:** S · **Owner:** @codex

**Measured trigger:** the preserved real-model canary at
`/tmp/docket-w25-c3-live-Ey3u1M` repaired the checkout, passed public and hidden acceptance, and
finished all five hops, but the final harness rejected two direct project-tool probes for an
inexistent `MEMORY.md`: one under the origin checkout and one under the Implementer's worktree.
Both reads failed and leaked no data. The system prompt already forbids searching private control
files, but the delegated maintenance task said only not to copy private logs into the repository.

**Goal:** make the realistic delegated task explicitly require every downstream role to use the
Lead's typed handoff for durable decisions and never search for or access Docket control files with
project tools, while keeping the decision values private and the final oracle fail-closed.

**Non-goals:** no filename/value leak from private memory, model-specific prompt branch, scripted
reply, relaxed privacy oracle, allowance for failed reads, change to the identity prompt, reduced
workflow gates, or retry-until-green policy.

**Live path / files:** `scripts/smoke_workflow.py::_run` delegates the memory-maintenance task →
public `docket pod smoke delegate` → the ordinary five-hop runtime → the final structured oracle
over durable `tool_call` traces and retained session calls. Own focused delegation/oracle tests in
`tests/python/test_workflow_smoke.py` and the live-canary clause in `specs/test-framework.md`; do
not change the production tool policy or private-state detector.

**RED test:** assert the actual delegate caller directs downstream roles to the Lead's typed
handoff, explicitly forbids project-tool access to `MEMORY.md`, `HEARTBEAT.md`, `memory/`, and
`.docket`, contains none of the seeded private values, stays within the public 500-character
ceiling, and persists through the real delegation CLI. It also requires structured `edit`/`write`
mutation and the README test command for validation. Keep the basic scenario byte-identical. Also
simulate a compacted-away failed `read` retained only in the durable trace and require a privacy-safe
rejection; cover relative selectors, malformed arguments, traversal/symlink escape, allowed
worktree normalization, and real approval prose resolved back to raw trace arguments.

**Acceptance:** the spec states that zero project-tool attempts at private control paths is part of
the live oracle; the delegated task carries that boundary without the private facts; durable traces
remain authoritative after compaction and retained sessions provide defense in depth without raw
argument/value leakage. A fresh un-scripted `memory-maintenance` world passes distillation, typed
handoff, repair, hidden acceptance, Reviewer/Tester/approval gates, session and trace checks, and
the structured private-access oracle. Then run full pytest/static/spec/metrics and deterministic
smoke gates.

**Contention:** owns the `test-framework`/smoke task text and shares the one mutable live endpoint,
so its remaining acceptance run must execute serially. It does not reopen C3's independently
measured agent-loop budget outcome.

**Implementation and acceptance history:** `memory-maintenance` now delegates a value-free boundary:
every downstream role must use only the Lead's typed handoff and never search `MEMORY.md`,
`HEARTBEAT.md`, `memory/`, or `.docket` with project tools. The 403-character instruction persists
through the real CLI and tells roles to mutate only through `edit`/`write` and validate only with
the README command. Test Framework 2.8.0 and 26 focused RED/green cases make durable traces the
historical authority, retain session defense in depth, normalize exact path components and allowed
roots, fail closed on opaque arguments, and resolve approval commands by traced `callId`.

The fresh un-scripted world `/tmp/docket-w25-c7-live-sRvVwQ` completed Lead, Implementer and
Reviewer; public plus hidden mechanical acceptance passed, the Reviewer approved, and the genuine
pipeline approval resumed Tester. The instruction reduced Implementer from 16 transports/90,000
tokens in `/tmp/docket-w25-c7-live-XesYwG` to five transports/21,315 tokens with one canonical
validation and no violations. Tester nevertheless requested 12 denied tool calls: eleven opaque
variants and one real, non-executed probe of an absent `<worktree>/.docket` child. It then reached
86,139 measured tokens; terminal finalization needed 6,644 estimated input plus 8,192 reserve, 975
more than the 13,861 remaining, so Docket refused transport locally. Only four hops completed and
the final Tester verdict is missing. The bounded re-audit found that the exact downstream boundary
did reach Tester, but its 6,302-byte effective system prompt simultaneously told it to write/read
private startup files and, later, never access them with project tools. W25-C8 owns that runtime
contradiction and W25-C9 owns truthful fail-fast canary evidence; no further live retry is authorized
until both land. W25-C10 is separate product hardening and is not a prerequisite for C7 acceptance.
W25-C8 and W25-C9 have now landed, so a fresh live acceptance run is authorized. The 2,371-test
collection (2,366 passed, five expected skips), Ruff, format, mypy, 24 specs, 18 goldens, metrics,
and deterministic smoke are green before that run.

Two fresh worlds exercised those changes. `/tmp/docket-w25-c7-live-vsw1AZ` proved C9 fail-fast:
the first opaque Implementer validation cancelled the active run, denied the approval and stopped
before another transport. That call used an alternate test runner despite the indirect README
instruction, so the delegated task now spells the only allowed shell command byte-for-byte and
forbids alternatives, wrappers, inline code and redirects while remaining 481/500 characters.
In `/tmp/docket-w25-c7-live-wN6msb`, the Implementer followed that exact command, received one real
operator grant, repaired the checkout, and passed public plus hidden mechanical acceptance; the
structured private-boundary oracle also passes. The Reviewer then put its approving marker on the
last line instead of the required first non-blank line, so the real verdict gate correctly failed
the task before approval/Tester. C7 remains blocked on live-model verdict conformance; another
unchanged retry is not authorized. W25-C11 now owns the deterministic marker-placement contract;
only after its gates land may C7 run one fresh serial acceptance.

W25-C11 shipped and closed the measured marker-placement blocker. The one authorized fresh serial
acceptance then passed in `/tmp/docket-w25-c7-live-L8nkOm`; no retry was used.

**Shipped / live acceptance:** the preserved un-scripted world discovered the single local Qwen
model and its 16,384-token window through the public endpoint, committed the intentionally red Git
fixture, distilled three private logs, and delegated the exact 481-character value-free boundary
through the public CLI. Task `task-e1b6620f-7dbb-4b5b-bb8e-9edb12c63363` reached `done` with five
typed hops; the persisted Reviewer/Tester verdicts are `approve`/`pass`. The Implementer repair
passes all four public regressions and the checkout-external hidden behavioral/AST acceptance.
Three genuine in-turn tool approvals and the distinct pipeline approval are granted, both run
records are `succeeded`, five isolated step histories retain measured usage, and 13 audit entries
verify clean. The durable-trace plus retained-session private-boundary oracle passes with no
confirmed-private or opaque call; diagnostics expose no raw arguments or private values. Measured
step usage totals 36,432 input and 1,530 output tokens, with no cost claimed for the local model.
After the canary, the full 2,382-test collection (2,377 passed, five contract-labelled skips), Ruff,
format, strict mypy, 24 specs, 18 goldens, metrics, `git diff --check`, and deterministic smoke pass.

### W25-C8 — compile one authoritative runtime startup contract

**Status:** DONE (2026-08-26) · **Size:** M · **Owner:** @codex

**Measured trigger:** in the preserved failing canary
`/tmp/docket-w25-c7-live-sRvVwQ`, every downstream role, including Tester, received the value-free
task boundary. Reconstructing Tester's real system prompt through
`core.identity.system_prompt_for_agent` produced 6,302 bytes containing both the generated
`WORKFLOW_AUTO.md` instructions to write `HEARTBEAT.md` and read `MEMORY.md` and the later runtime
footer that says those same private files are already loaded and must never be accessed through a
project tool. Tester then made one real `.docket` probe. This is a deterministic prompt-contract
contradiction, not missing handoff propagation.

**Goal:** give a live turn one non-contradictory runtime startup contract: preserve identity,
role/project rules, codebase location, and bounded current private state, while making Docket's
runtime ownership of private reads/durability the only actionable instruction the model receives.

**Non-goals:** no deletion or migration of the durable workspace files, loss of private context,
larger context/token budgets, model-specific prompt branch, task-description rewrite, relaxed C7
oracle, change to project-tool roots, or another live retry before deterministic gates pass.

**Live path / files:** `core/dispatch.py` resolves a hop →
`edges/adapters/docket_runtime.py::DocketDriver.run_turn` →
`core/agent_loop.py::run_agent_turn` → `core/identity.py::system_prompt_for_agent` currently folds
raw `SOUL.md`/`WORKFLOW_AUTO.md` plus `_runtime_workspace_context`; the conflicting generated prose
comes from `core/memory.py` and `core/archetypes.py::_LEGACY_AGENTS_TEMPLATE`. Own a runtime-safe
projection at that composition seam, focused identity/driver tests, requirement 30 and the
changelog in `specs/functional/agent-loop.spec.md`, and the matching README runtime-context claim.
The files stored in each Docket workspace remain owned by their existing provisioning contracts.

**RED test:** provision an ordinary Tester workspace with the real generated `WORKFLOW_AUTO.md`,
`AGENTS.md`, `HEARTBEAT.md`, and `MEMORY.md`, then call the default `DocketDriver` with a recording
backend. Assert its effective system message contains the role, effective project root, and private
state sentinels, but contains no active instruction to open, create, or write any private control
file and contains one authoritative project-tool prohibition. The current path carries both the
legacy read/write imperatives and the later prohibition. Assert the source workspace files remain
byte-identical and the system message is not persisted into the session.

**Acceptance:** define the runtime projection in the owning spec before code; do not regex-filter
arbitrary operator prose or silently discard role rules; preserve current priority, visible
truncation, persona refresh, small-context degradation, and session non-persistence behavior.
Tests cover full fit, truncated private state, absent optional files, a role with custom AGENTS
rules, and the exact C7 Tester contradiction through the real driver call path. Focused
identity/loop/driver tests, Ruff, format, mypy, spec validation, full pytest/goldens/metrics, and
deterministic smoke pass before C7 may resume.

**Contention:** shipped before W25-C10 because both own the agent-loop contract. W25-C9 remains
independent at code/test level; only the final local-model evidence is serial.

**Shipped:** every real turn now receives one runtime contract keyed to the exact roots already
resolved by `DocketDriver`; raw `WORKFLOW_AUTO.md` prose never reaches the backend. HEARTBEAT keeps
its actual H2 state but drops generated authoring scaffolding, AGENTS drops only `Session Startup`
while retaining red lines/custom sections, and TOOLS/MEMORY keep their bounded priority. The source
workspace stays byte-identical and no system context is persisted. Agent Loop 1.14.0, caller-level
driver REDs, all owning identity/loop/driver suites, the 2,363-test collection (2,358 passed, five
expected skips), Ruff, format, mypy, 24 specs, 18 goldens, metrics, and deterministic smoke pass.

### W25-C9 — type canary policy verdicts and fail fast on disqualification

**Status:** DONE (2026-08-26) · **Size:** S · **Owner:** @codex

**Measured trigger:** the latest live Tester created seven safe approvals, eleven opaque commands,
and one confirmed `.docket` target. `_private_tool_violation` returns `str | None`, so the monitor
and final oracle report both a confirmed private target and an unauditable command as
"private-state access." After the first irreversible canary violation, `_approve_live_tool_calls`
only accumulates an error while the blocking `pipeline run --follow` continues; the invalid world
therefore consumed 86,139 tokens before failure.

**Goal:** make the smoke oracle return and consume one typed verdict that distinguishes allowed,
confirmed-private, and opaque/malformed calls, while keeping both denial classes fail-closed and
stopping a live canary immediately once it can no longer satisfy acceptance.

**Non-goals:** no production policy-engine or `ToolResult` change, approval auto-grant, relaxed
opaque-shell handling, raw argument/private-value diagnostics, model prompt edit, retry-until-green,
or acceptance of a denied/absent private-file probe.

**Live path / files:** `scripts/smoke_workflow.py::_private_tool_violation` →
`_approval_private_tool_violation` → `_approve_live_tool_calls` for live decisions, and the same
classifier through `_verify_private_tool_boundary` for durable trace/session evidence. Own a typed
smoke-only verdict, the live subprocess/cancellation orchestration, focused cases in
`tests/python/test_workflow_smoke.py`, and the live-canary/oracle clause plus changelog in
`specs/test-framework.md`. Use the public approval and run-cancellation surfaces; do not mutate
Docket-owned JSON directly.

**RED test:** create a hermetic canary world with real-shaped durable traces and pending approvals.
Feed one allowed README validation, one opaque command, and one exact private component. Assert the
same classifier returns three distinct typed outcomes; the operator grants only the allowed call,
denies the disqualifying call through the real CLI, cancels the active run once, and makes no later
grant or model transport. The final trace/session oracle must reach the identical classification.
Today the two denials are both strings and the pipeline keeps running. A nearby counterexample
keeps a root-contained universal glob and the physical worktree prefix allowed.

**Acceptance:** monitor and final oracle share one typed decision function; diagnostics contain
only source/role/tool/call id/verdict/marker, never raw arguments or private values. Confirmed
private and opaque outcomes remain distinct but both invalidate the canary. Cancellation is
idempotent, preserves trace/session/audit evidence, never executes the denied handler, and does not
turn a disqualified run into success. The deterministic basic scenario remains byte-identical.
Focused workflow-smoke tests, deterministic full workflow, Ruff/format/mypy, spec validation, full
pytest/goldens/metrics pass; live endpoint acceptance remains deferred to C7 after C8 also lands.

**Contention:** owns the same smoke/Test Framework files as blocked C7, so C7 cannot resume while it
is in progress. Its code/tests do not overlap W25-C8; only the final local-model endpoint is shared
and must be used serially.

**Shipped:** the smoke monitor and final trace/session oracle now share a typed
`allowed`/`confirmed_private`/`opaque` verdict. Allowed README validation is granted; both denial
classes remain distinct and fail closed. The first disqualifying approval cancels the active run
and denies the token through the public CLI, signals the blocking `pipeline run --follow` to
terminate, and prevents subsequent subprocess/model transport. Privacy-safe diagnostics expose
only source, role, tool, call id, verdict, and marker. Test Framework 2.9.0, 34 focused workflow
cases, the 2,371-test collection (2,366 passed, five expected skips), Ruff, format, mypy, 24 specs,
18 goldens, metrics, and deterministic smoke pass; the real endpoint is intentionally delegated to
the resumed W25-C7 acceptance run.

### W25-C10 — make repeated in-turn policy denials typed and bounded

**Status:** DONE (2026-08-26) · **Size:** M · **Owner:** @codex

**Measured trigger:** in `/tmp/docket-w25-c7-live-sRvVwQ`, Tester received twelve consecutive
operator denials and continued producing alternative tool calls until 86,139 measured tokens. The
loop currently has only generic caps of 20 model iterations, 40 dispatched tool calls, and 100,000
tokens. `ToolVerdict` knows policy id/action, but `ToolResult` drops that provenance and returns only
free-text `REFUSED: <reason>`; `run_agent_turn` cannot distinguish invalid arguments, a guardrail
block, explicit approval denial, or approval timeout, nor detect denial-only non-convergence.

**Goal:** preserve the single `dispatch_tool` chokepoint while giving denied, non-executed calls a
stable typed denial kind and a bounded recovery contract. Permit correction after an isolated
refusal, but stop a turn predictably after three consecutive denied tool results instead of letting
policy refusal consume the general tool/token limits.

**Non-goals:** no change to allow/ask/deny precedence, auto-approval, weaker command classifier,
different policy matching, partial dispatch of a tool-call batch, raw command content in traces,
higher budgets, harness-specific branch, or treating an executed tool failure as a policy denial.

**Live path / files:** backend response → `core/agent_loop.py::run_agent_turn` →
`core/tools.py::dispatch_tool` → `evaluate_tool_call`/approval wait → `ToolResult.as_tool_output` →
atomic assistant/tool-result persistence and the next loop preflight. Own a `ToolDenialKind`-style
contract on `ToolResult`, propagation of policy/approval outcome without secrets, the consecutive
denial counter/config and terminal behavior, `tool_result` trace evidence, focused tool/loop/driver
tests, and coordinated version/changelog updates in
`specs/functional/security-gates.spec.md` and `specs/functional/agent-loop.spec.md`.

**RED test:** through the default `DocketDriver`, script three consecutive `bash` calls whose real
approval records are explicitly denied. Assert no handler executes, all three assistant/result
units and measured usage remain durable, denial kinds are stable despite different approval tokens,
no fourth backend call occurs, and the turn fails locally with `stop_reason="tool_denials"` and
`failure_kind="invalid_output"`. A counterexample
with one denial followed by an allowed executed call resets the consecutive count and can finish
normally. The current loop continues until a generic cap or token budget.

**Acceptance:** define a closed privacy-safe denial taxonomy covering invalid call, gate denial,
explicit approval denial, and approval timeout; propagate it through result, model-visible refusal,
and trace without exposing raw arguments. Default `max_consecutive_tool_denials` is three and is
independent of `max_tool_calls`; only denied/non-executed results increment it, an allowed executed
result resets it, and an entire returned tool-call batch retains current all-dispatched-or-none
preflight semantics. After the third denial, return one bounded actionable error containing only
the count and denial kinds, make no further model request, and leave every completed atomic unit
and measured usage durable. Focused security/tools/loop/driver tests, Ruff, format, mypy, both spec
validators, full pytest/goldens/metrics, and deterministic smoke pass.

**Contention:** W25-C8 is complete, so this card is ready. It is product hardening prompted by C7
evidence, not a prerequisite for C7's zero-attempt live acceptance and not parallel-safe with
another agent-loop/budget/session lane.

**Shipped:** `ToolResult.denial_kind` now carries the closed `invalid_call`, `gate_denied`,
`approval_denied`, or `approval_timeout` outcome for every denied, non-executed call; allowed or
executed failures carry none. Refusals expose the stable kind without approval tokens, and denied
`tool_result` traces add only `denialKind`. The live loop permits correction after an isolated
refusal, resets after an allowed executed result, and after the default third consecutive denial
persists the whole assistant/tool-result batch and measured usage before returning local
`tool_denials`/`invalid_output` with no next model request. Security Gates 0.16.0, Agent Loop
1.15.0, 194 owning tests, the 2,374-test collection (2,369 passed, five expected skips), Ruff,
format, mypy, 24 specs, 18 goldens, metrics, and deterministic smoke pass.

### W25-C11 — make terminal verdict placement unambiguous

**Status:** DONE (2026-08-30) · **Size:** S · **Owner:** @codex

**Measured trigger:** in `/tmp/docket-w25-c7-live-wN6msb`, the Reviewer approved the repair but put
its configured `APPROVE` marker on the final line. `core/orchestrator.py::parse_verdict` inspects
only the first non-blank line, so the live dispatch rejected that otherwise valid verdict and
blocked W25-C7 before approval and Tester. This is the exact expected/actual reproduction; another
unchanged paid-model retry is not authorized.

**Goal:** accept exactly one unambiguous configured verdict marker on any complete output line,
persist the normalized verdict once, and make live dispatch and resume derive the same result.

**Non-goals:** no permissive substring search, model-specific prompt, retry-until-green behavior,
provider structured-output API, changed rework limit, weakened zero/conflicting-marker failure, or
change to mechanical and human-approval gates.

**Live path / files:** `core/orchestrator.py::parse_verdict` parses a completed hop →
`core/dispatch.py` advances/reworks/fails and persists the handoff → resume reuses that artifact.
Own the configured verdict instruction in `core/archetypes.py`, focused parser/gate/resume tests,
and the current-state clauses in `specs/functional/pipeline-format.spec.md` and
`specs/functional/pod-dispatch.spec.md`. Do not edit the dirty agent-loop, run, smoke, identity,
memory, tool, or Test Framework paths. `TODO.md` and spec/README rollups remain integrator-owned.

**RED test:** exercise the public pipeline path with Reviewer prose followed by `APPROVE` on the
last line and Tester evidence followed by `PASS`; both must advance. Put `APPROVE` and
`REQUEST-CHANGES` on separate marker lines and require a local unparseable failure. Marker words
embedded in prose do not count. Repeated identical marker lines normalize to one verdict. Persist
an accepted verdict, simulate resume, and assert no second interpretation changes it. The current
first-line parser fails the valid-last-line cases.

**Acceptance:** scan complete output for line-anchored configured markers; accept exactly one
distinct normalized verdict, fail closed on zero or conflicting verdicts, and never infer a marker
from ordinary prose. Error text no longer claims a first-line contract. The handoff artifact stores
the accepted normalized verdict and crash-resume uses it without reparsing model prose. Run focused
orchestrator/reviewer/tester/rework/resume tests, Ruff and mypy while iterating, then full pytest,
format, goldens, spec validation, metrics, and deterministic smoke. Only after those gates pass may
W25-C7 own one fresh serial live canary.

**Contention / dependency:** the named source/spec paths are currently outside W25's 22 dirty
paths, but the card must still branch from the reconciled Wave 25 baseline and must not edit central
rollups. Dependency is `W25-C11 deterministic gates → W25-C7 fresh live acceptance → Wave 25 close
and dirty-tree integration → Wave 26 activation`.

**Shipped:** `parse_verdict` now applies the configured regex independently at the start of every
non-blank output line and accepts exactly one distinct normalized marker. A marker after prose and
repeated identical markers pass; zero markers, conflicting distinct markers, and marker words
embedded later in prose fail closed. Reviewer, Tester, Critic, downstream-checkout, and generic
hop prompts describe the same placement contract, and unparseable errors no longer claim a
first-line requirement. Dispatch persists the normalized value in the hop artifact; crash replay
uses it without reparsing model prose, while legacy records with no usable value retain their raw
output fallback. Pipeline Format 2.2.0 and Pod Dispatch 6.5.0 record the behavior. Public
Reviewer/Tester, conflict, repetition, prose, generic-gate, artifact round-trip, and resume cases
pass; the full 2,382-test collection (2,377 passed, five expected skips), Ruff, format, strict mypy,
24 specs, 18 goldens, metrics, `git diff --check`, and deterministic smoke are green. No paid/live
model call was made by this card.

---

## ☑ WAVE 26 COMPLETE (2026-08-31) — first successful turn and release/governance truth

**Integration state (2026-08-31):** COMPLETE. All Wave 26 cards are DONE. W26-C0 established
`main` as the canonical public/default release lineage without rewriting history; C1–C10c shipped
the first-turn, artifact, runtime-boundary, atomic-governance, and cooperative-cancellation
contracts; C11 reconciled every public claim with those behaviors. The Phase 23 decision and
later-wave triggers live in
[ROADMAP.md](ROADMAP.md#current-planned-program--phase-23-product-truth-and-ecosystem-proof). The
bounded coordinator packet is
[`.agents/handoffs/phase-23-productization.md`](.agents/handoffs/phase-23-productization.md).

**Why one wave can use many agents safely:** after activation, C1, C2, C6, C7, C8, C9, and C10
have independent source/function ownership. C3 waits for C0+C2; C4 waits for C1–C3; C5 waits for
C2; C11 integrates truth after the behavior cards. With four execution slots, use one coordinator
plus three workers and refill from the ready, non-contending pool after every merge. In a larger
pool, every dependency-free row may run concurrently in a separate worktree. Workers never edit
`ROADMAP.md`, `TODO.md`, `README.md`, or `specs/README.md`, never share `DOCKET_HOME`, temp paths,
ports, or a live model endpoint, and return evidence to the integrator instead of updating rollups.

### W26-C0 — establish one public release source

**Status:** DONE (2026-08-31) · **Size:** S · **Owner:**
integrator only

**Explicit trigger:** the 2026-08-30 audit found `platform` at the current Docket-owned runtime while
the public/default `main` lineage and mutable installer path still present older product truth. A
release cannot be reproducible when the landing page, installer, workflow, package, and formula do
not identify one source commit.

**Goal:** record and apply one non-destructive release-source decision: promote `platform` to the
default release lineage or explicitly version releases from it, so every public artifact resolves
to the same commit. Remote branch/default-branch changes require maintainer authorization at
execution time.

**Non-goals:** no history rewrite, forced push, deletion of `main`, compatibility shim for the
retired daemon, product rename, implementation feature, or automatic external publication.

**Live path / files:** repository branch/default settings → `.github/workflows/release.yml` tag
checkout → versioned source/package asset → `install.sh`/Homebrew metadata → README/quickstart.
Own only the decision, release ref checks, and integrator rollups. C2 owns Python packaging and C3
owns artifact immutability; do not absorb them here.

**RED evidence:** from a fresh clone of the configured release source, compare the checked-out
commit, package version, release workflow ref, installer asset ref, and documented architecture.
The current paths do not form one immutable lineage. A nearby counterexample is a feature branch,
which must never become a release merely because it is newer.

**Acceptance:** ROADMAP records the chosen lineage; the release workflow and installers consume an
explicit tag/commit from it; a read-only script or test fails when the repository/default docs and
release source diverge; no remote state changes without approval. The decision leaves both branch
histories recoverable. Run the focused release-source check and documentation/link validation; C3
and C11 own the final artifact and claim gates.

**Contention:** central/integration files only. It may coordinate with C1/C2/C6–C10 but no worker
branch edits its files.

**Shipped evidence:** maintainer authorization selected `main` as the canonical release lineage.
GitHub already reported `main` as the default branch; after refreshing origin, the preflight showed
`platform` was exactly 300 commits ahead of `origin/main` and zero behind. The integration update
fast-forwarded and synchronized both refs atomically without force push, deletion, or history
rewrite. ROADMAP D-31 records that releases/tags originate from `main`; C3 owns converting the
remaining mutable installer and formula inputs to immutable tagged assets.

### W26-C1 — guarantee a resolvable first provider

**Status:** DONE (2026-08-30) · **Size:** M · **Owner:** @codex

**Deterministic trigger:** `config.py` defaults to `anthropic/claude-sonnet-4-6`, onboarding asks
for `ANTHROPIC_API_KEY`, and `edges/adapters/llm.py::resolve_endpoint` has built-in URLs only for
OpenRouter and Vercel; a direct Anthropic key therefore resolves no endpoint. The advertised first
run can fail before one model request.

**Goal:** make the recommended clean setup select or register a callable OpenAI-compatible
endpoint, validate its credential/model/tool-call capability before initialization is declared
ready, and fail early with one exact corrective action when it cannot.

**Non-goals:** no vendor SDK, provider zoo, automatic paid network call in CI, dynamic model catalog,
fallback that silently changes models, streaming, multimodality, or weakening the one-driver rule.

**Live path / files:** `core/models_policy.py` presets and `config.py` default →
`cli/_install.py`/`cli/_provider.py` onboarding → API-key resolution →
`edges/adapters/llm.py::resolve_endpoint` and recording HTTP request → default `DocketDriver` turn.
Own model/API-key/CLI contract clauses and provider tests. Follow the provider-compatibility
reference in `docket-context-runtime`; do not edit packaging/release files.

**RED test:** with a fresh temporary `DOCKET_HOME`, follow the recommended non-interactive setup
using only an Anthropic key and assert initialization refuses to claim readiness because no native
endpoint exists. Then configure the supported loopback OpenAI-compatible endpoint through the
public surface and assert the selected model, credential, base URL, advertised context limits, tool
schema, and measured usage reach the recording server. The current first case incorrectly appears
configured.

**Acceptance:** every offered preset either resolves a callable endpoint or is labeled as requiring
an explicit compatible base URL before it can be selected; direct Anthropic/OpenAI/Google keys are
never presented as sufficient without a shipped adapter. `docket doctor` or the setup validation
reports the selected endpoint/model without exposing credentials. A fresh deterministic setup can
perform one gated tool-call turn. Run focused provider/auth/driver tests, Ruff, format, mypy, full
pytest, goldens, specs, metrics, and deterministic smoke.

**Contention:** the Wave 25 baseline is reconciled at `6b925f0`; this card is independent of C2 and
C6–C9. It owns provider/onboarding code and tests plus the named model/API-key/CLI spec clauses;
coordinate with C10 if either card changes the driver protocol.

**Shipped evidence:** setup now treats a coding-tool subscription or direct vendor key as distinct
from a callable runtime endpoint, refuses unresolved presets before persistence, verifies local
registration before writing, selects the exact registered model, and blocks first-project
continuation until provider readiness is structural. A provider-only `fleet.json` no longer skips
the shared foundation. The deterministic public-path test reaches a gated tool turn with no stored
key. The keyless live canary against `127.0.0.1:8081` completed all five governed hops at zero cost,
verified 11 audit records, and is preserved at `/tmp/docket-w26-c1-live-smoke-pa9AyI`. Closure gates:
2,391 tests with five contract-labelled skips, Ruff/format, strict mypy, 24 specs, 18 goldens,
metrics, deterministic smoke, and `git diff --check` pass.

### W26-C2 — provide one canonical installable CLI

**Status:** DONE (2026-08-30) · **Size:** M · **Owner:** @terra-c2

**Deterministic trigger:** root `pyproject.toml` exposes only `docket-py` while all primary docs use
`docket`; installed metadata lacks the expected license/project identity, and releases publish no
wheel or sdist that CI installs as a user would.

**Goal:** build a standards-compliant root wheel and sdist from the release source, install them in
a clean environment, and expose the documented `docket` command with matching version, license,
metadata, and import behavior.

**Non-goals:** no live PyPI publication without maintainer authorization, runtime-wheel redesign
(C5), dependency expansion, product rename, Homebrew update (C3), or source-checkout import in the
installation oracle.

**Live path / files:** root `pyproject.toml` metadata/scripts/build config → build artifacts → fresh
venv install → `docket --version`, `docket --help`, and a minimal `docket init --help`. Own focused
packaging tests and the CLI/package contract; do not edit docs/metrics rollups.

**RED test:** build the current root package, install only its artifact into a temporary venv whose
working directory is outside the repository, and invoke `docket --version`. The current artifact
does not supply that executable. Also inspect installed metadata for Apache-2.0, project URLs,
Python floor, and version agreement, and prove no source-tree module satisfies imports.

**Acceptance:** wheel and sdist build reproducibly; both install cleanly at the dependency floor;
`docket` is the canonical executable and any retained alias is explicitly documented; metadata and
license agree with the repository; uninstall leaves no unexpected shared files. Run artifact-build
and clean-venv tests, dependency-floor resolution, focused CLI tests, then full static/pytest,
goldens, specs, and packaging gates.

**Contention:** owns root packaging only. C3 consumes its artifact after merge; C5 may not edit root
packaging until C2 lands. Independent of provider and governance paths.

**Shipped evidence:** integrated commit `2d3e713` builds wheel and sdist artifacts that install from
outside the checkout at the direct dependency floor, expose canonical `docket` version/help/init
help, report aligned Apache-2.0/version/project metadata, and uninstall without deleting shared
dependencies. The two artifact-only oracles pass; `uv.lock` matches the verified Typer floor.

### W26-C3 — make release artifacts immutable and verifiable

**Status:** DONE (2026-08-31) · **Size:** M · **Owner:** @codex

**Deterministic trigger:** `Formula/docket-cli.rb` contains an all-zero SHA and declares MIT instead
of Apache-2.0; its comment says release automation updates it, but the workflow only archives source
and creates a release. `install.sh` downloads mutable `main` and does not consume the generated
checksum.

**Goal:** make one tagged release produce immutable install artifacts, checksums, correct formula
metadata, and verifiable installation inputs; CI must install the exact artifact before release is
eligible for publication.

**Non-goals:** no secret creation, external publication or default-branch mutation without approval,
package-manager proliferation, unsigned mutable fallback, or release of a dirty tree.

**Live path / files:** `.github/workflows/release.yml`, `Formula/docket-cli.rb`, `install.sh`, build
scripts/tests, and release documentation. Consume C2's artifact and C0's source decision. Keep
runtime distribution C5 separate.

**RED test:** generate a release in a temporary fixture and assert the current zero checksum,
license mismatch, mutable URL, and unused checksum fail. Tamper with one downloaded byte and require
the installer to stop before execution. A correct versioned artifact installs and reports the tag
version from outside the source tree.

**Acceptance:** workflow builds/tests wheel+sdist, records SHA-256 checksums, correct Apache-2.0
metadata, SBOM and provenance/attestation inputs, and creates formula/installer data from the exact
tagged asset. Installer verifies before executing and has no mutable-`main` path. Publishing remains
an explicit protected job. Run ShellCheck, workflow/config validation, clean artifact install,
tamper rejection, dependency floor, and the full repository gates.

**Contention:** release/install files only after C0/C2. It can run while governance cards execute;
C11 alone updates README/quickstart claims from the final artifacts.

**Shipped evidence:** RED commit `0251972` defines six release-boundary oracles; implementation
commit `5bb106a` makes all six pass. Tagged releases build and clean-install the exact root wheel and
sdist outside the checkout, checksum every downloadable install asset, produce an SPDX SBOM, request
build provenance, and publish only through the protected `release` environment. The remote installer
verifies the versioned asset before extraction; Homebrew consumes that same tagged asset with the
real SHA-256 and Apache-2.0 metadata. Preserved diagnosis proved the earlier smoke signal was a
noncanonical invocation error: the exact 16 artifact bytes existed, while `.venv/bin/python` had not
added the venv to child `PATH`; the documented `uv run python scripts/smoke_workflow.py` command
completed the approval/resume workflow. Commit-level closure passes ShellCheck, workflow/YAML,
clean dependency-floor artifact installs, tamper rejection, 2,442 tests with five contract-labelled
skips, Ruff/format, strict mypy over 74 source files, 24 specs, 18 goldens, metrics, and canonical
deterministic smoke.

### W26-C4 — enforce clean-install-to-first-turn in CI

**Status:** DONE (2026-08-31) · **Size:** M · **Owner:** @codex

**Measured trigger:** focused suites are strong, but no release gate proves that a user can install
the built artifact, configure a supported endpoint, initialize a project, execute a governed turn,
and inspect durable evidence without importing the checkout. The broken default provider and CLI
entrypoint survived because these boundaries were tested separately.

**Goal:** create the Wave 26 release oracle: one hermetic, deterministic journey from built artifact
to a successful governed tool turn and observable session/trace/audit state.

**Non-goals:** no paid/live provider, source-mode shortcut, broad workflow benchmark, UI, flaky
network dependency, or replacement for focused tests.

**Live path / files:** isolated release-journey script/workflow → fresh venv and home → public
provider configuration → `docket init` → task delegation/dispatch through loopback Chat
Completions → governed tool → terminal response → public trace/run inspection. Own a new bounded
release acceptance fixture and Test Framework clause; do not make the existing live canary larger.

**RED test:** install the pre-C1/C2 artifact outside the repository and follow the documented setup;
require failure at the missing `docket` executable or unresolved default endpoint. The green fixture
must reject a hidden `PYTHONPATH`/checkout import and prove the recording server observed the model,
tools, tool result, final turn, and measured usage.

**Acceptance:** a single CI command builds, installs, configures, initializes, dispatches, and
asserts terminal run/task state plus session, trace, audit, and tool side effects. Failed endpoint
validation leaves no half-ready installation. The fixture uses unique temp state/ports and prints
only bounded failure evidence. Run it on Linux and the supported macOS lane, then full static,
pytest, goldens, specs, metrics, deterministic smoke, and packaging-floor gates. This is Wave 26's
release exit gate.

**Contention:** depends on C1–C3 and consumes their public surfaces unchanged. It owns the new
release journey, not their implementation files.

**Shipped evidence:** RED commit `f8f897e` defines three artifact-installed journey contracts;
implementation commit `6c52df7` adds the bounded `scripts/release_journey.py` oracle and a blocking
Ubuntu/macOS CI matrix. The journey builds the exact wheel, installs it into a fresh venv outside
the checkout with a poisoned `PYTHONPATH`, configures the public provider, initializes a project,
executes one governed tool effect, and proves the request tools, tool result, final response,
measured usage, task/run/session/trace/audit records, and clean failure without half-ready state.
Commit-level closure passes the Linux and macOS journey jobs, 2,445 tests with five
contract-labelled skips, Ruff/format, strict mypy over 74 source files, workflow YAML, clean
dependency-floor artifact installs, 24 specs, 18 goldens, metrics, and deterministic smoke.

### W26-C5 — publish a non-overlapping runtime distribution boundary

**Status:** DONE (2026-08-31) · **Size:** M · **Owner:** @terra-c5

**Deterministic trigger:** `packages/docket-runtime/pyproject.toml` force-includes the same
`docket/*` paths as the full distribution, so installing/upgrading/uninstalling both wheels can
overwrite or remove shared files. The package is unpublished, wheel-only, and has no small stable
embedding facade or executable import tutorial.

**Goal:** give the embedded runtime one non-colliding installation topology, minimal versioned
public facade, clean wheel+sdist build, and end-to-end embedding example while preserving the owned
loop and policy chokepoint.

**Non-goals:** no generic plugin framework, moving every internal module, new runtime features,
tenant/serving layer, second driver, or exposing every internal name as a stability promise.

**Live path / files:** `packages/docket-runtime/pyproject.toml`, runtime namespace/facade, root
package dependency/layout after C2, packaging tests, and `specs/api/runtime-library.spec.md`.
Exercise installed artifacts from outside the monorepo.

**RED test:** install current full and runtime wheels into one temporary venv, capture their owned
files, uninstall either distribution, and assert imports from the other break or ownership
overlaps. Then build the runtime sdist and require its current monorepo-relative failure. A minimal
consumer program must import only the proposed public facade and execute one gated fake tool call.

**Acceptance:** distributions have one intentional ownership graph with no independently
uninstallable wheel deleting the other's files; wheel and sdist install at the declared dependency
floor; public facade and SemVer/deprecation boundary are spec-pinned; consumer example exercises
policy, approval stub, audit/trace and tool dispatch without CLI dependencies. Run clean dual-install,
upgrade/uninstall, build, import, consumer, dependency-floor, full static/pytest/spec/golden gates.

**Contention:** starts only after C2 freezes root packaging. It owns runtime packaging/spec; C11
owns public prose. External adapters remain Wave 28, not this card.

**Shipped evidence:** commits `cabad9e` and `55ef80b` give `docket-runtime` exclusive ownership of
the `docket_runtime/` namespace, a versioned facade, and a private CLI-free runtime closure built
from the canonical source. The artifact oracle rebuilds wheel and sdist outside the checkout at
the direct dependency floor, proves disjoint RECORD paths and both uninstall directions, exercises
granted and denied gated fake tools with audit/trace evidence, and verifies build staging cleanup.

### W26-C6 — make audit append and rotation one atomic chain transition

**Status:** DONE (2026-08-30) · **Size:** M · **Owner:** @terra-c6

**Deterministic trigger:** direct inspection of `core/audit.py::audit_log` shows rotation, current
head calculation, and append occur without one inter-process critical section. Parallel workers
can derive the same sequence/predecessor and make the public `docket audit verify` oracle reject
otherwise legitimate history. The current contract is best-effort and non-raising, so silent loss
must be corrected without retroactively making every mutation command fail on audit I/O.

**Goal:** serialize rotate → head → append as one durable chain transition, preserve sequence and
predecessor hashes across rotation, give callers a bounded written/failed result, and make both
programmatic readers and the public verify command observe a coherent snapshot.

**Non-goals:** no database, event bus, remote audit sink, mutation-command failure policy, operator
health/metric surface, rewrite of prior entries, secret-bearing diagnostics, approval-state change,
or generic store lock.

**Live path / files:** mutator → `core/audit.py::audit_log` → dedicated audit lock →
`_rotate_if_needed` → `_chain_head` → append/flush/close/permission check of `audit.log[.1]` →
`read_audit`/`verify_chain` → `cli/_audit.py` → public `docket audit verify [--json]`. Own
`core/audit.py`, its audit tests, the audit behavior spec, and only the narrow `_audit.py` routing
needed to stop raw unlocked reads. Do not edit `edges/store.py`, approval functions, unrelated
mutators, or central CLI plumbing.

**RED test:** use a process barrier and a delay after head calculation to make at least 32 unique
writers overlap, first below and then across a forced-small rotation threshold. Add deterministic
lock-timeout, append-failure-before-write, and append-failure-after-rotation injections. Prove the
current implementation can duplicate/break lineage, and that the current API cannot distinguish a
recorded event from a failed write. Include sequential, legacy-readable, and JSON CLI verify
counterexamples.

**Acceptance:**

- `audit_log` returns a typed `written | failed` status, never raises audit I/O detail, and remains
  source-compatible with existing callers that intentionally ignore the result. C6 adds no health
  metric and does not change the success/failure of the mutation that called it.
- One dedicated inter-process lock covers rotation decision, head read, append, flush, close, and
  owner-only permission restoration. Every successful concurrent event appears exactly once with
  contiguous sequence/predecessor hashes; `docket audit verify` and `--json` pass after rotation.
- Lock timeout or write failure returns `failed` and leaves no partial JSON line or false event. If
  append fails after rotation, the intact backup remains authoritative, the current log contains no
  claimed event, and the next successful append continues from the backup head without a gap.
- `read_audit`/`verify_chain` take a compatible snapshot under the audit lock, and `_audit.py` uses
  that core reader rather than bypassing it. Ordinary sequential output and every legacy shape the
  spec promises remain unchanged.
- Focused evidence names the barrier tests, rotation case, two write-failure phases, lock timeout,
  permissions, public CLI text/JSON verify, and compatibility cases. Then run audit/mutator tests,
  repeated concurrency, Ruff/mypy, and full pytest/goldens/specs/metrics/smoke.

**Contention:** owns audit module/spec/tests plus the narrow CLI audit reader call. C7 may consume
the typed status without editing audit code; merge C6 first if C7 asserts it. Any request to make
mutations fail, add health visibility, or change another caller becomes a separately measured card.

**Shipped evidence:** commits `4493874` and `6e6cfd3` make rotate → head → append/flush/close/0600
one bounded inter-process transition and route public readers through a coherent snapshot.
Thirty-two-process cases pass below and across rotation; timeout, pre-write, post-rotation, and
close-after-close failures return `failed` without a partial or false event, while the next write
continues the verified chain.

### W26-C7 — make approval resolution compare-and-set atomic

**Status:** DONE (2026-08-31) · **Size:** M · **Owner:** @terra-c7

**Deterministic trigger:** `approval_grant`/`approval_deny` read `pending`, then `_set_state` rereads
and separately writes. Concurrent CLI, HTTP, Telegram, timeout, or pipeline decisions can both
report success, emit contradictory trace/audit events, and let the last write win.

**Goal:** resolve `pending → granted|denied|expired` with one locked conditional transition and emit
exactly one matching trace/audit outcome from the winning decision.

**Non-goals:** no approval UX change, new channel, token format, policy precedence change, audit
implementation edit, retry-until-success, or acceptance of stale state.

**Live path / files:** CLI/HTTP/Telegram/pipeline waiter → `core/approval.py` grant/deny/timeout →
existing `edges/store.py::read_modify_write` → trace/audit. Own approval functions and focused
channel/concurrency tests plus approval clauses in security/audit specs; use store/audit unchanged.

**RED test:** place a real pending record behind a process/thread barrier and race grant vs deny,
grant vs grant, deny vs expiry, and two HTTP/Telegram-shaped callers. Assert the current path can
let more than one caller observe pending. Include unknown/already-terminal counterexamples.

**Acceptance:** exactly one caller changes state and emits the one trace/audit event; every loser
gets the correct stable noop/error from the committed state; record remains valid and owner-only;
approval wait observes the winning result and cannot execute a denied handler. Run focused
approval/channel/serve/tool tests, concurrency repetition, Ruff/mypy, then full repository gates.

**Contention:** owns `approval.py` and approval tests/spec clauses only. No `audit.py`, store helper,
serve handler, Telegram adapter, or tool-policy implementation edits unless a failing live caller
proves a separate card is required.

**Shipped evidence:** commit `7babf67` moves the pending-state check and terminal write into one
existing store RMW. Repeated grant/deny, grant/grant, deny/expiry, HTTP, and Telegram races prove
one winner and one matching trace/audit event; losers retain stable error/no-op behavior, timeout
waiters observe the persisted winner, and approval records remain owner-only.

### W26-C8 — allocate pod resources without collisions

**Status:** DONE (2026-08-30) · **Size:** S · **Owner:** @terra-c8

**Deterministic trigger:** `allocate_pod_resources` loads the registry, computes the next range, and
later writes under a separate lock. Concurrent CLI or threaded `POST /pods` provisioning can assign
the same port range to two projects. Static inspection also exposes a same-project rollback race:
two attempts can share the idempotent allocation; if one succeeds while the other fails, the
loser's unconditional `free_pod_resources(project)` can remove the winner's range and runtime
directory. The duplicate/cross-attempt outcomes remain expected reproductions until the RED barrier
tests run; the unlocked transitions themselves are directly observed.

**Goal:** serialize one project's exists-check → resource ownership → member creation → commit or
rollback, allocate different projects through one locked registry transition, and ensure a failed
attempt removes only resources and files it created.

**Non-goals:** no dynamic port scan, daemon allocator, changed range size/base, generic scheduler,
serve refactor, or worktree behavior change.

**Live path / files:** `serve.py::_handle_post_pods` or
`cli/_pod.py::build_pod_from_blueprint` → `pod_provisioning.provision_pod` →
`provision_members` → `allocate_pod_resources`/`free_pod_resources` →
`store.read_modify_write(PORT_ALLOC_FILE)` → member metadata/workspace and attempt-owned rollback.
Own project-scoped serialization/resource-ownership functions in `pod_provisioning.py`,
`tests/python/test_pod_resources.py::TestPortAllocation`, and
`tests/python/test_serve_pods_endpoint.py::{TestIdempotence,TestRollback}`. Primary contract is
`specs/data/serve-read-api.spec.md`'s `POST /pods` partial-failure paragraph and validation clause;
the resource-field side effect is `specs/data/docket-meta.spec.md`'s
`portRangeStart`/`portRangeCount`/`scratchDir` table. Do not edit generic store code or duplicate the
CLI/HTTP provisioning path.

**RED test:** add barrier-backed cases for (1) two different projects reading the same empty
registry, and (2) two same-project `provision_pod` calls where one succeeds and the other fails
after allocation. The first must currently be able to choose the same range; the second must expose
whether the loser frees the winner's allocation/runtime. Green cases require unique different-project
ranges, exactly one same-project winner with the loser returning already-exists or failure without
touching the winner, idempotent allocation, free/reuse, and rollback after member creation fails.
Focused RED command:
`uv run pytest -q tests/python/test_pod_resources.py::TestPortAllocation
tests/python/test_serve_pods_endpoint.py::TestIdempotence
tests/python/test_serve_pods_endpoint.py::TestRollback`.

**Acceptance:** concurrent successful pods have disjoint deterministic ranges; failed provisioning
removes only state created by that attempt; a same-project successful winner retains its allocation,
runtime directory, members, metadata, and scratch directory after the losing request exits. The
project-scoped critical section covers the already-exists check through rollback/commit, and a
different project is not forced through that project lock except at the short shared allocation
registry transition. Registry and member metadata agree after every result. Run the named focused
command repeatedly, the remaining provisioning/serve/store tests, Ruff/mypy, then full
pytest/goldens/specs/metrics/smoke.

**Contention:** activation reconciled the clean baseline before the isolated lane started. The
shipped path is independent of C7/C9/C10 and calls generic store APIs unchanged.

**Shipped evidence:** commit `f9c9fd5` serializes one project's full provisioning attempt and uses
one short atomic allocation-registry transition across different projects. The 13-case focused
oracle proves disjoint ranges, one same-project winner, allocation/member/metadata consistency,
free/reuse, and rollback that removes only attempt-created state while preserving pre-existing
runtime files.

### W26-C9 — preserve concurrent conversation updates

**Status:** DONE (2026-08-31) · **Size:** S · **Owner:** @terra-c9

**Deterministic trigger:** dispatch `_persist_hop` performs `_conv.load()` → pure
`touch_for_hop()` → `_conv.save()` as separate operations. Parallel hops updating different
conversations can each save a stale whole registry and erase the other's activity.

**Goal:** expose one locked conversation mutation boundary and route hop touches plus public
conversation mutators through it without changing the registry shape or fabricating conversations.

**Non-goals:** no transcript storage, new messaging channel, schema expansion, automatic topic
generation, raw hop output beyond the existing preview, or dispatch state-machine refactor.

**Live path / files:** dispatch `_persist_hop` and conversation CLI/wire callers →
`core/conversations.py` pure mutation → `CONVERSATIONS_FILE` through existing store RMW. Own
conversation I/O/mutation helpers and focused concurrent tests; dispatch owns only the exact
conversation call site.

**RED test:** seed two wired agents, synchronize two hop touches after each has read the same
registry, and assert current load/save loses one update. Green cases preserve both task refs and
previews, keep unrelated/unknown fields promised by the contract, make unwired agents a byte-identical
no-op, and fail atomically on a mutation exception.

**Acceptance:** every public mutation is one locked read/validate/mutate/write; parallel different
and same-conversation updates obey a documented deterministic winner/merge rule; no raw full hop is
stored; malformed registry behavior remains explicitly fail-closed or recoverable. Run focused
conversation/dispatch/Telegram/store tests, Ruff/mypy, then full repository gates.

**Contention:** owns `conversations.py` and the narrow `_persist_hop` call only. Do not combine with
pipeline dispatch changes; coordinate if another active card owns `dispatch.py`.

**Shipped evidence:** commit `790f578` routes every production conversation writer through one
validated store RMW and changes `_persist_hop` only at its conversation touch. Concurrent same- and
different-conversation cases preserve both updates and unknown fields; unwired/unknown mutations
are byte-identical no-ops, malformed registries fail closed, callback errors are atomic, and hop
previews remain bounded.

### W26-C10 — make run cancellation cooperative and truthful

**Status:** DONE (scope split 2026-08-31; no product behavior claimed) · **Size:** L → M/M/M ·
**Owner:** coordinator

**Deterministic trigger:** `DocketDriver` ignores `on_spawn` because the turn is in-process, while
`cancel_run` kills only recorded child PIDs and marks state cancelled. The active model/tool loop
can continue producing tool side effects after the operator sees a cancelled terminal run.

**Goal:** propagate a run-scoped cooperative cancellation signal through dispatch, driver, loop,
approval wait, model-request boundaries, and tool dispatch; stop before any new transport/tool side
effect after cancellation and document the bounded behavior of an already-blocking HTTP request.

**Non-goals:** no unsafe thread kill, false claim that Python can abort every socket instantly,
subprocess-only workaround, new async framework, state-only cancellation, or loss of completed
session/trace/audit evidence.

**Split result:** W26-C10a owns the persisted signal lifecycle and terminal CAS; W26-C10b consumes
that exact contract through driver/loop/approval/tool checkpoints; W26-C10c reconciles task/run
outcomes and public surfaces with a cross-process whole-path oracle. No child is claimed by this
planning change. The three children are sequential because each consumes the prior contract.

**Live path / files:** `docket runs cancel` CLI plus existing GET run readers →
`core/runs.py` registry/signal →
`core/dispatch.py` → `core/runtime_driver.py` → `DocketDriver.run_turn` →
`agent_loop.run_agent_turn` before model transport, approval wait, and tool dispatch → final
run/task/session/trace reconciliation. Own the agent-loop/pod-dispatch/serve cancellation clauses
and recording backend tests.

**RED test:** block a recording backend or approval wait, cancel through the public surface, then
release the block. Current code proceeds. Green acceptance makes no subsequent backend request,
approval grant, tool handler call, or success overwrite; repeated cancel is idempotent; completed
atomic assistant/tool units remain durable. A separate blocking-transport case records that the
current request may finish but its result is discarded and no next side effect occurs.

**Acceptance:** one signal identity follows the run; checkpoints exist before every model request,
before/after approval wait, and before tool execution; cancellation wins terminal-state races;
run/task outcomes and public wording distinguish requested, observed, and fully stopped; no orphan
tool-call/result pair is persisted. Run split-card focused REDs, concurrency/repetition tests,
serve/CLI/golden contracts, Ruff/mypy, then full pytest/specs/metrics/smoke.

**Contention:** superseded by the exact child boundaries below. This parent is planning-complete,
not implementation-complete.

### W26-C10a — persist one truthful run-cancellation signal

**Status:** DONE (2026-08-31) · **Size:** M · **Owner:** @codex

**Decision / deterministic trigger:** D-30 governs this card. `cancel_run` currently performs an
unlocked read, kills captured PIDs, clears them in a second transition, and immediately writes the
terminal state `cancelled`. For the shipped in-process driver that terminal label is false evidence:
the backend/tool thread may still be running. A thread-only `Event` would also make a separate
`docket runs cancel` process invisible to the running dispatcher.

**Goal:** establish one typed, cross-process cancellation identity per run and one atomic registry
lifecycle that distinguishes request, observation, and full stop while preserving queued-run and
terminal-race behavior.

**Non-goals:** no loop/driver checkpoints, approval/tool changes, task-status changes, CLI wording,
new HTTP mutation endpoint, unsafe thread termination, new async framework, or generic signal bus.

**Live path / ownership:** `core/runs.py` functions `create_run`, `execute`, `cancel_run`,
`_finish_run_transition`, and `current_run_id`, plus a small typed signal handle in that module;
`edges/store.py` remains the
sole JSON writer and is consumed unchanged. Own focused registry/cancellation tests in
`tests/python/test_run_registry.py`, `test_run_cancellation.py`, and
`test_dispatch_run_records.py`; own only the run-record cancellation lifecycle/schema clauses in
`specs/data/serve-read-api.spec.md`. Do not edit dispatch, driver, loop, approval, tools, CLI,
serve handlers, public docs, central rollups, or runtime packaging.

**Persisted contract:** the run id is the signal identity. A typed handle reads the authoritative
run record at each checkpoint; no process-local event is sufficient. Add one forward-compatible
`cancellation` object with nullable `requestedAt`, `observedAt`, and `stoppedAt` timestamps plus a
bounded non-secret reason/source. Do not persist a redundant derived phase. A queued request sets
all three timestamps and terminal `cancelled` in one RMW because no work started. A running request
sets `requestedAt` once and leaves the run nonterminal until execution observes/stops. Observation
and stop are monotonic/idempotent. Existing records without the object mean “not requested.”

**RED tests:** (1) barrier `cancel_run` against `_finish_run_transition` and prove the current
separate read/clear/finish path can report cancellation after success or lose the terminal winner;
(2) start `runs.execute` in one process/thread and issue cancellation from a separate Python/CLI
process sharing only `DOCKET_HOME`, proving a local event cannot be the authority; (3) cancel a
running run with no PIDs and assert current state claims fully `cancelled` before the blocked body
returns. Include unknown, queued, already-requested, and succeeded/failed/cancelled fixtures.

**Acceptance / oracles:** one conditional store RMW chooses request-versus-terminal winner and
captures the PIDs to signal; exactly one first request audits, repeated requests are idempotent and
never re-kill/re-audit; queued cancellation prevents `execute` from invoking its body and is fully
stopped immediately; running cancellation remains visibly requested until `execute` observes it;
if request wins, later success/failure folding finalizes `cancelled` rather than overwriting it, and
if success/failure wins, cancellation is a stable no-op. Malformed lifecycle data fails closed
without fabricating a stopped claim. Permissions and unrelated/unknown run fields remain intact.

**Validation:** focused repeated command:
`uv run pytest -q tests/python/test_run_registry.py tests/python/test_run_cancellation.py
tests/python/test_dispatch_run_records.py`; then affected CLI/read-API compatibility tests,
Ruff/format, strict mypy, spec validation, and full pytest/goldens/metrics/smoke before handoff.

**Dependency / contention:** ready now. This card exclusively owns `runs.py` and the run-record
lifecycle spec/tests. C10b starts only after its commit lands and may consume but not redesign the
signal. No parallel loop/session/budget card may touch the same run ContextVar or registry.

**Shipped evidence:** RED contract commit `0d24f7a` and implementation commit `dc69142` add the
versioned persisted lifecycle and typed run-id signal, resolve request-versus-terminal in one store
transition, keep running work nonterminal until its executor stops, and preserve queued, malformed,
legacy, repeated-request, permission, and unknown-field behavior. Cross-process, barrier-race,
CLI/read compatibility, full pytest/smoke, static, spec, golden, and metrics gates pass.

### W26-C10b — stop the owned loop at every side-effect boundary

**Status:** DONE (2026-08-31) · **Size:** M · **Owner:** @codex

**Deterministic trigger:** after C10a, the persisted signal is truthful but the in-process
`DocketDriver` still does not consume it. `run_agent_turn` can start later backend requests, wait on
an approval, or call a tool handler after cancellation was requested.

**Goal:** carry C10a's one signal identity through dispatch → driver → agent loop and cooperatively
stop before every not-yet-started model transport, approval wait continuation, and tool handler,
while retaining already-completed atomic assistant/tool units.

**Non-goals:** no public CLI/API/docs changes, new cancellation lifecycle fields, new task-status
vocabulary, unsafe interruption of an already-blocking HTTP request or tool handler, subprocess-only
fallback, second driver, async rewrite, or bypass around `core/tools.py::dispatch_tool`.

**Live path / ownership:** exact production call in `core/dispatch.py::_execute_unit` →
`core/runtime_driver.py::{RuntimeDriver,TurnResult,FailureKind}` →
`edges/adapters/docket_runtime.py::DocketDriver.run_turn` →
`core/agent_loop.py::run_agent_turn` → `core/tools.py::dispatch_tool` →
`core/approval.py::wait_for_approval`. Own the narrowly required cancellation callback on
`ToolContext`, the `run_cancelled` result/failure/stop vocabulary, and focused tests in
`test_agent_loop.py`, `test_runtime_driver.py`, `test_approval_gated_dispatch.py`,
`test_run_cancellation.py`, and exact neighboring dispatch tests. Own cancellation clauses in
`specs/functional/agent-loop.spec.md` and `security-gates.spec.md`. Consume C10a `runs.py` APIs;
do not redesign its persisted shape. Do not edit CLI/serve/public docs, central rollups, unrelated
dispatch state-machine code, session storage primitives, audit implementation, or runtime facade.

**RED tests:** use barrier recording backends at (a) compaction transport and (b) ordinary task
transport, an approval wait, and a recording tool handler. Request cancellation, release the block,
and show current code starts the next request, accepts a granted token, or invokes the handler.
Add a model response containing multiple tool calls and cancel between calls to expose partial
execution/history risk. Record backend-call ordinal, signal checkpoint, handler count, approval
state, session bytes, and trace events.

**Acceptance / oracles:** the same typed signal reaches parallel worker context and driver/loop;
checkpoints run before every compaction/task/finalization backend call, immediately after each
backend return, before and after approval wait, immediately before each handler, and after an
already-running handler returns. A request already blocking may finish, but its post-cancel response
is discarded, no tool call from it executes, and only measured usage explicitly promised by the
owning session contract may persist. Cancellation during approval conditionally denies the pending
token and cannot execute after a concurrent grant; cancellation during a multi-call batch produces
a complete non-orphan assistant/tool-result unit for work already admitted and explicit cancelled
results for the remainder. Cancellation during an already-running handler lets that handler finish,
persists its complete unit, then stops before another handler/backend call. No retry treats
`run_cancelled` as transient. Existing non-run embedding callers with no signal remain unchanged.

**Validation:** repeat focused cancellation node ids at least 20 times, then run agent-loop,
runtime-driver, approval/tool, dispatch/parallel, session atomicity, and runtime-package-boundary
tests; Ruff/format, strict mypy, both owning specs, full pytest, goldens, metrics, and deterministic
smoke. The artifact boundary must prove the optional signal did not add a CLI/control-plane import
to `docket-runtime`.

**Dependency / contention:** C10a is accepted at `dc69142`; consume that signal without redesigning
it. This card owns the loop/driver/tool path serially and cannot overlap another agent-loop,
session, approval, tool-dispatch, or runtime-package card. C10c starts only after these typed
outcomes and checkpoints land.

**Shipped evidence:** RED contract commit `3244fb2` and implementation commit `d6eca09` propagate
C10a's persisted signal through the production driver into the agent loop and sole tool
chokepoint. Cancellation now discards post-cancel compaction/task responses while retaining measured
usage, conditionally resolves pending approval without overwriting a concurrent winner, lets an
already-running handler finish, writes explicit `run_cancelled` results for an unstarted batch
remainder, persists the complete assistant/tool unit, and stops without retry. The four barrier
nodes pass 50/50 repeated runs; production driver binding, approval/tool, runtime-package, full
2,429-test suite with five contract-labelled skips, Ruff/format, strict mypy over 74 source files,
24 specs, 18 goldens, metrics, and deterministic smoke all pass.

### W26-C10c — reconcile cancelled task/run truth through public surfaces

**Status:** CLOSED (2026-08-31) · **Size:** M · **Owner:** @codex

**Deterministic trigger:** C10b can stop the owned loop, but current dispatch maps every failed hop
through ordinary failure semantics and current CLI/docs say `cancel` immediately kills/marks the
run. Public run/task records cannot yet distinguish requested, observed, and stopped cancellation.

**Goal:** fold C10b's typed cancellation outcome into durable task/run reconciliation, render the
C10a lifecycle truthfully through existing CLI and read APIs, and prove the complete path with one
cross-process public cancellation oracle.

**Non-goals:** no new POST cancellation API, dashboard, websocket/streaming surface, signal redesign,
new loop checkpoints, transport abortion claim, cancellation of arbitrary non-run library calls,
or unrelated task-state refactor.

**Live path / ownership:** C10b outcome at the narrow `core/dispatch.py` hop/task reconciliation →
C10a `core/runs.py::execute` finalization → `cli/_runs.py` list/show/cancel and existing
`serve.py` GET `/runs`/`/runs/<id>` readers. Own the additive task status `cancelled` from
`TaskResult` through the existing task registry so a cooperatively stopped hop is not mislabeled
`failed`; preserve every other task shape. Own
`tests/python/test_cooperative_run_cancellation.py` as the whole-path oracle plus focused
`test_runs_cli.py`, `test_dispatch_run_records.py`, `test_dispatch.py`, and serve read tests. Own
the cancellation clauses/version/changelog in `pod-dispatch.spec.md`, `serve-read-api.spec.md`,
`cli-interface.spec.md`, and `cli-json-shapes.spec.md`, plus `docs/commands.md`, `docs/DOCKET.md`,
and `docs/WORKFLOW-GUIDE.md`. README/spec index/ROADMAP/TODO/metrics remain integrator-owned.

**RED test:** run a real `runs.execute` + production `DocketDriver` path against a recording
loopback backend blocked on its first response; from a separate subprocess invoke the installed
`docket runs cancel <id>` against the same `DOCKET_HOME`, then release the backend. Current public
command immediately claims terminal cancellation while the returned tool call still executes.
Add approval-wait and already-running-handler variants, repeated cancel, queued cancel, and a
finish-versus-request barrier. Capture only bounded counters/state/timestamps—never model/tool text.

**Acceptance / oracles:** running cancel output says the request was recorded and whether process
groups were signalled; it never says fully stopped until `stoppedAt` exists. `runs list/show` text
and JSON plus existing authenticated GET readers expose the additive lifecycle consistently; no new
mutation endpoint appears. The blocked-backend result is discarded, handler count remains zero,
task/run become durably cancelled only after observation/stop, success cannot overwrite them, and
audit contains one bounded request while trace contains observed/stopped evidence without secrets.
The approval variant denies/no-ops atomically and never runs its handler. The already-running-handler variant
finishes one complete assistant/tool unit, starts no subsequent side effect, and ends cancelled.
Queued cancellation runs no dispatch body. Repeated cancel is byte-stable/idempotent. Public docs
state that already-running HTTP/tool work cannot be forcibly interrupted and may finish before its
result is discarded or the run is fully stopped.

**Validation:** run the whole-path oracle repeatedly with unique `DOCKET_HOME`, temp root, and
loopback port; focused run/dispatch/loop/approval/CLI/serve tests; CLI text/JSON and golden parity;
documentation command/link scans; Ruff/format, strict mypy, all four owning specs, runtime artifact
boundary, full pytest, metrics, and deterministic smoke. The integrator then updates central
rollups and unblocks C11 only if C0-C10 acceptance is complete.

**Dependency / contention:** blocked on C10b and serial with all run/dispatch/CLI cancellation work.
It owns final public truth but not central rollups. It cannot run in parallel with C11; C11 consumes
its accepted wording and remains last.

**Shipped evidence:** the cross-process production-driver oracle invokes `python -m docket runs
cancel` against the executor's shared Docket home, proves the running request stays nonterminal,
discards the late backend response before tool dispatch, persists the task/run as `cancelled`, and
records one audit plus one observed/one stopped trace edge. Typed `run_cancelled` now wins dispatch
and parallel reconciliation; returned cancelled tasks terminalize their run; CLI text, raw JSON,
and authenticated GET readers expose the same lifecycle. The oracle passes three independent
repetitions. Focused cancellation/dispatch/CLI/serve tests, the 2,436-test suite with five
contract-labelled skips, Ruff/format, strict mypy over 74 source files, 24 specs, runtime artifact
boundary, 18 goldens, synchronized metrics, and deterministic smoke all pass.

### W26-C11 — reconcile public claims and close the wave

**Status:** DONE (2026-08-31) · **Size:** M ·
**Owner:** @codex (integrator)

**Explicit trigger:** the audit found stale/default-branch architecture, quickstart/provider drift,
`docket add --from` examples, no-op `DEBUG=1` guidance, invalid Homebrew claims, overbroad runtime
package language, and cancellation wording stronger than behavior.

**Goal:** regenerate the public truth from merged behavior and make one ten-minute route from the
release artifact to first governed turn, plus one minimal runtime embedding example, match the
tested contracts byte-for-byte where applicable.

**Non-goals:** no marketing superlatives, broad “framework-neutral” claim before Wave 28, test-count
guess, feature implementation, dashboard, hosted/SaaS promise, or suppression of known limits.

**Live path / files:** merged specs and CLI/package artifacts → README, quickstart, model-gateway,
compatibility, security, examples, command reference, formula/install instructions,
`specs/README.md`, ROADMAP/TODO status, and metrics. Central files are integrator-owned.

**RED evidence:** run every documented command in an isolated fixture and check links/package names;
the current quickstart/provider/install examples fail or disagree. Scan for old architecture,
mutable install URLs, `docket add --from`, unsupported debug flags, “kills in-flight” wording, and
framework-neutral claims without two adapters.

**Acceptance:** clean artifact installation and first-turn docs are executable in CI; runtime
embedding example imports the C5 facade from an artifact; every known limit is explicit; metrics are
regenerated from the real suite; public/default release source matches C0; spec status/version/
changelog rows match shipped behavior. Run documentation examples/link checks, metrics check,
ShellCheck, full pytest/static/golden/spec/packaging/smoke gates, and one final clean status/diff
ownership audit before closing Wave 26.

**Contention:** integrator-only and last. Worker branches report evidence but never edit these
rollups. External publication and branch/default changes still require separate maintainer approval.

**Shipped evidence:** RED commit `dcce5b2` defines executable public-release truth for immutable
installation, supported provider setup, the governed first turn, artifact-only runtime embedding,
known limits, and stale-claim rejection. GREEN commit `f9a4086` makes the landing page, quickstart,
provider, command, compatibility, security, installation, example, and spec-index surfaces agree
with the shipped CLI and packages. The isolated ten-minute route and runtime example pass from built
artifacts without checkout imports. The full 2,451-test collection has 2,446 passes and five
contract-labelled skips; Ruff, format, strict mypy over 74 source files, ShellCheck, 24 specs, 18
goldens, synchronized metrics, dependency-floor artifacts, deterministic smoke, and the exact-wheel
release journey pass.

---

## ☑ WAVE 27 COMPLETE (2026-09-01) — dependency safety and public front door

**Integration state:** COMPLETE. W27-C1 closes the only live dependency alert and W27-C2 closes the
explicit public-front-door request. No other Phase 23 deferred item was promoted by this triage.

### W27-C1 — remediate the open high-severity optional-dependency alert

**Status:** DONE (2026-09-01) · **Size:** S · **Owner:** @codex

**Measured trigger:** GitHub Dependabot alert 1 reports CVE-2026-69247 / GHSA-g6cj-pr64-35w5 in
`cryptography` 49.0.0 from `uv.lock`; the patched release is 50.0.0. `uv tree` traces it through
the optional `mcp` extra's `pyjwt[crypto]` dependency. Repository search finds no Docket-owned
PKCS#7 EnvelopedData decryption caller, so direct exploitability is not claimed, but the vulnerable
artifact remains in the supported all-extras development/install graph.

**Goal:** resolve the supported dependency graph to `cryptography>=50.0.0`, retain the optional MCP
surface, and make the alert's exact vulnerable range absent from the committed lock.

**Non-goals:** no security marketing claim, MCP SDK upgrade unless resolution requires it, direct
`cryptography` dependency, CVE reproduction, speculative PKCS#7 code, or dismissal of the alert
without a patched artifact.

**Live path / ownership:** `pyproject.toml` optional `mcp` extra → MCP SDK → `pyjwt[crypto]` →
`cryptography`; own `uv.lock` and only change `pyproject.toml` if the resolver proves an explicit
constraint is necessary. Existing MCP import/optional-dependency tests are the behavior oracle.

**RED evidence:** assert the locked `cryptography` version is outside Dependabot's vulnerable
`>=44,<50` range and that `uv tree` still resolves the MCP extra; the committed 49.0.0 lock fails.

**Acceptance:** lock contains a patched version; the optional MCP import/absence contracts pass;
`uv sync --all-extras --dev --locked` succeeds; focused MCP tests and the packaging/dependency
gates pass; `git diff --check` is clean. Confirm the external alert closes after the exact commit
reaches `main`, without weakening the alert or excluding the extra.

**Contention:** lockfile-only card. It does not edit README, docs, assets, renderers, roadmap, or
spec indexes outside the integrator rollup.

**Shipped evidence:** commit `a78d342` upgrades the supported optional MCP graph from
`cryptography` 49.0.0 to 50.0.1 and adds the advisory-range regression assertion to the existing MCP
optional-surface smoke without changing the 2,451-test count. `uv sync --all-extras --dev --locked`
and all focused MCP suites pass. Exact-SHA CI run 33469380331 passes blocking Python, dependency
floors, ShellCheck/specs, 18 goldens, and both Ubuntu/macOS release journeys. GitHub marks Dependabot
alert 1 fixed at 2026-09-01T04:20:01Z; it was not dismissed or excluded.

### W27-C2 — rebuild the public README and reproducible visual evidence

**Status:** DONE (2026-09-01) · **Size:** M · **Owner:** @codex

**Explicit trigger:** the maintainer requested a public-repo README/content/visual rewrite on
2026-09-01. The bounded audit measures 773 lines / 6,873 words in `README.md`, deep API/poller prose
before contributor guidance, a stale Phase 22 “What's next”, a stale cost screenshot, two unused
OpenClaw-era images, and six manually maintained screenshots with no reproducible capture path.

**Goal:** make the repository front door answer, in order: what Docket is, why governance matters,
what is shipped, how to install and reach the first governed turn, what evidence/limits exist, and
where operators/integrators/contributors go next. Replace the visual set with a small, current,
anonymized, reproducible set derived from real CLI contracts.

**Non-goals:** no product capability, framework-neutral claim, hosted/SaaS promise, dashboard,
competitive superlative, invented benchmark, hidden limitation, generated product UI, or duplicate
command/API reference. Do not keep an image merely because it already exists.

**Live path / ownership:** `README.md`, `docs/README.md`, `docs/assets/*`, the asset renderer, its
dev-only Pillow dependency/lock, and only adjacent public-doc copy/link changes required by those
surfaces. `docs/commands.md` keeps complete command detail; `ROADMAP.md` keeps future work;
SECURITY/COMPATIBILITY keep deep limits.

**RED evidence:** public-doc tests plus an asset-manifest check must reject stale brands/commands,
unreferenced assets, non-reproducible screenshots, missing alt text, and README sections that repeat
the command reference or historical roadmap instead of linking to their owners.

**Acceptance:** README is materially shorter and has one primary install-to-first-turn route, a
scannable shipped-feature map, explicit best-practice and known-limit sections, and clear operator/
integrator/contributor links. Every retained PNG/GIF is regenerated by one documented script from
current anonymized command contracts; every asset is referenced and has useful alt text; stale and
unused assets are removed. Public links/claims, positioning, metrics, artifact journey, docs/assets
generation, formatting, specs, goldens, and full pytest gates pass.

**Contention:** owns the public front door and visual renderer after C1 closes. It does not change
runtime behavior, CLI output, release workflows, specs, or runtime dependencies. Pillow is an
explicit development-only renderer dependency, recorded in `pyproject.toml` and `uv.lock`.

**Shipped evidence:** commit `d9e914a` reduces the root README from 773 lines / 6,873 words to 280
lines / 1,858 words, moves deep command and roadmap detail to its owning documents, and presents one
install-to-governed-turn route, a feature map, best practices, honest limits, and contributor paths.
Seven stale/manual PNGs and the one-off hero renderer are replaced by three referenced, anonymized
terminal assets generated and render-contract-checked by one script. The RED public-front-door
contract and the migrated dead-file guard pass. Closure collects 2,452 tests (2,447 passed, five
contract-labelled skips); Ruff/format, strict mypy over 74 source files, ShellCheck, 24 specs, 18
goldens, synchronized metrics, locked all-extras sync, deterministic smoke, and the exact-wheel
release journey pass.

**Commit-level closure:** the first rollup run exposed two false portability assumptions in the new
test: runtime dependency floors intentionally omit dev-only Pillow, and host PNG/font rasterization
is not byte/pixel stable. Commits `fc07656` and `07e32c9` keep Pillow dev-only, vendor one licensed
font, and embed a SHA-256 render contract covering renderer/font/golden/smoke sources plus structural
animation checks. Exact-SHA CI run 33471779283 passes blocking Python, dependency floors,
ShellCheck/specs, 18 goldens, and both Ubuntu/macOS artifact-installed release journeys. The
advisory macOS full suite contains only its four pre-existing portability failures; no public-doc or
asset check fails.

---

## ☑ WAVE 28 COMPLETE (2026-09-02) — portable governance proof

**Activation evidence (2026-09-01):** the bounded selection pass inspected the artifact-installed
`docket-runtime` facade, its owning spec/tests, D-25/D-27, and the current upstream extension and
test seams. The facade currently gates one tool call but does not own external-run token/tool-call
budgets, emit the loop's paired `tool_call`/`tool_result` trace records, or produce the typed handoff
contract. Those are measured gaps, so the wave begins with one shared envelope rather than two
adapter-specific imitations.

| Candidate | Triage disposition | Decisive reason |
| --- | --- | --- |
| OpenHands standard SDK `Agent` | **selected coding runtime** | accepts an explicit tool list and custom Action/Observation/Executor definitions; the fixture can assert that no default, MCP, plugin, bash, or file-editor tool exists |
| OpenHands `ACPAgent` | **rejected for Wave 28** | the ACP server owns its tools, context window, approvals, and execution; launching it would be delegation, not Docket enforcement |
| PydanticAI | **selected general framework** | a custom `AbstractToolset` owns tool enumeration and `call_tool`, `RunContext` exposes provider-reported usage, and `FunctionModel` makes the proof deterministic without credentials |
| LangGraph | not selected | `StateGraph`/`ToolNode` can run supplied tools, but adds a second graph language and no stronger enforcement evidence for this bounded fixture |
| Agno | not selected | explicit tools and tool hooks are feasible, but hook middleware plus default concurrent async tool execution creates more interception/concurrency surface than the selected custom-toolset seam |

**Shared fixture oracle:** both adapters consume the same immutable scenario table and a fresh
workspace containing `state.txt`. Only a Docket-registered read tool and a Docket-registered
mutation/exec tool may reach that path. The scripted model sequence proves: exact advertised tool
names; unknown native bash/file-edit bypass refusal; allow; policy deny; approval deny with a
byte-identical workspace; approval grant with exactly one mutation; provider-reported usage crossing
the Docket budget before a requested mutation; paired trace records sharing the execution identity;
the existing hash-chained audit semantics for non-allow decisions; and one typed handoff with the
final summary. Run every scenario from a built `docket-runtime` artifact outside the checkout with a
unique `DOCKET_HOME`, temp root, cache, and loopback port. No hosted API key, Anthropic credential,
Codex/Claude subscription, network model, Docker container, A2A transport, or OTLP collector is a
closure prerequisite. An operator's local OpenAI-compatible endpoint on port 8081 may be an opt-in
canary only after the deterministic oracle passes; it cannot replace or block CI evidence.

### W28-C1 — define the shared governed-execution envelope

**Status:** DONE (2026-09-01) · **Size:** M · **Owner:** @codex

**Measured trigger:** the published facade exposes `Runtime.register` and `Runtime.dispatch`; the
private Docket loop, not that facade, currently owns cumulative reported-token/tool-call limits,
paired action traces, atomic assistant/tool history, and terminal results. Two adapters built
directly on `dispatch` would therefore share policy/approval but silently diverge on the other
D-27 semantics. The facade's approval stub also patches one module-global function, so concurrent
embedding calls with different stubs need a deterministic isolation oracle before adapters can call
the seam safely.

**Goal:** add the smallest synchronous, per-execution public envelope needed by both selected
callers. It must accept framework-reported usage before any corresponding tool request is
dispatched, enforce a finite cumulative token budget and tool-call budget, route the call through
the existing `Runtime.dispatch`/private `dispatch_tool` path, emit the same redacted paired action
trace shape under one caller-supplied identity, and terminalize once into a typed result/handoff.

**Non-goals:** no public agent loop, model/provider client, conversation store, graph, scheduler,
streaming API, async runtime, plugin discovery/registry, dynamic package loading, framework base
class, remote task protocol, A2A, OTLP, new audit format, new policy language, persistence migration,
or direct handler escape hatch. Do not expose the private copied `docket` namespace. Do not claim
that arbitrary foreign native tools are governable.

**Read first (bounded):** D-27, D-28, D-32, D-33; `specs/api/runtime-library.spec.md`; the public
facade and build hook; `core/tools.py::dispatch_tool`; the loop's budget decision plus
`_trace_tool_call`/`_trace_tool_result`; `TokenUsage`, `HandoffArtifact`, and the existing runtime
artifact boundary test. Do not load other runtime/framework docs or the full agent-loop spec.

**Live path / ownership:** own `packages/docket-runtime/src/docket_runtime/__init__.py`, additive
public facade modules under that package, `packages/docket-runtime/pyproject.toml`, the runtime build
hook only if a new facade module is not already included, `specs/api/runtime-library.spec.md`, and
new focused envelope/artifact tests. Own two isolated fixture dependency projects/locks up front so
C2 and C3 never contend on root `pyproject.toml`, root `uv.lock`, or runtime package metadata. The
base `docket-runtime` install must remain only Pydantic + filelock; framework SDKs are optional,
adapter-specific dependencies. Preserve Python 3.11 base support; the OpenHands fixture may require
Python 3.12 and must say so explicitly.

**RED tests (commit before production):** from a built wheel and rebuilt sdist outside the source
tree, prove the current facade fails each missing contract:

1. a model response reports usage over the configured Docket budget and requests a mutation; the
   handler must not run and the envelope must terminalize with a typed budget stop;
2. a second requested tool would exceed the tool-call budget; the entire not-yet-started call is
   refused without incrementing executed count;
3. one allowed, one policy-denied, one approval-denied, and one approval-granted call each produce
   exactly one redacted `tool_call` and one `tool_result` sharing project/session/call identity;
4. malformed/unknown calls remain fail-closed through `dispatch_tool`, not adapter validation;
5. `finish` produces the public typed handoff/result once; dispatch, usage, or a second finish after
   terminal state is rejected without another write;
6. two concurrent runtimes with opposite approval stubs cannot answer each other's token or execute
   the wrong handler; repeat behind a barrier to make the current global-patch race observable;
7. wheel and sdist exports are identical, the CLI distribution stays disjoint, base floors remain
   Pydantic + filelock, and no private namespace becomes public.

**Smallest production contract:** choose names in the spec/RED commit, but keep the semantic surface
to one immutable limits/usage shape, one execution object created by `Runtime`, one `dispatch`
method, and one terminal result carrying usage, stop reason, tool count, and `HandoffArtifact`.
Usage is provider-reported and must remain labelled as such; no byte/token estimate may be promoted
to measured usage. Serialize or otherwise isolate the approval-stub seam without creating a second
approval implementation. Reuse the existing trace/audit writers and `dispatch_tool`; do not copy
their decisions into the facade.

**Acceptance / gates:** planted bypasses prove direct handler invocation and unreported tool-bearing
responses fail; all RED cases turn green; exact public exports and schema version/changelog are
recorded; base and optional dependency resolution are reproducible; focused runtime, policy,
approval, audit, trace, packaging, and concurrency tests pass; then Ruff/format, strict mypy,
runtime artifact floors, full pytest, 18 goldens, 24 specs, metrics, deterministic smoke, and
`git diff --check` pass. Report separate Python 3.11 base-artifact and Python 3.12 OpenHands-fixture
environment evidence.

**Dependency / contention / handoff:** this is the only ready card and blocks C2/C3. It owns every
shared public type, fixture scenario schema, dependency lock, and package metadata edit. Handoff only
the exported contract, scenario fixture API, exact focused commands, RED commit, GREEN commit, and
unresolved risks—never raw framework docs/logs. After integration, C2 and C3 may run simultaneously
in isolated worktrees because they own disjoint adapter modules and tests.

**Shipped evidence:** RED commit `9f6a79c` pins seven artifact-installed lifecycle, budget, trace,
handoff, packaging, malformed-call, and concurrent approval-stub cases. GREEN commit `d2e1b33`
ships the public `0.3.0` governed envelope while retaining `dispatch_tool` as the sole execution
chokepoint; all seven cases pass from wheel and rebuilt sdist. Commit `2e37361` freezes the shared
seven-scenario oracle and disjoint adapter environments: OpenHands SDK `1.44.1` on Python 3.12 and
PydanticAI `2.37.0` on Python 3.11, with exact independent locks and unchanged runtime base
dependencies. Closure passes 2,457 tests with five contract-labelled skips, 13 focused runtime and
fixture cases, Ruff/format, strict mypy, 24 specs, 18 goldens, synchronized metrics, both frozen
dependency resolutions, the deterministic smoke, and `git diff --check`. C2 and C3 may now be
claimed independently; C4 still waits on both adapters.

### W28-C2 — prove the OpenHands SDK coding-runtime adapter

**Status:** DONE (2026-09-01) · **Size:** M · **Owner:** @codex

**Measured trigger:** the standard OpenHands SDK agent supports an explicit tool list and custom
typed tool definitions, while `ACPAgent` explicitly delegates tools/execution to its subprocess.
The coding proof is therefore feasible only with the standard SDK and only if its resolved tool map
contains Docket adapter tools and nothing capable of native mutation/exec.

**Goal:** ship a narrow OpenHands adapter that translates Docket tool specs to OpenHands
Action/Observation/Executor definitions, reports each completed model response's measured usage to
the C1 envelope before executing its requested action, converts the action to Docket `ToolCall`, and
returns the Docket result to the OpenHands conversation. Produce the shared typed terminal handoff
from the conversation result.

**Non-goals:** no ACP support, OpenHands CLI/UI/Cloud/agent-server integration, OpenHands default
tools, `openhands-tools`, Docker/remote workspace, MCP, plugins, public skill loading, OpenHands
security-policy substitution, provider credential, browser, shell/file executor outside Docket,
adapter auto-discovery, or changes to C1's public types. Do not treat OpenHands confirmation or
metrics as a replacement for Docket approval/budget/audit.

**Read first (bounded):** the extracted C2 card and D-27/D-32/D-33; C1's facade spec and handoff;
the pinned OpenHands SDK version's `Agent`, ToolDefinition/Action/Observation/Executor, conversation
event, and LLM metrics APIs; only the shared fixture scenario and C2 test. Do not read ACP internals,
OpenHands app/server code, other candidate frameworks, or central rollups.

**Live path / ownership:** additive `docket_runtime.adapters.openhands` module/package, its focused
tests, and its isolated Python 3.12 fixture project. Do not edit the common facade, shared scenario,
runtime/root package metadata or locks, runtime-library spec, ROADMAP/TODO/README/spec index, or the
PydanticAI adapter. If the pinned SDK cannot expose response usage before action execution, stop and
return that exact incompatibility rather than weakening the budget oracle.

**RED fixture:** run a loopback OpenAI-compatible scripted server on a unique ephemeral port. It
returns fixed usage counts and deterministic tool calls; no real key/network is used. Instantiate
the standard Agent with explicit Docket tools, `include_default_tools=[]`, empty MCP config, and no
plugins/public skills. Assert its resolved tool map equals the adapter-provided names. Script the
shared allow/deny/approval/budget/handoff cases, plus prompts that request known OpenHands bash and
file-editor tool names; those names must be absent and the workspace must remain byte-identical.

**Acceptance:** all mutations/execs observed by the fixture pass through the C1 envelope and sole
`dispatch_tool` chokepoint; Docket's deliberately lower token limit wins before a tool on an
over-budget OpenHands response; approval deny/grant and policy deny match the common oracle; trace,
audit, call ids, usage, and handoff preserve one execution identity; exact tool registration is
asserted behaviorally; repeated runs use fresh home/workspace/cache/port and leave no process; wheel
and rebuilt-sdist installs work outside checkout. The local endpoint at 8081 is optional and
non-blocking, and any result is labelled a canary rather than closure evidence.

**Validation / handoff:** run focused adapter + common conformance + artifact tests on Python 3.12,
then the card-scoped lint/type/spec checks. C4, not this worker, runs central/full closure. Handoff
the exact upstream version, Python constraint, files changed, tests, process-cleanup proof, and any
unsupported OpenHands shape. Never edit central board/docs/metrics. This card can run in parallel
with C3 after C1 because their modules, test files, fixture environments, caches, and ports are
disjoint.

**Shipped evidence:** RED commit `071a744` pins the credential-free loopback, exclusive tool map,
seven shared governance scenarios, wheel, and rebuilt-sdist contract for OpenHands SDK `1.44.1` on
Python 3.12. GREEN commits `c7d6a59` and `fbb4084` ship the standard synchronous Agent adapter:
reported response usage reaches the C1 envelope before any admitted action, only Docket-backed
tools resolve, over-budget calls terminalize before execution, and results return through a
concrete Observation and typed handoff. All nine C2 artifact cases pass; shared C1/fixture/package
checks pass as part of the 13-case cross-card group; Ruff/format, pinned-SDK strict mypy, and all 24
spec validations pass. Commit `be61ab1` corrects the card-owned trace oracle to assert broad
`decision="deny"` separately from typed `denialKind`. No hosted key, subscription, port-8081
canary, ACP, default/MCP/plugin/native mutation tool, or new runtime dependency is closure evidence.

### W28-C3 — prove the PydanticAI general-framework adapter

**Status:** DONE (2026-09-01) · **Size:** M · **Owner:** @codex-c3

**Measured trigger:** PydanticAI provides a custom `AbstractToolset` with direct ownership of
`get_tools`/`call_tool`, per-run provider-reported usage in `RunContext`, sequential toolset mode,
and procedural `FunctionModel`. That is a smaller deterministic enforcement seam than a second
graph DSL or general hook middleware.

**Goal:** ship a narrow PydanticAI toolset adapter that enumerates only Docket tools, reports the
current response usage to C1 before its requested call, converts the call to Docket `ToolCall`, and
maps the Docket result back through `call_tool`. Produce the same terminal result/handoff as C2.

**Non-goals:** no provider SDK/key, MCP/native/provider-executed tools, LangGraph/Agno bridge,
PydanticAI capability bundle, Logfire/OTLP, durable-execution backend, UI/streaming, parallel tool
execution, retry-policy rewrite, framework usage limits as the governing boundary, or changes to
C1/C2 files. PydanticAI may retain a looser safety limit, but the fixture must prove Docket's lower
budget is the decision that prevents execution.

**Read first (bounded):** the extracted C3 card and D-27/D-32/D-33; C1's facade spec and handoff;
the pinned PydanticAI version's `AbstractToolset`, `FunctionToolset` schemas, `RunContext.usage`,
`FunctionModel`, and `UsageLimits`; only the shared fixture and C3 test. Do not load graph/durable/UI
documentation, other candidate frameworks, or central rollups.

**Live path / ownership:** additive `docket_runtime.adapters.pydantic_ai` module/package, its
focused tests, and its isolated Python 3.11 fixture project. Do not edit common facade/scenario,
package metadata/locks, runtime-library spec, ROADMAP/TODO/README/spec index, or OpenHands files.

**RED fixture:** use `FunctionModel` to emit deterministic responses, tool call ids/arguments, and
reported usage without HTTP or credentials. Build one sequential custom toolset containing exactly
the Docket adapter tools; provider-native and run-time-added toolsets are absent. Give PydanticAI a
limit above the fixture response and C1 a lower limit, then prove the Docket boundary refuses the
requested mutation before `call_tool` reaches its handler. Run every shared allow/deny/approval/
trace/audit/handoff scenario and a native/unknown-tool bypass probe.

**Acceptance:** exact tool enumeration and call mapping are typed and deterministic; the shared
workspace outcomes, budget stop, paired traces, audit decisions, usage totals, and handoff are
byte/field equivalent to the common oracle; no adapter path invokes a handler directly; sequential
execution avoids hidden parallel dispatch; wheel and rebuilt-sdist installs work outside checkout;
Python 3.11 base compatibility remains green; no PydanticAI dependency enters the base runtime
install.

**Validation / handoff:** run focused adapter + common conformance + artifact tests on Python 3.11,
then card-scoped lint/type/spec checks. C4 owns full closure. Handoff exact upstream version, files,
tests, and any limitation in the toolset/usage seam. Never edit central board/docs/metrics. This
card is parallel-safe with C2 after C1; its environment must not share home/cache/ports even though
its deterministic model needs no socket.

**Shipped evidence:** RED commit `648dec5` pins the credential-free `FunctionModel`, exact
sequential tool enumeration, shared governance scenarios, native/unknown bypass probes, wheel, and
rebuilt-sdist contract for PydanticAI `2.37.0` on Python 3.11. GREEN commit `a6c9197` ships one
custom `DocketToolset`: cumulative `RunContext` usage is converted to per-response deltas before
the corresponding call is admitted, exact ids/names/arguments dispatch only through C1, and
`finish()` returns the shared typed terminal. All seven C3 artifact cases pass; the same 13 shared
C1/fixture/package checks, Ruff/format, pinned-environment strict mypy, and all 24 specs pass. Base
Python 3.11 compatibility and the runtime's two existing dependencies remain unchanged; provider
SDKs/keys, native or runtime-added toolsets, parallel execution, and telemetry are outside this
configuration-scoped proof.

### W28-C4 — reconcile cross-adapter parity and close Wave 28

**Status:** DONE (2026-09-02) · **Size:** M · **Owner:** @codex (integrator)

**Explicit trigger:** two focused adapters are not a portable-governance claim until their merged,
artifact-installed behavior passes the same oracle and public wording names the exact supported
configurations and limits.

**Goal:** integrate C2/C3, run the shared scenario as a single cross-adapter matrix, prove the
execution-envelope contract is identical, and update public/spec/roadmap truth narrowly. Decide from
captured trace evidence whether JSONL preserves identity and whether any remote task protocol was
actually used; add neither OTLP nor A2A when the answer remains yes/no respectively.

**Non-goals:** no third adapter, generic framework-neutral/plugin claim, benchmark ranking, live
provider requirement, default tool enablement, package publication, hosted service, broad README
rewrite, new metrics subsystem, or Wave 29 benchmark/adoption work.

**Read first (bounded):** C1-C3 delta handoffs and commits; D-25/D-27/D-32/D-33; merged common
conformance tests; runtime-library spec and only the public integration/compatibility/security
sections that need truth updates. Do not reopen candidate research unless merged evidence
contradicts the selection.

**Integration / ownership:** central files only after adapter commits merge: common conformance
matrix, `specs/api/runtime-library.spec.md` final status/version/changelog, `specs/README.md`, a
compact adapter example/index, relevant README/compatibility/security links/limits, ROADMAP/TODO
rollups, and metrics. Resolve no worker conflict by dropping either contract; rerun the losing
scenario first. Remove fixture processes/caches/temp artifacts, but do not delete user state or
global package caches.

**Closure oracle:** build wheel + sdist once, install each with one adapter fixture outside checkout,
and run the same scenario table repeatedly. Assert framework-specific events normalize to identical
Docket outcomes for every action, byte-identical no-mutation cases, exactly-once approved mutation,
provider-reported cumulative usage, tool-call count, stop reason, paired trace payload fields,
hash-chain verification, and typed handoff. Assert OpenHands native tools and PydanticAI native/
additional toolsets are absent. Scan public prose to reject bare “framework-neutral,” ACP-governed,
all-OpenHands, all-PydanticAI, subscription-required, A2A, or OTLP claims.

**Closure gates:** focused cross-adapter repetitions; Python 3.11 base/Pydantic and Python 3.12
OpenHands artifact environments; optional-dependency absence/error tests; runtime floors and
disjoint wheel ownership; Ruff/format, strict mypy, full pytest, 18 goldens, all specs, ShellCheck,
metrics check, deterministic smoke, public-doc/link/example checks, `git diff --check`, privacy
scan, clean worktree, and canonical commit-level rerun. External publication remains separately
approval-gated.

**Required closeout truth:** claim only that Docket governs the tested standard OpenHands SDK and
PydanticAI configurations when their relevant tools are exclusively Docket-backed. State that ACP,
native/provider tools, plugins/MCP added beside the adapter, and arbitrary framework configurations
are outside the proof. Record why A2A/OTLP stayed absent. Close Wave 28 only after both adapters and
the shared installed-artifact matrix pass; Wave 29 then becomes eligible for its own bounded
activation pass, not automatically active.

**Shipped evidence:** RED `3294f58`, typed terminal-usage bridge `b1c9f44`, and scoped public truth
`739b1ca` close the merged proof. The six-module installed-artifact group passes 37 tests, including
the repeated eight-case cross-adapter matrix; the full suite passes 2,485 tests with five
contract-labelled skips (2,490 collected). Ruff, format, root and pinned-adapter strict mypy, all 24
specs, 18 goldens, ShellCheck, metrics, reproducible public assets, deterministic smoke, public
documentation/example checks, diff hygiene, and the Wave 28 privacy scan pass. Exact implementation
SHA `739b1ca70dc2` passes the blocking Python and dependency-floor jobs plus artifact-installed
release journeys on both Ubuntu and macOS in GitHub Actions run `33652365412`. The evidence supports
only standard OpenHands SDK Agent `1.44.1` and PydanticAI `2.37.0` configurations whose relevant
tools are exclusively Docket-backed. ACP, native/provider tools, adjacent plugins/MCP, and arbitrary
framework configurations remain outside the claim. A2A remains absent because both selected paths
are in-process; OTLP remains absent because paired JSONL trace identity stayed sufficient. No hosted
credential, subscription, port-8081 canary, or external publication was required. Wave 29 is merely
eligible for bounded triage and is not active.

---

## ☑ WAVE 24 COMPLETE (2026-08-19) — realistic local-model evaluation

### W24-C1 — memory-backed maintenance canary

**Status:** DONE (2026-08-19) · **Size:** M · **Owner:** @codex

**Measured trigger:** W23's real local-model canary completed the production workflow and exposed a
startup-context defect, but its task is still an exact one-line file creation. The current harness
never invokes `docket maintain <lead> distill`, never checks whether a superseding decision survives
into `MEMORY.md`, and never requires the Lead to carry a private durable fact through a typed handoff
so an Implementer can repair real code. Infrastructure is proven; memory-assisted product work is
not.

**Goal:** make the default live-local scenario repair a small but non-trivial Python checkout bug
using durable project decisions that exist only in the Lead's dated memory logs. Cross the public
distillation CLI, real runtime/model turn, fresh system-context injection, pipeline handoffs, tool
path, review, approval, test, observability, and hidden behavioral acceptance in one preserved world.

**Non-goals:** no scripted live replies, exact prose/request/turn-count assertions, model-specific
prompt branch, artificial subprocess/pipeline timeout, reduced retry/backoff, raised product limit,
remote endpoint, credential, benchmark score, broad eval framework, or mutation of the operator's
real Docket home. The deterministic basic smoke remains the blocking CI composition proof.

**Live path / files:** `scripts/smoke_workflow.py` owns scenario fixtures/orchestration/evidence;
public `docket maintain smoke-lead distill` reaches `cli/_agents.py::_run_distillation` →
`core.memory.distill_memory` → `DocketDriver.run_turn`; `core.identity.system_prompt_for_agent`
injects the resulting MEMORY; `core.dispatch._hop_message` carries the Lead artifact to the
Implementer. `tests/python/test_workflow_smoke.py` and `specs/test-framework.md` own acceptance.

**RED test:** the opt-in live subprocess selects `memory-maintenance`, expects archived daily logs,
current-decision evidence, a memory-bearing Lead handoff, and passing hidden checkout behavior. It
fails before the scenario flag and fixtures exist; ordinary pytest remains hermetic and skipped.

**Acceptance:** `--live-model` defaults to the memory-maintenance scenario while `--scenario basic`
keeps the W23 live task available. The scenario seeds two dated logs where the newer tenant decision
explicitly supersedes the older one, distills them through the public CLI with genuine inference,
and verifies source logs were archived and the current invariant survived in MEMORY. The delegated
task refers to durable decisions without copying their values; the Lead artifact must carry the
current tenant/integer-rounding constraints, and the Implementer must repair a real Python module.
The module must begin with a failing regression suite that defines the rounding edge and required
metadata key without exposing the private tenant value; that suite plus an acceptance check outside
project-tool roots must pass, including rejection of the superseded tenant. The canary must also
prove that the untouched fixture starts red for exactly those two seeded defects, commit it as a
real Git repository before provisioning, and validate the Implementer's effective worktree rather
than the unchanged origin checkout. An un-scripted policy-gated `bash` request must be
granted through the real CLI in the isolated canary home rather than by disabling the policy or
waiting for a timeout; the pipeline's own approval remains a separate asserted pause. All normal
production guardrails remain intact.
Focused/default/full gates and an actual port-8081 run must pass; docs must explain both scenarios.

**Contention:** this card owns the smoke script/test/spec/docs and the mutable local inference
endpoint. No parallel lane may run the same live canary or edit memory/context composition while its
evidence is being collected.

**Shipped evidence:** the preserved Git-backed run at `/tmp/docket-live-memory-w24-k` began with
exactly two failing regressions, distilled three logs, carried the current exact formula/tenant
through the Lead artifact, repaired the Implementer worktree, passed four public regressions plus
hidden acceptance, received Reviewer APPROVE and Tester PASS, crossed real approval pause/resume,
verified five isolated histories, two run records and 31 chained audit lines, and attempted no
private-state tool access.

### W24-C2 — make private-state completion unambiguous and tool approvals decidable

**Status:** DONE (2026-08-19) · **Size:** S · **Owner:** @codex

**Measured trigger:** the first W24 run proved MEMORY → Lead handoff → correct code. With genuine
tool approvals enabled, the Implementer passed its tests but then tried to locate and rewrite its
private `HEARTBEAT.md` through `bash`, despite project `read/edit` correctly rejecting that root.
It continued redundant validations until the unchanged 100,000-token turn budget failed at 105,119.
The approval record exposed only “`cd` is not on the curated allowlist,” not the rendered command,
so an operator could not distinguish project validation from private-state access before granting.

**Goal:** make runtime-loaded private state explicitly read-only through every project tool,
including bash, and state that returning the completed task is sufficient because Docket owns task
durability. Include the redacted rendered tool call in an `ask` approval's action so a CLI/HTTP/
Telegram operator can decide what is actually being requested.

**Non-goals:** no new tool root, sandbox default change, command parser, silent truncation, higher
token/iteration limit, shorter approval timeout, model-specific branch, or bypass of the approval
store. This does not claim unsandboxed bash is a filesystem jail; opt-in isolation remains separate.

**Live path / files:** `core.identity._RUNTIME_CONTEXT_NOTE/_FOOTER` → every live turn;
`core.tools.dispatch_tool` → `approval_create` → CLI approval surfaces; focused tests in
`test_role_tools_and_identity.py` and `test_pre_tool_call_policy.py`; owning agent-loop and
security-gates specs. W24's operator monitor may grant only an inspectable project validation call.

**RED test:** runtime context must forbid all project tools (naming bash) from private state and say
a final task response completes durability; an approval created by the real dispatch chokepoint must
contain the redacted rendered call, not only the classifier reason. Both fail before the change.

**Acceptance:** no private control file is accessed by any tool in a fresh W24 run; safe validation
commands remain approvable through the public CLI with the call visible in the record; the agent
stops after implementation/validation under existing budgets; memory, hidden acceptance, gates,
history atomicity and observability all pass. Specs, focused/full suite, goldens and static gates pass.

**Contention:** owns `core/identity.py`, `core/tools.py`, their focused tests/specs and the W24
approval monitor. W24-C1 waits for its result; no parallel context/security lane is safe.

### W24-C3 — fail-closed exact memory and downstream worktree continuity

**Status:** DONE (2026-08-19) · **Size:** M · **Owner:** @codex

**Measured trigger:** a Git-backed canary caught the model silently changing the durable tax
divisor from `10_000` to `1_000`; a later run proved Implementer and its mechanical gate used the
repaired worktree while Tester correctly rejected the untouched origin checkout.

**Goal / shipped:** sparse `- [exact]` records now validate decision IDs and backtick literals
before any memory write/archive and are carried verbatim; malformed output leaves all logs
untouched. Dispatch passes the latest successful Implementer worktree as a bounded coordinate;
`DocketDriver` accepts it only from a registered same-pod Implementer, strips it from tool env, and
keeps Reviewer/Tester permissions unchanged. Focused tests and the final live canary pass.

**Non-goals:** no raw-log retention, semantic database, arbitrary root override, shared model
history, relaxed verdict parser, raised token/turn limit, scripted reply, or weaker role gate.

---

## ☑ WAVE 23 COMPLETE (2026-08-19) — real local-model workflow evidence

### W23-C1 — opt-in end-to-end canary against the local model

**Status:** DONE (2026-08-19) · **Size:** M · **Owner:** @codex

**Measured trigger:** the W22 smoke proves Docket's complete composition against a scripted
OpenAI-compatible loopback endpoint, but `scripts/smoke_workflow.py` always replaces the endpoint
and therefore cannot exercise the real model at `127.0.0.1:8081`. A read-only `/v1/models` probe on
2026-08-19 succeeded and reported one llama.cpp-hosted Qwen model with a 16,384-token context.

**Goal:** add an explicit live-local mode that discovers and registers the model served at the
operator-selected loopback endpoint, provisions every smoke role against it, and runs the same
observable tool/gate/approval/session/trace/audit workflow with genuine, un-scripted inference.

**Non-goals:** no paid/remote endpoint, stored credential, fake response in live mode, exact model
wording or request-count assertion, CI dependency on a running model, product guardrail removal,
load/quality benchmarking, or automatic mutation of the operator's real `DOCKET_HOME`.

**Live path / files:** `scripts/smoke_workflow.py` owns mode selection, endpoint discovery and the
temporary-world orchestration; public `models provider add` / `models set` configure the temporary
fleet; the existing CLI → `DocketDriver` → agent loop → tool/gate path remains unchanged.
`tests/python/test_workflow_smoke.py`, `specs/test-framework.md`, README and CONTRIBUTING own the
executable contract and operator instructions.

**RED test:** an opt-in environment test invokes `--live-model` and fails before the flag exists;
ordinary pytest continues to exercise only hermetic state and never contacts the operator endpoint.

**Acceptance:** `--live-model` defaults to `http://127.0.0.1:8081/v1`, accepts an explicit loopback
endpoint/model override, discovers the loaded model without embedding its host path, uses no API
key or scripted replies, and preserves normal product inference/tool budgets rather than tightening
them for the test. A real run creates the requested artifact through the `write` tool, crosses the
mechanical/verdict/approval gates, ends `done`, and verifies typed handoffs, step-isolated sessions,
atomic tool history, traces, audit and run records. The deterministic default smoke and all final
gates remain green; documentation clearly separates CI smoke from opt-in live evidence.

**Contention:** this card owns the smoke script/test/spec/docs. No parallel lane may use the same
local endpoint while the canary runs, because inference latency and server state are shared.

**Shipped:** `uv run python scripts/smoke_workflow.py --live-model` now discovers the model at
`127.0.0.1:8081`, configures only a temporary Docket home through public provider/model commands,
and runs the same five-hop workflow with genuine Qwen inference. It makes no exact wording/request
count assumptions and does not tighten Docket's normal production guardrails. Three preserved live
runs completed `SMOKE PASS`; the opt-in pytest wrapper also passed independently. The deterministic
default remains the blocking CI smoke, while `--endpoint`/`--model` support explicit loopback-only
overrides.

### W23-C2 — make required startup state reachable without widening tool roots

**Status:** DONE (2026-08-19) · **Size:** M · **Owner:** @codex

**Measured trigger:** the first real W23-C1 run passed, but a second independent run exhausted
`max_iterations=20` in the Lead. Its durable session shows repeated searches for
`HEARTBEAT.md`/`MEMORY.md` under the codebase. Docket's injected `WORKFLOW_AUTO.md` requires those
reads, while `core.identity.system_prompt_for_agent` injects only SOUL/WORKFLOW and
`DocketDriver._resolve_roots` correctly excludes the private agent workspace. The existing docs
claim AGENTS/TOOLS/HEARTBEAT/MEMORY are re-injected, so prose and the live wire disagree.

**Goal:** inject the current, relevant private-workspace control files into each turn's system
prompt, explicitly tell the model they are already loaded/read-only for project tools, and bound
that static context with the existing `CONTEXT_TOKEN_BUDGET` using visible truncation.

**Non-goals:** no second writable root, no ability for an Implementer to self-edit SOUL or policy
files, no higher iteration/token/tool limit, no model-specific prompt branch, no session-history
duplication, and no claim that project tools can maintain private memory files.

**Live path / files:** `core.identity.system_prompt_for_agent` →
`core.agent_loop.run_agent_turn`; `SOUL.md`, `WORKFLOW_AUTO.md`, `HEARTBEAT.md`, `AGENTS.md`,
optional `TOOLS.md`, and `MEMORY.md`; focused tests in `test_role_tools_and_identity.py` and
`test_workspace_root_agreement.py`; owning `agent-loop.spec.md`.

**RED test:** a real provisioned workspace's composed system prompt must contain current
HEARTBEAT/MEMORY/AGENTS state and the read-only runtime note; before implementation those strings
are absent. A deliberately oversized low-priority section must produce a visible omission marker.

**Acceptance:** the four control files are loaded fresh per turn, never persisted in session
history, and prioritized HEARTBEAT → AGENTS → TOOLS → MEMORY within the existing static
budget; any cut is explicit. Tool roots remain byte-for-byte unchanged. The preserved failed
canary proves the old loop, a new real canary completes, and focused/full validation stays green.

**Contention:** W23-C1 waits for this card because both need the same local endpoint and final live
evidence. No parallel context work may touch identity/loop composition or the mutable canary state.

**Shipped:** `system_prompt_for_agent` now reads HEARTBEAT/AGENTS/optional TOOLS/MEMORY fresh every
turn, appends them after mandatory SOUL/WORKFLOW in priority order, and fits them into the existing
static-context budget with a visible truncation marker. A final runtime handoff tells the model the
private state is already loaded and is not a project-tool path; tool roots are unchanged and the
system message remains absent from durable conversation history. The first repeated live canary
had failed at the Lead's existing `max_iterations=20`; after the fix the final run completed with
7 Lead turns and 18,395 input tokens versus 16 turns/45,639 tokens in the pre-footer run — about
60% less measured input, with no raised limit. Validation: opt-in live pytest passed; the ordinary
2,233-test suite completed with 5 expected environment/opt-in skips; 18 goldens, 24 specs, Ruff,
format, mypy and metrics all passed.

---

## ☑ WAVE 22 COMPLETE (2026-08-19) — observable full-workflow proof

### W22-C1 — executable end-to-end workflow smoke

**Status:** DONE (2026-08-19) · **Size:** M · **Owner:** @codex

**Measured trigger:** the 2,229-test suite covers provisioning, CLI routing, dispatch, approvals,
the HTTP model adapter, tools, sessions, traces, and run records in separate focused tests, but no
single executable test crosses the real CLI process boundary and proves those parts compose into a
completed task. The existing `pipeline run` CLI test replaces `DocketDriver` with `FakeDriver`, and
the HTTP-adapter tests stop below dispatch.

**Goal:** provide one hermetic, human-readable smoke command that provisions a full pod, queues a
task, plans and runs a custom pipeline against a deterministic local OpenAI-compatible endpoint,
executes a real tool call and mechanical check, pauses for and resumes after approval, passes
Reviewer/Tester verdict gates, and verifies durable task, session, trace, audit, and run state.

**Non-goals:** no paid/live endpoint, credentials, remote network, Docker/MCP/Telegram coverage, UI
automation, load testing, exhaustive failure cases, or replacement for focused tests.

**Live path / files:** `scripts/smoke_workflow.py`; `tests/python/test_workflow_smoke.py`; public
commands `add --from` → `pod delegate` → `pipeline plan/run --follow` → `approve` → resumed
`pipeline run`; `edges/adapters/llm.py` → `DocketDriver` → `core/agent_loop.py` →
`core/tools.py::dispatch_tool`; `TASK_LIST.json`, sessions, traces, audit, and run registry.

**RED test:** the focused pytest invokes the documented smoke command in an isolated directory and
must fail before the harness exists; after implementation it asserts the visible PASS summary and
the created artifact/state root.

**Acceptance:** one documented command runs without real credentials or non-loopback network;
subprocess CLI output exposes every stage; the fake endpoint receives real chat-completions payloads;
the Implementer writes an artifact through the gated tool chokepoint; the pipeline proves
`waiting_approval` → grant → exact-position resume → `done`; persisted hops contain typed artifacts
and verdicts; step-scoped sessions retain the tool-call/result atomically; trace/audit/run records
are queryable; focused pytest plus Ruff/format/mypy, full pytest, goldens, spec validation, and
metrics are green.

**Contention:** the harness/test/framework spec are card-owned. `TODO.md`, `ROADMAP.md`,
`specs/README.md`, and README metrics remain integrator roll-ups and are updated only at close.

**Shipped:** `uv run python scripts/smoke_workflow.py` now displays and asserts the complete
happy-path composition across real CLI subprocesses and the real OpenAI-compatible HTTP adapter,
using only a deterministic loopback model. It provisions `agentic-product`, delegates and plans,
runs Lead → Implementer (`write` tool + mechanical check) → Reviewer, pauses at a pipeline approval,
grants via CLI, resumes exactly at the gated step, runs release-check → Tester, and finishes `done`.
The harness then verifies five typed hop artifacts, five step-scoped sessions, atomic tool-call/result
persistence, measured usage, traces, a clean audit chain, and two successful run records. The pytest
suite contains a subprocess acceptance wrapper and README/CONTRIBUTING/test-framework document the
standalone command. Validation: 2,230 tests passed (4 expected environment skips), 18 goldens, 24
specs, Ruff, format, mypy for product + harness, and metrics all green.

---

## ☑ WAVE 21 COMPLETE (2026-08-19) — daemon-free truth pass

### W21-C1 — remove stale current-state OpenClaw contracts

**Status:** DONE (2026-08-19) · **Size:** M · **Owner:** @codex

**Measured trigger:** the post-W20 roadmap audit found no live runtime dependency, but current
acceptance stories, JSON/API specs, source comments, golden fixtures, and the board's own layer rule
still named the deleted daemon, its home directory, or its removed driver as if they were current.

**Goal:** make every current-state contract describe Docket's owned runtime, state root, fleet,
sessions, and protocol boundaries without presenting the retired daemon as a dependency or product
anchor.

**Non-goals:** no runtime behavior change, no deletion of explicit changelog/decision history, no
rename of Docket, and no removal of versioned neutral fields such as `gateway` where compatibility
requires them.

**Live path / files:** current sections of `ROADMAP.md`, `TODO.md`, `README.md`/`NOTICE`, owning
specs and acceptance stories, `src/docket/` comments/names, and the golden fixture root.

**Acceptance:** `src/docket/` has zero OpenClaw references; current examples use `~/.docket`;
normative JSON/API shapes match their live producers; remaining repository references are explicitly
historical; focused tests, Ruff/format/mypy, full pytest, golden parity, spec validation, and metrics
checks are green.

**Shipped:** product code and ordinary docs/tests now carry no retired-brand references; the golden
harness uses `$DOCKET_HOME`/`.docket`; live specs describe the Docket-owned driver, fleet, sessions,
audit, costs, cancellation, Telegram channel, overlays, and JSON shapes directly. A source-tree
guard prevents the coupling from returning. Explicit migration history remains only in
`CHANGELOG.md`, ROADMAP/TODO history, and older spec changelogs. Validation: 2,229 tests passed
(4 environment skips), 18 golden cases passed, 24 specs valid, Ruff/format/mypy green, and README
metrics synchronized.

---

## ☑ WAVE 20 COMPLETE (2026-08-19) — bounded development context and live-turn efficiency

The trigger is measured, not aspirational: a real 16k endpoint rejected the reviewer at 19,827
tokens while the live loop never called the already-built compactor; MCP output also bypassed the
operator's small-context ceiling. Separately, the repository had no Codex instruction/skill/hook
layer, so an agent had to rediscover these facts from multi-thousand-line planning files.

This wave keeps two boundaries explicit. Repository skills and hooks improve how contributors work;
they are not a claim that Docket itself has a product skill system. Product changes remain
spec-first and must prove the default live caller.

### W20-H1 — repository development harness

**Status:** DONE (2026-08-19) · **Size:** S · **Owner:** integrator

**Goal:** restore only bounded repository state after start/resume/compaction and load specialized
instructions on demand.

**Shipped:** a concise root `AGENTS.md`; three repo skills (`docket-roadmap`, `docket-spec-work`,
`docket-context-runtime`) with progressive references; a deterministic, 1,800-character-capped
snapshot script; a trusted-project `SessionStart` hook definition; and
`docs/DEVELOPMENT-HARNESS.md`.

**Acceptance:** every skill passes `skill-creator` quick validation; hook JSON parses; the snapshot
selects this active wave, bounds dirty paths/output, and makes no model/network call.

### W20-C1 — MCP tool output obeys the live context ceiling

**Status:** DONE (2026-08-19) · **Size:** S · **Owner:** integrator

**Goal:** make `DOCKET_TOOL_MAX_OUTPUT_CHARS` cover MCP results as well as built-ins.

**Shipped:** `edges/adapters/mcp_client.py` resolves `config.TOOL_MAX_OUTPUT_CHARS` per call and
keeps the visible omitted-character marker. `mcp-client.spec.md` 1.3.0 and a regression test change
the value after import and prove consecutive calls honor distinct limits.

### W20-C2 — wire fail-closed session compaction into the live turn

**Status:** DONE (2026-08-19) · **Size:** M · **Owner:** integrator

**Goal:** bound durable history before `ChatBackend.complete` without weakening message atomicity,
tool gating, or usage honesty.

**Read:** `specs/functional/agent-loop.spec.md`, `session-history.spec.md`,
`core/agent_loop.py::run_agent_turn`, `core/session.py::compact_session`, and the
`$docket-context-runtime` live-path reference.

**Required design decisions:** an explicit non-recursive summarizer path; whether it persists to an
isolated key or nowhere; how its measured tokens enter turn/session usage; what happens when
summarization fails; and trace payloads for no-op/success/failure without raw history.

**Acceptance:** a live-path RED test exceeds a deliberately tiny history budget and proves the
backend receives compacted history; no-op makes no summarizer call/write; failure leaves prior
history byte-identical and returns an honest result; assistant tool-call/result units remain whole;
no recursive turn/session growth is possible; focused tests plus all repository gates are green.

**Shipped:** `run_agent_turn` now checks `compact_session` before task completion through one
tool-free call on the already-resolved backend. The summarizer uses an isolated non-persisted key,
has an independent re-entry guard, records endpoint-measured usage, fails the turn without dropping
history, and emits content-free no-op/success/failure traces with before/after estimates. A real
`docket-dev` Lead -> Implementer -> Reviewer -> Tester dispatch against llama.cpp at 16k completed
with `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`: two successful compactions reduced estimated history
2,676 -> 94 and 10,825 -> 197 tokens; endpoint-measured session usage was 40,747 input + 382 output,
with zero orphaned results or unanswered calls. All 2,221 tests, 18 golden cases, 24 spec checks,
ruff, formatting, mypy, and metrics passed.

### W20-C2b — bound oversized compaction prompts hierarchically

**Status:** DONE (2026-08-19) · **Size:** M · **Owner:** integrator

**Measured trigger:** W20-C2's real 16k dispatch succeeded, but its unresolved-risk review found
that `compact_session` still renders every selected old unit into one summarizer prompt. A durable
history much larger than the endpoint window can therefore fail before it has a chance to shrink.

**Goal:** compact arbitrarily many normal-sized atomic units through bounded hierarchical summary
rounds, preserving real leading system messages and writing only the final successful candidate.

**Non-goals:** no truncation of a single oversized atomic unit, no tokenizer dependency, no role
session-key migration, and no weakening of fail-closed or tool-call/result atomicity.

**Live path / files:** `core/session.py::plan_compaction` / `compact_session`,
`core/agent_loop.py::run_agent_turn`, their two functional specs, and owning tests.

**Acceptance:** RED proves an aggregate history far above a tiny summary-input budget never sends
an oversized prompt; multiple summarizer calls converge below the role budget; generated summaries
may be summarized again while real leading system messages remain byte-identical; a later-round
failure writes none of the earlier candidates; all prompts contain whole atomic units; focused and
full gates pass.

**Shipped:** `compact_session` now selects the largest oldest atomic prefix whose complete prompt
fits the role's input budget, folds additional raw history through in-memory hierarchical rounds,
and writes only the final candidate. Generated summaries can be re-summarized; real leading system
messages remain verbatim. Oversized single units, non-shrinking output, round-cap exhaustion, and
failure in any later round all preserve the original record. Trace output adds round count and the
maximum estimated prompt size without content. All 2,225 tests plus static, spec, golden, and
metrics gates pass.

### W20-C3 — measure cross-hop history redundancy after compaction

**Status:** DONE (2026-08-19) · **Size:** S · **Owner:** integrator

**Goal:** re-run one four-role dispatch on the 16k endpoint and measure per-hop prompt/history size.
If compaction removes the failure, close with evidence. If a reviewer/tester still receives material
raw history already represented by `HandoffArtifact`, write a separate spec/card for hop-scoped
session keys before changing `core/pod.py`'s shared-key contract. No speculative key migration in
this card.

**Measured trigger:** W20-C2's successful run showed a Reviewer history estimate of 10,825 tokens
before compaction while `_hop_message` also carried typed prior-hop artifacts. C2b removes summary
prompt overflow as a confounder; redundancy can now be measured directly.

**Live path / evidence:** `dispatch_task`'s task-wide `session_id`, `_hop_message` and its
`context_composed` event, per-role `session_compaction` events, final measured `SessionRecord.usage`,
and one real Lead -> Implementer -> Reviewer -> Tester run on `docket-dev` at 16k.

**Acceptance:** record per-role composed-prompt bytes and durable-history estimates without raw
content; distinguish estimates from endpoint usage; prove whether Reviewer/Tester receive shared raw
history plus typed artifacts; close C3 with the numbers and, if material duplication remains, add a
separate spec-first card for hop-scoped runtime session keys. Do not implement that migration here.

**Measured:** a real 4-hop `docket-dev` run on llama.cpp 16k completed with 27,834 measured tokens
(27,270 input + 564 output). Hierarchical Lead compaction reduced estimated durable history
8,132 -> 2,012 in 4 rounds; its largest summary prompt was 1,990/2,000 tokens. Subsequent durable
history estimates were 2,229 (Implementer), 2,663 (Reviewer), and 3,049 (Tester), while typed
prior-hop sections added 428, 550, and 1,009 bytes respectively. The Lead artifact's 428-byte
summary occurred in 4 stored messages; across completed artifacts the conservative duplicate lower
bound was 1,802 bytes. No orphaned results or unanswered calls remained. This confirms material
raw-history + typed-handoff duplication and fires W20-C4's trigger.

### W20-C4 — isolate durable runtime history by pipeline step

**Status:** DONE (2026-08-19) · **Size:** M · **Owner:** integrator

**Measured trigger:** W20-C3 found at least 1,802 duplicated bytes in one controlled 4-hop task;
Tester received 1,009 bytes of typed carryover while also replaying 3,049 estimated tokens from the
task-wide durable session.

**Goal:** give each pipeline step its own durable runtime history so cross-role context travels once
through `HandoffArtifact`, while retries/rework of the same step retain their useful local history.

**Non-goals:** no deletion or migration of existing task-wide session files, no change to dispatch
trace/audit task identity, no removal of typed handoffs, and no weakening of resume or rework.

**Required design decisions:** specify the step-key format (including parallel/repeated roles),
separate durable-history identity from task-level trace identity if necessary, define retry/rework
reuse, and decide how `DocketDriver.list_sessions` exposes the new keys.

**Live path / files:** `core/dispatch.py::dispatch_task`, pipeline node `step_id`,
`DocketDriver.run_turn`, `run_agent_turn`'s history/trace coordinates, `core/pod.py::session_key`,
`session-history.spec.md`, `pod-dispatch.spec.md`, and session-scoping truth cleanup.

**Acceptance:** a RED live-path test proves Implementer/Reviewer/Tester backend messages do not
contain a previous role's raw assistant turn in durable history while their typed artifact remains;
same-step retry and rework continuity survive; task-level traces remain queryable; old session files
remain readable; focused tests and all repository gates pass.

**Shipped:** pod-dispatch histories now use percent-encoded
`agent:<member>:<project>:task:<task>:step:<step-id>` keys while every loop and dispatch event stays
on `agent:<project>:<task>`. The production-path regression proves the Implementer sees the Lead
sentinel exactly once through its typed user handoff and never as a replayed assistant message;
retry/rework reuse one step key, repeated-role parallel children get distinct keys, and an old
task-wide history stays unchanged, unread by new steps, and enumerable under its old prefix.
`DocketDriver.list_sessions(member)` exposes new histories, and in-process trace appends are
serialized for parallel convergence. Specs are current at Agent Loop 1.6.0, Pod Dispatch 6.1.0,
Session History 1.3.0, and Session Scoping 2.0.0. Final evidence: 2,229 pytest cases pass with 4
environment-dependent skips; Ruff, format, mypy, 18 golden cases, 24 spec validations, and README
metrics all pass.

---

## ▶ LOCAL ENVIRONMENT — rebuilt and verified against the real tree (2026-08-05)

**Status: working, with one named gap.** `docket` on PATH is an editable install whose venv resolves
to this repo's `src/docket`, so **the installed CLI follows this branch** — no reinstall
needed after a merge. Verified: `0.2.0b1`, launcher at `~/.local/bin/docket` → the dedicated venv.

### What the rebuild found

**The previous `~/.docket` was 100% test-suite residue** — the leak CLAUDE.md warns about, in its
third occurrence. 67 registered agents, every one a fixture name (`alpha`, `beta`, `goodagent`,
`legacyagent`, `declaredagent`, `sweepdemo`, `pod-a`, `pod-b`, `flatpod`, `gitless`, `taskpod`,
`leanapp`, `myapp`, `myops`, `myproj`, `myresearch`, `demo`, `demo2`, `other`). Two workspace dirs
survived and **both were empty**, one holding only a stale `.docket.lock`. No real project was ever
registered. `docket doctor` reported 14 pods "in sync" while `docket list` reported none — the
mismatch that exposed it.

Backed up to `~/.docket.backup-20260805-085622` (1.3M) before deleting anything.

### What now exists

`docket install --portfolio` → org specialists (`manager`, `knowledge`, `security`) + the four
Portfolio roles + 6 baseline policies. One real pod, **`docket-dev`, pointed at this repo**, full
4-role roster, `$5` cap, `verifyCmd = uv run ruff check . && uv run mypy src`.

All three isolation layers verified as **real, not declared**:

| Layer | Evidence |
| --- | --- |
| git worktree | `~/.docket/workspaces/projects/docket-dev-implementer/worktree` on branch `docket/docket-dev/docket-dev-implementer` |
| port range | `3000-3099`, disjoint |
| scratch dir | `~/.docket/workspaces/pods/docket-dev/.scratch` |
| session key | `agent:docket-dev:default` |

`docket gates isolate on` is **enabled and now genuinely consulted** (W18-3): `gates status` reports
`non-main (consulted by the turn loop)`. Both `docker` and `bwrap` are present and usable.

### This session's work, exercised end to end against a live server

`docket serve --port 7477 --token-file …` (token file `0600`), then:

| Check | Result |
| --- | --- |
| `POST /tasks` unauthenticated | **401** |
| `POST /tasks/docket-dev` (P22-1) | task id returned, `pending` |
| `GET /tasks/docket-dev` (P22-2) | queue read back, full normalized shape |
| **`pre_input` gate on the HTTP path** | **`guardrail_check` traced: `policy=prompt-injection action=warn`** |
| `GET /traces/…?since=` (P22-3) | compound cursor `2026-08-05T12:00:03Z:1` |
| **cursor resume** | polled from cursor → **exactly 1 new event, no replay** |
| `POST /pods` (P22-5) | pod created, roster returned |
| duplicate `POST /pods` | **409**, not a silent re-provision |
| CLI sees HTTP-created pod + tasks | **yes — one path, not two** |
| `docket audit verify` | 6 chained lines clean, incl. the HTTP provisioning |
| `docket trace expire --dry-run` (P22-6) | 187 scanned, 1 kept open, 186 kept recent |

**Two corrections to my own first reading, both worth recording.** An injection-style enqueue looked
ungated until checked properly: the string `ignore all previous instructions` does **not** match
`ignore\s+(previous|all|prior)\s+instructions` (a word sits between), and the policy's action is
`warn` by design, not `block`. With a genuinely matching string the gate fired and traced. **Neither
was a defect — reporting either as one would have been a false finding.**

### The model endpoint — CLOSED (2026-08-05)

A local **llama.cpp** server is now the org endpoint: `127.0.0.1:8081`, Qwen3.6-35B-A3B GGUF,
`--ctx-size 16384`. No API key is stored and none is needed. `docket doctor`'s four critical
endpoint issues are gone.

### Second real pod: **Adapta** (a sibling FastAPI project)

Full 4-role roster on the local endpoint, its own worktree
(`docket/adapta/adapta-implementer`), its own port range and scratch dir, `verifyCmd =
python3 -m compileall -q adapta` (the project's `.venv` is empty, so `pytest` genuinely is not
available there — the first verify command was wrong and the gate correctly failed the task).
Telegram was recovered from the pre-docket config, re-homed into docket's own secret store, and the
group identity resolved through the Bot API rather than guessed.

### What a real dispatch proved — and what it cost to get there

Running an actual pod against an actual small-context model surfaced **three defects in one
session**, none of which any test caught. See WAVE 19 below. After the two fixes:

| Hop | Result |
| --- | --- |
| lead | **works** — read the real tree through gated tools, named `adapta` and `adapta/api/app.py` correctly |
| implementer | **works** — `<promise>DONE</promise>` |
| verify gate | **passes** — `{"verification": "passed", "cmd": "python3 -m compileall -q adapta"}` |
| reviewer | **runs**, produces a real review; emits `APPROVE` on the *last* line, so the first-line verdict parse rejects it |
| tester | not reached |

**The reviewer failure is the gate working, not a docket bug.** A trailing `APPROVE` is exactly what
a structural first-line verdict parse must refuse; accepting a verdict from anywhere in the reply
would void the gate. What remains is the local model's instruction-following, not docket's.

**Operating note for a 16k endpoint:** `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`. The 30k default is
tuned for a hosted large-context model; at 30k, two tool results alone (~15k tokens) overflow the
window and the turn dies on an HTTP 400 with no partial progress.


---

## ☑ WAVE 19 COMPLETE (2026-08-05) — what running a real pod found; board CLEAR

Not a scheduled wave. Three defects, all surfaced by **actually dispatching the Adapta pod against a
real 16k-context endpoint**, none caught by 2,209 tests. `platform` green: **2,209 tests**, 18/18
goldens, 24/24 specs, `mypy --strict` clean, metrics in sync.

**W19-1 — a worktree member was told to work in a directory it was forbidden to read.** FIXED.
`provision_member` gives an Implementer a git worktree, and `_resolve_roots` then returns that
worktree **alone**. But `SOUL.md` (the system prompt) and `WORKFLOW_AUTO.md` (the startup contract
re-read after every context reset) both named the **origin checkout**, while `TOOLS.md` named the
worktree. Every read of the advertised path came back `resolves outside the allowed roots`; the
model retried other spellings and the turn died on the token budget with **zero successful tool
calls**. Nothing crashed, so nothing went red.

*Now:* one `told_root = worktree_dir or codebase` at the single point all three files are written,
so a member with a worktree is told the worktree and a member without one is **byte-identical**.
`docket doctor`'s contract heal was the same defect's second writer and is fixed with it. New
`tests/python/test_workspace_root_agreement.py` pins the invariant as *the advertised path is inside
`_resolve_roots()` for that member* — a property, not a path string. Proven RED first: 4 of 8 failed
before the fix, and the doctor test was re-proven RED on its own.

**Deployed pods were repaired, not just new ones.** `docket doctor` does not re-render `SOUL.md` for
pod members (they are excluded from template-drift), so `adapta-implementer` and
`docket-dev-implementer` were repaired in place and their contracts re-seeded through the fixed
doctor path.

**W19-2 — the tool-output ceiling was unreachable from outside the code.** FIXED.
`toolbox.MAX_OUTPUT_CHARS` was a bare `30_000` literal. It is a **context** bound, not a display
bound — the usable value is a function of the endpoint, and docket had no way to say so. Now
`config.py`'s `TOOL_MAX_OUTPUT_CHARS` (`DOCKET_TOOL_MAX_OUTPUT_CHARS`), added to the single-owner
guard, resolved **per call** rather than bound as a default argument so it stays a live setting.
Both guards proven RED: the import-time binding restored, and a re-declared `os.environ.get` planted
in `toolbox.py`.

**W19-4 — the trace cursor replayed on any project with more than one session.** FIXED.
`GET /traces/<project>?since=` is what an external plan-of-record polls, and P22-3's whole point was
resuming without re-ingesting. But `core.trace.export_lines` concatenates session files in **sorted
filename order**, and a session id is a uuid — so with more than one session (any project with
history) the stream is not chronological, while `_traces_page` anchored the cursor on the *last*
line of the page and counted a *trailing* run at that ts. Both are correct only on an ordered page.

Measured on the real `adapta` project: first poll 47 events, cursor `…T15:45:01Z:2` — a timestamp
*earlier* than events in the same page — and a resume from it replayed **36 of the 47**. The
earlier wave-16 verification ("exactly 1 new event, no replay") was correct but not general: that
project had a single session file at the time. *Now:* the page is sorted by ts before anchoring, so
the cursor lands on the newest event and the tie-count covers the whole page. Re-measured on the
same project: resume returns **0 events**. Events also now arrive in time order across sessions,
which is what a consumer folding them onto a board needs. Three tests added, all proven RED first.

**W19-5 — the README described a conversational Telegram bot that does not exist.** FIXED (docs).
Found by *using* the wired Adapta group: plain prose (`hablame del proyecto`) comes back
"Unrecognized command", which is precisely what the README promised would work. Three false claims
in one section:

| Claim | Reality |
| --- | --- |
| "Conversational dispatch — message the Lead directly" | Four slash commands only; anything else is refused |
| "a gated action **pings** the wired group" | `send_message` has **one** call site (the reply in `poll_once`); `core/approval.py` has zero references to the module. Nothing is ever pushed. |
| setup snippet used `docket serve` | The poll loop only starts under `--telegram` |

Corrected in `README.md`, `docs/commands.md` and `docs/QUICK-START-DOCKET.md`, plus the two limits
that follow and were nowhere stated: docket never messages first, and `/delegate` returns a task id
rather than the agent's answer.

**The spec was right the whole time.** `specs/functional/telegram-integration.spec.md` has always
required "exactly four verbs" and that any other text be treated as unrecognized — *"never as an
implicit delegate"*. This was prose drifting from a correct spec, which is a different failure from
the W17-1/W18-3/W19-3 family (machinery unwired). **The lesson is the inverse one: a CI-validated
spec did not stop the README from promising something else**, because nothing compares them.

Made durable rather than just corrected: the spec now states inbound-only as requirement 7 (and
`/delegate`-returns-an-id as 8) with both echoed in Non-Goals, pinned by an AST guard
(`TestInboundOnly`) that fails if anything outside the reply path calls `send_message` or if
`core/approval.py` ever reaches the Telegram module. Proven RED by planting an outbound push in
`serve.py` and an import in `approval.py`. The boundary can still be moved — deliberately, in a
change that has to update the guard.

**W19-3 — session compaction is implemented, tested, documented, and never called.** FOUND, NOT
FIXED. `core/session.py` ships `plan_compaction`/`compact_session` with fail-closed summarisation.
**Nothing in `src/` calls either.** `core/agent_loop.py` imports only `append_messages`/
`load_messages`. Every hop of a dispatch shares one session key, so the reviewer hop sees the lead's
and implementer's full raw history *on top of* the compiled `HandoffArtifact` — the typed-handoff
budget bounds the message, not the history. On a 16k endpoint this rejects the prompt outright at
19,827 tokens; on a 200k hosted model it stays invisible.

**This is the third instance of the exact shape CLAUDE.md names** (MCP tools, W17-1; sandbox, W18-3):
machinery built, tested, never wired to the default path, with docs claiming it works. Both false
claims were corrected immediately rather than held pending the fix — `maintain sessions` said
*"Per-session compaction is automatic"* and `docket help` said *"(compaction is now automatic)"*.
The help golden moved by exactly one line, for a string that was factually false.

**Wiring it is a real card, not a patch:** `compact_session` needs a `SessionSummaryRunner` (a
`run_turn` call), so calling it from inside `DocketDriver.run_turn` needs a recursion guard, a
decision about which session key the summariser uses, a trace event, and tests. Deliberately not
attempted inside an unscheduled wave.

---

## ☑ WAVE 18 COMPLETE (2026-08-05) — two false security claims, both now true; board CLEAR

Three cards. `platform` green: **2,199 tests**, 18/18 goldens byte-identical, 24/24 specs,
`mypy --strict` clean, metrics in sync.

**The wave found more than it was opened for.** It was scheduled against one reproduced defect
(the audit chain). The claims-audit card that ran alongside it found a **second, worse one**.

**W18-3 — `docket gates isolate on` did nothing.** The flag persisted to `fleet.json`;
`get_isolation_enabled`'s only caller was a CLI inspection path; `DocketDriver.run_turn` never set
`ToolContext.sandbox`, so it stayed `"off"` and **every tool call ran unsandboxed regardless of the
setting.** The bwrap/docker argv construction was implemented and tested, and `core/tools.py`
threaded `ctx.sandbox` to the handler — nothing ever set it. **Identical in shape to the MCP gap
wave 17 closed: machinery present, tested, unreachable on the default path.** The difference is that
this one is a security control the README advertised three times.

*Now:* `run_turn` resolves the flag through the single field every writer funnels through, so it
cannot disagree with `docket gates status`. **Fail-closed is a turn-level refusal, not a downgrade** —
isolation on with no usable backend refuses the turn before any model call, audit-logged, because a
refused turn emits no `dispatch_tool` entry to carry the reason. The agent explicitly rejected
`run_bash`'s per-call degrade as a stand-in: *a marker buried in one tool's output is not isolation
meaning something at the turn level.* Verified by forcing `DOCKET_SANDBOX_BACKEND=none`.

**W18-1 — the audit chain now survives rotation.** Rotation restarted at `seq=1` with a
single-generation backup, so flooding past two rotations erased history while `docket audit verify`
reported clean. Rotation now carries the previous generation's final `seq`+hash forward as a
continuation claim, checked against the retained backup, giving three distinguishable states:
genesis, continuation verified, and **continuation whose predecessor cannot be produced** — the
erasure case that was invisible. Re-ran the reproduction: first `seq` is now 396 rather than 1, and
deleting the backup yields a named break.

**Both agents' RED/GREEN was re-verified by the integrator, not taken on report.** Planting drift in
rotation turned **six** audit tests red; the isolation guard was proven by its own agent and the
fail-closed path re-run by hand.

**Where the honesty rules actually bit, and it is worth keeping:** the README was corrected to say
isolation *did not work* **before** W18-3 landed, then corrected again to describe the fix. A
security claim that is false today gets corrected today — not held pending a fix that might slip.

**What stays true and is now documented rather than implied:** only one rotation back is verifiable;
deleting both audit files at once is still indistinguishable from a fresh install; and `--no-gates`
never disabled the tool-call gate at all — it skips approval *routing*, while the policy engine and
classifier are always active (`cli/_install.py` says so in its own docstring).

**Three undersells found and not yet folded in** — a sixth `channel="tack"` audit label, full
5-field cron support beyond `@every`/`HH:MM`, and baseline policies installing unconditionally
regardless of `--gates`. Deferred deliberately so the README moves once, not three times.

**A measurement note for the next wave:** worktree baselines drift from the main checkout by more
than the one `CLAUDE.md` skip — an agent measured 2179/5 where main showed 2184/4. **Have each agent
measure its own base commit** rather than quoting a number from the board.

---

## ☑ WAVE 18 board (closed) — opened 2026-08-05

**Not a deferral being worked down.** The board was clear and every remaining deferral has an
unfired trigger. This wave exists because a **reproduced defect** was found in an advertised
guarantee — README lists "Hash-chained tamper-evident audit log ✅ `docket audit verify`" as a
differentiator, and the chain does not survive its own rotation.

### The reproduction (run before scheduling, not inferred from reading)

With `AUDIT_LOG_MAX_BYTES` lowered and two security-relevant entries recorded, appending noise until
the log rotates twice produces:

| observation | result |
| --- | --- |
| security entries in `audit.log` | **gone** |
| security entries in `audit.log.1` | **gone** — the 2nd rotation overwrote the backup holding them |
| `verify_chain()` | **no break reported** |
| first `seq` in the current chain | **1** — indistinguishable from a fresh install |
| after `rm audit.log.1` | `rotated_backup=False` — looks pristine |

`_rotate_if_needed` does `os.replace(logf, backup)` to a **single** generation, and `_chain_head` on
the now-absent file returns `(1, GENESIS_HASH)`. So each generation is an island: tamper-evident
*within* itself, with nothing asserting that anything preceded it.

**Anyone who can cause audit writes can erase audit history, and the verifier will call the result
clean.** For a log whose entire value is honest provenance, that is the property that matters.

### Cards

**W18-1 · Make the chain survive rotation** — *TODO · M*
Owns `core/audit.py`, `cli/_audit.py` (or wherever `docket audit verify` renders), `config.py`'s
audit constants.

**W18-2 · Verify the capability claims against the tree** — *TODO · S · report only, no code*
Produces a findings file; the integrator applies any README edits (README is integrator-owned).
Justified by track record, not suspicion: the comparison table has been **wrong twice this month** —
the MCP row claimed tools reached a live turn when the wire did not exist, and the read-API row
undersold what shipped. A table whose stated purpose is "honesty is the point of this table" earns
periodic checking against the code.

### Constraints on W18-1

- **`audit_log` must keep its never-fail contract.** It is best-effort by design and silently
  no-ops on `OSError`. Do not make an audit write able to break a command.
- **Do not conflate this with trace retention.** P22-6 deliberately excluded `audit.log`: telemetry
  may be sampled and lossy, an audit log may not. This card makes history *harder to destroy
  silently*, never easier.
- **Detection beats prevention here.** Unbounded retention is not the goal — bounded disk is still
  desirable. The goal is that a missing generation becomes **visible** rather than invisible.
- Whatever ships must be **honestly described**. If some erasure remains undetectable (an attacker
  with full filesystem access can always delete everything), say so plainly rather than implying the
  log is now unforgeable.

---

## ☑ WAVE 17 COMPLETE (2026-08-05) — the MCP wire landed

Two cards, two agents, both merged. `platform` green: **2,184 tests**, 18/18 goldens byte-identical,
24/24 specs, `ruff` + `mypy --strict` (73 files) clean, `metrics.py --check` in sync.

**W17-1 closed docket's oldest recorded limit.** The wire itself was one seam (`DocketDriver.mcp_loader`,
loading *before* `run_agent_turn` narrows per role — that ordering is load-bearing). **Making it safe
was the entire card**, and the answer used data already present rather than a new archetype field:
`core/mcp_tools.py` already registers every adapted tool `kind="write"` unconditionally, so
`registry_for_role` now strips by the *kinds* a role's `denied_tools` imply, via a new
`ToolRegistry.without_kind()`.

**The integrator found one hole in that answer, and it is the wave's most useful artifact.** The
denied-kind set was derived by looking each denied name up **in the registry being narrowed**:

```python
{tool.kind for name in archetype.denied_tools if (tool := base.get(name)) is not None}
```

That makes the whole denial conditional on the denied built-in still being *present*.
`DocketDriver.registry_factory` exists precisely so a caller can inject a narrower tool set — its own
docstring says so — and against a base of `{read, mcp__fs__write_file}` a Reviewer **kept the
write-capable MCP tool**, verified by running it. Production was unaffected (the driver builds
`builtin_registry()` first), so it was latent, not live. But it is the exact failure mode the card
exists to prevent, re-entering through a different door.

Fixed with a static `BUILTIN_TOOL_KINDS` map: **the denial depends only on the role's own data,
never on what the caller passed in.** Two tests, both proven RED first — one narrows against a base
with no built-in write/edit/bash, one pins the map against `builtin_registry()` so a new built-in
cannot silently gain no denial. **Every pre-existing kind-exclusion test started from
`builtin_registry()`, which is exactly why this shape was uncovered.**

The generalizable rule, worth more than the fix: **when a capability can arrive under a name you do
not control, deny the capability, never the name.**

**W17-1's honest residue**, recorded rather than carried silently: a read-only role now gets **zero**
MCP tools rather than a correctly narrowed subset, because nothing can distinguish a genuinely
read-only remote tool from a write-capable one. And there is no listing cache — each configured stdio
server is re-spawned per turn (~0.6s **measured**, not assumed). Zero servers costs ~0.004ms and
spawns nothing, so the default path is unchanged.

**W17-2 found more than the card described.** `config.py`'s `METRICS_WINDOW` **had no reader at all**
— dead code advertising a knob that did nothing, because `cli/_metrics.py` used its own declaration.
`DOCKET_SECRETS_BACKEND` and `DOCKET_NO_TRACE` were each duplicated too. Two constants became
**functions** rather than constants, for a reason worth keeping: tests toggle them with
`monkeypatch.setenv` mid-test and expect the next call to observe it, which a module-level constant
read once at import cannot do. Genuine lookups (`EDITOR`, `PATH`, per-provider API keys,
`DOCKET_LLM_BASE_URL`) were deliberately left alone — **not every environment read is a tunable
constant.** Guarded by an AST test, proven RED.

**A measurement correction worth keeping.** The "2,162 passed / 4 skipped" baseline in the wave-16
record is **main-checkout-only**. Every agent worktree sees **5** skips, because
`test_docs_positioning.py` skips when `CLAUDE.md` is absent — and `CLAUDE.md` is gitignored, so it
never exists in a fresh worktree. Quote worktree baselines as 5 skips, or an agent will waste a cycle
reconciling a phantom regression.

---

## ☑ WAVE 17 board (closed) — opened 2026-08-05

**This wave adds no new capability to the plan.** It closes the first of the four *known-true
limits* CLAUDE.md lists, plus one hygiene defect. Both were **re-verified against the tree before
being scheduled** — the P20-4 rule — and both are real today:

- `load_mcp_tools` appears in `src/docket/` only inside docstrings and comments. It is never called.
  `DocketDriver.registry_factory` is `builtin_registry` and nothing overrides it.
- `METRICS_WINDOW` is declared twice, independently: `config.py:81` and `cli/_metrics.py:26`.
  `config.py` declares **none** of `RUNAWAY_TURNS_THRESHOLD`, `RUNAWAY_COST_THRESHOLD` or
  `KEY_MAX_AGE_DAYS`, which are read straight from the environment in `cli/_cost.py` (inline, twice
  each) and `cli/_doctor.py` — despite CLAUDE.md stating `config.py` holds *every* path and constant.

### Cards

**W17-1 · MCP tools reachable in a live turn** — *TODO · M/L*
Owns `edges/adapters/docket_runtime.py`, `core/agent_loop.py`'s registry composition, and
`core/archetypes.py` if the role decision below requires it.

**W17-2 · One owner per configuration constant** — *TODO · S*
Owns `config.py`, `cli/_metrics.py`, `cli/_cost.py`, `cli/_doctor.py`.

### The question W17-1 must answer before it writes any code

**Role narrowing runs on built-in names only, and MCP names are not built-in names.**
`core/agent_loop.py:264` calls `registry_for_role(registry, ctx.role)`, which removes exactly the
names in the role archetype's `denied_tools` — `("write", "edit", "bash")` for a Reviewer. Every
adapted MCP tool is registered as `mcp__<server>__<tool>`, so **none of them match any
`denied_tools` entry.**

Load MCP tools into a turn naively and a Reviewer — which the README says *structurally cannot
write*, and whose registry genuinely lacks `write`/`edit`/`bash` today — is handed
`mcp__filesystem__write_file` by any configured filesystem server. That is not a regression in a
detail; it silently falsifies a headline guarantee, and the guarantee is the product's whole claim.

**No implementation may land that does not answer this.** Fail closed by default.

### What must stay true

- **The chokepoint.** `core/mcp_tools.py` never calls a handler itself, so adapted tools already
  route through `dispatch_tool`. Nothing in this wave may create a second execution path; the AST
  guard exists and must stay green.
- **Failure isolation.** `load_mcp_tools` never raises. An unreachable or hung server must degrade
  to "unavailable" and must never block or fail a turn that would otherwise run on built-ins.
- **Turn cost is a real constraint.** Loading is per-turn, and a stdio server means spawning a
  subprocess. Measure it before deciding whether the wire needs caching or opt-in gating; do not
  assume either way.

---

## ☑ WAVE 16 — Phase 22 COMPLETE (2026-08-04). All six cards shipped

Two rounds, four agents. **Round 1:** P22-1+P22-4 (`do_POST`), P22-2+P22-3 (`do_GET`), P22-6
(`core/trace.py`). **Round 2:** P22-5 alone. `platform` green at close: **2,162 tests**, 18/18
goldens byte-identical, 24/24 specs, `ruff`+`ruff format`+`mypy --strict` (73 files) clean,
`metrics.py --check` in sync.

**The ownership split worked.** Five of six cards touched `serve.py`; splitting by HTTP *method*
produced zero code conflicts. The one conflict was the one the scheduling rule predicts —
`specs/data/serve-read-api.spec.md`, where two cards both wrote a 2.4.0 changelog entry. Resolved by
keeping **both** and merging them, never by picking a side: neither side held the other's change.

**Four defects found in review, not by the suite.** Worth recording because each is a pattern:

1. **A cursor that ate its own timestamp.** `_decode_trace_cursor` split `since` on the last colon
   to separate `<ts>:<n>` — but *a timestamp contains colons*. Safe for every cursor docket mints
   (`_now_iso()` always writes a trailing `Z`), broken for the hand-supplied bare timestamp the
   function documents as supported: `"…T12:34:56"` decoded as `ts="…T12:34", n=56`, rewinding a poll
   loop to the start of the minute. **The existing test covered the bare form only *with* the `Z`,
   which is exactly why it survived review.**
2. **A comment that was false when written.** The retention sweep wiring initially claimed sweep
   *order* mattered so a stale-open trace expires in the same pass. The test written to pin it
   failed: `_end_record` stamps `_now_iso()`, so terminating a trace **resets its age**. Real
   semantics — retention runs from when a session *ended*, not from last activity. Caught only
   because the comment was tested instead of trusted.
3. **A caveat that a shipped card made false.** `serve.py`'s and the spec's `/metrics` durability
   note said trace-derived counters had no history gap *because traces were never deleted*. P22-6
   deleted that premise. Both now state that every counter there is a lifetime-of-current-storage
   count, not a monotonic total.
4. **A pointer left behind by a refactor.** `cli/_doctor.py` referenced
   `cli/_pod.py::_write_member_workspace` after P22-5 moved it to `core/pod_provisioning.py`.

**Every new guard was proven RED before being trusted** — the channel allowlist, the `trusted`
override, the open-trace liveness rule, the sweep wiring, the cursor fix, and the rollback (which
fails on real orphaned filesystem state, not a mock asserting cleanup was called).

**P22-5's honest finding, recorded rather than buried:** `docket add` has no `--verify` flag today
(only `docket pod <p> set-verify` does), so threading `verifyCmd` into initial provisioning is the
closest this phase came to growing new surface. Judged reuse — `provision_member` already had the
parameter, and the roadmap's own body spec named the field — but it is the one call worth revisiting
if the CLI and HTTP surfaces are ever compared field by field.

---

## ☑ WAVE 16 board (closed) — Phase 22, the control-plane write API (opened 2026-08-04)

**Read [ROADMAP.md](ROADMAP.md) §PHASE 22 before claiming anything here.** The phase exists because
a real consumer (**Tack**, holding the plan of record) is blocked on each card by name. The design
rule governs every card:

> **Expose what `core/` already does; add no new behaviour.** Every card is a `serve.py` route over
> an existing `core/` function, with the same Bearer auth, the same policy hooks and the same audit
> entries the CLI path produces. **A card that starts designing new semantics has stopped being this
> phase.**

### Scheduling — ownership is by HTTP method, not by file

`serve.py` is this wave's hotspot the way `core/dispatch.py` was Phase 14's and `core/tools.py` was
Phase 19's. Five of six cards add a branch to the *same two* methods, so the split is:

| Round | Card(s) | Owns | Must not touch |
| --- | --- | --- | --- |
| 1 | P22-1 + P22-4 | `serve.py::do_POST`, `core/dispatch.py::enqueue_task`, `core/approval.py` | `do_GET`, `core/trace.py` |
| 1 | P22-2 + P22-3 | `serve.py::do_GET` | `do_POST`, `core/trace.py`, `core/dispatch.py` |
| 1 | P22-6 | `core/trace.py`, `cli/_trace.py`, `config.py` | `serve.py` entirely |
| 2 | P22-5 | provisioning extraction + `do_POST` | — (runs alone) |

**Why P22-5 is alone and second.** It is the card ROADMAP already flags as the one that can grow, and
a measurement confirms it: `serve.py` imports `docket.config`, `docket.core.*` and `docket.edges.*`
and **never `docket.cli`** — but the real provisioning path is `cli/_pod.py::build_pod_from_blueprint`
→ `build_pod` → `cli/_agents.py::_provision_agent`, which prints through `ui.py`. So `POST /pods` is
not a route over an existing `core/` function; it is *an extraction into `core/` first*, then a thin
route. That makes it structurally different from the other five and it gets its own round.

### Cards

- **P22-1 · `POST /tasks/<project>`** — TODO · S · *blocks Tack Phase 35*
- **P22-2 · `GET /tasks/<project>`** — TODO · XS
- **P22-3 · `GET /traces/<project>?since=`** — TODO · S · *P20-3's deferral trigger firing*
- **P22-4 · `channel="tack"` on approval decisions** — TODO · XS
- **P22-5 · `POST /pods`** — TODO · M · *blocks Tack Phase 37* · **round 2, alone**
- **P22-6 · Trace retention** — TODO · S · *un-defers P20-3's retention half*
- **P22-7** — not a card. Recorded in ROADMAP for its consequence (agents cannot self-report onto
  Tack's board until MCP-in-a-live-turn lands).

### Two constraints this wave will be judged on

1. **`enqueue_task` hardcodes `source="operator"` and therefore `trusted=True`.** P22-1's body names
   a `trusted` field. Threading it is acceptable *only* as an optional parameter wired to the
   `trusted=` argument `core/policy.py::policy_eval_detail` already takes — with a default that
   leaves the CLI and MCP paths byte-identical. Inventing a new trust concept is out of phase.
2. **Retention must not touch `audit.log`.** Telemetry is sampled and lossy by design; an audit log
   must be neither. Conflating them is the mistake Phase 20's design rule already names.

---

## ☑ Wave 13 close (2026-08-04) — Phases 19, 20 and 21 all shipped

**Every scheduled card is done.** Phase 19 (13 cards), Phase 21's surviving two (P21-1, P21-5) and
Phase 20's surviving one (P20-2) have all shipped. P20-4 was dispatched and came back a **no-op** —
the gap it was written against had been closed by W-4 months earlier and never re-trued (see
ROADMAP's P20-4 card; the lesson is that a gap list is a claim about the tree and decays like one).

`platform` green at wave 13 close: **2,081 tests** (`pytest` exit 0, 4 env skips), 18/18 goldens
byte-identical, **25 specs** valid / 0 warnings, 37 commands, ~26,700 lines, `ruff` + `ruff format`
+ `mypy --strict` (73 files) clean, `metrics.py --check` in sync across all five claims.

**What was cut stays cut.** OpenTelemetry, streaming and the tenant axis were cut by D-24 and Phase
22 does not reopen them. The two D-24 deferrals Phase 22 *does* pick up are picked up because a
trigger fired (P22-3) or the reasoning genuinely changed (P22-6) — not because the list was
re-litigated. Egress lockdown and the build-agent profile remain deferred with their triggers intact.

## ☑ WAVE 14 — the cleanup wave (2026-08-04). Docs re-trued, dead code gone, archaeology stripped

Six cards, two rounds. **Round 1:** CL-A (`docs/**`), CL-B (root `*.md`), CL-C (dead code in
`src/`+`tests/`), CL-D (repo hygiene: `examples/`, `Formula/`, `install.sh`, `.github/`, `scripts/`).
**Round 2:** CL-E (`src/` comments), CL-F (`tests/` ceremony + comments).

**What it removed:** `restart_gateway()` and its ~15 ceremonial call sites (a documented no-op each
one rendered a result for); `ToolResult.needs_approval`; `save_mcp_servers`; the golden suite's fake
`openclaw` binary; two `.lobster.yml` examples for a removed command; `scripts/wire-local-provider.sh`
(shelled out to `openclaw config set`); `DOCKET_NO_RESTART` in 37 test files; `OPENCLAW_DIR`/
`openclaw.json` fixture setup in 11; two genuinely dead tests. ~2,900 lines net.

**Comment archaeology, `src/`:** `Phase 1X` 204→3 · `P19-` 163→1 · `ROADMAP` 142→5 · `W-N` 147→2 ·
`D-1X` 57→0. `tests/`: `P19-` 109→1 · `Phase NN` 86→0. Survivors are golden-pinned strings or live
pointers to standing rules (§4.5), not shipped-card records.

**The policy applied, worth keeping for the next sweep:** delete card ids, phase numbers, dates,
provenance, and narration of deleted things — git history and ROADMAP hold all of it. **Keep** any
sentence whose loss would let someone introduce a bug: why a constant has its value, why something
fails closed, why two similar things differ deliberately, and (in tests) which regression a guard
exists to prevent plus any note that a guard was proven RED before being trusted. When in doubt, keep.

**Three findings that were defects, not staleness:**
1. **MCP tools are not reachable in a live turn.** `load_mcp_tools` is never called; `DocketDriver`'s
   `registry_factory` defaults to `builtin_registry` and nothing overrides it. Configuring a server
   registers and gates it; the last wire is missing. README and `commands.md` both overclaimed this
   (text written the same session) and were corrected. **The spec had it right all along.**
   *"Browser support is just an MCP config" is only true once that wire exists — do not reuse that
   argument to decline work until then.*
2. **`NOTICE` declared the project MIT-licensed** while `LICENSE`, the CHANGELOG relicense entry and
   the README badge all say Apache 2.0.
3. **All four `examples/configs/*-agent-meta.json` failed `AgentMeta` validation**, and
   `agents.yaml` silently dropped 2 of its 3 entries through `docket add --from`.

~~**Carried forward, NOT carded — the eval harness is dead code.**~~ — **resolved by CL-J** (wave 15):
the feature was removed outright. See the wave 15 block below.

---

## ☑ WAVE 15 — the last legacy sweep (2026-08-04)

Four cards. **CL-G** renamed 94 of 104 test files from card ids to subjects. **CL-H** fixed a real
bug and finished the `src/` prose sweep. **CL-I** measured the eval harness and recommended deletion;
**CL-J** executed it completely.

**CL-G — the suite now says what it tests.** `test_m4_wave1.py` → `test_profile_scope_models.py`,
`test_ch6_tier_shims.py` → `test_tier_shims_removed.py`, and 92 more, all via `git mv` so history
follows. Its one collision (two files both stripping to `test_verify_gate.py`) was resolved by
subject, not by number. Remaining card-id archaeology in `tests/` is now zero except protected
`D-12` (a live rule named in CLAUDE.md) and `ROADMAP §4.5` pointers. It also found a guard silently
exempting `core/drift.py`, a module deleted long ago — the test's own docstring had said to remove
the entry once that happened. **Integrator follow-up:** 29 files outside `tests/` still named the old
paths; repointed mechanically from the rename map git recorded, then verified zero survivors.

**CL-H — a documented invariant that was never wired.** `TELEGRAM_REQUEST_TIMEOUT_S` was defined,
documented and env-overridable but referenced nowhere, so the adapter used a hardcoded 35s socket
timeout. Setting the env var did nothing, and raising `TELEGRAM_POLL_TIMEOUT_S` above 35 (Telegram
permits it) would put the socket timeout *below* the poll wait — making every empty long-poll read as
a local failure, exactly what the constant's own comment warned about. Now resolved in `core/` and
threaded through; on violation it **clamps to poll + 10s with a warning** rather than refusing,
following `MCP_CLIENT_MAX_TIMEOUT_S`'s precedent (this is not a security decision, and a one-line env
mistake should not take the approval channel down). Proven red before green. **Reported not fixed:**
`METRICS_WINDOW` is declared in `config.py` but `cli/_metrics.py` keeps its own `os.environ.get`
copy — a drift risk, not the same silent failure.

**CL-I/CL-J — `docket eval` removed outright, no replacement.** The harness could not run: it shelled
out to the deleted daemon and **skipped silently** rather than failing, so it read as coverage while
doing nothing, and CONTRIBUTING and README both cited it as a real gate. Two findings settled
repair-vs-delete: no CLI entry point runs a single agent turn (`run_turn` is reached only from pod
dispatch and distillation), and three of six eval scripts assume the pre-Phase-10 global
`programmer`/`reviewer`/`tester` roles that `doctor` now flags as legacy debt. Removed coherently —
module, command, doctor advisory, spec (per the retire-by-deletion convention), and every doc/CI
reference. `docket eval` prints a removed-command notice and exits 1, matching `workflow`/`team`.
CL-J also found `config.py`'s `cli_root()` existed only to serve the deleted module and removed it.

**A guard earned its keep on unrelated work:** CL-J's first draft of the notice tripped
`test_no_openclaw_references.py` — the AST guard forbids that word outside comments and docstrings,
and the notice is a live string. pytest caught it.

**Repo cruft:** 52 stale agent worktrees pruned and 114 fully-merged card branches deleted
(`git branch --no-merged platform` was empty first, so nothing was lost).

**Tree at close:** 2,079 tests · 26,253 lines · **36 commands** · **24 specs** · 18/18 goldens ·
all guards in sync. Command and spec counts *fell* because a feature was removed; that is the work
landing, not drift.

---

## Historical — Phase 19 waves 8-9 shipped; the daemon is unused

**Platformization (Phases 14-18) is COMPLETE** — 38 cards, 7 waves; durable per-card records are the
`☑ Waves 3-4 / 5 / 6 / 7 shipped` blocks in ROADMAP.md's Phase 16 section.

**Phase 19 is ACTIVE.** Waves 8-9 shipped six cards: P19-1 (chat port) · P19-2 (gated tool registry)
· **P19-3 (`pre_tool_call` is live — the milestone)** · P19-4 (session history) · **P19-5 (the turn
loop + `DocketDriver`)** · P19-9 (sandboxed exec) · P19-10 (MCP client).

**Where that leaves the daemon: unused, not yet uninstalled.** docket can now run a fully gated agent
turn end to end — and does not yet, because `core/dispatch.py` still resolves `OpenClawDriver`. The
cutover is wave 11 (P19-6 -> P19-7), which is also where the ACL and `openclaw.json` are deleted.

`platform` green at wave 9 close: **2,026 tests** (`pytest` exit 0), 18/18 goldens byte-identical,
**24 specs** valid / 0 warnings, 37 commands, ~27,100 lines, `ruff` + `ruff format` + `mypy --strict`
(71 files) clean, `metrics.py --check` in sync across all five claims.

**The goal is now stated, and it resolved the open decision.** The user's objective is **a factory for
agentic products**. That answers **D-20: both, in an order** — factory first (it exists; Phase 19
finishes it), embeddable substrate second (Phase 21). The reasoning is one sentence and worth keeping
in front of you while working: *if every product is agentic, the runtime is the common part of every
product*, so the factory's highest-value output is a **reusable substrate**, not agent-written code.

**What that answer does NOT buy — read this before scoping anything:** the *hosted-SaaS* half.
Multi-tenancy, authn for external callers, queues/workers, streaming and per-customer quota are
**out of scope**. The substrate is a **library a product embeds**; the product owns its own serving
layer. Conflating "embeddable library" with "hosted product runtime" is the failure mode D-20 exists
to prevent.

**Decision status (2026-07-31):** **D-20 ANSWERED** (both, factory first) · **D-21 YES** — the package
split is live, *packaging only*, after the removal wave · **D-22 CUT** — stay project-scoped, build
nothing, re-open only if docket itself serves multiple end customers · **D-23 re-scoped** — ship the
`fetch` tool, defer the egress lockdown · **D-24 NEW — the prioritization ruling.**

**D-24 cut roughly half of Phases 20/21, including the integrator's own recommendations from hours
earlier.** Full verdict table in ROADMAP §5 (*"Prioritization ruling"*). What it means for this board:
**CUT** — OpenTelemetry (P20-1), streaming (P21-2), tenant axis (P21-3), and any browser-automation
tooling (that is an MCP config, per P19-13). **DEFERRED** — egress lockdown, fleet trace query
(P20-3), build-agent profile (P21-4). **KEPT** — the removal wave, P19-11's `fetch` tool, P19-12,
P19-13, P21-1, one new XS card **P21-5** (`agentic-product` blueprint — a row in an existing
registry, not new machinery), P20-2 and P20-4. The test applied was §4.5's, not "is this best practice
for someone": **does a measured need in *this* system ask for it.** It binds the integrator too.

**Phase status:** Phase 14 **COMPLETE** (R-1…R-8) · Phase 15 **COMPLETE** (G-1…G-6, closed by G-3)
· Phase 16 **COMPLETE** (W-1…W-8) · Phase 17 **COMPLETE** (C-1…C-5, closed by C-3/C-5) ·
Phase 18 **COMPLETE** (L-1/L-2/L-3/L-6 shipped; L-4 and L-5 answered as evidenced spikes).

### Three standing integrator checks (all earned the hard way)

1. **Never resolve a conflict in a roll-up table by picking a side.** `specs/README.md`'s status
   table, README's metric counts and the golden completion lists are edited by several branches at
   once, so *no side holds every change*. Regenerate from ground truth — the spec headers, the real
   CLI (`bash tests/golden/run.sh capture <case> <shell>`), the actual suite — and read the diff.
   This caught real regressions on three consecutive merges, including two that would have deleted a
   shipped command from the completion surface and one that silently downgraded three spec versions.
2. **A green guard is not evidence until you have seen it fail.** `scripts/metrics.py --check` spent
   all of Phase 14 reporting success while verifying nothing (comma-blind `(\d+)` claim regexes plus
   a silent skip for unmatched claims, against a README that had lost 3 of its 4 claims). Fixed:
   thousands separators are matched, and a README stating none of the tracked metrics is now a hard
   failure. When adding a guard, add a test that proves it fails on bad input.
3. **Ask what set a guard actually checks, not just whether it is green.** Check 2 caught guards
   that verified *nothing*; wave 7 caught two that verified the *wrong set* while reporting
   success. `metrics.py` counted specs with an `*.spec.md` suffix filter while the blocking
   validator globs `specs/acceptance/*.md`, so README published 20 where CI counted 21. The
   dependency floors in `pyproject.toml` had never once been resolved-and-tested, and two of six
   were false. **The tell is the same every time: a number nobody has ever watched go red.** When
   two scripts both claim authority over one number, pin them to each other.

---

## Wave 5 — ☑ COMPLETE (2026-07-30, all five merged; Phase 16 finished with it)

Merge order `l-4 → g-4b → w-4 → cl-2 → w-5`. Durable record: the `☑ Wave 5 shipped` block in
ROADMAP.md's Phase 16 section. **Tree: 1,512 → 1,600 tests**, 18/18 goldens byte-identical
throughout, 20 specs, 37 commands.

☑ **W-5** (`0d91b51`) typed `HandoffArtifact` replaces raw-text hop concatenation — **unblocks C-1**
· ☑ **W-4** (`9e6cd04`) cron, webhook→pipeline variables, `--follow`, `runs.cancel` audit
· ☑ **G-4b** (`fe7af1c`) `models.*` audit family · ☑ **CL-2** (`dac85c8`) dead-code register,
non-dispatch half · ☑ **L-4** (`312787e`) daemon-MCP-registry spike, answered with dated evidence.

**Three lessons this wave, all of them cheap to forget:**

1. **A fourth neither-side-is-correct conflict** (`audit.spec.md`): G-4b's draft said `models.*`
   shipped and `runs.cancel` was open; W-4's said the reverse. Both shipped the same wave, so
   neither card could see the other's merge. Either side alone publishes a spec claiming a shipped
   feature is missing. **Cards that close sibling gaps in one wave will always do this** — read both
   sides against the code, never pick.
2. **Worktrees start on `main`.** Three of five agents branched from `main` instead of `platform`
   and caught it themselves. **Name the base branch in every card prompt.**
3. **`CLAUDE.md` is gitignored on purpose** (`.gitignore:56`). It cannot travel on a card branch —
   a worktree agent's correction is invisible in the diff and must be applied by hand. Any card
   whose work makes CLAUDE.md untrue must say so in its report.

---

## Wave 6 — ☑ COMPLETE (2026-07-30, all five merged)

Merge order `l-5 → w-5b → c-1 → c-2 → g-2`. Durable record: the `☑ Wave 6 shipped` block in
ROADMAP.md's Phase 16 section. **Tree: 1,600 → 1,684 tests.**

☑ **G-2** policy engine on the live dispatch path · ☑ **C-1** context compiler (per-role token
budgets; R-7's byte cap retired **and its dead helpers deleted on merge**) · ☑ **C-2** memory
distillation, fail-closed, zero new deps · ☑ **W-5b** artifact diff producer · ☑ **L-5** gateway
spike, answered yes with no code needed.

**The carve-out experiment worked, and is worth repeating.** Three branches edited
`core/dispatch.py`. C-1 (`_hop_message` only) and W-5b (one function + one call site) auto-merged
with **zero** conflicts. G-2 conflicted once — at the artifact construction site — and it was the
dangerous kind: **neither side was correct**, and taking W-5b's verbatim would have silently undone
`pre_output`'s redaction by sourcing the artifact summary from raw subprocess output. **Function-level
ownership is a workable narrowing of the one-owner rule, provided every card reports exactly which
functions it touched** — which is what made this reconcilable.

**Fifth neither-side-is-correct conflict** (after `audit.spec.md`, `role-archetypes.spec.md`,
`specs/README.md`, `pod-dispatch.spec.md`). This is now a *predictable* consequence of running
sibling cards concurrently, not bad luck. Budget merge time for it.

---

## Wave 7 — ☑ COMPLETE (2026-07-31) — and with it, the whole Platformization program

Merge order `c-3-c-5 → g-3 → cl-3`. Durable record: the `☑ Wave 7 shipped` block in ROADMAP.md's
Phase 16 section. **Phases 14–18 are all closed. 38 cards across 7 waves.**

**Tree at close:** 1,684 → **1,735 tests** (`pytest` exit 0, zero FAILED/ERROR), 18/18 goldens
byte-identical, **21 specs** / 0 warnings, 37 commands, ~22,880 lines, `ruff` + `ruff format` +
`mypy --strict` (62 files) clean, `metrics.py --check` in sync across all five claims.

☑ **C-3 + C-5** (`0381e22`) durable task ledger + self-maintaining conversation registry — one
branch, not two · ☑ **G-3** (`5e71330`) high-risk classification on two real docket-launched paths
· ☑ **CL-3** (`31dadbb`) post-program sweep, 4 symbols deleted from 97 examined.

**Integrator commits this wave:** `997e5c8` dependency floors corrected + `floors` CI job ·
`77c4367` spec-count guard aligned to the blocking validator · `bb0de2c` the three high-risk
helpers deleted · `9d02d4f` distillation failure kind reported.

### Four lessons, in the order they cost something

1. **"Wire the unused function" can be the wrong instruction.** G-3's card named
   `resolve_command_action`. Wiring it proved it was unwireable: it resolves `ask`/`allow` for a
   command string, and that decision belongs to the daemon's exec gate (D-15), which keys on
   binary path and has no hook to consult docket. `match_high_risk` was the function that *could*
   be called. **The card was right about the defect and wrong about the fix** — the agent caught
   this and said so, which is the only reason it was caught.
2. **A dead function next to the code that fixed dead code is worse than elsewhere.** Deleting
   `resolve_command_action`/`is_high_risk`/`high_risk_bins` was not tidiness: leaving a
   never-called ask/allow resolver one function away from Phase 15's whole point would have
   published the opposite lesson.
3. **Two guards were checking the wrong set while reporting success** — the same shape as Phase
   14's vacuous `metrics.py --check`, found again twice in one day. The dependency floors had
   never been resolved-and-tested (`typer>=0.12` fails 216 tests; `pydantic>=2` fails 56 modules
   at import). `metrics.py` and `validate-specs.sh` disagreed on how many specs exist because one
   used a suffix filter the other didn't. **Both are now pinned by a job or a test that fails on
   bad input.** The recurring tell in all three: a number nobody had ever seen go red.
4. **Carve-outs need disjoint regions, not merely different names.** C-3 and C-5 were queued as
   separate cards with a note offering "one owner or a carve-out". Neither was available — they
   write from the *same five* functions. Merging them into one branch was cheaper than any
   scheduling trick, and both siblings then auto-merged with zero conflicts.

### The scheduling decision, kept for the next program

The queued board offered two options — one dispatch owner, or a repeat of wave 6's function-level
carve-out. **Neither applies to a pair like C-3/C-5.** They do not merely share a *file*; they
write from the **same lifecycle points** — task claim, hop persist, task finalize. A carve-out
only works when the regions are disjoint, and these are the same five functions. Split, they would
have produced a guaranteed hand-resolved conflict in the one file that has cost the most to merge
all program. They shipped on one branch.

**The carve-out that did apply** — G-3 vs C-3/C-5 in `core/dispatch.py`, genuinely disjoint
regions, declared before dispatch so the merge was predictable. It held exactly: every hunk landed
where declared (verified by reading the diff's hunk headers, not by trusting the reports), and all
three branches merged with **no code conflict**.

| Branch | Owns in `core/dispatch.py` | Owns elsewhere |
| --- | --- | --- |
| `pc/g-3` | the `pre_output` guardrail block inside `_execute_unit` **only** | `core/security.py`, `edges/adapters/system.py`, `cli/_gates.py` |
| `pc/c-3-c-5` | `_claim_next_task`, `_persist_hop`, `_finalize_task`, `_touch_claim`, `_apply_result` **only** | `core/memory.py`, `core/conversations.py`, `serve.py`, `cli/_doctor.py` |
| `pc/cl-3` | **nothing — the file is off-limits**; findings inside it are *deferred to the register*, not edited | everything neither sibling owns |

CL-3 sweeps the whole tree but may only **delete** in unowned files; anything dead inside a
sibling's file is recorded in the register with file/symbol/evidence for the integrator to apply
after that sibling merges. This is the wave-6 lesson generalized: C-1 could not delete R-7's dead
helpers because they sat outside its carve-out, and the integrator removed 56 lines by hand on
merge. A precise deferred finding is worth as much as a deletion, and it is the only shape of this
card that does not conflict with both siblings.

### ☑ Dependency floors — CLOSED 2026-07-31 (integrator, off-card)

Deferred since Phase 14 because measuring it needed network access. Network came back; measured.
**Two of the six advertised floors were false**, and the guard note's "do not raise the floors
blind" turned out to be the right instinct for the opposite reason — they needed *raising*, and
only measurement could say by how much.

| Bound | Was | Now | Evidence |
| --- | --- | --- | --- |
| `typer` | `>=0.12` ✗ | `>=0.13` | typer 0.12.x + modern click (8.4.2) raises `TypeError: Secondary flag is not valid for non-boolean flag` on this CLI's `--flag/--no-flag` options. **216 tests failed.** Bisected: 0.12.0 → exit 2, 0.12.5 → exit 1, 0.13.0 → clean. |
| `pydantic` | `>=2` ✗ | `>=2.1` | pydantic 2.0 raises `NameError` on the `model_source` field (protected `model_` namespace) and rejects `Field(discriminator="type")` on the pipeline union. **56 test modules failed to import.** 2.1.0 collects and passes. |
| `rich` | `>=13` ✓ | unchanged | 13.0.0 verified green. |
| `pydantic-settings` | `>=2` ✓ | unchanged | 2.0.0 verified green. |
| `filelock` | `>=3.13` ✓ | unchanged | 3.13.0 verified green. |
| `pyyaml` | `>=6` ✓ | unchanged | 6.0 verified green. |

Verified set — `typer 0.13.0 · rich 13.0.0 · pydantic 2.1.0 · pydantic-settings 2.0.0 ·
filelock 3.13.0 · pyyaml 6.0 · click 8.4.2` — installed into a clean 3.11 venv from
`uv pip compile --resolution lowest-direct`, then run against the **full suite: exit 0, zero
FAILED, zero ERROR**. The corrected bounds re-resolve to exactly that set.

**The fix is the CI job, not the numbers.** `.github/workflows/ci.yml` gains a `floors` job that
repeats the resolve-and-test on every push. Without it these bounds rot again the moment a
dependency ships a breaking release — which is precisely how they got a year out of date. This is
the same lesson as the `metrics.py --check` guard: *a bound nothing tests is a wish, not a
constraint.*

---

## Dead-code register (CL-1, 2026-07-30) — the standing "no legacy code" work list

Produced by a full-tree sweep. **The non-dispatch half is DONE** — CL-2 merged in wave 5; the
three dispatch-local rows belong to W-5. Kept here as the durable record of what was decided and
why, because "we looked at this and chose to keep it" is worth exactly as much as "we deleted it",
and without the record the next sweep re-litigates the same rows.

**Operational note learned here:** `CLAUDE.md` is **gitignored on purpose** (`.gitignore:56`, "AI
assistant dev guidance (kept local, not published)"). It therefore **cannot travel on a card
branch** — a worktree agent that corrects it changes only its own copy, and the integrator must
apply the change by hand in the main worktree. Any card whose work makes CLAUDE.md untrue must say
so in its report; the diff will never show it.

### High confidence — ☑ all fixed (CL-2, except the dispatch row W-5 owns)

| Finding | Location | Blocked by | Note |
| --- | --- | --- | --- |
| ☑ **`core/sync.py` was an entirely dead module** | whole file | **fixed (CL-2)** — kept as the single implementation, `cli/_doctor.py` now calls `check_agent` instead of reimplementing it; `SYNCED_FIELDS` is now iterated rather than shadowed by hardcoded field names | `check_agent`/`check_all`/`Drift`/`SYNCED_FIELDS` have **zero** production callers. `cli/_doctor.py:280-334`'s `_check_drift` reimplements the identical model+sessionKey comparison inline without importing it. **Independently verified: zero `import sync` in `src/`.** Note CLAUDE.md describes this module as the thing that "keeps the two config sources in sync" — the docs and the code disagree. Prefer keeping `sync.py` as the single source and pointing doctor at it. `SYNCED_FIELDS` is dead even *within* `check_agent`, which hardcodes the field names instead of iterating it. |
| ☑ **`HEARTBEAT_FILE` unused; literal hardcoded in 9 files** | `core/memory.py:57` | **fixed (CL-2)** — constant used everywhere, following L-2's `GATEWAY_UNIT` pattern | The string `"HEARTBEAT.md"` is repeated across `cli/_agents.py`, `_pod.py`, `_install.py`, `_context.py`, `_doctor.py`, `cli/__init__.py`. Same shape as the `openclaw-gateway.service` duplicate fixed in L-2. |
| **`print()` inside `core/` — a layering violation** | `core/dispatch.py:1313` | **W-5 owns this** | `print(f"[dispatch] verification skipped...")` breaks the standing rule that `core/`/`edges/` never print; it should return a typed result for `cli/` to render. |
| ☑ **Zero-caller ACL functions** | `edges/adapters/openclaw.py` | **deleted (CL-2)** — `meta_write`, `set_agent_project_key`; verified gone from `src/` and `tests/` | `meta_write` and `set_agent_project_key` have no callers anywhere, tests included. |

### Medium confidence — ☑ all resolved (CL-2): two fixed, three kept with a dated in-code reason

| Finding | Location | Note |
| --- | --- | --- |
| `with_lock()` has no production caller | `edges/store.py:49` | `read_modify_write` has its own independent `_acquire` body rather than calling it; only `test_data_layer.py` exercises it. **Re-check after W-2 lands** — W-2 is reworking the claim/locking path and may add a genuine call site. |
| `docker_ps()`, `git_current_branch()` | `edges/adapters/system.py:~166, ~223` | Zero production callers; each has a dedicated unit test. May be forward-looking scaffolding for a future doctor check rather than abandoned code. Genuinely ambiguous. |
| `validate_policy()` never called by the CLI | `core/policy.py:44` | Implemented and tested, but `cli/_policies.py`'s `_list()` does its own generic JSON parse. Either wire a `docket policies validate` command or remove it. |
| `VerifyResult.total_lines` written, never read | `core/audit.py:206` | Populated at 7 construction sites; no renderer or test reads it. **G-4b owns this** (it is the card already inside `core/audit.py`). |
| `dispatch_all_pods` flagged uncalled | `core/dispatch.py:1684` | **W-5 owns this** — wire it or delete it, and say which in the commit body. |

### Deliberately NOT dead — do not "clean these up"

- `core/security.py`'s `high_risk_bins`/`resolve_command_action`/`match_high_risk`/`is_high_risk` —
  documented in-code **and** in CLAUDE.md as deferred infrastructure for a daemon capability that
  does not exist yet. Intentional, not orphaned.
- `core/pipeline.py`'s `validate_pipeline()` — its own docstring says it awaits W-2's wiring.
- `edges/adapters/openclaw.py` importing `core/models.py`/`oc_models.py`/`runtime_driver.py` — a
  documented schema-only exception (pure typing modules), **not** a layering violation.

### Confirmed false positives (dynamic access — checked, not dead)

`cli/__init__.py`'s ~35 `cmd_*` functions (Typer-registered) · `serve.py`'s
`do_POST`/`do_HEAD`/`log_message` (`BaseHTTPRequestHandler` overrides) ·
`ConversationStatus.waiting`/`.done` (constructed dynamically from `--status`) · every
Pydantic `model_config` · `RuntimeDriver` Protocol members (used via runtime `isinstance`).

**Swept and clean:** `scripts/` (all referenced), `templates/policies/*.json` (all seeded via the
glob copy), no unconditional skips, no vacuous tests.

### Still owed — all of it now W-5's

The ~76 `_oc.AgentRunResult(...)` test call sites → `TurnResult`, the ad-hoc-double → `FakeDriver`
sweep, the legacy `CostTotals`/`DayRecord` decision, plus the two dispatch-local rows above
(`core/dispatch.py`'s `print()` and `dispatch_all_pods`). W-2 unblocked them; W-5 owns
`core/dispatch.py` and the dispatch-adjacent test families this wave.

**Confirmed resolved (CL-3, 2026-07-31)** — see the wave 3-6 section below: every row in this
list, and every "medium confidence" row above, now has a real, verified production caller.

---

## Dead-code register — wave 3-6 sweep (CL-3, 2026-07-31)

Re-ran CL-1's full-tree method against everything waves 3-6 added on top of the CL-1 baseline
(`5f73e30`..`910a557`, ~4,100 inserted lines across 38 files) — the scope CL-2 explicitly left
open (it covered waves 3-5's non-dispatch half only). Method: every top-level function/class/
constant added since CL-1 (97 symbols) plus every method on a class among them, checked with
`command grep -rn "<symbol>" src/ tests/ specs/ docs/ scripts/` for non-definition, non-test
references. Per this wave's file-ownership split, deletions below are limited to files neither
G-3 nor C-3/C-5 own; `core/dispatch.py` was swept read-only (fully off-limits for edits this
wave — both siblings are in it) and its findings are recorded as deferred.

### Deleted (high confidence — zero callers anywhere, verified)

| Symbol | Location | Evidence |
| --- | --- | --- |
| `step_id_of()` | `core/orchestrator.py:81-83` (3 lines) | Zero references anywhere in `src/`/`tests/`/`specs/`/`docs/` — not even its own test file. `PlannedUnit`/`PlannedGroup` (the two members of the `PlannedNode` union it exists to abstract over) are accessed via plain `.step_id` attribute access everywhere it matters (`core/orchestrator.py`'s own `render_plan`, `core/dispatch.py`'s hop-loop, `tests/python/test_orchestrator.py`) — the helper was never wired to a caller that needed the abstraction. |
| `BlueprintRegistry.__contains__()` | `core/blueprints.py` (was lines 231-233, 3 lines) | Zero callers. Built symmetrically with `core/archetypes.py`'s `ArchetypeRegistry` (which has a real `"producer" in registry`-style caller in `tests/python/test_archetypes.py`), but no code ever does `name in blueprint_registry` — there is no `docket blueprints` listing surface to need it. |
| `BlueprintRegistry.items()` | `core/blueprints.py` (was lines 237-238, 2 lines) | Zero callers. Same shape as `ArchetypeRegistry.items()` (which IS called, by `cli/_roles.py:61,143` for `docket roles list/validate`) but `core/blueprints.py` has no CLI listing command to call it. |
| `BUILTIN_BLUEPRINT_ORDER` | `core/blueprints.py` (was line 216, 1 line) | Zero production callers — only referenced by its own test file (`tests/python/test_pod_blueprints.py`, which used it in two assertions). Mirrors `core/archetypes.py`'s `BUILTIN_ROLE_ORDER`/`STARTER_ROLE_ORDER`, which ARE wired into `docket roles list`'s display (`cli/_roles.py:68-69`) — blueprints has no equivalent `docket blueprints list` command, so the display-order constant was never consumed. Textbook "seam shipped for a producer that never arrived" (built by the same convention as the archetypes registry, one card over). |

Test fallout (expected, per the card): `test_pod_blueprints.py::TestRegistry::test_builtin_order`
deleted — it tested only `BUILTIN_BLUEPRINT_ORDER`'s own value, nothing else, so it dies with the
constant. `test_get_blueprint_known_roundtrips` (same class) is **not** deleted — its assertion
(every built-in blueprint's name round-trips through `get_blueprint`) is real coverage — it now
iterates `bp.load_registry().names()` instead of the deleted constant, matching the pattern the
test right above it already uses. Net: **1,684 → 1,683 tests.**

### Confirmed resolved since CL-1's register closed (no action — dated evidence for the record)

Every row CL-1 left open with "re-check later" or "ambiguous, may be forward-looking" now has a
real, verified production caller. This is the register earning its keep — recorded here so the
next sweep doesn't re-litigate them:

| Finding (as CL-1/CL-2 left it) | Now | Evidence |
| --- | --- | --- |
| `with_lock()` — "re-check after W-2 lands" | Resolved | `edges/store.py:83`'s `read_modify_write` now calls `with with_lock(path):` directly — exactly the call site CL-1 predicted W-2 would add. |
| `git_current_branch()` — "genuinely ambiguous... may be forward-looking" | Resolved | `core/dispatch.py:835`, inside W-5b's `_implementer_diff_probe`: `diff_ref = _sys.git_current_branch(cwd) or None`. One wave later than CL-2 kept it, exactly as this card's brief cited. |
| `validate_policy()` — "never called by the CLI" | Resolved | G-2 (wave 6) wired it into `docket policies validate` (`cli/_policies.py:178,197,213`). |
| `VerifyResult.total_lines` — "written, never read" | Resolved | G-4b (wave 5) wired it into `cli/_audit.py:73`'s tamper-check message (`"...FAILED at line {result.break_at.line} of {result.total_lines}"`). |
| `core/dispatch.py`'s `print()` layering violation | Resolved | W-5 (wave 5) replaced it with the typed `HopResult.verification_skipped` flag (`core/dispatch.py:177-183`); `cli/`'s renderer prints the notice now, not `core/`. |
| `dispatch_all_pods` | Resolved | W-5 deleted it outright — `core/dispatch.py:2286-2293` carries the dated removal comment, pinned by `test_dispatch_all_pods_no_longer_called_unguarded_in_serve`. |
| `AgentRunResult` alias | Resolved | Fully deleted (`edges/adapters/openclaw.py:906-912`'s comment documents the removal); only 3 historical/comment mentions remain tree-wide, zero live references. |
| Ad-hoc-double → `FakeDriver` sweep | Resolved | `FakeDriver` (`tests/python/fakes.py`) is now the shared fixture across 7 test modules. |
| Legacy `CostTotals`/`DayRecord` decision | Resolved (predates this card's scope — Phase 18 L-1) | Kept deliberately as the stable public shape `cli/_cost.py`/`cli/_doctor.py`/`core/dispatch.py` depend on, now a pure translation of the RuntimeDriver port's `UsageTotals` (`core/utils.py:90-97`'s docstring records the decision). Not part of waves 3-6, included here only because the old "still owed" row pointed at it. |

### Checked specifically per this card's brief — kept, not dead

- **`core/handoff.py`'s `notes` field** — still written by no producer (confirmed:
  `core/dispatch.py` never sets it), but it is live schema: in `HandoffArtifact.DROP_ORDER`, in
  `render()`'s conditional, in `_EMPTY_VALUES`. A schema field with no producer yet is not a dead
  code path — its own docstring already says "reserved" and dated (W-5b). Do not delete; do not
  read it as populated data either (see the "known-open gaps" section below).
- **`core/handoff.py`'s `from_legacy_output()`** — has two real production callers:
  `core/dispatch.py:187` (`HopResult.__post_init__`'s backfill) and `core/dispatch.py:884`
  (`_hop_from_record`'s pre-W-5 record replay path). Not dead.
- **`cli/_pod.py`'s `build_pod()`** — looked at first glance like it might be superseded by the
  newer `build_pod_from_blueprint()` (W-7), since `docket add`'s interactive path now calls the
  latter. It is not superseded: `build_pod_from_blueprint` calls `build_pod` internally
  (`cli/_pod.py:601`) as its underlying primitive, and `build_pod` is still the direct, real
  entry point for `docket pod add full` and ~50 test call sites that exercise pod provisioning
  without a blueprint. Wrapped, not replaced.
- **`cli/__init__.py`'s `cmd_pipeline`** — flagged by the automated sweep as having zero non-test
  references (only its own test calls it directly); confirmed false positive — it is
  Typer-registered via `@app.command("pipeline", ...)` immediately above its definition
  (`cli/__init__.py:1337-1341`), the same pattern as the ~35 other `cmd_*` functions the register
  already documents as confirmed-not-dead.

### Medium confidence — flagged, not deleted (struct fields, not symbols)

Two typed-result fields are populated with real data but have no production reader today — the
same shape as CL-1's `VerifyResult.total_lines` finding, which sat unread for a full wave before
G-4b gave it one. Given that precedent, deleting these now risks the exact false negative CL-1
avoided by leaving `total_lines` for a later card to claim:

| Field | Location | Note |
| --- | --- | --- |
| `CancelOutcome.killed_pids` | `core/runs.py:76` | `cancel_run()` builds the full pid list and returns it (`core/runs.py:324`), but `cli/_runs.py`'s `_cancel` only renders `.ok`/`.message` (a count), and the audit-log entry logs `len(killed)`, not the list. Only `tests/python/test_run_cancellation.py` reads the field itself. No HTTP `/runs/<id>/cancel` endpoint exists yet that might want the exact pids. |
| `DistillResult.failure_kind` | `core/memory.py` (in `core/memory.py` — **C-3/C-5-owned this wave, not edited**) | Populated from the driver's `TurnResult.failure_kind` at the one construction site, but `cli/_agents.py`'s `_run_distillation`/`_maintain_distill` only ever read `.error` (the string), never `.failure_kind`. Only `tests/python/test_memory_distillation.py` reads it directly. Recorded here rather than acted on because the file is owned this wave. |

### Deferred findings inside sibling-owned files (for the integrator, after G-3 / C-3-C-5 merge)

Swept read-only per this wave's file-ownership split — nothing below was edited. Both are minor
(struct-field level, not whole symbols) and low-risk to leave for the next sweep if the owning
card doesn't touch the exact lines:

1. **`core/runs.py:76` `CancelOutcome.killed_pids`** — see the table above. `core/runs.py` itself
   is not owned by either sibling, but the *decision* of whether this is worth trimming belongs
   with whoever next touches `docket runs cancel`'s rendering — flagging here rather than
   deleting per this card's "judgment required" rule, since the precedent (`total_lines`) argues
   for patience over deletion.
2. **`core/memory.py` `DistillResult.failure_kind`** — see the table above. `core/memory.py` is
   C-3/C-5-owned this wave; if their conversation-registry/task-durability work ends up touching
   `_run_distillation`'s error rendering anyway, this is the moment to either wire `failure_kind`
   into the CLI message (e.g. distinguishing a timeout from a malformed reply) or drop the field
   — not before, since `core/dispatch.py`'s off-limits status this wave meant it could not be
   cross-checked against how `TurnResult.failure_kind` is rendered elsewhere for consistency.

No findings to defer in `core/security.py`, `edges/adapters/system.py`, or `cli/_gates.py`
(G-3's files) — `high_risk_bins`/`resolve_command_action`/`match_high_risk`/`is_high_risk` are
already correctly tracked as "deliberately not dead, awaiting G-3's wiring" in the section above
and in ROADMAP's wave 7 table; re-flagging them here would just be re-litigating G-3's own card.
Likewise `core/conversations.py`, `serve.py`, and `cli/_doctor.py` (C-3/C-5's other files) were
read in full for this sweep and showed no new orphans introduced by waves 3-6 — `cli/_doctor.py`'s
`_check_drift` now correctly delegates to `core/sync.py`'s `check_agent` (CL-2's fix, still
holding), and `core/dispatch.py`'s off-limits `_UnitOutcome`/pre_output block were checked and
have real, heavily-used call sites — nothing to hand off there either.

---

## Phase 19 — docket owns the runtime (opened 2026-07-31)

**Goal, in the user's terms:** stop depending on OpenClaw so docket has control of every layer —
reusing robust libraries where they help, but **keeping control of guardrails and tool handling**.
Decision **D-19** in ROADMAP §6.

**Scope ruling (2026-07-31, from the user): clean break, no compatibility layer.** docket is
pre-1.0 with no external installs to protect, so this phase does **not** stand a second runtime up
beside the daemon and ships **no** migration path. The OpenClaw driver, the ACL, the daemon's
config file and every shell-out to the `openclaw` binary are **deleted**; `docket install` is
reimplemented to provision a docket-native home from scratch. Local installs are **re-created, not
upgraded**. This supersedes this phase's first draft, which sequenced a per-agent migration and
kept the daemon installed throughout — legacy carried for nobody.

### The finding that decides the architecture

docket ships **four** guardrail policy templates hooked on `pre_tool_call` — `block-destructive`,
`high-risk-credentials`, `high-risk-deploy`, `high-risk-payment` — and **not one has ever been
evaluated.** `core/policy.py` defines the hook, `validate_policy` accepts it, the templates ship in
the wheel, and `core/dispatch.py` says in three places that it stays "daemon-gated, never evaluated
here."

That is the whole argument. docket already owns the governance stack — policy engine (3 hooks, 2
live), approval store with three channels and fail-closed timeout, high-risk classifier, hash-chained
audit, per-hop traces, worktree/port/scratch isolation. All of it can only act *between* turns,
because the daemon owns what happens *inside* one. **Owning the loop is not new scope; it is the
missing half of work already shipped.** The single most valuable guardrail docket has is currently
dead code.

### Verified preconditions (measured 2026-07-31, not assumed)

| Check | Result |
| --- | --- |
| Local llama-server does native tool calling | **Yes** — returned a well-formed `tool_calls` for a `calc` tool |
| `pre_tool_call` exists as a first-class hook | **Yes**, with 4 shipped templates and zero evaluations |
| `RuntimeDriver` port ready for a 2nd driver | **Yes** — 7 methods, built by L-1 for exactly this |
| MCP client present? | **No** — docket ships an MCP *server* (10 tools); the client side is new |
| New deps needed for inference | **None** — OpenAI-compatible chat completions is plain HTTP/JSON |

### Measured blast radius of the break (do not re-estimate from memory)

| Surface | Size |
| --- | --- |
| ACL functions/classes to delete or re-home | **82** in `edges/adapters/openclaw.py` (1,600 lines) |
| `src/` modules importing the ACL | **22** |
| test modules mentioning openclaw | **62 of 91** |

### What actually replaces each daemon capability

Nothing may be quietly dropped in the name of "no legacy" — this table is the completeness check.

| Daemon capability today | docket replacement | Card |
| --- | --- | --- |
| Inference call | OpenAI-compatible HTTP, stdlib | P19-1 |
| Tool execution | `core/tools.py` gated registry | P19-2 |
| In-turn exec approval gate | `pre_tool_call` + existing approval store | P19-3 |
| Session persistence / transcript | `core/session.py` (docket-owned, durable) | P19-4 |
| The turn loop itself | `core/agent_loop.py` + `DocketDriver` | P19-5 |
| Agent registry (`openclaw.json`) | docket-owned `fleet.json` via `edges/store.py` | P19-6 |
| Token/cost usage from session JSONL | real `usage` counts off the API response | P19-4 → P19-7 |
| Auth profiles / provider config | `docket keys` + docket-owned provider config | P19-7 |
| Gateway systemd unit | not needed — `docket serve` already exists | P19-7 |
| Telegram channel | docket-owned bot | P19-8 |

### The architecture

```text
docket OWNS (control plane -- never delegated to a library)
  core/agent_loop.py     the turn loop: call model -> receive tool_calls -> gate -> execute -> feed back
  core/tools.py          tool registry + dispatch; EVERY call passes the gates below
  core/policy.py         pre_input (live) | pre_tool_call (finally live) | pre_output (live)
  core/approval.py       human-in-the-loop, 3 channels, fail-closed on timeout
  core/security.py       high-risk action classes, allowlist, argument-aware at last
  core/audit.py+trace.py hash-chained audit, per-tool-call traces
  core/session.py        turn history + compaction (NEW; docket already owns memory/ledger/registry)

docket RENTS (protocol only -- no library sees a control decision)
  inference   OpenAI-compatible /v1/chat/completions  -> stdlib urllib, zero new deps
  tools       MCP client (official SDK, already an optional extra) -> pluggable tool servers
  isolation   containers / git worktrees              -> already wrapped in edges/adapters
```

**Why no agent framework.** LangGraph/CrewAI/AutoGen own the loop, so they own the interception
points. Adopting one moves docket's guardrails into a third party's callback API — the same
dependency being escaped, with a new vendor and a worse audit story. It also contradicts the
product's own positioning ("an ops/control plane, not an agent framework").

**Why MCP for tools.** It makes the tool set pluggable without docket implementing every tool, it
reuses an SDK already declared as an optional extra, and docket stays the dispatcher — so
`pre_tool_call` fires on every call regardless of which server provides the tool. Built-in tools
(read/write/edit/bash) still land in `core/tools.py` behind the same gate.

### Wave A — the runtime (additive; the tree stays green throughout)

**P19-1 · `core/llm.py` port + `edges/adapters/llm.py` client** — *DONE (`5ec051c`) · M*
Typed chat port in `core/` (`ChatMessage`, `ToolCall`, `ChatResponse`, `ChatBackend` Protocol),
OpenAI-compatible implementation in `edges/` over stdlib `urllib` — **zero new dependencies**, and
the same core-is-pure-typing / edges-does-I/O split `runtime_driver.py` already uses. Reports the
response's real `usage` token counts: docket's first non-estimated token numbers. Failure modes map
onto the existing `FailureKind` vocabulary so `core/dispatch.py`'s retry policy needs no changes.

**P19-2 · `core/tools.py`: the gated tool registry** — *DONE (`75c2b04`) · M*
Tool schema (JSON-Schema, as the model expects it), registry, and **one** dispatch chokepoint every
call goes through — there must be no second path. Ships the built-in set
(`read`/`write`/`edit`/`glob`/`grep`/`bash`). Bash **parses its arguments**, not just the binary
path — the gap the daemon's allowlist structurally could not close.

**P19-3 · Turn on `pre_tool_call`** — *DONE (`9814da4`) · S, and the point of the phase*
Wire the hook into P19-2's chokepoint so the four shipped templates finally evaluate. `deny` blocks
and writes an audit entry; `require_approval` routes to the existing store and fails closed on
timeout. Acceptance, test-pinned: a `block-destructive` policy actually blocks an `rm -rf` tool
call, and `high-risk-deploy` catches `git push` **by argument** — the deferred backlog item since
Phase 13.

**P19-4 · `core/session.py`: turn history + compaction** — *DONE (`08c5c11`) · M*
docket already owns HEARTBEAT, the conversation registry and memory logs; this adds the in-turn
message history the loop needs. Durable per `agent:<id>:<project>` session key, written through
`edges/store.py`. Compaction reuses C-1's budget compiler and C-2's distillation. Retires the
daemon's session JSONL as the source of usage data.

**P19-5 · `core/agent_loop.py` + `DocketDriver`** — *DONE (`71b792f`) · L*
The loop: compose context -> call model -> receive `tool_calls` -> **gate** -> execute -> feed
results back -> repeat until a stop condition (final message, tool-call cap, token budget, timeout).
`edges/adapters/docket_runtime.py::DocketDriver` implements `RuntimeDriver` on top of it, so
`core/dispatch.py`, the pipeline executor and every existing caller are unchanged.
**After this card the daemon is unused — not yet uninstalled.**

### Wave B — the removal (this is what "no legacy" means)

> **Re-sequenced 2026-07-31:** P19-6 was pulled forward into **wave 10** (it is disjoint from the
> runtime-capability cards and the spine should start immediately); P19-7 and P19-8 are **wave 11**.
> The card text below is the durable definition — the live schedule is the wave-10 block and the
> sequencing table further down.

**P19-6 · docket-native home + fleet registry** — *moved to wave 10 · M*
`~/.openclaw/` -> `~/.docket/`; agent registration, channel bindings, gates/isolation flags and
model defaults move out of `openclaw.json` into a docket-owned `fleet.json` through
`edges/store.py`. **The dual-source problem disappears with it:** `core/sync.py`,
`core/oc_models.py` and `doctor`'s config-drift check are **deleted rather than ported** — with one
source of truth there is nothing left to drift.

> **Split into P19-7a + P19-7b (integrator, 2026-08-03).** Measured before dispatching rather than
> estimated from the card text: **44 files** under `src/` mention `openclaw`, **23** import the ACL,
> and the ACL itself is **1,549 lines / 72 functions**. That is too large for one agent to keep
> coherent, and it bundles two different risks — *flipping the runtime* and *deleting the old one*.
> The seam is exact: `_oc.default_driver()` is the **single** point that decides which runtime
> executes a hop (`core/dispatch.py` ~1207 and ~1399), so the flip can be verified on its own before
> anything is deleted. Splitting there buys an integration checkpoint at the most consequential
> moment in the phase.
>
> **P19-7a · The runtime cutover** — *IN-PROGRESS · M · wave 11*
> `default_driver()` returns `DocketDriver`, so production pod-dispatch hops execute on docket's own
> gated loop. Moves the four remaining docket-owned constants (`MODEL_REGISTRY_FILE`,
> `ARCHETYPE_REGISTRY_FILE`, `PROJECTS_DIR`, `AUDIT_LOG`) under `DOCKET_HOME`. Deletes nothing.
> **Walks straight into wave 10's trap** — it moves four more constants across the
> `OPENCLAW_DIR`/`DOCKET_HOME` boundary that silently de-isolated the suite last time, so rule 10's
> snapshot proof is mandatory and `test_docket_home_isolation.py`'s third test is *expected*
> to fire until `_DOCKET_HOME_PATHS` is extended. Extend the list; never weaken the guard.
>
> **P19-7b · Delete the ACL; reimplement install/doctor/cost** — *TODO · L · wave 11, after P19-7a*
Delete `edges/adapters/openclaw.py` and every `openclaw` shell-out, auth-profile read, gateway
restart and version probe. Reimplement `docket install` to provision a docket-native home with no
external daemon; re-point `doctor`, `gates`, `keys`, `auth`, `cost` and `context` at docket-owned
state. `openclaw` leaves the dependency list, CLAUDE.md and the README.
**Acceptance: `command grep -ril openclaw src/` returns nothing but a historical note.**

**P19-8 · Channels: docket-owned Telegram** — *TODO · M · wave 11 (was BLOCKED; the clean break decides it)*
With no daemon there is no daemon channel to fall back on, so docket owns the bot: long-poll over
stdlib HTTP, bound to the existing approval store and pod delegation. This is what finally makes
Telegram a **real** docket approval channel — the claim CLAUDE.md has had to explicitly deny since
Phase 15, and G-5's unbridgeable gap closed by removing the other side of it.

### Wave C — hardening

**P19-9 · Sandboxed exec** — *DONE (`fe0d7b0`) · M*
Container/bwrap jail for bash-class tools, reusing `edges/adapters/system.py`'s docker wrappers and
the existing worktree/port/scratch isolation.

**P19-10 · MCP client: pluggable tool servers** — *DONE (`3d3e3ed`) · M*
Consume external MCP tool servers through P19-2's dispatcher. Never a second, ungated path. docket
already ships an MCP *server*; this is the client half.

### Wave 8 record (in flight)

**Shipped: P19-1 (`5ec051c`) + P19-2 (`75c2b04`).** Facts later cards depend on, so they are not
re-derived from memory:

- **Inference needs no new dependency and the local endpoint really does tool-call.** Verified live,
  not stubbed: a tool-calling exchange returned a well-formed call with real `usage` counts, and the
  tool-result round-trip came back `finish_reason=stop`. Two real-server quirks are handled and
  test-pinned — an assistant tool-call turn must be replayed with `content: null` (not `""`), and
  llama.cpp can emit already-decoded dict arguments where the spec says JSON *string*.
- **`TokenUsage` carries counts reported by the endpoint.** These are docket's first non-estimated
  token numbers. Everything prior — `core/context.py` budgets, `maintain check` guards — is a
  bytes/divisor approximation. Do not let the two get conflated in code or in prose.
- **The Phase 13 per-argument gap is closed on the paths docket controls.** `classify_command` reads
  the whole command line and every segment behind `;`/`&&`/`||`/pipe, so `git status` is allowed and
  `git push origin production` asks. The daemon-side half remains impossible, and is moot once P19-7
  lands.
- **`resolve_command_action`'s deletion in G-3 was still correct.** It classified a bare binary name,
  the exact granularity that made this distinction impossible, and it had no possible caller while
  the daemon owned the turn. The new classifier is a different shape with a real enforcement point.
- **Three architectural guards now hold the chokepoint invariant**: no module outside `core/tools.py`
  imports the handlers, `dispatch_tool` itself calls the gate, and `edges/adapters/toolbox.py` holds
  no policy vocabulary. All three were verified red against planted drift.

- **`pre_tool_call` fires.** The four shipped templates evaluate for the first time since Phase 11,
  against a **pinned canonical render** (`render_tool_call`: `"<name> <key>=<json-value> ..."`) — that
  render is a contract every policy pattern depends on, not an implementation detail, so it is
  test-pinned. Policy and command classifier are combined most-restrictive-wins, mirroring
  `core/policy.py`'s own `_RANK`.
- **Two shipped policy patterns could never have matched anything, and now do.** P19-3 verified rather
  than assumed it: `block-destructive`'s `\.env\b.*write` and `\.ssh\/\s*write` require the path to
  appear *before* the verb, which no natural render produces. Both were fixed to match either order.
  **This is what "shipped but never evaluated" costs** — nobody had ever run these against real input.
- **The policy engine gates tools the command classifier cannot see.** A `write` call to `.env` is not
  a shell command, so `classify_command` never inspects it; the hook does. That is the argument for
  having both, and it is test-pinned.
- **In-turn approval blocks and fails closed.** `wait_for_approval` (new, in `core/approval.py`) is the
  in-turn counterpart to dispatch's async `waiting_approval`: the model is blocked on this exact
  answer, so there is nowhere to return to. Timeout resolves the record to **denied** through the same
  helper the expiry sweep uses — never left dangling. `TOOL_APPROVAL_TIMEOUT` is 120s, deliberately
  short against dispatch's 300s hop budget so a grant still leaves time for the tool to run; the async
  `APPROVAL_TIMEOUT` stays 900s because nothing is blocked on it.
- **Compaction's real trap is tool-call atomicity.** An assistant message carrying `tool_calls` and the
  `tool` messages answering it are one unit; split them and every endpoint rejects the next request.
  `plan_compaction` only ever moves whole units, and `compact_session` re-validates its own output
  before persisting. Failure to summarise leaves the stored history untouched (fail closed, per C-2).

**Scheduling, and how it went.** P19-3 and P19-4 ran in parallel — disjoint footprints
(`core/tools.py` + `core/approval.py` + policy templates vs. a new `core/session.py`), each in its
own worktree, per the Phase 14 contention rule. Both auto-merged with **zero conflicts**; the one
shared file (`config.py`, both adding constants) was verified after the merge to still carry both
cards' additions rather than trusted to have merged cleanly. Every load-bearing claim in both
cards' reports was re-verified by the integrator planting the drift independently: the policy hook
being consulted, the approval timeout failing closed, the `.env` pattern fix, and compaction's
unit atomicity all went red on demand. P19-5 depends on both and follows.

### Wave 9 ownership map (in flight)

Three cards in parallel. `core/tools.py` is now the contention hotspot the way `core/dispatch.py` was
in Phase 14, so ownership is **function-level**, not file-level, and is stated here rather than left
to goodwill:

| Card | Owns | Explicitly may not touch |
| --- | --- | --- |
| **P19-5** loop + driver | `core/agent_loop.py`, `edges/adapters/docket_runtime.py` (both new) | all of `core/tools.py`, `toolbox.py`, `system.py`, `llm.py`, `session.py` — import only |
| **P19-9** sandboxed exec | `toolbox.py`, `system.py`, **and only** `ToolContext` + the `bash` registration in `core/tools.py` | `dispatch_tool` / `evaluate_tool_call` / `render_tool_call` — P19-3's gate logic stays byte-stable |
| **P19-10** MCP client | new client modules under `edges/adapters/` + `core/` | **all** of `core/tools.py` — works through the public `Tool`/`ToolRegistry.register` API |

Each appends to `config.py` in one contiguous commented block; that file auto-merged cleanly in wave
8 and is checked after merge rather than trusted.

**The P19-10 constraint worth remembering:** an MCP tool registers with `kind="write"`, never
`"exec"` — `"exec"` routes into the shell-command classifier, which expects an `args["command"]` an
MCP tool does not have, and would classify every such call as an empty command. `"write"` is not
"ungated": the `pre_tool_call` hook fires for every tool kind, which is exactly why renting MCP as a
transport does not cost docket its guardrails.


**Wave 9 outcome.** All three merged. **The daemon is now unused, not yet uninstalled** — that was
P19-5's job and it is done. Findings worth keeping:

- **Truncation and compaction interact.** P19-5 found that persisting a length-truncated assistant
  message which requested tool calls would create exactly the orphaned-tool-call state P19-4's
  compaction post-conditions exist to forbid. A truncated response is therefore neither dispatched
  **nor persisted**. Neither card could have found this alone.
- **`cost_usd` stays 0.0 in `DocketDriver`, deliberately.** Real token counts are recorded; turning
  them into dollars where `docket cost` reports *recorded spend* would convert an estimate into a
  billing claim. Pinned by a test that goes red if a future card fabricates one.
- **`provision`/`teardown` are honest no-ops** with `supports_provisioning=False`, rather than
  returning `ok=True` for work that does not exist. `teardown` deliberately does not guess at deleting
  sessions from a bare `agent_id` — a session is keyed by the full `agent:<id>:<project>`.
- **Docker needs an explicit container kill on timeout.** P19-9 verified empirically that killing
  `docker run`'s process group leaves the container alive under `dockerd` — it is a thin client. bwrap
  needs nothing extra (its pid namespace tears down with its first process).
- **A sandbox that silently degrades is worse than none.** `run_bash` reports the backend that actually
  ran (`[sandbox: none (docker unavailable, bwrap unavailable)]`), kept distinct from "a jail is
  possible on this host". Opt-in, default off — a filesystem jail can break a call the gate would allow.
- **MCP tools are namespaced `mcp__<server>__<tool>`,** so a remote server naming its tool `bash` lands
  at `mcp__evil__bash` and cannot shadow the gated built-in. Proven with a hostile fake server.
- **Server-supplied tool descriptions are screened** through the existing `prompt-injection` policy on
  `pre_input` before registration — that text is attacker-controlled and ends up in a model's prompt.
  `block`/`require_approval` both refuse registration, since there is no human-approval channel for
  static catalog text.

**Integration findings (the merge itself).** `config.py` conflicted — both P19-5 and P19-10 appended a
constants block — and was resolved by keeping **both**, then verified by importing the module and
asserting all eleven constants from waves 8-9 exist. **`specs/README.md`'s status table had six stale
version cells**, some drifting since wave 7, plus a missing row; it was regenerated from the spec
headers rather than hand-patched. That is integrator check #1 paying for itself again: a roll-up table
edited by several branches at once holds no single correct side.

**P19-10 widened one of P19-2's guards** (the toolbox-import allowlist) to admit two files that
reference only the inert `ToolOutcome` type, and added a narrower guard in its place. The integrator
re-verified that replacement by planting a real handler-function import — it fired.

### ☑ Wave 10 — COMPLETE (2026-08-02, all four merged)

Merge order `p19-11 -> p19-12 -> p19-13 -> p19-6`. **Tree: 2,026 -> 2,096 tests**, 18/18 goldens,
24 specs / 0 warnings, `mypy --strict` clean (71 files — `sync.py` + `oc_models.py` deleted,
`fleet.py` added). Four cards ran in parallel with **zero code conflicts** outside the one
`config.py` collision the ownership map predicted; it was resolved by keeping both blocks and then
*importing the module* to assert all 16 constants survived.

**The finding no card could have made alone.** P19-6 decoupled `DOCKET_HOME` from `OPENCLAW_DIR`.
Before it, the two were the same physical directory, so **every test that repointed `OPENCLAW_DIR`
for hermeticity isolated docket's own state for free**. Afterwards it did not — and the card
isolated exactly *one* of the ten constants that changed meaning (its own `FLEET_FILE`), while
writing a docstring that correctly described the danger for that one. A full `pytest` was writing
real approval records, trace JSONL, `docket-conversations.json` and `port-allocations.json` into
the developer's actual `~/.docket`. Found by **snapshotting the directory either side of a run**,
not by reading code. Two of the leaking constants (`PORT_ALLOC_FILE`, `CONVERSATIONS_FILE`) have no
env override at all, so no test could have opted out even deliberately.
Fixed in `conftest.py` (`_isolate_docket_home`) + guarded by
`tests/python/test_docket_home_isolation.py`, whose third test reads `config.py`'s source and
fails if a *future* `DOCKET_HOME`-derived constant is added unisolated — because a guard is only as
good as the set it checks (integrator check #3).

**A reporting failure worth institutionalising: three of four agents claimed a gate failure was
somebody else's.** P19-6, P19-11 and P19-12 each reported "3 pre-existing `mypy` errors in
`mcp_client.py`, confirmed against the `platform` baseline"; two said they verified it with `git
stash`. The baseline is clean (`Success: no issues found in 71 source files`) and so is every merge.
It was an artifact of their worktree environments. No code impact — but **"seen it fail" was applied
to their own new guards and not to a red they inherited.** Wave 11 briefs must require: *if a gate
is red, prove the attribution on a clean checkout of the base commit before calling it pre-existing.*

**Carried open (integrator, decide before wave 12):** `fetch` refuses every domain by default
(`FETCH_ALLOWED_DOMAINS=()`) while `python3`/`node`/`git clone` reach the network unattended, so the
**inspectable path is the closed one and the escape hatch is the open one**. Verified at the gate:
both `fetch` and the `python3` one-liner return `decision='allow'`; `fetch` is then refused *inside
the handler*, which also means the domain decision never reaches the policy engine and **no approver
can ever be asked** "may this agent fetch example.com?". P19-12 sharpened it — `reviewer`/`lead` now
have `fetch` but no `bash`, so their only egress tool is one that refuses everything.
**Proposed fix:** a non-allowlisted domain should resolve to `ask` at the gate, not a handler
refusal. Fail-closed on the safe path while the unsafe path stays open is the wrong shape.

### Wave 10 dispatch record (kept — the ownership map that produced zero conflicts)

**Change from the earlier plan:** wave 10 was three runtime-capability cards with the removal
deferred to wave 11. It now **pulls P19-6 forward** so the removal spine starts immediately — the
daemon still resolves `OpenClawDriver`, and every runtime claim on this board is theoretical until
that flips. P19-6 (state-side) and P19-11/12/13 (runtime-side) touch disjoint trees, so they run
together. P19-7 stays in wave 11 because it cannot start until P19-6's registry exists.

#### Ownership map — function-level where a file is hot (state it, do not leave it to goodwill)

| Card | Owns | Explicitly may not touch |
| --- | --- | --- |
| **P19-6** fleet registry | `edges/adapters/openclaw.py` (writes redirected), new `fleet.json` handling, `config.py` **path constants only**, deletion of `core/sync.py` + `core/oc_models.py` | `core/tools.py`, `core/agent_loop.py`, `core/archetypes.py`, `cli/_mcp.py`, `edges/adapters/toolbox.py` |
| **P19-11** `fetch` tool | new `edges/adapters/fetch.py`, **and only** the registration entry for `fetch` in `core/tools.py` | `dispatch_tool` / `evaluate_tool_call` / `render_tool_call` — P19-3's gate logic stays byte-stable. Also all of `toolbox.py` |
| **P19-12** role tool sets + identity | `core/archetypes.py`, `core/identity.py`, `core/agent_loop.py` (prompt composition) | **all** of `core/tools.py` — compose through the public `ToolRegistry.without()` API only |
| **P19-13** MCP servers CLI | `cli/_mcp.py`, `core/mcp_tools.py`, `edges/adapters/mcp_client.py`, docs | **all** of `core/tools.py`; any built-in tool registration |

**`config.py` will conflict again** — P19-6 adds path constants while others may add tool constants.
That is expected and the resolution is settled: **keep both blocks, then import the module and assert
every constant exists**. Do not resolve it by reading the diff and assuming (wave 9's lesson).

#### Dispatch protocol (identical for every card in the wave — no per-card negotiation)

1. **One agent per card, one worktree per card, branch `pc/<card-id>`** (e.g. `pc/p19-12`). Merge
   into `platform`, never into `main`.
2. **Read before writing:** ROADMAP.md's Phase 19 section, §2 (Python ground truth), §4.5
   (architectural principles + the anti-overengineering "we will NOT" list), §6 decisions
   **D-19/D-20/D-21/D-24**, `CLAUDE.md`, and this card's own ownership row above.
3. **Stay inside your ownership row.** If a card genuinely needs a file another card owns, **stop and
   report it** rather than editing it — the integrator re-slices the wave. Three waves have now run
   clean on this rule; every conflict we did hit came from a file nobody had assigned.
4. **Do not edit `ROADMAP.md`, `TODO.md`, `README.md` or `CLAUDE.md`.** They are integrator-owned.
   **Report what you shipped; do not update the board.** Phase 14 lost real time to roll-up tables
   conflicting on nearly every merge.
5. **A guard is not evidence until you have seen it fail.** Any test a card adds to protect an
   invariant must be run against **planted drift** — break the thing on purpose, watch it go red,
   restore, watch it go green — and the report must say which drift was planted. Three separate
   guards in this repo were green while verifying nothing; this is the only rule that catches that.
6. **Never regenerate a golden to make a diff go away.** Only P19-13 adds CLI surface, so only P19-13
   regenerates goldens, and it must explain the diff line by line. For every other card the 18 goldens
   stay byte-identical.
7. **Definition of done** is the list in *"How to use this board"* above — full gate suite green
   (`ruff check` · `ruff format --check` · `mypy src` · `pytest` · `golden verify-all` ·
   `validate-specs.sh`), the card's spec updated with a version bump + changelog entry and a Status
   line matching **what actually shipped**, commit as `Type: description` with **no** AI/Claude/
   Co-Authored-By trailer, and the diff grepped for real names and `/home/<user>` paths.
8. **Report back:** what shipped, what you deliberately did **not** ship and why, every load-bearing
   claim with the command that proves it, and anything you found in a sibling card's territory
   (do not fix it — report it).
9. **Never call a red gate "pre-existing" without proving it on the base commit.** Added after wave
   10, where **three of four agents** reported the same three `mypy` errors as pre-existing — two
   claiming they had confirmed it with `git stash` — against a baseline that was clean. It was
   their worktree environment. If a gate is red, check out the base commit **clean** (a fresh
   worktree, not a stash in a dirty tree) and re-run there before attributing it to anyone else. A
   stash does not restore deleted files, added files, or a changed environment, so it is not a
   baseline.
10. **Isolation is part of done.** If your card changes where docket stores state, snapshot the real
    directory (`find ~/.docket -printf '%p %s\n' | sort`) before and after a full `pytest`, and prove
    the suite created, modified and removed nothing there. Wave 10's worst defect was invisible to
    every gate: the suite was writing into the developer's home and every check stayed green.

#### The cards

**P19-6 · docket-native home + fleet registry** — *TODO · M · the removal spine starts here*
`~/.openclaw/` -> `~/.docket/`; agent registration, channel bindings, gates/isolation flags and model
defaults move out of `openclaw.json` into a docket-owned `fleet.json` through `edges/store.py`.
**The dual-source problem disappears with it:** `core/sync.py`, `core/oc_models.py` and `doctor`'s
config-drift check are **deleted rather than ported** — with one source of truth there is nothing left
to drift. Per the clean-break amendment to D-19, **write no migration code**; local installs are
re-created, not upgraded.

**P19-11 · `fetch` tool** — *TODO · S (was M) · decision D-23, re-scoped*
**Re-scoped by D-24: ship the tool, drop the lockdown.** The gap is measured, not assumed:
`curl`/`wget` correctly ask, but `python3 -c "import urllib..."`, `node` and `git clone <url>` are
**allowed unattended** — both interpreters are on the curated allowlist because agents need them
constantly, and both are universal escape hatches. Ship a first-class `fetch` tool (domain allowlist,
size cap, timeout, gated like every other tool) so there is an **inspectable** egress path.
**Do NOT ship** the opt-in `--network none` / `--unshare-net` lockdown: it is off by default, breaks
`npm install`/`pip`/`git clone` when on, and buys a config option rather than a guarantee.
**Instead, this card must make the docs say the true thing** — egress is open, `fetch` is the
inspectable path, and the escape hatches are named. An honestly-open gate beats one that reads as
closed.

**P19-12 · Per-role tool sets + identity composition** — *TODO · M*
Two omissions P19-5 recorded honestly rather than papering over. (1) `ToolRegistry.without()` exists
and is tested but **nothing composes it per role** — a Reviewer is *told* not to edit code instead of
being *unable* to, which is a strictly weaker guarantee and the exact distinction docket sells.
(2) The loop **composes no system prompt at all**: `SOUL.md`, the docket-owned persona
(`core/identity.py`) and `WORKFLOW_AUTO.md`'s resume contract never reach the model. Wire both;
role -> toolset belongs in `core/archetypes.py` as **data, not a branch**. Acceptance must include a
test that a Reviewer registry genuinely lacks `write`/`edit` — asserted by dispatching and getting a
tool-not-found denial, not by inspecting a dict.

**P19-13 · `docket mcp servers` CLI + browser recipe** — *TODO · S*
P19-10 shipped `add_mcp_server`/`load_mcp_tools` as tested, uncalled library functions. Give them a
CLI (`docket mcp servers add/list/remove`) and document the payoff: **browser support is
configuration, not code** — point it at the Playwright MCP server and P19-10's client gates those
tools exactly like a built-in (namespaced `mcp__<server>__<tool>`, so a remote server cannot shadow
`bash`). Same for web search. This is what "rent the protocol" buys, and it is why **browser
automation is on the never-build list** (D-24). Adds CLI surface, so this card **regenerates goldens**
and must explain the diff.

### Sequencing (updated 2026-07-31)

| Wave | Cards | Mode | Gate to the next wave |
| --- | --- | --- | --- |
| 8-9 | ☑ P19-1 -> P19-2 -> **P19-3** -> P19-4 -> P19-5 -> P19-9/P19-10 | done | — |
| 10 | ☑ P19-6 · P19-11 · P19-12 · P19-13 | done (2026-08-02) | — |
| 11 | ☑ P19-7a -> P19-7b -> P19-8 | done (2026-08-03) | **PHASE 19 CLOSED** — acceptance grep clean |
| 12 | ☑ P21-1 -> P21-5 | done (2026-08-03) | — |
| 13 | ☑ **P20-2** · ~~P20-4~~ | done (2026-08-04) | **BOARD CLEAR** — P20-2 shipped; P20-4 was a phantom card (W-4 had already closed it). Everything else was cut/deferred by D-24 |

**Wave 11 closes Phase 19. Wave 12 is Phase 21 (the substrate — the factory's actual product line).
Wave 13 is all that survives of Phase 20.** Anything not in this table was cut or deferred by D-24;
do not let it get quietly re-claimed.

**P19-3 was the milestone that mattered** — the moment docket's guardrails stopped being advisory.
**P19-7 is the moment the dependency is actually gone**; do not report Phase 19 complete before that
grep is clean.

Wave A is additive — every card lands on a green tree with the existing suite passing. The daemon
stops being *used* at P19-5 and stops being *present* at P19-7. Wave C is optional depth once the
loop is real.

**P19-3 is the milestone that matters** — the moment docket's guardrails stop being advisory.
**P19-7 is the moment the dependency is actually gone**; do not report the phase complete before
that grep is clean.

### Measured caveat, unchanged

The local Qwen answered a one-word prompt in **107 s**. Owning the loop does not make the model
fast; model choice per role stays a separate decision from runtime ownership. Nothing in this phase
may be sold as a performance improvement.

---

## Known-open gaps carried forward (do not let these get quietly re-claimed)

From Phase 14's honest record — these are **still true** until the cards above close them:

- ~~Cancellation of an in-flight hop and parallel hop execution are not implemented~~ — **closed by W-2**
  (`docket runs cancel`; `agent_run` now spawns a process group there was previously nothing to kill).
  Three narrower gaps replace it: `runs.cancel` writes **no audit entry** (W-4 owns it), resuming a task
  that crashed mid-parallel-group **re-runs the whole group**, and approval gates are **rejected inside a
  parallel group** as a configuration error.
- `docket models set/preset/reset` still write **no audit entry** (G-4 follow-up — **G-4b owns it this wave**).
- Enforcement exists **only** in the pod-dispatch lane — spend or actions from a Telegram session or
  direct daemon use are entirely ungated, per D-9's "docket orchestrates hops" boundary.
- ~~Per-argument daemon enforcement for allowlisted bins (`git`, `npm`) still does not exist~~ —
  **closed on docket's own paths by P19-2/P19-3 (wave 8)**: `classify_command` reads the whole command
  line and every segment behind `;`/`&&`/`||`/pipe, so `git status` is allowed and `git push origin
  production` asks. The daemon-side half remains impossible by construction (its allowlist gates by
  binary path) and becomes moot at P19-7, when the daemon goes.
- `maxReworkCycles` has no dedicated CLI setter (set via the internal `meta-set` path).
- **`CLAUDE.md` had drifted badly and was re-trued by hand on 2026-07-30** (it is gitignored, so no
  card could have fixed it): it still advertised "Lobster Workflows" as a core capability nine
  merges after W-3 deleted that surface, and quoted 847 tests / 17 goldens against a tree with
  1,684 and 18. **Nothing guards this file** — `metrics.py --check` covers README only. Re-read it
  for truth at the end of each wave, or give it its own guard.
- ~~Hops still exchange concatenated raw text~~ — **closed by W-5**, and W-5b gave
  `files_changed`/`diff_ref` real producers. **`notes` still has no producer** and is documented as
  reserved. Do not read a populated-looking schema as populated data.
- ~~The policy engine is not on any live path~~ — **closed by G-2** (wave 6): `install` seeds the
  baseline policies, `pre_input` evaluates at enqueue, `pre_output` on every hop output, and the
  existing `cli/_metrics.py` reader needed no changes. ~~**Still daemon-gated:** `pre_tool_call`~~ —
  **closed by P19-3 (wave 8)** for the calls docket dispatches itself: `core/tools.py`'s chokepoint
  evaluates the hook, so all three hooks are now live. Precise scope, do not overstate it: nothing in
  the pod-dispatch hop path calls that dispatcher yet (P19-5 wires it), and the daemon's own
  tool-calling loop stays unbridged until P19-7 deletes it. `resolve_command_action` stayed deleted —
  P19-2's `classify_command` is a different, argument-aware shape with a real enforcement point.
- Hops still exchange **concatenated raw text**, not structured artifacts (W-5, in flight this wave).
- ~~The runtime dependency floors in `pyproject.toml` are unverified~~ — **closed 2026-07-31, and
  the suspicion was right: two of the six advertised floors were false.** `typer>=0.12` failed 216
  tests (click 8.4.2 incompatibility) and `pydantic>=2` failed 56 test modules at import; both were
  raised to what actually runs (`typer>=0.13`, `pydantic>=2.1`). The measured floor set —
  typer 0.13.0 / rich 13.0.0 / pydantic 2.1.0 / pydantic-settings 2.0.0 / filelock 3.13.0 /
  pyyaml 6.0 — now passes the full suite, and a `floors` CI job resolves `--resolution
  lowest-direct` and runs pytest against it so the claim stays real. **Do not raise or lower a
  floor without re-measuring** — an untested floor and a wrong floor look identical until someone
  installs.
- ~~`scripts/validate-specs.sh` reports two spec references on one line as a broken reference~~ —
  **fixed by the integrator in `771f622`**, along with a second defect found next to it: `check_todos`
  ran its loop in a pipe subshell, so every warning increment was discarded and a spec full of TODO
  markers still reported zero warnings. Both were reproduced before being fixed.

---

### W29-C1 — recover a corrupt Docket JSON primary from its valid backup

**Status:** DONE (2026-09-02) · **Size:** M · **Owner:** @codex-w29-c1

**Measured trigger:** at `de08206`, two `edges.store.write_json` calls create a valid
`state.json.bak`; replacing `state.json` with `{broken` leaves the backup present, but
`edges.store.read_json` raises `JSONDecodeError`. Threshold: one deterministic, concurrency-safe
recovery path for a representative Docket-owned registry. Observed: zero.

**Goal:** make the store chokepoint recover a malformed primary from a parseable owned backup under
the existing per-directory lock, quarantine the malformed bytes for diagnosis, and return the
recovered document without allowing two readers/writers to perform competing restores.

**Non-goals:** no generic filesystem backup service, JSONL audit/trace recovery, remote backup,
schema migration, silent reset to `{}`, repair of a missing primary, or change to the persisted JSON
shape. Do not route around `edges/store.py` or add a second writer.

**Owns:** `src/docket/edges/store.py::{read_json,read_modify_write,_atomic_write}` plus the smallest
private recovery helpers; new `tests/integration/test_store_recovery.py`; new
`specs/data/docket-store.spec.md`. `specs/README.md`, public docs, and central rollups are forbidden.

**Acceptance / RED oracle:** start with a temporary registry produced by two real `write_json`
calls. Corrupt only the primary, retain its valid `.bak`, then read through the public store API and
through one real CLI consumer such as `docket runs list`. Both must recover the prior complete
document; the restored primary must be valid JSON with mode `0600`; the malformed bytes must remain
in one bounded quarantine file; and no invented empty state may appear. A valid primary must win
without changing any byte even when its backup is stale or malformed. Missing/corrupt backup must
raise one typed actionable error and preserve every input byte. A barrier race between recovery and
a writer must serialize, retain one complete generation, leave no `.tmp`, and never replace a valid
backup with malformed bytes. The pre-change test must fail specifically at the recovery assertion.

**Focused validation:** new recovery tests repeated (`--count=20` when the plugin is available, or
an explicit in-test barrier loop); neighboring `test_store_writer.py`, `test_run_registry.py`, and
the selected CLI consumer tests; owning spec validation; Ruff/format and strict mypy. Final gates:
full pytest, 18 goldens, ShellCheck, metrics, deterministic smoke, diff/privacy/clean checks.

**Handoff:** report the corruption fixture, quarantine naming/retention rule, lock boundary, byte
identity for no-op/error cases, focused results, and any registry whose caller bypasses the store.

**Shipped evidence:** RED `4b796de` and GREEN `b673645` recover a corrupt primary from a valid
backup under the directory lock, preserve exact malformed bytes in one bounded `.corrupt`, restore
mode `0600`, retain valid-primary and unusable-backup byte identity, and preserve existing
`JSONDecodeError` caller compatibility through typed `StoreRecoveryError`. All 11 focused cases,
including 20-repetition reader/writer barriers, pass on merged `main`.

### W29-C2 — ship an extractable, artifact-installed ten-minute starter

**Status:** DONE (2026-09-02) · **Size:** M · **Owner:** @codex-w29-c2

**Measured trigger:** `examples/` contains configurations, pipelines, and two single Python files,
but no starter directory, dependency lock, self-contained instructions, or copied-outside-checkout
journey. `examples/runtime_embed.py` cannot run in the root environment because `docket-runtime` is
not installed. Threshold: one credential-free starter that a new user can copy, install from exact
artifacts, run, and inspect within a 600-second test timeout. Observed: zero.

**Goal:** create a small extractable starter that uses the installed `docket` CLI to show one
governed tool mutation, an approval pause and grant, a persisted typed terminal handoff, paired
trace identity, run-registry inspection, and audit verification against a deterministic loopback
model.

**Non-goals:** no hosted provider, subscription, port 8081, runtime-adapter dependency, framework
template zoo, package-index publication, web UI, Docker requirement, or duplication of the full
smoke harness. The starter teaches the installed CLI journey; it does not claim that the narrower
`docket-runtime` facade owns Docket's run registry or arbitrary framework governance.

**Owns:** `examples/starter/**`, new `tests/agent/release/test_starter_journey.py`, and new
`specs/acceptance/starter-journey.spec.md`. It may import existing fixture utilities only when they
are part of an installed public package; it must not import `tests/` or the source checkout.
README/docs indexes and central metrics are forbidden until C6.

**Acceptance / RED oracle:** build the exact root wheel and sdist once, copy only
`examples/starter/` to a fresh directory outside the checkout, install one exact root artifact into
a fresh Python 3.11 environment, and invoke one documented starter command with a fresh
`DOCKET_HOME`. Within 600 seconds it must mutate exactly one declared workspace file after one
approval, persist a typed terminal handoff, and let the installed public CLI inspect the matching
run (`docket runs list/show`), paired trace (`docket trace export`), and valid audit chain
(`docket audit verify`). Pre-approval and denial runs must leave the target bytes unchanged. The
journey must work with network disabled after artifact installation and with no API key. The
pre-change test fails because the extractable starter path does not exist.

**Focused validation:** starter contract and artifact journey on Python 3.11/Linux, plus the
existing release journey, release-artifact, run-registry/CLI, trace, audit, and public link/example
tests; owning spec; Ruff/format/mypy. Final gates match C1 and include the deterministic smoke.

**Handoff:** report cold/warm elapsed time separately, exact artifacts and Python version, public
command, resulting state/trace/audit locators, network/credential posture, and cleanup performed.

**Shipped evidence:** RED `b138f25` and GREEN `16ef7bc` add the extractable
`examples/starter/` journey. Its Python 3.11 test copies outside the checkout, builds and installs
the exact root artifact, runs without provider credentials or post-install network, proves denial
and approval/grant mutation boundaries, persists a typed handoff and paired trace, and verifies the
public run registry and audit chain. The merged artifact journey passes in 18.6 seconds.

### W29-C3 — define the adoption benchmark schema and deterministic runner

**Status:** DONE (2026-09-02) · **Size:** M · **Owner:** @codex-w29-c3

**Measured trigger:** repository search finds zero benchmark/baseline files. `docket metrics` reports
session success, duration, estimated cost, and guardrail trips independently, but there is no
versioned scenario result tying completion, provider-reported tokens, estimate basis, prevented
violations, approval latency, crash/restart recovery, and handoff failure to the same run. Threshold:
one deterministic machine-readable schema plus runner and invalid-input oracle. Observed: zero.

**Goal:** add a dependency-light benchmark runner that consumes fixed scenarios and durable Docket
records, emits canonical per-attempt JSONL plus a deterministic aggregate JSON document, and keeps
measurement provenance explicit enough for review or reproduction.

**Non-goals:** no telemetry backend, hosted benchmark service, leaderboard, competitor ranking,
price synchronization, model-quality claim, new product metrics subsystem, or claim that fake-model
completion predicts real-model quality.

**Owns:** `benchmarks/harness.py`, `benchmarks/schema.json`, `benchmarks/README.md`, base scenario
fixtures under `benchmarks/fixtures/`, new `tests/agent/release/test_adoption_benchmark.py`, and new
`specs/validation/adoption-benchmark.spec.md`. Product runtime files and public/central docs are
forbidden. C4 may extend the spec and scenario directory only after C3 merges.

**Acceptance / RED oracle:** a fixed scenario/seed must emit stable identifiers and normalized
fields for scenario version, source commit/artifact hash, runtime/configuration, deterministic vs
live measurement class, attempts/completions, provider-reported input/output/total tokens,
tool-call count, prevented policy violations, approval latency, crash/restart recovery, handoff
failures, stop reason, and trace/audit locators. Every dollar value must carry `estimate=true` and a
versioned pricing source/assumption; unknown pricing must be `null`, never fabricated zero. Raw
prompts, secrets, home paths, approval tokens, and unredacted tool arguments must be absent. Invalid,
partial, duplicate, or mismatched records fail closed without overwriting a prior result. The
aggregate must be reproducible from JSONL alone. The pre-change test fails because no schema/runner
exists.

**Focused validation:** schema unit/property cases, two identical deterministic runs compared after
normalizing measured elapsed time, malformed/redaction cases, and metrics/trace/run fixture parity;
owning spec; Ruff/format/mypy. Final gates match C1.

**Handoff:** report schema version, field provenance map, normalization boundary, estimate labeling,
redaction scan, repeatability result, and exact command needed by C4.

**Shipped evidence:** RED `a556fdc` and GREEN `2bf46a5` add schema version `1.0.0`, a
dependency-light runner, documentation, and a minimal public-artifact fixture. All 11 focused cases
prove deterministic identifiers/serialization, strict task/session/trace/audit joins, explicit
estimate provenance, redaction, failure atomicity, and byte-identical JSONL-only aggregation.

### W29-C4 — add adversarial governance and crash/recovery benchmark scenarios

**Status:** DONE (2026-09-03) · **Size:** M · **Owner:** @codex-w29-c4

**Measured trigger:** 31 focused release, crash-resume, and policy-template tests pass, but zero
whole-journey scenario emits the Wave 29 benchmark record. Unit behavior exists; adoption evidence
does not. C4 is deliberately fixture-first and must not reimplement policy, approval, audit, or
resume logic.

**Goal:** drive the C3 runner through representative allowed, policy-denied, approval-denied,
approval-granted, malformed-handoff, hard-crash/resume, and corrupt-primary/backup-recovery journeys
using public actions and durable state, then emit comparable records.

**Non-goals:** no prompt-injection detector claim beyond the configured policy fixture, destructive
real command, live provider, chaos platform, arbitrary fault injection, new retry semantics, or
product fix hidden inside a benchmark scenario.

**Owns after dependencies merge:** `benchmarks/scenarios/**`,
`tests/agent/release/test_adoption_adversarial_recovery.py`, and an additive C4 section/version bump in
`specs/validation/adoption-benchmark.spec.md`. Product code is forbidden. If a scenario exposes a
new product defect beyond C1, stop and split a named defect card with its own spec/RED evidence.

**Acceptance / RED oracle:** each scenario starts from a fresh home/workspace and names its intended
side effect. Policy/approval denial must record one prevented violation and preserve target bytes;
grant must mutate exactly once; the crash case must persist completed hops, resume only unfinished
hops, and reach one terminal run; corrupted primary with valid backup must recover through C1 and
retain the quarantined evidence; malformed handoff must become a counted failure rather than a
completion. Repeat the table at least three times with unique state/ports and no cross-run leakage.
Every result must validate under C3 and reference verifiable trace/audit state.

**Focused validation:** C3 harness tests plus all new scenarios, `TestCrashRecovery`, policy-template,
approval, store-recovery, audit-chain, and handoff tests; owning spec; Ruff/format/mypy. Final gates
match C1.

**Handoff:** report the scenario table, public action, observable outcome, mutation/no-mutation
hashes, restart boundary, record locators, repetitions, and any split defect card.

**Shipped evidence:** RED `fcdff9a` and GREEN `0c8dac7` add seven versioned case definitions and a
credential-free scenario driver. Twenty-one isolated journeys prove allowed/granted/crash
single-write behavior; policy/approval denial byte identity; counted malformed handoff; retained-hop
crash resume; public `runs list` recovery with exact quarantine bytes; C3 schema validity; and
byte-identical normalized output across three repetitions. The merged 184-case C4/C5 focused suite,
Ruff/format/strict mypy, and all 27 specifications pass; no product defect was split.

### W29-C5 — publish truthful support, deprecation, governance, and succession policy

**Status:** DONE (2026-09-03) · **Size:** S · **Owner:** @codex-w29-c5

**Measured trigger:** `SECURITY.md` supports only `main` and rejects older tags;
`COMPATIBILITY.md` describes Python/platform support; neither defines a release-support or
deprecation window. There is no governance document. `.github/CODEOWNERS` names one account and the
90-day Git history resolves to one underlying human author identity. Threshold: one truthful policy
for support/deprecation and one maintainership/succession path. Observed: zero complete policies.

**Goal:** state who decides and releases, how contributors become maintainers, how breaking changes
and deprecations are announced during beta, which versions receive security fixes, and what happens
if the sole maintainer becomes unavailable—without inventing a committee or promised staffing.

**Non-goals:** no legal entity claim, foundation, CLA, paid support SLA, fake maintainer roster,
branch-protection mutation, release publication, or claim that beta has LTS support.

**Owns:** new `GOVERNANCE.md`, new `SUPPORT.md`, and new
`tests/agent/truth/test_project_policy_truth.py`. Existing `SECURITY.md`, `COMPATIBILITY.md`, README,
CODEOWNERS, and central indexes are read-only inputs; C6 owns their links/summary alignment.

**Acceptance / RED oracle:** public policy must explicitly name current single-maintainer reality,
decision and release authority, contributor-to-maintainer criteria, conflict/security escalation,
support matrix, pre-1.0 breaking-change/deprecation notice rule, succession/transfer-or-archive
procedure, and inactivity trigger. It must link only real channels and files, never promise an
unverified response time beyond `SECURITY.md`, and never name a successor who has not accepted.
Repository-relative links must resolve. Counterexample fixtures reject claims of multiple active
maintainers, LTS branches, guaranteed compatibility, or a governing foundation. Pre-change RED:
both policy files are absent.

**Focused validation:** new truth/link tests plus existing public-doc, security-boundary, and
positioning tests; Ruff/format. Final gates match C1.

**Handoff:** report the exact maintainer/support truth, deprecation window, succession trigger,
rejected overclaims, link test, and any item requiring owner consent rather than code.

**Shipped evidence:** RED `ac05dc3` and GREEN `c480e97` publish the current one-maintainer authority,
an evidence-based contributor-to-maintainer path, conflict/security escalation, main-only support,
one-published-beta deprecation notice, and a 90-day transfer-or-archive succession trigger. Eight
policy cases pass, every repository-relative link resolves, and counterexamples reject invented
multiple maintainers, LTS, compatibility guarantees, or foundation governance.

### W29-C6 — generate and publish the reproducible adoption baseline

**Status:** DONE (2026-09-03) · **Size:** M · **Owner:** @codex-w29-c6

**Measured trigger:** Phase 23 requires published completion/cost/safety/recovery evidence; C2 and
C4 produce the first reproducible inputs, while current public prose has no versioned result.

**Goal:** run the starter and scenario matrix from exact artifacts, commit the canonical raw and
aggregate result with provenance, and publish a compact interpretation that distinguishes measured
facts, deterministic-fixture evidence, estimates, failures, and unsupported conclusions.

**Non-goals:** no competitor ranking, dollar-savings promise, benchmark cherry-picking, live-model
requirement, hidden failed trials, regenerated numbers by hand, telemetry/A2A, or feature expansion.

**Owns after dependencies merge:** `benchmarks/results/**`, `docs/ADOPTION-EVIDENCE.md`, relevant
public links/limits in `README.md`, `COMPATIBILITY.md`, `SECURITY.md`, `docs/README.md`, spec indexes,
CHANGELOG entry, and metrics synchronization. It does not own VERSION, Formula, tags, or GitHub
release state.

**Acceptance / oracle:** one command on clean exact artifacts must regenerate byte-identical
normalized records and aggregate for the native starter plus every C4 scenario; elapsed/approval
latency may use a separately identified tolerance field and must never be represented as a stable
byte. The report must include attempts and failures, completion rate, measured tokens, explicitly
estimated or unavailable dollars, prevented violations, approval latency, crash/restart recovery,
and handoff failures. Every claim links to raw data/schema/commit and states that deterministic fake
results are contract evidence, not model-quality evidence. Public truth tests reject rankings,
unlabeled estimates, savings claims, secrets/private paths, and missing failed attempts.

**Focused validation:** complete C2–C4 matrix with two regenerations; schema/redaction/public-link
tests; all specs; metrics; Ruff/format/mypy. Closure gates: full pytest, 18 goldens, ShellCheck,
deterministic smoke, Linux/macOS artifact journeys, diff/privacy/clean checks.

**Handoff:** report artifact/source hashes, scenario/result counts, all failed attempts, normalization
and tolerance rules, published claims/non-claims, metrics delta, and whether C7 may request release
approval.

**Integrated closure evidence (2026-09-03):** `main` contains RED `82a3239` and GREEN `033bb4b`.
The baseline binds source `82a3239980bbda3673fdd8030751f1342bcab132` to wheel SHA-256
`0fe67120737c4d09da3229c1182d8bf5474e96f7077476f997c98f7c67667fce`: eight scenario groups,
nine attempts, five completions, and the four retained failures (`starter`, `policy-denied`,
`approval-denied`, `malformed-handoff`). Only approval-latency and wall-clock fields use the
manifest's 5,000 ms comparison tolerance. Public prose labels this deterministic contract evidence,
keeps dollars unavailable, and rejects model-quality, ranking, savings, or production-rate claims.
The test metric moves 2,522 → 2,536, including the CI-history, floor-harness, and canonical-builder
regressions. Local commit-level gates at `03693a3` pass: 2,528 tests with five expected
skips, 18 goldens, 27 specs, Ruff/format, strict mypy, ShellCheck, metrics, reproducible documentation
assets, deterministic smoke, Linux exact-wheel journey, diff, and privacy. GitHub run `33764191509`
passed both Linux and macOS release-journey jobs, while its
three full-suite jobs exposed two distinct CI defects: depth-one checkout cannot resolve pinned
source `82a3239`, and the floor environment cannot collect the benchmark tests because `jsonschema`
is absent. Commit `c817955` makes the Python, floor, and macOS jobs fetch complete history and adds a
passing regression test. Commit `ca45e38` declares the schema oracle as a test-only dependency,
installs it explicitly in the floor harness without changing runtime floors, and pins that boundary
with a second regression. GitHub run `33788650508` confirms that both defects are fixed, then exposes
one shared exact-artifact defect: its Python 3.11 builder produces wheel SHA-256 `9283d326…256b4`
instead of the published `0fe67120…67fce`, even though the extracted wheel trees are identical.
Commit `f789bc6` preserves the published baseline and makes raw wheel identity independent of the
ambient interpreter: it pins uv-managed CPython 3.14.3 and the complete Hatchling closure, then
recompresses with checksum-verified zlib-ng 2.3.3 at canonical Deflate level 6. Two isolated
regenerations inheriting different `UV_PYTHON` values now reproduce `0fe67120…67fce`; the full suite
passes 2,531 tests with five expected skips, and the complete Python 3.11 dependency-floor suite is
green. Hosted CI run [`33812881329`](https://github.com/yielab/docket/actions/runs/33812881329)
at `37e91a8` closes the remaining gate: its overall conclusion is success; Python, dependency
floors, ShellCheck/spec validation, 18 goldens, metrics, and both Ubuntu/macOS artifact-installed
release journeys pass. The exact-artifact publication oracle therefore reproduces the unchanged
`0fe67120…67fce` wheel in clean Python and floor environments without accepting drift. The advisory
macOS full-suite lane completes with 2,514 passes, 14 skips, and eight separate portability failures
(three Bash-3.2 assumptions, four OpenHands fixture timeouts, and one Linux-only `/proc` path); no
C6 baseline or artifact-journey check fails there. C6 is closed, and C7 may now request the explicit
version/tag publication approval required by its own boundary.

## ☑ WAVE 31 COMPLETE (2026-09-11 to 2026-09-12) — human maintainability: test lanes, comment budget, generated docs (Phase 25, D-36)

**Active since 2026-09-11.** W29-C7 was deferred behind this wave by the maintainer so the
repository is made maintainable before any further publication; Wave 30 waits behind it too.
**W31-C0–C3 run first and sequentially**: C1 moves every test file, so any card that owns a test
path while C1 is open would merge against a moved tree. After C3 merges, W31-C4+ fan out and
W30-C1+ becomes claimable, scheduled by file contention like any other lanes. Decision D-36 and the measured triggers live in ROADMAP
"Planned program — PHASE 25"; the audit and the phase-by-phase plan are
`internal-docs/maintainability-audit-2026-09-11.md` and
`internal-docs/plan-tests-comments-docs-2026-09-11.md` (gitignored; read at `main` `0d3720a`).
The contract every card here implements is `specs/test-framework.md` §"Lanes and placement"
(2.13.0). Two analysis scripts already exist uncommitted in `scripts/maint/` and C0 commits them.

**Activation measurement (2026-09-11, working tree at `0d3720a`, `uv run pytest -q --durations=15`):**

| Metric | Locator | Observed | Threshold |
| --- | --- | --- | --- |
| Default suite wall time | `uv run pytest` | 8 min 12 s (2,377 passed, 5 skipped); **3 min 23 s after C1** | < 90 s after C5; < 5 min after C1 alone |
| Share of wall time in the 15 slowest tests | `--durations=15` | ~257 s, every one a release/evidence/adapter test | those tests out of the default suite |
| Test files that assert on prose, release artifacts, or the agent's own hook scripts | `scripts/maint/test_inventory.py` | 35 files, 8,313 lines, 227 tests (18% of test lines); **17 files, 5,157 lines after C1-C2 and the harness retirement** | in `tests/agent/`, ratcheted against a shrink-only baseline (D-38) |
| Test files touching one subject | `rg -l` over `tests/python` | `serve` in 19 files, `runs` in 17, `tools` in 12 | one unit file per `src/` module, guarded |
| Archaeology in comments/docstrings | `scripts/maint/comment_lint.py src tests` | 20 hits in `src/`, 69 in `tests/` | 0, ratcheted |
| `subprocess` call sites in tests | `rg -c 'subprocess\.(run\|Popen\|check_output)'` | 91 sites in 40 files | 0 in `unit/`; only process-boundary tests elsewhere |
| Board and roadmap volume | `wc -l TODO.md ROADMAP.md` | 4,628 + 3,541 lines; active wave began at line 1642 between closed waves (archive shipped 2026-09-11: ~1,100 + ~810 remain, all of it active or planned) | TODO ≤ 200 once W30/W31 close, ROADMAP ≤ 500, history in `docs/cycles-ended/` |
| Hand-written CLI reference | `docs/commands.md` | 2,247 lines, no drift check; **generated since C6** | generated from Typer, `--check` in CI |
| Functions over 500 lines | `src/docket/core/agent_loop.py::run_agent_turn` 789, `core/dispatch.py::dispatch_task` 703, `::_execute_unit` 501 | 3 | 0 (C8) |

**Execution graph / contention:** C0 → C1 → C2 → C3 strictly sequential (each rewrites paths or
headers across the whole test tree). C4 and C5 are per-module packets and may run in parallel with
each other and with W30 when they do not share a test file. C6 and C7 touch only docs/board/scripts
and are parallel-safe with everything except W30-C5 (central rollups). C8 is one module per branch,
last. **Every card runs with an isolated `DOCKET_HOME`** and snapshots the real `~/.docket` before
and after its focused run.

### W31-C0 — commit the baseline and the two analysis scripts

**Status:** DONE (integrator, `4e6caa0`) · **Size:** S · **Owner:** integrator

**Shipped:** `scripts/maint/test_inventory.py`, `comment_lint.py` and `split_board.py` committed;
`.maint/` gitignored and seeded with `inv/inventory.json`, `inv/moves.tsv`, `comment-baseline.txt`
and `durations-0.txt`. Baseline recorded in the commit body: suite 8 min 12 s (2,377 passed,
5 skipped); 15 slowest ~257 s, all release/evidence/adapter; 35 prose/release/harness files at
8,313 lines and 227 tests; 91 archaeology hits; 91 `subprocess` call sites in 40 files.

**Trigger:** the activation table above is a working-tree measurement; the board contract requires
a locator a later card can re-run. `scripts/maint/test_inventory.py` and
`scripts/maint/comment_lint.py` exist uncommitted and pass `ruff`.

**Goal:** commit both scripts unchanged; add `.maint/` (gitignored) and write
`inventory.json`, `moves.tsv`, `comment-baseline.txt`, and `durations-0.txt` there from the exact
commands in the plan's Phase 0; record the four numbers in the commit body.

**Non-goals:** no test moves, no fixes, no CI change.

**Owns:** `scripts/maint/`, `.gitignore` (one line). **Forbidden:** everything else.

**Acceptance / oracles:** `uv run python scripts/maint/test_inventory.py` prints six lanes whose
line totals sum to the `tests/python` total; `comment_lint.py src tests --summary` ends with the
totals line matching the table; both scripts pass `ruff check`/`ruff format --check`.

**Validation:** ruff; no pytest change expected. **Handoff:** the four artefact paths and numbers.

### W31-C1 — move the suite into lanes and take the agent lane out of the default run

**Status:** DONE (2026-09-11, `351a5f5` merged as `16aa056`) ·
**Size:** M · **Owner:** @sonnet-c1 · **Depends on:** C0 (done)

**Shipped:** 135 test files moved by `scripts/maint/apply_moves.sh`; `tests/python/` deleted;
`conftest.py` and `fakes.py` raised to `tests/`; `--import-mode=importlib` added and the
per-directory `__init__.py` files dropped; default `testpaths` now `unit`, `integration`, `guards`
with an `agent-lane` CI job for the rest. Default wall time 8 min 12 s -> 3 min 23 s (2,393 tests);
agent lane 149 tests in its own job. Twenty destinations differed from the script's proposal, all
recorded in the commit body. The integrator added the docs CI job, fixed ROADMAP's four stale
`tests/python` references, and merged the two scale claims in CONTRIBUTING.

**Deterministic trigger:** at `0d3720a`, `pyproject.toml` `testpaths = ["tests/python"]` collects
every file, including the 18 the inventory classifies as `agent/*`; the 15 slowest tests (257 s of
492 s) are all in that set. Reproduction: `uv run pytest --collect-only -q | tail -1` shows one
flat directory; `--durations=15` names only release/evidence/adapter tests.

**Goal:** review `.maint/inv/moves.tsv` by hand (correct lane and destination per row; suffix
`__<aspect>` where several files target one unit module — C4 merges them); write
`scripts/maint/apply_moves.sh` (git mv per row; `sed` of every old path to its new path across
`src/ specs/ docs/ *.md .agents/ tests/ scripts/ .github/`; move `conftest.py` and `fakes.py` to
`tests/`; delete `tests/python/__init__.py`); set `testpaths = ["tests/unit", "tests/integration",
"tests/guards"]`, `addopts = "-ra -q --import-mode=importlib"`, marker `slow`; add the CI job
`agent-lane` running `uv run pytest tests/agent` with a path filter; update
`test_docket_home_isolation.py`'s path to `tests/conftest.py`; update `tests/run-all-tests.sh`.
`scripts/metrics.py --check` will report the smaller default-suite count: **fix the CONTRIBUTING
claim, not the script**, and say in the commit body that the count now excludes the agent lane.

**Non-goals:** no test content edits, no merges, no deletions, no new guards (C2), no docstring or
comment edits (C3).

**Owns:** `tests/**` (moves only), `pyproject.toml` pytest block, `.github/workflows/ci.yml`,
`scripts/maint/apply_moves.sh`, path strings in `src/` docstrings, `specs/`, `docs/`, `TODO.md`
(paths only — including the W30 cards), `CONTRIBUTING.md` paths and count. **Forbidden:** test
bodies; `scripts/metrics.py`; README.

**RED tests / oracles:** (1) before the move, `uv run pytest tests/agent --collect-only` fails
(no such directory); after, it collects exactly the reviewed `agent/*` rows and the default run
collects none of them. (2) `uv run pytest -q --durations=0` wall time < 5 min and no `agent/*`
node in the default durations. (3) `rg -n 'tests/python' --glob '!.maint/**' --glob '!internal-docs/**'`
returns only `CHANGELOG.md` history lines. (4) `bash tests/golden/run.sh verify-all` byte-identical.
(5) `~/.docket` snapshot byte-identical before and after the full run.

**Validation:** full default suite, `uv run pytest tests/agent`, goldens, ruff/format, mypy,
`validate-specs.sh`, `metrics.py --check` after the claim fix. **Handoff:** the wall time before/
after, the final lane counts, and every TSV row changed from the script's proposal and why.

### W31-C2 — structural guards, lane headers, and one test for removed commands

**Status:** DONE (2026-09-11, `0ed085e` merged as `ab1b488`) · **Size:** M · **Owner:** @sonnet-c2

**Shipped:** four per-removal files replaced by one parametrized `tests/guards/test_removed_commands.py`;
`test_layout.py` maps every unit file to an existing module and every module over 150 lines to a
unit file; `test_lane_headers.py` checks the three constants on every agent-lane file and bans
`subprocess` in `tests/unit/`; `test_agent_lane_budget.py` ratchets the lane against a committed
baseline; a duration hook in `tests/conftest.py` fails a unit or guard test over 2 s and an
integration test over 10 s. `scripts/maint/add_test_headers.py` wrote the skeletons. All six guards
were seen red before green, each pair recorded in the commit body. The lane retirement was left to
the maintainer and is not in this card.

**Found while doing it:** `trace.redact` backtracks quadratically, now W31-C9.

**Deterministic trigger:** at `0d3720a`, four files (`test_tier_shims_removed.py`,
`test_eval_command_removed.py`, `test_team_command_removed.py`, `test_workflow_command_removed.py`;
639 lines, 32 tests) verify that `__main__._REMOVED` entries print a notice — one file per
removal. Nothing enforces that a unit test file names an existing module, that `tests/agent/` stays
bounded, or that `unit/` stays subprocess-free.

**Goal:** `tests/guards/test_removed_commands.py`, one parametrized test over `_REMOVED`
(≤ 60 lines) replacing the four files; `tests/guards/test_layout.py` (every `unit/**/test_X.py`
maps to an existing `src/docket/**/X.py`, `SUBJECT` matches, every `src/` module > 150 lines has a
unit file); `test_lane_headers.py` (`LANE`/`REASON`/`RETIRE_WHEN` present in every `tests/agent/**`
file; no `subprocess` import in `tests/unit/**`, AST); `test_agent_lane_budget.py` (sum of
`tests/agent/**` lines ≤ 4,000); a duration guard in `tests/conftest.py` failing the session when
a `unit/`/`guards/` test exceeds 2 s or an `integration/` test exceeds 10 s. Add `SUBJECT` to every
unit file and the three header constants to every agent-lane file (script writes the skeleton,
the human fills 18 `REASON` lines). To meet the 4,000-line budget, cut ~1,650 lines from the agent
lane: `test_workflow_smoke.py` (1,121 lines testing `scripts/smoke_workflow.py`) and
`test_adoption_benchmark.py` (666) are the named candidates; the human decides which public claims
keep a test and records each retirement in `RETIRE_WHEN` terms in the commit body.

**Non-goals:** no changes to product behaviour; no golden change; no merges of behavioural files
(C4); the existing seven AST guards move unchanged.

**Owns:** `tests/guards/**`, `tests/conftest.py` (duration hook only), `tests/agent/**` headers and
the named cuts, `SUBJECT` lines in `tests/unit/**`, `tests/integration/**` `SUBJECT` lines.
**Forbidden:** `src/`, `specs/` other than `test-framework.md`'s enforcement status, central files.

**RED tests:** each of the five guards must be **seen to fail** before the commit: plant a unit
file with a non-existent subject, a `tests/agent` file without headers, a `subprocess` import in
`unit/`, a 4,001-line total, and a `time.sleep(3)` in a unit test; record each red/green pair in
the commit body. The removed-commands test must fail when one `_REMOVED` key is deleted.

**Acceptance / oracles:** guard failures reproduce as described; the default suite passes; the
agent lane passes at ≤ 4,000 lines; `python -m docket tier` and the other removed verbs still
print their notice (golden or CLI oracle).

**Validation:** full gates plus `uv run pytest tests/agent`. **Handoff:** the five red/green
records, the agent-lane line count, and the list of retired agent-lane tests with their reasons.

### W31-C3 — zero archaeology in comments and docstrings, ratcheted

**Status:** DONE (2026-09-12, `17dc447` merged as `e6819e8`) · **Size:** S · **Owner:** @sonnet-c3

**Shipped:** archaeology across `src/` and `tests/` from 86 hits to zero, with
`scripts/maint/comment-baseline.json` and `tests/guards/test_comment_hygiene.py` holding it there;
the guard was seen red on a planted card id. Rationale was rewritten present-tense, not deleted.
The nine hits the branch could not reach were fixture text in the development-harness file, which
has since been retired, so the baseline is zero rather than nine. Docstring-budget counts stay
ratcheted where they landed; they were never the target.

**Deterministic trigger:** at `0d3720a`, `scripts/maint/comment_lint.py src tests --summary`
reports `archaeology=20` in `src/` and `69` in `tests/`, plus 45 (`src`) and 68 (`tests`) module
docstrings over budget; ROADMAP §3 states the rule but nothing in CI reads it. Reproduction: the
totals line of that command.

**Goal:** run `comment_lint.py src tests --fix` (removes only whole-line comments that carry no
rationale word — 3 lines in `src/`); process the remaining hits one file per packet, rewriting only
the flagged lines and keeping every rationale; shorten test module docstrings to ≤ 6 lines and
test docstrings to one line; commit `scripts/maint/comment-baseline.json` (per-kind counts) and
`tests/guards/test_comment_hygiene.py`, which runs the linter and fails if any count rises above
the baseline. `def-max` for `src/` starts at 12; tests at 3.

**Non-goals:** no rewriting of `src/` docstrings that document contracts; no behaviour change; no
changes to the linter's detection rules beyond documented false positives ("used to <verb>").

**Owns:** comment and docstring lines the linter names in `src/**` and `tests/**`;
`scripts/maint/comment_lint.py` (baseline support only); `tests/guards/test_comment_hygiene.py`;
`CONTRIBUTING.md` comment-policy section (already written; verify). **Forbidden:** code lines.

**RED tests:** the hygiene guard fails when a `# W17-1` comment is planted in `src/`; passes after
removal. `git diff --stat` shows only comment/docstring hunks — reviewer confirms with
`git diff -w | rg '^[+-]\s*[^#"'"'"' ]'` returning nothing outside docstrings.

**Acceptance / oracles:** linter totals `archaeology=0` for both trees; module-docstring counts
at or below baseline; full suite unchanged in pass count.

**Validation:** full gates. **Handoff:** the before/after totals and the per-file list of
rationale lines deliberately kept.

### W31-C4 — one unit file per module: merge history-named and fragmented test files

**Status:** DONE (2026-09-12, split in two: `60a7b1d` merged as `7e2ad99`, `af2ad28` merged as
`d76fb89`) · **Size:** M · **Owner:** @sonnet-c4a, @sonnet-c4b · **Depends on:** C3 (done)

**Shipped:** the trigger below described the wrong work. The aspect suffixes had been assigned by
filename prefix rather than by subject, so six files claimed a module they never exercised. C4a
repointed each at the module its assertions actually reach (`test_archetypes__orchestrator` ->
`test_orchestrator`, `__pod_blueprints` -> `test_blueprints`, `__context_compiler` ->
`test_context`, `test_llm__mcp_tools_in_a_live_turn` -> `test_mcp_tools`, `__session_history` ->
`test_session`, `test_tools__fetch_tool` -> `edges/adapters/test_fetch`, `test_memory__doctor` ->
`cli/test__doctor`) and merged the two genuine memory fragments into one file, all 33 cases
preserved by name. C4b renamed the four history-named files for their subject and split the serve
file that mixed sweep wiring with redaction; `test_hop_carryover` was judged and kept, since hop
carryover is a behaviour rather than a migration.

**Correcting the labels exposed a real gap:** `core/archetypes` and `core/llm` never had unit
coverage. The layout guard had been satisfied by a filename prefix naming a module the file did
not test. Both joined `layout_baseline.txt`; six modules left it, so the ratchet fell by four. No
test was written to paper over it -- a test invented to satisfy a guard is worse than an honest
baseline entry. Collected count 2398 before and after both halves. The integrator repointed nine
references in four specs, ROADMAP, CONTRIBUTING, `core/orchestrator.py` and one integration test.

**Deterministic trigger:** at `0d3720a` the inventory shows six unit destinations fed by several
files (`test_serve.py` ← 8, `core/test_memory.py` ← 3, `core/test_archetypes.py` ← 3,
`core/test_tools.py` ← 2, `core/test_llm.py` ← 2, `core/test_pipeline.py` ← 2) and files named for
events rather than modules (`test_audit_v2`, `test_mcp_sdk_v2_migration`, `test_deferred_gaps`,
`test_legacy_role_parity`, `test_hop_carryover`); 33 test names are duplicated across files.

**Goal:** one packet per destination module, in this order: `serve` → `core/runs` →
`core/memory` → `core/archetypes` → `core/tools` → `core/pipeline` → the history-named files.
Packet input is the module's signatures (`rg -n '^def |^class ' src/docket/<m>.py`) plus the N
test files; output is one file ≤ 800 lines (or `__<aspect>` files), every test function preserved
unless its assertions are an exact duplicate, docstrings one line, no archaeology.

**Non-goals:** no assertion changes; no fixture redesign; no `subprocess` conversion (C5).

**Owns:** the listed test files only. **Forbidden:** `src/`, guards, agent lane.

**RED tests / oracles:** per packet, `rg -c 'def test_'` before and after differ only by the
listed exact duplicates; `uv run pytest tests/unit/<destination>` green; `test_layout.py` green
(no orphan file remains). Whole-suite pass count at the end equals the start minus documented
duplicates.

**Validation:** focused per packet; full gates at the end of the card. **Handoff:** per module,
the function counts before/after and the duplicate list.

### W31-C5 — in-process CLI tests: `subprocess` only where the process boundary is the subject

**Status:** DONE (2026-09-12, `5d2c5e9` + `ec0c319` merged as `dff06b4`; integrator follow-ups
`c9d6436` and `6915baa`) · **Size:** M · **Owner:** @sonnet-c5 · **Depends on:** C1 (done)

**Shipped:** the card's trigger was re-measured at HEAD first, and had already shrunk -- 38 sites
in 18 files, not 91 in 40, because C1's lane move had taken most of them out of the default run.
Nine files spawned `python -m docket` purely to read its output; all nine now invoke the same
`docket.cli.app` the entry point uses through `typer.testing.CliRunner`. Assertions are untouched:
same exit codes, same exact stdout and stderr text, same JSON shapes, confirmed by a byte-for-byte
comparison of in-process against subprocess output for one command. Seven files keep `subprocess`
because the process boundary is what they test: sandboxed exec, run cancellation and its
cooperative variant, implementer worktree isolation, the diff probe, the runtime execution
envelope (a fresh-venv wheel and sdist install) and the live workflow smoke. Two files that looked
like candidates were neither: `test_high_risk_enforcement.py`'s references are inside monkeypatch
and assertion strings, and `test_system_adapter.py` had already moved.

**Sent back once, for shipping the drift the wave exists to remove.** The first pass gave each of
the nine files its own tuple of DOCKET_HOME-derived constants and its own patch helper -- eight
partial, independently drifting copies of `_DOCKET_HOME_PATHS`. The AST guard proves a new
`config.py` constant reaches the canonical tuple; it cannot see eight local copies that were not
updated, so the guard would have been defeated without ever going red. One exported
`repoint_docket_home` helper in `tests/conftest.py` replaced all eight. It names `DOCKET_HOME`,
`FLEET_FILE` and `core/secrets.py`'s `SECRETS_FILE`/`SECRETS_META_FILE` explicitly, each for a
stated reason, then loops the tuple; the secrets pair binds from `DOCKET_HOME` at import rather
than through config at call time, so a caller that does not know that detail would otherwise split
its chosen home in two. The guard was proved, not assumed: a throwaway `DRIFT_PROBE_FILE` in
`config.py` drove `test_the_guard_covers_every_docket_home_derived_constant` red naming exactly
that constant, and removing it returned the guard suite to green.

**The integrator found one more instance after merging** (`6915baa`): `test_data_layer.py`'s
`oc_env` fixture repointed four constants by hand and set a `DOCKET_HOME` environment variable for
the rest. That split worked only while the commands ran as a child process, which re-imported
config from the environment. The conversion made the environment variable inert, so the conversion
made this fixture worse rather than better. It now calls the shared helper, which is a strict
superset of what it set by hand.

**The wall-time oracle was not met, and the card is closed anyway.** Target was under 90 s. The
suite falls from 152-162 s to 117-122 s, measured across four separate post-conversion runs plus
one integrator run on the merged tree -- a real 25 to 30 percent cut, and short of the number.
What remains is not `subprocess` overhead, so no further conversion buys it back; finding where the
remaining two minutes actually go is a measurement task, not this card.

**Collected count unchanged at 2398** (2393 passed, 5 skipped, 0 failed) before conversion, after
conversion, after the dedup and after the integrator's fixture fix. Full gates green on the merged
tree: ruff check and format, mypy, the 18-case golden suite, `validate-specs.sh` 27/27, metrics in
sync. The real `~/.docket` hashed identically either side of the whole card, and `docket doctor`
and `docket list` agree on two pods with no fixture residue.

**Follow-up opened:** W31-C10. The same hand-written repointing shape pre-exists across the tree;
a census found 57 sites setting `DOCKET_HOME` directly, two of them carrying partial constant
lists of exactly this kind. Not folded into this card, which had already been revised twice, and
the sites are not uniform.

### W31-C6 — generated CLI reference and strict docs build

**Status:** DONE (2026-09-11, `4cff59f` merged as `af6a090`; integrator hygiene pass `6796e36`) ·
**Size:** M · **Owner:** @sonnet-c6 · **Depends on:** C0 (done); **ran in parallel with C1**
(disjoint: C1 owns `tests/**`, `pyproject.toml`, `.github/workflows/ci.yml` and the `tests/python`
path strings in `src/`, `specs/`, `docs/DEVELOPMENT-HARNESS.md`; this card owns the CLI-reference
generator and `docs/commands.md`, which carry no such path string)

**Shipped:** `scripts/gen_cli_docs.py` renders the reference from the live Typer registry and
`--check` fails on drift; `docs/commands.md` 2,247 -> 1,475 lines with the per-command prose moved
into the docstrings Typer prints; `mkdocs.yml` + `scripts/mkdocs_hooks.py` build the site under
`--strict` (verified red with a planted dead link); `packages/docket-runtime/docs/api.md` anchors
mkdocstrings; `completions_zsh.golden` regenerated because it freezes the help strings this card
rewrote. The integrator exempted rendered command docstrings from the comment-budget check, since
that text is product surface, and removed the archaeology the moved prose carried in.

**Left for the integrator at C1's merge** (both files belong to C1, which was still in flight):
the `docs` optional-dependency group (`mkdocs>=1.6`, `mkdocs-material>=9.5`,
`mkdocstrings[python]>=0.26`) and a CI `docs` job running `gen_cli_docs.py --check` then
`mkdocs build --strict`. Text is in the C6 handoff.

**Deterministic trigger:** at `0d3720a`, `docs/commands.md` is 2,247 hand-written lines with no
drift check, while `count_commands()` in `scripts/metrics.py` already introspects the Typer app
live; `test_public_release_truth.py` checks Markdown links by hand because no docs build does.

**Goal:** `scripts/gen_cli_docs.py` renders `docs/commands.md` from the Typer registry (groups,
options, help strings, arguments) and supports `--check`, which exits non-zero when the file on
disk differs from what the registry produces; content present in the old file but absent from a
help string moves **into the help string**, so nothing is lost and the source of truth is the code.
`mkdocs.yml` declares a fixed nav: the four guides, the generated CLI reference, the
`docket-runtime` API via mkdocstrings, the spec index, `docs/adr/`, `docs/cycles-ended/`, and the
changelog.

**Non-goals:** no published site until the maintainer enables Pages; no README rewrite (C7); **no
edit to `.github/workflows/ci.yml` or `pyproject.toml`** — C1 owns both this wave, so return the
exact `docs` extra block and the `docs` CI job as text in the handoff and the integrator applies
them; no folding or moving of other docs (follow-up C6b); no retirement of agent-lane tests
(follow-up, after the strict build is wired).

**Owns:** `scripts/gen_cli_docs.py` (new), `docs/commands.md` (regenerated), `mkdocs.yml` (new),
and help strings in `src/docket/cli/**` **only** where content moves out of the old hand-written
reference. **Forbidden:** `tests/**`, `pyproject.toml`, `.github/workflows/**`, `README.md`,
`specs/**`, every other file under `docs/`, and all `core/`/`edges/` code.

**RED tests / oracles:** (1) `uv run python scripts/gen_cli_docs.py --check` exits non-zero
against the current hand-written `docs/commands.md` **before** regeneration, and zero after;
(2) after editing one help string in `src/`, `--check` exits non-zero again until regenerated;
(3) every one of the 37 live commands from `scripts/metrics.py::count_commands` appears in the
generated file, and no retired command does; (4) `uvx --with mkdocs-material --with
'mkdocstrings[python]' mkdocs build --strict` succeeds, and fails when a dead link is planted.
Run (4) with `uvx` so no dependency is added to the tree.

**Validation:** the four oracles above; `uv run ruff check . && uv run ruff format --check .`;
`uv run mypy src`; `uv run pytest -q tests/agent/release/test_public_release_truth.py
tests/integration/test_completions_eval_metrics_help.py`; `uv run python scripts/metrics.py --check`;
`bash tests/golden/run.sh verify-all` (help strings are golden-pinned — if a `help` golden changes
because content moved into a help string, regenerate it and explain the diff line by line).
**Handoff:** the dropped-paragraph list with where each went, the nav, and the exact `docs` extra
and CI job text for the integrator to apply.

### W31-C7 — board and roadmap to size: active wave only, history in CHANGELOG, decisions as ADRs

**Status:** DONE (2026-09-12) · **Size:** M · **Owner:** integrator

**What shipped.** Six long decisions became ADRs with their roadmap rows cut to one sentence and a
link: D-19, D-20, D-23, D-24, D-33 and D-36. D-35 already had `docs/adr/0001-harness-mode.md` but
its row had never been shortened, so that was done too. The "Prioritization ruling" section moved
into ADR 0005, which is D-24's own verdict table and had been referenced from the ADR as "the
section below" — a link that would have dangled. The six closed Wave 29 cards and the whole of
Wave 31 were archived byte-for-byte into `docs/cycles-ended/`, and `split_board.py check` verifies
every archived section is present there and absent from the board.

**CONTRIBUTING.md now carries the rules a contributor cannot otherwise see.** Six working rules and
the comment policy lived only in a gitignored file, which meant nobody outside this machine could
read them. The guard-must-be-seen-to-fail rule, the never-edit-the-counting-script rule, the
prove-pre-existing rule, isolation as part of done, the decaying gap list, and diff scrubbing are
now in the repository, along with the comment policy and the note that `comment_lint`'s exit code
covers archaeology only.

**Line counts, measured.**

| file | before | after | target |
|---|---|---|---|
| TODO.md | 1,357 | 471 before this wave archived | 200 |
| ROADMAP.md | 820 | 705 | 500 |
| README.md | 317 | 260 | 150 |

**Two of the three targets are gated on closures this card cannot perform, which the activation
measurement above already says.** Its board-volume row reads "TODO ≤ 200 **once W30/W31 close**".
Wave 30's five planned cards are 322 lines and Wave 29's remaining card about 70; they archive when
those waves close, not now. The same holds for ROADMAP: the Phase 23 and Phase 24 program sections
are 167 and 79 lines of measured triggers that Wave 29 and Wave 30 are executed from, and they
archive on the same closures. Removing either early would delete the evidence those waves rest on.

**The README's floor is set by a test this card may not edit, and finding that out cost two
rounds.** The first trim reached 231 lines by cutting the "Features" and "Best practices" sections
as duplication of the guarantees, the configuration table and `docs/AGENT-TEAMS.md`. Two agent-lane
tests then failed:
`tests/agent/release/test_public_release_truth.py::test_public_front_door_is_compact_and_visuals_are_reproducible`
requires six named front-door headings including both of those, and
`test_readme_and_compatibility_name_only_the_tested_adapter_configurations` pins six exact phrases
of the adapter-boundary caveat that the rewording had paraphrased away. Two further rounds followed: an earlier trim had broken four `tests/agent/truth` positioning
assertions, and rewrapping the restored caveat put `not` and `framework-neutral` on separate
lines, which a line-based check rejects. Every one of them was
fixed by restoring the README, never by touching a test: this card owns `README.md`, not `tests/`,
and a prose-truth test is the contract rather than the obstacle. The structural test's own bound is
500 lines, which 260 meets comfortably; the card's 150 is not reachable while six named sections
are required, and closing that gap means amending the test under a card that owns it.

**The "Known limits" section was kept whole and untouched.** It is the honest boundary of the
governance claim, and shrinking the file is not worth shrinking that.

**Non-goals held.** No history was deleted, every archived section is byte-preserved with a SHA-256
in `docs/cycles-ended/manifest.json`, no decision was re-litigated, and both roadmap scripts still
work against the smaller files: `context_snapshot.py` still prints the board marker and
`card_packet.py W30-C1` still resolves.

### W31-C8 — split the three functions over 500 lines into named phases

**Status:** SPLIT (2026-09-12) into C8a and C8b below · **Size:** L · **Depends on:** C4 (done)

**The trigger double-counted.** It named `core/agent_loop.py::run_agent_turn` at 789 lines,
`core/dispatch.py::dispatch_task` at 703 and `::_execute_unit` at 501, as three functions. Measured
at `7f02c55` by AST, `_execute_unit` is a closure **nested inside** `dispatch_task` (lines
1284-1784 of 1172-1874), so 501 of those 703 lines are the same lines counted twice. There are two
oversized functions, in two files, not three. The split follows the files: one branch each, and
they may run in parallel because they share no module.

### W31-C8a — split `run_agent_turn` into named phases

**Status:** DONE (2026-09-12, `56bd65a` merged as `13a191f`) · **Size:** M · **Owner:** @sonnet-c8a ·
**Depends on:** C4 (done) · ran in parallel with C8b (disjoint module and test files)

**Shipped:** `run_agent_turn`'s own body -- the statements sitting directly in it, excluding its
nested defs -- falls from 328 lines to 75, over eight named phases. Three are pure, module-level
functions: `_resolve_context_bounds`, `_resolve_trace_coordinates` and
`_resolve_role_registry_and_prompt`. Five are the per-iteration body: `_check_iteration_bounds`,
`_prepare_request_or_finalize`, `_call_backend_and_handle_response`, `_dispatch_tool_batch` and
`_run_iteration`. The nested-inclusive span grows 789 to 893 lines, because each new def carries
its own signature and docstring; the card never had a total-length target, and the goal was moving
logic into named units rather than shrinking text.

**The bounds are the product here, so they were checked independently of the card's own table.**
The ordered sequence of cancellation checks, `max_iterations`, wall clock, token budget,
`max_tool_calls`, context fit, terminal finalization, the backend call, usage accumulation, every
response-shaped stop condition, the batch ceiling, `dispatch_tool` and the denial ceiling is
identical before and after, and the two `_accumulate(total_usage, ...)` points sit at the same
place in that sequence. `dispatch_tool` keeps its single call site. The one user-facing string
that was rewrapped across source lines is byte-identical once concatenated, which the 18-case
golden suite confirms.

**Not delivered, and worth naming: five of the eight phases have no unit test.** The card asked for
unit tests per phase; only the three pure functions got them, because the other five stay nested
closures sharing mutable turn state (`total_usage`, `iteration`, `tool_calls_executed`,
`consecutive_denial_kinds`) and a closure cannot be imported. The agent judged that threading that
state out explicitly carried more behaviour-change risk than the readability gain was worth. C8b
shows the opposite choice is available -- it lifted a 501-line closure by inventorying its captures
into a `_UnitContext` dataclass first -- so if this module needs work again, that is the route.

**Integrator follow-up (`f86a4c7`).** The seven new docstrings pushed the shrink-only comment
ratchet from 558 to 565 and the suite failed on
`tests/guards/test_comment_hygiene.py::test_counts_do_not_exceed_baseline`. The card missed it
because `comment_lint.py --check` reports only archaeology; the docstring budget is enforced by the
guard test, not by that exit code. Each rationale moved verbatim from its docstring to a comment
above the def, which the budget does not count -- the idiom `tests/conftest.py` already uses. Suite
2404 to 2413; `CONTRIBUTING.md` reconciled by the integrator, which is why the card correctly left
`metrics.py --check` failing.

**Ratchet earned, not asserted.** `docket.core.agent_loop` came out of
`tests/guards/layout_baseline.txt` now that `tests/unit/core/test_agent_loop.py` exists. The guard
was seen red with that file hidden and green with it restored.

### W31-C8b — split `dispatch_task` and its nested `_execute_unit` into named phases

**Status:** DONE (2026-09-12, `5a521a5` merged as `1dd9456`) · **Size:** M · **Owner:** @sonnet-c8b ·
**Depends on:** C4 (done) · ran in parallel with C8a (disjoint module and test files)

**Shipped:** `_execute_unit` is a module-level function. `dispatch_task` falls from 703 lines to
about 125 and the lifted function from 501 to 52, each a thin orchestrator over named phases:
`_gate_budget`, `_gate_pre_hop_approval`, `_compose_hop`, `_run_hop_turn`,
`_apply_output_guardrails`, `_build_hop_result`, `_persist_hop_and_trace`, `_evaluate_post_hop_gate`
(delegating to `_evaluate_mechanical_gate` and `_evaluate_verdict_gate`), with `_run_group_node`
lifted alongside, and `_resolve_pipeline_steps`, `_resolve_resume_state`, `_resolve_gate_override`
and `_run_pipeline` carved out of `dispatch_task` itself.

**The inventory came before the lift, which is why it is safe.** Every name the closure reached
through lexical scope became either an explicit call argument (`node`, `prior_snapshot`,
`rework_hop`, `check_approval`, `index_for_context` -- the ones that vary per call) or an attribute
of a new `_UnitContext` dataclass. Two are mutated rather than read, and those are where a lift
like this breaks silently: `rework_counts` is a dict mutated in place, so the same object must keep
flowing through and never a copy; `override_index` was rebound through `nonlocal` to consume a
granted approval's single-use gate override exactly once, and is now rebound as an attribute of a
shared mutable context. Both risks are written into the code, and the second is pinned by a test
asserting the override is consumed at the named pipeline index and survives at any other.

**Six tests exist that could not exist before**, calling the lifted function and two of its gates
directly. Seen red against the pre-lift file (the context class reported missing) and green after.
No existing test was retired and the full prior suite passed unchanged throughout, which is the
evidence a refactor claiming no behaviour change owes.

**Unchanged, deliberately:** the hop sequence, the `verifyCmd` gate, the Tester first-line verdict
parse, `maxReworkCycles`, the trace event set. The two user-facing strings that moved are
byte-identical, confirmed by the 18-case golden suite.

**Integrator note:** the agent's worktree had been checked out at a stale base predating the whole
wave. It detected this itself and reset to `main` before working, so the branch that merged is one
commit on top of `main` touching two files. Suite 2398 to 2404; `CONTRIBUTING.md` reconciled by the
integrator, which is why the card correctly left `metrics.py --check` failing.

### W31-C9 — `trace.redact` degrades quadratically on a long alphanumeric run

**Status:** DONE (2026-09-12, `a3f03b0` merged as `d698d16`) · **Size:** S · **Owner:** @sonnet-c9

**Shipped:** two secret-shape patterns had an unbounded quantifier followed by a required literal
from the same character class; both are now capped at the real limits (40 characters for an
environment-variable name, the RFC lengths for an email). A third instance of the same shape, a
redundant `\s*` before a class that already matches whitespace, went with them. 20,000 characters
fall from 2.76 s to 0.02 s and 40,000 from 10.68 s to 0.03 s; the redacted set is unchanged,
pinned by a table test built from assertions already in the suite.

**Deterministic trigger:** a product defect surfaced by W31-C2, which hit it as a 33-second test
and worked around it rather than fixing it (`src/` was forbidden to that card). Reproduction, from
the repository root:

```python
import time
from docket.core import trace
for n in (20_000, 40_000):
    s = "Z" * n
    t = time.perf_counter(); trace.redact(s)
    print(n, round(time.perf_counter() - t, 2))
```

Measured on this machine: 20,000 characters take 2.76 s, 40,000 take 10.68 s, and `"A1" * 20_000`
takes 8.05 s. Doubling the input roughly quadruples the time, so a secret-shaped pattern is
backtracking. A punctuation-only string of the same length takes 0.006 s.

**Why it matters on the live path:** `redact` runs on trace payloads, and `DOCKET_TOOL_MAX_OUTPUT_CHARS`
defaults to 30,000. Base64, a hex dump, a long token or a minified bundle in tool output all have
the shape that triggers it, so a single tool result can add several seconds to a turn, repeatedly,
with nothing in the trace saying why.

**Goal:** the same redaction outcome in linear time. Bound the secret-shaped patterns so they
cannot backtrack (possessive or atomic matching, an anchored scan, or a length ceiling past which
a run cannot be a credential), and keep every currently redacted shape redacted.

**Non-goals:** no change to what counts as a secret; no new trace fields; no truncation of tool
output; no change to `core/trace.py`'s file format.

**Owns:** `src/docket/core/trace.py` and its unit file. **Forbidden:** the tool chokepoint, the
output cap, central rollups.

**RED test:** a unit test that calls `redact` on 40,000 repeated alphanumerics and fails on a wall
clock over 0.5 s; it must be seen to fail on the current implementation. Plus a table test proving
every pattern still redacts the values it redacts today, taken from the existing tests.

**Acceptance / oracles:** the timing test passes; the existing redaction tests pass unchanged;
`tests/integration/test_hop_carryover.py`'s `_BigOutputRunner` filler can go back to a repeated
letter and the suite stays inside the duration guard.

**Validation:** full gates. **Handoff:** the before/after timings at both sizes and the pattern
that was backtracking.

### W31-C10 — one way to repoint DOCKET_HOME, not fifty-six

**Status:** DONE (2026-09-12, `aa34fdc`, merged) · **Size:** M

**What shipped.** Every test that repoints to a home it chooses now calls
`tests/conftest.py`'s `repoint_docket_home`. Fifty files converted, 297 lines added against 496
deleted. The 21 private `_point_at` helpers are gone, and with them 21 tests that ran against a
home split in two.

**The guard is the deliverable, not the conversion.** `tests/guards/test_docket_home_repointer.py`
is AST-based and scoped **per function** rather than per module, so one correct test sitting beside
one drifted test in the same file is still caught. A module-wide "calls the helper somewhere" check
would have missed that, and was rejected for it.

**Proved by failure, twice by the card and once more by the integrator.** Planting a partial
repointer in `test_diff_probe.py` turned the guard red and named the exact function and line;
removing it turned it green. The integrator repeated that independently rather than reading the
transcript.

**The allowlist is empty, and that is a structural fact rather than an oversight.** The card
expected a class of test that sets a `DOCKET_HOME` environment variable for a child process and
must never be converted. That class exists here, but every real instance sets `os.environ` or a
subprocess `env=` dict, never `_cfg.DOCKET_HOME`, because patching an already-imported module
cannot reach a separate process's fresh import of `config.py`. None of them can trip the guard, so
there is nothing legitimate for the allowlist to hold. It stays as a mechanism with a shrink-only
self-check.

**Two shapes the guard does not catch, both named in its own docstring.** A private helper that
hand-rolls the raw setattr calls is flagged where it is defined, not at every call site, which is
enough to fail the suite and name the file. And the condition keys on `_cfg.DOCKET_HOME` itself, so
a function that repoints only derived constants and never claims a home does not trip it.

**Follow-up observed, not scheduled.** The integrator measured **16 functions across 13 modules**
that hand-roll two or more tracked constants without ever setting `DOCKET_HOME`. They are not this
card's drift shape: each overrides a named constant deliberately, which `conftest.py` blesses, and
the autouse fixture still isolates everything they leave alone, so none can reach the real
`~/.docket`. The honest rule for them is a threshold rather than a boolean, which needs its own
baseline and its own card. Do not schedule it without re-measuring first.

**Process deviation, recorded rather than smoothed over.** A session rate limit killed the run
mid-conversion, leaving `test_docket_driver.py` calling the helper without importing it and 36
collection errors. The integrator preserved the in-flight diff before reviewing it. The card's
classification artifact was required **before** any edit and was written afterwards instead; that
ordering is unrecoverable and the artifact says so.

**Gates, every exit code read directly rather than through a pipe.** pytest 0 with 2,410 passed and
5 skipped, ruff check 0, ruff format 0, mypy 0 on 74 source files, golden 18/18, specs 27/27.
Comment hygiene holds at exactly its 558 baseline within the guard's `src` and `tests` scope; the
one archaeology hit tree-wide is `comment_lint.py`'s own self-describing docstring. The real
`~/.docket` hashes identically either side of a full run. Test count 2,413 to 2,415;
`CONTRIBUTING.md` reconciled by the integrator.
---

## ☑ WAVE 30 COMPLETE (2026-09-11 to 2026-09-12) — harness mode seams and contract (Phase 24, D-35)

**Active since 2026-09-12.** Deferred behind Wave 31 on 2026-09-11 and scoped once so it would be
ready; Wave 31 closed, W31-C1's move of every test file is merged, and no other wave holds the
marker. C1, C2 and C3 are claimed together per the contention analysis below. W29-C7 remains
claimable in parallel and is held separately: it publishes a public release, which is an
irreversible outward-facing act, so it waits on an explicit go-ahead rather than on this wave. Decision D-35 and its corrected reasoning live in
[docs/adr/0001-harness-mode.md](docs/adr/0001-harness-mode.md); the audit that produced these cards
is `internal-docs/harness-mode-audit.md` (read at `main` `4032133`). ROADMAP's "Planned program —
PHASE 24" section holds the measured-gap table and the exit contract; this section holds the cards.

**Activation measurement (2026-09-11, `4032133`):** five deterministic gaps, each with a locator and
an expected/actual reproduction — not a demand estimate.

| Gap | Locator | Actual | Expected |
| --- | --- | --- | --- |
| In-flight `bash` ignores cancellation | `edges/adapters/toolbox.py::run_bash` (`communicate(timeout)`, `start_new_session=True`); `core/tools.py` `bash` handler lambda passes no callback; `DocketDriver` reports no pid so `runs.cancel_run` kills nothing | cancel at 0.2 s into `sleep 30` → returns at 30 s / tool timeout | returns < 2 s, child group gone |
| Gated call waits, then loop continues | `core/tools.py::dispatch_tool` `ask` branch → `wait_for_approval` (`TOOL_APPROVAL_TIMEOUT`=120 s); `core/agent_loop.py` denial accounting (`max_consecutive_tool_denials`=3) | ≥120 s wait; terminal `tool_denials` only after 3; no `policyId` in `tool_result` trace | 0 s; terminal on first gated call; result names tool/callId/policyId/reason |
| No trace subscriber | `core/trace.py::trace_event` | append-only | one synchronous seam; zero-subscriber path byte-identical |
| No published contract | `docs/contracts/` absent; no versioned shapes/fixtures | zero | generated schema pinned by test; NDJSON fixtures |
| No non-interactive entry point | `cli/`; `POST /dispatch/` returns before the work | zero | `docket harness run` / `status` |

**Execution graph / contention:** C1, C2 and C3 are independent and start together. `core/tools.py`
is the one hot file: C1 owns **only** the `bash` handler lambda; C2 owns `ToolContext`,
`ToolResult`, `ToolDenialKind` and the `ask` branch of `dispatch_tool`; nobody else touches it.
C4 starts after C1+C2+C3 land on `main`. C5 is integrator closure. **Nobody edits** `core/runs.py`,
`core/approval.py`, `core/dispatch.py`, `serve.py`, or the runtime facade, and
`edges/adapters/docket_runtime.py` changes only by C4's one env-coordinate pop: the design's whole
point is that they are consumed unchanged. Central files stay
integrator-owned. Every card runs with an isolated `DOCKET_HOME`; the real `~/.docket` must be
byte-identical before and after each focused run (snapshot it — this suite has leaked three times).

### W30-C1 — make cancellation reach an in-flight bash command

**Status:** DONE (2026-09-12, `5c95d52` + `76332c6`, merged `61864e6`) · **Size:** S

**What shipped.** `run_bash` takes an optional cancellation callback and waits in a bounded poll
instead of blocking in `communicate()`, killing exactly the way the timeout path already does:
`system.docker_kill` under the docker backend, then the process group. The `bash` handler passes
`ctx.cancellation_check`, so `docket runs cancel` terminalizes a run whose hop sits inside a long
command, under three seconds, through the public CLI with no new code. That whole-path result is
the card's real oracle and it holds. A caller passing no callback is byte-identical, timeout message
included. D-30's "may finish" rule is narrowed for this one handler and unchanged for every other.

**Merged on the second pass, and the first pass is the lesson.** The original poll used
`proc.wait()`, which never drains the child's pipes, so a command writing past the pipe buffer
blocked on its own next write, never exited, and was reported as a timeout with its output thrown
away. The card's own handoff described this accurately and then classified it as out of scope
because the no-callback path was untouched. That does not follow: the handler passes the
cancellation check unconditionally, so any dispatch wiring one took the new path for every shell
command it ran. A build, a test run or a verbose git command would have failed falsely.

**Measured, by the integrator, before and after.** One 200 KB command at an 8 s timeout. Before the
fix: the no-callback path returned in 0.01 s with `ok=True` and 30,037 characters, the
cancellation-aware path took the full 8 s, returned `ok=False` and zero characters. After: 0.11 s,
`ok=True`, content byte-identical to the baseline. Fifteen cancellations under continuous heavy
output produced no anomaly, and real cancellation latency is unchanged at about 0.2 s.

**The regression test was seen to fail.** Reintroducing an undrained wait fails
`test_a_callback_that_never_fires_still_drains_output_over_a_full_pipe` on its wall-time assertion,
"took 8.01s (baseline 0.01s), not promptly", and restoring the drain turns it green. It asserts
content equality against the no-callback run of the same command, not the absence of an exception.

**Merge conflict, resolved by keeping both sides.** C1 and C2 each added a requirement and a
changelog entry to `security-gates.spec.md` and `agent-loop.spec.md`. The approval requirement stays
11 and cancellation became 12; each spec took a new version section rather than two entries
competing for one. Survival of both sides was checked by grepping key phrases from each, not by
reading the diff.

### W30-C2 — give a non-interactive caller a typed, immediate, terminal approval outcome

**Status:** DONE (2026-09-12, `988ed93`, merged `55faaa6`) · **Size:** M

**What shipped.** `ToolContext.approval_mode` defaults to `"wait"`, so every existing caller is
untouched. Under `"refuse"` the `ask` branch audits `tool.ask` exactly as before, creates no
approval record, waits zero seconds, and denies with a new `approval_unavailable` kind carrying the
policy id and reason. `ToolResult.policy_id` is populated on every non-allow verdict, the
`tool_result` trace record carries `policyId` and `reason` when present, and the loop returns a
matching `StopReason` terminally on the first such denial, after the batch's complete unit is
persisted and independently of `max_consecutive_tool_denials`. Measured refuse-path latency about
10 ms against the shipped `block-destructive` template, versus 120 s per call before.

**Verified by falsification, by the integrator, not by reading the handoff.** Neutralising only the
two behavioural branches while keeping the new dataclass fields made the three new tests fail at
their assertions — `approval_timeout` where `approval_unavailable` was expected, `ok` true where
false was expected, and a scripted backend running out of responses because the turn did not stop.
None failed at setup. Restoring the branches made them pass.

**The specificity proof is the point and it holds.** `gate_denied` and `invalid_call` still continue
under `"refuse"` and are still bounded by the existing denial limit. Lowering that limit to 1 would
have been the cheap version of this card and would have made a recoverable `invalid_call` terminal.

**A defect this card could not see on its own, found at merge and fixed in `c91d596`.** The error
string was prose, and W30-C3 parses it back into the published contract's blocked payload as quoted
key=value pairs. Both cards passed their own suites and together produced a payload whose tool, call
id and policy id were all empty — losing exactly the rule attribution this card exists to carry. The
renderer is now `approval_unavailable_error`, a named function, and
`tests/integration/test_harness_contract.py` pins the round trip end to end.

**Known and deliberate:** `DocketDriver.run_turn` does not thread `approval_mode` into the
`ToolContext` it builds, so a production dispatch cannot reach `approval_unavailable` yet. That is
this card's non-goal and W30-C4's job. **The integrator must confirm C4 actually wires it** — this
repository has three recorded instances of machinery built, tested and never reached by the live
path, and this is precisely that shape until C4 closes it.

### W30-C3 — add the trace subscriber seam and publish the harness contract before the command

**Status:** DONE (2026-09-12, `0d7f4cc`, merged `deacfc5`) · **Size:** M

**What shipped.** `core/trace.py::subscribe` is a context manager over a module-level sink list.
Every sink is called synchronously on the calling thread with the exact record `trace_event` is
about to append, after redaction and before the write; a raising sink is suppressed and never
changes the return value; with zero sinks the function is byte-identical. `core/harness.py` is the
contract itself, pure: the event envelope, the result and its blocked payload, the status enum, and
`preflight`, `agent_meta_for` and `result_from`. `scripts/harness_schema.py` generates
`docs/contracts/harness-v1/schema.json`, which a test regenerates in memory and compares byte for
byte. Four NDJSON fixtures cover ok, blocked, cancelled and refused, validated line by line, and a
fixture declaring version 0.9.0 fails closed.

**The contract ships before the command, deliberately.** `specs/api/harness-mode.spec.md` carries
the status that the contract is defined and test-pinned while `docket harness` arrives in W30-C4.
An external consumer has committed to building nothing until these bytes exist, and this repository
has shipped five doc claims that ran ahead of the code.

**`core/harness.py` sits outside the runtime closure**, checked against the package-boundary test
rather than assumed. Changing the closure was a non-goal.

**The one thing this card got wrong, found at merge and fixed in `c91d596`.** `result_from` parsed
the driver's error string for quoted key=value pairs while W30-C2 wrote the tool and call id as
prose, so every structured field in the blocked payload arrived empty. The card flagged the coupling
as a guess in its own handoff, which is why it was caught, but a guess about another card's wire
format is not evidence and nothing tested the pair. `tests/integration/test_harness_contract.py`
now drives the real renderer end to end; reintroducing prose turns it red.

**Pending for the integrator at C5:** the `specs/README.md` row for the new spec, which this card
correctly left alone.

### W30-C4 — ship `docket harness run` and `docket harness status`

**Status:** DONE (2026-09-12, `01d6c67`, merged `60dfc51`) · **Size:** M

**What shipped.** `docket harness run` executes one agent, one turn, to completion, in a workspace
and home the caller owns, streaming NDJSON events on stdout and finishing with one versioned
result; `docket harness status TOKEN` reports `live`, `finished` or `unknown`. stdout carries the
wire protocol and nothing else, line-buffered; every human-facing word goes to stderr.

**This card closed the wave's own trigger, which is the point of it.** C1, C2 and C3 built seams
that nothing called — the repository's recorded "machinery built, tested, never reached by the live
path" shape, which has cost it three defects. W30-C2's refusal mode in particular could not be
reached by any real dispatch until now. It travels to `ToolContext` through the same env coordinate
`DOCKET_PIPELINE_WORKTREE` already uses: a `DOCKET_APPROVAL_MODE` constant in
`core/runtime_driver.py`, passed in `run_turn`'s `env`, popped by `DocketDriver.run_turn` before
the tool env is built. No Protocol change, no new keyword.

**Verified by the integrator, independently of the handoff.** Severing the driver's pop fails
`test_a_destructive_command_denies_immediately_as_blocked`, which drives a real subprocess rather
than poking the seam; restoring it passes. A live run against the local llama.cpp endpoint exits 0
with nine contiguous NDJSON events, every line carrying `v="1.0.0"`, a served model that differs
from the requested id, `cost_usd` null rather than invented, and a workspace genuinely containing
the file the agent was told to write. The refusal path emits exactly one valid JSON line on stdout,
nothing on stderr, and exits 2. The developer's real `~/.docket` hashes identically either side of
the harness suite — which had to be asserted by snapshot, because these tests spawn subprocesses
that the in-process isolation fixtures cannot reach.

**The card was wrong about its own golden and the card lost.** It required `help.golden` to be
regenerated "because a new command appears in `docket help`". That file lists none of `runs`,
`cost`, `doctor`, `trace` or `audit` either; it is a curated tour, not an enumeration. The real
change is one word in the bash completion command list and one line in the zsh one, both derived
from the live Typer registry. Measured rather than assumed, which is the correct outcome.

**An honest gap, recorded in the spec rather than papered over:** a finished run's `status` cannot
recover `model.served` or the blocked rule detail, because those existed only in the ephemeral
turn result.

**Also required by an existing gate and not in the card's file list:** `tests/unit/cli/test__harness.py`,
because the layout guard requires a unit file for any `src/` module over 150 lines.

### W30-C5 — close Phase 24 truthfully and hand the contract to the consumer

**Status:** DONE (2026-09-12) · **Size:** S · **Owner:** integrator

**What shipped.** D-35 dated and marked shipped in the decision index; Phase 24 and Wave 30 marked
complete in the status table; the Phase 24 program record archived byte-for-byte; the harness-mode
row added to the spec index; the three-exit-code exception recorded in the CLI interface spec with
a version bump and changelog; one README sentence; a CHANGELOG entry; and a consumer handoff packet
naming the schema path, the fixture directory, the contract version, the commit, the exit-code
table and both amendments.

**The exit-code exception is a real exception and is written as one.** docket's return convention
is deliberately flat: the printed message distinguishes error kinds, not the code. `docket harness
run` breaks that with three codes, because its stdout is a wire protocol and a program cannot read
a printed message — it needs the status to separate a turn that ran and ended badly from one that
never started. `docket harness status` stays flat.

**The README sentence is scoped to what was measured.** One agent, one turn, non-interactive, in a
workspace and home the caller owns. It claims no pod, no fleet, no supported consumer integration,
and no guarantee beyond what W30-C1 actually timed.


---
## ◇ WAVE 32 CLOSED (2026-09-12) — documentation truth pass and two deferred follow-ups

All seven cards merged. Four parallel read-only audits measured the drift before anything was
scheduled; the full per-finding record is in the integrator's plan file.

| Card | Shipped | Proved by |
| --- | --- | --- |
| W32-C1 | `SSD-WORKFLOW.md`: removed a script, a CI workflow and a hook that never existed | eight real `ci.yml` job names checked individually |
| W32-C2 | the public spec index derives from disk; three versions, three missing rows corrected | a planted spec file failing the guard by name |
| W32-C3 | the harness contract paths an external consumer reads first | `ls` on both directories |
| W32-C4 | partial-repointer ratchet at 14; six worst converted; dead scaffolding deleted | a planted partial repointer going red |
| W32-C5 | three false capability claims removed from the guides | `isolation.refused` traced to the live adapter |
| W32-C6 | harness mode and the ADRs made discoverable; name collision cross-linked | anchors resolved; harness commands run |
| W32-C7 | env-var table derived: 10 hardcoded rows replaced by 55 scanned; exit codes corrected | a planted env var failing `--check` |

**Three cards corrected their own briefs and were right every time** — on which agent lanes
exist, on `DOCKET_APPROVAL_MODE` not being an environment variable, and on a guard already
existing where the brief said none did. Each correction came from measuring rather than from
reasoning about the instruction.

**The re-measured follow-up had grown** from 16 functions across 13 modules to 20 across 15,
which is why the board rule says a gap list decays and must be re-measured before scheduling.

**Integrator note for the next wave:** a card's gates pass on the card's branch, which proves
nothing about the merge. Merging C2 broke the agent-lane ratchet its own handoff reported green,
and only re-running the gates on the merge result caught it.

---

