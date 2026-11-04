"""The pod and member reports behind ``docket pod show`` and ``GET /pods/<p>``.

Read-only readers that compose existing resolvers into one report. See
specs/data/cli-json-shapes.spec.md, "`docket pod show --json`".
"""

from __future__ import annotations

import hashlib
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic.alias_generators import to_camel

from docket.governance import policy as _policy
from docket.hops.application import builtin_tools as _builtin_tools
from docket.hops.application import capabilities as _capabilities
from docket.hops.application import executor as _executor
from docket.hops.application import steps as _steps
from docket.hops.application.usage import pod_counted_tokens
from docket.hops.domain.gate_decisions import window_start
from docket.hops.gates import profile as _profile
from docket.hops.gates.pre_hop import hop_model
from docket.kernel import clock as _clock
from docket.kernel.errors import DispatchError
from docket.kernel.home import current_home
from docket.models import catalog as _provider
from docket.models import provider_lifecycle as _provider_lifecycle
from docket.models.application import endpoint as _endpoint
from docket.observability import exporter as _exporter
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain import spec as _pipeline
from docket.pipeline.domain.spec import bounded_routes
from docket.platform import read_json
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.state import Status
from docket.teams import fleet as _fleet
from docket.teams import identity as _identity
from docket.teams import mcp_servers as _mcp_servers
from docket.teams import model_selection as _models
from docket.teams import network_posture as _network_posture
from docket.teams import pod as _pod
from docket.teams import pod_settings as _pod_settings
from docket.teams import records as _records
from docket.teams import role_composer as _role_composer
from docket.teams import roles as _archetypes
from docket.teams import settings as _settings
from docket.teams.apply import lock as _lock
from docket.teams.apply import needs as _needs
from docket.teams.apply import review as _review
from docket.teams.models import AgentKind, AgentMeta, WorkspaceKind
from docket.teams.workspace import skills as _skills


def network_text(net: dict[str, Any]) -> str:
    """The network line, worded by ``teams.network_posture`` from the report's own ``enforced``
    so it never claims a cut network the report says is open."""
    posture = _network_posture.network_posture(
        str(net["mode"]), str(net["scope"]), jailed=bool(net["enforced"])
    )
    return posture.line


def _network_report(project: str) -> dict[str, Any]:
    """``network`` as the reports and ``GET /pods`` carry it: the effective mode, its scope and
    whether a jail that runs enforces it."""
    mode, scope = _pod_settings.effective_network(project or None)
    posture = _network_posture.network_posture(mode, scope, jailed=_network_posture.jail_enforces())
    return {"mode": mode, "scope": scope, "enforced": posture.enforced}


def _work_dir_fields(project: str) -> dict[str, str]:
    """``workDir`` for a ``workdir`` pod (its Lead's folder), nothing for a ``codebase`` pod."""
    if _pod_settings.workspace_kind(project) != WorkspaceKind.workdir:
        return {}
    return {"workDir": _fleet.meta_get(_pod.member_id(project, "lead"), "workDir", "") or ""}


def _roots_for(agent_id: str, meta: AgentMeta) -> tuple[Path, ...]:
    """The containment roots a standalone turn would resolve for *agent_id*: codebase >
    work_dir > the agent's own workspace (mirrors ``hops/application/driver.py``'s
    ``_resolve_roots``, reproduced for display; a dispatched task's worktree is per task)."""
    if meta.codebase:
        return (Path(meta.codebase),)
    if meta.work_dir:
        return (Path(meta.work_dir),)
    return (current_home().workspace_dir(agent_id),)


_SOURCE_SCOPE: dict[str, str] = {
    "built-in": "built-in",
    "starter": "built-in",
    "operator": "operator",
}


def _scope_label(source: str) -> str:
    """Map ``ArchetypeRegistry.source_of``'s ``built-in | starter | operator | pod:<p>``
    onto this report's ``built-in | operator | pod`` role provenance."""
    if source.startswith("pod:"):
        return "pod"
    return _SOURCE_SCOPE.get(source, "")


