# User Stories and Acceptance Criteria

**Version**: 1.0.0
**Status**: Active
**Last Updated**: 2026-06-26

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
| TEAM-001 | Initialize Org Manager | Team Coordination |
| TEAM-002 | Delegate Tasks | Team Coordination |
| WF-001 | Create Lobster Pipeline | Workflow Automation |
| WF-002 | Execute Workflow | Workflow Automation |
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

Criteria SHOULD be phrased so each line maps to at least one test. Stories whose criteria
are not yet test-backed are tracked as gaps in `spec-coverage.sh`.

## Epic: Agent Management

### Story: AGT-001 - Create Project Agent

**As a** developer
**I want** to create a new project agent with a single command
**So that** I can quickly start AI-assisted development on my project

**Acceptance Criteria:**
- [ ] Agent is created with unique ID in under 2 seconds
- [ ] Workspace directory is created with correct permissions (700/600)
- [ ] Stack is auto-detected from project files
- [ ] Appropriate model tier is suggested based on project size
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
**I want** to reset my agent's memory at different levels
**So that** I can clear context when switching tasks or fixing issues

**Acceptance Criteria:**
- [ ] Level 1 reset clears only daily logs
- [ ] Level 2 reset also clears MEMORY.md and HEARTBEAT.md
- [ ] Level 3 reset regenerates all configuration files
- [ ] User is warned before destructive resets (level 2/3)
- [ ] Reset preserves codebase path and type
- [ ] Session key is regenerated only at level 3
- [ ] Operation completes in under 3 seconds
- [ ] Confirmation shows what was reset

**Definition of Done:**
- All three reset levels tested
- Rollback possible if reset fails
- Performance meets criteria
- User documentation includes reset level guide

### Story: AGT-003 - Monitor Agent Costs

**As a** project manager
**I want** to track token usage and costs per agent
**So that** I can manage AI spend effectively

**Acceptance Criteria:**
- [ ] Cost command shows tokens used (input/output)
- [ ] Costs calculated using current model pricing
- [ ] Can filter by time period (days)
- [ ] Can aggregate across all agents
- [ ] CSV export available for reporting
- [ ] Costs broken down by model tier
- [ ] Historical data preserved for 90 days
- [ ] Real-time updates after each session

**Definition of Done:**
- Cost tracking accurate to 0.01 USD
- Performance handles 1000+ sessions
- Export formats validated
- Budget alert thresholds implemented

## Epic: Team Coordination (Retired, D-11 / CH-4)

`docket team` — the org-wide manual task queue this epic originally described — was retired in
0.2.0. It was never dispatched (no code ever executed a queued task), and several of its
`TEAM-002` acceptance criteria below (load balancing, a monitoring dashboard, 100+ concurrent
tasks) were never implemented under `team` either — they were aspirational when written. Real,
working delegation with actual execution now lives in **Epic: Pod Lifecycle (Phase 10)** below,
specifically **Story: POD-002 - Run the Pod Dispatch Pipeline**, which supersedes both stories
here. Running `docket team <anything>` now prints a removed-command notice mapping to the pod
equivalent. The original stories are kept below for historical reference only.

### Story: TEAM-001 - Initialize Org Manager (historical)

**As a** team lead
**I want** to run `docket install` to create the shared org Manager specialist
**So that** cross-cutting coordination tasks have a dedicated, shared agent

**Acceptance Criteria:**
- [ ] Manager agent created at `~/.openclaw/workspaces/manager/` with org-specialist template
- [ ] Task queue (TASK_LIST.json) initialized in the manager's workspace
- [ ] Manager cannot directly edit code files (delegation mode only)
- [ ] `docket team delegate "<task>"` queues work on the Manager's queue
- [ ] `docket team queue` shows pending tasks with state and priority
- [ ] Tasks have states: pending, in-progress, complete, cancelled
- [ ] Manager is distinct from per-pod Leads — it handles cross-pod coordination only
- [ ] Manager runs on the cheap model class (role policy: `manager`)

