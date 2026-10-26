"""HTTP `fetch` tool: an inspectable, allowlisted egress path.

**What this module is not.** It does not close docket's network-egress gap.
That gap has been measured precisely: `curl`/`wget` correctly ask for approval
through the `bash` tool's command classifier, but `python3 -c
"import urllib..."`, `node`, and `git clone <url>` are all on the curated
exec allowlist (`governance/security.py`'s `SAFE_BINS`) and reach the network
unattended today. Closing that would mean a `--network none`/`--unshare-net`
sandbox lockdown, which was deliberately **deferred** — it is off by
default, it breaks `npm install`/`pip`/`git clone` when turned on, and it
buys a config option, not a guarantee. This module ships the other half of
that decision instead: a first-class tool that gives an agent an
*inspectable* way to reach the network, so reaching for `fetch` never has to
mean reaching for the escape hatch.

**Mechanism, not a gate — same discipline as `agent/tools/builtins/toolbox.py`.**
The domain allowlist, response-size cap, and timeout enforced here are
containment, exactly the way `toolbox.resolve_within` contains a file path:
real, load-bearing, and independent of whatever `agent/tools/registry.py`'s chokepoint
(`evaluate_tool_call` / `dispatch_tool`) decided before this function was
ever called. This module holds no approval/policy vocabulary and consults no
gate of its own — a second module that could decide whether to run is a
second place a gate can be forgotten (see `agent/tools/registry.py`'s module docstring).

**Zero new dependencies, on purpose** — the same stdlib-`urllib` choice
`models/adapters/openai_http.py` already made, for the same reason: pulling in
an HTTP client library for a GET request would be the exact kind of
dependency creep ROADMAP §4.5's anti-overengineering guardrails exist to
block.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request

from docket.kernel import clock as _clock
from docket.kernel.home import current_home
from docket.kernel.tool_outcome import ToolOutcome, text_outcome

_USER_AGENT = "docket-fetch/1"
# A caller's per-call timeout is clamped to this multiple of FETCH_TIMEOUT_S.
FETCH_CLAMP_MULTIPLE = 4
_READ_CHUNK = 8192


class _DomainLockedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse to follow a redirect off the allowlist.

    Without this, an allowlisted host could redirect anywhere and the
    allowlist would be decorative — `urllib` follows redirects transparently
    by default. `redirect_request` is the sanctioned extension point for
    exactly this (see the stdlib docs: "raising `HTTPError` if the redirect
    should not happen"), so the refusal surfaces through the same
    `urllib.error.HTTPError` path every other HTTP failure in this module
    already handles, rather than needing a parallel error case.
    """

    def __init__(self, allowed: frozenset[str]) -> None:
        self._allowed = allowed

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        new_host = (urllib.parse.urlsplit(newurl).hostname or "").lower()
        if new_host not in self._allowed:
            raise urllib.error.HTTPError(
                newurl,
                code,
                f"redirected to {new_host!r}, which is not on the fetch domain allowlist",
                {},  # type: ignore[arg-type]
                None,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)  # type: ignore[arg-type]


def allowed_domains() -> frozenset[str]:
    return frozenset(current_home().fetch_allowed_domains)


def _effective_timeout(timeout: int) -> float:
    """The caller's timeout bounded by the clamp; non-positive falls back to the default."""
    if timeout > 0:
        return min(timeout, FETCH_CLAMP_MULTIPLE * current_home().fetch_timeout_s)
    return current_home().fetch_timeout_s


def _read_until_deadline(resp: object, cap: int, deadline: float) -> bytes | None:
    """Read up to *cap* + 1 bytes in chunks; None when the monotonic *deadline* passes first."""
    read1 = getattr(resp, "read1", None) or resp.read  # type: ignore[attr-defined]
    buf = bytearray()
    while len(buf) <= cap:
        chunk: bytes = read1(min(_READ_CHUNK, cap + 1 - len(buf)))
        if not chunk:
            break
        buf += chunk
        if _clock.monotonic() >= deadline:
            return None
    return bytes(buf)


def fetch_url(url: str, timeout: int = 0) -> ToolOutcome:
    """Fetch *url* over HTTP(S), refusing anything off the domain allowlist.

    Refuses before ever opening a socket when the host is not allowlisted —
    same "fail before any side effect" shape `dispatch_tool` already uses for
    a half-specified call. A non-positive *timeout* falls back to
    `Home.fetch_timeout_s`, matching `run_bash`'s own
    `_int_arg(..., ctx.timeout) or ctx.timeout` pattern in `agent/tools/registry.py`.
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        return ToolOutcome(
            False, error=f"unsupported scheme {parsed.scheme!r}: only http/https are fetchable"
        )
    host = (parsed.hostname or "").lower()
    if not host:
        return ToolOutcome(False, error=f"could not parse a host out of {url!r}")

    allowed = allowed_domains()
    if host not in allowed:
        shown = ", ".join(sorted(allowed)) or "none configured"
        return ToolOutcome(
            False,
            error=(
                f"{host!r} is not on the fetch domain allowlist ({shown}); "
                "add it to FETCH_ALLOWED_DOMAINS to permit it"
            ),
            refusal="fetch_not_allowed",
        )

    effective_timeout = _effective_timeout(timeout)
    deadline = _clock.monotonic() + effective_timeout
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    opener = urllib.request.build_opener(_DomainLockedRedirectHandler(allowed))
    try:
        with opener.open(request, timeout=effective_timeout) as resp:
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            read = _read_until_deadline(resp, current_home().fetch_max_response_bytes, deadline)
            if read is None:
                return ToolOutcome(
                    False, error=f"timed out after {effective_timeout}s fetching {url}"
                )
            raw = read
    except urllib.error.HTTPError as ex:
        try:
            detail = ex.read(2000).decode("utf-8", errors="replace").strip()
        except OSError:
            detail = ""
        return ToolOutcome(False, error=f"HTTP {ex.code} from {url}: {detail[:500] or ex.reason}")
    except TimeoutError:
        return ToolOutcome(False, error=f"timed out after {effective_timeout}s fetching {url}")
    except urllib.error.URLError as ex:
        if isinstance(ex.reason, TimeoutError):
            return ToolOutcome(False, error=f"timed out after {effective_timeout}s fetching {url}")
        return ToolOutcome(False, error=f"cannot reach {url}: {ex.reason}")
    except OSError as ex:
        return ToolOutcome(False, error=f"cannot reach {url}: {ex}")

    truncated = len(raw) > current_home().fetch_max_response_bytes
    body = raw[: current_home().fetch_max_response_bytes]
    text = body.decode("utf-8", errors="replace")
    if truncated:
        text += (
            f"\n\n[truncated: response exceeded {current_home().fetch_max_response_bytes} bytes]"
        )
    header = f"HTTP {status} {content_type}".rstrip()
    return text_outcome(f"{header}\n\n{text}" if content_type else text)
