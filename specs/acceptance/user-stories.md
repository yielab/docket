# User Stories and Acceptance Criteria

**Version**: 2.0.0
**Status**: Active
**Last Updated**: 2026-10-22

## Overview

This document states what an operator can do with docket today, as user stories with the
conditions that hold for each. A story follows the format:
```
As a [role]
I want [feature]
So that [benefit]
```

The CLI has ten top-level commands: `init status inbox task run pod log setup start stop`. Every
story below is written against them. A story whose behaviour does not exist is not kept here.
Owning specs (cost-tracking, pod-dispatch, security-gates, telegram-integration, agent-lifecycle)
hold the full requirements; this document restates the operator-visible part and names the tests
that answer to it.

## Stories

Each story has a stable ID used to cross-reference criteria and tests.

| ID | Story | Epic |
|----|-------|------|
| AGT-002 | Reset a Member's Ledger | Pod Members |
| AGT-003 | Monitor Token Use and Estimated Cost | Pod Members |
| POD-001 | Provision a Project Pod | Pod Lifecycle |
| POD-002 | Run the Pod Dispatch Pipeline | Pod Lifecycle |
| POD-003 | Grow and Shrink a Pod | Pod Lifecycle |
| SEC-001 | Project Isolation | Security and Isolation |
| SEC-002 | Tool Approval Gates | Security and Isolation |
| COM-001 | Telegram Integration | Communication |
| MON-002 | System Diagnostics | Monitoring and Maintenance |

## Criteria

Every story carries two checklists:

- **Acceptance Criteria**: observable conditions that MUST hold for the story to be accepted.
- **Definition of Done**: the engineering bar that MUST be satisfied before the story is closed.

Each criterion is true of the current CLI. A criterion followed by *(untested)* holds in the code
but has no test that exercises it yet; the same items are listed under "Untested" at the end of
each story. No script tracks story-to-test coverage: the test names given in the Scenarios section
and in each story are the evidence. `scripts/validate-specs.sh` checks each spec's required
sections, not story coverage.

## Epic: Pod Members

### Story: AGT-002 - Reset a Member's Ledger

**As a** developer
**I want** to clear a pod member's task ledger without losing what it has learned
**So that** I can start a member clean when switching tasks or fixing issues

The surface is `docket pod reset <member>`.

**Acceptance Criteria:**
- [ ] `pod reset` resets the member's HEARTBEAT.md and leaves MEMORY.md, `memory/` and the
      pod's memory alone (`test_leaves_memory_md_the_daily_logs_and_the_pod_memory_alone`)
- [ ] `pod reset` rebuilds SOUL.md, AGENTS.md and the other generated workspace files from the
      member's metadata (`test_rebuilds_workspace_files_from_metadata`)
- [ ] `pod reset` calls no model (`test_resets_the_ledger_and_calls_no_model`)
- [ ] `pod reset` asks for confirmation on a TTY and needs `--yes` off one; a non-interactive call
      without it exits 1 and changes nothing
      (`test_off_a_tty_without_yes_refuses_and_changes_nothing`)
- [ ] A member id outside the pod is refused (`test_a_name_outside_the_pod_is_refused`)
- [ ] Reset preserves identity: the member's metadata (codebase path, session key) and its fleet
      registration are not rewritten *(untested)*

**Definition of Done:**
- Reset is covered by the integration tests named above
- `docket pod reset --help` and the generated CLI reference list the verb

### Story: AGT-003 - Monitor Token Use and Estimated Cost

**As a** project manager
**I want** to see how many tokens a pod used and a labelled cost estimate
**So that** I can manage AI spend without mistaking an estimate for billing

**Acceptance Criteria:**
- [ ] `docket status` shows the pod's measured tokens as `<in> in / <out> out`, or `none yet`,
      beside the pod's done / failed / aborted counts and latency
      (`test_a_scripted_trace_of_one_done_and_two_failed_reads_1_2_0`)
- [ ] The dollar figure beside the tokens is labelled `est.`: docket records no dollar spend, so
      the figure is a token-count times catalog-price estimate and is never presented as recorded
      (`test_status_labels_the_dollar_figure_an_estimate`)
