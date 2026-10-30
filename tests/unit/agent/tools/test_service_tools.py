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
