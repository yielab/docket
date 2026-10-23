"""Webhook params bound into pipeline variables.

See specs/data/serve-read-api.spec.md for the ``variables`` field contract.
Two layers: ``pipeline.domain.spec.resolve_variables`` (pure resolution: caller
values win over a variable's ``default``, an undeclared key passes through,
a missing ``required`` variable raises :class:`~docket.pipeline.domain.spec.
VariableError` naming every missing name), and ``POST /dispatch/<project>``,
whose JSON body is resolved against the pod's effective pipeline via that
function before any run record is created -- a malformed body or missing
required variable is rejected 400 before the run record exists.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

import pytest
from tests.support import http as _support_http
from tests.support.pods import spec_2 as _spec

from docket.pipeline.domain import spec as _pipeline
from docket.tasks.application import runs as _runs

live_server = _support_http.live_server_3

SUBJECT = "docket.tasks.application.runs"

_TEST_TOKEN = "test-serve-token"


# ── pipeline.domain.spec.resolve_variables (pure, no server) ────────────────────────


# ── POST /dispatch/<project> body -> run record's `variables` field ─────────


def _post_json(url: str, body: dict[str, Any], token: str) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Content-Length", str(len(data)))
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _post_raw(url: str, raw: bytes, token: str) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(url, data=raw, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Content-Length", str(len(raw)))
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


class TestWebhookVariableBinding:
    def test_params_reach_the_run_records_variables_field(
        self, live_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        url, token = live_server
        monkeypatch.setattr("docket.tasks.application.sweep.dispatch_pod", lambda proj, **kw: [])

        status, body = _post_json(
            f"{url}/dispatch/myproject", {"env": "staging", "count": 3}, token
        )
        assert status == 200
        run_id = body["run"]

        rec = _runs.get_run(run_id)
        assert rec is not None
        assert rec["variables"] == {"env": "staging", "count": 3}

    def test_empty_body_is_still_the_pre_w4_no_params_behavior(
        self, live_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        url, token = live_server
        monkeypatch.setattr("docket.tasks.application.sweep.dispatch_pod", lambda proj, **kw: [])

        status, body = _post_json(f"{url}/dispatch/myproject", {}, token)
        assert status == 200
        rec = _runs.get_run(body["run"])
        assert rec is not None
        assert rec["variables"] == {}

    def test_non_object_body_is_rejected(
        self, live_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        url, token = live_server
        dispatched: list[str] = []
        monkeypatch.setattr(
            "docket.tasks.application.sweep.dispatch_pod",
            lambda proj, **kw: dispatched.append(proj) or [],
        )

        status, body = _post_json(f"{url}/dispatch/myproject", [1, 2, 3], token)  # type: ignore[arg-type]
        assert status == 400
        assert body["ok"] is False
        assert dispatched == []

    def test_malformed_json_body_is_rejected(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post_raw(f"{url}/dispatch/myproject", b"{not json", token)
        assert status == 400
        assert body["ok"] is False

    def test_missing_required_variable_rejected_before_any_run_is_created(
        self, live_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        url, token = live_server
        spec = _spec(env=_pipeline.Variable(required=True))
        monkeypatch.setattr(
            "docket.pipeline.application.steps.effective_pipeline", lambda proj, s: spec
        )
        dispatched: list[str] = []
        monkeypatch.setattr(
            "docket.tasks.application.sweep.dispatch_pod",
            lambda proj, **kw: dispatched.append(proj) or [],
        )

        before = len(_runs.list_runs())
        status, body = _post_json(f"{url}/dispatch/myproject", {}, token)
        assert status == 400
        assert "env" in body["error"]
        assert dispatched == []
        assert len(_runs.list_runs()) == before

    def test_required_variable_satisfied_by_payload_is_accepted(
        self, live_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        url, token = live_server
        spec = _spec(env=_pipeline.Variable(required=True))
        monkeypatch.setattr(
            "docket.pipeline.application.steps.effective_pipeline", lambda proj, s: spec
        )
        monkeypatch.setattr("docket.tasks.application.sweep.dispatch_pod", lambda proj, **kw: [])

        status, body = _post_json(f"{url}/dispatch/myproject", {"env": "staging"}, token)
        assert status == 200
        rec = _runs.get_run(body["run"])
        assert rec is not None
        assert rec["variables"] == {"env": "staging"}
