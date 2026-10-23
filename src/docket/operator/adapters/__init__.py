"""Delivery dialects for `kind: channel` documents (ADR 0016 SS7). `sink_for` maps a
`ChannelSpec`'s `dialect` to its `deliver` function -- the one seam `operator/notify.py::flush`
uses; `core/` never imports this package directly.

Wired here: `console`, `webhook`, `command`, `ntfy`, `desktop`, `email`, `telegram`.
"""

from __future__ import annotations

from typing import Protocol

from docket.operator.adapters.command import deliver as _command_deliver
from docket.operator.adapters.console import deliver as _console_deliver
from docket.operator.adapters.desktop import deliver as _desktop_deliver
from docket.operator.adapters.email import deliver as _email_deliver
from docket.operator.adapters.ntfy import deliver as _ntfy_deliver
from docket.operator.adapters.telegram import deliver as _telegram_deliver
from docket.operator.adapters.webhook import DeliveryResult
from docket.operator.adapters.webhook import deliver as _webhook_deliver
from docket.operator.channel import ChannelSpec
from docket.operator.contract import CloudEvent

__all__ = ["Deliver", "DeliveryResult", "sink_for"]


class Deliver(Protocol):
    """One dialect's send function: sends *event* through *spec*, never raises."""

    def __call__(
        self, spec: ChannelSpec, event: CloudEvent, *, secret: str | None, timeout: float
    ) -> DeliveryResult: ...


_DIALECTS: dict[str, Deliver] = {
    "console": _console_deliver,
    "webhook": _webhook_deliver,
    "command": _command_deliver,
    "ntfy": _ntfy_deliver,
    "desktop": _desktop_deliver,
    "email": _email_deliver,
    "telegram": _telegram_deliver,
}


def sink_for(spec: ChannelSpec) -> Deliver | None:
    """The `deliver` function for *spec*'s dialect, or `None` for one not wired yet."""
    return _DIALECTS.get(spec.dialect)
