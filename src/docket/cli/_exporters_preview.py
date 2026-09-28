"""docket exporters preview -- see what a destination would receive before sharing it.

Projects a real local session through one exporter's `ExportPolicy` (its own resolved
`privacy`/`share`, or an overriding `--level`/`--share`, which is never written) and prints
exactly what would be sent: no network call, no write, no audit entry. See ADR 0015 rule 10 and
observability-export.spec.md "Preview".
"""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Any

from rich.markup import escape

import docket.config as _cfg
from docket import ui
from docket.core import exporter as _exp
from docket.core import privacy as _privacy
from docket.core import telemetry as _telemetry
from docket.core import trace as _trace
from docket.edges.adapters.exporters import otlp_http as _otlp_http

_DISPLAY_MAX_CHARS = 200
_PER_PART_ATTR = "gen_ai.input.messages"
_CONTENT_KEYS = ("inputMessages", "outputMessages", "systemInstructions")


def _parse_opts(args: list[str]) -> tuple[list[str], dict[str, str]]:
    """Split *args* into positionals and `--key value`/`--key=value` options -- the same
    hand-parsed shape every `cli/_exporters*.py` action uses."""
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
    ui.console.print(f"  trace file: {tracefile}")
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


def run_preview(args: list[str]) -> int:
    """`docket exporters preview <name> [--session <id>] [--level <level>|--share a,b]
    [--json]`. Returns a process exit code. No socket, no write, no audit entry."""
    json_out = "--json" in args
    args = [a for a in args if a != "--json"]
    pos, opts = _parse_opts(args)
    if not pos:
        ui.error(
            "Usage: docket exporters preview <name> [--session <id>]"
            " [--level minimal|actions|conversation|full] [--share a,b] [--json]"
        )
        return 1
    name = pos[0]

    catalog = _exp.load_catalog()
    spec = catalog.get(name)
    if spec is None:
        ui.error(f"Unknown exporter '{name}'.")
        return 1

    level = opts.get("level") or None
    share_raw = opts.get("share")
    share = [s.strip() for s in share_raw.split(",") if s.strip()] if share_raw else None
    if level and share:
        ui.error("--level and --share are mutually exclusive")
        return 1

    try:
        if level or share:
            label, classes = _privacy.resolve(level, share)
        else:
            label, classes = spec.privacy_label, spec.privacy_classes
    except ValueError as exc:
        ui.error(str(exc))
        return 1

    session_id = opts.get("session")
    if session_id:
        tracefile = _trace.find_trace(session_id)
        if tracefile is None:
            ui.error(f"No trace found for session: {session_id}")
            return 1
    else:
        tracefile = _newest_trace_file()
        if tracefile is None:
            ui.error("No local sessions found.")
            return 1

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
        ui.console.print(_json.dumps(document))
        return 0

    note: str | None = None
    if classes & {"prompts", "completions", "instructions"} and not _recorded_content(records):
        note = (
            "this session recorded no conversation content; content is captured only once an "
            "exporter grants it, so later sessions would also send it"
        )
    total_bytes = len(_json.dumps(document).encode("utf-8"))
    _render(name, tracefile, label, classes, spans, total_bytes, note)
    return 0
