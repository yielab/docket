"""The ``kind: service`` document, its stores and the name rule it shares with MCP servers."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from docket.kernel import mcp as _mcp
from docket.kernel.errors import InvalidInput
from docket.kernel.home import current_home
from docket.teams import mcp_servers as _mcp_servers
from docket.teams import services as _services

SUBJECT = "docket.teams.services"

_DOC: dict[str, Any] = {
    "kind": "service",
    "name": "crm",
    "baseUrl": "https://api.example.com/v2",
    "auth": {"header": "Authorization", "value": "Bearer ${secret:crm}"},
    "hosts": ["files.example.com"],
    "timeout": 20.0,
    "idempotencyHeader": "Idempotency-Key",
    "operations": [
        {
            "name": "get_contact",
            "method": "GET",
            "path": "/contacts/{id}",
            "params": [{"name": "id", "in": "path", "type": "integer", "required": True}],
            "access": "read",
            "description": "One contact.",
        },
        {
            "name": "create_contact",
            "method": "POST",
            "path": "/contacts",
            "body": {"type": "object", "properties": {"email": {"type": "string"}}},
            "access": "send",
        },
    ],
}


def _write(tmp_path: Path, doc: dict[str, Any], name: str = "crm.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return path


def _document(config: Any) -> dict[str, Any]:
    body = config.model_dump(mode="json", by_alias=True, exclude_defaults=True)
    return {"kind": "service", **body}


def _with_operation(**fields: Any) -> dict[str, Any]:
    doc = copy.deepcopy(_DOC)
    doc["operations"] = [{"name": "op", "method": "GET", "path": "/x", **fields}]
    return doc


def test_a_valid_document_round_trips(tmp_path: Path) -> None:
    config = _services.load_service_document(_write(tmp_path, _DOC))

    assert (config.name, config.baseUrl, config.hosts, config.timeout) == (
        "crm",
        "https://api.example.com/v2",
        ["files.example.com"],
        20.0,
    )
    again = _services.load_service_document(_write(tmp_path, _document(config), "again.yaml"))
    assert again == config
    assert _document(config) == _DOC


def test_access_defaults_from_the_method(tmp_path: Path) -> None:
    doc = copy.deepcopy(_DOC)
    doc["operations"] = [
        {"name": "read_it", "method": "GET", "path": "/a"},
        {"name": "post_it", "method": "POST", "path": "/a"},
        {"name": "delete_it", "method": "DELETE", "path": "/a"},
        {"name": "send_get", "method": "GET", "path": "/a", "access": "send"},
    ]
    config = _services.load_service_document(_write(tmp_path, doc))

    assert {op.name: op.access for op in config.operations} == {
        "read_it": "read",
        "post_it": "send",
        "delete_it": "send",
        "send_get": "send",
    }


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_a_write_declared_read_is_refused_naming_the_operation(tmp_path: Path, method: str) -> None:
    doc = _with_operation(method=method, access="read")
    path = _write(tmp_path, doc)

    with pytest.raises(_services.ServiceDocError, match=r"crm\.yaml.*'op'.*send"):
        _services.load_service_document(path)


def test_a_path_placeholder_without_its_param_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, _with_operation(path="/contacts/{id}"))

    with pytest.raises(_services.ServiceDocError, match=r"'op'.*\{id\}|\{id\}.*'op'"):
        _services.load_service_document(path)


def test_a_path_param_missing_from_the_path_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, _with_operation(params=[{"name": "id", "in": "path"}]))

    with pytest.raises(_services.ServiceDocError, match="id"):
        _services.load_service_document(path)


def test_a_secret_reference_round_trips_unresolved(tmp_path: Path) -> None:
    config = _services.load_service_document(_write(tmp_path, _DOC))
    assert config.auth is not None
    assert config.auth.value == "Bearer ${secret:crm}"

    _services.add_service(config)
    (stored,) = _services.load_services()
    assert stored.auth is not None and stored.auth.value == "Bearer ${secret:crm}"
    assert "${secret:crm}" in current_home().services_file.read_text(encoding="utf-8")
    assert _document(stored)["auth"]["value"] == "Bearer ${secret:crm}"


@pytest.mark.parametrize("value", ["Bearer ${secret:}", "Bearer ${secret:a b}", "${secret:crm"])
def test_a_malformed_secret_reference_is_refused(tmp_path: Path, value: str) -> None:
    doc = copy.deepcopy(_DOC)
    doc["auth"]["value"] = value

    with pytest.raises(_services.ServiceDocError, match="auth"):
        _services.load_service_document(_write(tmp_path, doc))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(extra="x"),
        lambda d: d["auth"].update(scheme="bearer"),
        lambda d: d["operations"][0].update(retries=3),
        lambda d: d["operations"][0]["params"][0].update(default=1),
        lambda d: d.update(base_url="https://api.example.com"),
    ],
)
def test_an_unknown_key_is_refused(tmp_path: Path, mutate: Any) -> None:
    doc = copy.deepcopy(_DOC)
    mutate(doc)

    with pytest.raises(_services.ServiceDocError):
        _services.load_service_document(_write(tmp_path, doc))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(name="not a name"),
        lambda d: d.update(baseUrl="ftp://example.com"),
        lambda d: d.update(baseUrl="https://user:pw@example.com"),
        lambda d: d.update(baseUrl="https://example.com/?q=1"),
        lambda d: d.update(timeout=-1),
        lambda d: d["operations"].append(copy.deepcopy(d["operations"][0])),
        lambda d: d["operations"][0].update(method="TRACE"),
        lambda d: d["operations"][0].update(path="contacts"),
        lambda d: d["operations"][0].update(body={"type": "object"}),
        lambda d: d["operations"][1].update(body={"type": "array"}),
        lambda d: d["operations"][0]["params"].append({"name": "id", "in": "query"}),
    ],
)
def test_an_invalid_document_is_refused_as_a_whole(tmp_path: Path, mutate: Any) -> None:
    doc = copy.deepcopy(_DOC)
    mutate(doc)

    with pytest.raises(_services.ServiceDocError, match=r"crm\.yaml"):
        _services.load_service_document(_write(tmp_path, doc))


def test_add_refuses_a_stored_name_and_writes_nothing_more(tmp_path: Path) -> None:
    config = _services.load_service_document(_write(tmp_path, _DOC))
    _services.add_service(config)
    before = current_home().services_file.read_text(encoding="utf-8")

    with pytest.raises(InvalidInput, match="already"):
        _services.add_service(config)
    assert current_home().services_file.read_text(encoding="utf-8") == before


def test_remove_reports_whether_the_service_was_there(tmp_path: Path) -> None:
    _services.add_service(_services.load_service_document(_write(tmp_path, _DOC)))

    assert _services.remove_service("crm") is True
    assert _services.remove_service("crm") is False
    assert _services.load_services() == []


def test_a_pods_own_service_comes_before_the_operators(tmp_path: Path) -> None:
    _services.add_service(_services.load_service_document(_write(tmp_path, _DOC)))
    own = copy.deepcopy(_DOC)
    own["baseUrl"] = "https://pod.example.com"
    folder = current_home().pod_config_dir("shop") / "services"
    folder.mkdir(parents=True)
    (folder / "crm.yaml").write_text(yaml.safe_dump(own), encoding="utf-8")

    (for_shop,) = _services.load_services("shop")
    (for_other,) = _services.load_services("other")

    assert for_shop.baseUrl == "https://pod.example.com"
    assert for_other.baseUrl == "https://api.example.com/v2"


def test_a_service_cannot_take_an_mcp_servers_name(tmp_path: Path) -> None:
    _mcp_servers.add_mcp_server(_mcp.McpServerConfig(name="crm", command="crm-mcp"))
    config = _services.load_service_document(_write(tmp_path, _DOC))

    with pytest.raises(InvalidInput, match=r"MCP server.*crm|crm.*MCP server"):
        _services.add_service(config)
    assert _services.load_services() == []
    assert not current_home().services_file.exists()


def test_a_pod_scoped_mcp_servers_name_is_taken_too(tmp_path: Path) -> None:
    (current_home().pods_dir / "shop").mkdir(parents=True)
    _mcp_servers.write_pod_mcp_servers(
        "shop", [_mcp.McpServerConfig(name="crm", command="crm-mcp")]
    )
    config = _services.load_service_document(_write(tmp_path, _DOC))

    with pytest.raises(InvalidInput, match="shop"):
        _services.add_service(config)


def test_an_mcp_name_is_refused_when_a_service_holds_it(tmp_path: Path) -> None:
    _services.add_service(_services.load_service_document(_write(tmp_path, _DOC)))

    assert "crm" in _services.service_name_conflict("crm")
    assert _services.service_name_conflict("other") == ""
