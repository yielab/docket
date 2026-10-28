"""The free helpers ``DocketDriver`` composes a turn from: pod settings, roots, budgets,
policy scope, loop config and the trace callback. Moved out of ``driver.py`` unchanged."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from docket.agent import loop as _loop
from docket.agent.ports import (
    DOCKET_TASK_DENIED_TOOLS,
    DOCKET_TASK_NETWORK,
    DOCKET_TASK_POLICIES,
    PIPELINE_WORKTREE_ENV,
    ChatBackend,
    TurnResult,
)
from docket.agent.tools import mcp_tools as _mcp
from docket.agent.tools import mcp_types as _mcp_types
from docket.agent.tools.registry import Pregrant, ToolContext, ToolRegistry
from docket.governance import policy as _policy
from docket.hops.application.base_view import base_commit_view
from docket.kernel.errors import DispatchError
from docket.kernel.gate import DEFAULT_MAX_CONSULTATIONS
from docket.kernel.home import current_home
from docket.models.catalog import ModelProfile
from docket.observability import trace as _trace
from docket.platform import read_json
from docket.tasks.application import runs as _runs
from docket.tasks.application.queue import touch_claim
from docket.tasks.application.repository import TaskRepository
from docket.teams import fleet as _fleet
from docket.teams import mcp_servers as _mcp_servers
from docket.teams import pod as _pod
from docket.teams import pod_settings as _pod_settings
from docket.teams.models import AgentMeta
from docket.teams.roles import BUILTIN_TOOL_KINDS
from docket.teams.workspace import repo_view as _repo_view


# Reads and validates *only* the mcpServers meta key, through `PodSettings.coerce` --
# not `PodSettings.load_for`, which validates every stored key at once the way
# `_resolve_allow_commands` above deliberately avoids for `allowCommands`. This
# turn's live path must not refuse over an unrelated stored key (e.g. a hand-edited
# `turnTimeoutS`); only a bad `mcpServers` value itself is this function's concern.
# Unlike `allowCommands`'s fail-open pattern, a bad value here *is* re-raised as
# `DispatchError`, never swallowed: `coerce`'s validator checks every stored name
# against the live MCP catalog on every read, not only at `pod set` time, so a
# selection valid when written but since renamed/removed surfaces here as this
# pod's own stale configuration -- not an ordinary turn failure like an
# unreachable/hung/malformed remote server (which `load_mcp_tools` already
# degrades to "unavailable" for, never raising).
def _pod_mcp_selection(project: str) -> tuple[str, ...] | None:
    """*project*'s own `mcpServers` pod setting, or ``None`` (load every configured
    server) for a non-pod caller or an unset setting."""
    if not project:
        return None
    lead_id = _pod.member_id(project, "lead")
    raw = _fleet.meta_get(lead_id, "mcpServers", "")
    if not raw:
        return None
    try:
        coerced = _pod_settings.PodSettings.coerce("mcpServers", raw, project=project)
    except _pod_settings.PodSettingsError as exc:
        raise DispatchError(str(exc)) from exc
    return tuple(str(coerced).split(","))


def _stdio_launch(ctx: ToolContext) -> _mcp_types.StdioLaunch:
    """How this turn starts stdio servers: its root, and its jail when the turn is isolated."""
    return _mcp_types.StdioLaunch(
        cwd=str(ctx.roots[0]),
        sandbox=ctx.sandbox,
        network=ctx.network,
        roots=ctx.roots,
        read_only=ctx.read_only,
    )


# Filters the shared catalog by *project*'s pod `mcpServers` selection (see
# `_pod_mcp_selection`, which is what actually raises `DispatchError` for a stale
# selection) before handing the rest to `load_mcp_tools`. ``None`` (no selection
# stored, or *project* names no pod) loads every configured server -- byte-for-byte
# the pre-selection behavior, including the zero-server fast path.
def _load_mcp_tools(
    registry: ToolRegistry,
    role: str,
    project: str = "",
    launch: _mcp_types.StdioLaunch | None = None,
) -> list[Any]:
    """Fold MCP servers' tools into *registry*; *launch* is how this turn starts stdio servers."""
    servers = _mcp_servers.load_mcp_servers(project)
    selection = _pod_mcp_selection(project)
    if selection is not None:
        servers = [s for s in servers if s.name in selection]
    if launch is None:
        return _mcp.load_mcp_tools(registry, servers=servers, role=role, project=project)
    return _mcp.load_mcp_tools(registry, servers=servers, role=role, project=project, launch=launch)


