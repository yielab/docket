# TODO — active task board

> **This is docket's single standing TODO file.** It holds the executable cards for whatever phase is
> currently active in [ROADMAP.md](ROADMAP.md). Do **not** create per-phase task files — when a phase
> finishes, clear its cards (the phase record stays in ROADMAP) and append the next phase's cards here.
>
> *Phase 10 (Agent architecture / pods, AA-0…AA-9) is **COMPLETE** — its record lives in ROADMAP §5
> (Phase 10) and the Changelog. Its board was cleared per the convention above. The one non-blocking
> follow-up it left (confirm the live `openclaw agent --json` cost schema) is carried forward here as
> **CD-0**.*
>
> ---
>
> ## Active: PHASE 11 — Competitive differentiation (OpenClaw fleet-management space)
>
> Executable board for **PHASE 11** in [ROADMAP.md](ROADMAP.md) (read that section first — market
> context + exit criteria). Full competitor map, **GitHub-verified** star counts, and the per-axis
> gap analysis: `internal-docs/competitive-analysis.md` (**read it before claiming a card**). Each
> task here is **self-contained** so a separate agent can claim and complete it independently.
>
> **What we're doing (one paragraph):** a verified sweep shows the OpenClaw-native space is
> **bifurcated** — monitoring *dashboards* (read side; `builderz-labs/mission-control` ~5.4k★,
> `abhi1693/openclaw-mission-control` ~4.1k★, several `openclaw-dashboard`s) and one-shot *setup
> scripts* (`shenhao-stu/openclaw-agents` ~445★). The only true CLI lifecycle+governance peer is
> `oguzhnatly/fleet` (~13★, Bash, no pods/cost-policy/isolation). The broader field treats three
> things as **unsolved**: runtime-resource isolation between parallel agents, anti-fragile *shared*
> context, and a real HITL/audit spine. docket already owns the second (Lead-owned context + session
> scoping). Phase 11 doubles down on the trio no competitor integrates and closes the two visible
> gaps: **no dashboard-feed API** and **gates are opt-in / Telegram-only**.

## How to use this board (read before claiming a task)

1. **Claim:** set Status → `IN-PROGRESS (@you)`. One agent per task.
2. **Read first (always):** `internal-docs/competitive-analysis.md`, ROADMAP.md §2 (Python ground
   truth), §4.5 (architectural principles — esp. *docket is not in the agent execution path*), the
   Phase 11 section, [CLAUDE.md](CLAUDE.md), and the task's own "Read" list.
3. **Layer rule (non-negotiable):** `cli/ → core/ → edges/`, inward only. OpenClaw formats live **only**
   in `edges/adapters/openclaw.py` (the ACL). docket-owned JSON goes **only** through `edges/store.py`.
   Every shell-out (`git`/`docker`/test runners) goes through `edges/adapters/system.py`.
4. **Honesty rule:** docket does not execute agents — the daemon does. docket *is* in the path for
   **dispatch** (`serve --dispatch` / `pod dispatch`) and for **its own mechanical work** (allocating
   resources, running a local lint/test gate). Never claim docket runs the agent's tool calls or
   executes Lobster workflows; the daemon owns those. Anything daemon-gated is spiked + isolated.
5. **Definition of done (per task):** acceptance criteria pass · a pytest covers it (add a golden case
   if output changes) · `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv
   run pytest` green · `bash tests/golden/run.sh verify-all` green · committed `Type: description` (no
   Claude/Co-Authored-By trailer) · public-repo privacy scrubbed.

**Status legend:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs CD-x)` · `DONE`
**Size:** S ≈ ½ day · M ≈ 1–2 days · L ≈ 3–5 days (split before claiming if L)
**Branch model:** one short-lived `pc/cd-<id>` branch per task → PR into the working branch (`develop`).

---

## Dependency map (what unblocks what)

```text
CD-0  (confirm openclaw agent --json cost schema)   ← cheap; do first; makes CD-1/CD-2 cost-honest
  │
