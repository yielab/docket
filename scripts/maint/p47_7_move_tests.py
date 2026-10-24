"""Move tests/integration/test_*.py into tests/integration/<context>/ (temporary, P47-7)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INTEG = ROOT / "tests" / "integration"

Q = "docket.tasks.application.queue"
SW = "docket.tasks.application.sweep"
CMD = "docket.interfaces.cli.commands."
SRV = "docket.interfaces.http.server"

# old name -> (folder, new name or "", subject or "")  ("" keeps the current value)
TABLE: dict[str, tuple[str, str, str]] = {
    "adoption_tools": ("product", "", ""),
    "agent_loop_no_progress": ("agent", "", ""),
    "agent_loop": ("agent", "", ""),
    "approval_gated_dispatch": ("tasks", "", SW),
    "approval_pack": ("hops", "", "docket.hops.application.driver"),
    "approve_task_grant": ("governance", "", "docket.governance.gate"),
    "archetypes": ("teams", "", ""),
    "audit_approval_parity": ("governance", "", "docket.governance.approval"),
    "audit_log": ("governance", "", "docket.governance.audit"),
    "auth_context_maintain_keys_add": (
        "interfaces",
        "init_status_and_removed_names",
        CMD + "status",
    ),
    "authenticated_redirects": ("platform", "", ""),
    "autopause": ("tasks", "", SW),
    "base_commit_repo_files": ("teams", "", ""),
    "bash_cancellation": ("agent", "", ""),
    "check_recipes": ("tasks", "", ""),
    "console_script_entry_point": ("bootstrap", "", "docket.__main__"),
    "consult_park": ("tasks", "", ""),
    "context_replay_bench": ("pipeline", "", ""),
    "conversations": ("teams", "", "docket.teams.conversations"),
    "cooperative_run_cancellation": ("tasks", "", ""),
    "data_layer": ("teams", "", "docket.teams.fleet"),
    "delete_bind_unbind": ("interfaces", "", CMD + "setup_notify"),
    "diff_probe": ("hops", "", "docket.hops.workspace.worktree"),
    "dispatch_heartbeat_and_conversation_sync": ("tasks", "", SW),
    "dispatch_hop_instructions": ("tasks", "", ""),
    "dispatch": ("tasks", "", ""),
    "dispatch_run_records": ("tasks", "", ""),
    "docket_driver": ("hops", "", "docket.hops.application.driver"),
    "doctor_ledger_drift": ("interfaces", "", CMD + "setup_check"),
    "edit_snapshot": ("interfaces", "", CMD + "status"),
    "enqueue_channel": ("tasks", "", ""),
    "envelope_commands": ("tasks", "", ""),
    "escape_matrix": ("sandbox", "", ""),
    "evidence_surfaces": ("tasks", "", ""),
    "exporters_cli": ("observability", "", ""),
    "external_gate": ("hops", "", "docket.hops.gates.post_hop"),
    "gate_failed_carryover": ("hops", "", "docket.hops.application.compose"),
    "gates_policies_approve_deny": ("governance", "", "docket.governance.policy"),
    "generalized_gates": ("tasks", "", SW),
    "guardrail_metrics": ("interfaces", "", "docket.interfaces.http.routes.metrics"),
    "handoff_artifacts": ("hops", "", "docket.hops.application.compose"),
    "high_risk_enforcement": ("governance", "", "docket.governance.security"),
    "hop_carryover": ("hops", "", "docket.hops.application.compose"),
    "hop_handoff_diff": ("tasks", "", ""),
    "hop_task_root": ("tasks", "", ""),
    "implementer_worktree_isolation": ("interfaces", "", ""),
    "init_leaves_alone": ("interfaces", "", ""),
    "init_refuses_unstorable": ("interfaces", "", ""),
    "install": ("interfaces", "", CMD + "setup"),
    "jail_landlock": ("sandbox", "", ""),
    "lights_out_profile": ("governance", "", "docket.governance.profile"),
    "list_info_cost_commands": (
        "interfaces",
        "bare_docket_guide",
        "docket.interfaces.cli.render.help",
    ),
    "llm_port": ("models", "", "docket.models.adapters.openai_http"),
    "mcp_client": ("agent", "", ""),
    "mcp_optional_dep": ("interfaces", "", CMD + "mcp"),
    "mcp_server": ("interfaces", "", CMD + "mcp"),
    "mcp_servers_cli": ("interfaces", "", CMD + "setup_mcp"),
    "mcp_stdio_jail": ("agent", "", ""),
    "mcp_stdio_root": ("agent", "", ""),
    "mcp_transport_contract": ("interfaces", "", CMD + "mcp"),
    "models_audit": ("interfaces", "", CMD + "setup_model"),
    "network_lockdown": ("sandbox", "", ""),
    "operator_loop_seams": ("product", "", "docket.operator.channel"),
    "operator_schemas_v11": ("kernel", "operator_schemas", ""),
    "otlp_export": ("hops", "", ""),
    "pipeline_cli": ("interfaces", "", CMD + "pod"),
    "pipeline_per_task": ("tasks", "", ""),
    "pod_blueprint_provisioning": ("teams", "", "docket.teams.blueprints"),
    "pod_cache_dir": ("agent", "", ""),
    "pod_config_settings": ("interfaces", "", ""),
    "pod_membership_from_meta": ("teams", "", ""),
    "pod_memory_controls": ("interfaces", "", ""),
    "pod_memory": ("teams", "", ""),
    "pod_memory_rules": ("teams", "", ""),
    "pod_provisioning": ("teams", "", "docket.teams.pod_provisioning"),
    "pod_reset": ("interfaces", "", ""),
    "pod_resources": ("teams", "", "docket.teams.resources"),
    "pod_roles_from_archetypes": ("teams", "", "docket.teams.pod"),
    "pod_role_workspace_parity": ("teams", "", "docket.teams.member_workspace"),
    "pod_rules_every_screen": ("tasks", "", ""),
    "pod_show": ("interfaces", "", ""),
    "policy_engine": ("governance", "", "docket.governance.policy"),
    "pre_tool_call_policy": ("agent", "", ""),
    "process_non_dumpable": ("platform", "", ""),
    "profile_scope_models": ("interfaces", "", CMD + "setup_model"),
    "prompt_layers": ("teams", "", ""),
    "provider_agnosticism": ("models", "", "docket.models.selection"),
    "provider_registration": ("models", "", "docket.models.provider_lifecycle"),
    "provisioning_contract": ("teams", "", "docket.teams.provisioning"),
    "prune_task_worktrees": ("teams", "", ""),
    "recipe_mcp_servers": ("teams", "", ""),
    "recipe_methodologies": ("teams", "", ""),
    "recipes": ("teams", "", ""),
    "repo_map": ("hops", "", ""),
    "retries_and_timeouts": ("tasks", "", SW),
    "reviewed_digest_files": ("governance", "", ""),
    "reviewer_gate": ("pipeline", "", "docket.pipeline.application.executor"),
    "role_tools_and_identity": ("agent", "", "docket.agent.tools.registry"),
    "run_cancellation": ("tasks", "", ""),
    "runs_cli": ("interfaces", "", CMD + "task"),
    "runtime_driver": ("agent", "", ""),
    "runtime_execution_envelope": ("product", "", "docket.bootstrap"),
    "sandboxed_exec": ("agent", "", ""),
    "serve_dispatch_webhook": ("interfaces", "", ""),
    "serve_inbox_options": ("interfaces", "", SRV),
    "serve_pods_config": ("interfaces", "", SRV),
    "serve_pods_corrections": ("interfaces", "", ""),
    "serve_pods_endpoint": ("interfaces", "", SRV),
    "serve_reattach": ("interfaces", "", SRV),
    "serve_status": ("interfaces", "", ""),
    "serve_stop_signals": ("interfaces", "", ""),
    "serve_task_answer_endpoint": ("interfaces", "", SRV),
    "serve_task_lifecycle": ("interfaces", "", ""),
    "serve_task_pregrant_endpoint": ("interfaces", "", SRV),
    "serve_tasks_endpoint": ("interfaces", "", ""),
    "store_recovery": ("platform", "", ""),
    "system_adapter": ("platform", "", ""),
    "task_check_changed": ("tasks", "", ""),
    "task_credentials": ("sandbox", "", ""),
    "task_prepare": ("hops", "", ""),
    "task_restrictions": ("tasks", "", ""),
    "task_worktree_base_ref": ("teams", "", ""),
    "task_worktrees": ("tasks", "", ""),
    "task_worktree_views": ("interfaces", "", ""),
    "telegram_channel": ("interfaces", "", "docket.interfaces.telegram.bot"),
    "trace_audit": ("governance", "", "docket.governance.audit"),
    "trace_retention": ("observability", "", ""),
    "two_homes_in_one_process": ("kernel", "", ""),
    "validate_cli": ("interfaces", "", ""),
    "verify_gate_cwd_resolution": ("hops", "", "docket.hops.gates.post_hop"),
    "verify_gate": ("hops", "", "docket.hops.gates.post_hop"),
    "workflow_smoke": ("product", "", "docket.__main__"),
}

_SUBJECT = re.compile(r'^SUBJECT = "[^"]+"', re.M)
_PARENTS = re.compile(r"(Path\(__file__\)(?:\.resolve\(\))?)\.parents\[2\]")


def _git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def move(folder: str) -> list[str]:
    done = []
    for old, (dest, new, subject) in TABLE.items():
        if dest != folder:
            continue
        src = INTEG / f"test_{old}.py"
        if not src.exists():
            continue
        target_dir = INTEG / dest
        target_dir.mkdir(exist_ok=True)
        target = target_dir / f"test_{new or old}.py"
        _git("mv", str(src), str(target))
        text = target.read_text(encoding="utf-8")
        if subject:
            text, n = _SUBJECT.subn(f'SUBJECT = "{subject}"', text, count=1)
            assert n == 1, old
        text = _PARENTS.sub(r"\1.parents[3]", text)
        target.write_text(text, encoding="utf-8")
        done.append(f"{old} -> {dest}/{target.name}")
    return done


if __name__ == "__main__":
    for line in move(sys.argv[1]):
        print(line)
