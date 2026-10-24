from __future__ import annotations

import json as _json
import re as _re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from docket.agent import ports as _rd
from docket.hops.workspace.worktree import _hop_diff_probe
from docket.kernel import clock as _clock
from docket.kernel import handoff as _handoff
from docket.kernel.home import current_home
from docket.kernel.ports import process as _process
from docket.observability import trace as _trace
from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import plan as _orch
from docket.platform import PARK_TOKEN_PREFIX, parked_question, read_modify_write
from docket.tasks.domain.task import HopResult
from docket.teams import agent_memory as _mem
from docket.teams import conversations as _conv
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod
from docket.teams.settings import pod_task_list_path

# Injectable runner for tests (matches the RuntimeDriver port's ``run_turn`` signature). The
# 4th positional arg is always the *agent-turn* timeout (never the verify timeout).
Runner = Callable[[str, str, str, int, dict[str, str] | None], _rd.TurnResult]


def _gate_did_not_pass(verify: dict[str, Any] | None) -> bool:
    """Whether *verify* evidence records a gate that did not pass: a non-``pass`` label, or, for
    a mechanical gate (no label), a nonzero exit."""
    if verify is None:
        return False
    label = verify.get("label") or ("pass" if verify.get("exitCode") == 0 else "fail")
    return str(label).lower() != "pass"


def _is_gate_failure_carryover(hop: HopResult | None) -> bool:
    """Whether *hop* is a routed gate hop whose gate did not pass. A verdict rework hop never has
    ``next_step``, and a backward ``pass`` route carries no failure."""
    return hop is not None and hop.next_step is not None and _gate_did_not_pass(hop.verify)


def hop_env(member_id: str, role: str) -> dict[str, str] | None:
    """Subprocess env override: only an Implementer with an allocated port range gets one
    (real ``DOCKET_PORT_*``/``DOCKET_SCRATCH_DIR`` vars, not TOOLS.md prose); every other
    case returns ``None`` (inherit the parent env)."""
    if role != "implementer":
        return None
    port_start = _fleet.meta_get(member_id, "portRangeStart", "")
    if not port_start:
        return None
    port_count = _fleet.meta_get(member_id, "portRangeCount", "")
    scratch_dir = _fleet.meta_get(member_id, "scratchDir", "")
    return {
        "DOCKET_PORT_BASE": port_start,
        "DOCKET_PORT_COUNT": port_count,
        "DOCKET_SCRATCH_DIR": scratch_dir,
    }


def _hop_record(h: HopResult) -> dict[str, Any]:
    """Persisted shape of one hop (round-trips via ``_hop_from_record``; pod-dispatch.spec.md,
    "Structured handoff artifacts" and "Hop evidence"). ``artifact``/``verify``/``evidence`` are
    persisted alongside ``output``; ``verification_skipped`` stays an in-memory-only flag."""
    return {
        "role": h.role,
        "member": h.member_id,
        "ok": h.ok,
        "output": h.output,
        "costUsd": round(h.cost_usd, 6),
        "error": h.error,
        "attempts": h.attempts,
        # Falls back to `role` when unset — see HopResult.step_id.
        "stepId": h.step_id or h.role,
        "artifact": h.artifact.model_dump() if h.artifact is not None else None,
        "nextStep": h.next_step,
        "parked": h.parked,
        "verify": h.verify,
        "evidence": h.evidence,
        "usage": h.usage,
        "trace": h.trace,
        "repoFiles": h.repo_files or None,
        "model": h.model,
        "provider": h.provider,
    }


