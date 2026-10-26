from __future__ import annotations

import threading

from docket.interfaces.telegram import bot as _telegram

# The Telegram long-poll loop. `interfaces.telegram.bot.poll_once` never raises for an
# unconfigured bot or a network failure (it returns a typed summary) -- the
# `except Exception` below is a last-resort backstop for a genuinely
# unexpected bug in that call chain, and it prints rather than swallows
# (a bare `contextlib.suppress(Exception)` around dispatch is banned; a
# delegate action reaching `tasks.application.queue.enqueue_task_once` is exactly that
# "dispatch" this loop must not hide a failure from).
TELEGRAM_UNCONFIGURED_BACKOFF_S = 30
TELEGRAM_ERROR_BACKOFF_S = 5


def telegram_poll_loop(stop: threading.Event) -> None:
    """Long-poll Telegram (one batch per call) until *stop* is set.

    Paced by Telegram's own blocking `getUpdates` wait when a bot token is configured and the
    previous call succeeded, so no extra sleep is needed on the happy path. Backs off on an
    unconfigured bot (re-checked periodically, in case a token is added while `docket start` is
    up) or a transport failure, so neither case busy-loops. A resolved-timeout misconfiguration
    warning prints once, not every poll -- the underlying env var cannot change without a
    restart."""

    printed_unconfigured = False
    printed_timeout_warning = False
    while not stop.is_set():
        try:
            summary = _telegram.poll_once()
        except Exception as exc:  # pragma: no cover - backstop, see docstring above
            print(f"[serve] telegram: poll failed: {type(exc).__name__}: {exc}")
            if stop.wait(TELEGRAM_ERROR_BACKOFF_S):
                return
            continue

        if not summary.configured:
            if not printed_unconfigured:
                print(
                    "[serve] telegram: no TELEGRAM_BOT_TOKEN configured "
                    "(docket setup notify enable telegram) -- channel idle"
                )
                printed_unconfigured = True
            if stop.wait(TELEGRAM_UNCONFIGURED_BACKOFF_S):
                return
            continue

        printed_unconfigured = False
        if summary.warning and not printed_timeout_warning:
            print(f"[serve] telegram: {summary.warning}")
            printed_timeout_warning = True
        if not summary.ok:
            print(f"[serve] telegram: {summary.error}")
            if stop.wait(TELEGRAM_ERROR_BACKOFF_S):
                return
