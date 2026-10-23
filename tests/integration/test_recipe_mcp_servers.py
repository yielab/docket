"""A recipe may declare pod-scoped MCP servers (``mcp-servers/*.yaml``, ``kind: mcp-server``).

Installed only by ``docket pod update`` (ADR 0012), live for that pod's turns only, never
selectable by another pod, and round-tripped by ``pod export``. See mcp-client.spec.md
("Pod-scoped servers") and config-format.spec.md.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.pods import build_pod

import docket.kernel.templates as _templates
from docket.agent.driver import _load_mcp_tools
from docket.agent.tools import mcp_tools as _mt
from docket.agent.tools.builtins.toolbox import ToolOutcome
from docket.agent.tools.registry import ToolRegistry
from docket.interfaces.cli.commands import pod_config as _pod_config
from docket.kernel.home import Home, current_home, use_home
from docket.teams import config_docs as _config_docs
from docket.teams import pod
from docket.teams import pod_settings as _pod_settings
from docket.teams.apply import model as _model
from docket.teams.apply import plan as _pod_apply
from docket.teams.apply import recipes as _recipes
from docket.teams.apply import write as _write

SUBJECT = "docket.teams.apply.plan"

_SERVER_DOC = """\
kind: mcp-server
name: fakesrv
command: fake-mcp
args: ["--stdio"]
env:
  FAKE_MODE: "1"
