# docket — Roadmap

docket's durable decisions and the one-line record of every phase. Executable cards live in
[TODO.md](TODO.md); the reasoning behind each phase is its ADR in [docs/adr/](docs/adr/); the full
phase records, wave narratives and this file's older sections are archived verbatim in
[docs/cycles-ended/](docs/cycles-ended/README.md) (SHA-256 manifest) and are never mined for work.

---

## Status

**Last updated: 2026-10-24.** Every phase 0–49 is complete; none is active. Phase 49 (D-70) made the
task one typed record behind one store, with the same JSON on disk. A new phase starts from a measured trigger or a
maintainer request, never from this file.

**The last three phases** closed on branch `plan/phase-46-structure`, not yet merged into `develop`
nor pushed (§7.1). Phases 46-47 are D-66, [ADR 0030](docs/adr/0030-organize-by-context-and-refactor-by-tool.md).
- **Phase 46** moved `src/docket/` into `kernel`, eleven context packages, `interfaces/` and
  `bootstrap.py`, with no module over 700 lines.
- **Phase 47** layered the contexts (an import of a context above is a test failure), and put each
  module in the context whose data it reads. It added:
  - ports for git, processes, the jail, the tracer and the tool gate;
  - one writer of a task's `status`;
  - tests by context, every file passing alone and none able to reach `~/.docket`;
  - one authored YAML form per kind;
  - `when.command` policies measured on a 310-row corpus.
- **The real runs:** the first, on the live home, found four defects, fixed the same day. The
  maintainer's second, from a fresh install, matches the Phase 46 baseline hop for hop.
- **Phase 48** (D-67, D-68, D-69) was planned as six cards and cut to three changes and the copy:
  - `docket init` turns isolation on where the machine can jail;
  - a task run under a caller's pipeline file keeps it;
  - workspace contract v5 drops the daily log docket never read;
  - the README leads with the teams configuration makes, beside the reader's own coding assistant.

**Release:** `v0.2.0-beta.4` is the latest published release (2026-10-06). `VERSION` declares
`0.2.0-beta.6` (API 6, `exec` deleted); beta.5 and beta.6 are in `CHANGELOG.md` and untagged.
Cutting a release is a maintainer action through `release.yml` (then
`scripts/update-homebrew-sha.sh` and a fast-forward of `main` from `develop`), not a board card.
Every release keeps a `-beta.N` suffix until the project drops its beta warning.

