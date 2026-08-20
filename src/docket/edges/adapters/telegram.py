"""Telegram Bot API adapter.

The **only** module in docket that knows the Telegram Bot API's wire format --
``getUpdates`` (long-poll) and ``sendMessage``. Stdlib ``urllib`` only, zero
new dependencies -- the same precedent ``edges/adapters/llm.py`` and
``edges/adapters/fetch.py`` already set for renting a protocol without
renting a vendor SDK ("docket rents protocols only").

Everything above this module speaks the typed ``TelegramUpdate`` shape;
nothing outside this file ever builds a Telegram URL, reads a Telegram JSON
response, or touches the bot token directly -- ``core/telegram.py`` calls
:func:`get_updates`/:func:`send_message` and never sees the wire format.

Real-world long-poll quirks handled here, not above:

- A ``getUpdates`` call with no new messages blocks server-side for up to
  ``timeout`` seconds and returns an empty list -- that is success, not a
  failure to report. ``request_timeout`` (this process's own socket timeout)
  must exceed ``timeout`` or a legitimately empty long-poll reads as a local
  timeout instead of "nothing happened". This module takes both values as
  given and does not enforce that relationship -- ``core/telegram.py``'s
  ``poll_once`` resolves ``request_timeout`` from config and corrects a
  misconfigured pair before ever calling down to this function.
- ``offset`` is the caller's job to advance (Telegram only forgets an update
  once a strictly-greater offset has been acknowledged); this module is
  stateless per call and simply echoes back every update it decoded so the
  caller can compute the next offset.
- A network failure (DNS, connection refused, a slow/dead endpoint) degrades
  to a typed ``ok=False`` result -- neither function ever raises, so a poll
  loop above can keep going and try again next iteration instead of taking
  ``docket serve`` down.

**The bot token never appears in a returned error message.** Every failure
path below reports the HTTP status / Telegram's own ``description`` field /
the socket exception's reason -- never the request URL the token is embedded
in. This is a real, tested property (see the adapter test module's
``TestTokenNeverLeaks``), not an assumption.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

# Overridable so tests can point this module at a local stdlib http.server
# instead of the real Telegram API -- the same seam
# edges/adapters/fetch.py's tests use for FETCH_ALLOWED_DOMAINS, applied to a
# module constant instead of a config knob because this is wire-format-only,
# not policy.
API_ROOT = "https://api.telegram.org"

_MAX_ERROR_DETAIL = 300


@dataclass(frozen=True)
class TelegramUpdate:
    """One inbound message, narrowed to the fields this module's callers use.

    ``chat_id``/``user_id`` are strings (Telegram's own ids are 64-bit
    integers that do not always fit a JS/JSON-safe integer range) -- callers
    compare them against ``fleet.json`` binding ids, which are already
    strings.
    """

    update_id: int
    chat_id: str
    user_id: str
    text: str
    chat_type: str = ""
    chat_title: str = ""


@dataclass(frozen=True)
class GetUpdatesResult:
    """Outcome of one ``getUpdates`` call. Never raised -- see module docstring."""

    ok: bool
    updates: tuple[TelegramUpdate, ...] = ()
    error: str = ""


def _parse_updates(raw: list[object]) -> list[TelegramUpdate]:
    """Decode ``result`` from a ``getUpdates`` response body.

    Tolerant by design: an update this module doesn't understand (an edited
    message, a callback query, a channel post, a malformed entry) is skipped,
    never raised -- one bad entry in a batch must not lose the rest.
    """
    out: list[TelegramUpdate] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        update_id = entry.get("update_id")
        if not isinstance(update_id, int):
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        chat = message.get("chat")
        chat_id_raw = chat.get("id") if isinstance(chat, dict) else None
        if chat_id_raw is None:
            continue
        frm = message.get("from")
        user_id_raw = frm.get("id") if isinstance(frm, dict) else None
        text = message.get("text")
        if not isinstance(text, str):
            continue
        out.append(
            TelegramUpdate(
                update_id=update_id,
                chat_id=str(chat_id_raw),
                user_id=str(user_id_raw) if user_id_raw is not None else "",
                text=text,
                chat_type=str(chat.get("type") or "") if isinstance(chat, dict) else "",
                chat_title=str(chat.get("title") or "") if isinstance(chat, dict) else "",
            )
        )
    return out


def get_updates(
    token: str,
    *,
    offset: int = 0,
    timeout: int = 25,
    request_timeout: float = 35,
) -> GetUpdatesResult:
    """Long-poll ``getUpdates`` once. Never raises.

    ``offset`` should be ``last_processed_update_id + 1`` -- Telegram treats
    every update below it as acknowledged and will not resend it.
    """
    if not token:
        return GetUpdatesResult(False, error="no bot token configured")

    params = {"offset": str(offset), "timeout": str(timeout)}
    url = f"{API_ROOT}/bot{token}/getUpdates?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=request_timeout) as resp:
            raw_body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as ex:
        # The body carries Telegram's own error description (e.g. "Unauthorized"
        # for a bad token) -- never the request URL, so the token cannot leak
        # through it even though it is what caused the failure.
        try:
            detail = ex.read().decode("utf-8", errors="replace").strip()
        except OSError:
            detail = ""
        return GetUpdatesResult(
            False, error=f"Telegram HTTP {ex.code}: {detail[:_MAX_ERROR_DETAIL]}"
        )
    except TimeoutError:
        return GetUpdatesResult(
            False, error=f"timed out after {request_timeout}s waiting for updates"
        )
    except urllib.error.URLError as ex:
        if isinstance(ex.reason, TimeoutError):
            return GetUpdatesResult(
                False, error=f"timed out after {request_timeout}s waiting for updates"
            )
        return GetUpdatesResult(False, error=f"cannot reach Telegram: {ex.reason}")
    except OSError as ex:
        return GetUpdatesResult(False, error=f"cannot reach Telegram: {ex}")

    try:
        data = json.loads(raw_body) if raw_body.strip() else {}
    except json.JSONDecodeError:
        return GetUpdatesResult(False, error="Telegram returned non-JSON")
    if not isinstance(data, dict):
        return GetUpdatesResult(False, error="Telegram returned a non-object response")
    if not data.get("ok"):
        return GetUpdatesResult(
            False, error=str(data.get("description") or "Telegram reported an error")
        )
    result = data.get("result")
    if not isinstance(result, list):
        return GetUpdatesResult(False, error="malformed getUpdates response (no 'result' list)")
    return GetUpdatesResult(True, updates=tuple(_parse_updates(result)))


def send_message(token: str, chat_id: str, text: str, *, request_timeout: float = 15) -> bool:
    """Send a plain-text reply. Returns ``False`` (never raises) on any failure.

    No inline keyboards, no Markdown/HTML parse mode, no rich UI --
    deliberately out of scope (approvals need a reply a human can read, not
    a UI kit). ``chat_id`` is deliberately required non-empty: sending is only
    ever called with the chat_id an inbound update just arrived on.
    """
    if not token or not chat_id:
        return False
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    url = f"{API_ROOT}/bot{token}/sendMessage"
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=request_timeout) as resp:
            raw_body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError:
        return False
    except (urllib.error.URLError, OSError, TimeoutError):
        return False

    try:
        data = json.loads(raw_body) if raw_body.strip() else {}
    except json.JSONDecodeError:
        return False
    return bool(isinstance(data, dict) and data.get("ok"))
