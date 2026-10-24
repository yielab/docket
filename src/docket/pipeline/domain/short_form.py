from __future__ import annotations

import re
from typing import Any

# ── Short form ─────────────────────────────────────────────────────────────────
#
# The one authored form of a step: `<id>: <role-or-agent>` plus optional `verify`/`verdict`/
# `approval`/`gate`/`instructions`/`timeout`/`retries`/`model`/`archetype`/`when`/`on`/`until`/
# `max` keys, `<id>: {run: ...}`, `<id>: {input: ...}` or `<id>: {parallel: [...]}`. A step
# written with an `id:` key (the canonical form, which is the in-memory model) is refused. See
# specs/functional/pipeline-format.spec.md ("Short form", "Outcome routing").

_STEP_SUGAR_KEYS = frozenset(
    {
        "verify",
        "verdict",
        "approval",
        "gate",
        "instructions",
        "timeout",
        "retries",
        "model",
        "on",
        "until",
        "max",
        "archetype",
        "when",
    }
)
_BASE_ROLES = frozenset({"lead", "implementer", "reviewer", "tester"})
_NO_ON = object()
_EXTERNAL_GATE_KEYS = frozenset({"external", "timeout", "exitMap"})


class _ShortFormError(ValueError):
    """Raised for an ``on:`` shape the executor cannot run yet; ``load_pipeline`` turns
    this into an ordinary entry in its ``errors`` list, same as any other load error."""


class CanonicalStepError(_ShortFormError):
    """A step is written in the canonical spelling (an ``id:`` key) instead of the short form."""


def _get_on(entry: dict[Any, Any]) -> Any:
    # PyYAML's default resolver reads an unquoted `on:` key as the boolean `True`
    # (the same implicit-boolean "Norway problem" `rework.when`'s own name avoids) --
    # a quoted `"on":` key stays the string "on", so both are accepted here.
    if "on" in entry:
        return entry["on"]
    if True in entry:
        return entry[True]
    return _NO_ON


def _looks_like_member_id(value: str) -> bool:
    # Shape check for a `pod.parse_member_id`-style id (e.g. "myshop-implementer" or
    # "myshop-implementer-2") without importing `pod`, mirroring the slug-shape check
    # this module already applies to `archetype`.
    parts = value.split("-")
    if len(parts) < 2:
        return False
    tail = parts[-1]
    if tail.isdigit():
        return len(parts) >= 3 and parts[-2] in _BASE_ROLES
    return tail in _BASE_ROLES


def _assign_target(step: dict[str, Any], value: str) -> None:
    if value in _BASE_ROLES or not _looks_like_member_id(value):
        step["role"] = value
    else:
        step["agent"] = value


def _escape_marker(value: str) -> str:
    # re.escape is deliberately over-cautious outside character classes (it escapes
    # "-", which is never special there); undo that so a plain marker list round-trips
    # to the exact hand-written pattern text an author would otherwise type.
    return re.escape(value).replace("\\-", "-")


def _build_verdict_gate(markers: Any) -> dict[str, Any]:
    if not isinstance(markers, list) or not markers:
        return {"type": "verdict", "pattern": "", "passValues": []}
    values = [str(m) for m in markers]
    pattern = r"^\s*(" + "|".join(_escape_marker(v) for v in values) + r")\b"
    return {"type": "verdict", "pattern": pattern, "passValues": [values[0].lower()]}


def _build_mechanical_gate(step_id: str, verify: Any) -> dict[str, Any]:
    if isinstance(verify, dict):
        unknown = sorted(str(k) for k in set(verify) - {"command", "timeout"})
        if unknown:
            raise _ShortFormError(
                f"step {step_id!r}: 'verify' takes 'command' and 'timeout' (got {', '.join(unknown)})"
            )
        return {"type": "mechanical", **verify}
    return (
        {"type": "mechanical", "command": verify}
        if isinstance(verify, str)
        else {"type": "mechanical"}
    )