| Phase | What it delivered | Decision · ADR | Closed |
| --- | --- | --- | --- |
| 0–13 | Truth and correctness, cost enforcement, channel portability, model/provider agnosticism, observability and guardrails, spec↔runtime integrity, project pods, differentiation, consolidation | D-1…D-13 | 2026-07-02 |
| 14–18 | Platformization I–V: dispatch hardening, wired governance, declarative orchestration, context and memory, the runtime-driver port and MCP | D-14…D-18 | 2026-07-31 |
| 19 | docket takes the runtime: it owns the loop, the tool registry, the three policy hooks, approvals, audit and sessions; no daemon | D-19 · [0002](docs/adr/0002-own-the-loop-rent-the-protocols.md) | 2026-08-04 |
| 20–21 | Fleet observability and the embeddable substrate (`packages/docket-runtime/`), at cut scope | D-20, D-24 · [0003](docs/adr/0003-factory-first-then-embeddable-substrate.md), [0005](docs/adr/0005-prioritization-ruling-viable-vs-overengineering.md) | 2026-08-04 |
| 22 | Control-plane write API for an external plan of record | D-22 | 2026-08-04 |
| 23 | Product truth and ecosystem proof (Waves 26–29; `v0.2.0-beta.2`) | D-25, D-33, D-39 · [0006](docs/adr/0006-portable-governance-execution-envelope.md) | 2026-09-14 |
| 24 | Harness mode: one agent, non-interactive, for a caller that owns the workspace | D-35 · [0001](docs/adr/0001-harness-mode.md) | 2026-09-12 |
| 25 | Human maintainability: test lanes, comment policy, generated docs | D-36 · [0007](docs/adr/0007-human-maintainability-lanes-comments-docs.md) | 2026-09-12 |
| 26 | The configuration contract | D-42 · [0008](docs/adr/0008-configuration-contract.md) | 2026-09-26 |
| 27 | Per-pod configuration and portable teams | D-43 · [0009](docs/adr/0009-per-pod-configuration-and-portable-teams.md) | 2026-09-26 |
| 28 | Configuration format v1 and the two extension points | D-44 · [0010](docs/adr/0010-config-format-v1-and-extension-points.md) | 2026-09-26 |
| 29 | The provider catalog | D-45 · [0011](docs/adr/0011-provider-catalog.md) | 2026-09-27 |
| 30 | The team lives in the repo | D-46 · [0012](docs/adr/0012-the-team-lives-in-the-repo.md) | 2026-09-27 |
| 31 | Recipes as a library; `AGENTS.md` and skills | D-47 · [0013](docs/adr/0013-recipes-as-a-library-and-the-repos-standards.md) | 2026-09-27 |
| 32 | Observability export (`kind: exporter`, OTLP/HTTP) | D-48 · [0014](docs/adr/0014-observability-export.md) | 2026-09-28 |
| 33 | Export privacy levels | D-49 · [0015](docs/adr/0015-export-privacy-levels.md) | 2026-09-28 |
| 34 | The operator loop: park, inbox, channels, intake | D-50 · [0016](docs/adr/0016-operator-loop-and-interop-standards.md) | 2026-09-29 |
| 35 | docket inside a harness-agnostic factory | D-51 · [0017](docs/adr/0017-docket-in-a-harness-agnostic-factory.md) | 2026-10-04 |
| 36 | Consultation packs and evidence v1 | D-53 · [0018](docs/adr/0018-consultation-packs-and-evidence-v1.md) | 2026-10-04 |
| 37 | Verification-ready execution: one worktree per task | D-54 · [0019](docs/adr/0019-verification-ready-execution.md) | 2026-10-04 |
| 38 | The execution envelope (isolation made opt-in again by D-56) | D-55, D-56 · [0020](docs/adr/0020-the-execution-envelope.md), [0021](docs/adr/0021-isolation-is-opt-in.md) | 2026-10-05 |
| 39 | One CLI surface: eleven top-level commands, nothing kept for the past | D-57 · [0022](docs/adr/0022-one-cli-surface.md) | 2026-10-08 |
| 40 | Harden the agent boundary (2026-10-12 security audit) | D-58, D-59 · [0023](docs/adr/0023-harden-the-agent-boundary.md) | 2026-10-12 |
| 41 | One execution envelope: Landlock + seccomp, Seatbelt, Docker when chosen | D-60 · [0024](docs/adr/0024-one-execution-envelope.md) | 2026-10-13 |
| 42 | Lights-out profile and external verification gate | D-61 · [0025](docs/adr/0025-lights-out-profile-and-external-gate.md) | 2026-10-13 |
| — | Harness contract 1.2: `docket exec` runs on the operator's own setup (no phase) | D-62 · [0026](docs/adr/0026-harness-uses-the-operators-setup.md) | 2026-10-13 |
| 43 | The team runtime behind an external plan of record: addressable tasks, HTTP lifecycle, pods over HTTP, `.docket/teams/`, one door (API 5, `exec` deleted) | D-63 · [0027](docs/adr/0027-the-team-runtime-behind-an-external-plan-of-record.md) | **complete** 2026-10-17: Wave 109 (the task, P43-1..5) 2026-10-14, Wave 110 (the pod, P43-6..9) and Wave 111 (the daemon and the command, P43-10..12) 2026-10-17; `exec` deleted, API 5, `0.2.0-beta.6` declared |
| 44 | Context in layers and a budget that counts new tokens: replay bench, new-token budget, bounded tool output, condensed history, delivered handoffs, cache-ordered prompt, governed pod memory | D-64 · [0028](docs/adr/0028-context-in-layers-and-a-budget-that-counts-new-tokens.md) | 2026-10-18 |
| 45 | A prepared checkout, models from the provider, and a check the change cannot define: install from the lockfile with a cache, limits from `/models`, protected paths that park for a person, approvals per (codebase, pod) | D-65 · [0029](docs/adr/0029-a-prepared-checkout-models-from-the-provider-and-a-check-the-change-cannot-define.md) | 2026-10-20 |
| 46 | Organize by context, refactor by tool: `kernel/` and `Home`, import contracts as tests, one owner of a task's state, the runtime as a package, scripts for every mechanical step | D-66 · [0030](docs/adr/0030-organize-by-context-and-refactor-by-tool.md) | **complete** 2026-10-23: contexts, splits, route table, `bootstrap.py`, architecture ratchets; real run matches the baseline; ports, state owner and test restructure are Phase 47 |
| 47 | The seams: layered contexts with each module where its data lives, ports for git, processes, the jail, the tracer and the tool gate, one state owner, tests by context, one authored config form, policies on the parsed command | D-66 · [0030](docs/adr/0030-organize-by-context-and-refactor-by-tool.md) | **complete** 2026-10-24: import baseline 1 line, local imports 1, corpus-measured policies, live-home defects fixed; fresh-install real run matches the Phase 46 baseline |
| 48 | Isolation where the machine can jail, a task keeps its pipeline file, contract v5, positioning | D-67, D-68, D-69 | 2026-10-24 |
| 49 | The task as a typed record behind one store: `TaskRecord` (flat, same JSON), `JsonTaskStore` + `TaskRepository` as the only writers of the queue, `hops` and `interfaces` read attributes, `claimId` and `source` deleted | D-70 | **complete** 2026-10-24 (`4a22a5be`..`423b67a1`); `dict[str, Any]` in `tasks/` and `hops/` 156 to 94, queue writers 19 to 0 outside the store, `src` +40 lines net |

