"""SMTP email delivery for a `kind: channel` document whose dialect is `email` (ADR 0016 SS7):
send notifications via SMTP. Uses stdlib smtplib and email.message only."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from docket.operator.adapters.webhook import DeliveryResult
from docket.operator.channel import ChannelSpec
from docket.operator.contract import CloudEvent
from docket.operator.notify import render_text


def deliver(
    spec: ChannelSpec,
    event: CloudEvent,
    *,
    secret: str | None,
    timeout: float,
) -> DeliveryResult:
    """Send an email via SMTP. Never raises."""
    host = spec.config.get("smtpHost", "")
    sender = spec.config.get("from", "")
    to = spec.config.get("to", "")
    if not host:
        return DeliveryResult(ok=False, error="channel has no config.smtpHost")
    if not sender or not to:
        return DeliveryResult(ok=False, error="channel missing config.from or config.to")

    named_secret = getattr(spec, "secret", None)
    if named_secret and not secret:
        return DeliveryResult(ok=False, error=f"channel secret {named_secret} did not resolve")

    port_str = spec.config.get("port", "587")
    try:
        port = int(port_str)
    except ValueError:
        return DeliveryResult(ok=False, error=f"invalid port: {port_str}")

    title, body = render_text(event)

    try:
        msg = EmailMessage()
        msg["Subject"] = f"[docket] {title}"
        msg["From"] = sender
        msg["To"] = to
        msg.set_content(body)

        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            smtp.ehlo()
            if smtp.has_extn("starttls"):
                smtp.starttls()
                smtp.ehlo()
            elif secret:
                return DeliveryResult(
                    ok=False, error="server does not offer STARTTLS; the secret was not sent"
                )
            if secret:
                smtp.login(spec.config.get("user") or sender, secret)
            smtp.send_message(msg)

        return DeliveryResult(ok=True)
    except Exception as exc:
        return DeliveryResult(ok=False, error=str(exc))