- [ ] `docket status --all --json` carries each agent's recorded `costUsd` and the fleet
      `totalCostUsd`, both `0.0` while nothing records a cost
      (`test_status_all_json_inventory_cost_field_stays_zero`)
- [ ] `docket status --all` summarises every pod
      (`test_all_shows_failed_counts`)
- [ ] `docket status --json` is machine-readable (`test_json_carries_tasks_usage_last_run_and_the_start_flag`)
- [ ] `docket status --history [--days N]` returns an empty history, because sessions store one
      running total and no per-turn timestamp (`test_history_with_no_dated_data_is_an_empty_list`)
- [ ] A budget cap (`docket pod set budgetUsd <USD>`) is checked before each hop against the same
      estimate; `docket setup --fix` warns at 80% or more of the cap and flags 100% or more, with
      the `estimated — no cost recorded` label
      (`test_budget_warns_at_80_percent_from_estimate`,
      `test_budget_over_cap_from_estimate_when_nothing_recorded`)
- [ ] A budgeted pod running a model with no catalog price is named by `docket status` and
      `docket pod show`, not counted as zero (`test_status_json_and_text_name_the_unpriced_model`)

**Definition of Done:**
- Token totals come from docket's own durable session records
- Cap enforcement is the pod-dispatch lane's (see POD-002); the warning display is `docket setup --fix`

## Epic: Pod Lifecycle

### Story: POD-001 - Provision a Project Pod

**As a** developer
**I want** to create an isolated pod for my project with `docket init <project> <location>`
**So that** each project gets its own Lead and Implementer with no shared state

**Acceptance Criteria:**
- [ ] `docket init myapp ~/code/myapp` creates `myapp-lead` and `myapp-implementer`
      (`test_default_lean_pod_is_lead_plus_implementer`)
- [ ] Each member gets its own workspace under `~/.docket/workspaces/projects/<member-id>/`,
      directories mode 700 and files mode 600 (`test_managed_workspace_modes_are_owner_only`)
- [ ] The codebase's stack is detected from its project files and recorded in the member's
      metadata (`test_detect_stack_python`)
- [ ] The role-to-model policy assigns each member's model, visible in
      `docket pod show <member>` as `(policy)`
- [ ] All members share the pod's session key `agent:myapp:default`
      (`test_members_have_correct_meta_and_shared_base_session_key`)
- [ ] `docket pod show --pod myapp` lists the members with their roles and models
- [ ] `docket status --pod myapp` counts the members immediately after creation *(untested)*
- [ ] `docket init myapp ~/code/myapp --pod full` also creates `myapp-reviewer` and `myapp-tester`
      (`test_full_pod_has_four_members`)
- [ ] A second `docket init myapp` fails with "A project or pod 'myapp' already exists." (exit 1)
      and does not touch the existing members *(untested)*
- [ ] `docket pod delete --confirm myapp` removes every member, workspace, session and trace and
      keeps the audit log; without `--confirm` it exits 1 and removes nothing
      (`test_delete_pod_removes_all_members`,
      `test_delete_pod_purges_runtime_sessions_and_traces_but_preserves_audit`)

**Definition of Done:**
- Provisioning is covered by pytest and golden-parity tests
- `docket pod show` lists all members after creation
- Deletion removes every pod member

### Story: POD-002 - Run the Pod Dispatch Pipeline

**As a** developer
**I want** to queue a task and dispatch it through the pod pipeline
**So that** the Lead, Implementer and optional Reviewer and Tester execute in sequence

**Acceptance Criteria:**
- [ ] `docket task add "<task>"` queues a task on the pod (`test_queues_from_the_pod_in_the_environment`)
- [ ] `docket task list` shows the task as `pending`, with a dash in the COST column because no
      cost is recorded *(untested)*
- [ ] `docket run` runs Lead, Implementer, then Reviewer and Tester when the pod has them, one
      real agent turn per hop (`test_traces_written_per_hop`)
