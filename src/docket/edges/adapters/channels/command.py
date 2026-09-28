"""Runs an operator-supplied binary with the event JSON on stdin (the `command` dialect,
ADR 0016 SS7). The one module in this package that shells out -- `subprocess` is forbidden in
every `core/` module and never `shell=True` here.

`config.argv` is a JSON-encoded list of strings (`config` itself is `dict[str, str]`, so a
real YAML list cannot live in it directly -- the document author writes
`config: {argv: '["/path/to/script", "--flag"]'}`). The built-in `04-command.yaml` document
instead ships a plain `config.command` (a bare binary path, no arguments); this adapter
accepts either, preferring `argv` when both are set.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from docket.core.channel import ChannelSpec
from docket.core.operator_contract import CloudEvent

from .webhook import DeliveryResult

_SUBPROCESS_TIMEOUT_S = 10


def _resolve_argv(spec: ChannelSpec) -> list[str] | None:
    raw_argv = spec.config.get("argv", "")
    if raw_argv:
        try:
            parsed: Any = json.loads(raw_argv)
        except (json.JSONDecodeError, TypeError):
            return None
        if isinstance(parsed, list) and parsed and all(isinstance(a, str) for a in parsed):
            return parsed
        return None
    command = spec.config.get("command", "").strip()
    return [command] if command else None


def deliver(
    spec: ChannelSpec, event: CloudEvent, *, secret: str | None, timeout: float
) -> DeliveryResult:
    """Run the resolved argv with the CloudEvent JSON on stdin. Never raises, never
    `shell=True`. *secret* is unused: a local command reads whatever credential it needs from
    its own environment, never from docket's stored secret."""
    del secret
    argv = _resolve_argv(spec)
    if argv is None:
        return DeliveryResult(ok=False, error="channel has no config.argv/config.command")

    body = json.dumps(event.model_dump(by_alias=True, mode="json")).encode()
    bounded_timeout = min(timeout, _SUBPROCESS_TIMEOUT_S)
    try:
        result = subprocess.run(
            argv, input=body, timeout=bounded_timeout, check=False, capture_output=True
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return DeliveryResult(ok=False, error=str(exc))

    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        return DeliveryResult(
            ok=False, status=result.returncode, error=detail or f"exit {result.returncode}"
        )
    return DeliveryResult(ok=True, status=0)