CD-1  (pod runtime-resource isolation)  ── FLAGSHIP ── parallel-safe with CD-0
  │     └─ CD-5 (git-worktree Implementer isolation — composes with CD-1)
CD-2  (deterministic pre-merge verification gate)   ← needs CD-0; composes with dispatch
  │
CD-3  (high-risk action classes)  ─┐
CD-4  (headless approval channel) ─┘  parallel; together they unblock the deferred gates-default-on
  │
CD-6  (scheduled & webhook dispatch)   ┐
CD-7  (Lobster validate + dry-run)     │  independent (serve / workflow surfaces)
CD-8  (stable read API + status surface)┘
  │
CD-9  (positioning / docs truth pass)               ← LAST; needs CD-1..CD-8 landed
```

Order to ship value fastest: **CD-0 → CD-1 → CD-2 → CD-3/CD-4 → CD-6/CD-8 → CD-5/CD-7 → CD-9.**
CD-1 (resource isolation), CD-2 (verify gate), and CD-3+CD-4 (on-by-default governance) are the three
the analysis flags as the highest-leverage, no-competitor-integrates differentiators.

---

### CD-0 — Confirm the live `openclaw agent --json` result schema (carried-forward AA-0 follow-up)
- **Depends on:** — *(do first; cheap)* · **Parallel-safe with:** CD-1
- **Read:** `internal-docs/POD-DAEMON-NOTES.md`, `src/docket/edges/adapters/openclaw.py` (`agent_run`, `AgentRunResult`, the tolerant JSON parse), `src/docket/core/dispatch.py` (`cost_charged` per hop), the AA-7 "Note" in the Phase 10 record.
- **Do:** Capture ≥1 **real** `openclaw agent --agent <id> --session-id <key> -m <text> --json` run against the live daemon in a throwaway agent. Record the actual JSON shape — especially the **cost/usage** field name(s) and units. Tighten `AgentRunResult` + the cost extraction to the real schema while keeping the tolerant fallback for older/newer daemons. Update `POD-DAEMON-NOTES.md` with the captured (redacted) sample + the field mapping.
- **Out of scope:** any new feature; CD-1+ behaviour.
- **Deliverables:** redacted real sample + field-map in `POD-DAEMON-NOTES.md`; edited `agent_run`/`AgentRunResult`; a pytest using the real-shaped canned JSON.
- **Acceptance gate:** [ ] a real run captured against the live daemon; [ ] `AgentRunResult` maps the real cost field (not a guess); [ ] tolerant fallback retained + tested; [ ] suite green.
- **Size:** S · **Status:** DONE

---

### CD-1 — Pod-level runtime-resource isolation (FLAGSHIP differentiator)
- **Depends on:** — · **Parallel-safe with:** CD-0
- **Read:** `src/docket/core/pod.py`, `src/docket/cli/_pod.py` (`_member_soul`/workspace + TOOLS emission), `src/docket/cli/__init__.py` (`cmd_add`, `cmd_pod`, `cmd_delete`), `src/docket/core/models.py` (`AgentMeta` — add local-sync fields), `specs/data/docket-meta.spec.md`, `src/docket/edges/store.py`, `src/docket/edges/adapters/system.py`.
- **Why:** the field's *acknowledged unsolved* problem — worktrees/workspaces isolate **files** but not **runtime** (ports collide; a shared local DB gets corrupted by concurrent migrations; caches/test-state bleed). No inner- or outer-ring competitor integrates this. Pure provisioning, no daemon change.
- **Do:** At pod provisioning, allocate per-pod runtime resources and inject them into the **Implementer**'s workspace:
  1. A **non-overlapping port range** (deterministic from a tracked allocation table, reclaimed on teardown — never collide across live pods).
  2. A **scratch data dir** `~/.openclaw/workspaces/pods/<project>/.scratch/` (0700).
  3. (Document, even if thin) a per-pod **scratch DB/cache namespace** convention (e.g. a `DOCKET_DB_NAMESPACE` suffix).
  Record on pod metadata (new `local` sync-class fields, e.g. `portRangeStart`/`portRangeCount`/`scratchDir`) and surface them to the agent via the Implementer's `TOOLS.md` + env (`DOCKET_PORT_BASE`, `DOCKET_SCRATCH_DIR`, …). `docket pod <project>` shows the allocated resources; `docket delete`/`pod remove` **reclaim** the range + scratch dir.
- **Out of scope:** enforcing that the agent actually binds to its range (we allocate + inject + document); kernel/network-namespace isolation (CD-5 / the microVM backlog item).
- **Deliverables:** meta fields + `docket-meta.spec.md` row; a pure allocator in `core/` (unit-tested for non-overlap + reclaim); TOOLS.md/env injection in `_pod.py`; `pod` listing shows resources; reclaim wired into delete/remove; integration test.
- **Acceptance gate:** [ ] two pods get **disjoint** port ranges + distinct scratch dirs; [ ] the Implementer's TOOLS.md/env exposes them; [ ] `docket pod <p>` shows them; [ ] `docket delete <p>` frees them (re-add reuses the freed range); [ ] suite + golden green.
- **Size:** L · **Status:** DONE

---

### CD-2 — Deterministic pre-merge verification gate (mechanical, not agent-judgment)
- **Depends on:** CD-0 · **Parallel-safe with:** CD-1
- **Read:** `src/docket/core/dispatch.py` (pipeline hops + where a task is marked done), `src/docket/edges/adapters/system.py` (shell-out wrappers), `src/docket/cli/_pod.py` + the project `TOOLS.md` (where a test/lint command lives), `src/docket/core/trace.py` (event types — add a verification event).
- **Why:** Bernstein's "Janitor" gates a merge on lint/type/test; docket's Reviewer/Tester are agent *judgment*. A hard mechanical gate turns "Tester says ok" into "tests actually passed." docket runs locally, so running the gate is legitimate docket-side work (not agent execution).
- **Do:** Add an **opt-in per-pod `verifyCmd`** (meta field, or sourced from the project's `TOOLS.md`). In the dispatch pipeline, **before a task is marked done** (after the Implementer hop), run `verifyCmd` via the system adapter **in the Implementer's workspace**. Non-zero exit ⇒ leave the task `pending`/`failed`, emit a `verification_failed` trace event with **redacted** captured output, and do **not** mark done. `verifyCmd` unset ⇒ skip, but **log that verification was skipped** (no silent pass — honesty rule / "no silent caps").
- **Out of scope:** auto-fixing failures; inferring the command heuristically beyond `TOOLS.md`/the meta field.
- **Deliverables:** `verifyCmd` meta field + spec row; the gate in `dispatch.py`; the new trace event (+ redaction); a system-adapter call; tests for pass→done, fail→pending+trace, unset→skip+log.
- **Acceptance gate:** [ ] a failing `verifyCmd` blocks done and traces it; [ ] a passing one allows done; [ ] unset ⇒ skipped **with a visible log line**; [ ] output is redacted in the trace; [ ] suite green.
- **Size:** M · **Status:** DONE

---

### CD-3 — High-risk action classes (always-approve, regardless of allowlist)
- **Depends on:** — · **Parallel-safe with:** CD-4
- **Read:** `src/docket/core/policy.py` (policy schema + most-restrictive-wins evaluator, OBS-5/6), `src/docket/cli/_policies.py` (`policies list/show/test`), `src/docket/core/security.py` (exec allowlist), the policy specs.
- **Why:** Galileo's governance guidance is explicit — *dual/human approval for actions touching money, medical/sensitive data, or production code*. docket's approval is currently uniform; there's no "this class always needs a human" concept.
- **Do:** Add a **`high-risk` policy class** matching configurable categories — money/payment, production-deploy, secret/credential access — that **always routes to approval even if the command's bin is on the exec allowlist** (most-restrictive-wins already supports this). Ship sensible baseline patterns; `docket policies show` surfaces them; `docket policies test <hook> <role> "<text>"` demonstrates them.
- **Out of scope:** the approval *channel* (CD-4); ML/semantic classification (regex/category match in v1).
- **Deliverables:** baseline `high-risk` policy + any schema support; `docket policies` surfacing; tests — incl. an **allowlisted** bin that still gets gated when it matches a high-risk pattern.
- **Acceptance gate:** [ ] a high-risk-matching action requires approval even though its bin is allowlisted; [ ] `docket policies test` shows the gate firing; [ ] baseline patterns documented; [ ] suite green.
- **Size:** M · **Status:** DONE

---

### CD-4 — Headless approval channel (unblock gates-on-by-default)
- **Depends on:** — *(composes with CD-3)* · **Parallel-safe with:** CD-3
- **Read:** `src/docket/core/approval.py` (durable store, grant/deny, fail-closed sweep — OBS-9/10), `src/docket/cli/_approve.py` + `_deny.py`, `src/docket/serve.py` (HTTP endpoints), `src/docket/core/trace.py` (approval events).
- **Why:** gates can't be recommended **on-by-default** while **Telegram is the only production approval channel** (memory: this is the long-deferred "Phase 0 gates default-on" blocker). Give operators a headless path.
- **Do:** Add a **headless approval channel** beyond Telegram via `serve`: `GET /approvals` (list pending, redacted) and `POST /approvals/<token>` (grant/deny), **token-guarded** and local-bind by default; keep `docket approve/deny <token>` as the CLI channel and document it as the headless default. Preserve **fail-closed** semantics (the expiry sweep still runs). Document the security model (local bind + token; never expose unauthenticated).
- **Out of scope:** a full web UI (CD-8 / backlog); auth beyond a local token; **flipping the gates default** (this card only *removes the blocker* — the default-on flip is a separate, later decision).
- **Deliverables:** `serve` approval endpoints (read + act) + token guard; docs of the security model; tests for grant/deny via the endpoint, unauthorized rejection, and expiry-still-fires.
- **Acceptance gate:** [ ] a pending approval can be listed + granted/denied **without Telegram**; [ ] an unauthorized request is rejected; [ ] expiry still fail-closes; [ ] suite green. *(Note in the PR: this satisfies the prerequisite for the deferred gates-default-on flip; do not flip it here.)*
- **Size:** M · **Status:** DONE

---

### CD-5 — Git-worktree-native Implementer isolation (the convergent industry pattern)
- **Depends on:** CD-1 (composes), CD-0 · **Parallel-safe with:** CD-6/CD-7
- **Read:** `src/docket/cli/__init__.py` (`cmd_add`/`_create_workspace` — codebase path), `src/docket/cli/_pod.py` (Implementer workspace), `src/docket/edges/adapters/system.py` (git wrappers), `src/docket/core/pod.py`, AA-0's `internal-docs/POD-DAEMON-NOTES.md` (workspace is per-agent).
- **Why:** the verified field convergence — *"every tool here converges on git worktrees"* (Cursor, Codex, Terra). docket uses flat workspace dirs; for **repo** pods this is off the dominant code-isolation pattern. Composes with CD-1's runtime-resource isolation.
- **Do:** For **repo** pods (codebase present), provision the Implementer's working tree as a `git worktree add` off the project repo (a branch per pod/task) instead of a flat dir, via the system adapter. Wire teardown (`git worktree remove`) into `pod remove`/`delete`. **Validate** that the daemon runs the agent against the worktree path (workspace is already per-agent per AA-0); if it can't target a worktree cleanly, **record the limitation and fall back** to the current workspace dir (honesty rule). Record the worktree path on pod meta.
- **Out of scope:** task pods (no codebase); merge/PR automation; multi-worktree-per-pod.
- **Deliverables:** worktree provisioning/teardown via the system adapter; a meta field for the worktree path; tests against a temp git repo; a **documented + tested fallback** if the daemon can't target the worktree.
- **Acceptance gate:** [ ] a repo pod's Implementer works in a dedicated worktree/branch; [ ] teardown removes it; [ ] non-repo (task) pods are unaffected; [ ] the daemon-incompatible fallback is documented + tested; [ ] suite green.
- **Size:** L · **Status:** TODO

---

### CD-6 — Scheduled & webhook-triggered dispatch (event-driven control plane)
- **Depends on:** CD-0 *(dispatch already exists — AA-7)* · **Parallel-safe with:** CD-7/CD-8
- **Read:** `src/docket/serve.py` (HTTP loop, `--dispatch`, interval), `src/docket/core/dispatch.py`, `src/docket/cli/__init__.py` (serve wiring), `src/docket/core/trace.py`.
- **Why:** OpenHands' Automation Server runs agents **on a schedule or in response to webhook events**; docket's `serve --dispatch` is interval-polling only. This turns the poller into an event-driven control plane.
- **Do:** Extend `serve` with (a) **schedule**: cron-like spec(s) (global or per-pod) that trigger a pod's dispatch at given times, not just on the poll interval; (b) **webhook**: a token-guarded `POST /dispatch/<project>` that triggers a pod's dispatch on an external event. Stay on stdlib `http.server`. Trace each triggered run (reuse Phase-8 events).
- **Out of scope:** *outbound* integrations (Slack/GitHub/Linear apps — backlog); distributed/clustered scheduling.
- **Deliverables:** schedule parsing + a tick in the serve loop; the webhook endpoint + token guard; tests — a scheduled time fires a dispatch; a webhook POST triggers one; unauthorized rejected.
- **Acceptance gate:** [ ] a scheduled time triggers a pod dispatch; [ ] a webhook POST triggers it; [ ] unauthorized rejected; [ ] suite green.
- **Size:** M · **Status:** DONE

---

### CD-7 — Lobster workflow `validate` + `dry-run`/`plan`
- **Depends on:** — · **Parallel-safe with:** CD-6/CD-8
- **Read:** `src/docket/cli/__init__.py` (`cmd_workflow` — list/create/show/delete), the Lobster YAML in `src/docket/templates/`, `src/docket/core/` (add a validator).
- **Why:** docket's Lobster workflows are **read-only** to docket (the daemon executes them); Conductor *authors + validates* YAML pipelines. A validate + dry-run narrows the UX gap without overclaiming execution.
- **Do:** Add `docket workflow <id> validate <name>` (schema/lint the Lobster YAML — structural + referenced-role/step checks) and `docket workflow <id> plan <name>` (render the **resolved** pipeline docket *would* hand the daemon, **without executing**). Output must **state explicitly** that docket does not execute the workflow — the daemon does (honesty rule).
- **Out of scope:** executing/running workflows (daemon owns it); editing them beyond create.
- **Deliverables:** a pure Lobster-YAML validator in `core/` (unit-tested, valid + invalid); the `validate`/`plan` subcommands; a golden for `plan` output; tests.
- **Acceptance gate:** [ ] invalid Lobster YAML is rejected with a clear, located error; [ ] `plan` prints the resolved steps **and** states docket doesn't run them; [ ] suite + golden green.
- **Size:** M · **Status:** TODO

---

### CD-8 — Stable read API + minimal status surface (feed the dashboards, don't out-UI them)
- **Depends on:** — · **Parallel-safe with:** CD-6/CD-7
- **Read:** `src/docket/serve.py` (`/status.json`, `/metrics`, `/health`), `src/docket/core/trace.py` + `src/docket/cli/_metrics.py` (metrics), `src/docket/cli/__init__.py` (`snapshot`), `specs/data/`.
- **Why:** the market visibly wants **visibility** (two 4–5k★ mission-control UIs + several dashboards). docket has no dashboard. The strategic call (see analysis): **don't build a worse dashboard — expose a stable read API a dashboard can consume**, positioning docket as the governed control plane *behind* the UI.
- **Do:** Harden `serve` into a **documented, versioned, read-only API**: solidify `/status.json` (pods, members, scope, model, budget, health), `/metrics` (success rate, latency, cost, guardrail trips), `/health`; version the contract and pin it in a new `specs/data/serve-read-api.spec.md`. **Optionally** ship a **single static HTML** page (no build step, à la `anis-marrouchi/openclaw-dashboard`) that renders the read API — explicitly framed as "feeds dashboards", not "is a dashboard". Strictly read-only (mutation stays in the CLI / CD-4).
- **Out of scope:** a full SPA; write endpoints; auth beyond local bind (the read API is local-bind by default).
- **Deliverables:** stabilized + versioned endpoints; `specs/data/serve-read-api.spec.md`; optional single-file HTML; tests pinning the JSON contract shape.
- **Acceptance gate:** [ ] `/status.json` + `/metrics` emit a **documented, versioned** shape; [ ] the contract spec exists and a test pins it; [ ] (optional) the static page renders from the API; [ ] suite green.
- **Size:** M · **Status:** TODO

---

### CD-9 — Positioning / docs truth pass (lead with the verified differentiators)
- **Depends on:** CD-1..CD-8 landed · **Do last**
- **Read:** `README.md`, `CLAUDE.md`, `docs/*`, `internal-docs/competitive-analysis.md`, the `product-positioning` memory.
- **Why:** the analysis says docket should **stop competing on cost** and lead with the trio the field treats as unsolved. The docs must reflect what shipped in CD-1..CD-8 and the honest contrast vs the competitor rings.
- **Do:** Rewrite the positioning to lead with: **coordinated Lead-owned context** (anti-fragility vs Cognition's "Don't Build Multi-Agents"), **project + runtime-resource isolation** (CD-1/CD-5), and the **governance/HITL/audit spine** (CD-2/CD-3/CD-4). Add explicit contrast lines: *"an ops/control plane, not an agent framework (vs CrewAI/LangGraph/AutoGen)"* and *"a governed multi-project fleet, not a solo personal assistant (vs raw openclaw)"*. Frame docket as the **write-side control plane that feeds dashboards** (CD-8), not a dashboard. Keep the **no-dollar-savings** discipline and name it as a **trust** stance vs marketing-grade rivals. No unfalsifiable claims.
- **Out of scope:** new feature docs beyond what CD-1..CD-8 shipped.
- **Deliverables:** edited `README`/`CLAUDE.md`/`docs/*`; a docs grep-audit test (no "savings"/dollar claims; the differentiator + contrast lines present).
- **Acceptance gate:** [ ] docs lead with coordinated-context + isolation + governance; [ ] the framework-vs and solo-assistant-vs contrast lines are present; [ ] no dollar-savings claims (grep test); [ ] suite green.
- **Size:** M · **Status:** TODO

---

## Roll-up checklist (Phase 11 definition of done)
- [ ] CD-0 — live `openclaw agent --json` cost schema confirmed; `agent_run` parsing tightened.
- [ ] CD-1 — a pod gets isolated runtime resources (disjoint port range + scratch dir), reclaimed on delete.
- [ ] CD-2 — a pod task cannot be marked done unless a mechanical verification gate passes (or is explicitly, visibly skipped).
- [ ] CD-3 + CD-4 — high-risk actions always require approval, and there is ≥1 **headless** approval channel (gates-default-on is unblocked).
- [ ] CD-5 — repo pods isolate the Implementer in a git worktree (or a documented fallback).
- [ ] CD-6 — `serve` can be triggered on a schedule and via webhook.
- [ ] CD-7 — Lobster workflows can be validated + dry-run/planned (without overclaiming execution).
- [ ] CD-8 — `serve` exposes a documented, versioned read API a dashboard can consume.
- [ ] CD-9 — public docs lead with the verified differentiators and make no unfalsifiable claims.
- [ ] Full suite green: ruff + mypy + pytest + goldens.

**Deferred to §7 Backlog (explicitly out of Phase 11):** docket's own full web UI; microVM/gVisor
isolation; multi-host/remote provisioning; cross-runtime (non-OpenClaw) adapters.
