# ADR 0008 (D-42): The configuration contract

**Question:** A file-by-file audit of what `docket init` and first use create, followed by a
re-audit at `a592328`, found that customizing agents, orchestration and governance works only
partly. Some settings govern nothing; some have no writer; some fail silently. Some governance
fails open. What should docket's customization surface guarantee, and which of the findings earn
a card?

**Where decided:** 2026-09-25, as Phase 26, which opens after Wave 37 closes.

**Evidence:**

- The user-facing guide [docs/CONFIGURATION.md](../CONFIGURATION.md).
- The audit `internal-docs/installed-files-audit-2026-09-25.md` (gitignored), re-verified at
  `a592328`.
- One real dispatch on the local 16k endpoint.
- Deterministic reproductions, quoted in the verdict table below.

## Decision

**Adopt one contract that every operator-facing setting must satisfy, and schedule only the gaps
where a setting breaks it.** Four properties matter most:

1. A setting either has a live consumer or does not exist.
2. Governance fails closed.
3. Nothing is dropped or defaulted silently.
4. The operator can ask docket what is in effect and why.

Most of the work is **wiring and validation over machinery that already exists**: the pipeline
dialect, role archetypes, the store, the approval refusal mode that harness mode already uses, and
the request preflight against the model window. It is not new machinery.

The request that opened this was explicit: make the pipeline and agent configuration robust,
standard and versatile, so that governance and customization are real, and do not let a fixed
~24 KB budget limit a simple or robust orchestration. That request plus the measured
reproductions below is the trigger (§4.5). No "best practice elsewhere" item is scheduled on the
strength of being best practice.

### The contract

Every operator-facing setting must satisfy all six properties:

| # | Property | Violated today by |
| --- | --- | --- |
| 1 | **One home, one writer.** A documented file and key, and a public command that writes it. Hand-editing may be possible, but it is never the only path. | `maxReworkCycles`, `turnTimeoutS`, `verifyTimeoutS` (hand-edit or a hidden `_json meta-set` only); `docket-schedules.json` (no writer) |
| 2 | **Typed and validated at write.** A bad value is refused when it is written, not discovered at run time. | `budgetUsd` stored as the raw CLI string; `policies validate` does not compile the regex |
| 3 | **A live consumer on the default path.** If only an opt-in flag, a hidden command or a display reads it, it is not a setting. This is the sixth unwired-machinery instance. | pipeline files (only `pipeline run --file`); pipeline `variables` (stored on the run, never interpolated); pod `templateVersion`; `fleet.json` `defaults.model`; `gates enable/disable`; provider `name`/`cost`/`reasoning`/`input`/`api`; workspace `.env` |
| 4 | **Governance fails closed; everything else fails loud.** Never skip or default silently. | A malformed `block` policy is skipped and the call is **allowed**. An invalid meta value, schedule, model entry or overlay role is silently replaced or ignored. |
| 5 | **Observable with provenance.** The effective value, and where it came from, can be asked for. | Nothing answers "what will this agent see and be allowed to do". This guide and two code-tracing audits were needed to find out. |
| 6 | **Versioned; operator edits survive regeneration.** | Generated `SOUL.md`/`AGENTS.md`/`TOOLS.md` have no user-owned layer (`set-verify` rewrites `TOOLS.md`), there is no re-render when an archetype changes, and pod `templateVersion` "2" is never compared |

### The three layers, evaluated

**Instructions (what an agent is told).** The composition order is right: identity, then the
runtime contract, then state, all rebuilt from disk every turn and never persisted. The defects
are the budget and silence:

- The state budget is a process-wide constant, `CONTEXT_TOKEN_BUDGET` × 4 bytes ≈ 24 KB. It
  ignores the resolved model's registered `contextWindow`, which docket already records and
  preflights against.