def _load_agent_meta(agent_id: str) -> AgentMeta | None:
    """Read *agent_id*'s ``.docket-meta.json`` via ``platform/store.py``. Returns ``(None, "")`` for
    a missing or malformed record rather than raising, per the Protocol's "never raises for an
    ordinary failure" contract."""
    raw = read_json(current_home().meta_path(agent_id))
    if not raw:
        return None
    try:
        return AgentMeta.model_validate(raw)
    except Exception:
        return None


def _resolve_roots(meta: AgentMeta | None, agent_id: str) -> tuple[Path, ...]:
    """The containment boundary ``dispatch_tool`` enforces: codebase > work_dir > the agent's
    own workspace (a dispatched task's worktree arrives as the pipeline root instead) --
    mirrors ``teams.pod.resolve_member_cwd``, extended here (not there) to also cover a
    ``workdir`` pod, which that helper's signature cannot express."""
    if meta is not None and meta.codebase:
        return (Path(meta.codebase),)
    if meta is not None and meta.work_dir:
        return (Path(meta.work_dir),)
    return (current_home().workspace_dir(agent_id),)


def _approval_timeout(raw: str | None) -> int | None:
    """A positive whole number of seconds from the env coordinate, else ``None``."""
    try:
        seconds = int(raw) if raw else 0
    except ValueError:
        return None
    return seconds if seconds > 0 else None


def _validated_pipeline_worktree(agent_id: str, env: dict[str, str] | None) -> str:
    """Accept a task root only when it is a directory under a same-pod Implementer's
    ``tasks/`` worktree directory."""
    candidate = str((env or {}).get(PIPELINE_WORKTREE_ENV, "")).strip()
    project = _pod.pod_of(agent_id)
    if not candidate or project is None:
        return ""
    candidate_path = Path(candidate).resolve()
    for registered in _fleet.list_agents():
        parsed = _pod.parse_member_id(registered.id, project)
        if parsed is None or parsed[0] != "implementer":
            continue
        tasks_dir = (current_home().projects_dir / registered.id / "tasks").resolve()
        if candidate_path.parent == tasks_dir and candidate_path.is_dir():
            return str(candidate_path)
    return ""


def _base_commit_view(
    pipeline_worktree: str, project: str, task_id: str
) -> _repo_view.RepoView | None:
    """The codebase's files at the task's recorded ``baseCommit``, or ``None`` (read the filesystem)
    without a task worktree, a base commit or recorded git dirs: without those, host-side git
    could not be kept off the worktree's own agent-writable ``.git`` file."""
    if not pipeline_worktree or not task_id:
        return None

    try:
        task = TaskRepository.for_pod(project).get(task_id)
    except Exception:  # an unreadable queue file must not fail the turn
        return None
    if task is None:
        return None
    return base_commit_view(task.worktree, pipeline_worktree)


def _resolve_allow_commands(agent_id: str) -> tuple[str, ...]:
    """This pod's ``allowCommands`` setting, or empty for a non-pod agent or an
    unreadable settings store -- fail closed, never grants more than SAFE_BINS."""
    project = _pod.pod_of(agent_id)
    if project is None:
        return ()
    try:
        return _pod_settings.PodSettings.load_for(project).allow_commands
    except _pod_settings.PodSettingsError:
        return ()


def _max_consultations(agent_id: str, raw: str | None) -> int:
    """This turn's ``consult`` budget: the caller's env value, else the agent's pod setting
    ``maxConsultationsPerTask``, else the default; a malformed value never raises."""
    if raw is not None:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    project = _pod.pod_of(agent_id)
    if project is not None:
        try:
            return _pod_settings.PodSettings.load_for(project).max_consultations_per_task
        except _pod_settings.PodSettingsError:
            pass
    return DEFAULT_MAX_CONSULTATIONS


def _consult_mode(agent_id: str, raw: str | None = None) -> str:
    """What a consult does: the mode the dispatch hop settled (*raw*) when it names one, else the
    agent's pod setting ``consultMode``; an agent outside a pod, or an unreadable settings store,
    parks -- the mode that waits for a person rather than deciding for one."""
    if raw in ("park", "decide"):
        return raw
    project = _pod.pod_of(agent_id)
    if project is None:
        return "park"
    try:
        return _pod_settings.PodSettings.load_for(project).consult_mode
    except _pod_settings.PodSettingsError:
        return "park"


def _turn_token_budget(raw: str | None) -> int:
    """*raw* as a positive measured-token ceiling, else the configured loop default -- a
    malformed value never raises here."""
    try:
        value = int(raw or "")
    except ValueError:
        return current_home().agent_loop_token_budget
    return value if value > 0 else current_home().agent_loop_token_budget


