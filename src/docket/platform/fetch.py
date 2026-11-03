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
import os
import selectors
import signal
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from docket.kernel import clock as _clock
from docket.kernel import ids as _ids
from docket.kernel.errors import Refused, Unavailable
from docket.kernel.home import current_home
from docket.kernel.ports import jail as _jail
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
_TEXT_TYPES = frozenset(
    {"application/json", "application/xml", "application/javascript", "application/ecmascript"}
)
_FIX = "list the exact host in the pod's fetchDomains to permit it"

_DROPPED = frozenset({"script", "style", "noscript", "svg"})
_PARAGRAPHS = frozenset(
    {"p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "ul", "ol", "blockquote", "table", "hr"}
)
_LINES = frozenset(
    {
        "div", "section", "article", "header", "footer", "nav", "main", "aside", "li", "tr",
        "br", "dl", "dt", "dd", "form", "fieldset", "figure", "figcaption", "address", "details",
        "summary", "title",
    }
)  # fmt: skip
_VERBATIM = frozenset({"pre", "code"})
_CELLS = frozenset({"td", "th"})
_HEADING_MARK = {"h1": "# ", "h2": "## ", "h3": "### "}


class _TextExtractor(HTMLParser):
    """Collects a page's readable text; the rules are security-gates.spec.md's `fetch` bullet."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._lines: list[str] = []
        self._cur: list[str] = []
        self._raw = False
        self._fresh = True
        self._dropped = 0
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

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _DROPPED:
            self._dropped += 1
        if self._dropped:
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
        if tag in _DROPPED:
            self._dropped = max(0, self._dropped - 1)
            return
        if self._dropped:
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
        if self._dropped:
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

    def text(self) -> str:
        self._flush()
        return "\n".join(self._lines).strip("\n")


def _looks_like_html(content_type: str, body: str) -> bool:
    head = body.lstrip()[:15].lower()
    return (
        "text/html" in content_type.lower()
        or head.startswith("<!doctype html")
        or head.startswith("<html")
    )


def _html_to_text(html: str) -> str:
    """Plain text of an HTML page: what a reader sees, without markup, scripts or styles."""
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    return extractor.text()


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
    A PDF comes back as a :class:`FetchedPdf` (the bytes, up to ``FETCH_MAX_DOCUMENT_BYTES``).

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
            # A PDF, and a body with no type that may be one, is read as far as a PDF may go.
            wide = media == _PDF_TYPE or not media
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
    truncated = len(raw) > response_cap
    body = raw[:response_cap]
    text = body.decode("utf-8", errors="replace")
    header = f"HTTP {status} {content_type}".rstrip()
    converted = _looks_like_html(content_type, text)
    if converted:
        text = _html_to_text(text)
        header = f"{header}; {len(text)} chars of text"
    if truncated:
        text += f"\n\n[truncated: response exceeded {response_cap} bytes]"
    return text_outcome(f"{header}\n\n{text}" if content_type or converted else text)


@dataclass(frozen=True)
class JailedRun:
    """One extractor run: *command* in *root*, the jail's only root, under *backend* with the
    network off. *env* is the whole environment it gets; *seconds* and *max_output* bound it."""

    backend: str
    root: Path
    command: tuple[str, ...]
    env: dict[str, str]
    read_only: tuple[Path, ...]
    seconds: float
    max_output: int
    network: bool = False


@dataclass(frozen=True)
class Ran:
    """What a run left: its exit status (None when killed at the deadline), what it wrote."""

    returncode: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    cut: bool = False


_STDERR_BYTES = 4096


def _jailed_argv(run: JailedRun) -> tuple[list[str], str]:
    """The jail's argv for *run* and the docker container's name ("" otherwise). Fails closed:
    a backend that is not a jail yields no argv, so nothing is started."""
    roots, command = (run.root,), list(run.command)
    if run.backend == "landlock":
        return _jail.landlock_command_argv(roots, command, run.network, run.read_only), ""
    if run.backend == "seatbelt":
        return _jail.seatbelt_command_argv(roots, command, run.network, run.read_only), ""
    if run.backend == "docker":
        name = _ids.new_short_id("docket-pdf")
        argv = _jail.docker_command_argv(name, roots, command, run.env, run.network, run.read_only)
        return argv, name
    raise Unavailable(f"no sandbox backend to run under: {run.backend!r}")


def _leader_exited(proc: subprocess.Popen[bytes], deadline: float) -> bool:
    """Wait for the group leader to exit without reaping it, so its process group id cannot be
    recycled before the group is killed. False when the deadline passes first."""
    while True:
        try:
            if os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None:
                return True
        except (AttributeError, ChildProcessError):
            return proc.poll() is not None
        if _clock.monotonic() >= deadline:
            return False
        time.sleep(0.02)


def run_jailed(run: JailedRun) -> Ran:
    """Run *run* in its jail, in a process group of its own that is killed at the deadline, when
    its output passes *max_output* and after the leader exits. Raises, never runs unjailed."""
    argv, container = _jailed_argv(run)
    deadline = _clock.monotonic() + run.seconds
    proc = subprocess.Popen(
        argv,
        cwd=run.root,
        env=run.env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    assert proc.stdout is not None and proc.stderr is not None
    out, err = bytearray(), bytearray()
    timed_out = cut = False
    try:
        with selectors.DefaultSelector() as sel:
            sel.register(proc.stdout, selectors.EVENT_READ, out)
            sel.register(proc.stderr, selectors.EVENT_READ, err)
            while sel.get_map() and not cut:
                left = deadline - _clock.monotonic()
                if left <= 0:
                    timed_out = True
                    break
                for key, _ in sel.select(min(left, 0.25)):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        sel.unregister(key.fileobj)
                        continue
                    buf: bytearray = key.data
                    room = (run.max_output if buf is out else _STDERR_BYTES) - len(buf)
                    buf += chunk[: max(room, 0)]
                    cut = cut or (buf is out and len(chunk) > room)
        if not (timed_out or cut) and not _leader_exited(proc, deadline):
            timed_out = True
    finally:
        # The leader is not reaped yet, so its group id is still its own: kill the whole group.
        if container:
            _jail.docker_kill(container)
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
        with contextlib.suppress(subprocess.SubprocessError, OSError):
            proc.wait(timeout=5)
        proc.stdout.close()
        proc.stderr.close()
    return Ran(None if timed_out else proc.returncode, bytes(out), bytes(err), timed_out, cut)
