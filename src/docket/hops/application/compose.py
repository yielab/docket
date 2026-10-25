from __future__ import annotations

import datetime as _dt
import json as _json
from dataclasses import dataclass, field
from typing import Any

from docket.agent import context as _ctx
from docket.agent import ports as _rd
from docket.hops.application import verify_tool as _verify
from docket.hops.application.verdict_tool import encode_values
from docket.hops.gates.pre_hop import _apply_task_restrictions, _consult_budget_env, _hop_model
from docket.kernel import brief as _brief
from docket.kernel import clock as _clock
from docket.kernel import handoff as _handoff
from docket.kernel.home import current_home
from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import plan as _orch
from docket.tasks.application.actions import mint_task_grant_pregrants
from docket.tasks.application.record import (
    UnitContext,
    claimed_worktree_dir,
    gate_did_not_pass,
    hop_env,
    is_gate_failure_carryover,
    trace_locked,
)
from docket.tasks.domain.parts import Answer
from docket.tasks.domain.task import HopResult, TaskRecord
from docket.teams import role_schema as _role_schema
from docket.teams import roles as _archetypes
from docket.teams.settings import load_pod_settings, pod_approval_mode
from docket.teams.workspace import repo_map as _repo_map


@dataclass
class _HopComposition:
    """Per-hop prompt-composition stats, recorded via the ``context_composed`` trace event."""

    description_bytes: int
    sections: list[dict[str, Any]] = field(default_factory=list)
    total_bytes: int = 0
    truncated: bool = False


_VERIFY_SENTENCE = (
    "Your work is accepted only if `{}` exits 0. Run it with the `verify` tool and fix what it "
    "reports before you finish."
)


def _resolve_hop_instructions(
    role: str,
    project: str,
    rework_hop: HopResult | None,
    step_instructions: str,
    verify_cmd: str = "",
) -> str:
    """This role's hop instruction text; an Implementer whose step has *verify_cmd* is told it."""
    text = _role_instructions(role, project, rework_hop, step_instructions)
    if verify_cmd and role == "implementer":
        return "\n\n".join(p for p in (text, _VERIFY_SENTENCE.format(verify_cmd)) if p)
    return text


def _role_instructions(
    role: str, project: str, rework_hop: HopResult | None, step_instructions: str
) -> str:
    """The role's own text: the step's own override, else a built-in role's fixed text, else a
    custom role's registry-resolved ``hopInstruction``."""
    if step_instructions:
        return step_instructions
    if role == "implementer":
        return (
            "You are the Implementer. Address the reviewer's REQUEST-CHANGES "
            "above, then implement the change in the workspace."
            if rework_hop is not None
            else "You are the Implementer. Implement the change in the workspace."
        )
    if role == "reviewer":
        return (
            "You are the Reviewer. Review the diff (read-only). The LAST line of your "
            "FINAL message must be exactly `APPROVE` or `REQUEST-CHANGES`, with nothing "
            "else on that line. Reasons go above it."
        )
    if role == "tester":
        return (
            "You are the Tester. Validate behaviour only. The LAST line of your FINAL "
            "message must be exactly `PASS` or `FAIL`, with nothing else on that line. "
            "Evidence goes above it."
        )
    # A custom role: its own archetype's `hopInstruction`, or one generated
    # from its `gateContract` (e.g. a verdict role's marker convention) --
    # see role-archetypes.spec.md ("Hop instructions"). An unrecognized
    # role name (absent from the registry) still gets no instruction,
    # matching today's behavior.
    archetype = _archetypes.load_registry(project).get(role)
    return _role_schema.resolve_hop_instruction(archetype) if archetype else ""


def _render_gate_reasons(reasons: list[dict[str, Any]]) -> str:
    """An external gate's screened reasons, one block per reason: ``- [severity] path:line
    summary`` and an indented ``detail`` line when there is one."""
    lines: list[str] = []
    for r in reasons:
        where = str(r.get("path") or "")
        if where and r.get("line") is not None:
            where = f"{where}:{r['line']}"
        head = " ".join(p for p in (f"[{r['severity']}]" if r.get("severity") else "", where) if p)
        lines.append(f"- {head} {r['summary']}" if head else f"- {r['summary']}")
        if r.get("detail"):
            lines.append(f"  {r['detail']}")
    return "\n".join(lines)


