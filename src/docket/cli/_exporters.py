"""docket exporters -- list, inspect and turn on an observability export destination.

`core/exporter.py` owns the `kind: exporter` document, the merged catalog and pure
classification (`activation_state`, `verify_endpoint`); this module renders those results,
prompts for a missing credential (`cli/_keys.py::prompt_and_store`), and dispatches the wire
probe by dialect -- the same split `cli/_provider.py` keeps from `core/provider.py`.
"""

from __future__ import annotations

import base64
import json as _json
import sys
from pathlib import Path
from typing import Any

from docket import ui
from docket.cli import _keys
from docket.core import exporter as _exp
from docket.core.audit import audit_log
from docket.edges.adapters.exporters import otlp_http as _otlp_http


def run_exporters(action: str, args: list[str]) -> int:
    """Dispatch one `docket exporters <action> ...` call. Returns a process exit code."""
    handlers = {
        "list": _run_list,
        "show": _run_show,
        "enable": _run_enable,
        "disable": _run_disable,
        "test": _run_test,
        "add": _run_add,
        "remove": _run_remove,
        "export": _run_export,
    }
    handler = handlers.get(action)
    if handler is None:
        ui.error(
            f"Unknown exporters action '{action}'.\n"
            "Usage:\n"
            "  docket exporters list [--json]\n"
            "  docket exporters show <name> [--json]\n"
            "  docket exporters enable <name> [--endpoint URL]"
            " [--payload metadata|full] [--events ...] [--no-verify]\n"
            "  docket exporters disable <name>\n"
            "  docket exporters test <name>\n"
            "  docket exporters add <file.yaml>\n"
            "  docket exporters remove <name>\n"
            "  docket exporters export <name> [<file>]"
        )
        return 1
    return handler(args)


def _parse_opts(args: list[str]) -> tuple[list[str], dict[str, str]]:
    """Split *args* into positionals and `--key value`/`--key=value` options -- the same
    hand-parsed shape `cli/_provider.py::_parse_opts` uses."""
    pos: list[str] = []
    opts: dict[str, str] = {}
    i = 0
    while i < len(args):
        tok = args[i]
        if tok.startswith("--"):
            key = tok[2:]
            if "=" in key:
                k, v = key.split("=", 1)
                opts[k] = v
            else:
                opts[key] = args[i + 1] if i + 1 < len(args) else ""
                i += 1
        else:
            pos.append(tok)
        i += 1
    return pos, opts


def _auth_header_for(spec: _exp.ExporterSpec, values: list[str]) -> tuple[str, str] | None:
    """Translate *spec*'s auth type into the one header a wire adapter's ``probe``/``emit``
    takes. ``basic`` is base64(first credential : second credential) on ``Authorization``; the
    other named types carry the single resolved value verbatim."""
    if spec.auth.type == "none" or not values or not any(values):
        return None
    if spec.auth.type == "bearer":
        return ("Authorization", f"Bearer {values[0]}")
    if spec.auth.type == "header":
        return (spec.auth.header, values[0])
    if spec.auth.type == "basic":
        user = values[0] if len(values) > 0 else ""
        password = values[1] if len(values) > 1 else ""
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        return ("Authorization", f"Basic {token}")
    return None


def _probe_for(spec: _exp.ExporterSpec) -> _exp.ProbeResult:
    """Dispatch *spec*'s dialect to its wire adapter's ``probe``. The dispatch stays local to
    this module rather than living in ``edges/adapters/exporters/__init__.py``, which may not
    yet expose a dialect-keyed sink lookup on every base this lands against."""
    values, _source = _exp.resolve_credentials(spec)
    auth_header = _auth_header_for(spec, values)
    if spec.dialect == "otlp-http":
        raw = _otlp_http.probe(spec.endpoint, auth_header, spec.headers)
        return _exp.ProbeResult(status=raw.status, error=raw.error)
    return _exp.ProbeResult(status=None, error=f"no probe for dialect '{spec.dialect}'")


