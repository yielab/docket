"""The HTTP call one service operation makes, inside the perimeter of `platform/perimeter.py`.

The caller is docket's own process, not the jail (as `fetch` is), so the hosts it may reach are the
service's alone: the base URL's host and the hosts the service document lists. Like `fetch`'s
allowlist that set is containment, independent of the gate that decided before this ran, and it
holds no policy vocabulary. The caller resolves a secret into a header before building the request,
so this module imports nothing from `governance`; it redacts the credential from what it returns
instead.

Zero new dependencies, as `fetch`: stdlib `urllib` and `http.client`.
"""

from __future__ import annotations

import contextlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field

from docket.kernel import clock as _clock
from docket.kernel.errors import InvalidInput, Refused
from docket.kernel.home import current_home
from docket.kernel.service import ResponseProjection
from docket.kernel.tool_outcome import ToolOutcome, text_outcome
from docket.platform.perimeter import build_opener, read_until_deadline

_USER_AGENT = "docket-service/1"
_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
_ERROR_HEAD = 500
_PARAM = re.compile(r"\{([^{}]+)\}")
_HEADER_NAME = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
_FORBIDDEN_HEADERS = frozenset({"host", "content-length", "transfer-encoding"})
_SENSITIVE_WORDS = ("key", "token", "secret", "auth")
_SENSITIVE_NAMES = frozenset({"cookie", "proxy-authorization"})
_REDACTED = "[REDACTED]"
_NOT_ALLOWED = "service_not_allowed"
_BAD_REQUEST = "service_bad_request"


@dataclass(frozen=True)
class ServiceRequest:
    """One resolved operation call. *path* is a template whose `{name}` parts take *path_params*;
    *timeout* bounds the whole call in seconds, ``0`` meaning ``Home.fetch_timeout_s``; *response*
    cuts a JSON answer to the fields the model needs."""

    method: str
    base_url: str
    path: str = ""
    path_params: Mapping[str, str] = field(default_factory=dict)
    query: Mapping[str, object] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)
    body: object | None = None
    hosts: tuple[str, ...] = ()
    secrets: tuple[str, ...] = ()
    timeout: float = 0.0
    response: ResponseProjection | None = None


def _split_base(base_url: str) -> urllib.parse.SplitResult:
    parts = urllib.parse.urlsplit(base_url)
    try:
        parts.port  # noqa: B018 -- reading it validates the port
    except ValueError:
        raise Refused(f"{base_url!r} has an invalid port") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise Refused(f"{base_url!r} is not an http(s) URL with a host")
    if parts.username is not None or parts.password is not None:
        raise Refused("a service base URL must not embed credentials")
    return parts


