"""One tool per service operation: its name, kind and schema, and the request its handler builds."""

from __future__ import annotations

from typing import Any

from docket.agent.tools import service_tools as _st
from docket.agent.tools.registry import Tool, ToolContext, ToolRegistry
from docket.kernel.service import ServiceConfig
from docket.kernel.tool_outcome import ToolOutcome
from docket.platform import ServiceRequest

SUBJECT = "docket.agent.tools.service_tools"

_CONFIG = ServiceConfig.model_validate(
    {
        "name": "crm",
        "baseUrl": "https://API.example.com/v2",
        "hosts": ["files.example.com"],
        "operations": [
            {
                "name": "get_contact",
                "method": "GET",
                "path": "/contacts/{id}",
                "description": "One contact.",
                "params": [
                    {"name": "id", "in": "path", "type": "integer"},
                    {"name": "verbose", "in": "query", "type": "boolean"},
                    {"name": "q", "in": "query"},
                ],
            },
            {
                "name": "create_contact",
                "method": "POST",
                "path": "/contacts",
                "body": {
                    "type": "object",
                    "properties": {"email": {"type": "string"}},
                    "required": ["email"],
                },
            },
            {"name": "ping", "method": "GET", "path": "/ping", "access": "send"},
        ],
    }
)
_SERVICE = _st.ResolvedService(
    _CONFIG, headers={"Authorization": "Bearer tok-1"}, secrets=("tok-1",)
)


class _Recorder:
    def __init__(self) -> None:
        self.requests: list[ServiceRequest] = []

    def __call__(self, request: ServiceRequest) -> ToolOutcome:
        self.requests.append(request)
        return ToolOutcome(True, content="seen")


def _load(call: _Recorder | None = None) -> tuple[ToolRegistry, _Recorder]:
    recorder = call or _Recorder()
    registry = ToolRegistry()
    _st.load_service_tools(registry, services=[_SERVICE], call=recorder)
    return registry, recorder


def _tool(registry: ToolRegistry, name: str) -> Tool:
    tool = registry.get(name)
    assert tool is not None
    return tool


def _run(tool: Tool, args: dict[str, Any]) -> ToolOutcome:
    return tool.handler(args, ToolContext())


def test_each_operation_is_one_tool_of_its_access() -> None:
    registry, _ = _load()

    assert registry.names() == [
        "svc__crm__create_contact",
        "svc__crm__get_contact",
        "svc__crm__ping",
    ]
    assert [_tool(registry, n).kind for n in registry.names()] == ["send", "read", "send"]


def test_the_description_names_the_service_and_the_operation() -> None:
    registry, _ = _load()

    assert _tool(registry, "svc__crm__get_contact").description == "[service:crm] One contact."
    assert _tool(registry, "svc__crm__ping").description == "[service:crm] GET /ping"


def test_the_schema_has_a_property_per_parameter_and_the_body() -> None:
    registry, _ = _load()

    get = _tool(registry, "svc__crm__get_contact").parameters
    assert get["type"] == "object"
    assert get["properties"] == {
        "id": {"type": "integer"},
        "verbose": {"type": "boolean"},
        "q": {"type": "string"},
    }
    assert get["required"] == ["id"]
    post = _tool(registry, "svc__crm__create_contact").parameters
    assert post["properties"]["body"]["properties"] == {"email": {"type": "string"}}
    assert post["required"] == ["body"]


def test_a_call_builds_the_request_from_the_document_and_the_resolved_header() -> None:
    registry, recorder = _load()

    outcome = _run(_tool(registry, "svc__crm__get_contact"), {"id": 7, "verbose": True})

    assert outcome == ToolOutcome(True, content="seen")
    (request,) = recorder.requests
    assert request == ServiceRequest(
        method="GET",
        base_url="https://API.example.com/v2",
        path="/contacts/{id}",
        path_params={"id": "7"},
        query={"verbose": True},
        headers={"Authorization": "Bearer tok-1"},
        body=None,
        hosts=("files.example.com",),
        secrets=("tok-1",),
    )


def test_a_body_is_sent_as_given() -> None:
    registry, recorder = _load()

    _run(_tool(registry, "svc__crm__create_contact"), {"body": {"email": "a@b.test"}})

    assert recorder.requests[0].body == {"email": "a@b.test"}


def test_an_undeclared_argument_is_refused_before_any_call() -> None:
    registry, recorder = _load()

    outcome = _run(_tool(registry, "svc__crm__get_contact"), {"id": 1, "extra": "x"})

    assert not outcome.ok and outcome.refusal == "service_bad_request"
    assert "extra" in outcome.error and recorder.requests == []


def test_an_argument_of_the_wrong_type_is_refused_naming_it() -> None:
    registry, recorder = _load()

    for args in (
        {"id": True},
        {"id": "seven"},
        {"id": 1, "q": {"a": 1}},
        {"id": 1, "verbose": "y"},
    ):
        outcome = _run(_tool(registry, "svc__crm__get_contact"), args)
        assert not outcome.ok and outcome.refusal == "service_bad_request"
    assert recorder.requests == []


def test_the_audit_detail_names_the_method_and_host_only() -> None:
    registry, _ = _load()

    assert (
        _tool(registry, "svc__crm__get_contact").audit_detail == "method=GET host='api.example.com'"
    )
    assert _tool(registry, "svc__crm__create_contact").audit_detail == (
        "method=POST host='api.example.com'"
    )


