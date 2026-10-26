"""``POST /a2a`` and ``GET /.well-known/agent.json``: the A2A binding over the existing records.

A task is the queue's record, its question is the pending escalation, and answering it is
``resolve``; this module only translates (a2a-binding.spec.md). Every method returns an A2A
``Task`` built by ``a2a_task`` or a result object, and every refusal is a ``RpcError``."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from docket import __version__
from docket.interfaces.http.exchange import HttpExchange
from docket.interfaces.http.routes import a2a_push, a2a_rpc, a2a_task
from docket.interfaces.http.routes.a2a_rpc import RpcError
from docket.kernel.errors import DispatchError, DocketError
from docket.operator import escalation_views
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application import queue as _queue
from docket.tasks.application.escalations import resolve
from docket.tasks.domain.state import Status

Method = Callable[[HttpExchange, dict[str, Any]], Any]

_ACTIONS = ("accept", "decline", "cancel")
_UNIMPLEMENTED = frozenset(
    {
        "message/stream",
        "tasks/resubscribe",
        "tasks/pushNotificationConfig/list",
        "tasks/pushNotificationConfig/delete",
        "agent/getAuthenticatedExtendedCard",
    }
)
_CHANNEL = "a2a"


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RpcError(a2a_rpc.INVALID_PARAMS, f"{name} must be an object")
    return value


def _string(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise RpcError(a2a_rpc.INVALID_PARAMS, f"{key} must be a non-empty string")
    return value


def _located(task_id: str) -> tuple[str, Any]:
    found = a2a_task.find_task(task_id)
    if found is None:
        raise RpcError(a2a_rpc.TASK_NOT_FOUND, f"no task {task_id!r}")
    return found


def _parts(message: dict[str, Any]) -> list[dict[str, Any]]:
    parts = message.get("parts")
    if not isinstance(parts, list) or not all(isinstance(p, dict) for p in parts):
        raise RpcError(a2a_rpc.INVALID_PARAMS, "message.parts must be a list of parts")
    return parts


def _pod_of(params: dict[str, Any], message: dict[str, Any]) -> str:
    """The pod a new task goes to: named in the metadata, else the only pod there is."""
    pods = _queue.dispatchable_pods()
    for source in (params.get("metadata"), message.get("metadata")):
        if isinstance(source, dict) and isinstance(source.get("pod"), str):
            pod = str(source["pod"])
            if pod not in pods:
                raise RpcError(a2a_rpc.INVALID_PARAMS, f"unknown pod {pod!r}; pods: {pods}")
            return pod
    if len(pods) == 1:
        return pods[0]
    raise RpcError(
        a2a_rpc.INVALID_PARAMS, f"name the pod in params.metadata.pod; pods: {', '.join(pods)}"
    )


def _create(h: HttpExchange, params: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
    texts = [str(p.get("text", "")) for p in _parts(message) if p.get("kind") == "text"]
    description = "\n\n".join(t for t in texts if t.strip())
    if not description:
        raise RpcError(a2a_rpc.INVALID_PARAMS, "the message needs a non-empty text part")
    pod = _pod_of(params, message)
    message_id = message.get("messageId")
    options: dict[str, Any] = (
        {"idempotency_key": f"a2a-{message_id}"} if isinstance(message_id, str) else {}
    )
    try:
        task, created = _queue.enqueue_task_once(
            pod, description, "normal", channel="http", **options
        )
    except DispatchError as exc:
        raise RpcError(a2a_rpc.INVALID_PARAMS, exc.message, {"reason": "invalid"}) from exc
    configuration = params.get("configuration")
    push = configuration.get("pushNotificationConfig") if isinstance(configuration, dict) else None
    if push is not None:
        a2a_push.store(pod, task.id, _object(push, "configuration.pushNotificationConfig"))
    if created and h.dispatch_on and task.status != Status.waiting_approval:
        h._submit_sweep(pod)
    return a2a_task.task_result(pod, task)


def _escalation_to_answer(pod: str, task_id: str, data: dict[str, Any]) -> Any:
    """The escalation an answer settles: the one named, else the task's one pending escalation."""
    named = data.get("escalationId")
    if named is not None:
        match = next((v for v in escalation_views(pod=pod, task=task_id) if v.id == named), None)
        if match is None:
            raise RpcError(
                a2a_rpc.INVALID_PARAMS,
                f"no escalation {named!r} on task {task_id}",
                {"reason": "not_found"},
            )
        return match
    pending = a2a_task.pending_escalations(pod, task_id)
    if not pending:
        raise RpcError(
            a2a_rpc.UNSUPPORTED,
            f"task {task_id} has no pending escalation",
            {"reason": "not_pending"},
        )
    if len(pending) > 1:
        raise RpcError(
            a2a_rpc.INVALID_PARAMS,
            f"task {task_id} waits on several escalations; name one in escalationId",
            {"reason": "invalid"},
        )
    return pending[0]


