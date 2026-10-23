from __future__ import annotations

import json as _json
import re as _re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from docket.agent import isolation_posture as _isolation_posture
from docket.agent import ports as _rd
from docket.agent.tools import registry as _tools
from docket.governance import policy as _policy
from docket.governance import security as _sec
from docket.hops.application.record import (
    _trace_locked,
    _UnitContext,
    _UnitOutcome,
    _verdict_event_names,
)
from docket.hops.workspace import prepare as _prepare
from docket.hops.workspace.worktree import _task_worktree_dir
from docket.kernel import clock as _clock
from docket.kernel.home import current_home
from docket.kernel.ports import jail as _jail
from docket.observability import trace as _trace
from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import plan as _orch
from docket.tasks.application import corrections as _corrections
from docket.tasks.domain.task import HopResult
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod
from docket.teams.settings import _pod_settings


def _apply_output_guardrails(
    ctx: _UnitContext, role: str, run_res: _rd.TurnResult
) -> tuple[str, bool, str]:
    """``pre_output`` guardrail scan over the hop's real output, before it is embedded in
    the carried-forward artifact or persisted record. See security-gates.spec.md
    ("pre_output"): only ``redact``/``block`` change what is carried forward;
    ``require_approval`` behaves like ``warn`` since the hop already ran -- there is no
    "before" moment left to gate. Returns the (possibly redacted) output, hop-ok, error text."""
    hop_output = run_res.output
    hop_ok = run_res.ok
    hop_error = run_res.error
    if hop_output:
        hit = _policy.policy_eval_detail(role, "pre_output", hop_output, project=ctx.project)
        # Also classify the hop's real output against the built-in
        # high-risk action classes (governance/security.py's HIGH_RISK_PATTERNS),
        # independently of the JSON policy engine above. This is a second,
        # independent check over what the hop *reports* it did, not what a
        # tool call literally asked to run — it still catches a
        # money-movement or secret-access command described in the hop's
        # own summary even when the underlying call never reached
        # `dispatch_tool`'s live `pre_tool_call` gate (e.g. a runner that
        # doesn't route through it at all, such as a test double). A match
        # never downgrades an already-stronger policy_eval_detail verdict —
        # redact/block/require_approval all outrank a bare "allow" — it only
        # raises a plain "allow" to "warn". It cannot go further than
        # "warn": there is no live approver to "ask" post-hoc (the hop
        # already ran, the same reasoning behind pre_output's
        # require_approval-behaves-like-warn rule), and HIGH_RISK_PATTERNS
        # is a built-in Python list, not an installed, operator-authored
        # JSON policy — so this only ever adds visibility, it never
        # redacts or blocks on the operator's behalf the way a real
        # installed policy can.
        risk_cls = _sec.match_high_risk(hop_output)
        if risk_cls is not None and hit.action == "allow":
            hit = _policy.PolicyHit(
                action="warn",
                policy_id=f"high-risk:{risk_cls.name}",
                message=risk_cls.description,
            )
        if hit.action != "allow":
            _trace_locked(
                ctx.project,
                ctx.session_id,
                role,
                "guardrail_check",
                _json.dumps({"hook": "pre_output", "policy": hit.policy_id, "action": hit.action}),
            )
        if hit.action == "redact":
            hop_output = _trace.redact(hop_output)
        elif hit.action == "block":
            _trace_locked(
                ctx.project,
                ctx.session_id,
                role,
                "guardrail_block",
                _json.dumps({"hook": "pre_output", "policy": hit.policy_id, "action": hit.action}),
            )
            if hop_ok:
                hop_ok = False
                hop_error = f"blocked by guardrail policy '{hit.policy_id}'"
    return hop_output, hop_ok, hop_error


