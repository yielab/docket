"""``docket pod test``: run a prompt's tests file against a model and record the result.
Registered onto ``pod_app`` by the registry."""

from __future__ import annotations

import re
from typing import NoReturn

import typer
from rich.markup import escape

from docket import bootstrap as _bootstrap
from docket.interfaces.cli.commands.pod_config import _fail, _scope_pod
from docket.interfaces.cli.commands.target import pod_option
from docket.interfaces.cli.render import ui
from docket.kernel.home import current_home
from docket.teams import model_selection as _models
from docket.teams import prompt_tests as _tests
from docket.teams import prompts as _prompts

_REF = re.compile(r"^(identity|task|hop)/([a-z][a-z0-9-]*)$")


def _refuse(what: str, do: str = "") -> NoReturn:
    ui.error(what, do)
    raise typer.Exit(2)


def _show(entry: dict[str, object], *, recorded: bool) -> None:
    head = f"{entry['result']}: {entry['prompt']} ({entry['cases']} cases)"
    ui.dim(f"recorded result, no model called - {head}" if recorded else head)
    failed = entry.get("failed")
    if isinstance(failed, list):
        for name in failed:
            ui.dim(f"  failed: {escape(str(name))}")


def cmd_test(
    prompt: str = typer.Argument(..., help="The prompt to test, as <layer>/<name> (hop/reviewer)"),
    model: str | None = typer.Option(
        None, "--model", help="provider/model to test; default is the model of the prompt's role"
    ),
    pod: str | None = pod_option(),
    force: bool = typer.Option(
        False, "--force", help="Run again although this model and prompt text have a result"
    ),
) -> None:
    """Run a prompt's tests against a model; exit 0 on pass, 1 on fail, 2 when it cannot run.

    The prompt's `tests` file holds cases (an input and assertions: contains, matchesSchema,
    calledHandoff, underTokens). Each case is one call to the model. The result is recorded once
    per model and prompt text, so a repeat reads the record; a role whose `floor` names this prompt
    refuses a model recorded as failed.

    Example: docket pod test hop/reviewer --model local/qwen"""
    match = _REF.match(prompt)
    if match is None:
        _refuse(f"'{prompt}' is not a prompt reference", "Use <layer>/<name>, e.g. hop/reviewer")
    layer, name = match.groups()
    project = _scope_pod(pod)
    try:
        base = _prompts.resolve_prompt(layer, name, project=project)
        chosen = model or _models.resolve_role_model(base.for_role or name, project=project)
        loaded = _prompts.resolve_prompt(
            layer, name, project=project, model_class=_models.model_class_of(chosen)
        )
    except _prompts.PromptError as exc:
        _refuse(str(exc))
    if loaded.tests is None:
        _refuse(f"{prompt} has no tests file", "Declare `tests:` in its front matter")
    if not force:
        found = _tests.recorded(chosen, loaded.sha256)
        if found is not None:
            _show(found, recorded=True)
            raise typer.Exit(0 if found.get("result") == _tests.PASS else 1)
    backend = _bootstrap.build_driver(current_home()).backend_factory(chosen)
    if backend is None:
        _refuse(f"No endpoint is configured for {chosen}", "Run docket setup model provider")
    try:
        outcome = _tests.run_cases(
            loaded.text,
            _tests.load_cases(loaded.tests),
            backend,
            handoff=loaded.output == "handoff/v1",
        )
    except _tests.PromptTestsError as exc:
        _fail(str(exc), code=2)
    for line in outcome.lines:
        ui.dim(escape(line))
    entry = _tests.record(chosen, loaded.sha256, prompt, outcome)
    _show(entry, recorded=False)
    if outcome.result != _tests.PASS:
        raise typer.Exit(1)
