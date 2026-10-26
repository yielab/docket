"""SUBJECT: interfaces.http.routes.a2a -- the JSON-RPC envelope, the method table and the card."""

from __future__ import annotations

import json
from typing import Any

import pytest

from docket import __version__
from docket.interfaces.http.routes import a2a
from docket.kernel.errors import DocketError
from docket.tasks.application import queue as _queue

SUBJECT = "docket.interfaces.http.routes.a2a"


class FakeExchange:
    """The part of ``HttpExchange`` the A2A handlers use, holding what they send."""

    dispatch_on = False

    def __init__(self, body: bytes = b"", host: str = "docket.test:7399") -> None:
        self.body = body
        self.headers = {"Host": host}
        self.sent: list[Any] = []

    def _read_body(self) -> bytes:
        return self.body

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        self.sent.append(payload)

    def _submit_sweep(self, project: str) -> bool:
        return True


def call(method: str, params: Any = None, **envelope: Any) -> dict[str, Any]:
    request = {"jsonrpc": "2.0", "id": 7, "method": method, **envelope}
    if params is not None:
        request["params"] = params
    exchange = FakeExchange(json.dumps(request).encode())
    a2a.post_a2a(exchange, "")  # type: ignore[arg-type]
    (answer,) = exchange.sent
    return dict(answer)


class TestEnvelope:
    def test_a_body_that_is_not_json_is_a_parse_error_with_no_id(self) -> None:
        exchange = FakeExchange(b"{nope")

        a2a.post_a2a(exchange, "")  # type: ignore[arg-type]

        assert exchange.sent == [
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "the body is not JSON"},
            }
        ]

    def test_the_id_of_the_request_answers_back_even_when_it_is_refused(self) -> None:
        answer = call("nope/nope")

        assert (answer["id"], answer["error"]["code"]) == (7, -32601)

    @pytest.mark.parametrize("method", sorted(a2a._UNIMPLEMENTED))
    def test_a_method_a2a_names_and_docket_lacks_is_unsupported_not_unknown(
        self, method: str
    ) -> None:
        assert call(method)["error"]["code"] == -32004

    def test_a_batch_is_an_invalid_request(self) -> None:
        exchange = FakeExchange(b'[{"jsonrpc": "2.0", "id": 1, "method": "tasks/get"}]')

        a2a.post_a2a(exchange, "")  # type: ignore[arg-type]

        assert exchange.sent[0]["error"]["code"] == -32600

    def test_a_refusal_the_domain_raises_is_mapped_and_an_rpc_error_passes_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuses(_h: object, _params: dict[str, Any]) -> None:
            raise DocketError("secret detail")

        monkeypatch.setitem(a2a.METHODS, "tasks/get", refuses)

        answer = call("tasks/get", {})

        assert answer["error"] == {"code": -32603, "message": "internal error"}

    def test_a_failure_nobody_expected_is_an_internal_error_without_its_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def breaks(_h: object, _params: dict[str, Any]) -> None:
            raise OSError("disk path /secret")

        monkeypatch.setitem(a2a.METHODS, "tasks/get", breaks)

        answer = call("tasks/get", {})

        assert answer["error"] == {"code": -32603, "message": "internal error"}
        assert "secret" not in json.dumps(answer)


class TestParams:
    @pytest.mark.parametrize(
        ("method", "params"),
        [
            ("tasks/get", {}),
            ("tasks/get", {"id": ""}),
            ("tasks/cancel", {"id": 3}),
            ("message/send", {}),
            ("message/send", {"message": "hi"}),
            ("message/send", {"message": {"taskId": 5, "parts": []}}),
            ("tasks/pushNotificationConfig/set", {"taskId": "t"}),
            ("tasks/pushNotificationConfig/get", {}),
        ],
    )
    def test_a_param_of_the_wrong_shape_is_invalid_params_before_anything_is_read(
        self, method: str, params: dict[str, Any]
    ) -> None:
        assert call(method, params)["error"]["code"] == -32602


class TestAgentCard:
    def test_each_pod_is_a_skill_and_the_url_follows_the_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_queue, "dispatchable_pods", lambda: ["alpha", "beta"])
        exchange = FakeExchange()

        a2a.get_agent_card(exchange, "")  # type: ignore[arg-type]

        (card,) = exchange.sent
        assert [s["id"] for s in card["skills"]] == ["alpha", "beta"]
        assert card["url"] == "http://docket.test:7399/a2a"
        assert card["version"] == __version__
        assert card["capabilities"]["pushNotifications"] is True
        assert card["capabilities"]["streaming"] is False
        assert card["security"] == [{"bearer": []}]
