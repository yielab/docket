"""Native OS notification delivery for a `kind: channel` document whose dialect is `desktop`
(ADR 0016 SS7): send notifications using `osascript` on macOS or `notify-send` on Linux."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

from docket.kernel.operator_contract import CloudEvent
from docket.operator.adapters.webhook import DeliveryResult
from docket.operator.channel import ChannelSpec
from docket.operator.notify import render_text


def deliver(
    spec: ChannelSpec,
    event: CloudEvent,
    *,
    secret: str | None,
    timeout: float,
) -> DeliveryResult:
    """Send a desktop notification. Never raises, never shell=True."""
    del spec, secret

    title, body = render_text(event)

    if sys.platform == "darwin":
        cmd = [
            "osascript",
            "-e",
            f"display notification {json.dumps(body)} with title {json.dumps(title)}",
        ]
        binary_name = "osascript"
    else:
        cmd = ["notify-send", title, body]
        binary_name = "notify-send"

    if not shutil.which(cmd[0]):
        return DeliveryResult(ok=False, error=f"{binary_name} not found")

    try:
        result = subprocess.run(cmd, timeout=timeout, check=False, capture_output=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return DeliveryResult(ok=False, error=str(exc))

    ok = result.returncode == 0
    return DeliveryResult(ok=ok)