def _hop_from_record(rec: dict[str, Any]) -> HopResult:
    """Reconstruct a HopResult from a persisted hop record (for resume). A missing or invalid
    ``artifact``, ``verify``, or ``evidence`` key degrades each to its own default -- see
    pod-dispatch.spec.md ("Structured handoff artifacts", "Hop evidence")."""
    output = str(rec.get("output", ""))
    artifact_raw = rec.get("artifact")
    artifact: _handoff.HandoffArtifact | None = None
    if isinstance(artifact_raw, dict):
        try:
            artifact = _handoff.HandoffArtifact.model_validate(artifact_raw)
        except Exception:
            artifact = None
    next_step_raw = rec.get("nextStep")
    verify_raw = rec.get("verify")
    evidence_raw = rec.get("evidence")
    usage_raw = rec.get("usage")
    trace_raw = rec.get("trace")
    files_raw = rec.get("repoFiles")
    return HopResult(
        role=str(rec.get("role", "")),
        member_id=str(rec.get("member", "")),
        ok=bool(rec.get("ok", False)),
        output=output,
        cost_usd=float(rec.get("costUsd", 0.0) or 0.0),
        error=str(rec.get("error", "")),
        attempts=int(rec.get("attempts", 1) or 1),
        step_id=str(rec.get("stepId", "") or rec.get("role", "")),
        artifact=artifact,
        next_step=next_step_raw if isinstance(next_step_raw, str) else None,
        parked=bool(rec.get("parked", False)),
        verify=verify_raw if isinstance(verify_raw, dict) else None,
        evidence=evidence_raw if isinstance(evidence_raw, dict) else None,
        usage=usage_raw if isinstance(usage_raw, dict) else None,
        trace=trace_raw if isinstance(trace_raw, dict) else None,
        repo_files=dict(files_raw) if isinstance(files_raw, dict) else {},
        model=str(rec.get("model", "") or ""),
        provider=str(rec.get("provider", "") or ""),
    )


@dataclass
class _ResumePosition:
    """Where a (possibly resumed) run should continue: ``pipeline_index`` into
    ``runtime_steps``; ``rework_counts``/``route_counts`` (cycles consumed, keyed by
    gated step id, or by ``(step_id, outcome_label)`` for a route)."""

    pipeline_index: int
    rework_counts: dict[str, int]
    route_counts: dict[tuple[str, str], int] = field(default_factory=dict)
    rework_hop: HopResult | None = None


def _group_complete(node: _orch.PlannedGroup, prior: list[HopResult]) -> bool:
    """Whether every child of a parallel group has a persisted hop whose latest attempt
    succeeded; a failed or parked child re-runs the whole group on resume."""
    latest: dict[str, HopResult] = {}
    for hop in prior:
        latest[hop.step_id or hop.role] = hop
    return all(
        (c.step_id or "") in latest
        and latest[c.step_id or ""].ok
        and not latest[c.step_id or ""].parked
        for c in node.children
    )


def _replay_pipeline_position(
    runtime_steps: tuple[_orch.PlannedNode, ...], prior: list[HopResult]
) -> _ResumePosition:
    """Replay a hop history to find where dispatch should continue. See pod-dispatch.spec.md
    ("Per-hop incremental persistence and crash recovery" for why a completed-roles set can't
    resume once rework reruns a role; "Parallel step groups" item 6 for the known group-resume
    limit this function's trailing loop implements). Matches a verdict gate's ``rework`` edge
    by step id, not a hardcoded role. Only replays *non-terminal* history -- a terminal outcome
    is decided/persisted synchronously in the same ``dispatch_task`` call, and an ordinary
    graded-failure ``failed`` task is never reclaimed for resume (only one tagged with a
    RESUMABLE_FAILURE_KINDS reason)."""
    id_to_index = {node.step_id: i for i, node in enumerate(runtime_steps)}
    pi = 0
    rework_counts: dict[str, int] = {}
    route_counts: dict[tuple[str, str], int] = {}
    rework_hop: HopResult | None = None
    # A failing gate hop routed forward to an `input` step: the operator's answer routes back
    # to the gated step, and that retry must still be told why the gate failed.
    parked_gate_failure: HopResult | None = None
    for hop in prior:
        step_id = hop.step_id or hop.role
        idx = id_to_index.get(step_id)
        if idx is None:
            continue  # a parallel-group child's hop — handled by the trailing check below
        node = runtime_steps[idx]
        carried_failure, parked_gate_failure = parked_gate_failure, None
        if hop.parked:
            # An in-turn tool call parked mid-hop (ADR 0016 SS2): the hop was
            # attempted, not decided -- it never reached a gate or a route, so
            # neither applies. Resume re-runs this exact index (not the one
            # after it), carrying no rework state forward.
            rework_hop = None
            pi = idx
            continue
        if hop.next_step:
            # This hop's gate outcome was routed via its step's own `on` map
            # (see `_route_outcome`) — follow that exact decision instead of
            # re-deriving it, the same "don't re-decide, replay" contract the
            # rework branch below already follows for the older mechanism.
            target_index = id_to_index.get(hop.next_step)
            if target_index is not None:
                if target_index <= idx:
                    label = (
                        hop.artifact.verdict
                        if hop.artifact is not None and hop.artifact.verdict is not None
                        else str((hop.verify or {}).get("label") or "fail")
                    )
                    key = (step_id, label)
                    route_counts[key] = route_counts.get(key, 0) + 1
                    rework_hop = hop if _is_gate_failure_carryover(hop) else None
                    if (
                        rework_hop is None
                        and carried_failure is not None
                        and isinstance(node, _orch.PlannedUnit)
                        and node.input is not None
                        and node.input.from_ == carried_failure.step_id
                    ):
                        rework_hop = carried_failure
                else:
                    rework_hop = None
                    if _is_gate_failure_carryover(hop):
                        parked_gate_failure = hop
                pi = target_index
                continue
        gate = node.gate if isinstance(node, _orch.PlannedUnit) else None
        if isinstance(gate, _gates.VerdictGate) and gate.rework is not None:
            verdict = hop.artifact.verdict if hop.artifact is not None else None
            if verdict is None:
                # A record whose artifact carries no verdict falls back to
                # parsing the hop's raw output.
                verdict = _orch.parse_verdict(gate, hop.output)
            when_set = _orch.normalize_values(gate.rework.when, gate.case_sensitive)
            cycles_so_far = rework_counts.get(step_id, 0)
            target_index = id_to_index.get(gate.rework.to)
            if (
                verdict is not None
                and verdict in when_set
                and cycles_so_far < gate.rework.max_cycles
                and target_index is not None
            ):
                rework_counts[step_id] = cycles_so_far + 1
                rework_hop = hop
                pi = target_index
                continue
        rework_hop = None
        pi = idx + 1
    while (
        pi < len(runtime_steps)
        and isinstance(runtime_steps[pi], _orch.PlannedGroup)
        and _group_complete(runtime_steps[pi], prior)  # type: ignore[arg-type]
    ):
        pi += 1
        rework_hop = None
    return _ResumePosition(
        pipeline_index=pi,
        rework_counts=rework_counts,
        route_counts=route_counts,
        rework_hop=rework_hop,
    )