def _query_pairs(query: Mapping[str, object]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for key, value in query.items():
        for item in value if isinstance(value, list | tuple) else [value]:
            if item is None:
                continue
            if isinstance(item, bool):
                pairs.append((key, "true" if item else "false"))
            elif isinstance(item, dict):
                pairs.append((key, json.dumps(item, separators=(",", ":"))))
            else:
                pairs.append((key, str(item)))
    return pairs


def build_url(request: ServiceRequest) -> str:
    """The base URL plus the path with each parameter percent-encoded, plus the query."""
    template = (
        request.path if request.path.startswith("/") or not request.path else "/" + request.path
    )
    if "{" in _PARAM.sub("", template) or "}" in _PARAM.sub("", template):
        raise InvalidInput(f"path {request.path!r} has an unmatched brace")

    def fill(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in request.path_params:
            raise InvalidInput(f"path parameter {name!r} has no value")
        value = str(request.path_params[name])
        if value in (".", ".."):
            raise InvalidInput(f"path parameter {name!r} must not be {value!r}")
        return urllib.parse.quote(value, safe="")

    url = request.base_url.rstrip("/") + _PARAM.sub(fill, template)
    pairs = _query_pairs(request.query)
    return f"{url}?{urllib.parse.urlencode(pairs)}" if pairs else url


def check_headers(headers: Mapping[str, str]) -> None:
    """Refuse a header that could split the request or override what the client owns."""
    for name, value in headers.items():
        if not _HEADER_NAME.fullmatch(name):
            raise InvalidInput(f"header name {name!r} is not a valid HTTP token")
        if name.lower() in _FORBIDDEN_HEADERS:
            raise InvalidInput(f"header {name!r} is set by the client, not the document")
        if any(ch in str(value) for ch in "\r\n\x00"):
            raise InvalidInput(f"header {name!r} holds a CR, LF or NUL character")


def redactions(headers: Mapping[str, str], secrets: tuple[str, ...]) -> tuple[str, ...]:
    """The values to scrub from an outcome: credential headers (whole and after the scheme)."""
    values: list[str] = []
    for name, value in headers.items():
        lowered = name.lower()
        if lowered in _SENSITIVE_NAMES or any(word in lowered for word in _SENSITIVE_WORDS):
            values.append(str(value))
            if " " in str(value).strip():
                values.append(str(value).strip().split(None, 1)[1])
    values.extend(secrets)
    return tuple(dict.fromkeys(v for v in values if v))


def redact(text: str, values: tuple[str, ...]) -> str:
    for value in sorted(values, key=len, reverse=True):
        if value:
            text = text.replace(value, _REDACTED)
    return text


def project_response(body: object, projection: ResponseProjection) -> object:
    """The list at ``projection.items`` with each object cut to ``projection.fields``; *body*
    itself when the path does not lead to a list."""
    node = body
    for key in projection.items.split("."):
        if not isinstance(node, dict) or key not in node:
            return body
        node = node[key]
    if not isinstance(node, list):
        return body
    return [
        {name: item[name] for name in projection.fields if name in item}
        if isinstance(item, dict)
        else item
        for item in node
    ]


def _success(
    content_type: str, raw: bytes, cap: int, projection: ResponseProjection | None
) -> ToolOutcome:
    truncated = len(raw) > cap
    text = raw[:cap].decode("utf-8", errors="replace")
    if truncated:
        return ToolOutcome(True, content=f"{text}\n\n[truncated: response exceeded {cap} bytes]")
    if "json" in content_type.lower() and text.strip():
        with contextlib.suppress(ValueError):
            parsed = json.loads(text)
            if projection is not None:
                parsed = project_response(parsed, projection)
            text = json.dumps(parsed, separators=(",", ":"), ensure_ascii=False)
    return text_outcome(text)


def call_operation(request: ServiceRequest) -> ToolOutcome:
    """Send one operation's request inside the perimeter; nothing raises."""
    scrub = redactions(request.headers, request.secrets)
    try:
        return _call(request, scrub)
    except InvalidInput as ex:
        return ToolOutcome(False, error=redact(str(ex), scrub), refusal=_BAD_REQUEST)
    except Refused as ex:
        return ToolOutcome(False, error=redact(str(ex), scrub), refusal=_NOT_ALLOWED)


def _call(request: ServiceRequest, scrub: tuple[str, ...]) -> ToolOutcome:
    method = request.method.upper()
    if method not in _METHODS:
        raise InvalidInput(f"unsupported method {request.method!r}")
    check_headers(request.headers)
    base = _split_base(request.base_url)
    url = build_url(request)
    host = (base.hostname or "").lower()
    listed = frozenset(h.lower() for h in request.hosts)
    allowed = listed | {host}
    shown = f"{host}{urllib.parse.urlsplit(url).path}"

    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json, text/plain;q=0.9"}
    headers.update(request.headers)
    data = None
    if request.body is not None:
        data = json.dumps(request.body, separators=(",", ":"), ensure_ascii=False).encode()
        if not any(name.lower() == "content-type" for name in headers):
            headers["Content-Type"] = "application/json"

    home = current_home()
    cap = home.fetch_max_response_bytes
    timeout = request.timeout or home.fetch_timeout_s
    deadline = _clock.monotonic() + timeout
    opener = build_opener(
        allowed.__contains__,
        listed,
        outside="outside the service's hosts",
        fix="list the host in the service's hosts to permit it",
    )

    try:
        with opener.open(
            urllib.request.Request(url, data=data, headers=headers, method=method), timeout=timeout
        ) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = read_until_deadline(resp, cap, deadline)
    except urllib.error.HTTPError as ex:
        try:
            head = ex.read(2000).decode("utf-8", errors="replace").strip()
        except OSError:
            head = ""
        detail = redact(head[:_ERROR_HEAD] or str(ex.reason), scrub)
        return ToolOutcome(False, error=f"HTTP {ex.code} from {method} {shown}: {detail}")
    except TimeoutError:
        return ToolOutcome(False, error=f"timed out after {timeout}s calling {shown}")
    except urllib.error.URLError as ex:
        why = "timed out" if isinstance(ex.reason, TimeoutError) else f"cannot reach: {ex.reason}"
        return ToolOutcome(False, error=redact(f"{why} ({shown})", scrub))
    except OSError as ex:
        return ToolOutcome(False, error=redact(f"cannot reach {shown}: {ex}", scrub))
    if raw is None:
        return ToolOutcome(False, error=f"timed out after {timeout}s calling {shown}")
    outcome = _success(content_type, raw, cap, request.response)
    return ToolOutcome(True, content=redact(outcome.content, scrub))