Waves that were not phases (17–22, 30–37, 89–90, 96–97, 108) are recorded in
[docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md).

**Deliberately not scheduled.** Each item is cut, or deferred behind a named trigger; a trigger
firing is a fact about this system, not a backlog to work down. Every ADR ends with its own
deferred list and triggers; the standing ones:

| Not doing | Why · trigger |
| --- | --- |
| Multi-tenancy, streaming, browser automation, a dashboard of our own | Cut (D-22, D-24). docket feeds a dashboard (Tack); browser tooling is an MCP server. |
| The OpenTelemetry SDK | Cut (D-24); Phases 32–33 project docket's own trace to OTLP/HTTP with no dependency. |
| `kind: autonomy`; per-task credential minting | Deferred: a verifier that emits an autonomy document; an issuer a pod needs. |
| A gate override, risk and domain, a corrections export, attempt ids and trace digests, a gate network grant | Deferred by ADR 0025's amendments, each with its trigger there. |
| A softer Landlock policy for a root that holds a `.git` directory | Landlock can only add rights down a tree, so it cannot keep `.git/hooks` read-only under a writable checkout; the jail refuses (exit 125) and points at a worktree or Docker. Pod dispatch runs in linked worktrees and never hits it. Trigger: an operator who must jail a turn in a plain checkout. |
| microVM / gVisor isolation, multi-host provisioning, a second `RuntimeDriver`, other channel auth flows, a Go/Rust rewrite | §7, each with its trigger. |
| Renaming the project (candidate `docketctl`) | Revisit before any wide public launch: "docket" is generic and collides with Ruby Docket. |

---

## 1. Mission (do not lose this)

**docket runs teams of autonomous coding agents across multiple projects, and governs what they are
allowed to do.** Trustworthy and honest before any new capability: correct state, real cost control,
and **zero features that lie about what they do.**

**The approach in one sentence:**
> **Own the loop, rent the protocols.** docket owns the turn loop, the tool registry, all three
> policy hooks, approvals, audit and sessions — because whoever owns the loop owns the interception
> points. It rents only protocols: an OpenAI-compatible HTTP endpoint, MCP for pluggable tool
> servers, containers for isolation.

**The three honesty rules that have the most teeth**, because each was earned by catching a false
claim already in the tree:

1. **Token counts are measured; dollars are estimated.** `agent.ports.TokenUsage` is real. There is no
   recorded dollar spend — `DocketDriver` reports `cost_usd = 0.0` by design. Never relabel an
   estimate as spend, and never project dollar savings.
2. **Context budgets use a characters-per-token approximation.** Never claim exact token counts
   from them.
3. **A capability is what the code does, not what the docs say.** Each spec's Status line and the
   README's "known limits" state what does not work; never overclaim past them. Before repeating a
   "docket does X" claim, find the code on the live turn path that reads the setting: the same
   shape (implemented, tested, never wired) has been found seven times.

