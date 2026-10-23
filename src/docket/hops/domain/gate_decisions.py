"""What each gate decides, as pure functions over facts.

The shell in ``hops/gates`` gathers the facts (an exit code, a verdict, a spent amount, a file's
parsed text), calls one function here, and then records and acts on the decision. Nothing in this
module reads a file, runs a process, reads the clock or the environment, or traces; a decision is
a table of cases (``tests/unit/hops/domain/test_gate_decisions.py``). See ADR 0030 "A context's
domain/ is a functional core for decisions".
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

GATE_FAILURE_KINDS = {
    "fail": "gate_failed",
    "needs_human": "gate_needs_human",
    "error": "gate_error",
}
GATE_REASONS_MAX_BYTES = 64 * 1024
GATE_REASON_TEXT_FIELDS = ("summary", "id", "path", "severity", "detail")


@dataclass(frozen=True)
class GateDecision:
    """One gate's verdict on a hop. ``kind`` is the outcome kind the executor routes on;
    ``event`` names the trace slot the shell records (``""`` for none) and ``detail`` carries the
    fields of that event other than the redacted output."""

    kind: Literal["advance", "routed", "failed", "rework", "blocked"]
    label: str = ""
    reason: str = ""
    failure_kind: str = ""
    event: str = ""
    detail: Mapping[str, Any] = field(default_factory=dict)
    rework_target_index: int | None = None
    record_correction: bool = False


# -- the verify (mechanical) gate ------------------------------------------------------------


def decide_verify_precheck(
    verify_cmd: str, require_verify: bool
) -> Literal["run", "fail_missing", "skip"]:
    """Whether a mechanical gate with *verify_cmd* runs, fails for want of one (the pod
    requires verification) or is skipped visibly."""
    if verify_cmd:
        return "run"
    return "fail_missing" if require_verify else "skip"


def decide_verify(*, passed: bool, routed: bool, cmd: str) -> GateDecision:
    """A mechanical gate after its command ran: ``pass``/``fail`` named in the step's ``on`` map
    routes; otherwise a nonzero exit fails the step and a zero exit advances."""
    label = "pass" if passed else "fail"
    if routed:
        return GateDecision("routed", label=label)
    if not passed:
        return GateDecision("failed", reason=f"verifyCmd failed: {cmd!r}")
    return GateDecision("advance", label=label)


def verify_evidence(
    cmd: str, exit_code: int, duration_s: float, redacted: str, tail_chars: int
) -> dict[str, Any]:
    """The hop's ``verify`` evidence. ``outputTail`` is the tail of the already redacted text,
    so a secret is never one truncation away from surviving into the persisted record."""
    return {
        "cmd": cmd,
        "exitCode": exit_code,
        "durationS": round(duration_s, 3),
        "outputTail": redacted[-tail_chars:],
    }


# -- the external gate -----------------------------------------------------------------------


def decide_external(*, label: str, routed: bool, cmd: str) -> GateDecision:
    """An external gate's *label* (from its exit map): a label the step's ``on`` map names
    routes, ``pass`` advances, and every other label fails with its kind."""
    if routed:
        return GateDecision("routed", label=label)
    if label == "pass":
        return GateDecision("advance", label=label)
    return GateDecision(
        "failed",
        reason=f"external gate {label}: {cmd!r}",
        failure_kind=GATE_FAILURE_KINDS[label],
    )


def external_failure_kind(label: object) -> str:
    """The failure kind of an external gate *label* that failed, ``""`` for any other."""
    return GATE_FAILURE_KINDS.get(str(label), "") if label else ""


def should_run_task_gate(
    *,
    has_task_gate: bool,
    step_id: str,
    task_gate_step_id: str | None,
    outcome_kind: str,
    outcome_label: str,
) -> bool:
    """The task's own gate runs after the step it follows, and only when the step's gate passed
    (advanced, or routed on ``pass``)."""
    if not has_task_gate or step_id != task_gate_step_id:
        return False
    return outcome_kind == "advance" or (outcome_kind == "routed" and outcome_label == "pass")


def clean_gate_reasons(
    doc: Any, screen: Callable[[str], str | None]
) -> tuple[list[dict[str, Any]], bool]:
    """A verifier's parsed reasons file as ``(reasons, invalid)``: ``{"reasons": [{"summary":
    str, ...}]}``, text fields passed through *screen* (``None`` means policy blocked it).
    Anything else is invalid, and no field is read for control flow."""
    raw = doc.get("reasons") if isinstance(doc, dict) else None
    if not isinstance(raw, list):
        return [], True
    reasons: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict) or not isinstance(entry.get("summary"), str):
            return [], True
        clean: dict[str, Any] = {}
        for key in GATE_REASON_TEXT_FIELDS:
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                screened = screen(value)
                if screened is None:
                    return [], True
                clean[key] = screened
        if isinstance(entry.get("line"), int) and not isinstance(entry.get("line"), bool):
            clean["line"] = entry["line"]
        if "summary" not in clean:
            return [], True
        reasons.append(clean)
    return reasons, False


# -- the verdict gate ------------------------------------------------------------------------


@dataclass(frozen=True)
class ReworkFacts:
    """A verdict gate's rework edge as the decision needs it: the verdicts that trigger it, its
    bound, and the index of its target step (``None`` when the target is not in the plan)."""

    when: frozenset[str]
    max_cycles: int
    target_index: int | None


def decide_verdict(
    *,
    verdict: str | None,
    role: str,
    pass_values: frozenset[str],
    routed: bool,
    rework: ReworkFacts | None,
    cycles_so_far: int,
) -> GateDecision:
    """A verdict gate on the hop's parsed *verdict*: pass advances; a verdict the step's ``on``
    map names routes; a rework verdict loops back while its budget lasts and is terminal after;
    anything else fails (unparseable when there is no verdict at all)."""
    if verdict is not None and verdict in pass_values:
        return GateDecision("advance", label=verdict)
    if verdict is not None and routed:
        return GateDecision("routed", label=verdict)
    if rework is not None and verdict is not None and verdict in rework.when:
        if cycles_so_far < rework.max_cycles and rework.target_index is not None:
            return GateDecision(
                "rework",
                event="rework",
                detail={"cycle": cycles_so_far + 1},
                rework_target_index=rework.target_index,
                record_correction=verdict.lower() == "request-changes",
            )
        return GateDecision(
            "failed",
            reason=f"{role} rejected after {cycles_so_far} rework cycle(s): {verdict.upper()}",
            event="rejected",
            detail={"cycles": cycles_so_far},
        )
    if verdict is None:
        return GateDecision(
            "failed",
            reason=f"{role} output unparseable (expected one unambiguous recognized "
            "verdict marker at the start of a line)",
            event="unparseable",
            detail={"verdict": "unparseable"},
        )
    return GateDecision(
        "failed",
        reason=f"{role} reported {verdict.upper()}",
        event="rejected",
        detail={"verdict": verdict},
    )


def decide_approval_in_group(*, check_approval: bool, role: str) -> GateDecision:
    """An ``approval`` gate after its hop: pre-hop already handled it, so it advances, except
    inside a parallel group where it cannot be asked at all."""
    if not check_approval:
        return GateDecision(
            "failed", reason=f"{role}: an 'approval' gate is not supported inside a parallel group"
        )
    return GateDecision("advance")


# -- the output guardrail --------------------------------------------------------------------


@dataclass(frozen=True)
class OutputGuardrail:
    """What the ``pre_output`` scan does to a hop's output: the effective policy hit, whether to
    trace it, redact the output, block it, and the error that failed an ok hop."""

    action: str
    policy_id: str
    trace_check: bool
    redact: bool
    block: bool
    fail_hop: bool
    error: str


def decide_output_guardrail(
    *,
    action: str,
    policy_id: str,
    high_risk: str | None,
    hop_ok: bool,
) -> OutputGuardrail:
    """The policy engine's *action* for the hop's output, raised from ``allow`` to ``warn`` when a
    built-in high-risk class (*high_risk*, its name) matched it -- never downgraded and never past
    ``warn``, since no live approver exists after the hop ran."""
    if high_risk is not None and action == "allow":
        action, policy_id = "warn", f"high-risk:{high_risk}"
    block = action == "block"
    return OutputGuardrail(
        action=action,
        policy_id=policy_id,
        trace_check=action != "allow",
        redact=action == "redact",
        block=block,
        fail_hop=block and hop_ok,
        error=f"blocked by guardrail policy '{policy_id}'",
    )


# -- budgets and limits ----------------------------------------------------------------------


def hop_network(pod_mode: str, task_mode: str | None) -> str:
    """The hop's jail network: ``"none"`` when the pod or the task says so, else ``"open"``.
    A task can only cut the network, never open one the pod closed."""
    return "none" if "none" in (pod_mode, task_mode) else "open"


def task_token_budget(task: Mapping[str, Any]) -> int | None:
    """What *task*'s ``maxTokens`` has left after its persisted hops' counted usage (input minus
    cache reads, plus output); ``None`` without a cap. Zero or less means no hop may start."""
    cap = task.get("maxTokens")
    if not isinstance(cap, int) or isinstance(cap, bool):
        return None
    used = 0
    for hop in task.get("hops") or []:
        usage = hop.get("usage") if isinstance(hop, dict) else None
        if isinstance(usage, dict):
            fresh = int(usage.get("input") or 0) - int(usage.get("cached") or 0)
            used += max(0, fresh) + int(usage.get("output") or 0)
    return cap - used


def decide_task_tokens(*, left: int | None, max_tokens: object, role: str) -> GateDecision:
    """Fail the task with ``failureKind: "budget"`` when its ``maxTokens`` is spent before *role*."""
    if left is None or left > 0:
        return GateDecision("advance")
    return GateDecision(
        "failed",
        reason=f"task token budget reached (maxTokens={max_tokens}) before {role}",
        failure_kind="budget",
    )


def decide_pod_budget(*, cap: float, spent: float, estimated: bool, role: str) -> GateDecision:
    """The pod's spend against its *cap* before a hop. No cap, or spend under it, advances; a
    tripped cap blocks the task (and the shell pauses the Lead)."""
    if cap <= 0.0 or spent < cap:
        return GateDecision("advance")
    spent_label = f"~${spent:.2f} (estimated — no cost recorded)" if estimated else f"${spent:.2f}"
    return GateDecision(
        "blocked",
        reason=f"pod budget reached ({spent_label} ≥ ${cap:.2f}) before {role}",
        event="budget_exceeded",
        detail={
            "spent": round(spent, 6),
            "cap": round(cap, 6),
            "role": role,
            "estimated": estimated,
        },
    )


def unpriced_budget_warning(*, cap: float, model: str, unpriced: bool) -> str | None:
    """Under a budget, a model the estimate cannot price leaves the cap unable to stop its spend:
    the warning text, else ``None``."""
    if cap <= 0.0 or not unpriced:
        return None
    return f"pod budget ${cap:.2f} cannot stop this hop: {model} has no price"


# -- approval, resources, profile, protected paths -------------------------------------------


def decide_pre_hop_approval(
    *, check_approval: bool, index: int, override_index: int | None, requires_approval: bool
) -> Literal["proceed", "consume_override", "require"]:
    """Before a hop: a granted approval's single-use override at this position is consumed; a
    step that requires approval parks for one; anything else proceeds."""
    if not check_approval:
        return "proceed"
    if index == override_index:
        return "consume_override"
    return "require" if requires_approval else "proceed"


def missing_resources(
    items: Sequence[str],
    *,
    secrets: frozenset[str],
    existing_paths: frozenset[str],
    has_verify_cmd: bool,
) -> list[str]:
    """The entries of a brief's ``resources`` a deterministic check cannot confirm: a secret not
    configured, a path that does not exist, or ``verify`` with no ``verifyCmd``."""
    missing: list[str] = []
    for item in items:
        if item.startswith("secret:"):
            ok = item[len("secret:") :] in secrets
        elif item.startswith("path:"):
            ok = item[len("path:") :] in existing_paths
        elif item == "verify":
            ok = has_verify_cmd
        else:
            continue
        if not ok:
            missing.append(item)
    return missing


def decide_resources(missing: Sequence[str]) -> GateDecision:
    """A ``READY`` brief whose resources are missing blocks the task with reason ``resources``."""
    if not missing:
        return GateDecision("advance")
    return GateDecision(
        "blocked", label="resources", reason="brief names missing resources: " + ", ".join(missing)
    )


def profile_refusal(violations: Sequence[tuple[str, str, str]]) -> tuple[str, str] | None:
    """Under the ``lights-out`` profile, unmet ``(requirement, detail, fix)`` triples refuse the
    task: ``(requirement names for the audit entry, error message)``, ``None`` when none."""
    if not violations:
        return None
    names = ",".join(v[0] for v in violations)
    lines = "; ".join(f"{req}: {detail} ({fix})" for req, detail, fix in violations)
    return names, f"lights-out profile not met -- {lines}"


def describe_changed_paths(paths: Sequence[str], max_listed: int) -> str:
    """The protected paths a change edits, at most *max_listed* of them, then a count of the rest."""
    listed = ", ".join(paths[:max_listed])
    if len(paths) > max_listed:
        listed += f" and {len(paths) - max_listed} more"
    return listed
