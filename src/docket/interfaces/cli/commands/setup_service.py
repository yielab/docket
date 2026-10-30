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
from docket.teams import services_openapi as _openapi

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
    target: str = typer.Argument(
        ..., help="A kind: service document (YAML or JSON), or the service name with --from-openapi"
    ),
    from_openapi: Path | None = typer.Option(
        None, "--from-openapi", help="Build the service from this local OpenAPI 3 or 2 file"
    ),
    operations: str = typer.Option(
        "", "--operations", help="operationIds to import, comma-separated"
    ),
    base_url: str = typer.Option("", "--base-url", help="Override the document's server URL"),
    auth_header: str = typer.Option("", "--auth-header", help="Header that carries the secret"),
    secret: str = typer.Option("", "--secret", help="Stored secret the header references"),
) -> None:
    """Store a service from its document, or from an OpenAPI 3 or 2 file, and show what each operation may do.

    A credential belongs in the auth value as ${secret:NAME}, with the value stored by
    docket setup secret set NAME; the document and this command never hold it. An OpenAPI
    operation that cannot be mapped is skipped and listed.
    Example: docket setup service add crm.yaml
    Example: docket setup service add crm --from-openapi crm-openapi.yaml --auth-header Authorization --secret crm"""
    if from_openapi is None and (operations or base_url or auth_header or secret):
        raise typer.BadParameter(
            "--operations, --base-url, --auth-header and --secret need --from-openapi"
        )
    built: _openapi.OpenApiImport | None = None
    try:
        if from_openapi is None:
            config = _services.load_service_document(target)
        else:
            built = _openapi.import_openapi(
                from_openapi,
                target,
                operations=[o.strip() for o in operations.split(",") if o.strip()],
                base_url=base_url,
                auth_header=auth_header,
                secret=secret,
            )
            config = built.config
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
    if built is not None:
        for line in built.notes:
            ui.dim(f"  note {line}")
        for line in built.skipped:
            ui.warn(f"skipped {line}")
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
