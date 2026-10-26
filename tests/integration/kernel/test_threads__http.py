"""A request handled by a real loopback server runs under the home the server was built in."""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from tests.support import home as _support_home

from docket.kernel.home import Home, current_home, use_home
from docket.kernel.threads import ContextHTTPServer

SUBJECT = "docket.kernel.threads"

_fresh_default = _support_home.fresh_default


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
