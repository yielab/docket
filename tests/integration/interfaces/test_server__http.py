"""The HTTP server answering over a real loopback socket."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from threading import Thread

from tests.support import home as _support_home

from docket.interfaces.http.server import _DocketHandler

SUBJECT = "docket.interfaces.http.server"


fake_home = _support_home.fake_home


class TestHttpServer:
    def test_endpoints_over_socket(self, fake_home: Path) -> None:
        from docket.kernel.threads import ContextHTTPServer

        server = ContextHTTPServer(("127.0.0.1", 0), _DocketHandler)
        port = server.server_address[1]
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{port}"
            with urllib.request.urlopen(base + "/health", timeout=5) as r:
                assert json.loads(r.read().decode())["status"] == "ok"
            with urllib.request.urlopen(base + "/status.json", timeout=5) as r:
                status = json.loads(r.read().decode())
                assert status["agents"][0]["id"] == "myshop"
            with urllib.request.urlopen(base + "/metrics", timeout=5) as r:
                metrics = r.read().decode()
                assert metrics.startswith("# HELP docket_agents_total")
                assert metrics.endswith("\n")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