def _gate_failed_section(
    step_id: str, output_tail: str, reasons: str = "", operator_answer: str = ""
) -> str:
    """The one place the ``--- GATE FAILED: <step id> ---`` section is written: the header, the
    external gate's rendered *reasons* if any, else the routed hop's redacted output tail, then
    the operator's answer when a human sent the task back. Ends with a newline."""
    answer = f"Operator answer:\n{operator_answer}\n" if operator_answer else ""
    return f"--- GATE FAILED: {step_id} ---\n{reasons or output_tail}\n{answer}"


def _gate_report(prior: list[HopResult], step_id: str) -> str:
    """What the latest gate on *step_id* reported when it did not pass: its rendered reasons,
    else its redacted output tail; empty when that gate passed or never ran."""
    for h in reversed(prior):
        if (h.step_id or h.role) != step_id:
            continue
        if h.verify is None or not gate_did_not_pass(h.verify):
            return ""
        reasons = h.verify.get("reasons")
        if isinstance(reasons, list) and reasons:
            return _render_gate_reasons(reasons)
        return str(h.verify.get("outputTail", ""))
    return ""


def _compose_gate_failed(
    hop: HopResult, budget_tokens: int, comp: _HopComposition, operator_answer: str = ""
) -> str:
    """The ``GATE FAILED`` section for *hop*: its persisted, redacted external reasons, else
    its ``verify.outputTail`` (never raw output), fit to *budget_tokens* and recorded in *comp*
    as role ``gate_failed``. Unlike a verdict rework hop, *hop* stays in the generic carryover
    loop: its own output is still prior context and only the gate's failure is new."""

    assert hop.verify is not None
    reasons = hop.verify.get("reasons")
    rendered = _render_gate_reasons(reasons) if isinstance(reasons, list) and reasons else ""
    raw_tail = rendered or str(hop.verify.get("outputTail", ""))
    tail, truncated = _ctx.truncate_summary(raw_tail, budget_tokens)
    comp.sections.append(
        {
            "role": "gate_failed",
            "original_bytes": len(raw_tail.encode("utf-8")),
            "sent_bytes": len(tail.encode("utf-8")),
            "truncated": truncated,
            "dropped_fields": [],
        }
    )
    comp.truncated = comp.truncated or truncated
    step_id = hop.step_id or hop.role
    if rendered:
        return _gate_failed_section(step_id, "", tail, operator_answer)
    return _gate_failed_section(step_id, tail, operator_answer=operator_answer)


def _latest_brief_hop_index(prior: list[HopResult]) -> int | None:
    """The most recent prior hop whose artifact carries a Lead intake brief, or ``None`` --
    the Implementer's own view (``_hop_message``) replaces that one hop's carryover
    entirely, so only the latest match (not every brief-bearing hop) matters here."""
    index: int | None = None
    for i, h in enumerate(prior):
        if h.artifact is not None and h.artifact.brief is not None:
            index = i
    return index


