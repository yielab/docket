"""The sandbox setup commands.
Holds gates."""

from __future__ import annotations

import typer

from docket import ui


def cmd_gates(ctx: typer.Context) -> None:
    """Show docket's tool-call gate and manage workspace isolation.

    The tool-call gate itself -- the policy engine plus the argument-aware
    high-risk command classifier, both evaluated in `core/tools.py`'s
    `dispatch_tool` chokepoint on every call docket's turn loop makes -- is
    always active and cannot be turned off. An "ask" verdict sits in
    docket's own approval store, answerable identically by the CLI, HTTP,
    MCP, and Telegram channels.

    Subcommands:
      status (default)  reports that the tool-call gate is always active,
                          plus the workspace-isolation mode
      isolate on|off    records whether tool execution runs inside a
                          sandbox (opt-in, off by default). `on` needs
                          bubblewrap (Linux) or a running docker; it probes
                          bwrap, then docker -- errors, exit 1, if neither is
                          usable. Enforced on the live
                          turn: with isolation on, DocketDriver runs tools
                          sandboxed (bwrap or docker), and refuses the whole
                          turn -- audited as `isolation.refused` -- when no
                          backend is usable, rather than running it
                          unsandboxed.
      network none|open records whether jailed tool calls may reach the
                          network (default open). `none` drops bwrap's
                          --share-net / adds docker's --network none, and
                          refuses any turn that would run with isolation
                          off -- audited as `network.refused`. A pod's
                          `network` setting can only narrow it. `fetch`
                          is untouched (its domain allowlist stays).
      classes           lists the built-in high-risk action classes
                          (`HIGH_RISK_PATTERNS` in `core/security.py`) --
                          money-movement, prod-deploy, and secret-access --
                          wired onto every bash call docket's turn loop
                          dispatches: the whole command line, including
                          every segment behind a `;`/`&&`/`||`/pipe, is
                          classified before a call is allowed to run, so
                          `git push origin production` asks even though
                          `git` itself stays on the curated allowlist
                          (`git status` does not). A pod's verifyCmd
                          separately refuses a matching command outright
                          before the shell starts; a hop's real output is
                          scanned for a match on the way through the
                          pipeline (flagged, not blocked, by itself).
                          Read-only; the pattern list is not yet
                          user-configurable.

    Any other subcommand prints usage and exits 2. Approvals are answerable
    headlessly via `docket approve`/`docket deny` or `POST
    /approvals/<token>` (`docket serve`), or MCP, in addition to Telegram --
    all four channels are audit-logged. See
    specs/functional/security-gates.spec.md."""
    from docket.cli._flags import find_unknown_flag
    from docket.cli._gates import run_gates

    args = list(ctx.args)
    sub = args[0] if args else None
    rest = args[1:]
    bad = find_unknown_flag(rest, frozenset())
    if bad is not None:
        ui.error(f"docket gates: unrecognized flag '{bad}'")
        raise typer.Exit(2)
    want = rest[0] if rest else None
    raise typer.Exit(run_gates(sub, want=want))