def _match_on_route(on: dict[str, Any] | None, label: str) -> Any:
    """The raw ``Route`` value in *on* whose key matches *label* case-insensitively
    (outcome labels always compare case-insensitively -- see pipeline-format.spec.md
    "Outcome routing"), or ``None`` when *on* has no entry for it."""
    if not on:
        return None
    norm = label.lower()
    for key, route in on.items():
        if str(key).lower() == norm:
            return route
    return None


@dataclass
class _GateRun:
    """One gate command's result: its exit status (``None`` when it never ran to an exit:
    refused, timed out, failed to start), redacted output and wall clock."""

    code: int | None
    redacted: str
    duration_s: float

    @property
    def passed(self) -> bool:
        return self.code == 0


def _gate_cwd(ctx: _UnitContext, member_id: str) -> str:
    """The directory a gate command runs in: the member's, worktree-aware (shared with
    interfaces/cli/commands/pod.py through ``teams.pod.resolve_member_cwd`` so the two never disagree)."""
    member_codebase = str(_fleet.meta_get(member_id, "codebase", "") or "")
    return _pod.resolve_member_cwd(member_id, _task_worktree_dir(ctx.task), member_codebase)


def _run_gate_command(
    ctx: _UnitContext, cmd: str, cwd: str, timeout: int, env: dict[str, str] | None = None
) -> _GateRun:
    """Run a gate command in the pod's envelope. The output is redacted here, once, so no
    caller can persist the raw string."""
    start = _clock.monotonic()
    code, raw_output = _run_in_envelope(ctx.project, "verify", cmd, cwd, timeout, env)
    duration_s = _clock.monotonic() - start
    return _GateRun(code, _trace.redact(raw_output), duration_s)


def _gate_evidence(cmd: str, exit_code: int, run: _GateRun) -> dict[str, Any]:
    """The hop's ``verify`` evidence, persisted regardless of pass/fail/route -- see
    HopResult.verify. ``outputTail`` is the redacted string's own tail (never the raw one), so
    a secret is never one truncation away from surviving into the persisted record."""
    return {
        "cmd": cmd,
        "exitCode": exit_code,
        "durationS": round(run.duration_s, 3),
        "outputTail": run.redacted[-current_home().verify_evidence_tail_chars :],
    }


def _evaluate_mechanical_gate(
    ctx: _UnitContext,
    gate: _gates.MechanicalGate,
    node: _orch.PlannedUnit,
    role: str,
    member_id: str,
    hop: HopResult,
) -> _UnitOutcome:
    """A ``MechanicalGate``: run ``verifyCmd`` (or the gate's own command) and gate on its
    exit, in the dir from ``teams.pod.resolve_member_cwd`` (shared with interfaces/cli/commands/pod.py so the two
    never disagree); a ``"pass"``/``"fail"`` named in the step's own ``on`` map routes instead."""
    verify_cmd = gate.command or str(_fleet.meta_get(member_id, "verifyCmd", "") or "")
    if not verify_cmd:
        # Check if verification is required
        require_verify = _pod_settings(ctx.project).require_verify
        if require_verify:
            _trace_locked(
                ctx.project,
                ctx.session_id,
                role,
                "verification_failed",
                _json.dumps({"reason": "verification_missing", "member": member_id}),
            )
            return _UnitOutcome(
                kind="failed",
                hops=[hop],
                reason="verifyCmd required but not set",
            )
        # Honesty rule: never silently skip — a missing verifyCmd is
        # visible via a trace event (parity with the "passed" case
        # below) and the hop's own `verification_skipped` flag, which
        # `interfaces/cli`'s dispatch renderer prints. Application code never prints
        # directly.
        _trace_locked(
            ctx.project,
            ctx.session_id,
            role,
            "tool_result",
            _json.dumps({"verification": "skipped", "member": member_id}),
        )
        hop.verification_skipped = True
        return _UnitOutcome(kind="advance", hops=[hop])

    cwd = _gate_cwd(ctx, member_id)
    # The verify command gets its own timeout, decoupled from the agent-turn
    # timeout above — a 20-minute test suite and a hung LLM turn are no longer
    # forced to share one budget.
    mech_timeout = gate.timeout or ctx.resolved_verify_timeout
    run = _run_gate_command(ctx, verify_cmd, cwd, mech_timeout)
    passed, redacted = run.passed, run.redacted
    hop.verify = _gate_evidence(verify_cmd, 0 if passed else 1, run)
    label = "pass" if passed else "fail"
    if _match_on_route(node.on, label) is not None:
        return _UnitOutcome(kind="routed", hops=[hop], label=label)
    if not passed:
        _trace_locked(
            ctx.project,
            ctx.session_id,
            role,
            "verification_failed",
            _json.dumps({"cmd": verify_cmd, "output": redacted}),
        )
        return _UnitOutcome(
            kind="failed",
            hops=[hop],
            reason=f"verifyCmd failed: {verify_cmd!r}",
        )
    _trace_locked(
        ctx.project,
        ctx.session_id,
        role,
        "tool_result",
        _json.dumps({"verification": "passed", "cmd": verify_cmd}),
    )
    return _UnitOutcome(kind="advance", hops=[hop], label=label)


