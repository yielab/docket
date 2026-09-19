# ADR 0001 (D-35): harness mode — docket runs one agent, non-interactively, for a caller that owns the workspace

**Decide:** approve a new non-interactive entry point, `docket harness`, that runs **one
agent, one turn loop, to completion, in a workspace the caller supplies**, streaming
newline-delimited events on stdout and finishing with a single versioned result object.
Approve that it is a **CLI subcommand over existing `core/` behaviour** — no second
`RuntimeDriver`, no plugin discovery, no async, no new store — and that its contract is
published and versioned because a consumer outside this repository depends on it byte for
byte.

Approve one safety rule with no exception: **harness mode refuses to run against the default
`DOCKET_HOME`.** The caller supplies a home it owns, or the command exits.

**Why now:** ROADMAP §4.5's durable lesson is that *whoever owns the loop owns the
interception points* — docket shipped four `pre_tool_call` policy templates that had never
once been evaluated, because a wrapped runtime owned the inside of a turn, and D-19 took the
runtime to fix it. **Tack is in that exact position today.** It ships a `permission-policy`
field on every execution request and then hands the work to a closed vendor CLI that decides
on its own what to honour. Its two harnesses both declare `decisions: Unsupported` and
`cancel: Advisory`, and neither can be fixed from Tack's side. docket already owns the loop,
the tool registry, the three policy hooks, the approvals and the audit trail. Harness mode is
how another product borrows that ownership without wrapping anything.

**If you do nothing:** `RuntimeDriver` keeps its one caller inside this repo, docket stays a
system a person operates rather than one a product embeds, and the part-3 thesis in
`CLAUDE.md` — *docket executes; something else holds the plan of record* — stays half-built.
Phase 22 built the read direction, where Tack polls docket. Nothing lets docket be the thing
that executes an item Tack scheduled.

## The decisions, in short