def _run_list(args: list[str]) -> int:
    _pos, opts = _parse_opts(args)
    catalog = _exp.load_catalog()
    health = _exp.read_health()

    if "json" in opts:
        rows = []
        for name in sorted(catalog.entries):
            spec = catalog.entries[name]
            state, _missing = _exp.activation_state(spec, health.get(name))
            rows.append(
                {
                    "name": name,
                    "dialect": spec.dialect,
                    "state": state,
                    "credentials": list(spec.auth.credentials),
                    "scope": catalog.source_of(name),
                }
            )
        ui.console.print(_json.dumps(rows, indent=2))
        return 0

    if not catalog.entries:
        ui.console.print("No exporters registered.")
        return 0

    ui.header("Exporters")
    ui.console.print()
    fmt = "  {:<14}  {:<11}  {:<16}  {:<28}  {}"
    ui.console.print(
        f"[bold]{fmt.format('NAME', 'DIALECT', 'STATE', 'CREDENTIALS', 'SCOPE')}[/bold]"
    )
    for name in sorted(catalog.entries):
        spec = catalog.entries[name]
        state, _missing = _exp.activation_state(spec, health.get(name))
        credentials = ", ".join(spec.auth.credentials) or "-"
        ui.console.print(
            fmt.format(name, spec.dialect, state, credentials, catalog.source_of(name))
        )
    return 0


def _run_show(args: list[str]) -> int:
    pos, opts = _parse_opts(args)
    if not pos:
        ui.error("Usage: docket exporters show <name> [--json]")
        return 1

    name = pos[0]
    catalog = _exp.load_catalog()
    spec = catalog.get(name)
    if spec is None:
        ui.error(f"Unknown exporter '{name}'.")
        return 1
    scope = catalog.source_of(name)
    health = _exp.read_health().get(name, {})
    state, missing = _exp.activation_state(spec, health)

    if "json" in opts:
        payload = {
            "scope": scope,
            "state": state,
            "missingCredentials": missing,
            "health": health,
            **spec.model_dump(by_alias=True),
        }
        ui.console.print(_json.dumps(payload, indent=2))
        return 0

    ui.header(f"Exporter: {name} ({scope})")
    ui.console.print()
    ui.console.print(f"  dialect       {spec.dialect}")
    ui.console.print(f"  endpoint      {spec.endpoint}")
    ui.console.print(
        f"  auth          {spec.auth.type}"
        + (f" ({', '.join(spec.auth.credentials)})" if spec.auth.credentials else "")
    )
    ui.console.print(f"  enabled       {spec.enabled}")
    ui.console.print(f"  state         {state}")
    if spec.aliases:
        aliases = ", ".join(f"{k} -> {v}" for k, v in spec.aliases.items())
        ui.console.print(f"  aliases       {aliases}")
    ui.console.print(f"  payload       {spec.payload}")
    if health:
        ui.console.print(
            f"  health        exported={health.get('exported', 0)}"
            f" dropped={health.get('dropped', 0)} failed={health.get('failed', 0)}"
        )
    return 0


def _run_enable(args: list[str]) -> int:
    no_verify = "--no-verify" in args
    args = [a for a in args if a != "--no-verify"]
    pos, opts = _parse_opts(args)
    if not pos:
        ui.error(
            "Usage: docket exporters enable <name> [--endpoint URL]"
            " [--payload metadata|full] [--events ...] [--no-verify]"
        )
        return 1
    name = pos[0]

    catalog = _exp.load_catalog()
    spec = catalog.get(name)
    if spec is None:
        ui.error(f"Unknown exporter '{name}'.")
        return 1

    values, _source = _exp.resolve_credentials(spec)
    missing = [cred for cred, val in zip(spec.auth.credentials, values, strict=True) if not val]
    if missing:
        if sys.stdin.isatty():
            for cred in missing:
                if not _keys.prompt_and_store(cred):
                    ui.error(f"'{cred}' was not stored. Exporter '{name}' was not enabled.")
                    return 1
        else:
            ui.error(f"Exporter '{name}' needs credentials that are not set:")
            for cred in missing:
                ui.console.print(f"  docket keys add {cred}")
            return 1

    overrides: dict[str, Any] = {}
    if "endpoint" in opts:
        overrides["endpoint"] = opts["endpoint"]
    if "payload" in opts:
        if opts["payload"] not in ("metadata", "full"):
            ui.error(f"--payload must be 'metadata' or 'full', got '{opts['payload']}'")
            return 1
        overrides["payload"] = opts["payload"]
    if "events" in opts:
        overrides["events"] = [e.strip() for e in opts["events"].split(",") if e.strip()]

    effective = spec.model_copy(update=overrides) if overrides else spec

    if not no_verify:
        result = _probe_for(effective)
        verification = _exp.verify_endpoint(effective, result)
        if not verification.reachable:
            ui.error(
                f"Could not reach {effective.endpoint}"
                + (f": {verification.warning}" if verification.warning else "")
                + f". Exporter '{name}' was not enabled."
            )
            return 1
        if verification.warning:
            ui.warn(verification.warning)

    enabled_spec = _exp.enable_exporter(name, overrides)
    ui.success(f"Exporter enabled: {name}  ->  {enabled_spec.endpoint}")
    ui.console.print(f"  scope: global  payload: {enabled_spec.payload}")
    if enabled_spec.payload == "full":
        ui.warn("tool arguments and results leave this host")
    return 0


