# Analysis of `docket` (123 modules)

## Gate metrics

| metric | value |
|---|---|
| cycle_largest | 38 |
| cycle_largest_toplevel | 1 |
| local_imports | 203 |
| module_largest_lines | 4728 |
| status_writers | 16 |
| monkeypatch_cross_module_targets | 9 |
| core_modules_importing_edges | 31 |
| dict_any_annotations | 638 |
| isinstance_dict_guards | 232 |

## Import cycles

- top_level: 0 cycle(s), sizes []
- with_local: 5 cycle(s), sizes [38, 3, 2, 2, 2]

Largest cycle (counting local imports):

- `docket.core.agent_loop`
- `docket.core.approval`
- `docket.core.archetypes`
- `docket.core.blueprints`
- `docket.core.consult`
- `docket.core.context`
- `docket.core.corrections`
- `docket.core.dispatch`
- `docket.core.exporter`
- `docket.core.identity`
- `docket.core.mcp_tools`
- `docket.core.models_policy`
- `docket.core.orchestrator`
- `docket.core.pipeline`
- `docket.core.pod`
- `docket.core.pod_memory`
- `docket.core.pod_provisioning`
- `docket.core.prepare`
- `docket.core.profile`
- `docket.core.protected_paths`
- `docket.core.provider`
- `docket.core.repo_map`
- `docket.core.runs`
- `docket.core.secrets`
- `docket.core.session`
- `docket.core.task_options`
- `docket.core.telemetry`
- `docket.core.tools`
- `docket.core.trace`
- `docket.core.utils`
- `docket.edges.adapters.docket_runtime`
- `docket.edges.adapters.exporters`
- `docket.edges.adapters.exporters.otlp_http`
- `docket.edges.adapters.fetch`
- `docket.edges.adapters.llm`
- `docket.edges.adapters.mcp_client`
- `docket.edges.adapters.system`
- `docket.edges.adapters.toolbox`

## Function-local imports by package

- docket.cli: 69
- docket.core: 69
- docket.edges: 14
- docket.serve: 51

## Call groups: `docket.core.dispatch`

186 definitions; hubs have fan-in >= 5.

| group | definitions | lines | external callers |
|---|---|---|---|
| g1 | 170 | 69-4685 | 64 |
| g2 | 1 | 271-290 | 0 |
| g3 | 1 | 4167-4191 | 3 |
| g4 | 1 | 4355-4379 | 2 |
| g5 | 1 | 4688-4696 | 10 |
| g6 | 1 | 4699-4718 | 1 |

Shared (name and fan-in): `DispatchError` (16), `HopResult` (38), `TaskResult` (9), `pod_task_list_path` (16), `_normalize_task` (8), `_pod_settings` (13), `_task_worktree_dir` (6), `_trace_locked` (15), `_UnitOutcome` (16), `_UnitContext` (37), `_match_on_route` (5)

## Call groups: `docket.serve`

51 definitions; hubs have fan-in >= 5.

| group | definitions | lines | external callers |
|---|---|---|---|
| g1 | 49 | 42-1991 | 2 |

Shared (name and fan-in): `_SWEEP_LOCK` (6), `_sweep_inflight` (5)

## Call groups: `docket.edges.adapters.system`

120 definitions; hubs have fan-in >= 5.