**Definition of Done:**
- Manager agent created and registered by `docket install`
- Task state machine implemented via `docket team` subcommands
- Pod Leads confirmed as the per-project orchestrators (not the Manager)
- Team workflow documented in AGENT-TEAMS.md

### Story: TEAM-002 - Delegate Tasks (historical, never fully implemented under `team`)

**As a** manager agent
**I want** to assign tasks to appropriate specialist agents
**So that** work is completed by the right expertise

**Acceptance Criteria:**
- [ ] Tasks can be assigned based on type (code/review/test)
- [ ] Agents receive task context and requirements
- [ ] Progress tracked in real-time
- [ ] Blocked tasks escalated to manager
- [ ] Completed tasks verified before closing
- [ ] Task history maintained for reporting
- [ ] Multiple tasks can be in progress simultaneously
- [ ] Load balancing across available agents

**Definition of Done:**
- Task routing logic implemented
- State synchronization reliable
- Performance handles 100+ concurrent tasks
- Monitoring dashboard available

## Epic: Workflow Automation

### Story: WF-001 - Create Lobster Pipeline

**As a** developer
**I want** to define deterministic workflows in YAML
**So that** complex tasks execute reliably and efficiently

**Acceptance Criteria:**
- [ ] Workflow template generated from command
- [ ] YAML validates against schema
- [ ] Steps execute sequentially as defined
- [ ] Conditional branching supported
- [ ] Variables can be passed between steps
- [ ] Workflow can call other workflows
- [ ] Execution logs captured for debugging
- [ ] Failed steps can be retried

**Definition of Done:**
- Lobster YAML parser integrated
- Workflow engine executes reliably
- 10+ example workflows provided
- Performance optimized for token usage

### Story: WF-002 - Execute Workflow

**As a** developer
**I want** to run predefined workflows with a single command
**So that** routine tasks are automated and consistent

**Acceptance Criteria:**
- [ ] Workflow executes all steps in order
- [ ] Progress shown in real-time
- [ ] Errors stop execution with clear messages
- [ ] Partial results saved on failure
- [ ] Can resume from failed step
- [ ] Tokens used tracked per workflow
- [ ] Execution time logged
- [ ] Results summarized at completion

**Definition of Done:**
- Workflow execution reliable
- Error recovery implemented
- Performance metrics collected
- Integration tests cover edge cases

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
- Penetration testing completed
- No data leakage detected
- Performance impact < 5%
- Security documentation updated

### Story: SEC-002 - Tool Approval Gates

**As a** security admin
**I want** to control which tools agents can use
**So that** dangerous operations require approval

**Acceptance Criteria:**
- [ ] Default gates for rm, git push, docker stop
- [ ] Telegram approval workflow implemented
- [ ] Timeout for pending approvals (5 minutes)
- [ ] Audit log of all approvals/denials
- [ ] Emergency override with logging
- [ ] Configurable per agent type
- [ ] Batch approval for similar operations
- [ ] Clear indication when approval needed

**Definition of Done:**
- Approval flow tested end-to-end
- Telegram integration reliable
- Audit logs tamper-proof
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
- [ ] File uploads/downloads supported
- [ ] Approval requests sent as buttons
- [ ] Status updates pushed proactively
- [ ] Multiple agents per group supported
- [ ] Secure token authentication

**Definition of Done:**
- Telegram bot fully functional
- Message handling reliable
- Mobile UI/UX optimized
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
- [ ] Automatic repair attempted
- [ ] Alerts sent for critical issues
- [ ] Health metrics dashboard available
- [ ] Historical health data retained

**Definition of Done:**
- Monitoring runs continuously
- Self-healing successful 80%+
- Alert fatigue minimized
- Dashboard provides actionable insights

### Story: MON-002 - System Diagnostics