def _hop_message(
    task: TaskRecord,
    role: str,
    prior: list[HopResult],
    rework_hop: HopResult | None = None,
    step_instructions: str = "",
    project: str = "",
    verify_cmd: str = "",
) -> tuple[str, _HopComposition]:
    """Build one role's message via ``agent/context.py``'s token-budget compiler (see
    pod-dispatch.spec.md, "Bounded hop prompts"). The task description is never truncated;
    each prior artifact is fit to a per-role share, shedding ``DROP_ORDER`` fields before
    ``summary``, which is only ever truncated with a marker, never silently dropped.
    *rework_hop* gets the implementer's full carryover budget in its own section, deliberately
    excluded from the generic per-hop loop (not left to recency ranking) since it addresses
    what the rework hop exists for. Returns the message plus a ``_HopComposition``.

    *step_instructions*, when non-empty, is this step's own already-interpolated
    ``instructions`` (pipeline-format.spec.md) -- it replaces whatever instruction text the
    target role would otherwise carry, for every role including the Lead (a built-in's own
    instruction text, or a custom role's own ``hopInstruction``/generated fallback, see
    role-archetypes.spec.md). *verify_cmd* is named in the Implementer's instruction."""

    desc = task.description.strip()
    worktree = "" if role == "lead" else claimed_worktree_dir(task)
    root_block = _repo_map.task_root_block(worktree, project, role)
    if role == "lead":
        if step_instructions:
            lead_instruction = step_instructions
        else:
            lead_archetype = _archetypes.load_registry(project).get("lead")
            lead_instruction = (
                _role_schema.resolve_hop_instruction(lead_archetype) if lead_archetype else ""
            )
        message = f"{lead_instruction}\n\n{desc}" if lead_instruction else desc
        if root_block:
            message = f"{message}\n\n{root_block}"
        answers_block = _render_operator_answers(task.answers)
        if answers_block:
            message = f"{message}\n\n## Operator answers\n{answers_block}"
        comp = _HopComposition(
            description_bytes=len(desc.encode("utf-8")), total_bytes=len(message.encode("utf-8"))
        )
        return message, comp

    instructions = _resolve_hop_instructions(
        role,
        project,
        None if is_gate_failure_carryover(rework_hop) else rework_hop,
        step_instructions,
        verify_cmd,
    )

    # The role's total token budget, minus what the immutable task
    # description and this role's own fixed instruction footer already cost
    # — what's left is what the carryover (rework note + prior hops) may
    # spend. This is what makes "the composed message fits its role's
    # budget" a real, checkable property rather than an aspiration: the two
    # pieces that are never shed are accounted for before anything
    # sheddable is given a share.
    reserved_tokens = sum(_rd.estimate_tokens(t) for t in (desc, instructions, root_block))
    carryover_budget = max(_ctx.budget_for_role(role, project=project) - reserved_tokens, 0)

    lines = [f"Task: {desc}", ""] + ([root_block, ""] if root_block else [])
    comp = _HopComposition(description_bytes=len(desc.encode("utf-8")))

    gate_failed_hop = rework_hop if is_gate_failure_carryover(rework_hop) else None
    if gate_failed_hop is not None:
        # Resumed right behind an operator's answer: that answer is what the human decided.
        answered = bool(prior) and prior[-1].role == "operator"
        answer = _render_operator_answers(task.answers[-1:]) if answered else ""
        lines.append(_compose_gate_failed(gate_failed_hop, carryover_budget, comp, answer))
    elif rework_hop is not None and rework_hop.output:
        # Rendered from the hop's *artifact*, not its raw output, so this
        # reflects the same structured content (see `render()`'s own
        # "Verdict: ..." line, added when the artifact carries one) the next
        # hop actually reasons about. Attributed to whichever step actually
        # drove the rework — not hardcoded to "reviewer" — so a custom
        # pipeline's rework source (any role with a verdict gate's `rework`
        # edge) is named correctly too.
        assert rework_hop.artifact is not None
        compiled = _ctx.compile_artifact(rework_hop.artifact, carryover_budget)
        comp.sections.append(
            {
                "role": "rework",
                "original_bytes": len(rework_hop.artifact.render().encode("utf-8")),
                "sent_bytes": len(compiled.text.encode("utf-8")),
                "truncated": compiled.truncated,
                "dropped_fields": list(compiled.dropped_fields),
            }
        )
        comp.truncated = comp.truncated or compiled.truncated
        lines.append(
            f"--- REWORK REQUIRED: {rework_hop.role} requested changes ---\n{compiled.text}\n"
        )

    last_index = len(prior) - 1
    # The Implementer's own view of the latest brief-bearing hop (almost always the
    # Lead's) replaces that hop's carried-forward prose entirely -- see the loop below.
    latest_brief_index = _latest_brief_hop_index(prior) if role == "implementer" else None
    # Iterate in the original chronological order (oldest first), so message
    # *layout* stays stable and only *content* varies with the budget. Only
    # the per-hop budget is recency-aware: rank counts back
    # from the most recent hop (rank 0), so `context.hop_share` gives it the
    # biggest share.
    for i, h in enumerate(prior):
        if not h.output or (h is rework_hop and gate_failed_hop is None):
            continue
        rank = last_index - i
        hop_budget = _ctx.hop_share(rank, carryover_budget)
        # The *artifact* is what gets carried forward and budgeted — not
        # the hop's raw output — so the budget bounds the same structured
        # content the next hop actually reasons about.
        assert h.artifact is not None
        if i == latest_brief_index:
            # The Implementer sees the Lead's typed brief in place of its prose
            # preamble -- never both -- so it reasons from the same structured
            # objective/acceptance/resources a human reviewing the task would.
            assert h.artifact.brief is not None
            brief_text = _handoff.render_brief(h.artifact.brief)
            comp.sections.append(
                {
                    "role": h.role,
                    "original_bytes": len(h.artifact.render().encode("utf-8")),
                    "sent_bytes": len(brief_text.encode("utf-8")),
                    "truncated": False,
                    "dropped_fields": [],
                }
            )
            lines.append(f"## Brief\n{brief_text}\n")
            continue
        compiled = _ctx.compile_artifact(h.artifact, hop_budget)
        comp.sections.append(
            {
                "role": h.role,
                "original_bytes": len(h.artifact.render().encode("utf-8")),
                "sent_bytes": len(compiled.text.encode("utf-8")),
                "truncated": compiled.truncated,
                "dropped_fields": list(compiled.dropped_fields),
            }
        )
        comp.truncated = comp.truncated or compiled.truncated
        lines.append(f"--- {h.role} output ---\n{compiled.text}\n")
    if instructions:
        lines.append(instructions)
    message = "\n".join(lines)
    comp.total_bytes = len(message.encode("utf-8"))
    return message, comp


