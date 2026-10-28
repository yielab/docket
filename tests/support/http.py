"""Shared http helpers and fixtures for the docket suite."""

from __future__ import annotations

import dataclasses
import json
import threading
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from docket.interfaces.http.server import _DocketHandler
from docket.kernel.home import current_home, use_home
from docket.kernel.threads import ContextHTTPServer


def get(url: str, token: str | None = None) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(url, method="GET")
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def post_raw(url: str, data: bytes, token: str | None = None) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Content-Length", str(len(data)))
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def post(
    url: str, body: dict[str, Any] | None = None, token: str | None = None
) -> tuple[int, dict[str, Any]]:
    return post_raw(url, json.dumps(body if body is not None else {}).encode(), token)


_TEST_TOKEN = "test-serve-token"


@pytest.fixture()
def live_server(pod_home: Path):  # type: ignore[no-untyped-def]
    class _Handler(_DocketHandler):
        serve_token = _TEST_TOKEN

    srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", _TEST_TOKEN
    srv.shutdown()


@pytest.fixture()
def live_server_on_approvals_dir(approvals_dir: Path):
    """Real ThreadingHTTPServer on a random port. Yields (base_url, token)."""

    class _Handler(_DocketHandler):
        serve_token = _TEST_TOKEN

    srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", _TEST_TOKEN
    srv.shutdown()


@pytest.fixture()
def live_server_in_tmp_home(tmp_path: Path):
    """Real server on a random port. Yields (base_url, token)."""
    d = tmp_path / "approvals"
    d.mkdir()
    with (
        use_home(dataclasses.replace(current_home(), approvals_dir_override=d)),
        use_home(
            dataclasses.replace(current_home(), runs_file_override=tmp_path / "docket-runs.json")
        ),
    ):

        class _Handler(_DocketHandler):
            serve_token = _TEST_TOKEN

        srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        yield f"http://127.0.0.1:{port}", _TEST_TOKEN
        srv.shutdown()


def metric_sample(lines: list[str], prefix: str) -> float:
    """The value of the one metric line that starts with *prefix*."""
    (line,) = [ln for ln in lines if ln.startswith(prefix)]
    return float(line.rsplit(" ", 1)[1])
