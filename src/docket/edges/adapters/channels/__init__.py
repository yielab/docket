"""Delivery dialects for `kind: channel` documents (ADR 0016 SS7). `sink_for` maps a
`ChannelSpec`'s `dialect` to its `deliver` function -- the one seam `core/notify.py::flush`
uses; `core/` never imports this package directly.

Wired here: `console`, `webhook`, `command`, `ntfy`, `desktop`, `email`, `telegram`.
"""

from __future__ import annotations

from typing import Protocol

from docket.core.channel import ChannelSpec
from docket.core.operator_contract import CloudEvent

from .command import deliver as _command_deliver
from .console import deliver as _console_deliver
from .desktop import deliver as _desktop_deliver
from .email import deliver as _email_deliver
from .ntfy import deliver as _ntfy_deliver
from .telegram import deliver as _telegram_deliver
from .webhook import DeliveryResult
from .webhook import deliver as _webhook_deliver

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