# Rough character budget for the Lead's "## Operator answers" section, expressed here as a
# token budget for `_ctx.truncate_summary`, which only ever bounds bytes -- ASCII text keeps
# the two close enough for a "capped near N characters" guarantee, never an exact one.
_ANSWERS_CHAR_BUDGET = 4000


def _render_answer_value(entry: Answer) -> str:
    """One answered entry's ``A: ...`` line: the single ``answer`` property's value for an
    ``accept``, else a plain marker -- see ``hops.application.answers.answer_task``."""
    action = entry.action
    if action == "accept":
        content = entry.content or {}
        if list(content.keys()) == ["answer"]:
            return str(content["answer"])
        return _json.dumps(content, sort_keys=True)
    if action == "decline":
        return "(declined)"
    if action == "cancel":
        return "(cancelled)"
    return "(no answer)"


def _render_operator_answers(answers: list[Answer]) -> str:
    """Render ``answers[]`` as ``Q: ...\\nA: ...`` blocks, oldest first, capped near
    ``_ANSWERS_CHAR_BUDGET`` characters with a visible truncation marker. Empty when the task
    carries no answers yet."""
    if not answers:
        return ""
    blocks = [f"Q: {entry.message.strip()}\nA: {_render_answer_value(entry)}" for entry in answers]
    text = "\n\n".join(blocks)
    budget_tokens = _ANSWERS_CHAR_BUDGET // current_home().context_bytes_per_token
    capped, _truncated = _ctx.truncate_summary(text, budget_tokens)
    return capped


def _consult_answer_note(task: TaskRecord, step_id: str) -> str:
    """The operator's answer to this step's parked consultation, as a trailing message block
    (empty when the step has none)."""
    answer = task.consult_answer
    if answer is None or answer.step != step_id:
        return ""
    return f"\n\n{answer.text}\n"


