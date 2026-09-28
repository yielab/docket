"""``docket chat`` -- the foreground way to see and answer one task's parked question.

Reads the task by id, across every pod or the one named by ``--pod``, and shows its brief,
its pending question (if any) and its earlier answers. On a TTY, a pending question is
followed by one prompt per schema property, then answered through the same
``core.answers.answer_task`` every other surface calls (``channel="cli"``). Off a TTY, or
with no pending question, this command only ever displays -- see ``docket pod <p> answer``
for the non-interactive path.
"""

from __future__ import annotations

import getpass as _getpass
import sys
from typing import Any

from docket import ui
from docket.core import answers as _answers
from docket.core import dispatch as _dispatch
from docket.core import operator_contract as _oc

_TYPE_COERCERS: dict[str, Any] = {
    "integer": int,
    "number": float,
    "boolean": lambda v: v.strip().lower() in ("1", "true", "yes", "y"),
}


def _actor() -> str:
    try:
        return _getpass.getuser()
    except Exception:
        return "?"


def _parse_args(args: list[str]) -> tuple[str | None, str | None]:
    """``<task-id> [--pod <project>]`` in any order."""
    task_id: str | None = None
    pod: str | None = None
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--pod":
            pod = args[i + 1] if i + 1 < len(args) else None
            i += 2
        elif tok.startswith("--pod="):
            pod = tok.split("=", 1)[1]
            i += 1
        elif task_id is None:
            task_id = tok
            i += 1
        else:
            i += 1
    return task_id, pod


def _find_task(task_id: str, pod: str | None) -> tuple[str, dict[str, Any]] | None:
    projects = [pod] if pod else _dispatch.dispatchable_pods()
    for project in projects:
        for task in _dispatch.read_tasks(project):
            if task.get("id") == task_id:
                return project, task
    return None


def _render_brief(brief_raw: dict[str, Any]) -> None:
    try:
        brief = _oc.TaskBrief.model_validate(brief_raw)
    except Exception:
        return
    ui.console.print(f"  Objective: {brief.objective}")
    if brief.acceptance:
        ui.console.print("  Acceptance:")
        for item in brief.acceptance:
            ui.console.print(f"    - {item}")
    if brief.expected_risky_actions:
        ui.console.print("  Expected risky actions:")
        for item in brief.expected_risky_actions:
            ui.console.print(f"    - {item}")


def _render_answers(answers: list[dict[str, Any]]) -> None:
    if not answers:
        return
    ui.console.print("  Earlier answers:")
    for a in answers:
        ui.console.print(f"    Q: {a.get('message', '')}")
        ui.console.print(f"    A ({a.get('action', '')}): {a.get('content')}")


def _prompt_for_content(schema: dict[str, Any]) -> dict[str, Any]:
    """One ``input()`` prompt per schema property; a blank optional property is
    omitted, a blank required one is passed through unchanged so the caller's own
    schema validation reports it (never a client-side retry loop)."""
    properties: dict[str, Any] = schema.get("properties", {})
    required: list[str] = schema.get("required", [])
    content: dict[str, Any] = {}
    for name, prop in properties.items():
        label = f"{name}{' (required)' if name in required else ''}"
        raw_value = input(f"  {label}: ").strip()
        if not raw_value and name not in required:
            continue
        coerce = _TYPE_COERCERS.get(prop.get("type"))
        if coerce is not None:
            try:
                content[name] = coerce(raw_value)
                continue
            except ValueError:
                pass
        content[name] = raw_value
    return content


def run_chat(args: list[str]) -> int:
    """``docket chat <task-id> [--pod <project>]``."""
    task_id, pod = _parse_args(args)
    if not task_id:
        ui.error("Usage: docket chat <task-id> [--pod <project>]")
        return 1

    found = _find_task(task_id, pod)
    if found is None:
        scope = f" in pod '{pod}'" if pod else ""
        ui.error(f"Task '{task_id}' not found{scope}.")
        return 1
    project, task = found

    ui.header(f"Task {task_id}")
    ui.console.print(f"  Pod: {project}   Status: {task.get('status', '')}")
    description = task.get("description") or task.get("reason") or ""
    if description:
        ui.console.print(f"  {description}")

    brief_raw = task.get("brief")
    if isinstance(brief_raw, dict):
        _render_brief(brief_raw)

    answers_raw = task.get("answers")
    if isinstance(answers_raw, list):
        _render_answers([a for a in answers_raw if isinstance(a, dict)])

    question_raw = task.get("question")
    if task.get("status") != "waiting_input" or not isinstance(question_raw, dict):
        ui.console.print()
        ui.dim("  No pending question.")
        return 0

    ui.console.print()
    ui.console.print(f"  Question: {question_raw.get('message', '')}")
    schema = question_raw.get("requestedSchema", {})

    if not sys.stdin.isatty():
        ui.dim(
            "  Not a TTY -- showing the question only. Answer with: "
            f"docket pod {project} answer {task_id} ..."
        )
        return 0

    content = _prompt_for_content(schema)
    try:
        _answers.answer_task(project, task_id, "accept", content, channel="cli", actor=_actor())
    except _answers.AnswerRejected as exc:
        ui.error(f"Answer blocked by policy '{exc.policy_id}'.")
        return 1
    except _answers.AnswerError as exc:
        ui.error(str(exc))
        return 1
    ui.success(f"Answered task '{task_id}'.")
    return 0