**Out of scope (do NOT do these now):** anything in the hosted-SaaS half — multi-tenancy, authn for
external callers, queues/workers, streaming, per-customer quota (see D-20 and D-22). Also: a
dashboard of docket's own (Phase 11 ruling, reaffirmed by Phase 22), and rewriting in another
language. If tempted, stop and add it to §7 "Backlog" instead.

---

## 2. Ground truth about the system (read once)

> Where an archived record contradicts this section, this section wins.

- **Language/stack:** Python 3.11+ (`docket` package under `src/docket/`), Typer + Rich + Pydantic + pydantic-settings + filelock. Installed via `uv`/pip; `bin/docket` is a thin Bash launcher that execs `python -m docket "$@"`. Gated by `ruff` + `mypy --strict` + `pytest`. **There is no daemon and no `systemctl` dependency.**
- **One package per business context, layered** (ADR 0030, D-66). `src/docket/` is `kernel` (imports nothing in `docket`), eleven contexts in layer order `platform < governance < agent < models < observability < pipeline < teams < sandbox < operator < tasks < hops` (each with at most `domain/`, `application/`, `adapters/`; a context imports only those below it), `interfaces/` (`cli http telegram`, the only code that talks to the user; `docket start --mcp` lives in `interfaces/cli/commands/mcp.py`) and one `bootstrap.py`, the only module that names a concrete adapter. The contracts are `tests/architecture/`; their baselines hold one line (the Telegram adapter) and one function-local import (`setup_shell._tree`), and only shrink. A module over 700 lines is a defect.
  - `interfaces/` ([src/docket/interfaces/](src/docket/interfaces/)) — Typer commands (`cli/`, Rich output in `cli/render/`), the HTTP control plane as a route table (`http/routes/`, API 6) and Telegram. `__main__.py` only calls the Typer `app`; a retired name is an ordinary unknown command (D-57).
  - `agent/` ([src/docket/agent/](src/docket/agent/)) — the turn engine: `loop.py` (**the turn loop**, with its budget, compaction and step collaborators `loop_*.py`), `tools/registry.py` (**the chokepoint**, `dispatch_tool`), `session.py`, `context.py`, and `ports.py` (the chat port and `TokenUsage`). It imports `kernel`, `platform`'s `__init__` and itself.
  - `tasks/`, `pipeline/`, `hops/` — the pod state machine: the queue, claims and state (`tasks/`, one `transition()` writes `status`), the pipeline format (`pipeline/domain/`), and hop composition, the executor, gates and the `DocketDriver` (`hops/application/`). `governance/` holds policy, security, approval and audit; `observability/` holds trace, telemetry and exporters; `teams/` holds the fleet, pods, roles, memory and workspaces; `models/` holds providers and the OpenAI-compatible wire adapter; `operator/` holds the inbox and channels.
  - `platform/` and `sandbox/` — the side-effecting code: `platform/store.py` (atomic, filelocked, 0600 JSON I/O — the single chokepoint for docket-owned JSON), `git.py`, `process.py`, `fetch.py`; and the jail (`sandbox/launch.py`, `landlock.py`, `seatbelt.py`, `docker.py`).
- **One state root, one writer per file.** Everything docket owns lives under `~/.docket/` (`DOCKET_HOME`): `fleet.json`, `secrets.json`, the `docket-*.json` registries, `audit.log`, `traces/`, `sessions/`, `approvals/`, `policies/`, `workspaces/`. Per-agent facts live in `.docket-meta.json` in each workspace. **These are not duplicated** — unlike the pre-Phase-19 dual-source world there is no drift to detect, and no sync step.
- **The two invariants that replaced the ACL invariant**, both machine-enforced:
  - **Every tool call goes through `agent/tools/registry.py`'s dispatcher**, where `pre_input`, `pre_tool_call` and `pre_output` all evaluate. A second execution path is a hole. Enforced by an AST test (`tests/unit/agent/tools/test_registry__dispatch.py::test_only_the_chokepoint_imports_the_handler_module`).
  - **Docket-owned JSON goes through `platform/store.py`.** Append-only JSONL (`observability/trace.py`, `governance/audit.py`) writes directly, per the documented **D-12** exemption.
