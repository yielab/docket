"""Lobster YAML workflow validator and planner (CD-7).

docket does not execute Lobster workflows — the Lobster daemon does.
This module provides:
  - ``validate_lobster(text)`` — structural schema check; returns [] on success.
  - ``plan_lobster(text, name)`` — render a human-readable plan the daemon would
    execute, **without running anything**. Honesty rule: the output explicitly
    states that the daemon runs the workflow, not docket.
"""

from __future__ import annotations

from typing import Any

# Known step types and the fields each requires.
_KNOWN_TYPES: frozenset[str] = frozenset({"shell", "llm", "message", "poll", "conditional", "goto"})
_REQUIRED_BY_TYPE: dict[str, list[str]] = {
    "shell": ["command"],
    "llm": ["prompt"],
    "message": ["channel", "message"],
    "poll": [],  # special: needs 'file' or 'files' — checked below
    "conditional": ["condition", "steps"],
    "goto": ["target"],
}


def _load(text: str) -> tuple[dict[str, Any] | None, str]:
    """Parse YAML text. Returns (doc, error). error is '' on success."""
    try:
        import yaml as _yaml  # type: ignore[import-untyped]
    except ImportError:
        return None, "PyYAML not installed — run: pip install pyyaml"
    try:
        doc = _yaml.safe_load(text)
    except Exception as exc:
        return None, f"YAML parse error: {exc}"
    if not isinstance(doc, dict):
        return None, f"workflow document must be a mapping (got {type(doc).__name__})"
    return doc, ""


def validate_lobster(text: str) -> list[str]:
    """Validate Lobster YAML content. Returns [] on success, error strings otherwise.

    Checks performed:
    - YAML parses cleanly.
    - Top-level 'name' and 'steps' fields are present.
    - Each step has 'id' and 'type'.
    - Step IDs are unique.
    - Step type is one of the known types.
    - Type-specific required fields are present.
    """
    doc, err = _load(text)
    if err or doc is None:
        return [err or "parse returned None"]

    errors: list[str] = []

    if "name" not in doc:
        errors.append("missing required top-level field 'name'")
    if "steps" not in doc:
        errors.append("missing required top-level field 'steps'")
        return errors

    steps = doc["steps"]
    if not isinstance(steps, list):
        errors.append("'steps' must be a list")
        return errors
    if not steps:
        errors.append("'steps' must not be empty")

    seen_ids: set[str] = set()
    for i, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            errors.append(f"step {i}: must be a mapping, got {type(step).__name__}")
            continue

        sid = str(step["id"]) if "id" in step else None
        if sid is None:
            errors.append(f"step {i}: missing required field 'id'")
        else:
            if sid in seen_ids:
                errors.append(f"step {i}: duplicate id {sid!r}")
            seen_ids.add(sid)

        if "type" not in step:
            errors.append(f"step {i} ({sid or '?'}): missing required field 'type'")
            continue

        stype = str(step["type"])
        label = f"step {i} ({sid or '?'!r})"
        if stype not in _KNOWN_TYPES:
            known = ", ".join(sorted(_KNOWN_TYPES))
            errors.append(f"{label}: unknown type {stype!r} (known: {known})")
            continue

        for req in _REQUIRED_BY_TYPE.get(stype, []):
            if req not in step:
                errors.append(f"{label}: {stype} step missing required field {req!r}")

        if stype == "poll" and "file" not in step and "files" not in step:
            errors.append(f"{label}: poll step requires 'file' or 'files'")

    return errors


def plan_lobster(text: str, workflow_name: str = "") -> tuple[str, list[str]]:
    """Render a human-readable plan of the resolved pipeline, without executing it.

    Returns (plan_text, []) on success, or ("", [errors]) if validation fails.

    The output **explicitly states** that docket does not execute the workflow
    (honesty rule — the Lobster daemon runs it, not docket).
    """
    errors = validate_lobster(text)
    if errors:
        return "", errors

    doc, _ = _load(text)
    assert doc is not None

    name = str(doc.get("name", workflow_name or "workflow"))
    desc = str(doc.get("description", ""))
    steps: list[dict[str, Any]] = doc["steps"]
    variables: dict[str, Any] = dict(doc.get("variables", {}) or {})

    lines: list[str] = [f"Workflow: {name}"]
    if desc:
        lines.append(f"Description: {desc}")
    lines.append("")
    lines.append(f"Steps ({len(steps)}):")

    for i, step in enumerate(steps, 1):
        sid = str(step.get("id", "?"))
        stype = str(step.get("type", "?"))
        detail = _step_detail(step, stype)
        lines.append(f"  {i:>3}  {sid:<26} {stype:<12} {detail}")

    if variables:
        lines.append("")
        lines.append(f"Variables ({len(variables)}):")
        for k in sorted(variables):
            lines.append(f"  {k}")

    sep = "─" * 72
    lines += [
        "",
        sep,
        "NOTE: docket does not execute this workflow — the Lobster daemon does.",
        f"  To execute:  lobster run --workflow {name}",
        sep,
    ]
    return "\n".join(lines), []


def _step_detail(step: dict[str, Any], stype: str) -> str:
    """One-line summary of a step's content for the plan table."""
    if stype == "shell":
        cmd_lines = str(step.get("command", "")).strip().splitlines()
        first = cmd_lines[0].strip() if cmd_lines else ""
        return first + ("..." if len(cmd_lines) > 1 else "")
    if stype == "llm":
        prompt_lines = str(step.get("prompt", "")).strip().splitlines()
        first = prompt_lines[0].strip() if prompt_lines else ""
        detail = first + ("..." if len(prompt_lines) > 1 else "")
        if step.get("agent"):
            detail = f"agent:{step['agent']}  {detail}"
        return detail
    if stype == "message":
        channel = str(step.get("channel", ""))
        target = str(step.get("target", ""))
        return f"channel:{channel}  -> {target}"
    if stype == "poll":
        if "file" in step:
            base = f"wait: {step['file']}"
        else:
            files: list[str] = list(step.get("files", []))
            base = f"wait: {files[0] if files else '?'}"
            if len(files) > 1:
                base += f" (+{len(files) - 1} more)"
        timeout = step.get("timeout")
        return base + (f"  timeout:{timeout}s" if timeout else "")
    if stype == "conditional":
        cond = str(step.get("condition", "?"))
        return "if " + (cond[:60] + "..." if len(cond) > 60 else cond)
    if stype == "goto":
        return f"-> {step.get('target', '?')}"
    return ""
