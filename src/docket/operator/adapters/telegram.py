"""Telegram outbound delivery for a `kind: channel` document whose dialect is `telegram`
(ADR 0016 SS7): push a rendered text notification to every chat id the operator has
allow-listed in `actors`. The wire format itself lives in
`interfaces/telegram/client.py::send_message` -- the same function `interfaces/telegram/bot.py`'s inbound
poll loop already replies with; this module is the second, explicitly operator-configured
caller `tests/integration/test_telegram_channel.py` pins.

Deliberately narrow: this is the `notify` half of the `telegram` dialect only. `converse`/
`decide` (answering a question, approving a token) stay inbound-only, handled entirely by
`interfaces/telegram/bot.py`'s poll loop against a chat that messaged docket first -- this module never
initiates a conversation, only a one-shot push.
"""

from __future__ import annotations

from docket.interfaces.telegram.client import send_message
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
    """Send *event* to every chat id in `spec.actors`. Never raises. `secret` is the bot
    token, resolved by `operator.notify.resolve_secret` from `spec.secret` -- the built-in
    document names the same `TELEGRAM_BOT_TOKEN` credential `docket setup provider add
    TELEGRAM_BOT_TOKEN` stores. Sends only to `spec.actors`; never broadcasts to every
    `fleet.json` binding."""
    if not secret:
        return DeliveryResult(ok=False, error="channel has no secret (bot token)")
    if not spec.actors:
        return DeliveryResult(ok=False, error="channel has no actors to notify")

    title, body = render_text(event)
    text = f"{title}\n{body}"

    failed = [
        chat_id
        for chat_id in spec.actors
        if not send_message(secret, chat_id, text, request_timeout=timeout)
    ]
    if failed:
        return DeliveryResult(ok=False, error=f"failed to reach chat id(s): {', '.join(failed)}")
    return DeliveryResult(ok=True)
