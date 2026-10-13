# ADR 0025 (D-61): a lights-out profile, an external verification gate, and directives from the repository

**Status:** Accepted 2026-10-13 **with the amendments at the end of this record**, which cut
and reshape parts of the decision below; where they disagree, the amendments win. Phase 42.

**Question:** docket is one of three tools that can be used alone or together: an orchestrator and
project manager (for example Tack), this runtime, and an independent verifier that emits a
merge-readiness pack (for example Prill, where `prill verify` exits 0 for "eligible for
auto-merge" and 1 for "reject"). Together they are meant to run a lights-out software factory,
where autonomy rises by level:
- **L3:** the agent proposes, a human validates every change.
- **L4:** autonomy inside bounded domains, humans only on failure.
- **L5:** full autonomy, humans informed.

Each tool must stay usable alone and at any of the three levels. What does docket add so that an
operator can run it at L4 or L5 safely, without docket learning who the verifier is and without
changing what a fresh install does?

**Shared principles** (the same five in every tool; they are restated so this ADR reads alone):
- **P1.** Tools integrate only through versioned contracts: files, CLI and exit codes. No tool
  imports another or shares its database.
- **P2.** The adapter lives in the consumer. A tool that wants another tool's output reads it;
  the producer does not grow a plugin for each consumer.
- **P3.** A missing partner degrades to L3: a human decides, and nothing breaks.
- **P4.** The autonomy level is a policy the operator chooses, not a code path: the same binary
  runs at every level, with stricter rules at higher ones.
- **P5.** One component decides a merge. docket executes and records; it never merges and never
  certifies its own work (ADR 0017 decision 5 stands).

**Where decided:** proposed 2026-10-13 for the owner. It follows ADR 0017 (the factory role),
ADR 0018 (consult packs, evidence-v1), ADR 0019 (task worktrees), ADR 0020 and 0021 (the
envelope, isolation opt-in) and ADR 0024 (one envelope). Work is not scheduled until the owner
accepts it.

**Evidence** (read on 2026-10-13; locators are symbol names,
re-locate with `rg -n`):

| Fact | Locator |
| --- | --- |
| The built-in pipeline is lead, implementer (mechanical gate), reviewer (verdict gate with a bounded rework edge to the implementer), tester | `core/pipeline.py::default_pipeline` |
| A `MechanicalGate` runs `command` or the member's `verifyCmd` and reads one thing: pass or fail. Its evidence is `{cmd, exitCode (0 or 1), durationS, outputTail}`. No reasons file, no third outcome | `core/dispatch.py::_evaluate_mechanical_gate`, `core/pipeline.py::MechanicalGate` |
| A failing mechanical gate fails the task unless the step's `on` map routes `fail` somewhere (`{goto, max}`, `until: verify` sugar) | `core/dispatch.py::_match_on_route`, `core/pipeline.py::_build_until_route` |
| The bounded rework edge (`ReworkEdge`, `maxCycles`) belongs to `VerdictGate` only; the pod default comes from `maxReworkCycles` (default 1) | `core/pipeline.py::ReworkEdge`, `core/dispatch.py::pod_max_rework_cycles` |
| A rework hop gets the previous hop's artifact in a `--- REWORK REQUIRED ---` section | `core/dispatch.py::_hop_message` |
| A missing `verifyCmd` advances, unless the pod sets `requireVerify` (`verification_missing`) | `core/dispatch.py::_evaluate_mechanical_gate`, `core/pod.py::PodSettings.require_verify` |
| A verify or `run:` command runs through the pod's isolation posture and gets `DOCKET_TASK_ID`, `DOCKET_BASE_COMMIT`, `DOCKET_HEAD_COMMIT` | `core/dispatch.py::_run_in_envelope`; ADR 0019 decision 3 |
| evidence-v1 (`v: "1.0.0"`) is built by one function; each hop has `verify`, `commit`, `baseCommit`, `diffStat`, `usage` and a `trace` link `{project, session, firstTs, lastTs}`. It carries no score, no attempt id and no digest | `core/evidence.py::task_evidence`, `TraceLink`, `HopEvidence` |
| The audit log is hash-chained (`seq`, `prev_hash`); the trace file has no content digest | `core/audit.py`; `core/trace.py` |
| The corrections ledger is `$DOCKET_HOME/corrections/<pod>.jsonl`, one record per deny reason, REQUEST-CHANGES text or declined answer: `{ts, project, kind, taskId, role, text, source}`, text redacted and cut to 4000 chars | `core/corrections.py::record`; callers `core/dispatch.py`, `core/answers.py`, `core/approval.py` |
| The only reader of the ledger is `docket task show` (its `corrections` key). No agent reads it and no export exists | `cli/_task.py` (`_corrections.read`) |
| A model can ask with `consult` (at least two options and a recommendation, capped by `maxConsultationsPerTask`, default 3). In pod dispatch the task parks `waiting_input` and the answer re-enters the same role | `core/consult.py::build_question`, `ConsultParked`; `core/answers.py` |
| Gated calls carry an approval pack: the model's rationale and three options (`approve_once`, `approve_task`, `deny`) | `core/approval.py` (`screen_rationale`, the options table) |
| An `input` pipeline step already parks a task with a docket-minted question | `core/dispatch.py::_run_input_step`; `core/pipeline.py::InputSpec` |
| Isolation is opt-in: no recorded choice means off, no backend probed. Once on, a turn with no usable backend is refused and audited (`isolation.refused`) | `edges/adapters/docket_runtime.py::_resolve_sandbox`; ADR 0021 |
| `network none` is a real mode. An unrecorded global mode reads as `none`, but it only binds the jail; with isolation off a scope-`default` `none` is not enforced and egress is open. A recorded or pod-level `none` with isolation off is refused (`network.refused`). A pod's `open` never widens a global `none` | `core/pod.py::effective_network`; `edges/adapters/docket_runtime.py::_resolve_network`; `core/fleet.py::get_network_mode` |
| `resolve_command_jail` gives verify commands and `run:` steps the same jail as `bash`, or a refusal | `edges/adapters/docket_runtime.py::resolve_command_jail` |
| docket's own secrets are stripped from the environment of verify, `run:` and unjailed `bash`; a jailed `bash` gets `PATH` and the pod's injected variables | ADR 0020 decision 8; `edges/adapters/system.py::run_verify_cmd` |
| `--max-tokens N` bounds an `exec` turn; it is refused with `--recipe` (`--max-tokens does not apply to --recipe runs`). The result's `cost_usd` is always `null`. `budgetUsd` is a pod setting for the Lead | `cli/_harness_recipe.py`; `core/harness.py::HarnessResultV11`; `core/pod.py::budget_usd` |
| The loop stops on `no_progress` after `AGENT_LOOP_NO_PROGRESS_ROUNDS` (default 3) rounds with nothing new | `core/agent_loop.py::stop_if_no_progress`; ADR 0019 decision 4 |
| `kind: autonomy` is deferred: nothing produces it and nothing in `src/` names it | ADR 0020 "Cut and deferred" |
| `AGENTS.md` at the codebase root is composed into every pod member's prompt by default (an explicit `projectInstructions` list replaces it), screened as untrusted by `pre_input`; skills come from `.docket/skills/`, the pod and `~/.docket/skills/`; recipes only through `pod update` | `core/identity.py::project_instruction_files`, `_project_instructions_raw`; `core/skills.py::discover_skills`; ADR 0012 |
| **The project-instructions root is the task worktree** when a task has one, so the agent can rewrite `AGENTS.md` and later hops read its version | `edges/adapters/docket_runtime.py` (`roots=(Path(pipeline_worktree),)`), `core/identity.py::_project_instructions_raw` (`project_roots[0]`) |
| The harness command is `docket exec` (it was `harness run`); exit codes 0 ended well, 1 ran and ended `failed`, `blocked` or `cancelled`, 2 refused before any run. Contract 1.1 adds `files`, `task`, `limits`, `approvals`, `question` | ADR 0022 decision 1; `core/harness.py`; ADR 0001 decision 8 |

## Decision

docket stays the governed executor of ADR 0017. It gains one gate that asks an outside command a
question, one profile that refuses to run unsafely, one source of standing instructions that a
human controls, and two small fields in its evidence. It still never names a verifier, never reads
a verdict beyond an exit code, and never decides a merge. Without the new settings nothing changes
(P3, P4).

### D1. An external verification gate

1. **A new gate kind, `type: external`, on a pipeline step.** It sits beside `mechanical` and
   `verdict` in `core/pipeline.py`, because `MechanicalGate` is documented as "nonzero exit fails"
   and gains no third outcome without breaking its readers. Proposed shape:

   ```yaml
   - id: implement
     role: implementer
     gate:
       type: external
       command: "prill verify --base $DOCKET_BASE_COMMIT --head $DOCKET_HEAD_COMMIT"  # example only
       reasonsFile: ".docket-gate/reasons.json"   # optional; relative to the task worktree
       exitMap: { pass: [0], fail: [1], needsHuman: [2] }   # default shown
       timeout: 900
     on:
       fail: { goto: implement, max: 3 }
   ```

   `command` is an operator string; the code never contains a verifier's name. The same shape is
   reachable from the harness as `docket exec --recipe ... --gate-cmd CMD [--gate-reasons PATH]
   [--gate-exit-map pass=0,fail=1,needs-human=2]` (contract 1.1 only, like `--recipe`), and from the
   short form of a step as `gate: {external: CMD}`. Flag and key names are proposals.
2. **Where it runs.** After the step's hop, in the task's worktree (`_task_worktree_dir`), through
   `_run_in_envelope`, so it gets the pod's jail when isolation is on and the same environment
   (`DOCKET_TASK_ID`, `DOCKET_BASE_COMMIT`, `DOCKET_HEAD_COMMIT`). The commit is the Implementer
   hop's recorded `commit`. A member `verifyCmd`, when set, runs first with the existing
   mechanical semantics; a failing `verifyCmd` is a plain `fail` and the external command is not
   called. This recommendation is "sit beside, reuse the runner": the external gate shares
   `_run_in_envelope`, the output redaction and the hop's `verify` evidence, and adds only the
   exit mapping, the reasons file and the park path. Extending `MechanicalGate` is rejected (see
   "Options considered").
3. **Exit mapping.** The exit code maps to `pass`, `fail` or `needs_human` through `exitMap`.
   Anything else is neither: an unmapped code, a timeout, a jail refusal, a missing command or a
   crash is a fourth label, `error`. `error` never passes. It routes as `needs_human` and does not
   spend a rework attempt (a broken verifier is not the agent's fault). The label and the raw exit
   code are recorded; docket attaches no meaning to the code beyond the map.
4. **Reasons file.** After the command exits, docket reads the file at `reasonsFile`, if named and
   present. It must be UTF-8 JSON of at most 64 KiB, an object with a `reasons` array whose entries
   are objects with `summary` (string) and optionally `id`, `path`, `line`, `severity`, `detail`.
   Anything else (too big, not JSON, wrong shape) is recorded as `reasonsInvalid` and the gate's
   outcome stands; the raw output tail is used as the reasons instead. Reasons are text produced by
   a process that read agent-written code, so they are untrusted: they pass `pre_input` and
   redaction before storage, as MCP results do (ADR 0019 decision 2). docket does not parse
   `severity` or any other field for control flow.
5. **On `fail`: the locksmith loop.** The `on.fail` route (`{goto, max}`) sends the task back to the
   named step with the reasons in a `--- GATE FAILED ---` section, composed the same way as the
   `REWORK REQUIRED` carryover. The bound is the route's `max` (default: the pod's
   `maxReworkCycles`) and the existing turn bounds, including the token and wall-clock limits and
   `no_progress`. When `max` is spent, the task ends `failed` with reason `gate_failed`. A task
   with an external gate cannot end `done` while the gate is not `pass`. The final gate result is
   in the hop's `verify` evidence and so in evidence-v1 (D4).
6. **On `needs_human`: park with a pack.** The task goes `waiting_input`, using the machinery of an
   `input` step (a docket-minted `QuestionV11`, ADR 0018). The pack: `kind: decision`, the reasons
   as the message, and three options: `rework` (go back to the named step with the reasons and an
   optional operator note), `accept` (advance; the hop is marked `gateOverridden` with the actor,
   audited), `reject` (fail the task). The recommendation is `rework` when the reasons are
   non-empty, `reject` otherwise. Under `--answers stdin` the question goes out on the wire and an
   unanswered question denies at its deadline (fail closed), as ADR 0017 decision 2 says.
7. **No gate, no change.** A pipeline without an external gate behaves byte for byte as today.

### D2. A `lights-out` profile

1. **The profile is a recorded operator choice.** Proposed: `docket setup profile lights-out`
   (global, in the fleet security record next to isolation and network) and `docket setup profile
   attended` (the default, nothing recorded). A pod may set `profile: lights-out` to opt in alone;
   a pod can only move toward stricter. `exec` accepts `--profile lights-out` for a caller that
   brings its own `DOCKET_HOME`. The setting and refusals are audited.
2. **What it requires**, checked before any model call, for every dispatch, `start --dispatch`
   sweep and `exec`:
   - isolation on, with a usable backend (`_resolve_sandbox` returns `want_sandbox` true);
   - the jail's network `none` for the pod (`effective_network` returns `none` and the jail
     enforces it), because docket has no domain-allowlist egress proxy (ADR 0024 decision 5);
     `fetch` keeps its operator allowlist and is the only network path;
   - an external gate on every step that has an Implementer role (D1), found by walking the
     loaded pipeline;
   - docket's credentials, and every name in the secret store, absent from every task process:
     the profile checks that ADR 0020 decision 8's stripping is in force and that the pod injects
     no variable named in the secret store into a jailed `bash`;
   - the task carries a `risk` and a `domain` (D5), when the operator set `lightsOut.requireRisk`.
