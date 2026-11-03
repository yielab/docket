"""A PDF is parsed in the jail by docket's own interpreter: no external program is needed, a hostile
extractor reads no token, dials no socket, outlives no deadline and leaves no directory, a memory
bomb is refused; with isolation off nothing runs at all."""

from __future__ import annotations

import dataclasses
import json
import os
import socket
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from unittest import mock

import pytest

from docket.agent.ports import ToolCall
from docket.agent.tools.registry import ToolContext, ToolResult, dispatch_tool
from docket.hops.application import pdf_text as _pdf
from docket.hops.application.builtin_tools import builtin_registry
from docket.kernel import clock as _clock
from docket.kernel.home import current_home, use_home
from docket.kernel.tool_outcome import ToolOutcome
from docket.sandbox import landlock, seatbelt

SUBJECT = "docket.hops.application.pdf_text"

_DOCS = Path(__file__).resolve().parents[2] / "fixtures" / "documents"
_HOLA = _DOCS / "hola.pdf"
_BOMB = _DOCS / "bomb.pdf"
_SECRET = "s3cr3t-token-value"
_EXTRACTOR_ARGV = "extract.py\x00in.pdf"  # the extractor's own argv, NUL-joined as /proc shows it
_SLEEP = "61.37"  # a duration no other process on the machine sleeps for

pytestmark = [
    pytest.mark.skipif(
        not (landlock.landlock_available() or seatbelt.seatbelt_available()),
        reason="neither Landlock nor Seatbelt is available on this host",
    ),
    pytest.mark.usefixtures("real_jail"),
]


@pytest.fixture
def real_jail(bind_launcher: Callable[..., object]) -> None:
    bind_launcher()


@pytest.fixture
def token(tmp_path: Path) -> Path:
    path = tmp_path / "home-like" / "token"
    path.parent.mkdir()
    path.write_text(_SECRET)
    return path


@pytest.fixture
def listener() -> Iterator[socket.socket]:
    """A loopback socket that is listening: a connect to it succeeds, queued or not."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(4)
    sock.setblocking(False)
    yield sock
    sock.close()


def _connected(sock: socket.socket) -> bool:
    try:
        sock.accept()
    except BlockingIOError:
        return False
    return True


@contextmanager
def _hostile_workdir(
    body: bytes, roots: tuple[Path, ...], cache_dir: Path | None, *, script: str
) -> Iterator[Path]:
    """The real workdir, with the extractor module replaced by *script*: the module seam."""
    with _pdf.fresh_workdir(body, roots, cache_dir) as root:
        (root / "extract.py").write_text(script)
        yield root


def _read(
    tmp_path: Path,
    *,
    script: str | None = None,
    body: bytes | None = None,
    sandbox: str = "auto",
    seconds: float = 10.0,
) -> ToolOutcome:
    """The pdf, read with no grant; *script* stands in for the extractor module when given."""
    workdir = _pdf.fresh_workdir
    if script is not None:
        workdir = lambda b, r, c: _hostile_workdir(b, r, c, script=script)  # noqa: E731
    return _pdf.pdf_text(
        _HOLA.read_bytes() if body is None else body,
        sandbox=sandbox,  # type: ignore[arg-type]
        roots=(tmp_path / "work",),
        cache_dir=None,
        read_only=(),
        deadline=_clock.monotonic() + seconds,
        workdir=workdir,
    )


def _leftovers() -> list[Path]:
    base = current_home().jail_tmp_dir
    return [p for d in base.iterdir() for p in d.iterdir()] if base.is_dir() else []


def _alive(marker: str) -> list[int]:
    found = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                cmdline = (entry / "cmdline").read_bytes()
            except OSError:
                continue
            if marker.encode() in cmdline:
                found.append(int(entry.name))
    return found


class TestAHostileExtractorIsContained:
    def test_it_reads_no_token_dials_no_socket_and_writes_outside_its_root_nowhere(
        self, tmp_path: Path, token: Path, listener: socket.socket
    ) -> None:
        marker = tmp_path / "marker"
        port = listener.getsockname()[1]
        out = _read(
            tmp_path,
            script=f"""
import os, socket
try:
    print("token:", open({str(token)!r}).read())
except OSError as ex:
    print("token:", ex.strerror)
try:
    socket.create_connection(("127.0.0.1", {port}), timeout=2).close()
    print("socket: open")
except OSError:
    print("socket: blocked")
try:
    open({str(marker)!r}, "w").write("hijack")
    print("marker: written")
except OSError:
    print("marker: denied")