- [ ] A Reviewer `REQUEST-CHANGES` sends the task back to the Implementer for one rework cycle by
      default (`maxReworkCycles`); a second one fails the task; a Tester `FAIL` is terminal
      (`test_request_changes_triggers_one_rework_then_approves`,
      `test_second_request_changes_fails_the_task`, `test_builtin_tester_has_no_rework`)
- [ ] Each hop is budget-gated against the pod's `budgetUsd` using the labelled estimate. Over the
      cap the task is set to `blocked` (never rewritten to `pending`) and the pod is paused
      (`test_cap_breach_pauses_lead_and_blocks_task`,
      `test_dispatch_pauses_pod_using_estimate_when_nothing_recorded_a_cost`)
- [ ] A blocked task re-enters the queue only through `docket run --resume`,
      `docket pod set budgetUsd <USD>` or `docket task retry <task-id>`
      (`test_resume_clears_the_budget_pause_and_unblocks_tasks`,
      `test_retry_task_unblocks_a_single_task`, `test_unblock_pod_unblocks_every_blocked_task`)
- [ ] Each hop emits trace events readable with `docket task trace <task> [--tail]`
      (`test_traces_written_per_hop`, `test_tail_returns_once_the_session_has_ended`)
- [ ] After completion `docket task list` shows the task as `done` *(untested at the CLI; the
      state change is covered by `test_resume_skips_already_completed_hops`)*

**Definition of Done:**
- The dispatch pipeline is covered by live-path tests with a deterministic chat backend
- Budget gating is tested (over-budget task is `blocked`, never rewritten to `pending`)
- Trace events are verified per hop

### Story: POD-003 - Grow and Shrink a Pod

**As a** developer
**I want** to add or remove roles from an existing pod
**So that** I can add a review gate when work becomes higher-stakes without reprovisioning

**Acceptance Criteria:**
- [ ] `docket pod add reviewer` adds `myapp-reviewer` to an existing pod (`test_add_reviewer`)
- [ ] `docket pod add implementer --count 2` adds two more implementers, `myapp-implementer-2`
      and `myapp-implementer-3` (`test_add_count_two_makes_two_implementers`)
- [ ] A second `docket pod add reviewer` adds `myapp-reviewer-2`: duplicated roles get indexed ids
      (`test_add_second_implementer_is_indexed`)
- [ ] `docket pod remove myapp-reviewer` removes that member and its workspace; it asks on a TTY
      and needs `--yes` off one (`test_remove_member`)
- [ ] `docket pod add lead` is rejected with exit 1: a pod has one Lead
      (`test_add_second_lead_rejected`)
- [ ] `docket pod remove` of the Lead is refused and points to `docket pod delete` *(untested)*
- [ ] `docket pod show` reflects the current members after each add or remove *(untested)*

**Definition of Done:**
- Add and remove are covered by the pytest suite
- The single-Lead constraint is tested

## Epic: Security and Isolation

### Story: SEC-001 - Project Isolation

**As a** developer
**I want** agents confined to their own project
**So that** sensitive data does not leak between projects

**Acceptance Criteria:**
- [ ] A pod has its own session key containing the pod name (`agent:<pod>:default`), so session
      history is not shared between pods
      (`test_members_have_correct_meta_and_shared_base_session_key`)
- [ ] The built-in file tools refuse a path outside their allowed roots: `..` traversal, an
      absolute path elsewhere and a symlink escape (`test_traversal_out_of_the_root_is_refused`,
      `test_absolute_path_outside_the_root_is_refused`, `test_symlink_escape_is_refused`)
- [ ] A pod dispatches only its own queue (`test_no_cross_pod_dispatch`)
- [ ] The audit log records authorizations, approvals and denials with their channel, and
      records unauthorized Telegram attempts without the message body
      (`test_grant_via_cli_audits_channel_cli`,
      `test_unauthorized_attempt_is_audited_without_the_message_body`)
- [ ] Workspace isolation (Landlock and seccomp on Linux, Seatbelt on macOS, or Docker when
      chosen) is opt-in with `docket setup sandbox on`; with it off, `docket status` and
      `docket setup` say the agent's commands run with the user's permissions
      (`test_isolation_is_off_by_default_and_needs_no_backend`,
      `test_isolation_reports_the_sandbox_state_in_json_and_on_the_line`); the escape matrix test gates release

