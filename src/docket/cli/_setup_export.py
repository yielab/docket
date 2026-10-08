"""The ``setup export`` group: observability export destinations and what they may see."""

from __future__ import annotations

import base64
import getpass as _getpass
import json as _json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import typer
from rich.markup import escape

import docket.config as _cfg
from docket import ui
from docket.cli import _contract
from docket.cli._setup_notify import NotifySetupError, store_secret
from docket.core import exporter as _exp
from docket.core import privacy as _privacy
from docket.core import telemetry as _telemetry
from docket.core import trace as _trace
from docket.core.audit import audit_log
from docket.edges.adapters.exporters import otlp_http as _otlp_http

export_app = typer.Typer(
    name="export",
    help="Observability export: destinations, credentials, privacy and a preview.",
    no_args_is_help=True,
)

_DISPLAY_MAX_CHARS = 200
_PER_PART_ATTR = "gen_ai.input.messages"
_CONTENT_KEYS = ("inputMessages", "outputMessages", "systemInstructions")


def _spec_or_exit(name: str) -> _exp.ExporterSpec:
    spec = _exp.load_catalog().get(name)
    if spec is None:
        ui.error(f"Unknown exporter '{name}'", "Run: docket setup export list")
        raise typer.Exit(1)
    return spec


def _split(raw: str | None) -> list[str] | None:
    return [s.strip() for s in raw.split(",") if s.strip()] if raw else None


def _auth_header_for(spec: _exp.ExporterSpec, values: list[str]) -> tuple[str, str] | None:
    """Translate the auth type into the one header a wire adapter's probe takes."""
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
    values, _source = _exp.resolve_credentials(spec)
    if spec.dialect == "otlp-http":
        raw = _otlp_http.probe(spec.endpoint, _auth_header_for(spec, values), spec.headers)
        return _exp.ProbeResult(status=raw.status, error=raw.error)
    return _exp.ProbeResult(status=None, error=f"no probe for dialect '{spec.dialect}'")


def _host_of(endpoint: str) -> str:
    return urlsplit(endpoint).hostname or endpoint


def _shares_display(classes: frozenset[str]) -> str:
    return ", ".join(sorted(classes)) if classes else "structure only"


def _render_leaves_this_host(spec: _exp.ExporterSpec) -> None:
    ui.console.print("  Leaves this host:", markup=False)
    for cls, granted, attrs in _privacy.describe(spec.privacy_classes):
        mark = "yes" if granted else "no "
        ui.console.print(f"    {mark} {cls}  ({', '.join(attrs)})", markup=False)
    ui.console.print("    never: credentials, secret-shaped values (redacted)", markup=False)


def _confirm_widening(
    name: str,
    endpoint: str,
    old_label: str,
    new_label: str,
    old_classes: frozenset[str],
    new_classes: frozenset[str],
    yes: bool,
) -> bool:
    """A widening privacy change names what is newly granted and where it goes, then asks."""
    ui.warn(f"'{name}' will widen from '{old_label}' to '{new_label}':")
    for cls, granted, attrs in _privacy.describe(new_classes):
        if granted and cls in new_classes - old_classes:
            ui.console.print(f"    + {cls}  (e.g. {attrs[0] if attrs else ''})", markup=False)
    ui.console.print(f"  destination: {_host_of(endpoint)}", markup=False)
    return _contract.confirm(f"Widen '{name}'", yes=yes)


def _verify(spec: _exp.ExporterSpec, refusal: str) -> None:
    """Probe the endpoint; an unreachable one refuses with ``refusal`` appended."""
    verification = _exp.verify_endpoint(spec, _probe_for(spec))
    if not verification.reachable:
        why = f": {verification.warning}" if verification.warning else ""
        ui.error(f"Could not reach {spec.endpoint}{why}", refusal)
        raise typer.Exit(1)
    if verification.warning:
        ui.warn(verification.warning)


