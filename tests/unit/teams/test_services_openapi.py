"""Operations imported from an OpenAPI document into a ``kind: service`` configuration."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from docket.kernel.errors import InvalidInput
from docket.teams import services_openapi as _openapi

SUBJECT = "docket.teams.services_openapi"

_FIXTURE = Path(__file__).parents[2] / "fixtures" / "openapi" / "crm.yaml"


def _document(**paths: Any) -> dict[str, Any]:
    doc = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    if paths:
        doc["paths"] = paths
    return doc


def _write(tmp_path: Path, doc: dict[str, Any], name: str = "api.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return path


def _ops(result: _openapi.OpenApiImport) -> dict[str, Any]:
    return {op.name: op for op in result.config.operations}


def test_a_get_is_a_read_with_its_query_params() -> None:
    result = _openapi.import_openapi(_FIXTURE, "crm")

    op = _ops(result)["listClients"]
    assert (op.method, op.path, op.access, op.description) == (
        "GET",
        "/clients",
        "read",
        "List clients.",
    )
    assert [(p.name, p.in_, p.type, p.required) for p in op.params] == [
        ("limit", "query", "integer", False),
        ("status", "query", "string", True),
    ]


def test_a_post_is_a_send_with_its_resolved_body() -> None:
    op = _ops(_openapi.import_openapi(_FIXTURE, "crm"))["createClient"]

    assert (op.method, op.access) == ("POST", "send")
    assert op.body is not None
    assert op.body["required"] == ["email"]
    assert op.body["properties"]["address"] == {
        "type": "object",
        "properties": {"city": {"type": "string"}},
    }
    assert "$ref" not in str(op.body)


def test_path_item_params_merge_and_a_delete_is_a_send() -> None:
    ops = _ops(_openapi.import_openapi(_FIXTURE, "crm"))

    assert [(p.name, p.in_, p.type, p.required) for p in ops["getClient"].params] == [
        ("clientId", "path", "integer", True)
    ]
    assert (ops["deleteClient"].access, ops["deleteClient"].path) == ("send", "/clients/{clientId}")


def test_what_cannot_be_mapped_is_skipped_and_listed() -> None:
    result = _openapi.import_openapi(_FIXTURE, "crm")

    assert "uploadAvatar" not in _ops(result)
    assert any("uploadAvatar" in line and "multipart/form-data" in line for line in result.skipped)
    assert any("GET /health" in line and "operationId" in line for line in result.skipped)
    assert any("X-Request-Id" in line for line in result.notes)
    assert set(_ops(result)) == {"listClients", "createClient", "getClient", "deleteClient"}


def test_operations_narrows_and_an_unknown_id_is_refused() -> None:
    result = _openapi.import_openapi(_FIXTURE, "crm", operations=["getClient", "uploadAvatar"])

    assert list(_ops(result)) == ["getClient"]
    assert any("uploadAvatar" in line for line in result.skipped)
    assert not any("listClients" in line for line in result.skipped)
    with pytest.raises(InvalidInput, match="noSuchOp"):
        _openapi.import_openapi(_FIXTURE, "crm", operations=["getClient", "noSuchOp"])


def test_the_base_url_comes_from_the_flag_else_the_first_server() -> None:
    assert _openapi.import_openapi(_FIXTURE, "crm").config.baseUrl == "https://api.example.test/v1"
    flagged = _openapi.import_openapi(_FIXTURE, "crm", base_url="https://other.example.com/api")
    assert flagged.config.baseUrl == "https://other.example.com/api"


@pytest.mark.parametrize("servers", [[{"url": "/v1"}], [{"url": "https://{env}.example.test"}], []])
def test_no_usable_server_asks_for_a_base_url(tmp_path: Path, servers: list[Any]) -> None:
    doc = _document()
    doc["servers"] = servers

    with pytest.raises(InvalidInput, match="--base-url"):
        _openapi.import_openapi(_write(tmp_path, doc), "crm")


def test_auth_is_a_secret_reference_never_a_value() -> None:
    result = _openapi.import_openapi(_FIXTURE, "crm", auth_header="Authorization", secret="crm")

    assert result.config.auth is not None
    assert (result.config.auth.header, result.config.auth.value) == (
        "Authorization",
        "${secret:crm}",
    )
    assert _openapi.import_openapi(_FIXTURE, "crm").config.auth is None
    with pytest.raises(InvalidInput, match="together"):
        _openapi.import_openapi(_FIXTURE, "crm", auth_header="Authorization")


def test_a_ref_outside_the_file_or_a_cycle_skips_the_operation(tmp_path: Path) -> None:
    doc = _document()
    doc["paths"]["/clients"]["post"]["requestBody"]["content"]["application/json"]["schema"] = {
        "$ref": "other.yaml#/components/schemas/NewClient"
    }
    doc["components"]["schemas"]["Loop"] = {
        "type": "object",
        "properties": {"next": {"$ref": "#/components/schemas/Loop"}},
    }
    doc["paths"]["/clients/{clientId}"]["delete"]["requestBody"] = {
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Loop"}}}
    }
    result = _openapi.import_openapi(_write(tmp_path, doc), "crm")

    assert "createClient" not in _ops(result)
    assert "deleteClient" not in _ops(result)
    assert any("createClient" in line and "other.yaml" in line for line in result.skipped)
    assert any("deleteClient" in line and "cycle" in line for line in result.skipped)


def test_an_operation_the_document_rules_refuse_is_skipped(tmp_path: Path) -> None:
    doc = _document()
    doc["paths"]["/clients"]["get"]["requestBody"] = {
        "content": {"application/json": {"schema": {"type": "object"}}}
    }
    doc["paths"]["/clients/{clientId}"]["get"]["operationId"] = "get.client"

    result = _openapi.import_openapi(_write(tmp_path, doc), "crm")

    assert "listClients" not in _ops(result) and "getClient" not in _ops(result)
    assert any("listClients" in line and "GET" in line for line in result.skipped)
    assert any("get.client" in line for line in result.skipped)


def test_a_repeated_operation_id_keeps_the_first(tmp_path: Path) -> None:
    doc = _document()
    doc["paths"]["/clients/{clientId}"]["delete"]["operationId"] = "getClient"

    result = _openapi.import_openapi(_write(tmp_path, doc), "crm")

    assert _ops(result)["getClient"].method == "GET"
    assert any("getClient" in line and "twice" in line for line in result.skipped)


def test_nothing_mappable_is_refused_listing_why(tmp_path: Path) -> None:
    doc = _document()
    doc["paths"] = {"/health": copy.deepcopy(doc["paths"]["/health"])}

    with pytest.raises(InvalidInput, match="operationId"):
        _openapi.import_openapi(_write(tmp_path, doc), "crm")


def test_openapi_2_and_unreadable_files_are_refused(tmp_path: Path) -> None:
    old = _write(tmp_path, {"swagger": "2.0", "paths": {}}, "old.yaml")
    junk = tmp_path / "junk.yaml"
    junk.write_text("- just\n- a list\n", encoding="utf-8")

    with pytest.raises(InvalidInput, match=r"old\.yaml.*OpenAPI 3"):
        _openapi.import_openapi(old, "crm")
    with pytest.raises(InvalidInput, match=r"junk\.yaml"):
        _openapi.import_openapi(junk, "crm")
    with pytest.raises(InvalidInput, match="missing"):
        _openapi.import_openapi(tmp_path / "missing.yaml", "crm")


def test_a_json_document_reads_the_same(tmp_path: Path) -> None:
    import json

    path = tmp_path / "crm.json"
    path.write_text(json.dumps(_document()), encoding="utf-8")

    assert (
        _openapi.import_openapi(path, "crm").config
        == _openapi.import_openapi(_FIXTURE, "crm").config
    )
