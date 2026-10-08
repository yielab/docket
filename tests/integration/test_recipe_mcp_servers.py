"""A recipe may declare pod-scoped MCP servers (``mcp-servers/*.yaml``, ``kind: mcp-server``).

Installed only by ``docket pod apply`` (ADR 0012), live for that pod's turns only, never
selectable by another pod, and round-tripped by ``pod export``. See mcp-client.spec.md
("Pod-scoped servers") and config-format.spec.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.cli import _pod as _cli_pod
from docket.cli import _pod_config
from docket.core import config_docs as _config_docs
from docket.core import mcp_tools as _mt
from docket.core import pod
from docket.core import pod_apply as _pod_apply
from docket.core.tools import ToolRegistry
from docket.edges.adapters.docket_runtime import _load_mcp_tools
from docket.edges.adapters.toolbox import ToolOutcome

SUBJECT = "docket.core.pod_apply"

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
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    monkeypatch.setattr(_cfg, "ARCHETYPE_REGISTRY_FILE", tmp_path / "docket-roles.json")
    for project in ("shop", "other"):
        _cli_pod.build_pod(project, pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")


def _recipe(tmp_path: Path, *, select: bool = False, doc: str = _SERVER_DOC) -> Path:
    directory = tmp_path / "recipe"
    (directory / "mcp-servers").mkdir(parents=True)
    (directory / "mcp-servers" / "fakesrv.yaml").write_text(doc, encoding="utf-8")
    manifest = "kind: pod\nname: r\n"
    if select:
        manifest += "settings:\n  mcpServers: [fakesrv]\n"
    (directory / "pod.yaml").write_text(manifest, encoding="utf-8")
    return directory


def _apply(project: str, directory: Path) -> _pod_apply.ApplyResult:
    return _pod_apply.apply(_pod_apply.plan_apply(project, directory))


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

    assert pod.PodSettings.coerce("mcpServers", "fakesrv", project="shop") == "fakesrv"
    with pytest.raises(pod.PodSettingsError, match="another pod"):
        pod.PodSettings.coerce("mcpServers", "fakesrv", project="other")
    with pytest.raises(pod.PodSettingsError, match="fakesrv"):
        pod.PodSettings.coerce("mcpServers", "fakesrv")


def test_a_recipe_may_select_its_own_server_in_the_same_apply(tmp_path: Path) -> None:
    _apply("shop", _recipe(tmp_path, select=True))

    assert pod.PodSettings.load_for("shop").mcp_servers == ("fakesrv",)


def test_dry_run_lists_it_and_installs_nothing(tmp_path: Path) -> None:
    plan = _pod_apply.plan_apply("shop", _recipe(tmp_path))

    assert [(i.kind, i.name, i.action) for i in plan.items] == [("mcp-server", "fakesrv", "add")]
    assert not (_cfg.pod_config_dir("shop") / "mcp-servers.json").exists()
    assert _mt.load_mcp_servers("shop") == []


def test_a_second_identical_apply_skips(tmp_path: Path) -> None:
    directory = _recipe(tmp_path)
    _apply("shop", directory)

    plan = _pod_apply.plan_apply("shop", directory)
    assert [i.action for i in plan.items] == ["skip"]


def test_a_name_that_collides_with_a_global_server_is_refused(tmp_path: Path) -> None:
    _mt.add_mcp_server(_mt.McpServerConfig(name="fakesrv", command="x"))

    with pytest.raises(_pod_apply.PodApplyError, match="global"):
        _pod_apply.plan_apply("shop", _recipe(tmp_path))


def test_summarize_recipe_names_the_servers(tmp_path: Path) -> None:
    summary = _pod_apply.summarize_recipe(_recipe(tmp_path))

    assert summary.mcp_servers == ("fakesrv",)
    assert summary.render().endswith("mcp-servers fakesrv")


def test_export_round_trips_the_server(tmp_path: Path) -> None:
    _apply("shop", _recipe(tmp_path))
    exported = tmp_path / "export"
    _pod_apply.export_pod("shop", exported)

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
    directory = _cfg.recipes_dir() / "code-intel"

    assert _config_docs.validate_directory(directory) == []
    plan = _pod_apply.plan_apply("shop", directory)
    assert any(i.kind == "mcp-server" for i in plan.items)


_FREE_DOC = _SERVER_DOC.replace("name: fakesrv", "name: freesrv") + "isolate: false\n"


def _two_server_recipe(tmp_path: Path) -> Path:
    directory = _recipe(tmp_path)
    (directory / "mcp-servers" / "freesrv.yaml").write_text(_FREE_DOC, encoding="utf-8")
    return directory


def test_isolate_false_is_stored_and_only_that_servers_launch_is_unjailed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mcp")
    from docket.edges.adapters import mcp_client as _client

    monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "bwrap")
    _apply("shop", _two_server_recipe(tmp_path))
    by_name = {s.name: s for s in _mt.load_mcp_servers("shop")}
    assert (by_name["freesrv"].isolate, by_name["fakesrv"].isolate) == (False, True)

    root = tmp_path / "root"
    root.mkdir()
    launch = _mt.StdioLaunch(cwd=str(root), sandbox="auto", network=True, roots=(root,))
    free = _client._stdio_params(by_name["freesrv"], launch)
    caged = _client._stdio_params(by_name["fakesrv"], launch)
    assert (free.command, free.args) == ("fake-mcp", ["--stdio"])
    assert caged.command == "bwrap"


def test_a_document_without_the_field_loads_jailed(tmp_path: Path) -> None:
    path = tmp_path / "s.yaml"
    path.write_text(_SERVER_DOC, encoding="utf-8")
    assert _mt.load_mcp_server_document(path).isolate is True


def test_export_round_trips_isolate_false_and_reapply_skips(tmp_path: Path) -> None:
    _apply("shop", _two_server_recipe(tmp_path))
    exported = tmp_path / "export"
    _pod_apply.export_pod("shop", exported)

    assert "isolate: false" in (exported / "mcp-servers" / "freesrv.yaml").read_text()
    assert "isolate" not in (exported / "mcp-servers" / "fakesrv.yaml").read_text()
    plan = _pod_apply.plan_apply("shop", exported)
    assert {i.action for i in plan.items} == {"skip"}
    _apply("other", exported)
    assert _mt.load_mcp_servers("other") == _mt.load_mcp_servers("shop")


def test_plan_summary_and_validate_say_the_server_runs_unjailed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = _two_server_recipe(tmp_path)
    plan = _pod_apply.plan_apply("shop", directory)
    _pod_config.render_apply_plan(plan)
    out = capsys.readouterr().out
    assert out.count("runs unjailed (isolate: false)") == 1
    assert "freesrv: runs unjailed (isolate: false)" in out
    rendered = _pod_apply.summarize_recipe(directory).render()
    assert rendered.endswith("mcp-servers fakesrv, freesrv · unjailed freesrv")
    assert _config_docs.validate_directory(directory) == []


def test_code_intel_declares_ast_grep_unjailed_and_language_intel_jailed() -> None:
    directory = _cfg.recipes_dir() / "code-intel"
    by_name = {
        c.name: c
        for c in (
            _mt.load_mcp_server_document(p) for p in (directory / "mcp-servers").glob("*.yaml")
        )
    }
    assert by_name["ast-grep"].isolate is False
    assert by_name["language-intel"].isolate is True
