"""GET /pods and GET /pods/<p> say when a pod is paused and why, and stop when it resumes."""

from __future__ import annotations

import pytest
from tests.support import http as _support_http
from tests.support import pods as _support_pods
from tests.support.http import get as _get
from typer.testing import CliRunner

from docket.hops.gates import pre_hop as _pre_hop
from docket.interfaces.cli.app import app as _app
from docket.interfaces.cli.commands import run as _run
from docket.interfaces.cli.commands import setup as _setup
from docket.teams import pod_provisioning as _pp

live_server = _support_http.live_server

pod_home = _support_pods.pod_home

SUBJECT = "docket.hops.application.report"

runner = CliRunner()


def _answers(url: str, token: str, pod: str) -> tuple[dict[str, object], dict[str, object]]:
    """The pod's `GET /pods` row and its `GET /pods/<p>` object."""
    status, listing = _get(f"{url}/pods", token)
    assert status == 200
    row = next(p for p in listing["pods"] if p["name"] == pod)
    status, detail = _get(f"{url}/pods/{pod}", token)
    assert status == 200
    return row, detail


def test_a_budget_pause_shows_on_both_routes_until_resume_clears_it(
    live_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The budget pause is served with its reason, and `run --resume` takes both fields away."""
    url, token = live_server
    _pp.provision_pod("demo", "build", location="/src/demo")

    row, detail = _answers(url, token, "demo")
    assert row["paused"] is False
    assert detail["paused"] is False
    assert "pausedReason" not in row
    assert "pausedReason" not in detail

    _pre_hop._pause_lead_for_budget("demo")

    row, detail = _answers(url, token, "demo")
    for answer in (row, detail):
        assert answer["paused"] is True
        assert answer["pausedReason"] == "budget"

    piece = _setup.Piece("model endpoint", True, "", "docket setup")
    monkeypatch.setattr(_run, "readiness", lambda: _setup.Readiness(endpoint=piece))
    result = runner.invoke(_app, ["run", "--pod", "demo", "--resume"])
    assert result.exit_code == 0, result.output

    row, detail = _answers(url, token, "demo")
    for answer in (row, detail):
        assert answer["paused"] is False
        assert "pausedReason" not in answer
