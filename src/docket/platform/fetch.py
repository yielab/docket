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

import contextlib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser

from docket.kernel import clock as _clock
from docket.kernel.errors import Refused
from docket.kernel.home import current_home
from docket.kernel.text import one_line
from docket.kernel.tool_outcome import ToolOutcome, text_outcome
from docket.platform.perimeter import build_opener, read_until_deadline

_USER_AGENT = "docket-fetch/1"
# A caller's per-call timeout is clamped to this multiple of FETCH_TIMEOUT_S.
FETCH_CLAMP_MULTIPLE = 4
_REFUSED = "fetch_not_allowed"
_SNIFF_BYTES = 8192
_PDF_MAGIC = b"%PDF-"
_PDF_TYPE = "application/pdf"
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_TEXT_TYPES = frozenset(
    {"application/json", "application/xml", "application/javascript", "application/ecmascript"}
)
_FIX = "list the exact host in the pod's fetchDomains to permit it"

_DROPPED = frozenset(
    {"script", "style", "noscript", "template", "svg", "nav", "header", "footer", "aside", "form"}
)
_DROPPED_ROLES = frozenset({"navigation", "banner", "contentinfo", "complementary"})
_LANDMARKS = ("main", "article")
_PARAGRAPHS = frozenset(
    {"p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "ul", "ol", "blockquote", "table", "hr"}
)
_LINES = frozenset(
    {
        "div", "section", "article", "header", "footer", "nav", "main", "aside", "li", "tr",
        "br", "dl", "dt", "dd", "form", "fieldset", "figure", "figcaption", "address", "details",
        "summary",
    }
)  # fmt: skip
_VERBATIM = frozenset({"pre", "code"})
_CELLS = frozenset({"td", "th"})
_HEADING_MARK = {"h1": "# ", "h2": "## ", "h3": "### "}


class _TextExtractor(HTMLParser):
    """Collects a page's readable text; the rules are security-gates.spec.md's `fetch` bullet."""

    def __init__(self, scope: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.landmarks = dict.fromkeys(_LANDMARKS, 0)
        self._scope = scope
        self._scope_depth = 0
        self._title: list[str] | None = None
        self._title_done = False
        self._lines: list[str] = []
        self._cur: list[str] = []
        self._raw = False
        self._fresh = True
        self._drop_tag = ""
        self._drop_depth = 0
        self._verbatim = 0
        self._skip_newline = False
        self._href = ""
        self._link_text: list[str] = []

    def _flush(self, keep_empty: bool = False) -> None:
        line = "".join(self._cur)
        self._cur, raw, self._raw, self._fresh = [], self._raw, False, True
        line = line.rstrip() if raw else line.strip()
        if line or (keep_empty and self._lines and self._lines[-1]):
            self._lines.append(line)

    def _break(self, blank: bool) -> None:
        self._flush()
        if blank and self._lines and self._lines[-1]:
            self._lines.append("")

    def _put(self, text: str) -> None:
        if self._href:
            self._link_text.append(text)
        self._cur.append(text)
        self._fresh = self._fresh and not text.strip()

    def _mark(self, marker: str) -> None:
        """A line's leading marker (`#`, `-`): the text after it is still the line's first."""
        self._cur.append(marker)

    def _within(self, tag: str, start: bool) -> bool:
        """Whether a tag lies in the kept subtree; the scope element itself adds nothing."""
        if not self._scope:
            return True
        if tag != self._scope:
            return self._scope_depth > 0
        if start:
            if not self._scope_depth:
                self._drop_tag, self._drop_depth = "", 0
            self._scope_depth += 1
            return self._scope_depth > 1
        if not self._scope_depth:
            return False
        self._scope_depth -= 1
        if not self._scope_depth:
            self._break(True)
        return self._scope_depth > 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title" and self._title is None and not self._title_done:
            self._title = []
            return
        if tag in self.landmarks:
            self.landmarks[tag] += 1
        if not self._within(tag, start=True):
            return
        if self._drop_tag:
            self._drop_depth += tag == self._drop_tag
            return
        if tag in _DROPPED or _DROPPED_ROLES.intersection(
            (dict(attrs).get("role") or "").lower().split()
        ):
            self._drop_tag, self._drop_depth = tag, 1
            return
        if tag in _PARAGRAPHS or tag in _LINES:
            self._break(tag in _PARAGRAPHS)
        if tag in _HEADING_MARK:
            self._mark(_HEADING_MARK[tag])
        elif tag == "li":
            self._mark("- ")
        elif tag in _CELLS:
            self._put(" ")
        elif tag == "a":
            self._href = dict(attrs).get("href") or ""
            self._link_text = []
        if tag in _VERBATIM:
            self._verbatim += 1
            self._skip_newline = tag == "pre"

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._title is not None and not self._title_done:
            self._title_done = True
            return
        if not self._within(tag, start=False):
            return
        if self._drop_tag:
            if tag == self._drop_tag:
                self._drop_depth -= 1
                if not self._drop_depth:
                    self._drop_tag = ""
            return
        if tag in _VERBATIM:
            self._verbatim = max(0, self._verbatim - 1)
        if tag == "a" and self._href:
            text = one_line("".join(self._link_text))
            if text and text != self._href:
                self._cur.append(f" ({self._href})")
            self._href = ""
        if tag in _PARAGRAPHS or tag in _LINES:
            self._break(tag in _PARAGRAPHS)

    def handle_data(self, data: str) -> None:
        if self._title is not None and not self._title_done:
            self._title.append(data)
            return
        if self._drop_tag or (self._scope and not self._scope_depth):
            return
        if not self._verbatim:
            data = one_line(data).join(
                (" " if data[:1].isspace() else "", " " if data[-1:].isspace() else "")
            )
            if self._fresh or "".join(self._cur).endswith(" "):
                data = data.lstrip()
            if data:
                self._put(data)
            return
        if self._skip_newline:
            self._skip_newline = False
            data = data.removeprefix("\n")
        for i, piece in enumerate(data.split("\n")):
            if i:
                self._flush(keep_empty=True)
            if piece:
                self._raw = True
                self._put(piece)

    def title(self) -> str:
        return one_line("".join(self._title or ()))

    def body(self) -> str:
        self._flush()
        return "\n".join(self._lines).strip("\n")


def _looks_like_html(content_type: str, body: str) -> bool:
    head = body.lstrip()[:15].lower()
    return (
        "text/html" in content_type.lower()
        or head.startswith("<!doctype html")
        or head.startswith("<html")
    )


def _extract(html: str, scope: str = "") -> _TextExtractor:
    extractor = _TextExtractor(scope)
    extractor.feed(html)
    extractor.close()
    return extractor


def _html_to_text(html: str) -> str:
    """Plain text of an HTML page: its title, then the one `main` or `article`, else the body."""
    page = _extract(html)
    body = page.body()
    for landmark in _LANDMARKS:
        if page.landmarks[landmark] == 1:
            body = _extract(html, landmark).body() or body
            break
    return f"{page.title()}\n\n{body}".strip() if page.title() else body


def host_allowed(host: str, allowed: Iterable[str]) -> bool:
    """Whether *host* is in *allowed*: an exact hostname, ``*.example.org`` (every subdomain at any
    depth, never the apex), or ``*`` (any host). The one matcher the call and the redirect guard
    share."""
    host = host.lower()
    for entry in allowed:
        entry = entry.lower()
        if entry == "*" or entry == host:
            return True
        if entry.startswith("*.") and host.endswith(entry[1:]) and len(host) > len(entry) - 1:
            return True
    return False


def _effective_timeout(timeout: int) -> float:
    """The caller's timeout bounded by the clamp; non-positive falls back to the default."""
    if timeout > 0:
        return min(timeout, FETCH_CLAMP_MULTIPLE * current_home().fetch_timeout_s)
    return current_home().fetch_timeout_s


def _exact_hosts(allowed: Iterable[str]) -> frozenset[str]:
    """The entries written as one host name: the only hosts whose private addresses are reachable."""
    return frozenset(e.lower() for e in allowed if not e.startswith("*"))


def _media(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def _declared_non_text(content_type: str) -> str | None:
    """Why a declared content type is not text, or None when it is (or none is declared)."""
    media = _media(content_type)
    if not media or media.startswith("text/") or media in _TEXT_TYPES:
        return None
    return None if media.endswith(("+json", "+xml")) else f"content type {media!r} is not text"


def _refused_type(why: str) -> ToolOutcome:
    return ToolOutcome(False, error=f"{why}; fetch reads text pages", refusal=_REFUSED)


@dataclass(frozen=True)
class FetchedPdf:
    """A PDF body, untouched, beside the response it came from. ``fetch_url`` never reads one as
    text: its caller hands the bytes to the jail. *deadline* is the call's, in monotonic seconds."""

    status: int
    content_type: str
    body: bytes
    deadline: float


def fetch_url(url: str, allowed: Iterable[str], timeout: int = 0) -> ToolOutcome | FetchedPdf:
    """Fetch *url* over HTTP(S), refusing anything outside *allowed* (``host_allowed`` entries).
    A PDF comes back as a :class:`FetchedPdf` (the bytes, up to ``FETCH_MAX_DOCUMENT_BYTES``). An
    HTML page is read up to the same bound and its text is cut at ``FETCH_MAX_RESPONSE_BYTES``.

    Refuses before ever opening a socket when the host is not allowed —
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

    allowed = tuple(allowed)
    if not host_allowed(host, allowed):
        shown = ", ".join(sorted(allowed)) or "none configured"
        return ToolOutcome(
            False,
            error=(
                f"{host!r} is not on the fetch domain allowlist ({shown}); add it to "
                "FETCH_ALLOWED_DOMAINS, or to the pod's fetchDomains, to permit it"
            ),
            refusal="fetch_not_allowed",
        )

    response_cap = current_home().fetch_max_response_bytes
    effective_timeout = _effective_timeout(timeout)
    deadline = _clock.monotonic() + effective_timeout
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    opener = build_opener(
        lambda name: host_allowed(name, allowed),
        _exact_hosts(allowed),
        outside="not on the fetch domain allowlist",
        fix=_FIX,
    )
    try:
        with opener.open(request, timeout=effective_timeout) as resp:
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            media = _media(content_type)
            if media != _PDF_TYPE and (why := _declared_non_text(content_type)):
                return _refused_type(why)
            # A PDF, an HTML page and a body with no type (which may be either) are read as far as
            # a document may go: the page is converted, and the text is what the response cap cuts.
            wide = media == _PDF_TYPE or media in _HTML_TYPES or not media
            cap = current_home().fetch_max_document_bytes if wide else response_cap
            read = read_until_deadline(resp, cap, deadline)
            if read is None:
                return ToolOutcome(
                    False, error=f"timed out after {effective_timeout}s fetching {url}"
                )
            raw = read
    except Refused as ex:
        return ToolOutcome(False, error=str(ex), refusal=_REFUSED)
    except urllib.error.HTTPError as ex:
        detail = ""
        if not _declared_non_text(ex.headers.get("Content-Type", "") if ex.headers else ""):
            with contextlib.suppress(OSError):
                detail = ex.read(2000).decode("utf-8", errors="replace").strip()
        return ToolOutcome(False, error=f"HTTP {ex.code} from {url}: {detail[:500] or ex.reason}")
    except TimeoutError:
        return ToolOutcome(False, error=f"timed out after {effective_timeout}s fetching {url}")
    except urllib.error.URLError as ex:
        if isinstance(ex.reason, TimeoutError):
            return ToolOutcome(False, error=f"timed out after {effective_timeout}s fetching {url}")
        return ToolOutcome(False, error=f"cannot reach {url}: {ex.reason}")
    except OSError as ex:
        return ToolOutcome(False, error=f"cannot reach {url}: {ex}")

    if media == _PDF_TYPE or (not media and raw.startswith(_PDF_MAGIC)):
        limit = current_home().fetch_max_document_bytes
        if len(raw) > limit:
            return ToolOutcome(
                False,
                error=(
                    f"the PDF is larger than FETCH_MAX_DOCUMENT_BYTES ({limit} bytes); "
                    "raise that setting to read it"
                ),
                refusal=_REFUSED,
            )
        return FetchedPdf(status, content_type, raw, deadline)
    if not content_type.strip() and b"\x00" in raw[:_SNIFF_BYTES]:
        return _refused_type("the body has no content type and holds binary data")
    as_html = media in _HTML_TYPES or _looks_like_html(
        content_type, raw[:_SNIFF_BYTES].decode("utf-8", errors="replace")
    )
    byte_cap = current_home().fetch_max_document_bytes if as_html and wide else response_cap
    text = raw[:byte_cap].decode("utf-8", errors="replace")
    notes = [f"response exceeded {byte_cap} bytes"] if len(raw) > byte_cap else []
    header = f"HTTP {status} {content_type}".rstrip()
    if as_html:
        text = _html_to_text(text)
        if len(text) > response_cap:
            text = text[:response_cap]
            notes.append(f"text exceeded {response_cap} characters")
        header = f"{header}; {len(text)} chars of text"
    for note in notes:
        text += f"\n\n[truncated: {note}]"
    return text_outcome(f"{header}\n\n{text}" if content_type or as_html else text)
