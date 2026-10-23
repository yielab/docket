"""``kernel.threads`` -- a thread docket starts sees the home it was started under, a bare
``threading.Thread`` does not, and a request to a server is handled under the server's home."""

from __future__ import annotations

import json
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

from docket.kernel.home import Home, current_home, reset_default, use_home
from docket.kernel.threads import ContextHTTPServer, new_thread, start_thread, submit

SUBJECT = "docket.kernel.threads"


@pytest.fixture(autouse=True)
def _fresh_default() -> None:
    reset_default()
    yield  # type: ignore[misc]
    reset_default()


def _root_seen_by(starter: object, home: Home) -> Path:
    seen: list[Path] = []

    def work() -> None:
        seen.append(current_home().root)

    with use_home(home):
        t = starter(work)  # type: ignore[operator]
    t.join(5)
    return seen[0]


def test_a_bare_thread_falls_back_to_the_default_home(tmp_path: Path) -> None:
    root = _root_seen_by(
        lambda fn: _started(threading.Thread(target=fn, daemon=True)), Home(root=tmp_path / "a")
    )
    assert root != tmp_path / "a"


def _started(t: threading.Thread) -> threading.Thread:
    t.start()
    return t


def test_start_thread_sees_the_home_it_was_started_under(tmp_path: Path) -> None:
    assert _root_seen_by(start_thread, Home(root=tmp_path / "a")) == tmp_path / "a"


def test_new_thread_copies_the_context_when_built_not_when_started(tmp_path: Path) -> None:
    seen: list[Path] = []
    with use_home(Home(root=tmp_path / "a")):
        t = new_thread(lambda: seen.append(current_home().root))
    t.start()
    t.join(5)
    assert seen == [tmp_path / "a"]


def test_submit_runs_the_callable_in_the_context_at_the_call(tmp_path: Path) -> None:
    with ThreadPoolExecutor(max_workers=1) as pool, use_home(Home(root=tmp_path / "a")):
        root = submit(pool, lambda: current_home().root).result(5)
    assert root == tmp_path / "a"


def test_two_homes_do_not_leak_into_each_other_across_threads(tmp_path: Path) -> None:
    a = _root_seen_by(start_thread, Home(root=tmp_path / "a"))
    b = _root_seen_by(start_thread, Home(root=tmp_path / "b"))
    assert (a, b) == (tmp_path / "a", tmp_path / "b")


class _Echo(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = json.dumps({"root": str(current_home().root)}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


def test_a_request_is_handled_under_the_home_the_server_was_built_in(tmp_path: Path) -> None:
    with use_home(Home(root=tmp_path / "a")):
        srv = ContextHTTPServer(("127.0.0.1", 0), _Echo)
    serving = threading.Thread(target=srv.serve_forever, daemon=True)
    serving.start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/"
        for _ in range(2):
            with urllib.request.urlopen(url, timeout=5) as resp:
                assert json.load(resp) == {"root": str(tmp_path / "a")}
        with use_home(Home(root=tmp_path / "other")), urllib.request.urlopen(url, timeout=5) as r:
            assert json.load(r) == {"root": str(tmp_path / "a")}
    finally:
        srv.shutdown()
        srv.server_close()
