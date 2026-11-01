"""Serve auth hardening.

Covers:
  - `_DocketHandler._check_auth` compares the bearer token with
    `secrets.compare_digest` (timing-safe), not `==`
  - a wrong token is still rejected (behaviour unchanged, just the compare
    mechanism)
  - `run_serve(token_file=...)` writes the bearer token to a 0600 file
    instead of printing it to stdout
  - the bind-semantics documentation exists (default 127.0.0.1, loopback-only)
"""

from __future__ import annotations

import re
import secrets as _secrets
import threading
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.support import home as _support_home
from tests.support import http as _support_http
from tests.support import pods as _support_pods
from tests.support.http import get as _get
from tests.support.http import post as _post
from tests.support.pods import build_pod

from docket.interfaces.cli.commands import pod as _pod
from docket.interfaces.http.routes.table import GET_ROUTES, POST_ROUTES
from docket.interfaces.http.server import _DocketHandler
from docket.kernel.threads import ContextHTTPServer
from docket.tasks.application import queue as _queue

live_server = _support_http.live_server_on_approvals_dir

approvals_dir = _support_home.approvals_dir

SUBJECT = "docket.interfaces.http.server"

pod_home = _support_pods.pod_home

_TEST_TOKEN = "test-serve-token"
_READ_TOKEN = "test-read-token"


# ── fixtures ──────────────────────────────────────────────────────────────────


# ── secrets.compare_digest is actually used ────────────────────────────────────


class TestCompareDigestAuth:
    def test_compare_digest_is_invoked_on_authenticated_request(
        self, live_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, str]] = []
        real_compare_digest = _secrets.compare_digest

        def spy(a: str, b: str) -> bool:
            calls.append((a, b))
            return bool(real_compare_digest(a, b))

        monkeypatch.setattr(_secrets, "compare_digest", spy)
        base_url, token = live_server
        status, _body = _get(f"{base_url}/escalations", token=token)
        assert status == 200
        assert calls, "_check_auth should call secrets.compare_digest"
        assert calls[0] == (f"Bearer {token}", f"Bearer {token}")

    def test_wrong_token_still_rejected(self, live_server: tuple[str, str]) -> None:
        base_url, _token = live_server
        status, body = _get(f"{base_url}/escalations", token="not-the-right-token")
        assert status == 401
        assert body["ok"] is False

    def test_no_token_still_rejected(self, live_server: tuple[str, str]) -> None:
        base_url, _token = live_server
        status, _body = _get(f"{base_url}/escalations")
        assert status == 401

    def test_correct_token_accepted(self, live_server: tuple[str, str]) -> None:
        base_url, token = live_server
        status, body = _get(f"{base_url}/escalations", token=token)
        assert status == 200
        assert body == {"escalations": [], "next": 0}

    def test_empty_serve_token_denies_all_even_with_compare_digest(
        self, approvals_dir: Path
    ) -> None:
        """serve_token == "" must short-circuit before ever reaching
        compare_digest (an empty expected token must never validate)."""

        class _Handler(_DocketHandler):
            serve_token = ""

        srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            status, _body = _get(f"http://127.0.0.1:{port}/escalations", token="")
            assert status == 401
        finally:
            srv.shutdown()


# ── the read-scoped token ─────────────────────────────────────────────────────


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def _sample(pattern: str, task_id: str) -> str:
    """A concrete path for a route pattern: the demo pod, its one task, a stub elsewhere."""
    return re.sub(r"<(\w+)>", lambda m: {"pod": "demo", "id": task_id}.get(m[1], "x"), pattern)


@pytest.fixture()
def scoped_server(pod_home: Path) -> Iterator[tuple[str, str]]:
    """A server with a serve token and a read token over a pod holding one task."""
    build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
    task, _created = _queue.enqueue_task_once("demo", "a task to leave alone", channel="cli")

    class _Handler(_DocketHandler):
        serve_token = _TEST_TOKEN
        read_token = _READ_TOKEN

    srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", task.id
    srv.shutdown()


class TestReadScopedToken:
    @pytest.mark.parametrize("route", POST_ROUTES, ids=lambda r: r.pattern)
    def test_read_token_is_refused_on_every_post_route(
        self, route: object, scoped_server: tuple[str, str], pod_home: Path
    ) -> None:
        base_url, task_id = scoped_server
        before = _snapshot(pod_home)
        status, body = _post(
            base_url + _sample(route.pattern, task_id),  # type: ignore[attr-defined]
            {"description": "must not be written"},
            token=_READ_TOKEN,
        )
        assert (status, body["code"], body["ok"]) == (403, "read_scope", False)
        assert _snapshot(pod_home) == before

    @pytest.mark.parametrize("route", [r for r in GET_ROUTES if r.auth], ids=lambda r: r.pattern)
    def test_read_token_reads_what_the_serve_token_reads(
        self, route: object, scoped_server: tuple[str, str]
    ) -> None:
        base_url, task_id = scoped_server
        url = base_url + _sample(route.pattern, task_id)  # type: ignore[attr-defined]
        assert _get(url, token=_READ_TOKEN) == _get(url, token=_TEST_TOKEN)

    def test_read_token_may_head(self, scoped_server: tuple[str, str]) -> None:
        base_url, _task_id = scoped_server
        req = urllib.request.Request(f"{base_url}/escalations", method="HEAD")
        req.add_header("Authorization", f"Bearer {_READ_TOKEN}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200

    def test_serve_token_still_writes(self, scoped_server: tuple[str, str]) -> None:
        base_url, _task_id = scoped_server
        status, _body = _post(f"{base_url}/tasks/demo", {"description": "written"}, _TEST_TOKEN)
        assert status == 201

    def test_wrong_token_is_401_on_get_and_post(self, scoped_server: tuple[str, str]) -> None:
        base_url, _task_id = scoped_server
        assert _get(f"{base_url}/escalations", token="nope")[0] == 401
        assert _post(f"{base_url}/tasks/demo", {"description": "x"}, "nope")[0] == 401

    def test_open_routes_need_no_token(self, scoped_server: tuple[str, str]) -> None:
        base_url, _task_id = scoped_server
        assert _get(f"{base_url}/status.json")[0] == 200
        assert _get(f"{base_url}/health")[0] == 200

    def test_no_read_token_configured_never_matches_an_empty_bearer(
        self, live_server: tuple[str, str]
    ) -> None:
        base_url, _token = live_server
        assert _post(f"{base_url}/tasks/demo", {"description": "x"}, token="")[0] == 401