def _policies_for_role(role: str, project: str) -> list[dict[str, str]]:
    """Installed policies whose ``applies_to`` covers *role*, read from
    ``policy_files(project)``, each carrying its ``scope`` (``pod`` for this pod's own
    ``config/policies/`` directory, else ``global``)."""
    pod_policies_dir = current_home().pod_config_dir(project) / "policies" if project else None
    matched: list[dict[str, str]] = []
    for path in _policy.policy_files(project):
        try:
            doc: dict[str, Any] = _policy.read_policy(path)
        except Exception:
            continue
        if _policy.validate_policy(path):
            continue
        applies = doc.get("applies_to") or []
        if "*" in applies or role in applies:
            is_pod_file = pod_policies_dir is not None and path.parent == pod_policies_dir
            scope = "pod" if is_pod_file else "global"
            matched.append(
                {
                    "id": str(doc.get("id", path.stem)),
                    "hook": str(doc.get("hook", "")),
                    "action": str(doc.get("action", "")),
                    "scope": scope,
                }
            )
    return matched


def _mcp_servers_report(
    pod_settings: _pod_settings.PodSettings | None, project: str = ""
) -> list[dict[str, Any]]:
    """Every MCP server a turn would load: the pod's own ``mcpServers`` selection when
    set (``scope: "pod"``), else the full catalog -- global servers (``scope: "global"``)
    and the pod's own pod-scoped ones (``scope: "pod"``)."""
    catalog = sorted(_mcp_servers.load_mcp_servers(project), key=lambda s: s.name)
    selected = pod_settings.mcp_servers if pod_settings is not None else None
    if selected is None:
        own = {s.name for s in _mcp_servers.load_pod_mcp_servers(project)} if project else set()
        return [
            {
                "name": s.name,
                "kind": s.kind,
                "scope": "pod" if s.name in own else "global",
            }
            for s in catalog
        ]
    by_name = {s.name: s for s in catalog}
    return [
        {"name": name, "kind": by_name[name].kind, "scope": "pod"}
        for name in sorted(selected)
        if name in by_name
    ]


def _pod_settings_report(
    settings: _pod_settings.PodSettings, project: str
) -> dict[str, dict[str, Any]]:
    """Every ``PodSettings`` key's effective value and source ("set"/"default") --
    the ``settings`` object of ``docket pod show --json``."""
    report: dict[str, dict[str, Any]] = {}
    for key in _pod_settings.PodSettings.KEYS:
        value, source = settings.value_and_source(key, project)
        report[key] = {"value": value, "source": source}
    if settings.pipeline:
        report["maxReworkCycles"] = {
            "value": _bound_rework_maxes(project),
            "source": "pipeline",
        }
    return report


def _bound_rework_maxes(project: str) -> str:
    """The rework bounds the bound pipeline itself carries, ``<step>:<max>`` comma-joined in step
    order (the verdict gate's rework edge and every ``on:`` route with a ``max``), ``none`` when
    it carries none or the bound copy cannot be read."""
    try:
        spec = _steps.effective_pipeline(project, None)
    except DispatchError:
        return "none"
    found = [
        f"{step.id}:{route.max}"
        for step in spec.steps
        for route in bounded_routes(step.id, step.gate, step.on)
    ]
    return ",".join(found) or "none"


def _config_of_record_report(
    settings: _pod_settings.PodSettings | None, project: str
) -> dict[str, str]:
    """``configSource``/``configDigest`` and ``drift`` (``applied.lock``: the source's lock or an
    applied overlay file no longer matches)."""
    report = {"configSource": "", "configDigest": "", "drift": ""}
    if settings is not None and settings.config_source:
        report = {
            "configSource": settings.config_source,
            "configDigest": settings.config_digest,
            "drift": _lock.drift(project, settings.config_source, settings.config_digest),
        }
    return report