_GATE_REASONS_MAX_BYTES = 64 * 1024
_GATE_REASON_TEXT_FIELDS = ("summary", "id", "path", "severity", "detail")
_GATE_FAILURE_KINDS = {
    "fail": "gate_failed",
    "needs_human": "gate_needs_human",
    "error": "gate_error",
}


def _gate_file_stem(task_id: str, step_id: str) -> str:
    return _re.sub(r"[^A-Za-z0-9_.-]", "_", f"{task_id}-{step_id}")


def _gate_reasons_path(project: str, task_id: str, step_id: str) -> Path:
    """Where an external gate's verifier writes its reasons: under the pod cache dir (a
    read-write jail root), one file per task and step. Deleted before every run."""
    return (
        current_home().pod_cache_dir(project)
        / "gate"
        / f"{_gate_file_stem(task_id, step_id)}.reasons.json"
    )


def _external_failure_kind(outcome: _UnitOutcome) -> str:
    """The failure kind of an external gate hop routed straight to ``fail``, else ``""``."""
    verify = outcome.hops[0].verify if outcome.hops else None
    label = verify.get("label") if verify else None
    return _GATE_FAILURE_KINDS.get(str(label), "") if label else ""


def _screen_gate_text(ctx: _UnitContext, role: str, text: str) -> str | None:
    """*text* as untrusted ``pre_input`` content, the way an MCP result is screened
    (``tools.screen_tool_result``), then redacted; ``None`` when policy blocks it."""

    screened = _tools.screen_tool_result(
        role,
        _tools.ToolOutcome(True, content=text),
        source="an external gate",
        detail=f"task={ctx.task_id!r}",
        blocked_action="gate.reasons_blocked",
        warn_action="gate.reasons_warn",
        project=ctx.project,
    )
    return _trace.redact(screened.content) if screened.ok else None


def _parse_gate_reasons(
    ctx: _UnitContext, role: str, path: Path
) -> tuple[list[dict[str, Any]], bool]:
    """The verifier's reasons file as ``(screened reasons, invalid)``: UTF-8 JSON of at most 64 KiB,
    ``{"reasons": [{"summary": str, ...}]}``. Anything else, or a policy block, is invalid;
    no field is read for control flow."""
    try:
        if not path.is_file():
            return [], False
        if path.stat().st_size > _GATE_REASONS_MAX_BYTES:
            return [], True
        doc = _json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return [], True
    raw = doc.get("reasons") if isinstance(doc, dict) else None
    if not isinstance(raw, list):
        return [], True
    reasons: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict) or not isinstance(entry.get("summary"), str):
            return [], True
        clean: dict[str, Any] = {}
        for key in _GATE_REASON_TEXT_FIELDS:
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                screened = _screen_gate_text(ctx, role, value)
                if screened is None:
                    return [], True
                clean[key] = screened
        if isinstance(entry.get("line"), int) and not isinstance(entry.get("line"), bool):
            clean["line"] = entry["line"]
        if "summary" not in clean:
            return [], True
        reasons.append(clean)
    return reasons, False