- **Tests** (`tests/`) — the counts here drift; `uv run python scripts/metrics.py --check` is the guard that fails CI when a README or doc number stops matching the tree. **Fix the claim, never the guard.**
  - `tests/unit/`, `tests/integration/`, `tests/guards/` — the default pytest suite (`uv run pytest`). `tests/agent/` is the budgeted agent lane and runs in its own CI job (`uv run pytest tests/agent`). Files are named by **subject**, not by card id.
  - `tests/golden/` — byte-parity golden suite (`bash tests/golden/run.sh verify-all`) — the net that catches a behaviour change. **Never regenerate a golden to hide one.**
  - `scripts/validate-specs.sh` — the spec suite, CI-blocking. CI also runs a `floors` job that resolves the **lowest** versions `pyproject.toml` permits: two of six advertised bounds were false when first measured, so do not move a floor without re-measuring.

---

## 3. Conventions (follow exactly)

> Current conventions. The Bash-era and ACL-era rules are preserved inside the historical phases;
> do not apply them to new work.

- **Typed, gated:** `ruff check .`, `ruff format --check .`, `mypy src` must all pass. No new `# type: ignore` without a reason.
- **Never write JSON by hand** — docket-owned JSON goes through [platform/store.py](src/docket/platform/store.py) (atomic, filelocked, 0600). Append-only JSONL logs (`observability/trace.py`, `governance/audit.py`) write directly; that is the **D-12** exemption and the only one.
- **Respect the import contracts of ADR 0030:** the dependency table in `tests/architecture/` is the rule. `kernel` imports nothing outside itself; the contexts are layered (`LAYERS`: `platform < governance < agent < models < observability < pipeline < teams < sandbox < operator < tasks < hops`) and a context imports only those below it; `agent` imports `kernel`, `platform`'s `__init__` and its own ports; only `interfaces/` talks to the user (no `print`, no `ui.py` elsewhere).
- **Shell-out invariant scope (D-13):** every `git`/`docker` shell-out and every jailed launch funnels through `platform/git.py`, `platform/process.py` and `sandbox/launch.py` — no other module invokes those binaries directly, and they degrade gracefully when one is missing. The sandboxed `bash` tool is not an exception: it reaches the same modules through the chokepoint.
- User-facing status goes through the Rich helpers in [ui.py](src/docket/interfaces/cli/render/ui.py) (`info/success/warn/error`); a command aborts by raising `typer.Exit`. Never raw `print` for status.
- **Nothing is kept for the past (D-57, ADR 0022 §3).** docket has no users. A removed or renamed command, flag, alias, route, persisted shape or behaviour is deleted in the same change that replaces it, with its tests, spec text and docs. No alias table, no retirement notice, no "did you mean the old name", no migration, no `_REMOVED` map, no hidden command, no deprecated no-op flag. A retired name is an ordinary unknown command (exit 2); `CHANGELOG.md` is the only record. The rule stands until docket has an installed base, which is a fact about the world, not a release number.
- Permissions: workspace dirs `700`, files `600`.
- Commit style: `Type: description` (`Add:`/`Fix:`/`Docs:`/`Feat:`/`Refactor:`/`Chore:`/`Test:`/`Merge:`/`Remove:`), detailed body. One task ≈ one commit. **No AI/assistant attribution trailers of any kind; ASCII only.** **Public repo** — scrub real client names, `/home/<user>` paths, and usernames before committing.
- **Every behaviour change adds or updates a test** (pytest; a golden case when output changes). A pure move or rename adds none: `pytest --co` and `tests/architecture/` are its check.
- **Comments: keep rationale, delete archaeology.** Delete card ids, phase numbers, dates, provenance, and narration of what a deleted thing used to do — git history and this file hold all of it. Keep any sentence whose loss would let someone introduce a bug. **When in doubt, keep.** A comment answers "why is it shaped this way"; a docstring is one line unless it states a contract. `scripts/maint/comment_lint.py --check src tests` is the reader of this rule (ratcheted in CI from W31-C3).
- **Tests are placed by lane, named by module.** `specs/test-framework.md` §"Lanes and placement" is the contract: one unit file per `src/` module, `integration/` for cross-module behaviour, `guards/` for AST invariants (the ≤ 80-line cap was dropped in test-framework 2.15.0; the shrink-only baselines are the bound), `agent/` — outside the default run, ratcheted against a shrink-only baseline, each file declaring `LANE`/`REASON`/`RETIRE_WHEN` — for checks that exist only so an agent does not repeat a recorded mistake. A test that reads prose or builds an artifact is agent-lane by definition.
- **Standing documents only:** `README.md` (front door; the W31-C7 ≤ 150-line target was superseded by the 9a45009 rebuild — it is descriptive per D-37 and pinned by the agent-lane prose tests, not by a line cap), `CONTRIBUTING.md` (working rules), `ROADMAP.md` (direction, decisions index, phase table), a single `TODO.md` (active and planned boards), `CHANGELOG.md` (release notes), `docs/cycles-ended/` (every closed board/phase section and the decision changelog, byte-preserved with a manifest), `docs/adr/` (one file per reasoned decision), `specs/` (current-state contracts), and generated reference under `docs/`. No bespoke document per task; analysis goes to gitignored `internal-docs/`.
- **A guard is not evidence until you have seen it fail.** Plant the drift, watch it go red, restore, watch it go green. Guards that verified the wrong set have shipped here more than once.

