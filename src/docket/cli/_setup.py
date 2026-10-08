"""The setup group: the first-run report as data, doctor and completions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import typer

setup_app = typer.Typer(
    name="setup",
    help="Set up this workstation: model endpoint, notifications, sandbox, shell.",
    no_args_is_help=False,
    invoke_without_command=True,
)

_PROVIDER_COMMAND = "docket setup provider add <name>"


@dataclass(frozen=True)
class Piece:
    """One line of the first-run report: ready or not, why, and the command that fixes it."""

    name: str
    ok: bool
    reason: str
    command: str


@dataclass(frozen=True)
class Readiness:
    """The first-run report as data; ``endpoint`` is the one required piece."""

    endpoint: Piece


def readiness() -> Readiness:
    """Compute the report without printing or writing; ``init`` and ``run`` read it."""
    from docket.core import models_policy as _mp
    from docket.core import provider as _provider

    resolved: list[str] = []
    for role in ("lead", "implementer"):
        try:
            model = _mp.resolve_role_model(role)
            state = _provider.model_readiness(model)
        except Exception as exc:
            return Readiness(Piece("model endpoint", False, f"{role}: {exc}", _PROVIDER_COMMAND))
        if not state.ready:
            reason = f"{role} -> {model}: {state.issue}"
            return Readiness(Piece("model endpoint", False, reason, _PROVIDER_COMMAND))
        resolved.append(f"{role} -> {model}")
    return Readiness(Piece("model endpoint", True, ", ".join(resolved), ""))


def _resolve_version() -> str:
    """docket version — package metadata, falling back to the VERSION file."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("docket")
    except PackageNotFoundError:
        cand = Path(__file__).resolve().parents[3] / "VERSION"
        if cand.is_file():
            return cand.read_text(encoding="utf-8").strip()
    return "unknown"


def _version_callback(value: bool) -> None:
    if value:
        print(f"docket {_resolve_version()}")
        raise typer.Exit(0)


def cmd_doctor(
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable health probe"),
    fix: bool = typer.Option(False, "--fix", help="Apply auto-fixes for detected drift"),
) -> None:
    """System-wide health check and diagnostics, with an optional auto-fix
    pass.

    `--json` emits a machine-readable health probe instead of the Rich
    report; `--fix` applies auto-fixes for detected drift (permission
    repairs, missing workspace files, session-key resync) -- this mutates
    state.

    Runs (in order): required dependencies (python3); per-project agent
    workspace/registration/binding checks; model validity across every
    registered agent; the dispatch task ledger (`TASK_LIST.json` vs. the pod Lead's
    HEARTBEAT.md dispatch ledger must agree -- a mismatch prints exactly
    which task ids are missing/stale, and `--fix` re-syncs the ledger, always
    safe since TASK_LIST.json is dispatch's own source of truth); budget-cap
    sanity and runaway-session detection; key hygiene and provider coverage;
    security-gate configuration; template/runtime-contract version (reseeds
    a missing or stale WORKFLOW_AUTO.md).

    `doctor` is diagnostic-only by default; `--fix` is not read-only -- it
    mutates workspace files and permissions to correct detected drift.
    Review its findings before running with `--fix` on a workspace you
    haven't backed up."""
    from docket.cli._doctor import run_doctor

    raise typer.Exit(run_doctor(json_out=json_out, do_fix=fix))


def cmd_completions(shell: str | None = typer.Argument(None)) -> None:
    """Shell completion helpers.

    Prints a shell-completion script for bash or zsh. With no argument,
    prints usage/install instructions. Only bash and zsh are supported (no
    fish) -- an unknown shell name errors with exit 1.

    The top-level command-name list is generated live from the real Typer
    command registry, so it can never drift from `docket --help`.
    Second-level subcommand words (e.g. `gates status isolate
    classes`) are hand-maintained in the completion templates, since those
    subcommands are parsed manually rather than being Click subgroups --
    only the top-level command list is regression-tested against drift, so
    hand-maintained subcommand words for `pipeline`, `conversations`,
    `runs`, and `persona` can and have drifted out of sync with their real
    subcommands."""
    from docket.cli._completions import run_completions

    raise typer.Exit(run_completions(shell))
