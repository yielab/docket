"""SUBJECT: interfaces.http.routes.a2a_rpc -- JSON-RPC envelopes and the refusal-to-code table."""

from __future__ import annotations

import json

import pytest

from docket.interfaces.http.routes import a2a_rpc
from docket.kernel.errors import DocketError
from docket.tasks.domain.resolution import (
    EscalationInvalid,
    EscalationNotFound,
    EscalationNotPending,
    EscalationRefused,
)

SUBJECT = "docket.interfaces.http.routes.a2a_rpc"


class TestRefusals:
    @pytest.mark.parametrize(
        ("raised", "code", "reason"),
        [
            (EscalationNotFound("no escalation 'esc-x'"), -32602, "not_found"),
            (EscalationNotPending("escalation esc-x is not pending"), -32004, "not_pending"),
            (EscalationInvalid("option 'x' is not offered"), -32602, "invalid"),
            (EscalationRefused("deny-secrets"), -32602, "refused"),
        ],
    )
    def test_each_escalation_refusal_has_one_code_and_a_reason(
        self, raised: DocketError, code: int, reason: str
    ) -> None:
        error = a2a_rpc.refusal(raised)

        assert (error.code, error.data) == (code, {"reason": reason})
        assert error.message == raised.message

    def test_an_error_nobody_mapped_hides_its_text(self) -> None:
        error = a2a_rpc.refusal(DocketError("token apr-secret leaked"))

        assert error.code == -32603
        assert "apr-secret" not in json.dumps(a2a_rpc.failure(1, error))


class TestEnvelope:
    def test_a_result_and_an_error_are_json_rpc_two_objects(self) -> None:
        assert a2a_rpc.success("r1", {"ok": 1}) == {
            "jsonrpc": "2.0",
            "id": "r1",
            "result": {"ok": 1},
        }
        assert a2a_rpc.failure(7, a2a_rpc.RpcError(-32001, "no task")) == {
            "jsonrpc": "2.0",
            "id": 7,
            "error": {"code": -32001, "message": "no task"},
        }

    def test_an_error_carries_data_only_when_it_has_some(self) -> None:
        error = a2a_rpc.RpcError(-32004, "gone", {"reason": "not_pending"})

        assert a2a_rpc.failure(1, error)["error"]["data"] == {"reason": "not_pending"}

    @pytest.mark.parametrize(
        "body",
        [
            [],
            {"id": 1, "method": "tasks/get"},
            {"jsonrpc": "2.0", "method": "tasks/get"},
            {"jsonrpc": "2.0", "id": 1, "method": 5},
        ],
    )
    def test_anything_but_one_request_object_is_invalid_request(self, body: object) -> None:
        with pytest.raises(a2a_rpc.RpcError) as refused:
            a2a_rpc.parse_request(body)

        assert refused.value.code == -32600

    def test_params_that_are_not_an_object_are_invalid_params(self) -> None:
        body = {"jsonrpc": "2.0", "id": 1, "method": "tasks/get", "params": [1]}

        with pytest.raises(a2a_rpc.RpcError) as refused:
            a2a_rpc.parse_request(body)

        assert refused.value.code == -32602

    def test_a_request_without_params_has_an_empty_object(self) -> None:
        request = a2a_rpc.parse_request({"jsonrpc": "2.0", "id": None, "method": "tasks/get"})

        assert (request.id, request.method, request.params) == (None, "tasks/get", {})
