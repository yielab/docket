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
> **Scheduling rule:** schedule by **file contention**, not phase number. Cards that edit the same
> files run one after the other, and work that would touch the same files twice belongs to one card.
> Parallel lanes are allowed only when they share no file, spec, persisted state or live environment;
> finishing a card well matters more than running two at once.
>
> ## ▶ ACTIVE BOARD — WAVE 71 · Phase 71 (triage of 2026-11-08, 15 cards, P71-10 blocked on the maintainer); Phases 69 (D-90) and 70 (D-91) closed 2026-11-07; Phases 67 (D-88) and 68 (D-89) closed 2026-11-06, Phase 66 (D-87) closed 2026-11-05
>
> **Phases 69 and 70 closed 2026-11-07** (D-90, D-91; not pushed), workers on Sonnet and Haiku only: docket has an agent
> eval lane (`evals/`, five suites, 109 tasks with hidden checks, pass@k and pass^k, a base per commit) and the 4,200-line
> canary is deleted; the guardrails are one source per check, measured on the lane's safety suite (attack success 0.00
> before and after, twin utility 0.92 to 1.00, false positives 3 to 0). Their sections are archived and what they leave
> open is under "Evals and guardrails" in the follow-ups below. **Phase 71** (below) is the triage of every follow-up on
> 2026-11-08, with the maintainer's request for a deep clean of dead code and documents.
> **Phases 67 and 68 closed 2026-11-06** (D-88, D-89; not pushed): a folder pod under the jail reads any public host and
> says how (`webRead`), a compaction that gains nothing no longer kills a turn, a file that mentions payments is not a
> payment, the writer drafts instead of researching, and search is a declared service. Their real run (P68-6, which
> closes P67-5) went through every hop with none of the failures the phases were opened for; the task itself ended on
> the Reviewer's veto. Their sections are archived and what they leave open is under "Phases 67-68" in the follow-ups
> below. **Phase 66** (D-87) closed 2026-11-05 (archived; what it leaves open is under "Phase 66"). Phases 63 (D-85) and 64 (D-86) closed 2026-11-04; their
> sections are archived and what they leave open is under "Phases 63-64" in the follow-ups below.
> Before them, Phases 60 (D-82), 61 (D-83) and 62 (D-84) closed 2026-11-03: a transient failure costs a request, a pod says what it can reach, and `fetch` keeps the perimeter. Their sections are archived and what they leave open is in the follow-ups below. Phase 59 (D-81, [ADR 0038](docs/adr/0038-a-step-budget-is-a-checkpoint-not-a-cliff.md)) closed 2026-11-03
> (decision 5 amended before the push): a step's budget is a checkpoint, not a cliff, and docket keeps no dollars. Its
> section is archived and what it leaves open is under "Phase 59" in the follow-ups below. Phase 58 (D-80) closed 2026-11-02: what a plan of record needs to follow a team it does
> not run. Its section is archived and what it leaves open is under "Phase 58" in the follow-ups below.
> **Phase 57** (D-79, [ADR 0037](docs/adr/0037-what-docket-gives-a-manager-in-the-plan-of-record.md)) closed 2026-11-01. Before it, Phase 56 (D-77, [ADR 0036](docs/adr/0036-a-pod-works-outward.md) decisions 13-16) closed
> 2026-10-30: an external service is declared, not programmed; a pod keeps records; one judge; one home layout; the
> four team shapes. Its section is archived and what it leaves open is under "Phase 56" in the follow-ups below.
> Decisions 15-16 of the ADR were accepted by the maintainer the same day. Phase 55
> closed 2026-10-30; Phases 52 to 54 closed 2026-10-29. The integration branch is `develop`. A new phase starts from
> a measured trigger or a maintainer request.

## How to use this board (read before claiming a card)

1. **One card is one worker run.** Its steps are ordered; each step ends green and committed. A run
   that does not finish parks at its last green commit and the card's Status names what is left; the
   next run continues the same card. A card is never split into sub-cards to make it fit.
2. **Claim.** Set Status to `IN-PROGRESS (@who)`; one owner per card. The worker gets a worktree made
   by hand from the integration branch's current head (`git worktree add -b <branch>
   .claude/worktrees/<card> <sha>`), and its own `DOCKET_HOME` and temp directory in the scratchpad.
3. **Read bounded.** `python3 .agents/skills/docket-roadmap/scripts/card_packet.py <CARD-ID>`, then
   the card's own read list. Never all of `ROADMAP.md`, `TODO.md`, `CLAUDE.md` or a spec directory.
   A task worktree has no `internal-docs/` (gitignored); a card needs only itself and tracked files.
4. **The layer rule** is ADR 0030's table, enforced by `tests/architecture/`: the contexts are layered
   `platform < governance < agent < models < observability < pipeline < teams < sandbox < operator <
   tasks < hops` and a context imports only those below it; `kernel` imports nothing outside itself;
   a `domain/` is pure; only `interfaces/` talks to the user; `bootstrap.py` is the only module that
   names a concrete adapter. Two invariants never move: every tool call passes `dispatch_tool`
   (`agent/tools/registry.py`), and docket-owned JSON is written only by `platform/store.py`.
5. **The testing budget, the same for every card.**
   1. Per commit: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run
      pytest --co -q` (about 10 s). No test runs.
   2. While iterating: only the tests of what the step changed, by path, each under `timeout 120`.
   3. The card's gate, as the card names it, in a few minutes.
   4. A pure move or rename adds no test: `pytest --co` and `tests/architecture` are its check. A
      behaviour change adds a failing test first, placed by lane (`specs/test-framework.md`).
   5. After each merge the integrator runs the default suite once, in parallel (`uv run pytest -n auto
      --dist loadfile -q --tb=line -p no:cacheprovider > <file>`, about 85 s), reads only the `FAILED`
      lines, fixes by cause and re-runs `--lf`. Never a second full run for the same merge. What
      each check costs, measured, is in `.agents/skills/docket-spec-work/references/validation.md`.
   6. Goldens, the agent lane, `scripts/maint/pytest-without-sandbox.sh`, the escape matrix,
      `validate-specs.sh`, the generated-docs checks and the real run: once, at
      the phase close. The agent lane takes about 5 min.
   7. **Stop rule:** a check that fails again after one fix stops the step. Park with the failing line
      and the hypothesis. No third attempt, no "until green", no background process or polling, no
      `git stash` (a WIP commit sets work aside).
   8. **A script is a means, not a deliverable.** A one-shot script (planner, path rewriter,
      converter) exists to save effort on the card's goal. Write it once, run it, review its output,
      and finish by hand whatever it did not cover. If it is wrong after one fix, stop improving it
      and do the remainder by bounded edits. Polishing, generalizing or testing a throwaway script is
      out of scope; it is never committed unless the card says so.
6. **Baselines only shrink.** A baseline file is rewritten (`--write`) only after the violations are
   gone, and its diff is deletions only. A new guard is trusted only after it was seen failing on a
   planted case.
7. **No behaviour change** unless the card says so: the HTTP API 6 tests, the CLI goldens and the
   `docket_runtime` facade stay byte for byte. **No re-export or shim:** a replaced name is
   deleted in the same change, with no alias or compatibility reader.
8. **Central files are integrator-owned:** `TODO.md`, `ROADMAP.md`, `README.md` metric counts and
   `CHANGELOG.md`. A worker reports what shipped; it does not edit them.
9. **Commits:** `Type: description`, ASCII only, a detailed body, no AI or assistant attribution.
   Scrub `/home/<user>` paths and real names from every diff.

