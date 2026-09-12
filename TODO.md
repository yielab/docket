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
> ## ◉ ACTIVE BOARD — WAVE 30 (Phase 24, harness mode, D-35)
>
> **Wave 31 closed on 2026-09-12** and is archived in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md). Thirteen cards shipped:
> test lanes with a budgeted agent lane, structural guards, a ratcheted comment budget, one unit
> file per module, in-process CLI tests, a generated command reference, the board archive and
> decision ADRs, the three functions over 500 lines split into named phases, and two cards opened
> by defects the work itself surfaced.
>
> **Both things that were waiting on it are now claimable, and nothing chooses between them
> automatically.** W29-C7 publishes the provenance-complete beta and closes Phase 23; its
> publication approval from 2026-09-07 still stands and only its ordering had changed. All of
> Wave 30 (Phase 24, harness mode, D-35) is also unblocked. Whichever is claimed first, mark its
> section active so the board has one marker again.
>
> **Two of this file's size targets are still gated.** `TODO.md` reaches 200 lines and `ROADMAP.md`
> reaches 500 once Waves 29 and 30 close and their sections archive. Their planned cards and
> measured triggers are what those waves are executed from, so they were deliberately left in place
> rather than trimmed early.
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
   `bash scripts/validate-specs.sh` green · the card's own spec updated with a version bump +
   changelog entry, **Status line matching what actually shipped** · committed `Type: description`
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

## ◇ WAVE 29 UNBLOCKED (2026-09-02, paused 2026-09-11, released 2026-09-12) — adoption evidence and public release

**One card left, and its gate has passed.** C1–C6 are merged, closed and archived in
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

**Status:** CLAIMABLE since 2026-09-12, when Wave 31 closed and released the hold placed on
2026-09-11; publication was approved 2026-09-07 and that approval still stands, only the ordering
had changed · **Size:** M · **Owner:** integrator

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

## ◉ WAVE 30 ACTIVE (2026-09-11, claimed 2026-09-12) — harness mode seams and contract (Phase 24, D-35)

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

**Status:** SENT BACK (2026-09-12) · **Size:** S · **Owner:** —

**Sent back for a regression the card itself surfaced and then shipped anyway.** The new
cancellation-aware wait polls with `proc.wait()`, which does not drain the child's pipes. A command
writing past the operating system's pipe buffer blocks on its next write, never exits, and the poll
loop runs to the deadline. Measured at the card's own commit with one 200 KB command and an
8 s timeout: the no-callback path returned in 0.01 s with `ok=True` and 30,037 characters; the
cancellation-aware path returned after the full 8 s with `ok=False`, zero characters and "command
timed out after 8s". The command had finished instantly in both cases.

This is not narrow. The `bash` handler lambda passes `ctx.cancellation_check` unconditionally, so
any dispatch that wires one takes the new path for every shell command it runs, and a build, a test
run or a verbose git command now fails falsely and loses its output. The handoff called it out of
scope on the grounds that the no-callback path was untouched, which does not follow.

**What is still owed:** drain both streams while polling, keep the cancelled and timed-out branches
reaching `system.docker_kill` and `_kill_group` as they do now, keep the no-callback path
byte-identical, and add the regression test that would have caught this — a command printing well
past a pipe buffer, through the cancellation-aware path with a callback that never fires, returning
promptly with its output intact and matching the no-callback result. Watch it fail first.