**As a** developer
**I want** comprehensive system diagnostics
**So that** I can quickly identify and fix issues

**Acceptance Criteria:**
- [ ] Check OpenClaw daemon status
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
When I run "docket add testapp ~/projects/app"
Then the pod should be created successfully with members testapp-lead and testapp-implementer
And workspaces should exist at ~/.openclaw/workspaces/projects/testapp-lead/ and testapp-implementer/

When I run "docket info testapp-lead"
Then I should see the agent details
And the session key should be "agent:testapp:default"

When I run "docket maintain testapp-lead clean"
Then memory logs should be cleared
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
  | Total cost    | $X.XX (recorded from daemon) |

And the total should reflect the daemon's recorded spend, not an estimate
```

## Epic: Pod Lifecycle (Phase 10)

### Story: POD-001 - Provision a Project Pod

**As a** developer
**I want** to create an isolated pod for my project with `docket add <project>`
**So that** each project gets its own Lead + Implementer with no shared state

**Acceptance Criteria:**
- [ ] `docket add myapp ~/code/myapp` creates `myapp-lead` and `myapp-implementer`
- [ ] Each member gets an isolated workspace at `~/.openclaw/workspaces/projects/<member-id>/`
- [ ] All members share the pod's session key `agent:myapp:default`
- [ ] `docket pod myapp` lists the pod members with their roles
- [ ] `docket add myapp --pod full` also creates `myapp-reviewer` and `myapp-tester`
- [ ] A second `docket add myapp` is idempotent — does not recreate existing members
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
- [ ] `docket pod myapp queue` shows the task with status `pending` and recorded cost `$0.00`
- [ ] `docket pod myapp dispatch` runs Lead → Implementer → (Reviewer) → (Tester), one real LLM turn per hop
- [ ] Each hop is budget-gated: if Lead's spend cap is exceeded, task stays `pending`
- [ ] Each hop emits a trace event visible in `docket trace tail myapp`
- [ ] After completion, `docket pod myapp queue` shows the task as `done` with recorded cost

**Definition of Done:**
- Dispatch pipeline covered by integration tests with a real openclaw shim
- Budget-gating tested (over-budget task stays pending)
- Trace events verified per-hop

### Story: POD-003 - Grow and Shrink a Pod

**As a** developer
**I want** to add or remove roles from an existing pod
**So that** I can add a review gate when work becomes higher-stakes without reprovisioning

**Acceptance Criteria:**
- [ ] `docket pod myapp add reviewer` adds `myapp-reviewer` to an existing pod
- [ ] `docket pod myapp add implementer --count 2` adds `myapp-implementer-2` and `myapp-implementer-3`
- [ ] `docket pod myapp remove myapp-reviewer` removes that member and its workspace
- [ ] A second `docket pod myapp add reviewer` rejects adding a duplicate when one already exists
- [ ] `docket pod myapp add lead` is rejected — a pod may have only one Lead
- [ ] `docket pod myapp` always reflects the current state after add/remove

**Definition of Done:**
- Add/remove covered by pytest suite
- Singleton-Lead constraint tested
- `docket pod` output verified after each operation

## Metrics

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

### Version 1.1.0 (2026-06-26)
- Updated TEAM-001 to reflect pod model: Manager is an org specialist, not a router to programmer/reviewer/tester
- Fixed Gherkin lifecycle scenario: `docket reset testapp 1` → `docket maintain testapp-lead clean`; creation now shows pod members
- Fixed cost scenario: removed "standard profile" tier language; cost output is daemon-recorded spend, not an estimate
- Added POD-001 (provision pod), POD-002 (dispatch pipeline), POD-003 (grow/shrink pod) for Phase 10 coverage
- Updated story index table and "Last Updated" date

### Version 1.0.0 (2024-01-20)
- Initial user stories defined
- Acceptance criteria established
- Success metrics defined
- Test scenarios created