| group | definitions | lines | external callers |
|---|---|---|---|
| g1 | 82 | 39-1694 | 34 |
| g2 | 1 | 101-115 | 2 |
| g3 | 1 | 118-131 | 1 |
| g4 | 2 | 763-794 | 1 |
| g5 | 1 | 1045-1053 | 2 |
| g6 | 1 | 1056-1067 | 1 |
| g7 | 2 | 1070-1108 | 1 |
| g8 | 1 | 1116-1128 | 4 |
| g9 | 1 | 1131-1139 | 2 |
| g10 | 1 | 1142-1170 | 3 |
| g11 | 4 | 1173-1525 | 4 |
| g12 | 1 | 1219-1242 | 1 |
| g13 | 1 | 1245-1257 | 1 |
| g14 | 1 | 1260-1277 | 2 |
| g15 | 1 | 1280-1290 | 2 |
| g16 | 1 | 1293-1311 | 2 |
| g17 | 1 | 1314-1330 | 2 |
| g18 | 1 | 1420-1432 | 1 |
| g19 | 4 | 1435-1462 | 1 |
| g20 | 1 | 1465-1474 | 1 |
| g21 | 3 | 1477-1495 | 1 |
| g22 | 1 | 1528-1539 | 1 |
| g23 | 1 | 1542-1555 | 1 |
| g24 | 1 | 1558-1568 | 1 |
| g25 | 1 | 1571-1582 | 2 |
| g26 | 1 | 1585-1596 | 2 |

Shared (name and fan-in): `_QUERY_TIMEOUT` (22), `_git_run` (17), `git_available` (25)

## Writers of a task's status

| site | function | value | other fields set |
|---|---|---|---|
| docket.core.answers:187 | _answer_consult | `'pending'` | consultAnswer |
| docket.core.answers:249 | _apply_route_outcome | `terminal` | claimId, completedAt, reason |
| docket.core.answers:258 | _apply_route_outcome | `'pending'` | - |
| docket.core.answers:408 | sweep_expired_questions | `'blocked'` | blockedReason, reason |
| docket.core.dispatch:466 | enqueue_task_once | `'waiting_approval'` | approvalToken, pendingApprovalIndex |
| docket.core.dispatch:3711 | _apply_result | `res.status` | claimId, costUsd, hops, reason |
| docket.core.dispatch:3811 | _refuse_claimed_task | `'failed'` | claimId, completedAt, failureKind, reason |
| docket.core.dispatch:3957 | _claim_next_task | `'running'` | claimId, claimPid, claimedAt, startedAt |
| docket.core.dispatch:4097 | _sweep_stale_claims | `'failed'` | claimId, failureKind, reason |
| docket.core.dispatch:4154 | reclaim_stale_running | `'failed'` | claimId, failureKind, reason |
| docket.core.dispatch:4181 | retry_task | `'pending'` | - |
| docket.core.dispatch:4217 | cancel_parked_task | `'cancelled'` | claimId, completedAt, reason |
| docket.core.dispatch:4372 | unblock_pod | `'pending'` | - |
| docket.core.dispatch:4458 | resolve_waiting_approval_detail | `'done'` | claimId, completedAt, reason |
| docket.core.dispatch:4464 | resolve_waiting_approval_detail | `'pending'` | - |
| docket.core.dispatch:4483 | resolve_waiting_approval_detail | `'failed'` | claimId, completedAt, failureKind, reason |
| docket.edges.adapters.exporters.otlp_http:79 (not a task record) | _encode_span | `{'code': status_code}` | - |

## Patches whose defining module differs (9 targets)

- `docket.cli._run.readiness` is defined in `docket.cli._setup`
- `docket.cli._setup_model.audit_log` is defined in `docket.core.audit`
- `docket.cli._status.sandbox_state` is defined in `docket.cli._setup_sandbox`
- `docket.core.agent_loop.compact_session` is defined in `docket.core.session`
- `docket.core.agent_loop.dispatch_tool` is defined in `docket.core.tools`
- `docket.core.agent_loop.trace_event` is defined in `docket.core.trace`
- `docket.core.runs.audit_log` is defined in `docket.core.audit`
- `docket.edges.adapters.channels.telegram.send_message` is defined in `docket.edges.adapters.telegram`
- `docket.edges.adapters.llm.open_same_origin` is defined in `docket.edges.adapters.redirects`

## Task-record keys nothing reads

channel, checkChanged, claimId, claimRefusal, source, usage

## Run records and hop records

Shared keys: error; duplicates hops: False

## Modules with no rule in the mapping

none