def _build_approval_gate(approval: Any) -> dict[str, Any]:
    return (
        {"type": "approval", "message": approval}
        if isinstance(approval, str)
        else {"type": "approval"}
    )


def _build_external_gate(step_id: str, gate: Any) -> dict[str, Any]:
    if not isinstance(gate, dict) or "external" not in gate or set(gate) - _EXTERNAL_GATE_KEYS:
        raise _ShortFormError(
            f"step {step_id!r}: 'gate' must be '{{external: <command>}}' "
            "(optionally with 'timeout' and 'exitMap')"
        )
    return {"type": "external", "command": gate["external"]} | {
        k: v for k, v in gate.items() if k != "external"
    }


def _try_build_rework(step_id: str, on: Any, seen_ids: list[str]) -> dict[str, Any] | None:
    """The canonical ``rework:`` mapping for the one recognized single-bounded-backward
    shorthand, else ``None`` (meaning *on* becomes the step's own canonical ``on`` field
    instead). A backward goto missing ``max`` keeps its own actionable error."""
    if not isinstance(on, dict) or len(on) != 1:
        return None
    label, action = next(iter(on.items()))
    if not isinstance(action, dict) or "goto" not in action or set(action) - {"goto", "max"}:
        return None
    goto = action["goto"]
    if not isinstance(goto, str) or goto not in seen_ids:
        return None
    if "max" not in action:
        raise _ShortFormError(f"step {step_id!r}: rework to {goto!r} requires 'max'")
    return {"to": goto, "when": [str(label).lower()], "maxCycles": action["max"]}


def _build_gate(
    step_id: str, entry: dict[Any, Any], seen_ids: list[str]
) -> tuple[dict[str, Any] | None, Any]:
    on = _get_on(entry)
    gate_keys = [key for key in ("verdict", "verify", "approval", "gate") if key in entry]
    if len(gate_keys) > 1:
        raise _ShortFormError(f"step {step_id!r}: one gate per step (got {', '.join(gate_keys)})")
    if "verdict" in entry:
        gate = _build_verdict_gate(entry["verdict"])
        if on is not _NO_ON:
            rework = _try_build_rework(step_id, on, seen_ids)
            if rework is not None:
                gate["rework"] = rework
                on = _NO_ON
        return gate, on
    if "verify" in entry:
        return _build_mechanical_gate(step_id, entry["verify"]), on
    if "approval" in entry:
        return _build_approval_gate(entry["approval"]), on
    if "gate" in entry:
        return _build_external_gate(step_id, entry["gate"]), on
    return None, on


def _build_until_route(
    step_id: str, entry: dict[Any, Any], gate: dict[str, Any] | None
) -> dict[str, Any] | None:
    """``until: verify`` + ``max`` sugar, rewritten to ``on: {fail: {goto: <self>,
    max}}`` -- this format's short-form-only repeat-until-mechanical-pass shorthand;
    the canonical form never carries ``until``. See "Outcome routing"."""
    if "until" not in entry:
        return None
    until = entry["until"]
    if until != "verify":
        raise _ShortFormError(f"step {step_id!r}: 'until' must be 'verify' (got {until!r})")
    if gate is None or gate.get("type") != "mechanical":
        raise _ShortFormError(f"step {step_id!r}: 'until: verify' requires a mechanical gate")
    if "max" not in entry:
        raise _ShortFormError(f"step {step_id!r}: 'until: verify' requires 'max'")
    return {"fail": {"goto": step_id, "max": entry["max"]}}


def _normalize_mapping_short_step(step_id: str, target: dict[Any, Any]) -> dict[str, Any]:
    # `- lint: {run: "ruff check ."}` / `- ask: {input: {from: triage}}` -- a one-key mapping
    # whose value is itself a mapping carrying `run` or `input`. The step's own keys live inside
    # *target*, not beside the id (unlike a role/agent short step), and pass through to the
    # canonical step unchanged, so the step model rejects any it does not define.
    step: dict[str, Any] = {"id": step_id}
    for key, value in target.items():
        step["on" if key is True else key] = value
    return step