def _provider_report(model: str) -> dict[str, Any]:
    """Where *model* resolves: catalog scope, dialect, base URL, the credential's
    name/source and the model's limits and where each came from -- the provenance ``resolve_endpoint``
    itself does not report. See model-profiles.spec.md "Provider catalog" 7."""
    provider_name, _, model_id = model.partition("/")
    if not model_id:
        provider_name, model_id = "", model

    catalog = _provider.load_catalog()
    spec = catalog.get(provider_name) if provider_name else None
    endpoint = _endpoint.resolve_endpoint(model)

    if spec is not None:
        credential_name = spec.auth.credentials[0] if spec.auth.credentials else ""
        _value, credential_source = _provider.resolve_credential(spec)
        found = _provider.resolve_limits(spec, model_id)
        return {
            "name": spec.name,
            "scope": catalog.source_of(provider_name),
            "dialect": spec.dialect,
            "baseUrl": spec.base_url,
            "credential": {"name": credential_name, "source": credential_source},
            "model": {
                "id": model_id,
                "contextWindow": found.context_window,
                "maxTokens": found.max_output,
                "contextWindowSource": found.context_window_source,
                "maxTokensSource": found.max_output_source,
                "source": found.source,
                "observedAt": found.observed_at,
            },
        }

    return {
        "name": provider_name,
        "scope": "",
        "dialect": "openai-chat",
        "baseUrl": endpoint.base_url if endpoint else None,
        "credential": {
            "name": "",
            "source": "env" if endpoint is not None and endpoint.api_key else "none",
        },
        "model": {
            "id": model_id,
            "contextWindow": endpoint.context_window_tokens if endpoint else None,
            "maxTokens": endpoint.max_output_tokens if endpoint else None,
            "contextWindowSource": "unknown",
            "maxTokensSource": "unknown",
            "source": "unknown",
            "observedAt": "",
        },
    }


def _skills_report(project: str, roots: tuple[Path, ...]) -> list[dict[str, str]]:
    """Every skill a live turn's ``# Skills`` prompt section would list: ``name`` and
    ``scope`` (``codebase | pod | global``), the same three-scope, nearest-wins discovery
    ``agent.identity`` composes from (ADR 0013 §3 rule 8)."""
    codebase_root = roots[0] if roots else None
    discovered = _skills.discover_skills(project, codebase_root)
    return [{"name": name, "scope": discovered[name].scope} for name in sorted(discovered)]


def _exporters_report() -> list[dict[str, Any]]:
    """Every catalog exporter's activation state and today's health counters -- global, not
    per-agent (an exporter has no per-pod scope; see observability-export.spec.md
    "Activation")."""
    catalog = _exporter.load_catalog()
    health = _exporter.read_health()
    report: list[dict[str, Any]] = []
    for name in sorted(catalog.entries):
        spec = catalog.entries[name]
        state, _missing = _exporter.activation_state(spec, health.get(name))
        _values, credential_source = _exporter.resolve_credentials(spec)
        record = health.get(name, {})
        report.append(
            {
                "name": name,
                "dialect": spec.dialect,
                "state": state,
                "scope": catalog.source_of(name),
                "credentialSource": credential_source,
                "privacy": {"label": spec.privacy_label, "classes": sorted(spec.privacy_classes)},
                "exported": record.get("exported", 0),
                "dropped": record.get("dropped", 0),
                "failed": record.get("failed", 0),
                "lastError": record.get("lastError", ""),
            }
        )
    return report