3. **Refuse, do not degrade.** When any requirement fails, the run does not start. The refusal
   names the missing requirement and its fix, writes an audit entry (`profile.refused`) and, for
   `exec`, exits 2 with `status: refused`, as `isolation.refused` does. There is no flag that
   drops one requirement and keeps the profile.
4. **Existing defaults do not move.** ADR 0021 (isolation opt-in) and ADR 0004 (egress open on the
   host) stand. A fresh install is `attended`. The profile only adds a mode that demands what the
   defaults leave to the operator.
5. **One profile for L4 and L5.** The difference between the two levels is not a different set of
   safeguards in docket; it is how much the operator allows. That is data, not a second code path
   (P4): `lightsOut.domains` (domains authorised to run unattended), `lightsOut.riskMax`
   (`low|medium|high`), and `onNeedsHuman` (`park`, the default; or `fail`, which ends the task
   instead of waiting, for an operator who wants no waiting task at all). An L4 operator lists a
   few domains and sets `riskMax: medium`; an L5 operator lists more and allows `high`. The
   caller, not docket, assigns each task's level.

### D3. Directives from the repository ("mentoring as code")

1. **One file: the codebase root's `AGENTS.md`.** docket already composes it into every pod
   member's prompt when `projectInstructions` is unset (`project_instruction_files`), in every
   role, screened as untrusted. A second `directives/` folder would be a second loader with the
   same trust problem and no reader that needs it. A repository that wants structure writes
   sections in `AGENTS.md` or points `projectInstructions` at more files, which exists today.
   The change below is not a new feature; it is making the existing one safe to rely on.
