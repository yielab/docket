# User Stories and Acceptance Criteria

**Version**: 1.4.1
**Status**: Active
**Last Updated**: 2026-09-19

## Overview

This document defines user stories following the format:
```
As a [role]
I want [feature]
So that [benefit]
```

Each story includes acceptance criteria that must be met for the story to be considered complete.

## Stories

The stories below are grouped into epics. Each has a stable ID used to cross-reference
acceptance criteria and tests.

| ID | Story | Epic |
|----|-------|------|
| AGT-001 | Create Project Agent | Agent Management |
| AGT-002 | Reset Agent Memory | Agent Management |
| AGT-003 | Monitor Agent Costs | Agent Management |
| POD-001 | Provision a Project Pod | Pod Lifecycle |
| POD-002 | Run the Pod Dispatch Pipeline | Pod Lifecycle |
| POD-003 | Grow and Shrink a Pod | Pod Lifecycle |
| TEAM-001 | (retired, see D-11) | Team Coordination (retired) |
| TEAM-002 | (retired, see D-11) | Team Coordination (retired) |
| WF-001 | (retired, see D-16) | Workflow Automation (retired) |
| WF-002 | (retired, see D-16) | Workflow Automation (retired) |
| SEC-001 | Project Isolation | Security and Isolation |
| SEC-002 | Tool Approval Gates | Security and Isolation |
| COM-001 | Telegram Integration | Communication |
| MON-001 | Health Monitoring | Monitoring and Maintenance |
| MON-002 | System Diagnostics | Monitoring and Maintenance |

The full story definitions (As a / I want / So that) follow, organized by epic.

## Criteria

Every story carries two checklists:

- **Acceptance Criteria** — observable conditions that MUST hold for the story to be
  accepted. Written as checkboxes so coverage is visible at a glance.
- **Definition of Done** — the engineering bar (tests, docs, error handling) that MUST
  be satisfied before the story is closed.

