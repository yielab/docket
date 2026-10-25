from __future__ import annotations

import getpass as _getpass
from typing import Any

import typer
from rich.markup import escape

from docket.interfaces.cli.commands import contract as _contract
from docket.interfaces.cli.commands import service as _service
from docket.interfaces.cli.render import ui
from docket.kernel.operator_contract import Option, Question, QuestionV11

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


def _resume_hint(project: str) -> None:
    """After a state change: say who picks the task up, or name the command that does."""

    if _service.is_running():
        ui.dim("docket is running and will pick it up")
        return
    _contract.next_step(f"docket run --pod {project}")


def _options(question: Question) -> list[Option]:
    return question.options if isinstance(question, QuestionV11) else []


def _recommended(question: Question) -> str:
    recommendation = question.recommendation if isinstance(question, QuestionV11) else None
    return recommendation.option_id if recommendation is not None else ""


def _option_ids(question: Question) -> list[str]:
    return [o.id for o in _options(question)]


def _parse_fields(fields: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in fields:
        key, sep, value = item.partition("=")
        if not sep or not key:
            ui.error(f"--field {item!r} is not name=value", "Pass --field name=value")
            raise typer.Exit(2)
        out[key] = value
    return out


def _render_options(question: Question) -> None:
    recommended = _recommended(question)
    for option in _options(question):
        mark = " (recommended)" if option.id == recommended else ""
        ui.console.print(escape(f"  {option.id} - {option.label}{mark}"))
        if option.description:
            ui.dim(escape(f"    {option.description}"))


def _prompt_content(question: Question) -> dict[str, Any]:
    """One prompt for the option (blank takes the recommended one), then one per schema
    property; a blank optional property is dropped, a blank required one is left to the
    answer's own validation."""
    content: dict[str, Any] = {}
    recommended = _recommended(question)
    if _option_ids(question):
        default = f" [{recommended}]" if recommended else ""
        content["optionId"] = input(f"  Option{default}: ").strip() or recommended
    schema = question.requested_schema
    required: list[str] = schema.get("required", [])
    for name, prop in schema.get("properties", {}).items():
        label = f"{name}{' (required)' if name in required else ''}"
        raw_value = input(f"  {label}: ").strip()
        if not raw_value and name not in required:
            continue
        coerce = _TYPE_COERCERS.get(prop.get("type"))
        try:
            content[name] = coerce(raw_value) if coerce is not None else raw_value
        except ValueError:
            content[name] = raw_value
    return content


def _answer_content(
    question: Question, text: list[str] | None, option: str | None, fields: list[str]
) -> dict[str, Any]:
    """The content an answer carries, built from flags; prompts on a TTY when none was given."""
    content = _parse_fields(fields)
    words = " ".join(text or []).strip()
    if words:
        properties = question.requested_schema.get("properties", {})
        if len(properties) != 1:
            ui.error("A bare text answer needs a one-property question", "Pass --field name=value")
            raise typer.Exit(1)
        content.setdefault(next(iter(properties)), words)
    if option:
        content["optionId"] = option
    if content:
        return content
    ids = _option_ids(question)
    if not _contract.is_tty():
        if ids:
            ui.error("This question has options", f"Pass --option <id>: {', '.join(ids)}")
        else:
            ui.error("Nothing to answer with", "Pass text, --field name=value or --option <id>")
        raise typer.Exit(1)
    ui.console.print(escape(f"  Question: {question.message}"))
    _render_options(question)
    return _prompt_content(question)