2. **Read the approved version, not the agent's.** Under the lights-out profile, docket reads the
   directives files from the task's `baseCommit` (the commit the worktree was created from, ADR
   0019 decision 1) with host-side git on the git dirs docket recorded, not from the worktree. A
   change the agent makes to `AGENTS.md` shows up in its diff for the verifier and the human, and
   takes effect only after the operator merges it. Outside the profile the behaviour is
   unchanged (see Evidence: today the worktree is the root).
3. **Evidence names what applied.** The task's evidence records `directives: [{path, sha256}]` for
   the files composed into its prompts (D4).
4. **The corrections ledger gains an export.** `docket task corrections [--pod P] [--task T]
   --json` (name a proposal) prints the ledger's records in a stable shape:

   ```json
   { "v": "1.0.0", "pod": "myapp", "corrections": [
     { "id": "<sha256 of the line>", "ts": "...", "taskId": "...", "role": "reviewer",
       "kind": "request-changes", "source": "...", "text": "<redacted, <= 4000 chars>" } ] }
   ```

   `id` is new (a digest of the record line, so a consumer can deduplicate). The schema is
   generated into `docs/contracts/corrections-v1/` like the other contracts. This is the whole
   feature: another tool may propose directives from it, a human merges them, docket reads the
   merged file. **docket never turns a correction into a directive.**