@export_app.command("list")
def cmd_list(json_out: bool = typer.Option(False, "--json", help="Emit JSON")) -> None:
    """List every export destination with its state and privacy level.

    Example: docket setup export list"""
    catalog = _exp.load_catalog()
    health = _exp.read_health()
    names = sorted(catalog.entries)
    if json_out:
        rows = [
            {
                "name": n,
                "dialect": catalog.entries[n].dialect,
                "state": _exp.activation_state(catalog.entries[n], health.get(n))[0],
                "credentials": list(catalog.entries[n].auth.credentials),
                "scope": catalog.source_of(n),
            }
            for n in names
        ]
        _contract.emit_json(rows)
        return
    if not names:
        ui.info("No exporters registered.")
        return
    ui.header("Exporters")
    ui.table(
        [
            [
                n,
                catalog.entries[n].dialect,
                _exp.activation_state(catalog.entries[n], health.get(n))[0],
                ", ".join(catalog.entries[n].auth.credentials) or "-",
                catalog.source_of(n),
                catalog.entries[n].privacy_label,
            ]
            for n in names
        ],
        ["NAME", "DIALECT", "STATE", "CREDENTIALS", "SCOPE", "SHARES"],
    )


@export_app.command("show")
def cmd_show(
    name: str = typer.Argument(..., help="Exporter name"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Show one exporter: document, state, health and what leaves this host.

    Example: docket setup export show langfuse"""
    spec = _spec_or_exit(name)
    scope = _exp.load_catalog().source_of(name)
    health = _exp.read_health().get(name, {})
    state, missing = _exp.activation_state(spec, health)
    if json_out:
        _contract.emit_json(
            {
                "scope": scope,
                "state": state,
                "missingCredentials": missing,
                "health": health,
                **spec.model_dump(by_alias=True),
            }
        )
        return
    ui.header("Exporter", f"{name} ({scope})")
    auth = spec.auth.type + (
        f" ({', '.join(spec.auth.credentials)})" if spec.auth.credentials else ""
    )
    rows = [
        ["dialect", spec.dialect],
        ["endpoint", spec.endpoint],
        ["auth", auth],
        ["enabled", str(spec.enabled)],
        ["state", state],
    ]
    if spec.aliases:
        rows.append(["aliases", ", ".join(f"{k} -> {v}" for k, v in spec.aliases.items())])
    rows.append(["privacy", spec.privacy_label])
    if health:
        rows.append(
            [
                "health",
                f"exported={health.get('exported', 0)} dropped={health.get('dropped', 0)}"
                f" failed={health.get('failed', 0)}",
            ]
        )
    ui.table(rows, ["FIELD", "VALUE"])
    _render_leaves_this_host(spec)


@export_app.command("enable")
def cmd_enable(
    name: str = typer.Argument(..., help="Exporter name"),
    endpoint: str | None = typer.Option(None, "--endpoint", help="Override the endpoint URL"),
    privacy: str | None = typer.Option(None, "--privacy", help="Privacy level"),
    share: str | None = typer.Option(None, "--share", help="Content classes, comma separated"),
    events: str | None = typer.Option(None, "--events", help="Event list, comma separated"),
    no_verify: bool = typer.Option(False, "--no-verify", help="Skip the reachability probe"),
    yes: bool = typer.Option(False, "--yes", help="Confirm a widening change"),
) -> None:
    """Enable an exporter: collect missing credentials, probe the endpoint, then write.

    Example: docket setup export enable langfuse --privacy actions"""
    spec = _spec_or_exit(name)
    values, _source = _exp.resolve_credentials(spec)
    missing = [c for c, v in zip(spec.auth.credentials, values, strict=True) if not v]
    if missing and not _contract._is_tty():
        ui.error(f"Exporter '{name}' needs credentials that are not set: {', '.join(missing)}")
        for cred in missing:
            ui.console.print(f"  export {cred}=<value>", markup=False)
        raise typer.Exit(1)
    for cred in missing:
        value = _getpass.getpass(f"Enter value for {cred} (hidden): ").strip()
        if not value:
            ui.error(f"'{cred}' was not stored", f"Exporter '{name}' was not enabled")
            raise typer.Exit(1)
        try:
            store_secret(cred, value)
        except NotifySetupError as exc:
            ui.error(str(exc))
            raise typer.Exit(1) from exc

    overrides: dict[str, Any] = {}
    if endpoint is not None:
        overrides["endpoint"] = endpoint
    if privacy is not None and share is not None:
        ui.error("--privacy and --share are mutually exclusive")
        raise typer.Exit(1)
    shares = _split(share)
    if privacy is not None or shares is not None:
        try:
            new_label, new_classes = _privacy.resolve(privacy, shares)
        except ValueError as exc:
            ui.error(str(exc))
            raise typer.Exit(1) from exc
        overrides["privacy" if privacy is not None else "share"] = (
            privacy if privacy is not None else shares
        )
        if _exp.is_widening(spec.privacy_classes, new_classes) and not _confirm_widening(
            name,
            spec.endpoint,
            spec.privacy_label,
            new_label,
            spec.privacy_classes,
            new_classes,
            yes,
        ):
            raise typer.Exit(1)
    if events is not None:
        overrides["events"] = _split(events) or []
    effective = spec.model_copy(update=overrides) if overrides else spec
    if not no_verify:
        _verify(effective, f"Exporter '{name}' was not enabled")
    enabled = _exp.enable_exporter(name, overrides)
    ui.success(f"Exporter enabled: {name} -> {enabled.endpoint}")
    ui.dim(f"  shares: {enabled.privacy_label} ({_shares_display(enabled.privacy_classes)})")
    _contract.next_step(f"docket setup export preview {name}")


@export_app.command("disable")
def cmd_disable(name: str = typer.Argument(..., help="Exporter name")) -> None:
    """Turn an exporter off; stored keys are kept.

    Example: docket setup export disable langfuse"""
    try:
        _exp.disable_exporter(name)
    except _exp.ExporterError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    ui.success(f"Exporter disabled: {name}")
    _contract.next_step("docket setup export list")


@export_app.command("test")
def cmd_test(name: str = typer.Argument(..., help="Exporter name")) -> None:
    """Probe an exporter's endpoint without changing anything.

    Example: docket setup export test langfuse"""
    spec = _spec_or_exit(name)
    verification = _exp.verify_endpoint(spec, _probe_for(spec))
    if not verification.reachable:
        why = f": {verification.warning}" if verification.warning else ""
        ui.error(f"Could not reach {spec.endpoint}{why}")
        raise typer.Exit(1)
    if verification.warning:
        ui.warn(verification.warning)
        raise typer.Exit(1)
    ui.success(f"{spec.endpoint} reachable (HTTP {verification.status})")


@export_app.command("add")
def cmd_add(
    file: Path = typer.Argument(..., help="A kind: exporter YAML document"),
    no_verify: bool = typer.Option(False, "--no-verify", help="Skip the reachability probe"),
    yes: bool = typer.Option(False, "--yes", help="Confirm a widening change"),
) -> None:
    """Add an exporter from a document.

    Example: docket setup export add ./my-exporter.yaml"""
    try:
        spec = _exp.load_exporter_document(file)
    except _exp.ExporterError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    existing = _exp.load_catalog().get(spec.name)
    old_label = existing.privacy_label if existing else "minimal"
    old_classes = existing.privacy_classes if existing else frozenset()
    if _exp.is_widening(old_classes, spec.privacy_classes) and not _confirm_widening(
        spec.name,
        spec.endpoint,
        old_label,
        spec.privacy_label,
        old_classes,
        spec.privacy_classes,
        yes,
    ):
        raise typer.Exit(1)
    if not no_verify:
        _verify(spec, "Exporter was not added")
    _exp.save_exporter(spec)
    audit_log(
        "exporter.added", f"name={spec.name} privacy={spec.privacy_label} endpoint={spec.endpoint}"
    )
    ui.success(f"Exporter added: {spec.name} -> {spec.endpoint}")
    _contract.next_step(f"docket setup export enable {spec.name}")


@export_app.command("remove")
def cmd_remove(
    name: str = typer.Argument(..., help="Exporter name"),
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation"),
) -> None:
    """Remove an exporter document.

    Example: docket setup export remove my-exporter --yes"""
    if _exp.load_catalog().source_of(name) == "built-in":
        ui.error(f"'{name}' is a built-in exporter with no global override", "Nothing to remove")
        raise typer.Exit(1)
    if not _contract.confirm(f"Remove exporter '{name}'", yes=yes):
        ui.warn("Aborted.")
        raise typer.Exit(1)
    try:
        _exp.delete_exporter(name)
    except _exp.ExporterError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    audit_log("exporter.removed", f"name={name}")
    ui.success(f"Removed exporter '{name}'.")
    _contract.next_step("docket setup export list")


@export_app.command("export")
def cmd_export(
    name: str = typer.Argument(..., help="Exporter name"),
    file: Path | None = typer.Argument(None, help="Write here instead of stdout"),
) -> None:
    """Print or write one exporter document.

    Example: docket setup export export langfuse ./langfuse.yaml"""
    try:
        text = _exp.export_exporter(name)
    except _exp.ExporterError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    if file is None:
        typer.echo(text, nl=False)
        return
    file.write_text(text, encoding="utf-8")
    ui.success(f"Exported '{name}' to {file}")


@export_app.command("privacy")
def cmd_privacy(
    name: str = typer.Argument(..., help="Exporter name"),
    level: str | None = typer.Argument(None, help="minimal, actions, conversation or full"),
    share: str | None = typer.Option(None, "--share", help="Content classes, comma separated"),
    max_chars: int | None = typer.Option(None, "--max-chars", help="Per-field character cap"),
    yes: bool = typer.Option(False, "--yes", help="Confirm a widening change"),
) -> None:
    """Show or change what an exporter shares; widening asks, narrowing never does.

    Example: docket setup export privacy langfuse conversation --yes"""
    spec = _spec_or_exit(name)
    if level is not None and share is not None:
        ui.error("A level argument and --share are mutually exclusive")
        raise typer.Exit(1)
    shares = _split(share)
    if level is None and shares is None and max_chars is None:
        ui.header("Exporter", name)
        _render_leaves_this_host(spec)
        return
    new_label, new_classes = spec.privacy_label, spec.privacy_classes
    if level is not None or shares is not None:
        try:
            new_label, new_classes = _privacy.resolve(level, shares)
        except ValueError as exc:
            ui.error(str(exc))
            raise typer.Exit(1) from exc
    if _exp.is_widening(spec.privacy_classes, new_classes) and not _confirm_widening(
        name, spec.endpoint, spec.privacy_label, new_label, spec.privacy_classes, new_classes, yes
    ):
        raise typer.Exit(1)
    try:
        updated = _exp.set_privacy(name, privacy=level, share=shares, content_max_chars=max_chars)
    except _exp.ExporterError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    ui.success(f"Exporter privacy updated: {name}")
    ui.dim(f"  shares: {updated.privacy_label} ({_shares_display(updated.privacy_classes)})")
    _contract.next_step(f"docket setup export preview {name}")


def _newest_trace_file() -> Path | None:
    """The most-recently-modified `*.jsonl` under `TRACES_DIR`, across every project."""
    files = list(_cfg.TRACES_DIR.glob("*/*.jsonl"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _events_for(spec: _exp.ExporterSpec) -> frozenset[str] | None:
    """Mirrors `core.telemetry.start`'s own inline resolution -- nothing is factored out of
    `start` itself, this call site just reads the same three fields it reads."""
    if spec.events == "all":
        return None
    if spec.events == "default":
        return _telemetry.DEFAULT_EVENTS
    return frozenset(spec.events)


def _attribute_class(key: str) -> str:
    """One display bucket for *key*: `"per part"` for the one attribute whose class varies by
    message part (`gen_ai.input.messages`, deliberately absent from `ATTRIBUTE_CLASSES`),
    a content class for every attribute `ATTRIBUTE_CLASSES` names, else `"structure"`."""
    if key == _PER_PART_ATTR:
        return "per part"
    return _telemetry.ATTRIBUTE_CLASSES.get(key, "structure")


def _display(value: object) -> str:
    text = str(value)
    if len(text) > _DISPLAY_MAX_CHARS:
        return f"{text[:_DISPLAY_MAX_CHARS]}…[+{len(text) - _DISPLAY_MAX_CHARS} chars]"
    return text


def _project(
    records: list[dict[str, Any]], policy: _telemetry.ExportPolicy
) -> list[_telemetry.Span]:
    state = _telemetry.ProjectionState()
    spans: list[_telemetry.Span] = []
    for record in records:
        admitted = policy.admit(record)
        if admitted is None:
            continue
        spans.extend(_telemetry.project(admitted, state, policy))
    spans.extend(_telemetry.flush_open(state))
    return spans


def _recorded_content(records: list[dict[str, Any]]) -> bool:
    """Whether any `llm_call` record in *records* already carries a content key -- captured
    only while some enabled exporter granted it at the time (`capture_classes`). A session
    recorded under `minimal` never does, whatever level this preview asks about."""
    for record in records:
        if record.get("event_type") != "llm_call":
            continue
        payload = record.get("payload")
        if isinstance(payload, dict) and any(payload.get(key) for key in _CONTENT_KEYS):
            return True
    return False


def _render(
    name: str,
    tracefile: Path,
    label: str,
    classes: frozenset[str],
    spans: list[_telemetry.Span],
    total_bytes: int,
    note: str | None,
) -> None:
    ui.header(f"Preview: {name}  (session {tracefile.stem})")
    ui.console.print(f"  trace file: {tracefile}", markup=False)
    granted = ", ".join(sorted(classes)) if classes else "(none)"
    ui.console.print(f"  privacy: {label}   shares: {granted}")
    ui.console.print()

    class_counts: dict[str, int] = {}

    def _print_attrs(attrs: dict[str, Any], indent: str) -> None:
        for key, value in attrs.items():
            cls = _attribute_class(key)
            class_counts[cls] = class_counts.get(cls, 0) + 1
            line = f"{indent}{key} [{cls}]  {_display(value)}"
            ui.console.print(escape(line))

    for span in spans:
        ui.console.print(escape(f"  {span.name}"))
        _print_attrs(dict(span.attributes), "    ")
        for event in span.events:
            ui.console.print(escape(f"    event: {event.name}"))
            _print_attrs(dict(event.attributes), "      ")

    ui.console.print()
    ui.console.print(f"  spans: {len(spans)}")
    ui.console.print("  attributes:")
    ui.console.print(f"    structure: {class_counts.get('structure', 0)}")
    for cls in _privacy.CONTENT_CLASSES:
        ui.console.print(f"    {cls}: {class_counts.get(cls, 0)}")
    ui.console.print(f"    per part: {class_counts.get('per part', 0)}")
    ui.console.print(f"  bytes: {total_bytes}")

    if note:
        ui.console.print()
        ui.warn(note)


@export_app.command("preview")
def cmd_preview(
    name: str = typer.Argument(..., help="Exporter name"),
    session: str | None = typer.Option(None, "--session", help="Session id (default: newest)"),
    level: str | None = typer.Option(None, "--level", help="Privacy level to preview"),
    share: str | None = typer.Option(None, "--share", help="Content classes, comma separated"),
    json_out: bool = typer.Option(False, "--json", help="Emit the OTLP document"),
) -> None:
    """Show what an exporter would send for a local session; no network call, no write.

    Example: docket setup export preview langfuse --level actions"""
    spec = _spec_or_exit(name)
    shares = _split(share)
    if level and shares:
        ui.error("--level and --share are mutually exclusive")
        raise typer.Exit(1)
    try:
        if level or shares:
            label, classes = _privacy.resolve(level, shares)
        else:
            label, classes = spec.privacy_label, spec.privacy_classes
    except ValueError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    if session:
        tracefile = _trace.find_trace(session)
        if tracefile is None:
            ui.error(f"No trace found for session: {session}")
            raise typer.Exit(1)
    else:
        tracefile = _newest_trace_file()
        if tracefile is None:
            ui.error("No local sessions found")
            raise typer.Exit(1)
    records = _trace.read_trace(tracefile)
    policy = _telemetry.ExportPolicy(
        events=_events_for(spec),
        classes=classes,
        label=label,
        content_max_chars=spec.content_max_chars,
    )
    spans = _project(records, policy)
    document = _otlp_http.encode(spans, resource=spec.resource, aliases=spec.aliases)
    if json_out:
        typer.echo(_json.dumps(document))
        return
    note: str | None = None
    if classes & {"prompts", "completions", "instructions"} and not _recorded_content(records):
        note = (
            "this session recorded no conversation content; content is captured only once an "
            "exporter grants it, so later sessions would also send it"
        )
    total_bytes = len(_json.dumps(document).encode("utf-8"))
    _render(name, tracefile, label, classes, spans, total_bytes, note)