| # | Decision | Why |
|---|---|---|
| 1 | `docket harness run` executes **one agent, one workspace, to completion, synchronously**, and blocks until the loop ends. | The consumer's execution model is spawn-and-wait on a local process. An entry point that returns before the work does cannot be adapted into it — that is exactly the property of `POST /dispatch/` that made it unusable for this. |
| 2 | It uses the shipped `DocketDriver` **unchanged**. No second driver, no driver selection, no entry points. | §4.5's "one typed port, one shipped driver" ban is untouched. This is a new *caller* of existing behaviour, which is the Phase 22 design rule verbatim: expose what `core/` already does, add no new semantics. |
| 3 | The workspace is **given, never provisioned**. Harness mode creates no pod, no worktree, no clone, and writes nothing into the workspace. It **does** write two docket-owned records into the `DOCKET_HOME` the caller supplied: a minimal `.docket-meta.json` (kind, role, `codebase=<workspace>`, model, session key) and a run record, because `DocketDriver.run_turn` reads its tool roots from that meta and refuses a turn without one. | The caller has already prepared an isolated checkout at a known base revision and reports those facts as its own. Provisioning a second one would create two answers to "where did this change happen". The meta file is registration in a disposable home, not a workspace: the alternative — calling `run_agent_turn` directly to avoid writing it — would create a second execution path beside the driver, which is the exact shape decision 2 forbids. |
| 4 | stdout is **newline-delimited JSON events** during the run, then exactly one final `result` object. stderr is logs. The exit code agrees with the result. | A consumer that must show progress and survive a crash needs incremental events. Retrofitting streaming onto a batch contract is the more expensive order, and the transcript is what makes a run auditable at all. The events are the existing trace vocabulary (`core/trace.py`'s `EVENT_TYPES`, already redacted) inside a versioned envelope — not a second vocabulary to keep in step. |
| 5 | Every event and the final result carry `harness_contract_version`, and the contract has its own fixture directory in this repo. The schema file is **generated from the Pydantic models** and pinned by a test that regenerates and diffs it. | An external consumer pins against this. A silently reshaped field is an outage in a product we do not build, which is a failure mode docket has never had before. Tack is Rust; it pins the JSON Schema, not the Python types, so the schema must be a checked-in artifact rather than something derived at read time. |
| 6 | The result **states which model served the last request of the run**, read from the response body rather than from what was requested. | `ChatResponse.raw` already holds the parsed body, `AgentLoopResult.raw` carries the last one through `TurnResult.raw` untouched, and its `model` field is never read today. A gateway may substitute a model, so requested-and-served are different facts and the consumer must be able to tell them apart. "Last request" is the honest scope: a run makes several requests and the driver retains one body. |
| 7 | Endpoint and credential come **only** from the per-spawn environment in harness mode. No stored provider block, no keyring, no hosted-gateway default. **`DOCKET_LLM_BASE_URL` is required**; harness mode refuses to start without it. | The caller holds the operator's credential and is accountable for it. Silently falling back to a credential stored in this home would spend money the caller never authorised. No change to `resolve_endpoint` is needed: with a fresh caller-owned home (decision 8) there is no provider block and no `secrets.json`, so the existing precedence already sees only the environment. The one hole is `_HOSTED_GATEWAY_BASE_URLS` — a model named `openrouter/...` would resolve a built-in URL with no base URL set. Requiring the variable closes it. |
| 8 | **`DOCKET_HOME` must be supplied and must not be the default.** Harness mode exits with code `2` — and emits one `result` with `status: refused` — if it is unset, resolves to the user's own `~/.docket`, or if `DOCKET_LLM_BASE_URL` is missing or `DOCKET_NO_TRACE=1` is set. Codes are `0` ok, `1` a run that ended `failed`, `blocked` or `cancelled` (a `result` is on stdout), `2` refused before any run started. | That directory holds real approvals and a real audit log. An execution runner writing into it would corrupt the record that makes governance claims true. `specs/api/cli-interface.spec.md` fixes a flat two-code convention for human-facing commands; harness mode is a machine contract, and the spec records these three codes as its one named exception rather than letting the ADR contradict it silently. |
| 9 | On `SIGTERM`, harness mode **persists a cancellation request, kills the process group of any tool subprocess in flight, emits a terminal `cancelled` result and exits** — all bounded by a short poll interval, not by the tool's own timeout. Escalation to `SIGKILL` on the harness pid after a grace period is the **caller's** job, as its crash matrix already does for the other harnesses. | This is the single capability neither of the consumer's existing harnesses can offer. **It is not true of docket today either:** `run_bash` starts every command with `start_new_session=True` — each child is its own session, outside the harness's group — and blocks in `communicate(timeout)` without ever reading `ToolContext.cancellation_check`. W26-C10b (D-30) deliberately stopped at "an already-running handler may finish", because a Python thread cannot be killed safely. **A subprocess can.** This decision amends D-30 for the `bash` handler only: `run_bash` polls the cancellation callback, kills the group it already knows how to kill (`_kill_group`, plus `docker_kill` under that backend), and returns a complete `ToolOutcome` so the session unit stays atomic. Everything D-30 says about HTTP requests and Python handlers stands. Closing this also makes `docket runs cancel` reach an in-flight `bash`, which it cannot today because `DocketDriver` never reports a pid. |
| 10 | Before the first turn, harness mode creates a run record through `core/runs.py` and prints its id as the **run token** in the first event. Given that token, `docket harness status` reports whether the run is `live` (record non-terminal), `finished` (terminal, with the outcome) or `unknown`. The harness does **not** register its own pid in the run's `pids` list. | The caller must resume its own bookkeeping after a crash. A bare pid is ambiguous once it has been reused; a token plus the caller's own pid is not. Reusing `runs.py` is what makes "no new store" literal: the token is a run id in `docket-runs.json`, and `execute()` already publishes it so `DocketDriver` wires the persisted cancellation signal into the loop and into `wait_for_approval` with no harness code. The pid stays out of `pids` because `cancel_run` SIGKILLs those groups — the harness would die before it could emit its `cancelled` result. Liveness of a non-terminal record is the caller's pid check. |
| 11 | **v1 is non-interactive on approvals.** `ToolContext` gains `approval_mode: "wait" \| "refuse"`, default `"wait"` (today's behaviour, byte for byte). Under `"refuse"`, a verdict of `ask` is audited as it is today, creates **no** approval record, waits **zero** seconds, and returns a new `ToolDenialKind` `approval_unavailable`; the loop stops on it immediately with `stop_reason="approval_unavailable"`, and the result carries the tool, call id, denial kind, policy id and reason that fired. | An interactive pause turns a synchronous subprocess into a session with a protocol. That is worth building and it is a separate decision — this one must not smuggle it in. **Today's code does the opposite of both halves:** `dispatch_tool` blocks in `wait_for_approval` for up to `TOOL_APPROVAL_TIMEOUT` (120 s) and then hands the model a denial it may retry three times before `max_consecutive_tool_denials` stops the turn. Lowering that limit to one is not a substitute: it would also make a recoverable `invalid_call` terminal. Terminality must be specific to this denial kind. |
| 12 | Cost stays honestly unmeasured: `reports_cost_usd` remains false and the result carries **token counts, never a fabricated dollar figure**. The counts are read back from the run's session (`DocketDriver.usage`), not from `TurnResult`, which has no usage field. | Those token counts are real, off the response body, accumulated by `core/session.py` into the session's `MeasuredUsage`. In a fresh home with one session that total is exactly this run. A zero USD field would be read by a consumer as "this run was free". |

If you accept this table, you have accepted the decision — record it as **D-35** in
ROADMAP §6 and date it here.

---

- **Status:** **accepted as D-35 and shipped 2026-09-12** (Phase 24 / Wave 30; ROADMAP §6).
  Proposed 2026-09-08 · audited and corrected 2026-09-11 against `main` at `4032133` (see
  `internal-docs/harness-mode-audit.md` for the claim-by-claim check). Published schema:
  `docs/contracts/harness-v1/schema.json`; fixtures: `tests/fixtures/harness-contract/v1/`. As
  shipped, decision 5's version field is named `v` on the wire (currently `"1.0.0"`), not
  `harness_contract_version`.
- **Date:** 2026-09-08
- **Counterpart:** Tack ADR 0066, `~/Sites/objetivosMios/docs/adr/0066-docket-as-a-third-harness.md`.
  It specifies the consumer side and explicitly builds nothing until this contract exists.
  **This document lands first.**
- **Executable plan:** ROADMAP.md "Planned program — PHASE 24" and the Wave 30 cards in
  TODO.md (W30-C1 … W30-C5). This file keeps the reasoning; those keep the work.
- **Why this is docket's first ADR.** ROADMAP §6 is a one-row-per-decision table, and
  everything below §4.5 is explicitly a historical record. A contract another repository
  pins against needs a stable document that a §6 row can cite. §6 keeps the index; this file
  keeps the reasoning.
- **Relationship to §4.5:** it does not amend it. Decision 2 leaves the one-driver rule
  intact, nothing here adds DI, an ORM, an event bus, FastAPI or async, and the entry point
  is a synchronous Typer subcommand in the existing `cli/ core/ edges/` split.
- **Relationship to D-30:** decision 9 amends it in one named place — the `bash` handler may
  be interrupted by killing its process group — and nowhere else. D-30's model of cancellation
  as a persisted lifecycle with cooperative checkpoints is what harness mode runs on.

## What is true today, measured

Read from this tree at `0d3720a` on 2026-09-08; re-verified at `4032133` on 2026-09-11. This is
the pre-implementation baseline, kept as measured: decisions 9 and 11 have since closed the bold
rows about `run_bash` ignoring cancellation and about `ask` always waiting (`ToolContext` now
carries `cancellation_check` and `approval_mode`). `DocketDriver` still ignores `on_spawn`, so
cancellation reaches an in-flight `bash` through that polled check, not through a recorded pid.

| Fact | Where |
|---|---|
| docket owns the turn loop, tool registry, all three policy hooks, approvals, audit and sessions | `core/agent_loop.py`, `core/tools.py`, D-19 |
| The tool surface is already a coding agent's: read, write, edit, glob, grep, bash | `edges/adapters/toolbox.py` |
| Tool roots are jailed by path resolution, not by convention | `resolve_within`, `PathEscapeError`, same file |
| Bash runs with a jailed environment and is killed by process group **on timeout only** | `_jailed_env`, `_kill_group`, `run_bash`'s `communicate(timeout)` handler, same file |
| **Every bash child is its own session (`start_new_session=True`), outside the caller's process group, and `run_bash` never reads `ToolContext.cancellation_check`** — a signal to docket reaches an in-flight command only when that command's own timeout expires | `run_bash`, same file; the `bash` registration in `core/tools.py` passes roots, timeout, env and sandbox but not the callback |
| **`DocketDriver` ignores `on_spawn`, so a run's `pids` list is always empty for a docket-native hop and `docket runs cancel` kills nothing in flight** | `DocketDriver.run_turn` docstring; `core/runs.py::add_hop_pid` docstring says the same |
| Every tool call passes a policy verdict and the decision is audited | `evaluate_tool_call`, `_audit_tool_decision` in `core/tools.py` |
| **A verdict of `ask` blocks the calling thread in `wait_for_approval` (default `TOOL_APPROVAL_TIMEOUT`, 120 s), resolves to denied, and the loop continues; only `max_consecutive_tool_denials` (3) ends the turn** | `dispatch_tool`'s `ask` branch, `core/tools.py`; `run_agent_turn`'s denial accounting, `core/agent_loop.py`; `config.py` |
| The wire is OpenAI-compatible `/v1/chat/completions` over stdlib `urllib` | `edges/adapters/llm.py` module doc |
| A process-wide endpoint override already sits at the **highest** precedence, above stored providers and the hosted default; the API-key fallback chain reads provider env names and then docket's secret store | `resolve_endpoint`, same file |
| The response body is parsed for `choices` and `usage`; `model` is present in the retained `raw` dict and never read; the loop keeps the **last** body and the driver passes it through | `edges/adapters/llm.py`, `ChatResponse.raw`; `AgentLoopResult.raw`; `DocketDriver.run_turn` |
| Token counts are real endpoint counts, accumulated per session; **`TurnResult` carries no usage field** — the driver drops `AgentLoopResult.usage` and exposes the total through `usage()` | `TokenUsage`, `core/llm.py`; `MeasuredUsage`, `core/session.py`; `DocketDriver.usage` |
| The driver declares that it reports no USD cost rather than returning a plausible number | `DriverCapabilities.reports_cost_usd`, `core/runtime_driver.py` |
| `RuntimeDriver` is a typed port with exactly one shipped driver and a stated ban on a second without a trigger | `core/runtime_driver.py` module doc |
| **`DocketDriver.run_turn` requires `.docket-meta.json` under `PROJECTS_DIR/<agent-id>/` and derives its tool roots from `meta.codebase`; a missing meta is an `invalid_output` failure** | `_load_agent_meta`, `_resolve_roots`, `edges/adapters/docket_runtime.py` |
| A turn's outcome is already structured, with a retryable/non-retryable failure vocabulary | `TurnResult`, `FailureKind`, same file |
| **Run records already have a persisted id, state machine, cross-process cancellation request and a `ContextVar` that the driver reads to wire cancellation into the loop and the approval wait** | `create_run`, `execute`, `cancel_run`, `current_cancellation_signal`, `core/runs.py` |
| **`trace_event` validates, redacts and appends; it has no subscriber seam, and `DOCKET_NO_TRACE=1` suppresses it before any write** | `core/trace.py` |
| **`ui.console` writes to stdout; `core/` never prints** | `ui.py`; the core-never-prints layer rule in TODO.md "How to use this board" step 3 |
| `POST /dispatch/` answers before the pipeline runs, on a daemon thread | `serve.py`, the `/dispatch/` branch |
| There is no docket-native auth exchange; credentials are stored keys | `docket auth` help text, `cli/__init__.py` |
| Everything docket owns lives under `DOCKET_HOME`, defaulting to the user's `~/.docket`; the value is read once at import | `config.py` |
| **The CLI return-code convention is flat: 0 and 1, "no other exit codes are produced"** | `specs/api/cli-interface.spec.md`, "Return Code Convention" |

**One correction found while measuring.** ROADMAP §6's D-14 row still names **OpenClaw** as
the one shipped driver. The code says `edges.adapters.docket_runtime.DocketDriver`, and D-19
is why. The row is stale, not wrong-in-spirit; it should be corrected in the same change that
adds D-35, because a decision table that misnames the thing it decided is what gets quoted
next.

**What the bold rows mean for the work.** The four capabilities this ADR leans on hardest —
interruptible cancellation, a non-waiting approval outcome, an event stream, and a
non-interactive entry point — are each one small seam away, and none of the seams is the
subcommand. The subcommand is the last card, not the first.

## What harness mode is *not*, and why each exclusion is load-bearing

- **Not a pod, and not a team.** One agent, one loop, one result. The multi-agent pipeline is
  docket's differentiator and it does not fit a caller whose unit of work is a single
  attempt with a single outcome. A pod-shaped harness is a later decision with a different
  contract.
- **Not a server.** No port, no registry, no background thread. Harness mode is a process
  that starts, works and exits.
- **Not a plugin boundary.** Decision 2 is the whole of it. If someone finds themselves
  adding driver selection or entry-point discovery to support this, they have left the
  decision and should stop.
- **Not a second store.** The run token is a run record in the `docket-runs.json` of a home
  the caller owns and disposes of. No new persisted format, no schema.
- **Not a second event vocabulary.** stdout carries the trace events docket already
  specifies, redacted by the same function, inside an envelope. A field the trace does not
  have is added to the trace, not to the harness.
- **Not silent.** `DOCKET_NO_TRACE=1` would empty the stream; harness mode refuses to start
  under it rather than run unobserved.
- **Not part of `docket-runtime`.** The subcommand is CLI and stays in the full distribution.
  The three seams it needs (`run_bash` cancellation polling, `approval_mode`, the trace
  subscriber) live in the runtime closure and must keep it CLI-free.

## What docket gets out of it

**A consumer for `RuntimeDriver` that is not docket.** The port was formalised as containment
of coupling and has had exactly one caller ever, all of it in-repo. §4.5's own anti-pattern
list ends with "abstract before the second caller exists." This is the second caller, and it
arrives without repealing the one-driver rule.

**A user interface, without building one.** The backlog has said since Phase 11 that docket
does not build a dashboard. In harness mode a docket run appears on a board with its
transcript, its token counts, its policy verdicts and its diff, and none of that is docket's
code to write or maintain.

**Distribution reach.** The consumer ships as a single binary with an installer. Harness mode
puts governed docket execution in front of people who will never run `pip install`.

**The execution half of the stated thesis.** `CLAUDE.md` says *docket executes; something
else holds the plan of record*, and names that consumer. Phase 22 built the direction where
it reads from docket. This is the direction where it runs docket, which is the half that
makes the sentence true.

**Two defects fixed for every caller, not only this one.** The `run_bash` cancellation seam
makes `docket runs cancel` actually stop an in-flight command, and `approval_mode` gives
any non-interactive embedding (the Wave 28 adapters included) a truthful outcome instead of a
two-minute wait.

## The risk this accepts

**A published contract is a promise to a codebase this repo does not control.** Until now
every interface here could be reshaped in the same change as its caller. After this,
reshaping an event field breaks a product mid-release. Decision 5's version field and
generated, test-pinned schema are the mitigation, and they are a real, permanent maintenance
cost that should be accepted deliberately rather than discovered later.

**Two products of the same author becoming load-bearing for each other** is the strategic
risk, and it is symmetric — the counterpart ADR states it from the other side. It is bounded
the same way: harness mode is one optional harness among three, so a docket that is broken
or absent degrades the consumer to precisely its current behaviour rather than breaking it.

**Amending D-30 in one place invites amending it in others.** Killing a subprocess group is
safe because no Python state is shared with it; that argument does not transfer to an HTTP
request or a Python tool handler, and this ADR must not be cited as precedent for either.

The residual risk accepted without mitigation is **scope pressure on decision 11**. Once a
run can be watched on a board, someone will want to approve a tool call from there, and that
is a genuinely good feature. It is also the change that turns a subprocess into a session.
It gets its own decision, or this one stops meaning anything.
