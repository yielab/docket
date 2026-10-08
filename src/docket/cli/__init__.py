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
    _remove,
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
        ui.console.print("  docket add <role>    add an agent to the current pod")
        ui.console.print("  docket setup         set up this workstation (model endpoint first)")
        ui.console.print("  docket help          show the full command reference")


app.add_typer(_setup.setup_app)
_setup.setup_app.add_typer(_setup_model.provider_app)
_setup.setup_app.add_typer(_setup_model.model_app)
_setup.setup_app.add_typer(_setup_sandbox.sandbox_app)
_setup.setup_app.command("shell")(_setup_shell.cmd_shell)
app.command("list")(_remove.cmd_list)
app.command("status")(_status.cmd_status)
app.command(
    "add",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_pod.cmd_add)
app.command(
    "init",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_agents.cmd_init)
app.command("info")(_pod.cmd_info)
app.command("delete")(_pod.cmd_delete)
app.command(
    "maintain",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_pod.cmd_maintain)
app.command(
    "context",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_remove.cmd_context)
app.command("wire")(_setup_notify.cmd_wire)
app.command("unwire")(_setup_notify.cmd_unwire)
app.command("scope")(_remove.cmd_scope)
app.command("profile")(_pod.cmd_profile)
app.command("persona")(_remove.cmd_persona)
app.command(
    "pod",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_pod.cmd_pod)
app.command(
    "pipeline",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_pod_config.cmd_pipeline)
app.command(
    "roles",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_pod_config.cmd_roles)
app.command("logs")(_remove.cmd_logs)
app.command("edit")(_remove.cmd_edit)
app.command("cost")(_status.cmd_cost)
app.command(
    "config",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_pod_config.cmd_config)
app.command(
    "conversations",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_setup_notify.cmd_conversations)
app.command(
    "runs",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_task.cmd_runs)
app.command(
    "harness",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_exec.cmd_harness)
app.command(
    "mcp",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_setup_mcp.cmd_mcp)
app.command("audit")(_log.cmd_audit)
app.command("snapshot")(_status.cmd_snapshot)
app.command("serve")(_service.cmd_serve)
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
    "exporters",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_setup_export.cmd_exporters)
app.command(
    "channels",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_setup_notify.cmd_channels)
app.command(
    "notify",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_setup_notify.cmd_notify)
app.command(
    "trace",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_task.cmd_trace)
app.command("metrics")(_status.cmd_metrics)
app.command(
    "policies",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_pod_config.cmd_policies)
app.command("approve")(_task.cmd_approve)
app.command("deny")(_task.cmd_deny)
app.command(
    "chat",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_task.cmd_chat)
app.command(
    "inbox",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(_inbox.cmd_inbox)
app.command("help")(_remove.cmd_help)
