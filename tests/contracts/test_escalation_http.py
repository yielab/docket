"""``GET /escalations`` and ``GET /inbox`` over the real route, for a consult parked by a real run.

The product runs for real in a subprocess: the pod, the sweep, the park, the service and its HTTP
route. Only the model is faked. The escalation's HTTP shape is compared with a recorded fixture
(``tests/fixtures/operator-v1.1/escalation-consult.json``) once its ids and times are replaced
by placeholders, so a drift in the route, the contract model or the join fails here.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.support.e2e import Service, World
from tests.support.model_server import FakeModel, call, say

SUBJECT = "docket.interfaces.http.routes.escalations"

FIXTURE = Path(__file__).parent.parent / "fixtures" / "operator-v1.1" / "escalation-consult.json"
PIPELINE = "name: ask\nsteps:\n  - implement: implementer\n"
QUESTION = {
    "message": "Which cache should the service use?",
    "kind": "decision",
    "options": [
        {"id": "redis", "label": "Redis", "description": "already deployed"},
        {"id": "memcached", "label": "Memcached", "description": "simpler"},
    ],
    "recommendation": {"optionId": "redis", "rationale": "it is already deployed"},
}


def normalized(view: dict[str, Any]) -> dict[str, Any]:
    """*view* with what differs between two runs (ids, times) replaced by placeholders."""
    out = json.loads(json.dumps(view))
    out["affordances"]["resolveUrl"] = out["affordances"]["resolveUrl"].replace(
        out["id"], "<escalation-id>"
    )
    out.update(id="<escalation-id>", task="<task-id>", askedAt="<time>", expiresAt="<time>")
    return out


def park_a_consult(root: Path, model: FakeModel) -> tuple[World, str]:
    """A world whose one task is parked on a consult; its task id."""
    w = World(root / "world", model)
    w.make_pod(PIPELINE)
    task_id = w.add_task("Add a cache to the service")
    w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30")
    assert w.task(task_id)["task"]["status"] == "waiting_input"
    return w, task_id


@pytest.fixture()
def parked(tmp_path: Path, fake_model: Any) -> Iterator[tuple[Service, str]]:
    model: FakeModel = fake_model(
        script={"implementer": [call("consult", "k1", **QUESTION), say("done")]}
    )
    w, task_id = park_a_consult(tmp_path, model)
    with w.service(dispatch=False) as service:
        yield service, task_id


def test_the_escalations_route_serves_the_recorded_shape(parked: tuple[Service, str]) -> None:
    service, task_id = parked

    status, body = service.get("/escalations")

    assert status == 200
    (view,) = body["escalations"]
    assert view["task"] == task_id
    assert normalized(view) == json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert body["next"] == view["seq"]


def test_the_inbox_carries_the_same_escalation_and_leaves_needs_you_as_it_was(
    parked: tuple[Service, str],
) -> None:
    service, task_id = parked
    _, escalations = service.get("/escalations")

    status, inbox = service.get("/inbox")

    assert status == 200
    assert inbox["escalations"] == escalations["escalations"]
    (waiting,) = inbox["needsYou"]
    assert (waiting["id"], waiting["status"]) == (task_id, "waiting_input")
    assert [o["id"] for o in waiting["question"]["options"]] == ["redis", "memcached"]
    assert waiting["question"]["recommendation"]["optionId"] == "redis"
    assert set(inbox) == {"needsYou", "failed", "doneSince", "running", "next", "escalations"}


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
