"""docket CLI — the Typer application.

Every command is implemented in Python (the Bash→Python migration is complete);
bin/docket is a thin launcher that execs ``python -m docket``. Command modules
live alongside this one in docket.cli; shared services are in docket.core and
docket.edges.
"""

from __future__ import annotations

import typer

from docket.interfaces.cli.commands import agents as _agents
from docket.interfaces.cli.commands import inbox as _inbox
from docket.interfaces.cli.commands import log as _log
from docket.interfaces.cli.commands import pod as _pod
from docket.interfaces.cli.commands import pod_config as _pod_config
from docket.interfaces.cli.commands import pod_config_library as _pod_config_library
from docket.interfaces.cli.commands import run as _run
from docket.interfaces.cli.commands import service as _service
from docket.interfaces.cli.commands import setup as _setup
from docket.interfaces.cli.commands import setup_export as _setup_export
from docket.interfaces.cli.commands import setup_mcp as _setup_mcp
from docket.interfaces.cli.commands import setup_model as _setup_model
from docket.interfaces.cli.commands import setup_notify as _setup_notify
from docket.interfaces.cli.commands import setup_sandbox as _setup_sandbox
from docket.interfaces.cli.commands import setup_shell as _setup_shell
from docket.interfaces.cli.commands import status as _status
from docket.interfaces.cli.commands import task as _task
from docket.interfaces.cli.commands.setup import _version_callback
from docket.interfaces.cli.render import ui
from docket.interfaces.cli.render.help import DAILY as _DAILY
from docket.interfaces.cli.render.help import MACHINE as _MACHINE
from docket.interfaces.cli.render.help import POD as _POD
from docket.interfaces.cli.render.help import DocketGroup

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


app.command("init", rich_help_panel=_DAILY)(_agents.cmd_init)
app.command("status", rich_help_panel=_DAILY)(_status.cmd_status)
app.command("inbox", rich_help_panel=_DAILY)(_inbox.cmd_inbox)
app.add_typer(_task.task_app, rich_help_panel=_DAILY)
app.command("run", rich_help_panel=_DAILY)(_run.cmd_run)
app.add_typer(_pod.pod_app, rich_help_panel=_POD)
app.add_typer(_log.log_app, rich_help_panel=_POD)
app.add_typer(_setup.setup_app, rich_help_panel=_MACHINE)
app.command("start", rich_help_panel=_MACHINE)(_service.cmd_start)
app.command("stop", rich_help_panel=_MACHINE)(_service.cmd_stop)
_setup.setup_app.add_typer(_setup_model.provider_app)
_setup.setup_app.add_typer(_setup_model.model_app)
_setup.setup_app.add_typer(_setup_sandbox.sandbox_app)
_setup.setup_app.command("profile")(_setup_sandbox.cmd_profile)
_setup.setup_app.command("shell")(_setup_shell.cmd_shell)
_setup.setup_app.add_typer(_setup_notify.notify_app)
_setup.setup_app.add_typer(_setup_export.export_app)
_setup.setup_app.add_typer(_setup_mcp.mcp_app)
_pod.pod_app.command("update")(_pod_config.cmd_update)
_pod.pod_app.command("export")(_pod_config.cmd_export)
_pod.pod_app.command("validate")(_pod_config.cmd_validate)
_pod.pod_app.command("plan")(_pod_config.cmd_plan)
_pod.pod_app.command("check")(_pod_config.cmd_check)
_pod.pod_app.command("recipes")(_pod_config_library.cmd_recipes)
_pod.pod_app.command("roles")(_pod_config_library.cmd_roles)
_pod.pod_app.command("policies")(_pod_config_library.cmd_policies)