---

## 4. Definition of Done (per task)

A task is done when:

1. Acceptance criteria all pass; a behaviour change has a test that failed before it.
2. The card's gate passes, and each commit passed `ruff check`, `ruff format --check`, `mypy src` and
   `pytest --co` (the testing budget in `TODO.md` §"How work runs on this board").
3. After the merge, the integrator's one parallel run of the default suite is green.
4. The card's own spec carries a version bump and a **Status line matching what actually shipped**
   (specs carry no changelog).
5. Committed with a conventional message, privacy-scrubbed.

Once per phase, at its close (and before a release): `bash tests/golden/run.sh verify-all`
byte-identical (or a deliberate CLI change with its diff explained line by line), `uv run pytest
tests/agent`, `scripts/maint/pytest-without-sandbox.sh`, the escape matrix, `bash
scripts/validate-specs.sh`, `uv run python scripts/metrics.py --check`, the generated-docs checks and a
real run.

Two rules that override any of the above when they conflict:

- **Never edit `scripts/metrics.py` or `scripts/validate-specs.sh` counting logic to make numbers agree.** Fix the claim, never the guard.
- **Prove "pre-existing" before claiming it.** Check out the base commit in a clean worktree — a `git stash` does not restore deleted files or a changed environment, so it is not a baseline. In an agent worktree run `uv sync --all-extras` **first**: a missing `anyio` produces three phantom mypy errors in `mcp_client.py` that are not real, and five agents have now reported them as pre-existing failures.

---

## 4.5 Architectural principles (durable — read before any structural change)

> These outlive any single phase; a change that violates one needs an explicit decision entry in
> §6, not a silent exception. The build-vs-wrap history that led to D-19 is archived in
> `docs/cycles-ended/roadmap-phases.md`; its lesson is [ADR 0002](docs/adr/0002-own-the-loop-rent-the-protocols.md).

**Own the loop, rent the protocols (D-19).** docket owns the turn loop, the tool registry, the three
policy hooks, approvals, audit and sessions, because whoever owns the loop owns the interception
points; that is also why agent frameworks that own the loop are rejected. It rents only protocols:
OpenAI-compatible HTTP, MCP, containers and the kernel's sandboxes. One typed `RuntimeDriver` port
with one shipped driver, not a plugin framework; a second driver needs a named trigger.

### Anti-overengineering guardrails (the "we will NOT" list)

| We will NOT | Because |
|---|---|
| Add a DI/IoC framework | Plain constructor/function args suffice at this size |
| Build a plugin system / `AbstractBackend` | One runtime driver (`DocketDriver`) behind one typed port — no speculative generality |
| Use FastAPI/async for `serve` | A handful of routes; stdlib `http.server`, synchronous |
| Add an ORM / database | JSON files modeled by Pydantic *are* the store (the filesystem is the trace/policy store too) |
| Event sourcing / message bus / CQRS | docket-owned JSON through one writer (`platform/store.py`) plus append-only JSONL logs |
| DDD ceremony, deep nesting | One package per business context, at most two levels inside (`domain/`, `application/`, `adapters/` only where the context needs them); a module over 700 lines is a defect (D-66) |
| Abstract before the second caller exists | Rule of three. Make it work, then generalize |

