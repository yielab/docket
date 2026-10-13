"""``docket setup harness``: what a program running ``docket exec --contract 1.2`` would get
from this machine's setup. Read-only and offline (ADR 0026); see
specs/api/harness-mode.spec.md "Contract 1.2" section 5."""

from __future__ import annotations

import os
from pathlib import Path

import typer

from docket import ui
from docket.cli import _contract
from docket.core import harness
from docket.core import setup_home as _setup_home
from docket.edges.adapters import system as _sys


def readiness_document(role: str) -> dict[str, object]:
    """The readiness document for *role*, read from the setup home this process would use."""
    home = _setup_home.setup_home(os.environ, Path.home() / ".docket")
    return _setup_home.readiness(
        _setup_home.load_setup(home),
        role=role,
        environ=os.environ,
        keyring=_sys.keyring_secret,
        version=harness.HARNESS_CONTRACT_V12,
    )


def cmd_harness(
    json_out: bool = typer.Option(False, "--json", help="Emit the readiness document as JSON"),
    role: str = typer.Option("implementer", "--role", help="Role a run would use"),
) -> None:
    """Show what docket exec --contract 1.2 can use from this machine's setup.

    Reads the setup home (DOCKET_SETUP_HOME, default ~/.docket) and never writes it,
    calls no network and prints no credential value. Exit 0 when a run with no
    --model would resolve a model, an endpoint and a credential, 1 otherwise.

    Example: docket setup harness --json"""
    doc = readiness_document(role)
    if json_out:
        _contract.emit_json(doc)
        raise typer.Exit(0 if doc["ready"] else 1)
    ui.header("Harness setup")
    ui.dim(f"Setup home: {doc['setup_home']}")
    if doc["ready"]:
        ui.success(f"Ready: {role} -> {doc['default_model']}")
    else:
        ui.warn(f"Not ready: {doc['reason']}")
    providers = doc["providers"]
    assert isinstance(providers, list)
    rows = []
    for entry in providers:
        cred = entry["credential"]
        state = (
            "not needed"
            if not cred["needed"]
            else (cred["source"] if cred["resolves"] else "missing")
        )
        rows.append([entry["name"], entry["scope"], cred["name"] or "-", state])
    ui.table(rows, ["PROVIDER", "SCOPE", "CREDENTIAL", "SOURCE"])
    models = doc["models"]
    assert isinstance(models, list)
    ui.dim(f"{len(models)} model(s) reachable without a network call; --json lists them")
    raise typer.Exit(0 if doc["ready"] else 1)