def member_report(agent_id: str) -> dict[str, Any]:
    """Compose one member's effective configuration. Raises ``DispatchError``/
    ``PodSettingsError`` unchanged when this pod's stored settings are invalid --
    never silently substitutes a default."""
    raw = read_json(current_home().meta_path(agent_id))
    meta = AgentMeta.model_validate(raw) if raw else AgentMeta(kind=AgentKind.project)
    role = str(raw.get("role", ""))
    project = _pod.pod_of(agent_id) or ""

    model = str(raw.get("model") or "") or current_home().default_model
    model_source = _model_source(role, project)
    readiness = _provider_lifecycle.model_readiness(model)
    provider_report = _provider_report(model)

    roots = _roots_for(agent_id, meta)
    composition = _identity.compose_agent_prompt(
        agent_id,
        project_roots=roots,
        context_window_tokens=readiness.context_window,
        max_output_tokens=readiness.max_output,
    )

    # Never substitute a default for a bad stored value -- raised here, before any of the resolvers below that also read
    # this pod's settings, so every value below reflects a validated PodSettings.
    pod_settings = _pod_settings.PodSettings.load_for(project) if project else None

    role_registry_scope = _archetypes.load_registry(project)
    role_scope = _scope_label(role_registry_scope.source_of(role))

    base_registry = _builtin_tools.builtin_registry(project)
    role_registry = (
        _role_composer.registry_for_role(base_registry, role, project) if role else base_registry
    )
    pod_denied = set(pod_settings.denied_tools) if pod_settings is not None else set()
    pod_denied |= {t for name in pod_denied for t in _role_composer.SERVED_TOOLS.get(name, ())}
    denied = [
        {"name": name, "scope": "pod" if name in pod_denied else role_scope}
        for name in sorted(set(base_registry.names()) - set(role_registry.names()))
    ]
    mcp_servers = _mcp_servers_report(pod_settings, project)

    pod_settings_report = _pod_settings_report(pod_settings, project) if pod_settings else None
    pipeline = {"source": _steps.effective_pipeline_source(project)} if project else None
    config_of_record = _config_of_record_report(pod_settings, project)
    if pod_settings is not None and roots:
        pi_files, pi_source = _identity.project_instruction_files(pod_settings, roots[0])
    else:
        pi_files, pi_source = (), ""
    skills_report = _skills_report(project, roots)

    return {
        "id": agent_id,
        "workspace": str(current_home().workspace_dir(agent_id)),
        "role": role,
        "roleScope": role_scope,
        "pod": project,
        "model": {"value": model, "source": model_source},
        "endpoint": {
            "baseUrl": readiness.base_url,
            "ready": readiness.ready,
            "contextWindowTokens": readiness.context_window,
            "maxOutputTokens": readiness.max_output,
            "issue": readiness.issue,
        },
        "provider": provider_report,
        "prompt": {
            "budgetTokens": composition.budget_tokens,
            "budgetSource": composition.budget_source,
            "sections": [
                {"name": s.name, "bytes": s.bytes, "status": s.status} for s in composition.sections
            ],
        },
        "tools": {
            "allowed": sorted(role_registry.names()),
            "denied": denied,
            "mcpServers": mcp_servers,
        },
        "policies": _policies_for_role(role, project),
        "pipeline": pipeline,
        "podSettings": pod_settings_report,
        "network": _network_report(project),
        "projectInstructions": {"files": list(pi_files), "source": pi_source},
        "skills": skills_report,
        "exporters": _exporters_report(),
        **config_of_record,
    }


def _model_source(role: str, project: str) -> str:
    """Where a member's model comes from: the pod's own role overlay, else the role policy."""
    if project and role and _archetypes.load_registry(project).source_of(role).startswith("pod:"):
        return "pod overlay"
    return "policy"


def caller_default() -> Literal["wait", "park"]:
    """The approval default an unset ``approvalMode`` takes for this caller: ``wait`` on a
    TTY, ``park`` without one."""
    return "wait" if sys.stdin.isatty() else "park"


def pod_report(project: str) -> dict[str, Any]:
    """The pod as one report; raises ``DispatchError``/``PodSettingsError`` when it is missing
    or its stored settings are invalid."""
    _pod.pod_pipeline(project)
    settings = _pod_settings.PodSettings.load_for(project)
    ids = [a.id for a in _fleet.list_agents()]
    members = [
        {
            "id": mid,
            "role": role,
            "model": {
                "value": _fleet.meta_get(mid, "model", "") or current_home().default_model,
                "source": _model_source(role, project),
            },
            "workspace": str(current_home().workspace_dir(mid)),
            "verifyCmd": _fleet.meta_get(mid, "verifyCmd", ""),
        }
        for mid, role, _idx in _pod.members_of(ids, project)
    ]
    caller = caller_default()
    approval = _settings.pod_approval_mode(project, caller_default=caller)
    record = _config_of_record_report(settings, project)
    return {
        "pod": project,
        "blueprint": _blueprint(project),
        "members": members,
        "settings": _pod_settings_report(settings, project),
        "approvalMode": {
            "effective": approval,
            "source": "set" if _settings.pod_approval_mode_is_set(project) else "unset",
        },
        "pipeline": _pipeline_report(project),
        "network": _network_report(project),
        "fetchDomains": list(settings.fetch_domains),
        "needs": [line.wire() for line in _pod_needs(project, settings)],
        "delivers": _delivers(project),
        "methods": _methods(project, settings),
        "budget": _budget_fields(project, settings),
        **_work_dir_fields(project),
        **record,
    }


