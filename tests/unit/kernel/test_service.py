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
