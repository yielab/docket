"""SMTP email delivery for a `kind: channel` document whose dialect is `email` (ADR 0016 SS7):
send notifications via SMTP. Uses stdlib smtplib and email.message only."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

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
) -> DeliveryResult:
    """Send an email via SMTP. Never raises."""
    host = spec.config.get("host", "")
    if not host:
        return DeliveryResult(ok=False, error="channel has no config.host")
    if not secret:
        return DeliveryResult(ok=False, error="channel has no secret (username credential)")

    port_str = spec.config.get("port", "587")
    user = spec.config.get("user", "")
    to = spec.config.get("to", "")

    if not user or not to:
        return DeliveryResult(ok=False, error="channel missing config.user or config.to")

    try:
        port = int(port_str)
    except ValueError:
        return DeliveryResult(ok=False, error=f"invalid port: {port_str}")

    title, body = render_text(event)

    try:
        msg = EmailMessage()
        msg["Subject"] = f"[docket] {title}"
        msg["From"] = user
        msg["To"] = to
        msg.set_content(body)

        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            smtp.starttls()
            smtp.login(user, secret)
            smtp.send_message(msg)

        return DeliveryResult(ok=True)
    except Exception as exc:
        return DeliveryResult(ok=False, error=str(exc))
