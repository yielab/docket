"""``POST /a2a`` and the agent card over the real route, for a consult parked by a real run.

The product runs for real in a subprocess: the pod, the sweep, the park, the service and its HTTP
route. Only the model is faked. Each JSON-RPC exchange is compared with a recorded fixture under
``tests/contracts/a2a/`` once its ids and times are placeholders, so a drift in the route, the
contract models or the join with the escalation record fails here. The fixtures were recorded
from this scenario with ``A2A_RECORD_DIR`` set; a mismatch is a change to look at, not to record.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.support.a2a import (
    CONSULT,
    EXTENSION,
    A2AClient,
    agent_card,
    normalize,
    push_listener,
)
from tests.support.e2e import Service, World
from tests.support.model_server import FakeModel, call, say

from docket import __version__

SUBJECT = "docket.interfaces.http.routes.a2a"

FIXTURES = Path(__file__).parent / "a2a"
PIPELINE = "name: ask\nsteps:\n  - implement: implementer\n"


def check(
    name: str, request: dict[str, Any], response: dict[str, Any], names: dict[str, str]
) -> None:
    """Compare one exchange, placeholders in, with ``a2a/<name>.json``."""
    actual = {"request": normalize(request, names), "response": normalize(response, names)}
    assert actual == recorded(name, actual), name


def recorded(name: str, actual: Any) -> Any:
    """The fixture ``a2a/<name>.json``; with ``A2A_RECORD_DIR`` set, *actual* is written there and
    returned, which is how the fixtures are made from a run."""
    if record := os.environ.get("A2A_RECORD_DIR"):
        Path(record, f"{name}.json").write_text(
            json.dumps(actual, indent=2) + "\n", encoding="utf-8"
        )
        return actual
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def parked_world(root: Path, make_model: Callable[..., FakeModel]) -> tuple[World, str]:
    """A world whose one task is parked on a consult; its task id."""
    model = make_model(script={"implementer": [call("consult", "k1", **CONSULT), say("done")]})
    w = World(root / "world", model)
    w.make_pod(PIPELINE)
    task_id = w.add_task("Add a cache to the service")
    w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30")
    assert w.task(task_id)["task"]["status"] == "waiting_input"
    return w, task_id


@pytest.fixture()
def parked(
    tmp_path: Path, fake_model: Any
) -> Iterator[tuple[Service, A2AClient, str, dict[str, str]]]:
    w, task_id = parked_world(tmp_path, fake_model)
    with w.service(dispatch=False) as service:
        _, page = service.get("/escalations")
        names = {task_id: "<task-id>", page["escalations"][0]["id"]: "<escalation-id>"}
        yield service, A2AClient(service), task_id, names


def test_a_sent_text_creates_a_submitted_task_and_a_retry_finds_the_same_one(
    parked: tuple[Service, A2AClient, str, dict[str, str]],
) -> None:
    service, client, task_id, names = parked
    message = {
        "kind": "message",
        "role": "user",
        "messageId": "m-1",
        "parts": [{"kind": "text", "text": "Add a second cache"}],
    }
    first = client.request("message/send", {"message": message})
    created = client.send(first)
    new_id = created["result"]["id"]
    names = {**names, new_id: "<new-task-id>"}

    again = client.send(client.request("message/send", {"message": message}))

    check("send-task", first, created, names)
    assert created["result"]["status"]["state"] == "SUBMITTED"
    assert again["result"] == created["result"]
    _, listed = service.get("/tasks/e2e")
    assert sorted(t["id"] for t in listed["tasks"]) == sorted([task_id, new_id])


def test_a_parked_consult_reads_input_required_with_the_escalation_as_a_data_part(
    parked: tuple[Service, A2AClient, str, dict[str, str]],
) -> None:
    _, client, task_id, names = parked
    request = client.request("tasks/get", {"id": task_id})

    response = client.send(request)

    check("get-parked", request, response, names)
    status = response["result"]["status"]
    assert status["state"] == "INPUT_REQUIRED"
    assert status["message"]["extensions"] == [EXTENSION]
    data = status["message"]["parts"][1]["data"]
    assert [o["id"] for o in data["options"]] == ["redis", "memcached", "decline"]
    assert data["requestedSchema"]["properties"]["optionId"]["enum"] == ["redis", "memcached"]
    assert "apr-" not in json.dumps(response)


def test_the_agent_card_names_the_pods_the_capabilities_and_the_extension(
    parked: tuple[Service, A2AClient, str, dict[str, str]],
) -> None:
    service, _, _, _ = parked

    status, card = agent_card(service, service.token)

    assert status == 200
    actual = normalize(card, {service.url: "<url>", __version__: "<version>"})
    assert actual == recorded("agent-card", actual)
    assert card["capabilities"]["pushNotifications"] is True
    assert [s["id"] for s in card["skills"]] == ["e2e"]


def test_the_card_and_the_endpoint_need_the_bearer_token(
    parked: tuple[Service, A2AClient, str, dict[str, str]],
) -> None:
    service, _, _, _ = parked

    assert agent_card(service, None)[0] == 401
    post = urllib.request.Request(service.url + "/a2a", data=b"{}", method="POST")
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(post, timeout=10)
    assert refused.value.code == 401


def test_the_answer_resolves_the_escalation_once_and_a_second_answer_is_refused(
    parked: tuple[Service, A2AClient, str, dict[str, str]],
) -> None:
    service, client, task_id, names = parked
    accept = client.request(
        "message/send", {"message": _answer(task_id, "m-2", "accept", "memcached")}
    )
    first = client.send(accept)
    again = client.request(
        "message/send", {"message": _answer(task_id, "m-3", "accept", "memcached")}
    )
    second = client.send(again)

    escalation_id = next(real for real, mask in names.items() if mask == "<escalation-id>")
    named = client.request(
        "message/send",
        {"message": _answer(task_id, "m-6", "accept", "redis", escalation_id=escalation_id)},
    )
    settled = client.send(named)

    check("answer-accept", accept, first, names)
    check("answer-again", again, second, names)
    check("answer-settled", named, settled, names)
    assert settled["error"]["code"] == -32004 and settled["error"]["data"] == {
        "reason": "not_pending"
    }
    assert first["result"]["status"]["state"] == "SUBMITTED"
    assert second["error"]["code"] == -32004 and second["error"]["data"] == {
        "reason": "not_pending"
    }
    _, page = service.get("/escalations")
    (view,) = page["escalations"]
    assert (view["state"], view["resolution"]["optionId"], view["resolution"]["channel"]) == (
        "resolved",
        "memcached",
        "a2a",
    )


def test_a_task_is_cancelled_while_parked(
    parked: tuple[Service, A2AClient, str, dict[str, str]],
) -> None:
    _, client, task_id, names = parked
    request = client.request("tasks/cancel", {"id": task_id})

    response = client.send(request)

    check("cancel", request, response, names)
    assert response["result"]["status"]["state"] == "CANCELED"
    assert client.state(task_id) == "CANCELED"
    assert client.rpc("tasks/cancel", {"id": task_id})["error"]["code"] == -32002


def test_a_push_config_is_stored_and_read_back_for_the_task(
    parked: tuple[Service, A2AClient, str, dict[str, str]],
) -> None:
    _, client, task_id, names = parked
    config = {"url": "http://127.0.0.1:9/hook"}
    setting = client.request(
        "tasks/pushNotificationConfig/set", {"taskId": task_id, "pushNotificationConfig": config}
    )
    stored = client.send(setting)
    getting = client.request("tasks/pushNotificationConfig/get", {"id": task_id})
    read = client.send(getting)

    check("push-set", setting, stored, names)
    check("push-get", getting, read, names)
    assert read["result"]["pushNotificationConfig"]["url"] == config["url"]


@pytest.mark.parametrize(
    ("name", "method", "params", "code"),
    [
        ("error-unknown-task", "tasks/get", {"id": "task-nope"}, -32001),
        ("error-unknown-method", "tasks/nope", {}, -32601),
        ("error-streaming", "message/stream", {}, -32004),
        ("error-no-push", "tasks/pushNotificationConfig/get", {"id": "<task>"}, -32602),
        ("error-bad-params", "tasks/get", {"id": 5}, -32602),
    ],
)
def test_a_refusal_is_a_json_rpc_error_object(
    parked: tuple[Service, A2AClient, str, dict[str, str]],
    name: str,
    method: str,
    params: dict[str, Any],
    code: int,
) -> None:
    _, client, task_id, names = parked
    request = client.request(
        method, {k: task_id if v == "<task>" else v for k, v in params.items()}
    )

    response = client.send(request)

    check(name, request, response, names)
    assert response["error"]["code"] == code


def test_a_body_that_is_not_json_is_a_parse_error_and_a_wrong_answer_names_the_option(
    parked: tuple[Service, A2AClient, str, dict[str, str]],
) -> None:
    service, client, task_id, _ = parked
    raw = urllib.request.Request(service.url + "/a2a", data=b"{nope", method="POST")
    raw.add_header("Authorization", f"Bearer {service.token}")
    with urllib.request.urlopen(raw, timeout=10) as reply:
        assert json.loads(reply.read())["error"]["code"] == -32700

    missing = client.answer(task_id, "m-4", "accept")
    unknown = client.answer(task_id, "m-5", "accept", optionId="mongo")
    still_parked = client.state(task_id)

    assert missing["error"]["code"] == unknown["error"]["code"] == -32602
    assert missing["error"]["data"] == unknown["error"]["data"] == {"reason": "invalid"}
    assert "mongo" in unknown["error"]["message"] and "redis" in unknown["error"]["message"]
    assert still_parked == "INPUT_REQUIRED"


def test_a_message_that_cannot_make_or_answer_a_task_is_refused_and_creates_nothing(
    parked: tuple[Service, A2AClient, str, dict[str, str]],
) -> None:
    service, client, task_id, _ = parked

    def sent(message: dict[str, Any], **params: Any) -> dict[str, Any]:
        return client.rpc("message/send", {"message": message, **params})

    text = {"kind": "message", "role": "user", "messageId": "m-9"}
    blank = sent({**text, "parts": [{"kind": "text", "text": "  "}]})
    elsewhere = sent({**text, "parts": [{"kind": "text", "text": "x"}]}, metadata={"pod": "nope"})
    no_action = sent({**text, "taskId": task_id, "parts": [{"kind": "text", "text": "yes"}]})
    no_task = sent(
        {**text, "taskId": "task-nope", "parts": [{"kind": "data", "data": {"action": "accept"}}]}
    )
    pod_named = client.send_text("Named pod", "m-10", metadata={"pod": "e2e"})

    assert [r["error"]["code"] for r in (blank, elsewhere, no_action)] == [-32602] * 3
    assert no_task["error"]["code"] == -32001
    assert pod_named["contextId"] == "e2e"
    _, listed = service.get("/tasks/e2e")
    assert len(listed["tasks"]) == 2


def test_a_push_reaches_a_local_listener_when_the_task_parks_and_when_it_completes(
    tmp_path: Path, fake_model: Any
) -> None:
    replies = [call("consult", "k1", **CONSULT), say("done"), say("done too")]
    w = World(tmp_path / "world", fake_model(script={"implementer": replies}))
    w.make_pod(PIPELINE)
    w.docket("pod", "set", "pipeline", str(w.pipeline))
    with push_listener() as listener, w.service() as service:
        client = A2AClient(service)
        task = client.send_text(
            "Add a cache to the service",
            "m-push",
            configuration={"pushNotificationConfig": {"url": listener.url}},
        )
        task_id = task["id"]
        client.wait_state(w, task_id, "INPUT_REQUIRED")
        w.wait_for(lambda: bool(listener.received), 30, "the first push")
        parked_push = list(listener.kinds())
        client.answer(task_id, "m-ans", "accept", optionId="redis")
        client.wait_state(w, task_id, "COMPLETED")
        w.wait_for(lambda: len(listener.received) >= 2, 30, "the completion push")
        other = client.send_text("A task nobody subscribed to", "m-other")["id"]
        client.wait_state(w, other, "COMPLETED")
        time.sleep(2.5)
        heard = listener.kinds()

    assert parked_push == [("dev.docket.task.input_required", task_id)]
    assert heard == [
        ("dev.docket.task.input_required", task_id),
        ("dev.docket.task.completed", task_id),
    ]
    assert listener.received[0]["body"]["data"]["options"][0]["id"] == "redis"
    assert listener.received[0]["headers"]["Content-Type"] == "application/cloudevents+json"


def _answer(
    task_id: str, message_id: str, action: str, option: str, escalation_id: str = ""
) -> dict[str, Any]:
    data: dict[str, Any] = {"action": action, "content": {"optionId": option}}
    if escalation_id:
        data["escalationId"] = escalation_id
    return {
        "kind": "message",
        "role": "user",
        "messageId": message_id,
        "taskId": task_id,
        "parts": [{"kind": "data", "data": data}],
    }
