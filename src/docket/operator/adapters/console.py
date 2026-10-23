"""No-op delivery for the `console` dialect: the console *is* the inbox (`docket inbox`
already shows everything a channel event would repeat), so nothing is sent. Present so
`sink_for` always finds a `deliver` function for a dialect the catalog allows.
"""

from __future__ import annotations

from docket.operator.adapters.webhook import DeliveryResult
from docket.operator.channel import ChannelSpec
from docket.operator.contract import CloudEvent


def deliver(
    spec: ChannelSpec, event: CloudEvent, *, secret: str | None, timeout: float
) -> DeliveryResult:
    """Always succeeds without sending anything."""
    del spec, event, secret, timeout
    return DeliveryResult(ok=True)
