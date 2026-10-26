"""JSON-RPC 2.0 for the A2A binding: the request, the response objects and the error table.

An edge maps each refusal of the domain to one code here and never by reading a message, so the
mapping is a table a test can pin. The A2A codes are the ones its specification names
(``-32001`` task not found, ``-32002`` not cancelable, ``-32004`` unsupported operation); the
rest are JSON-RPC's own."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from docket.kernel.errors import DocketError
from docket.tasks.domain.resolution import (
    EscalationInvalid,
    EscalationNotFound,
    EscalationNotPending,
    EscalationRefused,
)
from docket.tasks.domain.task import TaskNotFoundError

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
TASK_NOT_FOUND = -32001
TASK_NOT_CANCELABLE = -32002
UNSUPPORTED = -32004


class RpcError(DocketError):
    """A failure that answers a JSON-RPC request: *code*, a sentence and optional *data*."""

    def __init__(self, code: int, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


@dataclass(frozen=True)
class Request:
    id: Any
    method: str
    params: dict[str, Any]


def parse_request(body: object) -> Request:
    """The one request *body* holds, or ``RpcError`` for what is not a JSON-RPC 2.0 request
    object (a batch included)."""
    if not isinstance(body, dict):
        raise RpcError(INVALID_REQUEST, "send one JSON-RPC 2.0 request object")
    if body.get("jsonrpc") != "2.0" or "id" not in body:
        raise RpcError(INVALID_REQUEST, "a request has jsonrpc 2.0 and an id")
    method = body.get("method")
    if not isinstance(method, str):
        raise RpcError(INVALID_REQUEST, "method must be a string")
    params = body.get("params", {})
    if not isinstance(params, dict):
        raise RpcError(INVALID_PARAMS, "params must be an object")
    return Request(body["id"], method, params)


def success(request_id: Any, result: object) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def failure(request_id: Any, error: RpcError) -> dict[str, Any]:
    body: dict[str, Any] = {"code": error.code, "message": error.message}
    if error.data is not None:
        body["data"] = error.data
    return {"jsonrpc": "2.0", "id": request_id, "error": body}


def refusal(exc: DocketError) -> RpcError:
    """The error that answers a refused request: the code of its kind, its own sentence, and a
    ``reason`` a client can branch on. What no row names is internal and hides its text."""
    if isinstance(exc, RpcError):
        return exc
    if isinstance(exc, TaskNotFoundError):
        return RpcError(TASK_NOT_FOUND, exc.message)
    if isinstance(exc, EscalationNotPending):
        return RpcError(UNSUPPORTED, exc.message, {"reason": "not_pending"})
    if isinstance(exc, EscalationNotFound):
        return RpcError(INVALID_PARAMS, exc.message, {"reason": "not_found"})
    if isinstance(exc, EscalationInvalid):
        return RpcError(INVALID_PARAMS, exc.message, {"reason": "invalid"})
    if isinstance(exc, EscalationRefused):
        return RpcError(INVALID_PARAMS, exc.message, {"reason": "refused"})
    return RpcError(INTERNAL_ERROR, "internal error")