def _compose_hop(
    ctx: UnitContext,
    node: _orch.PlannedUnit,
    role: str,
    member_id: str,
    prior_snapshot: list[HopResult],
    rework_hop: HopResult | None,
) -> tuple[str, dict[str, str] | None]:
    """Build this hop's prompt/environment and emit its ``context_composed``/``tool_call``
    trace pair. A downstream hop's message gets an extra checkout note naming the real
    implementation worktree, when allocated -- see pod-dispatch.spec.md ("Downstream worktree continuity")."""
    step_override = ctx.step_instructions.get(node.step_id, "")
    verify_plan = None if role == "lead" else _verify.plan_for_hop(ctx, node, member_id)
    message, composition = _hop_message(
        ctx.task,
        role,
        prior_snapshot,
        rework_hop,
        step_instructions=step_override,
        project=ctx.project,
        verify_cmd=verify_plan.command if verify_plan is not None else "",
    )
    message += _consult_answer_note(ctx.task, node.step_id)
    pipeline_worktree = ""
    if role != "lead":
        pipeline_worktree = claimed_worktree_dir(ctx.task)
        if pipeline_worktree:
            # The task block already names the checkout as the working directory.
            checkout_note = ""
            if role != "implementer" and isinstance(node.gate, _gates.VerdictGate):
                checkout_note = (
                    "\nYour final message must still end with the verdict marker as its LAST "
                    "line, with nothing else on that line.\n"
                )
            message += checkout_note
            composition.total_bytes += len(checkout_note.encode("utf-8"))
    trace_locked(
        ctx.project,
        ctx.session_id,
        role,
        "context_composed",
        _json.dumps(
            {
                "hop": role,
                "description_bytes": composition.description_bytes,
                "sections": composition.sections,
                "total_bytes": composition.total_bytes,
                "truncated": composition.truncated,
            }
        ),
    )
    trace_locked(
        ctx.project,
        ctx.session_id,
        role,
        "tool_call",
        _json.dumps({"hop": role, "agent": member_id}),
    )
    planned_model = _hop_model(node, member_id)
    trace_locked(
        ctx.project,
        ctx.session_id,
        role,
        "hop_started",
        _json.dumps(
            {
                "task": ctx.task_id,
                "step": node.step_id,
                "role": role,
                "member": member_id,
                "model": planned_model,
                "provider": planned_model.partition("/")[0] if "/" in planned_model else "",
                "cycle": sum(ctx.rework_counts.values()),
                "attempt": 1,
            }
        ),
    )
    env = hop_env(member_id, role)
    if verify_plan is not None:
        env = {**(env or {}), _rd.DOCKET_VERIFY_PLAN: _verify.plan_env_value(verify_plan)}
    if pipeline_worktree:
        env = dict(env or {})
        env[_rd.PIPELINE_WORKTREE_ENV] = pipeline_worktree
    resolved_mode = pod_approval_mode(ctx.project, caller_default=ctx.approval_default)
    if resolved_mode in ("refuse", "park"):
        # Same internal-env route as PIPELINE_WORKTREE_ENV: DocketDriver pops this before the tool env
        # reaches ToolContext, so it is never a real tool-visible variable.
        env = dict(env or {})
        env[_rd.DOCKET_APPROVAL_MODE] = resolved_mode
        if resolved_mode == "park":
            # This hop's own deadline for a call it parks (ADR 0016 SS2) --
            # popped by DocketDriver into ToolContext.approval_expires_at,
            # stamped on the parked record by governance/gate.py's `_park`.
            # Computed fresh per hop (not once per task) so a long-running
            # earlier hop never shortens a later one's window.
            expiry_hours = load_pod_settings(ctx.project).approval_expiry_hours
            deadline = _clock.now() + _dt.timedelta(hours=expiry_hours)
            env[_rd.DOCKET_APPROVAL_EXPIRES_AT] = deadline.isoformat()
    if ctx.approval_timeout is not None:
        env = dict(env or {})
        env[_rd.DOCKET_APPROVAL_TIMEOUT] = str(ctx.approval_timeout)
    if isinstance(node.gate, _gates.VerdictGate):
        env = dict(env or {})
        env[_rd.DOCKET_VERDICT_VALUES] = encode_values(
            _orch.verdict_values(node.gate), node.gate.case_sensitive
        )
    env = _consult_budget_env(ctx, env)
    env = _apply_task_restrictions(ctx, env)
    pregrants_raw = [
        *(g.model_dump(by_alias=True) for g in ctx.task.pregrants),
        *mint_task_grant_pregrants(ctx, role),
    ]
    if pregrants_raw:
        # Every pre-grant this task's human has already resolved (ADR 0016
        # SS2) -- a human already consumed one carries no live effect
        # (`consume_pregrant` is single-use and atomic), so passing the whole
        # list along is a harmless no-op for anything already spent; it only
        # ever lets an unconsumed exact-match call through without asking
        # again.
        env = dict(env or {})
        env[_rd.DOCKET_PREGRANTS] = _json.dumps(pregrants_raw)
    return message, env


def _brief_from_step(prior: list[HopResult], step_id: str) -> _brief.TaskBrief | None:
    """The most recent *step_id* hop's parsed brief, or ``None`` -- a plain-text hop, a
    step that never ran, or a Lead reply with no parseable brief all degrade the same way."""
    for h in reversed(prior):
        if h.step_id == step_id and h.artifact is not None and h.artifact.brief is not None:
            return h.artifact.brief
    return None


def _brief_questions_schema(questions: list[str]) -> dict[str, Any]:
    """One string property per brief question (``q1``..``qn``, ``title`` = the question
    text), every one required -- the richer schema an intake brief's own questions earn
    over the generic single free-text ``answer`` property."""
    properties = {f"q{i}": {"type": "string", "title": q} for i, q in enumerate(questions, 1)}
    return {"type": "object", "properties": properties, "required": list(properties)}
