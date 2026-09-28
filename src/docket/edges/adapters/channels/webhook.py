"""Standard Webhooks delivery for a `kind: channel` document whose dialect is `webhook`
(ADR 0016 SS1/SS7): POST the CloudEvent as `application/cloudevents+json` with
`webhook-id`/`webhook-timestamp`/`webhook-signature` headers. Stdlib `urllib` only, modelled
on `edges/adapters/exporters/otlp_http.py`.

`DeliveryResult` is the shared outcome shape every dialect in this package returns --
`command.py`/`console.py` import it from here rather than redefining it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from docket.core.channel import ChannelSpec
from docket.core.operator_contract import CloudEvent


@dataclass(frozen=True)
class DeliveryResult:
    """The outcome of one dialect's `deliver` call. `ok` is `False` for any failure --
    transport, auth, a missing config key. `deliver` never raises."""

    ok: bool
    status: int | None = None
    error: str = ""


def _sign(secret_value: str, event_id: str, ts: str, body: bytes) -> str:
    """`v1,<base64>` over `hmac-sha256(base64-decoded whsec_ key, "<id>.<ts>.<body>")` -- the
    Standard Webhooks signature scheme (ADR 0016 SS1)."""
    key = base64.b64decode(secret_value.removeprefix("whsec_"))
    signed = f"{event_id}.{ts}.".encode() + body
    digest = hmac.new(key, signed, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode()


def deliver(
    spec: ChannelSpec,
    event: CloudEvent,
    *,
    secret: str | None,
    timeout: float,
    opener: Any = urllib.request.urlopen,
) -> DeliveryResult:
    """POST *event* to `spec.config["url"]`. Never raises -- a missing URL, a transport
    failure or a non-2xx response all return `ok=False`."""
    url = spec.config.get("url", "")
    if not url:
        return DeliveryResult(ok=False, error="channel has no config.url")

    body = json.dumps(event.model_dump(by_alias=True, mode="json"), sort_keys=True).encode()
    ts = str(int(time.time()))
    headers = {
        "Content-Type": "application/cloudevents+json",
        "webhook-id": event.id,
        "webhook-timestamp": ts,
    }
    if secret:
        headers["webhook-signature"] = _sign(secret, event.id, ts, body)

    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
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
