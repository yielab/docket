"""Ntfy.sh delivery for a `kind: channel` document whose dialect is `ntfy` (ADR 0016 SS7):
POST the notification title and body as HTTP headers to an ntfy.sh server. Stdlib `urllib`
only."""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any

from docket.core.channel import ChannelSpec
from docket.core.notify import render_text
from docket.core.operator_contract import CloudEvent

from .webhook import DeliveryResult


def deliver(
    spec: ChannelSpec,
    event: CloudEvent,
    *,
    secret: str | None,
    timeout: float,
    opener: Any = urllib.request.urlopen,
) -> DeliveryResult:
    """POST the event to an ntfy.sh server. Never raises."""
    url = (
        spec.config.get("server", "https://ntfy.sh").rstrip("/")
        + "/"
        + spec.config.get("topic", "")
    )
    if not spec.config.get("topic"):
        return DeliveryResult(ok=False, error="channel has no config.topic")

    title, body = render_text(event)
    priority = (
        "high" if event.type.endswith(("input_required", "approval.requested")) else "default"
    )

    headers = {"Title": title, "Priority": priority}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    request = urllib.request.Request(url, data=body.encode(), headers=headers, method="POST")
    try:
        with opener(request, timeout=timeout) as resp:
            resp.read()
            status = int(resp.status)
            return DeliveryResult(ok=200 <= status < 300, status=status)
    except urllib.error.HTTPError as exc:
        return DeliveryResult(ok=False, status=exc.code, error=exc.reason or f"HTTP {exc.code}")
    except urllib.error.URLError as exc:
        return DeliveryResult(ok=False, error=f"cannot reach {url}: {exc.reason}")
    except OSError as exc:
        return DeliveryResult(ok=False, error=f"cannot reach {url}: {exc}")
