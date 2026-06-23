"""docket CLI — Typer application with all 33 command stubs.

Each stub exits with code 127 (DOCKET_NOT_PORTED) which the bin/docket dispatcher
recognises as "fall through to Bash". Once a command is fully ported it:
  1. Implements real logic here instead of calling _not_ported().
  2. Is added to lib/core/ported.list so the dispatcher routes to Python.
"""

import sys

import typer

app = typer.Typer(
    name="docket",
    help="OpenClaw project agent manager",
    add_completion=False,
    no_args_is_help=False,
    invoke_without_command=True,
)

# Exit code the dispatcher checks: "not yet ported, fall to Bash"
_NOT_PORTED = 127


def _not_ported(cmd: str) -> None:
    """Signal to the dispatcher that this command is not yet on the Python path."""
    print(f"docket-py: {cmd} not yet ported — falling through to Bash", file=sys.stderr)
    raise typer.Exit(_NOT_PORTED)


# ── default (no subcommand) → list ────────────────────────────────────────────
@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        _not_ported("list")


# ── lifecycle ──────────────────────────────────────────────────────────────────
@app.command("install")
def cmd_install() -> None:
    """Bootstrap OpenClaw + specialist agents."""
    _not_ported("install")


@app.command("list")
def cmd_list(json: bool = typer.Option(False, "--json", help="Emit JSON")) -> None:
    """List all project agents."""
    _not_ported("list")


@app.command("add")
def cmd_add(agent_id: str | None = typer.Argument(None)) -> None:
    """Add a new project agent (interactive)."""
    _not_ported("add")


@app.command("info")
def cmd_info(
    agent_id: str | None = typer.Argument(None),
    json: bool = typer.Option(False, "--json"),
) -> None:
    """Detailed status of one agent."""
    _not_ported("info")


@app.command("delete")
def cmd_delete(agent_id: str | None = typer.Argument(None)) -> None:
    """Remove agent and optionally its workspace."""
    _not_ported("delete")


# ── maintenance ────────────────────────────────────────────────────────────────
@app.command("maintain")
def cmd_maintain(
    agent_id: str | None = typer.Argument(None),
    sub: str | None = typer.Argument(None),
) -> None:
    """Maintain an agent workspace (clean/reset/rebuild/check/sessions)."""
    _not_ported("maintain")


# ── context / memory ──────────────────────────────────────────────────────────
@app.command("context")
def cmd_context(
    agent_id: str | None = typer.Argument(None),
    sub: str | None = typer.Argument(None),
) -> None:
    """Show/search/snapshot/index/compress agent memory."""
    _not_ported("context")


# ── telegram ───────────────────────────────────────────────────────────────────
@app.command("wire")
def cmd_wire(agent_id: str | None = typer.Argument(None)) -> None:
    """Wire or update a Telegram group binding."""
    _not_ported("wire")


@app.command("unwire")
def cmd_unwire(agent_id: str | None = typer.Argument(None)) -> None:
    """Remove Telegram binding."""
    _not_ported("unwire")


# ── configuration ──────────────────────────────────────────────────────────────
@app.command("scope")
def cmd_scope(
    agent_id: str | None = typer.Argument(None),
    sub: str | None = typer.Argument(None),
) -> None:
    """Manage session scope / project isolation key."""
    _not_ported("scope")


@app.command("profile")
def cmd_profile(
    agent_id: str | None = typer.Argument(None),
    model: str | None = typer.Argument(None),
) -> None:
    """Pin or unpin an agent's model; set a budget."""
    _not_ported("profile")


@app.command("keys")
def cmd_keys(sub: str | None = typer.Argument(None)) -> None:
    """Manage centralised API keys."""
    _not_ported("keys")


@app.command("auth")
def cmd_auth(sub: str | None = typer.Argument(None)) -> None:
    """Manage model authentication (via OpenClaw auth profiles)."""
    _not_ported("auth")