def _trace_locked(*args: Any, **kwargs: Any) -> _trace.TraceStatus:
    """``trace.trace_event``, serialized against ``orchestrator.trace_write_lock`` because a
    parallel group's children share one task's tracefile (the append-only exemption is safe
    only across *different* session files). See pod-dispatch.spec.md ("Parallel step groups")."""
    with _orch.trace_write_lock:
        return _trace.trace_event(*args, **kwargs)


def _verdict_event_names(role: str) -> tuple[str, str, str]:
    """(rework_event, rejected_event, unparseable_event) names for a verdict gate's non-pass
    outcome. Keeps the established names for ``reviewer``/``tester`` (pinned by
    test_reviewer_gate.py/test_verify_gate.py) so gate logic stays generic without changing
    operator-visible trace names; other roles get generic ``verdict_*`` names."""
    if role == "reviewer":
        return "rework_started", "review_rejected", "reviewer_verdict_unparseable"
    if role == "tester":
        return "verdict_rework_started", "tester_verdict_failed", "tester_verdict_failed"
    return "verdict_rework_started", "verdict_rejected", "verdict_unparseable"


@dataclass
class _UnitOutcome:
    """What happened running one ``PlannedUnit``'s hop. ``kind`` adds ``"routed"`` to the
    existing set; its resolved gate outcome (for ``_route_outcome``) is ``label``."""

    kind: str
    hops: list[HopResult] = field(default_factory=list)
    reason: str = ""
    rework_target_index: int | None = None
    approval_token: str = ""
    pending_approval_index: int | None = None
    label: str = ""
    # Only set for kind == "waiting_input" -- the minted Question, dumped by alias.
    question: dict[str, Any] | None = None
    # Only set for an external gate's unrouted failure (``gate_failed`` and its siblings).
    failure_kind: str = ""