Criteria SHOULD be phrased so each line maps to at least one test. No script tracks
story-to-test coverage: a criterion without a backing test is simply left unchecked here.
(`scripts/validate-specs.sh` checks each spec's required sections, not story coverage.)

## Epic: Agent Management

### Story: AGT-001 - Create Project Agent

**As a** developer
**I want** to create a new project agent with a single command
**So that** I can quickly start AI-assisted development on my project

**Acceptance Criteria:**
- [ ] Agent is created with unique ID in under 2 seconds
- [ ] Workspace directory is created with correct permissions (700/600)
- [ ] Stack is auto-detected from project files
- [ ] The role→model policy assigns the agent's model (visible in `docket list`)
- [ ] Agent appears in `docket list` immediately after creation
- [ ] Session key is generated for project isolation
- [ ] Creation fails gracefully if agent ID already exists
- [ ] User receives clear success confirmation with workspace path

**Definition of Done:**
- Unit tests pass for agent creation
- Integration test creates and verifies agent
- Documentation updated with examples
- Error cases handled with helpful messages

### Story: AGT-002 - Reset Agent Memory

**As a** developer
**I want** to clear my agent's memory at the right depth
**So that** I can clear context when switching tasks or fixing issues

The numbered reset levels were retired. The surface is `docket maintain <id> <mode>`.

**Acceptance Criteria:**
- [ ] `clean` clears only the daily memory logs (`memory/*.md`)
- [ ] `reset` clears memory logs, MEMORY.md, and HEARTBEAT.md
- [ ] `rebuild` regenerates SOUL.md, AGENTS.md, and TOOLS.md from `.docket-meta.json`
- [ ] `clean` and `reset` distill pending logs into MEMORY.md first (one driver-backed turn) and
      archive the originals; `--no-distill-first` opts out
- [ ] A failed distillation aborts the delete: nothing is touched
- [ ] `clean`, `reset`, and `rebuild` ask for confirmation and need a TTY; a non-interactive
      call is cancelled, not applied
- [ ] Every mode preserves identity (`.docket-meta.json`, including codebase path and session
      key, and fleet registration)

**Definition of Done:**
- Each maintain mode tested, including the distill-first abort path
- User documentation lists the modes (`docket maintain --help`, docs/commands.md)

### Story: AGT-003 - Monitor Agent Costs

**As a** project manager
**I want** to track token usage and costs per agent
**So that** I can manage AI spend effectively

**Acceptance Criteria:**
- [ ] Cost command shows tokens used (input/output/cache)
- [ ] `Total cost` reads "none recorded for these sessions": `DocketDriver` records no dollar
      spend, and `docket cost` never substitutes an estimate for it
- [ ] The token × pricing estimate appears only in the pod-dispatch budget gate, always labelled
      `(estimated — no cost recorded)`
- [ ] `--history [--days N]` returns an empty history (known gap: sessions store no per-turn
      timestamps; cost-tracking.spec.md)
- [ ] Aggregates across all agents when no id is given
- [ ] `--json` output available for scripting (cli-json-shapes.spec.md)
- [ ] Budget warnings render at ≥80% and ≥100% of a configured cap (computed from recorded
      spend, which is always 0 today, so they do not trip in production)

**Definition of Done:**
- Token totals match Docket's durable session records exactly
- Budget warning thresholds implemented (display; enforcement per cost-tracking.spec.md)

## Epic: Team Coordination (Retired, D-11 / CH-4)

`docket team` — the org-wide manual task queue this epic originally described — was retired in
0.2.0. It was never dispatched (no code ever executed a queued task), and several of its
original acceptance criteria (load balancing, a monitoring dashboard, 100+ concurrent tasks)
were never implemented either — they were aspirational when written. Real, working delegation
with actual execution lives in **Epic: Pod Lifecycle (Phase 10)** below, specifically
**Story: POD-002 - Run the Pod Dispatch Pipeline**, which supersedes this epic entirely.
Running `docket team <anything>` prints a removed-command notice mapping to the pod
equivalent. The retired TEAM-001/TEAM-002 story bodies were removed in v1.2.0 — git history
retains them; the durable retirement record is ROADMAP decision D-11.

## Epic: Workflow Automation (Retired, D-16 / W-3)

`docket workflow` — the Lobster YAML surface this epic originally described — was retired in
Phase 16 (D-16). Its acceptance criteria were largely aspirational when written: docket's
Lobster validator/planner authored, linted, and dry-ran a `.lobster.yml` template, but never
executed one (conditional branching, calling other workflows, retries, and progress/token
tracking were never implemented — a separate "Lobster daemon" was always meant to run the
YAML, and it never existed). The single pipeline dialect docket actually executes lives in
`pipeline-format.spec.md` (ROADMAP Phase 16 W-1) and its executor (W-2, shipped); running
`docket workflow <anything>` prints a removed-command notice pointing at the `docket pipeline
validate`/`plan`/`run` names. The retired WF-001/WF-002 story bodies were removed when this
epic was retired — git history retains them; the durable retirement record is ROADMAP decision
D-16.

## Epic: Security and Isolation

### Story: SEC-001 - Project Isolation

**As a** developer
**I want** agents to be isolated by project
**So that** sensitive data doesn't leak between projects

**Acceptance Criteria:**
- [ ] Each agent has unique session key
- [ ] Session keys include project identifier
- [ ] Agents cannot access other agents' workspaces
- [ ] Memory is segregated by session
- [ ] API keys scoped per project if needed
- [ ] Cross-project references blocked
- [ ] Audit log tracks access attempts
- [ ] Isolation validated by security tests

**Definition of Done:**
- Penetration testing completed (not scheduled — no ROADMAP card)
- No data leakage detected (not scheduled — depends on the penetration testing above)
- Performance impact < 5% (not scheduled — no ROADMAP card, no perf-measurement harness)
- Security documentation updated

### Story: SEC-002 - Tool Approval Gates

**As a** security admin
**I want** to control which tools agents can use
**So that** dangerous operations require approval

**Acceptance Criteria:**
- [ ] Default gates for rm, git push, docker stop
- [ ] Telegram approval workflow implemented (`/approve`, `/deny`; inbound only)
- [ ] Timeout for pending approvals (5 minutes)
- [ ] Audit log of all approvals/denials
- [ ] Emergency override with logging
- [ ] Configurable per agent type
- [ ] Batch approval for similar operations
- [ ] Clear indication when approval needed

**Definition of Done:**
- Approval flow tested end-to-end
- Telegram integration reliable
- Audit log tamper-evident (hash-chained, checked by `docket audit verify`; erasure is made
  visible, not prevented)
- Documentation includes security guide

## Epic: Communication

### Story: COM-001 - Telegram Integration

**As a** developer
**I want** to interact with agents via Telegram
**So that** I can manage agents from mobile devices

**Acceptance Criteria:**
- [ ] Agent can be wired to Telegram group
- [ ] Commands accepted via messages
- [ ] Responses formatted for mobile
- [ ] File uploads/downloads supported (not scheduled — no ROADMAP card; the channel accepts
      only its four verbs, none of which transfers a file)
- [ ] Pending approvals discovered by sending `/status` (the channel is inbound-only by
      design and never messages a chat first — telegram-integration.spec.md requirement 7)
- [ ] Multiple agents per group supported
- [ ] Secure token authentication

**Definition of Done:**
- Telegram bot fully functional
- Message handling reliable
- Mobile UI/UX optimized (not scheduled — no ROADMAP card; there is no UI beyond the four verbs)
- Security validated

## Epic: Monitoring and Maintenance

### Story: MON-001 - Health Monitoring

**As a** operations engineer
**I want** automatic health monitoring of agents
**So that** issues are detected and fixed proactively

**Acceptance Criteria:**
- [ ] Heartbeat checked every 5 minutes
- [ ] Memory usage monitored
- [ ] Stale sessions detected
- [ ] Workspace corruption identified
- [ ] Automatic repair attempted (not scheduled — no ROADMAP card; `docket maintain check`
      offers to regenerate missing files, but only with an interactive TTY confirmation, never
      unattended)
- [ ] Alerts sent for critical issues (not scheduled — no ROADMAP card, no alerting surface)
- [ ] Health metrics dashboard available (not scheduled — no ROADMAP card, no dashboard)
- [ ] Historical health data retained (not scheduled — no ROADMAP card)

**Definition of Done:**
- Monitoring runs continuously (not scheduled — no ROADMAP card, no continuous-monitoring daemon)
- Self-healing successful 80%+ (not scheduled — no ROADMAP card, nothing measures this)
- Alert fatigue minimized (not scheduled — no ROADMAP card, no alerting surface)
- Dashboard provides actionable insights (not scheduled — no ROADMAP card, no dashboard)

### Story: MON-002 - System Diagnostics

**As a** developer
**I want** comprehensive system diagnostics
**So that** I can quickly identify and fix issues

**Acceptance Criteria:**
- [ ] Validate the Docket-owned state root and fleet registry
- [ ] Verify all dependencies present
- [ ] Validate configuration files
- [ ] Test workspace permissions
- [ ] Verify agent registrations
- [ ] Network connectivity tested
- [ ] Resource usage reported
- [ ] Remediation steps suggested

**Definition of Done:**
- Diagnostics complete in < 10 seconds
- All common issues detected
- Fix suggestions accurate
- Can run in verbose mode

## Scenarios

### Scenario: Complete Agent Lifecycle

```gherkin
Given a clean docket installation
When I run "docket init testapp ~/projects/app"
Then the pod should be created successfully with members testapp-lead and testapp-implementer
And workspaces should exist at ~/.docket/workspaces/projects/testapp-lead/ and testapp-implementer/

When I run "docket info testapp-lead"
Then I should see the agent details
And the session key should be "agent:testapp:default"

When I run "docket maintain testapp-lead clean" in a terminal and confirm
Then pending memory logs should be distilled into MEMORY.md and archived
And the daily memory logs should be cleared
But SOUL.md should remain unchanged

When I run "docket delete testapp"
And I confirm the deletion
Then the workspaces for all pod members should be removed
And no testapp-* agents should appear in "docket list"
```

### Scenario: Cost Tracking

```gherkin
Given an agent "webapp-implementer" exists
And the agent has processed 50000 input tokens
And the agent has generated 25000 output tokens
And the agent runs on anthropic/claude-sonnet-4-6 (role policy: programmer → strong class)

When I run "docket cost webapp-implementer"
Then I should see:
  | Metric        | Value          |
  | Input Tokens  | 50,000         |
  | Output Tokens | 25,000         |
  | Total cost    | none recorded for these sessions |

And no dollar figure, recorded or estimated, should be printed as the total
```

## Epic: Pod Lifecycle (Phase 10)

### Story: POD-001 - Provision a Project Pod

**As a** developer
**I want** to create an isolated pod for my project with `docket init <project>`
**So that** each project gets its own Lead + Implementer with no shared state

**Acceptance Criteria:**
- [ ] `docket init myapp ~/code/myapp` creates `myapp-lead` and `myapp-implementer`
- [ ] Each member gets an isolated workspace at `~/.docket/workspaces/projects/<member-id>/`
- [ ] All members share the pod's session key `agent:myapp:default`
- [ ] `docket pod myapp` lists the pod members with their roles
- [ ] `docket init myapp ~/code/myapp --pod full` also creates `myapp-reviewer` and `myapp-tester`
- [ ] A second `docket init myapp` fails with "A project or pod 'myapp' already exists." (exit 1)
      and does not touch the existing members
- [ ] `docket delete myapp` removes all pod members and their workspaces

**Definition of Done:**
- Pod provisioning covered by pytest and golden-parity tests
- `docket pod <project>` correctly lists all members after creation
- Deletion tears down all members atomically

### Story: POD-002 - Run the Pod Dispatch Pipeline

**As a** developer
**I want** to queue a task and dispatch it through the pod pipeline
**So that** the Lead, Implementer, and optional Reviewer/Tester execute in sequence

**Acceptance Criteria:**
- [ ] `docket pod myapp delegate "<task>"` queues a task on the Lead's TASK_LIST.json
- [ ] `docket pod myapp queue` shows the task with status `pending` and `—` in the COST column
      (no cost is recorded)
- [ ] `docket pod myapp dispatch` runs Lead → Implementer → (Reviewer) → (Tester), one real LLM turn per hop
- [ ] A Reviewer REQUEST-CHANGES sends the task back to the Implementer for one rework cycle by
      default; a Tester FAIL is terminal
- [ ] Each hop is budget-gated against the Lead's `budgetUsd` (using the labelled estimate, since
      recorded spend is always 0). Over the cap, the task is set to `blocked` (never rewritten to
      `pending`) and the Lead is paused. The task re-enters the queue only via
      `docket profile <lead-id> --resume`, `docket profile <lead-id> --budget <USD>`, or
      `docket pod <project> queue --retry <task-id>`