def _source_field(source: str) -> dict[str, str]:
    return {"source": source} if source else {}


def _evaluate_external_gate(
    ctx: _UnitContext,
    gate: _gates.ExternalGate,
    node: _orch.PlannedUnit,
    role: str,
    member_id: str,
    hop: HopResult,
    prior: list[HopResult],
    source: str = "",
) -> _UnitOutcome:
    """An ``ExternalGate``: run the operator's command, never the member's ``verifyCmd``; map
    its exit through ``exitMap`` and read its reasons file. The step's ``on`` map routes the
    label, else ``pass`` advances and the rest fail with their kind (pod-dispatch.spec.md)."""
    cmd = gate.command.strip()
    cwd = _gate_cwd(ctx, member_id)
    reasons_path = _gate_reasons_path(ctx.project, ctx.task_id, node.step_id)
    usable = True
    try:
        reasons_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        reasons_path.unlink(missing_ok=True)
    except OSError:
        usable = False
    env = {
        **_task_command_env(ctx, [*prior, hop]),
        "DOCKET_GATE_REASONS_FILE": str(reasons_path),
    }
    run = _run_gate_command(ctx, cmd, cwd, gate.timeout or ctx.resolved_verify_timeout, env)
    # The status is the process's own exit; a command that never reached one is `error`.
    code = -1 if run.code is None else run.code
    label = gate.label_for(code)
    reasons, invalid = _parse_gate_reasons(ctx, role, reasons_path) if usable else ([], False)
    evidence = _gate_evidence(cmd, code, run)
    evidence["label"] = label
    if source:
        evidence["source"] = source
    if reasons:
        evidence["reasons"] = reasons
    evidence["reasonsInvalid"] = invalid
    hop.verify = evidence
    if _match_on_route(node.on, label) is not None:
        return _UnitOutcome(kind="routed", hops=[hop], label=label)
    if label == "pass":
        _trace_locked(
            ctx.project,
            ctx.session_id,
            role,
            "tool_result",
            _json.dumps({"verification": "passed", "cmd": cmd, **_source_field(source)}),
        )
        return _UnitOutcome(kind="advance", hops=[hop], label=label)
    _trace_locked(
        ctx.project,
        ctx.session_id,
        role,
        "verification_failed",
        _json.dumps({"cmd": cmd, "output": run.redacted, "label": label, **_source_field(source)}),
    )
    return _UnitOutcome(
        kind="failed",
        hops=[hop],
        reason=f"external gate {label}: {cmd!r}",
        failure_kind=_GATE_FAILURE_KINDS[label],
    )