@dataclass
class _UnitContext:
    """Per-invocation state a ``PlannedUnit``'s execution needs but does not own. Two
    attributes are mutated across a run, not just read -- passing a *copy* instead of the
    same shared object would silently break each: ``rework_counts`` accumulates each gated
    step's cycle count in place; ``override_index`` is rebound to ``None`` the first time a
    run reaches the pipeline position a granted approval named (see ``_claim_next_task``)."""

    project: str
    task: dict[str, Any]
    task_id: str
    session_id: str
    cap: float
    resolved_turn_timeout: int
    resolved_verify_timeout: int
    id_to_index: dict[str, int]
    rework_counts: dict[str, int]
    override_index: int | None
    track_pid: bool
    run: Runner
    do_sleep: Callable[[float], None]
    on_hop: Callable[[HopResult], None] | None
    on_retry: Callable[[], None] | None
    # Each step id's own already-interpolated `instructions` override (see
    # `_pipeline.step_instructions_by_id`/`interpolate_instructions`); a step
    # absent here defers to its role's own hop instruction. Defaulted so
    # every existing direct `_UnitContext(...)` construction (tests included)
    # is unaffected.
    step_instructions: dict[str, str] = field(default_factory=dict)
    # This run's resolved pipeline variables, stringified -- the `var`/`is` half of a
    # step's `when` predicate compares against these. Defaulted for the same reason
    # as `step_instructions` above.
    variables: dict[str, str] = field(default_factory=dict)
    # Cycles consumed by an `on:` backward/self route, keyed by (step_id,
    # outcome_label) -- alongside `rework_counts`, mutated in place by
    # `_route_outcome`. Defaulted for the same reason as `step_instructions`.
    route_counts: dict[tuple[str, str], int] = field(default_factory=dict)
    # The caller's own resolution for an *unset* pod ``approvalMode`` (ADR 0016 SS2) --
    # "wait" for a foreground TTY dispatch, "park" for `serve --dispatch`'s sweep or a
    # non-TTY foreground dispatch. An explicit pod value always wins over this (see
    # `pod_approval_mode`). Defaulted for the same reason as `step_instructions` above.
    approval_default: Literal["wait", "park"] = "wait"
    # Seconds an in-turn approval or consult wait may last for every hop; None keeps the default.
    approval_timeout: int | None = None
    # The task's own gate and the step it follows (``_task_gate_step_id``); see
    # ``_evaluate_hop_gates``. Defaulted like the fields above.
    task_gate: _gates.ExternalGate | None = None
    task_gate_step_id: str | None = None


def _hop_usage(run_res: _rd.TurnResult) -> dict[str, int] | None:
    """The turn's measured tokens as the hop record's ``usage`` block, or ``None``."""
    if run_res.usage is None:
        return None
    return {
        "input": run_res.usage.input_tokens,
        "cached": run_res.usage.cached_tokens,
        "cacheWrite": run_res.usage.cache_write_tokens,
        "output": run_res.usage.output_tokens,
    }


def _hop_trace_link(ctx: _UnitContext, first_ts: str) -> dict[str, str] | None:
    """The hop's trace link; ``lastTs`` is refreshed once the hop's closing events are written
    (``_persist_hop_and_trace``). ``None`` under ``DOCKET_NO_TRACE``."""
    if _process.no_trace() or not first_ts:
        return None
    return {
        "project": ctx.project,
        "session": ctx.session_id,
        "firstTs": first_ts,
        "lastTs": _clock.stamp(),
    }


def _build_hop_result(
    ctx: _UnitContext,
    node: _orch.PlannedUnit,
    role: str,
    member_id: str,
    run_res: _rd.TurnResult,
    hop_output: str,
    hop_ok: bool,
    hop_error: str,
    attempt: int,
    first_ts: str = "",
    prior: list[HopResult] | None = None,
) -> HopResult:
    """Build this hop's persisted record and handoff artifact. The verdict is parsed once,
    guarded on ``hop_ok`` (not ``run_res.ok``) since a ``pre_output`` block can fail an
    otherwise-successful call and must not hand a "here is what I changed" artifact
    downstream; the diff probe is likewise gated. Uses ``hop_output``, never
    ``run_res.output`` -- the raw text would silently undo a ``redact`` verdict's rewrite."""
    verdict: str | None = None
    if hop_ok and isinstance(node.gate, _gates.VerdictGate):
        verdict = _orch.parse_verdict(node.gate, hop_output)
    files_changed: list[str] = []
    diff_ref: str | None = None
    evidence: dict[str, Any] | None = None
    diff = ""
    if hop_ok:
        prior_diff = next(
            (h.artifact.diff for h in reversed(prior or []) if h.artifact and h.artifact.diff), ""
        )
        files_changed, diff_ref, evidence, diff = _hop_diff_probe(
            member_id, role, ctx.task, prior_diff
        )
    # A hop's raw text carrying a parseable TaskBrief (ADR 0016 §4) is never limited to
    # the Lead role by construction -- any hop's reply can end in one -- but is `None`
    # for the overwhelming majority that never emit one, `_handoff.parse_brief` failing
    # closed on anything else.
    brief = _handoff.parse_brief(hop_output) if hop_ok else None
    artifact = _handoff.HandoffArtifact(
        summary=hop_output,
        verdict=verdict,
        files_changed=files_changed,
        diff_ref=diff_ref,
        diff=diff,
        brief=brief,
    )
    served = run_res.model
    if served and run_res.provider and "/" not in served:
        served = f"{run_res.provider}/{served}"
    return HopResult(
        role=role,
        member_id=member_id,
        model=served,
        provider=run_res.provider,
        ok=hop_ok,
        output=hop_output,
        cost_usd=run_res.cost_usd,
        error=hop_error,
        attempts=attempt,
        step_id=node.step_id,
        artifact=artifact,
        evidence=evidence,
        usage=_hop_usage(run_res),
        trace=_hop_trace_link(ctx, first_ts),
        repo_files=dict(run_res.repo_files),
    )