def _task_scope(registry: ToolRegistry, tool_env: dict[str, str]) -> AbstractContextManager[None]:
    """The policy scope for the turn's task restrictions; pops their coordinates from *tool_env*
    so no tool sees them (the network one was read by ``resolve_posture``)."""
    tool_env.pop(DOCKET_TASK_NETWORK, None)
    denied_raw = tool_env.pop(DOCKET_TASK_DENIED_TOOLS, None)
    policies_raw = tool_env.pop(DOCKET_TASK_POLICIES, None)
    return _policy.task_policies(_task_policy_documents(registry, denied_raw, policies_raw))


def _loop_config(
    backend: ChatBackend,
    timeout: int,
    token_budget: int,
    profile: ModelProfile,
    closing_tool: str,
) -> _loop.LoopConfig:
    """The turn loop's bounds: wall clock, measured-token budget and the endpoint's own windows,
    with the sampling and tool choice the model's profile declares."""
    context_window = getattr(backend, "context_window_tokens", None)
    max_output_tokens = getattr(backend, "max_output_tokens", None)
    return _loop.LoopConfig(
        wall_clock_timeout_s=float(timeout),
        token_budget=token_budget,
        context_window_tokens=(
            context_window if isinstance(context_window, int) and context_window > 0 else None
        ),
        max_tokens=(
            max_output_tokens
            if isinstance(max_output_tokens, int) and max_output_tokens > 0
            else None
        ),
        temperature=profile.sampling.temperature,
        top_p=profile.sampling.top_p,
        tool_choice=profile.tool_choice,
        closing_tool=closing_tool,
        profile=profile.name,
    )


def _task_policy_documents(
    registry: ToolRegistry, denied_raw: str | None, policies_raw: str | None
) -> list[dict[str, Any]]:
    """The turn's task-restriction policy documents: one block document for the denied tools
    (closed by kind, like ``registry_for_role``) plus the task's own, already-checked documents."""

    documents: list[dict[str, Any]] = []
    try:
        denied = [str(n) for n in json.loads(denied_raw)] if denied_raw else []
        if denied:
            kinds = {kind for name in denied if (kind := BUILTIN_TOOL_KINDS.get(name))}
            named = {
                name
                for name in registry.names()
                if (tool := registry.get(name)) is not None and tool.kind in kinds
            }
            documents.append(_policy.denied_tools_document(sorted({*denied, *named})))
        for doc in json.loads(policies_raw) if policies_raw else []:
            documents.append(_policy.checked_task_document(doc))
    except ValueError as exc:
        raise DispatchError(f"task restrictions refused: {exc}") from exc
    return documents


def _parse_pregrants(raw: str | None) -> tuple[Pregrant, ...]:
    """Decode ``DOCKET_PREGRANTS``' JSON list into ``Pregrant`` tuples; malformed or
    incomplete entries are dropped rather than raised, fail closed (a dropped entry
    just asks again instead of granting)."""
    if not raw:
        return ()
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return ()
    if not isinstance(parsed, list):
        return ()
    out: list[Pregrant] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        token = str(item.get("token", ""))
        tool = str(item.get("tool", ""))
        args_digest = str(item.get("argsDigest", ""))
        if token and tool and args_digest:
            out.append(Pregrant(token=token, tool=tool, args_digest=args_digest))
    return tuple(out)


def _build_on_process(
    project: str, session_key: str, role: str, task_id: str = ""
) -> Callable[[str, dict[str, Any]], None]:
    """A `ToolContext.on_process` for one turn: trace a tool call's process lifecycle and,
    while a dispatch run is current, register/clear its pgid against it so `docket task
    cancel` reaches a live subprocess. A started process of a turn that serves *task_id*
    refreshes the task's claim."""

    def _on_process(kind: str, data: dict[str, Any]) -> None:
        run_id = _runs.current_run_id()
        pgid = data.get("pgid")
        if kind == "started" and task_id:
            touch_claim(project, task_id)
        if run_id is not None and isinstance(pgid, int):
            if kind == "started":
                _runs.add_hop_pid(run_id, pgid)
            elif kind == "exited":
                _runs.remove_hop_pid(run_id, pgid)
        _trace.trace_event(project, session_key, role, f"process_{kind}", json.dumps(data))

    return _on_process


def _turn_result_from(result: _loop.AgentLoopResult) -> TurnResult:
    """The loop outcome as the driver port's ``TurnResult``, field for field plus the loop's own
    stop reason. ``cost_usd`` stays 0.0: tokens are measured, and turning them into dollars
    here would silently convert an estimate into a billing claim."""
    return TurnResult(
        result.ok,
        result.output,
        0.0,
        result.raw,
        result.error,
        failure_kind=result.failure_kind,
        retry_after_s=result.retry_after_s,
        usage=result.usage if result.usage.total_tokens else None,
        stop_reason=result.stop_reason,
        model=result.model,
        provider=result.provider,
    )