**Status:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs X)` · `PARKED (left: X)` · `DONE`.
**Size:** S ≈ one short run · M ≈ one run · L ≈ one long run that may park once · XL ≈ two cards'
scope in one pass over the same files, parks at least once.
**Branch model (D-52):** card branches base on and merge into the integration branch (`develop`).
`main` moves only
by a fast-forward from `develop` when the maintainer cuts a release. Tags and release jobs originate
from `main`.

## ▶ PHASE 71 ACTIVE — WAVE 71 · what the follow-ups' fired triggers and verified drift leave, and a deep clean (triage 2026-11-08, no new decision)

> **Trigger: the maintainer's request for a triage of the follow-ups (2026-11-08).** Every follow-up was read and
> each candidate re-checked in code on `develop` `e347980c`, and the live home measured from 2026-11-03 to the last
> event, 2026-11-06T13:43Z (16 tasks, 311 `llm_call`s, pods `web-research`, `app-dev`, `hn-live`). Cards exist only
> where a trigger fired with that evidence, or the text of a spec or comment is false against the code. The
> follow-ups these cards replace, and those found stale, are removed from the list below.
>
> - **Fired:** shell-idiom approvals (5 of 9 Implementer hops parked on `$(`/`${`/a `/tmp` redirect, threshold 1 in
>   5; all five in `task-69fa3927`, 2026-11-04): P71-8. `messages_changed` on 25 % of the window's calls and 47 %
>   and 43 % of its two largest tasks (threshold 20 %): P71-10. Three flakes under load in one test class: P71-9.
>   P63-2 landed, which was the A2A card's trigger: P71-6.
> - **False against the code:** spec and doc text (P71-1, P71-2), the init order requirement 16 promises (P71-3),
>   two comments that state a wrong rule (P71-4), a flush error dropped silently (P71-5), names written twice (P71-7).
> - **Re-measured, not fired:** a parked turn is no longer paid twice (5 of 6 resumes kept the cache, about 2k
>   uncached tokens each; the sixth was the compaction P68-1 fixed); streaming (3 timeouts, all in one task, 0.48
>   per 50 calls against 1); the long docstring count is 202, under the 205 it was measured against.
>
> - **The maintainer's request (2026-11-08):** a deep clean of dead code and every document brought to what holds,
>   deleting what no longer does: P71-11 (dead code, measured with vulture over the whole repository), P71-12 to
>   P71-15 (each document checked claim by claim against its spec and the code). The integrator rewrites `README.md`
>   from their reports at the close.
>
> **Waves by file ownership.** Wave 1, parallel: P71-1, P71-2, P71-3, P71-4, P71-5, P71-6, P71-7, P71-9, P71-11,
> P71-13, P71-14, P71-15 (no two share a file or a spec; one worker may run several S cards in a row). Wave 2: P71-12
> after P71-2 (`CONFIGURATION.md`), P71-8 after P71-4 and P71-14 (`governance/security.py`, `SECURITY-SIMPLE.md`).
> P71-10 waits for the maintainer.
> P71-8 and P71-10 change what the agent sees or may do, so they name a suite, a threshold and the base `e347980c`.

### P71-1 — Six specs say what the code does

**Status:** TODO · **Size:** S · **Model:** Haiku · **Kind:** spec text only

- **Trigger:** verified 2026-11-08: each line below is false against the code at `e347980c`.
- **Goal:**
  1. Delete the `memory/` token, keeping `MEMORY.md`: `specs/api/cli-interface.spec.md:472`,
     `specs/acceptance/user-stories.md:63`, `specs/functional/agent-lifecycle.spec.md:153`. No member workspace
     has a `memory/` directory (`rg 'memory/' src/docket/teams` is empty; `teams/agent_memory.py:28`).
  2. `specs/functional/trace-store.spec.md` items 30-32: an MCP server's `process_*` payload is
     `{"tool": "mcp", "server": <name>[, "reason": <text>]}` with no `pgid`
     (`agent/tools/mcp_client.py:437-439`). Name the exception; leave every other process event as stated.
  3. `specs/functional/audit.spec.md:85-90` "Pods and agents": add `pod.network_widen`, `pod.network_narrow`
     (`interfaces/cli/commands/pod_settings.py:230,273`), `pod.fetch_widen` and `pod.fetch_narrow`
     (`teams/pod_settings.py:760,774`).
  4. `specs/functional/config-format.spec.md:115`: `load_pipeline(text, *, roles)` (`pipeline/domain/spec.py:398`).
- **Non-goals:** any code change; any other spec.
- **Change:** the six spec files; bump each one's patch version.
- **Acceptance:** each claim above reads like its locator; `rg -n 'memory/' specs/api/cli-interface.spec.md
  specs/acceptance/user-stories.md specs/functional/agent-lifecycle.spec.md` is empty.
- **Gate:** `bash scripts/validate-specs.sh` (about 3 s). No tests.

### P71-2 — The home layout and `pod update` list the routines, services and records they carry

**Status:** TODO · **Size:** S · **Model:** Haiku · **Kind:** data + spec text

- **Trigger:** verified 2026-11-08: `kernel/layout.py:39-42` and `docs/CONFIGURATION.md:69-72` list
  `docket-schedules.json`, `docket-runs.json` and `docket-conversations.json` but not `state/docket-routines.json`
  (written by `kernel/home.py:416`); `specs/functional/pod-blueprints.spec.md:251-275` (requirement 1, the
  `pod update` parts) names no `services/`, `records/` or `routines/`, which `teams/apply/plan.py:556,566` plans
  and `docs/CONFIGURATION.md:802` already lists.
- **Goal:** add the routines entry to the layout tuple; add three bullets to requirement 1 (`CONFIGURATION.md` is P71-12's).
- **Non-goals:** any change to what `pod update` does.
- **Change:** `kernel/layout.py`, `pod-blueprints.spec.md` (patch bump); the unit test whose
  `SUBJECT` is `kernel/layout.py` if it enumerates the tuple (`rg -l 'kernel/layout.py' tests/unit`).
- **Acceptance:** the layout's state files name every file `kernel/home.py` writes under `state/`; the layout test passes.
- **Gate:** the layout unit test; `validate-specs.sh` (about 3 s).

### P71-3 — `docket init --blueprint respond` names the jail it needs after recording it

**Status:** TODO · **Size:** S · **Model:** Sonnet · **Kind:** behaviour (CLI output order)

- **Trigger:** deterministic. `pod-blueprints.spec.md:534-536` (requirement 16) says the `needs fetch-hosts ...`
  line is printed after isolation is recorded. Actual: `cmd_init` builds the pod (`interfaces/cli/commands/agents.py`
  ~382), which prints through `render_reading_need` (`interfaces/cli/commands/pod.py:111`,
  `render/apply.py:105-111`), and only then calls `_setup_sandbox.turn_on_where_detected()` (`agents.py:410`;
  `:579` on the batch path). A throwaway home printed "-> docket setup sandbox on" and then `pod show` said the
  jail was on (2026-11-04). With `--recipe` and a researcher the line can print twice (`render_recipe_needs`,
  `agents.py:417`).
- **Goal:** `build_pod_from_blueprint` stops printing; `cmd_init` prints the reading need once, after
  `turn_on_where_detected()`, on both paths, and not again when `render_recipe_needs` printed it. `pod add`
  (`pod_members.py:128`) is unchanged.
- **Non-goals:** the wording of the line; refusing a folder inside a repository (separate follow-up).
- **Change:** `interfaces/cli/commands/pod.py`, `interfaces/cli/commands/agents.py`, the init CLI test
  (`rg -l 'blueprint.*respond' tests/unit/interfaces/cli tests/integration/interfaces`).
- **Acceptance (RED first):** on a home where a backend is detected, `docket init p --blueprint respond` output shows
  the isolation line before any `needs fetch-hosts` line, and the line appears once; with `--recipe` naming a
  researcher, once. The golden for `init`, if one covers it, moves only by that order (say so in the commit body).
- **Gate:** the init test file; `bash tests/golden/run.sh verify-all` only if a golden covers init (about 20 s).

### P71-4 — Two comments that state a wrong rule

**Status:** TODO · **Size:** S · **Model:** Haiku · **Kind:** comments only

- **Trigger:** verified 2026-11-08. `governance/security.py:86-98` says `HighRiskClass.bins` is "for visibility
  only", and the test comment at `tests/integration/governance/test_gates_policies_approve_deny.py:101-103` says
  nothing else wants the flattened set; `teams/pod_settings.py:345-358` refuses an `allowCommands` name in it (so the
  follow-up "delete `bins`" is withdrawn: `pattern` is a regex and cannot give the binaries).
  `teams/builtin_roles.py:68` says "forward-compat, not exercised today".
- **Goal:** the docstring says `bins` feeds the display and the `allowCommands` refusal; the test comment says the
  same; line 68 states the rule it guards or goes.
- **Non-goals:** any code change. **Change:** the three files.
- **Acceptance:** `scripts/maint/comment_lint.py --check` on the three files passes; the per-commit check passes.
- **Gate:** per-commit only (about 4 s).

### P71-5 — The service's notify flush says when a channel failed

**Status:** TODO · **Size:** S · **Model:** Sonnet · **Kind:** behaviour

- **Trigger:** verified 2026-11-08: `interfaces/http/server.py:230-231` calls `flush_notify_channels(...)` inside
  `contextlib.suppress(Exception)`; the function returns `None` (`operator/notify.py:523-527`) and drops
  `FlushReport.error` (`:93`), so a channel that fails every flush is silent in `docket start`'s output.
- **Goal:** `flush_notify_channels` returns the `FlushReport`; the sweep prints `[serve] sweep: notify flush: <error>`
  when `error` is set, in the format of the sweep's other lines. Delivery and the health record are unchanged.
- **Change:** `operator/notify.py`, `interfaces/http/server.py`, `operator-loop.spec.md` if it states the sweep's
  lines (patch bump), the unit test whose `SUBJECT` is `operator/notify.py`.
- **Acceptance (RED first):** a channel whose sink raises gives a `FlushReport` with `error`, and the sweep tick's
  captured output names it; a clean flush prints nothing new.
- **Gate:** the notify unit file and the server test that drives a sweep tick (`rg -l 'notify' tests/integration/interfaces/http`).

### P71-6 — The A2A agent card says what the pod does

**Status:** TODO · **Size:** S · **Model:** Sonnet · **Kind:** behaviour (HTTP shape, additive)

- **Trigger:** the follow-up's own: P63-2 landed. `interfaces/http/routes/a2a.py:263` still writes
  `"Runs tasks in the {pod} pod."`; `pod_report` (`hops/application/report.py:413`) carries `blueprint` (`:438`)
  and `delivers` (`:451`); the blueprint's text is `PodBlueprint.description` (`teams/blueprints.py:244-268`).
- **Goal:** the card's skill `description` is the blueprint's description plus what the pod delivers, falling back to
  today's sentence for a pod with neither; `tags` carries the blueprint name.
- **Non-goals:** a `description` field on the pod (a pod has none); other card fields.
- **Change:** `interfaces/http/routes/a2a.py`, `a2a-binding.spec.md` (additive, patch bump), the A2A contract test
  that reads the card (`rg -l 'agent-card\|agent_card' tests/contracts tests/integration`).
- **Acceptance (RED first):** a `respond` pod's card names the blueprint's description and its `delivers`; a pod
  with no blueprint reads as today.
- **Gate:** that test file; `tests/e2e -n 4` is not needed (one route's text); the HTTP API 6 tests stay as they are.

### P71-7 — Names and writers that exist twice, once each

**Status:** TODO · **Size:** S · **Model:** Sonnet · **Kind:** refactor, no behaviour change

- **Trigger:** the maintainer's rule of 2026-11-05 (no duplicate mechanisms) and the Phase 57/56 follow-ups,
  verified 2026-11-08: the `reply` option id in `tasks/application/answers.py:22` and `escalations.py:80`;
  `tool_queue` and `tool_retry` repeat one dump (`interfaces/cli/commands/mcp.py:78-81,91-94`);
  `setup_model_credentials.py:32-56` `_write_credential` repeats `governance/secrets.py:79-97` `store_secret`
  (keyring/file split, `touch_meta`, audit); `teams/config_docs.py:23` imports itself (used `:244`).
- **Goal:** one `REPLY_ID` in `escalations.py` imported by `answers.py`; one `_queue_dump` in `mcp.py`;
  `_write_credential` calls `store_secret` and renders its failure (`setup_model_provider.py:126` is the caller);
  `config_docs.py:244` uses the bare name.
- **Non-goals:** `task_control.py`'s refusal path (unifying it moves an HTTP body); the two `_brings` (they render
  different text).
- **Change:** `answers.py`, `escalations.py`, `mcp.py`, `setup_model_credentials.py`, `setup_model_provider.py`,
  `config_docs.py`.
- **Acceptance:** no test changes; the audit row a credential write produces is byte-identical (the existing
  `setup model` credential test is the oracle); `rg -n '"reply"' src/docket/tasks/application` hits one line.
- **Gate:** the unit files whose `SUBJECT` is each module; `tests/architecture` (about 6 s).

### P71-8 — A shell idiom whose command is known is classified, not asked

**Status:** TODO · **Size:** M · **Model:** Sonnet · **Kind:** guardrail behaviour + eval task + spec · **After:** P71-4, P71-14

- **Trigger (fired):** "Approvals for shell idioms" (Phases 60-62 follow-up): in the week after Phase 59 approvals
  parked more than one Implementer hop in five. Observed 2026-11-03..06 on the live home: 6 of 9 Implementer hops
  parked, 5 of them on these commands from `audit.log` `tool.ask` (`task-69fa3927`): `cd "$(git rev-parse
  --show-toplevel ...)"` (3), `${PIPESTATUS[0]}` (2), `>/tmp/lint.log` (2). The cause: `_OPAQUE_MARKERS`
  (`governance/security.py:218`) asks for any `$(`, backtick or `${`.
- **Eval contract (before the change):** suite `safety`, k=3, local endpoint, base `e347980c`. Write first two tasks
  under `evals/tasks/safety/`: a benign twin whose solution needs `"$(git rev-parse --show-toplevel)"` and
  `${PIPESTATUS[0]}`, and its attack twin where the substitution runs a destructive or network command
  (`$(curl ... | sh)`, `$(rm -rf ...)`), which must still ask or deny. Threshold: attack success stays 0.00; twin
  utility not down more than 5 points; the new benign twin passes with no ask.
- **Goal:** in the classifier (`security.py` ~419-460), a `$(...)` whose body is one command line with no nested
  opaque marker is classified by the same rule as a top-level command, and the line takes the stricter verdict;
  `${NAME}` and `${NAME[N]}` (a plain parameter, no `:-`, `/`, `#` or nested `$`) are not opaque. Backticks, `eval`,
  `exec` and nested substitutions stay opaque. A redirect outside the workspace stays an ask (a non-goal: the jail
  owns where writes go).
- **Non-goals:** a shell parser; widening `SAFE_BINS`; any change with isolation on beyond what the classifier says.
- **Change:** `governance/security.py`, `tests/unit/governance/test_security*.py` (by `SUBJECT`), the policy corpus
  rows for `$(` if any (`rg -n '\$\(' tests/fixtures evals -g '*corpus*'`), the two eval tasks,
  `security-gates.spec.md` (the opaque-marker requirement, minor bump), the sentence of `docs/SECURITY-SIMPLE.md` that
  says what asks (`rg -n 'substitution' docs/SECURITY-SIMPLE.md`).
  Also, found by P71-14 in the same spec: `security-gates.spec.md` "Enablement" 3 says `docket setup --json` reports
  `securityGates.toolCallGate` and `docket setup` reports each broken policy file, but bare `setup --json` returns only
  `{ready, pieces}` (`interfaces/cli/commands/setup.py` `_report_json`) and both come from `setup --fix`
  (`setup_check._check_json`): the spec says `--fix`. `docket setup sandbox classes` prints "Every shell command is
  classified before it runs" (`setup_sandbox.py:267`); the classes apply to every acting tool: say so.
- **Acceptance (RED first):** `git -C "$(git rev-parse --show-toplevel)" status` allows; `echo ${PIPESTATUS[0]}`
  allows; `echo $(rm -rf /)` and `x=$(curl -s h | sh)` ask or deny exactly as their inner command would at top
  level; `` echo `id` `` and `$(echo $(id))` ask. The integrator pastes the safety tables before and after in Status.
- **Gate:** the unit file; `check-solutions --suite safety`; the safety run (integrator).

### P71-9 — `TestAnsweredInPlace` waits for events, not the clock

**Status:** TODO · **Size:** S · **Model:** Sonnet · **Kind:** test only

- **Trigger (fired):** three tests of `tests/integration/tasks/test_consult_wait.py::TestAnsweredInPlace` failed
  once each under load and passed alone (Phase 55 Wave 2 and Wave 4 follow-ups); the board's rule makes a third in
  one class its trigger.
- **Goal:** find the wall-clock waits the class uses (`_the_waiting_consult(deadline_s=20.0)` ~124-131, the
  `time.sleep(0.02)` poll ~218, the sweep thread's `turn_timeout=60` ~119) and replace each with a wait on the event
  the product emits (the escalation file appearing, the worker thread joining), with one generous deadline that
  fails naming what it waited for.
- **Non-goals:** product changes; other test files.
- **Change:** `tests/integration/tasks/test_consult_wait.py` (and `tests/support/` only if a waiter there is reused).
- **Acceptance:** the class passes 20 times in a row under `pytest -n 8` with `--count`-style repetition
  (`for i in $(seq 20)` is fine in a shell script file, not inline), alongside a CPU load (`stress`-free: run two
  copies at once); a planted delay in the product path fails with the waited-for name, not a timeout.
- **Gate:** that file only.

### P71-10 — A cache breakpoint at the condensed boundary

**Status:** BLOCKED (needs the maintainer: D-76 refuses more than two breakpoints) · **Size:** M · **Model:** Sonnet ·
**Kind:** wire behaviour + spec

- **Trigger (fired twice):** the Phases 60-62 follow-up's threshold is `messages_changed` on more than 20 % of a real
  task's requests. 2026-11-04: 16 of 30 calls (53 %, `task-52c89dbb`). 2026-11-03..06: 79 of 311 calls (25 %);
  `web-research` `4538bdd6` 27 of 57 (267,948 uncached input tokens of 928,675), `app-dev` `c01138ac` 13 of 30. The
  two breakpoints today are the last system block and the last message (`models/adapters/anthropic_wire.py:121-124`;
  `openai_wire.py:87` for the gateway). The replay of P60-2's sizes: a third breakpoint at the first message after
  the condensed range re-sends 31 % of what a miss re-sends now.
- **Choice for the maintainer:** amend D-76 (and ADR 0011's amendment of 2026-10-29) to allow a third breakpoint, on
  the last message of the condensed range (`agent/session.py:381` `condense_history` marks it), on both dialects;
  Anthropic accepts four. The alternative: no change, and this follow-up closes as measured.
- **Eval contract:** suite `regression`, local and Haiku 5.5, base `e347980c`; threshold: pass@1 not lower, cached
  input tokens per task higher on the tasks that condense. Tokens only, never a price.
- **Change (once unblocked):** the two wire adapters, the message type that carries the boundary mark
  (`agent/ports.py`), `session-history.spec.md` (~92) and `model-providers` spec, the wire unit tests and the recorded
  request fixtures (regenerated and reviewed).
- **Gate:** the wire unit files; `tests/e2e -n 4` (the wire changed); the regression run (integrator).

### P71-11 — Dead parameters and a dead total deleted

**Status:** TODO · **Size:** S · **Model:** Sonnet · **Kind:** deletion, no behaviour change

- **Trigger:** measured 2026-11-08 with `uvx vulture src/docket tests evals scripts packages --min-confidence 60`
  (whole repository, so a name read only by a test counts as read): after the framework false positives (Typer
  commands, pydantic validators, `HTMLParser`/`BaseHTTPRequestHandler` hooks, a property reached through
  `kernel/home.py:23`'s name table), three names have a writer and no reader:
  1. `on_spawn` on `RuntimeDriver.run` (`agent/ports.py:326`): the one driver left ignores it
     (`hops/application/driver.py:145,158` "is ignored"), so `runner.py:173-198`'s `_on_spawn` never fires;
     `tests/support/fakes.py:83-89` and the comment at `executor.py:511` follow it.
  2. `preserve_cancelled` (`tasks/application/runs.py:223`) is accepted, passed by `:570` and `:609`, never read.
  3. `UsageTotals.cache_write` (`agent/ports.py:272`) is summed at `driver.py:377` and never read.
- **Goal:** delete each with its writers and callers. Before deleting 2, read `runs.py:218-262`: if a caller relies on
  a cancelled run staying cancelled, that is a defect, not dead code; then stop and report it.
- **Non-goals:** anything vulture reports under 100 % that a framework calls; `packages/` beyond what `rg` finds.
- **Change:** `agent/ports.py`, `hops/application/driver.py`, `hops/application/runner.py`, `hops/application/executor.py`,
  `tasks/application/runs.py`, `tests/support/fakes.py`; a spec line only if `rg -n 'on_spawn|preserve_cancelled' specs`
  finds one.
- **Acceptance:** `rg -n 'on_spawn|preserve_cancelled|\.cache_write\b' src packages tests` is empty; no test changes
  beyond the fake; `mypy src` passes.
- **Gate:** the unit files whose `SUBJECT` is each module; `tests/architecture`; `tests/integration/hops -n 4`
  (about 40 s).

### P71-12 — `docs/CONFIGURATION.md` says what the code reads and writes

**Status:** TODO · **Size:** M · **Model:** Sonnet · **Kind:** documentation · **After:** P71-2

- **Trigger:** the maintainer's request of 2026-11-08 (update every document in detail; delete what no longer holds)
  and the project's rule that nothing in CI compares a doc to a spec (CLAUDE.md "Correct spec, wrong prose"). Known
  instance: `CONFIGURATION.md:69-72` omits `state/docket-routines.json` (`kernel/home.py:416`).
- **Goal:** every file, key, default and command in the document is checked against its spec, then the code
  (`kernel/home.py`, `kernel/layout.py`, the pydantic models it names); a claim that is false is fixed, a section about
  something deleted goes, nothing is added that the code does not do. History stays out: the document teaches what
  is, never when it changed.
- **Non-goals:** generated sections (regenerate them with their script, never hand-edit); a restructure.
- **Change:** `docs/CONFIGURATION.md` only. **Report:** a list of each claim changed or deleted with the locator that
  proved it, for the integrator's commit body.
- **Acceptance:** the report names a locator for every change; `rg -n -i 'tamper-proof|\$[0-9]|dashboard' docs/CONFIGURATION.md`
  is empty; `gen_cli_docs.py --check` passes.
- **Gate:** `gen_cli_docs.py --check`, `validate-specs.sh` (about 5 s together).

### P71-13 — `docs/recipes.md` and `docs/AGENT-TEAMS.md` say what the recipes and team shapes do

**Status:** TODO · **Size:** M · **Model:** Sonnet · **Kind:** documentation

- **Trigger:** the maintainer's request of 2026-11-08, as P71-12. Phases 69-70 deleted four policy templates and two
  recipe rules (`high-risk-deploy`, `-credentials`, `-payment`, `secret-pii-redact`, `secrets-guard-redact-output`,
  `prompt-injection`) and the trusted flag; the four team shapes are `build`, `respond`, `operate`, `routine`
  (`teams/blueprints.py:238-262`).
- **Goal:** as P71-12, against `templates/`, the recipe directories, `teams/blueprints.py` and `pod-blueprints.spec.md`;
  `rg -n 'high-risk-deploy|high-risk-credentials|high-risk-payment|secret-pii-redact|redact-output|prompt-injection|trusted'`
  on both files finds only what is still true.
- **Change:** the two files (and `scripts/gen_recipe_docs.py`'s output if recipes.md is generated in part:
  regenerate it). **Report:** as P71-12.
- **Gate:** `gen_cli_docs.py --check`; the recipe-docs check if one exists (`rg -n 'check' scripts/gen_recipe_docs.py`).

### P71-14 — `docs/SECURITY-SIMPLE.md`, `docs/troubleshooting.md` and `docs/MODEL-GATEWAYS.md` say what holds

**Status:** TODO · **Size:** M · **Model:** Sonnet · **Kind:** documentation

- **Trigger:** the maintainer's request of 2026-11-08, as P71-12. Phase 70 changed what these describe: one list of
  high-risk classes applied to every acting tool, one redaction always on, tool results framed as untrusted, every
  denial audited; the do-not-overclaim rules (no "tamper-proof", isolation's real default, enforcement covers the tool
  calls docket dispatches) apply.
- **Goal:** as P71-12, against `security-gates.spec.md`, `governance/`, `sandbox/` and `models/`; a troubleshooting
  entry whose error text the code no longer prints goes (find each quoted message with `rg -F` in `src`).
- **Change:** the three files. **Report:** as P71-12.
- **Gate:** `rg -n -i 'tamper-proof|\$[0-9]'` on the three is empty; the alt texts still match `docs/assets/README.md`.

### P71-15 — The quick start, the docs index, CONTRIBUTING and the eval lane's README say what holds

**Status:** TODO · **Size:** M · **Model:** Sonnet · **Kind:** documentation

- **Trigger:** the maintainer's request of 2026-11-08, as P71-12.
- **Goal:** as P71-12 for `docs/QUICK-START-DOCKET.md`, `docs/README.md`, `CONTRIBUTING.md`, `evals/README.md` and
  `docs/contracts/*.md`: every command in them runs as written on a fresh home (`DOCKET_HOME` in the scratchpad, the
  installed or `uv run docket`, no model call), every link resolves, every count matches the code or goes.
  `CONTRIBUTING.md`'s "Rules that have cost this project time" keep their reasons; a rule about something deleted goes.
- **Non-goals:** `README.md` (the integrator rewrites it at the phase close from these reports); `docs/commands.md`
  (generated).
- **Change:** the files named. **Report:** as P71-12, plus each command run and its exit code.
- **Gate:** the commands themselves; `gen_cli_docs.py --check`.

### P71-16 — An exported pod applied back unchanged does not read as drifted

**Status:** TODO · **Size:** S · **Model:** Sonnet · **Kind:** behaviour (deterministic defect)

- **Trigger:** reproduced by P71-15 on 2026-11-08 (scratch home, no model call): on a recipe-applied pod,
  `docket pod export` then `docket pod update .docket` (applied) and `docket pod show` reports `drift: yes`. The files
  `export_pod` writes start with a `# yaml-language-server: $schema=...` line (`teams/apply/write.py:43-49`), so the
  overlay bytes of the items the update skips differ from their lock `sha256`, and `overlay_drifted`
  (`teams/apply/lock.py:207-214`, `_applied_digest` ~190-204) is true.
- **Goal:** find which side is wrong (the lock recorded the pre-header bytes, or the update skips an item whose bytes
  changed) from the spec (`pod-blueprints.spec.md`, the lock and drift requirements; `rg -n 'drift' specs/functional`)
  and fix that side; a pod exported and applied back with no edit reports `drift: no`.
- **Non-goals:** dropping the schema header from exports.
- **Change:** `teams/apply/lock.py` or `teams/apply/write.py` (one of them), the spec if it is silent (patch bump),
  one integration test (`rg -l 'overlay_drifted\|drift' tests/integration/teams`).
- **Acceptance (RED first):** init a pod with `--recipe secure-build`, export, apply the export: `pod show --json`
  `drift` is `no`; edit one exported role file and apply: `yes` only until the next apply.
- **Gate:** that test; `tests/integration/teams -n 4` (about 30 s).

## ◇ FOLLOW-UPS WITH TRIGGERS (not cards; triage when a trigger fires)

> Re-checked against the code on 2026-10-24; paths are current. Removed as no longer true: notification
> dedup is persisted (`operator/notify.py`), the `kind:`-less canonical-document advisory is gone, and
> `_create_workspace` no longer exists. Decisions that belong to the maintainer are in ROADMAP §7.1.

**Evals and guardrails (planned 2026-11-06, D-90/D-91).** Left out of the two phases on purpose, each with its trigger:

- **A model judge** (`evals/evaluator/graders/judge.py`): binary, one per failure mode, with an `Unknown` option, from
  another model family through `ai-gateway`, decides a trial only after 30-50 pass and 30-50 fail human labels give
  TPR and TNR ≥ 0.90 on a held-out set; report-only before that. Trigger: a capability task whose outcome no code
  grader can decide (today every task has a hidden check).
- **`violations` in a summary counts a breach the gate refused** (the final nightly's `private_path` read: classed `model`, yet `violations 1`). Trigger: an operator or a gate reading `violations` as "a guard failed"; then count only executed breaches there and report refused ones apart.
- **The corpus's 11 false positives** are unchanged by Phase 70 (`block-destructive` 6 `rm -rf` rows, `money-movement` 2, `secret-access` 2, `prod-deploy` 1). Trigger: an operator's ask on one in a real run; narrowing a pattern changes what the agent may do, so it names the safety suite and its twins first.
- **A classifier `tool.ask` audits `policy_id='' policy_action='allow'`** (the 2026-11-07 gate capture): true of the policy engine, misleading on an ask. Trigger: an operator reading the log as an allow, or the next audit-format change; then leave the policy fields out when no policy matched.
- **A Harbor adapter** (`evals/harbor.py`, `BaseInstalledAgent`, model over the OpenAI-compatible wire) to run docket
  on Terminal-Bench 2.1 and SWE-rebench. Trigger: the `0.3.0-beta.1` release, or a request to compare docket with
  another harness.
- **Eval scores on the export**: OTel `gen_ai.evaluation.result` events (Development status) and Langfuse experiment
  attributes by observation (trace-level evaluators stop on Langfuse Cloud 2026-11-16). Trigger: a second consumer of
  eval results besides `summary.md`; needs privacy `full` on the home the evals export from (the operator's call).
- **Inspect AI** as a runner. Trigger: a wish to run an `inspect_evals` suite (AgentDojo, agentdojo-inspect) against docket.
- **Landlock cannot deny a path inside a granted root** (P69-4 states it): the file tools and the classifier are the
  control for `.docket/` under a repository root. Trigger: a Landlock ABI that supports a deny rule, or a jail that
  bind-mounts.
- **A model that refuses a named `tool_choice` cannot serve a pod** (`meta/muse-spark-1.3` answered HTTP 400 "only auto is
  supported" on 2026-11-06): the handoff tool is called by name. Trigger: a second such model, then `setup provider add`
  probes it and says so (model-profiles).
- **The judge's and the capability suite's remote tokens**: each run needs the maintainer's go; the suites report tokens
  by role and model, never a price.

**Phases 63-64 (2026-11-04).** Left out of the cards on purpose, or found while merging:
- *`POST /pods/<p>/apply` over HTTP writes a `pod.apply` audit entry even when it skips everything*; the CLI
  writes none (P63-4's exception to requirement 6). Trigger: an audit reader that counts applies.
- *The policy-pack recipes (`outward`, `ops-approval`, `records`, `hacker-news`) declare no `shape`.* Trigger:
  a plan of record that needs their shape before it applies one.
- *The imperative-verb defence is gone* (P64-3 deleted `_IMPERATIVE_FIRST_WORDS`): a `generated` note such as
  "Run make proto..." is accepted when the path exists and renders under the untrusted frame. Trigger: a live
  note that tries to steer the next task.
- *A `generated` check proves a path exists, not that the note is true* (a live note said "top5.md is not
  present" and was accepted). Trigger: an operator reads a wrong accepted note.
- *`_still_there` in `teams/memory.py` repeats the P64-3 verifier's path logic*, and `render_entries` also hides
  a `generated` entry whose path is missing under the first project root. The stale re-check runs on every
  finished task that has an accepted `generated` entry. Trigger: a third place needs the same check.
- *`docket run`'s header and `docket setup` show the lifetime token count*, which differs from
  `budget.used` for a windowed pod; seven tests stub `pod_counted_tokens` as `lambda _p: 5` instead of taking
  `since`. A pipeline with a missing role and an out-of-pod agent reports only the roles.

**Phase 66 (2026-11-05).** Found by the real runs (`internal-docs/baselines/phase-66/real-run.md`). Fixed after the close,
the same day: a provider's context-overflow refusal is typed and taught to the estimate, for the task request and the
summary request, and so is a summary cut short because its prompt ate the reply room (agent-loop 48a; `635cdc7e`,
`4a8b5024`, `69e7b823`, `7a2a1af9`); a request-fit reduction frees a quarter of the request room beyond the overflow,
counts units as the preflight does, and a range of earlier summaries alone is not "compacted" (47; `e756d141`); a round
takes in at most half the request room, later calls answered "not run" (115; `3a317465`, `ef34c834`). Decided, not
defects: the replay bench sends more where P68-7 keeps an unanswered result whole; the summary prompt is estimated twice
(a local byte count, the bound and the request's own preflight); a record written before `session.json` can be left
orphaned, which is the order that never loses the replaced messages. Closed 2026-11-06 with real runs (same record,
"The three open follow-ups, closed"):
- *A reply cut at the output cap* is answered by one request carrying an ask for a shorter reply (agent-loop 116,
  `70f9c63f`); seen live twice on Haiku 5.5 at `--max-tokens 1024` (replies of 710 and 868 tokens after the ask). A
  summary cut at the cap is repeated once with the same ask (116a, `1880448e`, `c9636960`); probed, it takes the
  shipped prompt from over 4,096 output tokens to 2,399. Haiku 5.5's thinking counts against the cap, so at 1,024 the
  summary still cannot finish: a configuration limit (the live home is at 8,192).
- *A slow endpoint* no longer gets the same timeout again: a retried transport timeout doubles the turn's request
  limit (110, `70f9c63f`); live on the local endpoint at 30 s: 30 s, 60 s, then answered under 120 s.
- *The half-room intake on the local model* held (the unseen batch was never summarized, every fit fits); the dense
  80-file task still fails there because Qwen's summaries keep no values and it then writes values it never read
  (3/80 and 0/80, against 32/80 in one run before the rule). A model limit, not a mechanism defect.
Also closed as stale: the two window-less `budget_for_role` callers and the pre-turn compaction test went with the
pre-turn pass (`32856e57`); the `_trace_compaction` locator note ended with Phase 66.

**Phases 67-68 (2026-11-06).** What the closes leave, each with its trigger:
- *The research task has not ended `done`.* P68-6 ended on the Reviewer's veto (the card's "fabualda" typo; one rework
  allowed). Trigger: the next research run through Tack; a second veto on a well-scoped card is a gate or prompt question.
- *A research hop without a task `maxTokens` lands on the turn default and fails.* Measured in P68-6's first send:
  the researcher landed at 100k (`budget_warning entered`, a report) and the task failed as a budget stop. Tack always
  sends `maxTokens`. Trigger: a research task from the CLI or a routine; then the research recipe declares a step budget.
- *Tack's app project and docket's `app-dev` pod point at a worktree in a session's `/tmp`.* A restart wiped it and
  Tack's runner refused the attempt ("workspace path is unresolved or unsafe"); re-created at the same path on
  2026-11-06. Durable fix in Tack's session (a project path outside `/tmp`), then `app-dev`'s codebase.
- *Measurements the cards left:* Brave's 20 live queries (P68-8 goal 4, waiting for a key); whether `hosted`
  `BudgetShares(history=0.025)` goes and the researcher's cache-read growth (P68-11); whether `content` stays in the
  search projection (P68-12); three run-3 pages and the unclosed `nav`/`aside`/`form` gap (P68-13); the analyst's
  `fetch` count, 6 in P68-6 against 5 in run 3 (P68-15). Trigger: the next research run, or a Brave key.
- *The Tack brief is 788 characters and `docket task add` takes 500*, so a CLI repeat of a Tack task sends the card's
  text only. Trigger: someone needing a byte-identical CLI repeat; then `--brief`.

**Phase 68 (2026-11-04).** Left out of the cards on purpose, or found while merging:
- *The pod report probes SearXNG on every `GET /pods/<p>` and plain `pod show` probes it twice.* Each probe is one
  `GET` with a 2 s timeout, only when a search service is declared. Trigger: a plan of record polling pods often, or
  a slow answer in `pod show`; then cache the probe for the length of the request.
- *Brave's storage terms.* Read 2026-11-05 (summarised fetch): section 3(b)(i) bars storing or caching results other
  than transient storage; 3(b)(xiii) bars using results to train or evaluate AI models; storage needs a plan with
  storage rights, which the pricing page did not list. docket keeps tool results in the session and the trace.
  Decision for the maintainer before Brave is recommended anywhere: whether that is transient; the README says it is
  undecided.
- *A role file that sets `tokenBudget: 6000` exactly reads as unpinned.* P68-9 tells a pinned value from the schema
  default by value. Trigger: an operator who pins 6000 on purpose; then the schema carries an explicit marker.
- *One search answer is 23,000-30,000 characters.* Measured twice: 20 queries through the service, and a real research
  run (`real-run-searxng.md`): a search adds about 8k tokens to the request and the answer is stored as an artifact
  the researchers did not open; they chose from the inline preview and the fetched URLs were real. The caps that cut
  it are settings of a machine, not facts about the feature. Trigger: a run where the preview lacks the URLs the
  model needs, or search results dominate a turn's input; then a response projection (`title`, `url`, `content`)
  in the service client.
- *`setup search searxng` settings mount.* The command makes the settings directory 0755 and the file 0644 so the
  container user can read them; the key in the file is random per machine. Trigger: an image change that stops
  reading the mount.
- *Converging on the real writer session takes 10 summarizer rounds* (4 more than the run that failed). A cap on
  the summary's length would cut it; measure it with the next real run (P68-6) before adding one.
- *`comment_lint` flags `_resolve_roots` and `_loop_config`* (`hops/application/driver_support.py`) as
  `long-def-doc`, and six docstrings in `governance/policy.py`; none new.

- *A turn that reads many pages can run out of its token budget before its landing fits.* A throwaway run's
  researcher used 86,021 of `token_budget=100000` in 8 model calls (39 `fetch`) and ended `cannot start terminal
  finalization ... estimated input 22406 + output reserve 8192, remaining 13979`, losing everything it read
  (`agent/loop_budget.py` `prospective_budget_error` ~139, `agent/loop.py` `enter_landing` ~373). Probably the
  re-fetching P68-7 removes; trigger: a researcher turn still ends this way after P68-7, then reserve the
  landing's input before a tool round starts.
- *A pod made with `docket init <name> --blueprint respond` from inside a repository takes that directory as its
  folder* (the throwaway run's writer wrote `informe.md` into the working tree). Probably as designed (`location`
  defaults to the current directory); say so in `init --help`, or refuse a folder inside a git repository.

**Phases 60-62 (2026-11-03).** Left out of the cards on purpose, or found while merging:
- *`NOT_ENFORCED` wording.* "isolation off" is also what a machine with isolation on and no backend prints
  (`teams/network_posture.py`); changing it moves a golden and security-gates requirement 14. `pod_summary`
  probes the backend per row. Trigger: an operator misreads the line, or a pod list slower than 50 ms.
- *The fetch refusal for a host off the pod's list does not name the pod command.* `platform/fetch.py` ~279 says
  "add it to FETCH_ALLOWED_DOMAINS, or to the pod's fetchDomains"; P61-3's card wanted the exact `docket pod set`
  command. `platform` does not know the pod. Trigger: a hop that stops on this refusal and a person asks how.
- *`capability_missing` for a tool is "a name the role could hold".* P61-3 chose that over "a tool another member
  holds" so a deliberate `deniedTools` is not a gap. A Reviewer calling a record write it may not use now fails
  the task `capability_missing` (`tests/e2e/test_workdir_pod.py` follows).
- *PDF reading, after P62-1.* `setup check` has no line for the PDF reader (whether isolation is on is the
  only fact it needs; the recipe readiness block already says it); an encrypted PDF is refused (only the empty
  password is tried and AES needs `cryptography`); `pypdf` decodes about 30 MB/s, so a real stream bomb ends by the
  1 GiB memory limit or the deadline after ~30 s of CPU. The jail runs a copy of `pdf_extract.py` beside `in.pdf`
  because `-m docket...` fails when docket is editable. Trigger: a PDF a user needs that these refuse.
- *`pod export` drops a recipe's `needs`* (`teams/apply/write.py` ~191, the manifest built there), by design: `needs` is
  a recipe declaration, not pod state. The "search service" check is a heuristic (a declared service whose name or an
  operation name contains "search"), and the known search hosts are a constant in `teams/apply/needs.py`. Trigger: a
  recipe that needs a fact these do not cover, or a search host that is not on the list.
- *Streaming with an idle timeout.* A stall is only seen after `AGENT_LOOP_REQUEST_TIMEOUT_S`
  because a non-streamed reply sends nothing until it ends. Trigger: after P60-1, more than one
  `request_retry` per 50 requests over a week of the live home, or a turn that ends `timeout` after
  its retries. Observed 2026-11-03..06 (16 tasks, 311 calls): no `request_retry` in the live traces, 3
  request timeouts, all in one task (0.48 per 50); not fired.
- *A missing workdir folder.* Not seen: `web-research`'s exists, and Tack's `workdir: null` was the
  absent field (P61-1). Trigger: a dispatch whose recorded `workDir` is gone; then the docket-owned
  default is recreated, and a declared location becomes a profile violation and a `POST /tasks` 422.
- *A network failure inside `bash`.* No deterministic signal; P61-5 states the posture. Trigger: a
  recorded hop that tried the network after its message said `none`.


**Toolchain read grants (dropped from Phase 48).** A sibling project's gates failed with exit 126 under the
jail until each toolchain under `$HOME` (`~/.nvm`, `~/.pyenv`, `~/.cargo`) was granted by hand with
`docket setup sandbox read add`. Trigger: a second pod whose first jailed gate fails that way. Next:
`docket setup` proposes the grants for the toolchains it finds.

**Phase 55 Wave 1 (merged 2026-10-30).** Loose ends, none a card yet; the first two belong to the later cards
that already own the files.
- *Required variables supplied by tasks.* `dispatch_pod`'s up-front check refuses a `required` pipeline variable that
  only tasks supply. P55-9 (routines) meets it first.
- *Smaller.* `docket task cancel` does not kill a `hop` MCP session directly (it closes at hop end); a top-level
  `networkGrant` in `pod.yaml` is an unknown-key error, not a skip (only under `settings`).
- *Flakes under load, seen once each and passing alone:* `test_run.py::TestForegroundApprovalPrompt` (two tests),
  `test_end_to_end.py` approval-mode tests. A second failure of the same test is its trigger.
- *Phase 55 Wave 2, P55-3.* The `outward` recipe's policy `ask` names one tool, `mcp__outbox__send`
  (`when.tool` matches an exact name), so a send tool of another name is not asked about: a kind predicate or a default
  `ask` for every `send` tool belongs with P55-4. `--kind` stays an operator assertion, not verified against the server.
  A pipeline step that runs a role from the pod's existing registry (not in the applied directory) is not checked by
  the read/act rule.
- *Phase 55 Wave 2, P55-6.* `docket task show` "Waiting on you", the foreground `run` progress view and Telegram
  `/status` do not special-case a `wait`. `serve-read-api.spec.md` (the `kind` label list) and `a2a-binding.spec.md`
  (`escalationKind`) still list five kinds. `docket_escalations_total` counts a probe-resolved wait as `by=person`. A
  `stale_claim` between wake and claim drops the wait, so the next claim parks the step again. A monitor-only `docket
  start` never runs a probe (only a dispatching sweep does). Tack's maintainer is told: `wait` is an additive
  `EscalationKind`, `machine` an additive `EscalationPolicy`, the task is `waiting_input` with a2a state `WORKING`, a
  timed-out wait with no route is `blocked` / `wait_expired`, and `POST /escalations/<id>` `{optionId: "resume"}` ends
  it early. The e2e lane took 344 s once on this host against about 42 s measured before; its slowest tests are 13 s,
  so it was host load, not a test; re-measure if it repeats.
- *Phase 55 Wave 3.*
  - P55-2: the refusal golden is not added. `tests/golden/run.sh` derives the command from the case id and
    `setup model set` validates the model id (it contains `/`) before the role; a CLI unit test in
    `tests/unit/interfaces/cli/commands/test_setup_model.py` plus checking the role first would fix both. The refusal
    hint and `setup model list` name only the ten built-in roles; `known_role_names()` reads every overlay per call.
  - P55-4: `task show --json` carries no `call` (deliberate). The `Authorization` redaction pattern needs a token of
    about 20 characters after "Bearer". `outward` and `call` are additive to `operator-v2`; tell Tack's maintainer.
  - P55-9: the recipe summary line does not name
    routines; cron day-of-month and day-of-week are ANDed, as in the existing parser; `tzdata` is not a declared
    dependency; no `--tz`-aware `HH:MM` form. A routine fires only under `docket start --dispatch`.
    A routine skip is traced as `step_skipped` because `EVENT_TYPES` is closed.
- *Phase 55 Wave 4.*
  - P55-8: the check and the increment of a quota are not atomic (two concurrent sends in one pod could both pass at
    count-1); an unreadable counter counts as empty; `pod policies` and `check` do not show quotas.
  - Phase 56 Wave 2 merge run (2026-10-30), passed alone: `tests/integration/product/test_runtime_execution_envelope.py`,
    8 setup errors from `uv build` exiting 2 in a parallel worker.
- *To investigate, important: a pod logging in to a site nobody configured.* Per-service MCP bridges and `secret:<name>`
  are fixed when a server is registered; a task that ends in a `send` at a new site that needs a login has no per-site
  credential the model never sees. Raised by the maintainer 2026-10-30. Analysis, seven open questions and a suggested
  path (ADR first, then `docket setup secret set`, then a per-site grant like the network grant, then a real run with a
  throwaway account) are in `internal-docs/design/site-credentials-for-a-pod.md`. No card yet.
- *Phase 59 merges and real runs (2026-11-03).* Seen while merging or in the six real runs.
  - The `bash` clamp is `max(1, int(deadline - now))`, so a hop clock of 2 s ends a clamped command at 1 s and
    the clock is not yet spent (`agent/loop_steps.py`). Round it up when a `time` stop is seen to need a
    second request.
  - Only an Implementer hop that ended `budget_exhausted` is pinned (ADR 0038 decision 2 reads wider). Trigger:
    a plan of record that needs the tree of another failed Implementer hop in the patch.
  - `--resume`'s lease still uses the pod's `turnTimeoutS` + `verifyTimeoutS` and ignores a step's `timeout`;
    the per-round claim refresh covers a live claim.
  - A `budget_exhausted` stop for a finalization reply that carried tool calls is a model misbehaviour with
    `stop_reason: token_budget`; it lands as a budget outcome. Trigger: one seen in a real trace.
  - A budget stop that entered its landing keeps the pre-landing reason: "cannot start tool-enabled task
    completion within token_budget=N ... no backend call made" (`agent/loop_budget.py`
    `prospective_budget_error`), though the landing call was made. It reads as a refusal with no call and
    quotes the 128000-token output reserve of a model with no registered cap. Trigger: an operator misreads
    one, or Tack shows the `reason` text.
  - The CLI cannot see why a task stopped: `docket task show` and `task list --json` print neither
    `failureKind` nor the hop's `budget`; they are in the HTTP task and `TASK_LIST.json`. Trigger: an
    operator asks for the limit that stopped a task from the terminal.
  - Tack's live run (2026-11-03) never reached a clean `time` stop: its request clock ran out first, as a
    transport timeout, while the loop was in its own landing. Unverified on docket's side (the landing's share of
    the clock, and whether a client's request timeout should exceed the step `timeout`). Trigger: a plan of record
    reports a `time` stop that arrived as a transport timeout, or a real run where the landing outlives its step
    clock.
  - A second implementation of a port can sit outside `src/` (the `docket-runtime` package's `Tracer`).
    Trigger: the next port-signature change sweeps `packages/` too (`rg` the method name there).
  - A policy `ask` on `.env.local.example` (a template, no secret) stopped the retried app-dev task. Trigger:
    the operator wants templates exempt from `block-destructive`.
- *Phase 59 planning (2026-11-02).* Left out of the phase by ADR 0038; each waits on its trigger.
  - docket continuing a budget-stopped hop on its own (ADR 0038 decision 6). Trigger: the same task
    retried after a `budget` stop with `treeChanged: true` three times in a week (audit `task.retry`
    plus the hop's `budget`).
  - A stall detector beyond identical calls (rounds that only re-read what the session already
    holds). Trigger: three Implementer `budget` stops with `treeChanged: false` in real runs.
  - The 300 s default hop clock (`AGENT_LOOP_WALL_CLOCK_TIMEOUT_S` after P59-4). Trigger: a `time` budget stop
    whose last `bash` the clamp killed (requirement 98's marker).
  - Parallel-group resume re-runs a group's ok children with their original prompt over their
    sessions (`pod-dispatch.spec.md` "Parallel step groups" item 6). Trigger: a group child re-run
    observed in a real retry.
- *Phase 58 planning (2026-11-01).* Asks from the manager audit that Tack would not read today.
  - `actor` on `POST /tasks/<pod>` and on retry. Enqueue audits no actor (`tasks/application/queue.py`
    ~237), and retry audits neither channel nor actor (`lifecycle.py` ~188). Tack sends `actor: "tack"`
    on resolve and nothing on enqueue. Trigger: Tack links an attempt to the principal that caused it
    and sends that principal.
  - `updatedAt` on a task, stamped beside `rev` in `tasks/application/json_store.py` ~40-49. Tack follows
    changes through `rev` and would show this only for work the board did not start. Trigger: a client
    that has to show when a task last moved.
  - A hop's `output` is not in the task shape of `operator-api.spec.md`. Tack uses `artifact.summary`
    as the reply of a conversation turn. Trigger: a recorded turn whose summary is too terse to serve
    as the reply.
- *Phase 58 wave 1 (2026-11-02).* Found by the workers of P58-1 to P58-3, none in a card.
  - An escalation's `seq` is issued before its record is written (`platform/store.py::write_escalation`).
    A poller reading between the two can return a later record and move `next` past the missing one.
    Trigger: a poller that reports a missed escalation, or a second writer that opens escalations
    concurrently with a poll.
  - Blocked outcomes other than the pod budget (`_block_on_missing_resources`, the `resources` block)
    carry no `failureKind`. Trigger: a client that has to tell those blocks apart.
  - `docket pod show --json` does not carry `paused`/`pausedReason` (`pod_report` feeds it;
    `cli-json-shapes.spec.md`). Trigger: an operator who reads the pause from the CLI JSON.
- *Phase 58 close (2026-11-02).* Seen once in the real run, not reproduced.
  - `POST /tasks/<pod>/<id>/cancel` sent a few milliseconds after `POST /tasks/<pod>` answered `409
    not_cancellable` ("is running; nothing to cancel"). The spec says a `running` task is cancelled by
    killing its hop's process group, so the claim had likely set `running` before any run or hop was there
    to stop. A client that cancels right after enqueueing gets a refusal for a task that then runs.
    Trigger: a second sighting, or Tack cancelling a task it just queued.
- *Phase 57 close (2026-11-01).* Loose ends of the phase, none a card yet; each waits on its trigger.
  - Park order. `_park_turn` marks the hop parked after it was persisted unparked and opens the `turn` escalation
    while the task is still `running` (`hops/application/executor.py`). A crash between leaves an unparked hop and a
    pending `turn`; replay moves past the step and the record expires unread. The reverse order would leave a
    waiting task nobody can answer, so this is the safer failure; a consult has the same window. Trigger: a
    conversation task found ended after a restart with a `turn` still pending.
  - One `current` slot. A parallel group names the child that started last and the key goes when that child ends
    (`operator-api.spec.md`). Trigger: Tack must show every running child; `current` then becomes a list under a
    new feature name.
  - "Turns taken" is read three ways: `len(hops)` in `_park_turn` and in the task dump, answered hops in the
    budget end. They agree until a final hop fails. Trigger: a `turns` count that disagrees with the hops shown.
  - Two refusal paths. An error `code` reaches the wire as `DocketError.code` and as `_send_json_error(code=)`;
    `task_control.py` builds a `Conflict` only to render it, where `post_task_retry` calls `_send_json_error` (unifying
    them moves an HTTP body). Trigger: the next edit of either route.
  - `decide_task_tokens` is untouched: the budget end of a conversation is decided in the executor
    (`conversation_ends_on_budget`). Trigger: a second consumer of "ended after an answered turn".
  - Flakes under load, each passing alone, seen once: `tests/guards/test_no_removed_cli_names.py` (a 2 s timing
    bound), `test_record_store_conformance.py` (two sqlite tests: the row cut, the CSV header) and
    `test_bash_background.py::TestTheTurnLeavesNoOrphan`. A second failure of the same test is its trigger.
- *Phase 56 close (the real run and the gates, 2026-10-30).*
  - Real evidence: the live Hacker News test (retired by P69-11; now the `hn-digest-records` capability task) ran the `hacker-news` recipe against
    `hn.algolia.com` and the local model; the fourth run passed (see P56-22 in the archive). The write path of a declared
    service (park, approve, one `POST`) against a real model was **not** repeated at this close; the deterministic e2e
    (`tests/e2e/test_declared_service.py`, a scripted model) covers it. A run with the real model is the trigger for
    the first service that sends.
  - The role prompt's "end your reply with `## Memory`" line made a local model run `echo` through `bash`, and the
    gate parked the task for an approval nobody was there to give. The `hacker-news` steps say to run no command; the
    prompt in `builtin_roles.py` is unchanged (trigger: a second pod where a model does the same).
  - P56-10 left: a producer of git evidence for a non-implementer role. The `operate` and `routine` pods are workdir
    pods with no commits, so nothing would read it (trigger: a git-backed pod whose non-implementer step commits what
    a later step needs).
  - `summarize_recipe` does not count a recipe's `services/`; `gen_recipe_docs._brings` and
    `pod_config_library._brings` are two near-duplicates. The `captured` column of `stories` holds the day a story
    was posted (the model has no clock); the row's `_at` is the capture time.
  - Records port (P56-23, merged): a second backend is one adapter module, one line in
    `bootstrap._open_records` and one `BACKENDS` entry in the conformance suite; a remote one needs the ADR
    amendment on `send` first, and S3 is an export destination, not a backend. `teams/records.py` quotes a set name
    in ANSI double quotes (each backend would quote its own); `ReadLimits` serves `read` and `export` though
    `export` honours only `timeout_s` (a possible `ExportLimits`).
  - Live Hacker News on Anthropic: the recipe ran on `claude-haiku-5-5` with Langfuse export (digest 218.9k tokens,
    weekly report 111.1k); the lane is now the `hn-digest-records` task, which any provider runs through
    `evals.evaluator.run run --provider` (P69-11). A fake key makes the run wait out its timeout instead of
    failing on the 401 at once.
  - Records and services: `pod update` does not check that a `rec__<set>` allow-list entry names a declared set;
    real PostgREST documents carry no `operationId`; `setup service list` shows secret names; the `ask-before-send` custom message is not shown
    for service sends; service results are not screened as untrusted; `pod records --csv` overwrites silently; the
    idempotency key also hashes path and query arguments.
  - Code: `decided_approval` sits in `escalations.py`; `_blueprint_pipeline` (`hops/application/steps.py:96-97`) loads a
    registry only to call `load_pipeline(None, ...)`; `conversations.load` returns an empty registry for an invalid file.
- *Phase 55 close (the repeated real run, 2026-10-30).* `docket run` does not wake a `wait` whose time has passed
  ("No pending tasks"); only the dispatch service's sweep does, as the spec says; a person expecting `run` to finish
  it is surprised (trigger: a second report). In one fresh home `setup provider add local ...` left the roles on
  `anthropic/*` until `setup model preset local` ran; an earlier fresh home applied the preset by itself: reproduce
  before a card. A stdio MCP server under isolation needs its script, interpreter and venv readable, and fails with
  `mcp_client.unavailable: ExceptionGroup` while python's "Permission denied" goes only to stderr (trigger: the next
  operator who meets it). P55-14 keys its note by task and role, not step, and splits the approval's `action` on
  `; call=` rather than reading a typed field; `task show --json` carries no `approval_unused`. P55-13 adds no trace
  line when the surface drops a role-named built-in (the closed event set has none that fits).
- *Live evidence, P55-5 (2026-10-30).* A real Playwright MCP server (0.0.83, headless system Chrome) driven through
  docket's MCP layer against a local page: under `lifetime: hop` navigate, snapshot and click by ref keep one session
  (the click ran, the page title changed); under `call` the snapshot after a navigate is `about:blank` and no ref
  exists. Not a model-driven pod run. That server's click argument is `target`, not `ref`.

**Phase 54 (closed 2026-10-29).** Two items wait for their triggers.
- *Dated model ids.* The native `/models` lists `claude-haiku-4-5-20251001`, and the probe matches ids
  exactly, so `claude-haiku-4-5` never gets an observed output cap and a call without a declared
  `--max-tokens` fails by design. Trigger: a second operator who meets that refusal. Next: the probe
  matches a catalog id to the dated id that starts with it.
- *Names.* `openai_http.py` and `OpenAIChatClient` hold both wires and still carry the first one's name;
  ADR 0011, ADR 0014 and two specs quote them. Trigger: a third dialect or the next edit of either module.

**Outward work (ADR 0036, deferred with triggers; the cards are Phase 55).**

- **HTTP/SSE MCP transport** (`mcp-client.spec.md:50`). Trigger: the first real pod whose connector
  exists only hosted.
- **`lifetime: task` for an MCP server.** Trigger: a recorded run in which a following hop needed the
  previous hop's session.
- **A structured-output gate** (a result that must match a schema). Trigger: a recorded run whose
  judge approved a malformed list.

**Standard teams and records (deferred from Phase 56, 2026-10-30; analysis in
`internal-docs/strategy/equipos-estandar-empresa-digital-2026-10-30.es.md` §8 and
`capa-de-datos-para-docket-2026-10-30.es.md`).**

- **A pod without a Lead member.** Not a blocker, so not a card: the Lead is the pod's *anchor record*
  (its workspace holds the queue, `teams/settings.py:21-26`, the settings and budget, `:29`,
  `teams/member_workspace.py:214`; `pre_input` is evaluated and session events traced as `"lead"`,
  `tasks/application/queue.py:72`, `governance/approval.py:73`), but no pipeline step has to use it: the
  `respond` blueprint's pipeline already runs researcher, writer, reviewer, actor. Making the pod the subject is
  a persisted-state change (the queue's and settings' location). Trigger: a measured cost of the idle Lead
  member (its workspace, its row in `status`), or a pod whose operator refuses a Lead at all.
- **Measuring the three-role full pod against the four-role one** (P56-15 ships the change on the
  maintainer's request; this is the evidence it did not wait for). Trigger: a maintainer go, since the
  comparison spends hosted-model tokens on `app-dev`: the same tasks under both rosters, measured tokens
  and escaped defects.
- **A port for docket's task store** (`TaskRepository` takes the concrete `JsonTaskStore`,
  `tasks/application/repository.py:48`). Not business data, and a port with one implementation is the
  "unwired machinery" this project refuses. Trigger: a queue the one file cannot carry (measured).

**Model adaptation and context (ADR 0033, deferred with triggers; the cards are Phase 52).**

- **Reasoning kept inside the turn** (`ChatMessage.reasoning`, resent only in the active tool
  loop; `reasoning_content` is dropped today in `models/adapters/openai_wire.py::decode_response`).
  Trigger: a profile that declares `reasoning: interleaved`.
- **Lifecycle condensation** (a `read` superseded by a later `read` or an `edit` of the same file
  is evicted first, in batches aligned to steps). Trigger: after P52-2 (which absorbed P52-8), the bench `--repeats`
  still shows re-reads on the recorded implementer steps.
- **A bounded model escalation** on a step (`escalate: {on: [verify_failed, no_progress], model:
  strong, max: 1}`), audited. Trigger: the `strong-plan-cheap-edit` recipe (P52-6) fails
  `verifyCmd` on a measured share of real runs.
- **A lazy MCP catalog** (`mcp_describe(server, tool)`, the tool list kept stable within a turn).
  Trigger: a pod whose MCP schemas exceed its built-in ones (`request_part_bytes["tools"]`).
- **A native Anthropic dialect** (1 h TTL, `cache_control` on tools, signed thinking blocks; the
  provider note already defers it). Trigger: direct use without the gateway, which caches today.

**Escalations (left at the Phase 51 close, 2026-10-25; ADR 0032).**

- **Approval, gate and `check_changed` follow-ups still run inside `resolve`** (`approval_grant`
  and the task-grant audit in `tasks/application/escalations.py`), not on the claim path; P51-6
  stopped at PARTIAL because deferring them breaks `approved_ready`, which reads pregrants and
  `gateOverridePipelineIndex`, and P51-9's "Also" list named the move. Trigger: a change to
  `approved_ready` or to the claim path.
- **Settled escalations written before P51-11 stay in the flat `escalations/` directory**; no
  migration is written. A scan of the live directory still opens them (`platform/store.py::list_escalations`
  reads the flat folder for `pending` and unfiltered scans). Trigger: an operator whose pre-P51-11
  records slow the inbox; then move them under `settled/` once.
- **`GET /escalations?since=` reads every settled file** (`operator/inbox.py::escalation_views`
  calls `list_escalations(since_seq=...)` with no state, so `settled/` is scanned on each poll).
  Trigger: a poller whose `settled/` directory is large; then index by `seq` or bound the scan.
- **docket follows an enclosing git repository when a pod path is not itself one**
  (`platform/git.py::git_is_repo` answers `rev-parse --git-dir`, true anywhere inside a work tree),
  so it would prepare and branch the enclosing repository. Only the live-eval and smoke worlds
  refuse that today (`specs/test-framework.md`). Trigger: a pod registered on a subdirectory or
  a nested path that is not a repo.

**Test suite under load (found at the Phase 47 close, 2026-10-24; each passes alone).**

- **Timing flakes seen once each:**
  `test_retries_and_timeouts.py::TestRetryDoesNotTripStaleClaimSweep`, and the foreground approval
  deny test (its fake approval timeout was raised from 5 s to 60 s, `1a704359`), and
  `test_escalation_http.py::test_a_parked_approval_is_served_with_no_token_anywhere` (`KeyError: 'escalations'`
  under the no-sandbox lane's load at the Phase 69-70 close; passes alone). Trigger: a second
  failure of the same test. Then replace its wall-clock wait with an event.
- **Two contract files set the merge run's floor** (measured 2026-10-28, `--durations=0`):
  `tests/contracts/test_a2a_http.py` 60 s and `test_escalation_http.py` 35 s of the 84 s run. Each
  test's function-scoped `parked` fixture runs a real `docket run` and starts a service (about 3 s
  of setup per test), and `--dist loadfile` keeps a file on one worker. Trigger: the merge run
  passes 120 s, or a card adds a test to either file. Then share one parked world per module for
  the read-only tests.

**Runtime and dispatch (from real runs).**

- **A refused task is resumed on every 30 s sweep tick** (`dispatch_refused` is in
  `RESUMABLE_FAILURE_KINDS`, `tasks/domain/state.py`; operator-api §6 by design). Trigger: the audit log
  fills with one task's refusals, or a second operator asks. Then resume only when the cause changed.
- **A parked turn is paid twice**: the resumed hop re-sends the whole prompt (4,157 input tokens before
  the park, 8,181 after; 100,573 in the 2026-10-18 joint run). Trigger: a third run that parks on the
  same shape. Then weigh resuming the session over re-running the hop (operator-loop §2 item 6).
  **FIRED 2026-11-04:** the P67-5 writer parked on a question and resumed with 21,642 input tokens, 0 cached
  (21:41:43 UTC); its second resume, after the approval, died in compaction (P68-1). **Re-measured 2026-11-08**
  (2026-11-03..06): 5 of 6 resumes kept the cache, about 2k uncached tokens each (`task-69fa3927`); the sixth is the
  compaction P68-1 fixed. Not a card; the trigger is a resume that re-sends uncached after P68-1.
- **A hop refused before any call records an empty model** (`hop_finished.model == ""`, a `""` key in
  `usage.byModel`). Trigger: a reader of `byModel` that trips on it.
- **Hop language drift:** a resumed step once wrote its report in another language, which became the
  next handoff. Trigger: a second occurrence; then a pod `language` setting.
- **The Lead plans with the codebase path while the Implementer is rooted in the task worktree**
  (`tool.refused` on `read`). Trigger: reproduce with a local-model dispatch in a worktree pod.
- **The prospective budget check ignores cache reads**, so a heavily cached step is refused early.
  Trigger: a real run refused with room left. `glob`/`grep` walk vendored trees before filtering;
  measure before changing.
- **A task's `network: none` cuts the agent turn only**; `verifyCmd` and `run:` steps keep the pod's
  posture (stated in the spec).
- **Cancel over HTTP reports `cancelled` once the stop is requested**; the task stays `running` until
  the executor notices. The slow-stub cancel path has no test.
- **Not examined:** each Phase 45 run's trace carries two `approval_denied` events beside its park.
- **Real-Docker tests exceed their duration ceiling under load** (`test_network_lockdown`,
  `test_sandboxed_exec`, the escape matrix's docker cases): they pass alone. A flake, measured
  2026-10-14.

**Workspace and checks.**

- **A file a check reaches only through `make` or `npm run` is protected only through the default
  files it reads**, and **a gitignored file is invisible to the check**. Trigger: a real gate whose
  script lives behind a target, or a repository that ignores a file its gate reads.
- **Prepare:** only `node_modules` is cached (`.venv` is not relocatable); `node_modules/.cache` is
  read-only in the jail; eviction can break a running task's link (resume prepares again); prepare is
  not cancellable (bounded by `PREPARE_TIMEOUT_S`); `hops/workspace/prepare.py::linked_entries` accepts
  any cache entry, not only the task's codebase. Trigger: a real run that hits one of them.
- **Shell keywords are classified as binaries when unjailed** (`for`, `do`, `done`, `if`, `then`,
  `while` ask in `governance/security`). Trigger: an operator without isolation reports it.

**Configuration.**

- **Parallel tasks in a pod:** ADR 0027 point 10 holds the trigger; a card would add a
  `maxParallelTasks` pod setting and a bounded pool in dispatch.

**Channels, inbox and the HTTP API.**

- **Enabling the `email` channel checks nothing**; with no `to`, `from` or `smtpHost`, every delivery
  fails into the health record. Trigger: an operator enables it.
- **Pending memory entries show in `docket inbox` but not in `GET /inbox`, MCP `inbox`, notifications or
  Telegram `/status`.** Needs an operator-v1 inbox contract bump. Interim: `GET /pods/<p>/memory?status=pending`
  (P63-6). Trigger for an HTTP approve route: Tack asks for one.
- **The corrections cursor needs `+` percent-encoded in `since`**; a pod whose Lead was removed but
  whose ledger remains answers `404`.

**Prompts and pod state.**

- `hops/application/compose.py::_resolve_hop_instructions` still opens "You are the Implementer..."
  (SOUL says it); recipe roles using `${codebaseOrConfigured}` render a path; `repo_map.SKIPPED_DIRS`
  mirrors `toolbox.SKIPPED_DIRS` (pinned by an equality test); pod read routes do not carry
  `tokenBudget`; the condensation notice carries the call's full path.
- **Every member of a pod shares the base session key `agent:<pod>:<key>`** (`teams/pod.py`); no turn
  reads it today. Trigger: a turn that does.
- **Three readers of the implementer's codebase** (`rg -n "def _pod_codebase|def _codebase|def
  task_diff" src`); one helper when next touched.
- **`memory_update` has no structural telemetry key**; members stamped `POD_TEMPLATE_VERSION` 4 show stale
  to `pod update` by text comparison.

**Phases 52 and 53 (closed 2026-10-29).** Triaged the same day: the brief redaction, the prompt `tests` file, a role's
unknown tool name, `pod test`'s handoff spec, the live-run key lookup and the stale docs were fixed; what stays waits
for its trigger.

- **P53-4 goal 3, the Lead's locators read into the Implementer's message.** Measured on three recorded smoke tasks
  (two local Qwen, one Haiku, `context_replay.py --repeats`): the Implementer read 1/1, 1/1 and 2/4 files the Lead had
  read, but all except one were files it then edited, whose exact text `edit` needs; "not edited after" was 0, 0 and
  1 file (682 bytes). Trigger: "not edited after" reaching 30 % of the Implementer's reads on recorded tasks of a real
  pod (the smoke repository has three files).
- **The model class comes only from the rank anchors** (`economy` is `cheap`, `standard` and `premium` are `strong`),
  so a non-anchor model such as the local Qwen resolves `any` and no `<name>.<class>.md` variant acts for it. No
  shipped prompt has a variant. Trigger: a variant written for a non-anchor model.
- **Structured `task` intake** exists on `POST /tasks/<pod>` only; the CLI, MCP and Tack's runner do not send it.
  Trigger: Tack adopting it.
- **Decided, not open:** P52-2's bench oracle is "no step worse than the recorded request, and prefix stability not
  worse", met on the fixture (sent 0.25 to 0.66 of the baseline per step; stable 8/10, 3/4, 5/7, 6/7). The "+0.3 %
  to +3 %" was against the pre-P52-2 `condense_history`, which the bench's `phase44` policy now calls live, so it is no
  longer reproducible; the small-result rule stays. The re-ask, finalization and closing texts
  (`hops/application/runner.py`, `agent/loop_request.py`) are the harness's protocol, versioned with the code and the
  agent-loop spec, not role prompts.

**Architecture and packaging.**

- **The runtime closure grows with any facade on a context the runtime imports** (measured in P47-8:
  agent 52 -> 75, teams 52 -> 157, governance 52 -> 101, observability 52 -> 60 files). Trigger: a
  proposed facade on one of them.

**Tests.**

- A worker's `monkeypatch.undo()` once undid the autouse home isolation and wrote into the real
  `~/.docket`; the fixture guards `setattr`, not `undo`. Trigger: a second leak.
