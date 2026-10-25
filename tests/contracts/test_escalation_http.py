"""``GET /escalations`` and ``GET /inbox`` over the real route, for a pause parked by a real run.

The product runs for real in a subprocess: the pod, the sweep, the park, the service and its HTTP
route. Only the model is faked. The escalation's HTTP shape and the inbox are compared with
recorded fixtures (``tests/fixtures/operator-v2/``) once their ids and times are replaced by
placeholders, so a drift in the route, the contract model or the join fails here. The fixtures
were recorded from these scenarios with ``OPERATOR_RECORD_DIR`` set; a mismatch is a change to
look at, not to record.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.support.e2e import Service, World
from tests.support.model_server import FakeModel, call, say

SUBJECT = "docket.interfaces.http.routes.escalations"

FIXTURES = Path(__file__).parent.parent / "fixtures" / "operator-v2"
PIPELINE = "name: ask\nsteps:\n  - implement: implementer\n"
ASKS_INPUT = "name: asks\nsteps:\n  - plan: lead\n  - ask:\n      input:\n        from: plan\n"
GATED = "rm -rf build"
QUESTION = {
    "message": "Which cache should the service use?",
    "kind": "decision",
    "options": [
        {"id": "redis", "label": "Redis", "description": "already deployed"},
        {"id": "memcached", "label": "Memcached", "description": "simpler"},
    ],
    "recommendation": {"optionId": "redis", "rationale": "it is already deployed"},
}
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def normalized(value: Any, names: dict[str, str]) -> Any:
    """*value* with what differs between two runs replaced by placeholders: every string in
    *names* by its placeholder, every ISO time by ``<time>``."""
    if isinstance(value, dict):
        return {k: normalized(v, names) for k, v in value.items()}
    if isinstance(value, list):
        return [normalized(v, names) for v in value]
    if isinstance(value, str):
        if _TIME.match(value):
            return "<time>"
        for real, placeholder in names.items():
            value = value.replace(real, placeholder)
    return value


def recorded(name: str, actual: Any) -> Any:
    """The fixture ``operator-v2/<name>.json``; with ``OPERATOR_RECORD_DIR`` set, *actual* is
    written there and returned, which is how the fixtures are made from a run."""
    if record := os.environ.get("OPERATOR_RECORD_DIR"):
        Path(record, f"{name}.json").write_text(
            json.dumps(actual, indent=2) + "\n", encoding="utf-8"
        )
        return actual
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def check(name: str, view: Any, names: dict[str, str]) -> None:
    """Compare *view*, placeholders in, with the fixture *name*."""
    actual = normalized(view, names)
    assert actual == recorded(name, actual), name


def park(root: Path, model: FakeModel, pipeline: str) -> tuple[World, str]:
    """A world whose one task is parked by a real run of *pipeline*; its task id."""
    w = World(root / "world", model)
    w.make_pod(pipeline)
    task_id = w.add_task("Add a cache to the service")
    w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30")
    return w, task_id


@pytest.fixture()
def parked(tmp_path: Path, fake_model: Any) -> Iterator[tuple[Service, str]]:
    """A service over a task parked on a consult."""
    model: FakeModel = fake_model(
        script={"implementer": [call("consult", "k1", **QUESTION), say("done")]}
    )
    w, task_id = park(tmp_path, model, PIPELINE)
    assert w.task(task_id)["task"]["status"] == "waiting_input"
    with w.service(dispatch=False) as service:
        yield service, task_id


@contextlib.contextmanager
def serving(
    root: Path, model: FakeModel, pipeline: str, status: str
) -> Iterator[tuple[Service, str]]:
    """A service over a task a real run of *pipeline* parked at *status*."""
    w, task_id = park(root, model, pipeline)
    assert w.task(task_id)["task"]["status"] == status
    with w.service(dispatch=False) as service:
        yield service, task_id


def test_the_escalations_route_serves_the_recorded_shape(parked: tuple[Service, str]) -> None:
    service, task_id = parked

    status, body = service.get("/escalations")

    assert status == 200
    (view,) = body["escalations"]
    assert view["task"] == task_id
    check(
        "escalation-consult",
        view,
        {view["id"]: "<escalation-id>", task_id: "<task-id>"},
    )
    assert body["next"] == view["seq"]


def test_the_inbox_carries_the_same_escalation_and_names_it_on_the_task_that_needs_you(
    parked: tuple[Service, str],
) -> None:
    service, task_id = parked
    _, escalations = service.get("/escalations")

    status, inbox = service.get("/inbox")

    assert status == 200
    assert inbox["escalations"] == escalations["escalations"]
    (waiting,) = inbox["needsYou"]
    assert (waiting["id"], waiting["status"]) == (task_id, "waiting_input")
    (view,) = escalations["escalations"]
    assert waiting["escalation"] == view["id"]
    assert [o["id"] for o in view["options"]][:2] == ["redis", "memcached"]
    assert view["recommendation"]["optionId"] == "redis"
    assert "question" not in waiting
    assert set(inbox) == {"needsYou", "failed", "doneSince", "running", "next", "escalations"}
    check("inbox-consult", inbox, {view["id"]: "<escalation-id>", task_id: "<task-id>"})


def test_a_cursor_pod_and_task_narrow_the_list(parked: tuple[Service, str]) -> None:
    service, task_id = parked
    _, body = service.get("/escalations")
    seq = body["next"]

    assert service.get(f"/escalations?since={seq}")[1] == {"escalations": [], "next": seq}
    assert len(service.get("/escalations?pod=e2e")[1]["escalations"]) == 1
    assert service.get("/escalations?pod=other")[1]["escalations"] == []
    assert len(service.get(f"/escalations?task={task_id}")[1]["escalations"]) == 1
    assert service.get("/escalations?task=task-nope")[1]["escalations"] == []


@pytest.mark.parametrize("since", ["abc", "-1", "1.5"])
def test_a_cursor_that_is_not_a_sequence_number_is_refused(
    parked: tuple[Service, str], since: str
) -> None:
    status, body = parked[0].get(f"/escalations?since={since}")

    assert status == 400 and body["ok"] is False


def test_the_route_needs_the_bearer_token(parked: tuple[Service, str]) -> None:
    service, _ = parked

    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(service.url + "/escalations", timeout=10)

    assert refused.value.code == 401


def test_a_parked_approval_is_served_with_no_token_anywhere(
    tmp_path: Path, fake_model: Any
) -> None:
    model: FakeModel = fake_model(
        script={"implementer": [call("bash", "c1", command=GATED), say("done")]}
    )

    with serving(tmp_path, model, PIPELINE, "waiting_approval") as (service, task_id):
        _, body = service.get("/escalations")
        (view,) = body["escalations"]
        _, inbox = service.get("/inbox")

        assert (view["kind"], view["state"]) == ("approval", "pending")
        assert GATED in view["prompt"]
        (waiting,) = inbox["needsYou"]
        assert waiting["escalation"] == view["id"]
        assert not re.search(r"apr[-_][0-9A-Za-z-]+", json.dumps([body, inbox]))
        names = {view["id"]: "<escalation-id>", task_id: "<task-id>"}
        check("escalation-approval", view, names)
        check("inbox-approval", inbox, names)


def test_a_parked_input_is_served_as_an_escalation_the_task_names(
    tmp_path: Path, fake_model: Any
) -> None:
    model: FakeModel = fake_model(script={"lead": [say("the plan")]})

    with serving(tmp_path, model, ASKS_INPUT, "waiting_input") as (service, task_id):
        _, body = service.get("/escalations")
        (view,) = body["escalations"]
        _, inbox = service.get("/inbox")

        assert (view["kind"], view["state"]) == ("input", "pending")
        (waiting,) = inbox["needsYou"]
        assert waiting["escalation"] == view["id"]
        names = {view["id"]: "<escalation-id>", task_id: "<task-id>"}
        check("escalation-input", view, names)
        check("inbox-input", inbox, names)