**Definition of Done:**
- Isolation is validated by the security tests named above
- Security documentation describes the opt-in sandbox honestly (`docs/SECURITY-SIMPLE.md`)

### Story: SEC-002 - Tool Approval Gates

**As a** security admin
**I want** to control which tool calls agents may make
**So that** dangerous operations require approval

**Acceptance Criteria:**
- [ ] The default policies and command classifier ask before `rm -rf`, a `git push` to
      main or production and `docker stop` (`docket pod check "<command>" --role implementer`
      prints `ask`; `test_rm_rf_bash_call_is_gated_and_handler_never_runs`,
      `test_push_to_main_is_gated_push_to_a_feature_branch_is_not`); `docker stop` has no test
      *(untested)*
- [ ] A pending approval is answered with `docket task approve <task>` or `docket task deny <task>`
      (`--reason` records why), through the CLI, HTTP, MCP or Telegram channel, all audited with
      their channel (`test_grant_via_cli_audits_channel_cli`,
      `test_deny_via_http_audits_channel_http`,
      `test_approve_grants_and_writes_a_telegram_tagged_audit_entry`)
- [ ] A pending approval left unanswered fails closed: the in-turn wait ends in a deny after
      `TOOL_APPROVAL_TIMEOUT` seconds (default 120), and a parked approval expires after the pod's
      `approvalExpiryHours` (`test_gated_command_is_not_executed`)
- [ ] One command can be pre-approved before the task asks with
      `docket task approve <task> --for "<command>"`, single use; `--task` extends one granted call
      to the rest of the task (`test_park_grant_resumes_the_parked_hop_with_a_single_use_pregrant`)
- [ ] Policies are scoped by role, and a pod chooses its approval mode with
      `docket pod set approvalMode` (`test_a_role_scoped_policy_does_not_fire_for_a_different_role`)
- [ ] Every approval and denial is in the audit log (`docket log`)
      (`test_grant_via_cli_audits_channel_cli`, `test_deny_via_cli_audits_channel_cli`)
- [ ] `docket inbox` shows a held approval with the whole command and the exact
      `docket task approve` and `docket task deny` commands
      (`test_a_held_approval_prints_the_whole_command_and_both_decisions`)

**Definition of Done:**
- The approval flow is tested end to end (the approval-gated dispatch integration tests)
- The audit log is hash-chained and checked by `docket log verify`; erasure is made visible, not
  prevented

## Epic: Communication

### Story: COM-001 - Telegram Integration

**As a** developer
**I want** to approve and queue work through Telegram
**So that** I can manage a pod from a phone

**Acceptance Criteria:**
- [ ] A pod member is bound to a chat with `docket setup notify bind <member>` (or
      `docket setup notify enable telegram`, which binds every pod Lead); a peer maps to at most
      one member at a time
- [ ] The bot accepts five commands from a bound chat: `/approve`, `/deny`, `/status`,
      `/delegate` and `/answer`. Anything else, including plain prose, is refused
      (`test_plain_text_with_no_slash_command_is_not_treated_as_delegate`,
      `test_unrecognized_command_never_defaults_to_a_grant`)
- [ ] An unbound chat cannot approve, deny, check status, delegate or answer, even with a real
      pending token (`test_an_unbound_chat_approving_never_grants_even_with_a_real_token`)
- [ ] `/status` lists the bound pod's pending approvals (`test_status_lists_only_this_projects_pending_approvals`)
- [ ] The bot replies to a message and never messages a chat first; the separate `telegram`
      notification channel (off by default) sends only to the chat ids in its own `actors` list
      (`test_sends_to_every_actor_with_the_resolved_secret`)
- [ ] The bot token lives in docket's secrets store and never appears in an audit entry, trace
      payload or `--json` response (`test_http_error_body_does_not_echo_the_token`)
- [ ] The bot is opt-in with `docket start --telegram` *(untested)*

**Definition of Done:**
- The channel behaves as telegram-integration.spec.md states
- Message handling is covered by the Telegram channel integration tests

