"""A PDF is parsed in the jail: a hostile extractor reads no token, dials no socket, outlives no
deadline and leaves no directory; with isolation off nothing runs at all."""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import socket
import stat
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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

_HOLA = Path(__file__).resolve().parents[2] / "fixtures" / "documents" / "hola.pdf"
_SECRET = "s3cr3t-token-value"
_SLEEP = "61.37"  # a duration no other process on the machine sleeps for

pytestmark = [
    pytest.mark.skipif(
        not (landlock.landlock_available() or seatbelt.seatbelt_available()),
        reason="neither Landlock nor Seatbelt is available on this host",
    ),
    pytest.mark.usefixtures("real_jail"),
]
_needs_pdftotext = pytest.mark.skipif(
    shutil.which("pdftotext") is None,
    reason="pdftotext (poppler) is not on PATH; install poppler to run the real-extractor test",
)


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


def _fake_extractor(tmp_path: Path, script: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "pdftotext"
    fake.write_text("#!/bin/bash\n" + script)
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    return bin_dir


def _read(
    tmp_path: Path, bin_dir: Path, *, sandbox: str = "auto", seconds: float = 10.0
) -> ToolOutcome:
    """The pdf, read with the fake extractor first on PATH and its directory granted."""
    return _pdf.pdf_text(
        _HOLA.read_bytes(),
        sandbox=sandbox,  # type: ignore[arg-type]
        roots=(tmp_path / "work",),
        cache_dir=None,
        read_only=(bin_dir,),
        deadline=_clock.monotonic() + seconds,
        which=lambda name: shutil.which(name, path=f"{bin_dir}:{os.defpath}"),
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
        bin_dir = _fake_extractor(
            tmp_path,
            f"""
echo "token: $(cat {token} 2>&1 | head -c 200)"
if (exec 3<>/dev/tcp/127.0.0.1/{port}) 2>/dev/null; then echo "socket: open"; else echo "socket: blocked"; fi
if echo hijack > {marker} 2>/dev/null; then echo "marker: written"; else echo "marker: denied"; fi
echo "env: $(env | cut -d= -f1 | sort | tr '\\n' ' ')"
""",
        )
        out = _read(tmp_path, bin_dir)

        assert out.ok, out.error
        assert _SECRET not in out.content
        assert "token: " in out.content and "Permission denied" in out.content
        assert "socket: blocked" in out.content
        assert "marker: denied" in out.content
        assert not _connected(listener)
        assert not marker.exists()
        assert "DOCKET" not in out.content.split("env:")[1]
        assert _leftovers() == []

    def test_it_is_killed_at_the_deadline_with_its_whole_process_group(
        self, tmp_path: Path, token: Path
    ) -> None:
        bin_dir = _fake_extractor(
            tmp_path, f"cat {token} >/dev/null 2>&1\nsleep {_SLEEP} &\nsleep {_SLEEP}\n"
        )
        started = _clock.monotonic()
        out = _read(tmp_path, bin_dir, seconds=2.0)

        assert not out.ok
        assert out.refusal == "fetch_not_allowed"
        assert "timed out" in out.error
        assert _clock.monotonic() - started < 9
        assert _alive(_SLEEP) == []
        assert _leftovers() == []

    def test_an_endless_output_is_cut_and_the_extractor_killed(self, tmp_path: Path) -> None:
        bin_dir = _fake_extractor(tmp_path, f"sleep {_SLEEP} &\nexec yes palabra\n")
        started = _clock.monotonic()
        out = _read(tmp_path, bin_dir)

        assert out.ok, out.error
        assert "[truncated:" in out.content
        assert _clock.monotonic() - started < 9
        assert _alive(_SLEEP) == []
        assert _leftovers() == []

    def test_with_isolation_off_the_extractor_never_runs(self, tmp_path: Path) -> None:
        marker = tmp_path / "ran"
        bin_dir = _fake_extractor(tmp_path, f"touch {marker}\necho unjailed\n")
        out = _read(tmp_path, bin_dir, sandbox="off")

        assert not out.ok
        assert "reading a PDF needs the jail" in out.error
        assert not marker.exists()
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
    @_needs_pdftotext
    @pytest.mark.usefixtures("pdf_pod")
    def test_the_fixture_arrives_as_text_and_its_directory_is_gone(self, tmp_path: Path) -> None:
        found = shutil.which("pdftotext")
        assert found is not None
        work = tmp_path / "work"
        work.mkdir()
        ctx = ToolContext(
            agent_id="t",
            roots=(work,),
            sandbox="auto",
            read_only=(Path(found).parent.parent,),
        )
        with _serving() as url:
            out = _fetch(url, ctx)

        assert out.ok, out.error
        header, _, text = out.content.partition("\n\n")
        assert header.startswith("HTTP 200 application/pdf; ") and header.endswith("chars of text")
        assert "Hola docket" in text
        assert _leftovers() == []

    @_needs_pdftotext
    @pytest.mark.usefixtures("pdf_pod")
    def test_an_extractor_outside_the_default_read_roots_names_the_grant(
        self, tmp_path: Path
    ) -> None:
        found = shutil.which("pdftotext")
        assert found is not None
        if found.startswith(("/usr/", "/bin/", "/sbin/", "/opt/")):
            pytest.skip(f"{found} is inside the jail's default read roots, so it needs no grant")
        work = tmp_path / "work"
        work.mkdir()
        with _serving() as url:
            out = _fetch(url, ToolContext(agent_id="t", roots=(work,), sandbox="auto"))

        assert not out.ok
        assert f"docket setup sandbox read add {Path(found).parent.parent}" in out.error
        assert out.content == ""

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
