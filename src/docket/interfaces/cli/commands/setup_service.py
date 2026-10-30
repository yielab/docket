"""The ``setup service`` group: external HTTP services a pod may reach, declared by a document."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import typer

from docket.governance import secrets as _secrets
from docket.governance.audit import audit_log
from docket.interfaces.cli.commands import contract as _contract
from docket.interfaces.cli.render import ui
from docket.kernel import service as _service
from docket.kernel.errors import InvalidInput
from docket.kernel.home import current_home
from docket.teams import services as _services

service_app = typer.Typer(
    name="service",
    help="External HTTP services: add a declared document, list and remove them.",
    no_args_is_help=True,
)


def _secrets_of(config: _service.ServiceConfig) -> list[str]:
    return _service.secret_names(config.auth.value) if config.auth else []


@service_app.command("list")
def cmd_list(json_out: bool = typer.Option(False, "--json", help="Emit JSON")) -> None:
    """List the stored services; an auth value is never shown, only its header and secret names.

    Example: docket setup service list"""
    services = _services.load_services()
    if json_out:
        _contract.emit_json(
            [
                {
                    "name": s.name,
                    "baseUrl": s.baseUrl,
                    "hosts": s.hosts,
                    "operations": len(s.operations),
                    "auth": {"header": s.auth.header, "secrets": _secrets_of(s)}
                    if s.auth
                    else None,
                }
                for s in services
            ]
        )
        return
    if not services:
        ui.info("No services configured.")
        return
    ui.header("Services")
    ui.table(
        [
            [
                s.name,
                s.baseUrl,
                str(len(s.operations)),
                f"{s.auth.header} ({', '.join(_secrets_of(s)) or 'literal'})" if s.auth else "-",
            ]
            for s in services
        ],
        ["NAME", "BASE URL", "OPERATIONS", "AUTH"],
    )
    ui.dim(f"  Config file: {current_home().services_file}")


@service_app.command("add")
def cmd_add(
    file: Path = typer.Argument(..., help="A kind: service document (YAML or JSON)"),
) -> None:
    """Store a service from its document and show what each operation may do.

    A credential belongs in the auth value as ${secret:NAME}, with the value stored by
    docket setup secret set NAME; the document and this command never hold it.
    Example: docket setup service add crm.yaml"""
    try:
        config = _services.load_service_document(file)
        _services.add_service(config)
    except InvalidInput as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    host = urlsplit(config.baseUrl).hostname or ""
    audit_log(
        "services.add", f"name={config.name!r} host={host!r} operations={len(config.operations)}"
    )
    stored = _secrets.secrets_keys()
    for name in _secrets_of(config):
        if name not in stored:
            ui.warn(
                f"{config.auth.header if config.auth else 'auth'}: no secret named '{name}' is stored yet"
            )
    ui.success(f"Service '{config.name}' added ({config.baseUrl}).")
    if config.operations:
        ui.table(
            [[op.name, op.method, op.path, str(op.access)] for op in config.operations],
            ["OPERATION", "METHOD", "PATH", "ACCESS"],
        )
    _contract.next_step("docket setup service list")


@service_app.command("remove")
def cmd_remove(name: str = typer.Argument(..., help="Service name")) -> None:
    """Remove a stored service.

    Example: docket setup service remove crm"""
    if not _services.remove_service(name):
        ui.error(f"No service named '{name}' is configured", "Run: docket setup service list")
        raise typer.Exit(1)
    audit_log("services.remove", f"name={name!r}")
    ui.success(f"Service '{name}' removed.")
    _contract.next_step("docket setup service list")