## Epic: Monitoring and Maintenance

### Story: MON-002 - System Diagnostics

**As a** developer
**I want** one diagnostic pass over my docket installation
**So that** I can quickly identify and fix issues

The diagnostic pass is `docket setup --fix`. Bare `docket setup` is the first-run readiness
report (model endpoint, notifications, sandbox, shell completion, background service).

**Acceptance Criteria:**
- [ ] `docket setup --fix` checks python3, the fleet registry, each registered
      member's workspace files, the model registry, the role overlay, schedules, the dispatch
      task ledger against HEARTBEAT.md, per-member budget and runaway-session limits, provider
      key coverage, the provider catalog, exporters, notification channels, security gates,
      guardrail policies, pod config overlays, template versions and the runtime startup contract
      (`test_project_agents_missing_files_flagged`, `test_budget_over_cap_flagged`,
      `test_runaway_flagged_by_turns`, `test_provider_coverage_missing_key`)
- [ ] Each failed check prints the command that fixes it
- [ ] It exits 1 when a critical issue is found and 0 when healthy
      (`test_human_degraded_exits_one`, `test_human_healthy_exits_zero`)
- [ ] `docket setup --fix --json` emits the same checks as JSON with `healthy` and `issues`
      (`test_json_structure_keys`, `test_json_degraded_exits_one`)
- [ ] A home with pods and no notification channel that delivers is counted as an issue
      (`test_agents_and_only_console_is_a_counted_issue`)
- [ ] `--fix` re-syncs a stale task ledger and stale member workspace files, and tightens the
      fleet and secrets files to mode 600 (`test_step_security_hardens_world_readable_secrets`)
- [ ] Bare `docket setup` prints the readiness report and exits 1 when the model endpoint is
      missing *(untested)*

**Definition of Done:**
- The pass runs in well under a second on an empty home *(not asserted by a test)*
- It does not test network connectivity or report resource usage

## Scenarios

The scenarios are prose. No BDD runner executes them; each names the tests that exercise it.

### Scenario: Complete Pod Lifecycle

```gherkin
Given a clean docket installation
When I run "docket init testapp ~/projects/app"
Then the pod should be created successfully with members testapp-lead and testapp-implementer
And workspaces should exist at ~/.docket/workspaces/projects/testapp-lead/ and testapp-implementer/

When I run "docket pod show testapp-lead --pod testapp"
Then I should see the member's effective configuration
And the session key should be "agent:testapp:default"

When I run "docket pod reset testapp-lead --pod testapp --yes"
Then the member's HEARTBEAT.md should be reset
And MEMORY.md and the pod's memory should remain unchanged
And SOUL.md should be rebuilt from the member's metadata

When I run "docket pod delete --confirm testapp"
Then the workspaces for all pod members should be removed
And "docket status --all" should list no testapp pod
```

Exercised by: `test_default_lean_pod_is_lead_plus_implementer`,
`test_members_have_correct_meta_and_shared_base_session_key`,
`test_resets_the_ledger_and_calls_no_model`,
`test_leaves_memory_md_the_daily_logs_and_the_pod_memory_alone`,
`test_rebuilds_workspace_files_from_metadata`, `test_delete_pod_removes_all_members`.
Untested: the member's effective-configuration view through `pod show <member>`, the TTY
confirmation prompt of `pod reset`, and `status --all` after deletion.

### Scenario: Status Shows Tokens and a Labelled Estimate

```gherkin
Given a pod "webapp" whose Lead has processed 1000000 input tokens and 1000000 output tokens
And the Lead runs on anthropic/claude-haiku-4-5

When I run "docket status --pod webapp"
Then I should see the tokens as "<in> in / <out> out"
And the dollar figure beside them should be labelled "est."
And no recorded dollar spend should be shown

When I run "docket status --all --json"
Then the Lead's "costUsd" and the fleet "totalCostUsd" should be 0.0
```

Exercised by: `test_status_labels_the_dollar_figure_an_estimate`,
`test_status_all_json_inventory_cost_field_stays_zero`.