# `agent.loop.approval_parked_error` owns this string's format (quoted
# key=value pairs) -- TurnResult carries no structured field for a parked call's
# token, so this is the one place this module re-derives it. Only the token is
# needed here, so this stays a narrow, single-field parser.
_PARKED_ERROR_PREFIX = "approval_parked:"
_APPROVAL_TOKEN_RE = _re.compile(r"approval_token=(?:'([^']*)'|\"([^\"]*)\"|(\S+))")


def _parked_approval_token(error: str) -> str | None:
    """The approval token from a hop's ``approval_parked`` stop, or ``None`` for an
    ordinary failure or an unparseable one."""
    # Fails closed: an unmatched parked call falls through to an ordinary `failed`
    # outcome instead of silently waiting forever.
    if not error.startswith(_PARKED_ERROR_PREFIX):
        return None
    match = _APPROVAL_TOKEN_RE.search(error)
    if not match:
        return None
    return next((g for g in match.groups() if g is not None), None) or None


def _parked_consult_question(
    ctx: _UnitContext, hop: HopResult, token: str | None
) -> dict[str, Any] | None:
    """The question a parked ``consult`` left, rebound to this task and step (stored on the
    task like an input step's), or ``None`` when *token* is not a consultation's."""
    if token is None or not token.startswith(PARK_TOKEN_PREFIX):
        return None
    question = parked_question(token)
    if question is None:
        return None
    question.task_id = ctx.task_id
    question.step = hop.step_id or hop.role
    return question.model_dump(by_alias=True)


def _turn_budget_failure_kind(ctx: _UnitContext, run_res: _rd.TurnResult) -> str:
    """``"budget"`` when the turn loop stopped on the token budget a task ``maxTokens`` set."""
    if run_res.stop_reason == "token_budget" and ctx.task.get("maxTokens") is not None:
        return "budget"
    return ""