- On overflow, later sections are dropped. Past about 24 KB of `SOUL.md`, **all state vanishes
  with no marker**, which breaks `agent-loop.spec.md` requirement 30 ("mark any
  truncation/omission visibly").
- The hop handoff budget (archetype `tokenBudget`, 6000) is also a constant, where it should be a
  share of the window.
- Operators have no instruction layer docket will not overwrite.
- The templates still contradict the runtime contract: an AGENTS red line tells the model to write
  `HEARTBEAT.md`, and the contract says private state is read-only.

The fix is not "a bigger number". Budgets become **a function of the resolved model window**. The
state the pipeline depends on (the runtime contract, the HEARTBEAT ledger, TOOLS facts such as the
verify gate and port range) is **protected**. `SOUL.md` is visibly truncated before state is
dropped. Every truncation or omission is marked in the prompt and traced.

**Orchestration (who runs, in what order, gated how).** The dialect is sound, and it is already
the one executor behind `plan`, `run` and `dispatch`. What is broken is binding and expressiveness:

- A pipeline file cannot be a pod's default, so serve, schedules, webhooks and MCP can never run
  it.
- A custom role gets no per-hop instruction, not even its verdict marker.
- `variables` are stored and never used.
- Pod settings are untyped and have no writer.

**Governance (what an agent may do).** The chokepoint design is right: one gate, and a
most-restrictive-wins rule between the classifier and policies. Three problems:

- The policy store fails **open**.
- Unattended turns wait 120 s on every ask even when nothing can answer. Three asks in a row
  killed the Tester hop in the real dispatch.
- There is no audited, scoped way to allow a project's own test runner (`pytest`, `uv`), so the
  only unattended path is `python3 -m …`.

## Verdict table

Items 1–24 are the re-verified audit findings at `a592328`. N1–N2 are new reproductions.

| Finding | Verdict | Card | Evidence / reason |
| --- | --- | --- | --- |
| N1 malformed `block` policy fails **open** (18) | **DO first** | P26-1 | `make\s+deploy` + `block` → `deny`; one extra `(` → **`allow`**, and `policies validate` says "valid"; bad JSON escape → `allow` |
| N2 prompt drops all state with no marker (22) | **DO** | P26-2 | `SOUL.md` 21.9 KB → MEMORY truncated; 24.4 KB → HEARTBEAT, AGENTS, TOOLS, MEMORY all absent, no marker, no trace |
| 22 static budgets ignore the model window | **DO** | P26-3 | the same repro against a 200k-window model; handoff `tokenBudget` fixed at 6000 |
| 6, 7 pod settings: no writer, stored as strings, silent default | **DO** — reverses D-41's "not scheduled" | P26-4 | D-41 judged a timeout writer unmeasured. What changed: invalid values are silently replaced (`dispatch.py:434-463`), `budgetUsd` is persisted as a string, and the explicit request makes pod tuning a first-class need. It is said here, not quietly re-litigated. |
| 24 unattended ask waits 120 s × N with no channel | **DO** | P26-5 | a real tester hop died on 3 × `approval_timeout`; harness mode already has `refuse` |
| 4 pipeline file cannot be a pod's default | **DO** | P26-6 | only `cli/_pod.py:575` and `cli/_pipeline.py:167,205` pass `spec=` |
| 3, 5 custom role gets no hop instruction; `variables` unused | **DO** | P26-7 | `dispatch.py:571-572,639`; `resolve_variables` only stores into `runs.py:285` |
| 1 (partial) `pytest`/`uv`/`python` ask | **DO — scoped, audited, per pod** | P26-8 | `classify_command('pytest -q')` → ask. Never loosens opaque markers, high-risk classes or policies |
| 2 templates contradict the runtime contract | **DO** | P26-9 | `archetypes.py:330,452`; `memory.py:114-171` |
| 8 + contract #6: no operator layer, no re-render | **DO** | P26-10 | `set-verify` rewrites `TOOLS.md`; `POD_TEMPLATE_VERSION` never compared |
| contract #5: no effective-config view | **DO** | P26-11 | read-only composition of existing functions |
| 18 (rest), 19 silent skips; schedules have no writer | **DO** | P26-12 | `schedule.py:189,196`, `models_policy.py:256-285`, `archetypes.py:664` |
| 13 plaintext `.env` copies with no reader; keyring never stores | **DO** | P26-13 | `cli/_keys.py:95-122`; `system.py` has lookup only |
| 9, 10, 11 duplicate or unread model fields | **DO — small** | P26-14 | one default of record; the provider label derives from `--model` |
| 14 registries never pruned | **DO** — trigger fired | P26-15 | this machine: `docket-runs.json` 9.45 MB, 23,925 runs, rewritten with a same-size `.bak` on every update |
| 15 approval trace attribution | **DO — small** | P26-15 | approvals filed under the agent id. (16 withdrawn: `guardrail_block.action` = policy id is contractual, security-gates.spec.md req. 4) |
| 12 `gates enable/disable` unread (W34-A1) | **Maintainer decision** — default: retire | P26-16 | P26-5 adds the wired approval setting this flag pretends to be |
| 17, 21 branch/lock leftovers, 0775 dirs | **DO — small** | P26-16 | `pod_provisioning.py:433-548`, `_install.py:433-435` |
| 20 stale docstrings | fold into the owning card | P26-1, P26-15 | not a card of its own |
| Codebase `AGENTS.md`/`CLAUDE.md` (the agents.md convention) as bounded project instructions | **DO — opt-in** | P26-17 | the standard way a repo states conventions; today agents see it only if they choose to `read` it |
| N3 membership guessed from the id string breaks hyphenated custom roles | **DO** | P26-18 | live: `pod add security-reviewer` provisions and `pipeline plan` resolves, then dispatch refuses `proj-security-reviewer` as "not in pod 'proj'" — `pod_of` rpartitions the id while the meta already records `"pod": "proj"` |
| N4 a deterministic refusal orphans the task as `running` | **DO** | P26-19 | live: after N3's refusal, the claim was never settled; the CLI then refused to dispatch at all ("No pending tasks"), so the recovering sweep could not run without queueing a decoy task |
| Shipped recipes: role+pipeline+policy bundles, tested and configurable | **DO** | P26-20 | explicit request (2026-09-25): recipes in the repo must be robust for real use yet easily configurable; today only 6 policy templates ship, and the first recipe attempt tripped N3 |
| Declarative pod manifest (`pod.yaml` apply/diff/export of roster, roles, models, policies) | **DEFER** | — | P26-4/P26-11 give every setting one writer and a view. A manifest needs reconciliation semantics (apply, diff, prune). **Trigger:** a pod reproduced on a second machine, or `POST /pods` needing a full spec. |
| Per-agent or per-pod tool capability overrides | **DEFER** | — | A custom role already gives one agent different denials. **Trigger:** two members of one role in one pod need different tools. |
| On-demand private reference directory (`context/`) | **DEFER** | — | **Trigger:** after P26-3, a real pod's measured instructions still exceed their window share. |
| User-registered blueprints | **DEFER** | — | P26-6 (pipeline binding) plus custom roles cover it. **Trigger:** the same custom pod shape provisioned a third time (rule of three). |
| A bigger `CONTEXT_TOKEN_BUDGET` default | **CUT** | — | It moves the cliff; it does not remove it. |
| A second pipeline dialect, a visual editor, a plugin system | **CUT** | — | §4.5 and D-16 stand. |

## What the E2E run proved (2026-09-25, second pass)

The same day, one full chain ran on the throwaway install against the local endpoint: custom role
YAML → `roles add` → `pod add` → custom `warn` policy dropped into `policies/` → `pipeline plan
--file` → `pipeline run --file`. Two tasks reached `done` through `lead → implementer → vetter`
(a custom verdict-gated role), with:

- the verify gate run in the implementer's worktree, and the produced diff left there for review;
- the downstream custom role reading the **implementer's worktree** (role-agnostic
  `DOCKET_PIPELINE_WORKTREE` root swap) plus a checkout note that repeats the verdict-marker duty
  — two links that are correctly wired and worth protecting with the P26-20 recipe test;
- the `warn` policy firing live and landing in the audit log (`tool.warn` with agent, role and
  policy id) — though not in traces, so `docket metrics`' guardrail counters never see in-turn
  warns (an attribution nuance P26-15 inherits);
- crash-resume continuity: after N3's refusal was cleared, the orphaned task resumed from its two
  persisted hops and finished with the new step only.

So the spine (chokepoint, gates, worktree continuity, resume) holds; what breaks is exactly the
contract's properties — derived state over recorded state (N3), a refusal that neither fails
closed nor loud (N4), and configuration whose only proof is a hand-run audit (P26-20's recipes
make the proof executable).

## Consequences

- Phase 26 has twenty cards, delivered in waves the integrator batches by function-level
  contention. The table in `TODO.md` is the input to that batching.
- `core/dispatch.py`, `core/identity.py` and `core/tools.py` are the hot files. Each card names the
  functions it owns there.
- Governance goes first (P26-1). A customization surface built on a policy store that fails open
  would advertise control it does not have.
- After Phase 26, `docs/CONFIGURATION.md` §5 ("Sharp edges") should shrink to the deferred items.
  Each closing card deletes its own bullet in the same commit (D-37: the prose follows the tree).
