"""A service call names its task: ``X-Docket-Task`` on every call, and an idempotency key on a
``send`` operation of a service that declares the header, built from the hop and never from the
model. The oracle is a loopback HTTP server that records the headers it saw, the real driver and a
scripted model; a ``send`` call runs on a pre-grant, as a resumed hop's does."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.support.llm import RecordingScriptedBackend as _ScriptedBackend
from tests.support.llm import final as _final
from tests.support.llm import tool_calls
from tests.support.pods import write_meta_overrides as _write_meta
from tests.support.roles import write_role_overlay
from tests.support.turns import run_turn

from docket.agent.ports import (
    DOCKET_HOP_STEP,
    DOCKET_PREGRANTS,
)
from docket.governance import approval_pregrant as _pregrant
from docket.governance import secrets as _secrets
from docket.kernel.operator_contract import canonical_args_digest
from docket.kernel.service import ServiceConfig
from docket.teams import fleet as _fleet
from docket.teams import services as _services

SUBJECT = "docket.hops.application.driver_support"

_KEY = "Idempotency-Key"
_SEND = "svc__crm__create_contact"
_BODY = {"email": "a@b.test"}


def _service(base: str, *, idempotency: str = _KEY) -> ServiceConfig:
    return ServiceConfig.model_validate(
        {
            "name": "crm",
            "baseUrl": base,
            "hosts": ["127.0.0.1"],
            "auth": {"header": "Authorization", "value": "Bearer ${secret:crm}"},
            "idempotencyHeader": idempotency,
            "operations": [
                {"name": "list_contacts", "method": "GET", "path": "/contacts"},
                {
                    "name": "create_contact",
                    "method": "POST",
                    "path": "/contacts",
                    "body": {"type": "object", "properties": {"email": {"type": "string"}}},
                },
            ],
        }
    )


@pytest.fixture
def world(tmp_path: Path) -> None:
    _fleet.disable_sandbox_isolation()
    code = tmp_path / "code"
    code.mkdir()
    _write_meta("impl-1", role="implementer", codebase=str(code))
    _secrets.save_secrets({"crm": "tok-0123456789"})
    write_role_overlay("acme", "implementer", [], extra="tools: [read, svc__crm]\n")


def _pregrants(name: str, arguments: dict[str, Any], count: int) -> str:
    digest = canonical_args_digest(name, arguments)
    return json.dumps(
        [
            {
                "token": _pregrant.create_pregrant(
                    "acme", "implementer", name, digest, channel="cli"
                ),
                "tool": name,
                "argsDigest": digest,
            }
            for _ in range(count)
        ]
    )


def _turn(
    backend: _ScriptedBackend, task: str, *, step: str = "build", pregrants: str = ""
) -> None:
    env = {DOCKET_HOP_STEP: step}
    if pregrants:
        env[DOCKET_PREGRANTS] = pregrants
    run_turn(backend, env, trace_project="acme", trace_task_id=task)


def _send_twice(task: str, *, step: str = "build") -> None:
    args = {"body": _BODY}
    backend = _ScriptedBackend([tool_calls((_SEND, args), (_SEND, args)), _final("done")])
    _turn(backend, task, step=step, pregrants=_pregrants(_SEND, args, 2))


class TestEveryCallNamesItsTask:
    def test_a_read_call_carries_the_task_id_and_no_idempotency_key(
        self, world: None, service_server: tuple[str, list[dict[str, Any]]]
    ) -> None:
        base, seen = service_server
        _services.add_service(_service(base))
        backend = _ScriptedBackend([tool_calls(("svc__crm__list_contacts", {})), _final("done")])

        _turn(backend, "t-1")

        (request,) = seen
        headers = request["headers"]
        assert headers["x-docket-task"] == "t-1"
        assert _KEY.lower() not in headers

    def test_a_send_call_carries_the_task_id_too(
        self, world: None, service_server: tuple[str, list[dict[str, Any]]]
    ) -> None:
        base, seen = service_server
        _services.add_service(_service(base))

        _send_twice("t-1")

        assert [h["headers"]["x-docket-task"] for h in seen] == ["t-1", "t-1"]


class TestASendCallCarriesAnIdempotencyKey:
    def test_identical_calls_in_one_step_share_a_key_and_another_task_or_step_has_another(
        self, world: None, service_server: tuple[str, list[dict[str, Any]]]
    ) -> None:
        base, seen = service_server
        _services.add_service(_service(base))

        _send_twice("t-1")
        _send_twice("t-2")
        _send_twice("t-1", step="verify")

        keys = [h["headers"][_KEY.lower()] for h in seen]
        assert keys[0] == keys[1]
        assert keys[2] == keys[3] and keys[4] == keys[5]
        assert len({keys[0], keys[2], keys[4]}) == 3
        assert all(len(k) == 32 and int(k, 16) >= 0 for k in keys)

    def test_a_service_that_declares_no_header_sends_none(
        self, world: None, service_server: tuple[str, list[dict[str, Any]]]
    ) -> None:
        base, seen = service_server
        _services.add_service(_service(base, idempotency=""))

        _send_twice("t-1")

        assert len(seen) == 2
        assert not [k for h in seen for k in h["headers"] if "idempotency" in k]