The target is **boring, typed, obvious Python.** "Scale" here is not throughput (single-host CLI) —
it's more *commands*, more *agents*, more *contributors*; the layered contexts + types + tests
address exactly those.

---

## 6. Decisions

Every decision D-1…D-70 is answered; D-1…D-66 are archived. The table, with each question and answer, is archived verbatim
in [docs/cycles-ended/roadmap-decisions.md](docs/cycles-ended/roadmap-decisions.md); from D-35 on,
the reasoning is the ADR in [docs/adr/](docs/adr/) the row names. That file is byte-preserved, so a
new decision gets its ADR and a row in the table below. The decisions that act as standing rules
today:

| Decision | The rule it set |
| --- | --- |
| D-12 | Docket-owned JSON is written only by `platform/store.py`; append-only JSONL is the one exemption |
| D-13 | `git`/`docker` and jailed launches go through `platform/git.py`, `platform/process.py`, `sandbox/launch.py` |
| D-18, D-19 | docket owns the loop and rents protocols; one `RuntimeDriver`, no hand-rolled vendor client ([0002](docs/adr/0002-own-the-loop-rent-the-protocols.md)) |
| D-20, D-22, D-24 | A factory and an embeddable library, not a hosted SaaS; no tenant axis; build only for a measured need ([0003](docs/adr/0003-factory-first-then-embeddable-substrate.md), [0005](docs/adr/0005-prioritization-ruling-viable-vs-overengineering.md)) |
| D-36, D-37 | Tests by lane; the README describes, specs require ([0007](docs/adr/0007-human-maintainability-lanes-comments-docs.md)) |
| D-52 | Work on `develop`; `main` moves only by fast-forward for a release |
| D-57 | Nothing is kept for the past: no alias, shim, notice or migration ([0022](docs/adr/0022-one-cli-surface.md)) |
| D-66 | One package per context, layered, checked by `tests/architecture/` ([0030](docs/adr/0030-organize-by-context-and-refactor-by-tool.md)) |
| D-67 | `docket init` records isolation on where a backend is detected and records nothing, said so, where none is; a recorded choice stands and a recorded `on` fails closed (supersedes D-56 in part) |
| D-68 | A task run under a caller's pipeline file keeps it (`pipelineSpec`). The nested task record and the pod's queue and settings under `workspaces/pods/<pod>/` are dropped for want of a measured need. No migration is written while no user needs one: a consequence, not a principle |
| D-69 | Positioning (2026-10-24): docket complements the governance coding agents ship by governing a team, not a session, and leads with its versatility: roles, pipelines and policies are configuration, so any team is a combination of files. No comparison against another product without a benchmark |
| D-70 | The task is one typed record (2026-10-24): `tasks/domain/task.py::TaskRecord`, flat, camelCase aliases, `extra="ignore"` (a queue written before a retired key still loads; unknown keys are not written back), the same keys on disk, behind `tasks/application/json_store.py` (the layer contract forbids `application` importing `adapters`; the only caller of `read_modify_write` on the queue) and `tasks/application/repository.py` (the pod's door, which also syncs the HEARTBEAT ledger). Readers use attributes; `_normalize_task`, `hop_record` and `hop_from_record` are deleted. No nested record (D-68 stands), no port protocol, no unit of work, no hooks: one implementation each. `claimId` and `source` are deleted outright (nothing read them); `Status.in_progress` likewise. The design and the measured counts are the Phase 49 cards; the architecture test `test_task_queue_writers.py` keeps the store the only writer |

---

## 7. Backlog (deferred indefinitely)

> Each entry is cut or waits for its named trigger; none is queued.

- **New channel auth flows (Discord OAuth, Slack app install)** — docket owns its channels
  (`interfaces/telegram/` is its own approval channel), so this is real work. **Trigger:** an operator who will not use Telegram. One channel that
  audit-logs honestly beats three that half-work.
- **Rewrite in Go/Rust as a single binary** — reserved, not planned. Revisit **only** if
  zero-runtime-deps single-artifact distribution becomes a hard product requirement. Python is the
  destination until then (see `docs/cycles-ended/roadmap-phases.md`, completed initiatives).
- **Multi-tenancy** — **CUT, not deferred** (D-22, reaffirmed by D-24 and by Phase 22). The bet is
  that docket serves *products*, and each product serves its own customers; the substrate is a
  library a product embeds, and the product owns its serving layer. **Trigger if the bet is wrong:**
  docket itself serving more than one end customer from one host. Retrofitting the tenant key is
  expensive — this is a genuine bet, not a free cut.
- **A dashboard of our own** — ruled out: docket competes on the write/governance side and feeds
  one (Tack, through the HTTP API). docket renders nothing.
- **microVM / gVisor workspace isolation** (deferred from Phase 11) — competitors running *untrusted*
  code use Firecracker (E2B/Vercel) or gVisor (Modal); docket's optional Landlock, Seatbelt or Docker jail shares the host
  kernel. **Trigger:** docket targeting untrusted-code execution. Large lift.
- **Multi-host / remote provisioning** (deferred from Phase 11) — manage agents across more than one
  host. The ceiling on the "fleet" claim; defer until single-host value is saturated.
- **A second `RuntimeDriver`** (supersedes the old "cross-runtime adapters" entry) — the port exists
  and is typed (`hops/application/driver.py`), with exactly **one** shipped driver by design. It is a
  port, **not** a plugin framework, and a second driver needs a named trigger — not a hypothetical
  about breadth.

## 7.1 Decisions waiting for the maintainer (2026-10-24)

> Engineering follow-ups with triggers live on `TODO.md` §"FOLLOW-UPS WITH TRIGGERS". These entries
> need a decision, not a trigger.

- **Integrate `plan/phase-46-structure` (Phases 46-47) into `develop` and push.** Until then the
  `no-sandbox` CI job (`scripts/maint/pytest-without-sandbox.sh`) has never run on CI. Asked at the Phase 47 close (2026-10-24).
- **The agent lane's retirements:** whether the PydanticAI and OpenHands adapters (no consumer;
  last changed 2026-09-01) and the adoption benchmark (`docs/ADOPTION-EVIDENCE.md`: fixture data a
  driver writes, no policy hook runs) stay public claims. Recommended: keep `docket-runtime`, delete
  the benchmark and the README link, delete the adapters until a product of ours uses one.