# ── models / policy ────────────────────────────────────────────────────────────
@app.command("models")
def cmd_models(sub: str | None = typer.Argument(None)) -> None:
    """View and edit the role→model policy."""
    _not_ported("models")


# ── team ───────────────────────────────────────────────────────────────────────
@app.command("team")
def cmd_team(sub: str | None = typer.Argument(None)) -> None:
    """Specialist team coordination (status/delegate/queue/done)."""
    _not_ported("team")


@app.command("workflow")
def cmd_workflow(
    agent_id: str | None = typer.Argument(None),
    sub: str | None = typer.Argument(None),
) -> None:
    """Manage Lobster YAML pipelines."""
    _not_ported("workflow")


# ── utilities ──────────────────────────────────────────────────────────────────
@app.command("logs")
def cmd_logs(agent_id: str | None = typer.Argument(None)) -> None:
    """View memory logs and gateway entries."""
    _not_ported("logs")


@app.command("edit")
def cmd_edit(agent_id: str | None = typer.Argument(None)) -> None:
    """Open workspace files in $EDITOR."""
    _not_ported("edit")


@app.command("cost")
def cmd_cost(
    agent_id: str | None = typer.Argument(None),
    json: bool = typer.Option(False, "--json"),
) -> None:
    """Token usage and cost breakdown."""
    _not_ported("cost")


@app.command("doctor")
def cmd_doctor() -> None:
    """System-wide health check with auto-fix."""
    _not_ported("doctor")


@app.command("gates")
def cmd_gates(sub: str | None = typer.Argument(None)) -> None:
    """Manage tool-approval security gates."""
    _not_ported("gates")


@app.command("audit")
def cmd_audit(sub: str | None = typer.Argument(None)) -> None:
    """Show audit log."""
    _not_ported("audit")


@app.command("eval")
def cmd_eval(sub: str | None = typer.Argument(None)) -> None:
    """Run specialist-role evaluation stubs."""
    _not_ported("eval")


@app.command("snapshot")
def cmd_snapshot(agent_id: str | None = typer.Argument(None)) -> None:
    """Export agent workspace snapshot."""
    _not_ported("snapshot")


@app.command("serve")
def cmd_serve() -> None:
    """Local HTTP endpoints: /status.json /metrics /health."""
    _not_ported("serve")


@app.command("completions")
def cmd_completions(shell: str | None = typer.Argument(None)) -> None:
    """Shell completion helpers."""
    _not_ported("completions")


# ── observability ──────────────────────────────────────────────────────────────
@app.command("trace")
def cmd_trace(sub: str | None = typer.Argument(None)) -> None:
    """View agent execution traces."""
    _not_ported("trace")


@app.command("metrics")
def cmd_metrics() -> None:
    """Show session success-rate and drift metrics."""
    _not_ported("metrics")


@app.command("policies")
def cmd_policies(sub: str | None = typer.Argument(None)) -> None:
    """Manage tool-approval policies."""
    _not_ported("policies")


@app.command("approve")
def cmd_approve(approval_id: str | None = typer.Argument(None)) -> None:
    """Approve a pending tool-action."""
    _not_ported("approve")


@app.command("deny")
def cmd_deny(approval_id: str | None = typer.Argument(None)) -> None:
    """Deny a pending tool-action."""
    _not_ported("deny")


# ── help ───────────────────────────────────────────────────────────────────────
@app.command("help")
def cmd_help(topic: str | None = typer.Argument(None)) -> None:
    """Show help."""
    _not_ported("help")


# ── hidden: data-layer bridge (T2.6) ──────────────────────────────────────────
# Used by bin/docket to replace the 136 inline python3 heredocs.
# Full implementation comes in M2/T2.6; stub here so imports resolve.
@app.command("_json", hidden=True)
def cmd_json(
    verb: str = typer.Argument(...),
    args: list[str] = typer.Argument(default=None),
) -> None:
    """Internal: JSON store bridge for Bash layer (M2/T2.6)."""
    _not_ported("_json")