def _normalize_parallel_short_step(step_id: str, target: dict[Any, Any]) -> dict[str, Any]:
    # `- reviews: {parallel: [{review-code: reviewer}, {review-risk: critic}]}` -- a group
    # whose children are short unit steps; the group itself carries nothing else.
    children = target["parallel"]
    if not isinstance(children, list) or not children:
        raise _ShortFormError(f"step {step_id!r}: 'parallel' must be a non-empty list of steps")
    if set(target) != {"parallel"}:
        raise _ShortFormError(
            f"step {step_id!r}: a parallel group carries only 'parallel'; its children carry the "
            "hop fields"
        )
    seen_children: list[str] = []
    normalized = []
    for child in children:
        if not isinstance(child, dict):
            raise _ShortFormError(f"step {step_id!r}: a parallel child must be a mapping")
        if "id" in child:
            raise CanonicalStepError(_canonical_step_message(child["id"]))
        unit = _normalize_short_step(child, seen_children)
        seen_children.append(str(unit["id"]))
        normalized.append(unit)
    return {"id": step_id, "parallel": normalized}


def _canonical_step_message(step_id: Any) -> str:
    return (
        f"step {step_id!r} is written in the canonical form (an 'id:' key); write the id as the "
        f"key: '- {step_id}: <role>', '- {step_id}: {{run: ...}}', '- {step_id}: {{input: ...}}' "
        f"or '- {step_id}: {{parallel: [...]}}'"
    )


def _normalize_short_step(entry: dict[Any, Any], seen_ids: list[str]) -> dict[str, Any]:
    id_keys = [k for k in entry if k not in _STEP_SUGAR_KEYS and k is not True]
    if len(id_keys) != 1:
        raise _ShortFormError(
            f"a step needs exactly one key that is not a sugar key, the step id "
            f"(got {', '.join(repr(k) for k in id_keys) or 'none'}); write '- <id>: <role>'"
        )
    step_id: str = id_keys[0]
    target = entry[step_id]
    if isinstance(target, dict) and "parallel" in target:
        return _normalize_parallel_short_step(step_id, target)
    if isinstance(target, dict) and ("run" in target or "input" in target):
        return _normalize_mapping_short_step(step_id, target)
    if not isinstance(target, str):
        raise _ShortFormError(
            f"step {step_id!r}: expected a role or agent name, or a mapping carrying "
            "'run', 'input' or 'parallel'"
        )
    step: dict[str, Any] = {"id": step_id}
    _assign_target(step, target)
    for key in ("instructions", "timeout", "retries", "model", "archetype", "when"):
        if key in entry:
            step[key] = entry[key]
    gate, on = _build_gate(step_id, entry, seen_ids)
    if gate is not None:
        step["gate"] = gate
    if "max" in entry and "until" not in entry:
        raise _ShortFormError(f"step {step_id!r}: 'max' requires 'until'")
    until_on = _build_until_route(step_id, entry, gate)
    if until_on is not None:
        if on is not _NO_ON:
            raise _ShortFormError(f"step {step_id!r}: 'until' cannot combine with 'on'")
        on = until_on
    if on is not _NO_ON:
        step["on"] = on
    return step


def _normalize_top_step(entry: Any, seen_ids: list[str]) -> Any:
    if not isinstance(entry, dict):
        return entry
    if "id" in entry:
        raise CanonicalStepError(_canonical_step_message(entry["id"]))
    normalized = _normalize_short_step(entry, seen_ids)
    seen_ids.append(str(normalized["id"]))
    return normalized


def normalize_pipeline(doc: dict[str, Any]) -> dict[str, Any]:
    """Expand the short-form steps of *doc* into the in-memory canonical mapping
    :class:`PipelineSpec` validates; a step written in the canonical form (an ``id:`` key) is
    refused. Pure -- never mutates *doc*, never touches the filesystem."""
    doc = dict(doc)
    steps = doc.get("steps")
    if isinstance(steps, list):
        seen_ids: list[str] = []
        doc["steps"] = [_normalize_top_step(s, seen_ids) for s in steps]
    return doc