### D4. Linking an attempt to its trajectory

evidence-v1 already links each hop to a trace session (`trace: {project, session, firstTs,
lastTs}`) and the audit log is hash-chained. What is missing is a stable attempt identity and a
content check. Proposed as evidence `1.1.0`, additive and opt-in like the other contract bumps
(every `1.0.0` byte unchanged unless asked):
- **`attemptId`** on each hop: a docket-minted id, unique per hop execution (a rework hop gets a
  new one), and **`trajectoryId`** on the task: one id for the whole task across attempts.
  Both are also written into the trace events of the hop (`attemptId` in the event body) so a
  trace reader can join on them.
- **`trace.sha256`**: the SHA-256 of the hop's trace events between `firstTs` and `lastTs` in the
  session file, canonicalised the way `core/audit.py` canonicalises a line (sorted keys, no
  whitespace). It is a content check, not a signature. It uses `hashlib`, no new dependency.
- **`auditHead`**: the audit log's `{seq, hash}` at the time the task reached its terminal or
  parked status, so a verifier can anchor the evidence to a point in the chain `docket log verify`
  checks.
- **`gate`** on the hop that ran an external gate: `{label, exitCode, reasonsInvalid, overridden}`
  and the `directives` list of D3. No verdict about the work is added; `label` is the exit-code
  mapping of D1 and nothing more.