def _persist_hop_and_trace(
    ctx: _UnitContext,
    role: str,
    hop: HopResult,
    run_res: _rd.TurnResult,
    hop_ok: bool,
    hop_error: str,
    index_for_context: int,
) -> _UnitOutcome | None:
    """Persist this hop and trace its result; short-circuit a failed hop. Returns the
    terminal outcome, or ``None`` to proceed to the gate."""
    # Persisted immediately, not deferred to a group join, so a crash in a sibling child
    # never loses an already-completed hop. A hop whose turn stopped on an in-turn
    # `approval_parked` denial (park-mode DOCKET_APPROVAL_MODE, see `_compose_hop`) is
    # persisted with `hop.parked = True` before `on_hop` -- so a crash right after still
    # leaves the correct record for `_replay_pipeline_position` to resume from -- and
    # yields the same `waiting_approval` outcome shape the pre-hop `require_approval` gate
    # already produces, at this hop's own pipeline index (ADR 0016 SS2).
    parked_token = None if hop_ok else _parked_approval_token(hop_error)
    if parked_token is not None:
        hop.parked = True
    consult_question = _parked_consult_question(ctx, hop, parked_token)

    _trace_locked(
        ctx.project,
        ctx.session_id,
        role,
        "tool_result" if hop_ok else "error",
        hop.output or hop_error or "",
        cost_usd=run_res.cost_usd or None,
    )
    if run_res.cost_usd:
        _trace_locked(
            ctx.project,
            ctx.session_id,
            role,
            "cost_charged",
            _json.dumps({"role": role}),
            cost_usd=run_res.cost_usd,
        )

    # The hop's closing events are written, so its trace window can now be closed; this precedes
    # `on_hop` so the persisted record's `lastTs` covers them (evidence-v1).
    if hop.trace is not None:
        hop.trace["lastTs"] = _clock.stamp()
    duration_ms: int | None = None
    if hop.trace and hop.trace.get("firstTs") and hop.trace.get("lastTs"):
        first = _clock.parse_iso(hop.trace["firstTs"])
        last = _clock.parse_iso(hop.trace["lastTs"])
        if first is not None and last is not None:
            duration_ms = int((last - first).total_seconds() * 1000)
    verdict = hop.artifact.verdict if hop.artifact is not None else None
    gate: str | None = None
    if hop.verify is not None:
        label = hop.verify.get("label")
        gate = (
            label
            if isinstance(label, str)
            else ("pass" if hop.verify.get("exitCode") == 0 else "fail")
        )
    _trace_locked(
        ctx.project,
        ctx.session_id,
        role,
        "hop_finished",
        _json.dumps(
            {
                "task": ctx.task_id,
                "step": hop.step_id,
                "role": role,
                "member": hop.member_id,
                "model": hop.model,
                "provider": hop.provider,
                "cycle": sum(ctx.rework_counts.values()),
                "attempt": hop.attempts,
                "ok": hop_ok,
                "verdict": verdict,
                "gate": gate,
                "usage": hop.usage,
                "durationMs": duration_ms,
                "error": hop_error,
            }
        ),
    )

    if ctx.on_hop is not None:
        ctx.on_hop(hop)

    if not hop_ok:
        if run_res.failure_kind == "run_cancelled":
            return _UnitOutcome(
                kind="cancelled",
                hops=[hop],
                reason="run cancellation requested",
            )
        if consult_question is not None:
            return _UnitOutcome(
                kind="waiting_input",
                hops=[hop],
                reason=f"{role} hop parked a consultation (question={consult_question['id']})",
                question=consult_question,
            )
        if parked_token is not None and parked_token.startswith(PARK_TOKEN_PREFIX):
            # No approval record can resolve a consult token, so parking on it would be stuck.
            return _UnitOutcome(
                kind="failed",
                hops=[hop],
                reason=f"{role} hop failed: consult_question_missing (the parked consultation carried no question)",
            )
        if parked_token is not None:
            # Reuses the pre-hop gate's own event type (observability/trace.py's
            # EVENT_TYPES is not this card's to extend): both mean exactly
            # "a require_approval-equivalent gate fired; task ->
            # waiting_approval", whether the trigger was a pre-hop gate or, as
            # here, an in-turn tool call parking mid-hop.
            _trace_locked(
                ctx.project,
                ctx.session_id,
                role,
                "approval_required",
                _json.dumps(
                    {"role": role, "token": parked_token, "pipelineIndex": index_for_context}
                ),
            )
            return _UnitOutcome(
                kind="waiting_approval",
                hops=[hop],
                reason=f"{role} hop parked for approval (token={parked_token})",
                approval_token=parked_token,
                pending_approval_index=index_for_context,
            )
        return _UnitOutcome(
            kind="failed",
            hops=[hop],
            reason=f"{role} hop failed: {hop_error or 'no result'}",
            failure_kind=_turn_budget_failure_kind(ctx, run_res),
        )
    return None


def _persist_hop(project: str, task_id: str, hop: HopResult) -> None:
    """Append one just-completed hop to the task's record, called after every hop (not only
    at task end) so a crash loses at most the in-flight hop. Also refreshes ``claimedAt``,
    re-syncs the HEARTBEAT.md ledger, and touches the hop agent's tracked conversation, if any
    -- see pod-dispatch.spec.md ("Conversation registry auto-population"); a no-op if unwired."""

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        tasks_raw = doc.get("tasks")
        tasks = tasks_raw if isinstance(tasks_raw, list) else []
        for t in tasks:
            if t.get("id") == task_id:
                hops = t.get("hops")
                if not isinstance(hops, list):
                    hops = []
                hops.append(_hop_record(hop))
                t["hops"] = hops
                t["costUsd"] = round(sum(float(h.get("costUsd", 0.0) or 0.0) for h in hops), 6)
                t["claimedAt"] = _clock.iso()
                return {"tasks": tasks}
        return None  # task no longer in the queue — nothing to persist

    doc = read_modify_write(pod_task_list_path(project), _fn)
    tasks_after = doc.get("tasks")
    lead_id = _pod.member_id(project, "lead")
    _mem.sync_dispatch_tasks(
        current_home().workspace_dir(lead_id), tasks_after if isinstance(tasks_after, list) else []
    )

    _conv.touch_for_hop_durable(
        agent_id=hop.member_id, task_ref=task_id, last_message=hop.output, now=_clock.iso()
    )
