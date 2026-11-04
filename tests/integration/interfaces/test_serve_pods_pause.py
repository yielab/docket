"""GET /pods and GET /pods/<p> say when a pod is paused, why and its budget; POST resume clears it."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from tests.support import http as _support_http
from tests.support import pods as _support_pods
from tests.support.http import get as _get
from tests.support.http import post as _post
from tests.support.pods import spend_tokens
from tests.support.trace import audit_entries
from typer.testing import CliRunner

from docket.agent import ports as _rd
from docket.hops.application import sweep as _sweep
from docket.hops.gates import pre_hop as _pre_hop
from docket.interfaces.cli.app import app as _app
from docket.interfaces.cli.commands import run as _run
from docket.interfaces.cli.commands import setup as _setup
from docket.kernel import clock as _clock
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.teams import fleet as _fleet
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


def _today() -> str:
    return _clock.now().strftime("%Y-%m-%d")


def _refuse_every_turn(*_args: object, **_kwargs: object) -> _rd.TurnResult:
    raise AssertionError("a gated pod runs no turn")


def test_post_resume_clears_a_gate_pause_requeues_the_task_and_audits_the_channel(
    live_server: tuple[str, str],
) -> None:
    """The gate pauses the pod at its cap; the route lifts it once and a second post is a no-op."""
    url, token = live_server
    _pp.provision_pod("demo", "build", location="/src/demo")
    _fleet.meta_set("demo-lead", "budgetTokens", 100)
    spend_tokens("demo-lead", {_today(): 150})
    _queue.enqueue_task_once("demo", "held by the cap", channel="cli")
    assert _sweep.dispatch_pod("demo", runner=_refuse_every_turn)[0].status == "blocked"

    row, _ = _answers(url, token, "demo")
    assert row["paused"] is True
    assert row["budget"]["used"] >= row["budget"]["tokens"]
    assert [t.status for t in TaskRepository.for_pod("demo").list()] == ["blocked"]

    status, body = _post(f"{url}/pods/demo/resume", token=token)

    assert status == 200
    assert body["resumed"] is True
    assert body["paused"] is False
    assert body["pod"] == "demo"
    assert [t.status for t in TaskRepository.for_pod("demo").list()] == ["pending"]
    (entry,) = audit_entries("run.resume")
    assert "pod=demo" in entry["detail"]
    assert "channel=http" in entry["detail"]

    status, again = _post(f"{url}/pods/demo/resume", token=token)

    assert status == 200
    assert again["resumed"] is False
    assert again["paused"] is False
    assert len(audit_entries("run.resume")) == 1


def test_post_resume_needs_the_token_and_a_known_pod(live_server: tuple[str, str]) -> None:
    """Like every write: 401 without the bearer token, 404 for a pod that does not exist."""
    url, token = live_server

    assert _post(f"{url}/pods/demo/resume")[0] == 401
    status, body = _post(f"{url}/pods/ghost/resume", token=token)
    assert status == 404
    assert body["ok"] is False


def test_a_pod_with_no_cap_serves_its_budget_on_both_routes(
    live_server: tuple[str, str],
) -> None:
    """`budget` is always there: no cap, every token counted, no window."""
    url, token = live_server
    _pp.provision_pod("demo", "build", location="/src/demo")
    spend_tokens("demo-lead", {"2026-01-01": 40, _today(): 2})

    row, detail = _answers(url, token, "demo")

    expected = {"tokens": None, "used": 42, "window": "none", "windowStart": None}
    assert row["budget"] == expected
    assert detail["budget"] == expected


def test_a_day_window_counts_today_only_from_midnight_utc_on_both_routes(
    live_server: tuple[str, str],
) -> None:
    """With `budgetWindow day` the answer names the window, its start and only today's tokens."""
    url, token = live_server
    _pp.provision_pod("demo", "build", location="/src/demo")
    _fleet.meta_set("demo-lead", "budgetTokens", 100)
    _fleet.meta_set("demo-lead", "budgetWindow", "day")
    spend_tokens("demo-lead", {"2026-01-01": 40, _today(): 2})

    row, detail = _answers(url, token, "demo")

    expected = {
        "tokens": 100,
        "used": 2,
        "window": "day",
        "windowStart": f"{_today()}T00:00:00Z",
    }
    assert row["budget"] == expected
    assert detail["budget"] == expected


def test_the_list_names_a_pod_with_invalid_settings_instead_of_failing(
    live_server: tuple[str, str],
) -> None:
    """One pod whose stored settings no longer validate does not take the whole list down."""
    url, token = live_server
    _pp.provision_pod("demo", "build", location="/src/demo")
    _pp.provision_pod("other", "build", location="/src/other")
    _fleet.meta_set("demo-lead", "approvalMode", "sometimes")

    status, listing = _get(f"{url}/pods", token)

    assert status == 200
    rows = {p["name"]: p for p in listing["pods"]}
    assert "approvalMode" in rows["demo"]["error"]
    assert "budget" not in rows["demo"]
    assert "error" not in rows["other"]
    assert rows["other"]["budget"]["window"] == "none"


_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "operator-v2"


def test_the_pod_budget_answers_are_the_recorded_fixture(live_server: tuple[str, str]) -> None:
    """The `budget` object and the resume answer's own keys, as a plan of record reads them."""
    url, token = live_server
    _pp.provision_pod("free", "build", location="/src/free")
    _pp.provision_pod("capped", "build", location="/src/capped")
    _fleet.meta_set("capped-lead", "budgetTokens", 100)
    _fleet.meta_set("capped-lead", "budgetWindow", "day")
    spend_tokens("capped-lead", {"2026-01-01": 40, _today(): 150})
    _pre_hop._pause_lead_for_budget("capped")

    free_row, free_detail = _answers(url, token, "free")
    row, detail = _answers(url, token, "capped")
    _, resumed = _post(f"{url}/pods/capped/resume", token=token)
    actual = json.loads(
        json.dumps(
            {
                "noCap": {"row": free_row["budget"], "detail": free_detail["budget"]},
                "dayCap": {
                    "row": row["budget"],
                    "detail": detail["budget"],
                    "paused": detail["paused"],
                    "pausedReason": detail["pausedReason"],
                },
                "resume": {"resumed": resumed["resumed"], "paused": resumed["paused"]},
            }
        ).replace(_today(), "<today>")
    )
    if record := os.environ.get("OPERATOR_RECORD_DIR"):
        Path(record, "pod-budget.json").write_text(json.dumps(actual, indent=2) + "\n", "utf-8")
        return
    recorded = json.loads((_FIXTURES / "pod-budget.json").read_text(encoding="utf-8"))
    assert actual == recorded