def _answer(message: dict[str, Any], task_id: str) -> dict[str, Any]:
    pod, _ = _located(task_id)
    data = next(
        (
            p.get("data")
            for p in _parts(message)
            if p.get("kind") == "data"
            and isinstance(p.get("data"), dict)
            and p["data"].get("action") in _ACTIONS
        ),
        None,
    )
    if data is None:
        raise RpcError(
            a2a_rpc.INVALID_PARAMS, f"send a data part with an action: {', '.join(_ACTIONS)}"
        )
    content = data.get("content")
    if content is not None and not isinstance(content, dict):
        raise RpcError(a2a_rpc.INVALID_PARAMS, "content must be an object")
    body = dict(content or {})
    option = body.pop("optionId", None)
    if option is not None and not isinstance(option, str):
        raise RpcError(a2a_rpc.INVALID_PARAMS, "content.optionId must be a string")
    escalation = _escalation_to_answer(pod, task_id, data)
    if data["action"] != "accept":
        option = "deny" if a2a_task.question_kind(escalation) == "approval" else "decline"
    resolved = resolve(escalation.id, option, body or None, by=_CHANNEL, channel=_CHANNEL)
    _, record = _located(task_id)
    result = a2a_task.task_result(pod, record)
    if resolved.note:
        result["metadata"]["docket"]["note"] = resolved.note
    return result


def message_send(h: HttpExchange, params: dict[str, Any]) -> dict[str, Any]:
    message = _object(params.get("message"), "message")
    task_id = message.get("taskId")
    if task_id is None:
        return _create(h, params, message)
    if not isinstance(task_id, str):
        raise RpcError(a2a_rpc.INVALID_PARAMS, "message.taskId must be a string")
    return _answer(message, task_id)


def tasks_get(_h: HttpExchange, params: dict[str, Any]) -> dict[str, Any]:
    pod, record = _located(_string(params, "id"))
    return a2a_task.task_result(pod, record)


def tasks_cancel(_h: HttpExchange, params: dict[str, Any]) -> dict[str, Any]:
    task_id = _string(params, "id")
    pod, _ = _located(task_id)
    outcome = _lifecycle.cancel_task(pod, task_id, channel=_CHANNEL, actor=_CHANNEL)
    if not outcome.cancelled:
        raise RpcError(
            a2a_rpc.TASK_NOT_CANCELABLE, f"task {task_id} is {outcome.status}; nothing to cancel"
        )
    _, record = _located(task_id)
    return a2a_task.task_result(pod, record)


def push_set(_h: HttpExchange, params: dict[str, Any]) -> dict[str, Any]:
    task_id = _string(params, "taskId")
    config = _object(params.get("pushNotificationConfig"), "pushNotificationConfig")
    pod, _ = _located(task_id)
    return {"taskId": task_id, "pushNotificationConfig": a2a_push.store(pod, task_id, config)}


def push_get(_h: HttpExchange, params: dict[str, Any]) -> dict[str, Any]:
    task_id = _string(params, "id")
    _located(task_id)
    config = a2a_push.read(task_id)
    if config is None:
        raise RpcError(
            a2a_rpc.INVALID_PARAMS,
            f"task {task_id} has no push notification config",
            {"reason": "no_push_config"},
        )
    return {"taskId": task_id, "pushNotificationConfig": config}


METHODS: dict[str, Method] = {
    "message/send": message_send,
    "tasks/get": tasks_get,
    "tasks/cancel": tasks_cancel,
    "tasks/pushNotificationConfig/set": push_set,
    "tasks/pushNotificationConfig/get": push_get,
}


def _dispatch(h: HttpExchange, request: a2a_rpc.Request) -> Any:
    method = METHODS.get(request.method)
    if method is None:
        if request.method in _UNIMPLEMENTED:
            raise RpcError(a2a_rpc.UNSUPPORTED, f"{request.method} is not supported")
        raise RpcError(a2a_rpc.METHOD_NOT_FOUND, f"unknown method {request.method!r}")
    try:
        return method(h, request.params)
    except RpcError:
        raise
    except DocketError as exc:
        raise a2a_rpc.refusal(exc) from exc
    except Exception as exc:  # a handler must answer, never drop the connection
        raise RpcError(a2a_rpc.INTERNAL_ERROR, "internal error") from exc


def post_a2a(h: HttpExchange, _arg: str) -> None:
    """``POST /a2a``: one JSON-RPC request, always answered ``200`` with a response object."""
    raw = h._read_body()
    if raw is None:
        return
    request_id: Any = None
    try:
        try:
            body = json.loads(raw)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise RpcError(a2a_rpc.PARSE_ERROR, "the body is not JSON") from exc
        if isinstance(body, dict):
            request_id = body.get("id")
        answer = a2a_rpc.success(request_id, _dispatch(h, a2a_rpc.parse_request(body)))
    except RpcError as error:
        answer = a2a_rpc.failure(request_id, error)
    h._send_json(answer)


def get_agent_card(h: HttpExchange, _arg: str) -> None:
    """``GET /.well-known/agent.json``: the pods as skills, push on, the operator extension."""
    skills = [
        {"id": pod, "name": pod, "description": f"Runs tasks in the {pod} pod.", "tags": []}
        for pod in _queue.dispatchable_pods()
    ]
    host = h.headers.get("Host") or "localhost"
    h._send_json(
        {
            "name": "docket",
            "description": "Teams of coding agents, governed. Each skill is a pod.",
            "url": f"http://{host}/a2a",
            "version": __version__,
            "protocolVersion": "0.3.0",
            "preferredTransport": "JSONRPC",
            "capabilities": {
                "streaming": False,
                "pushNotifications": True,
                "stateTransitionHistory": False,
                "extensions": [{"uri": a2a_task.EXTENSION_URI, "required": False}],
            },
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain", "application/json"],
            "skills": skills,
            "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
            "security": [{"bearer": []}],
        }
    )