- [ ] Each hop emits a trace event visible in `docket trace tail myapp`
- [ ] After completion, `docket pod myapp queue` shows the task as `done` (COST stays `—`)

**Definition of Done:**
- Dispatch pipeline covered by live-path tests with a deterministic `ChatBackend`
- Budget-gating tested (over-budget task is set to `blocked`, never rewritten to `pending`)
- Trace events verified per-hop

### Story: POD-003 - Grow and Shrink a Pod

**As a** developer
**I want** to add or remove roles from an existing pod
**So that** I can add a review gate when work becomes higher-stakes without reprovisioning

**Acceptance Criteria:**
- [ ] `docket pod myapp add reviewer` adds `myapp-reviewer` to an existing pod
- [ ] `docket pod myapp add implementer --count 2` adds `myapp-implementer-2` and `myapp-implementer-3`
- [ ] `docket pod myapp remove myapp-reviewer` removes that member and its workspace
- [ ] A second `docket pod myapp add reviewer` adds `myapp-reviewer-2`, since duplicated roles
      get indexed ids
- [ ] `docket pod myapp add lead` is rejected — a pod may have only one Lead
- [ ] `docket pod myapp` always reflects the current state after add/remove

**Definition of Done:**
- Add/remove covered by pytest suite
- Singleton-Lead constraint tested
- `docket pod` output verified after each operation

