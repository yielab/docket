"""The typed service config: access resolved from the method, secret references named."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from docket.kernel import service as _service

SUBJECT = "docket.kernel.service"


def _config(**operation: Any) -> dict[str, Any]:
    return {
        "name": "crm",
        "baseUrl": "https://api.example.com",
        "operations": [{"name": "op", "path": "/x", **operation}],
    }


def test_access_is_resolved_into_the_typed_operation() -> None:
    get = _service.ServiceConfig.model_validate(_config(method="GET"))
    post = _service.ServiceConfig.model_validate(_config(method="POST"))

    assert get.operations[0].access == "read"
    assert post.operations[0].access == "send"


def test_a_write_declared_read_names_the_operation() -> None:
    with pytest.raises(ValidationError, match="'op'"):
        _service.ServiceConfig.model_validate(_config(method="PUT", access="read"))


def test_secret_names_lists_each_reference_in_order() -> None:
    assert _service.secret_names("Bearer ${secret:a} ${secret:b.c}") == ["a", "b.c"]
    assert _service.secret_names("token") == []


def test_a_service_name_with_a_double_underscore_is_refused_naming_the_field() -> None:
    with pytest.raises(ValidationError, match=r"name"):
        _service.ServiceConfig.model_validate({**_config(method="GET"), "name": "my__crm"})


def test_a_single_underscore_in_a_service_name_is_fine() -> None:
    assert _service.ServiceConfig.model_validate({**_config(method="GET"), "name": "my_crm"})


def test_tool_names_are_built_and_read_back_by_one_pair_of_functions() -> None:
    assert _service.service_tool_name("crm", "get_contact") == "svc__crm__get_contact"
    assert _service.service_tool_name("crm") == "svc__crm"
    assert _service.service_of_tool("svc__crm__get_contact") == "crm"
    assert _service.service_of_tool("svc__crm__a__b") == "crm"


def test_a_name_that_is_not_a_service_operation_has_no_service() -> None:
    for name in ("svc__crm", "svc__", "mcp__crm__x", "read", "svc__crm__"):
        assert _service.service_of_tool(name) == ""
