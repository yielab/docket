"""docket CLI — the Typer application.

Every command is implemented in Python (the Bash→Python migration is complete);
bin/docket is a thin launcher that execs ``python -m docket``. Command modules
live alongside this one in docket.cli; shared services are in docket.core and
docket.edges.
"""

from __future__ import annotations

import typer

from docket import ui
from docket.cli import (
    _agents,
    _exec,
    _inbox,
    _log,
    _pod,
    _pod_config,
    _run,
    _service,
    _setup,
    _setup_export,
    _setup_mcp,
    _setup_model,
    _setup_notify,
    _setup_sandbox,
    _setup_shell,
    _status,
    _task,
)
from docket.cli._help import DAILY as _DAILY
from docket.cli._help import MACHINE as _MACHINE
from docket.cli._help import POD as _POD
from docket.cli._help import DocketGroup
from docket.cli._setup import _version_callback

app = typer.Typer(
    name="docket",
    cls=DocketGroup,
    help=ui.TAGLINE,
    add_completion=False,
    no_args_is_help=False,
    invoke_without_command=True,
    context_settings={"help_option_names": ["--help", "-h"]},
)

_GUIDE = [
    ("docket init", "create the team for this repository"),
    ('docket task add "..."', "queue a task"),
    ("docket run", "run the queued tasks"),
    ("docket status", "see what is happening"),
    ("docket inbox", "answer what is waiting for you"),
]


@app.callback(invoke_without_command=True)
def _default(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True, help="Show version"
    ),
) -> None:
    if ctx.invoked_subcommand is None:
        ui.guide(_GUIDE)


app.command(
    "init",
    rich_help_panel=_DAILY,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_agents.cmd_init)
app.command("status", rich_help_panel=_DAILY)(_status.cmd_status)
app.command("inbox", rich_help_panel=_DAILY)(_inbox.cmd_inbox)
app.add_typer(_task.task_app, rich_help_panel=_DAILY)
app.command("run", rich_help_panel=_DAILY)(_run.cmd_run)
app.add_typer(_pod.pod_app, rich_help_panel=_POD)
app.add_typer(_log.log_app, rich_help_panel=_POD)
app.add_typer(_setup.setup_app, rich_help_panel=_MACHINE)
app.command("start", rich_help_panel=_MACHINE)(_service.cmd_start)
app.command("stop", rich_help_panel=_MACHINE)(_service.cmd_stop)
app.command("exec", rich_help_panel=_MACHINE)(_exec.cmd_exec)
_setup.setup_app.add_typer(_setup_model.provider_app)
_setup.setup_app.add_typer(_setup_model.model_app)
_setup.setup_app.add_typer(_setup_sandbox.sandbox_app)
_setup.setup_app.command("shell")(_setup_shell.cmd_shell)
_setup.setup_app.add_typer(_setup_notify.notify_app)
_setup.setup_app.add_typer(_setup_export.export_app)
_setup.setup_app.add_typer(_setup_mcp.mcp_app)
_pod.pod_app.command("apply")(_pod_config.cmd_apply)
_pod.pod_app.command("export")(_pod_config.cmd_export)
_pod.pod_app.command("validate")(_pod_config.cmd_validate)
_pod.pod_app.command("plan")(_pod_config.cmd_plan)
_pod.pod_app.command("check")(_pod_config.cmd_check)
_pod.pod_app.command("recipes")(_pod_config.cmd_recipes)
_pod.pod_app.command("roles")(_pod_config.cmd_roles)
_pod.pod_app.command("policies")(_pod_config.cmd_policies)