## Metrics

**Not scheduled.** No ROADMAP card tracks any metric below and docket has no metrics-collection
or reporting surface that would compute a success rate, a satisfaction score, or a response-time
percentile. Retained as the illustrative target these stories were written against, not as
in-progress work, per specs/README.md's prime rule (an aspirational requirement must name the
card that will make it true — none exists for these).

### Quantitative Metrics
- Agent creation success rate > 99%
- Reset operations complete in < 3 seconds
- Cost tracking accuracy within 1%
- Workflow execution success rate > 95%
- Security gate response time < 5 seconds
- Health check detection rate > 90%

### Qualitative Metrics
- User satisfaction score > 4.5/5
- Setup time reduced by 80%
- Support tickets reduced by 60%
- Developer productivity increased by 40%

## Changelog

### Version 1.4.1 (2026-09-19)
- Doc-truth pass against the shipped CLI, no behavior change:
  - Dropped the nonexistent `spec-coverage.sh`.
  - Rewrote AGT-002 from the retired numbered reset levels to `docket maintain`
    `clean`/`reset`/`rebuild`, with distill-first and abort-on-failed-distill.
  - AGT-003 and the cost scenario now match `docket cost`: no recorded dollars, the estimate
    only in the dispatch gate, `--history` always empty. The nonexistent "incremental cost
    index" is gone.
  - Scenarios and POD-001 use `docket init`, not `docket add`, which no longer creates projects.
    A repeat `init` errors instead of being idempotent.
  - POD-002: the queue shows `—` for cost, the budget gate uses the labelled estimate,
    `--budget` also unblocks, and the rework/terminal verdict rules are stated.
  - POD-003: a duplicate Reviewer is indexed, not rejected.
  - Replaced COM-001's proactive-push and button criteria, and SEC-002's "tamper-proof", with
    the inbound-only and tamper-evident contracts.