### D5. Task-level risk input

1. **docket accepts, records and enforces a ceiling; it never classifies.** A task brief gains
   optional `risk` (`low|medium|high`) and `domain` (a label, `^[a-z0-9][a-z0-9._-]{0,63}$`).
   `docket task add --risk R --domain D` and `docket exec --risk R --domain D` carry them. Both are
   caller-supplied text, recorded on the task and in evidence (`task.risk`, `task.domain`) and in
   the harness result's `task` block.
2. **The profile may refuse.** Under `lights-out`, a task whose `risk` is above `lightsOut.riskMax`,
   or whose `domain` is not in `lightsOut.domains`, is refused at enqueue (`risk.refused`, audited)
   with a message that says which rule applied and that a human can run it under `attended`.
   `high` is refused unless the domain is listed, which is how the caller says the domain is
   authorised. A task with no `risk` is `high` when `requireRisk` is set, else unlabeled.
3. **No inference.** docket does not derive risk from the diff, the files or the brief. This is
   consistent with ADR 0017, which cut risk tiers from docket.

## What this reverses or amends

| Earlier decision | Now |
| --- | --- |
| ADR 0021: isolation is opt-in; ADR 0004: egress open by default | **Unchanged.** The `lights-out` profile requires isolation and `network none`, and refuses to start otherwise. It amends them only by adding the profile. |
| ADR 0017 decision 5: docket never scores its own work | Reaffirmed. The external gate maps an exit code and passes reasons through; it adds no judgment. |
| ADR 0017 decision 4: `requireVerify` fails a missing `verifyCmd` | Extended: under the profile a missing external gate is a refusal to start. |
| ADR 0020 "Cut and deferred": `kind: autonomy` | **Unchanged and still deferred.** The profile's `domains` and `riskMax` are operator settings, not a document a verifier emits. Trigger: a verifier that emits one. |
| ADR 0018 evidence-v1 (`1.0.0`) | Amended: `1.1.0` adds the D4 fields, opt-in. |
| ADR 0012: the repository's `.docket/` applies only by an operator command | Unchanged. `AGENTS.md` has been read live since ADR 0013; D3 only fixes which version is read under the profile. |
| ADR 0001 / 0022: exit codes 0, 1, 2 for `exec` | Unchanged. A parked gate question ends the run `blocked` (exit 1) unless answered, as a consult already does. |

