"""``docket setup service add|list|remove`` and the pod path of a ``kind: service`` document:
``pod update`` carries ``services/`` into the pod overlay and ``pod export`` writes it back."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from tests.support.pods import build_pod
from typer.testing import CliRunner

from docket.governance import audit as _audit
from docket.governance import secrets as _secrets
from docket.interfaces.cli.app import app
from docket.kernel import mcp as _mcp
from docket.kernel.home import Home, current_home, use_home
from docket.teams import mcp_servers as _mcp_servers
from docket.teams import pod
from docket.teams import services as _services
from docket.teams.apply import model as _model
from docket.teams.apply import plan as _pod_apply
from docket.teams.apply import write as _write

SUBJECT = "docket.interfaces.cli.commands.setup_service"

_runner = CliRunner()

_DOC = """\
kind: service
name: crm
baseUrl: https://api.example.com/v2
auth:
  header: Authorization
  value: Bearer ${secret:crm}
operations:
  - name: get_contact
    method: GET
    path: /contacts/{id}
    params:
      - {name: id, in: path, type: integer}
  - name: create_contact
    method: POST
    path: /contacts
    body: {type: object, properties: {email: {type: string}}}
"""


@pytest.fixture(autouse=True)
def _pods_home(tmp_path: Path) -> Iterator[None]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        for project in ("shop", "other"):
            build_pod(project, pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
        yield


def _file(tmp_path: Path, text: str = _DOC, name: str = "crm.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _svc(*args: str) -> tuple[int, str]:
    result = _runner.invoke(app, ["setup", "service", *args])
    return result.exit_code, result.output


def _recipe(tmp_path: Path, *, mcp: bool = False) -> Path:
    directory = tmp_path / "recipe"
    (directory / "services").mkdir(parents=True, exist_ok=True)
    (directory / "services" / "crm.yaml").write_text(_DOC, encoding="utf-8")
    if mcp:
        (directory / "mcp-servers").mkdir(exist_ok=True)
        (directory / "mcp-servers" / "crm.yaml").write_text(
            "kind: mcp-server\nname: crm\ncommand: crm-mcp\n", encoding="utf-8"
        )
    (directory / "pod.yaml").write_text("kind: pod\nname: r\n", encoding="utf-8")
    return directory


def _update(project: str, directory: Path) -> _model.ApplyResult:
    return _write.apply(_pod_apply.plan_apply(project, directory))


def test_add_list_and_remove(tmp_path: Path) -> None:
    code, out = _svc("add", str(_file(tmp_path)))
    assert code == 0, out
    assert "get_contact" in out and "read" in out
    assert "create_contact" in out and "send" in out
    assert [s.name for s in _services.load_services()] == ["crm"]

    code, out = _svc("list")
    assert code == 0
    assert "crm" in out and "api.example.com" in out

    code, out = _svc("remove", "crm")
    assert code == 0, out
    assert _services.load_services() == []
    actions = [e["action"] for e in _audit.read_audit()]
    assert "services.add" in actions and "services.remove" in actions


def test_list_json_shows_no_literal_credential(tmp_path: Path) -> None:
    literal = _DOC.replace("Bearer ${secret:crm}", "Bearer sk-live-123")
    assert _svc("add", str(_file(tmp_path, literal)))[0] == 0

    code, out = _svc("list", "--json")

    assert code == 0
    (entry,) = json.loads(out)
    assert entry["name"] == "crm" and entry["operations"] == 2
    assert "sk-live-123" not in out


def test_the_audit_never_carries_an_auth_value(tmp_path: Path) -> None:
    literal = _DOC.replace("Bearer ${secret:crm}", "Bearer sk-live-123")
    _svc("add", str(_file(tmp_path, literal)))

    assert "sk-live-123" not in json.dumps(_audit.read_audit())


def test_an_unstored_secret_warns_and_a_stored_one_does_not(tmp_path: Path) -> None:
    _, out = _svc("add", str(_file(tmp_path)))
    assert "crm" in out and "secret" in out.lower()
    _svc("remove", "crm")

    _secrets.store_secret("crm", "token")
    code, out = _svc("add", str(_file(tmp_path)))

    assert code == 0
    assert "no secret named" not in out


def test_a_refused_document_exits_one_and_writes_nothing(tmp_path: Path) -> None:
    bad = _DOC.replace("method: POST", "method: POST\n    access: read")

    code, out = _svc("add", str(_file(tmp_path, bad)))

    assert code == 1
    assert "create_contact" in out
    assert not current_home().services_file.exists()


def test_a_stored_name_and_an_unknown_remove_exit_one(tmp_path: Path) -> None:
    _svc("add", str(_file(tmp_path)))
    before = current_home().services_file.read_text(encoding="utf-8")

    assert _svc("add", str(_file(tmp_path)))[0] == 1
    assert current_home().services_file.read_text(encoding="utf-8") == before
    assert _svc("remove", "ghost")[0] == 1


def test_a_name_an_mcp_server_holds_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    _mcp_servers.add_mcp_server(_mcp.McpServerConfig(name="crm", command="crm-mcp"))

    code, out = _svc("add", str(_file(tmp_path)))

    assert code == 1
    assert "MCP server" in out
    assert not current_home().services_file.exists()


def test_a_name_a_service_holds_is_refused_to_an_mcp_server(tmp_path: Path) -> None:
    _svc("add", str(_file(tmp_path)))

    result = _runner.invoke(app, ["setup", "mcp", "add", "crm", "--", "crm-mcp"])

    assert result.exit_code == 1
    assert "service" in result.output
    assert _mcp_servers.load_mcp_servers() == []


def test_a_recipe_declaring_both_is_refused_and_writes_nothing(tmp_path: Path) -> None:
    with pytest.raises(_model.PodApplyError, match="crm"):
        _pod_apply.plan_apply("shop", _recipe(tmp_path, mcp=True))

    assert _services.load_pod_services("shop") == []


def test_a_recipe_service_against_a_stored_mcp_server_or_service_is_refused(
    tmp_path: Path,
) -> None:
    _mcp_servers.add_mcp_server(_mcp.McpServerConfig(name="crm", command="crm-mcp"))
    with pytest.raises(_model.PodApplyError, match="crm"):
        _pod_apply.plan_apply("shop", _recipe(tmp_path))
    _mcp_servers.remove_mcp_server("crm")

    _services.add_service(_services.load_service_document(_file(tmp_path)))
    with pytest.raises(_model.PodApplyError, match="crm"):
        _pod_apply.plan_apply("shop", _recipe(tmp_path))


def test_pod_update_carries_services_into_that_pod_only(tmp_path: Path) -> None:
    result = _update("shop", _recipe(tmp_path))

    assert [(i.kind, i.name) for i in result.items if i.kind == "service"] == [("service", "crm")]
    assert [s.name for s in _services.load_services("shop")] == ["crm"]
    assert _services.load_services("other") == []
    assert _services.load_services() == []
    again = _pod_apply.plan_apply("shop", _recipe(tmp_path))
    assert [i.action for i in again.items if i.kind == "service"] == ["skip"]


def test_pod_update_records_a_service_in_the_lock(tmp_path: Path) -> None:
    _update("shop", _recipe(tmp_path))

    lock = json.loads((current_home().pod_config_dir("shop") / "applied.lock").read_text())
    (item,) = [i for i in lock["items"] if i["kind"] == "service"]
    assert item["name"] == "crm" and item["applied"] == "services/crm.yaml"


def test_pod_export_writes_the_service_back(tmp_path: Path) -> None:
    _update("shop", _recipe(tmp_path))
    exported = tmp_path / "export"
    _write.export_pod("shop", exported)

    written = exported / "services" / "crm.yaml"
    assert yaml.safe_load(written.read_text())["name"] == "crm"
    assert "${secret:crm}" in written.read_text()
    _update("other", exported)
    assert _services.load_services("other") == _services.load_services("shop")


_CRM_OPENAPI = Path(__file__).parents[2] / "fixtures" / "openapi" / "crm.yaml"


def test_from_openapi_stores_a_service_the_loader_reads(tmp_path: Path) -> None:
    code, out = _svc(
        "add", "crm", "--from-openapi", str(_CRM_OPENAPI), "--auth-header", "Authorization",
        "--secret", "crm",
    )  # fmt: skip

    assert code == 0, out
    assert "listClients" in out and "createClient" in out
    assert "uploadAvatar" in out and "multipart/form-data" in out
    (stored,) = _services.load_services()
    assert stored.name == "crm" and stored.baseUrl == "https://api.example.test/v1"
    assert {op.name: op.access for op in stored.operations} == {
        "listClients": "read",
        "createClient": "send",
        "getClient": "read",
        "deleteClient": "send",
    }
    assert stored.auth is not None and stored.auth.value == "${secret:crm}"
    assert "no secret named 'crm'" in out
    assert "services.add" in [e["action"] for e in _audit.read_audit()]
    exported = tmp_path / "crm.yaml"
    exported.write_text(
        yaml.safe_dump({"kind": "service", **stored.model_dump(mode="json", by_alias=True)}),
        encoding="utf-8",
    )
    assert _services.load_service_document(exported) == stored


def test_from_openapi_operations_narrows(tmp_path: Path) -> None:
    code, out = _svc(
        "add", "crm", "--from-openapi", str(_CRM_OPENAPI), "--operations", "getClient,listClients"
    )

    assert code == 0, out
    assert [op.name for op in _services.load_services()[0].operations] == [
        "listClients",
        "getClient",
    ]
    assert _svc("remove", "crm")[0] == 0
    code, out = _svc("add", "crm", "--from-openapi", str(_CRM_OPENAPI), "--operations", "ghost")
    assert code == 1 and "ghost" in out
    assert _services.load_services() == []


def test_from_openapi_refusals_write_nothing(tmp_path: Path) -> None:
    junk = _file(tmp_path, "swagger: '2.0'\n", "old.yaml")

    code, out = _svc("add", "crm", "--from-openapi", str(junk))

    assert code == 1 and "OpenAPI 3" in out
    assert _svc("add", "crm", "--from-openapi", str(_CRM_OPENAPI), "--secret", "x")[0] == 1
    _mcp_servers.add_mcp_server(_mcp.McpServerConfig(name="crm", command="crm-mcp"))
    code, out = _svc("add", "crm", "--from-openapi", str(_CRM_OPENAPI))
    assert code == 1 and "MCP server" in out
    assert not current_home().services_file.exists()


def test_openapi_options_without_from_openapi_are_a_usage_error(tmp_path: Path) -> None:
    for option in (
        ["--operations", "a"],
        ["--base-url", "https://x.example.test"],
        ["--secret", "s"],
    ):
        code, _ = _svc("add", str(_file(tmp_path)), *option)
        assert code == 2
    assert not current_home().services_file.exists()