def _budget_fields(project: str, settings: _pod_settings.PodSettings) -> dict[str, Any]:
    """``budget``: the cap, the tokens the gate would count now over the window, and where the
    window began (operator-api.spec.md, "Pod answers")."""
    since = window_start(settings.budget_window, _clock.now())
    return {
        "tokens": settings.budget_tokens,
        "used": pod_counted_tokens(project)
        if since is None
        else pod_counted_tokens(project, since),
        "window": settings.budget_window,
        "windowStart": None if since is None else since.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _pod_needs(project: str, settings: _pod_settings.PodSettings) -> tuple[_needs.NeedLine, ...]:
    """The pod's recorded needs, computed as the pod is now; a recorded name this build does not
    know is left out."""
    return _needs.readiness(project, tuple(n for n in settings.needs if n in _needs.NEEDS))


def _delivers(project: str) -> list[str]:
    """What a task on *project* hands back: a branch or a report, then its records."""
    kind = _pod_settings.workspace_kind(project)
    delivers = ["report" if kind == WorkspaceKind.workdir else "branch"]
    if _records.pod_record_sets(project)[0]:
        delivers.append("records")
    return delivers


def _methods(project: str, settings: _pod_settings.PodSettings) -> list[dict[str, Any]]:
    """The pipelines a task may name, one per name from the file a claim resolves it to."""
    roster = _pod.pod_full_roster(project)
    registry = _archetypes.load_registry(project)
    methods: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name, path, source in _steps.task_pipeline_files(project):
        if name in seen:
            continue
        seen.add(name)
        method: dict[str, Any] = {"name": name, "source": source, "missingRoles": []}
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            methods.append({**method, "error": str(exc), "default": False})
            continue
        loaded = _pipeline.load_pipeline(text, roles=registry.names())
        if loaded.spec is None:
            method["error"] = "; ".join(loaded.errors)
        else:
            plan = _orch.resolve_plan(loaded.spec, roster, registry=registry)
            method["missingRoles"] = list(_steps.unstaffed_steps(plan))
        method["default"] = hashlib.sha256(text.encode("utf-8")).hexdigest() == settings.pipeline
        methods.append(method)
    return methods


def _blueprint(project: str) -> str:
    """The shape *project* was provisioned with (its Lead's ``blueprint``), ``""`` without one."""
    return _fleet.meta_get(_pod.member_id(project, "lead"), "blueprint", "") or ""


def _pipeline_report(project: str) -> dict[str, Any]:
    """``pipeline``: where the effective pipeline comes from and, when it resolves, its steps."""
    report: dict[str, Any] = {"source": _steps.effective_pipeline_source(project)}
    try:
        nodes = _executor.resolve_pipeline_steps(project, None)[0]
    except DispatchError:
        return report
    report["steps"] = [_step_view(node) for node in nodes]
    return report


def _step_view(node: _orch.PlannedNode) -> dict[str, Any]:
    """One step as data (cli-json-shapes.spec.md, "`docket pod show --json`")."""
    if isinstance(node, _orch.PlannedGroup):
        branches = [_step_view(child) for child in node.children if not child.skipped]
        view = _step_fields(node.step_id, "parallel", None, None, None, [])
        return {**view, "steps": branches}
    kind = _step_kind(node)
    agent = kind == "agent" and node.member_id is not None
    member = node.member_id or ""
    routes = bounded_routes(node.step_id, node.gate, node.on)
    return _step_fields(
        node.step_id,
        kind,
        (node.role or node.archetype or _fleet.meta_get(member, "role", "")) if agent else None,
        _models.model_class_of(hop_model(node, member)) if agent else None,
        node.gate.type if node.gate is not None else None,
        [{"when": list(r.when), "to": r.to, "max": r.max} for r in routes],
    )


def _step_kind(node: _orch.PlannedUnit) -> str:
    if node.run is not None:
        return "command"
    if node.input is not None:
        return "ask"
    if node.wait is not None or node.until is not None:
        return "wait"
    return "agent"


def _step_fields(
    step_id: str,
    kind: str,
    role: str | None,
    model_class: str | None,
    gate: str | None,
    rework: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": step_id,
        "kind": kind,
        "role": role,
        "modelClass": model_class,
        "gate": gate,
        "rework": rework,
    }


def _codebase(project: str) -> str:
    return _fleet.meta_get(_pod.member_id(project, "lead"), "codebase", "") or ""


def task_counts(project: str) -> dict[str, int]:
    """The queue counts ``status --json`` prints under ``tasks``: one per ``Status``, keyed by its
    camelCase name."""
    counts = Counter(r.status for r in TaskRepository.for_pod(project).list())
    return {to_camel(status.value): counts[status] for status in Status}


def project_violations(
    project: str, spec: _pipeline.PipelineSpec | None = None
) -> list[_profile.Violation]:
    """The pod's violations under ``lights-out``, with its own pipeline planned for the facts
    (``doctor`` and ``status``); ``[]`` when its effective profile is attended."""
    if _profile.effective_profile(project) != _profile.LIGHTS_OUT:
        return []
    return _profile.project_violations(project, _executor.resolve_pipeline_steps(project, spec)[0])


def lights_out_report() -> dict[str, list[_profile.Violation]]:
    """Every dispatchable pod whose effective profile is ``lights-out``, with its violations; empty
    on a fleet that records nothing (the usual case)."""
    report: dict[str, list[_profile.Violation]] = {}
    for project in _queue.dispatchable_pods():
        if _profile.effective_profile(project) == _profile.LIGHTS_OUT:
            report[project] = project_violations(project)
    return report


def pod_summary(project: str) -> dict[str, Any]:
    """One row of ``GET /pods``: name, codebase, workspace kind, member count, effective profile,
    queue and budget; a pod whose stored settings are invalid carries ``error`` in place of
    ``budget``."""
    ids = [a.id for a in _fleet.list_agents()]
    budget: dict[str, Any]
    try:
        budget = {"budget": _budget_fields(project, _pod_settings.PodSettings.load_for(project))}
    except _pod_settings.PodSettingsError as exc:
        budget = {"error": str(exc)}
    return {
        "name": project,
        "codebase": _codebase(project),
        "workspaceKind": str(_pod_settings.workspace_kind(project)),
        "blueprint": _blueprint(project),
        "members": len(_pod.members_of(ids, project)),
        "profile": _profile.effective_profile(project),
        "network": _network_report(project),
        "queue": task_counts(project),
        **budget,
        **_work_dir_fields(project),
        **_pause_fields(project),
    }


def _pause_fields(project: str) -> dict[str, Any]:
    """``paused`` always; ``pausedReason`` only while the Lead is paused (operator-api.spec.md,
    "Pod answers")."""
    lead = _pod.member_id(project, "lead")
    if not AgentMeta.coerce_paused(_fleet.meta_get(lead, "paused", "")):
        return {"paused": False}
    return {"paused": True, "pausedReason": _fleet.meta_get(lead, "pausedReason", "") or "budget"}


def pod_detail(project: str) -> dict[str, Any]:
    """``pod_report`` plus the profile verdict, the pipeline source, the workspace kind, the repo
    config dir and the read-only jail grants the pod keeps."""
    effective = _profile.effective_profile(project)
    verdict = (
        _profile.as_json(project_violations(project))
        if effective == _profile.LIGHTS_OUT
        else {"name": effective, "violations": []}
    )
    report = pod_report(project)
    members = [
        {**m, "capabilities": _capabilities.member_capabilities(project, m["role"])}
        for m in report["members"]
    ]
    return {
        **report,
        "members": members,
        "profile": verdict,
        "pipelineSource": _steps.effective_pipeline_source(project),
        "workspaceKind": str(_pod_settings.workspace_kind(project)),
        "repoConfigDir": _repo_config_dir(project),
        "readOnly": [str(path) for path in _pod_settings.effective_read_only(project)],
        **_pause_fields(project),
    }


def _repo_config_dir(project: str) -> str:
    """The pod's configuration-of-record directory, `""` for a pod with no codebase."""
    codebase = _codebase(project)
    return str(_review.repo_config_dir(Path(codebase), project)) if codebase else ""