## Options considered and not adopted

| Option | Why not |
| --- | --- |
| Call a specific verifier by name (its CLI, its pack format) | Breaks P1 and P2. A verifier changes, a second one appears, and docket would carry a plugin per consumer. The gate takes a command and an exit map; the adapter that knows the verifier's flags is the operator's string. |
| Turn isolation on by default for everyone | ADR 0021: a host with no sandbox could not run one turn, and CI failed on stock macOS. The profile gets the same safety for the operator who asked for it. |
| Extend `MechanicalGate` with a third outcome and a reasons file | Its readers (`until: verify`, the default pipeline, `on: {pass,fail}` routes, evidence `exitCode` 0 or 1) assume two outcomes. A new gate kind changes none of them. |
| docket scores its own work, or decides merge readiness | P5 and ADR 0017 decision 5. The agent that did the work, or the runtime that ran it, is not an independent check. |
| One profile per level (`l4`, `l5`) | The safeguards are the same; only the operator's grants differ, and those are data (D2.5). Two profiles invite a third. |
| A `directives/` folder with its own loader | A second loader to screen and test, with no consumer that needs it. `AGENTS.md` is already loaded for every role. |
| docket turns corrections into directives itself | A directive is a standing instruction to every agent. The human who merges it is the control (P5). docket only exports. |
| docket classifies task risk | ADR 0017 cut risk tiers. Classification is the caller's, the ceiling is the operator's. |
| Reading the verifier's verdict from its pack | docket would then depend on the pack's schema (P1). The exit code and an optional reasons file are the whole contract. |

## Consequences

- An operator can run L4 or L5 with one profile and one gate, and the same binary stays L3 with
  neither. A missing verifier is a missing gate, which the profile refuses and `attended` ignores
  (P3).
- The locksmith loop spends tokens, not dollars: docket reports no dollar cost (`cost_usd` is
  `null`), so the loop's real bound is `max`, the turn bounds and the token limit. `--max-tokens`
  does not apply to `--recipe` runs today, so a lights-out recipe run is bounded by `max` and
  wall-clock only until that is lifted (open question 5).
- The profile makes the `network none` plus `fetch`-allowlist posture the only unattended one. A
  task that needs a package registry waits for the operator to warm caches (ADR 0024) or runs
  `attended`.
- Evidence grows by a few fields; a consumer that ignores them is unaffected.
- The repository's `AGENTS.md` becomes a control surface that a human merges. A reviewer of a
  change to it is the one place a bad standing instruction can enter the fleet.
- `docs/SECURITY-SIMPLE.md`, `docs/commands.md`, `specs/functional/pipeline-format.spec.md`,
  `specs/functional/security-gates.spec.md` and the evidence/harness contract docs need updating
  when each card merges (D-37).

## Open questions for the owner

1. **Does the external gate run in the jail?** It executes tests the agent wrote, so the answer is
   yes by default (`_run_in_envelope`). But with `network none` a verifier that needs a license
   server, a model API or a remote index cannot run. Options: allow a gate to declare
   `network: open` (an operator grant, audited), or require such a verifier to run on the host,
   which weakens ADR 0024's "the host runs only docket". Which?
