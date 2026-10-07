"""The service commands.
Holds serve."""

from __future__ import annotations

import typer


def cmd_serve(
    port: int = typer.Option(7331, "--port", "-p", help="Port to bind (default 7331)"),
    interval: int = typer.Option(
        30, "--interval", "-i", help="Sweep refresh interval in seconds (default 30)"
    ),
    dispatch: bool = typer.Option(
        False,
        "--dispatch",
        help="Also drive each pod's queued tasks through its pipeline (real, costed agent turns)",
    ),
    telegram: bool = typer.Option(
        False,
        "--telegram",
        help=(
            "Long-poll docket's own Telegram bot for /approve /deny /status /delegate "
            "(needs: docket keys add TELEGRAM_BOT_TOKEN)"
        ),
    ),
    token_file: str | None = typer.Option(
        None,
        "--token-file",
        help=(
            "Write the /approvals + /dispatch bearer token to this file (0600) instead of "
            "printing it to stdout"
        ),
    ),
) -> None:
    """Local HTTP endpoints: /status.json /metrics /health.

    Binds to 127.0.0.1 (loopback-only) -- not reachable off this host. With
    --dispatch, each refresh also runs every pod's queue through the
    Lead->Implementer->Reviewer->Tester pipeline. Each hop is a real agent
    turn and is budget-gated; leave it off for a read-only monitor. With
    --telegram, also polls docket's own Telegram bot so a chat bound via
    `docket wire` can /approve, /deny, /status, /delegate or /answer -- idle until a
    bot token is stored.

    `-p`/`--port <N>` (default 7331) binds a port -- 127.0.0.1 only, never
    reachable off the host. `-i`/`--interval <seconds>` (default 30) sets
    the sweep refresh interval. `--token-file <path>` writes the bearer
    token needed for /approvals, /dispatch, and /runs to a 0600 file instead
    of printing it to stdout.

    HTTP endpoints while running: GET /status.json, /metrics, /health (no
    auth); GET /approvals, POST /approvals/<token>
    {"action": "grant"|"deny"}, GET /runs and /runs?project=<p>, GET
    /runs/<id>, GET /tasks/<project>, GET /traces/<project>?since=<cursor>,
    POST /tasks/<project>, POST /dispatch/<project>, POST /pods (all
    Bearer-token-authed). The
    bearer token is generated fresh per invocation (printed to stdout,
    written to --token-file if given, or overridable via
    DOCKET_SERVE_TOKEN) and compared with secrets.compare_digest. POST
    /dispatch/<project> returns {"run": "<id>"} immediately and runs the
    pipeline in the background -- poll GET /runs/<id> (or
    `docket runs show <id>`) for the outcome.

    Plain `docket serve` never dispatches and never polls Telegram; both are
    opt-in. Read-only by default, so it's safe to leave running for
    monitoring. --dispatch spends real budget; over-budget tasks are left
    blocked, not run. Per-task dispatch is traced (`docket trace`) for
    auditability."""
    from docket.serve import run_serve

    run_serve(
        port=port, interval=interval, dispatch=dispatch, telegram=telegram, token_file=token_file
    )