**Deterministic trigger:** at `4032133`, `edges/adapters/toolbox.py::run_bash` starts every command
with `start_new_session=True` (each child is its own session, outside any caller's group) and blocks
in `proc.communicate(timeout=timeout)`; the `bash` registration in `core/tools.py` passes roots,
timeout, env and sandbox but not `ctx.cancellation_check`. Reproduction: a `ToolContext` whose
callback flips true 0.2 s into `bash sleep 30` still returns after 30 s (or after the tool timeout,
which defaults to the whole turn's wall clock). Separately, `DocketDriver.run_turn` ignores
`on_spawn`, so `pids` is always `[]` and `docket runs cancel` "kills nothing in flight" for every
docket-native hop. D-30 deliberately let "an already-running handler finish" because a Python thread
cannot be killed safely; a subprocess can, and D-35 decision 9 amends D-30 for this handler only.

**Goal:** `run_bash` accepts an optional `cancelled: Callable[[], bool] | None = None`, waits with a
short bounded poll (`proc.wait(timeout=<poll>)` in a loop that also enforces the existing overall
timeout), and on a true callback kills exactly the way the timeout path already does —
`system.docker_kill` under the docker backend, then `_kill_group` — returning a complete
`ToolOutcome(ok=False, error="cancelled before completion" + sandbox tag)`. The `bash` handler lambda
passes `ctx.cancellation_check`. Nothing else changes.

**Non-goals:** no interruption of HTTP requests or Python tool handlers (D-30 stands there); no
change to `runs.py`'s pid registry or `DocketDriver.on_spawn`; no new `StopReason`,
`ToolDenialKind` or trace event; no CLI/serve/docs change; no change in behaviour or timing when
no callback is given (today's callers stay byte-identical, including the timeout message); no
sandbox-mode change.

**Owns:** `edges/adapters/toolbox.py::run_bash` plus one private poll constant; the `bash`
`handler=` lambda in `core/tools.py::builtin_registry` and nothing else in that file; tests in
`tests/integration/test_sandboxed_exec.py` and `tests/integration/test_cooperative_run_cancellation.py` (or a
new `test_bash_cancellation.py`); the `bash`/exec clauses of `specs/functional/security-gates.spec.md`
and requirement 66's "does not attempt to interrupt a running handler" clause in
`specs/functional/agent-loop.spec.md`, narrowed to non-`bash` handlers, with version bump and
changelog. **Forbidden:** `agent_loop.py`, `approval.py`, `runs.py`, `dispatch.py`,
`docket_runtime.py`, `ToolContext`/`ToolResult`, central files.

**RED tests:** (1) `run_bash(roots, "sleep 30", timeout=60, cancelled=flips_at_0_2s)` returns
`ok=False` within 2 s, the error names cancellation and carries the sandbox tag, and
`os.killpg(pgid, 0)` on the recorded child group raises `ProcessLookupError`; record wall time and
the child pgid. (2) The same command through `run_agent_turn` with a recording backend that
requests one `bash` call and a `ToolContext(cancellation_check=...)` that flips during the call:
the session holds one complete assistant/tool unit whose tool output is the cancelled outcome, the
loop returns `stop_reason="run_cancelled"`, and the backend was called exactly once. (3) With
`cancelled=None`, `sleep 30` under `timeout=1` produces today's exact timeout message and kills the
group (regression guard on the existing path). (4) A bwrap variant of (1), skip-labelled when the
backend is absent. Before implementation, (1) and (2) must fail at the wall-time assertion, not at
setup.

**Acceptance / oracles:** wall time, child-group liveness, session unit atomicity, backend call
count, and byte-identity of the no-callback outcomes are the oracles. `docket runs cancel` against
a run whose hop is inside `bash sleep 30` (through the production driver, isolated home) must
terminalize the run as `cancelled` within 3 s of the request with `observedAt`/`stoppedAt` set —
this is the whole-path proof that the amendment reaches the public CLI without new code.

**Validation:** focused nodes repeated 20× (barrier-timed tests are flaky by construction if
under-bounded); then `test_agent_loop.py`, `test_tool_registry.py` (the only-the-chokepoint-imports-
toolbox AST guard), `test_run_cancellation.py`, `test_runtime_adapter_fixture_contract.py` (runtime
closure still CLI-free); Ruff/format, strict mypy, both owning specs; full pytest, 18 goldens,
specs, metrics.

**Handoff:** report measured wall times before/after, the poll constant and why its value, the
D-30 sentence that changed and the one that did not, and the `docket runs cancel` whole-path result.

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

**Status:** TODO · **Size:** M · **Owner:** — · **Depends on:** C1, C2, C3 merged to `main`

**Deterministic trigger:** after C1–C3, the seams and the contract exist and nothing calls them —
the repository's recorded "unwired machinery" shape. `docs/contracts/harness-v1/schema.json` has no
producer; Tack ADR 0066 needs a binary to probe. D-35 decisions 1, 3, 7, 8, 9, 10, 12.

**Goal:** `cli/_harness.py` with `run --workspace DIR (--task TEXT | --task-file PATH) --model
PROVIDER/ID [--role implementer] [--timeout S] [--agent-id ID]` and `status TOKEN`; one
`@app.command("harness", ...)` block in `cli/__init__.py` following `cmd_runs`. Sequence, all
synchronous on the main thread: `harness.preflight` (exit 2 + one `result{status: refused}` on
stdout) → write the meta through `edges/store.py` → `runs.create_run("cli", agent_id)` → emit
`harness_start{token, pid, requested model, workspace}` as event seq 0 → install a `SIGTERM`
handler whose only action is `runs.cancel_run(token)` → `with trace.subscribe(emit)` →
`runs.execute(token, lambda: [driver.run_turn(agent_id, session_key, task, timeout, env,
trace_project=agent_id)])` with `ToolContext.approval_mode="refuse"` reaching the driver
through the existing internal env-coordinate precedent: a `DOCKET_APPROVAL_MODE` constant beside
`PIPELINE_WORKTREE_ENV` in `core/runtime_driver.py`, passed in `run_turn`'s `env`, popped by
`DocketDriver.run_turn` before the tool env is built and mapped onto `ToolContext.approval_mode`
(exactly how `DOCKET_PIPELINE_WORKTREE` already travels) — no Protocol change, no new keyword
→ `driver.usage(agent_id)` → `harness.result_from` → one `result` line → exit 0/1. stdout is
line-buffered (`sys.stdout.reconfigure(line_buffering=True)`) and carries **only** NDJSON; every
log goes to stderr via `ui`'s stderr console; `ui.info/success/warn` (stdout) are forbidden in this
module. `status TOKEN` maps `runs.get_run` to `HarnessStatus` plus the terminal `result` when
finished.

**Non-goals:** no interactive approvals (decision 11), no pod/team, no server, no provisioning of
worktrees or clones, no second driver, no `on_spawn`/pid registration of the harness itself in
`pids`, no README claim (C5), no `docket-runtime` change, no new `config.py` constant.

**Owns:** new `cli/_harness.py`; one command block in `cli/__init__.py`; the smallest addition in
`core/harness.py` the sequence needs; the `DOCKET_APPROVAL_MODE` constant in `core/runtime_driver.py`
and its pop in `edges/adapters/docket_runtime.py::run_turn`; `specs/api/harness-mode.spec.md` Status → "Implemented" with
version bump; a `docket harness` section in `docs/commands.md`; new `tests/integration/test_harness_cli.py`;
`tests/golden/cases/help.golden` regenerated **because a new command appears in `docket help`** —
diff explained line by line in the commit. **Forbidden:** `agent_loop.py`, `tools.py`, `toolbox.py`,
`runs.py`, `approval.py`, `docket_runtime.py` beyond the one env-coordinate pop in `run_turn`,
`specs/README.md`, README, central files.

**RED tests (all against an isolated `DOCKET_HOME` and the loopback OpenAI-compatible
`ThreadingHTTPServer` stub pattern from `test_approval_gated_dispatch.py`, driving the real
`python -m docket` subprocess):** (a) **ok:** stub scripts one `write` call then a final message;
stdout parses line by line, seq is contiguous, the order is `harness_start`, `session_start`, …,
`tool_call`/`tool_result` pair, `session_end`, `result`; every line carries `v="1.0.0"` and the
token; `result.status="ok"`, `model.served` equals the `model` the stub put in its body (deliberately
different from the requested id), `usage` equals the stub's summed `usage` fields, `cost_usd` is
null; exit 0; the run record is `succeeded`; the workspace contains exactly the tool's write;
stderr is non-empty and stdout has no non-JSON byte. (b) **blocked:** `block-destructive` template
in the isolated `POLICIES_DIR`, stub requests `bash rm -rf build` → `result.status="blocked"`,
`blocked.policy_id="block-destructive"`, exit 1, no approval record, run `failed`, one backend
request. (c) **cancelled:** stub requests `bash sleep 30`; the test sends `SIGTERM` to the
subprocess 0.5 s after the `tool_call` event arrives → `result.status="cancelled"` within 3 s, exit 1,
the child pgid recorded in the event stream is gone, the run record is `cancelled` with
`requestedAt`/`observedAt`/`stoppedAt`. (d) **refused ×5:** unset home, default home, missing base
URL, `DOCKET_NO_TRACE=1`, missing workspace → exit 2, exactly one stdout line, no run record, no
meta written. (e) **status:** `live` while (c) is inside its tool call, `finished` with the result
afterwards, `unknown` for a random token. (f) **isolation:** the developer's real `~/.docket`
byte-identical before and after (a)–(e) — assert with a snapshot, do not assume the conftest guard
covers a subprocess. (a)–(c) must fail on the missing command; (d) on the missing preflight.

**Acceptance / oracles:** parsed NDJSON, exit codes, run-record state, approval-store contents,
child-group liveness, workspace diff, home snapshot. **Live oracle (handoff evidence, not a
fixture):** one run against llama.cpp `127.0.0.1:8081` with `DOCKET_TOOL_MAX_OUTPUT_CHARS=2500`, a
temporary home and a throwaway workspace; report the transcript's event count, served model, token
totals and exit code.

**Validation:** focused tests; `test_runs_cli.py`, `test_cli_json_shapes`-family (no existing shape
changed), `test_docket_driver.py`; Ruff/format, strict mypy, `validate-specs.sh`; full pytest;
**goldens regenerated for `help` only**, every other case byte-identical; metrics.

**Handoff:** report the exact route by which `approval_mode` reaches `ToolContext`, the exit-code
table, the golden diff, the live-run figures, and any refusal reason the preflight table lacks.

### W30-C5 — close Phase 24 truthfully and hand the contract to the consumer

**Status:** TODO · **Size:** S · **Owner:** integrator · **Depends on:** C4 merged

**Trigger:** the board contract requires closure to match what shipped, and Tack ADR 0066
decision 4 needs a path, a version and a commit to pin against.

**Goal:** date D-35 in ROADMAP §6 and mark Phase 24 / Wave 30 done in the status table; move this
section to the completed record; add the `harness-mode.spec.md` row to `specs/README.md`; record
the three-exit-code exception in `specs/api/cli-interface.spec.md`'s Return Code Convention (version
bump, changelog); one README sentence scoped to "one agent, one workspace, non-interactive,
caller-owned home" with `scripts/metrics.py --check` green; `CHANGELOG.md` entry; a consumer
handoff packet in `.agents/handoffs/` naming `docs/contracts/harness-v1/schema.json`, the fixture
directory, `HARNESS_CONTRACT_VERSION`, the exact commit, the exit-code table and the two amendments
(D-30 for `bash`; `approval_mode`) so ADR 0066 can proceed.

**Non-goals:** no new behaviour, no claim that decisions/artifacts are supported on the Tack side
(that is Tack's probe to prove), no dollar figures, no "tamper-proof"/"cancel-guaranteed" wording
beyond what C1 measured.

**Acceptance / oracles:** `validate-specs.sh`, `metrics.py --check`, full gates green on the closing
commit; the status table, §6, this board, the spec index and README agree; the handoff packet
resolves every path it names.

---
