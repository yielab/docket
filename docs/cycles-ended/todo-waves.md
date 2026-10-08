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

## ◇ WAVE 34 CLOSED (2026-09-13) — finish the D-36 function split, two measured fixes, one audit

All seven cards merged on 2026-09-13; every branch was checked against its declared ownership,
an AST comparison of public names and signatures, the function-span measurer, and the full gates
on each merged batch.

| Card | Shipped | Proved by |
| --- | --- | --- |
| W34-C1 | `run_agent_turn` 909 lines, twenty closures, into a `_TurnState` class of named phases; `run_agent_turn` is about 35 lines | span measurer empty for the file; public API AST-identical; 76 focused tests and the harness fixtures unchanged |
| W34-C2 | `compact_session` into `_validate_compaction_range`, `_run_compaction_rounds`, `_plan_and_apply_compaction` | same; fail-closed and atomic-unit tests unchanged |
| W34-C3 | `do_POST` into `_handle_post_approvals`/`_tasks`/`_dispatch` | same; serve and approval-gated dispatch tests unchanged |
| W34-C4 | `_doctor_json` into nine per-section helpers | golden 18/18 byte-identical |
| W34-C5 | bounded poll for the sleeping child before and after SIGTERM | red with a 0.3 s spawn delay, green with the poll, 20 of 20 under load |
| W34-C6 | `PROVIDER_CREDENTIAL_NAMES` owned by `core/provider.py`, imported by the adapter | new unit test red on base, green after |
| W34-A1 | read-only audit of ten persisted settings | one cli-only flag with live-path claims found |
| W34-C7 | spec 0.19.1, help text, generated reference, guide and README say the routing flag is recorded posture only | `rg` for the false claims empty; golden unchanged; agent lane green |

**Function-span baseline:** seven entries at open, one at close (`builtin_registry`, a flat
registration table kept on purpose).

**Integrator notes for the next wave.** Worker worktrees can be created from a commit older than
the one the integrator dispatched from; every check must diff from `git merge-base`, and each
packet now tells the worker to fast-forward to the named base first. A card's "owns" list must
name the file that actually renders a generated doc (C7 found `docs/commands.md`'s gates section
comes from `cli/__init__.py`, not `cli/_gates.py`).



**Measured before scheduling (integrator, 2026-09-13, `633ef91`):** `scripts/maint/measure_function_spans.py`
reports seven functions over 150 lines, nested closures included: `run_agent_turn` 909 (20 nested
closures, own body 87 lines), `compact_session` 225 (`_mutate` 172 inside it), `run_agent_turn._fit_task_request`
184, `builtin_registry` 180, `_DocketHandler.do_POST` 175, `_doctor_json` 168. `builtin_registry` is a
flat registration table and is left in the baseline on purpose. One W33 agent saw
`test_sigterm_after_the_tool_call_event_cancels_within_three_seconds` fail once under parallel load
and pass in isolation and on the base commit. `core/provider.py:35` and `edges/adapters/llm.py:57`
hold byte-identical five-entry credential tables.

**Shared rules for every card.** One worktree, one branch, base `main` at the wave's opening commit.
Workers never edit `tests/guards/function_span_baseline.txt`, `TODO.md`, `ROADMAP.md`, `README.md`,
`CONTRIBUTING.md`, `specs/README.md` or any counting script; the integrator regenerates the baseline
after each merge. A split card is behaviour-preserving: no public signature changes, no new modules,
no test edited or deleted (a split that needs a test change has changed behaviour: stop and report).
Full gates: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q`,
plus `bash tests/golden/run.sh verify-all` for anything under `src/docket/cli/`. Commit subjects
`Type: description`, ASCII, no attribution trailer.

**Contention graph.** C1 owns `core/agent_loop.py`; C2 owns `core/session.py` and must keep every
name `agent_loop.py` imports (`CompactionResult`, `append_messages`, `compact_session`, `load_messages`)
with the same signature; C3 owns `serve.py`; C4 owns `cli/_doctor.py`; C5 owns
`tests/integration/test_harness_cli.py`; C6 owns `core/provider.py`, `edges/adapters/llm.py` and one new
unit test. No two cards share a file. Merge order: C6, C5, C4, C3, C2, C1 (smallest blast radius first).

### W34-C1 — split `run_agent_turn` into module-level phases

**Status:** READY · **Size:** L · **Owner:** one worker

**Measured trigger:** `src/docket/core/agent_loop.py::run_agent_turn` spans 909 lines (lines 514 to
1422) with 20 nested closures; `_fit_task_request` alone is 184. ADR 0007 says this function was split.

**Goal:** hoist the nested closures into module-level private functions (or methods on one private
turn-state class) so that no function in the file exceeds 150 lines and `run_agent_turn` reads as a
sequence of named phases. Behaviour identical.

**Non-goals:** no change to `LoopConfig`, `run_agent_turn`'s signature, `approval_unavailable_error`,
stop reasons, trace events, the harness NDJSON contract or session compaction semantics; no new module.

**Owns:** `src/docket/core/agent_loop.py` only.

**Acceptance / oracle:** `uv run python scripts/maint/measure_function_spans.py src/docket/core/agent_loop.py`
prints nothing (no function over 150). `uv run pytest -q` passes unchanged, including
`tests/unit/core/test_agent_loop*.py`, `tests/integration/test_agent_loop.py`,
`tests/integration/test_harness_cli.py` and the byte-pinned fixtures under
`tests/fixtures/harness-contract/v1/`. `git diff --stat` touches one file. The integrator additionally
compares the module's public names and signatures before and after with an AST script.

**RED:** `uv run python scripts/maint/measure_function_spans.py src/docket/core/agent_loop.py` lists
two entries before the split.

**Focused validation:** `uv run pytest -q tests/unit/core/test_agent_loop.py tests/integration/test_agent_loop.py tests/integration/test_harness_cli.py`.

### W34-C2 — split `compact_session` into named phases

**Status:** READY · **Size:** M · **Owner:** one worker

**Measured trigger:** `src/docket/core/session.py::compact_session` spans 225 lines with the 172-line
`_mutate` closure inside it.

**Goal:** split planning, summarisation, atomic-unit validation and the locked write into
module-level private functions; no function in the file over 150 lines. Behaviour identical, including
the fail-closed contract (a failed summarisation leaves the stored history untouched) and the
atomic tool-call/tool-result unit guarantee.

**Non-goals:** no signature change to `compact_session`, `plan_compaction`, `CompactionResult`,
`append_messages`, `load_messages`; no new module.

**Owns:** `src/docket/core/session.py` only.

**Acceptance / oracle:** `measure_function_spans.py src/docket/core/session.py` prints nothing;
`uv run pytest -q` passes unchanged, including `tests/unit/core/test_session*.py` and the compaction
tests under `tests/integration/test_agent_loop.py`; one file in the diff.

**RED:** the measuring script lists two entries for the file before the split.

**Focused validation:** `uv run pytest -q tests/unit/core/ -k session tests/integration/test_agent_loop.py -k compact`.

### W34-C3 — route `do_POST` through per-route handlers

**Status:** READY · **Size:** M · **Owner:** one worker

**Measured trigger:** `src/docket/serve.py::_DocketHandler.do_POST` spans 175 lines; `_handle_post_pods`
already shows the per-route shape.

**Goal:** one private handler per POST route, `do_POST` reduced to auth, routing and error framing; no
function in the file over 150 lines. Byte-identical responses, status codes, audit entries and the
`docket runs` records each route produces.

**Non-goals:** no route added or removed, no auth change, no change to
`specs/data/serve-read-api.spec.md`.

**Owns:** `src/docket/serve.py` only.

**Acceptance / oracle:** `measure_function_spans.py src/docket/serve.py` prints nothing;
`uv run pytest -q` passes unchanged, including `tests/unit/test_serve__*.py`,
`tests/integration/test_serve_*.py` and `tests/integration/test_approval_gated_dispatch.py`; one file in the diff.

**RED:** the measuring script lists one entry for the file before the split.

**Focused validation:** `uv run pytest -q tests/unit -k serve tests/integration -k serve`.

### W34-C4 — split `_doctor_json`

**Status:** READY · **Size:** S · **Owner:** one worker

**Measured trigger:** `src/docket/cli/_doctor.py::_doctor_json` spans 168 lines.

**Goal:** split the JSON report assembly into per-section helpers; no function in the file over 150
lines; `docket doctor --json` output byte-identical.

**Non-goals:** no check added, removed or reordered; no change to the human-readable output.

**Owns:** `src/docket/cli/_doctor.py` only.

**Acceptance / oracle:** `measure_function_spans.py src/docket/cli/_doctor.py` prints nothing;
`uv run pytest -q` passes unchanged including `tests/unit/cli/test__doctor.py`;
`bash tests/golden/run.sh verify-all` passes 18/18 without regenerating anything; one file in the diff.

**RED:** the measuring script lists one entry for the file before the split.

**Focused validation:** `uv run pytest -q tests/unit/cli/test__doctor.py && bash tests/golden/run.sh verify-all`.

### W34-C5 — make the harness cancellation test deterministic under load

**Status:** READY · **Size:** S · **Owner:** one worker

**Measured trigger:** on 2026-09-13 a full-suite run alongside twelve other suites saw
`tests/integration/test_harness_cli.py::TestCancelledRun::test_sigterm_after_the_tool_call_event_cancels_within_three_seconds`
fail once and pass on re-run, in isolation, and on the base commit. The test looks up the sleeping
child once, immediately after the `tool_call` event, but that event is emitted before the bash
handler has spawned the child, so under load the single lookup races the spawn.

**Goal:** wait for the child process to appear (bounded poll, deadline of a few seconds) before
asserting it exists, without loosening the three-second cancellation bound, which is the contract
under test.

**Non-goals:** no change under `src/`; no change to the three-second bound; no skip or retry marker.

**Owns:** `tests/integration/test_harness_cli.py` only.

**Acceptance / oracle:** the test passes 20 times in a row locally while `uv run pytest -q -n 0` runs
in another shell (or under `stress`-like CPU load); one file in the diff; the assertion message still
names the missing child on a genuine failure.

**RED:** reproduce the race by inserting a `time.sleep(0.3)` before the bash handler spawns (locally,
not committed) or by running the suite under load; the single lookup fails with
"the sleeping child process was never found".

**Focused validation:** `for i in $(seq 20); do uv run pytest -q tests/integration/test_harness_cli.py -k cancels_within || break; done`.

### W34-C6 — one owner for the provider credential table

**Status:** READY · **Size:** S · **Owner:** one worker

**Measured trigger:** `src/docket/core/provider.py:35` (`_PROVIDER_CREDENTIALS`) and
`src/docket/edges/adapters/llm.py:57` (`_PROVIDER_CREDENTIAL_NAMES`) are byte-identical five-entry
dicts with separate readers (`provider.py:129`, `llm.py:447`). A provider added to one and not the
other makes `docket models`/provider checks and the adapter's request path disagree silently.

**Goal:** a single definition in `core/provider.py` (public name `PROVIDER_CREDENTIAL_NAMES`), imported
by `edges/adapters/llm.py` (edges may import core), with one unit test asserting the adapter reads the
same object and an import-cycle check (`python -c "import docket.edges.adapters.llm, docket.core.provider"`).

**Non-goals:** no change to the table's contents or to how either reader resolves a credential.

**Owns:** `src/docket/core/provider.py`, `src/docket/edges/adapters/llm.py`, and one new test in
`tests/unit/core/test_provider.py` (create it with `SUBJECT = "docket.core.provider"` if absent, or add to it).

**Acceptance / oracle:** `rg -n 'ANTHROPIC_API_KEY' src/` finds exactly one dict literal; the new test
fails on the base commit (two objects) and passes after; `uv run pytest -q` passes; `mypy src` passes.

**RED:** the new unit test on the base commit.

**Focused validation:** `uv run pytest -q tests/unit/core/test_provider.py tests/unit/edges/adapters/test_llm.py tests/integration/test_provider_agnosticism.py`.

### W34-C7 — make the approval-routing claims true

**Status:** READY · **Size:** S · **Owner:** one worker

**Measured trigger (A1 audit, 2026-09-13, verified by the integrator):** `fleet.json`'s
`security.approvalRoutingState`/`approvalRoutingMode` are written by `core/fleet.py:329,337` via
`core/security.py:299,309` (`docket gates enable/disable`, `docket init`) and read only by
`cli/_gates.py:55` and `cli/_doctor.py:331,678` for display. `rg -n 'approval_routing|approvalRouting' src/`
finds no reader in `core/tools.py`, `core/approval.py`, `core/telegram.py`, `core/agent_loop.py` or
`serve.py`. Yet `specs/functional/security-gates.spec.md` requirement 2 says the state controls
"whether a `require_approval`/`ask` verdict's prompt is routed to a channel-bound agent's session",
`README.md:58-59` says `gates enable/disable` "changes where an `ask` verdict is routed", and
`docs/commands.md` (rendered from `cli/_gates.py` help) says `enable` makes a verdict "reach a channel
instead of just sitting on docket's approval store" and `disable` makes it "time out to denied
faster". None of that happens: docket never pushes a prompt anywhere (telegram spec requirements
7-8), approvals always sit in the store, and every channel answers them regardless of this flag.
This is the fourth unwired-machinery instance, with the same shape as W19-5 (spec and prose
claiming a path that never existed).

**Goal:** make spec, help text, generated reference and guide say what is true: the routing state is
a recorded, audited posture flag that `gates status` and `doctor` report, and nothing on the live
path reads it. Do not invent semantics for it and do not remove the commands (a removal or a real
wiring is a separate decision for the maintainer; record it in the spec as an open question).

**Non-goals:** no change to `core/`, `edges/`, `serve.py`; no new behaviour; no README edit (integrator
owns `README.md:58-59` and will change it at merge to match your spec wording).

**Owns:** `src/docket/cli/_gates.py` and `src/docket/cli/_install.py` (help/docstring text only, no
logic); `docs/commands.md` regenerated with `./scripts/gen_cli_docs.py` (never hand-edited);
`docs/SECURITY-SIMPLE.md` lines about `--no-gates`/`gates enable` (26-30, 60, 247);
`specs/functional/security-gates.spec.md` requirement 2, the command block near line 663, version
bump and changelog entry; the one `Security Gates` row in `specs/README.md` for the version;
`tests/golden/cases/writers/gates_status.golden` ONLY if `docket gates status` currently prints a
false sentence, and then explain the golden diff line by line in the commit body.

**Acceptance / oracle:** `rg -n 'routed|reach a channel|times out to denied faster' src/docket/cli/_gates.py docs/commands.md docs/SECURITY-SIMPLE.md specs/functional/security-gates.spec.md`
finds no remaining claim that the flag changes delivery; `bash scripts/validate-specs.sh` green;
`./scripts/gen_cli_docs.py --check` (or the repo's equivalent drift check) green;
`bash tests/golden/run.sh verify-all` green; `uv run pytest -q` and `uv run pytest -q tests/agent` green
(the agent lane pins README prose and public docs; if a prose test pins one of the false sentences in a
file you own, correct the test's expected phrase in the same commit and say so).

**RED:** the `rg` above lists the false claims before the change.

**Focused validation:** `bash scripts/validate-specs.sh && bash tests/golden/run.sh verify-all && uv run pytest -q tests/agent`.

### W34-A1 — read-only audit: the fourth unwired-machinery instance

**Status:** READY · **Size:** S · **Owner:** one read-only worker (no commits)

**Measured trigger:** three recorded instances of "implemented, tested, never wired to the default
path" (W17-1, W18-3, W19-3). The record says to assume a fourth exists; nobody has scanned for it.

**Goal:** for every setting docket persists under `DOCKET_HOME` with a writer in `cli/` (fleet gate and
isolation flags, model policy, retention, schedules, MCP servers, policies, secrets, budgets), name the
reader on the live path (`core/agent_loop.py`, `core/tools.py`, `core/dispatch.py`,
`edges/adapters/docket_runtime.py`, `serve.py` loops). Report every setting whose only reader is in
`cli/` or tests, with file:line evidence for writer and reader.

**Non-goals:** no code change, no doc change, no card creation; the report is the deliverable.

**Acceptance / oracle:** a table of settings with writer, live-path reader (or "none found"), and the
`rg` command that proves it; each "none found" row re-checked once by grepping the setting's key
across `src/`.

---

## ◇ WAVE 35 CLOSED (2026-09-13) — second docstring sweep, one dead flag, one lane rule

All eight cards merged on 2026-09-13; every branch was checked against its declared ownership,
a docstring-stripped AST comparison (docstring cards), the comment linter, and the full gates on
the closing tree.

| Card | Shipped | Proved by |
| --- | --- | --- |
| W35-C1 | `core/dispatch.py` over-budget function docstrings 50 to 19 | AST `SAME`; invariant sentences grepped on the branch |
| W35-C2 | `cli/_install.py`, `_mcp.py`, `_pod.py`, `_agents.py` 43 to 9, three module docstrings into budget | AST `SAME`; golden 18/18; generated reference unchanged |
| W35-C3 | `core/approval.py`, `llm.py`, `memory.py`, `pod.py` 43 to 10, three module docstrings into budget | AST `SAME` |
| W35-C4 | `core/telegram.py`, `models_policy.py`, `runs.py`, `trace.py` 37 to 13 | AST `SAME`; inbound-only, D-30 and retention sentences grepped |
| W35-C5 | `core/archetypes.py`, `identity.py`, `models.py`, `orchestrator.py`, `runtime_driver.py`, `tools.py` 48 to 28, four module docstrings shortened | AST `SAME`; chokepoint and capability-denial sentences grepped |
| W35-C6 | `core/security.py`, `toolbox.py`, `serve.py`, `cli/_doctor.py`, `mcp_tools.py`, `policy.py`: five module docstrings into budget, 39 to 38 | AST `SAME`; golden 18/18 |
| W35-C7 | `FleetSecurity.gatesEnabled`, its accessors, the hidden `_json` verbs and their three tests removed; spec 0.19.2 | `rg` empty in `src/`; old `fleet.json` with the key still loads (kept test) |
| W35-C8 | test-framework 2.17.0 requirement 2 covers `integration/`; `test_layout.py` checks importability; thirteen `SUBJECT` lines corrected | guard seen red on a restored base file by the integrator; scan shows zero missing modules |

**Comment baseline:** 372/40 at open, 297/40 after C1, C4, C5, 229/29 at close. **Integrator
commits:** the data-layer `SUBJECT` (`docket.core`), CONTRIBUTING counts, the `gen_cli_docs.py`
import fix, the `maintain sessions` banner, three comment pointers repointed at specs.

**Integrator notes for the next wave.** Run `scripts/gen_cli_docs.py --check` in every batch
gate; it is a CI job and it was red for a whole wave without anyone noticing. Never prefix the
suite with `DOCKET_TOOL_MAX_OUTPUT_CHARS`; three tests assert the default. One worker used
`git stash` and one wrote an attribution trailer before catching itself; the brief forbids
both, and the checks caught nothing because both were undone, but the rule stands.

**Measured at `a6ce41e` (all gates green, main pushed).** `scripts/maint/comment_lint.py` with
the enforced budget (module 12 lines, def 3 lines) over `src/` and `tests/` counts 372
over-budget function docstrings and 40 over-budget module docstrings, the shrink-only baseline
`scripts/maint/comment-baseline.json` left by Wave 33. The per-file tally is steep at the top
and flat below: `core/dispatch.py` 50, then twenty files at 6 to 11 each, then a long tail
under 6. The Wave 34 audit classified `FleetSecurity.gates_enabled` as cli-only: `rg -n
'gates_enabled|gatesEnabled' src/` finds the field, two accessors in `core/fleet.py`, and the
hidden `_json gates-get`/`gates-set` verbs in `cli/__init__.py`; no live-path reader, no
product writer, no documentation. The integration lane declares `SUBJECT` on every file with
no rule behind it: seven values are free text (`"edit snapshot"`, `"logs command"`), six name
a module the file does not exercise (`test_agent_loop.py` says `docket.core.llm`), and
`tests/guards/test_layout.py` checks only the unit lane.

**Rules for every docstring card (C1 to C6).** Only docstrings change: the integrator strips
docstrings from both revisions and compares `ast.dump`; any code difference rejects the branch
whole. Every invariant, "why", fail-closed, limit, ordering or "never" sentence survives,
compressed if needed; a docstring may stay over budget when its rationale lives nowhere else.
History, card ids, dates, signature restatement and step narration go. A paragraph that already
lives in a spec becomes one line citing the spec path. Typer command docstrings are user help
and stay byte-identical. No `#` comments added, no other file touched.

**Contention.** The six docstring packets, C7 and C8 own disjoint files. C7 owns
`tests/integration/test_data_layer.py`; C8 therefore leaves that file's `SUBJECT` line alone
and the integrator sets it at merge. Merge order: C7 and C8 first (they change tests), then
C1 to C6 in any order, with the comment baseline lowered by the integrator after each batch.

| Card | Owns | Over-budget def docstrings at open |
| --- | --- | --- |
| W35-C1 | `src/docket/core/dispatch.py` | 50 |
| W35-C2 | `src/docket/cli/_install.py`, `_mcp.py`, `_pod.py`, `_agents.py` | 11, 11, 11, 10 |
| W35-C3 | `src/docket/core/approval.py`, `llm.py`, `memory.py`, `pod.py` | 11, 11, 11, 10 |
| W35-C4 | `src/docket/core/telegram.py`, `models_policy.py`, `runs.py`, `trace.py` | 10, 9, 9, 9 |
| W35-C5 | `src/docket/core/archetypes.py`, `identity.py`, `models.py`, `orchestrator.py`, `runtime_driver.py`, `tools.py` | 8 each |
| W35-C6 | `src/docket/core/security.py`, `edges/adapters/toolbox.py`, `serve.py`, `cli/_doctor.py`, `core/mcp_tools.py`, `core/policy.py` | 7, 7, 7, 6, 6, 6 |

### W35-C1 — trim docstrings in `core/dispatch.py`

**Status:** DONE (2026-09-13) · **Size:** S · **Owner:** one worker

**Measured trigger:** 50 of the 372 over-budget function docstrings sit in one 2,247-line
module, the dispatch state machine.

**Goal:** bring every function, method and class docstring in the file to three lines or fewer
where its content allows, keeping every invariant sentence (claim/hop/finalize ordering, the
docket-owned `HEARTBEAT.md` region, verify-gate and reviewer-gate semantics, rework bounds,
cancellation checkpoints). The module docstring is in budget and stays.

**Owns:** `src/docket/core/dispatch.py` only.

**Acceptance / oracle:** `uv run python scripts/maint/comment_lint.py --module-max 12 --def-max 3 src/docket/core/dispatch.py`
reports a lower `long-def-doc` count than 50, with each remaining entry justified in the
handoff; `--check` reports zero archaeology; the integrator's docstring-stripped AST comparison
reports `SAME`; `uv run pytest -q tests/unit/core/test_dispatch.py tests/integration/test_dispatch.py` unchanged and green.

**RED:** the lint command above lists 50 findings on the base commit.

**Focused validation:** the lint command, then `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q`.

### W35-C2 — trim docstrings in the `cli/` packet

**Status:** DONE (2026-09-13) · **Size:** S · **Owner:** one worker

**Measured trigger:** 43 over-budget function docstrings across `cli/_install.py`, `cli/_mcp.py`,
`cli/_pod.py` and `cli/_agents.py`.

**Goal:** as C1, for the four files. Typer `@app.command`/`@app.callback` docstrings are
rendered as user help and into `docs/commands.md`; they are not touched, so the golden suite
and the generated reference stay byte-identical.

**Owns:** the four files only.

**Acceptance / oracle:** as C1 over the four files; additionally `bash tests/golden/run.sh verify-all`
green and `./scripts/gen_cli_docs.py --check` (or the repository's drift check) reports no
change to `docs/commands.md`.

**RED:** the lint command lists 43 findings on the base commit.

**Focused validation:** lint, `bash tests/golden/run.sh verify-all`, then the full python gates.

### W35-C3 — trim docstrings in `core/` packet A

**Status:** DONE (2026-09-13) · **Size:** S · **Owner:** one worker

**Measured trigger:** 43 over-budget function docstrings across `core/approval.py`, `core/llm.py`,
`core/memory.py` and `core/pod.py`.

**Goal:** as C1, for the four files. `core/llm.py` carries the `TokenUsage` "measured, never
estimated" distinction and `core/memory.py` the `CONTRACT_VERSION` resume rules; both survive.

**Owns:** the four files only.

**Acceptance / oracle:** as C1 over the four files.

**RED:** the lint command lists 43 findings on the base commit.

**Focused validation:** lint, then the full python gates.

### W35-C4 — trim docstrings in `core/` packet B

**Status:** DONE (2026-09-13) · **Size:** S · **Owner:** one worker

**Measured trigger:** 37 over-budget function docstrings across `core/telegram.py`,
`core/models_policy.py`, `core/runs.py` and `core/trace.py`.

**Goal:** as C1, for the four files. `core/telegram.py`'s inbound-only and four-verb sentences,
`core/runs.py`'s cancellation lifecycle (D-30) and `core/trace.py`'s retention and redaction
bounds survive.

**Owns:** the four files only.

**Acceptance / oracle:** as C1 over the four files.

**RED:** the lint command lists 37 findings on the base commit.

**Focused validation:** lint, then the full python gates.

### W35-C5 — trim docstrings in `core/` packet C

**Status:** DONE (2026-09-13) · **Size:** S · **Owner:** one worker

**Measured trigger:** 48 over-budget function docstrings, eight in each of `core/archetypes.py`,
`core/identity.py`, `core/models.py`, `core/orchestrator.py`, `core/runtime_driver.py` and
`core/tools.py`.

**Goal:** as C1, for the six files. `core/tools.py` is the chokepoint: every sentence about the
three policy hooks, capability-based denial and the single execution path survives.
`core/runtime_driver.py`'s one-driver-not-a-framework sentence survives.

**Owns:** the six files only.

**Acceptance / oracle:** as C1 over the six files; `tests/unit/core/test_tools.py` unchanged and
green.

**RED:** the lint command lists 48 findings on the base commit.

**Focused validation:** lint, then the full python gates.

### W35-C6 — trim docstrings in the mixed packet

**Status:** DONE (2026-09-13) · **Size:** S · **Owner:** one worker

**Measured trigger:** 39 over-budget function docstrings across `core/security.py`,
`edges/adapters/toolbox.py`, `serve.py`, `cli/_doctor.py`, `core/mcp_tools.py` and
`core/policy.py`.

**Goal:** as C1, for the six files. `edges/adapters/toolbox.py` "holds no policy" and
`core/mcp_tools.py` "every adapted tool is `kind="write"`" survive. `cli/_doctor.py` has Typer
command docstrings that stay byte-identical.

**Owns:** the six files only.

**Acceptance / oracle:** as C1 over the six files; `bash tests/golden/run.sh verify-all` green.

**RED:** the lint command lists 39 findings on the base commit.

**Focused validation:** lint, golden, then the full python gates.

### W35-C7 — retire the `gatesEnabled` fleet flag

**Status:** DONE (2026-09-13) · **Size:** S · **Owner:** one worker

**Measured trigger (W34-A1, verified by the integrator at `a6ce41e`):** `rg -n 'gates_enabled|gatesEnabled' src/ docs/ specs/ README.md`
finds `FleetSecurity.gates_enabled` (`core/fleet.py:71`), `get_gates_enabled`/`set_gates_enabled`
(`core/fleet.py:282-289`), and the hidden `_json gates-get`/`gates-set` verbs in
`cli/__init__.py` (about line 2636). Nothing on the live path reads it; no product command
writes it (`docket init --no-gates` and `docket gates enable/disable` write
`approvalRoutingState`, per `specs/functional/security-gates.spec.md` requirement 2); no spec,
doc or golden mentions it. Twelve test fixtures seed `"gatesEnabled": false` into `fleet.json`
and `FleetSecurity` is lenient, so an existing `fleet.json` carrying the key keeps loading.

**Goal:** remove the field, the two accessors and the two verbs, and the three tests in
`tests/integration/test_data_layer.py` that exist only to exercise them (`test_security_gates`,
`test_gates_get_false`, `test_gates_set_true`, plus the `gates_enabled` assertion in the
fixture-loading test). Keep the `test_extra_fields_survive` case: an old `fleet.json` with the
key must still load, which is now the property that test proves. Record the removal in the
security-gates spec changelog (version 0.19.2) as the retirement of a flag that had no reader.

**Non-goals:** no change to `approvalRoutingState`/`isolationEnabled` or their commands; no
fixture edits outside the owned test file (the seeded key is legitimate "unknown key survives"
data); no golden regeneration (`tests/golden/fixtures/seed.sh` keeps its key for the same
reason).

**Owns:** `src/docket/core/fleet.py` (the field and the two accessors only),
`src/docket/cli/__init__.py` (the two `_json` verbs only), `tests/integration/test_data_layer.py`,
`specs/functional/security-gates.spec.md` (version line, changelog entry, and the one sentence
near line 678 if it lists the field), the `Security Gates` row in `specs/README.md`.

**Acceptance / oracle:** the `rg` above finds nothing in `src/`; a `fleet.json` containing
`"security": {"gatesEnabled": false}` still validates (the kept test); `uv run pytest -q`,
`bash tests/golden/run.sh verify-all`, `bash scripts/validate-specs.sh` green.

**RED:** the `rg` above lists the field, accessors and verbs on the base commit.

**Focused validation:** `uv run pytest -q tests/integration/test_data_layer.py tests/guards`, golden, specs, then the full python gates.

### W35-C8 — give the integration lane's `SUBJECT` a rule and a guard

**Status:** DONE (2026-09-13) · **Size:** S · **Owner:** one worker

**Measured trigger:** every file under `tests/integration/` declares `SUBJECT`, but
`specs/test-framework.md` requirement 2 and `tests/guards/test_layout.py` cover only
`tests/unit/`. Measured at `a6ce41e`: seven integration values are free text
(`test_auth_context_maintain_keys_add.py`, `test_edit_snapshot.py`,
`test_list_info_cost_commands.py`, `test_logs_command.py`, `test_models_audit.py`,
`test_profile_scope_models.py`, `test_runtime_execution_envelope.py`) and at least six name a
module the file does not exercise (`test_agent_loop.py`, `test_cooperative_run_cancellation.py`,
`test_role_tools_and_identity.py`, `test_runtime_driver.py`, `test_trace_audit.py` all say
`docket.core.llm`; `test_dispatch_run_records.py` says `docket.serve`).

**Goal:** amend requirement 2 so that every `integration/` file's `SUBJECT` names an importable
`docket` module or package (dotted path, the most specific one the file exercises; a
cross-module file may name a package); extend `tests/guards/test_layout.py` to check
importability for the integration lane (a mismatch with the file name is not an error there);
see the guard fail on the free-text values before fixing them; then set every wrong or free-text
`SUBJECT` to the module the file's imports and docstring say it exercises.

**Non-goals:** no test body changes, no file renames, no change to the unit-lane rule or the
exemption table, no edit to `tests/integration/test_data_layer.py` (C7 owns it; the integrator
sets its `SUBJECT` at merge).

**Owns:** `specs/test-framework.md` (requirement 2, enforcement-status sentence, version 2.17.0
and changelog), the `Test Framework` row in `specs/README.md`, `tests/guards/test_layout.py`, and
the `SUBJECT` line only of every file under `tests/integration/` except `test_data_layer.py`.

**Acceptance / oracle:** the new guard is red on the base commit's seven free-text values (say
so in the handoff with the failure text) and green after; `uv run pytest -q tests/guards`,
`uv run pytest -q`, `bash scripts/validate-specs.sh` green; a scan of every integration
`SUBJECT` shows an importable `docket` path.

**RED:** the extended guard fails on the base commit.

**Focused validation:** `uv run pytest -q tests/guards/test_layout.py`, then the full python gates and `bash scripts/validate-specs.sh`.

---

## ◇ WAVE 29 CLOSED (2026-09-14) — adoption evidence and public release

**Closed 2026-09-14 by ROADMAP D-39.** W29-C7 published `v0.2.0-beta.2` on 2026-09-07; its closing
half (a newer beta, public-URL install on Linux and macOS) was removed at the maintainer's request.
The text below is the card as it stood. C1–C6 are merged, closed and archived in
`docs/cycles-ended/todo-waves.md`. W29-C7 (publish the provenance-complete beta and close Phase
23) was deferred behind Wave 31 by maintainer decision on 2026-09-11 so the repository would be
made maintainable before it was published further. Wave 31 closed on 2026-09-12, so W29-C7 is
claimable. Its publication approval from 2026-09-07 still stands; only its ordering had changed.
Claiming it means marking this section active.

**Activation measurement:** bounded inspection used exact `main` commit `de08206`, the current
public GitHub release/API state on 2026-09-02, the Phase 23 exit contract, and only the live
starter/metrics/store/release/governance paths. The measurement did not infer demand from stars or
feature counts and did not reopen telemetry, A2A, a dashboard, multi-tenancy, or more adapters.

| Candidate | Source / threshold | Observed value | Disposition |
| --- | --- | --- | --- |
| Extractable ten-minute starter | `examples/`; at least one artifact-installed, copied-outside-checkout starter with a bounded end-to-end test | zero starter directories; `examples/runtime_embed.py` is a single consumer file and fails from the root environment when `docket-runtime` is not installed | **activate C2** |
| Machine-readable adoption benchmark | repository paths and `docket metrics`; at least one versioned schema/result covering all Phase 23 measures | zero benchmark/baseline files; current metrics omit one comparative record for measured tokens, estimate provenance, approval latency, recovery, and handoff failure | **activate C3** |
| Persisted-state recovery | `edges/store.py::{read_json,_atomic_write}`; a corrupt primary with a valid owned backup must have one safe recovery path | second write creates `.bak`, but corrupting the primary makes `read_json` raise `JSONDecodeError`; recovery paths: zero | **activate C1**, then prove it in C4 |
| Adversarial/crash evidence | policy, dispatch, and release focused tests; at least one public-journey scenario/report, not helper-only coverage | 31 focused policy-template, crash-resume, and release-contract tests pass; whole-journey benchmark scenarios/results: zero | **activate C4 after C1+C3**; reuse behavior rather than rebuilding it |
| Release supply chain | current workflow plus latest public beta; wheel, sdist, checksums, SPDX SBOM, and provenance must be publicly verifiable | workflow code and six release-contract tests already cover the machinery; public `v0.2.0-beta.1` has only tarball + checksum and predates it | **no duplicate implementation**; C7 performs approval-gated publication/verification |
| Support and succession policy | `SECURITY.md`, `COMPATIBILITY.md`, `.github/CODEOWNERS`, 90-day Git history; one truthful support/deprecation policy and one governance/succession path | main-only security support exists; no deprecation policy or governance document; one CODEOWNER and one underlying human author identity | **activate C5** |

**Execution graph / contention:** C1 through C6 are closed. C7 is the only remaining card and the
only release/version/tag owner; it may not publish without a fresh explicit approval. `ROADMAP.md`,
`TODO.md`, `README.md`, `CHANGELOG.md`, `COMPATIBILITY.md`, `SECURITY.md`, `specs/README.md`,
metrics, tags, and release state remain coordinator-owned unless a card below explicitly assigns
them.

### W29-C7 — publish a current provenance-complete beta and close Phase 23

**Status:** REMOVED (2026-09-14, ROADMAP D-39) · **Size:** M · **Owner:** integrator

**Measured trigger:** public release `v0.2.0-beta.1` (published 2026-07-03) has two assets—the legacy
tarball and checksum—and predates the current wheel/sdist/SBOM/provenance workflow. Static release
machinery and its six focused tests already pass, so publication/verification is the remaining gap.

**Goal:** choose an approved next beta version, align every version surface, run canonical release
rehearsal and cross-platform artifact journeys, create one signed/immutable tag through the protected
workflow, verify every public asset and attestation, then close Wave 29 and Phase 23 from evidence.

**Non-goals:** no silent tag, force push, mutable release replacement, package-index publication
unless separately approved, stable/LTS claim, Homebrew tap mutation beyond the repository formula,
or release while any required C1–C6 gate is red.

**Owns after approval:** `VERSION`, root/runtime package versions, `Formula/docket-cli.rb`, installer
default, CHANGELOG release section, release-truth tests, final ROADMAP/TODO/spec/metrics rollups, the
new Git tag, and GitHub release verification. `.github/workflows/release.yml` changes only if the
rehearsal proves its current contract false.

**Acceptance / oracle:** before any external mutation, print the proposed version, exact commit,
asset manifest, and approval boundary. Version/tag/package/formula/installer must agree. Both wheel
and sdist must install outside checkout and pass the release journey on Linux and macOS. The public
release must contain wheel, canonical sdist/versioned installer asset, individual checksum,
`SHA256SUMS`, SPDX JSON, and a GitHub-verifiable provenance attestation bound to exact digests.
Tampered bytes must fail verification. Fresh Homebrew/versioned-installer paths must resolve to the
new immutable assets. Only after public verification may Wave 29/Phase 23 become complete.

**Focused validation:** version/release/public-truth tests, local artifact manifest and tamper check,
release journey, and workflow syntax before approval. Post-publication: query GitHub release assets
and attestation, install from public URLs on both OS jobs, then run full canonical closure gates and
snapshot a clean synchronized `main`.

**Handoff:** report approval text/time, tag/commit, release/run/attestation URLs, asset names/digests,
cross-platform install evidence, failures, cleanup, and the final board/phase status. External
publication is never implied by claiming the card.

---

## ◇ WAVE 36 CLOSED (2026-09-21) — eleven defects the documentation audit found in code

**Measured at `834321d` (all gates green, main pushed).** The documentation audit fixed every
place where prose was wrong and listed thirteen where spec and code disagreed. Each was then
re-verified against the live path, most by running it under a throwaway `DOCKET_HOME`. Two
turned out not to be defects (`tack` is an audit label on the HTTP transport, not a fifth
channel; `/status.json` already emits numeric budgets). Three new ones surfaced: `provision_pod`
builds workspace paths from an unvalidated project string (reproduced through the function
`POST /pods` calls), `docket mcp servers add` rejects its own help example because Click eats the
`--` separator before `cmd_mcp` sees it (reproduced), and `POST /approvals/<token>` lets the HTTP
caller name any channel, including a grant tagged `timeout`.

**Worker packets.** Locators, allowed and forbidden paths, RED tests, focused gates and the
return format for every card are in
[.agents/handoffs/wave-36-worker-packets.md](.agents/handoffs/wave-36-worker-packets.md). A worker
loads its card with `card_packet.py W36-C<N>`, reads that file's §0 and its own packet, and
nothing else.

**Rules for every card.** Spec requirement text first, then a RED test seen failing on the base
for the stated reason, then the smallest change. Workers never edit `TODO.md`, `ROADMAP.md`,
`README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `specs/README.md`, or any spec's version header
and changelog section: they return the line and the integrator applies it once per batch. That
is what lets three cards share `pod-dispatch.spec.md`. `scripts/metrics.py --check` is expected
to fail on a branch that adds tests; every other gate must pass.

**Contention and batches.** A batch starts when the previous one is merged and green.

| Batch | Cards | Merge order | Why this batch |
| --- | --- | --- | --- |
| 1 | C1, C2, C4, C5, C6, C7 | C1, C2, C4, C5, C7, C6 | disjoint functions; C6 last because it changes behaviour |
| 2 | C3, C8, C9, C10 | C3, C8, C9, C10 | C3 shares `serve.py` and `serve-read-api.spec.md` with C1; C8 and C9 share `cli/__init__.py` with C2 |
| 3 | C11 | — | docstrings in the hottest file; must describe what batches 1 and 2 shipped |

Hot files are owned at function level (full table in the packets file): `serve.py`
(C1 every project-taking handler, C3 `_handle_post_approvals`), `cli/_mcp.py` (C2 `_servers_*`,
C4 `tool_approvals_*`), `cli/_agents.py` (C1 declarative path, C5 `_maintain_rebuild`, C8 info
JSON), `cli/__init__.py` (C2 `cmd_mcp`, C8 list JSON and `cmd_snapshot`, C9 root callback and
models footer, C11 five docstrings).

**Publication order.** C1's RED test documents a traversal in a Bearer-authenticated,
loopback-only route. The integrator pushes this board together with C1, or C1 first.

### W36-C1 — validate project ids at the core provisioning boundary

**Status:** DONE (2026-09-21, merged a46782c) · **Size:** M · **Owner:** one worker · **Batch:** 1

**Trigger (deterministic reproduction):** `core/pod_provisioning.py::provision_pod("../../x",
"software", location=<dir>)` under a throwaway home succeeds and creates `x/`, `x-lead/` and
`x-implementer/` at the `DOCKET_HOME` root, outside `workspaces/`. `serve.py::_handle_post_pods`
checks only that `project` is a non-empty string; only `cli/_agents.py::run_init` slugifies.
`input-validation.spec.md` §1 has had no implementing function (spec Status: Partial).

**Goal:** one `validate_project_id` in `core/provisioning.py`, enforced as the first statement of
`provision_pod`, mapped to `400` by every `serve.py` handler that takes a project, and to exit 1
by the declarative `docket init --from` path.

**Non-goals:** reserved-word list, `location` path validation (§2), changing `slugify`,
migrating existing pods.

**Owns:** `core/provisioning.py`, `core/pod_provisioning.py::provision_pod`, `serve.py`
(`_handle_post_pods`, `_handle_post_tasks`, `_handle_post_dispatch`, the `/tasks/` and `/traces/`
`do_GET` branches), `cli/_agents.py::_cmd_add_declarative` and `_provision_pod_from_spec`,
`input-validation.spec.md` §1, `serve-read-api.spec.md` (`POST /pods` and project-segment errors).

**Acceptance / oracle:** `POST /pods {"project": "../../escaped", ...}` with a valid Bearer
returns `400`; the filesystem is the oracle — no path containing `escaped` exists under the
test's temp root and `fleet.json` has no such agent. Every id `slugify` can emit still
provisions. A declarative spec with a bad `id` exits 1 and provisions nothing.

**RED:** the `POST /pods` test returns `201` and creates the directories on the base.

**Focused validation:** `uv run pytest -q tests/integration/test_serve_pods_endpoint.py tests/unit/test_serve.py`, then the worker gates.

### W36-C2 — make `docket mcp servers add` reachable from the real CLI

**Status:** DONE (2026-09-21, merged c68dcbd) · **Size:** S · **Owner:** one worker · **Batch:** 1

**Trigger (deterministic reproduction):** `docket mcp servers add playwright -- npx -y
@playwright/mcp@latest` — the help text's own example — exits 1 with "Missing '--' separator".
Click consumes the `--` before `cli/__init__.py::cmd_mcp` reads `ctx.args`.
`tests/integration/test_mcp_servers_cli.py` calls `_mcp.run_mcp` with `--` already in the list,
so no test crosses the seam. No external MCP server can be configured from the CLI today.

**Goal:** the separator reaches `cli/_mcp.py::_servers_add` through the real entry point; flags
after `--` belong to the server command verbatim.

**Non-goals:** `mcp serve`, the stored schema, `__main__.py`.

**Owns:** `cli/__init__.py::cmd_mcp`, `cli/_mcp.py` (`run_mcp`, `_servers_*`),
`tests/integration/test_mcp_servers_cli.py`, `mcp-client.spec.md` requirement 21 (which
contradicts itself and is rewritten).

**Acceptance / oracle:** a subprocess `python -m docket mcp servers add …` with an isolated
home exits 0 and `load_mcp_servers()` holds `["npx", "-y", "@playwright/mcp@latest"]`; `--env`
before `--` is parsed, after `--` is stored verbatim; a missing separator and an empty command
still exit 1. Every existing `run_mcp` test passes unchanged; `help.golden` is byte-identical.

**RED:** the subprocess test exits 1 on the base.

**Focused validation:** `uv run pytest -q tests/integration/test_mcp_servers_cli.py`, then the worker gates.

### W36-C3 — HTTP may not forge an approval's channel

**Status:** DONE (2026-09-21, merged 9ffbf95) · **Size:** S · **Owner:** one worker · **Batch:** 2

**Trigger (read on the live path):** `serve.py::_handle_post_approvals` accepts any `channel` in
`core/approval.py::APPROVAL_CHANNELS`, so a Bearer holder can record a decision in the
hash-chained audit log as `cli`, `telegram` or `mcp`, or a **grant** as `timeout` — which
`serve-read-api.spec.md` says only ever pairs with `denied`.

**Goal:** the HTTP transport may claim only `http` (default) or `tack`; anything else is `400`
before any approval state changes.

**Non-goals:** changing `APPROVAL_CHANNELS`, auth, or any other channel's path.

**Owns:** `serve.py::_handle_post_approvals`, `tests/unit/test_serve.py` channel tests,
`serve-read-api.spec.md` `POST /approvals/<token>` text.

**Acceptance / oracle:** `{"action": "grant", "channel": "timeout"}` and `"cli"` return `400`,
`approval_get(token)["state"]` is still `pending`, and no `approval.*` audit entry was written;
`"tack"` and the default still work.

**RED:** the `timeout` grant returns `200` and writes `channel=timeout` on the base.

**Focused validation:** `uv run pytest -q tests/unit/test_serve.py tests/unit/core/test_approval.py`, then the worker gates.

### W36-C4 — an MCP grant or deny resolves the dispatch task it gated

**Status:** DONE (2026-09-21, merged 7de7219) · **Size:** S · **Owner:** one worker · **Batch:** 1

**Trigger (read on the live path):** `cli/_mcp.py::tool_approvals_grant` and `_deny` never call
`core/dispatch.py::resolve_waiting_approval`; the CLI, HTTP and Telegram paths all do. A
`waiting_approval` task decided over MCP stays there forever. Contradicts
`security-gates.spec.md` requirement 2 and the docstrings' own "Identical to `docket approve`".

**Goal:** mirror `cli/_approve.py` and `cli/_deny.py` exactly, including the `ApprovalNoop` branch.

**Non-goals:** `core/dispatch.py`, the `_servers_*` half of `cli/_mcp.py`.

**Owns:** `cli/_mcp.py::tool_approvals_grant`, `tool_approvals_deny`;
`tests/integration/test_mcp_server.py`; `pod-dispatch.spec.md` approval requirement 4;
`mcp-server.spec.md` approvals tool text.

**Acceptance / oracle:** from a `waiting_approval` fixture, `tool_approvals_grant(token)` leaves
the task `pending` with the gate override recorded; `tool_approvals_deny(token)` leaves it
`failed` with `failureKind == "approval_denied"`.

**RED:** both tasks stay `waiting_approval` on the base.

**Focused validation:** `uv run pytest -q tests/integration/test_mcp_server.py`, then the worker gates.

### W36-C5 — `maintain rebuild` never deletes memory and refuses a pod member

**Status:** DONE (2026-09-21, merged e434d57) · **Size:** S · **Owner:** one worker · **Batch:** 1

**Trigger (read on the live path):** `cli/_agents.py::_maintain_rebuild` backs up five top-level
files, regenerates through the legacy flat-agent `_create_workspace`, then unlinks every
`memory/*.md` with no distillation and no copy — against the rule `clean` and `reset` enforce.
For a pod member it also replaces the role prompt with the generic template, writes a
`TOOLS.md` a Lead must not have, and resets `HEARTBEAT.md`.

**Goal:** rebuild never touches `memory/`; a pod member (meta carries `pod`) is refused with
exit 1 before the prompt and before any write; the function returns its exit code.

**Non-goals:** a role-aware re-render for pod members (follow-up), `clean`/`reset`.

**Owns:** `cli/_agents.py::_maintain_rebuild` and the rebuild branch of `run_maintain`; a
maintain integration test; `agent-lifecycle.spec.md` rebuild section.

**Acceptance / oracle:** a flat agent's `memory/2026-01-01.md` has identical bytes after a
confirmed rebuild; a pod member's rebuild exits 1 with `SOUL.md` bytes unchanged and no
`.backup-*` directory created.

**RED:** the log file is gone and the pod member's rebuild returns 0 on the base.

**Focused validation:** `uv run pytest -q tests/integration -k maintain`, then the worker gates.

### W36-C6 — dispatch runs the pod's blueprint pipeline

**Status:** DONE (2026-09-21, merged f26376d + e1bc9c2) · **Size:** M · **Owner:** one worker · **Batch:** 1

**Trigger (fifth unwired-machinery instance):** `core/dispatch.py::effective_pipeline(project,
None)` always returns `core/pipeline.py::default_pipeline()`. Nothing on the dispatch path reads
the `blueprint` meta that provisioning records, so a `research`, `content` or `ops` pod runs
only its Lead while `docket init --help` promises "Critic gates the final step". No command
exports a blueprint pipeline for `--file`, so there is no workaround.

**Goal:** with no caller-supplied spec, start from the Lead's blueprint `default_pipeline`
(`core/blueprints.py::get_blueprint`), falling back to the built-in default when the key is
absent or unknown, then apply the existing rework-budget patch.

**Non-goals:** new flags, a pipeline export command, `--file` precedence, gate semantics,
`core/orchestrator.py`.

**Owns:** `core/dispatch.py::effective_pipeline`, `core/blueprints.py` module docstring, the
unit tests for both, one assertion in `tests/integration/test_pipeline_cli.py`,
`pod-blueprints.spec.md` (delete the known-gap text), `pod-dispatch.spec.md` "Pipeline order and
participation".

**Acceptance / oracle:** a `research` pod resolves to `lead, researcher, analyst, writer,
critic`; a `software` pod and a pod with no or an unknown `blueprint` resolve exactly as before;
the pod's `maxReworkCycles` reaches the Critic's rework edge; `docket pipeline plan` on a
research pod lists no step as "skipped — role not in pod".

**RED:** the research pod resolves to `lead, implementer, reviewer, tester` on the base.

**Behaviour change:** non-`software` pods run more hops and spend more tokens. The worker
returns the `CHANGELOG` line; the integrator records one live `research` and one live `ops`
dispatch against the local endpoint before closing the wave.

**Focused validation:** `uv run pytest -q tests/unit/core/test_dispatch.py tests/unit/core/test_blueprints.py tests/integration/test_pipeline_cli.py`, then the worker gates.

### W36-C7 — a timed-out verify command leaves no orphan

**Status:** DONE (2026-09-21, merged e39ef34) · **Size:** S · **Owner:** one worker · **Batch:** 1

**Trigger (measured):** `edges/adapters/system.py::run_verify_cmd("sleep 6 & wait", ".",
timeout=1)` returns at 1.0 s and the `sleep` is still alive afterwards: `subprocess.run(shell=True,
timeout=…)` kills only the shell. `pod-dispatch.spec.md` Cancellation requirement 2 claims the
command runs in its own session and that cancelling kills its group; neither is true.

**Goal:** run the verify command in its own session and kill the whole group on timeout, with
the return value, truncation and refusal path byte-identical. Narrow the spec to what ships.

**Non-goals:** registering the pid, `on_spawn` plumbing, `docket runs cancel`.

**Owns:** `edges/adapters/system.py::run_verify_cmd`, the verify-gate integration tests,
`pod-dispatch.spec.md` Cancellation requirement 2.

**Acceptance / oracle:** a verify command that backgrounds a child writing its pid to a temp
file, run with `timeout=1`: within 2 s of return `os.kill(pid, 0)` raises `ProcessLookupError`.

**RED:** the child is alive on the base.

**Focused validation:** `uv run pytest -q tests/integration/test_verify_gate.py tests/integration/test_retries_and_timeouts.py tests/guards/test_no_subprocess_in_core.py`, then the worker gates.

### W36-C8 — CLI `--json` emits the types its spec and `/status.json` already use

**Status:** DONE (2026-09-21, merged e8745bc) · **Size:** S · **Owner:** one worker · **Batch:** 2

**Trigger (read on the live path):** `list --json` and `info --json` emit `budgetUsd` as the
stored string; `snapshot` emits `lastActivity: "—"`. `cli-json-shapes.spec.md`, `/status.json`
and `cost --json` all use `number | null` and `"never"`.

**Goal:** one pure helper for "stored budget to `float | None`"; the two CLI emitters use it;
`snapshot` emits `"never"`. Storage and human tables are unchanged.

**Non-goals:** storage migration, new keys, `/status.json`.

**Owns:** the `list --json` builder and `cmd_snapshot` in `cli/__init__.py`, the `info --json`
builder in `cli/_agents.py`, `cli-json-shapes.spec.md`, one sentence in `docket-meta.spec.md`.

**Acceptance / oracle:** parsed output has a numeric or null `budgetUsd` for an agent with and
without a budget; an agent with no logs has `lastActivity == "never"`.

**Goldens that change, with the reason stated line by line:** `list_--json.golden`,
`info_myshop_--json.golden` — the old output contradicted the spec.

**Focused validation:** `uv run pytest -q tests/integration/test_edit_snapshot.py`, the golden suite, then the worker gates.

### W36-C9 — retire two claims nothing backs: `--debug` and the PRICE override

**Status:** DONE (2026-09-21, merged 9517c5f) · **Size:** S · **Owner:** one worker · **Batch:** 2

**Trigger (read on the live path):** `--debug` sets `os.environ["DEBUG"]` and `rg DEBUG src/`
finds no reader, while `cli/_help.py` calls it "Verbose mode". The `docket models` footer says
prices can be overridden in `docket-models.json`; `models_policy.load_registry` reads no pricing key.

**Goal:** `--debug` stays accepted as a hidden no-op that writes nothing, and leaves the help
and the generated environment table; the models footer loses the override clause.

**Non-goals:** building a verbose mode or a pricing overlay.

**Owns:** the root callback and the models footer in `cli/__init__.py`, `cli/_help.py`, the
`DEBUG` rows in `scripts/gen_cli_docs.py`, `cli-interface.spec.md` Global options.

**Acceptance / oracle:** invoking the root callback with `--debug` exits 0 and leaves
`os.environ` without `DEBUG`; `docs/commands.md` regenerated.

**Goldens that change:** `help.golden` (one line), `models.golden` (footer) — both strings were false.

**Focused validation:** `uv run pytest -q tests/unit/cli`, the golden suite, `gen_cli_docs --check`, then the worker gates.

### W36-C10 — budget warnings read the same estimate the dispatch gate does

**Status:** DONE (2026-09-21, merged 37301e9) · **Size:** S · **Owner:** one worker · **Batch:** 2

**Trigger (read on the live path):** `cli/_doctor.py::_check_budget` and the cost-threshold
warning in `cli/_cost.py` compare the budget with **recorded** cost, which `DocketDriver` always
reports as `0.0`, so they can never fire. The dispatch gate uses
`core/dispatch.py::pod_gating_cost`, which falls back to a labelled estimate.

**Goal:** both warnings use the gating figure and print it with the existing
`~$… (estimated — no cost recorded)` label. An estimate is never printed as spend.

**Non-goals:** the dispatch gate, `MODEL_PRICING`, the `docket cost` table, `cost --json`.

**Owns:** `cli/_doctor.py::_check_budget` and its caller, the cost-threshold warning in
`cli/_cost.py`, `tests/unit/cli/test__doctor.py`, `cost-tracking.spec.md` Enforcement requirement 5.

**Acceptance / oracle:** an agent with a `0.01` cap, zero recorded cost and measured tokens whose
estimate exceeds the cap is reported over budget with the estimated label and a non-zero issue
count; `cost.golden` is byte-identical.

**RED:** `_check_budget` reports nothing on the base.

**Focused validation:** `uv run pytest -q tests/unit/cli/test__doctor.py`, then the worker gates.

### W36-C11 — help-text and spec sweep for what the audit left in prose

**Status:** DONE (2026-09-21, merged 1fd830a) · **Size:** S · **Owner:** one worker · **Batch:** 3

**Trigger (verified 2026-09-19):** five docstrings and three spec passages still state things
the code does not do: `cmd_pod` ("created by `docket add`"), `cmd_init` (workdir auto-provision
"if omitted"), `cmd_maintain` (`sessions` "archive", `check` "fleet registration"), `cmd_scope`
(updates `SOUL.md`), `_delete_pod` (gateway restart), `core/agent_loop.py` "Durability";
`input-validation.spec.md` §2/§4/§5, `model-profiles.spec.md` overlay requirements 1 and 3,
and the unscheduled remainders in `user-stories.md`.

**Goal:** prose matches the code as it stands after batches 1 and 2. Docstrings and spec text
only.

**Non-goals:** any code change, `README.md`, the `docs/` guides.

**Owns:** the five docstrings in `cli/__init__.py`, one in `core/agent_loop.py`, the three spec
passages, regenerated `docs/commands.md`.

**Acceptance / oracle:** the integrator's docstring-stripped `ast.dump` comparison reports
`SAME`; `help.golden` byte-identical; `comment_lint.py --check src/docket/cli/__init__.py`
reports zero `long-def-doc`.

**Focused validation:** `gen_cli_docs.py --check`, `validate-specs.sh`, `comment_lint.py --check` on both files, then the worker gates.
## ◇ WAVE 37 CLOSED (2026-09-25) — defects found by running the product (D-41)

Every card: spec section first, RED test seen failing on the wave base for the stated reason,
smallest change, the §"How to use this board" definition of done. Board, ROADMAP, README,
CHANGELOG, spec headers/changelogs and `specs/README.md` are integrator-owned.

### W37-C1 — a `cd` prefix must not turn an allowed command into an approval

**Status:** DONE (2026-09-25, merged f9d6375 + badc988) · **Size:** S · **Batch:** 1

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

**Status:** DONE (2026-09-25, merged 0defabe + c215a6a) · **Size:** M · **Batch:** 1

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

**Status:** DONE (2026-09-25, merged 82225bc + 7fd3f4c) · **Size:** S · **Batch:** 1

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

**Status:** DONE (2026-09-25, merged c1a6ef3 + e314a8a) · **Size:** S · **Batch:** 1

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

**Status:** DONE (2026-09-25, merged 2b25bcd + f0ee31b) · **Size:** S · **Batch:** 2 (after C2 merges; both touch `serve.py`)

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

**Status:** DONE (2026-09-25, merged 5d65336 + 271f26f) · **Size:** S · **Batch:** 2 (after C3 merges; both may touch `cli/__init__.py`)

**Trigger:** `cli/_cost.py::run_cost` returns the fleet snapshot for `--json` before reading
`agent_id`, so `docket cost <id> --json` returns every agent and a bogus id exits 0 (sibling
commands exit 1). `docket roles list --json` prints the table and exits 0: commands that dispatch
`ctx.args` by hand never reject unknown options.

**Goal:** `cost <id> --json` emits that agent's row in the documented shape (amend
`cli-json-shapes.spec.md`), unknown id -> stderr error, exit 1. Hand-dispatched commands (`roles`,
`maintain`, `gates`, `keys`, `policies`; not `add`/`init`/`pod`/`pipeline`, which pass options through) reject an unrecognised `--flag` with exit 2 and
the usage line, through one shared helper.

**Owns:** `cli/_cost.py`, the `ctx.args` parsers in those modules, a shared helper in `cli/`,
their tests, `cli-json-shapes.spec.md`, `docs/commands.md` (regenerated).

**Acceptance / oracle:** `cost <real> --json` has exactly one agent; `cost bogus --json` exit 1,
nothing on stdout; `roles list --json` exit 2; every documented flag of those commands still
works (goldens unchanged).

**RED:** the three assertions fail on the base.


---

## ◆ PHASE 26 — COMPLETE (opened 2026-09-25, closed 2026-09-26): the configuration contract (D-42)

**Opened 2026-09-25, immediately after Wave 37 closed (`3089a00`) removed the file-contention
blocks (W37-C5 on `core/approval.py`, W37-C6 on `cli/_policies.py`/`cli/_keys.py`).** Twenty
cards. **Wave 38 batch A closed 2026-09-25**: P26-1, P26-2, P26-13, P26-16, P26-18 merged (P26-1 by the coordinator, the rest by one Sonnet worker each in isolated worktrees); **Batch B closed 2026-09-26** (P26-4 `acf471f`, P26-19 `1781c73`; both Sonnet workers, integrator-resolved conflicts). **Wave 39 closed 2026-09-26**: P26-3, P26-5 (`971cb4c`), P26-6 (`c12dae5`), P26-7 (`3d63caa`), P26-8 (`1184eb8`) — five Sonnet workers in parallel from base `2087e0b`; the integrator re-versioned two silent same-day spec collisions (security-gates 0.24.0, pod-dispatch 6.12.0, pipeline-format 2.4.0). **Wave 40 closed 2026-09-26 — Phase 26 complete, 20/20 cards DONE**: P26-9 `17c41c9`, P26-10 `5c80be7`, P26-11, P26-12 `bb5598f`, P26-14 `6db711d`, P26-15 `8b5a1c8`, P26-17 `680c793`, P26-20 `2236624`; eight Sonnet workers, pre-assigned spec versions eliminated the silent same-version collisions (the two remaining collisions were cross-wave and re-versioned at merge). Decision, verdict table and the
six-property contract: [docs/adr/0008-configuration-contract.md](docs/adr/0008-configuration-contract.md).
The user-facing map of every installed file is [docs/CONFIGURATION.md](docs/CONFIGURATION.md).
Each closing card deletes its own bullet from that guide's §5 "Sharp edges" in the same commit.

**Trigger (explicit request + reproductions):** the 2026-09-25 request to make agent, pipeline and
governance configuration robust, standard and versatile, to stop a fixed ~24 KB budget from
limiting orchestration, and to ship recipes that are robust for real use yet easily configurable.
The reproductions are quoted per card, at `a592328`. A same-day E2E connection audit (pod →
config changes → custom-role pipeline run on the local endpoint) added P26-18/P26-19/P26-20; its
positive results are in `docs/adr/0008-configuration-contract.md` ("What the E2E run proved").

**Proposed batching:** the integrator confirms it when the phase opens, from function-level
contention.

| Wave | Cards | Hot file and function ownership |
| --- | --- | --- |
| 38 | P26-1, P26-2, P26-4, P26-13, P26-16, P26-18, P26-19 | `identity.py::_runtime_workspace_context` → P26-2 only; `dispatch.py` pod-setting readers → P26-4 only, claim/refusal lifecycle → P26-19 only; `core/pod.py` membership → P26-18 only; `cli/_doctor.py`: each card adds its **own** check function |
| 39 | P26-3, P26-5, P26-6, P26-7, P26-8 | `dispatch.py`: P26-5 the hop env builder, P26-6 `effective_pipeline`/`_blueprint_pipeline`, P26-7 the hop-message builder; `tools.py`/`security.py` → P26-8 only; `identity.py` → P26-3 only |
| 40 | P26-9 → P26-10 → P26-17, with P26-11, P26-12, P26-14, P26-15, P26-20 alongside | P26-9, P26-10 and P26-17 all touch templates or `identity.py`, so they run serially; P26-11 is read-only over merged code; P26-20 is data + tests over P26-6/P26-7/P26-18's merged behaviour |

Every card follows the §"How to use this board" definition of done.

### P26-1 — a broken policy fails closed, never open

**Status:** DONE (2026-09-25, `ed965e5`) · **Size:** S · **Wave:** 38 · **Spec:** `security-gates.spec.md`

**Trigger:**
- Base: a `pre_tool_call` policy with `match.pattern: "make\\s+deploy"` and `action: block` makes
  `docket policies test pre_tool_call implementer 'make deploy'` return `deny`.
- One extra `(` in the pattern → `allow`, and `docket policies validate` prints "valid".
- An invalid JSON escape in the file → `allow`.
- Cause: `core/policy.py:109-110,132-133` `continue` silently; `validate_policy` never compiles the
  regex.
- Related dry-run gap: `policies test pre_tool_call implementer 'write path="main.py"'` reports
  `ask` ("'write' is not on the curated allowlist") — the W37-C1 parity change runs the bash
  classifier on every text, but the live gate classifies `kind=exec` tools only, so a policy on a
  `write`/`edit` render cannot be tested truthfully.

**Goal:**
- An unloadable policy file, uncompilable pattern or unknown action makes every call on that
  file's hook (all hooks, when the JSON cannot be parsed) resolve to `deny`, naming the file.
  This covers the live gate, `pre_input`, `pre_output` and `policies test`.
- `policies validate` compiles regexes.
- `docket doctor` reports broken policies as errors.
- A trace event names each skipped file.
- Fix the stale `validate_policy` docstring and the `programmer` role in the `policies init` hint.
- `policies test pre_tool_call` accepts `--tool <name>` (default `bash`) and only applies the
  command classifier when the named tool's kind is `exec`, matching `evaluate_tool_call`.

**Non-goals:** policy schema changes; loosening; per-file enable/disable.

**Owns:** `core/policy.py` (evaluation plus `validate_policy`), `cli/_policies.py` validate, a new
doctor check function, and the policy section of `security-gates.spec.md`.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| valid block | `deny` |
| bad regex | `deny`, with a reason naming the file |
| bad JSON | `deny` |
| unknown action | `deny` |
| `policies validate` on the bad regex | exit 1 |
| doctor on the bad regex | reports it |
| `policies test --tool write 'write path="main.py"'` with the warn fixture | `allow`, policy hit reported, no classifier verdict |
| a valid store | every existing test and golden unchanged |

**RED:** the bad-regex and bad-JSON cases return `allow` on the base.

### P26-2 — the system prompt never drops state silently

**Status:** DONE (2026-09-25, merged 7b6544a) · **Size:** S · **Wave:** 38 · **Spec:** `agent-loop.spec.md` req. 30

**Trigger:**
- A `SOUL.md` of 21.9 KB → `MEMORY.md` truncated.
- A `SOUL.md` of 24.4 KB → `HEARTBEAT`, `AGENTS`, `TOOLS` and `MEMORY` all absent from
  `system_prompt_for_agent`, with **no marker** (`identity.py:_runtime_workspace_context` returns
  `""` when the header does not fit, and `break`s after the first truncation).
- This violates req. 30 ("mark any truncation/omission visibly").

**Goal:**
- Protected order: the runtime contract, then `HEARTBEAT` state, then `TOOLS`, are never dropped
  in favour of `SOUL`.
- An oversized `SOUL` is truncated visibly first.
- Every omitted section gets a one-line marker naming it and its size.
- Each composition emits a `prompt_composed` trace event: per section, the bytes included and
  whether it was full, truncated or omitted.

**Non-goals:** changing the budget size (P26-3); new sections.

**Owns:** `core/identity.py` composition helpers, the trace call site in `core/agent_loop.py`, and
spec req. 30.

**Acceptance / oracle:**
- With the 24.4 KB fixture, the prompt contains the TOOLS verify-gate line and the HEARTBEAT ledger
  region, a `SOUL` truncation marker, and an omission marker for anything dropped.
- The trace event lists all four sections.
- A small workspace composes byte-identically to the base.

**RED:** the 24.4 KB fixture lacks `## TOOLS.md` and any marker.

### P26-3 — context budgets follow the resolved model window

**Status:** DONE (merged, worker commit `9f3926f`; dispatch hop-carryover and compaction budgets deliberately left on the fixed default — wiring them is a measured follow-up, not scheduled) · **Size:** M · **Wave:** 39 (after P26-2) · **Spec:** `agent-loop.spec.md` 1.20.0,
`session-history.spec.md` 1.5.0

**Trigger:**
- `identity.py:263` budgets state as `CONTEXT_TOKEN_BUDGET` × 4 bytes ≈ 24 KB for every model,
  16k and 200k windows alike.
- The hop handoff budget is the archetype `tokenBudget` (6000) whatever the window (`context.py`).
- The registered `contextWindow`/`maxTokens` are already read (`edges/adapters/llm.py:469-470`) and
  preflighted.

**Goal:**
- Default both budgets to documented shares of the resolved window, after the output reserve and
  tool schemas.
- `CONTEXT_TOKEN_BUDGET` and an archetype `tokenBudget` stay **explicit overrides** when set.
- `docket maintain check` and the `prompt_composed` event report the effective budget and its
  source.
- On an unregistered window, keep today's constants and say so.

**Non-goals:** changing `AGENT_LOOP_TOKEN_BUDGET` (a cost stop, not a context budget); compaction
changes.

**Owns:** the budget resolution in `core/identity.py` and `core/context.py`, and the window
plumbing from `DocketDriver` into `LoopConfig`/`ToolContext`.

**Acceptance / oracle:**
- A 200k-window provider fits the 24.4 KB `SOUL` fixture with every section full.
- A 16k window keeps today's behaviour, via P26-2's protected order.
- The request preflight still passes on the local endpoint.
- A live dispatch on the 16k endpoint reaches the same terminal state as the base.

**RED:** the 200k fixture still drops sections on the base.

### P26-4 — pod settings are typed, validated and writable

**Status:** DONE (2026-09-26, merged acf471f) · **Size:** M · **Wave:** 38 · **Spec:** `pod-dispatch.spec.md`,
`cli-json-shapes.spec.md`

**Trigger:**
- `maxReworkCycles`, `turnTimeoutS` and `verifyTimeoutS` are writable only by hand-edit or the
  hidden `_json meta-set`.
- Invalid values silently become defaults (`dispatch.py:434-463`).
- `profile --budget` stores `budgetUsd` as the raw string (`cli/__init__.py:934`).
- This **reverses D-41's "not scheduled"** for a timeout writer (see D-42 for what changed).

**Goal:**
- One Pydantic `PodSettings` model over the Lead-meta keys.
- `docket pod <p> config [get|set|unset] [<key> [<value>]]`, with `--json` on `get`. Values are
  validated at write and audited (`pod.config`).
- Dispatch reads the model. An invalid stored value **refuses** dispatch with the key and the
  reason, instead of defaulting.
- Doctor flags it.
- `profile --budget` writes a number.

**Non-goals:** new setting semantics. Later cards add their keys (`approvalMode`, `pipeline`,
`allowCommands`) to this model.

**Owns:** the new model in `core/pod.py`, the `dispatch.py` pod-setting readers, `cli/_pod.py`
config, and the `profile --budget` write.

**Acceptance / oracle:**
- `set maxReworkCycles 2` → `pipeline plan` shows 2.
- `set turnTimeoutS abc` → exit 1, and the meta is unchanged.
- A hand-written `"turnTimeoutS": "abc"` → dispatch refuses, naming the key.
- `budgetUsd` is persisted as a number.
- Goldens change only for the new help text, with every diff line explained.

**RED:** `pod <p> config` does not exist, and an invalid stored timeout dispatches.

### P26-5 — unattended turns can refuse instead of waiting on nobody

**Status:** DONE (merged `971cb4c`, worker commit `25186d3`) · **Size:** S · **Wave:** 39 (after P26-4) · **Spec:** `pod-dispatch.spec.md` 6.11.0,
`security-gates.spec.md` 0.23.0

**Trigger:**
- On the 2026-09-25 real dispatch, the tester hop failed on 3 × `approval_timeout`, having waited
  120 s each with no channel able to answer.
- Only harness mode can refuse (`DOCKET_APPROVAL_MODE=refuse`, set at `cli/_harness.py:185`).
  Serve, schedules, webhooks and MCP always wait (`docket_runtime.py:201-204`).

**Goal:**
- A pod setting `approvalMode: wait|refuse` (default `wait`, today's behaviour) is threaded into the
  hop's tool env.
- `refuse` ends the call at once with the existing `approval_unavailable` shape naming the tool,
  call and policy.
- The task fails with that reason, recorded in the run and the trace.

**Non-goals:** channel-liveness detection; changing the default.

**Owns:** the hop tool-env builder in `core/dispatch.py`, plus the `PodSettings` key.

**Acceptance / oracle:**
- With `refuse`, an asking call ends the hop well under one approval timeout, with a named reason.
- With `wait`, behaviour is identical to the base.

**RED:** there is no pod-level refuse, and the hop waits the full timeout.

### P26-6 — a pipeline file can be a pod's default for every trigger

**Status:** DONE (merged `c12dae5`, worker commit `e06a401`; follow-up noted: serve.py webhook calls `effective_pipeline` without catching the new bound-pipeline `DispatchError`) · **Size:** M · **Wave:** 39 (after P26-4) · **Spec:** `pipeline-format.spec.md` 2.3.0,
`pod-dispatch.spec.md` 6.12.0 (re-versioned from the worker's 6.11.0 — collided with P26-5)

**Trigger:** only `cli/_pod.py:575` and `cli/_pipeline.py:167,205` pass `spec=`. `serve.py:453,503,1064`
(sweep, schedule, webhook) and `cli/_mcp.py:127` always run the blueprint default, so a declared
pipeline can never run unattended. This is the unwired-machinery shape.

**Goal:**
- `docket pod <p> config set pipeline <file>` validates the file, plans it against the roster, and
  stores a docket-owned copy plus its hash in the Lead workspace.
- `effective_pipeline(project, None)` resolves that pipeline before the blueprint, for every
  trigger.
- `unset` restores the blueprint default.
- `pipeline plan <p>` names the source.
- The spec states `maxReworkCycles` precedence.

**Non-goals:** new dialect features; multiple pipelines per pod.

**Owns:** `core/dispatch.py::effective_pipeline` and `_blueprint_pipeline`, plus the `PodSettings`
key.

**Acceptance / oracle:**
- With a bound pipeline, a serve sweep and an MCP dispatch execute its steps (trace step ids).
- An unbound pod is unchanged.
- A roster missing a step's role is refused at `set`, not at run.

**RED:** a serve-sweep dispatch ignores the bound file.

### P26-7 — custom roles and steps carry their own hop instructions; `variables` get a consumer

**Status:** DONE (merged `3d63caa`, worker commit `b096fdf`) · **Size:** M · **Wave:** 39 · **Spec:** `role-archetypes.spec.md` 1.8.0,
`pipeline-format.spec.md` 2.4.0 (re-versioned from the worker's 2.3.0 — collided with P26-6)

**Trigger:**
- `dispatch.py:571-572,639`: any role outside lead, implementer, reviewer and tester gets
  `instructions = ""`, so a custom verdict-gated role is never told its marker.
- `resolve_variables` only stores values on the run record (`runs.py:285`).

**Goal:**
- An archetype field `hopInstruction`. A gated role without one gets an instruction generated
  from its `gateContract`.
- An optional pipeline step field `instructions` overrides the role's.
- `${var}` in step instructions is interpolated from the run's resolved variables, which today
  arrive by webhook. Add `--var k=v` to `pipeline run`.
- An unresolved variable refuses the run.

**Non-goals:** variables anywhere else (env, commands).

**Owns:** the hop-message builder in `core/dispatch.py`, the archetype field in
`core/archetypes.py`, the step field in `core/pipeline.py`.

**Acceptance / oracle:**
- The §3.4 `security-reviewer` role's hop message contains its marker instruction.
- A step `instructions: "Focus on ${area}"` with `--var area=auth` renders "Focus on auth".
- The four built-in roles are byte-identical to the base.

**RED:** the custom role's hop message has no instruction.

### P26-8 — a pod can allow its own tool binaries, scoped and audited

**Status:** DONE (merged `1184eb8`, worker commit `1fe5428`) · **Size:** S · **Wave:** 39 (after P26-4) · **Spec:** `security-gates.spec.md` 0.24.0 (re-versioned from the worker's 0.23.0 — collided with P26-5)

**Trigger:**
- `classify_command('pytest -q')`, `('uv run pytest')` and `('python -m pytest')` → `ask`.
- W37-C1 added builtins only, so an unattended tester or implementer on a `uv`/`pytest` project
  must ask, or be told to use `python3 -m`.

**Goal:**
- A pod setting `allowCommands` holds exact binary basenames. Validation rejects paths, shell
  metacharacters, the opaque builtins (`eval`, `exec`, `source`, `.`) and anything that names a
  high-risk class.
- It is carried on `ToolContext` for that pod's turns and merged into the allowlist check only.
- Opaque markers, high-risk classes and policies still apply, most-restrictive-wins.
- `set` is audited.

**Non-goals:** a global allowlist edit; argument patterns; per-agent scope.

**Owns:** `core/security.py::classify_command` (an extra-bins parameter), the `ToolContext` field
and its single use in `core/tools.py::evaluate_tool_call`, and the driver plumbing.

**Acceptance / oracle:**

| Command, in a pod with `allowCommands: [pytest, uv]` | Result |
| --- | --- |
| `pytest -q` | allow |
| `uv run pytest` | allow |
| `uv run pytest && git push origin main` | still asks |
| a `block` policy on `pytest` | still denies |
| `pytest -q` in another pod | still asks |

**RED:** `pytest -q` asks with the setting present.

### P26-9 — generated instructions agree with the runtime contract

**Status:** DONE (merged, worker commit `17c41c9`; known gap recorded in the spec: `cli/_agents.py`/`cli/_install.py` carry their own copy of the same HEARTBEAT-write contradiction for standalone agents and org specialists — small follow-up card) · **Size:** S · **Wave:** 40 · **Spec:** `workspace-structure.spec.md` 1.10.0,
`role-archetypes.spec.md` 1.9.0

**Trigger:**
- The AGENTS red line "Before starting multi-step work, write it to HEARTBEAT.md"
  (`archetypes.py:330,452`) reaches the model, while the runtime contract says private state is
  read-only (`identity.py:178`).
- `WORKFLOW_AUTO.md` tells agents to `cd` and to write `memory/` (`memory.py:114-171`), but is
  never sent.

**Goal:**
- Rewrite the built-in role templates so nothing sent to the model asks for a private write or a
  `cd`.
- Keep `WORKFLOW_AUTO.md` only as the manual-path contract, with a header saying so.
- Bump `POD_TEMPLATE_VERSION`.

**Non-goals:** new template content beyond removing the contradictions.

**Owns:** the built-in template strings in `core/archetypes.py`, `core/memory.py::seed_contract`
text, and the pod template version.

**Acceptance / oracle:**
- A grep-free structural test composes each built-in role's prompt and finds no instruction to
  write `HEARTBEAT.md`/`memory/`.
- Workspace goldens are regenerated, with each line explained.

**RED:** the implementer's composed prompt contains the HEARTBEAT write instruction.

### P26-10 — operator instructions survive regeneration, and roles can be re-rendered

**Status:** DONE (merged `678c469`, worker commit `5c80be7`; set-verify still owns TOOLS.md wholesale by design — operator text lives in INSTRUCTIONS.md; JSON-doctor parity and pod-subcommand completions noted as small follow-ups) · **Size:** M · **Wave:** 40 (after P26-9) · **Spec:** `workspace-structure.spec.md`,
`agent-loop.spec.md` req. 30

**Trigger:**
- `pod set-verify` rewrites `TOOLS.md` wholesale (`cli/_pod.py:374-399`).
- An archetype change never reaches existing members (templates render once at provisioning).
- `POD_TEMPLATE_VERSION` is never compared (`pod_provisioning.py:37,336`; doctor skips pod members
  at `_doctor.py:372,738`).

**Goal:**
- An operator-owned `INSTRUCTIONS.md` per member that docket never writes, composed right after
  `SOUL.md` and inside P26-2/P26-3's budget.
- `docket pod <p> sync [--dry-run]` re-renders `SOUL`, `AGENTS` and `TOOLS` from the current
  archetype and meta for members whose template or archetype version is stale, and shows a diff.
- Doctor flags stale pod members.

**Non-goals:** merging operator edits made inside generated files (they move to
`INSTRUCTIONS.md`).

**Owns:** the overlay read in `core/identity.py`, a re-render function in
`core/pod_provisioning.py`, `cli/_pod.py` sync, and a doctor check.

**Acceptance / oracle:**
- `INSTRUCTIONS.md` text reaches the prompt and survives `set-verify` and `sync`.
- After editing an overlay role, `sync --dry-run` shows the diff and `sync` applies it.
- An untouched pod is a no-op.

**RED:** `set-verify` destroys an operator line in `TOOLS.md`, and `sync` does not exist.

### P26-11 — `docket config explain <agent>`: the effective configuration with provenance

**Status:** DONE (merged, worker commit; golden suite grew to 19 cases with config --help; MCP reported as configured server names only — live enumeration would spawn/audit) · **Size:** M · **Wave:** 40 (after P26-3, P26-4, P26-6, P26-8) · **Spec:**
`cli-json-shapes.spec.md`

**Trigger:** there is no command that answers "what will this agent see and be allowed to do". The
2026-09-25 guide needed two code-tracing audits to find out.

**Goal:** a read-only command, with `--json`, that composes existing functions only. It prints, each
with the source that set it (meta/policy/pin, pod setting, env, default):
- the resolved model and endpoint;
- each prompt section with its bytes and fit status (from P26-2's composer);
- tools after denials, including MCP;
- the policies that apply to the role;
- the effective pipeline and its source;
- budgets, timeouts, `approvalMode` and `allowCommands`.

**Non-goals:** writing anything; a second composer.

**Owns:** a new `cli/_config.py`, and a golden for its help.

**Acceptance / oracle:** for the §3.4 fixture pod, every value matches what a real dispatch uses
(asserted against the trace of a run on the fake driver). A pinned model shows `pinned`.

**RED:** the command does not exist.

### P26-12 — configuration errors are loud; schedules get a writer

**Status:** DONE (merged `6a06840`, worker commit `bb5598f`; JSON doctor path and the stale pod --help key list noted as small follow-ups) · **Size:** S · **Wave:** 40 · **Spec:** `pod-dispatch.spec.md`,
`model-profiles.spec.md`, `role-archetypes.spec.md`

**Trigger:** silent skips at:
- `schedule.py:189,196` (a bad spec is never due; a bad file is `{}`);
- `models_policy.py:256-285` (malformed entries ignored);
- `archetypes.py:664` (overlay role skipped).

`docket-schedules.json` has no writer, and `record_last_run` drops unknown keys.

**Goal:**
- Doctor reports each of these with file, key and reason.
- `docket pod <p> config set schedule "<spec>"` validates and writes through `edges/store.py`;
  `unset` removes it.
- Serve logs a skipped spec once per sweep.

**Non-goals:** new schedule formats.

**Owns:** the doctor check functions, the schedule write path in `core/schedule.py`, and the
`PodSettings` routing for `schedule`.

**Acceptance / oracle:**
- `set schedule "@every 3x"` → exit 1.
- A hand-broken models entry → doctor error naming it.
- A valid schedule set by the command fires under `serve --dispatch`.

**RED:** doctor is silent on all three fixtures.

### P26-13 — secrets are stored once, where they are read

**Status:** DONE (2026-09-25, merged 7ea025a) · **Size:** S · **Wave:** 38 · **Spec:** `api-keys.spec.md`

**Trigger:**
- `cli/_keys.py:95-122` writes every stored key as plaintext into each project workspace's `.env`
  (`write_text` and then `chmod`, so the file briefly carries umask permissions), and nothing
  reads it.
- `DOCKET_SECRETS_BACKEND=keyring` never stores: `edges/adapters/system.py` has lookup only.

**Goal:**
- Stop writing `.env`. `doctor --fix` removes existing copies.
- The keyring backend stores through `secret-tool store`, or `keys add` refuses under `keyring`
  with an honest message. Choose one in the card.

**Non-goals:** new backends; rotation policy.

**Owns:** `cli/_keys.py`, `edges/adapters/system.py` (secret-tool), and a doctor check.

**Acceptance / oracle:**
- After `keys add`, no workspace contains `.env`.
- Turn key resolution is unchanged (the existing endpoint tests pass).
- Under `keyring`, the value is not in `secrets.json`.

**RED:** `keys add` creates `.env` files.

### P26-14 — one default model of record; provider fields that mean something

**Status:** DONE (merged, worker commit `6db711d`; legacy fleet default migrates in and clears on first read) · **Size:** S · **Wave:** 40 · **Spec:** `model-profiles.spec.md`

**Trigger:**
- `fleet.json` `defaults.model` is read only by the hidden `_json default-model-get`
  (`cli/__init__.py:2680`), and it diverges from `docket-models.json` `default` on a fresh install.
- The provider `name` defaults to the literal "Qwen3 30B-A3B (local)" (`provider.py:31`) even with
  `--model qwen`.
- `name`, `cost`, `reasoning`, `input` and `api` are never read.
- `rankAnchors` is live (it maps `modelClass` cheap/strong) but is documented as private.

**Goal:**
- `docket-models.json` `default` is the only default. The fleet key is migrated away and ignored.
- The label derives from `--model`.
- Unread provider fields are dropped or documented as display-only.
- The spec and `CONFIGURATION.md` describe `rankAnchors` truthfully.

**Non-goals:** pricing.

**Owns:** `core/provider.py`, the default-model read and write in `core/fleet.py`/`cli/_install.py`,
and `model-profiles.spec.md`.

**Acceptance / oracle:** after init plus `preset local`, one default exists and matches what agents
resolve. `provider add x url --model m` labels the entry `m`.

**RED:** the two defaults differ after a fresh init.

### P26-15 — registries stay bounded; traces are filed where an operator looks

**Status:** DONE (merged, worker commit `8b5a1c8`; approvals prune is sweep-only by scope call — no CLI slot; cli-interface.spec.md prose left for a later sync) · **Size:** M · **Wave:** 40 · **Spec:** `pod-dispatch.spec.md`, `audit.spec.md`
(retention wording), the trace spec section

**Trigger:**
- This machine: `~/.docket/docket-runs.json` is 9.45 MB with 23,925 runs, rewritten together with a
  same-size `.bak` on every update.
- `approvals/` and `docket-conversations.json` are never pruned either.
- Approval trace events are filed under the agent id (`docket_runtime.py:215` →
  `approval.py:158-160`).
- The `config.py:41-44` audit-rotation comment is stale.
- (Withdrawn 2026-09-25: `guardrail_block` carrying the policy id as `payload.action` is
  **contractual** — security-gates.spec.md req. 4, `cli/_metrics.py` keys its tally on it.)

**Goal:**
- Terminal runs, resolved approvals and closed conversations older than a retention knob (default
  as `TRACE_RETENTION_DAYS`) are removed by the same sweep that expires traces, and by a command.
- Live and pending records are never touched.
- Approval events are filed under the pod.
- Fix the comment.

**Non-goals:** changing audit-log retention (a separate, non-lossy record).

**Owns:** the prune functions in `core/runs.py`, `core/approval.py` and `core/conversations.py`,
the serve sweep call, the `ToolContext.project` value in the driver, and `dispatch.py:260,1181`.

**Acceptance / oracle:**
- A fixture of 10,000 old terminal runs plus 1 running run → after the sweep only the running run
  and the recent ones remain.
- The approval trace lands in `traces/<pod>/`.

**RED:** nothing prunes, and the approval trace sits in `traces/<agent-id>/`.

### P26-16 — lifecycle hygiene, and the `gates enable/disable` decision

**Status:** DONE (2026-09-25, merged 38f6764) · **Size:** S · **Wave:** 38 · **Spec:** `agent-lifecycle.spec.md`,
`security-gates.spec.md`

**Trigger:**
- `docket delete` removes the worktree but never the `docket/<pod>/<member>` branch
  (`pod_provisioning.py:530-548`).
- `.pod-provision-locks/<hex>` is never removed (`:433-434`).
- `workspaces/`, `pods/<p>` and the lock directories are created 0775 (`_install.py:433-435`,
  `pod_provisioning.py:434,454`).
- `gates enable/disable` writes a flag nothing on the live path reads (W34-A1).
- `init --no-gates` prints "recorded as off" and writes nothing (`_install.py:120-122`).

**Goal:**
- `delete` removes the branch when it is merged into the codebase's current branch, and otherwise
  keeps it and prints how to delete it.
- Lock directories are removed with the pod.
- Directories are created 0700.
- **Default unless the maintainer answers otherwise:** retire `gates enable/disable` into a
  removed-command notice that points at `pod <p> config set approvalMode` (P26-5), and make
  `--no-gates` print nothing false.

**Non-goals:** changing isolation (`gates isolate`), which is wired.

**Owns:** teardown in `core/pod_provisioning.py`, the mkdir sites, `cli/_gates.py`, `__main__.py`
`_REMOVED`, and the `--no-gates` branch.

**Acceptance / oracle:**
- A merged branch is gone after `delete`; an unmerged one survives with a message.
- The new directories are 0700.
- `docket gates enable` prints the notice.

**RED:** the branch survives a merged `delete`, and the directories are 0775.

### P26-17 — opt-in project instructions from the codebase (the AGENTS.md convention)

**Status:** DONE (merged, worker commit `680c793`; PodSettingsError is deliberately swallowed on the prompt path — an unrelated bad setting must not break composition; noted for maintainer glance) · **Size:** S · **Wave:** 40 (after P26-10) · **Spec:** `agent-loop.spec.md`
req. 30

**Trigger:**
- A repository states its conventions in `AGENTS.md`/`CLAUDE.md` at its root. This repository and
  the `docket-dev` pod's codebase do.
- A docket agent sees them only if it chooses to `read` them, and the explicit request asks for
  standard configuration.

**Goal:**
- A pod setting `projectInstructions` holds relative paths inside the codebase root (default
  unset, so nothing changes).
- Those files are composed after `INSTRUCTIONS.md`, inside the budget, with the P26-2 markers.
- Each file is screened by `pre_input` as untrusted input on every composition.
- A missing file is a visible marker, not an error.

**Non-goals:** auto-discovery without opt-in; recursive includes.

**Owns:** one section source in `core/identity.py`, plus the `PodSettings` key.

**Acceptance / oracle:**
- With `projectInstructions: [AGENTS.md]`, the fixture repo's line reaches the prompt.
- A path escaping the root is refused at `set`.
- An injection-pattern line trips the `pre_input` policy.

**RED:** the line is absent with the setting present.

### P26-18 — pod membership is read from recorded metadata, never guessed from the id string

**Status:** DONE (2026-09-25, merged c326796) · **Size:** S · **Wave:** 38 · **Spec:** `pod-dispatch.spec.md`,
`role-archetypes.spec.md`

**Trigger (deterministic, live 2026-09-25):** a custom role `security-reviewer` passes
`roles add`, `pod proj add security-reviewer` (workspace provisioned, meta records
`"pod": "proj"`) and `pipeline plan --file` — then `pipeline run --file` fails its step with
`DispatchError: refusing cross-pod dispatch: 'proj-security-reviewer' is not in pod 'proj'`.
Cause: `core/pod.py::pod_of` rpartitions the id; the tail `reviewer` is a registered role, so it
answers pod `proj-security`. Any custom role whose name ends in a registered role name is
provisionable but not dispatchable. The authoritative facts (`pod`, `role`) already sit in
`.docket-meta.json` and `pod_of` never reads them.

**Goal:** membership and role resolution on the dispatch path read the member's recorded meta
(`pod`, `role`) first, falling back to id parsing only for a member with no meta; `pod add`
refuses a role name that the id grammar cannot round-trip **only if** the meta-first resolution
cannot cover it (goal is to cover it); a regression test provisions a `<x>-reviewer`-named custom
role and dispatches through it.

**Non-goals:** changing the member-id naming scheme; migrating existing ids.

**Owns:** `core/pod.py::pod_of` (and its callers' expectations), the dispatch membership check at
`core/dispatch.py:1477-1480`, their unit tests.

**Acceptance / oracle:** the exact live reproduction (custom role `security-reviewer`, fake
driver) dispatches to `done`; `pod_of('proj-security-reviewer')` returns `proj` when that member's
meta exists; a genuinely cross-pod member id is still refused; `members_of`/`next_index` behaviour
for built-in roles is byte-identical.

**RED:** the reproduction raises the cross-pod refusal on the base.

### P26-19 — a deterministic dispatch refusal settles the claim; an orphaned task is recoverable

**Status:** DONE (2026-09-26, merged 1781c73) · **Size:** S · **Wave:** 38 · **Spec:** `pod-dispatch.spec.md`

**Trigger (live 2026-09-25):** the P26-18 refusal raised out of `dispatch_pod` after the build
hop. The claim was never settled, so the task sat `running` with no process. Recovery deadlock:
`cli/_pod.py` refuses to start a dispatch when nothing is `pending` or `failed`+`stale_claim`, so
the in-dispatch stale sweep that would fail the orphan can never run until a *new* task is
queued. `--resume` does not see a `running` task, and `queue --retry` only moves `blocked` ones.

**Goal:** a deterministic refusal inside a claimed task (membership, config validation, unknown
member) fails **that task** with a named reason and settles its claim instead of raising out of
the whole dispatch; the CLI's "anything to do?" gate also counts stale-claimed `running` tasks
when `--resume` is passed, so recovery needs no decoy task.

**Non-goals:** changing crash semantics (the stale sweep stays the recovery for real crashes);
retrying deterministic refusals.

**Owns:** the claim/refusal lifecycle in `core/dispatch.py` (the `DispatchError` raise sites
inside a claimed task and the finalize path), the resumable filter in `cli/_pod.py:542-551`.

**Acceptance / oracle:** with the P26-18 reproduction on the base pipeline (before its fix), the
task ends `failed` with the refusal as its reason, the queue shows it, and `--resume` after fixing
the pipeline file re-runs it from the last persisted hop — no `CLAIM_STALE_TIMEOUT` override, no
decoy task. A mid-hop kill -9 still leaves `running` and is swept as today.

**RED:** on the base, the task stays `running` and `pipeline run --resume` answers "No pending
tasks".

### P26-20 — shipped recipes: role + pipeline + policy bundles that are tested, real and configurable

**Status:** DONE (merged, worker commit `2236624`; secure-build dispatches end to end on the fake driver with both verdicts in the trace) · **Size:** M · **Wave:** 40 (after P26-6, P26-7, P26-18) · **Spec:**
`pipeline-format.spec.md`, `role-archetypes.spec.md`, `workspace-structure.spec.md` (shipped-data
section)

**Trigger (explicit request, 2026-09-25):** configuring the pipeline, guardrails and policies is
to be a principal, reviewed feature, and the templates/recipes the repo ships must be robust for
real use yet easily configurable. Today the wheel ships only `templates/policies/` (6 files);
there is no shipped pipeline or role, and the E2E audit showed a first recipe attempt trips
P26-18 at dispatch.

**Goal:** a `templates/recipes/<name>/` tree shipped in the wheel, each recipe holding role
YAML(s), a pipeline YAML, an optional policy pack and a README that states what it is for and the
exact commands to apply it (`docket roles add`, `docket pod <p> add <role>`,
`docket pod <p> config set pipeline`, copy policies). Ship at least three: `secure-build`
(implementer + security vetter, verdict gate, one rework cycle), `research-review` (over the
research blueprint, critic verdict), `ops-approval` (operator + human approval gate). CI
validates every recipe: `roles validate`, `pipeline validate`, `policies validate`, and a
`pipeline plan` against a fixture pod; one integration test dispatches `secure-build` end to end
on the fake driver. `docs/CONFIGURATION.md` §3 points at them.

**Non-goals:** a `docket recipes` command or any new CLI surface (applying uses existing
commands; revisit only if three real applications show the manual steps are the friction — rule
of three); auto-applying policies on `init`.

**Owns:** `templates/recipes/` (new, data only), the packaging include in `pyproject.toml`, the
validation tests (default lane: they read data the wheel ships, not prose), a
`docs/CONFIGURATION.md` §3 pointer.

**Acceptance / oracle:** a fresh fixture pod applies `secure-build` using only documented
commands and dispatches to `done` on the fake driver, with the vetter's verdict gate observed in
the trace; every recipe file passes its validator in CI; the wheel contains the recipes
(`python -m build` + unzip listing, or the existing wheel-content test extends).

**RED:** `templates/recipes/` does not exist and no test validates any shipped pipeline.
## ◆ PHASE 27 — COMPLETE (opened 2026-09-26, closed 2026-09-26): per-pod configuration and portable teams (D-43)

**Opened and closed 2026-09-26; ten cards (eight planned plus integrator-added P27-9 and P27-10) merged over Waves 41–43.** Eight cards in three waves. Decision, the three
scopes, the resolution rule, the verdict table and the pre-assigned spec versions are in
[docs/adr/0009-per-pod-configuration-and-portable-teams.md](docs/adr/0009-per-pod-configuration-and-portable-teams.md);
this section holds only the executable cards. **Activation gate:** the integrator confirms the
batching below from function-level contention, writes `.agents/handoffs/wave-41-worker-packets.md`
with the base commit, and puts a `## ▶ ACTIVE BOARD — WAVE 41` banner as this file's first H2
(with a matching `## ▶ WAVE 41 ...` heading over the wave's cards) so
`context_snapshot.py` resolves the board; only then are cards claimable.

**Trigger (explicit request, 2026-09-26 + a fired deferral):** each pod must carry robust, standard
customization; recipes must apply to any pod; global is only the structural base; configuration is
per pod; MCP and tool permissions must be versatile. ADR 0008 deferred the pod manifest with the
trigger "a pod reproduced on a second machine"; the request is that case. Evidence locators are
in the ADR's evidence table.

**Test rule for every card (ADR 0009 §"Test discipline"):** one RED behavioural test in the
module's existing `SUBJECT` file; a second only for a fail-closed/most-restrictive negative case;
the existing suite, goldens and specs are the no-change oracle; no agent-lane tests, no guards.

| Wave | Cards | Hot file and function ownership |
| --- | --- | --- |
| 41 | P27-1, P27-2, P27-3 | `core/archetypes.py` → P27-1 only; `core/policy.py` → P27-2 only; `core/tools.py` → P27-2 owns only the `policy_eval_detail` call inside `evaluate_tool_call`; `core/mcp_tools.py` + `cli/_mcp.py` → P27-3 only; `edges/adapters/docket_runtime.py`: P27-1 the project plumbing into `run_agent_turn`, P27-2 the `ToolContext(...)` construction |
| 42 | P27-4, P27-5 | `core/pod.py` + `cli/_pod.py` config key table → P27-4; `core/archetypes.py`: P27-4 owns `registry_for_role`, P27-5 owns the built-in `lead` literal + `resolve_hop_instruction`; `core/dispatch.py` hop-message builder + `core/blueprints.py` → P27-5; `docket_runtime.py::_load_mcp_tools` → P27-4 |
| 43 | P27-6 ∥ P27-8, then P27-9, P27-7, P27-10 | new `core/pod_apply.py` + `cli/_pod.py` `apply` → P27-6; `export` in the same module → P27-7 after P27-6 merges; `cli/_config.py`, `cli/_doctor.py` (own check function), `docs/CONFIGURATION.md` → P27-8 |

Every card follows the §"How to use this board" definition of done.

### P27-1 — a pod has its own role overlay, resolved nearest-wins

**Status:** DONE (2026-09-26, e12b567, merged in Wave 41) · **Size:** M · **Wave:** 41 · **Spec:** `role-archetypes.spec.md` → 1.12.0 ("User registry overlay"), `cli-interface.spec.md` → 1.30.0

**Trigger:**
- `core/archetypes.py::load_registry` reads one overlay, `ARCHETYPE_REGISTRY_FILE`; two pods
  cannot hold different `security-vetter` definitions.
- `registry_for_role(base, role)` and every lookup (`agent_loop.run_agent_turn`,
  `pod_provisioning.py` member lookups, `cli/_pod.py` `add` and pipeline plan, the
  `dispatch.py` hop-message builder) take no project.

**Goal:**
- `config.py::pod_config_dir(project)` = `PODS_DIR/<p>/config/`, created 0700 on first write.
- `load_registry(project="")` merges `pod_config_dir/roles.json` **above** the global overlay,
  above built-ins; `project=""` is byte-identical to today.
- `registry_for_role(base, role, project="")` and the lookups above pass the pod (the driver
  reads it from meta; provisioning and the CLI already hold it).
- `docket roles add <file> --pod <p>` writes the pod overlay; `roles list` gains a `source`
  value `pod:<p>` when `--pod <p>` is given; `roles show <name> --pod <p>` resolves the same way.
- `find_overlay_problems(project)` covers the pod file so doctor (P27-8) can report it.

**Non-goals:** pod-level tool denials (P27-4); doctor output (P27-8); any change to built-ins.

**Owns:** `core/archetypes.py` (`load_registry`, `registry_for_role`, `find_overlay_problems`,
`add_user_archetype`), `config.py::pod_config_dir`, `cli/_roles.py`, the `project` plumbing at
the four lookup sites (read-only edits: add the argument, nothing else).

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| pod overlay defines `vetter` with `deniedTools: [write]`, global overlay defines `vetter` with `[]` | `registry_for_role(base, "vetter", project=p)` lacks `write`; with `project=""` it keeps `write` |
| `roles add v.yaml --pod p` then `roles list --pod p` | shows `vetter` with source `pod:p`; `roles list` without `--pod` does not show it |
| a pod member of role `vetter` runs a turn on the fake driver | the trace's `tool_registry` (or the denial) proves the pod definition applied |
| no pod overlay present | every existing test, golden and spec unchanged |

**RED:** `tests/unit/core/test_archetypes.py`: the first row returns a registry that still holds
`write` on the base (no `project` parameter exists).

### P27-2 — a pod has its own policies, and they only add

**Status:** DONE (2026-09-26, ae8c3ac, merged in Wave 41) · **Size:** S · **Wave:** 41 · **Spec:** `security-gates.spec.md` → 0.25.0 (policy store section), `cli-interface.spec.md` → 1.31.0

**Trigger:**
- `core/policy.py::policy_files` globs `POLICIES_DIR` only; `policy_eval_detail(role, hook, text)`
  takes no project.
- `core/tools.py::ToolContext.project` exists and is not passed to the policy evaluation.
- A pod that needs "always ask before touching `.env`" has to install a fleet-wide file.

**Goal:**
- `policy_files(project="")` returns global files plus `pod_config_dir(project)/policies/*.json`;
  `policy_eval_detail`/`policy_eval`/`policy_test` take `project=""`.
- The existing most-restrictive-wins evaluation across files is the whole mechanism: a pod
  `block` adds to a global `allow`; a pod file can never override a global `block` or
  `require_approval`.
- A malformed pod policy fails closed exactly as P26-1 made global ones (same code path).
- `evaluate_tool_call` passes `ctx.project`; `DocketDriver` sets `ToolContext.project` from meta
  if it does not already.
- `docket policies validate|test|list --pod <p>` include the pod directory.

**Non-goals:** new policy actions or schema; scoping `SAFE_BINS` or high-risk classes.

**Owns:** `core/policy.py`, `cli/_policies.py`, the `policy_eval_detail` call in
`core/tools.py::evaluate_tool_call` (that call only), the `ToolContext(...)` construction in
`edges/adapters/docket_runtime.py::run_turn`.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| global: none; pod p: `block` on `make deploy` | `policy_eval("implementer","pre_tool_call","make deploy", project="p")` → `deny`; `project="q"` → `allow` |
| global `block` on X; pod p: `allow`-shaped file on X | still `deny` (negative case, the second permitted test) |
| pod file with a bad regex | `deny` naming the file, via the existing P26-1 path |
| `policies test pre_tool_call implementer 'make deploy' --pod p` | `deny`, hit names the pod file |
| no pod directory | every existing policy test and `policies_list.golden` unchanged |

**RED:** `tests/unit/core/test_policy.py`: the first row returns `allow` on the base.

### P27-3 — an MCP server declares its kind and its exposed tools

**Status:** DONE (2026-09-26, f775166, merged in Wave 41) · **Size:** S · **Wave:** 41 · **Spec:** `mcp-client.spec.md` → 1.5.0 ("Configuration", "Enumeration and adaptation"), `cli-interface.spec.md` → 1.32.0

**Trigger:**
- `core/mcp_tools.py::_build_tool` registers every remote tool `kind="write"`; README limit 1
  ("a read-only role gets no MCP tools at all") follows from it.
- A read-only `researcher` with a search server configured gets nothing.

**Goal:**
- `McpServerConfig` gains `kind: Literal["read","write"] = "write"` and
  `tools: list[str] = []` (empty = all). Both are operator assertions, validated at write.
- `docket mcp servers add <name> --kind read --tools search,fetch -- <cmd>`; `servers list`
  shows both; an existing file without the keys loads as before.
- `load_mcp_tools` registers each tool with the server's declared kind and skips (with a
  `McpToolSkip` reason) every tool not in a non-empty `tools` list.
- Because `registry_for_role` already removes by kind, a `kind: read` server reaches a role that
  denies `write` with no change to `core/archetypes.py`.
- The audit entry `mcp_client.load` (or the existing report) names the declared kind.

**Non-goals:** per-tool kinds; proving a remote tool is read-only; pod selection (P27-4).

**Owns:** `core/mcp_tools.py` (`McpServerConfig`, `_build_tool`, `load_mcp_tools`, the add
function), `cli/_mcp.py`, the mcp-client spec sections named.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| fake server declared `kind: read`, role with `deniedTools: [write, edit, bash]` | `registry_for_role(registry, role)` keeps the server's tools |
| same server declared `kind: write` (or undeclared) | tools removed — today's behaviour, the negative case |
| `tools: [search]` on a server listing `search` and `delete` | only `mcp__<s>__search` registered; `delete` in `skipped` with the reason |
| `mcp servers add x --kind bogus -- cmd` | exit 1 naming the field |
| existing `docket-mcp-servers.json` without the keys | loads, every existing MCP test unchanged |

**RED:** `tests/unit/core/test_mcp_tools.py`: the first row loses the tools on the base.

### P27-4 — pod settings `mcpServers` and `deniedTools`, each with its live reader

**Status:** DONE (2026-09-26, 4eac7a1, merged in Wave 42) · **Size:** M · **Wave:** 42 (after P27-1 and P27-3) · **Spec:** `pod-dispatch.spec.md` → 6.16.0 (pod settings), `mcp-client.spec.md` → 1.6.0 (live-turn wiring), `role-archetypes.spec.md` → 1.13.0 (per-role tool sets)

**Trigger:**
- `DocketDriver._load_mcp_tools` loads every catalog server into every pod's turns; a pod cannot
  say "only `search`" or "none".
- Denials are per role only (`docs/CONFIGURATION.md` §5): a pod cannot say "nobody here uses
  `fetch`".
- Contract property 3 (ADR 0008): a setting ships with its consumer, so both keys and both readers
  are one card.

**Goal:**
- `PodSettings` gains `mcp_servers: tuple[str, ...] | None` (alias `mcpServers`; `None` = all,
  today's behaviour) and `denied_tools: tuple[str, ...]` (alias `deniedTools`), both in the
  `docket pod <p> config get|set|unset` key table with the same validation and `pod.config` audit.
- `mcpServers` reader: `_load_mcp_tools(registry, role, project)` filters `load_mcp_servers()` by
  the pod's selection; a selected name absent from the catalog refuses the dispatch naming it
  (`DispatchError`), never silently loads nothing.
- `deniedTools` reader: `registry_for_role(base, role, project)` removes the union of the role's
  and the pod's names, then applies the existing kind-based removal to the union.
- `config explain` (P27-8) will label both; this card only makes the values reachable through
  the existing `PodSettings.load_for`.

**Non-goals:** per-agent overrides (deferred, D-42 trigger); a pod-local server catalog.

**Owns:** `core/pod.py` (`PodSettings`, `_SETTING_FIELD_BY_ALIAS`, validation), the key table in
`cli/_pod.py` config handler, `core/archetypes.py::registry_for_role` (this function only),
`edges/adapters/docket_runtime.py::_load_mcp_tools` and its call in `run_turn`.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| catalog `a`,`b`; `pod config set mcpServers a` | a fake-driver turn registers `mcp__a__*` only |
| `mcpServers` unset | both load — byte-identical to today |
| `pod config set mcpServers zzz` | write refused naming `zzz` (validated against the catalog at write) |
| `pod config set deniedTools fetch`, role `implementer` | its registry lacks `fetch` and still lacks nothing else; role `reviewer` lacks `fetch` too |
| `deniedTools` names a high-risk-class or unknown tool | unknown: refused at write; known: removed (negative case) |

**RED:** `tests/unit/core/test_pod.py`: `PodSettings.load_for` rejects `mcpServers` as an unknown
key on the base.

### P27-5 — the Lead's instruction is data, and step instructions reach it

**Status:** DONE (2026-09-26, 92ad787, merged in Wave 42) · **Size:** S · **Wave:** 42 · **Spec:** `pod-dispatch.spec.md` → 6.17.0 (hop message), `pipeline-format.spec.md` → 2.6.0 (step `instructions`), `pod-blueprints.spec.md` → 1.5.0, `role-archetypes.spec.md` → 1.14.0 (hop instructions)

**Trigger:**
- `core/dispatch.py` hop-message builder, `role == "lead"` branch: "Decompose this task into a
  concrete plan for the Implementer (you never edit code yourself)" for every pipeline, and the
  docstring states step `instructions` are not applied to the Lead.
- A research or ops pod's Lead is told to plan for an Implementer it does not have.

**Goal:**
- The built-in text becomes the `lead` archetype's `hop_instruction`; the builder's Lead branch
  reads it through `resolve_hop_instruction` like any custom role, so a pod or global overlay of
  `lead` changes it.
- A step's `instructions` (already interpolated) override the Lead's line too; the docstring's
  scope boundary is removed.
- The research, content and ops blueprint pipelines carry a Lead `instructions` line naming
  their own next role ("plan for the Researcher" / "Writer" / "Operator").
- The software and agentic-product pipelines and the default Lead line stay byte-identical, so a
  software pod's first hop message does not change.

**Non-goals:** changing the Lead's tools or gate; per-step models.

**Owns:** the hop-message builder in `core/dispatch.py` (Lead branch only), the built-in `lead`
literal and `resolve_hop_instruction` in `core/archetypes.py`, the three pipeline literals in
`core/blueprints.py`.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| research pod, blueprint pipeline, fake driver | the Lead's hop message names the Researcher and not the Implementer |
| software pod, no overlay | the Lead's hop message is byte-identical to the base (capture it in the test from the base first) |
| pipeline step `{id: plan, role: lead, instructions: "Plan in three bullets"}` | the Lead's message carries that text |
| `roles show lead` | prints the `hopInstruction` |

**RED:** `tests/unit/core/test_dispatch.py`: the research-pod message contains "Implementer" on
the base.

### P27-6 — `docket pod <p> apply <dir>`: a recipe applies to any pod in one command

**Status:** DONE (2026-09-26, 95c67fe, merged in Wave 43) · **Size:** M · **Wave:** 43 (after Wave 42 merges) · **Spec:** `pod-blueprints.spec.md` → 1.6.0 (new section "Pod manifests: apply"), `role-archetypes.spec.md` → 1.15.0 ("Shipped recipes"), `cli-interface.spec.md` → 1.33.0

**Trigger:**
- Each shipped recipe README lists six commands; every teammate repeats them per machine.
- ADR 0008 deferred "declarative pod manifest (apply)" with the trigger "a pod reproduced on a
  second machine"; the 2026-09-26 request fires it.

**Goal:**
- `core/pod_apply.py`: `plan_apply(project, dir) -> ApplyPlan` (pure: reads `roles/*.yaml`,
  `policies/*.json`, `pipeline.yaml`, `pod.yaml` with `members`, `settings`, `pipeline`;
  validates roles, policies, settings and the pipeline **against the roster as it will be after
  `members`**; returns per-item `add | replace | skip` with reasons) and
  `apply(plan) -> ApplyResult` (writes pod scope only, through the existing writers:
  `add_user_archetype(..., project)`, the pod policy directory, `provision member`, the bind
  function behind `config set pipeline`, `PodSettings` setter). Any validation error returns
  before any write.
- `docket pod <p> apply [<dir>] [--dry-run] [--json]`; `<dir>` defaults to
  `<codebase>/.docket/` (Lead meta `codebase`), exit 1 naming the path when absent.
- Idempotent: a second run is all `skip`. Audited once as `pod.apply` with the item list.
- The three recipe READMEs' "Apply it" becomes the one command; each recipe gains a minimal
  `pod.yaml` (`members`; `secure-build` keeps its policy as an optional file the README names).
- `tests/integration/test_recipes.py` switches its fixture to `plan_apply`/`apply` and keeps the
  `secure-build` dispatch-to-`done` case — no parallel test file.

**Non-goals:** removal/prune/diff; auto-apply at `init`; a new file format beyond `pod.yaml`'s
three keys; `export` (P27-7).

**Owns:** new `core/pod_apply.py`, the `apply` subcommand in `cli/_pod.py`,
`src/docket/templates/recipes/*` (READMEs and `pod.yaml`), `tests/integration/test_recipes.py`.
Adds CLI surface: regenerate `completions_bash`/`completions_zsh` goldens and `docs/commands.md`,
listing the added lines.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| fresh pod `p` (lead+implementer), `apply templates/recipes/secure-build` | plan lists role add, member add, pipeline bind; afterwards `pipeline plan p` prints `Source: bound`, `roles list --pod p` shows `security-vetter`, `.docket-meta.json` of the new member exists |
| second `apply` | every item `skip`, no audit entry beyond the first, files byte-identical |
| `pod.yaml` with `settings: {mcpServers: [zzz]}` | exit 1 naming `zzz`, **nothing written** (side-effect check: the pod overlay and policy dir do not exist) |
| `--dry-run` | prints the plan, writes nothing |
| `apply` with no dir and no `<codebase>/.docket` | exit 1 naming the path |
| `secure-build` after apply on the fake driver | dispatches to `done` with the verdict gate in the trace (existing case, now through apply) |

**RED:** `tests/integration/test_recipes.py`: `from docket.core import pod_apply` fails on the base.

### P27-9 — pod-scoped custom roles resolve in the roster, and `apply` writes pod scope

**Status:** DONE (2026-09-26, 3dcd099, merged in Wave 43) · **Size:** S · **Wave:** 43 (serially after P27-6, before P27-7) · **Spec:** `pod-dispatch.spec.md` → 6.18.0 (membership), `pod-blueprints.spec.md` → 1.7.0 ("Pod manifests: apply" corrected), `role-archetypes.spec.md` → 1.16.0 ("Shipped recipes" corrected)

**Trigger (deterministic reproduction, found by the P27-6 worker on 2026-09-26):** a role
registered only in a pod overlay (`add_user_archetype(doc, project)`) can be provisioned as a
member, but `core/pod.py::_role_names()` reads `load_registry()` with no project, so
`parse_member_id`, `members_of`, `normalize_role` and `resolve_member` do not recognise the
role and `dispatch.py::pod_full_roster` silently drops the member; the secure-build dispatch
test failed with pod-scoped registration. P27-6 therefore shipped `apply` writing roles to the
**global** overlay, contradicting ADR 0009 ("apply writes pod scope only") and making P27-7's
export of the pod overlay empty.

**Goal:**
- `core/pod.py`: `_role_names(project="")`, `normalize_role(role, project="")` and
  `resolve_member` resolve through `load_registry(project)`; `parse_member_id` and
  `members_of` already receive `project` and pass it on. `pod_of`'s string fallback stays
  global (it has no project yet; meta is authoritative first).
- Callers that hold the project pass it: `cli/_pod.py` (`normalize_role` at `add` and the
  pipeline plan), `edges/adapters/docket_runtime.py`, `core/telegram.py`, `cli/_status.py`.
- `core/pod_apply.py`: roles plan against `load_registry(project)` with `source_of ==
  f"pod:{project}"` as the "already applied" check and `add_user_archetype(doc, project)` as
  the writer; module docstring and the spec sections that recorded the global-overlay
  workaround are corrected.

**Non-goals:** `export` (P27-7); changing built-ins; a pod-local server catalog.

**Owns:** `core/pod.py` (the five functions named), `core/pod_apply.py` (`_plan_roles`, the
role write in `apply`, module docstring), the `normalize_role` call sites in `cli/_pod.py`,
the three spec sections named, `tests/unit/core/test_pod.py`,
`tests/integration/test_recipes.py` (assertion that the recipe role lands in
`pod_config_dir(project)/roles.json` and not in the global overlay).

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| `vetter` defined only in pod `acme`'s overlay | `parse_member_id("acme-vetter", "acme")` → `("vetter", 1)`; `members_of([...,"acme-vetter"], "acme")` lists it; `parse_member_id("beta-vetter", "beta")` → `None` |
| `apply templates/recipes/secure-build` on a fresh pod | `security-vetter` is in `pod_config_dir(p)/roles.json`, absent from `docket-roles.json`; `roles list` without `--pod` does not show it; the dispatch-to-`done` case still passes |
| no pod overlay anywhere | every existing pod, dispatch and recipe test unchanged |

**RED:** `tests/unit/core/test_pod.py`: the first row returns `None` on the base.

### P27-7 — `docket pod <p> export <dir>`, and the round trip is the proof

**Status:** DONE (2026-09-26, e4ea782, merged in Wave 43) · **Size:** S · **Wave:** 43 (serially after P27-6) · **Spec:** `pod-blueprints.spec.md` → 1.7.0 ("Pod manifests: export"), `cli-interface.spec.md` → 1.34.0

**Trigger:** the deferred manifest's own trigger, "a pod reproduced on a second machine", needs
the write direction; `roles show` already emits the YAML wire format, the bound pipeline copy and
pod policy files are plain files, and `PodSettings` serializes.

**Goal:**
- `core/pod_apply.py::export_pod(project, dir)` writes `roles/*.yaml` (pod overlay only, via
  `to_wire`), `policies/*.json` (pod directory only), `pipeline.yaml` (the bound copy, if any) and
  `pod.yaml` (`members`: the pod's non-lead roles; `settings`: every non-default pod setting).
  Global scope is never exported — it is the operator's, not the team's.
- `docket pod <p> export <dir>` refuses a non-empty directory unless `--force`.
- Round trip: `export p → fresh DOCKET_HOME → init q → apply q <dir>` gives a
  `config explain q --json` equal to `config explain p --json` after normalising ids and paths.

**Non-goals:** exporting global overlays, secrets, sessions, traces or the task queue.

**Owns:** `export_pod` in `core/pod_apply.py`, the `export` subcommand in `cli/_pod.py`.
Adds CLI surface: completions goldens and `docs/commands.md`, listed line by line.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| pod with a pod-scoped role, one pod policy, a bound pipeline, `approvalMode refuse` | the four files exist with exactly those contents; nothing from `~/.docket/policies/` appears |
| round trip into a second home | `config explain --json` equal after normalisation (the phase's one integration proof) |
| export into a non-empty dir | exit 1 without `--force`; overwrites with it |

**RED:** `tests/integration/test_recipes.py` (or `test_pod_apply.py` if P27-6 created it): the
round-trip test fails on the base because `export_pod` does not exist.

### P27-8 — every resolved value says which scope it came from

**Status:** DONE (2026-09-26, 0a81f45, merged in Wave 43) · **Size:** S · **Wave:** 43 (parallel with P27-6) · **Spec:** `cli-interface.spec.md` → 1.35.0 (`config explain`, `doctor`)

**Trigger:** contract property 5 (ADR 0008): after P27-1…P27-5 a role, policy, server or denial
can come from three places and `config explain` names none; `docket doctor` reports malformed
global overlay entries and policies but not pod ones.

**Goal:**
- `docket config explain <agent>` labels the resolved role archetype, each applicable policy
  file, each loaded MCP server (with declared kind and the pod's selection) and each denied tool
  with `built-in | global | pod`; `--json` carries a `scope` field per item.
- `docket doctor` gains one check function that reports a malformed pod overlay entry
  (`find_overlay_problems(project)`) and an invalid pod policy file for every pod, and re-uses the
  P26-era fix path where one exists.
- `docs/CONFIGURATION.md`: the ownership map gains a scope column and the pod config directory;
  §3.10 becomes "apply a recipe in one command"; §5 loses "Tool denials are per role only".

**Non-goals:** new explain sections; changing what explain resolves.

**Owns:** `cli/_config.py` (explain renderer and JSON), one new check function in
`cli/_doctor.py`, `docs/CONFIGURATION.md`.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| pod overlay shadows `reviewer`; global policy + pod policy; server declared `read` selected by the pod; pod `deniedTools: [fetch]` | `config explain <p>-reviewer --json` shows `scope: pod` for the role, both policies with their scopes, the server with `kind: read` and `scope: pod` selection, `fetch` with `scope: pod` |
| no pod scope at all | explain output byte-identical to the base (capture in the test) |
| a pod `roles.json` with a bad entry | `doctor` names pod, role and reason |

**RED:** `tests/unit/cli/test_config.py` (the file that declares `SUBJECT` for `cli/_config.py`):
the JSON has no `scope` key on the base.

### P27-10 — `apply` carries a recipe's policies into the pod

**Status:** DONE (2026-09-26, e2f7d4d, merged in Wave 43) · **Size:** S · **Wave:** 43 (serially after P27-7) · **Spec:** `pod-blueprints.spec.md` → 1.9.0 ("Pod manifests: apply"), `role-archetypes.spec.md` → 1.17.0 ("Shipped recipes")

**Trigger (found by the P27-7 worker on 2026-09-26):** `core/pod_apply.py::plan_apply` plans
roles, members, the pipeline and settings but never `policies/*.json`, so a recipe's policy
(`secure-build`, `ops-approval`) is not written into `pod_config_dir(p)/policies/`, and the
`secure-build` README still tells the operator to `cp` it into the **global** `~/.docket/policies/`.
`export` (P27-7) reads that directory, so the round trip silently drops what `apply` never wrote.
ADR 0009 defines a recipe as role + pipeline + policy applied at pod scope.

**Goal:**
- `plan_apply` gains a `policy` item per `policies/*.json`: validated with
  `core/policy.py::validate_policy` (any error aborts the plan before any write, naming the
  file); `add` when absent, `replace` when the pod copy differs byte-for-byte, `skip` when equal.
- `apply` writes the file into `pod_config_dir(project)/policies/<name>` (0700 dir, 0600 file)
  through the existing writer discipline; the item is listed in the single `pod.apply` audit
  entry like the others.
- The `secure-build` and `ops-approval` READMEs drop the manual `cp`; "Apply it" is the one
  command, and the "undo" section removes the pod copy, not a global file.

**Non-goals:** policy schema changes; applying to global scope; `export` changes.

**Owns:** `core/pod_apply.py` (`plan_apply`, `apply`, one new `_plan_policies` helper),
`src/docket/templates/recipes/{secure-build,ops-approval}/README.md`, the two spec sections
named, `tests/integration/test_recipes.py`.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| fresh pod, `apply templates/recipes/secure-build` | `pod_config_dir(p)/policies/require-approval-secret-writes.json` exists byte-identical to the recipe file; `policy_eval("implementer","pre_tool_call", <matching text>, project=p)` is the policy's action; `~/.docket/policies/` untouched |
| second `apply` | the policy item is `skip`; no second audit entry |
| recipe policy with a bad regex | exit 1 naming the file, nothing written (roles dir and policies dir absent) |
| export after apply into a fresh dir | `policies/` holds the same file (round trip now carries it) |

**RED:** `tests/integration/test_recipes.py`: the first row's pod policy file does not exist on
the base.

## ◆ PHASE 28 — COMPLETE (opened 2026-09-26, closed 2026-09-26): configuration format v1 and the two extension points (D-44)

**Closed 2026-09-26; every card DONE.** Eight cards in three waves. Decision, the format, the control-flow rule,
the plugin trust boundary and the verdict table are in
[docs/adr/0010-config-format-v1-and-extension-points.md](docs/adr/0010-config-format-v1-and-extension-points.md).
**Activation gate met:** Phase 27 closed 2026-09-26 (`e7dffbb`); packets in
[.agents/handoffs/wave-44-worker-packets.md](.agents/handoffs/wave-44-worker-packets.md), which
also corrects the spec versions Phase 27 consumed (role-archetypes → 1.18.0, pod-blueprints →
1.10.0, pod-dispatch → 6.19.0).

**Trigger (explicit request, 2026-09-26):** every configuration file must have a standard
structure a non-expert can read; pipelines and policies must use a clear language; complex
customization needs an extension mechanism in code, like Drupal migrate's process plugins. The
evidence table in the ADR names the current formats' inconsistencies by locator.

**Test rule:** one RED test per card; each normaliser proven by one round trip; P28-7 carries
the two negative cases (a codebase-only plugin is not loaded; a raising plugin denies); no
agent-lane tests, no guards.

| Wave | Cards | Hot file and function ownership |
| --- | --- | --- |
| 44 | P28-1, P28-2, P28-3, P28-4 | new `core/config_docs.py` → P28-1; `core/policy.py` + the `policy_eval_detail` call in `core/tools.py::evaluate_tool_call` → P28-2; `core/pipeline.py` normaliser → P28-3; `core/archetypes.py::from_wire`/`parse_yaml_file` → P28-4 |
| 45 | P28-5, P28-6 | `core/orchestrator.py`: P28-5 outcome routing + termination/reachability, P28-6 step skipping + command-step executor; `core/pipeline.py`: P28-5 `on`/`until`, P28-6 `when`/`run` |
| 46 | P28-7 ∥ P28-8 | new `core/plugins.py` + `cli/_plugins.py` + the predicate hook in `core/policy.py` → P28-7; schemas, `export`, docs, recipes → P28-8 |

### P28-1 — every configuration file says what it is, and one command validates them all

**Status:** DONE (2026-09-26) · **Size:** S · **Wave:** 44 · **Spec:** new `specs/functional/config-format.spec.md` 1.0.0, `cli-interface.spec.md` → 1.36.0

**Trigger:** no configuration file carries a `kind`; roles, pipelines, policies and the Phase 27
manifest are told apart by directory and by the caller's choice of parser; policies are JSON
while everything else is YAML.

**Goal:**
- `core/config_docs.py::load_document(path) -> Document` reads YAML (JSON included), requires
  `kind` in `{role, pipeline, policy, pod, provider}` and `name`, and dispatches to the existing
  parser of that kind (`provider` delegates to `core/provider.py::load_provider_document` once
  P29-1 has merged; until then the arm is absent and the card says so — ADR 0011). A file without `kind` loads through today's parser and returns a deprecation note
  the CLI prints once per command.
- `docket validate [dir]` (default `<cwd>/.docket`, or one file) validates every document and
  the manifest, printing `file:line field: message (valid: a, b, c; did you mean "b"?)`, exit 1 on
  the first invalid file after listing all.
- The Phase 27 `apply` planner and every `roles|pipeline|policies validate` path call
  `load_document` so there is one parse path.

**Non-goals:** short forms (P28-2..4); schemas (P28-8); removing the old format.

**Owns:** new `core/config_docs.py`, new `cli/_validate.py`, the call-site swaps in
`cli/_roles.py`, `cli/_pipeline.py`, `cli/_policies.py`, `core/pod_apply.py` (one line each).
Adds CLI surface: completions goldens and `docs/commands.md`, listed line by line.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| `kind: policy` YAML with `then: require_approval` | `validate` exits 1 naming line, field, valid values and suggests `ask` |
| a recipe directory with one bad file | every file listed, the bad one first with its reason, exit 1 |
| today's role YAML without `kind` | loads, one deprecation line, byte-identical result |
| `kind: banana` | exit 1 naming every known kind |

**RED:** `tests/unit/core/test_config_docs.py` (new `SUBJECT` file): `from docket.core import
config_docs` fails on the base.

### P28-2 — policies read as "when this, then that", with predicates over the tool and its arguments

**Status:** DONE (2026-09-26) · **Size:** M · **Wave:** 44 · **Spec:** `security-gates.spec.md` → 0.26.0 (policy format)

**Trigger:**
- `core/policy.py` documents `{id, applies_to, hook, match{type,pattern}, action}`: runtime
  vocabulary, snake_case, JSON.
- `core/tools.py::evaluate_tool_call` passes only `render_tool_call(tool.name, args)`; a policy
  cannot say "the `write` tool under `.github/`" without a regex over rendered text.

**Goal:**
- Short form: `kind: policy`, `appliesTo`, `on: input|toolCall|output` (default `toolCall`),
  `when: {tool, path, matches, branch, anyOf: [...]}` (implicit AND, `anyOf` for OR, no `not`),
  `then: allow|warn|ask|block|redact`, `message`. `normalize_policy(short) -> canonical` is a pure
  function; the canonical dict is today's shape plus an optional structured `when`.
- The engine receives the tool name, its arguments and the worktree branch beside the rendered
  text (`policy_eval_detail(..., call=ToolCallFacts | None)`); `path` is a glob over the call's
  path argument, `branch` a glob over the current branch. Text-only callers (`pre_input`,
  `pre_output`, `policies test` for text) pass `None` and behave as today.
- `policy_files` also globs `*.yaml`/`*.yml`; the six shipped templates are rewritten in short
  form (their behaviour unchanged, proven by the existing policy tests).
- Most-restrictive-wins and fail-closed are untouched.

**Non-goals:** plugins (P28-7); new actions; removing the JSON form.

**Owns:** `core/policy.py` (`normalize_policy`, predicate evaluation, file globbing), the one
call in `core/tools.py::evaluate_tool_call`, `templates/policies/*`.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| short-form file `{tool: write, path: ".github/**", then: ask}`; `write path=.github/x.yml` | `ask`; `write path=src/x.py` → `allow` |
| the same rule as a JSON regex policy | identical verdicts for both renderings (the round trip) |
| `anyOf: [{branch: main}, {branch: "release/*"}]` with `git push` on `feature/x` | `allow`; on `main` → `ask` |
| every shipped template rewritten | existing `test_policy.py` and `policies_list.golden` unchanged except the file extension column, listed |

**RED:** `tests/unit/core/test_policy.py`: `normalize_policy` does not exist on the base.

### P28-3 — a pipeline step reads as "who, what is checked, where it goes"

**Status:** DONE (2026-09-26) · **Size:** S · **Wave:** 44 · **Spec:** `pipeline-format.spec.md` → 2.7.0 (short form)

**Trigger:** every shipped recipe repeats `pattern: '^\s*(APPROVE|REQUEST-CHANGES)\b'`,
`passValues: [approve]` and `rework: {to, when, maxCycles}` to say "verdict gate, one rework".

**Goal:**
- Short form: a step is `- <id>: <role or agent id>` plus optional `verify: true|<command>`,
  `verdict: [PASS, FAIL]`, `approval: <message>`, `instructions`, `timeout`, `retries`, and
  `on: {<label>: {goto: <step>, max: N} | fail | stop | <step>}` where a backward `goto` requires
  `max`. `normalize_pipeline(short) -> PipelineSpec` is a pure function producing today's
  canonical models (`VerdictGate` with the derived pattern and `pass_values`, `rework` from the
  one backward edge). A step with no gate key inherits its role's gate contract, as today.
- Canonical long form stays valid and is what `plan` prints.
- `on:` beyond the single backward edge is **stored** canonically here and **executed** by P28-5;
  this card refuses at `validate` any `on:` shape P28-5 has not shipped ("outcome routing is not
  available yet"), so no file silently means less than it says.

**Non-goals:** executor changes (P28-5/P28-6); `when`, `until`, `run`.

**Owns:** `core/pipeline.py::normalize_pipeline` and the short-form parsing in `load_pipeline`;
`cli/_pipeline.py` help text; the three recipe `pipeline.yaml` files rewritten in short form.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| `secure-build` in short form | `normalize_pipeline(short) == load_pipeline(long).spec` (the round trip) |
| `verdict: [APPROVE, REQUEST-CHANGES]` | `pass_values == ["approve"]`, pattern matches exactly the two markers at line start |
| backward `goto` without `max` | `validate` exit 1 naming the step |
| `plan` on each recipe | byte-identical to the base |

**RED:** `tests/unit/core/test_pipeline.py`: `normalize_pipeline` does not exist on the base.

### P28-4 — a role file carries only what is enforced, and its prose lives in Markdown

**Status:** DONE (2026-09-26) · **Size:** S · **Wave:** 44 · **Spec:** `role-archetypes.spec.md` → 1.18.0 (wire format; 1.16.0 was consumed by Phase 27)

**Trigger:** `RoleArchetype.edit_rights` is "descriptive only" beside `denied_tools`; `gateContract:
{kind, regexes}` duplicates the pipeline's verdict vocabulary; `soulTemplate` and `agentsTemplate`
are long block scalars a non-expert edits badly.

**Goal:**
- Short form: `kind: role`, `name`, `description`, `model: cheap|strong|<id>`, `cannot: [...]`,
  one of `verdict: [...] | verify: true | approval: true`, `instructions: <file.md>` (default: the
  `.md` beside the YAML; the Markdown renders with the same `${variables}` into `SOUL.md`, and
  `AGENTS.md` keeps the built-in red lines unless the Markdown has an `## AGENTS` section).
- `normalize_role(short, base_dir) -> canonical dict` is pure; `editRights` is derived
  (`cannot` contains `write` → `read-only`) and no longer written by `export`.
- `model:` accepts `cheap|strong` only; a model id is refused naming `docket models set` (an
  archetype has no model-id field and this card adds none). Printing the short form back
  (`roles show`, `export`) is P28-8's, beside export.

**Non-goals:** changing built-ins; the pod overlay (Phase 27).

**Owns:** `core/archetypes.py::from_wire` (accept both), new `normalize_role`, `parse_yaml_file`;
`templates/recipes/*/roles/*` rewritten with a `.md` beside each.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| `security-vetter` short form + `.md` | `normalize_role(short) == from_wire(long)` (the round trip); the rendered `SOUL.md` is byte-identical to the base's |
| `cannot: [write]` and no gate key | `deniedTools == ["write"]`, `gateContract.kind == "none"` |
| both `verdict` and `verify` | `validate` exit 1 |

**RED:** `tests/unit/core/test_archetypes.py`: `normalize_role` does not exist on the base.

### P28-5 — outcomes route the pipeline, and every loop has a bound

**Status:** DONE (2026-09-26) · **Size:** M · **Wave:** 45 (after P28-3) · **Spec:** `pipeline-format.spec.md` → 2.8.0 (control flow), `pod-dispatch.spec.md` → 6.19.0

**Trigger:** `core/orchestrator.py` routes only through a `VerdictGate.rework` edge to an earlier
step; a verdict cannot send the task to a later step, escalate to an approval step, or stop; a
mechanical gate cannot retry its own step.

**Goal:**
- Executor: after a step's gate resolves to an outcome label (a verdict value, `pass`/`fail` for
  mechanical, `approved`/`denied` for approval), `on:` picks the next step: `goto` (forward or
  backward, backward counting against `max`), `fail`, `stop` (task `done` with a trace note), or
  the default next step. Today's `rework` is exactly `on: {request-changes: {goto: <step>, max}}`
  and stays byte-identical.
- `until: verify` + `max`: sugar for `on: {fail: {goto: <self>, max}}`.
- `validate`/`plan`: a backward edge without `max` and an unreachable step are errors; `plan`
  prints each step's routes.
- Every routing decision is a trace event naming step, outcome and target.

**Non-goals:** `when` and command steps (P28-6); parallel changes.

**Owns:** the routing of a gate's outcome in `core/dispatch.py` (`_route_outcome`, called by
`_run_pipeline`; the executor lives there, not in `core/orchestrator.py`, which only plans),
the two checks as `PipelineSpec` validators, `PlannedUnit.on` and the plan suffix;
`core/pipeline.py` `on`/`until` model fields (P28-3 parsed them; this card lifts the "not
available yet" refusal). Function ownership against P28-6 is in the packets file.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| `vet` with `on: {REQUEST-CHANGES: {goto: build, max: 1}}` on the fake driver | identical hop sequence and trace to the base's `rework` form |
| `on: {FAIL: escalate}` where `escalate` is a later approval step | the task reaches `waiting_approval` at `escalate` |
| `until: verify, max: 2` with a verify that fails twice then passes | three implementer hops, then advance; a third failure → task `failed` |
| unreachable step | `validate` exit 1 naming it |

**RED:** `tests/unit/core/test_orchestrator.py`: the forward `goto` case advances to the next
sequential step on the base.

### P28-6 — a step can be skipped on a closed predicate, and a step can be a command

**Status:** DONE (2026-09-26) · **Size:** S · **Wave:** 45 · **Spec:** `pipeline-format.spec.md` → 2.9.0, `pod-dispatch.spec.md` → 6.20.0, `cli-interface.spec.md` → 1.37.0 (only if help text changes)

**Trigger:** a Tester step cannot be skipped when nothing under `src/` changed; a lint or report
step needs an agent turn even when a command would do; the only code escape for a pipeline is a
verify command attached to an agent.

**Goal:**
- `when:` with exactly three predicates implemented in code and listed by `validate`:
  `changed: <glob>` (against the implementer worktree's diff from the task's base), `var: <name>,
  is: <value>`, `memberPresent: <role>`. A false predicate skips the step with a `step_skipped`
  trace event and routes to the default next step.
- Command step: `- lint: {run: "ruff check ."}` runs the command in the pod's worktree through
  `edges/adapters/system.py` (no agent, no model tokens), bounded by `timeout`; exit code 0 →
  outcome `pass`, otherwise `fail`; the last stdout line, if it is a single uppercase token, is
  the outcome label for `on:`. Output is captured into the run's hop record and the trace, redacted.
  It is subject to `allowCommands`/the command classifier like a verify command.
- `plan` prints `[lint] run ... [gate: exit code]` and `when` on each step.

**Non-goals:** more predicates (a new one is a card with a test); Python step plugins (deferred).

**Owns:** step skipping and the command-step executor in `core/dispatch.py` (`_step_skipped`,
`_run_command_step`, called at the top of `_run_pipeline`'s loop), `core/pipeline.py`
`when`/`run` fields, `PlannedUnit.when`/`run`, the `plan` renderer lines.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| `when: {changed: "src/**"}` with a diff only under `docs/` | step skipped, trace event, next step ran |
| `run: "false"` | outcome `fail`, task `failed`, no model call recorded |
| `run: "printf 'ok\\nPASS\\n'"` with `on: {PASS: ship}` | routes to `ship` |
| `run: "git push origin production"` | classified high-risk: asks, or refuses under `approvalMode refuse` |

**RED:** `tests/unit/core/test_orchestrator.py`: a `run:` step is rejected as an unknown key on
the base.

### P28-7 — a policy can call a Python predicate the operator applied, never one the agent wrote

**Status:** DONE (2026-09-26) · **Size:** M · **Wave:** 46 (after Phase 27's `apply`) · **Spec:** `security-gates.spec.md` → 0.27.0 (predicate plugins), `cli-interface.spec.md` → 1.38.0

**Trigger:** the predicate vocabulary is closed by design; a team with a genuinely complex rule
("ask when a migration file is touched outside the migrations/ tree of the app that owns it") has
no path but a fragile regex. The Drupal-migrate precedent: named plugins in YAML, custom plugins in
code. The trust boundary: the agent edits the repository the plugin would live in.

**Goal:**
- `docket.plugins` public API: `PLUGIN_API_VERSION = "1.0.0"`, `@predicate(name)`, typed
  `ToolCall` (tool, args, rendered) and `PolicyContext` (role, project, branch, worktree root);
  a predicate returns `bool`.
- Discovery: `~/.docket/plugins/*.py` (global) and `pod_config_dir/plugins/*.py` (pod), imported
  with `importlib.util.spec_from_file_location`; a duplicate name across files is an error;
  `docket plugins list` prints name, scope, file and sha256. **Nothing is imported from the
  codebase.** `docket pod <p> apply` copies a recipe's `plugins/*.py` into pod scope with its hash
  (the bound-pipeline rule), so a codebase edit changes nothing until an operator applies again.
- YAML: `when: {plugin: <name>, with: {...}}`; `then:` decides as always.
- Fail closed: an unknown name at load, a raising plugin, a non-bool return or a plugin over a
  fixed wall-clock budget (default 250 ms, measured per call) → `deny` naming the plugin; every
  invocation is audited (`policy.plugin`) with name, scope, hash and verdict.
- `docket policies test` runs plugins the same way.

**Non-goals:** action or gate plugins, entry-point packaging, `engine: cedar|rego` (all deferred
with triggers in the ADR); sandboxing plugin code (it is operator code, and the ADR says so).

**Owns:** new `core/plugins.py`, new `cli/_plugins.py`, the `plugin` predicate branch in
`core/policy.py`, the `plugins/` copy step in `core/pod_apply.py`. Adds CLI surface: completions
goldens and `docs/commands.md`, listed.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| global plugin `touches_migrations`; policy `when: {plugin: touches_migrations}, then: ask`; `write path=app/migrations/0002.py` | `ask`, audit entry names plugin, scope `global`, hash |
| the same `.py` present only under `<codebase>/.docket/plugins/`, not applied | `docket plugins list` does not show it; the policy load fails closed (`deny` naming the unknown plugin) — negative case 1 |
| a plugin that raises | `deny` naming it — negative case 2 |
| `apply` a recipe with `plugins/x.py`, then edit the codebase copy | the pod-scope hash is unchanged and the old code runs until re-apply |

**RED:** `tests/unit/core/test_plugins.py` (new `SUBJECT` file): `from docket.core import plugins`
fails on the base.

### P28-8 — schemas editors can use, export in the short form, and docs that show only v1

**Status:** DONE (2026-09-26) · **Size:** S · **Wave:** 46 · **Spec:** `config-format.spec.md` → 1.1.0, `pod-blueprints.spec.md` → 1.10.0 (export; 1.8.0 was consumed by Phase 27), `cli-interface.spec.md` → 1.39.0

**Trigger:** contract property 5 and the request's "easy to interpret for a non-expert": a file
format without a schema has no autocomplete and no inline errors in an editor; `export` (P27-7)
would otherwise write the long form.

**Goal:**
- `docs/contracts/config-v1/{role,pipeline,policy,pod}.schema.json` generated from the short-form
  models and pinned byte-for-byte by one test, the harness-v1 pattern.
- `export` writes the short form with a first line `# yaml-language-server: $schema=<relative
  path>`; `apply` of an export is a no-op (round trip through P27-7's test, extended by one
  assertion).
- `docs/CONFIGURATION.md` §3.4–3.6 and the recipe READMEs show only the short form; the long
  form moves to the spec's "canonical form" section.

**Non-goals:** new fields; a docs site page.

**Owns:** `scripts/gen_config_schemas.py` (mechanical), `docs/contracts/config-v1/`, the export
writer in `core/pod_apply.py`, `docs/CONFIGURATION.md` §3, recipe READMEs.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| regenerate the four schemas | byte-identical to the committed files (the pin) |
| a short-form recipe validated by a standard JSON Schema validator against its schema | valid; a `then: bogus` policy invalid at the right path |
| `export` then `apply` | every item `skip` |

**RED:** the schema pin test fails on the base because the directory does not exist.

## ◆ PHASE 29 — COMPLETE (opened 2026-09-27, closed 2026-09-27): the provider catalog (D-45)

**Closed 2026-09-27; every card DONE.** Seven cards in three waves. Decision, the document, the two scopes, the
adapter seam, the twelve amended spec rules, the retired-code table and the verdict table are in
[docs/adr/0011-provider-catalog.md](docs/adr/0011-provider-catalog.md). Worker packets:
[.agents/handoffs/wave-47-worker-packets.md](.agents/handoffs/wave-47-worker-packets.md).
**Activation gate met 2026-09-27:** Phase 28 closed at `56e8d9d`; batching confirmed from the
function-level ownership below; the packets file records the base commit and the spec versions
Phase 28 consumed (`pod-dispatch` → 6.21.0 for P29-5, `config-format` → 1.2.0 for P29-1, which
now also adds the `provider` arm to `load_document`).

**Trigger (explicit request + deterministic regression, 2026-09-26):** provider selection must be
configurable like roles, policies and pipelines, with abstractions that make agnosticism real, no
overengineering and no legacy left behind. Reproduced on `0764091`: `docket models preset
anthropic` demands a registered block; `docket models provider add anthropic
https://api.anthropic.com/v1 --model claude-sonnet-4-6` refuses because the unauthenticated probe
of `/models` gets 401 (openai 401, google 404) and `HTTPError` is read as unreachable; no bypass
exists. Evidence locators are in the ADR's evidence table.

**Test rule (ADR 0011):** one RED behavioural test per card in the module's `SUBJECT` file; a
negative case only for a fail-closed property (P29-1, P29-3); existing tests, goldens and specs
are the no-change oracle; no agent-lane tests, no guards; goldens change only where a card lists
the lines.

| Wave | Cards | Hot file and function ownership |
| --- | --- | --- |
| 47 | P29-1 | `core/provider.py` (rewritten), `config.py::PROVIDERS_FILE`, `core/fleet.py` (delete `add_local_provider`/`get_local_provider`; comment on the field), `edges/adapters/llm.py::resolve_endpoint` + `::client_for` only, one-line swaps in `cli/__init__.py::_cmd_models_preset` and `cli/_agents.py`, test seeding sites |
| 48 | P29-2 ∥ P29-5 ∥ P29-7 | `core/provider.py`: P29-2 owns new derivation functions + its fields; `core/models_policy.py`, `templates/providers/`, `cli/_doctor.py` (the `_PROVIDER_KEY` users), `cli/_keys.py::_validate_key_format`, `scripts/gen_cli_docs.py` → P29-2; `core/llm.py::ChatResponse`, `edges/adapters/llm.py::complete` (`HTTPError` branch), `core/agent_loop.py` (`call_backend_and_handle_response`, `done`), `core/runtime_driver.py::TurnResult`, `edges/adapters/docket_runtime.py::run_turn` (the `TurnResult(...)` construction), `core/dispatch.py` (the `do_sleep` line), `config.py` → P29-5; `cli/_keys.py::_keys_setup` + `run_auth`, `cli/__init__.py` (the `auth` command), `__main__.py::_REMOVED` → P29-7 |
| 49 | P29-3 ∥ P29-4, then P29-6 | `core/provider.py`: P29-3 owns `verify_endpoint`/`register_provider`/`remove_provider`/`export_provider`, P29-4 owns `AuthSpec` + `headers`; `edges/adapters/llm.py`: P29-3 owns new `probe_models`, P29-4 owns `_headers` + `core/llm.py::Endpoint`; `cli/_provider.py`, `cli/__init__.py` (`models provider` dispatch, `_cmd_models_preset`) → P29-3; `cli/_config.py`, `cli/_doctor.py` (own check), `docs/` → P29-6 after both merge |

Every card follows the §"How to use this board" definition of done.

### P29-1 — a provider is a document, and today's configuration resolves exactly as before

**Status:** DONE (2026-09-27, `0be9812`) · **Size:** M · **Wave:** 47 · **Spec:** `model-profiles.spec.md` → 2.11.0 (new section "Provider catalog"; "Hosted gateway resolution" rule 3 amended; "Provider registration display fields" removed), `config-format.spec.md` → 1.2.0 (`kind: provider` joins the envelope; P28-1 shipped)

**Trigger:**
- `fleet.json → providers` is a loose dict (`core/fleet.py::FleetConfig.providers`, "kept as a
  loose dict"); one model per block; `api`/`name`/`cost`/`reasoning`/`input` are written and read
  by nothing (spec "Provider registration display fields").
- `core/llm.py`'s docstring reserves room for a second dialect; nothing selects the adapter today
  (`edges/adapters/llm.py::client_for` constructs `OpenAIChatClient` unconditionally).

**Goal:**
- `core/provider.py::ProviderSpec` (pydantic, `populate_by_name`, camelCase aliases) with exactly
  the fields this card consumes: `name` (`^[a-z0-9][a-z0-9-]*$`), `dialect: Literal["openai-chat"]`,
  `baseUrl` (http/https), `auth: AuthSpec{type: Literal["bearer","none"], credentials: list[str]}`
  (each `^[A-Z][A-Z0-9_]*$`; `bearer` requires ≥ 1; `none` requires 0), `local: bool`,
  `models: list[ModelRow{id, contextWindow: int|None > 0, maxTokens: int|None > 0}]` (unique ids),
  `note: str`. `local: true` defaults `auth.type` to `none`.
- `load_provider_document(path) -> ProviderSpec`: YAML (JSON included), requires `kind: provider`
  and `name`; raises `ProviderError(file, field, message, valid)` — an unknown `dialect` or
  `auth.type` names the valid values.
- `Catalog` = built-in (`templates/providers/*.yaml`, empty until P29-2) + global
  (`config.PROVIDERS_FILE` = `DOCKET_HOME/docket-providers.json`, shape `{"providers": {name:
  spec}}`), nearest-wins by name; `load_catalog() -> Catalog`, `Catalog.get(name)`,
  `Catalog.source_of(name) -> "built-in" | "global"`, `save_provider(spec)` and
  `delete_provider(name)` through `edges/store.py`.
- `resolve_credential(spec) -> tuple[str, str]` (value, source ∈ `override|env|store|none`):
  `DOCKET_LLM_API_KEY` → env → store, per name in `auth.credentials`, first present wins.
- `migrate_fleet_providers()` on first `load_catalog()`: ports each `fleet.json → providers`
  block (`apiKey` `"local"`/empty → `auth: none`; loopback URL or all-zero `cost` → `local: true`;
  a literal non-placeholder `apiKey` → stored under `<NAME>_API_KEY` via `core/secrets.py` and
  referenced by name, audited `provider.migrate`; display fields dropped), writes the destination,
  then clears the fleet field. Idempotent. `FleetConfig.providers` stays for this read only (comment
  says so; removal deferred one release).
- `edges/adapters/llm.py::resolve_endpoint` reads the catalog instead of `get_local_provider`; for
  a provider absent from the catalog it keeps today's `_HOSTED_GATEWAY_BASE_URLS` / derived
  `<PREFIX>_API_KEY` path untouched (P29-2 retires it). `client_for` dispatches on
  `spec.dialect` over `_DIALECTS = {"openai-chat": OpenAIChatClient}` and returns `None` for
  anything else.
- Delete `core/fleet.py::add_local_provider` and `::get_local_provider`; swap every caller and
  every test seed (`tests/integration/test_llm_port.py` monkeypatches, `test_install.py`,
  `test_maintain_rebuild.py`, `test_provider_registration.py` reads) to the catalog. One-line swaps
  in `cli/__init__.py::_cmd_models_preset` (`registered = load_catalog().get(preset)`) and
  `cli/_agents.py` (the `fleet.providers` foundation check → global catalog non-empty).
  `register_local_provider` keeps its signature and writes through `save_provider` (P29-3 rewrites it).

**Non-goals:** built-in documents, presets, prices, key prefixes (P29-2); `auth: header`, `headers`
(P29-4); verification changes and the CLI actions (P29-3); any doc outside the spec.

**Owns:** `core/provider.py` (whole file), `config.py::PROVIDERS_FILE`, `core/fleet.py` (the two
functions, the field comment), `edges/adapters/llm.py::resolve_endpoint` and `::client_for` only,
the one-line call-site swaps named above, the test seeding sites named above.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| `fleet.json` with this machine's `local` block (URL `http://127.0.0.1:8081/v1`, ctx 16384, max 8192, `apiKey: local`) in a fresh `DOCKET_HOME` | `resolve_endpoint("local/<id>")` returns the same `Endpoint` (base URL, empty key, 16384, 8192) as on the base; `docket-providers.json` holds `{"providers": {"local": {... "auth": {"type": "none"}, "local": true, ...}}}`; `fleet.json` has no `providers` content; a second load writes nothing |
| a fleet block with a literal `apiKey: sk-test-123` | the value is in the central store under `<NAME>_API_KEY`, the document references the name, one `provider.migrate` audit entry, the value never appears in `docket-providers.json` |
| document with `dialect: grpc` | `ProviderError` naming `dialect` and `openai-chat` (negative case) |
| document with `auth: {type: bearer, credentials: []}` | `ProviderError` naming `auth.credentials` |
| `resolve_endpoint("openrouter/openrouter/free")` with no document | unchanged (`https://openrouter.ai/api/v1`) — `TestEndpointResolution` untouched and green |

**RED:** `tests/unit/core/test_provider.py`: `from docket.core.provider import load_provider_document`
fails on the base; `tests/integration/test_llm_port.py`: the migration case above fails on the base
because `docket-providers.json` is never written.

### P29-2 — the providers docket knows are documents, and every table derives from them

**Status:** DONE (2026-09-27, `d9e05f8`) · **Size:** M · **Wave:** 48 · **Spec:** `model-profiles.spec.md` → 2.12.0 ("Presets" 1, "Hosted gateway resolution" 2, "Provider readiness" 2, "Pricing" 1/3/4 amended), `api-keys.spec.md` → 1.5.0 ("Propagation" 3 amended)

**Trigger:** seven tables, seven populations (ADR 0011 evidence row 1); `docket doctor` asks for
`GROQ_API_KEY` for a model `resolve_endpoint` cannot resolve; `resolve_endpoint("anthropic/…")` is
`None` on a fresh install although the preset is the default.

**Goal:**
- `ProviderSpec` gains, each with its reader in this card: `presets: list[Preset{name, ranks{economy,
  standard, premium}, note}]`, `marketplace: bool`, `credentialPrefix: str`, `pricesAsOf: str`
  (`YYYY-MM-DD`, required when any row has a price), `ModelRow.price: Price{input, output,
  cacheRead, cacheWrite}` (USD per MTok, ≥ 0).
- `src/docket/templates/providers/*.yaml`: `anthropic`, `openai`, `google`, `openrouter` (presets
  `openrouter` and `openrouter-free`, `marketplace: true`), `ai-gateway` (`credentials:
  [AI_GATEWAY_API_KEY, VERCEL_OIDC_TOKEN]`, `marketplace: true`), `groq`, `mistral`, `deepseek`,
  `xai`, `cerebras`, `together`, `ollama` (`http://127.0.0.1:11434/v1`, `local: true`), `lmstudio`
  (`http://127.0.0.1:1234/v1`, `local: true`), `local` (today's `DEFAULT_BASE_URL`, `local: true`,
  no rows). Ranks, prices and `pricesAsOf` copied from today's `PRESET_TABLE`/`MODEL_PRICING`
  verbatim; the `anthropic`/`google` preset notes carry the vendor's own evaluation-only / beta
  wording (ADR 0011 evidence, last row). Built-in files are validated by the same loader in a test.
- `core/models_policy.py`: `presets()`, `preset_table()`, `is_local_provider(prefix)`,
  `is_marketplace(prefix)`, `price_for(model)`, `rank_anchors()` (= built-in `anthropic` preset
  ranks) replace `KNOWN_PRESETS`, `PRESET_TABLE`, `LOCAL_PROVIDERS`, `UNPRICED_MARKETPLACE_PROVIDERS`,
  `MODEL_PRICING`, `MODEL_PRICING_AS_OF` and the `_RANK_ANCHORS` literal; `pricing_label`,
  `validate_model`, `load_registry`, `find_registry_problems`, `write_registry` and
  `core/utils.py::estimate_cost_usd` read them. `MODEL_ALIASES` stays.
- `edges/adapters/llm.py`: delete `_HOSTED_GATEWAY_BASE_URLS` and the `PROVIDER_CREDENTIAL_NAMES`
  import; a provider absent from the catalog resolves only under `DOCKET_LLM_BASE_URL` (with the
  derived `<PREFIX>_API_KEY` env name), else `None`. `core/provider.py`: delete
  `PROVIDER_CREDENTIAL_NAMES`; `model_readiness` reads the catalog.
- `cli/_doctor.py`: `_check_provider_coverage` and the JSON twin read `auth.credentials` from the
  catalog (delete `_PROVIDER_KEY`). `cli/_keys.py::_validate_key_format` reads `credentialPrefix`
  (delete `_KEY_PREFIXES`). `scripts/gen_cli_docs.py::_provider_credential_names` reads the catalog.
- `config.DEFAULT_MODEL` stays the one literal; a test pins it to the built-in `anthropic` preset's
  `standard` rank.

**Non-goals:** the `preset` command's registration check and the `provider` CLI (P29-3); docs
(P29-6); `keys setup` (P29-7).

**Owns:** `core/provider.py` (the fields above and new derivation helpers only), `core/models_policy.py`,
`core/utils.py::estimate_cost_usd`, `templates/providers/`, `edges/adapters/llm.py` (the two
deletions only), `cli/_doctor.py` (the two `_PROVIDER_KEY` readers), `cli/_keys.py::_validate_key_format`,
`scripts/gen_cli_docs.py::_provider_credential_names`, `tests/unit/core/test_provider.py`.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| fresh `DOCKET_HOME`, `resolve_endpoint("anthropic/claude-sonnet-4-6")` | `https://api.anthropic.com/v1`, empty key, 200000 / 64000 from the row |
| global document `anthropic` with another `baseUrl` | the global wins; `Catalog.source_of("anthropic") == "global"` |
| `docket models preset` (list) | the seven names of today plus every built-in preset; `openrouter-free` note unchanged |
| `pricing_label("local/x")`, `("openrouter/anything")`, `("groq/x")` | `$0 (local)`, `n/a (bring your own)`, `n/a` — `TestPricingHonesty` untouched and green |
| every file in `templates/providers/` | loads through `load_provider_document` |
| AST test | no dict/tuple literal containing `"anthropic"` or `"openai"` outside `core/provider.py` and `templates/` |

**RED:** `tests/unit/core/test_provider.py`: replace `test_five_known_providers` with the AST test
above (fails on the base on `_PROVIDER_KEY`) and a test that `load_catalog().get("anthropic")` is
non-`None` on a fresh home (fails on the base).

### P29-3 — registration verifies with the credential, and a provider round-trips through the CLI

**Status:** DONE (2026-09-27, `a37bb7d`) · **Size:** M · **Wave:** 49 (after P29-2) · **Spec:** `model-profiles.spec.md` → 2.13.0 ("Provider readiness" 3/4 amended; classification table added), `cli-interface.spec.md` → 1.40.0 (`docket models provider` actions; `preset` no longer requires a block)

**Trigger:** the reproduction in this section's header. `ping_endpoint` also performs network I/O
inside `core/` (side effects belong in `edges/`).

**Goal:**
- `edges/adapters/llm.py::probe_models(endpoint, timeout) -> ProbeResult{status: int|None,
  transport_error: str, model_ids: list[str]}` — GET `<baseUrl>/models` with the same headers
  `complete` would send; never raises.
- `core/provider.py::verify_endpoint(spec) -> ProviderVerification{reachable, status,
  credential_present, credential_name, advertised: list[str], warning: str}` — pure classification of
  a `ProbeResult` per the ADR §4 table; `register_provider(spec) -> Registration{spec, verification,
  changed}` refuses only when `reachable` is `False`, writes global scope, audits `provider.add`;
  `remove_provider(name)` (global only; a built-in name with no override refuses naming the scope),
  audits `provider.remove`; `export_provider(name) -> str` writes the ADR §1 document omitting
  defaults. Delete `ping_endpoint`, `local_provider_config`, `register_local_provider`,
  `ProviderRegistration`, `DEFAULT_MODEL_NAME`, `DEFAULT_PROVIDER/BASE_URL/MODEL_ID/CTX/MAX_TOKENS`
  (the shortcut's defaults come from the built-in `local` document).
- `cli/_provider.py`: `add <file.yaml>` and the existing `add <name> <base-url> --model <id>
  [--ctx] [--max-tokens] [--credential NAME]` shortcut (builds the same `ProviderSpec`; `--name`
  is dropped: the display label no longer exists), `list`, `show <name> [--json]`, `remove
  <name>`, `export <name> [<file>]`; warnings printed literally from `verification.warning`;
  `_print_local_selection` strings re-checked against `TestProviderGuidanceStringsAreReal`.
- `cli/__init__.py`: `models provider <action>` dispatch; `_cmd_models_preset` drops the
  "registered block" refusal and instead prints the readiness line (credential name present or
  missing) after applying, for every preset alike.

**Non-goals:** `auth: header`/`headers` (P29-4); explain/doctor/docs (P29-6).

**Owns:** `core/provider.py` (the functions named), `edges/adapters/llm.py::probe_models` (new
function only), `cli/_provider.py`, `cli/__init__.py` (`models provider` dispatch and
`_cmd_models_preset` only), `tests/integration/test_provider_registration.py`. Adds CLI surface:
`help` and completions goldens, `docs/commands.md`, listed line by line.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| fake HTTP server answering 401 on `/models`; `docket models provider add hosted http://127.0.0.1:<p>/v1 --model m --credential HOSTED_API_KEY` | exit 0, the document is stored, output names `HOSTED_API_KEY`, `verification.status == 401` |
| no server listening | exit 1, nothing stored — `test_ping_failure_is_fail_closed_and_does_not_persist` unchanged and green (negative case) |
| server answering 200 with `{"data":[{"id":"a"},{"id":"b"}]}` and a document listing only `a` | stored; `b` printed as a suggestion; `models[]` still has one row |
| `export local > f.yaml` on this machine's document; fresh home; `add f.yaml` | `show local --json` identical on both homes |
| `docket models preset anthropic` on a fresh home with no key | exit 0, policy applied, one line naming `ANTHROPIC_API_KEY` as missing; `docket init` still stops at step 5 |
| `remove anthropic` with no global override | exit 1 naming the built-in scope |

**RED:** `tests/integration/test_provider_registration.py`: the 401 case fails on the base with
"Provider was not registered".

### P29-4 — a provider can authenticate by header and send static headers

**Status:** DONE (2026-09-27, `00498d1`) · **Size:** S · **Wave:** 49 · **Spec:** `model-profiles.spec.md` → 2.14.0 ("Provider catalog": `auth.type: header`, `auth.header`, `headers`, the reserved-header rule)

**Trigger:** the adapter sends `Authorization: Bearer` or nothing (`OpenAIChatClient._headers`);
Azure OpenAI authenticates with an `api-key` header and multi-workspace Anthropic keys need
`anthropic-workspace-id`; `Endpoint.is_local` has no consumer outside one test.

**Goal:**
- `AuthSpec.type` gains `"header"` with a required `header: str`; `ProviderSpec.headers:
  dict[str, str]` whose keys may not be `authorization`, `content-type` or `accept`
  (case-insensitive; `ProviderError` otherwise).
- `core/llm.py::Endpoint` gains `auth_type`, `auth_header`, `headers` (frozen, defaults keep
  today's behaviour) and loses `is_local`; `resolve_endpoint` fills them from the document.
- `OpenAIChatClient._headers()`: `bearer` → `Authorization: Bearer <v>`; `header` → `<auth.header>:
  <v>`; `none` → no credential header; then `headers`. `probe_models` (P29-3) reuses `_headers`.

**Non-goals:** query-parameter auth (deferred); any second dialect.

**Owns:** `core/provider.py::AuthSpec` and the `headers` field only, `core/llm.py::Endpoint`,
`edges/adapters/llm.py::_headers` and the `Endpoint(...)` construction inside `resolve_endpoint`,
the one `is_local` test.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| document `auth: {type: header, header: api-key, credentials: [AZURE_KEY]}`, `headers: {x-title: docket}`; env `AZURE_KEY=k` | the POST carries `api-key: k` and `x-title: docket` and no `Authorization` |
| document `headers: {Authorization: x}` | `ProviderError` naming `headers` |
| a bearer document | request headers byte-identical to today — `TestTransport` untouched and green |

**RED:** `tests/integration/test_llm_port.py::TestTransport`: the header case fails on the base
(`AuthSpec` rejects `header`).

### P29-5 — a retry waits as long as the provider asked, up to a ceiling

**Status:** DONE (2026-09-27, `7bfbbe2`) · **Size:** M · **Wave:** 48 · **Spec:** `pod-dispatch.spec.md` → 6.21.0 (6.18–6.20 were consumed by Phases 27–28) ("Retries and the failure-kind taxonomy")

**Trigger:** `core/dispatch.py` sleeps `DISPATCH_RETRY_BACKOFF_S * attempt` (2 s, 4 s) and
`edges/adapters/llm.py::complete` discards response headers; a 429 with a 60 s window exhausts
`DISPATCH_RETRIES_DEFAULT` in 6 s. `docs/MODEL-GATEWAYS.md` states the gap.

**Goal:**
- `core/llm.py::ChatResponse.retry_after_s: float | None`; `complete`'s `HTTPError` branch parses
  `Retry-After` (integer seconds, or an HTTP-date as a non-negative delta) when the status is
  retryable; anything unparseable → `None`.
- `core/agent_loop.py`: `call_backend_and_handle_response` passes it to `done(...)`;
  `AgentLoopResult.retry_after_s`; `core/runtime_driver.py::TurnResult.retry_after_s: float |
  None = None` (keyword-only, positional construction unchanged — `test_positional_construction_still_works_without_failure_kind` stays green); `DocketDriver.run_turn` forwards it.
- `core/dispatch.py` hop retry loop: `ctx.do_sleep(min(max(_cfg.DISPATCH_RETRY_BACKOFF_S * attempt,
  run_res.retry_after_s or 0.0), _cfg.DISPATCH_RETRY_MAX_WAIT_S))`; the `hop_retry` trace event
  records `retry_after_s`. `config.py::DISPATCH_RETRY_MAX_WAIT_S` (env, default 60).

**Non-goals:** retry counts, jitter, circuit breaking, the `FailureKind` vocabulary.

**Owns:** `core/llm.py::ChatResponse`, `edges/adapters/llm.py::complete` (`HTTPError` branch only),
`core/agent_loop.py` (`call_backend_and_handle_response`, `done`, `AgentLoopResult`),
`core/runtime_driver.py::TurnResult`, `edges/adapters/docket_runtime.py::run_turn` (the
`TurnResult(...)` construction only), `core/dispatch.py` (the `do_sleep` line and the `hop_retry`
payload only), `config.py` (the new constant).

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| scripted runner: attempt 1 → `daemon_error` with `retry_after_s=7`, attempt 2 → ok | `do_sleep(7.0)` once, task done |
| `retry_after_s=3600` | `do_sleep(60.0)` |
| `retry_after_s=None` | `do_sleep(2.0)`, `do_sleep(4.0)` — `test_linear_backoff_sleeps_increase_per_attempt` untouched |
| fake endpoint: 429 with `Retry-After: 7` | `ChatResponse.retry_after_s == 7.0`, `failure_kind == "daemon_error"` |
| 400 with `Retry-After: 7` | `retry_after_s is None` |

**RED:** `tests/integration/test_retries_and_timeouts.py`: the first case fails on the base
(`TurnResult` has no `retry_after_s`).

### P29-6 — `config explain` names the provider and its scope, and every doc says the same thing

**Status:** DONE (2026-09-27, `1c977aa`) · **Size:** S · **Wave:** 49 (after P29-3 and P29-4) · **Spec:** `model-profiles.spec.md` → 2.15.0 (observability rules), `cli-interface.spec.md` → 1.41.0 (`config explain` provider section; doctor)

**Trigger:** `docket config explain` reports the model id and nothing about where it goes;
`docs/troubleshooting.md` §1 shows an error a CLI user cannot reach; `docs/CONFIGURATION.md`
maps `providers` to `fleet.json`; `docs/MODEL-GATEWAYS.md` documents one-model blocks.

**Goal:**
- `cli/_config.py::_explain` adds `provider: {name, scope, dialect, baseUrl, credential: {name,
  source}, model: {id, contextWindow, maxTokens, source: "row" | "none"}}` (via `resolve_endpoint`,
  `Catalog.source_of`, `resolve_credential`), rendered in `_render_human`.
- `cli/_doctor.py`: `_check_provider_catalog()` reports each malformed global document (file, field,
  reason) the way `find_overlay_problems` is reported; included in `--json`.
- Docs: `docs/CONFIGURATION.md` (§3.1 command table, the file table rows for
  `docket-providers.json` and `templates/providers/`, the note on display fields removed),
  `docs/MODEL-GATEWAYS.md` (rewritten around the document; the "Compatibility does not mean
  feature parity" list kept and re-trued for `Retry-After`), `docs/troubleshooting.md` §1 (the
  reachable error) and its "built-in mappings" sentence about OpenRouter/AI Gateway (now every
  built-in document), `docs/QUICK-START-DOCKET.md` (unchanged commands; one sentence on `export`).
  README limit bullet "Compatible HTTP, not provider SDK parity" gains the Anthropic
  evaluation-only clause — returned as a line for the integrator (D-37).

**Non-goals:** any code beyond `cli/_config.py` and the one doctor function.

**Owns:** `cli/_config.py::_explain` + `_render_human`, `cli/_doctor.py::_check_provider_catalog`
(new) and its two call sites, the four docs named. `docs/commands.md` regeneration.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| agent on `local/<id>` from this machine's document | `config explain --json` has `provider.scope == "global"`, `credential.source == "none"`, `model.contextWindow == 16384` |
| agent on `anthropic/claude-sonnet-4-6`, `ANTHROPIC_API_KEY` in the store | `scope == "built-in"`, `credential.source == "store"` |
| a global document with `auth.type: oauth` | `docket doctor` names the file and `auth.type`; `--json` carries it |
| `grep -n "api.anthropic.com/v1/..." docs/troubleshooting.md` | shows an error the P29-3 path can produce |

**RED:** `tests/integration/test_config_explain.py` (or the file holding `SUBJECT =
"docket.cli._config"`): `report["provider"]` is absent on the base.

### P29-7 — `docket auth` is a removed command, and `keys setup` asks for what the catalog needs

**Status:** DONE (2026-09-27, `04a0ffd`) · **Size:** S · **Wave:** 48 · **Spec:** `cli-interface.spec.md` → 1.42.0 (`docket auth` section removed; removed-command list), `api-keys.spec.md` → 1.6.0 (`setup` iterates the catalog)

**Trigger:** every `docket auth` subcommand answers "gone, use `docket keys add`"
(`cli/_keys.py::run_auth`); the project's mechanism for that is `__main__.py::_REMOVED`
(`workflow`, `team`, `eval`); `_keys_setup` holds the seventh provider table.

**Goal:**
- `__main__.py::_REMOVED["auth"]` = one line pointing at `docket keys add <NAME>` and `docket
  models provider`; delete `run_auth` and its helpers, the `auth` Typer command, the
  `--provider` parsing it carried.
- `_keys_setup` iterates the built-in catalog entries that declare `credentials`, in catalog order,
  using `credentialPrefix` as the hint; the five-row tuple is deleted.
- `TestAuthProviderGoneHonestly` is replaced by one case in the existing removed-commands test.

**Non-goals:** anything in `docket keys` beyond `setup` and `_validate_key_format`'s P29-2 change.

**Owns:** `cli/_keys.py::_keys_setup` and `run_auth` (+ helpers), `cli/__init__.py` (the `auth`
command only), `__main__.py::_REMOVED`, `tests/integration/test_provider_agnosticism.py` (the one
class). Goldens: `help`, `completions_bash`, `completions_zsh` lose the `auth` lines — listed.

**Acceptance / oracle:**

| Case | Result |
| --- | --- |
| `docket auth login` | exit 1, the removed-command line, no traceback |
| `docket keys setup` with a fresh home, scripted input | asks for `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_AI_API_KEY`, `OPENROUTER_API_KEY`, `AI_GATEWAY_API_KEY` and every other built-in credential in catalog order |
| `docket --help` | no `auth` entry |

**RED:** the removed-commands test: `docket auth` prints the `_REMOVED` line on the base — fails
because `auth` is a live command.
## ◆ PHASE 30 — COMPLETE (opened 2026-09-27, closed 2026-09-27): the team lives in the repo (D-46)

**Closed 2026-09-27; every card DONE.** Seven cards in two waves (six planned plus P30-7, a defect found by running the product).
Decision, the directory, the seven best-practice rules, the amended spec rules and the verdict
table are in [docs/adr/0012-the-team-lives-in-the-repo.md](docs/adr/0012-the-team-lives-in-the-repo.md).
Worker packets: [.agents/handoffs/wave-50-worker-packets.md](.agents/handoffs/wave-50-worker-packets.md).
**Activation gate met 2026-09-27:** Phase 29 closed at `8154676`; batching confirmed from the
function-level ownership below; the packets file records the base commit.

**Trigger (explicit request, 2026-09-27):** the front door becomes *agent teams as configuration,
your rules, in YAML*, and repository configuration files must be handled properly, to standards
and best practices. Measured on `b75a258`: `<codebase>/.docket/` is already `apply`'s and
`validate`'s default, yet `docket init` never reads it, a shipped recipe needs `init` then
`apply <wheel path>` (`config.recipes_dir()` has no consumer), `export` demands a path, nothing
records which directory a pod was configured from, a step cannot name its model, and `editRights`
is written by `to_wire` and read only by a display column.

**Test rule (ADR 0012):** one RED behavioural test per card in the module's `SUBJECT` file or the
integration file the card names; a negative case only for a fail-closed property (P30-1, P30-2);
existing tests, goldens and specs are the no-change oracle; no agent-lane tests, no guards;
goldens change only where a card lists the lines.

| Wave | Cards | Hot file and function ownership |
| --- | --- | --- |
| 50 | P30-1 ∥ P30-2 ∥ P30-3 ∥ P30-4 | `cli/_agents.py::run_init` + `_parse_add_args`, `core/pod_apply.py::resolve_recipe` (new) → P30-1; `core/pod.py::PodSettings` (two fields), `core/pod_apply.py::apply` + `::directory_digest` (new), `cli/_pod.py::_pod_export_cmd`, `cli/_config.py` → P30-2; `core/pipeline.py::Step` + `normalize_pipeline`, `core/orchestrator.py::PlannedUnit`, `core/dispatch.py::_run_hop_turn`, `core/runtime_driver.py::RuntimeDriver.run_turn`, `edges/adapters/docket_runtime.py::run_turn`, `cli/_pipeline.py` → P30-3; `core/archetypes.py`, `cli/_roles.py`, `cli/__init__.py` (roles help line), `core/config_docs.py::_load_role`, schemas → P30-4 |
| 51 | P30-5, then P30-6 | integrator: `scripts/render-doc-assets.py`, `scripts/maint/capture-doc-journey.sh`, `docs/assets/`; then `README.md`, `tests/agent/{truth,release}`, `pyproject.toml`, `mkdocs.yml`, `docs/CONFIGURATION.md`, `docs/QUICK-START-DOCKET.md` |

Every card follows the §"How to use this board" definition of done.

**Wave 50 integrator notes (2026-09-27):** the four worker worktrees were checked out at a
stale `88f184e`; every worker re-based its branch on `9101d44` before starting and the
integrator verified `git merge-base` for all four. Two spec conflicts (cli-interface 1.45/1.46/1.47,
pod-blueprints 1.11/1.12) resolved by keeping the higher header and every changelog entry newest
first. `cli-json-shapes.spec.md` → 1.12.0 (integrator): the `provider` block Phase 29 added and
the three configuration-of-record fields were missing from the documented `config explain --json`
shape. **Follow-ups parked (locators only):** `cli/_agents.py::_apply_repo_config` renders the
apply plan with its own loop instead of sharing `cli/_pod.py::_pod_apply_cmd`'s; `core/archetypes.py::
load_role_file`'s `is_short` heuristic routes a `kind: role` document that also carries canonical
fields through `normalize_role` (pre-existing, found by P30-4).

### P30-1 — `docket init` reads the team from the repo, or from a recipe

**Status:** DONE (2026-09-27, `418e684`) · **Size:** M · **Wave:** 50 · **Spec:** `pod-blueprints.spec.md` → 1.11.0 ("Pod manifests: apply" gains the `init` paragraph), `cli-interface.spec.md` → 1.45.0 (`docket init --recipe <name|dir>`, `--no-apply`)

**Trigger:** `cli/_agents.py::run_init` provisions from a blueprint and stops; `<codebase>/.docket/`
is read only by a later `docket pod <p> apply`; `config.recipes_dir()` has no consumer, so a
shipped recipe is two commands and a path into the wheel.

**Goal:**
- `docket init` with a present `<codebase>/.docket/`: validate every document there
  (`core.config_docs.validate_directory`) **before** provisioning; any error prints as `docket
  validate` does, exits 1, provisions nothing. After `build_pod_from_blueprint` succeeds, plan and
  apply the directory through `core.pod_apply.plan_apply`/`apply`, print the plan lines the way
  `docket pod <p> apply` does (shared renderer, never a second loop), and let `apply`'s own
  `pod.apply` audit entry stand.
- `docket init --recipe <name|dir>`: `core/pod_apply.py::resolve_recipe(name_or_dir) -> Path`
  (a directory as given, else `config.recipes_dir()/<name>`; unknown → `PodApplyError` naming
  the shipped names), then the same validate/provision/apply sequence. `--recipe` with a present
  `.docket/` exits 1 naming both sources, before provisioning. `--no-apply` provisions only and
  prints the `docket pod <p> apply` command that would apply the directory.
- The readiness rule (a callable endpoint before the first pod) is unchanged and runs first.

**Non-goals:** recording the source/digest (P30-2); `export` (P30-2); reading `.docket/` anywhere
but `init` and `apply` (ADR 0012 rule 1); multi-pod repositories.

**Owns:** `cli/_agents.py::_parse_add_args` + `::run_init`, `core/pod_apply.py::resolve_recipe`
(new function only), the two specs, `docs/commands.md` regeneration. **Forbidden:**
`core/pod_apply.py::apply`/`export_pod`, `cli/_pod.py`, `core/pod.py`.

**Acceptance:**
- Fixture: a fresh `DOCKET_HOME`, a fake endpoint, a codebase directory holding `.docket/pod.yaml`
  with `members: [reviewer]`. Action: `docket init` from that directory. Result: exit 0, the pod's
  roster (`core.dispatch.pod_full_roster`) has `reviewer`, one `pod.apply` audit entry. Oracle:
  the roster and the audit log, not the printed text.
- Negative: the same codebase with `.docket/roles/bad.yaml` carrying an unknown key. Action:
  `docket init`. Result: exit 1 naming the file and field; no pod member exists; no audit entry.
- `docket init --recipe secure-build` in a codebase without `.docket/` provisions the pod and
  applies the recipe (roster has `security-vetter`); `--recipe x` with a `.docket/` present exits
  1 before provisioning.

**RED test:** `tests/integration/test_pod_provisioning.py` (or the file that drives `run_init`
with a fake endpoint; `rg -n "run_init" tests/`): one positive, one negative as above; both fail
on the base because `run_init` never reads the directory.

**Gates:** worker gates (§0 of the packets); `init` help golden lines listed.

### P30-2 — the pod records its configuration of record; `export` defaults to it

**Status:** DONE (2026-09-27, `60fe2b8`) · **Size:** M · **Wave:** 50 · **Spec:** `pod-blueprints.spec.md` → 1.12.0 ("apply" 6 records source and digest; "export" 1 and 3 default `<dir>`), `cli-interface.spec.md` → 1.46.0 (`pod <p> export [<dir>]`; `config explain` reports `configSource`, `configDigest`, `drift`)

**Trigger:** `core/pod.py::PodSettings` records a bound pipeline by sha256 (verified on every
dispatch) but nothing records the directory a pod was configured from; `cli/_pod.py::
_pod_export_cmd` requires a path while `apply` already defaults to `<codebase>/.docket/`.

**Goal:**
- `PodSettings.config_source` (alias `configSource`, absolute directory) and `config_digest`
  (`configDigest`, `^(|[0-9a-f]{64})$`), written only by `core.pod_apply.apply` after a plan that
  wrote at least one item; `docket pod <p> config set` refuses both keys with "written by apply".
- `core/pod_apply.py::directory_digest(directory) -> str`: sha256 over the sorted relative paths
  and bytes of the files `discover_config_paths` returns plus `plugins/*.py`; `.schemas/` excluded.
- `docket pod <p> export [<dir>]`: default `<codebase>/.docket/`; a non-empty target still refuses
  without `--force`.
- `docket config explain <agent>` (`cli/_config.py`): `configSource`, `configDigest` and `drift`
  (`yes` when the directory's digest differs, `no` when equal, `""` when no source) in `--json` and
  one line in the human view.

**Non-goals:** any reader of the digest on the dispatch path (nothing is applied without an
operator command); reconciliation or prune; `init` (P30-1).

**Owns:** `core/pod.py::PodSettings` (the two fields and the `config set` refusal), `core/
pod_apply.py::apply` + `::directory_digest` (new), `cli/_pod.py::_pod_export_cmd`, `cli/_config.py`,
the two specs. **Forbidden:** `cli/_agents.py`, `core/pod_apply.py::plan_apply` internals.

**Acceptance:**
- Fixture: a pod in a fresh `DOCKET_HOME`, a recipe directory. Action: `docket pod <p> apply
  <dir>`. Result: the pod's settings carry `configSource == <dir>` and `configDigest ==
  directory_digest(<dir>)`. Then edit one policy file in `<dir>`; `docket config explain <lead>
  --json` reports `drift: yes`. Oracle: the settings file and the JSON.
- Negative: `<codebase>/.docket/` non-empty; `docket pod <p> export` (no argument) exits 1 and
  writes nothing; with `--force` it writes and `apply` of the result plans every item `skip`.

**RED test:** `tests/integration/test_pod_apply.py` (`rg -n "export_pod" tests/`): the
apply/drift case and the export-default negative; both fail on the base because the fields do
not exist and `export` rejects a missing argument.

**Gates:** worker gates; `pod` help golden line for `export [<dir>]` listed.

### P30-3 — a pipeline step names its model

**Status:** DONE (2026-09-27, `59e06f6`) · **Size:** S · **Wave:** 50 · **Spec:** `pipeline-format.spec.md` → 2.10.0 ("Steps" + "Short form" gain `model`), `pod-dispatch.spec.md` → 6.22.0 (hop execution honours a step `model` for that hop only), `model-profiles.spec.md` → 2.16.0 (resolution: a step override sits above pin and policy, per hop, never persisted)

**Trigger:** `core/pipeline.py::Step` carries `retries`/`timeout`/`instructions` overrides but no
`model`; `core/dispatch.py::_run_hop_turn` always runs the member's meta model, so a team cannot
say "the review step uses the strong model" in the file that defines the team.

**Goal:**
- `Step.model: str | None` — `cheap`, `strong`, or `<provider>/<id>`; `normalize_pipeline`
  carries it through like `timeout`; `PlannedUnit.model`; `plan` prints `model=<x>` on such a step.
- `RuntimeDriver.run_turn` gains keyword-only `model: str | None = None`; the production driver
  (`edges/adapters/docket_runtime.py::run_turn`) resolves the endpoint for that model and reports
  it in the trace; `_run_hop_turn` resolves `cheap`/`strong` through `core.models_policy`'s rank
  anchors and passes a literal id as is — for that hop only, never written to `.docket-meta.json`.
- An unresolvable literal (provider absent from the catalog) is a `validate`/`plan` error naming
  the step, like an unresolvable role.

**Non-goals:** persisting the override; changing `docket profile` or `config explain` (they show
the persisted model); the 5-arg `ctx.run` test-double shape.

**Owns:** `core/pipeline.py::Step` + `normalize_pipeline`, `core/orchestrator.py::PlannedUnit`,
`core/dispatch.py::_run_hop_turn`, `core/runtime_driver.py::RuntimeDriver.run_turn`,
`edges/adapters/docket_runtime.py::run_turn`, `cli/_pipeline.py` (plan render), the three specs,
`docs/contracts/config-v1/pipeline.schema.json` regeneration. **Forbidden:** `core/agent_loop.py`,
`core/tools.py`, `core/pod.py`.

**Acceptance:**
- Fixture: a pod with a bound pipeline whose implementer step says `model: strong`, the fake HTTP
  server from `tests/integration/test_docket_driver.py`. Action: one dispatch through the
  production driver. Result: the request body's `model` is the `strong` rank anchor; afterwards
  the member's `.docket-meta.json` `model` is unchanged. Oracle: the captured request and the meta.
- `docket pipeline plan` on that file prints `model=` on the step; `validate` on `model:
  nope/x` fails naming the step.

**RED test:** `tests/unit/core/test_pipeline.py` (field + short form) and the driver case above;
both fail on the base because `Step` forbids the key (`extra="forbid"`).

**Gates:** worker gates; no golden expected to change (say so).

### P30-4 — one field says it: `editRights` retired

**Status:** DONE (2026-09-27, `b806fd6`) · **Size:** S · **Wave:** 50 · **Spec:** `role-archetypes.spec.md` → 1.19.0 (wire format: `editRights` accepted and dropped, never written; `deniedTools` is the only capability statement), `cli-interface.spec.md` → 1.47.0 (`roles list` columns)

**Trigger:** `core/archetypes.py::RoleArchetype.edit_rights` is validated and written by
`to_wire`, read only by `cli/_roles.py`'s list column; the registry is narrowed by `deniedTools`
alone, so two fields describe one capability and only one is applied.

**Goal:**
- Remove `edit_rights`, `EDIT_RIGHTS`, its validator and the `to_wire` key; `from_wire` pops
  `editRights` when present so every existing overlay loads. Built-ins and starter templates stop
  declaring it. `core/config_docs.py::_load_role` emits one `note:` for a file that carries it
  (the no-`kind:` deprecation mechanism). `roles list` drops the column; the `roles` help line
  and `core/blueprints.py`'s comment are reworded. Regenerate `role.schema.json` and
  `docs/commands.md`.

**Non-goals:** any other role field; the short form (already has no such key).

**Owns:** `core/archetypes.py`, `core/config_docs.py::_load_role`, `cli/_roles.py`,
`cli/__init__.py` (the `roles` help lines only), `core/blueprints.py` (comment only), the two
specs, schema + docs regeneration. **Forbidden:** `core/pod_apply.py`, `cli/_agents.py`,
`cli/_pod.py`.

**Acceptance:**
- Fixture: a wire document with `editRights: write`. Action: `from_wire` then `to_wire`. Result:
  loads; the output has no `editRights`; `docket roles add --pod p` writes an overlay without it.
  Oracle: the overlay file.
- `docket validate` on a role file carrying the key prints `ok` plus one `note:` line.

**RED test:** `tests/unit/core/test_archetypes.py`: fails on the base because `to_wire` writes
the key.

**Gates:** worker gates; `roles list`/`roles show` golden lines listed if any change.

### P30-7 — a recipe's role follows the fleet's preset, never the compiled-in default

**Status:** DONE (2026-09-27, `6df12aa`) · **Size:** S · **Wave:** 51 · **Spec:** `model-profiles.spec.md` → 2.17.0 ("Roles and built-in policy" requirement 5 amended)

**Trigger (found by running the product for P30-5):** on a throwaway home with `docket models
preset local`, `docket init --recipe secure-build` gave `security-vetter` the model
`anthropic/claude-sonnet-4-6` (source `policy`) while the Lead and Implementer were
`local/local-model`; the first dispatch failed at the vetter hop with HTTP 401 from the hosted
vendor. Cause: `core/models_policy.py::_resolve_via_archetype_class` looked the archetype up in
the **global** registry only; a role applied into the pod's `config/roles.json` was unknown there
and fell to the compiled-in `DEFAULT_MODEL` literal. Second defect in the same run: `pod apply`
and `init` printed the plan without its `[add]`/`[skip]` actions (Rich read them as style tags).

**Goal:** `resolve_role_model(role, role_models, *, project)` resolves a pod-scoped archetype in
`load_registry(project)` against the live rank anchors; an unknown role falls back to the
registry's own `default`, never the literal; `core/pod.py::resolve_member`, `core/pod_apply.py`'s
member planning and `docket profile <id> default` pass the member's pod. One shared, markup-safe
`cli/_pod.py::render_apply_plan` used by `pod apply` and `init`.

**Acceptance:** fixture pod + registry with local anchors → `pod apply secure-build` gives the
vetter `local/x` (`tests/integration/test_recipes.py`); unit: a pod-scoped archetype resolves to
the anchor, an unknown role to the registry default (`tests/unit/core/test_models_policy.py`).
All three failed on the tree before the fix for the stated reason. Live: the throwaway-home
reproduction now reports `local/local-model` and the plan prints `[add]`.

### P30-5 — the assets show the team from the repo

**Status:** DONE (2026-09-27, `2a79a1e`) · **Size:** M · **Wave:** 51 · **Spec:** none (docs assets; `docs/assets/README.md` records the capture)

**Trigger:** `docs/assets/hero.gif` was captured 2026-09-18 before Phases 26–30: its four
frames show `init`, `dispatch`, the gate and harness mode, none shows a team defined in files,
and its title reads "govern agent work".

**Goal:** one real run against the local endpoint (`scripts/maint/capture-doc-journey.sh`, new
scenes: `docket init --recipe secure-build`, `docket validate`, `docket pipeline plan`, `docket
pod <p> dispatch` to `done`, `docket audit verify`), transcribed into `scripts/render-doc-assets.py`
with a `docket` wordmark title; `hero.gif` four clean frames (recipe applied → plan → dispatch →
record), `governance.png` and `isolation.png` from the same run; `--check` passes; scene text is
what the run printed, elided with `⋯`, never reworded.

**Owns (integrator):** the renderer, the capture script, `docs/assets/`. **Acceptance:** the three
outputs regenerate reproducibly (`render-doc-assets.py --check` exit 0) and every frame is
readable at 820 px; the capture root renders as `~`.

**RED test:** none new; `tests/agent/release/test_public_release_truth.py`'s asset checks are the
oracle.

### P30-6 — README v3 on the tagline; prose tests rebuilt from it

**Status:** DONE (2026-09-27, `cefee2e`) · **Size:** M · **Wave:** 51 · **Spec:** none (D-37: the README is descriptive)

**Trigger:** the README of `b75a258` leads with governance; the maintainer's tagline is *agent
teams as configuration, your rules, in YAML* and the pitch is versatility, recipes, YAML + CLI,
open source, governance as the closing property.

**Goal:** README with H1 + tagline, one paragraph, three heroes in this order — *The team you
define* (recipe → `init`/`apply`, role and pipeline short forms, `validate`, `explain`), *The run*
(queue, dispatch, verify by exit code, verdicts, bounded rework, triggers), *The gate and the
record* — each with its asset, its limit beside it and its proving commands; quick start; "Use
something else if"; the configuration table; Known limits; Documentation. The three agent-lane
prose tests are deleted and rewritten from this README's own rules; `pyproject.toml`, the package
docstring and `mkdocs.yml` carry the tagline's short form; `docs/CONFIGURATION.md` gains "The team
lives in the repo" and the quick start starts from `.docket/`.

**Owns (integrator):** `README.md`, `tests/agent/truth/test_docs_positioning.py`,
`tests/agent/release/test_public_release_truth.py`,
`tests/agent/release/test_runtime_adapter_public_truth.py`, `pyproject.toml`, `mkdocs.yml`,
`src/docket/__init__.py`, `docs/CONFIGURATION.md`, `docs/QUICK-START-DOCKET.md`, `CHANGELOG.md`.

**Acceptance:** `pytest tests/agent` exit 0; each rebuilt test fails on the previous README;
`scripts/metrics.py --check` in sync; README under the rebuilt ratchet.
## ◆ PHASE 31 — COMPLETE (opened 2026-09-27, closed 2026-09-27): recipes as a library, and the repository's standards (D-47)

**Closed 2026-09-27; every card DONE.** Seven cards in three waves (four Sonnet workers in parallel, two more, then the integrator). Decision, the library, the three-scope rule,
the amended spec rules and the verdict table are in
[docs/adr/0013-recipes-as-a-library-and-the-repos-standards.md](docs/adr/0013-recipes-as-a-library-and-the-repos-standards.md).
Worker packets: [.agents/handoffs/wave-53-worker-packets.md](.agents/handoffs/wave-53-worker-packets.md).
**Activation gate met 2026-09-27:** Phase 30 and Wave 52 closed at `e3a765b`; batching confirmed
from the function-level ownership below; the packets file records the base commit.

**Trigger (explicit request, 2026-09-27):** recipe handling that is robust, extensible and
maintainable; example recipes for the methodologies practised in autonomous-agent orchestration;
stronger policy and pipeline recipes; `AGENTS.md` and skills so the product extends under the
standards. Measured on `e3a765b`: every recipe part is already optional in
`core/pod_apply.py::plan_apply`, yet nothing derives or prints what a directory brings, `pod.yaml`
has no `description`, the only listing of names is `resolve_recipe`'s error text, the three
shipped recipes are all whole teams, `apply` records `configSource` only from a directory that
changed something, the recipe policies match prose where `tool`/`path` predicates exist unused,
`AGENTS.md` is read only when an operator names it, and the prompt has no skills section.

**Test rule (ADR 0013):** one RED behavioural test per card in the module's `SUBJECT` file or the
integration file the card names; a negative case only for a fail-closed property (P31-1, P31-5,
P31-6); existing tests, goldens and specs are the no-change oracle; no agent-lane tests, no
guards; goldens change only where a card lists the lines.

| Wave | Cards | Hot file and function ownership |
| --- | --- | --- |
| 53 | P31-1 ∥ P31-5 ∥ P31-3 ∥ P31-4 | `core/pod_apply.py::summarize_recipe` (new) + `::apply` (record on every validated apply) + `::_export_manifest` + `_MANIFEST_KEYS`, `core/config_docs.py::PodDocument`, schemas, `cli/_validate.py`, `cli/_pod.py::_pod_apply_cmd`, `cli/_agents.py::_apply_repo_config` → P31-1; `core/identity.py::_project_instructions_raw`, `cli/_config.py::_explain` → P31-5; `templates/recipes/{git-safety,no-egress,secrets-guard,prod-approval}/`, the two existing policy files, `tests/integration/test_recipes.py` → P31-3; `templates/recipes/{tdd,spec-first,reflexion,dual-review,frugal}/`, `tests/integration/test_recipe_methodologies.py` (new) → P31-4 |
| 54 | P31-2 ∥ P31-6 | `core/pod_apply.py::resolve_recipe` + `::list_recipes` (new), `config.py::user_recipes_dir` (new), `cli/_recipes.py` (new), `cli/__init__.py` (one command), `completions` golden → P31-2; `core/skills.py` (new), `core/identity.py` (skills section), `core/tools.py` (one `skill` registration), `core/pod_apply.py::_plan_skills`/`_export_skills`/`directory_digest`/`summarize_recipe` (skills count), `config.py::SKILLS_DIR`, `cli/_config.py` (skills line), `templates/recipes/secure-build/skills/` → P31-6 |
| 55 | P31-7 | integrator: `scripts/gen_recipe_docs.py`, `docs/recipes.md`, `.github/workflows/ci.yml`, `templates/recipes/{tdd,spec-first}/skills/`, `docs/CONFIGURATION.md`, `docs/AGENT-TEAMS.md`, `docs/QUICK-START-DOCKET.md`, `docs/README.md`, `mkdocs.yml`, `README.md`, `tests/agent/{truth,release}`, `CHANGELOG.md`, rollups |

Every card follows the §"How to use this board" definition of done.

**Integrator notes (2026-09-27):** every worker worktree was checked out at a stale `88f184e`
again; each worker re-based onto the wave's base before starting and the integrator verified
`git merge-base` (Wave 50's lesson, now standing). Spec conflicts (cli-interface 1.49/1.50 and
1.51/1.52, pod-blueprints 1.14/1.15/1.16 and 1.17/1.18, workspace-structure 1.13/1.14) were
resolved by keeping the higher header and every changelog entry newest first; the two halves of
"The recipe library" became one table. Two workers shipped `pod.yaml` `description` before
P31-1's parser landed and skipped the dependent assertions with a named reason; the skips were
removed at integration. Running the suite inside P31-6 found two unwired seams and closed them:
the `skill` tool's kind was missing from `core/archetypes.py::BUILTIN_TOOL_KINDS` (a denial by
capability would have missed it) and `core/skills.py` was absent from the runtime wheel's file
list. P31-6 widened the span baseline for `builtin_registry` (180 → 206); the integrator split
the `skill` and `fetch` registrations out instead and the baseline shrank to 157. The derived
one-word `kind` P31-2 printed could not tell a methodology recipe from a team, so `recipes list`
derives `brings` (the summary parts joined with `+`) instead; cli-interface 1.53.0,
pod-blueprints 1.19.0. Nothing is parked.

### P31-1 — a recipe says what it brings

**Status:** DONE (2026-09-27, `f3aafe3`) · **Size:** M · **Wave:** 53 · **Spec:** `pod-blueprints.spec.md` → 1.14.0 ("Pod manifests: apply" req 1 key set gains `description`; req 6 records source and digest on every validated apply; new req 9 "Recipe summary"), `config-format.spec.md` → 1.3.0 (manifest key set), `cli-interface.spec.md` → 1.49.0 (`validate` summary line; `apply`/`init --recipe` header)

**Trigger:** `core/pod_apply.py::plan_apply` accepts a directory with only `policies/`, only
`roles/` or only `pipeline.yaml`, but nothing derives or prints what a directory contains;
`_MANIFEST_KEYS` has no `description`; `apply` writes `configSource`/`configDigest` only under
`if plan.has_changes()`, so a second, all-`skip` apply of an identical directory at another path
leaves the record pointing at the first.

**Goal:**
- `core/pod_apply.py::summarize_recipe(directory: Path) -> RecipeSummary` (frozen dataclass:
  `roles`, `policies`, `plugins`, `skills`, `members`, `settings` as `int`; `pipeline` as
  `str` — the pipeline document's `name`, or `""`; `description: str`), pure, reads only; `skills`
  counts `skills/*/SKILL.md` directories so P31-6 changes no signature. `RecipeSummary.render()`
  returns one line: `roles 1 · policies 1 · members 1 · pipeline secure-build · plugins 0 · skills 0 · settings 0`
  (every count always shown, in that order).
- `pod.yaml` accepts `description` (string; any other type refused naming the key); `_MANIFEST_KEYS`
  gains it; `core/config_docs.py::PodDocument.description: str | None`; both schema copies
  regenerated; `_export_manifest` writes it when set. A `scope:` key stays refused as unknown.
- `apply` records `configSource`/`configDigest` after every plan `plan_apply` validated, all-`skip`
  included; the `pod.apply` audit entry keeps its "only when something changed" rule.
- `docket validate <dir>` prints, after the per-file lines, `summary: <render()>` (and the
  description on its own line when set); a file target prints no summary.
- `docket pod <p> apply [<name|dir>]` and `docket init --recipe` print the same header before the
  plan (`Apply plan — <p> <- <dir>` then the description line when set, then `  <render()>`),
  through one shared renderer (`cli/_pod.py`; `cli/_agents.py::_apply_repo_config` calls it —
  this closes the parked "own loop" follow-up).

**Non-goals:** listing recipes (P31-2); the operator scope (P31-2); skills content (P31-6);
any reader of `description` on the dispatch path.

**Owns:** `core/pod_apply.py::summarize_recipe` (new), `::plan_apply` (the `description`
key), `::apply` (the record), `::_export_manifest`, `_MANIFEST_KEYS`; `core/config_docs.py::
PodDocument`; `docs/contracts/config-v1/pod.schema.json` + `src/docket/templates/schemas/
pod.schema.json` (regenerated); `cli/_validate.py`; `cli/_pod.py::_pod_apply_cmd` (+ the
extracted renderer); `cli/_agents.py::_apply_repo_config`; the three specs. **Forbidden:**
`cli/__init__.py` (`cmd_pod` sits at the span limit), `core/pod_apply.py::resolve_recipe`,
`core/identity.py`, `templates/recipes/`.

**Acceptance:**
- Fixture: a directory holding only `policies/one.yaml` (a valid short-form policy). Action:
  `summarize_recipe(dir)`. Result: `policies == 1`, every other count `0`, `pipeline == ""`;
  `render()` is the exact line above with those numbers. Oracle: the dataclass.
- Fixture: a pod in a fresh `DOCKET_HOME`; directory A applied (writes); directory B, byte-identical
  content at another path. Action: `apply(plan_apply(p, B))`. Result: every item `skip`, no new
  `pod.apply` audit line, and `PodSettings.load_for(p).config_source == str(B.resolve())`.
  Oracle: the settings file and `read_audit`.
- Negative: `pod.yaml` with `scope: policies` — `plan_apply` raises `PodApplyError` naming
  `scope`, nothing written.
- `docket validate <recipe dir>` output ends with the `summary:` line; `docket pod <p> apply
  secure-build --dry-run` prints the header, the description line and the summary before
  `[add] role: security-vetter`.

**RED test:** `tests/unit/core/test_pod_apply.py` (the summary case; fails on the base:
`summarize_recipe` does not exist) and `tests/integration/test_pod_apply.py` (`rg -n
"config_source" tests/integration/`; the all-skip record case fails on the base because the
record stays at A). The negative rides in the unit file.

**Gates:** worker gates; no golden changes expected (`validate`/`apply` output is not a golden
case; confirm with `rg -n "Apply plan" tests/golden/`).

### P31-2 — `docket recipes list|show`, and the operator's own recipes directory

**Status:** DONE (2026-09-27, `0d37e8d`) · **Size:** M · **Wave:** 54 (after P31-1) · **Spec:** `pod-blueprints.spec.md` → 1.17.0 ("apply" req 8 resolution order gains the operator scope; new "Recipe listing" requirement), `cli-interface.spec.md` → 1.51.0 (`docket recipes list [--json]`, `docket recipes show <name|dir> [--json]`), `workspace-structure.spec.md` → 1.13.0 (`~/.docket/recipes/`)

**Trigger:** `core/pod_apply.py::resolve_recipe` knows two places (a path, the wheel); the only
enumeration of names is its error text; ADR 0013 §1 rule 5 records why a listing is now due.

**Goal:**
- `config.py::user_recipes_dir() -> Path` (`DOCKET_HOME / "recipes"`); `resolve_recipe` order: a
  directory path as given, else `user_recipes_dir()/<name>`, else `recipes_dir()/<name>`; the
  error names both scopes' names (`operator: a, b; shipped: ...`).
- `core/pod_apply.py::list_recipes() -> list[RecipeInfo]` (`name`, `scope` in `operator|shipped`,
  `directory`, `summary: RecipeSummary`), nearest-wins by name, sorted by name.
- New `cli/_recipes.py::run_recipes(args) -> int`: `list` (table: NAME, SCOPE, KIND derived —
  `team` when members and a pipeline, `policies` when only policies, `pipeline` when a pipeline and
  no policies, else `mixed` — plus DESCRIPTION; `--json` a list of objects with the summary fields),
  `show <name|dir>` (description, scope, directory, summary, the README body when present);
  unknown name exits 1 with the resolution error. Registered in `cli/__init__.py` exactly as
  `plugins` is (one `@app.command` block); `completions` golden gains the command; `docs/commands.md`
  regenerated.

**Non-goals:** installing, removing or fetching recipes; `docs/recipes.md` (P31-7); any change to
`apply`'s plan or record.

**Owns:** `config.py::user_recipes_dir` (new), `core/pod_apply.py::resolve_recipe` + `::list_recipes`
(new) + `RecipeInfo` (new), `cli/_recipes.py` (new), `cli/__init__.py` (one new command block only),
`tests/golden/cases/completions*` (the one line), `docs/commands.md`, the three specs. **Forbidden:**
`core/pod_apply.py::plan_apply`/`apply`/`summarize_recipe` internals, `cli/_pod.py`,
`core/identity.py`, `core/skills.py`.

**Acceptance:**
- Fixture: fresh `DOCKET_HOME` with `recipes/mine/policies/x.yaml` (valid) and no `pod.yaml`. Action:
  `list_recipes()`. Result: an entry `mine` with scope `operator`, `summary.policies == 1`; every
  shipped recipe present with scope `shipped`. Then `docket pod <p> apply mine --dry-run` plans
  `[add] policy: x.yaml`. Oracle: the list and the CLI output.
- Negative: `docket recipes show nope` exits 1; the message names `operator:` and `shipped:` lists.

**RED test:** `tests/integration/test_recipes.py` (the operator-scope case; fails on the base:
`list_recipes` does not exist and `apply mine` reports an unknown recipe).

**Gates:** worker gates; `completions` golden: the one added line listed.

### P31-3 — policy packs: four single-concern recipes, and the two existing policies on structured predicates

**Status:** DONE (2026-09-27, `a3ea102`) · **Size:** M · **Wave:** 53 · **Spec:** `pod-blueprints.spec.md` → 1.15.0 (new section "The recipe library": kinds and the twelve names; this card writes the section with the policy-pack rows and the three team rows, P31-4 adds the methodology rows)

**Trigger:** `core/policy.py::_predicate_matches` evaluates `tool`, `path`, `branch` and `anyOf`
over the call, yet `secure-build/policies/require-approval-secret-writes.yaml` matches the prose
`write.*\.env` and `ops-approval/policies/ops-approval-high-risk.yaml` matches text only; no
shipped recipe is a policy pack, so a reader cannot see that one can be.

**Goal:** four recipes under `templates/recipes/`, each `pod.yaml` (`kind: pod`, `name`,
`description`), `policies/*.yaml` in the short form, and a README that opens with what the pack
adds, its threat model in three sentences, the `docket policies test` command that shows it
firing, and "Undo":
- `git-safety`: block `git push --force|-f`, `git reset --hard`, `git clean -f*`, `git branch -D`,
  `git checkout -- .`, `git config --global`; ask on `git push` to `main|master|production|prod`
  (branch-aware where the `branch` predicate applies); every role that can run `bash`.
- `no-egress`: ask on `bash` calls naming `curl|wget|nc|ncat|ssh|scp|rsync|ftp`; ask on
  `pip install|pipx|uv add|uv pip install|npm install|npx|pnpm add|yarn add|cargo add|go get`;
  ask on `tool: fetch`. README states that this pack closes by policy what `bash` leaves open
  (security-gates D-23), and what it does not close (interpreters).
- `secrets-guard`: block `write`/`edit` whose `path` matches `**/.env*`, `**/*.pem`, `**/*.key`,
  `**/id_rsa*`, `**/*.p12` (one `anyOf`); block text carrying a private-key header, an AWS access
  key id shape or a `sk[-_]` bearer shape on `toolCall`; `redact` the same shapes `on: output`.
  Every pod role.
- `prod-approval`: the existing ops policy generalised to `implementer` and `operator` — ask on
  `kubectl apply|delete|replace|rollout`, `helm upgrade|install`, `terraform apply|destroy`,
  `docker push`, `npm publish`, `fly deploy`, `vercel --prod`, `heroku promote`, `git push` to a
  production-shaped branch.
- `secure-build`'s policy: `anyOf` of `{tool: write, path: '**/.env*'}`, `{tool: edit, path:
  '**/.env*'}`, `{matches: <private-key header>}` — ask; `ops-approval`'s policy: keep `matches`
  but add `tool: bash`. Both READMEs updated to say why.
- `tests/integration/test_recipes.py`: `test_every_recipe_has_a_pipeline_and_a_readme` becomes
  "a README and at least one of pipeline / roles / policies / members"; the parametrised
  validation cases already cover the new files; new RED: applying `git-safety` onto a lean
  fixture pod plans only `policy` items, and after `apply`, `core.policy.policy_test`
  (`rg -n "def policy_test" src/`) on `pre_tool_call` for `implementer` with
  `git push --force origin main` returns `block`; `secrets-guard` on a `write` to `.env` returns
  `block` and on a plain `write` to `README.md` returns `allow`.

**Non-goals:** any change to `core/policy.py`; new predicate keys; pipelines (P31-4); the
`pre_output` redaction engine (use what `then: redact` already does; if `on: output` with
`redact` is refused by `validate_policy`, drop that rule and say so in the return).

**Owns:** the four new recipe directories, the two existing policy files and their READMEs,
`tests/integration/test_recipes.py`, `pod-blueprints.spec.md` (the new section only).
**Forbidden:** `core/policy.py`, `core/pod_apply.py`, every other recipe directory,
`tests/integration/test_recipe_methodologies.py`.

**Acceptance:** the fixture/action/result triples above; every new policy file passes
`validate_policy` (`test_recipe_policy_validates` parametrises over it); `docket policies test
pre_tool_call implementer 'git push --force origin main'` prints `block` after `apply git-safety`
on a throwaway `DOCKET_HOME`.

**RED test:** the three new cases in `tests/integration/test_recipes.py`; they fail on the base
because the directories do not exist.

**Gates:** worker gates; no goldens.

### P31-4 — methodology recipes: five pipelines that are the practice

**Status:** DONE (2026-09-27, `de092d2`) · **Size:** M · **Wave:** 53 · **Spec:** `pod-blueprints.spec.md` → 1.16.0 ("The recipe library" gains the five methodology rows; if P31-3 has not merged, write the section with your rows and the integrator merges)

**Trigger:** the pipeline dialect carries `verify`, `verdict`, `on:` with `max`, `parallel`,
`run:`, `model:` and `settings`, and the built-in and starter roles cover reviewer, tester,
critic and writer; the only shipped pipelines are three whole teams, so the practices operators
ask for (test-first, spec-first, bounded self-critique, independent double review, a spend cap)
have no example.

**Goal:** five recipes, each `pod.yaml` (`kind: pod`, `name`, `description`, `members` limited to
the roles the pipeline needs from `docket roles list`), `pipeline.yaml` in the short form, a README
that names the practice, its source idea (one line, no citation needed), what docket's gates make
structural, and "Undo":
- `tdd`: `red: implementer` (step `instructions`: write one failing test for the task, change
  nothing else), `check-red: {run: <the verify command>}` routed `on: {pass: fail, fail: green}`
  if `validate` accepts an `on:` map on a command step (read pipeline-format "Conditional steps
  and command steps" and pod-dispatch "command step"; if not accepted, `check-red` is dropped and
  the README says why), `green: implementer` with `verify: true`, `test: tester` verdict
  `[PASS, FAIL]`. `members: [tester]`. If `run:` cannot reference the pod's own verify command, the
  literal is `python3 -m pytest -q` and the README says to edit it.
- `spec-first`: `spec: writer` (instructions: write the specification file), `approve-spec:
  critic` verdict `[APPROVE, REJECT]` with `on: {REJECT: {goto: spec, max: 1}}`, `build:
  implementer` `verify: true`, `review: reviewer` verdict `[APPROVE, REQUEST-CHANGES]` with a
  bounded route back to `build`. `members: [writer, critic, reviewer]`.
- `reflexion`: `build: implementer` `verify: true`, `critique: critic` verdict
  `[APPROVE, REQUEST-CHANGES]` with `on: {REQUEST-CHANGES: {goto: build, max: 2}}`, `test: tester`
  verdict `[PASS, FAIL]`. `members: [critic, tester]`.
- `dual-review`: `build: implementer` `verify: true`, then a `parallel` group of `review-code:
  reviewer` and `review-risk: critic`, each with its verdict gate (read "Parallel groups" for what
  a child may carry). `members: [reviewer, critic]`.
- `frugal`: `settings: {budgetUsd: 2, maxReworkCycles: 1, turnTimeoutS: 600}`; `plan: lead` with
  `model: cheap`, `build: implementer` `verify: true`, `review: reviewer` `model: cheap` verdict.
  `members: [reviewer]`.
- New `tests/integration/test_recipe_methodologies.py` (`SUBJECT = "docket.config"`, the
  `_seed_fixture_pod` pattern copied from `test_recipes.py` — import it if it is importable,
  otherwise a local copy): parametrised over the five: `plan_apply` + `apply` on a lean pod then
  `resolve_plan` leaves no step skipped; `dual-review`'s plan has one `PlannedGroup`; `frugal`'s
  plan carries three `setting` items; `tdd`'s spec routes `check-red` as declared (or has no such
  step, per the README); one `FakeDriver` dispatch of `reflexion` (the pattern at the bottom of
  `test_recipes.py`) whose critic answers `REQUEST-CHANGES` once then `APPROVE` reaches `done`
  with the rework counted.

**Non-goals:** new dialect features; changes to `core/dispatch.py`, `core/pipeline.py`,
`core/orchestrator.py`; skills (P31-7 adds them to `tdd`/`spec-first`); policy packs (P31-3).

**Owns:** the five recipe directories, `tests/integration/test_recipe_methodologies.py` (new),
`pod-blueprints.spec.md` (the five rows). **Forbidden:** every other recipe directory,
`tests/integration/test_recipes.py`, every `core/` module.

**Acceptance:** the parametrised triples above; `docket pipeline validate` and `pipeline plan`
succeed for each recipe on a throwaway `DOCKET_HOME` after `init --recipe <name>` against a
fake endpoint (`rg -n "FakeDriver\|fake endpoint" tests/integration/test_pod_provisioning.py`
shows how `init` runs hermetically).

**RED test:** the new file; every case fails on the base because the directories do not exist.

**Gates:** worker gates; no goldens.

### P31-5 — `AGENTS.md` is read by default

**Status:** DONE (2026-09-27, `366bd0d`) · **Size:** S · **Wave:** 53 · **Spec:** `agent-loop.spec.md` → 1.23.0 ("System prompt composition" req 30: the default), `cli-interface.spec.md` → 1.50.0 (`config explain` reports the project-instructions source), `cli-json-shapes.spec.md` → 1.13.0 (`projectInstructions: {files: [...], source: "set"|"default"|""}`)

**Trigger:** `core/identity.py::_project_instructions_raw` returns `""` when
`PodSettings.project_instructions` is empty, so the `AGENTS.md` a repository already keeps for
Codex, Copilot, Cursor and Claude Code reaches a docket agent only if an operator repeats its
name in a pod setting.

**Goal:**
- When the setting is unset and `project_roots[0] / "AGENTS.md"` is a file, compose it exactly as
  an explicitly named file is composed today: screened through `pre_input` as untrusted, the same
  `## AGENTS.md` heading, the same cap and `projectInstructions` report. An explicit setting
  replaces the default entirely. No root, no file, or a set list without it: byte-identical to
  today.
- `core/identity.py::project_instruction_files(settings, root) -> tuple[tuple[str, ...], str]`
  (the files and `"set"|"default"|""`), used by composition and by `cli/_config.py::_explain`,
  which gains `projectInstructions` in `--json` and one human line
  (`Project instr.:   AGENTS.md (default)` / `(set)` / `none`).

**Non-goals:** nested `AGENTS.md`; `CLAUDE.md` or any second default name; changing the cap or
the screening; the workspace's own docket-written `AGENTS.md` (a different file, unchanged).

**Owns:** `core/identity.py::_project_instructions_raw` + `::project_instruction_files` (new),
`cli/_config.py::_explain` + its human renderer, the three specs. **Forbidden:** `core/pod.py`,
`core/tools.py`, `core/skills.py`, `core/pod_apply.py`.

**Acceptance:**
- Fixture: a pod in a fresh `DOCKET_HOME`, `projectInstructions` unset, a codebase root holding
  `AGENTS.md` with a sentinel line. Action: `compose_agent_prompt(lead_id, project_roots=(root,))`.
  Result: the text carries `## AGENTS.md` and the sentinel, and the sections report names
  `projectInstructions`. Oracle: the composition.
- Negative: the same root plus `projectInstructions: CONTRIBUTING.md`. Result: the sentinel is
  absent; `## CONTRIBUTING.md` present. Oracle: the composition.
- `docket config explain <lead> --json` carries `{"files": ["AGENTS.md"], "source": "default"}`.

**RED test:** `tests/unit/core/test_identity.py` (the default case; fails on the base: the
section is empty). The negative rides in the same class.

**Gates:** worker gates; goldens unchanged (confirm `config explain` is not a golden case).

### P31-6 — skills: the Agent Skills shape, three scopes, one `skill` tool

**Status:** DONE (2026-09-27, `588fa71`) · **Size:** L · **Wave:** 54 (after P31-1 and P31-5) · **Spec:** `agent-loop.spec.md` → 1.24.0 (req 30 gains the `skills` section; "Per-role tool narrowing" names `skill` in the built-in set), `pod-blueprints.spec.md` → 1.18.0 (`skills/` planned, applied, exported, digested, counted), `workspace-structure.spec.md` → 1.14.0 (`~/.docket/skills/`, the pod's `config/skills/`), `cli-interface.spec.md` → 1.52.0 (`config explain` skills line), `cli-json-shapes.spec.md` → 1.14.0 (`skills: [{name, scope}]`)

**Trigger:** `core/identity.py::compose_agent_prompt` composes identity, instructions, project
instructions, contract and workspace state; there is no place for a reusable, on-demand
instruction module, and `core/tools.py::build_default_registry` offers no way to read one that
lives outside the project roots. The Agent Skills shape (`skills/<name>/SKILL.md`, frontmatter
`name` + `description`, body on demand) is what the ecosystem already writes.

**Goal:**
- New `core/skills.py`: `SkillMeta(name, description, directory, scope)`;
  `parse_skill_file(path) -> SkillMeta` (YAML frontmatter between `---` lines; `name` required,
  1–64 chars `[a-z0-9-]`, equal to the directory name; `description` required, ≤1024 chars; other
  keys ignored; a violation raises `SkillError` naming the file and field);
  `discover_skills(project, codebase_root) -> dict[str, SkillMeta]` over
  `<codebase_root>/.docket/skills/`, `config.pod_config_dir(project)/skills/`, `config.SKILLS_DIR`
  (`DOCKET_HOME/skills`), nearest wins by name in that order; an invalid skill is skipped and
  audited once (`skills.invalid`), never raised into a turn.
- `core/identity.py`: after project instructions and before the runtime contract, a section
  `# Skills` listing `- <name>: <description>` per discovered skill (descriptions screened through
  `pre_input` as untrusted, the section capped to half the remaining budget and reported as
  `skills`, like `projectInstructions`), ending with one line telling the model to call the
  `skill` tool with a name for the full instructions. No skills, no section, byte-identical.
- `core/tools.py`: one new built-in `skill` (`kind="read"`, parameters `name` required, `path`
  optional) whose handler resolves the name through `core.skills.discover_skills(ctx.project,
  ctx.roots[0] if ctx.roots else None)` and returns `toolbox.read_file((skill.directory,),
  path or "SKILL.md")` — containment to the skill's own directory, output truncated like every
  tool; an unknown name is a failed call naming the known names. Denied like any tool
  (`deniedTools: [skill]`).
- `core/pod_apply.py`: `_plan_skills` (a recipe's `skills/<name>/` copied whole into the pod's
  `config/skills/<name>/`, compared by a sha256 over the directory's sorted relative paths and
  bytes: add/replace/skip), `apply` writes it (mode 0700/0600), `_export_skills` writes it back,
  `directory_digest` includes `skills/**`, `summarize_recipe` counts it.
- `secure-build` gains `skills/security-review/SKILL.md` (a review checklist the vetter can pull;
  frontmatter per the shape) so the round trip is proven on shipped data.
- `cli/_config.py::_explain`: `skills` in `--json` (`[{name, scope}]`) and one human line.

**Non-goals:** auto-loading a body by task match; `skills:` on a role; `allowed-tools`
enforcement; a `docket skills` command; reading `scripts/` for execution (a skill's script runs
only if the model runs it through `bash`, gated as ever).

**Owns:** `core/skills.py` (new) + `tests/unit/core/test_skills.py` (new, `SUBJECT =
"docket.core.skills"`), `core/identity.py` (the skills section only; P31-5's function is merged
before you start), `core/tools.py` (one `registry.register` block for `skill`; the AST test
`test_only_the_chokepoint_imports_the_handler_module` must stay green — `core/skills.py` never
imports `edges/`), `core/pod_apply.py::_plan_skills`/`_export_skills` (new) + `directory_digest`
+ `summarize_recipe` (the count) + `apply`/`export_pod` (the two calls), `config.py::SKILLS_DIR`,
`cli/_config.py` (the skills line), `templates/recipes/secure-build/skills/`, the five specs.
**Forbidden:** `core/agent_loop.py`, `core/policy.py`, `edges/adapters/toolbox.py`,
`core/pod_apply.py::resolve_recipe`/`list_recipes` (P31-2), every other recipe directory.

**Acceptance:**
- Fixture: fresh `DOCKET_HOME`, a pod, `config/skills/security-review/SKILL.md` (valid). Action:
  `compose_agent_prompt(vetter_id, project_roots=(root,))`. Result: the text carries
  `- security-review: <description>` under `# Skills` and the section report `skills`. Then
  `dispatch_tool(ToolCall("skill", {"name": "security-review"}), ctx, registry)` returns
  `ok` with the body. Oracle: the composition and the `ToolResult`.
- Fixture: the same, plus the vetter's archetype `deniedTools: [skill]`. Action: the same call
  after per-role narrowing (the pattern in `tests/unit/core/test_tools.py` for a denied tool).
  Result: a typed denial, not executed. Oracle: `ToolResult.executed is False`.
- Round trip: `apply` of `secure-build` plans `[add] skill: security-review`; `export` writes
  `skills/security-review/SKILL.md`; `apply` of the export plans `skip`; `summarize_recipe`
  reports `skills 1`.
- Negative: a `SKILL.md` whose `name` differs from its directory is skipped with one
  `skills.invalid` audit line and the prompt has no section.

**RED test:** `tests/unit/core/test_skills.py` (parse + discover), `tests/unit/core/
test_identity.py` (the section), `tests/unit/core/test_tools.py` (the tool and its denial),
`tests/integration/test_pod_apply.py` (the round trip). Each fails on the base: the module, the
section and the tool do not exist.

**Gates:** worker gates; goldens unchanged unless the tool list appears in one (`rg -n
'"fetch"' tests/golden/`); if it does, list the line.

### P31-7 — the library is documented from data; the docs and README carry the standards

**Status:** DONE (2026-09-27, `05e7a95`) · **Size:** M · **Wave:** 55 (integrator, after 54) · **Spec:** none (D-37: README and docs are descriptive); `test-framework.md` only if the generator gains a CI check the spec must name

**Trigger:** twelve recipes, two kinds of repository standard and a new tool with no page that is
generated from what ships; `docs/CONFIGURATION.md` §3.10 still describes three whole-team recipes.

**Goal:** `scripts/gen_recipe_docs.py` renders `docs/recipes.md` (one section per recipe: name,
kind, description, derived summary, apply commands, the README body) with `--check`, run in the
CI docs job beside `gen_cli_docs.py`; `tdd` and `spec-first` gain a skill each
(`skills/test-first/SKILL.md`, `skills/writing-a-spec/SKILL.md`); `docs/CONFIGURATION.md` §3.10
rewritten around the three kinds, composition and the operator scope, new §3.12 `AGENTS.md`
and §3.13 skills; `docs/AGENT-TEAMS.md`, the quick start §6, `docs/README.md` and `mkdocs.yml`
gain the page and the two standards; `README.md` gains one feature line each for the library,
`AGENTS.md` and skills, with the agent-lane prose tests rebuilt from the README; `CHANGELOG.md`
Unreleased; CONTRIBUTING gates list; the board and roadmap closed and archived.

**Owns:** everything in the Wave 55 row. **Forbidden:** `src/` except the two skills directories.

**Acceptance:** `gen_recipe_docs.py --check` passes in CI and fails when a README line is edited
without regenerating; `mkdocs build --strict` passes; the agent lane passes; the smoke on a
throwaway `DOCKET_HOME` runs `init --recipe tdd`, `recipes list`, `config explain` showing
`AGENTS.md (default)`, and a `skill` tool call in one fake-driver turn.

**RED test:** none in the default suite (docs); the agent-lane files are rebuilt.

**Gates:** the full integrator gate list (CONTRIBUTING).

## ◆ PHASE 32 — COMPLETE (opened 2026-09-27, closed 2026-09-28): observability as configuration (D-48)

**Closed 2026-09-28; every card DONE.** Nine cards in four waves (two Sonnet
workers in parallel, then three, then three, then the integrator). Decision, the rules, the
destination table, the verdict table and the test discipline are in
[docs/adr/0014-observability-export.md](docs/adr/0014-observability-export.md).
Worker packets: [.agents/handoffs/wave-56-worker-packets.md](.agents/handoffs/wave-56-worker-packets.md).
**Activation gate met 2026-09-27:** Phase 31 closed at `3f39484`, README follow-up at `0191ffe`;
batching confirmed from the function-level ownership below; the packets file records the base
commit. **Wave 56 merged 2026-09-27:** P32-1 at `8576090`, P32-2 at `7f6a364`. **Wave 57 merged
2026-09-27:** P32-4 at `96680d9`, P32-5 at `8dc5c45` (their independent `observability-export.spec.md`
bumps from the same 1.0.0 base were reconciled by hand into one sequential 1.1.0 -> 1.2.0
history, requirements renumbered 19-43), P32-3 at `235db20` (also fixed a real regression in
the shared `tests/fakes.py::FakeDriver.run_turn`, which needed the new `trace_task_id` kwarg
once `core/dispatch.py` started passing it unconditionally). **Wave 58 merged 2026-09-27:**
P32-6 at `40166fb`, P32-7 at `db760be` and P32-8 at `f6e80bb` (P32-6/P32-7 again independently
bumped `observability-export.spec.md` from the same 1.2.0 base -- reconciled to 1.3.0 -> 1.4.0,
requirements renumbered 58-63; P32-7/P32-8 independently bumped `cli-interface.spec.md` from the
same 1.53.0 base -- reconciled to 1.54.0 -> 1.55.0). P32-8 also found a real discrepancy between
its card's literal Acceptance text and `activation_state`'s actual, already-shipped behaviour
(a disabled built-in always reports `"disabled"`, never `"needs credential"`) and implemented
against the verified live behaviour, per AGENTS.md's rule to record the discrepancy rather than
choose the convenient reading. Full gates green after each rollup (3,212 tests, 31 specs, 19/19
goldens, mypy/ruff/spec-index clean); `specs/README.md` and `CONTRIBUTING.md` re-trued. Analysis
and plan (gitignored): `internal-docs/observability-export-audit-2026-09-27.es.md`,
`internal-docs/observability-export-plan-2026-09-27.es.md`.

**Trigger (explicit request, 2026-09-27):** observability and telemetry configurable and adaptable
to standards such as OpenTelemetry or Langfuse; solid and maintainable, with enough abstraction to
add remote destinations simply; destinations as YAML like providers; Langfuse and OpenTelemetry
shipped ready, only to be authenticated; no over-sizing. Measured on `0191ffe`: `core/trace.py`
has one record shape, a closed `EVENT_TYPES` and a synchronous `subscribe` seam with one consumer
(`cli/_harness.py::_emit`); no event exists for the model call (usage goes to the session record
in `_TurnState.call_backend_and_handle_response`; `edges/adapters/llm.py::complete` measures no
latency; `ChatResponse` carries neither model nor latency); `trace_ingest` appends past the seam;
`taskId` rides only in dispatch payloads; telemetry is configured by five environment variables
while every other surface is a `kind:` document (`core/config_docs.py::KINDS`); the store has no
owning spec. D-24 (ADR 0005) cut the OpenTelemetry SDK and D-25's two-runtime trigger has not
fired: ADR 0014 records what changed and keeps the SDK cut.

**Test rule (ADR 0014):** one RED behavioural test per card in the module's `SUBJECT` file or the
integration file the card names; a negative case only for a fail-closed property (P32-2, P32-6,
P32-7); existing tests, goldens and specs are the no-change oracle; no agent-lane tests, no
guards, no new test files unless the card names one; goldens change only where a card lists the
lines. **No worker probes a real vendor host or a real model endpoint**; every HTTP target in a
test is a local `http.server` the test starts. The integrator performs the external verification
(P32-9).

| Wave | Cards | Hot file and function ownership |
| --- | --- | --- |
| 56 | P32-1 ∥ P32-2 | `core/llm.py::ChatResponse`, `edges/adapters/llm.py::OpenAIChatClient.complete`, `core/agent_loop.py::_TurnState.call_backend_and_handle_response` + new `_trace_llm_call`, `core/trace.py::EVENT_TYPES` (one entry), `cli/_trace.py::_render_event`, new `specs/functional/trace-store.spec.md` → P32-1; `core/telemetry.py` (new: `Span`, `SpanEvent`, `ProjectionState`, `project`, `ExportPolicy`, `DEFAULT_EVENTS`), `tests/unit/core/test_telemetry.py` (new), `tests/fixtures/traces/` (new), new `specs/functional/observability-export.spec.md` → P32-2 |
| 57 | P32-3 ∥ P32-4 ∥ P32-5 | `core/trace.py::trace_event` (+`task_id`) + `::trace_ingest` (notify), `core/agent_loop.py::run_agent_turn`/`_TurnState` (`trace_task_id` threaded to the `_trace_*` helpers), `edges/adapters/docket_runtime.py::run_turn` (one kwarg), `core/dispatch.py` (the one call site that passes it) → P32-3; `core/exporter.py` (new), `config.py` (five constants + `no_export`), `core/config_docs.py::KINDS`/`_MODEL_FOR_KIND`, `docs/contracts/config-v1/exporter.schema.json` + `src/docket/templates/schemas/` copy, `src/docket/templates/exporters/` (new), `tests/unit/core/test_exporter.py` (new) → P32-4; `edges/adapters/exporters/otlp_http.py` (new; `encode`, `OtlpHttpSink`, `probe`), `tests/unit/edges/test_otlp_http.py` (new), `tests/fixtures/otlp-v1/` (new) → P32-5 |
| 58 | P32-6 ∥ P32-7 ∥ P32-8 | `core/telemetry.py::Pipeline` + module-level `start`/`flush`/`close`/`health` (new), `edges/adapters/exporters/__init__.py` (`_DIALECTS`, `sink_for`), `edges/adapters/docket_runtime.py::run_turn` (lazy start + flush), `tests/integration/test_otlp_export.py` (new), `packages/docket-runtime/hatch_build.py` closure → P32-6; `cli/_exporters.py` (new), `cli/__init__.py` (one command block), `cli/_keys.py::prompt_and_store` (extracted), `cli/_config.py::_explain` (`exporters` key + renderer line), `cli/_doctor.py::_check_exporters` (new), `core/exporter.py::enable_exporter`/`disable_exporter` (new), `completions` golden, `docs/commands.md` → P32-7; `core/pod_apply.py::summarize_recipe`/`plan_apply`/`_MANIFEST_KEYS`/`_export_manifest`, `core/config_docs.py::PodDocument.exporters`, `pod.schema.json` (both copies), `cli/_pod.py` (the apply header renderer), `cli/_recipes.py::show` → P32-8 |
| 59 | P32-9 | integrator: `specs/README.md`, `docs/CONFIGURATION.md`, `docs/SECURITY-SIMPLE.md`, `docs/README.md`, `mkdocs.yml`, `README.md`, `CHANGELOG.md`, `tests/fixtures/traces/` (real capture), the external verification, rollups, archive |

Every card follows the §"How to use this board" definition of done.

### P32-1 — the model call is a trace event

**Status:** DONE (2026-09-27, `8576090`) · **Size:** M · **Wave:** 56 · **Spec:** new `specs/functional/trace-store.spec.md` → 1.0.0 (the record shape, `EVENT_TYPES` with `llm_call`, redaction, `subscribe`, `trace_ingest`, retention — the owner the store never had; Status "Implemented and live"), `agent-loop.spec.md` → 1.25.0 ("Tracing": one `llm_call` per backend request; Module API: `ChatResponse.latency_ms`, `.model`, `.provider`), `harness-mode.spec.md` → 1.1.2 (event table: `llm_call` appears on stdout like any record; additive)

**Trigger:** `core/trace.py::EVENT_TYPES` has no event for the model call; usage is persisted
only through `append_messages(..., usage=)` in `_TurnState.call_backend_and_handle_response`;
`edges/adapters/llm.py::OpenAIChatClient.complete` uses `timeout` and measures nothing;
`ChatResponse` has `usage` but no `model`/`latency_ms`. OpenTelemetry GenAI and Langfuse both
need one "generation" per request with model, tokens and latency.

**Goal:**
- `core/llm.py::ChatResponse` gains `model: str = ""`, `provider: str = ""`, `latency_ms: int = 0`.
  `OpenAIChatClient.complete` fills all three on every return path (success, HTTP error,
  timeout, transport error): `model`/`provider` from its `Endpoint`, `latency_ms` from
  `time.perf_counter()` around the request.
- `core/trace.py::EVENT_TYPES` gains `"llm_call"`.
- `core/agent_loop.py`: a new module-level `_trace_llm_call(project, session, role, response,
  iteration)` beside `_trace_tool_call`, called from `_TurnState.call_backend_and_handle_response`
  once per `complete()` return, before any early return. Payload: `{"model", "provider", "ok",
  "finishReason", "failureKind", "inputTokens", "outputTokens", "cachedTokens", "iteration"}`;
  `duration_ms=response.latency_ms`; **never** `cost_usd`. The compaction summariser's own call
  (`summarize_without_reentry`) is also traced, with `"purpose": "compaction"`.
- `cli/_trace.py::_render_event` renders `llm_call` on one line (`model`, `in/out` tokens,
  `ms`, and `failed: <kind>` when not ok); colour entry added.
- `docs/contracts/harness-v1/schema.json` unchanged (`event` is `additionalProperties: true`);
  the spec says so.

**Non-goals:** exporting anything; `task_id` (P32-3); changing `TokenUsage`; any dollar figure.

**Owns:** `core/llm.py::ChatResponse`; `edges/adapters/llm.py::OpenAIChatClient.complete`;
`core/agent_loop.py::_trace_llm_call` (new) + the call inside
`call_backend_and_handle_response` only; `core/trace.py::EVENT_TYPES` (one line); `cli/_trace.py`;
the three specs. **Forbidden:** `core/trace.py` beyond that line, `core/dispatch.py`,
`core/session.py`, `serve.py`, `core/telemetry.py` (P32-2).

**Acceptance:**
- Fixture: `run_agent_turn` with a fake `ChatBackend` that answers one tool call then a final
  message (the pattern in `tests/integration/test_agent_loop.py`, `rg -n "class .*Backend"`).
  Action: run the turn under a `trace.subscribe` list sink. Result: exactly two `llm_call`
  records, `iteration` 1 and 2, `inputTokens`/`outputTokens` equal to the fake's usage,
  `duration_ms` an int ≥ 0, no `cost_usd` key. Oracle: the subscribed records.
- Fixture: a fake backend whose second answer is `ChatResponse(ok=False, failure_kind="timeout")`.
  Result: the second `llm_call` has `ok: false`, `failureKind: "timeout"`; the turn result is
  unchanged from the base. Oracle: records + `AgentLoopResult`.
- `OpenAIChatClient.complete` against a local `http.server` that sleeps 50 ms: `latency_ms ≥ 50`,
  `model` = the endpoint's `model_id`. Against a closed port: `ok=False`, `latency_ms ≥ 0`.
- `docket trace <session>` on a trace holding an `llm_call` prints the one-line render.

**RED test:** `tests/integration/test_agent_loop.py` (the two-records case fails on the base:
no `llm_call` records; `SUBJECT` importable) and `tests/integration/test_llm_port.py`
(the latency case fails: no attribute `latency_ms`).

**Gates:** worker gates. Goldens: check `rg -ln "trace" tests/golden/cases`; if a `trace` render
case exists it gains one line per request — list the lines. `docs/commands.md` unchanged.

### P32-2 — a neutral span model and the projection

**Status:** DONE (2026-09-27, `7f6a364`) · **Size:** M · **Wave:** 56 · **Spec:** new `specs/functional/observability-export.spec.md` → 1.0.0 (Purpose, Scope; Requirements "Span model", "Projection", "Export policy"; Status "Draft — model and projection implemented; no exporter yet"; later cards add sections and bump)

**Trigger:** the only consumer of the trace vocabulary outside docket is the harness, which
forwards raw records. A vendor format written from records directly would put a wire format in
`core/` and re-derive pairing (`tool_call`/`tool_result` by `callId`) in every exporter.

**Goal:** `core/telemetry.py` (new; imports nothing from `edges/`, opens no socket):
- `SpanEvent(name, ts, attributes)` and `Span(trace_id, span_id, parent_id, name, start_ts,
  end_ts, status, attributes, events)` — frozen dataclasses; attribute values `str | int | bool`.
- Deterministic ids: `trace_id = sha256(session_id)[:32]`, `span_id = sha256(f"{session_id}|{kind}|{key}")[:16]`.
- `ProjectionState` (per-session open spans, keyed) and `project(record, state) -> list[Span]`
  — incremental: returns the spans **closed** by this record (a `tool_result` closes its
  `execute_tool` span; `session_end` closes the root and everything still open with `status:
  unset`), and `flush_open(state) -> list[Span]` closes the rest at flush time. Rules: `session_start`
  opens `docket.session` (root; attributes `docket.project`, `docket.role`, `docket.session_id`,
  `session.id`); `llm_call` is a complete child `gen_ai.chat` (`gen_ai.system`,
  `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`,
  `gen_ai.response.finish_reasons`, `docket.iteration`; start = `ts − duration_ms`; `status: error`
  when `ok` is false); `tool_call` opens `execute_tool <name>` (`gen_ai.tool.name`,
  `gen_ai.tool.call.id`) and `tool_result` closes it (`docket.tool.ok`, `docket.tool.blocked_by`
  when present); `hop_retry`, `rework_started`, `verdict_*`, `route_taken`, `command_step`,
  `review_rejected`, `tester_verdict_failed`, `verification_failed` are span events on the root
  named by their event type with `docket.hop`/`docket.task_id` when the payload has them; every
  other member of `EVENT_TYPES` is a span event on the innermost open span, attributes = the
  payload's scalar fields prefixed `docket.`. A record whose `event_type` is not in `EVENT_TYPES`
  is ignored, never raises.
- `ExportPolicy(events: frozenset[str] | None, payload: Literal["metadata","full"], payload_max_chars: int)`
  with `DEFAULT_EVENTS` (session_start, session_end, llm_call, tool_call, tool_result,
  guardrail_check, guardrail_block, approval_*, budget_*, error, hop_retry, verdict_*,
  rework_started, review_rejected, route_taken, command_step, verification_failed,
  tester_verdict_failed, reviewer_verdict_unparseable, stale_claim, paused_refused,
  run_cancelled) and `policy.admit(record) -> dict | None`: `None` when the event type is not
  admitted; otherwise the record with its payload reduced — `metadata` keeps scalar
  non-content keys (ids, names, counts, booleans, `tool`, `callId`, `model`, `hop`, `verdict`,
  `finishReason`, `exitCode`…) and drops `arguments`, `text`, `content`, `output`, `result`,
  `prompt`, `messages`, `summary`; `full` keeps them truncated to `payload_max_chars`. Pure, O(1).

**Non-goals:** any wire encoding (P32-5); the queue/thread (P32-6); `task_id` on the record
(P32-3 — read it from `record.get("task_id", "")` so nothing changes later).

**Owns:** `core/telemetry.py` (new), `tests/unit/core/test_telemetry.py` (new, `SUBJECT =
docket.core.telemetry`), `tests/fixtures/traces/dispatch-3-hops.jsonl` (new; hand-built to
`trace-store.spec.md`'s record shape with the P32-1 `llm_call` payload keys — the integrator
replaces it with a real capture in P32-9 and this card's assertions must still hold), the spec.
**Forbidden:** everything else.

**Acceptance:**
- Fixture: the JSONL fixture (one session: `session_start`, two `llm_call`, one
  `tool_call`+`tool_result`, one `guardrail_block`, `session_end`). Action: feed every record to
  `project` then `flush_open`. Result: one root `docket.session`, two `gen_ai.chat` children
  with `gen_ai.usage.input_tokens` from the payload, one `execute_tool read` with
  `docket.tool.ok: true`, the `guardrail_block` as a span event on the root; every `parent_id`
  refers to a span in the output; ids identical on a second run. Oracle: the dataclasses.
- Every member of `core.trace.EVENT_TYPES` fed as a minimal record produces no exception and
  either a span or a span event (the coverage test; fails when a new event type is added
  without a rule).
- Negative: `ExportPolicy(payload="metadata").admit(tool_call record with arguments)` returns a
  record whose payload has no `arguments`; `payload="full"` keeps it truncated to
  `payload_max_chars`; a `prompt_composed` record is `None` under `DEFAULT_EVENTS`.

**RED test:** `tests/unit/core/test_telemetry.py` (the file does not exist on the base; the
import fails). **Gates:** worker gates; no goldens; `comment_lint` on the new module.

### P32-3 — `task_id` on the record; the ingestion bridge notifies the seam

**Status:** DONE (2026-09-27, `235db20`) · **Size:** S · **Wave:** 57 (after the Wave 56 rollup) · **Spec:** `trace-store.spec.md` → 1.1.0 (record gains optional `task_id`; `trace_ingest` MUST notify subscribers), `pod-dispatch.spec.md` → 6.23.0 (hop records carry the task id), `serve-read-api.spec.md` → 2.13.2 (`/traces` lines may carry `task_id`; additive)

**Trigger:** `core/dispatch.py` passes `context={"taskId": ...}` into the hop and
`docket_runtime.py::run_turn` receives `trace_project`/`trace_session_key` but no task id, so
a record's task is recoverable only from some payloads; `core/trace.py::trace_ingest` calls
`_append` directly, so a subscriber never sees ingested `tool_call`/`tool_result` records.

**Goal:**
- `core/trace.py::trace_event(..., task_id: str = "")` writes `"task_id"` only when non-empty
  (older readers unaffected). `trace_ingest` builds its records and passes each through
  `_notify_subscribers` before `_append` (ingested records carry `payload.source: "ingested"`
  already).
- `core/agent_loop.py::run_agent_turn(..., trace_task_id: str = "")`; `_TurnState` stores it and
  every `_trace_*` helper (including P32-1's `_trace_llm_call`) passes it through.
- `edges/adapters/docket_runtime.py::run_turn(..., trace_task_id: str | None = None)` forwards it;
  the one dispatch call site that already passes `trace_project=ctx.project` passes
  `trace_task_id=ctx.task_id`.

**Non-goals:** a span/parent id on the record (ids are derived in `core/telemetry.py`);
changing the ingest index or offsets.

**Owns:** `core/trace.py::trace_event` + `::trace_ingest`; `core/agent_loop.py::run_agent_turn`
signature, `_TurnState` field, the `_trace_*` helpers' one extra argument;
`edges/adapters/docket_runtime.py::run_turn` signature + forwarding; `core/dispatch.py` (the one
call site only); the three specs. **Forbidden:** `core/dispatch.py` beyond that line,
`core/telemetry.py`, `core/exporter.py`, `serve.py`.

**Acceptance:**
- Fixture: a pod dispatch against the fake driver (`tests/integration/test_dispatch.py`).
  Action: one hop. Result: every record of that hop's trace carries `task_id` equal to the
  claimed task's id; a record written by `trace_event` with no `task_id` has no such key. Oracle:
  the JSONL lines.
- Fixture: a session log the driver can ingest (`tests/unit/core/test_trace.py::*ingest*`).
  Action: `trace_ingest(project)` under `trace.subscribe(list.append)`. Result: the sink received
  every ingested record, in file order, before they were appended. Oracle: the list.

**RED test:** `tests/integration/test_dispatch.py` (the `task_id` case fails: key absent) and
`tests/unit/core/test_trace.py` (the ingest-notifies case fails: sink stays empty).
**Gates:** worker gates; no goldens.

### P32-4 — `kind: exporter`: the document, the catalog, the built-ins

**Status:** DONE (2026-09-27, `96680d9`) · **Size:** M · **Wave:** 57 · **Spec:** `observability-export.spec.md` → 1.1.0 (new sections "Exporter documents", "Catalog and scopes", "Activation state", "Health file"), `config-format.spec.md` → 1.4.0 (`exporter` joins the envelope kinds), `workspace-structure.spec.md` → 1.15.0 (`docket-exporters.json`, `exporters-health.json`)

**Trigger:** telemetry is configured by five environment variables (`TRACES_DIR`,
`DOCKET_NO_TRACE`, `TRACE_RETENTION_DAYS`, `AUDIT_LOG_MAX_BYTES`, `METRICS_WINDOW`) and nothing
else; `core/config_docs.py::KINDS` is `role, pipeline, policy, pod, provider`. The request asks
for destinations as YAML like providers, with Langfuse and OpenTelemetry shipped ready.

**Goal:** `core/exporter.py` (new), a deliberate copy of `core/provider.py`'s shape:
- `ExporterSpec` (Pydantic, `populate_by_name`): `kind: Literal["exporter"]`, `name`
  (`^[a-z0-9][a-z0-9-]*$`), `dialect: Literal["otlp-http"]`, `endpoint: str` (http/https),
  `auth: ExporterAuth` (`type: bearer|header|basic|none`, `header` required for `header`,
  `credentials: list[str]` names `^[A-Z][A-Z0-9_]*$`; `basic` requires exactly two names,
  user then password; `bearer`/`header` exactly one; `none` zero), `headers: dict[str,str]`
  (reserved names refused as in provider), `resource: dict[str,str]` (default
  `{"service.name": "docket"}`), `aliases: dict[str,str]`, `events: "default" | "all" | list[str]`
  (each a member of `core.trace.EVENT_TYPES`), `payload: Literal["metadata","full"] = "metadata"`,
  `payloadMaxChars: int = 2000`, `enabled: bool = False`, `note: str = ""`. A credential value
  in a document (a field matching `^[A-Za-z0-9/_\-+.]{20,}$` where a name is expected) is
  refused naming the field.
- `load_exporter_document(path)`, `Catalog` (built-in `config.EXPORTER_TEMPLATES_DIR` + global
  `config.EXPORTERS_FILE` through `edges/store.py`, nearest-wins, `source_of(name)`),
  `load_catalog`, `save_exporter`, `delete_exporter` (refuses a built-in name that has no global
  entry), `_with_inherited_identity` (a global entry under a built-in's name inherits every
  field it does not set), `resolve_credentials(spec) -> tuple[list[str], str]` (values in
  declaration order via `core/secrets.py`, plus the source label), `load_enabled_exporters()`,
  `export_exporter(name) -> str` (YAML, no values).
- `ExporterState = Literal["enabled","needs credential","disabled","unreachable"]` and
  `activation_state(spec, health) -> tuple[ExporterState, list[str]]` (the missing credential
  names), pure; `unreachable` when enabled and the health file's `lastError` is newer than
  `lastOk`.
- `verify_endpoint(spec, probe: ProbeResult) -> ExporterVerification` (pure, same table as the
  provider's: transport failure → unreachable; 401/403 → credential warning; 2xx → ok; other →
  warning naming the status). `ProbeResult` here is a plain dataclass (`status`, `error`) so this
  module imports nothing from `edges/`.
- Health file: `config.EXPORTERS_HEALTH_FILE` (`exporters-health.json`), documented shape
  `{"<name>": {"exported": int, "dropped": int, "failed": int, "lastOk": ts, "lastError": str,
  "lastErrorAt": ts}}`; `read_health()` here, writes happen in P32-6 through `store.py`.
- `config.py`: `EXPORTERS_FILE`, `EXPORTER_TEMPLATES_DIR`, `EXPORTERS_HEALTH_FILE`,
  `EXPORT_QUEUE_MAX` (1000), `EXPORT_FLUSH_TIMEOUT_S` (5.0), `no_export()` (`DOCKET_NO_EXPORT=1`,
  same shape as `no_trace`).
- `core/config_docs.py`: `KINDS` gains `"exporter"`, `_MODEL_FOR_KIND["exporter"] = ExporterSpec`;
  `docket validate <file>` accepts an exporter document; `scripts/gen_config_schemas.py` emits
  `exporter.schema.json` into both copies.
- `src/docket/templates/exporters/`: `01-otel-collector.yaml` (`http://127.0.0.1:4318/v1/traces`,
  `auth: none`, `payload: full`, note: stays on this host), `02-jaeger.yaml` (same endpoint
  shape, `payload: metadata`), `03-langfuse.yaml` (`https://cloud.langfuse.com/api/public/otel/v1/traces`,
  `auth: basic`, `[LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY]`, `aliases: {"session.id":
  "langfuse.session.id"}`, note: EU cloud; override `endpoint` for US or self-hosted),
  `04-honeycomb.yaml` (`https://api.honeycomb.io/v1/traces`, `auth: header`, header
  `x-honeycomb-team`, `[HONEYCOMB_API_KEY]`), `05-phoenix.yaml` (`http://127.0.0.1:6006/v1/traces`,
  `auth: none`). All `enabled: false`. Every file validates with `docket validate`.

**Non-goals:** the wire (P32-5); the queue and the health writer (P32-6); `enable`/`disable`
and the CLI (P32-7).

**Owns:** `core/exporter.py` (new), `config.py` (the constants and `no_export`),
`core/config_docs.py` (the two entries), the schema (both copies), `templates/exporters/`
(new), `tests/unit/core/test_exporter.py` (new, `SUBJECT = docket.core.exporter`), the three
specs. **Forbidden:** `core/provider.py`, `cli/`, `edges/adapters/`, `core/telemetry.py`.

**Acceptance:**
- Fixture: the five templates. Action: `load_catalog()` in a fresh `DOCKET_HOME`. Result: five
  specs, `source_of` = `builtin` for each, `activation_state` = `disabled` for all; with
  `LANGFUSE_PUBLIC_KEY` stored but the secret key absent and a global `{name: langfuse, enabled:
  true}` entry: `("needs credential", ["LANGFUSE_SECRET_KEY"])`; with both stored: `enabled`.
  Oracle: the dataclasses and the state tuple.
- Fixture: a global document `{kind: exporter, name: langfuse, enabled: true, endpoint:
  https://lf.internal/api/public/otel/v1/traces}`. Action: `load_catalog().get("langfuse")`.
  Result: `endpoint` overridden, `auth`/`aliases`/`resource` inherited from the built-in,
  `source_of` = `global`.
- Negative: a document with `credentials: ["pk-lf-<20 chars>"]` is refused naming
  `auth.credentials`; `dialect: otlp-grpc` is refused listing `otlp-http`; `events: [nope]` is
  refused naming the event.
- `docket validate src/docket/templates/exporters/03-langfuse.yaml` prints `ok`.

**RED test:** `tests/unit/core/test_exporter.py` (file absent on the base). **Gates:** worker
gates including `gen_config_schemas.py --check`; no goldens.

### P32-5 — the `otlp-http` dialect

**Status:** DONE (2026-09-27, `8dc5c45`) · **Size:** M · **Wave:** 57 · **Spec:** `observability-export.spec.md` → 1.2.0 (new section "The otlp-http dialect": encoding rules, auth, timeout, retry, the wire golden)

**Trigger:** no module in docket knows OTLP; D-19 rents protocols through one adapter module
each (`edges/adapters/llm.py` for chat completions) and the runtime library allows no new
dependency.

**Goal:** `edges/adapters/exporters/otlp_http.py` (new; the **only** module that knows the OTLP
JSON mapping; stdlib `urllib` and `json` only), with `edges/adapters/exporters/__init__.py`
holding only the package docstring (P32-6 adds `_DIALECTS`/`sink_for`):
- `encode(spans: Sequence[Span], *, resource: Mapping[str,str], aliases: Mapping[str,str]) -> dict`
  → `{"resourceSpans": [{"resource": {"attributes": [...]}, "scopeSpans": [{"scope": {"name":
  "docket", "version": <docket version>}, "spans": [...]}]}]}`; each span: `traceId`/`spanId`/
  `parentSpanId` hex strings, `name`, `kind` 1 (INTERNAL) or 3 (CLIENT) for `gen_ai.chat`,
  `startTimeUnixNano`/`endTimeUnixNano` as **decimal strings**, `attributes` as a list of
  `{"key", "value": {"stringValue"|"intValue"(string)|"boolValue"}}`, `events` with
  `timeUnixNano`, `status` `{"code": 1|2}` (`unset` → no status). `aliases` duplicates an
  attribute under the alias key (never renames). Deterministic key order (sorted attributes).
- `OtlpHttpSink(endpoint, auth_header: tuple[str,str] | None, headers, resource, aliases,
  timeout_s=5.0, clock=time.monotonic, opener=urllib.request.urlopen)` with
  `emit(spans) -> SinkResult(accepted: int, status: int | None, error: str, retry_after_s: float | None)`
  and `close()`. Auth: `bearer` → `Authorization: Bearer <v>`; `basic` → `Authorization: Basic
  base64(user:pass)`; `header` → `<name>: <v>`; the sink receives the already-resolved header
  pair, never credential names. One retry only on 429/502/503/504, sleeping `min(Retry-After,
  DISPATCH_RETRY_MAX_WAIT_S)` (default 1 s without a header); a 4xx other than 429 is not
  retried and reports `accepted 0`. A transport failure is `status None`. Never raises.
- `probe(endpoint, auth_header, headers, timeout_s) -> ProbeResult(status, error)`: POSTs
  `{"resourceSpans": []}`.
- `tests/fixtures/otlp-v1/dispatch-3-hops.json`: `encode()` of P32-2's projected fixture,
  committed; the unit test compares byte-for-byte (`json.dumps(sort_keys=True, indent=2)`).

**Non-goals:** any queue/thread; reading `ExporterSpec` (P32-6's `sink_for` maps spec →
constructor); protobuf.

**Owns:** `edges/adapters/exporters/__init__.py` (docstring only), `edges/adapters/exporters/
otlp_http.py` (new), `tests/unit/edges/test_otlp_http.py` (new, `SUBJECT =
docket.edges.adapters.exporters.otlp_http`), `tests/fixtures/otlp-v1/` (new), the spec section.
**Forbidden:** `core/`, `cli/`, `edges/adapters/llm.py`.

**Acceptance:**
- Fixture: P32-2's projected spans (build them in the test from
  `tests/fixtures/traces/dispatch-3-hops.jsonl` through `core.telemetry.project`). Action:
  `encode`. Result: byte-identical to the golden; a `gen_ai.chat` span has `kind: 3`,
  `gen_ai.usage.input_tokens` as `{"intValue": "<n>"}`, and `langfuse.session.id` present when
  `aliases` maps it. Oracle: the golden file.
- Fixture: a local `http.server` that records requests and answers 200. Action: `emit`. Result:
  one POST, `Content-Type: application/json`, `Authorization: Basic <base64>` for a basic pair,
  body parses back to the encoded dict; `accepted == len(spans)`.
- Fixture: the server answers 429 with `Retry-After: 1` then 200. Result: exactly two POSTs,
  `accepted` full, the sleep observed through the injected clock is 1 s. Answers 400: one POST,
  `accepted 0`, `status 400`. Closed port: `status None`, `error` non-empty, no exception.

**RED test:** `tests/unit/edges/test_otlp_http.py` (absent on the base). **Gates:** worker
gates; no goldens (the OTLP golden is a fixture, not a CLI golden).

### P32-6 — the pipeline, wired where turns run

**Status:** DONE (2026-09-27, `40166fb`) · **Size:** M · **Wave:** 58 (after the Wave 57 rollup) · **Spec:** `observability-export.spec.md` → 1.3.0 (new sections "Pipeline" and "Wiring"; Status "Implemented — awaiting external verification (P32-9)"), `agent-loop.spec.md` → 1.26.0 (`DocketDriver` conformance: `run_turn` starts export lazily and flushes on return; zero enabled exporters change nothing)

**Trigger:** the fifth unwired-machinery instance (CLAUDE.md) is machinery with a writer, a CLI
reader and no consumer on the live path. This card is the consumer: without it P32-2/4/5 are
that shape again.

**Goal:**
- `core/telemetry.py::Pipeline(sink: SpanSink, policy: ExportPolicy, *, queue_max, batch_max=100,
  batch_wait_s=1.0, clock)`: `SpanSink` is a `Protocol` (`emit(spans) -> SinkResult`, `close()`);
  `offer(record)` runs `policy.admit` and `project` in the caller's thread and puts closed spans
  on a `queue.Queue(maxsize=queue_max)` with `put_nowait` — on `queue.Full` increments
  `dropped` and returns; one daemon thread drains in batches and calls `sink.emit`, adding
  `accepted` to `exported` and the rest to `failed` with `last_error`; `flush(timeout_s)` drains
  what is queued plus `flush_open(state)` and waits at most `timeout_s`; `close()` flushes and
  joins. Never raises out of `offer`/`flush`/`close`. `stats() -> PipelineStats`.
- Module-level registry: `start(specs: Sequence[ExporterSpec], sink_for) -> int` (builds one
  `Pipeline` per enabled spec whose credentials resolve, subscribes **one** fan-out sink through
  `core.trace.subscribe`'s non-context form — add `trace.add_subscriber(sink) -> Callable[[], None]`
  beside `subscribe`, same lock, same semantics; returns the count started; a second `start` is a
  no-op), `flush(timeout_s)`, `close()`, `health() -> dict` (the P32-4 shape). `start` with zero
  specs subscribes nothing and starts no thread. `no_export()` makes `start` return 0.
- `edges/adapters/exporters/__init__.py`: `_DIALECTS = {"otlp-http": _otlp_sink}` and
  `sink_for(spec, credential_values) -> SpanSink` (builds the auth header pair from
  `spec.auth.type` and the resolved values; raises `ValueError` for an unknown dialect).
- `edges/adapters/docket_runtime.py::run_turn`: before the turn, if the registry is not started,
  `telemetry.start(load_enabled_exporters(), sink_for)`; after the turn (every return path),
  `telemetry.flush(EXPORT_FLUSH_TIMEOUT_S)` and `store.write_json(EXPORTERS_HEALTH_FILE, telemetry.health())`
  through `edges/store.py`; `atexit.register(telemetry.close)` once.
- `packages/docket-runtime/hatch_build.py`: `core/telemetry.py`, `core/exporter.py` and
  `edges/adapters/exporters/` join the measured closure (P31-6's lesson: a module on the turn
  path missing from the wheel).

**Non-goals:** the CLI (P32-7); changing `serve.py` or `cli/_harness.py` (both reach `run_turn`).

**Owns:** `core/telemetry.py::Pipeline`, `PipelineStats`, `start`/`flush`/`close`/`health`
(new); `core/trace.py::add_subscriber` (new, beside `subscribe`); `edges/adapters/exporters/
__init__.py`; `edges/adapters/docket_runtime.py::run_turn` (the start/flush/health lines only);
`packages/docket-runtime/hatch_build.py`; `tests/integration/test_otlp_export.py` (new); the two
specs. **Forbidden:** `core/telemetry.py::project`/`ExportPolicy` internals, `core/exporter.py`,
`cli/`, `otlp_http.py`.

**Acceptance:**
- Fixture: a fresh `DOCKET_HOME` with a global exporter document `{name: local, dialect:
  otlp-http, endpoint: http://127.0.0.1:<port>/v1/traces, auth: none, enabled: true, payload:
  full}` and a local `http.server` recording bodies; a `DocketDriver` with the fake backend from
  `tests/integration/test_docket_driver.py`. Action: `run_turn`. Result: the server received ≥ 1
  POST whose body has a `gen_ai.chat` span with `gen_ai.usage.input_tokens` > 0 and a
  `docket.session` root; `exporters-health.json` shows `local.exported ≥ 2`, `failed 0`. Oracle:
  the recorded bodies and the health file.
- Negative (fail-closed on the turn): the server accepts the connection and never answers.
  Result: `run_turn` returns within `EXPORT_FLUSH_TIMEOUT_S + turn time` (assert `< 2×` the
  no-exporter duration measured in the same test), `AgentLoopResult` identical to the
  no-exporter run, health shows `failed ≥ 1` or `dropped ≥ 1` with `lastError` set.
- Zero enabled exporters: `run_turn` starts no thread (`threading.enumerate()` unchanged) and
  registers no subscriber (`trace._SUBSCRIBERS` empty).
- `DOCKET_NO_EXPORT=1` with the enabled document: no POST, health untouched.

**RED test:** `tests/integration/test_otlp_export.py` (absent on the base). **Gates:** worker
gates; `tests/agent/release/test_runtime_adapter_public_truth.py` if the closure list is asserted
there (`rg -n "skills.py" tests/agent packages/docket-runtime`).

### P32-7 — `docket exporters`: enable by authenticating

**Status:** DONE (2026-09-27, `db760be`) · **Size:** M · **Wave:** 58 · **Spec:** `observability-export.spec.md` → 1.4.0 (new section "Activation": `enable`/`disable`/`test`, the audit entries, the TTY rule), `cli-interface.spec.md` → 1.54.0 (`docket exporters list|show|enable|disable|test|add|remove|export`; `config explain` `exporters` lines; `doctor` check), `cli-json-shapes.spec.md` → 1.15.0 (`exporters list --json`, `config explain --json` `exporters`)

**Trigger:** the request's experience is "the YAML exists, I only put the key". `cli/_keys.py::
_keys_add` holds the hidden prompt inline; `cli/_provider.py::_run_add` shows the verify-then-
register flow; `cli/_config.py::_explain` names the provider and credential source; nothing does
any of that for an exporter.

**Goal:**
- `cli/_keys.py::prompt_and_store(name) -> bool` extracted from `_keys_add` (hidden input,
  format warning, 0600 store, meta touch); `_keys_add` calls it; behaviour byte-identical.
- `cli/_exporters.py::run_exporters(action, args) -> int`, registered in `cli/__init__.py` exactly
  as `cmd_recipes` is (one block): `list [--json]` (NAME, DIALECT, STATE, CREDENTIALS, SCOPE;
  state from `activation_state`), `show <name>` (effective document, source, state, health
  counters), `enable <name> [--endpoint URL] [--payload metadata|full] [--events ...]
  [--no-verify]` → for each missing credential: if `sys.stdin.isatty()` call `prompt_and_store`,
  else print `docket keys add <NAME>` for each and exit 1 writing nothing; then `probe` through
  `edges.adapters.exporters.otlp_http.probe` (or the dialect's), `verify_endpoint`; a transport
  failure exits 1 and writes nothing unless `--no-verify`; success writes **only** `{kind, name,
  enabled: true, <overrides given>}` via `core/exporter.py::enable_exporter(name, overrides)`
  (new; global entry, inheriting identity), prints the source and `payload`, and when `payload`
  is `full` prints `tool arguments and results leave this host`; `disable <name>`
  (`disable_exporter`, keeps keys); `test <name>` (probe + classification, exit 0/1); `add
  <file>` (a full document, verified like `enable`); `remove <name>` (global entries only; a
  built-in name without a global entry says so and exits 1); `export <name>`. Audit:
  `exporter.enabled` / `exporter.disabled` / `exporter.added` / `exporter.removed`, detail
  `name=<n> payload=<p> endpoint=<url>`, never a value.
- `cli/_config.py::_explain`: `"exporters": [{name, dialect, state, scope, credentialSource,
  payload, exported, dropped, failed, lastError}]` and one rendered line per exporter under a
  `Exporters:` header (`none enabled` when empty).
- `cli/_doctor.py::_check_exporters()`: warns per enabled exporter whose health has `failed >
  0` since `lastOk`, names `docket exporters test <name>`; ok line otherwise.
- `completions` golden gains `exporters`; `docs/commands.md` regenerated.

**Non-goals:** per-pod scope; any change to `core/telemetry.py` or the wire; `keys setup`
walking exporters (a later card if asked).

**Owns:** `cli/_exporters.py` (new), `cli/__init__.py` (one command block), `cli/_keys.py::
prompt_and_store` (+ the call in `_keys_add`), `cli/_config.py::_explain` (the key + renderer
line), `cli/_doctor.py::_check_exporters` (+ its call in `run_doctor`), `core/exporter.py::
enable_exporter`/`disable_exporter` (new functions only), `tests/golden/cases/completions*`,
`docs/commands.md`, `tests/integration/test_exporters_cli.py` (new), the three specs.
**Forbidden:** `core/exporter.py` beyond the two functions, `core/telemetry.py`,
`edges/adapters/docket_runtime.py`, `cli/__init__.py::cmd_pod`.

**Acceptance:**
- Fixture: fresh `DOCKET_HOME`, no keys, stdin not a TTY. Action: `docket exporters enable
  langfuse`. Result: exit 1, output names `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` with
  the `docket keys add` command, `docket-exporters.json` absent. Oracle: exit code + file.
- Fixture: both keys stored, a local server answering 200 at `--endpoint`. Action: `enable
  langfuse --endpoint http://127.0.0.1:<port>/v1/traces`. Result: exit 0; the global file holds
  exactly `{kind: exporter, name: langfuse, enabled: true, endpoint: <url>}`; `list` shows
  `enabled`; `read_audit()` has `exporter.enabled` with `payload=metadata`; `show langfuse`
  prints the inherited `aliases`. `disable langfuse` flips it, keys remain.
- Negative: `remove jaeger` (built-in, no global entry) exits 1 naming it as built-in.
- `docket config explain <agent> --json` carries `exporters[0].state == "enabled"`; `doctor`
  after a health file with `failed: 3, lastOk: ""` warns naming `docket exporters test langfuse`.

**RED test:** `tests/integration/test_exporters_cli.py` (absent on the base). **Gates:** worker
gates; `completions` golden regenerated with the one line listed; `gen_cli_docs.py --check`.

### P32-8 — a recipe names its destinations

**Status:** DONE (2026-09-27, `f6e80bb`) · **Size:** S · **Wave:** 58 · **Spec:** `pod-blueprints.spec.md` → 1.20.0 ("Pod manifests: apply" key set gains `exporters`; "Recipe summary" gains the names; `apply` reports state, activates nothing), `config-format.spec.md` → 1.5.0 (manifest key), `cli-interface.spec.md` → 1.55.0 (`apply` state lines; `recipes show` line)

**Trigger:** ADR 0014 rule 7: a repository can state that its team is observed in Langfuse
without carrying a credential or activating anything; `core/pod_apply.py::_MANIFEST_KEYS` is
`members, settings, pipeline, description`.

**Goal:**
- `pod.yaml` accepts `exporters: [<name>, ...]` (list of names; each must resolve in
  `core.exporter.load_catalog()` at `plan_apply` time or the plan fails naming it; a document,
  a URL or a credential-shaped string is refused naming the key). `_MANIFEST_KEYS` gains it;
  `core/config_docs.py::PodDocument.exporters: list[str] | None`; both schema copies regenerated;
  `_export_manifest` writes it when the pod's settings hold one (store it under
  `PodSettings` as a typed key `exporters` — a recorded, not configurable, key like
  `configSource`; `pod config set exporters` refused).
- `summarize_recipe` gains `exporters: tuple[str, ...]`; `render()` appends `· exporters langfuse`
  when non-empty.
- `apply` (and therefore `init --recipe`/`init` from `.docket/`) prints, after the plan, one line
  per name: `exporter langfuse: needs credential LANGFUSE_SECRET_KEY -> docket exporters enable
  langfuse` / `exporter otel-collector: enabled` / `exporter jaeger: disabled -> docket exporters
  enable jaeger`, from `activation_state`; **writes nothing** to `docket-exporters.json`.
  `recipes show` prints the same lines.

**Non-goals:** activating; per-pod routing of spans; anything in `core/telemetry.py`.

**Owns:** `core/pod_apply.py::summarize_recipe`/`RecipeSummary`/`plan_apply`/`_MANIFEST_KEYS`/
`_export_manifest`/`apply` (the state lines' data), `core/pod.py::PodSettings` (one recorded
key), `core/config_docs.py::PodDocument.exporters`, `pod.schema.json` (both copies),
`cli/_pod.py` (the shared apply header/plan renderer: the state lines), `cli/_recipes.py::show`,
`tests/unit/core/test_pod_apply.py`, the three specs. **Forbidden:** `cli/__init__.py`,
`core/exporter.py`, `cli/_exporters.py`, `templates/recipes/` (no shipped recipe names an
exporter in this phase).

**Acceptance:**
- Fixture: a recipe directory whose `pod.yaml` is `{kind: pod, name: x, exporters: [langfuse]}`;
  no keys stored. Action: `apply(plan_apply(p, dir))`. Result: every item `skip`, the pod's
  settings record `exporters: ["langfuse"]`, `docket-exporters.json` absent, and the CLI prints
  `exporter langfuse: needs credential LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY -> docket
  exporters enable langfuse`. Oracle: the settings file, the absent file, the output.
- Negative: `exporters: [{endpoint: ...}]` and `exporters: [nope]` each raise `PodApplyError`
  naming `exporters`, nothing written.
- `summarize_recipe(dir).render()` ends with `· exporters langfuse`; `docket validate <dir>`
  shows it.

**RED test:** `tests/unit/core/test_pod_apply.py` (the summary case fails: unknown key
`exporters`). **Gates:** worker gates including `gen_config_schemas.py --check`; no goldens.

### P32-9 — docs, external verification, close (integrator)

**Status:** DONE (2026-09-28, `571089b`) · **Size:** M · **Wave:** 59 (after the Wave 58 rollup) · **Spec:** `observability-export.spec.md` → 1.5.0 (Status "Implemented and live"; "External verification" records the collector's real transcripts and Langfuse's blocked status), `specs/README.md` re-trued

**Closed with one recorded discrepancy and one open item, both named in the spec's "External
verification" section rather than glossed over:**
- The card's own instruction to replace `tests/fixtures/traces/dispatch-3-hops.jsonl` with the
  real capture conflicts with that fixture's committed, deterministic assertions (exact token
  values `{120, 180}`, a `guardrail_block` event a real dispatch does not reliably produce) —
  overwriting it would break `test_telemetry.py`/`test_otlp_http.py`'s pinned literals for no
  gain, since what a real capture actually proves (real event shapes) is already confirmed
  live. The fixture and its golden are unchanged.
- `docket exporters show <name>` reports the `exported` health counter (`exported=71` in the
  live run below), not `config explain` as the card's Goal literally said — a stale detail,
  corrected in the spec.
- Langfuse's live round-trip stays open, named as blocked on the operator's own
  `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` rather than skipped silently; the real, reproducible
  non-TTY refusal transcript for both Langfuse and Honeycomb is recorded instead.

**Live proof, this machine, 2026-09-28:** a real `otel/opentelemetry-collector` container (`debug`
exporter) received a real `docket pod rack-cli dispatch` (4 hops, local llama.cpp model) after
`docket exporters enable otel-collector` — 5 `docket.session` roots, 29 `gen_ai.chat` spans with
real measured token counts, 39 `execute_tool` spans; `docket trace <session>` showed the matching
29 `llm_call` lines; `docket exporters show otel-collector` reported `exported=71 dropped=0
failed=0`. Full detail in the spec's "External verification" section.

**Goal:**
- Live proof on this machine: `otel/opentelemetry-collector` (`debug` exporter) in Docker,
  `docket exporters enable otel-collector`, one real dispatch of the `docket-dev` pod against
  the local endpoint (`DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`): the collector log shows
  `docket.session`, ≥ 1 `gen_ai.chat` with real token counts and `execute_tool` spans; `docket
  trace <session>` shows the matching `llm_call` lines; `config explain` shows `exported > 0`.
  Then `docket exporters enable langfuse` with the operator's keys and the same dispatch: the
  trace appears in Langfuse with generations. If Langfuse rejects `application/json`, record it
  and open the deferred protobuf card instead of patching inside this one.
- Replace `tests/fixtures/traces/dispatch-3-hops.jsonl` with the real capture (secrets scrubbed,
  paths generic) and regenerate `tests/fixtures/otlp-v1/` from it; P32-2's and P32-5's tests
  must pass unchanged in their assertions.
- Docs: `docs/CONFIGURATION.md` §3.14 "Export traces to OpenTelemetry or Langfuse" (the three
  `enable` transcripts, `payload` rule, `exporters:` in `pod.yaml`, the health counters);
  `docs/SECURITY-SIMPLE.md` (what leaves the host under `metadata` and `full`); `docs/README.md`,
  `mkdocs.yml`; **one** README sentence in the "gate and record" lane naming that traces can be
  sent to any OpenTelemetry or Langfuse endpoint from a YAML document; `CHANGELOG.md`;
  `docs/commands.md` regenerated; `tests/agent` rebuilt only if a pinned README sentence moved.
- Board: rollup commits, `scripts/metrics.py --check` re-measured, `split_board.py archive` of
  this section at close, ROADMAP status line and D-48 row re-trued to what shipped.

**Acceptance:** every gate in §"How to use this board" green on `main`; the two live transcripts
pasted into the spec's "External verification"; `docket exporters list` golden added.
## ◆ PHASE 33 — COMPLETE (opened 2026-09-28, closed 2026-09-28): export privacy levels (D-49)

**Opened 2026-09-28. Wave 60 merged (`1890420`, merge `a6ebd7d`); Wave 61 merged (P33-2 `80ec2e4`, P33-3 `db76762`) with the capture-to-wire seam test already in `tests/integration/test_otlp_export.py::TestCapturedContentReachesTheWire`; Wave 62 merged (P33-4 `8e7a1bf`, P33-5 `9bcaad4`); Wave 63 (P33-6) closed the phase: docs, live proof at three levels, the `tool_result` capture fix.** Six cards in four waves (one Sonnet worker, then two in
parallel, then two, then the integrator). Decision, the class and level tables, the eleven rules
and the verdict table are in [docs/adr/0015-export-privacy-levels.md](docs/adr/0015-export-privacy-levels.md).
Worker packets: [.agents/handoffs/wave-60-worker-packets.md](.agents/handoffs/wave-60-worker-packets.md).
**Activation gate met 2026-09-28:** Phase 32 closed at `5f53e52`, the Langfuse follow-up at
`940c3cd`; batching below is by function-level ownership.

**Trigger (explicit request + live evidence, 2026-09-28):** a real dispatch exported to Langfuse
rendered every generation's Input/Output as `null`/`undefined`; the operator asked for privacy
levels that are solid, configurable from the exporter's own settings, chosen consciously and
evident, so they know what they share and can turn it off. Measured at `940c3cd`: `payload:
full` changes nothing a destination renders (`gen_ai.chat`/`execute_tool` attribute sets are
closed; `core/agent_loop.py::_trace_llm_call` records no content); `payload: metadata` is a
denylist of eight key names (`core/telemetry.py::_CONTENT_KEYS`), so `approval_requested.action`
(a command line) and `error.error` (free text) already reach every enabled destination through
`_handle_generic_event`; nothing shows the operator what leaves. OTel GenAI semantic conventions
make content `Opt-In` and name the attributes; Langfuse reads those names natively.

**Spec ownership rule (the Phase 32 lesson, applied up front):** three Phase 32 merges conflicted
because parallel cards bumped the same spec from the same base. In this phase **workers add
requirements under their own new section heading in a pre-assigned number range and do not
touch `**Version**`, `**Status**` or the changelog**; the integrator bumps each spec once per
rollup. Ranges in `observability-export.spec.md` (last requirement today: 63): P33-1 64–79,
P33-2 80–87, P33-4 88–97, P33-5 98–101. P33-3 owns its sections in `trace-store.spec.md` and
`agent-loop.spec.md`.

**Test rule (ADR 0015):** one RED behavioural test per card in the module's `SUBJECT` file; a
negative case only for a fail-closed property (P33-1 canary under `minimal`, P33-3 byte-identical
record with no exporter above `minimal`, P33-4 widening off a TTY without `--yes`). Existing
tests, goldens and specs are the no-change oracle except where a card lists the change. No
worker probes a real vendor host or a real model endpoint.

| Wave | Cards | Hot file and function ownership |
| --- | --- | --- |
| 60 | P33-1 | `core/privacy.py` (new), `core/telemetry.py` (`ExportPolicy`, `project`, every `_handle_*`, `_new_root`, `capture_classes`, the one `ExportPolicy(...)` line in `start`), `tests/unit/core/test_privacy.py` (new), `tests/unit/core/test_telemetry.py`, `tests/fixtures/otlp-v1/` (two root attributes) |
| 61 | P33-2 ∥ P33-3 | `core/exporter.py::ExporterSpec` + audit detail lines, `core/telemetry.py::start` (policy from spec), `templates/exporters/*.yaml`, exporter schema (both copies), `cli/_exporters.py` + `cli/_config.py::_exporters_report` (`payload` readers only) → P33-2; `core/agent_loop.py::_trace_llm_call` + its two call sites, `cli/_trace.py::_render_event` (llm_call line only) → P33-3 |
| 62 | P33-4 ∥ P33-5 | `cli/_exporters.py` (`_run_list`, `_run_show`, `_run_enable`, `_run_add`, new `_run_privacy`), `cli/_config.py::_explain` renderer line, `cli/_doctor.py::_check_exporters`, `core/exporter.py::set_privacy` (new), `exporters list` golden → P33-4; `cli/_exporters_preview.py` (new), one `run_exporters` handler entry → P33-5 (the handler dict, usage text and `cli/__init__.py` exporters help are shared lines: the integrator reconciles) |
| 63 | P33-6 | integrator: seam test, docs, live proof at three levels, canary on the real wire, rollups, archive |

Every card follows the §"How to use this board" definition of done.

### P33-1 — what may leave is a class; the projection is an allowlist

**Status:** DONE (2026-09-28, `1890420`) · **Size:** M · **Wave:** 60 · **Spec:** `observability-export.spec.md` new sections "Privacy classes and levels" and "Allowlist projection" (requirements 64–79); requirements 11, 16 and 17 amended in place (integrator bumps the version)

**Trigger:** `core/telemetry.py::_CONTENT_KEYS` is a denylist; `_handle_generic_event` forwards
every scalar as `docket.<key>`, so `approval_requested.action` and `error.error` leave under the
default `metadata`; no handler can emit prompt/tool content at any setting.

**Goal:**
- `core/privacy.py` (new, pure data, imports nothing from `core/` but `typing`):
  `CONTENT_CLASSES = ("toolArguments", "errors", "toolResults", "completions", "prompts",
  "instructions")`; `LEVELS: dict[str, frozenset[str]]` with `minimal` = ∅, `actions` =
  {toolArguments, errors}, `conversation` = actions ∪ {toolResults, completions, prompts},
  `full` = all six; `resolve(privacy: str | None, share: Sequence[str] | None) ->
  tuple[str, frozenset[str]]` returning the label (`minimal`…`full`, or `custom` for a `share`
  list that equals no level) and the class set, raising `ValueError` on an unknown level, an
  unknown class, or both arguments given; `describe(classes) -> list[tuple[str, bool, tuple[str,
  ...]]]` (class, granted, attribute names) for the CLI.
- `core/telemetry.py`: `ExportPolicy(events, classes: frozenset[str] = frozenset(),
  label: str = "minimal", content_max_chars: int = 4000)`; `admit` filters by event only and
  never rewrites the payload. `project(record, state, policy=MINIMAL_POLICY)` threads the policy
  to handlers; `ATTRIBUTE_CLASSES: dict[str, str]` maps every attribute any handler can emit to
  `structure` or one content class, and one helper (`_granted(policy, cls)`) is the only way a
  content attribute is set. `_handle_tool_call` adds `gen_ai.tool.call.arguments` (toolArguments);
  `_handle_tool_result` adds `gen_ai.tool.call.result` from `text`/`output` (toolResults);
  `_handle_llm_call` adds `gen_ai.input.messages`, `gen_ai.output.messages`,
  `gen_ai.system_instructions` from the payload keys `inputMessages`, `outputMessages`,
  `systemInstructions` (written by P33-3; read defensively, absent today) and always
  `docket.instructions.sha256` when `systemInstructionsSha256` is present. Input messages are
  filtered **per part** (ADR 0015 rule 3): a `tool` role turn needs toolResults, an assistant
  `tool_call` part's arguments need toolArguments, a `system` turn needs instructions; a withheld
  part becomes `{"type": "withheld", "class": "<class>"}`. Every text part and every content
  attribute is cut to `content_max_chars` with the suffix `…[truncated <n> chars]`, JSON
  structure kept; message attributes are JSON strings.
- `_handle_generic_event` forwards only the keys in a per-event table `_STRUCTURAL_KEYS`
  (derive it from the call sites: `guardrail_*` → `hook`, `policy`, `action`; `approval_*` →
  `token`; `error` → `run`, `source`; budget/stale/paused/cancel events → their counters and
  ids; unlisted keys drop). `approval_requested.action` becomes `docket.approval.action`
  (toolArguments); `error.error` becomes `docket.error.message` (errors).
- `_new_root` gains `docket.privacy` (the policy label) and `docket.privacy.classes`
  (comma-joined, sorted, `""` for minimal).
- `capture_classes() -> frozenset[str]`: the union of the classes of the started pipelines'
  policies (empty when none is started). `start` builds `ExportPolicy(events=..., classes=
  frozenset(), label="minimal")` until P33-2 wires the document — the interim state narrows,
  never widens.
- Remove `_CONTENT_KEYS`, `_reduce_metadata`, `_reduce_full`.

**Non-goals:** the exporter document fields (P33-2); capturing model content (P33-3); any CLI.

**Owns:** `core/privacy.py` (new), `core/telemetry.py` (the functions named in the wave table),
`tests/unit/core/test_privacy.py` (new, `SUBJECT = docket.core.privacy`),
`tests/unit/core/test_telemetry.py`, `tests/fixtures/otlp-v1/dispatch-3-hops.json` (only the two
new root attributes), the spec sections. **Forbidden:** `core/exporter.py`, `core/agent_loop.py`,
`cli/`, `edges/`, `tests/fixtures/traces/`.

**Acceptance:**
- Fixture: every member of `core.trace.EVENT_TYPES` gets a synthetic record whose every string
  payload field is `CANARY-<event>-<key>`, plus an `llm_call` carrying `inputMessages` (system,
  user, assistant-with-tool-call, tool turns), `outputMessages`, `systemInstructions`, each part
  a distinct canary. Action: project and flush under each level and under each single-class
  `share`, then `otlp_http.encode`. Result: under `minimal` the encoded bytes contain no
  `CANARY-`; under each policy every canary found sits in an attribute whose
  `ATTRIBUTE_CLASSES` class is granted, and every granted class's canary is present. Oracle: a
  substring search over the encoded JSON, not the handler's own return value.
- `share: [prompts]` exports the user/assistant text of `gen_ai.input.messages` and a
  `withheld` part (class `toolResults`) in place of the tool turn's content.
- The committed wire golden differs from its base only by `docket.privacy: "minimal"` and
  `docket.privacy.classes: ""` on the root; P32-2's and P32-5's other assertions hold unchanged.
- A 10,000-character part under `content_max_chars=4000` exports as 4,000 characters plus the
  marker, and the attribute still parses as JSON.

**RED test:** the canary case in `tests/unit/core/test_telemetry.py` fails on the base
(`approval_requested`'s and `error`'s canaries appear under `metadata`). **Gates:** worker gates;
`tests/golden/run.sh verify-all` unchanged (no CLI output moves).

### P33-2 — the exporter document declares its privacy

**Status:** DONE (2026-09-28, `80ec2e4`) · **Size:** M · **Wave:** 61 (after the Wave 60 rollup) · **Spec:** `observability-export.spec.md` "Exporter documents" amended + requirements 80–87; `config-format.spec.md` (exporter fields); `workspace-structure.spec.md` only if a template path changes (integrator bumps)

**Trigger:** privacy must be configurable from the exporter's own settings (the request);
`ExporterSpec.payload`/`payloadMaxChars` no longer mean anything after P33-1.

**Goal:**
- `core/exporter.py::ExporterSpec`: `privacy: Literal["minimal","actions","conversation","full"]
  | None = None`, `share: list[str] | None = None`, `content_max_chars: int = Field(4000,
  alias="contentMaxChars", gt=0, le=100_000)`; a model validator calls `core.privacy.resolve`
  (both set → refused naming both; unknown level/class → refused naming it); `privacy_label` and
  `privacy_classes` properties (unset = `minimal`). `payload`/`payloadMaxChars` removed; a stored
  document still carrying `payload` loads as `minimal` and `legacy_fields` names it (never a wider
  level; ADR 0015 rule 7).
- Every file in `templates/exporters/` declares `privacy: minimal` (including `otel-collector`,
  whose `payload: full` goes; its `note` says why: a collector forwards). Schemas regenerated
  (`scripts/gen_config_schemas.py`, both copies).
- `core/telemetry.py::start` builds `ExportPolicy(events=..., classes=spec.privacy_classes,
  label=spec.privacy_label, content_max_chars=spec.content_max_chars)`.
- Every reader of `spec.payload` moves to `privacy_label` (`cli/_exporters.py` show/enable
  lines, `cli/_config.py::_exporters_report` key `privacy` replacing `payload`, the audit detail
  strings in `core/exporter.py`), with no new UX (P33-4 owns that).

**Non-goals:** the `privacy` command, confirmation, `SHARES`, preview (P33-4/P33-5); capture
(P33-3).

**Owns:** `core/exporter.py` (`ExporterSpec`, the audit detail lines), `core/telemetry.py::start`
(the one constructor call), `templates/exporters/*.yaml`, the exporter schema (both copies),
`cli/_exporters.py` and `cli/_config.py` (the `payload` readers only), `tests/unit/core/test_exporter.py`,
`tests/integration/test_otlp_export.py` (only where it sets `payload`), the spec text.
**Forbidden:** `core/agent_loop.py`, `core/privacy.py` (read it; return a contention note if it
needs a change), every other `core/telemetry.py` function.

**Acceptance:**
- `docket validate` accepts `privacy: conversation`, accepts `share: [toolArguments]`, refuses
  both together, refuses `privacy: everything` and `share: [secrets]`, each naming the field.
- A global document `{kind: exporter, name: langfuse, payload: full, enabled: true}` in
  `docket-exporters.json` resolves to label `minimal`, classes ∅, and `legacy_fields == ["payload"]`.
- With a local `http.server` sink and `privacy: actions`, one real `run_turn` through the fake
  backend exports a span whose attributes include `gen_ai.tool.call.arguments`; the same with the
  document at `minimal` exports none (integration, `tests/integration/test_otlp_export.py`).
- `docket exporters list` golden unchanged; every built-in validates.

**RED test:** the `privacy: actions` integration case fails on the base (policy still minimal).
**Gates:** worker gates including `gen_config_schemas.py --check`.

### P33-3 — the model call records its content when, and only when, a destination asks

**Status:** DONE (2026-09-28, `db76762`) · **Size:** M · **Wave:** 61 (after the Wave 60 rollup) · **Spec:** `trace-store.spec.md` new section "Captured content" (the three optional `llm_call` keys, the capture rule, the dedup rule); `agent-loop.spec.md` "Tracing" amended; `harness-mode.spec.md` event row note (additive) (integrator bumps)

**Trigger:** `core/agent_loop.py::_trace_llm_call` records model, provider, tokens and latency,
never the conversation, so no level can show Langfuse a generation's Input/Output.

**Goal:**
- `_trace_llm_call(..., messages: Sequence[ChatMessage] | None = None)`; both call sites
  (`_TurnState.call_backend_and_handle_response` and the compaction summarizer) pass the exact
  list sent to `backend.complete`. With `granted = telemetry.capture_classes()`:
  `completions` ∈ granted → `outputMessages` (the reply: text parts + `tool_call` parts with id,
  name, arguments); `prompts` ∈ granted → `inputMessages` without the system turn (OTel shape:
  `{"role", "parts": [...]}`; tool turns as `tool_call_response` parts; P33-1 withholds the parts
  of classes an exporter was not granted); `instructions` ∈ granted → `systemInstructions` (the system
  turn's text) on the session's first call and whenever its SHA-256 differs from the last one
  recorded for that trace key, and `systemInstructionsSha256` whenever any content is captured.
  Parts cut to 4,000 characters here too (the bound on disk); the per-exporter cut is P33-1's.
- Empty `granted` → the payload is byte-identical to today's (no key added, no JSON reordering).
- `cli/_trace.py::_render_event`: an `llm_call` line with captured content ends in
  `+content(<keys>)`; nothing changes otherwise.

**Non-goals:** filtering per exporter (P33-1 does it at projection); any exporter field (P33-2).

**Owns:** `core/agent_loop.py::_trace_llm_call` and its two call lines, a module-level helper for
the message shape, `cli/_trace.py::_render_event` (the `llm_call` branch), `tests/integration/test_agent_loop.py::TestLlmCallTrace`,
the three spec sections. **Forbidden:** `core/telemetry.py` (call `capture_classes()` only),
`core/exporter.py`, `edges/`, `core/session.py`.

**Acceptance:**
- With `capture_classes` returning ∅ (no pipeline started), a two-iteration turn through the
  fake backend writes `llm_call` records byte-identical to the base branch's for the same input.
- Monkeypatching `capture_classes` to `{"prompts","completions"}`: the second call's record
  holds `inputMessages` (user, assistant with a tool call, tool turn) and `outputMessages`, no
  `systemInstructions`; a secret-shaped string in a tool result arrives redacted (`redact` at
  write). With `{"instructions"}` the first call records `systemInstructions` and the second
  does not (same hash), both carry the hash.
- `docket trace <session>` shows `+content(inputMessages,outputMessages)` on those lines.

**RED test:** the `{"prompts","completions"}` case in `TestLlmCallTrace` fails on the base.
**Gates:** worker gates; the `docket trace` golden unchanged (its fixture has no content).

### P33-4 — widening is a confirmed command; the level is shown everywhere

**Status:** DONE (2026-09-28, `8e7a1bf`) · **Size:** M · **Wave:** 62 (after the Wave 61 rollup) · **Spec:** `observability-export.spec.md` new section "Privacy commands and disclosure" (88–97); `cli-interface.spec.md`, `cli-json-shapes.spec.md` (integrator bumps)

**Trigger:** nothing tells the operator what leaves before or after enabling; a level must be
chosen consciously (the request).

**Goal:**
- `core/exporter.py::set_privacy(name, privacy=None, share=None, content_max_chars=None) ->
  ExporterSpec`: writes only the changed keys into the global override (the `enable_exporter`
  mould), returns the effective spec; `is_widening(old, new) -> bool` (new classes ⊄ old).
- `docket exporters privacy <name> [<level>|--share a,b] [--max-chars N] [--yes]`: no argument
  prints the "Leaves this host" block; a widening prints each newly granted class with one example
  attribute and the destination host, then asks on a TTY (`y/N`) and, off a TTY, exits 1 naming
  `--yes` and writes nothing; narrowing never asks. `enable --privacy <level>|--share` follows the
  same rule. `add <file>` with a document above `minimal` follows it too.
- Audit `exporter.privacy` with `name`, `from`, `to`, `host` (never content).
- `exporters list`: a `SHARES` column (label). `show`: "Leaves this host" (`core.privacy.describe`:
  ✓/✗ per class, its attributes, and "never: credentials, secret-shaped values (redacted)").
  `enable` always prints `shares: <label> (<classes or "structure only">)`. `config explain`
  prints the label per exporter; `--json` carries `privacy: {label, classes}`. `doctor` adds an
  informational line for `conversation`/`full` to a non-loopback host, and one per legacy
  `payload` field naming `docket exporters privacy <name> <level>`.

**Non-goals:** preview (P33-5); any projection change.

**Owns:** `cli/_exporters.py` (`_run_list`, `_run_show`, `_run_enable`, `_run_add`, new
`_run_privacy`, one handler entry), `cli/__init__.py` (the exporters help text),
`cli/_config.py::_explain` renderer, `cli/_doctor.py::_check_exporters`,
`core/exporter.py::set_privacy`/`is_widening` (new), `tests/unit/cli/test__exporters.py`,
`tests/integration/test_exporters_cli.py`, the `exporters list` golden, `docs/commands.md`
(regenerated), the spec sections. **Forbidden:** `core/telemetry.py`, `core/privacy.py`,
`cli/_exporters_preview.py`.

**Acceptance:**
- Off a TTY, `docket exporters privacy langfuse conversation` exits 1 naming `--yes`, and the
  global file and audit log are byte-identical before and after; with `--yes` it exits 0, the
  override holds `privacy: conversation` only, and one `exporter.privacy` entry names
  `from=minimal to=conversation host=cloud.langfuse.com`.
- `docket exporters privacy langfuse minimal` after that never asks and audits the narrowing.
- `list` shows `SHARES`; `show langfuse` lists every class with ✓/✗; the `list` golden changes
  by exactly the new column (listed line by line).

**RED test:** the off-TTY widening case in `tests/integration/test_exporters_cli.py` fails on the
base (no `privacy` action). **Gates:** worker gates; `gen_cli_docs.py --check` after regeneration.

### P33-5 — see what a destination would receive before sharing it

**Status:** DONE (2026-09-28, `9bcaad4`) · **Size:** S · **Wave:** 62 (after the Wave 61 rollup) · **Spec:** `observability-export.spec.md` new section "Preview" (98–101); `cli-interface.spec.md` (integrator bumps)

**Trigger:** the request asks that the operator *know what they are sharing*; the only proof
today is opening the destination after the fact.

**Goal:** `cli/_exporters_preview.py` (new): `docket exporters preview <name> [--session <id>]
[--level <level>|--share a,b] [--json]`. It reads the named local session (default: the newest
trace under `TRACES_DIR`), projects every record through that exporter's `ExportPolicy` (or the
overriding `--level`/`--share`, which is never written), and prints, per span, its name and each
attribute with its class, content shown to 200 characters; a footer counts spans, attributes per
class and total bytes. `--json` prints the exact `otlp_http.encode` document. No network call, no
write, no audit.

**Non-goals:** changing the policy (P33-4); capture (P33-3).

**Owns:** `cli/_exporters_preview.py` (new), one `run_exporters` handler entry,
`tests/integration/test_exporters_cli.py` (a new class), the spec section. **Forbidden:**
`core/`, `edges/`, every other function in `cli/_exporters.py`.

**Acceptance:**
- With a seeded session containing a canary in a tool argument, `preview langfuse` (minimal)
  prints no canary and a footer with zero content attributes; `preview langfuse --level actions`
  prints the canary under `gen_ai.tool.call.arguments [toolArguments]`; the global file, the
  health file and the audit log are unchanged after both.
- `--json` output equals `otlp_http.encode` of the same projection (byte comparison).

**RED test:** the minimal/actions pair fails on the base (no `preview` action). **Gates:**
worker gates.

### P33-6 — docs, live proof at three levels, close (integrator)

**Status:** DONE (2026-09-28) · **Size:** M · **Wave:** 63 (after the Wave 62 rollup) · **Spec:** `observability-export.spec.md` → final version, Status "Implemented and live", "External verification" gains a "Privacy levels" subsection; `specs/README.md` rows for every bumped spec

**Goal:**
- The seam test ADR 0015 assigns the integrator: the real `_trace_llm_call` (P33-3) into the
  real projection (P33-1) under `conversation`, asserting the generation carries both message
  attributes and under `share: [prompts]` a `withheld` tool part.
- Live proof on this machine, one real dispatch per level, with a unique canary in the delegated
  task and in a file the agent reads: `minimal` — the collector's debug log and Langfuse show no
  canary, Input/Output empty; `actions` — tool spans show arguments, no file contents;
  `conversation` — Langfuse generations show Input/Output and tool results. `preview` run before
  each and matched against what arrived.
- Docs: `docs/CONFIGURATION.md` §3.14 rewritten around the level table and the three commands
  (`privacy`, `preview`, `enable --privacy`); `docs/SECURITY-SIMPLE.md` Layer 6 around classes;
  the README "gate and record" sentence only if its claim moves; `CHANGELOG.md`;
  `docs/commands.md` regenerated.
- Board: rollups, `scripts/metrics.py --check` re-measured, `split_board.py archive`, ROADMAP
  status line and D-49 row re-trued.

**Acceptance:** every gate in §"How to use this board" green on `main`; the three live results
recorded in the spec with dates; no canary found at `minimal` in either destination.
## ◆ PHASE 34 — COMPLETE (opened 2026-09-28, closed 2026-09-29): the operator loop (D-50)

**Opened 2026-09-28 at `0197e8b`.** Seventeen cards in seven waves. Decision, standards, cut and
deferred lists: [docs/adr/0016-operator-loop-and-interop-standards.md](docs/adr/0016-operator-loop-and-interop-standards.md).
Worker packets: [.agents/handoffs/wave-64-worker-packets.md](.agents/handoffs/wave-64-worker-packets.md).

**Trigger (explicit request plus facts read on the live path, 2026-09-28).** The operator asked
for five things:
- a Lead that reasons about a task before assigning it;
- clarifications as a short conversation with the human;
- approval as a separate flow;
- standard, intuitive notification (console, Telegram, email, phone; WhatsApp and Trello named);
- all of it usable by a variety of systems in a standard way.

Measured or read at `0197e8b`:
- the only four real approvals (2026-08-05) expired unanswered (`audit.log`,
  `channel=timeout` ×4);
- `serve.py::_run_sweeps` walks pods serially, so an in-turn `ask` stalls every pod for
  `TOOL_APPROVAL_TIMEOUT`;
- the Lead has `GateContract(kind="none")` and its prompt claims "human communication" that no
  path implements.

**Spec ownership rule (Phases 32–33 lesson).**
- A worker adds requirements under **its own new section heading**, numbered from 1 inside that
  section. It never touches `**Version**`, `**Status**`, `**Last Updated**` or the changelog: the
  integrator bumps each spec once per rollup.
- P34-2 creates `specs/functional/operator-loop.spec.md` with **every** later section heading
  already stubbed (`Status: Planned — owned by P34-N`). A later card replaces only its own stub,
  so no two cards append at the end of the same file.

**Standards (ADR 0016 §1), applied by every card.**
- A2A 1.0.0 `TaskState` names for `a2aState`.
- MCP elicitation (2025-06-18) shape for questions and answers.
- CloudEvents 1.0 structured JSON for events.
- Standard Webhooks headers and signing for the `webhook` dialect.
- JSON Schema 2020-12 under `docs/contracts/operator-v1/`.
- Event `type` = `dev.docket.<noun>.<verb>`; schema `$id` base
  `https://docket.dev/schemas/operator-v1/`.

**Test rule.**
- One RED behavioural test per card in the module's `SUBJECT` file.
- A second test only for the card's fail-closed negative case.
- No real model, no real vendor host: every HTTP target is a local `http.server` on port 0.
- Existing tests, goldens and specs are the no-change oracle, except where a card lists the
  change.

| Wave | Cards (parallel inside the wave) | Hot file and function ownership |
| --- | --- | --- |
| 64 | P34-1 ∥ P34-2 ∥ P34-3 ∥ P34-4 | `scripts/smoke_workflow.py` → P34-1; `core/operator_contract.py` (new), `scripts/gen_operator_schemas.py` (new), `docs/contracts/operator-v1/` (new), `specs/functional/operator-loop.spec.md` (new) → P34-2; `core/archetypes.py::_LEAD_BODY`, the Lead row of `docs/AGENT-TEAMS.md`, the two role-parity tests → P34-3; `cli/_pod.py::_pod_dispatch`, `_parse_dispatch_args`, `cli/_progress.py` (new), `specs/api/cli-interface.spec.md` → P34-4 |
| 65 | P34-5 ∥ P34-6 ∥ P34-7 | `core/tools.py::dispatch_tool` (ask branch) + `ToolContext`, `core/approval.py` (new `create_pregrant`, `consume_pregrant`, per-record `expiresAt`), `core/agent_loop.py` (`approval_parked` stop), `edges/adapters/docket_runtime.py` (env pops) → P34-5; `core/inbox.py` (new), `cli/_inbox.py` (new), one `inbox` stub in `cli/__init__.py`, `serve.py::do_GET` `/inbox` branch + metrics line, `cli/_mcp.py::tool_inbox`, `core/telegram.py` `/status` renderer → P34-6; `core/pipeline.py` (`InputSpec`, `Step.input`, validators, short form), `core/orchestrator.py` (plan render + temporary refusal), pipeline schema regen → P34-7 |
| 66 | P34-8 ∥ P34-9 | `core/dispatch.py` (`pod_approval_mode`, `_compose_hop`, `_execute_unit` parked outcome, resume position, `resolve_waiting_approval`, `dispatch_pod` signature), `core/pod.py` (`approvalMode`, `approvalExpiryHours`, `inputExpiryHours`), `serve.py::_run_sweeps` (one argument), `cli/_pod.py::_pod_dispatch` (one argument) → P34-8; `core/channel.py` (new), `templates/channels/` (new), `cli/_channels.py` (new), one `channels` stub in `cli/__init__.py`, `core/config.py` path constant, `core/config_docs.py::KINDS`, `scripts/gen_config_schemas.py::KINDS` → P34-9 |
| 67 | P34-10 ∥ P34-11 | `core/dispatch.py` (input-step execution, `waiting_input`, `_hop_message` answers section), `core/orchestrator.py` (remove the refusal), `core/answers.py` (new), `core/trace.py::EVENT_TYPES` (+2), `core/telemetry.py::_STRUCTURAL_KEYS` (+2), `serve.py::_run_sweeps` (question expiry call) → P34-10; `core/notify.py` (new), `edges/adapters/channels/` (new: `__init__`, `webhook`, `command`, `console`), `cli/_notify.py` (new), one `notify` stub in `cli/__init__.py`, `cli/_channels.py` (`test` subcommand), `serve.py::_run_sweeps` (flush call, after dispatch), `cli/_pod.py::_pod_dispatch` (flush call) → P34-11 |
| 68 | P34-12 ∥ P34-13 ∥ P34-14 | `core/handoff.py` (`TaskBrief` parse/render, `HandoffArtifact.brief`), `core/dispatch.py` (brief to Implementer, question from brief, resource check, `enqueue_task(brief=)`), `core/archetypes.py::_LEAD_BODY`, `templates/recipes/intake/` (new), `docs/recipes.md` regen → P34-12; `cli/_pod.py` (`answer`, `delegate --brief` in the `dispatch` table), `cli/_chat.py` (new), one `chat` stub in `cli/__init__.py`, `serve.py` (`POST /tasks/<id>/answer`, `brief` on `POST /tasks`), `cli/_mcp.py::tool_task_answer` → P34-13; `edges/adapters/channels/{ntfy,desktop,email}.py` (new) + three `sink_for` entries → P34-14 |
| 69 | P34-15 ∥ P34-16 | `core/interruptions.py` (new), `cli/_pod.py` (`explain`, `pregrant` in the `dispatch` table, the `delegate` summary line), `serve.py` (`POST /tasks/<id>/pregrants`), `cli/_mcp.py::tool_task_pregrant` → P34-15; `core/telegram.py` (`/answer` verb), `edges/adapters/channels/telegram.py` (new) + one `sink_for` entry, `tests/integration/test_telegram_channel.py::TestInboundOnly` rewrite, `telegram-integration.spec.md` → P34-16 |
| 70 | P34-17 (integrator) | seam tests, scenario re-run (deterministic and live), docs, CI line, spec bumps, rollups, archive |

`cli/__init__.py::cmd_pod` sits exactly at the 150-line function-span ratchet. **No card adds a
line to it.** Pod subcommands are added to `cli/_pod.py::dispatch`'s table, and the integrator
reconciles the `cmd_pod` help text.

Every card follows the §"How to use this board" definition of done.

### P34-1 — the operator-loop scenario: the phase's measured baseline and oracle

**Status:** DONE (2026-09-28, `2c543f9`) · **Size:** M · **Wave:** 64 · **Model:** Sonnet · **Spec:** none (a tool, not
behaviour)

**Trigger:** the phase's claims are about time and loss (a stalled fleet, work lost to a
timeout, nobody told). Nothing measures them today.

**Goal:**
- `scripts/smoke_workflow.py --scenario operator-loop [--live-model] [--report PATH]`.
- Setup:
  - a throwaway `DOCKET_HOME` and two temp git codebases;
  - two pods, `alpha` and `beta`, provisioned through the real CLI;
  - the `prod-approval` recipe applied to `alpha`;
  - `beta`'s Implementer given `verifyCmd false`.
- Four tasks:
  - A1 on `alpha`: the scripted Implementer issues `git push origin main`, so it asks;
  - A2 on `alpha`: a deliberately ambiguous description;
  - B1 on `beta`: plain;
  - B2 on `beta`: verify fails.
- Environment: `TOOL_APPROVAL_TIMEOUT=3` and `APPROVAL_TIMEOUT=10`, so the run is fast.
- Run one real `docket serve --dispatch -i 1` sweep cycle until every task is terminal or
  waiting, then stop it.
- Write one JSON report:

  ```json
  {"scenario": "operator-loop", "mode": "deterministic|live", "sweepBlockedSeconds": 0.0,
   "tasks": {"<id>": {"pod": "", "status": "", "reason": ""}},
   "approvals": {"timeout": 0, "granted": 0, "denied": 0, "pending": 0},
   "eventsDelivered": 0, "leadAsked": false, "elapsedSeconds": 0.0}
  ```

  `sweepBlockedSeconds` = the start of beta's first hop minus the time of alpha's
  `approval_requested`, both read from the traces.
- Separately, find which test or script wrote the 200 `project=proj` approval entries into the
  real audit log on 2026-09-25. Report the root cause; fix it only if the fix is inside `tests/`
  and is a single isolation change.

**Non-goals:** asserting future behaviour; adding the scenario to CI; any change under `src/`.

**Acceptance:**
- The deterministic run finishes in under 90 s and reports the baseline:
  - A1 `failed` with a reason containing `approval timed out`;
  - `sweepBlockedSeconds >= 3`;
  - `leadAsked: false`;
  - `eventsDelivered: 0`.
- Two consecutive deterministic runs produce identical `tasks`.
- The real `$HOME/.docket/audit.log` size and mtime are unchanged by the run (the script
  asserts this).
- `--live-model` runs against `127.0.0.1:8081` with `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500` and
  writes a report. Its task outcomes may vary; the report is the evidence.

**RED:** before the change, `python scripts/smoke_workflow.py --scenario operator-loop` exits
non-zero with an unknown-scenario error.

**Docs:** return a one-line README/CONTRIBUTING mention for the integrator.

### P34-2 — the `operator-v1` contract: one model set, A2A mapping, elicitation shape, CloudEvents

**Status:** DONE (2026-09-28, `320319e`) · **Size:** M · **Wave:** 64 · **Model:** Sonnet (Haiku-capable: the packet
lists every field) · **Spec:** `specs/functional/operator-loop.spec.md` (new; creates every
section stub, fills §"Contract")

**Trigger:** ADR 0016 §1. Every later card, and every external consumer, needs one typed
vocabulary before any behaviour exists.

**Goal:**
- `core/operator_contract.py` (new; pure; imports only `pydantic`, `typing`, `hashlib`, `json`,
  `datetime`):
  - `A2A_STATES` and `a2a_state(status, blocked_reason=None, failure_kind=None) -> str`, exactly
    the ADR 0016 §3 table; unknown input raises `ValueError`.
  - `TaskBrief`.
  - `QuestionSchema`: an elicitation `requestedSchema` validator. It accepts a flat
    `{"type": "object", "properties": {...}, "required": [...]}` whose properties are `string`
    (formats `email`, `uri`, `date`, `date-time` only), `number`, `integer`, `boolean`, or a
    string `enum` with optional `enumNames`. It rejects nesting, arrays and any other format.
  - `Question`.
  - `AnswerResult` (`action: Literal["accept", "decline", "cancel"]`, `content: dict | None`)
    and `validate_answer(question, result)`.
  - `ApprovalView`, `TaskView` (carries `a2aState`), `InboxView`.
  - `CloudEvent` (`specversion` fixed `"1.0"`) and
    `make_event(kind, pod, subject, data, *, time) -> CloudEvent`, with a deterministic `id`
    and `datacontenttype: application/json`.
  - `EVENT_TYPES`: the seven ADR 0016 §7 types plus `dev.docket.channel.test`.
  - `canonical_args_digest(tool, args) -> str`: SHA-256 hex of
    `json.dumps({"tool": tool, "args": norm(args)}, sort_keys=True, separators=(",", ":"))`,
    where `norm` collapses runs of whitespace inside string values (`" ".join(s.split())`)
    recursively.
- `scripts/gen_operator_schemas.py [--check]` renders
  `docs/contracts/operator-v1/{task,question,answer,approval,inbox,brief,event}.schema.json`
  (JSON Schema 2020-12, `$id` under `https://docket.dev/schemas/operator-v1/`), modelled on
  `scripts/gen_config_schemas.py`.
- The spec file with the header block and these sections, the later ones stubbed:
  1. Contract (P34-2)
  2. Inbox (P34-6)
  3. Answers (P34-10)
  4. Answer surfaces (P34-13)
  5. Channels (P34-9)
  6. Operator events and delivery (P34-11)
  7. Dialects (P34-11, P34-14)
  8. Telegram as a channel (P34-16)
  9. Interruption forecast (P34-15)

**Non-goals:** any caller; any change to existing modules; CI wiring (the integrator).

**Acceptance:**
- `a2a_state` covers every row of ADR 0016 §3 in a table-driven test.
- A nested `requestedSchema` is rejected.
- `validate_answer` rejects `accept` without a required property and accepts `decline` with no
  content.
- `canonical_args_digest("bash", {"command": "git  push   origin main"})` equals the digest of
  `"git push origin main"`, and argument key order does not matter.
- `make_event` output validates against `event.schema.json`, with `type` beginning `dev.docket.`.
- `gen_operator_schemas.py --check` passes after generation and fails after hand-editing a
  schema.
- `bash scripts/validate-specs.sh` passes with the new spec.

**RED:** `tests/unit/core/test_operator_contract.py` (`SUBJECT = "docket.core.operator_contract"`)
fails on import at the base.

### P34-3 — the Lead stops promising human communication it does not have

**Status:** DONE (2026-09-28, `de843e5`) · **Size:** S · **Wave:** 64 · **Model:** Haiku · **Spec:**
`role-archetypes.spec.md`, only where the Lead body is quoted (`rg -n "human" specs/functional/role-archetypes.spec.md`)

**Trigger:** `core/archetypes.py::_LEAD_BODY` says "You own the pod's context, memory, and
human communication" and "Surface architectural decisions and risky actions to the human
(HITL)"; `docs/AGENT-TEAMS.md`'s roles table says the Lead "owns … human (Telegram) comms". No
path implements either (ADR 0016 evidence). This is the unwired-capability shape: a false
statement to the model and to the reader.

**Goal:**
- In `_LEAD_BODY`, replace exactly those two lines with:

  ```text
  - You own the pod's context and memory. You cannot message the human directly.
  - When a decision or a risky action needs the human, say so at the top of your plan: list every assumption and every open question.
  ```

- In `docs/AGENT-TEAMS.md`, the Lead row's third cell becomes: "Orchestrates the pod, owns its
  context and memory, decomposes work into a plan for the workers".
- Update the expected text in `tests/integration/test_pod_role_workspace_parity.py` and
  `tests/integration/test_legacy_role_parity.py`, and any golden case that embeds a Lead
  `SOUL.md`.
- Explain every changed line: the old string was factually false, the one allowed reason (board
  rule 4).

**Non-goals:** any other role body; the intake wording (P34-12 amends this body again).

**Acceptance:** `rg -n "human communication|human \(Telegram\)" src docs` returns nothing;
parity and golden suites pass with only the listed lines changed.

**RED:** after editing only `_LEAD_BODY`, the parity test fails on exactly the two lines. That
proves it pins the text. Then update the expectation.

### P34-4 — foreground dispatch shows what it waits for, and asks in place on a TTY

**Status:** DONE (2026-09-28, `964a019`) · **Size:** M · **Wave:** 64 · **Model:** Sonnet · **Spec:**
`specs/api/cli-interface.spec.md` new section "Foreground dispatch progress and in-place
approval"

**Trigger:** `cli/_pod.py::_pod_dispatch` is silent while a hop blocks on an in-turn approval for
`TOOL_APPROVAL_TIMEOUT`. The operator needs a second terminal and must already know the token.

**Goal:**
- When stderr is a TTY (or `--progress`), `_pod_dispatch` runs `dispatch_pod` in a worker
  thread. A `trace.subscribe` sink only enqueues events; the main thread renders one stderr
  line per:
  - `session_start` (`▶ <role> …`);
  - `approval_requested` (`⏸ <role> wants: <action> · token <t> · denies in <n>s ·
    docket approve <t>`);
  - `approval_required` (the hop-level gate);
  - `session_end`.
- When stdin is also a TTY and `--no-prompt` is absent, an `approval_requested` event prompts
  `[a]pprove  [d]eny  [Enter] keep waiting`. `a` calls
  `core.approval.approval_grant(token, channel="cli")` then
  `core.dispatch.resolve_waiting_approval`; `d` denies. The blocked hop's own poll picks up the
  decision.
- The rendering and parsing are pure functions in `cli/_progress.py` (new).
- `docket pipeline run` inherits this: it calls `_pod_dispatch`.

**Non-goals:** a park option in the prompt (P34-8 adds it); any `core/` change; output when
stderr is not a TTY.

**Acceptance:**
- With stdin and stderr faked as TTYs, a scripted backend whose Implementer calls a gated
  `bash` command, and the input `a\n`: the command executes once, and the audit log holds
  `approval.grant … channel=cli`.
- With input `d\n`: the hop reports `approval_denied`.
- Without a TTY: stdout and stderr are byte-identical to the base (goldens unchanged).

**RED:** the TTY-faked test in `tests/unit/cli/test_pod.py` fails at the base (no prompt, the
wait times out).

### P34-5 — the chokepoint parks a call and honours single-use pre-grants

**Status:** DONE (2026-09-28, `cff4a5d`) · **Size:** M · **Wave:** 65 · **Model:** Sonnet · **Spec:**
`security-gates.spec.md` new section "Parked calls and single-use pre-grants";
`agent-loop.spec.md` new section "The approval_parked stop"

**Trigger:** ADR 0016 §2. A `park` posture needs the chokepoint to record the exact call and end
the turn without waiting. A grant needs a way to let exactly that call through once.

**Goal:**
- `ToolContext.approval_mode: Literal["wait", "park", "refuse"]`.
- `ToolContext.pregrants: tuple[Pregrant, ...] = ()`, where `Pregrant` is `(token, tool,
  args_digest)`.
- `ToolContext.approval_expires_at: str | None = None` (ISO). A parked record carries it as
  `expiresAt` when set.
- In `dispatch_tool`'s `ask` branch, **first**: if a pre-grant matches `(tool.name,
  canonical_args_digest(tool.name, args))` and `core.approval.consume_pregrant(token)` returns
  `True`, allow with reason `pre-granted (token=<t>)`.
- Under `park`:
  - `approval_create(..., context={"tool", "argsDigest", "callId", "parked": True})`;
  - return `decision="deny"`, `denial_kind="approval_parked"`, and the token on the result;
  - no wait.
- `core/approval.py`:
  - `consume_pregrant(token) -> bool`: atomic through `store.read_modify_write`, sets
    `consumedAt`, audits `approval.consume`. A second call returns `False`.
  - `create_pregrant(project, role, tool, args_digest, *, task_id, expires_at, channel, actor)
    -> str`: a record born `granted`, with context `{"kind": "pregrant", ...}`, audited
    `approval.pregrant`.
  - Every record may carry `expiresAt`. The expiry sweep honours it when present and falls back
    to `APPROVAL_TIMEOUT` otherwise.
- `core/agent_loop.py`: the loop stops on `approval_parked` exactly as it stops on
  `approval_unavailable`. Add `approval_parked_error(result) -> str` beside
  `approval_unavailable_error`: one function owns the format (the W30 seam rule).
- `edges/adapters/docket_runtime.py`: pop `DOCKET_PREGRANTS` (JSON list) and
  `DOCKET_APPROVAL_EXPIRES_AT` (ISO) from the tool env dict exactly as `DOCKET_APPROVAL_MODE`
  is popped, into `ToolContext.pregrants` and `ToolContext.approval_expires_at`. Both constants
  are new in `core/runtime_driver.py`.

**Non-goals:** anything in `core/dispatch.py`; the defaults; harness mode (it stays `refuse`).

**Acceptance:**
- Under `park`, a gated call returns in under 1 s (with `TOOL_APPROVAL_TIMEOUT=60`), the handler
  is never called, and exactly one pending record carries the digest.
- With a matching pre-grant, the handler runs once; an identical second call asks again; a call
  with a different argument asks.
- A pre-grant whose `expiresAt` is past is swept to `denied` and never consumed.
- The AST chokepoint test is unchanged and green.

**RED:** the `park` case in `tests/unit/core/test_tools.py` fails at the base (`Literal`
rejects `park`, or the call waits).

### P34-6 — one derived inbox for the whole fleet

**Status:** DONE (2026-09-28, `1e4c882`) · **Size:** M · **Wave:** 65 · **Model:** Sonnet · **Spec:** operator-loop
§"Inbox"; `specs/data/serve-read-api.spec.md` new section "GET /inbox";
`specs/api/mcp-server.spec.md` (tool `inbox`); `telegram-integration.spec.md` requirement 3
amended (same scope, new renderer)

**Trigger:** ADR 0016 §6. What needs the operator is spread over four commands, one pod at a
time.

**Goal:**
- `core/inbox.py::build_inbox(*, now, since=None) -> InboxView`. It is pure over:
  - every pod's task list (`core.dispatch.read_tasks` for every provisioned pod, paused
    included);
  - `core.approval.list_pending()`;
  - running runs.

  Sections:
  - `needsYou`: every `waiting_*` status (future-proof: any status starting `waiting_`), every
    `blocked` task, and every pending approval not attached to a task;
  - `failed`;
  - `doneSince`: terminal after `since`;
  - `running`.

  Every item is a `TaskView` or `ApprovalView` with `a2aState`. `next` is the maximum
  timestamp seen.
- `docket inbox [--json] [--since C] [--peek]`: without `--peek`, advances a cursor stored in
  `~/.docket/inbox-cursor.json` through `edges/store.py`.
- `GET /inbox?since=C` (Bearer, like `/approvals`).
- MCP `inbox(since=None)`.
- Telegram `/status` renders from `build_inbox`, filtered to the bound project (requirement 3
  intact).
- `/metrics` gains `docket_inbox_items{section}`.

**Non-goals:** notifications; answering; per-consumer cursors on the server.

**Acceptance:**
- A fixture with two pods (tasks in `pending`, `running`, `waiting_approval`, `blocked`,
  `failed`, `done`, and one status `waiting_input` written by hand) and one pending approval
  yields exactly the expected sections, and each item's `a2aState` matches ADR 0016 §3.
- A second `docket inbox` shows no `doneSince` items.
- `GET /inbox` JSON equals `docket inbox --json` for the same state.
- `/status` output for a bound pod lists only that pod.

**RED:** `tests/unit/core/test_inbox.py` fails on import at the base.

### P34-7 — the pipeline format gains an `input` step (format only)

**Status:** DONE (2026-09-28, `91831b4`) · **Size:** S · **Wave:** 65 · **Model:** Haiku · **Spec:**
`pipeline-format.spec.md` new section "Input steps"

**Trigger:** ADR 0016 §4. A question is a pipeline step, so a team declares when it may be
asked, in YAML.

**Goal:**
- `core/pipeline.py`:
  - `InputSpec(extra="forbid")`: `from_` (alias `from`, required), `message: str = ""`,
    `expiresHours: int | None` (`> 0`).
  - `Step.input: InputSpec | None`, exclusive with `role`, `agent`, `run`, `parallel`, `gate`,
    `retries`, `timeout`, `instructions` and `model`.
  - `PipelineSpec` validates that `from` names an **earlier** step id.
  - An input step's `on` may use only the labels `answered` and `declined`.
  - The short form accepts `- ask: {input: {from: triage}}`.
- `docket pipeline plan` / `validate` render `ask ← asks the operator (from triage)`.
- `core/orchestrator.py`: building an executable plan that contains an input step raises the
  existing error type, with the message `input steps are not executable until P34-10 ships`.
  P34-10 deletes this refusal.
- Regenerate `docs/contracts/config-v1/pipeline.schema.json` (both copies) with
  `scripts/gen_config_schemas.py`.

**Non-goals:** execution; `waiting_input`; any change to `core/dispatch.py`.

**Acceptance:**
- The ADR 0016 §4 YAML validates.
- Each of these is rejected with an error string naming the dotted location: `input` together
  with `role`; a forward `from`; `on: {pass: …}` on an input step.
- `plan` renders the line above.
- `pod dispatch` on such a pipeline fails with the refusal message and leaves no task mutated.

**RED:** the valid-document test in `tests/unit/core/test_pipeline.py` fails at the base
(unknown key `input`).

### P34-8 — dispatch parks: `approvalMode: park`, caller defaults, expiry, re-entry with the pre-grant

**Status:** DONE (2026-09-28, `7eea68c`) · **Size:** L (the packet splits the work into two commits on one branch) ·
**Wave:** 66 · **Model:** Sonnet · **Spec:** `pod-dispatch.spec.md` "Unattended approval
posture" amended (item 5's default non-goal removed, `park` added) plus a new section "Parked
approvals"; the pod-settings keys wherever `approvalMode` is specified (`rg -n approvalMode
specs`)

**Trigger:** ADR 0016 §2, and the fleet stall in `serve.py::_run_sweeps`.

**Goal:**
- `core/pod.py`:
  - `approvalMode: Literal["wait", "park", "refuse"]`;
  - new keys `approvalExpiryHours` (int, default 24, `>= 1`) and `inputExpiryHours` (int,
    default 72, `>= 1`; read by P34-10);
  - "unset" is detected from the stored settings (`model_fields_set` or the raw record), never
    by changing a field default. `config explain` shows `approvalMode: (unset → park under
    serve and without a TTY, wait on a TTY)`.
- `core/dispatch.py`:
  - `pod_approval_mode(project, *, caller_default)` returns the pod value when set, else
    `caller_default`.
  - `dispatch_pod(..., approval_default: Literal["wait", "park"] = "wait")`.
  - `serve.py::_run_sweeps` passes `"park"`. `cli/_pod.py::_pod_dispatch` passes `"wait"`
    when `sys.stdin.isatty()`, else `"park"`.
  - `_compose_hop` sets `DOCKET_APPROVAL_MODE=park` as it does for `refuse`, and
    `DOCKET_PREGRANTS` from the task's `pregrants` list.
  - A hop whose turn stopped on `approval_parked` yields the existing `waiting_approval`
    outcome with the token and **its own** pipeline index. The parked hop is persisted with
    `parked: true`.
  - The resume-position builder re-runs a parked index instead of advancing past it.
  - `resolve_waiting_approval` on a grant of a parked record appends
    `{token, tool, argsDigest}` to the task's `pregrants` and returns it to `pending`.
  - `_compose_hop` also sets `DOCKET_APPROVAL_EXPIRES_AT = now + approvalExpiryHours`, so the
    parked record P34-5 creates carries its `expiresAt`.
- P34-4's prompt gains `[p]ark and continue` when the pod resolves to `wait` on a TTY. It
  flips the in-flight wait into a deny with `denial_kind="approval_parked"` through the
  existing cancellation seam, and the task parks.

**Non-goals:** questions; notifications; one worker per pod in the sweep (deferred, ADR 0016).

**Acceptance (scripted backend):**
- Under `park`:
  - the Implementer's gated `git push origin main` leaves the task `waiting_approval` in under
    1 s;
  - `docket approve <t>` then `docket pod <p> dispatch` executes that exact command once and
    reaches `done`;
  - a deny fails the task `approval_denied`;
  - an `expiresAt` in the past plus a sweep also fails it.
- Two pods in one `serve` sweep: pod A parks and pod B's task still runs in the same sweep (the
  P34-1 scenario's `sweepBlockedSeconds` drops below 1).
- A pod with no `approvalMode` dispatched from a TTY still waits, and its goldens are unchanged.

**RED:** the parked-dispatch test in `tests/integration/test_dispatch.py` fails at the base
(`approvalMode` rejects `park`).

### P34-9 — `kind: channel` documents, catalog and CLI

**Status:** DONE (2026-09-28, `ad97918`) · **Size:** M · **Wave:** 66 · **Model:** Sonnet · **Spec:** operator-loop
§"Channels"; `config-format.spec.md` (the `channel` kind)

**Trigger:** ADR 0016 §7. Destinations are configuration, shaped like providers and exporters.

**Goal:**
- `core/channel.py` (new), modelled on `core/exporter.py`.
- `ChannelSpec`:
  - `kind: Literal["channel"]`, `name`, `description`;
  - `dialect: Literal["console", "desktop", "webhook", "command", "ntfy", "email", "telegram"]`;
  - `enabled: bool = False`;
  - `capabilities: list[Literal["notify", "converse", "decide"]]`;
  - `on: list[str]` (the ADR 0016 §7 type suffixes, plus the shorthand `needs_you`);
  - `content: Literal["minimal", "actions", "conversation"] = "minimal"`;
  - `actors: list[str]`;
  - `config: dict[str, str]`;
  - `secret: str | None` (a credential **name**, validated like exporter credential names).
- Validation:
  - `capabilities` ⊆ `DIALECT_MAX[dialect]`: `console` = decide; `telegram` = decide;
    `desktop`, `webhook`, `command`, `ntfy`, `email` = notify;
  - `decide` or `converse` requires non-empty `actors`, except `console`.
- Catalog: built-ins `templates/channels/01-console.yaml` … `07-telegram.yaml` (only `console`
  enabled); global `docket-channels.json` (a new `config.py` path) through `edges/store.py`;
  nearest wins.
- `docket channels list|show|enable [--set k=v]|disable|add <file>|remove|export|content <name>
  <level> [--yes]`. Widening `content` requires a TTY confirmation or `--yes` and is audited
  (`channel.content`), exactly like `docket exporters privacy`.
- `docket validate` accepts `kind: channel`.
- `docs/contracts/config-v1/channel.schema.json` is generated.

**Non-goals:** delivery (P34-11); `channels test` (P34-11); per-pod channel selection
(deferred: a second pod needing a different destination).

**Acceptance:**
- The catalog lists seven built-ins, only `console` enabled.
- An `email` document with `decide` is rejected with an error naming the dialect's maximum.
- A `telegram` document with `decide` and no `actors` is rejected.
- `enable ntfy --set topic=x` persists and `show` reflects it.
- `content ntfy actions` off a TTY without `--yes` exits non-zero and writes nothing.
- `gen_config_schemas.py --check` passes.

**RED:** `tests/unit/core/test_channel.py` fails on import at the base.

### P34-10 — questions execute: `waiting_input`, `answer_task`, expiry to `blocked`

**Status:** DONE (2026-09-28, `fc5275f`) · **Size:** L · **Wave:** 67 (after P34-7 and P34-8) · **Model:** Sonnet ·
**Spec:** `pod-dispatch.spec.md` "Task status vocabulary" item 7 plus a new section "Input steps
and waiting_input"; operator-loop §"Answers"; `trace-store.spec.md` (two event types)

**Trigger:** ADR 0016 §3–4. The Lead has no way to ask.

**Goal:**
- `core/dispatch.py::_run_pipeline` gains an input-step branch, and P34-7's refusal is removed.
  - With no unconsumed answer for this step, it builds a `Question`:
    - `message` = the step's `message`, else the `from` step's latest hop output (at most
      2,000 chars);
    - `requestedSchema` = `{"type": "object", "properties": {"answer": {"type": "string",
      "title": "Answer"}}, "required": ["answer"]}`;
    - `expiresAt` from `inputExpiryHours` or the step's `expiresHours`.

    It persists the question on the task, sets `waiting_input` and `pendingInputIndex`, and
    traces `input_requested` with `{task, step, questionId}` only.
  - With an unconsumed answer, it marks the answer consumed and persists a synthetic
    `operator` hop carrying `next_step`, so the route counts survive a resume. It then routes
    `answered` (`accept`) or `declined` (`decline`/`cancel`) through the step's `on`. An
    unrouted `answered` advances; an unrouted `declined` fails with `operator declined`.
- `core/answers.py::answer_task(project, task_id, result, *, channel, actor) -> TaskView`:
  - requires `waiting_input`;
  - calls `validate_answer`;
  - screens every string through the same `pre_input` evaluation `/delegate` uses;
  - appends to `answers[]` and sets the task `pending`;
  - audits `task.answer`;
  - traces `input_answered`.
- `core/answers.py::sweep_expired_questions(now)` turns an expired `waiting_input` into
  `blocked` with `blockedReason: input_expired`. `serve.py::_run_sweeps` calls it next to the
  approval sweep.
- `_hop_message`: the Lead branch and the Implementer branch gain an `## Operator answers`
  section: every Q/A pair, bounded to 4,000 chars with the existing truncation marker.
- `core/trace.py::EVENT_TYPES` += `input_requested`, `input_answered`.
  `core/telemetry.py::_STRUCTURAL_KEYS` gets their structural keys only. Question text never
  becomes a structural attribute.

**Non-goals:** CLI, HTTP and MCP surfaces (P34-13); the brief (P34-12); notifications.

**Acceptance (scripted backend; pipeline `triage: lead` with verdict `[READY, NEEDS-INPUT]`,
`ask: input from triage`, `build: implementer`):**
- The first dispatch leaves `waiting_input`, with the Lead's text as the question.
- `answer_task(accept, {"answer": "per account"})` returns the task to pending. The next
  dispatch's Lead message contains `per account`. The Lead replies `READY`, the Implementer
  runs, and the task reaches `done`.
- With `max: 1` and the Lead asking twice, the task fails `exhausted its routing budget`.
- An expired question becomes `blocked`/`input_expired`, **never** `failed`.
- An answer matching a `pre_input` block policy raises and leaves the task `waiting_input`.

**RED:** the first-dispatch test in `tests/integration/test_dispatch.py` fails at the base
(P34-7's refusal).

### P34-11 — operator events: derived from inbox transitions, delivered by channels (webhook, command)

**Status:** DONE (2026-09-28, `bae3af3`) · **Size:** L · **Wave:** 67 · **Model:** Sonnet · **Spec:** operator-loop
§"Operator events and delivery" and §"Dialects" (webhook, command, console)

**Trigger:** ADR 0016 §7. Nobody is told.

**Goal:**
- `core/notify.py`:
  - `diff_events(prev, inbox, now) -> (events, snapshot)` is pure. It emits one CloudEvent per
    new `needsYou`/`failed`/`doneSince` item, plus `approval.expiring` once per approval at 80 %
    of its life. Event ids are deterministic: SHA-256 of type, subject and the item's version
    token.
  - `render_data(item, level)` enforces the content levels:
    - `minimal` = `pod`, `taskId`, `role`, `reasonCode`, `token` or `questionId`, `expiresAt`,
      and `respond: {cli, http}`;
    - `actions` adds `action` (the rendered command);
    - `conversation` adds `question` and `brief`.
  - `render_text(event) -> (title, body)` feeds text dialects.
  - `flush(specs, sink_for, *, now) -> FlushReport`: loads and saves `notify-state.json` and
    `channels-health.json` through `edges/store.py`; delivers to every enabled channel with
    `notify` whose `on` matches; 5 s per delivery, 2 retries; never raises.
- `edges/adapters/channels/`:
  - `sink_for(spec)`;
  - `webhook.py`: POST `application/cloudevents+json` with the Standard Webhooks headers:
    - `webhook-id` = the event id;
    - `webhook-timestamp` = unix seconds;
    - `webhook-signature` = `v1,` + base64(HMAC-SHA256(key, f"{id}.{ts}.{body}")), where `key`
      is the base64-decoded part of a `whsec_…` secret read by name through
      `core.secrets.secret_value`;
  - `command.py`: runs an operator binary with an argv list and the event JSON on stdin, 10 s
    timeout;
  - `console.py`: no-op (the console *is* the inbox).
- Wiring:
  - `serve.py::_run_sweeps` calls `flush` after dispatch;
  - `cli/_pod.py::_pod_dispatch` calls `flush` once at the end;
  - `docket notify flush [--dry-run]` (new) prints what would be sent;
  - `docket channels test <name>` sends one `dev.docket.channel.test` event.

**Non-goals:** ntfy, desktop, email (P34-14); Telegram (P34-16); any receipt of answers.

**Acceptance:**
- Two flushes over the same state deliver once (dedupe).
- A new parked approval yields exactly one `dev.docket.approval.requested`.
- **Canary:** a `minimal` event's JSON contains neither the parked command string nor the
  question text; at `actions` it contains the command.
- A local `http.server` receives the POST. The test recomputes the signature from a known
  `whsec_` secret and it matches; `webhook-id` equals the CloudEvent `id`.
- A dead port records an error in `channels-health.json` and returns within the timeout
  without raising.

**RED:** `tests/unit/core/test_notify.py` fails on import at the base.

### P34-12 — the Lead's intake: `TaskBrief`, the `intake` recipe, resource checks, the brief reaches the Implementer

**Status:** DONE (2026-09-28, `7576574`) · **Size:** L · **Wave:** 68 (after P34-10) · **Model:** Sonnet · **Spec:**
`pod-dispatch.spec.md` new section "Task brief"; `role-archetypes.spec.md` (Lead body);
`docs/recipes.md` regenerated

**Trigger:** ADR 0016 §4. The Implementer gets free prose; the Lead cannot declare a task not
ready or name what is missing.

**Goal:**
- `core/handoff.py`: `parse_brief(text) -> TaskBrief | None` reads the **last** fenced
  `json` block that validates as `TaskBrief`. `render_brief(brief) -> str` renders the fields
  in a fixed order. `HandoffArtifact.brief: TaskBrief | None`.
- `core/dispatch.py`:
  - a hop whose output carries a brief sets `artifact.brief`;
  - the Implementer's message renders `## Brief` from the latest brief in place of the Lead's
    summary;
  - an input step whose `from` hop has `brief.questions` builds a `requestedSchema` with one
    string property per question (`q1`…`qn`, `title` = the question) and the message `The
    Lead needs answers before starting: <objective>`;
  - after a `READY` verdict carrying a brief, `_check_brief_resources(project, brief)` checks
    `secret:<NAME>` against `core.secrets.secrets_keys()`, `path:<p>` for existence, and
    `verify` for the Implementer's `verifyCmd`. Anything missing ends the task `blocked` with
    `blockedReason: resources` and a reason naming each item, without another turn;
  - `enqueue_task(..., brief: dict | None = None)` validates and stores a pre-brief, which the
    Lead's message then includes.
- `templates/recipes/intake/`:
  - `pipeline.yaml`: the ADR 0016 §4 pipeline, with the Lead step's `instructions` telling it
    to end with one `json` fenced `TaskBrief` and then one marker line `READY`, `NEEDS-INPUT`
    or `REJECT`;
  - `pod.yaml` with `description`;
  - `README.md` in the recipes convention.
- `REJECT` routes to `fail` with `failureKind: rejected` (`a2aState` `REJECTED`).
- `_LEAD_BODY` gains, after P34-3's lines:

  ```text
  - If your pod's pipeline has an intake step, your questions reach the human through it: list them in your brief and end with NEEDS-INPUT.
  ```

  Parity tests are updated with the reason.
- `scripts/gen_recipe_docs.py` regenerates `docs/recipes.md`.

**Non-goals:** making `intake` the `software` default (deferred with trigger); surfaces
(P34-13); pre-grants (P34-15).

**Acceptance (scripted backend, `pod apply intake`):**
- The Lead emits a brief with two questions and `NEEDS-INPUT`: the question has properties `q1`
  and `q2`. After both are answered, the Lead emits `READY`, and the Implementer's message
  contains `## Brief` with the acceptance items and not the Lead's prose preamble.
- A brief naming `secret:MISSING_KEY` blocks with `resources`; the task view shows
  `AUTH_REQUIRED`.
- A reply with no parseable brief but a `READY` marker still advances: the brief is optional,
  and the verdict rule is unchanged.
- `REJECT` fails the task as `rejected`.

**RED:** the brief-reaches-Implementer test in `tests/integration/test_dispatch.py` fails at
the base.

### P34-13 — answer surfaces: CLI, `docket chat`, HTTP, MCP, pre-brief on delegate

**Status:** DONE (2026-09-28, `34fc8cb`) · **Size:** M · **Wave:** 68 (after P34-10) · **Model:** Sonnet · **Spec:**
operator-loop §"Answer surfaces"; `serve-read-api.spec.md` new section "POST
/tasks/<id>/answer"; `mcp-server.spec.md` (`task_answer`); `cli-interface.spec.md` (`pod
answer`, `chat`, `delegate --brief`)

**Trigger:** ADR 0016 §8. `answer_task` has no caller.

**Goal:**
- `docket pod <p> answer <task> [TEXT] [--field k=v]... [--decline]`. A bare `TEXT` fills the
  single property of a one-property schema.
- `docket chat <task> [--pod p]` shows the question, the brief, earlier answers and any
  `expectedRiskyActions`. On a TTY it prompts for each property and calls `answer_task` with
  `channel="cli"` and `actor=<OS user>`.
- `docket pod <p> delegate --brief FILE.json`.
- `POST /tasks/<id>/answer`, body `{"pod": "...", "action": ..., "content": {...}}` (the
  elicitation result). It returns the `TaskView`; 409 when not `waiting_input`; 422 on schema
  or screen failure.
- `POST /tasks` accepts `brief`.
- MCP `task_answer(project, task_id, action, content)`.

**Non-goals:** Telegram (P34-16); notifications.

**Acceptance:**
- Each surface answers the same fixture task and leaves identical `answers[]` entries except
  `channel`.
- The HTTP 409 and 422 paths leave the task unchanged.
- `delegate --brief` with an invalid brief exits non-zero and enqueues nothing.

**RED:** the HTTP answer test (the pattern in the existing serve tests) returns 404 at the base.

### P34-14 — ntfy, desktop and email dialects

**Status:** DONE (2026-09-28, `1b2f3dc`) · **Size:** S · **Wave:** 68 (after P34-11) · **Model:** Haiku · **Spec:**
operator-loop §"Dialects" (ntfy, desktop, email)

**Trigger:** ADR 0016 §7. The phone, the desktop and the mailbox are where an operator already
looks.

**Goal:** three sinks in `edges/adapters/channels/`, registered in `sink_for`, each built from
`core.notify.render_text`:
- `ntfy.py`: POST the plain-text body to `{config.server or "https://ntfy.sh"}/{config.topic}`
  with headers `Title` and `Priority` (`high` for a needs-you type, else `default`), plus
  `Authorization: Bearer <secret>` when `secret` is set.
- `desktop.py`: `notify-send <title> <body>` on Linux, `osascript -e 'display notification …'`
  on macOS, always with an argv list and never a shell; a missing binary is a silent no-op
  recorded in health.
- `email.py`: `smtplib.SMTP(host, port or 587)` with STARTTLS, login with `config.user` and the
  secret, subject `[docket] <title>`, plain-text body. It never reads mail and can never decide
  (P34-9 already enforces that).

**Non-goals:** IMAP; HTML mail; any inbound path.

**Acceptance:**
- A local `http.server` receives the ntfy POST with the expected headers and body.
- A fake `notify-send` on a temporary `PATH` records its argv.
- A monkeypatched `smtplib.SMTP` records `starttls`, `login` and one `send_message` with the
  subject.
- A `minimal` body contains no command text (canary).

**RED:** `tests/unit/edges/test_channel_dialects.py` fails on import at the base (create the
file; it is named by this card).

### P34-15 — see it coming: `explain interruptions`, and pre-grants from the intake

**Status:** DONE (2026-09-28, `28a6137`) · **Size:** M · **Wave:** 69 · **Model:** Sonnet · **Spec:** operator-loop
§"Interruption forecast"; `pod-dispatch.spec.md` new section "Pre-grants from intake"

**Trigger:** ADR 0016 §10. The operator cannot know before delegating what may stop a task, and
cannot answer an expected approval while already engaged.

**Goal:**
- `core/interruptions.py::forecast(project, *, caller_default) -> list[Interruption]`, derived
  from:
  - effective policies whose action is `require_approval` (with their pattern or predicate);
  - the classifier's high-risk classes;
  - the pipeline's `approval` and `input` steps;
  - `requireApprovalRoles`;
  - the resolved `approvalMode`;
  - both expiries;
  - enabled channels that can notify.
- `docket pod <p> explain interruptions [--json]` prints it. On a pod with nothing that can
  ask, it prints `Nothing in this pod will ask you.`
- `delegate` prints one summary line, `May ask you: …`.
- `docket pod <p> pregrant <task> "<command>" [--tool bash]`, `POST /tasks/<id>/pregrants` and
  MCP `task_pregrant`:
  - call `create_pregrant` with `canonical_args_digest(tool, {"command": command})`, an expiry
    of `approvalExpiryHours`, the channel and the actor;
  - append the pre-grant to the task's `pregrants`.
- `docket chat` prints the suggested `pregrant` command for each of the brief's
  `expectedRiskyActions`.

**Non-goals:** fuzzy matching (the exact-after-whitespace limit is stated in the spec and the
help text).

**Acceptance:**
- With `prod-approval` applied, `explain interruptions` lists its patterns and the park
  posture.
- A pre-granted `git push origin main` executes once during dispatch with no new pending
  record. `git push origin main --force` asks.
- A pre-grant on a task in another pod is refused.

**RED:** the pre-granted-dispatch test fails at the base (no `pregrant` subcommand).

### P34-16 — Telegram becomes a channel: minimal pushes and `/answer` (Command grammar 7 amended)

**Status:** DONE (2026-09-28, `45e21b8`) · **Size:** M · **Wave:** 69 · **Model:** Sonnet · **Spec:**
`telegram-integration.spec.md`: requirements 7 and 8 and the Non-goals amended per ADR 0016
§9, plus a new section "As a channel"

**Trigger:** ADR 0016 §9. The operator named Telegram; the bot is already bound and trusted to
decide.

**Goal:**
- `edges/adapters/channels/telegram.py`: a sink that sends `render_text` at the channel's
  content level to every chat bound to an actor in `actors`, through the existing
  `edges/adapters/telegram.py::send_message`.
- `core/telegram.py`: a fifth verb, `/answer <task-id> <text>`. It goes through the same
  `_authorize`, then calls `answer_task(..., channel="telegram", actor=<chat id>)`, whose
  `pre_input` screen applies. The reply is `answered; <task-id> resumes on the next dispatch`.
- `/approve` and `/deny` are unchanged.
- Rewrite `TestInboundOnly` in the same commit, as `TestOutboundOnlyThroughTheChannel`: an AST
  walk over `src/` finds exactly two `send_message` call sites, the reply inside `poll_once`
  and the channel sink.

**Non-goals:** reply-to-message threading (deferred); inline keyboards (cut); free text.

**Acceptance:**
- With a fake `send_message`, a parked approval's flush sends one message to the bound chat
  whose text lacks the command at `minimal` (canary).
- `/answer` from an unbound chat is refused and nothing changes.
- `/answer t-1 per account` resumes a `waiting_input` task.
- The rewritten AST test fails if a third call site is added (proven by a throwaway local edit
  that is not committed).

**RED:** the `/answer` test in `tests/integration/test_telegram_channel.py` fails at the base
(unknown verb).

### P34-17 — integrator: seams, the scenario again, docs, close

**Status:** DONE (2026-09-29) · **Size:** M · **Wave:** 70 · **Model:** integrator · **Spec:** every
touched spec bumped once, `specs/README.md` index

**Goal:**
- **Seam tests** in `tests/integration/test_operator_loop_seams.py`, using the real producers
  and consumers:
  - park (P34-5/8) → inbox (P34-6) → flush (P34-11) → `POST /approvals` → resume;
  - intake question (P34-10/12) → webhook event (P34-11) → `POST /tasks/<id>/answer` (P34-13)
    → resume;
  - Telegram `/answer` (P34-16) → the same resume.
- **Scenario:** `smoke_workflow.py --scenario operator-loop` re-run deterministic and live,
  extended so A2 runs under the `intake` recipe and a `webhook` channel points at a local
  receiver. Record the P34-1 baseline beside the new numbers in the roadmap changelog:
  `sweepBlockedSeconds` below 1, no task lost to `approval_timeout`, `leadAsked: true`,
  `eventsDelivered` ≥ 3.
- **Deferred triggers:** evaluate the live Lead-brief parse rate (the `intake`-default trigger)
  and the re-run-misses-granted-call rate (the mid-turn resume trigger). Record them; schedule
  nothing.
- **Docs:**
  - README: "The gate and the record" gets park, inbox and channels; the agent-lane prose tests
    are rebuilt from the README;
  - `docs/AGENT-TEAMS.md`: the intake and how the human is asked;
  - `docs/SECURITY-SIMPLE.md`: capability tiers, email never decides, the Telegram amendment;
  - `docs/CONFIGURATION.md`: channel documents and the three pod keys;
  - `docs/QUICK-START-DOCKET.md`: `docket inbox`;
  - `docs/contracts/operator-v1/README.md`: the standards map and the A2A table;
  - `CHANGELOG.md`.
- CI docs job: add `gen_operator_schemas.py --check`. Run `metrics.py --check`. Archive the
  board with `split_board.py`.
## ☑ WAVE 73 COMPLETE — Phase 35 CLOSED 2026-10-04 — docket in a harness-agnostic factory (D-51), Waves 71–75 (opened 2026-09-29)

**Phase 35 CLOSED 2026-10-04 (Wave 73 rollup, card P35-10).** All ten cards are DONE, and the
phase's oracle is the harness contract 1.1 seam, not a green card. Wave 73: P35-6 `83d82b2`
(written paths, `--token-file`, caller limits), P35-10 integrator (seam test `f02f5f6`, live-run
record `f7e26fc`, doc corrections `9c8ff7d`, harness-mode spec 1.4.0 `58a435b`, CONTRIBUTING counts
`c9075ee`, this rollup). Wave 74: P35-9 `09308aa` (`--recipe` runs). **P35-11** `3aee5a4` (typed
`approvals` on the v1.1 result) has no card block on this board; its spec text is harness-mode 1.4.0.
**Decisions in P35-9:** (a) `run_recipe_task` takes no `env` parameter, because the approval mode
travels as the ephemeral pod's Lead `approvalMode` setting, which dispatch reads on every hop;
(b) `--verify CMD` is added, because `requireVerify` without a verify command fails every hop;
(c) `--max-tokens` and `--agent-id` are refused with `--recipe`.
**Wave 72 caveats, at close:** (1) the env parameter: **resolved by design**, decision (a).
(2) a denied or timed-out approval reads as a clean run: **closed by P35-11**; `status` and the exit
code are unchanged by design, and a caller reads `approvals`. (3) `TOOL_APPROVAL_TIMEOUT` is
process-wide for the run: **carried to the next phase**; the per-run route needs an env seam in
dispatch that the owning card's list did not include, and `wait_budget` sets the attribute and
restores it. (4) the lint failure: resolved in `ad64810`. (5) the answer reader is a daemon thread
(`cli/_harness_answers.py::serve`) that is not joined and blocks in `sys.stdin`: **carried to the
next phase**, because interrupting that read needs a select-based reader.
**Live run (ADR 0017, "Live run"):** `--recipe software` is refused (it is a pod blueprint, not a
recipe; exit 2); `--recipe tdd` ends `failed` at the check-red gate (exit 1); `--answers stdin` with
a declined `bash` approval ends `status` `ok` (exit 0) with `approvals` `declined`, which is the
caveat-2 shape observed live.
**Tack M3 handoff (each of the four items present):** (1) process-group events: `e7dc098`;
(2) stdout question answered on stdin: `75b7e3f`, with typed `approvals` in `3aee5a4`;
(3) written-path list: `83d82b2`; (4) token on stderr or `--token-file`: `83d82b2`.
A commit cannot name its own hash, so the P35-10 status line names the rollup commit by role.

**Wave 72 done 2026-10-03** — P35-8 `920076b` (CONTRIBUTING counts re-trued `82d3117`), P35-7
`9537491`, P35-5 `75b7e3f`; merged to `develop`, not pushed; each branch gated green after
rebase. P35-5 and P35-7 were cut from the stale `6525b52`; P35-5/P35-7 reset to `f394be2`
after finding it, P35-8 did not and was rebased. Rollup commit: spec bumps (harness-mode 1.3.0,
security-gates 0.29.0, pod-dispatch 6.26.0), item 8 of security-gates corrected. **Caveats carried
forward:** (1) P35-7's `run_recipe_task` has **no `env` parameter** the packet named: dispatch has
no caller-env seam and `core/dispatch.py` was not on its list. P35-9 must settle how a recipe run
gets a per-run `DOCKET_APPROVAL_MODE` before it can pass `wait`. (2) P35-5: a denied or timed-out
approval ends as a tool result, run status `ok`, exit 0; a caller reading only exit or status
cannot tell it from a clean run. Visible on trace and audit only. Decide at the Phase 35 close
whether the result carries it. (3) P35-5 sets `TOOL_APPROVAL_TIMEOUT` process-wide for the run
(the env route needed edits outside its list). (4) A pre-existing `ruff` failure in
`tests/unit/core/test_context.py` (P35-1's test) was fixed in `ad64810` so the lint gate is green.

**Wave 71 done 2026-09-29** — P35-1 `9dd0a7f`, P35-2 `7b42f86`, P35-3 `e7dc098`, P35-4 `44e35e4`,
harness-mode.spec.md's P35-3 stub reconciled `72cebea`, spec version bumps `c90d4e6`. All merged
to `develop`, not pushed. Full gates (pytest, ruff, mypy, golden suite, validate-specs, guards,
comment-lint, gen_cli_docs/config/operator-schemas --check, metrics --check, secret-grep) green
after every merge. Two of the isolated worktrees this wave used branched one commit behind the
stated base and two workers committed the difference (deleting this section's own ADR/packets
files) before noticing; recovered by hand-extracting each worker's legitimate diff against the
true base rather than merging its commit as-is. A worktree-base self-check (`git merge-base HEAD`
against the stated base commit before any commit, diffed against that same base, never against a
worker's own `HEAD`) is worth adding to the worker packet template for the next wave.

**Opened 2026-09-29 at `6525b52`.** Ten cards in five waves. Decision, reversals, cut and
deferred lists: [docs/adr/0017-docket-in-a-harness-agnostic-factory.md](docs/adr/0017-docket-in-a-harness-agnostic-factory.md).
Worker packets: [.agents/handoffs/wave-71-worker-packets.md](.agents/handoffs/wave-71-worker-packets.md).

**Trigger (explicit request plus facts read on the live path and in the consumer, 2026-09-29).**
The maintainer asked for docket's part of the structured-agentic-engineering plan to be
architected into the roadmap for parallel Sonnet workers, setting existing ADR limits aside
(each reversal is recorded in ADR 0017). Read at `6525b52` and in Tack at `7718420`:
- Tack's U8 is blocked because docket ships no `harness-v1.1` (Tack `docs/plans/phase-65.md`,
  M3 "done 2026-09-20: absent"). It needs four items: a process-group event, a stdout question
  answered on stdin, a written-path list, and the token on stderr or `--token-file`.
- Tack declares docket `decisions: Unsupported`, `artifacts: Advisory`, `cancel: Advisory` and
  passes it no policy or budgets (Tack `crates/tack-runner/src/harness/docket.rs::capabilities`).
- A passing verify's output is discarded and a missing `verifyCmd` advances
  (`core/dispatch.py::_evaluate_mechanical_gate`); `diff_ref` is a branch, not a commit
  (`_implementer_diff_probe`).
- Two defects: `guardrail_block` writes the policy id into `action`
  (`_enqueue_pre_input_gate`, `_apply_output_guardrails`); `budget_for_role` ignores
  pod-scoped roles (`core/context.py`).

**Spec ownership rule (Phases 32–34 lesson).**
- A worker adds requirements under **its own new section heading**, numbered from 1 inside that
  section, and never touches `**Version**`, `**Status**`, `**Last Updated**` or a changelog. The
  integrator bumps each spec once per rollup.
- P35-2 adds a "Contract 1.1" section to `specs/api/harness-mode.spec.md` with **every** later
  harness subsection already stubbed (`Status: Planned — owned by P35-N`). A later card
  replaces only its own stub.

**Contract rule (the W30 seam lesson).** P35-2 owns every v1.1 model in `core/harness.py`.
Every later card builds its wire values through those models and never hand-builds a second
dict. `--contract 1.0` (the default) stays byte-identical: the four v1 fixtures and the v1
schema are the no-change oracle for every card.

**Test rule.**
- One RED behavioural test per card, in the module's `SUBJECT` file.
- A second test only for the card's fail-closed negative case.
- No real model and no real vendor host: every HTTP target is a local `http.server` on port 0.
  The only exception is P35-10's live run, and only against `127.0.0.1:8081`.
- Existing tests, goldens and specs are the no-change oracle, except where a card names the
  change.

| Wave | Cards (parallel inside the wave) | Hot file and function ownership |
| --- | --- | --- |
| 71 | P35-1 ∥ P35-2 ∥ P35-3 ∥ P35-4 | `core/dispatch.py::_enqueue_pre_input_gate`, `_apply_output_guardrails`, `_hop_message` (the one `budget_for_role` call), `core/context.py::budget_for_role`, `core/session.py` (the one `budget_for_role` call), `role-archetypes.spec.md` → P35-1; `core/harness.py` (all v1.1 models, `HARNESS_CONTRACT_VERSIONS`), `scripts/harness_schema.py`, `docs/contracts/harness-v1.1/` (new), `tests/fixtures/harness-contract/v1.1/` (new), `cli/_harness.py::_flag`/`_usage_error` and the version selection in `_run`, `harness-mode.spec.md` "Contract 1.1" → P35-2; `edges/adapters/toolbox.py::run_bash`, `core/tools.py::ToolContext` (one field) and the `bash` handler lambda only, `core/trace.py::EVENT_TYPES` (+2), `core/telemetry.py::_STRUCTURAL_KEYS` (+2), `edges/adapters/docket_runtime.py` (the `ToolContext` construction), `trace-store.spec.md` → P35-3; `core/dispatch.py::_evaluate_mechanical_gate`, `_implementer_diff_probe`, `HopResult`, `_hop_record`, `_hop_from_record`, `edges/adapters/system.py` (new `git_head_sha`, `git_merge_base`, `git_diff_stat`), `pod-dispatch.spec.md` → P35-4 |
| 72 | P35-5 ∥ P35-7 ∥ P35-8 | `cli/_harness.py::_run` (answer wiring only), `cli/_harness_answers.py` (new), `core/approval.py::approval_create` (trace payload only) → P35-5; `core/harness_pipeline.py` (new), `core/pod_provisioning.py` (an in-place member path, no worktree) → P35-7; `core/pod.py::PodSettings` (`requireVerify`), `core/dispatch.py::_evaluate_mechanical_gate` (the `not verify_cmd` branch only), `pod-dispatch.spec.md` new section → P35-8 |
| 73 | P35-6 | `cli/_harness.py::_run` (pre-turn token file, limits, policies; post-turn files), `core/harness.py::result_from` (the `files` argument), `edges/adapters/docket_runtime.py` (pop `DOCKET_TURN_TOKEN_BUDGET`), `core/runtime_driver.py` (one constant) |
| 74 | P35-9 | `cli/_harness.py::_run` (the `--recipe` branch), `core/harness.py` (`task` block builder) |
| 75 | P35-10 (integrator) | seam test, live run, docs corrections, spec bumps, rollups, archive |

`cli/_harness.py::_run` is owned by exactly one card per wave (P35-2, P35-5, P35-6, P35-9 in
that order). No other card edits it.

Every card follows the §"How to use this board" definition of done.

### P35-1 — two measured defects: `guardrail_block.action` and pod-scoped role token budgets

**Status:** DONE (`9dd0a7f`) · **Size:** S · **Wave:** 71 · **Model:** Haiku · **Spec:**
`role-archetypes.spec.md` 1.21.0, new section "Pod-scoped token budgets"

**Trigger:** deterministic defects read at `6525b52`.
- `core/dispatch.py::_enqueue_pre_input_gate` and `_apply_output_guardrails` write
  `"action": hit.policy_id` into the `guardrail_block` payload. Expected: `hit.action`. The
  `guardrail_check` line just above each writes it correctly.
- `core/context.py::budget_for_role` calls `_arch.load_registry()` with no project. A
  `tokenBudget` declared on a pod-scoped role (written by `pod apply` through
  `core/archetypes.py`) is never read at `core/dispatch.py::_hop_message` or in
  `core/session.py`. This is the same shape as the Phase 30 `resolve_role_model(..., project=)`
  defect.

**Goal:**
- Both `guardrail_block` payloads carry `"action": hit.action`.
- `budget_for_role(role, *, project: str = "", context_window_tokens=..., max_output_tokens=...)`
  resolves `load_registry(project)` when a project is given, and the global registry otherwise.
- Both callers pass their project.

**Non-goals:** any other trace payload; changing budget defaults.

**Acceptance:**
- A pod whose applied role `implementer` declares `tokenBudget: 1234` gets `1234` from
  `budget_for_role("implementer", project=<pod>)`. The global call still returns the built-in
  value.
- A `pre_input` block and a `pre_output` block each write a `guardrail_block` record whose
  `action` equals the policy's action (`block`), not its id.

**RED:** the pod-scoped budget test in `tests/unit/core/test_context.py` fails at the base
(returns the built-in budget).

### P35-2 — the harness contract v1.1: models, schema, fixtures, `--contract`

**Status:** DONE (`7b42f86`) · **Size:** M · **Wave:** 71 · **Model:** Sonnet · **Spec:**
`harness-mode.spec.md` 1.2.0, new section "Contract 1.1", with stubs for P35-5, P35-6, P35-9
(the P35-3 stub was reconciled to "Implemented and live" in `72cebea` once that card merged)

**Trigger:** ADR 0017 §1–2; Tack M3.

**Goal:**
- `core/harness.py`:
  - `HARNESS_CONTRACT_VERSIONS = ("1.0.0", "1.1.0")`; `HARNESS_CONTRACT_VERSION` stays
    `"1.0.0"`.
  - `HarnessEvent` and `HarnessResult` validate `v` exactly against the version they were built
    for. Keep the v1.0 classes unchanged; add `HarnessEventV11` and `HarnessResultV11`, or a
    version-parameterised validator, whichever keeps the v1.0 schema byte-identical.
  - New v1.1 models:
    - `FileChange{path, op: "write"|"edit"|"delete"|"unknown"}`;
    - `AnswerLine{v, token, answer: {approvalToken: str|None, questionId: str|None, action:
      "accept"|"decline"|"cancel", content: dict|None}}`, where exactly one of
      `approvalToken`/`questionId` is set;
    - `HarnessTask{status, hops: list[dict], evidence: dict|None}`;
    - `HarnessResultV11` = v1.0 fields + `files: list[FileChange] = []` + `task: HarnessTask |
      None = None` + `limits: {maxTokens: int|None}`.
- `scripts/harness_schema.py` writes both `docs/contracts/harness-v1/schema.json` (unchanged)
  and `docs/contracts/harness-v1.1/schema.json`, including `AnswerLine`.
- Fixtures at `tests/fixtures/harness-contract/v1.1/`: `ok-files.ndjson`,
  `asked-answered.ndjson` (an `approval_requested` event, then an ok result),
  `cancelled-process.ndjson` (`process_started`/`process_exited` with `signal`),
  `recipe-ok.ndjson` (a result with a `task` block), `answer-lines.ndjson` (stdin lines). Each
  line validates against the committed v1.1 schema.
- `cli/_harness.py`: `--contract 1.0|1.1` (default `1.0`). An unknown value is refused (exit 2).
  The chosen version is stamped on every emitted line. No other v1.1 behaviour yet.

**Non-goals:** process events, stdin, files, recipe execution (later cards fill their stubs).

**Acceptance:**
- `docket harness run --contract 1.1 ...` against the fake endpoint emits lines with `"v":
  "1.1.0"` that validate against the v1.1 schema.
- The same run without `--contract` is byte-identical to the base on the four v1 fixtures'
  scenarios.
- `--contract 2.0` → exit 2, one refused result.
- The v1 and v1.1 schema pins both hold.

**RED:** the v1.1 schema-pin test fails at the base (the file does not exist).

### P35-3 — process lifecycle events and cancellable process groups

**Status:** DONE (`e7dc098`) · **Size:** M · **Wave:** 71 · **Model:** Sonnet · **Spec:**
`trace-store.spec.md` 1.4.0, new section "Process lifecycle events"; the `harness-mode.spec.md`
stub reconciled in `72cebea`

**Trigger:** ADR 0017 §2; Tack M3 item 1 ("an event per child process group started").

**Goal:**
- `edges/adapters/toolbox.py::run_bash` accepts `on_process: Callable[[str, dict], None] | None
  = None`. After `Popen` it calls `on_process("started", {"pgid": proc.pid})`. On every exit
  path (normal, non-zero, timeout, cancellation) it calls `on_process("exited", {"pgid",
  "exitCode" | "signal"})`, exactly once per start.
- `core/tools.py::ToolContext.on_process` (one field, default `None`). The `bash` handler
  lambda passes it, closing over `tool` and `callId`. No other change in `core/tools.py`.
- `core/trace.py::EVENT_TYPES` gains `process_started` and `process_exited`.
  `core/telemetry.py::_STRUCTURAL_KEYS` gains their structural keys (`pgid`, `tool`, `callId`,
  `exitCode`, `signal`).
- `edges/adapters/docket_runtime.py` builds `ToolContext.on_process` to:
  - emit the trace event;
  - call `core/runs.py::add_hop_pid(current_run_id(), pgid)` on start and `remove_hop_pid` on
    exit, when a run is current.

  `docket runs cancel` and harness SIGTERM then reach a live tool's process group.

**Non-goals:** harness-specific output (the trace already streams to stdout); MCP server
processes (Phase 38).

**Acceptance:**
- A turn whose `bash` call runs `sleep 30` under a run emits `process_started` with a live pgid.
- `docket runs cancel <run>` kills that group within the grace period and a `process_exited`
  with `signal` follows.
- A normal command emits one started/exited pair with `exitCode: 0`.
- No `bash` call → no process events (byte-identical trace otherwise).

**RED:** the start/exit pair test in a new `tests/unit/edges/adapters/test_toolbox.py`
(`SUBJECT = "docket.edges.adapters.toolbox"`) fails at the base (no callback parameter). The
cancel-kills-the-group case belongs beside `tests/integration/test_bash_cancellation.py`.

### P35-4 — pod dispatch keeps its evidence: verify output, commit, base, diffstat

**Status:** DONE (`44e35e4`) · **Size:** M · **Wave:** 71 · **Model:** Sonnet · **Spec:**
`pod-dispatch.spec.md` 6.25.0, new section "Hop evidence"

**Trigger:** ADR 0017 §4. `_evaluate_mechanical_gate` discards a passing verify's output;
`_implementer_diff_probe` records a branch name only.

**Goal:**
- `HopResult.verify: dict | None`, set by `_evaluate_mechanical_gate` on pass **and** fail:
  - `cmd`, `exitCode`, `durationS`;
  - `outputTail`: the last `VERIFY_EVIDENCE_TAIL_CHARS = 4000` characters, after
    `trace.redact`.

  The `verification_failed` trace event is unchanged.
- `_implementer_diff_probe` also returns:
  - `commit`: `git rev-parse HEAD` in the member's checkout;
  - `baseCommit`: merge-base of HEAD with the codebase's current branch;
  - `diffStat`: `{files, insertions, deletions}`.

  Each is `None` when not a repository. New `edges/adapters/system.py` helpers: `git_head_sha`,
  `git_merge_base`, `git_diff_stat`, which degrade to `None` like the existing git helpers.
- `_hop_record` persists `verify` and `evidence: {commit, baseCommit, diffStat}`;
  `_hop_from_record` round-trips them, and a legacy record without them loads unchanged.

**Non-goals:** committing on the agent's behalf; any CLI renderer (Phase 36); `requireVerify`
(P35-8).

**Acceptance:**
- A dispatched task with `verifyCmd: "echo ok"` persists a hop whose `verify.exitCode == 0` and
  whose `verify.outputTail` contains `ok`.
- A failing verify persists `exitCode != 0` and its redacted tail, and a stored secret value
  never appears in it (canary).
- In a git codebase the Implementer hop persists a 40-hex `commit`; outside git all three
  evidence fields are `None`.
- A hop record written at the base still loads.

**RED:** the passing-verify evidence test in `tests/integration/test_dispatch.py` fails at the
base (no `verify` key).

### P35-5 — questions on stdout, answers on stdin (`--answers stdin`)

**Status:** DONE (`75b7e3f`) · **Size:** M · **Wave:** 72 · **Model:** Sonnet · **Spec:** the P35-5 stub in
`harness-mode.spec.md`; `security-gates.spec.md` new section "The harness answer channel"

**Trigger:** ADR 0017 §2; Tack M3 item 2 and U8 `decisions: Supported`.

**Goal:**
- `--answers stdin` (v1.1 only; with `--contract 1.0` → exit 2):
  - sets `DOCKET_APPROVAL_MODE=wait` in `run_turn`'s env instead of `refuse`;
  - `--answer-timeout S` (default `TOOL_APPROVAL_TIMEOUT`) bounds each wait.
- Refused (exit 2) when the task comes from stdin: `--task-file` naming `-`, `/dev/stdin`, or
  `/proc/self/fd/0`.
- `cli/_harness_answers.py` (new): a daemon reader thread started around the turn.
  - It parses each stdin line as `core.harness.AnswerLine` and rejects a wrong `v`/`token`
    with one stderr line, ignoring the answer.
  - For an `approvalToken`: `content` (if any) passes `core.policy.policy_eval_detail("lead",
    "pre_input", text, trusted=False)`, then `accept` → `core.approval.approval_grant(t,
    channel="harness")` and `decline`/`cancel` → `approval_deny(t, channel="harness")`.
  - A `questionId` answer is accepted by the model and answered with a stderr "unsupported
    until a recipe run" line (P35-9 wires it).
  - It stops when the turn ends.
- `core/approval.py::approval_create`: the `approval_requested` trace payload adds `tool` and
  `callId` when the context has them. Nothing else changes.

**Non-goals:** a question tool for agents (Phase 36); HTTP; `park` in harness.

**Acceptance:**
- A scripted turn whose `bash` call needs approval emits `approval_requested` with `token`,
  `tool` and `callId`. Writing an `accept` line for that token runs the command and ends `ok`.
- A `decline` line denies it.
- No line within `--answer-timeout 1` denies (fail closed) and the run ends `blocked` or
  `failed` per the existing mapping.
- An answer whose content trips a `pre_input` block policy is refused and the approval stays
  pending until timeout.
- Every resolution writes an audit entry with `channel=harness`.

**RED:** the accept-line test in `tests/integration/test_harness_cli.py` fails at the base
(`--answers` unknown → exit 2).

### P35-6 — written paths, `--token-file`, and the caller's limits

**Status:** DONE (`83d82b2`) · **Size:** M · **Wave:** 73 · **Model:** Sonnet · **Spec:** the P35-6 stub in
`harness-mode.spec.md`

**Trigger:** ADR 0017 §2; Tack M3 items 3–4; Tack `additional: Unsupported` (policy and budgets
not passed).

**Goal (v1.1 only; each flag with `--contract 1.0` → exit 2):**
- **`files`:** the harness collects every `tool_call` record for `write`/`edit` from its own
  trace subscription (path from the arguments). When the workspace is a git repository it
  merges `git status --porcelain` (through `edges/adapters/system.py`). The result is
  deduplicated, relative to the workspace, and passed to `core/harness.py::result_from(...,
  files=)`.
- **`--token-file PATH`:** written atomically with mode 0600 **before** the turn starts. It
  contains `{"v","token","pid"}`. The stderr line `docket harness: run <token> agent=...` is
  pinned in the spec as the stable format.
- **`--max-tokens N`:** `run_turn` env key `DOCKET_TURN_TOKEN_BUDGET` (new constant in
  `core/runtime_driver.py`), popped in `edges/adapters/docket_runtime.py` into the loop's
  measured-token bound. The result echoes `limits.maxTokens`.
- **`--policy FILE`** (repeatable):
  - each file is validated with `core.policy.validate_policy`;
  - an invalid file → exit 2 before any run;
  - valid files are copied into the caller's `DOCKET_HOME` policies directory and are active
    for the turn.

**Non-goals:** diff content (the caller captures it); dollar budgets.

**Acceptance:**
- A scripted turn that writes `a.txt` and edits `b.txt` returns `files` with both.
- A git workspace with an untracked file written by `bash` also lists it.
- The token file exists, with mode 0600, before the first model request (assert from the fake
  endpoint's first request handler).
- `--max-tokens 10` stops the turn on the token bound.
- A `--policy` denying `bash` blocks a `bash` call; a malformed policy file exits 2 with no run
  created.

**RED:** the `files` test in `tests/integration/test_harness_cli.py` fails at the base.

### P35-7 — the in-place recipe runner (core)

**Status:** DONE (`9537491`; `env` parameter not added, see the Wave 72 block) · **Size:** M · **Wave:** 72 · **Model:** Sonnet · **Spec:**
`pod-dispatch.spec.md` new section "In-place ephemeral pods"

**Trigger:** ADR 0017 §3. Harness mode must run a pipeline without a second executor.

**Goal:** `core/harness_pipeline.py::run_recipe_task(workspace: Path, recipe: str, task: str, *,
model: str, approval_mode: str, timeout: int, env: dict) -> RecipeRun`, which does the
following in the current `DOCKET_HOME`:
- provisions an ephemeral pod `h-<run-token-prefix>` with `codebase = workspace`, whose members
  work **in place**. Add the smallest parameter to `core/pod_provisioning.py` so an Implementer
  skips `provision_worktree` and its `cwd` resolves to the codebase;
- sets every role's model to `model`;
- applies the recipe through `core/pod_apply.py::resolve_recipe` / `plan_apply` and the
  existing apply path;
- enqueues one task (`enqueue_task`);
- runs `dispatch_task` synchronously with the pod's `approvalMode` set to `approval_mode`;
- returns `RecipeRun{task: dict, hops: list[dict]}` from the persisted task record.

**Non-goals:** the CLI flag (P35-9); worktrees; tearing down the ephemeral pod (it lives in the
caller's disposable home).

**Acceptance:**
- With the scripted backend, `run_recipe_task(tmp_repo, "tdd", ...)` runs the recipe's steps in
  order.
- The Implementer's `bash`/`write` calls land inside `tmp_repo` itself (a file appears there,
  and no worktree directory is created).
- The returned hops match the persisted task.
- An unknown recipe raises the existing `resolve_recipe` error before any pod is provisioned.

**RED:** the in-place write test in `tests/integration/test_harness_pipeline.py` (new) fails at
the base (module missing).

### P35-8 — `requireVerify`: a missing verify command fails instead of advancing

**Status:** DONE (`920076b`) · **Size:** S · **Wave:** 72 · **Model:** Haiku · **Spec:**
`pod-dispatch.spec.md` new section "Required verification"

**Trigger:** ADR 0017 §4. `_evaluate_mechanical_gate` advances when `verifyCmd` is empty.

**Goal:**
- `core/pod.py::PodSettings.require_verify: bool = Field(False, alias="requireVerify")`, added
  to `KEYS` so `docket pod <p> config set requireVerify true` writes it.
- In `_evaluate_mechanical_gate`'s `not verify_cmd` branch, when the pod's setting is true:
  - trace `verification_failed` with `{"reason": "verification_missing", "member"}`;
  - return a `failed` outcome with reason `verifyCmd required but not set`.
- Otherwise the branch is unchanged.

**Non-goals:** changing the default; the harness flag (P35-9 sets the setting in recipe mode).

**Acceptance:**
- With `requireVerify: true` and no `verifyCmd`, dispatch ends the task `failed` with that
  reason and no Reviewer hop runs.
- With `false`, the base behaviour (`verification_skipped`) is byte-identical.
- `docket pod <p> config explain` shows the key.

**RED:** the required-verify test in `tests/integration/test_dispatch.py` fails at the base
(task advances).

### P35-9 — `harness run --recipe`: a pipeline for an external caller

**Status:** DONE (`09308aa`; decisions in the Phase 35 close paragraph) · **Size:** M · **Wave:** 74 · **Model:** Sonnet · **Spec:** the P35-9 stub in
`harness-mode.spec.md`

**Trigger:** ADR 0017 §3; the verdict table's "multi-role loop" row.

**Goal (v1.1 only):**
- **Arguments:** `--recipe NAME|DIR` is mutually exclusive with `--role`. With `--contract 1.0`
  it exits 2.
- **Execution:** `cli/_harness.py::_run` calls `core/harness_pipeline.py::run_recipe_task` with:
  - `approval_mode`: `wait` under `--answers stdin`, else `refuse`;
  - `requireVerify` set true on the ephemeral pod.
- **Result:** built through the P35-2 models:
  - `task` block: `status`, `hops` (role, stepId, ok, verdict, `verify`, `evidence`), `brief`;
  - `files` as in P35-6;
  - status mapping: task `done` → `ok`; `failed` → `failed`; a refused approval →
    `blocked`; `waiting_input` with no answer channel → `blocked`.
- **Answers:** `questionId` lines from P35-5's reader now route to
  `core.answers.answer_task` for the ephemeral pod's task.

**Non-goals:** new pipeline semantics; a second executor.

**Acceptance:**
- `docket harness run --contract 1.1 --recipe tdd --task-file t.md ...` against the scripted
  backend streams hop events and ends with a `task` block whose hops follow the recipe.
- A failing verify ends `failed` with that hop's `verify.exitCode`.
- The `intake` recipe's question, answered with a `questionId` line, reaches the Lead's re-entry.
- The emitted result validates against the v1.1 schema.

**RED:** the `--recipe` run test in `tests/integration/test_harness_cli.py` fails at the base.

### P35-10 — integrator: the consumer seam, a live run, doc corrections, close

**Status:** DONE (the Wave 73 rollup commit that adds this line; card commits `f02f5f6`, `f7e26fc`, `9c8ff7d`, `58a435b`, `c9075ee`) · **Size:** M · **Wave:** 75 · **Model:** the integrating session · **Spec:**
every Phase 35 spec: version, status and changelog bumps

**Goal:**
- **Seam test:** `tests/integration/test_harness_v11_consumer.py` drives the real `docket
  harness run --contract 1.1` subprocess the way Tack does. Task from a file, then:
  - read `process_started`;
  - answer an approval on stdin;
  - read `files`;
  - run `--recipe`;
  - cancel with SIGTERM and see `process_exited`.

  Every line is validated against the **committed** v1.1 schema file.
- **Live run** against `127.0.0.1:8081` (`DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`): one `--recipe
  software` run and one `--answers stdin` run. Record the result lines in the ADR.
- **Doc corrections:**
  - ADR 0016 §6 (Tack does not poll);
  - `docs/SECURITY-SIMPLE.md` (notifications exist since Phase 34; only `bash` is jailed);
  - the stale comment in `core/orchestrator.py`;
  - `docs/DEVELOPMENT-HARNESS.md` and the harness section of `docs/DOCKET.md`;
  - `CHANGELOG.md`; the README sentence on harness mode (D-37: describe what is now true).
- **Handoff note** for Tack's M3: each of the four items `present`, with its commit.
- Spec bumps, rollups, `scripts/metrics.py --check`, board archive.

**Acceptance:** all gates green; the seam test fails when any one card's piece is reverted
(prove it once for the answer line and once for `files`).

## ☑ WAVE 81 COMPLETE — Phase 36 CLOSED 2026-10-04 — consultation packs and evidence-v1 (D-53), Waves 76–81 (opened 2026-10-04)

Reasoning in [docs/adr/0018-consultation-packs-and-evidence-v1.md](docs/adr/0018-consultation-packs-and-evidence-v1.md).
Phase 35 closed at `184e02e` (archived in `docs/cycles-ended/todo-waves.md`). Phase 36 closed 2026-10-04
at the integrator close commit on `develop`; not pushed.

**Carried past the close (named, not parked as cards):** the parked consult question crosses to the
answering process through an in-process registry; `approve_task` is scoped to one turn;
`question.taskId` in a single-turn harness consult is the session key; options are not rendered in
Telegram or channel notifications (deferred by ADR 0018); a resumed role sees `REFUSED
[approval_parked]` before the operator answer, and the pod-dispatch park was not run against a real
model (ADR 0018 "Live run").

**Contract rule (the W30 seam lesson, as in Phase 35).** P36-1 owns every operator-v1.1 model,
and P36-3 owns every evidence-v1 model. Later cards build values through those models, never
through a hand-built dict. When a card adds a field to a published contract (operator, harness or
evidence), it regenerates that contract's schema with its generator script, never by hand, and
v1 bytes stay the same.

**Workers.** Each card runs in an isolated worktree that is reset to `develop` before editing. The
worker diffs from `git merge-base`, commits on its branch, and never merges, pushes, stashes, or
edits `TODO.md`/`ROADMAP.md`/`CONTRIBUTING.md`. The integrator rebases, gates, merges, and bumps
spec versions.

| Wave | Cards (parallel inside the wave) | Hot file and function ownership |
| --- | --- | --- |
| 76 | P35-12 ∥ P36-1 ∥ P36-2 | `cli/_harness.py::_touched_files` and its callers' snapshot, `core/dispatch.py::_evaluate_mechanical_gate` (verify fingerprint only), `edges/adapters/system.py` (status fingerprint) → P35-12; `core/operator_contract.py` (all v1.1 models), `scripts/gen_operator_schemas.py`, `docs/contracts/operator-v1.1/` (new), `operator-loop.spec.md` new section → P36-1; `core/approval.py::approval_grant`/`approval_deny`, `cli` approve/deny `--reason`, `serve.py` approval POST body (`reason` only), `security-gates.spec.md` → P36-2 |
| 77 | P36-3 | `core/evidence.py` (new), `core/dispatch.py::HopResult`/`_hop_record`/`_hop_from_record` and the hop's usage capture, `scripts/gen_evidence_schema.py` (new), `docs/contracts/evidence-v1/` (new), `pod-dispatch.spec.md` |
| 78 | P36-4 ∥ P36-5 ∥ P36-6 | `cli/_pod.py` (`evidence` branch), `serve.py` (the evidence GET route), `cli/_harness_recipe.py::_hop_view` → P36-4; `core/corrections.py` (new), one call each in `approval_deny`, `core/answers.py` decline, the Reviewer `REQUEST-CHANGES` site in `core/dispatch.py`, `cli/_pod.py` (`corrections` branch) → P36-5; `core/tools.py` (the approval request path), `core/agent_loop.py` (the rationale hand-off), `core/approval.py::approval_create`, the harness `approval_requested` payload → P36-6 |
| 79 | P36-7 ∥ P36-9 | `core/tools.py` (`_consult_tool`), `core/archetypes.py::BUILTIN_TOOL_KINDS`, `core/pod.py` (`maxConsultationsPerTask`), `cli/_harness.py`/`_harness_answers.py` (consult questions) → P36-7; `serve.py::render_metrics`, `cli` `metrics --escalation` → P36-9 |
| 80 | P36-8 | `core/dispatch.py` (consult park and re-entry), `core/answers.py` (consult answers) |
| 81 | P36-10 (integrator) | seam tests, live run, docs, spec bumps, rollup, archive |

`cli/_pod.py` is shared by P36-4 and P36-5 in Wave 78. Each adds exactly one `elif` branch and
its own `_pod_<verb>` function, and the integrator resolves the adjacent-line conflict.

Every card follows the §"How to use this board" definition of done.

### P35-12 — `files` stops reporting verify artifacts and pre-existing dirt (Phase 35 follow-up)

**Status:** DONE `c70ec56` (fingerprint snapshots of baseline-dirty and verify-produced paths; internal `verify.touched`) · **Size:** S · **Model:** Sonnet · **Spec:**
`harness-mode.spec.md` §4

**Trigger:** the P35-10 live run (ADR 0017 "Live run"): `files` listed `__pycache__/*.pyc`
produced by `--verify "python3 -m compileall -q ."`.

**Goal:** `files` means "what this run changed":
- paths dirty before the run and unchanged at the end are dropped;
- paths that appeared or changed only during a verify command are dropped;
- in both cases the model's own traced write/edit wins.

The mechanism is a snapshot (fingerprints), not a name list. Paths the model wrote with `bash`
still appear.

**Acceptance:**
- A verify artifact is absent from `files`, and the seam test asserts it.
- A pre-existing dirty file the run did not touch is absent.
- A pre-existing dirty file the run edited is present.
- The P35-6 bash-untracked test still passes.

### P36-1 — operator-v1.1: kind, options, recommendation, optionId

**Status:** DONE `d1ff7a0` · **Size:** M · **Wave:** 76 · **Model:** Sonnet · **Spec:** `operator-loop.spec.md`
new section "Contract 1.1"

**Goal:** in `core/operator_contract.py`:
- `QuestionKind` = `approval|clarification|decision`;
- `Option{id, label, description, risks: list[str], estimatedTokens: int|None}`;
- `Recommendation{optionId, rationale, evidenceRefs: list[str]}`;
- `QuestionV11` = `Question` plus `kind`, `options`, `recommendation`. A validator checks that
  the recommendation's `optionId` names an option and that option ids are unique;
- `AnswerResultV11` = `AnswerResult` plus `optionId`. With `action: accept` and options present,
  `optionId` is required and must name an option.

`scripts/gen_operator_schemas.py` also writes `docs/contracts/operator-v1.1/`.

**Non-goals:** any producer or consumer of the new models (P36-6, P36-7, P36-8); changing v1.

**Acceptance:**
- v1 schema files are byte-identical.
- The v1.1 schemas are generated, and the generator's `--check` mode covers them.
- Unit tests cover each validator: unknown `optionId`, duplicate ids, `accept` without
  `optionId`.

### P36-2 — approval grant and deny gain `reason` and `actor`

**Status:** DONE `8897657` + `70154af` (second commit: the `pre_input` screen of `reason`) · **Size:** S · **Wave:** 76 · **Model:** Haiku · **Spec:** `security-gates.spec.md`

**Goal:**
- `approval_grant(token, channel="unknown", *, actor="", reason="")` and the same for
  `approval_deny`.
- A non-empty `reason` is screened with `core.policy.policy_eval_detail("lead", "pre_input",
  reason, trusted=False)`. A blocked reason raises the module's existing error, and nothing is
  resolved.
- The audit detail gains `actor=` and `reason=` (redacted like every audit field), and the trace
  payload gains `actor` and `reason` when non-empty.
- Surfaces:
  - `docket approve|deny <token> --reason TEXT`, where the actor is the OS user;
  - the HTTP approval POST accepts an optional `reason` (the actor is the channel);
  - the harness stdin answer passes `content.reason` when it is a string.

**Non-goals:** Telegram/MCP reason syntax; storing reasons anywhere else (P36-5).

**Acceptance:**
- A CLI deny with `--reason` writes an audit line carrying the reason and actor.
- A reason that trips a `pre_input` block leaves the approval pending.
- With no reason, the audit line and trace payload are byte-identical to today.

### P36-3 — evidence-v1: the model, per-hop tokens and trace link, the schema

**Status:** DONE `bb62855` (trace link = session `agent:<project>:<taskId>` + a one-second window; usage `null` when the endpoint reports zero) · **Size:** M · **Wave:** 77 · **Model:** Sonnet · **Spec:** `pod-dispatch.spec.md`
new section "Evidence v1"

**Goal:**
- `core/evidence.py` holds the Pydantic models: `HopEvidence{role, stepId, ok, verdict, verify,
  commit, baseCommit, diffStat, usage{input, output}, trace{project, session, firstTs, lastTs}}`
  and `TaskEvidence{v: "1.0.0", pod, taskId, status, hops[]}`.
- `task_evidence(project, task_id) -> TaskEvidence` is the one builder, reading the persisted
  task record.
- Dispatch records each hop's measured `TokenUsage` (from the turn result, never estimated) and
  the trace session id plus first and last event timestamps on the hop record. That is the
  identifier `GET /traces` and `docket trace` accept, so verify it.
- `scripts/gen_evidence_schema.py` (with `--check`) writes `docs/contracts/evidence-v1/schema.json`.

**Non-goals:** surfaces (P36-4); scores or verdicts about the evidence (ADR 0017 §5); dollars.

**Acceptance:**
- A scripted 3-hop dispatch yields `task_evidence` with three hops and non-zero measured usage
  on each.
- The trace link resolves to that hop's events through the existing trace reader.
- The schema `--check` passes in CI's docs job.
- Old task records without the new fields still build (fields null).

### P36-4 — evidence-v1 surfaces: CLI, HTTP, harness

**Status:** DONE `f01f03c` (one builder behind CLI, HTTP and `task.evidence`) · **Size:** M · **Wave:** 78 · **Model:** Sonnet · **Spec:** `serve-read-api.spec.md`,
`cli-interface.spec.md`, `harness-mode.spec.md` §6

**Goal:**
- `docket pod <p> evidence <task> [--json]` (`--json` prints `task_evidence(...).model_dump_json`).
- `GET /tasks/<p>/<id>/evidence`, Bearer-authenticated like `/tasks/<p>`, 404 for an unknown
  task.
- The harness v1.1 recipe result's `task.evidence` is the same document.

All three call `core.evidence.task_evidence`.

**Acceptance:**
- One task's evidence through the CLI `--json`, HTTP and the harness compares equal.
- An unauthenticated GET returns 401.
- `gen_cli_docs --check` passes after the docs are regenerated.

### P36-5 — the corrections ledger

**Status:** DONE `f514658` · **Size:** M · **Wave:** 78 · **Model:** Haiku · **Spec:** `operator-loop.spec.md`
new section "Corrections"

**Goal:**
- `core/corrections.py::record(project, kind, *, task_id, role, text, source)`, where kind is
  `deny_reason|request_changes|declined_answer`. It appends one JSON line to
  `$DOCKET_HOME/corrections/<project>.jsonl` (D-12 exemption, file mode 0600, the text redacted
  like trace payloads), and `read(project) -> list[dict]`.
- Writers, one call each:
  - `approval_deny` when a reason is given;
  - `core/answers.py` on `decline`;
  - the Reviewer hop when its verdict is `REQUEST-CHANGES` (the hop output text, tail-bounded).
- `docket pod <p> corrections [--json]`.

**Non-goals:** deriving directives (cut by ADR 0018); a deny without a project (skip it).

**Acceptance:**
- Each of the three writers produces one line.
- The file is 0600.
- `corrections --json` round-trips.
- A failed write never fails the deny, answer or hop (log it to stderr through the existing
  helper).

### P36-6 — approval packs: rationale and three options

**Status:** DONE `0edeafd` (`approve_task` pre-grant lives in the turn's `ToolContext` only, so it does not cross a parked and resumed hop; the v1.0 stream strips the pack keys) · **Size:** M · **Wave:** 78 · **Model:** Sonnet · **Spec:** `security-gates.spec.md`,
`harness-mode.spec.md` §5

**Goal:**
- The assistant text content of the message that made a gated call becomes its `rationale`:
  screened with `pre_input` as untrusted (a blocked rationale becomes `""` and is traced), then
  truncated to `APPROVAL_RATIONALE_MAX_CHARS = 500`.
- `approval_create` stores `rationale` and `options` (three `operator_contract` v1.1 `Option`s:
  `approve_once`, `approve_task`, `deny`) on the approval record and on the `approval_requested`
  payload.
- The harness v1.1 stdin answer accepts `content.optionId`:
  - `approve_task` grants and records a single-task pre-grant through the existing pre-grant
    path;
  - `deny` uses `content.reason` (P36-2).

  Regenerate the harness v1.1 schema if a model changes.

**Non-goals:** rendering options in Telegram or notifications (deferred by ADR 0018).

**Acceptance:**
- A scripted turn whose message says "need to run the tests" before a gated `bash` call shows
  that rationale on `approval_requested`.
- A 2,000-char rationale is truncated.
- An injection-shaped rationale is blanked.
- `approve_task` pre-grants a second identical call in the same task.
- The v1.0 harness stream is byte-identical.

### P36-7 — the `consult` tool: single turn, harness stdio, refuse, the cap

**Status:** DONE `aeaa538` (`question.taskId` in a single-turn harness consult is the session key) · **Size:** M · **Wave:** 79 · **Model:** Sonnet · **Spec:** `operator-loop.spec.md`
"Consult", `harness-mode.spec.md` §5

**Goal:**
- A built-in `consult` tool, kind `read`, in `BUILTIN_TOOL_KINDS`. Its arguments are `kind`
  (`clarification|decision`), `message`, `options[]` (at least two) and `recommendation`, and
  they are validated through P36-1's `QuestionV11`. An invalid call is an error result.
- Under harness `--answers stdin`: the `question_asked` event (or the existing question event
  name, if one exists in `EVENT_TYPES`) carries the question. The stdin reader routes a
  `questionId` answer to the waiting call, and the tool result is the chosen option and content.
  `--answer-timeout` bounds the wait, and on timeout it returns "no answer, decide yourself".
- Under `refuse`: the turn ends `blocked`, and the question pack is in the v1.1 result.
- Pod setting `maxConsultationsPerTask` (default 3): past the cap the tool returns an error
  result without asking.

**Non-goals:** park and re-entry in pod dispatch (P36-8).

**Acceptance:**
- A scripted turn that consults and gets an answer line receives the chosen `optionId`.
- A consult without a recommendation is refused.
- The fourth consult in a task is refused without a question event.
- A Reviewer can consult.
- The result validates against the committed harness v1.1 schema.

### P36-8 — `consult` parks in pod dispatch and re-enters

**Status:** DONE `b6abb3d` (the parked question crosses processes through an in-process registry and fails closed out of process) · **Size:** M · **Wave:** 80 · **Model:** Sonnet · **Spec:** `operator-loop.spec.md`
"Consult"

**Goal:**
- Under `park` (and pod dispatch generally), a consult ends the hop with the task
  `waiting_input`. The question (P36-1 model, `kind`, options) goes on the task the way
  `_run_input_step` mints one.
- `answer_task` resumes **the same role's step**, with the answer in its next message.
- The inbox shows it under `needsYou`.
- The recipe-mode harness (`P35-9`'s answer source) answers it unchanged.

**Acceptance:**
- An Implementer consult parks the task.
- `docket pod <p> answer` with an `optionId` resumes the Implementer, and the answer is in its
  message.
- A declined answer resumes it with "declined", and P36-5 records it.
- `intake` behaviour is unchanged.

### P36-9 — escalation metrics

**Status:** DONE `2c29680` + `a30ef7e` + `42980b5` (the integrator fixed the approval source to read real audit actions and TRACES_DIR) · **Size:** S · **Wave:** 79 · **Model:** Haiku · **Spec:** `serve-read-api.spec.md`
metrics section

**Goal:** in `serve.py::render_metrics`:
- `docket_tasks_started_total` (dispatch claims, from the trace);
- `docket_questions_total{kind,outcome}` (from task `answers[]` and approval resolutions);
- `docket_decision_latency_seconds` as a summary (`_sum`, `_count`) from question `createdAt` to
  `answeredAt`.

`docket metrics --escalation` prints the same numbers as a table. These are lifetime-of-storage
counts, as CLAUDE.md limit 4 says.

**Acceptance:** a fixture home with two answered questions and one approval produces the
expected lines, and the metric names pass the existing name-format test.

### P36-10 — integrator: seams, live run, docs, close

**Status:** DONE in the close commit that archives this section (seams `1b73f03`, live run and docs `a8302d6`, spec bumps, counts) · **Size:** M · **Wave:** 81 · **Model:** the integrating session

**Goal:**
- **Seam tests:**
  - consult over the real `docket harness run --contract 1.1` subprocess, every line validated
    against the committed harness v1.1 and operator-v1.1 schemas;
  - evidence equality across CLI, HTTP and harness.

  Prove each red once by reverting one card's piece.
- **Live run** on `127.0.0.1:8081`: one consult and one approval pack.
- **Close:** docs (D-37), CHANGELOG, spec bumps, `metrics.py --check`, and the board archived
  with `scripts/maint/split_board.py`.

## ☑ WAVE 84 COMPLETE — Phase 37 CLOSED 2026-10-04 — verification-ready execution (D-54), Waves 82–84 (opened 2026-10-04)

**Opened 2026-10-04** (ROADMAP D-54, [ADR 0019](docs/adr/0019-verification-ready-execution.md)).
Every outline locator was re-verified at `9dd871f`. Two outline claims were false and are
corrected in ADR 0019:
- "recipes, no core change": a `run:` step gets no task id or base commit (P37-3);
- "an MCP pack as recipes": a recipe cannot declare an MCP server (P37-7).

Carried out of Phase 36, not scheduled here: the in-process consult registry, `approve_task`
scoped to one turn, the session key as `question.taskId` in a single-turn consult, and options
not rendered in Telegram or channel notifications (ADR 0018 "Cut and deferred").

**Workers.** Each card runs in an isolated worktree that is reset to `develop` before editing. The
worker diffs from `git merge-base`, commits on its branch, and never merges, pushes, stashes, or
edits `TODO.md`/`ROADMAP.md`/`CONTRIBUTING.md`/`README.md` counts. The integrator rebases, gates,
merges, and bumps spec versions. **`~/.docket` was wiped on 2026-10-04 and must not reappear**:
a test that creates it leaks into the real home and fails the card.

| Wave | Cards (parallel inside the wave) | Hot file and function ownership |
| --- | --- | --- |
| 82 | P37-1 ∥ P37-2 ∥ P37-3 ∥ P37-4 | `core/mcp_tools.py::_build_tool` (the handler), `mcp-client.spec.md` → P37-1; `core/pod_provisioning.py` (worktree provisioning and teardown), `core/pod.py::resolve_member_cwd`, `core/dispatch.py` claim, finalize, `_implementer_diff_probe`, `_prior_implementer_worktree`, `_when_cwd`, `workspace-structure.spec.md`, `pod-dispatch.spec.md` "Hop evidence" → P37-2; `core/dispatch.py::_run_command_step` plus one new helper, `edges/adapters/system.py::run_verify_cmd` (an `env` parameter), `pod-dispatch.spec.md` command-step section → P37-3; `core/agent_loop.py` (`StopReason`, `_TurnState`), `config.py` (one constant), `agent-loop.spec.md` → P37-4 |
| 83 | P37-5 ∥ P37-6 ∥ P37-7 | `templates/recipes/mutation/`, `templates/recipes/anti-tautology/` → P37-5; `templates/recipes/spec-writer/`, `templates/recipes/cross-family-review/` → P37-6; `core/pod_apply.py` (the `mcp-server` kind), `core/mcp_tools.py::load_mcp_servers` (pod scope), `core/pod.py::_parse_mcp_servers`, `templates/recipes/code-intel/`, `config-format.spec.md`, `mcp-client.spec.md` → P37-7 |
| 84 | P37-9 → P37-8 (integrator) | `edges/adapters/mcp_client.py::_stdio_params` and its turn-time callers → P37-9; then seam tests, live run, docs, spec bumps, rollup, archive |

`core/dispatch.py` is shared in Wave 82 at function level only: P37-2 must not touch
`_run_command_step`, and P37-3 reads the base commit from the prior hops' recorded evidence, never
from a worktree path. `docs/recipes.md` is regenerated by the integrator after Wave 83
(`scripts/gen_recipe_docs.py`).

Every card follows the §"How to use this board" definition of done.

### P37-1 — MCP tool results pass `pre_input`

**Status:** DONE `33377867` (audit `mcp_client.tool_result_blocked`/`_warn`; a failed call's error text is screened too) · **Size:** S · **Wave:** 82 · **Model:** Sonnet · **Spec:** `mcp-client.spec.md`

**Trigger:** `core/mcp_tools.py::_build_tool._handler` returns `call_tool(...)` unchanged, while
the same server's descriptions are screened (`_screen_description`).

**Goal:** the adapted tool's handler screens the result text with
`policy_eval_detail(ctx.role, "pre_input", text, trusted=False)`:
- `block`: `ToolOutcome(ok=False)` whose error names the policy and server, plus one audit entry;
- `redact`: the redacted text;
- `warn`: the text unchanged, plus one audit entry.

A result with no text passes as is.

**Non-goals:** built-in tool results; `fetch` (deferred in ADR 0019); description screening
(unchanged).

**Acceptance:**
- With a real baseline `pre_input` policy and a fake `call_tool` whose result carries an
  injection phrase, a live `dispatch_tool` call returns `ok=False` naming the policy.
- An audit entry names the server and tool.
- A clean result passes byte-identical.
- A redact policy returns the redacted text.

### P37-2 — one worktree per task

**Status:** DONE `f97380b0` (Lead stays on the codebase; in-place Implementers carry `inPlace`; the live smoke and doc-journey scripts still name the member `worktree/` -- P37-8) · **Size:** L · **Wave:** 82 · **Model:** Sonnet · **Spec:**
`workspace-structure.spec.md`, `pod-dispatch.spec.md` "Hop evidence"

**Trigger:** `_implementer_diff_probe` computes `baseCommit` as a merge-base with the codebase's
current branch, on a worktree that lives as long as the member. With nothing merged between
tasks, task 2's `diffStat` includes task 1's commits.

**Goal (ADR 0019 §1):**
- `docket add` no longer creates a worktree for a repo Implementer. The per-member worktree code
  path is deleted, with no fallback.
- At claim, dispatch creates `<member workspace>/tasks/<taskId>` on the branch
  `docket/<project>/<taskId>` from the codebase's HEAD. It records
  `task["worktree"] = {dir, branch, baseCommit}` through the existing task-list writer.
- Every hop, verify gate and `when`/command cwd of that task resolves to that directory. The
  re-entry of a parked task reuses it.
- Evidence `baseCommit` is the recorded commit, and `diffStat` is taken against it.
- Member removal removes its task worktrees and reports unmerged branches
  (`_teardown_worktree_branch`).
- When git is missing or `worktree add` fails, the task runs in place with a recorded reason, as
  the current fallback does.

**Non-goals:** merging branches; retention of finished worktrees; parallel tasks; harness
`--recipe` (in place by design, ADR 0017).

**Acceptance:**
- A real git repo and a scripted driver run two tasks back to back with nothing merged. Each task
  has its own branch and directory.
- Task 2's evidence `baseCommit` is its own creation commit, and its `diffStat` lists only task
  2's file.
- A parked-then-answered task resumes in the same worktree.
- `docket pod <p> remove <member>` leaves no worktree in `git worktree list`.
- Goldens are regenerated only where `add` output changes, with the diff explained line by line.

### P37-3 — command steps get the task's coordinates

**Status:** DONE `72d529d8` (finished by the integrator: the Haiku worker's test leaked into the real home and its fix patched `sys.path` in `tests/conftest.py`, so only its implementation shape was kept) · **Size:** S · **Wave:** 82 · **Model:** Haiku · **Spec:** `pod-dispatch.spec.md`
(the command-step section)

**Trigger:** `_run_command_step` calls `run_verify_cmd(cmd, cwd, timeout)` with the inherited
environment only, so a recipe cannot name the base commit (ADR 0019 §3).

**Goal:**
- `run_verify_cmd` gains an optional `env: dict[str, str] | None`, merged over `os.environ`.
- `_run_command_step` passes `DOCKET_TASK_ID`, plus `DOCKET_BASE_COMMIT` and
  `DOCKET_HEAD_COMMIT` from the latest `ok` Implementer hop in `prior`
  (`evidence["baseCommit"]`/`["commit"]`, empty string when absent).

**Non-goals:** the Implementer's verify gate; any worktree logic (P37-2).

**Acceptance:**
- A pipeline Implementer → `run: 'printenv DOCKET_BASE_COMMIT'`, driven by the existing scripted
  dispatch test helpers, records the Implementer hop's `baseCommit` in the command hop's output.
- With no Implementer hop, the variables are empty strings.
- `run_verify_cmd` without `env` behaves byte-identically.

### P37-4 — a `no_progress` stop reason

**Status:** DONE `b0ed9ef3` (`failure_kind=invalid_output`; the harness passes `failure_kind`, so no schema change) · **Size:** M · **Wave:** 82 · **Model:** Sonnet · **Spec:** `agent-loop.spec.md`

**Trigger:** one of four dispatches on 2026-09-18 ended `exceeded max_iterations=20` on the
16k endpoint. No bound notices repeated, unproductive rounds.

**Goal (ADR 0019 §4):**
- A round's fingerprint is the set of `(tool, canonical args, ok, result digest)` for its tool
  calls.
- When `AGENT_LOOP_NO_PROGRESS_ROUNDS` (default 3, `config.py`, an env override like its
  neighbours) consecutive rounds each have a fingerprint already seen in the turn, the turn stops
  with `stop_reason="no_progress"` and `ok=False`, and the error names the repeated tool.
- `LoopConfig` carries the value, and `0` disables it.
- Any surface that enumerates stop reasons (harness schema, dispatch failure text) is updated
  through its generator.

**Non-goals:** retrying, nudging the model, or cross-turn detection.

**Acceptance:**
- A fake chat port that repeats the same read call stops after exactly N+1 rounds with
  `no_progress`.
- An edit that flips a file A→B→A→B stops.
- A sequence whose results differ every round runs to `final_message`.
- `0` disables the check.
- The harness schema `--check` passes after regeneration.

### P37-5 — `mutation` and `anti-tautology` recipes

**Status:** DONE `afda0c67` (each check is one `python3 -c` command step that classifies `allow`; mutmut 3.8 scopes by file, not line; overrides read from the process environment) · **Size:** M · **Wave:** 83 (after P37-3) · **Model:** Sonnet · **Spec:**
`config-format.spec.md` (recipes)

**Goal:** two pipeline recipes under `templates/recipes/`, data only, built on P37-3's variables.
- `anti-tautology`: after the Implementer, a `run:` step fails when a test file added or changed
  since `DOCKET_BASE_COMMIT` passes on `DOCKET_BASE_COMMIT`.
- `mutation`: a `run:` step that mutates only the lines changed since `DOCKET_BASE_COMMIT` and
  fails below a stated threshold, using a mutation tool the recipe names. Its `description` says
  the tool must be installed.

Each command must classify `allow` under `core/security.py::classify_command`, or the recipe
documents the approval it asks for. **If a check cannot be written as a `run:` command without new
core code, stop and report the contention. Do not add core code.**

**Acceptance:**
- `docket validate` and `docket recipes show` accept both.
- A scripted dispatch over a real git repo fails `anti-tautology` on a test that passes on the
  base, and passes it on a test that fails there.
- The `mutation` recipe's command is exercised on a tiny repo when the tool is installed, and is
  otherwise marked skip with the reason.

### P37-6 — `spec-writer` and `cross-family-review` recipes

**Status:** DONE `6d293948` + `7567c717` (the integrator pinned both steps' models; the worker had left the Implementer on the pod default and pointed at the removed `docket auth set`) · **Size:** S · **Wave:** 83 · **Model:** Haiku · **Spec:** `config-format.spec.md`
(recipes)

**Goal:** two pipeline recipes under `templates/recipes/`, data only:
- `spec-writer`: a test-writing step with its own `model:` runs before the Implementer and is
  briefed to write tests from the brief alone.
- `cross-family-review`: a Reviewer step whose `model:` names a provider other than the
  Implementer's.

Both descriptions say the operator must have the named providers configured. Model names come
from built-in provider presets (`templates/providers/`), never invented.

**Acceptance:**
- `docket validate` and `docket recipes show` accept both, and the derived summary
  (`summarize_recipe`) names the pipeline.
- `docket pod <p> apply <name> --dry-run` lists the steps and their models.

### P37-7 — recipe-declared MCP servers and the `code-intel` pack

**Status:** DONE `032280d0` (documents under `mcp-servers/`, read/write declared as `access:` because `kind:` is the envelope; stored in the pod's `config/mcp-servers.json`; `code-intel` = ast-grep-mcp + mcp-language-server restricted to read tools) · **Size:** M · **Wave:** 83 (after P37-1) · **Model:** Sonnet · **Spec:**
`config-format.spec.md`, `mcp-client.spec.md`

**Goal (ADR 0019 §5–6):**
- A recipe may ship `kind: mcp-server` documents (the global server fields, including `kind:
  read|write` and `tools`).
- `docket pod <p> apply` installs them pod-scoped, the dry-run summary lists them, and
  `summarize_recipe` names them.
- `load_mcp_servers(project)` returns global plus that pod's servers. A pod's `mcpServers` may
  name its own servers, and another pod's may not.
- `templates/recipes/code-intel/` declares structural-search and language-server MCP servers by
  **real, verifiable package or binary names**. A server that cannot be verified is left out and
  named in the card report. Each is declared `kind: read` only where it truly cannot write.

**Non-goals:** auto-applying anything (ADR 0012); installing the servers' binaries.

**Acceptance:**
- Applying a recipe with one fake stdio server makes its tools reach a live turn for that pod
  only.
- A second pod cannot select it.
- `apply --dry-run` lists it without installing it.
- `pod export` round-trips it.

### P37-9 — stdio MCP servers start in the turn's root

**Status:** DONE `d99d7dba` (`cwd` is a runtime argument from the driver's `ctx.roots[0]`, never stored) · **Size:** S · **Wave:** 84 · **Model:** Sonnet · **Spec:** `mcp-client.spec.md`

**Trigger:** found integrating P37-7. `edges/adapters/mcp_client.py::_stdio_params` passes no
`cwd`, so a stdio server inherits the directory docket was started from. `code-intel`'s
`language-intel` server takes `--workspace .`, so under `docket serve --dispatch` it would index
the serve process's directory, not the task's worktree.

**Goal:** a stdio server spawned for a turn starts in that turn's resolved root. The root is the
same one the built-in file tools are confined to: the task worktree, else the codebase, else the
workspace. A server that declares an absolute path in its args is unaffected. Listing outside a
turn (`docket mcp servers test`, `config explain`) keeps the current directory.

**Non-goals:** jailing MCP servers (Phase 38); any change to http servers.

**Acceptance:**
- A fake stdio server that prints its working directory into a tool result, loaded for a pod
  turn, reports the task worktree.
- The same server listed outside a turn reports the process's working directory.

### P37-8 — integrate and close Phase 37

**Status:** DONE (this close: spec bumps, CHANGELOG, the member-worktree doc sweep, doc assets re-captured live, live two-task run in ADR 0019) · **Size:** M · **Wave:** 84 · **Model:** integrator

**Goal:**
- The two ADR 0019 seam tests (task worktree → evidence, evidence → command step).
- A live dispatch on the local endpoint: two tasks back to back on one pod, with evidence showing
  separate bases.
- Spec bumps, regenerated docs, README/CHANGELOG sentences, metrics, and the ROADMAP close; the
  section is archived.

## ☑ WAVE 88 COMPLETE — Phase 38 CLOSED 2026-10-05 — the execution envelope (D-55), Waves 85–88 (opened 2026-10-05)

**Opened 2026-10-05** (ROADMAP D-55, [ADR 0020](docs/adr/0020-the-execution-envelope.md)).
Every outline locator was re-verified at `25fe5252`. Three outline claims were corrected and one
item deferred in ADR 0020:
- file tools are not moved into a subprocess jail; a symlink walk is closed instead (P38-8);
- the lockdown does not change ADR 0004's open default (P38-4);
- docket has no credential issuer, so its own credentials are stripped instead (P38-6);
- `kind: autonomy` is deferred until a verifier produces one.

Two facts measured on 2026-10-05 shape P38-3: under bwrap a task worktree cannot `git commit`
(`.git/worktrees/<t>/index.lock: Read-only file system`), and docker's default image `alpine:3.20`
has neither `git` nor `python3`.

Carried, not scheduled here: finished task worktrees have no retention policy; the check recipes
read their overrides from the process environment; the four Phase 36 items (ADR 0018 "Cut and
deferred").

**Workers.** Each card runs in an isolated worktree that is reset to `develop` before editing. The
worker diffs from `git merge-base`, commits on its branch, and never merges, pushes, stashes, or
edits `TODO.md`/`ROADMAP.md`/`CONTRIBUTING.md`/`README.md` counts. The integrator rebases, gates,
merges, and bumps spec versions. **`~/.docket` must not exist**: a test that creates it leaks into
the real home and fails the card. Packets: `.agents/handoffs/wave-85-worker-packets.md`.

| Wave | Cards (parallel inside the wave) | Hot file and function ownership |
| --- | --- | --- |
| 85 | P38-1 ∥ P38-2 ∥ P38-3 ∥ P38-6 ∥ P38-7 ∥ P38-8 | `core/trace.py::_REDACT_PATTERNS`, `trace-store.spec.md` → P38-1; `core/tools.py::_fetch_tool`, `core/mcp_tools.py::_screen_result` (extracted into one shared screening function) → P38-2; `core/fleet.py::FleetSecurity` and its isolation readers/writers, `core/security.py` isolation wrappers, `edges/adapters/docket_runtime.py::_resolve_sandbox`, `edges/adapters/system.py::sandbox_availability`, `bwrap_argv`, `docker_run_argv`, `cli/_gates.py`, `cli/_doctor.py::_check_security_gates` (and its JSON twin), goldens `gates_status`/`help` → P38-3; `edges/adapters/system.py::run_verify_cmd`, `edges/adapters/toolbox.py::run_bash` (the unjailed env only) plus one new env helper → P38-6; `serve.py::_run_sweeps`, `_sweep_loop`, one `config.py` constant → P38-7; `edges/adapters/toolbox.py::resolve_within`, `glob_files`, `grep_files`, `write_file`, `edit_file` → P38-8 |
| 86 | P38-4 | `core/fleet.py` (a `network` flag), `cli/_gates.py` (`gates network`), `core/pod.py` settings (`network`), `system.py::bwrap_argv`/`docker_run_argv` (a network parameter), `docket_runtime.py` (the turn's network mode on `ToolContext`), `toolbox.py::run_bash` (passing it) |
| 87 | P38-5 ∥ P38-10 | `edges/adapters/mcp_client.py::_stdio_params` and its callers, `core/mcp_tools.py::load_mcp_tools` (a launch spec replacing the two `cwd` lambdas), `McpServerConfig.isolate`, `cli` `mcp servers add --no-isolate`, `docket_runtime.py::_load_mcp_tools` |
| 88 | P38-11 → P38-9 (integrator) | seam tests, live run, docs, spec bumps, rollup, archive |

`specs/functional/security-gates.spec.md` is shared by P38-2, P38-3, P38-6 and P38-8 at section
level: each worker edits only its own section and adds one `Unreleased` changelog line; the
integrator merges the changelog lines and bumps the version once. `toolbox.py` is shared in Wave
85 at function level only: P38-6 owns `run_bash`'s environment, P38-8 the file tools. P38-3 owns
the argv builders in Wave 85 and hands them to P38-4 in Wave 86.

Every card follows the §"How to use this board" definition of done.

### P38-1 — the redaction pattern matches only at a word start

**Status:** DONE `f426a32a` (integrator: the boundary lives in trace-store requirement 7, no renumbering) · **Size:** S · **Wave:** 85 · **Model:** Haiku · **Spec:** `trace-store.spec.md` (redaction)

**Trigger (measured live, 2026-10-04 and re-run 2026-10-05):** `trace.redact("task=task-<uuid>")`
returns `ta[REDACTED]`; the first `_REDACT_PATTERNS` entry's `sk|pk|api|key|tok|...` alternation
has no left boundary.

**Goal:** give that alternation a left boundary (not preceded by a letter or digit), so a label
matches only where it starts a word. `_` stays a boundary, so `api_key=<20+ chars>` and
`MY_TOKEN=<...>` are still redacted.

**Non-goals:** the other three patterns; the stored-secret pass; any new pattern.

**Acceptance:**
- `redact("task=task-8d627c86-9a63-4379-beee-ee3b2afff6f7")` is unchanged.
- `redact("risk=" + "a" * 24)` is unchanged.
- `redact("api_key=" + "A" * 24)`, `redact("key: " + "A" * 24)`, `redact("Bearer " + "A" * 24)` and
  `redact("token=" + "A" * 24)` each contain `[REDACTED]` and not the value.
- The existing redaction tests stay green unchanged.

### P38-2 — `fetch` results pass `pre_input`

**Status:** DONE `c8c61a7b` (integrator: one public `core.tools.screen_tool_result`; the policy is evaluated once) · **Size:** S · **Wave:** 85 · **Model:** Haiku · **Spec:** `security-gates.spec.md` (fetch section), `mcp-client.spec.md` (result screening, a pointer only)

**Trigger:** `core/tools.py::_fetch_tool` returns the page text as is, while
`core/mcp_tools.py::_screen_result` screens MCP results (ADR 0019 cut `fetch`; ADR 0020 §7).

**Goal:** extract `_screen_result` into one function that both the MCP handler and `_fetch_tool`
call, with the source named in the audit entry. `fetch` audits under `fetch.result_blocked` /
`fetch.result_warn`; the MCP audit actions are unchanged.

**Non-goals:** built-in tools other than `fetch`; the fetch allowlist; description screening.

**Acceptance:**
- With a real baseline `pre_input` policy and a fake HTTP response carrying an injection phrase, a
  live `dispatch_tool("fetch", ...)` returns `ok=False` naming the policy, plus one audit entry
  naming the URL's host.
- A clean page passes byte-identical; a redact policy returns the redacted text.
- The P37-1 MCP result tests stay green unchanged (one function, two callers).

### P38-3 — isolation on by default, bwrap first, a jail that can commit

**Status:** DONE `bf7d8cd1` + `c982046f` (integrator review: 95 tests depended on the host having bwrap, now `tests/conftest.py::record_isolation_off` per fixture; `.git/hooks`, `config`, `config.worktree` overlaid read-only; `isolationEnabled` and `get_isolation_mode` deleted) · **Size:** L · **Wave:** 85 · **Model:** Sonnet · **Spec:** `security-gates.spec.md` ("Workspace isolation" and its live-wiring and CLI sections), `cli-interface.spec.md` (gates/doctor lines)

**Trigger:** `FleetSecurity.isolation_enabled` defaults to `False`. Measured 2026-10-05: under
bwrap, `git commit` in a task worktree fails (`index.lock: Read-only file system`), and the docker
default image has no `git`/`python3`.

**Goal (ADR 0020 §1–3):**
- A `DOCKET_HOME` with no recorded choice is isolated. `gates isolate off` records an explicit,
  audited off; `isolate on` records on. The display shows `on (default)`, `on` or `off`.
- `sandbox_availability` tries bwrap first, then docker; `DOCKET_SANDBOX_BACKEND` still forces.
- `gates isolate on` and `doctor` probe `sandbox_availability` (no `shutil.which("docker")`).
  `doctor` reports the backend that a turn would use, or the refusal and its two fixes.
- The turn refusal (`isolation.refused`) names both fixes.
- `bwrap_argv` (and the docker `-v` mounts) add the git dir and common dir of every root that is a
  git worktree or repository, read-write.

**Non-goals:** the network (P38-4); MCP servers (P38-5); `run:`/`verifyCmd` (cut, ADR 0020).

**Acceptance:**
- With no `fleet.json`, a `DocketDriver` turn's `ctx.sandbox` is not `"off"` (the inverse of
  `test_isolation_off_leaves_ctx_sandbox_off`, which now writes an explicit off).
- With `DOCKET_SANDBOX_BACKEND=none` and no recorded choice, a turn is refused before any model call
  and the error names `bubblewrap` and `docket gates isolate off`.
- **Real bwrap** (skip with a reason when absent): `run_bash` jailed in a real git worktree runs
  `git add` + `git commit` successfully, and a write to a host path outside the roots fails.
- `sandbox_availability()` with both backends faked available returns `bwrap`.
- Every test that wants no jail says so in its own fixture; no autouse switch.
- Goldens `gates_status`/`help` regenerated only where the CLI text changed, each line explained.

### P38-4 — a network lockdown mode

**Status:** DONE `169e131d` (`gates network`, pod `network`, `network.refused`; docker `--network none` proven by argv only) · **Size:** M · **Wave:** 86 · **Model:** Sonnet · **Spec:** `security-gates.spec.md` (the D-23/D-24 egress section), `pod-dispatch.spec.md` (pod settings), `cli-interface.spec.md`

**Trigger:** neither backend cuts the network (`--share-net`, docker's bridge); ADR 0004 deferred
the mechanism. ADR 0020 §4.

**Goal:** `docket gates network none|open` (global, audited) and the pod setting `network`
(`none` only narrows a global `open`). Under `none`, `bwrap_argv` omits `--share-net` and
`docker_run_argv` adds `--network none`. `network none` with isolation off refuses the turn before
any model call. `fetch` is untouched. `gates status`, `doctor` and `config explain` show the mode
and its scope.

**Acceptance:**
- **Real bwrap:** under `none`, a jailed `python3 -c` socket connect to `1.1.1.1:53` fails, and the
  same call under `open` gets past socket creation. (No connection to a real host is required: a
  failed `socket.socket()` or `ENETUNREACH` is the oracle.)
- A pod with `network: none` under a global `open` gets `none`; a pod `open` under a global `none`
  stays `none`.
- `network none` + `isolate off` → the turn is refused, naming both settings.

### P38-5 — stdio MCP servers start in the jail

**Status:** DONE `2874490d` (`StdioLaunch`; `bwrap_command_argv`/`docker_command_argv`; the two `type: ignore`s are gone; the `kind: mcp-server` document cannot say `isolate: false` -- P38-11) · **Size:** M · **Wave:** 87 · **Model:** Sonnet · **Spec:** `mcp-client.spec.md`

**Trigger:** `mcp_client.py::_stdio_params` spawns the server on the host; `load_mcp_tools` threads
`cwd` through two `type: ignore` lambdas (carried from Phase 37). ADR 0020 §5.

**Goal:** a stdio server's `command`/`args` are wrapped by the turn's backend (roots, git dirs,
network mode) when isolation is on. A server declared `isolate: false` (`mcp servers add
--no-isolate`, audited, shown by `doctor`) starts unjailed. `load_mcp_tools` takes one launch value
(`cwd`, backend, network, roots) instead of the `cwd` lambdas, and the `type: ignore`s go.

**Acceptance:**
- **Real bwrap:** a stdio test server that writes outside the roots fails to; the same server
  declared `isolate: false` succeeds.
- Under `network none`, a jailed test server cannot open a socket.
- Isolation off: the argv is the server's own, byte-identical to before.

### P38-6 — a task's processes never see docket's credentials

**Status:** DONE `c10fb679` (`system.task_environment`; ~21 ms per call) · **Size:** S · **Wave:** 85 · **Model:** Sonnet · **Spec:** `security-gates.spec.md` (a "Credentials in task processes" section)

**Trigger:** `run_verify_cmd` passes `{**os.environ, **env}`; `run_bash` with `sandbox="off"`
inherits `os.environ`; both carry provider keys when the operator exported them. ADR 0020 §8.

**Goal:** one helper returns the host environment minus `DOCKET_LLM_API_KEY`, every credential
name the provider catalog declares, `TELEGRAM_BOT_TOKEN` and every name in the secret store. Both
call sites use it; the explicit `env` overlay still wins.

**Acceptance:**
- With `OPENAI_API_KEY`, `DOCKET_LLM_API_KEY` and a stored secret's name exported, a real
  `run_verify_cmd("env", ...)` output contains none of them, and still contains `PATH` and a
  harmless exported variable.
- An unjailed `run_bash("env")` gives the same result.
- `DOCKET_TASK_ID` passed through `env=` still arrives.

### P38-7 — one sweep worker per pod

**Status:** DONE `6b63cf4c` + `24debddd` (a shared scripted-turn test pinned to one worker) · **Size:** M · **Wave:** 85 · **Model:** Sonnet · **Spec:** `pod-dispatch.spec.md` (the serve sweep), `serve-read-api.spec.md` only if a route's output changes

**Trigger:** `serve.py::_run_sweeps` loops over `dispatchable_pods()` and runs each synchronously;
its own comment records that one blocking hop stalls the other pods. ADR 0020 §9.

**Goal:** each pod is swept in a worker; a pod with a sweep in flight is skipped until it ends;
at most `DISPATCH_SWEEP_WORKERS` (default 4) run at once. Run records, audit and trace stay what
they are per pod. `stop` ends the loop and waits for in-flight sweeps.

**Acceptance:**
- Two pods, one whose fake dispatch blocks on an event: the other pod's task reaches `done`
  while the first is still blocked.
- A second tick while pod A's sweep is in flight does not start a second sweep of A.
- With `DISPATCH_SWEEP_WORKERS=1`, sweeps are serial again.
- `stop` returns only after the in-flight sweeps end.

### P38-8 — file tools never follow a symlink out of their roots

**Status:** DONE `b1f3d7bc` + `5c6a31ec` (integrator: every walked path passes `resolve_within`, so a symlinked directory and a `..` selector are closed too) · **Size:** S · **Wave:** 85 · **Model:** Haiku · **Spec:** `security-gates.spec.md` (file-tool containment)

**Trigger:** `resolve_within` checks the requested path; `glob_files` and `grep_files` walk a root
and may meet a symlink to a host path. Not yet measured either way: the card's first step is the
RED test. ADR 0020 §6.

**Goal:** a path yielded by `glob`, or searched by `grep`, resolves inside the roots, or it is
skipped. `write`/`edit` refuse a target whose final component is a symlink that resolves outside.

**Acceptance:**
- A root containing `link -> /etc` (or a tmp dir outside the root): `glob("**/*")` lists no file
  under the target, and `grep("root")` returns no match from it.
- `write("link/x", ...)` is refused with `PathEscapeError`.
- A symlink that stays inside the root still works.
- If the RED tests pass before any change, the card closes as verified with the tests kept, and
  says so.

### P38-10 — a refused isolation or network posture is not retried

**Status:** DONE `d83360e3` (refusals raise `DispatchError`; harness `_invoke` now catches it, which the `run_turn` docstring had already claimed and the code had not done) · **Size:** S · **Wave:** 87 · **Model:** Sonnet · **Spec:** `pod-dispatch.spec.md` (retry and `dispatch_refused`), `security-gates.spec.md` (the two refusals)

**Trigger (measured in the 2026-10-05 live run):** with `gates network none` and `isolate off`, one
dispatch of one task wrote three `network.refused` audit entries 2 s and 4 s apart. Both posture
refusals (`_resolve_sandbox`, `_resolve_network` in `edges/adapters/docket_runtime.py`) return
`failure_kind="daemon_error"`, which `core/dispatch.py::_RETRYABLE_FAILURE_KINDS` retries. The
refusal is deterministic: a retry cannot succeed and only multiplies the audit trail.

**Goal:** both refusals take the existing deterministic-refusal path: `DocketDriver.run_turn`
raises `DispatchError` (as a stale `mcpServers` selection already does), dispatch settles the
task `failed` with `failureKind: dispatch_refused` (one attempt, resumable with `--resume` once
the operator fixes the setting), and the audit entry is written once. Harness mode keeps a coherent
result for the same refusal (read `cli/_harness.py`'s `DispatchError` handling; do not change the
published contract).

**Acceptance:**
- A pod dispatch under `network none` + `isolate off` makes exactly one turn attempt, writes one
  `network.refused`, and leaves the task `failed` / `dispatch_refused`; the same with no backend
  writes one `isolation.refused`.
- After `gates isolate on`, `dispatch --resume` reclaims and runs the task.
- The harness result for the same refusal is unchanged in shape (pin it with a test).

### P38-11 — a recipe's MCP server can declare `isolate: false`; `code-intel`'s ast-grep does

**Status:** DONE `3467c24d` (`doctor` does not list a pod's unjailed servers -- carried) · **Size:** S · **Wave:** 88 · **Model:** Sonnet · **Spec:** `config-format.spec.md` (the `mcp-server` kind), `mcp-client.spec.md`, `pod-blueprints.spec.md` (code-intel)

**Trigger (measured 2026-10-05):** `code-intel`'s `ast-grep` server is `uvx --from git+... ast-grep-server`.
Run through `system.bwrap_command_argv` with a warm cache it fails: `Could not acquire lock ...
Read-only file system (os error 30) at path "~/.cache/uv/.tmp..."`. With isolation on by default
the shipped recipe's server cannot start. P38-5 added `McpServerConfig.isolate`, but the
`kind: mcp-server` document (`core/mcp_tools.py::McpServerDocument`, its published schema) has no
such field, so a recipe cannot declare it and `pod apply` installs every recipe server jailed.

**Goal:** the document accepts `isolate: false` (default true), `pod apply` installs it into the
pod's `config/mcp-servers.json`, `pod export` writes it back, `docket validate` and
`recipes show`/`apply --dry-run` show it, and the apply step prints that the server runs
unjailed. `code-intel`'s `ast-grep` declares `isolate: false` and its README says why (measured);
`language-intel` stays jailed (its binary was not installed on the measuring host; the README says
to declare it if it cannot start). Schema regenerated with `gen_config_schemas.py`, recipe docs with
`gen_recipe_docs.py`.

**Acceptance:**
- Applying a recipe whose server says `isolate: false` stores it, and a turn's launch for that
  server is the server's own argv (no jail) while the recipe's other server is jailed.
- `pod export` round-trips the field (an apply of the export plans `skip`).
- A document without the field still loads jailed.

### P38-9 — integrate and close Phase 38

**Status:** DONE (seam tests in the cards; two live runs in ADR 0020; doc sweep `c4f69f84`; specs bumped `9df66adc`; CHANGELOG `0f0dc300`) · **Size:** M · **Wave:** 88 · **Model:** integrator

Seam tests owned by the integrator (ADR 0020 "Test discipline"): a default-on dispatch commits in
its task worktree; a jailed MCP server under `network none` cannot connect out; one screening
function, two callers. A live run on the local endpoint with isolation on by default (bwrap) and a
second under `network none`. Docs that say isolation is opt-in are rewritten (README,
`docs/SECURITY-SIMPLE.md`, `docs/QUICK-START-DOCKET.md`, the security-gates spec status line).
Spec bumps, CHANGELOG, metrics, board rollup and archive.
## ☑ WAVES 89–90 COMPLETE — the carried items, CLOSED 2026-10-05 (no phase; opened 2026-10-05)

**Trigger:** the operator asked on 2026-10-05 to close every item carried out of Phases 36–38. For
the two items deferred to a trigger (task-worktree retention, options in channels) that request is
the trigger: an operator asking. `kind: autonomy` and per-task credential minting stay deferred,
because nothing in the system produces an autonomy verdict or issues credentials. Scoping read
the live code paths (three read-only passes, 2026-10-05) and found one more jail escape: a linked
worktree's `.git` file and its admin files are writable from the jail.

Packets: [.agents/handoffs/wave-89-worker-packets.md](.agents/handoffs/wave-89-worker-packets.md).
Wave 89 (W89-1..5) runs in parallel; Wave 90 (W89-6..9) starts after Wave 89 is merged; W89-10
integrates and closes.

### W89-1 — `doctor`, `config explain` and `recipes show --json` show unjailed MCP servers

**Status:** DONE `2c3a7601` + integrator `35f022df` (one doctor helper; unit test instead of a layout-baseline entry) · **Size:** S · **Wave:** 89 · **Model:** Haiku · **Spec:** `mcp-client.spec.md` (Requirement 40, and the stale line saying the document has no `isolate`), `cli-json-shapes.spec.md` (`doctor --json`, `config explain` `tools.mcpServers`, `recipes show --json`), `cli-interface.spec.md` (`docket doctor` checks)

**Today:** `cli/_doctor.py` builds its unjailed list from `load_mcp_servers()` (the global registry)
and only in the human path; a pod's `isolate: false` server (from a recipe) is not listed and
`doctor --json` has no field. `cli/_config.py::_mcp_servers_report` emits name/kind/scope only;
`cli/_recipes.py::_info_dict` emits server names without `RecipeSummary.unjailed_mcp_servers`.

**Goal:** `doctor` (human and `--json`) lists every unjailed server, global and per pod (`name (pod
X)`), whenever isolation is not off; `config explain` (both renders) carries `isolate` per server;
`recipes show --json` and `recipes list --json` carry `unjailed_mcp_servers`.

**Acceptance:**
- A pod with a recipe-applied `isolate: false` server: `doctor --json` names it with its pod.
- `config explain <member> --json` shows `isolate: false` for that server and `true` for a jailed one.
- `recipes show code-intel --json` has `unjailed_mcp_servers == ["ast-grep"]`.

### W89-2 — the jail cannot rewrite git metadata the host later runs

**Status:** DONE `38988783` + integrator `908a13ac` (an absent `hooks/` or `info/attributes` is created empty, then bound read-only) · **Size:** M · **Wave:** 89 · **Model:** Sonnet · **Spec:** `security-gates.spec.md` (Workspace isolation, Requirement 4, and its example)

**Today:** `edges/adapters/system.py::_mount_dirs` re-binds read-only only the git dir's and common
dir's `hooks`, `config` and `config.worktree`. Still writable from the jail:
- a submodule's git dir (`modules/<name>/{hooks,config}`, nested `modules/a/modules/b`), so a hook
  or `core.hooksPath` there runs on the host's next git command in the submodule;
- in a linked worktree (every task worktree since Phase 37), the root's `.git` *file*: rewritten to
  `gitdir: <root>/evil`, it points the host's next git command at attacker hooks and config;
- the worktree admin files `<common>/worktrees/<wt>/{gitdir,commondir}`;
- `info/attributes` (selects filter/diff drivers; only live if a host config defines one).

**Goal:** `_mount_dirs` adds, read-only and only when present: every submodule git dir's `hooks`,
`config`, `config.worktree` (found by walking `modules/` for directories holding `HEAD`, without
running git in them); the root's `.git` when it is a file; the linked worktree's `gitdir` and
`commondir` admin files; `info/attributes`. A jailed `git add`/`git commit` in a linked task
worktree still works (objects, refs, index, logs stay writable). Both backends share `_mount_dirs`.
A submodule added inside the jail after it starts is out of scope; the spec says so.

**Acceptance (real bwrap, skip with a reason when absent):**
- A super-repo with a submodule (`-c protocol.file.allow=always`): from the jail, writing
  `modules/sub/hooks/post-commit` and `git -C sub config core.hooksPath /x` both fail; the host
  files are unchanged.
- In a linked worktree, rewriting `<root>/.git` from the jail fails and the host's `git -C <root>
  rev-parse --git-dir` still names the real git dir.
- The existing jailed-commit test still commits.

### W89-3 — a second stop signal makes `docket serve` abandon in-flight sweeps

**Status:** DONE `936b8a43` · **Size:** M · **Wave:** 89 · **Model:** Sonnet · **Spec:** `pod-dispatch.spec.md` (Sweep workers, and the "stop waits for in-flight sweeps" line), `serve-read-api.spec.md` (cancellation lifecycle note)

**Today:** `serve.py::run_serve` catches `KeyboardInterrupt` around `serve_forever`, then the
`finally` joins the sweeper, whose `_drain_sweeps` waits with no timeout. A second Ctrl-C raises
inside the join (a traceback) and the pool's threads still block exit; SIGTERM is not handled.

**Goal:** SIGINT and SIGTERM (main thread) drive a two-stage stop: the first stops accepting
work, prints one line (`stopping: waiting for N pod sweep(s); signal again to abandon`) and waits;
the second requests cancellation of every in-flight sweep run (`core/runs.py` cancel, recorded
per pod in `_sweep_one_pod`), cancels queued futures, waits a bounded few seconds for the runs to
settle, and exits 130 (SIGINT) or 143 (SIGTERM). Extract the logic into a small testable
controller. Read how dispatch handles a cancelled task (requeued or `cancelled`) and state it in
the spec; do not change it.

**Acceptance:**
- Unit: the controller's first signal sets stop only; the second sets abandon and requests
  cancellation of each recorded run id.
- Subprocess: a serve whose sweep blocks survives one SIGINT for a second, exits non-zero within a
  few seconds of the second, and the run record shows the cancellation request.

### W89-4 — `docket pod <p> worktrees prune` removes finished, merged task worktrees

**Status:** DONE `57b3d509` + integrator `d818f581` (a resumable failed task keeps its worktree; `git_branch_merged` reads the `+` marker) · **Size:** M · **Wave:** 89 · **Model:** Sonnet · **Spec:** `pod-dispatch.spec.md` (Task worktrees, new requirement), `cli-interface.spec.md` (the verb)

**Today:** a task's worktree (`<member>/tasks/<taskId>`, branch `docket/<project>/<taskId>`) is
removed only when its member is removed (`core/pod_provisioning.py::teardown_member`).

**Goal:** `core/pod_provisioning.py::prune_task_worktrees(project, *, force=False, dry_run=False)`
and `docket pod <p> worktrees prune [--dry-run] [--force]` (check how `docket pod <p> <verb>`
sub-commands are registered and follow that). It considers tasks in a terminal status with a
recorded `worktree.dir`; never a pending, running or waiting task. Default: remove the worktree
and delete the branch only when the branch is merged into the codebase's current branch and the
worktree has no uncommitted change; report every kept one with its reason. `--force` removes
unmerged/dirty ones and writes an audit entry. The `worktree.dir` must resolve inside the
member's task-worktrees dir before anything is removed. The task record gains
`worktree.prunedAt` via `edges/store.py`. Reuse the existing `system.py` git helpers; do **not**
edit `edges/adapters/system.py` (W89-2 owns it this wave); if a helper is missing, compose from
existing ones in `core/`.

**Acceptance (real git):** two finished tasks, one merged: prune removes the merged one's dir and
branch and records `prunedAt`, keeps and names the unmerged one; a running task is untouched;
`--dry-run` changes nothing; `--force` removes the unmerged one and audits it.

### W89-5 — options reach channel notifications, and Telegram `/answer` can pick one

**Status:** DONE `398b96fd` + integrator `d7dac7f6` (the inbox `TaskView` never carried `question`/`brief`: a sixth unwired-machinery instance, now wired) · **Size:** M · **Wave:** 89 · **Model:** Sonnet · **Spec:** `operator-loop.spec.md` (Notifications), `telegram-integration.spec.md` (`/answer`)

**Today:** `core/operator_contract.py::TaskView.question` is the base `Question`, so v1.1
`options`/`recommendation` are dropped before `core/notify.py::render_data`/`render_text` run;
Telegram `/answer <task> <text>` (`core/telegram.py::_handle_answer`) fills the question's single
schema property from free text, never `optionId`.

**Goal:** the view keeps the v1.1 question; at the `conversation` level (never `minimal`, since
labels are question content) `render_data` adds `options` (`id`, `label`) and `recommendation`
(`optionId` only) and `render_text` adds one line per option (`<id> - <label>`, `(recommended)`
on one) and `reply: /answer <task> <id>`. Labels are model text: strip control characters and
truncate. In Telegram, when the pending question has options and the answer text exactly equals an
option id, `/answer` sends `{"optionId": <id>}` through the existing `answer_task` path (same chat
authorisation, same `pre_input` screen); any other text keeps today's behaviour. Telegram stays
inbound-only: no new outbound call site in `core/telegram.py`.

**Acceptance:**
- `render_data`/`render_text` at `conversation` carry both options and the recommendation; at
  `minimal` neither appears.
- Telegram `/answer t1 iterative` on a consult question records `optionId=iterative`; a non-id text
  behaves as today.

### W89-6 — the docker jail is proven for real: commit and `network none`

**Status:** DONE `16f11fad` (real docker: commit with a git image, `network none` against a bridge listener; doctor probes the image) · **Size:** M · **Wave:** 90 · **Model:** Sonnet · **Spec:** `security-gates.spec.md` (Requirement 4 note on the docker image), `cli-interface.spec.md` (`doctor` check)

**Today:** `config.SANDBOX_DOCKER_IMAGE` defaults to `alpine:3.20` (busybox: no `git`, no `python3`),
so only bwrap is proven to commit, and docker `--network none` is proven by argv only
(`TestRealDockerJail` covers uid, env and timeout).

**Goal:** keep the default image (docket ships no image); document that the docker jail is only as
capable as `DOCKET_SANDBOX_IMAGE`, which needs `git` to commit. `docket doctor`, when the backend
in use is docker, probes the image once (`command -v git`) and warns with the fix. Real-docker
tests (skip with a reason when the daemon or the image build is unavailable): build a tiny test
image `FROM alpine:3.20` + `apk add --no-cache git` once per session; monkeypatch the image
constant (read at import); prove (i) a jailed `bash` commits in a linked task worktree and the
host sees the commit, (ii) with `network=False` a busybox `nc` connect fails, and (iii) as a
positive control it succeeds against a host-side listener with the network open.

### W89-7 — a `run:` step can carry `env:`; the check recipes use it

**Status:** DONE `4496818f` · **Size:** M · **Wave:** 90 · **Model:** Sonnet · **Spec:** `pipeline-format.spec.md` (Steps, command steps), `pod-dispatch.spec.md` (command-step environment), `pod-blueprints.spec.md` (anti-tautology, mutation)

**Today:** command steps get only `DOCKET_TASK_ID`/`DOCKET_BASE_COMMIT`/`DOCKET_HEAD_COMMIT` over the
serve process environment (`core/dispatch.py::_task_command_env`, `_run_command_step`), so the
`anti-tautology` (`ANTI_TAUTOLOGY_GLOB`, `ANTI_TAUTOLOGY_RUNNER`) and `mutation`
(`MUTATION_THRESHOLD`, `MUTATION_CMD`) overrides can only be set in the process that runs serve.

**Goal:** `Step.env: dict[str, str]` (`core/pipeline.py`), allowed only on `run` steps, keys
`^[A-Z][A-Z0-9_]*$`, refused for `PATH`, `LD_*`, `PYTHON*`, `BASH_ENV`, `ENV`, `DOCKET_*` and any
name `system.task_environment` strips as a credential. Carried through short form, planning and
export. Merged under the task coordinates (coordinates win). Values never reach the trace. The two
recipes declare their overrides as `env:` defaults and their READMEs say a pod overrides them by
editing the step. Regenerate config schemas and recipe docs.

**Acceptance:** a `run` step with `env: {FOO: bar}` sees `bar`; one declaring `DOCKET_BASE_COMMIT`
is refused at validation; `env` on a role step is refused; an export round-trips `env`.

### W89-8 — a parked consult's question travels with the denial; a harness consult names its run

**Status:** DONE `421d457b` + integrator `dfa77259` (the question is persisted 0600 under `consult-parked/`, not base64 in the token, which reached hop errors and the trace past redaction) · **Size:** M · **Wave:** 90 · **Model:** Sonnet · **Spec:** `operator-loop.spec.md` (Consult), `harness-mode.spec.md` (consult `question.taskId`)

**Today:** `core/consult.py` keeps parked questions in the in-process `_PARKED` registry;
`core/dispatch.py::_parked_consult_question` takes it while persisting the hop. When it is not
there (another process, a restart) the task goes `waiting_approval` on a `consult:` token that no
approval record can resolve: stuck. In a single-turn harness consult `question.taskId` is the
session key (`build_question`: `ctx.session_key or ctx.agent_id`).

**Goal:** `ConsultParked` carries the question; the denial result carries it to dispatch, which
reads it from the hop result; `_PARKED` and `take_parked` are deleted (no shim). A `consult:` token
with no question fails the task with a named reason instead of parking it as an approval.
`ToolContext.task_id` is set by the driver from the env route used for `DOCKET_APPROVAL_MODE`;
pod dispatch passes the task id, the harness passes its run token (or the caller's task id if the
harness accepts one); `build_question` uses `task_id`, falling back to the session key only when
neither exists. Operator schemas unchanged; regenerate if a description changes.

**Acceptance:** a dispatch whose turn parks a consult in a separate interpreter state (registry not
shared) ends `waiting_input` with the question; a harness consult's `question.taskId` equals the
run token, not `agent:...`; pod dispatch still sees the task id.

### W89-9 — `approve_task` grants the same call for the rest of the task

**Status:** DONE `83202b77` + integrator `e29b9de1` (a task grant reaches only hops of the role that asked) and `06474729` (HTTP and MCP channels) · **Size:** M · **Wave:** 90 · **Model:** Sonnet · **Spec:** `operator-loop.spec.md` (approval pack options, pre-grants), `pod-dispatch.spec.md` (task record), `harness-mode.spec.md` (scope wording), `telegram-integration.spec.md` (`/approve`)

**Today:** choosing `approve_task` takes effect only inside one turn's `ToolContext`; in pod
dispatch `resolve_waiting_approval` ignores `context.optionId`, so the next identical call in a
later hop of the same task parks again.

**Goal:** granting a parked approval with `approve_task` (CLI `docket approve ... --option
approve_task` or however the CLI names it today, and Telegram `/approve <token> task`) appends a
task-scoped grant `{tool, argsDigest, token, grantedAt, actor, channel}` to the task record;
`_compose_hop` mints one single-use pre-grant per entry for each later hop (existing
`create_pregrant`, bound to project and role), so every use is audited as today. Exact match on
`(tool, argsDigest)`, only on the `ask` path (never widens `deny`), at most 20 per task, dropped
when the task reaches a terminal status, never inherited by another task.

**Acceptance:** a task parks on a call, the grant uses `approve_task`, a later hop of the same task
runs the identical call without a new approval and the audit shows the use; another task with the
same call still parks; a different argument digest still parks.

### W89-10 — integrate, run it for real, refresh the screenshots and the README

**Status:** DONE (live runs and fixes `56ca8ffe` git identity in the jail, `73e44188` prune and untracked artifacts, `fb7bfa6a` a policy ask on consult; screenshots `4eeec5bc`; README `b16426c2`; guides `c7200c7a`; specs `02852079`; CHANGELOG `087e3538`; ADR 0020 and ROADMAP) · **Size:** M · **Wave:** 90 · **Model:** integrator

Cherry-pick each card, full gates per batch (also with `DOCKET_SANDBOX_BACKEND=none`), spec bumps,
CHANGELOG. Live runs on the local endpoint: a default-isolated dispatch with a submodule and the
`.git` rewrite attempt; a consult answered from Telegram-less `pod answer` with an option id and an
`approve_task` grant reused by a later hop; `worktrees prune`; a two-stage serve stop. Re-capture
the doc journey (`scripts/maint/capture-doc-journey.sh`), transcribe it into
`scripts/render-doc-assets.py` and regenerate the three assets; correct the README and the
guides where the run shows they are wrong, keeping the README at most 270 lines. Record the close
in ADR 0020, the deferral tables of ADRs 0018/0019 and ROADMAP.

## ☑ WAVE 95 COMPLETE — Phase 39 CLOSED 2026-10-08 — one CLI surface (D-57), Waves 91–95 (opened 2026-10-07)

**Decision:** ROADMAP D-57, [ADR 0022](docs/adr/0022-one-cli-surface.md). Read the ADR's
"Decision" section once; it is the contract every card below answers to. **Trigger (explicit
scoped request, 2026-10-07):** the maintainer asked for the CLI audit's recommendations to be
confirmed and applied in their strict form: every command that is not needed or is redundant is
removed outright, with no alias, no retirement notice and no memory of the old name; what remains
must say what it does and nest under what owns it; and the no-compatibility rule written into the
repository's rules. The result is eleven top-level commands (`init status inbox task run pod log
setup start stop exec`); the noun `pod` stays; `setup` with no verb is the guided first run;
every command speaks with one voice (ADR 0022 decisions 9 and 10). The audit's evidence is in the gitignored
`internal-docs/cli-ux-audit-2026-10-07/`; the facts a card needs are restated in the ADR's
evidence table and in the card itself.

**Shape of the work.** Twenty-four cards over five waves. Wave 91 is the foundation (no rename,
six parallel lanes). Wave 92 is one mechanical card that splits `cli/__init__.py` so every later
card owns one module. Wave 93 builds the tree, one group or sub-group per card. Wave 94 is help,
guards, documentation and assets. Wave 95 is the measurement that closes the phase. **One worker
per card in an isolated worktree based on `develop`; one integrator owns the rollups.** Packets:
[.agents/handoffs/wave-91-worker-packets.md](.agents/handoffs/wave-91-worker-packets.md).
Models: `Sonnet` for code and spec cards, `Haiku` for the documentation sweeps after the
mechanical rename script exists, `Integrator` for rollups, goldens, assets and the live run.

**Rules every card follows (in addition to the board rules above).**
- A removed name is deleted everywhere in the same commit: code, tests, spec text, `docs/`,
  `templates/`, `scripts/`, completions. No alias, no notice, no hidden command, no "was".
  `CHANGELOG.md` lines are returned to the integrator, not written by the card.
- A command with more than one operation is a Typer sub-app (`typer.Typer()` registered with
  `app.add_typer`), with Typer-declared arguments and options only; `ctx.args` parsing is gone
  from the module the card owns. A bare group prints its help (`no_args_is_help`). Every leaf's
  help ends with one `Example:` line.
- Pod-scoped commands take the pod from `cli/_target.py::resolve_pod` (P39-1); confirmations,
  `--json` emission, the non-TTY rule and hints come from `cli/_contract.py` (P39-2). No card
  hand-rolls a second copy of either.
- The card amends its owning spec section first (version bump + changelog line, pre-assigned in
  the packet), writes the RED test, implements, then runs the gates. One unit file per module
  (`tests/unit/cli/test_<module>.py`, `CliRunner`, in-process); exact text goes to the golden
  suite. Goldens are regenerated only for the cases the packet names, with every changed line
  explained in the return.
- The `exec` contract (events, result, exit codes), the HTTP routes, the MCP tool names and the
  Telegram verbs are frozen. `core/tools.py`, `core/agent_loop.py`, `core/policy.py`,
  `core/security.py` are not touched by any card in this phase.

**Wave map**

| Wave | Cards (parallel inside the wave) | Merge order | Contention notes |
| --- | --- | --- | --- |
| 91 | P39-1, P39-2, P39-3, P39-4, P39-5, P39-6 | 4, 6, 3, 5, 1, 2 | P39-4 owns `core/models_policy.py` wholesale and removes its specialist references, so P39-6 never touches it. P39-5 and P39-6 share `cli/_doctor.py` at function level (P39-6: the specialist check only). P39-1 and P39-6 share `cli/_agents.py` at function level. |
| 92 | P39-7 | — | Alone: it moves every command body out of `cli/__init__.py`. |
| 93a | P39-12, P39-13, P39-14, P39-15, P39-16 | 12, 13, 14, 15, 16 | Disjoint modules (`setup`, `log`/`start`/`stop`/`exec`, `run`/`status`/`inbox`, removals). P39-15 owns the dispatch functions of `cli/_pod.py`. |
| 93b | P39-8, P39-9, P39-10, P39-11 | 8, 9, 10, 11 | All take functions out of `cli/_pod.py` or build onto it; ownership is per function, named in each packet. Based on the 93a rollup. |
| 94 | P39-17, P39-18 first; then P39-19, P39-20, P39-21, P39-22; then P39-23 | 17, 18, 19–22, 23 | P39-18's script runs before any Haiku doc card. P39-19 (README) is Sonnet. |
| 95 | P39-24, P39-25 | 25 | P39-24 is the integrator on the live endpoint (no source files); P39-25 adds one script and one guard. |

**Wave 91 closed 2026-10-07** (six merges `5cbcac79`..`54bb3977` plus the integrator rollup). Follow-ups the workers returned are recorded in the packets file under "Wave 91 returns"; Wave 92 (P39-7) based on the rollup commit.

**Wave 92 closed 2026-10-07** (one merge `a99e0344` plus the integrator rollup): `cli/__init__.py` is a 177-line registry; the worker's return is under "Wave 92 returns" in the packets file. Wave 93a (P39-12, P39-13, P39-14, P39-15, P39-16) is next and bases on the Wave 92 rollup commit.

**Wave 93a closed 2026-10-07** (five merges `3633ed8d`, `7c4acba1`, `c81aac07`, `77ca8ed6`, `e29436be`, the integrator wiring `f61f1bac` and the rollup): the five groups exist (`setup` with `provider|model|notify|export|sandbox|mcp|shell`, `log`, `start|stop`, `exec`, `run`, `status`, `inbox`); 27 top-level commands remain. The workers' returns are under "Wave 93a returns" in the packets file. Wave 93b (P39-8, P39-9, P39-10, P39-11) is next and bases on the Wave 93a rollup commit.

**Wave 93b closed 2026-10-08** (seed `f54020ee`, four merges `f2dcfb4b`, `372c46d4`, `9fba00fb`, `2f1105e1`, the integrator release-lane pass `515a606b`, its completion `70b41380` and the rollup): `task` (`add|list|show|diff|trace|prune|approve|deny|answer|retry|cancel`) and `pod` (`show|add|remove|reset|set|unset|delete|apply|export|validate|plan|check|recipes|roles|policies`) are real groups; eleven top-level commands remain (`init status inbox task run pod log setup start stop exec`), the tree ADR 0022 names. The workers' returns are under "Wave 93b returns" in the packets file. Wave 94 (P39-17 and P39-18 first, then P39-19..P39-22, then P39-23) is next and bases on the Wave 93b rollup commit.

**Wave 94 closed 2026-10-08** (stage one: P39-17 `cc81c003` and P39-18 `254fba94` with the integrator fixes `55b77647` and `a5f04351`; the integrator pass `70fbec81`, `4aeedf8c` (`cli-interface` 2.0.0), `7ea2d5c3`; stage two: P39-21 `22861f7b`, P39-20 `305e05ed`, P39-22 `7a1a85ce`, P39-19 `d362eb5f`, with `c6b4cc53` and `dbc3b49d`; then the rollup): grouped help under one tagline, `-h` everywhere, the bare three-part guide, completions from the tree, the three CLI guards, the rename script and its guard over the whole tree, and every doc, template and spec on the eleven-command surface. P39-23's remaining items (Tack's one line, the live asset capture, the board archive) are listed on the card; the workers' returns are under "Wave 94 returns" in the packets file. Wave 95 (P39-24, the measurement) is next and bases on the Wave 94 rollup commit.

**Wave 95 closed 2026-10-08** (P39-24 `833e2366`, P39-25 merged, the rollup): the six journeys of the audit's live run were re-run against the Wave 94 rollup; none of the sixteen defects reproduces, the newcomer path types no pod name, a fresh machine reaches Ready through `docket setup` alone, every help level has an example, and the checklist scores 18/20 with the two exceptions named in ADR 0022 "Live run" (bare-name library readers; no hint switch). `scripts/maint/lint_cli_invocations.py` and its guard check every documented invocation against the live tree. The transcript's eighteen locators are the triage list for whatever follows; the returns are under "Wave 95 returns" in the packets file. Phase 39 is complete except P39-23's two user-owned items (Tack's `exec` line and the live asset capture) and the board archive.

### P39-1 — one pod resolver: `--pod`, `DOCKET_POD`, then the directory you stand in

**Status:** DONE (merged to `develop` 2026-10-07, `847c637c`) · **Size:** S · **Wave:** 91 · **Model:** Sonnet · **Spec:** `cli-interface.spec.md` (new section "Pod targeting" under "Global Command Structure")

**Trigger (ADR 0022 evidence):** the pod is named seven ways; only `status` and `add` infer it
from the cwd through `cli/_agents.py::_pod_for_directory`; `docket pod dispatch` inside the repo
answers `No pod found for 'dispatch'. Create one with: docket init dispatch` (exit 0).

**Goal:** one function, `cli/_target.py::resolve_pod(explicit: str | None, *, env: Mapping,
cwd: Path) -> str`, used by every pod-scoped command from Wave 93 on and by `status`/`add` now.
Order: explicit `--pod/-p` > `DOCKET_POD` > the registered pod whose codebase contains `cwd`,
deeper match wins. No match raises `TargetError` whose message names the lookup, the flag and the
fix: `No pod for <cwd> (looked for a registered codebase containing it). Run 'docket init'
here, or pass --pod <name>.` Two matches at the same depth name both. `cli/_target.py` also
exports `pod_option()` (one Typer option factory, `--pod/-p`, help text fixed) so every command
declares it identically. `_pod_for_directory` moves into `_target.py`; `cli/_agents.py` and
`cli/_status.py` import it from there.

**Non-goals:** touching any command beyond `status` and `add`; `--project` removal (Wave 93).

**Acceptance:** a home with pods `a` (codebase `/x`) and `b` (codebase `/x/sub`): from `/x/sub/deep`
→ `b`; from `/x` → `a`; `DOCKET_POD=a` from `/x/sub` → `a`; `--pod b` from `/` → `b`; from `/tmp`
with no env → `TargetError` with the exact message above; `docket status` from `/tmp` prints it,
exit 1. Oracle: the resolver's return value and the printed message; `fleet.json` untouched.

**RED:** `tests/unit/cli/test__target.py` (new, `SUBJECT = "docket.cli._target"`), the five cases
above, fails on the base with `ModuleNotFoundError`.

### P39-2 — one interaction contract and one console voice; bare `gates isolate` and bare `notify` stop writing

**Status:** DONE (merged to `develop` 2026-10-07, `54bb3977`) · **Size:** M · **Wave:** 91 · **Model:** Sonnet · **Spec:** `cli-interface.spec.md` ("Interactive Features", "Output Formats" rewritten as "The console voice", "Return Code Convention"), `security-gates.spec.md` (bare `gates isolate`), `operator-loop.spec.md` (bare `notify`)

**Trigger (ADR 0022 evidence):** three different off-TTY policies for destructive commands
(`delete <pod>` proceeds silently, `maintain` refuses, `exporters privacy` needs `--yes`); bare
`docket gates isolate` turns isolation on; bare `docket notify` delivers; `inbox --bogus` exits 0;
four taglines; `help` and `metrics` print raw ANSI when piped; tables truncate mid-word
(`require_approv`); every module writes its own `[green]`/`[red]` markup; `init`'s next steps
leave out the actual next thing to do.

**Goal (a): the contract.** `cli/_contract.py` with four functions and nothing else: `confirm(action,
*, yes, typed=None)` (TTY: y/N, or the typed name when `typed` is given; no TTY: refuse with exit 1
naming `--yes` or `--confirm <name>`); `emit_json(obj)` (plain `json.dumps` to stdout, never
Rich); `require_value(name, value, flag)` (no TTY and no value: exit 1 naming the flag; never a
picker); `next_step(command)` (one `→ Next: docket ...` line on stderr; silent under
`DOCKET_NO_HINTS=1`). `sys.stdin.isatty()` is probed in one module function tests can patch.

**Goal (b): the voice (ADR 0022 decision 9).** `ui.py` becomes the only place that knows
symbols, colours and layout: five symbols (`✓` done, `✗` failed or refused, `⚠` attention, `→`
next step, `·` detail), five colour roles (`success`, `error`, `warn`, `accent` for names and
ids and commands, `dim`), `header(noun, name)` rendering `docket · pod myapp`, `section(title)`
for the shared section names (`Needs you`, `Running`, `Done`, `Failed`), `table(rows, columns)`
that wraps cells and never cuts a word, `error(what, do)` rendering `✗ <what>. <do>` on stderr,
and plain output (no colour, no boxes, no symbols beyond ASCII `ok`/`x`/`!`/`->`) when stdout is
not a TTY or `NO_COLOR` is set. One tagline constant, `TAGLINE = "docket runs teams of coding
agents and governs what they may do"`, read by the bare greeting, `--help` and `pyproject`. A
shrink-only guard (`tests/guards/test_console_voice.py`, baseline committed) counts Rich markup
literals (`[green]`, `[bold]`, …) outside `ui.py`; every Wave 93 card lowers it for the modules it
rewrites. The copy rule for every later card, pinned in the spec: a command that changes state
ends with exactly one `→ Next:` line; a read command ends with none; an error is one line that
says what happened and what to do.

**Goal (c): two blockers now, one line each.** `cli/_gates.py::run_gates` defaults `want` to
`None` and bare `isolate` prints the status plus `Usage: docket gates isolate on|off`, exit 2,
nothing written, nothing audited; `cli/_notify.py::run_notify` treats `""` as unknown (usage,
exit 2); only `flush` flushes.

**Acceptance:** with stdin not a TTY, `confirm("delete pod x", yes=False)` exits 1 naming
`--yes`; with `typed="x"` it names `--confirm x`; `yes=True` returns. Piped stdout → `ui.success`
writes `ok ...` with no escape codes; a table with a 40-character cell in a 20-column width
wraps and every word survives. Fresh home → `docket gates isolate` → `fleet.json` and `audit.log`
byte-identical, exit 2; `docket notify` with one enabled channel and one pending event → the sink
receives nothing, exit 2. The voice guard is seen red by planting one `[green]` in a module
outside `ui.py`. Oracle: file bytes, the sink file, `json.loads`/regex over captured stdout.

**RED:** `tests/unit/cli/test__contract.py` (new), `tests/unit/test_ui.py` (new or existing
`SUBJECT = "docket.ui"`), one test each in `test__gates.py` and `test__notify.py` (new) for the
two bare commands; the gates and notify tests fail on the base with a written file / a delivered
event.

### P39-3 — one task id everywhere

**Status:** DONE (merged to `develop` 2026-10-07, `5cae754f`) · **Size:** S · **Wave:** 91 · **Model:** Sonnet · **Spec:** `pod-dispatch.spec.md` (new requirement "Task references")

**Trigger (ADR 0022 evidence, live run C6):** `pod queue` prints `task-04ff2ff5-7be8`; `chat`
rejects it; `trace` wants `agent:<p>:<task>`, which no command lists; `trace list` errors.

**Goal:** `core/task_ref.py::resolve_task(project: str | None, ref: str) -> TaskRef` resolves a
full id, the short id `task list` prints, or any unambiguous prefix, across one pod or (when
`project` is `None`) every pod; `TaskRef` carries `task_id`, `project`, `session_key`,
`run_ids` and the worktree path when one exists; a harness run id (what `harness status` took)
resolves to the `TaskRef` of the run record, so `task show <run-id>` can replace that command. An ambiguous prefix raises `TaskRefError`
listing every candidate with its pod; an unknown one raises it naming what was searched.
`core/dispatch.py` is read through its existing `read_tasks`; nothing there changes.

**Non-goals:** wiring the resolver into commands (Wave 93 cards P39-8, P39-9 and P39-15 do that).

**Acceptance:** two pods each with a task whose id starts `task-04ff`: `resolve_task(None,
"task-04ff")` raises listing both with pods; `resolve_task("a", "task-04ff")` returns `a`'s;
the short form and the full id resolve to the same `TaskRef`; `session_key` equals what
`core/dispatch.py::step_session_key` produces for the Lead hop. Oracle: equality with the task
record `read_tasks` returns.

**RED:** `tests/unit/core/test_task_ref.py` (new), fails on the base with `ModuleNotFoundError`.

### P39-4 — one role vocabulary: the model policy speaks archetype names

**Status:** DONE (merged to `develop` 2026-10-07, `5cbcac79`) · **Size:** M · **Wave:** 91 · **Model:** Sonnet · **Spec:** `model-profiles.spec.md` (roles and classes), `role-archetypes.spec.md` (`policy_role` removed), `cli-json-shapes.spec.md` (`models` output)

**Trigger (ADR 0022 evidence, live run C10):** `docket models` lists `manager`/`programmer`/
`reviewer`/`tester`/`knowledge`/`security`/`repo`; pods use `lead`/`implementer`/...;
`core/archetypes.py::RoleArchetype.policy_role` maps one to the other; after `models provider
add` the printed hint `docket profile programmer` fails.

**Goal:** `core/models_policy.py::ALL_ROLES` is the archetype name set (built-in plus starter:
`lead`, `implementer`, `reviewer`, `tester`, `researcher`, `analyst`, `writer`, `critic`,
`operator`, `monitor`, and any pod-scoped archetype resolves by its own name); `ROLE_CLASS` is
keyed the same way (`lead`, `reviewer`, `tester`, `monitor`, `analyst`, `writer` cheap;
`implementer`, `critic`, `operator`, `researcher` strong). `policy_role` and
`resolved_policy_role` are deleted from `core/archetypes.py` and from the role document shape
(`policyRole` is an unknown key, refused by `load_role_file`). `docket-models.json` `roles:`
keys are archetype names; a key that is not an archetype is reported by `doctor` and ignored
(no migration). The `is_specialist` branch and the `ORG_SPECIALIST_ORDER` loop in
`core/models_policy.py` are deleted here (P39-6 deletes the constants). `docket models` prints
the archetype names and `preset` writes them.

**Non-goals:** the per-agent pin (`profile`, `modelSource`), which P39-10 removes; the `models`
command's conversion to `setup model` (P39-12).

**Acceptance:** `resolve_role_model("implementer")` reads the `implementer` row; a pod-scoped
archetype `security-vetter` with no row resolves to the registry default (unchanged rule); a
`roles add` file with `policyRole:` is refused naming the key; `docket models` output contains
`implementer` and not `programmer`. Oracle: the resolved model string and the refusal message.

**RED:** `tests/unit/core/test_models_policy.py` (existing): `resolve_role_model("implementer")`
fails on the base because the row is `programmer`.

### P39-5 — the record decides: run state, exit codes, doctor, counts

**Status:** DONE (merged to `develop` 2026-10-07, `315dc23c`) · **Size:** M · **Wave:** 91 · **Model:** Sonnet · **Spec:** `pod-dispatch.spec.md` (run states, retry of a failed task, stale lease reclaim), `cli-interface.spec.md` (`runs show` exit code, `doctor` summary)

**Trigger (ADR 0022 evidence, live run C9, C11, C12):** a dispatch that parked `waiting_input`
is listed `succeeded`; `runs show <failed>` prints ✗ and exits 0; `metrics` counts 0/0/0 after
three terminal tasks; `doctor` says "1 critical issue" with none marked ✗ and hints `docket
maintain  check` (fails); `queue --retry <failed>` refuses ("not a blocked task"); a killed
dispatch leaves its task `running` forever (`runs cancel`: nothing in flight; `dispatch --resume`:
no-op, exit 0).

**Goal:** (a) `core/runs.py` records `waiting_input`/`waiting_approval` as the run's terminal
state when a hop parks, never `succeeded`; `cli/_runs.py` show exits 1 when the run or any
returned task failed. (b) `core/dispatch.py`: a `failed` task is retryable (status back to
`pending`, attempt counter kept, audited `task.retry`); a `running` task whose claim's process is
gone (`os.kill(pid, 0)` through `edges/adapters/system.py`) or whose lease is older than the
pod's `turnTimeoutS` plus `verifyTimeoutS` is stale, and `--resume` reclaims it (audited
`task.reclaimed`). (c) `cli/_doctor.py`: the summary counts only lines marked ✗ as critical, and
the fix hint names a command that exists (`docket doctor --fix`); the success/failure/aborted
counts in `cli/_metrics.py` come from the trace's terminal task events, not sessions.

**Non-goals:** the run banner (P39-15), `status --all` counts (P39-15), `pod show`'s
approvalMode source (P39-10), the `task retry` verb (P39-9 wires this core change).

**Acceptance:** a scripted dispatch whose Lead hop parks → `runs list` shows `waiting_input`;
a run with one failed task → `runs show` exit 1; a task record `running` with a dead pid →
`dispatch --resume` reclaims it and the audit has `task.reclaimed`; a `failed` task → the retry
function re-queues it, audit `task.retry`; a home with one ⚠ and no ✗ → `doctor` exit 0, no
"critical". Oracle: the run record and the audit log, never a renderer.

**RED:** `tests/unit/core/test_runs.py` (parked run state), `tests/unit/core/test_dispatch.py`
(stale reclaim and retry), `tests/unit/cli/test__doctor.py` (critical count); each fails on the
base for the measured reason.

### P39-6 — remove the org specialists and the portfolio manager (seventh unwired instance)

**Status:** DONE (merged to `develop` 2026-10-07, `798bd56c`) · **Size:** M · **Wave:** 91 · **Model:** Sonnet · **Spec:** `agent-lifecycle.spec.md`, `workspace-structure.spec.md`, `docket-meta.spec.md` (`scope: org`), `serve-read-api.spec.md` (`/status.json` agents), `cli-interface.spec.md` (`init --portfolio`)

**Trigger (ADR 0022 evidence):** `manager`, `knowledge` and `security` are provisioned by the
first `docket init` (`cli/_install.py`), listed by `list`/`snapshot`, reported by `doctor` and
`/status.json`, resolved by the model policy, and **no reader in `core/dispatch.py`,
`core/orchestrator.py`, `core/pipeline.py`, `serve.py` or the driver ever runs one**. The same
holds for the opt-in portfolio manager (`init --portfolio`). Machinery with a writer and no
consumer on the live path.

**Goal:** delete them: `config.py` (`ORG_ROLES`, `ORG_SPECIALIST_ORDER`, `ORG_DISPLAY_ORDER`,
`PORTFOLIO_MANAGER_ROLE`, `is_specialist`, the specialist branch of `workspace_dir`);
`cli/_install.py` (specialist provisioning, `_specialist_*`, `_provision_portfolio_manager`,
`--portfolio`); `serve.py::_SPECIALISTS` and the `kind="specialist"` records (bump
`SERVE_API_VERSION`); `cli/_doctor.py` (the specialist check only); `cli/__init__.py` (the two
`ORG_*` loops in `list` and `snapshot`, minimal edit: P39-16 and P39-15 delete the commands); the
`_cfg.is_specialist(aid)` branch in `cli/_agents.py`; `core/telegram.py`'s "org specialist"
sentence; `tests/integration/test_portfolio_manager.py`; the six specialist workspaces in
`tests/golden/fixtures/seed.sh`; `docs/AGENT-TEAMS.md` "Org specialists" section and the
`scope: org` prose in `docs/DOCKET.md`. The `security` and `knowledge` *archetypes*, if any pod
role carries those names, are untouched: this card removes shared agents, not role names.

**Acceptance:** fresh home → `docket init` → `workspaces/` holds only the pod's members;
`fleet.json` has no `manager`/`knowledge`/`security` entry; `docket init --portfolio` is an
unknown option (exit 2); `/status.json` lists pod agents only; `doctor` on a home that still has
a `workspaces/manager/` directory from before says nothing about it. Oracle: the directory
listing and `fleet.json`.

**RED:** `tests/unit/cli/test__install.py` (new, `SUBJECT = "docket.cli._install"`): after
`init`, no specialist directory exists; fails on the base with three directories.

### P39-7 — split `cli/__init__.py` into one module per group, mechanically

**Status:** DONE (merged to `develop` 2026-10-07, `a99e0344`) · **Size:** M · **Wave:** 92 · **Model:** Sonnet (integrator reviews the script before it runs) · **Spec:** `test-framework.md` (lanes: one unit file per module)

**Trigger:** `cli/__init__.py` is 2,842 lines holding 46 command bodies; every Wave 93 card
would edit it, so nothing in Wave 93 could run in parallel.

**Goal:** `scripts/maint/split_cli_registry.py` moves every `cmd_*` function and its private
helpers out of `cli/__init__.py` into the module that will own it in Wave 93, **unchanged**
(AST-located, text moved byte for byte, imports hoisted), and leaves `cli/__init__.py` as the
registry: `app`, the callback, and one `app.command(...)(module.cmd_x)` or `app.add_typer`
line per command. Target modules: `_run.py` (dispatch, pipeline run; new), `_task.py` (approve, deny, chat; new),
`_pod.py` (add, info, delete, maintain, profile join it), `_pod_config.py` (config, validate,
pipeline, roles, policies, plugins, recipes; new), `_status.py` (cost, metrics, snapshot join
it), `_inbox.py`, `_agents.py` (init only), `_log.py` (audit; new), `_setup.py` (doctor,
completions; new), `_setup_model.py` (models, keys; new; `_provider.py` joins it),
`_setup_notify.py` (channels, wire, unwire, notify, conversations; new), `_setup_export.py`
(exporters; new), `_setup_sandbox.py` (gates; new), `_setup_mcp.py` (mcp; new), `_service.py`
(serve; new), `_exec.py` (harness; new), `_remove.py` (list, context, logs, edit, scope,
persona, help; new, for P39-16 to delete). The script has `--check` (every `cmd_*` is in exactly one module and
`cli/__init__.py` has no function longer than ten lines) and `--dry-run`.

**Non-goals:** any behaviour or text change. Goldens, `docs/commands.md`, help output and the
full suite are the no-change oracle.

**Acceptance:** `bash tests/golden/run.sh verify-all` byte-identical; `gen_cli_docs.py --check`
green without regeneration; `uv run pytest` green; `tests/guards/test_layout.py` green with
new unit files only where the moved module exceeds 150 lines (empty `SUBJECT` files are
allowed for this card alone). Oracle: the goldens and the docs check.

**RED:** `tests/guards/test_layout.py` gains the rule "no function in `cli/__init__.py` longer
than ten lines"; it fails on the base with forty-six.

### P39-8 — the `task` group: add, list, show, diff, trace, prune

**Status:** DONE (merged to `develop` 2026-10-08, `f2dcfb4b`) · **Size:** M · **Wave:** 93b · **Model:** Sonnet · **Spec:** `pod-dispatch.spec.md` (task views, worktree prune, the queue), `trace-store.spec.md` (`task trace`), `cli-json-shapes.spec.md` (`task list|show --json` with `worktree`), `cli-interface.spec.md` (`delegate`, `pod delegate|queue|evidence|corrections|explain|worktrees`, `runs list|show|prune`, `trace` removed)

**Trigger (ADR 0022 evidence, live run B3, C6, P7):** a task reported `done` changes nothing the
operator can see; the fix sits uncommitted in the task worktree and no surface prints the path,
branch or diff; `pod queue` prints a short id that `chat` rejects; `trace` wants an internal
session key no command lists; `trace tail` on a finished session dumps raw JSONL.

**Goal:** `cli/_task.py` defines `task_app` and these verbs: `task add "<text>" [--priority]
[--brief FILE] [--pod]` (what `delegate` did; prints the `docket run` hint), `task list [--json]
[--pod]` (the queue with status, cost and the worktree path when one exists), `task show <ref>
[--json]` (status, hops, evidence, corrections, the interruption forecast, the runs, and for a
task with a worktree: path, branch, base commit and the exact `git -C <path> diff <base>` and
merge commands; a harness run id resolves too, replacing `harness status`), `task diff <ref>`
(runs that diff through `edges/adapters/system.py`), `task trace <ref> [--tail] [--export]
[--json]` (tool names on tool_call lines; `--tail` ends when the session ends), `task prune
[--dry-run] [--force] [--traces --days N] [--pod]` (what `pod worktrees prune` and `trace
expire`/`runs prune` did). Every ref goes through `core/task_ref.py`. The `pod` actions
`delegate`, `queue`, `explain`, `evidence`, `corrections`, `worktrees` leave `cli/_pod.py`;
`cli/_runs.py` (`list`, `show`, `prune`) and `cli/_trace.py` are deleted.

**Non-goals:** `approve|deny|answer|retry|cancel` (P39-9).

**Acceptance:** after a scripted `done` task with an uncommitted change → `task show` prints a
path that exists and `git -C <path> diff <base>` is non-empty; `task list --json` parses and each
item has `worktree` (path or null); `task show task-04ff` with two matches lists both and exits 1;
`task add "x"` from inside the repo queues without a pod name; `docket runs`, `docket trace`,
`docket delegate` are unknown commands (exit 2). Oracle: the filesystem and `TASK_LIST.json`.

**RED:** `tests/unit/cli/test__task.py` (new): `task show` prints the worktree path; fails on
the base (no command).

### P39-9 — `task approve|deny|answer|retry|cancel`

**Status:** DONE (merged to `develop` 2026-10-08, `372c46d4`) · **Size:** M · **Wave:** 93b · **Model:** Sonnet · **Spec:** `operator-loop.spec.md` (answer surfaces: `task answer` absorbs `chat`; pre-grant through `task approve --for`; the "approved, ready" state and the `run` hint), `pod-dispatch.spec.md` (`task retry` uses the core retry; `task cancel`), `cli-interface.spec.md` (`approve`, `deny`, `chat`, `pod answer|pregrant`, `runs cancel` removed)

**Trigger (ADR 0022 evidence, live run C5, C6, C11, C12):** `approve` says "may now proceed"
while nothing proceeds and `inbox` says "Nothing needs you"; `chat` rejects the short id; a failed
task cannot be retried; a killed dispatch leaves its task `running` forever.

**Goal:** registered onto `task_app` from `cli/_task.py` (P39-8 defines the app; this card adds
five verbs in the same module, functions `_task_approve`, `_task_deny`, `_task_answer`,
`_task_retry`, `_task_cancel`): `task approve <ref> [--reason] [--once|--task] [--for "<cmd>"
[--tool bash]]` resolves the task's pending approval (the `apr-…` token leaves the surface;
`--for` is what `pod pregrant` did) and prints the `docket run` hint, or "docket is running and
will pick it up" when the sweep holds the pod lock; `task deny <ref> [--reason]`; `task answer
<ref> [text] [--option ID] [--field k=v]... [--decline]` (on a TTY with no text or option it
prompts through the options as `chat` did; off a TTY it fails naming `--option`); `task retry
<ref>` (P39-5's core retry: failed or blocked); `task cancel <ref>` (the in-flight run plus the
stale reclaim). `cli/_approve.py`, `cli/_deny.py`, `cli/_chat.py` and `_pod_answer`,
`_pod_pregrant` in `cli/_pod.py` are deleted.

**Acceptance:** a parked task with options → `task answer <short-id> --option x` records the
answer and prints the run hint; after `task approve <id>` the inbox JSON item carries
`state: "approved_ready"` (P39-15 renders it); `task approve <id> --for "git push origin main"`
writes the same pre-grant `pod pregrant` wrote (compare the approvals directory); `task retry
<failed>` re-queues (audit `task.retry`); `docket approve` is an unknown command. Oracle: the
approvals directory and the audit log.

**RED:** `tests/unit/cli/test__task.py`: `task approve <id>` resolves the task's token; fails on
the base.

### P39-10 — the `pod` group, roster half: show, add, remove, reset, set, unset, delete

**Status:** DONE (merged to `develop` 2026-10-08, `9fba00fb`) · **Size:** M · **Wave:** 93b · **Model:** Sonnet · **Spec:** `agent-lifecycle.spec.md` -> 2.0.0 (member lifecycle; Lead removal refused; `reset` distills first, fails closed; pod deletion by typed name, never a picker), `model-profiles.spec.md` (per-agent pin removed), `docket-meta.spec.md` (`modelSource` removed), `pod-blueprints.spec.md` (`pod set|unset` over every `PodSettings` key), `cli-interface.spec.md` (`add`, `info`, `delete`, `maintain`, `profile`, `pod <p> list|add|remove|set-verify|config`, `config explain` removed)

**Trigger (ADR 0022 evidence, live run B2, B5, C9, C13, F6, F7):** `set-verify <m> --clear`
stores the literal `--clear`; `pod add wizard` prints a traceback; `pod remove <lead>` has no
confirmation; `delete <pod>` off a TTY deletes silently; the verify command that decided two
outcomes is shown by nothing; `explain interruptions` says `park` while `pod config` says `wait`;
a per-agent model pin is a fourth model layer with no measured need.

**Goal:** `cli/_pod.py` becomes `pod_app`: `pod show [MEMBER] [--json]` (members with role,
model and its source among policy / pod overlay / step, workspace path, verifyCmd; the pod's
settings with their source; the approvalMode `core/dispatch.py` will actually use, pinned by a
test that drives both; `configSource`/`configDigest`/`drift`: this is `config explain` and `pod
config get` in one), `pod add <role> [--count N] [--verify CMD]` (unknown role: one line, exit
1), `pod remove <id> [--yes]` (confirms; the Lead is refused with "delete the pod instead"), `pod
reset <id> [--yes]` (rebuilds the workspace files from metadata, distilling memory first, aborting
if distillation fails), `pod set <key> <value> [--member ID]` (every `PodSettings` key;
`budgetUsd` included; `verify` with `--member` writes a member's verifyCmd), `pod unset <key>
[--member ID]`, `pod delete [--confirm NAME]` (TTY: name typed; off a TTY: `--confirm` or exit 1;
an agent id is refused). Deleted: `add`, `info`, `delete`, `maintain` (all modes), `profile`
(`--resume` becomes part of `run --resume` in P39-15), `config explain`, `pod config`,
`modelSource` in `.docket-meta.json` and the pin branch of `core/models_policy.py::
resolve_role_model`. `cli/_agents.py` keeps `run_init` only.

**Acceptance:** `pod remove <lead>` → refused, pod unchanged; piped stdin → `pod remove <impl>`
→ exit 1 naming `--yes`; `pod unset verify --member <impl>` → meta has no `verifyCmd`; `pod add
wizard` → one line, exit 1; piped `pod delete` → exit 1 naming `--confirm`; `pod delete
--confirm demo` → every member gone, audit `pod.delete`; `pod show` names the implementer's
verifyCmd and the dispatcher's resolved approvalMode; a meta written with `modelSource` is read
without it. Oracle: `.docket-meta.json`, `fleet.json`, the workspaces directory.

**RED:** `tests/unit/cli/test__pod.py` (existing): Lead removal refused and piped deletion
refused; both fail on the base.

### P39-11 — the `pod` group, configuration half: apply, export, validate, plan, check, recipes, roles, policies

**Status:** DONE (merged to `develop` 2026-10-08, `2f1105e1`) · **Size:** M · **Wave:** 93b · **Model:** Sonnet · **Spec:** `config-format.spec.md` (one validator: `pod validate [PATH]` for any `kind:` document or directory), `pod-blueprints.spec.md` (`pod apply|export`; `apply` with no argument re-syncs instructions; `apply <file>` installs one document), `pipeline-format.spec.md` (`pod plan`), `security-gates.spec.md` (`pod check`), `role-archetypes.spec.md` (`pod roles`), `cli-interface.spec.md` (`validate`, `roles`, `policies`, `recipes`, `plugins`, `pipeline validate|plan`, `pod <p> apply|export|sync` removed)

**Trigger (ADR 0022 evidence, inventory C6):** four validators and a fifth check; two installers;
`roles`/`policies` unknown actions exit 0; `plugins` is a one-verb command; `policies test` is
the useful one and is hidden among them.

**Goal:** `cli/_pod_config.py` registers onto `pod_app` (imported from `cli/_pod.py`): `pod
apply [NAME|DIR|FILE] [--dry-run] [--json]` (recipe by name, directory, or a single `kind:`
document, which is what `roles add`/`policies add` did; no argument re-syncs instructions as
`pod sync` did), `pod export [DIR] [--force]`, `pod validate [PATH]` (the one validator), `pod
plan [--pipeline FILE]` (what `pipeline plan` did, from the real executor), `pod check "<text>"
--role R [--hook pre_tool_call] [--tool bash]` (what `policies test` did: would the pod's rules
allow this), `pod recipes [NAME] [--json]`, `pod roles [NAME] [--json]`, `pod policies [ID]
[--json] [--plugins]` (list without a name, show with one; plugins as a section). The `pod`
actions `config`, `apply`, `export`, `sync` leave `cli/_pod.py`; `cli/_config.py`,
`cli/_validate.py`, `cli/_pipeline.py`, `cli/_roles.py`, `cli/_policies.py`, `cli/_recipes.py`,
`cli/_plugins.py` are deleted (their bodies moved by P39-7 into `_pod_config.py`).

**Acceptance:** `pod validate .docket/` on an invalid role exits 1 with the message `validate`
printed; `pod apply roles/critic.yaml` installs the role `roles add` installed (compare the
pod's `config/roles.json`); `pod check "git push origin production" --role implementer` prints
the same verdict `policies test` printed; `docket validate`, `docket pipeline`, `docket roles`,
`docket policies`, `docket recipes`, `docket plugins` are unknown commands. Oracle: the pod's
config directory and the printed verdict.

**RED:** `tests/unit/cli/test__pod_config.py` (new): `pod check` verdict; fails on the base (no
command).

### P39-12 — `setup` is the first-run flow: the report, then only what is missing; `provider`, `model`, `sandbox`, `shell`

**Status:** DONE (merged to `develop` 2026-10-07, `3633ed8d`) · **Size:** M · **Wave:** 93a · **Model:** Sonnet · **Spec:** `cli-interface.spec.md` (the `setup` group; `doctor`, `models`, `models provider`, `keys`, `gates`, `completions` removed), `model-profiles.spec.md` (`setup model`; `provider add` applies the preset), `api-keys.spec.md` (credentials under `setup provider`; `remove` confirmation), `security-gates.spec.md` (`setup sandbox`; bare is a read), `agent-lifecycle.spec.md` (first run: `init` no longer bootstraps silently; it points at `setup`)

**Trigger (ADR 0022 evidence and decision 10):** the first run is four fragments of a wizard
and no wizard: `init` bootstraps the home without saying so and offers desktop notifications on
a TTY; `keys setup` walks the provider catalog; `models preset` reports readiness; `doctor`
checks health with one warning per agent and a hint to a command that fails. "Use Anthropic" is
three commands (`provider add`, `keys add`, `models preset`); the local preset is one, which is
why the quick start works and the hosted path does not. The only thing a task needs is a
reachable endpoint with a model per role; nothing says so.

**Goal.** `cli/_setup.py` defines `setup_app`. **`setup` with no verb is the flow**, idempotent,
two modes by TTY (the contract's rule). It always starts with the report, one line per piece
with its state and the exact command: model endpoint (required: a provider, its credential, and
`lead`/`implementer` resolving to a model), notifications (`console only (nobody is told)` is a
warning), sandbox (state and whether bwrap or docker was found), shell completion, the
background service. On a TTY it continues by asking only for what is missing, required first:
choose a provider (the catalog's built-ins plus `local`), the credential (stored 0600, never
echoed), probe `/models`, apply the preset, confirm the two roles resolve; then the optional
pieces, each default `N`: desktop notifications when a desktop session exists, Telegram (one
step, P39-13), the sandbox when a backend exists, shell completion. It prints every command it
runs (`ran: docket setup provider add anthropic --credential`) and ends with
`Ready. → Next: cd into a repo and run docket init`. Off a TTY it prints the report with the
commands and exits 1 when the required piece is missing, 0 otherwise; `--json` emits the report;
`--fix` repairs what `doctor --fix` repaired (the P39-5 critical count; hints name commands that
exist). The wizard has no logic of its own: it calls the same functions the verbs call.
`setup shell bash|zsh` prints the completion script (regenerated from the tree by P39-17).
`cli/_setup_model.py`: `setup provider add <name> [url] [--credential] [--model] [--ctx]
[--no-preset]` does the whole intent (store the credential, prompt on a TTY or take the flag/env
off it, probe, apply the provider's preset unless `--no-preset`, print which role resolves to
what), plus `list | show | remove [--yes] | export | rotate`; `setup model list [--json] | set
<role> <model> | preset [NAME] | reset [--yes]` stays for overrides and listing.
`cli/_setup_sandbox.py`: `setup sandbox status [--json] | on | off | network none|open | classes`
(bare is the status). `init` no longer provisions the home silently: with no endpoint
configured it still builds the team and ends with `⚠ No model endpoint yet → Next: docket
setup`; `run` refuses with the same line (P39-15 renders it; this card exposes
`setup.readiness()` for both). `cli/_doctor.py`, `cli/_keys.py`, `cli/_gates.py`,
`cli/_completions.py` are deleted after their bodies move (P39-7 put them in these modules).

**Non-goals:** `setup notify|export|mcp` (P39-13); the bare `docket` greeting (P39-17).

**Acceptance:** fresh home, piped stdin → `docket setup` → the report names `Model endpoint
missing` with `docket setup provider add ...`, exit 1, nothing written; a scripted TTY (stdin
feed) answering `local` → `docket-providers.json` has the provider, `docket-models.json` the
preset rows, the output contains `ran: docket setup provider add local`, exit 0; a second run
prints `Ready` and asks nothing; `setup provider add anthropic --credential sk-x` against a fake
`/models` → preset applied, `lead` resolves; `setup provider add x --no-preset` → no model rows;
`setup sandbox` writes nothing (`fleet.json` byte-identical); piped `setup provider remove X` →
exit 1 naming `--yes`; `docket doctor`, `docket models`, `docket keys`, `docket gates`,
`docket completions` are unknown commands. Oracle: the three JSON stores and captured stdout.

**RED:** `tests/unit/cli/test__setup.py` (new): piped `setup` on a fresh home exits 1 naming the
provider command and writes nothing; fails on the base (no command).

### P39-13 — `setup notify` (Telegram in one step), `setup export`, `setup mcp`

**Status:** DONE (merged to `develop` 2026-10-07, `7c4acba1`) · **Size:** M · **Wave:** 93a · **Model:** Sonnet · **Spec:** `telegram-integration.spec.md` (connecting Telegram is one operation writing the secret, the actors and every Lead's binding; the inbound-only AST pins on `core/telegram.py` are untouched), `operator-loop.spec.md` (`setup notify flush`), `observability-export.spec.md` (`setup export` verbs), `mcp-client.spec.md` (`setup mcp` verbs), `cli-interface.spec.md` (`channels`, `wire`, `unwire`, `notify`, `conversations`, `exporters`, `mcp servers` removed)

**Trigger (ADR 0022 evidence, inventory C3):** connecting Telegram is three commands over two
stores (`keys add TELEGRAM_BOT_TOKEN`, `channels enable telegram --set actors=<chat>`, which
refuses while `actors` is empty, and `wire <lead>` for the inbound binding), and the two setups
store different ids in different files; five commands cover notifications; bare `channels` exits 1.

**Goal:** `cli/_setup_notify.py` registers onto `setup_app`: `setup notify list [--json] | show
<name> [--json] | enable <name> [--set k=v] [--chat ID] | disable <name> | add <file> | remove
<name> [--yes] | export <name> [FILE] | privacy <name> [LEVEL] [--yes] | test <name> | bind
<member> [--channel telegram] | unbind <member> | flush [--dry-run]`. **`setup notify enable
telegram --chat <id>` is the one step:** it stores the bot token (prompted on a TTY, `--token`
or the env off it, through the same 0600 store), sets `actors`, binds every pod's Lead (what
`wire` did, for each pod), sends one test message only if `--test` is passed (the inbound-only
rule stands: nothing is sent unasked), and prints what it wrote in each store; `bind`/`unbind`
remain for the per-pod exception. `show telegram` lists the bindings and the open conversations
the registry holds. The `setup` wizard (P39-12) calls this one function for its Telegram step.
`cli/_setup_export.py`: `setup export` with the verbs `exporters` had. `cli/_setup_mcp.py`:
`setup mcp list | add <name> [...] -- cmd | remove <name>` (what `mcp servers` did; `mcp serve`
moves to `start --mcp` in P39-14). `cli/_channels.py`, `cli/_notify.py`,
`cli/_conversations.py`, `cli/_exporters.py`, `cli/_exporters_preview.py` (its body joins
`_setup_export.py`), `cli/_mcp.py`'s servers half are deleted after their bodies move;
`core/conversations.py` stays (dispatch and the service read it).

**Acceptance:** a home with two pods → `setup notify enable telegram --chat 42 --token t` →
`secrets.json` holds the token, the telegram channel document has `actors: ["42"]` and is
enabled, both Leads have a binding in `fleet.json`, nothing was sent (the fake sink is empty);
`setup notify bind demo-lead` writes the binding `wire` wrote; `docket wire`, `docket notify`,
`docket conversations`, `docket channels`, `docket exporters` are unknown commands; `setup
notify flush --dry-run` delivers nothing; `setup mcp list` prints what `mcp servers list`
printed. Oracle: `secrets.json`, the channel catalog, `fleet.json`, the sink,
`docket-mcp-servers.json`.

**RED:** `tests/unit/cli/test__setup_notify.py` (new): `enable telegram --chat` writes the three
stores; fails on the base (no command).

### P39-14 — `log`, `start`, `stop`, `exec`

**Status:** DONE (merged to `develop` 2026-10-07, `c81aac07`) · **Size:** M · **Wave:** 93a · **Model:** Sonnet · **Spec:** `audit.spec.md` (`log`, `log verify`), `serve-read-api.spec.md` (`start|stop`; routes unchanged), `harness-mode.spec.md` (the command is `exec`; contract 1.0/1.1 unchanged; `harness status` replaced by `task show <run-id>`), `mcp-server.spec.md` (`start --mcp`), `cli-interface.spec.md` (`audit`, `serve`, `harness`, `mcp serve` removed)

**Trigger (ADR 0022 decisions 1 and 5):** "audit" names the mechanism, "serve" does not say what
is served, "harness run" is two words describing an architecture, and Tack calls it by name.

**Goal:** `cli/_log.py`: `log [N] [--json]` (what `audit` printed; `audit bogus` exited 0, an
unknown verb now exits 2) and `log verify`. `cli/_service.py`: `start [--port] [--interval]
[--http/--no-http] [--telegram] [--dispatch/--no-dispatch] [--mcp] [--token-file]` (what `serve`
did plus `mcp serve` behind `--mcp`; the help says what runs in the background) and `stop`
(the two-stage stop that exists; `status` reports whether it is running). `cli/_exec.py`: `exec`
with every option `harness run` had, the same NDJSON events, result line and exit codes 0/1/2;
`tests/fixtures/harness-contract/v1/` and `docs/contracts/harness-v1/` are untouched except the
command name in prose; `harness status` is deleted (`task show <run-id>` resolves the record
through `core/task_ref.py`). `cli/_audit.py`, `cli/_harness.py` (renamed to `_exec.py` by
`git mv`, with `_harness_answers.py`/`_harness_recipe.py` kept as they are), `cli/_mcp.py`'s
serve half deleted.

**Acceptance:** the harness contract tests (`tests/integration/test_harness_*`) pass with the
command name replaced and nothing else; `docket harness`, `docket serve`, `docket audit` are
unknown commands; `log verify` on a tampered line exits 1 as `audit verify` did; `start --mcp`
serves the MCP tool set `mcp serve` served (pin by the existing MCP server test). Oracle: the
fixture files and the existing tests.

**RED:** `tests/unit/cli/test__exec.py` (renamed from `test__harness.py` by `git mv`): invoke
`exec`; fails on the base (no command). Return the one-line change Tack needs in
`tack-runner/src/harness/docket/probe.rs` for the integrator; do not edit Tack.

### P39-15 — `run`, `status`, `inbox`

**Status:** DONE (merged to `develop` 2026-10-07, `77ca8ed6`) · **Size:** M · **Wave:** 93a · **Model:** Sonnet · **Spec:** `pod-dispatch.spec.md` (`run`: `--dry-run` starts nothing; the banner lists the effective pipeline after roster filtering; `--resume` reclaims stale claims and budget pauses), `pipeline-format.spec.md` (`run --pipeline FILE`), `cost-tracking.spec.md` (cost and counts in `status`), `cli-json-shapes.spec.md` (`status --all --json` carries what `snapshot` carried; `inbox` items carry `state`), `operator-loop.spec.md` (`inbox` prints `docket task approve <id>` lines; "approved, ready"), `cli-interface.spec.md` (`dispatch`, `pod dispatch`, `pipeline run`, `cost`, `metrics`, `snapshot` removed)

**Trigger (ADR 0022 evidence, live run B1, C5, C7, C8, C9, P1):** `pod dispatch --dry-run`
runs; the banner names reviewer and tester for a two-member pod; `inbox --bogus` exits 0 and
truncates the command being approved; `metrics` prints raw ANSI when piped and counts sessions;
cost appears in five places, none per pod; `status --all` hides failed tasks.

**Goal:** `cli/_run.py`: `run [--resume] [--timeout S] [--progress] [--no-prompt] [--pipeline
FILE] [--var k=v]... [--dry-run] [--pod]` (what `pod dispatch` and `pipeline run` did; `--dry-run`
prints the plan the real executor renders and starts nothing; `--resume` also clears a budget
auto-pause, what `profile --resume` did; the banner lists the effective pipeline's steps after
roster filtering; the summary line `✓ 1 done · 0 failed · 2.1k tokens (~$0.00 est.)` and one
`→ Next:` line; with no model endpoint configured it refuses with `✗ No model endpoint yet. Run
docket setup` through `setup.readiness()` from P39-12). `cli/_status.py`: `status [--all] [--json] [--history]
[--days N]` shows the pod's tokens, the labelled estimate and the success/failure/aborted counts
and latency P39-5 moved to trace events (what `cost` and `metrics` did, per pod), failed counts
under `--all`, the last run, "approved, ready" tasks, whether `docket start` is running;
`status --all --json` is the inventory `snapshot` printed. `cli/_inbox.py`: the sub-app `inbox
[--json] [--since] [--peek]`, unknown flags exit 2, full held command (wrap, never cut), each
item printed with its exact `docket task approve|deny|answer <id>` line, `approved_ready` state.
`_pod_dispatch*`, `_parse_dispatch_args` (deleted: Typer parses), `_flush_notify_after_dispatch`
leave `cli/_pod.py`; `cli/_cost.py`, `cli/_metrics.py` deleted after their counting moves (a pure
trace reader may land in `core/trace.py`, one function).

**Acceptance:** inside the repo → `run --dry-run` prints the plan, no run record, no trace event,
no task status change; a home with no provider → `run` exits 1 naming `docket setup`; `run --bogus` exit 2 naming the flag; a two-member pod's banner names two
hops; `status --all` shows `2 failed`; a scripted trace with 1 done, 2 failed → `status` prints
`1 / 2 / 0`; `inbox --json` parses with no escape codes and each item has `command`; `docket
dispatch`, `docket cost`, `docket metrics` are unknown commands. Oracle: `docket-runs.json`, the
trace directory, `TASK_LIST.json`, `json.loads` on stdout.

**RED:** `tests/unit/cli/test__run.py` (new): `--dry-run` leaves `docket-runs.json` unchanged;
fails on the base (no command).

### P39-16 — remove: `list`, `context`, `logs`, `edit`, `scope`, `persona`, `help`

**Status:** DONE (merged to `develop` 2026-10-07, `e29436be`) · **Size:** M · **Wave:** 93a · **Model:** Sonnet · **Spec:** `session-scoping.spec.md` -> 3.0.0 (operator-set scope removed; the derived key stands), `workspace-structure.spec.md` (persona block removed from `SOUL.md`), `cli-json-shapes.spec.md` (`list`, `info` shapes removed), `cli-interface.spec.md` (the seven removed)

**Trigger (ADR 0022 decision 5):** read views over files the operator can open, an operator-set
session key with no reader on the live path, a cosmetic persona with one writer, and a `help`
command whose four examples all fail.

**Goal:** delete the seven commands, `cli/_remove.py` (P39-7's holding module), `cli/_help.py`,
`cli/_context.py`, the persona layer (`core/identity.py` persona rendering and parsing, the
`persona` field of `AgentMeta`, the block in `SOUL.md`), `core/utils.py::aggregate_cost`/
`last_activity` if `list`/`snapshot` were their last callers (P39-15 may keep one), the `scope
set|reset` writers (the `sessionKey` in meta stays as the derived value provisioning writes).
`tests/integration/test_completions_eval_metrics_help.py` loses its `help` cases. The bare
`docket` guide names the eleven commands (P39-17 owns its final text; this card only removes the
`docket help` line).

**Acceptance:** each of the seven names is an unknown command (exit 2); a meta written with
`persona` is read without it and `SOUL.md` renders without the block; `status --all --json`
still carries the member inventory `list --json` carried. Oracle: the exit codes and the
rendered `SOUL.md`.

**RED:** `tests/integration/test_console_script_entry_point.py` (existing): the retired-name
test is parametrized over these seven; fails on the base (exit 0).

### P39-17 — grouped help, one tagline, the bare guide, completions and the three guards

**Status:** DONE (merged to `develop` 2026-10-08, `cc81c003`) · **Size:** M · **Wave:** 94 · **Model:** Integrator · **Spec:** `cli-interface.spec.md` ("Help" rewritten: the eleven commands in three panels, examples, exit codes), `test-framework.md` (the guards)

**Trigger (ADR 0022 decisions 1 and 6):** `docket --help` lists 46 commands in registration
order; four taglines; 0 of 21 actions show their own help; the completion script offers agent ids
after `pod`.

**Goal:** three `rich_help_panel` groups (Daily: `init status inbox task run`; The pod: `pod log`;
Machine: `setup start stop exec`); one tagline ("docket runs teams of coding agents and governs
what they may do") in `--help`, the bare `docket` greeting (the tagline, the five daily commands, and `Not set up yet? docket
setup`, rendered through `ui.py`'s voice) and `pyproject.toml`; `setup shell` regenerated from the tree (every group's verbs, pod ids after
`--pod`, task ids after `task <verb>`); `scripts/gen_cli_docs.py` `GROUPS` replaced by the panels
and `docs/commands.md` regenerated; `-h` accepted. Three guards in `tests/guards/`: every leaf
reachable from the registry prints its own `--help` containing `Example:`; every `list`, `show`,
`status`, `inbox` and `log` parses as JSON under `--json`; every prompt site reached with stdin
closed exits 1 naming a flag. Each guard is seen red by planting one defect before it counts.
Goldens regenerated for every case the Wave 93 cards changed, with the line-by-line explanation
in the rollup commit; the golden runner's `cases_dir()` read-only list rewritten for the new
names.

**Acceptance:** `docket --help` shows three panels and eleven commands; `docket task show --help`
shows one example; `docket dispatch` → "did you mean `run`?", `docket delegate x` → usage with a
suggestion, exit 2; the three guards fail when a planted leaf loses its example / its JSON / its
flag. Oracle: the guards themselves, after they have been seen red.

### P39-18 — the mechanical rename script

**Status:** DONE (merged to `develop` 2026-10-08, `254fba94`) · **Size:** S · **Wave:** 94 · **Model:** Sonnet · **Spec:** none (tooling)

**Trigger:** about 357 doc lines, 142 source lines, 42 test lines and 17 script lines invoke
`docket pod ...`; the templates carry `docket pod <project> config unset pipeline` thirteen
times. A model rewriting those by reading whole files is the failure mode CLAUDE.md names.

**Goal:** `scripts/maint/rewrite_cli_names.py` with one table (old invocation pattern → new
invocation, from ADR 0022 decision 5) applied over `docs/`, `src/docket/templates/`, `scripts/`,
`specs/`, `tests/agent/`, `README.md`, `CONTRIBUTING.md`, `CHANGELOG.md` `[Unreleased]` only;
`--check` fails naming every surviving invocation of a removed name (the fourth guard of ADR
0022, wired as `tests/guards/test_no_removed_cli_names.py` calling the script's check); `--dry-run`
prints the diff. Patterns that cannot map one to one (`docket info <agent>` where the pod is
meant, `docket help`, `conversations`, `scope`, `persona`, `logs`, `edit`, `context`) are listed
by the script for the doc cards, not rewritten.

**Acceptance:** `--check` on the base lists hundreds; after `--write`, an `rg` for every removed
top-level name over `docs`, `src/docket/templates`, `scripts`, `specs`, `tests/agent` and
`README.md` prints only the lines the script listed as unmappable. Oracle: the rg.

### P39-19 — README and quick start on the new surface

**Status:** DONE (merged to `develop` 2026-10-08, `d362eb5f`) · **Size:** M · **Wave:** 94 · **Model:** Sonnet · **Spec:** none (README is descriptive, D-37); agent-lane prose tests rebuilt

**Goal:** after P39-18, rewrite `README.md` ("Quick start", "Your first team", "The run", "The
gate and the record", "Make it yours", "Everything is configuration", "Also shipped", "Known
limits") and `docs/QUICK-START-DOCKET.md` so every command shown exists, the newcomer path never
types the pod name, the sentence defining `pod` from ADR 0022 decision 3 appears where the first
`docket pod` command does, and the sentences the prose tests pin are rebuilt from this README
(`tests/agent/truth/test_docs_positioning.py`, `test_public_release_truth.py`): no assertion
carried from the old README. The "Known limits" entry on org specialists goes. The transcripts
and images stay as they are (P39-23 re-captures them).

**Acceptance:** `uv run pytest tests/agent` green; `scripts/maint/rewrite_cli_names.py --check`
green on both files; every `docket ...` line in both files runs under a throwaway home (the
integrator spot-checks six). Oracle: the agent lane and the check.

### P39-20 — the guides: AGENT-TEAMS, DOCKET, WORKFLOW-GUIDE

**Status:** DONE (merged to `develop` 2026-10-08, `305e05ed`) · **Size:** M · **Wave:** 94 · **Model:** Haiku · **Spec:** none

**Goal:** after P39-18's mechanical pass, the three guides read as one surface: every remaining
unmappable line (listed by the script) is rewritten by hand, the "Org specialists" section of
`docs/AGENT-TEAMS.md` and every `scope: org` sentence are removed (P39-6 already cut the
section; this card removes the cross-references), the `pod <p> ...` prose becomes "from inside
the repo" prose, and no sentence describes a removed command, a pin, a persona or a specialist.
The script's `--check` is the gate; a Haiku worker edits only the lines the script lists plus
the sentences that reference them.

**Acceptance:** `rewrite_cli_names.py --check` green on the three files; an `rg` for
`specialist|persona|modelSource|docket help|harness run` over the three files is empty. Oracle:
the two commands.

### P39-21 — the reference docs: CONFIGURATION, SECURITY-SIMPLE, troubleshooting, MODEL-GATEWAYS, docs index, contracts

**Status:** DONE (merged to `develop` 2026-10-08, `22861f7b`) · **Size:** S · **Wave:** 94 · **Model:** Haiku · **Spec:** none

**Goal:** same method as P39-20 over `docs/CONFIGURATION.md`, `docs/SECURITY-SIMPLE.md`
(`gates` → `setup sandbox` throughout; the opt-in section keeps its content),
`docs/troubleshooting.md` (61 invocations; every remedy names a command that exists),
`docs/MODEL-GATEWAYS.md`, `docs/README.md` (the start-here order), `docs/contracts/harness-v1/`
prose (`harness run` → `exec`; the schema is untouched). `docs/recipes.md` is regenerated by
`scripts/gen_recipe_docs.py` after P39-22, not edited.

**Acceptance:** `rewrite_cli_names.py --check` green on the files; an `rg` for `docket gates|
docket profile|docket maintain|harness run` over `docs/` is empty. Oracle: the two commands.

### P39-22 — recipe READMEs, templates and the specs' prose

**Status:** DONE (merged to `develop` 2026-10-08, `7a1a85ce`) · **Size:** S · **Wave:** 94 · **Model:** Haiku · **Spec:** every spec that names a CLI command in prose (26 files, listed in the packet); versions bumped patch-level with one changelog line each: "command names follow ADR 0022"

**Goal:** after the script: the eighteen recipe `README.md` files under `src/docket/templates/
recipes/` (thirteen say `docket pod <project> config unset pipeline`; they now say `docket pod
unset pipeline`), the Lead instruction and workspace templates that print a next command, and
the prose of every spec outside `cli-interface.spec.md` that names a removed invocation. A
spec's *requirements* are not changed by this card: if a requirement itself names a removed
command, the card returns the locator and the Wave 93 card that owns it is reopened.
`scripts/gen_recipe_docs.py` regenerates `docs/recipes.md`.

**Acceptance:** `rewrite_cli_names.py --check` green over `specs/` and `src/docket/templates/`;
`bash scripts/validate-specs.sh` green; `gen_recipe_docs.py --check` green. Oracle: the three
checks.

### P39-23 — assets, CHANGELOG, spec close, Tack's one line, board archive

**Status:** PARTIAL, carried (integrator, 2026-10-08: CHANGELOG, `cli-interface` 2.0.0, the spec index, `metrics --check` and the board archive done on `develop`; Tack's `exec` line and the live asset re-capture were refused twice by the session's permission classifier and are carried by name to the board's open section, maintainer-owned) · **Size:** M · **Wave:** 94 · **Model:** Integrator · **Spec:** `cli-interface.spec.md` 2.0.0 (status, the registry rewritten as the eleven commands; a `#### docket <cmd>` section per top-level command, each with its verbs)

**Goal:** `scripts/maint/capture-doc-journey.sh` re-run on the local endpoint and
`scripts/render-doc-assets.py` re-transcribed so the hero GIF and both PNGs show commands that
exist; `CHANGELOG.md` `[Unreleased]` gains a "Removed" list (every name in ADR 0022 decision 5,
one line each, with the replacement) and a "Changed" entry for the tree, the pod resolver, the
contract and the role vocabulary; `cli-interface.spec.md` cut to the eleven commands at 2.0.0
with the removed sections gone (not struck through); `specs/README.md` row updated;
`scripts/metrics.py --check` re-measured (`commands=11`); the one-line change in
`objetivosMios/crates/tack-runner/src/harness/docket/probe.rs` (`"harness", "run"` → `"exec"`)
applied in that repo and its harness tests run there; the YieLab landing page
(`~/Sites/newPortaflio/content/docket-landing.ts`) is updated after the release that ships the
names, recorded as the one follow-up.

**Acceptance:** every gate in the board rules green on `develop`; `docs/commands.md` lists eleven
commands; the three new guards and the removed-name guard green; `git grep -n 'docket pod '`
finds only `docket pod <verb>` forms outside `docs/cycles-ended/` and `CHANGELOG.md`; Tack's
docket harness tests pass against `exec`. Oracle: the gates.

### P39-24 — the measurement: six journeys re-run, checklist re-scored

**Status:** DONE (integrator, 2026-10-08: six journeys re-run on the local endpoint under a throwaway `DOCKET_HOME`; none of the sixteen defects reproduces; checklist 18/20 with rule 5 (bare-name library readers) and rule 16 (no hint switch) as the named exceptions; transcript in `internal-docs/cli-ux-audit-2026-10-07/live-run-after.md`, score in ADR 0022 "Live run", eighteen new locators for triage in the transcript) · **Size:** S · **Wave:** 95 · **Model:** Integrator · **Spec:** ADR 0022 gains a "Live run" section

**Goal:** the six journeys of the audit's live run (first run, daily loop, the gate, make it
yours, ops, errors) re-run against the Wave 94 rollup under the same throwaway `HOME` and the
local endpoint with `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`; the 20-rule checklist re-scored; every
defect of the audit's table checked for reproduction; the result recorded in ADR 0022 "Live run"
with the score, the two named exceptions and any new defect as a locator for triage (not fixed
in this card unless one line).

**Acceptance (ADR 0022 "How done is measured"):** zero of the sixteen defects reproduces; the
newcomer path never types the pod name; every `--help` at every level has an example; the four
guessed commands work or suggest correctly; checklist 18/20 or better. Oracle: the transcript
saved under `internal-docs/cli-ux-audit-2026-10-07/live-run-after.md`.

### P39-25 — every documented invocation is true against the live tree

**Status:** DONE (merged to `develop` 2026-10-08, see the Wave 95 close) · **Size:** S · **Wave:** 95 · **Model:** Sonnet · **Spec:** none (a guard; lane per `specs/test-framework.md` §"Lanes and placement", beside `tests/guards/test_no_removed_cli_names.py`)

**Trigger (deterministic reproduction, 2026-10-08, "Wave 94 returns" in the packets file):** the
removed-name guard proves an old name is gone and nothing proves a new line is true. P39-21's
first return carried about twenty invocations the tree does not have (`setup sandbox isolate on`,
`setup notify content`, `status <agent>`, `task list --retry`, `pod check <hook> <role>`) and four
more survived in `docs/README.md` to the merge; the integrator's scratch linter, walking the live
Click tree, found every one and the gates found none.

**Goal:** `scripts/maint/lint_cli_invocations.py` checks every `docket ...` invocation found in
a code span or a fenced block of the given files against the live command tree: each word is a
verb of its group, each `--flag` is an option of its leaf, the positional count fits the leaf's
arguments; placeholders (`<x>`, `[x]`, `UPPER`, `...`, `$VAR`, quoted text) are accepted; `a|b`
is accepted when every alternative is live; `init` is exempt (hand-parsed flags). It prints
`file:line: invocation: reason` and exits 1 on any finding; `--self-check` plants false lines and
expects them back. `tests/guards/test_cli_invocations_true.py` runs it in process over
`README.md`, `CONTRIBUTING.md`, `docs/` (not `cycles-ended/`, not `adr/`), `specs/` (a spec's
`## Changelog` is the record: `rewrite_cli_names.py::split_record`), `src/docket/templates/` and
the `Example:` line of every leaf's help. A line it flags that is false is fixed in this card.

**Non-goals:** prose (`docket runs teams of coding agents` is a sentence), `CHANGELOG.md`,
Python source (P39-18's roots cover comments), any behaviour change; no table of removed names.

**Acceptance:** RED: on the base, a tmp file holding `docket task list --retry` and a tmp spec
whose body (not its changelog) holds `docket status <agent>` each produce one finding, and the
guard lists the live findings over the roots (fixed in the card, one line each); GREEN: zero
findings over the roots in under 2 s, `--self-check` returns its planted lines, every gate green.
Oracle: the guard, and `lint_cli_invocations.py FILE` by hand on a doc with one false line.