def _run_disable(args: list[str]) -> int:
    pos, _opts = _parse_opts(args)
    if not pos:
        ui.error("Usage: docket exporters disable <name>")
        return 1
    name = pos[0]
    try:
        _exp.disable_exporter(name)
    except _exp.ExporterError as exc:
        ui.error(str(exc))
        return 1
    ui.success(f"Exporter disabled: {name}")
    return 0


def _run_test(args: list[str]) -> int:
    pos, _opts = _parse_opts(args)
    if not pos:
        ui.error("Usage: docket exporters test <name>")
        return 1
    name = pos[0]
    catalog = _exp.load_catalog()
    spec = catalog.get(name)
    if spec is None:
        ui.error(f"Unknown exporter '{name}'.")
        return 1

    result = _probe_for(spec)
    verification = _exp.verify_endpoint(spec, result)
    if not verification.reachable:
        ui.error(
            f"Could not reach {spec.endpoint}"
            + (f": {verification.warning}" if verification.warning else "")
        )
        return 1
    if verification.warning:
        ui.warn(verification.warning)
        return 1
    ui.success(f"{spec.endpoint} reachable (HTTP {verification.status})")
    return 0


def _run_add(args: list[str]) -> int:
    no_verify = "--no-verify" in args
    args = [a for a in args if a != "--no-verify"]
    pos, _opts = _parse_opts(args)
    if not pos:
        ui.error("Usage: docket exporters add <file.yaml>")
        return 1

    try:
        spec = _exp.load_exporter_document(pos[0])
    except _exp.ExporterError as exc:
        ui.error(str(exc))
        return 1

    if not no_verify:
        result = _probe_for(spec)
        verification = _exp.verify_endpoint(spec, result)
        if not verification.reachable:
            ui.error(
                f"Could not reach {spec.endpoint}"
                + (f": {verification.warning}" if verification.warning else "")
                + ". Exporter was not added."
            )
            return 1
        if verification.warning:
            ui.warn(verification.warning)

    _exp.save_exporter(spec)
    audit_log("exporter.added", f"name={spec.name} payload={spec.payload} endpoint={spec.endpoint}")
    ui.success(f"Exporter added: {spec.name}  ->  {spec.endpoint}")
    return 0


def _run_remove(args: list[str]) -> int:
    pos, _opts = _parse_opts(args)
    if not pos:
        ui.error("Usage: docket exporters remove <name>")
        return 1
    name = pos[0]
    try:
        _exp.delete_exporter(name)
    except _exp.ExporterError as exc:
        ui.error(str(exc))
        return 1
    audit_log("exporter.removed", f"name={name}")
    ui.success(f"Removed exporter '{name}'.")
    return 0


def _run_export(args: list[str]) -> int:
    pos, _opts = _parse_opts(args)
    if not pos:
        ui.error("Usage: docket exporters export <name> [<file>]")
        return 1
    try:
        text = _exp.export_exporter(pos[0])
    except _exp.ExporterError as exc:
        ui.error(str(exc))
        return 1
    if len(pos) > 1:
        Path(pos[1]).write_text(text, encoding="utf-8")
        ui.success(f"Exported '{pos[0]}' to {pos[1]}")
    else:
        ui.console.print(text, end="")
    return 0
