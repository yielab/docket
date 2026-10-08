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
from docket.cli._setup import _version_callback

app = typer.Typer(
    name="docket",
    help="docket project agent manager",
    add_completion=False,
    no_args_is_help=False,
    invoke_without_command=True,
)


@app.callback(invoke_without_command=True)
def _default(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True, help="Show version"
    ),
) -> None:
    if ctx.invoked_subcommand is None:
        ui.console.print("[bold]docket[/bold] — project agent manager")
        ui.console.print("  docket init          initialize this project (Lead + Implementer)")
        ui.console.print("  docket status        show the current project's status")
        ui.console.print("  docket status --all  show global status by project")
        ui.console.print("  docket pod add <role>  add an agent to the current pod")
        ui.console.print("  docket setup         set up this workstation (model endpoint first)")


app.add_typer(_setup.setup_app)
_setup.setup_app.add_typer(_setup_model.provider_app)
_setup.setup_app.add_typer(_setup_model.model_app)
_setup.setup_app.add_typer(_setup_sandbox.sandbox_app)
_setup.setup_app.command("shell")(_setup_shell.cmd_shell)
_setup.setup_app.add_typer(_setup_notify.notify_app)
_setup.setup_app.add_typer(_setup_export.export_app)
_setup.setup_app.add_typer(_setup_mcp.mcp_app)
app.command("status")(_status.cmd_status)
app.command(
    "init",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_agents.cmd_init)
app.add_typer(_pod.pod_app)
app.command(
    "pipeline",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_pod_config.cmd_pipeline)
app.command(
    "roles",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_pod_config.cmd_roles)
app.command("exec")(_exec.cmd_exec)
app.add_typer(_log.log_app)
app.command("start")(_service.cmd_start)
app.command("stop")(_service.cmd_stop)
app.command("validate")(_pod_config.cmd_validate)
app.command(
    "plugins",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_pod_config.cmd_plugins)
app.command(
    "recipes",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_pod_config.cmd_recipes)
app.command(
    "policies",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_pod_config.cmd_policies)
app.command("inbox")(_inbox.cmd_inbox)
app.add_typer(_task.task_app)
app.command("run")(_run.cmd_run)