def _evaluate_verdict_gate(
    ctx: _UnitContext,
    gate: _gates.VerdictGate,
    node: _orch.PlannedUnit,
    role: str,
    hop: HopResult,
) -> _UnitOutcome:
    """A ``VerdictGate``: pass/rework/fail on the hop's already-parsed verdict (reused from
    the hop's own artifact, never reparsed from ``run_res.output``); a verdict named in the
    step's own ``on`` map routes instead, beating the rework/fail handling below."""
    assert hop.artifact is not None
    verdict = hop.artifact.verdict
    hop_output = hop.output
    pass_set = _orch.normalize_values(gate.pass_values, gate.case_sensitive)
    if verdict is not None and verdict in pass_set:
        return _UnitOutcome(kind="advance", hops=[hop], label=verdict)

    if verdict is not None and _match_on_route(node.on, verdict) is not None:
        return _UnitOutcome(kind="routed", hops=[hop], label=verdict)

    rework = gate.rework
    if rework is not None and verdict is not None:
        when_set = _orch.normalize_values(rework.when, gate.case_sensitive)
        if verdict in when_set:
            cycles_so_far = ctx.rework_counts.get(node.step_id, 0)
            target_index = ctx.id_to_index.get(rework.to)
            if cycles_so_far < rework.max_cycles and target_index is not None:
                ctx.rework_counts[node.step_id] = cycles_so_far + 1
                rework_event, _unused1, _unused2 = _verdict_event_names(role)
                redacted = _trace.redact(hop_output)
                _trace_locked(
                    ctx.project,
                    ctx.session_id,
                    role,
                    rework_event,
                    _json.dumps({"cycle": ctx.rework_counts[node.step_id], "output": redacted}),
                )

                # Record REQUEST-CHANGES to the corrections ledger
                if verdict and verdict.lower() == "request-changes":
                    _corrections.record(
                        ctx.project,
                        "request_changes",
                        task_id=ctx.task_id,
                        role=role,
                        text=hop_output,
                        source="reviewer",
                    )

                return _UnitOutcome(kind="rework", hops=[hop], rework_target_index=target_index)
            # Rework budget exhausted (or, defensively, no valid target) —
            # this verdict is now terminal.
            _unused3, rejected_event, _unused4 = _verdict_event_names(role)
            redacted = _trace.redact(hop_output)
            _trace_locked(
                ctx.project,
                ctx.session_id,
                role,
                rejected_event,
                _json.dumps({"cycles": cycles_so_far, "output": redacted}),
            )
            return _UnitOutcome(
                kind="failed",
                hops=[hop],
                reason=(
                    f"{role} rejected after {cycles_so_far} rework cycle(s): {verdict.upper()}"
                ),
            )

    # Anything else is either truly unparseable (no match at all) or a
    # real, parsed marker that's simply neither a pass nor a
    # rework-trigger — distinct outcomes (though, for the tester role
    # specifically, they share one event name — see
    # `_verdict_event_names`).
    _unused5, rejected_event2, unparseable_event = _verdict_event_names(role)
    redacted = _trace.redact(hop_output)
    if verdict is None:
        _trace_locked(
            ctx.project,
            ctx.session_id,
            role,
            unparseable_event,
            _json.dumps({"verdict": "unparseable", "output": redacted}),
        )
        return _UnitOutcome(
            kind="failed",
            hops=[hop],
            reason=f"{role} output unparseable (expected one unambiguous recognized "
            "verdict marker at the start of a line)",
        )
    _trace_locked(
        ctx.project,
        ctx.session_id,
        role,
        rejected_event2,
        _json.dumps({"verdict": verdict, "output": redacted}),
    )
    return _UnitOutcome(kind="failed", hops=[hop], reason=f"{role} reported {verdict.upper()}")


def _evaluate_post_hop_gate(
    ctx: _UnitContext,
    node: _orch.PlannedUnit,
    role: str,
    member_id: str,
    hop: HopResult,
    prior: list[HopResult],
    *,
    check_approval: bool,
) -> _UnitOutcome:
    """Resolve this step's post-hop gate generically, by the gate's own type. See
    pod-dispatch.spec.md ("Generalized gate execution"). An ``ApprovalGate`` was already
    handled pre-hop, so once the turn has run it simply advances."""
    gate = node.gate
    if gate is None:
        return _UnitOutcome(kind="advance", hops=[hop])

    if isinstance(gate, _gates.MechanicalGate):
        return _evaluate_mechanical_gate(ctx, gate, node, role, member_id, hop)

    if isinstance(gate, _gates.ExternalGate):
        return _evaluate_external_gate(ctx, gate, node, role, member_id, hop, prior)

    if isinstance(gate, _gates.VerdictGate):
        return _evaluate_verdict_gate(ctx, gate, node, role, hop)

    if isinstance(gate, _gates.ApprovalGate):
        if not check_approval:
            return _UnitOutcome(
                kind="failed",
                hops=[hop],
                reason=f"{role}: an 'approval' gate is not supported inside a parallel group",
            )
        # Pre-hop already handled this (above) — post-hop, nothing further
        # to check; a granted/override'd approval simply advances.
        return _UnitOutcome(kind="advance", hops=[hop])

    return _UnitOutcome(kind="advance", hops=[hop])  # pragma: no cover - closed Gate union