print("env:", " ".join(sorted(os.environ)))
""",
        )

        assert out.ok, out.error
        assert _SECRET not in out.content
        assert "token: Permission denied" in out.content
        assert "socket: blocked" in out.content
        assert "marker: denied" in out.content
        assert not _connected(listener)
        assert not marker.exists()
        assert "DOCKET" not in out.content.split("env:")[1]
        assert _leftovers() == []

    def test_it_is_killed_at_the_deadline_with_its_whole_process_group(
        self, tmp_path: Path
    ) -> None:
        started = _clock.monotonic()
        out = _read(
            tmp_path,
            script=(
                f"import subprocess, time\nsubprocess.Popen(['sleep', '{_SLEEP}'])\n"
                f"time.sleep({_SLEEP})\n"
            ),
            seconds=2.0,
        )

        assert not out.ok
        assert out.refusal == "fetch_not_allowed"
        assert "timed out" in out.error
        assert _clock.monotonic() - started < 9
        assert _alive(_SLEEP) == []
        assert _leftovers() == []

    def test_an_endless_output_is_cut_and_the_extractor_killed(self, tmp_path: Path) -> None:
        started = _clock.monotonic()
        out = _read(
            tmp_path,
            script=(
                "import subprocess, sys\n"
                f"subprocess.Popen(['sleep', '{_SLEEP}'])\n"
                "while True:\n    sys.stdout.write('palabra ' * 1000)\n"
            ),
        )

        assert out.ok, out.error
        assert "[truncated:" in out.content
        assert _clock.monotonic() - started < 9
        assert _alive(_SLEEP) == []
        assert _leftovers() == []

    def test_with_isolation_off_the_extractor_never_runs(self, tmp_path: Path) -> None:
        marker = tmp_path / "ran"
        out = _read(tmp_path, script=f"open({str(marker)!r}, 'w')\n", sandbox="off")

        assert not out.ok
        assert "reading a PDF needs the jail" in out.error
        assert not marker.exists()
        assert _leftovers() == []


class TestTheRealExtractor:
    def test_the_fixture_is_read_with_no_external_program_and_no_read_grant(
        self, tmp_path: Path
    ) -> None:
        with mock.patch.dict(os.environ, {"PATH": str(tmp_path / "nowhere")}):
            out = _read(tmp_path)

        assert out.ok, out.error
        assert out.content.strip() == "Hola docket"
        assert _leftovers() == []

    def test_a_pdf_that_inflates_past_the_memory_limit_is_refused_and_nothing_is_left(
        self, tmp_path: Path
    ) -> None:
        # pypdf decodes about 30 MB/s, so filling the real 1 GiB takes the whole deadline; the
        # same module with a smaller limit shows the limit, not the clock, ending the run.
        source = resources.files("docket.sandbox").joinpath("pdf_extract.py").read_text()
        small = source.replace("MEMORY_BYTES = 1 << 30", "MEMORY_BYTES = 192 << 20")
        assert small != source
        assert _BOMB.stat().st_size < 100_000
        started = _clock.monotonic()
        out = _read(tmp_path, script=small, body=_BOMB.read_bytes(), seconds=30.0)

        assert not out.ok
        assert out.refusal == "fetch_not_allowed"
        assert "memory" in out.error
        assert out.content == ""
        assert _clock.monotonic() - started < 9
        assert _alive(_EXTRACTOR_ARGV) == []
        assert _leftovers() == []

    def test_bytes_that_are_not_a_pdf_are_refused_with_the_readers_first_line(
        self, tmp_path: Path
    ) -> None:
        out = _read(tmp_path, body=b"%PDF-1.4\nnot really\n")

        assert not out.ok
        assert out.error.startswith("the PDF reader exited 1: ")
        assert _leftovers() == []


class _Pdfs(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:  # BaseHTTPRequestHandler's own naming convention
        body = _HOLA.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextmanager
def _serving() -> Iterator[str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Pdfs)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/hola.pdf"
    finally:
        srv.shutdown()
        thread.join(timeout=5)


def _fetch(url: str, ctx: ToolContext) -> ToolResult:
    call = ToolCall(id="c1", name="fetch", arguments=json.dumps({"url": url}))
    return dispatch_tool(call, ctx, builtin_registry())


@pytest.fixture
def pdf_pod() -> Iterator[None]:
    with use_home(dataclasses.replace(current_home(), fetch_allowed_domains=("127.0.0.1",))):
        yield


class TestTheFetchToolReadsAPdf:
    @pytest.mark.usefixtures("pdf_pod")
    def test_the_fixture_arrives_as_text_and_its_directory_is_gone(self, tmp_path: Path) -> None:
        work = tmp_path / "work"
        work.mkdir()
        ctx = ToolContext(agent_id="t", roots=(work,), sandbox="auto")
        with _serving() as url:
            out = _fetch(url, ctx)

        assert out.ok, out.error
        header, _, text = out.content.partition("\n\n")
        assert header.startswith("HTTP 200 application/pdf; ") and header.endswith("chars of text")
        assert "Hola docket" in text
        assert _leftovers() == []

    @pytest.mark.usefixtures("pdf_pod")
    def test_with_isolation_off_the_pdf_is_refused_and_no_text_arrives(
        self, tmp_path: Path
    ) -> None:
        ctx = ToolContext(agent_id="t", roots=(tmp_path,), sandbox="off")
        with _serving() as url:
            out = _fetch(url, ctx)

        assert not out.ok
        assert "reading a PDF needs the jail" in out.error
        assert out.content == ""