### Scenario: A Budget Cap Blocks Dispatch

```gherkin
Given a pod with a task queued
And the pod's budgetUsd cap is already reached by the token estimate

When I run "docket run"
Then the task should be set to "blocked"
And the pod should be paused for "budget"

When I run "docket run --resume"
Then the pause should be cleared
And the blocked task should be pending again
```

Exercised by: `test_cap_breach_pauses_lead_and_blocks_task`,
`test_paused_pod_refuses_claim_at_next_dispatch`,
`test_resume_clears_the_budget_pause_and_unblocks_tasks`,
`test_unblock_pod_unblocks_every_blocked_task`.

### Scenario: A Gated Command Waits for Approval

```gherkin
Given a pod whose approvalMode is "park"
And an Implementer that tries to run "rm -rf build"

When I run "docket run"
Then the task should park as "waiting approval" with a trace event "approval_required"

When I run "docket task approve <task>"
And I run "docket run"
Then the Implementer hop should run again
And the exact approved command should pass once
And the audit log should hold an "approval.grant" entry with channel "cli"
```

Exercised by: `test_park_grant_resumes_the_parked_hop_with_a_single_use_pregrant`,
`test_grant_via_cli_audits_channel_cli`.

## Metrics

Docket reports these measurements itself; none is a target. Acceptance of a story does not depend
on a threshold.

- **Tokens**: measured input and output tokens per pod (`docket status`, `docket status --json`).
- **Estimated cost**: a labelled token-count times catalog-price estimate; recorded spend is
  always `0.0`.
- **Outcomes**: done, failed and aborted task counts and mean and p95 latency per pod
  (`docket status`).
- **Guardrails**: approval, denial and policy-hit counts on the service's `/metrics` endpoint
  (`docket start`; `test_hits_are_counted_by_policy_id_hook_and_action`).
- **Audit integrity**: `docket log verify` reports a break in the hash chain.

## Implementation

Where the names above live today. Phase 46 rewrites this section and nothing else.

- `src/docket/cli/_status.py`: `docket status` (tokens, estimate label, `--history`)
- `src/docket/cli/_pod.py`: `docket pod` verbs (`show`, `add`, `remove`, `reset`, `delete`, `set`, `check`)
- `src/docket/cli/_agents.py`: `docket init`
- `src/docket/cli/_task.py`, `src/docket/cli/_run.py`: `docket task`, `docket run`
- `src/docket/cli/_setup.py`, `src/docket/cli/_setup_check.py`: `docket setup`, `docket setup --fix`
- `src/docket/core/dispatch.py`: pod dispatch, budget gate, `unblock_pod`, `retry_task`
- `src/docket/core/telegram.py`: the Telegram bot commands
- `src/docket/templates/policies/block-destructive.yaml`, `src/docket/core/security.py`: the default
  gates (`HIGH_RISK_PATTERNS`, `classify_command`)
- `src/docket/kernel/home.py`: the `Home` members `tool_approval_timeout`

Tests cited by name above:

- `tests/integration/test_pod_reset.py`, `tests/integration/test_pod_provisioning.py`,
  `tests/integration/test_provisioning_contract.py`, `tests/integration/test_pod_blueprint_provisioning.py`
- `tests/integration/test_autopause.py`, `tests/integration/test_dispatch.py`,
  `tests/integration/test_reviewer_gate.py`, `tests/integration/test_approval_gated_dispatch.py`
- `tests/integration/test_audit_approval_parity.py`, `tests/integration/test_telegram_channel.py`,
  `tests/integration/test_install.py`, `tests/integration/test_escape_matrix.py`,
  `tests/integration/test_pre_tool_call_policy.py`
- `tests/unit/cli/test__status.py`, `tests/unit/cli/test__task.py`, `tests/unit/cli/test__run.py`,
  `tests/unit/cli/test__setup_check.py`, `tests/unit/cli/test__inbox.py`, `tests/unit/core/test_tools.py`,
  `tests/integration/test_guardrail_metrics.py`,
  `tests/unit/core/test_pipeline__spec.py`, `tests/unit/edges/adapters/test_telegram.py`