def _evaluate_hop_gates(
    ctx: _UnitContext,
    node: _orch.PlannedUnit,
    role: str,
    member_id: str,
    hop: HopResult,
    prior: list[HopResult],
    *,
    check_approval: bool,
) -> _UnitOutcome:
    """The step's own gate, then the task's gate when this is the step it follows and the own
    gate passed; a non-passing task gate decides the outcome (pod-dispatch.spec.md)."""
    outcome = _evaluate_post_hop_gate(
        ctx, node, role, member_id, hop, prior, check_approval=check_approval
    )
    gate = ctx.task_gate
    if gate is None or node.step_id != ctx.task_gate_step_id:
        return outcome
    if outcome.kind != "advance" and not (outcome.kind == "routed" and outcome.label == "pass"):
        return outcome
    own = hop.verify
    task_outcome = _evaluate_external_gate(
        ctx, gate, node, role, member_id, hop, prior, source="task"
    )
    if task_outcome.label != "pass":
        return task_outcome
    if own is not None:
        hop.verify = {**own, "taskGate": hop.verify}
    return outcome


def _resolve_gate_override(task: dict[str, Any]) -> int | None:
    """A granted approval's single-use override for this one claim (see
    ``_claim_next_task``), consumed the first time this run reaches that pipeline position,
    so a later hop at the same position (a rework cycle) still gates normally."""
    override_index = task.get("gateOverridePipelineIndex")
    return override_index if isinstance(override_index, int) else None


def _latest_implementer_evidence(prior: list[HopResult]) -> dict[str, Any]:
    """The evidence of the latest successful Implementer hop in *prior*, ``{}`` when none."""
    for hop in reversed(prior):
        if hop.role == "implementer" and hop.ok and hop.evidence is not None:
            return hop.evidence
    return {}


def _task_command_env(
    ctx: _UnitContext, prior: list[HopResult], step_env: dict[str, str] | None = None
) -> dict[str, str]:
    """A command step's environment: the step's own ``env`` under the task's coordinates -- its
    id, and the base and head commits of the latest successful Implementer hop's evidence
    (empty strings when there is none). The coordinates always win."""
    evidence = _latest_implementer_evidence(prior)
    return {
        **(step_env or {}),
        "DOCKET_TASK_ID": ctx.task_id,
        "DOCKET_BASE_COMMIT": str(evidence.get("baseCommit") or ""),
        "DOCKET_HEAD_COMMIT": str(evidence.get("commit") or ""),
    }


def _run_in_envelope(
    project: str,
    label: str,
    cmd: str,
    cwd: str,
    timeout: int,
    env: dict[str, str] | None = None,
) -> tuple[int | None, str]:
    """Run a verify or ``run:`` command under the pod's isolation posture (jail when isolation
    is on, refused with no usable backend, host otherwise): ``(exit status or None, output)``."""
    jail, refusal = _isolation_posture.resolve_command_jail(project, label)
    if refusal is not None:
        return None, f"[{label} not run: {refusal}]"
    if jail is not None:
        linked = _prepare.linked_entries(cwd)
        jail = replace(jail, read_only=(*jail.read_only, *linked)) if linked else jail
        return _jail.run_command(cmd, cwd, timeout, env=env, jail=jail)
    if env is None:
        return _jail.run_command(cmd, cwd, timeout)
    return _jail.run_command(cmd, cwd, timeout, env=env)