2. **Where does the reasons file live?** In the worktree it appears in the diff and in `files`.
   The alternative is a path docket supplies in the environment (for example
   `DOCKET_GATE_REASONS_FILE`) under the pod's cache directory. The proposal above allows both;
   pick one.
3. **Does the answer to a parked gate question re-enter the same role?** `core/answers.py`
   re-enters the role that asked a `consult`. A gate has no asking role, so `rework` needs a new
   continuation and `accept` needs none. Is the new continuation acceptable, or should `needs_human`
   simply fail the task and leave resuming to the caller?
4. **AGENTS.md is agent-writable today.** Under the evidence above, the project-instructions root is
   the task worktree, so an Implementer can edit the file that the Reviewer and Tester then read.
   D3.2 fixes this only under the profile. Should it be fixed for every run (a behaviour change to
   an existing feature, with no users to migrate, per D-57)?
5. **`--max-tokens` is refused with `--recipe`** (`cli/_harness_recipe.py`), and `budgetUsd` is a
   Lead setting against a runtime that reports no dollars. What is the spending bound of an
   unattended pipeline run: a per-task token budget (new), the rework `max` only, or lifting the
   `--recipe` restriction?
6. **Which secrets does a jailed `bash` still see?** ADR 0020 decision 8 says a jailed `bash` gets
   `PATH` and "the pod's injected variables". If a pod can inject a secret-store value, "credentials
   not exposed" in D2.2 is weaker than it reads. Does the profile refuse any injected variable, or
   only those named in the secret store?
7. **docket's own egress is outside the jail.** `fetch` (operator allowlist) and HTTP MCP servers
   (called by docket's own client, ADR 0020 decision 5) leave the host regardless of the jail's
   `network none`. Does the profile require an empty or allowlisted set of HTTP MCP servers?
8. **`network none` with isolation off is a silent hole at the default scope.** `effective_network`
   returns `none` with scope `default` when nothing is recorded, and `_resolve_network` then allows
   the turn with the network open. Is that the intended reading of ADR 0004 (egress open until the
   operator records otherwise)? The profile avoids the question by requiring isolation, but `doctor`
   and `gates status` may be reporting `none` where egress is in fact open.
9. **Where does `risk` come from for a task made by a pod's Lead?** A Lead can split a brief into
   tasks. Does a child inherit the parent's `risk` and `domain`, or must each carry its own?
10. **Where is the ledger read?** Only `docket task show` shows it. ADR 0022 lists a `pod <p>
    corrections` entry that has no command in `src/docket/cli/`. Should the export be a flag on
    `task show`, a new command, or that missing entry?
11. **Order of `verifyCmd` and the external gate.** D1.2 runs the member's `verifyCmd` first. If a
    pod wants only the external gate, it must clear `verifyCmd`. Is a single `gate` slot per step
    enough, or should a step be allowed an ordered list of gates?
12. **Does the profile apply to a harness caller's workspace?** `exec --recipe` works in place on
    the caller's directory with no worktree (ADR 0017 decision 3), so there is no `baseCommit` for
    D3.2 and no worktree for the gate. Should the profile refuse in-place runs?

## Related fixes (not decisions)

Found while reading; not fixed by this ADR:
- `SECURITY.md` lines 76-83 and 120-121 still describe the pre-Phase-41 sandbox: bubblewrap as the
  first choice, a "stdio MCP servers start in the same jail unless declared `--no-isolate`" clause
  (the flag and `isolate: false` were deleted, ADR 0024 decision 5), "needs bubblewrap on Linux or
  a running Docker", `docket gates isolate on` (now `docket setup sandbox on`) and the refusal
  text. Landlock plus seccomp on Linux, Seatbelt on macOS and Docker only when chosen are the
  current backends (ADR 0024 decision 3).
- ADR 0017 names the independent verifier "Assay" (decision 5). The verifier that exists today is
  Prill. ADR 0017 is a record of its date; the name should be corrected with a note, not
  rewritten.
- ADR 0022's table lists `pod <p> ... corrections`, which has no command in `src/docket/cli/`
  (open question 10).

## Accepted with amendments (2026-10-13)

The owner accepted the decision with the cuts below, made on the §4.5 test (a measured need in
this system). Two facts found at acceptance drove them:
- **An `input` step already parks a task and routes its answer.** `core/answers.py::answer_task`
  resolves `answered`/`declined` through the step's own `on:` map (`_resolve_route`, bounded by
  `max`, cycle counts rebuilt from the persisted hops). A gate needs no continuation of its own.