### Version 1.4.0 (2026-08-19)
- W21-C1 daemon-free truth pass: replaced the retired daemon's status/path/cost language with
  Docket's owned state root, fleet registry, durable session usage, and live `ChatBackend` path.
  No acceptance behavior changed; the stories now describe the implementation that already ships.

### Version 1.3.0 (2026-07-30)
- ROADMAP Phase 16 W-3 (D-16): `docket workflow`/Lobster was retired — removed the retired
  WF-001/WF-002 historical story bodies (banner + pointer to pipeline-format.spec.md remain;
  git history retains the text), following the same treatment TEAM-001/TEAM-002 got in v1.2.0.

### Version 1.2.0 (2026-07-30)
- Truth pass (Platformization baseline): fixed the header version (was 1.0.0 while the
  changelog said 1.1.0); removed the retired TEAM-001/TEAM-002 historical story bodies
  (banner + pointer to POD-002 remain; git history retains the text); replaced AGT-003's
  fictional cost criteria (CSV export, per-tier breakdown, 90-day retention — none exist)
  with the real `docket cost` surface; removed the remaining model-tier phrasing from
  AGT-001.

### Version 1.1.0 (2026-06-26)
- Updated TEAM-001 to reflect pod model: Manager is an org specialist, not a router to programmer/reviewer/tester
- Fixed Gherkin lifecycle scenario: `docket reset testapp 1` → `docket maintain testapp-lead clean`; creation now shows pod members
- Fixed cost scenario: recorded spend and the separately labelled budget estimate now have
  distinct provenance.
- Added POD-001 (provision pod), POD-002 (dispatch pipeline), POD-003 (grow/shrink pod) for Phase 10 coverage
- Updated story index table and "Last Updated" date

### Version 1.0.0 (2024-01-20)
- Initial user stories defined
- Acceptance criteria established
- Success metrics defined
- Test scenarios created