access: read
tools: [lookup]
"""


@pytest.fixture(autouse=True)
def _home(tmp_path: Path) -> Iterator[None]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        for project in ("shop", "other"):
            build_pod(project, pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
        yield


def _recipe(tmp_path: Path, *, select: bool = False, doc: str = _SERVER_DOC) -> Path:
    directory = tmp_path / "recipe"
    (directory / "mcp-servers").mkdir(parents=True)
    (directory / "mcp-servers" / "fakesrv.yaml").write_text(doc, encoding="utf-8")
    manifest = "kind: pod\nname: r\n"
    if select:
        manifest += "settings:\n  mcpServers: [fakesrv]\n"
    (directory / "pod.yaml").write_text(manifest, encoding="utf-8")
    return directory


def _apply(project: str, directory: Path) -> _model.ApplyResult:
    return _write.apply(_pod_apply.plan_apply(project, directory))


def test_apply_installs_the_server_for_that_pod_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apply("shop", _recipe(tmp_path))

    assert [s.name for s in _mt.load_mcp_servers("shop")] == ["fakesrv"]
    assert _mt.load_mcp_servers("other") == []
    assert _mt.load_mcp_servers() == []
    server = _mt.load_mcp_servers("shop")[0]
    assert (server.kind, server.tools, server.args) == ("read", ["lookup"], ["--stdio"])

    captured: dict[str, tuple[str, ...]] = {}

    def _spy(registry: ToolRegistry, *, servers: Any = None, role: str = "", **_: Any) -> list[Any]:
        captured["names"] = tuple(s.name for s in (servers or []))
        return []

    monkeypatch.setattr(_mt, "load_mcp_tools", _spy)
    _load_mcp_tools(ToolRegistry(), "implementer", "shop")
    assert captured["names"] == ("fakesrv",)
    _load_mcp_tools(ToolRegistry(), "implementer", "other")
    assert captured["names"] == ()


def test_the_installed_server_reaches_the_registry_narrowed_to_its_tools(tmp_path: Path) -> None:
    _apply("shop", _recipe(tmp_path))
    registry = ToolRegistry()

    def _list(config: _mt.McpServerConfig, timeout: float) -> _mt.McpListResult:
        return _mt.McpListResult(
            ok=True,
            tools=(_mt.McpRemoteTool("lookup", "find"), _mt.McpRemoteTool("edit_file", "write")),
        )

    _mt.load_mcp_tools(
        registry,
        servers=_mt.load_mcp_servers("shop"),
        list_tools=_list,
        call_tool=lambda *a: ToolOutcome(True),
    )
    assert registry.names() == ["mcp__fakesrv__lookup"]


def test_a_second_pod_cannot_select_it(tmp_path: Path) -> None:
    _apply("shop", _recipe(tmp_path))

    assert _pod_settings.PodSettings.coerce("mcpServers", "fakesrv", project="shop") == "fakesrv"
    with pytest.raises(_pod_settings.PodSettingsError, match="another pod"):
        _pod_settings.PodSettings.coerce("mcpServers", "fakesrv", project="other")
    with pytest.raises(_pod_settings.PodSettingsError, match="fakesrv"):
        _pod_settings.PodSettings.coerce("mcpServers", "fakesrv")


def test_a_recipe_may_select_its_own_server_in_the_same_apply(tmp_path: Path) -> None:
    _apply("shop", _recipe(tmp_path, select=True))

    assert _pod_settings.PodSettings.load_for("shop").mcp_servers == ("fakesrv",)


def test_dry_run_lists_it_and_installs_nothing(tmp_path: Path) -> None:
    plan = _pod_apply.plan_apply("shop", _recipe(tmp_path))

    assert [(i.kind, i.name, i.action) for i in plan.items] == [("mcp-server", "fakesrv", "add")]
    assert not (current_home().pod_config_dir("shop") / "mcp-servers.json").exists()
    assert _mt.load_mcp_servers("shop") == []


def test_a_second_identical_apply_skips(tmp_path: Path) -> None:
    directory = _recipe(tmp_path)
    _apply("shop", directory)

    plan = _pod_apply.plan_apply("shop", directory)
    assert [i.action for i in plan.items] == ["skip"]


def test_a_name_that_collides_with_a_global_server_is_refused(tmp_path: Path) -> None:
    _mt.add_mcp_server(_mt.McpServerConfig(name="fakesrv", command="x"))

    with pytest.raises(_model.PodApplyError, match="global"):
        _pod_apply.plan_apply("shop", _recipe(tmp_path))


def test_summarize_recipe_names_the_servers(tmp_path: Path) -> None:
    summary = _recipes.summarize_recipe(_recipe(tmp_path))

    assert summary.mcp_servers == ("fakesrv",)
    assert summary.render().endswith("mcp-servers fakesrv")


def test_export_round_trips_the_server(tmp_path: Path) -> None:
    _apply("shop", _recipe(tmp_path))
    exported = tmp_path / "export"
    _write.export_pod("shop", exported)

    written = exported / "mcp-servers" / "fakesrv.yaml"
    assert written.is_file()
    assert _config_docs.load_document(written).kind == "mcp-server"

    _apply("other", exported)
    assert _mt.load_mcp_servers("other") == _mt.load_mcp_servers("shop")


def test_validate_rejects_a_malformed_server_document(tmp_path: Path) -> None:
    directory = _recipe(tmp_path, doc="kind: mcp-server\nname: fakesrv\naccess: maybe\n")

    errors = _config_docs.validate_directory(directory)
    assert len(errors) == 1


def test_code_intel_validates_and_plans() -> None:
    directory = _templates.RECIPES_DIR / "code-intel"

    assert _config_docs.validate_directory(directory) == []
    plan = _pod_apply.plan_apply("shop", directory)
    assert any(i.kind == "mcp-server" for i in plan.items)


_ISOLATE_DOC = _SERVER_DOC.replace("name: fakesrv", "name: freesrv") + "isolate: false\n"


def test_an_isolate_key_is_an_unknown_key_error(tmp_path: Path) -> None:
    directory = _recipe(tmp_path)
    (directory / "mcp-servers" / "freesrv.yaml").write_text(_ISOLATE_DOC, encoding="utf-8")

    errors = _config_docs.validate_directory(directory)
    assert len(errors) == 1
    assert "isolate" in str(errors[0])
    with pytest.raises(_mt.McpServerDocError):
        _mt.load_mcp_server_document(directory / "mcp-servers" / "freesrv.yaml")


def test_export_writes_no_isolate_key(tmp_path: Path) -> None:
    _apply("shop", _recipe(tmp_path))
    exported = tmp_path / "export"
    _write.export_pod("shop", exported)

    assert "isolate" not in (exported / "mcp-servers" / "fakesrv.yaml").read_text()


def test_the_plan_summary_carries_no_unjailed_note(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = _recipe(tmp_path)
    _pod_config.render_apply_plan(_pod_apply.plan_apply("shop", directory))
    assert "unjailed" not in capsys.readouterr().out
    assert "unjailed" not in _recipes.summarize_recipe(directory).render()


def test_code_intel_servers_declare_no_isolate_key() -> None:
    directory = _templates.RECIPES_DIR / "code-intel"
    for path in (directory / "mcp-servers").glob("*.yaml"):
        assert "isolate" not in path.read_text(encoding="utf-8")