- **A backward `on:` route re-runs its target blind.** `_run_pipeline` fills
  `pending_rework_by_index` only for a verdict gate's `rework` outcome; a `routed` outcome
  (`until: verify` included) re-runs the Implementer without the gate's output, which is not in
  the artifact `_hop_message` renders. That is a defect today and the base of the gate loop.

What changes:

| Item | Amended to |
| --- | --- |
| D1.1 `exec --gate-cmd/--gate-reasons/--gate-exit-map` | **Cut.** By P2 the caller that spawns `exec` calls the verifier itself; `exec --recipe` runs in place with no worktree. Trigger: a caller runs `exec` unattended and asks docket to close the loop. |
| D1.1 `reasonsFile` key (in the worktree) | **Replaced** by `DOCKET_GATE_REASONS_FILE`, a path docket supplies under the pod cache dir (a read-write jail root since ADR 0024), deleted before each run. A worktree path shows in the diff and can be pre-written by the agent. |
| D1.2 `verifyCmd` runs before the external gate | **Cut.** One gate per step; an external gate runs only its command (answers question 11). |
| D1.3 `error` routes as `needs_human` | **Amended.** Four labels `pass`, `fail`, `needs_human`, `error`, each routable by `on:`; an unrouted `fail`, `needs_human` or `error` fails the task (fail closed) with its own failure kind. |
| D1.5 `--- GATE FAILED ---` carryover | **Kept and generalised** to every backward `on:` route from a gated hop, mechanical included (card P42-1). |
| D1.6 the `rework/accept/reject` pack, `gateOverridden` | **Cut.** `on: {needs_human: <input step>}` parks with an existing `input` step whose `answered`/`declined` route on (answers question 3). An override that advances past a failed gate has no requester. Trigger: an operator asks for one. |
| D2 profile | **Kept**, pod dispatch only (`run`, `start --dispatch`); `exec --profile` cut with D1.1 (answers question 12). Checks: isolation usable; network `none` enforced by the jail; an external gate on every Implementer step; no HTTP MCP server in the pod's effective set (question 7); no pod-injected variable named in the secret store (question 6). |
| D2.5 `lightsOut.domains`, `riskMax`, `requireRisk`, `onNeedsHuman` | **Cut.** The pod is the bounded domain: L4 is some pods `lights-out`, L5 all of them; the caller chooses which pod gets a task. `onNeedsHuman` is a route. |
| D3.2 directives from `baseCommit` under the profile only | **Every run with a task worktree** (answers question 4): one code path, not a profile branch (P4, D-57). Skills under the codebase's `.docket/skills/` are read the same way. |
| D3.4 `docket task corrections` and `corrections-v1` | **Deferred.** No consumer exists. Trigger: one does (answers question 10). |
| D4 `attemptId`, `trajectoryId`, `trace.sha256`, `auditHead` | **Cut / deferred.** The trajectory is the task id and an attempt is a hop's index in `hops[]`; the digests have no reader. Trigger: a verifier that reads evidence asks for them. Evidence `1.1.0` carries only `gate` (per hop) and `directives` (per task). |
| D5 risk and domain | **Deferred whole** (question 9 is moot). Trigger: one pod must run two risk ceilings at once. |
| Question 1, gate network | The gate runs in the jail with the pod's network; a verifier that needs the network ends `error`, visibly. Trigger for a `network: open` grant: such a verifier. |
| Question 5, spending bound | Unchanged: the mandatory `max` on every backward route plus the turn bounds and `no_progress`. |
| Question 8, `none` reported where egress is open | A truthfulness defect of its own (card P42-7, RED first). |
