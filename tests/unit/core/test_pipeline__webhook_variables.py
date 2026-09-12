"""Webhook params bound into pipeline variables.

Two layers:

  * ``core.pipeline.resolve_variables`` — the pure resolution function (unit
    tests only, no server involved): caller-supplied values win over a
    variable's ``default``, an undeclared key passes through unchanged, and a
    ``required`` variable missing from both the caller and (by definition,
    per ``Variable._check``) the spec's own default is a single
    :class:`~docket.core.pipeline.VariableError` naming every missing name.
  * ``POST /dispatch/<project>``'s JSON body is resolved against the pod's
    effective pipeline via that same function before any run record is
    created — a well-formed payload's values land on the run record's new
    ``variables`` field (queryable via ``docket runs show``/``GET
    /runs/<id>``); a malformed body or a missing required variable is
    rejected with 400 *before* a run record is ever created.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.core import pipeline as _pipeline
from docket.core import runs as _runs
from docket.serve import _DocketHandler

_TEST_TOKEN = "test-serve-token-w4-vars"


# ── core.pipeline.resolve_variables (pure, no server) ────────────────────────


def _spec(**variables: _pipeline.Variable) -> _pipeline.PipelineSpec:
    return _pipeline.PipelineSpec(
        name="t",
        variables=variables,
        steps=[_pipeline.Step(id="lead", role="lead")],
    )


class TestResolveVariables:
    def test_no_declared_variables_passes_provided_through_unchanged(self) -> None:
        spec = _spec()
        assert _pipeline.resolve_variables(spec, {"foo": "bar"}) == {"foo": "bar"}

    def test_no_provided_values_at_all_defaults_to_empty(self) -> None:
        spec = _spec()
        assert _pipeline.resolve_variables(spec) == {}
        assert _pipeline.resolve_variables(spec, None) == {}

    def test_default_used_when_not_provided(self) -> None:
        spec = _spec(env=_pipeline.Variable(default="prod"))
        assert _pipeline.resolve_variables(spec, {}) == {"env": "prod"}

    def test_provided_value_wins_over_default(self) -> None:
        spec = _spec(env=_pipeline.Variable(default="prod"))
        assert _pipeline.resolve_variables(spec, {"env": "staging"}) == {"env": "staging"}

    def test_required_variable_provided_is_fine(self) -> None:
        spec = _spec(env=_pipeline.Variable(required=True))
        assert _pipeline.resolve_variables(spec, {"env": "staging"}) == {"env": "staging"}

    def test_required_variable_missing_raises_naming_it(self) -> None:
        spec = _spec(env=_pipeline.Variable(required=True))
        with pytest.raises(_pipeline.VariableError, match="env"):
            _pipeline.resolve_variables(spec, {})

    def test_multiple_missing_required_named_together(self) -> None:
        spec = _spec(
            env=_pipeline.Variable(required=True),
            region=_pipeline.Variable(required=True),
        )
        with pytest.raises(_pipeline.VariableError) as exc_info:
            _pipeline.resolve_variables(spec, {})
        assert "env" in str(exc_info.value)
        assert "region" in str(exc_info.value)

    def test_undeclared_key_passes_through_alongside_declared_ones(self) -> None:
        spec = _spec(env=_pipeline.Variable(default="prod"))
        result = _pipeline.resolve_variables(spec, {"extra": 42})
        assert result == {"env": "prod", "extra": 42}

    def test_explicit_null_counts_as_provided_not_missing(self) -> None:
        spec = _spec(env=_pipeline.Variable(required=True))
        assert _pipeline.resolve_variables(spec, {"env": None}) == {"env": None}


# ── POST /dispatch/<project> body -> run record's `variables` field ─────────


@pytest.fixture()
def live_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Real server on a random port. Yields (base_url, token)."""
    d = tmp_path / "approvals"
    d.mkdir()
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", d, raising=True)
    monkeypatch.setattr(_cfg, "RUNS_FILE", tmp_path / "docket-runs.json", raising=True)

    class _Handler(_DocketHandler):
        serve_token = _TEST_TOKEN

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", _TEST_TOKEN
    srv.shutdown()


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
        monkeypatch.setattr("docket.core.dispatch.dispatch_pod", lambda proj, **kw: [])

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
        monkeypatch.setattr("docket.core.dispatch.dispatch_pod", lambda proj, **kw: [])

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
            "docket.core.dispatch.dispatch_pod",
            lambda proj, **kw: dispatched.append(proj) or [],
        )

        status, body = _post_json(f"{url}/dispatch/myproject", [1, 2, 3], token)  # type: ignore[arg-type]
        assert status == 400
        assert body["ok"] is False
        assert dispatched == []

    def test_malformed_json_body_is_rejected(
        self, live_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        url, token = live_server
        status, body = _post_raw(f"{url}/dispatch/myproject", b"{not json", token)
        assert status == 400
        assert body["ok"] is False

    def test_missing_required_variable_rejected_before_any_run_is_created(
        self, live_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        url, token = live_server
        spec = _spec(env=_pipeline.Variable(required=True))
        monkeypatch.setattr("docket.core.dispatch.effective_pipeline", lambda proj, s: spec)
        dispatched: list[str] = []
        monkeypatch.setattr(
            "docket.core.dispatch.dispatch_pod",
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
        monkeypatch.setattr("docket.core.dispatch.effective_pipeline", lambda proj, s: spec)
        monkeypatch.setattr("docket.core.dispatch.dispatch_pod", lambda proj, **kw: [])

        status, body = _post_json(f"{url}/dispatch/myproject", {"env": "staging"}, token)
        assert status == 200
        rec = _runs.get_run(body["run"])
        assert rec is not None
        assert rec["variables"] == {"env": "staging"}