- **The implementer's re-sent context** (a fired trigger on `TODO.md`): its measurement spends
  hosted-model tokens on `fab-dev`, so it needs a go.
- **A release.** `VERSION` is `0.2.0-beta.6`; the last tag is `v0.2.0-beta.4`. Cutting it publishes
  the Phase 43-48 changes (API 6, `exec` deleted, one authored YAML form, isolation by detection).
- **Fabulada's blueprint** (`onboard/tack` in its own repository) still has three canonical-form
  pipelines current docket refuses; the converted versions are in the maintainer's backup. It is
  another repository's branch, so converting it is the maintainer's call.

---

## 8. How to work

**The goal: a factory for agentic products**, in three parts, in order: (1) docket itself; (2) the
embeddable substrate `packages/docket-runtime/`, because the governed runtime is the common part of
every agentic product; (3) the control-plane API an external plan of record (Tack) drives. It does
not buy the hosted-SaaS half (multi-tenancy, external authn, per-customer quota): conflating an
embeddable library with a hosted runtime is the failure D-20 exists to prevent.

**Scheduling by file contention**, four rules each earned by a merge that went badly first:

1. **At most one in-flight card owns a hot file per wave.** The two cards that both edited the
   dispatch call sites produced Phase 14's only dangerous merge.
2. **When a file is hot, state ownership at function level** (or by HTTP method). Phase 19 ran three
   cards against the chokepoint module with zero conflicts that way.
3. **A roll-up table several branches edit cannot be merged by picking a side.** Regenerate it from
   ground truth (spec headers, the real CLI, the suite) and verify the diff.
4. **Resolve an append-only conflict by keeping both sides, then import the module** to assert
   nothing was lost.

Central files (`ROADMAP.md`, `TODO.md`, `README.md` metric counts, `CHANGELOG.md`) are
integrator-owned; a card branch reports what it shipped. **Branch model (D-52):** cards base on and
merge into `develop`; `main` moves only by a fast-forward from `develop` when the maintainer cuts a
release. Specs describe the code, not aspirations.