def test_a_name_already_registered_is_skipped_never_replaced() -> None:
    registry, _ = _load()
    before = _tool(registry, "svc__crm__ping")

    results = _st.load_service_tools(registry, services=[_SERVICE], call=_Recorder())

    assert _tool(registry, "svc__crm__ping") is before
    assert results[0].ok and results[0].registered == ()


def test_the_load_reports_what_it_registered() -> None:
    registry = ToolRegistry()

    (result,) = _st.load_service_tools(registry, services=[_SERVICE], call=_Recorder())

    assert (result.service, result.ok, result.registered) == (
        "crm",
        True,
        ("svc__crm__get_contact", "svc__crm__create_contact", "svc__crm__ping"),
    )


def test_only_a_delete_operation_s_tool_deletes() -> None:
    config = ServiceConfig.model_validate(
        {
            "name": "crm",
            "baseUrl": "https://api.example.com",
            "operations": [
                {
                    "name": "drop",
                    "method": "DELETE",
                    "path": "/c/{id}",
                    "params": [{"name": "id", "in": "path"}],
                },
                {"name": "add", "method": "POST", "path": "/c"},
                {"name": "get", "method": "GET", "path": "/c"},
            ],
        }
    )
    registry = ToolRegistry()
    _st.load_service_tools(registry, services=[_st.ResolvedService(config)], call=_Recorder())

    flags = {n: (_tool(registry, n).kind, _tool(registry, n).deletes) for n in registry.names()}
    assert flags == {
        "svc__crm__add": ("send", False),
        "svc__crm__drop": ("send", True),
        "svc__crm__get": ("read", False),
    }


_IDEM = "Idempotency-Key"


def _identity_registry(
    idempotency: str = _IDEM, timeout: float = 0.0
) -> tuple[ToolRegistry, _Recorder]:
    config = ServiceConfig.model_validate(
        {
            "name": "crm",
            "baseUrl": "https://api.example.com",
            "idempotencyHeader": idempotency,
            "timeout": timeout,
            "operations": [
                {"name": "get", "method": "GET", "path": "/c"},
                {"name": "add", "method": "POST", "path": "/c", "body": {"type": "object"}},
                {
                    "name": "drop",
                    "method": "DELETE",
                    "path": "/c/{id}",
                    "params": [{"name": "id", "in": "path"}],
                },
            ],
        }
    )
    recorder = _Recorder()
    registry = ToolRegistry()
    service = _st.ResolvedService(config, headers={"Authorization": "Bearer t"})
    _st.load_service_tools(registry, services=[service], call=recorder)
    return registry, recorder


def _ctx(task: str = "t-1", step: str = "build") -> ToolContext:
    return ToolContext(task_id=task, step_id=step)


def _key(tool: str, args: dict[str, Any], ctx: ToolContext, **kw: Any) -> str:
    registry, recorder = _identity_registry(**kw)
    _tool(registry, tool).handler(args, ctx)
    return recorder.requests[0].headers.get(_IDEM, "")


def test_every_call_carries_the_task_id_from_the_hop() -> None:
    registry, recorder = _identity_registry()

    _tool(registry, "svc__crm__get").handler({}, _ctx("t-9"))
    _tool(registry, "svc__crm__get").handler({}, ToolContext())

    assert recorder.requests[0].headers["X-Docket-Task"] == "t-9"
    assert recorder.requests[0].headers["Authorization"] == "Bearer t"
    assert "X-Docket-Task" not in recorder.requests[1].headers


def test_a_model_argument_cannot_name_or_override_either_header() -> None:
    registry, recorder = _identity_registry()

    for name in ("X-Docket-Task", _IDEM, "headers"):
        outcome = _tool(registry, "svc__crm__add").handler({name: "forged", "body": {}}, _ctx())
        assert not outcome.ok and outcome.refusal == "service_bad_request"
    assert recorder.requests == []


def test_a_send_key_is_32_hex_and_stable_for_the_same_call() -> None:
    first = _key("svc__crm__add", {"body": {"a": 1, "b": 2}}, _ctx())
    again = _key("svc__crm__add", {"body": {"b": 2, "a": 1}}, _ctx())

    assert first == again and len(first) == 32 and int(first, 16) >= 0


def test_the_key_changes_with_task_step_body_and_arguments() -> None:
    base = _key("svc__crm__add", {"body": {"a": 1}}, _ctx())

    assert _key("svc__crm__add", {"body": {"a": 1}}, _ctx(task="t-2")) != base
    assert _key("svc__crm__add", {"body": {"a": 1}}, _ctx(step="verify")) != base
    assert _key("svc__crm__add", {"body": {"a": 2}}, _ctx()) != base
    assert _key("svc__crm__drop", {"id": "1"}, _ctx()) != _key(
        "svc__crm__drop", {"id": "2"}, _ctx()
    )


def test_a_read_and_a_service_without_the_header_carry_no_key() -> None:
    assert _key("svc__crm__get", {}, _ctx()) == ""
    assert _key("svc__crm__add", {"body": {}}, _ctx(), idempotency="") == ""


def test_the_documents_timeout_reaches_the_request() -> None:
    registry, recorder = _identity_registry(timeout=7.5)

    _tool(registry, "svc__crm__get").handler({}, _ctx())

    assert recorder.requests[0].timeout == 7.5
