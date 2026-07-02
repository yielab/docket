"""AA-3: pod provisioning + the `docket pod` command (hermetic, no daemon)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer

import docket.config as _cfg
from docket.cli import _pod
from docket.edges.adapters import openclaw as _oc


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _point_at(oc_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_file = oc_dir / "openclaw.json"
    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", oc_dir / "docket-models.json", raising=True)
    monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_oc, "meta_path", _cfg.meta_path, raising=True)


def _fake_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend openclaw is present; register/unregister mutate agents.list."""
    monkeypatch.setattr(_pod.shutil, "which", lambda _name: "/usr/bin/openclaw")

    def _register(agent_id: str, workspace: str, model: str) -> tuple[bool, str]:
        raw = json.loads(_cfg.CONFIG_FILE.read_text())
        raw.setdefault("agents", {}).setdefault("list", []).append(
            {"id": agent_id, "model": model, "metadata": {}}
        )
        _cfg.CONFIG_FILE.write_text(json.dumps(raw))
        return (True, "")

    def _unregister(agent_id: str) -> tuple[bool, str]:
        raw = json.loads(_cfg.CONFIG_FILE.read_text())
        raw["agents"]["list"] = [a for a in raw["agents"]["list"] if a["id"] != agent_id]
        _cfg.CONFIG_FILE.write_text(json.dumps(raw))
        return (True, "")

    monkeypatch.setattr(_oc, "register_agent_cli", _register)
    monkeypatch.setattr(_oc, "unregister_agent_cli", _unregister)


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    oc_dir = tmp_path / ".openclaw"
    (oc_dir / "workspaces" / "projects").mkdir(parents=True)
    cfg_file = oc_dir / "openclaw.json"
    cfg_file.write_text(json.dumps({"agents": {"list": []}, "bindings": [], "channels": {}}))
    _point_at(oc_dir, monkeypatch)
    _fake_daemon(monkeypatch)
    return oc_dir


def _ids(oc_dir: Path) -> list[str]:
    raw = json.loads((oc_dir / "openclaw.json").read_text())
    return [a["id"] for a in raw["agents"]["list"]]


def _meta(oc_dir: Path, member_id: str) -> dict:
    p = oc_dir / "workspaces" / "projects" / member_id / ".docket-meta.json"
    return json.loads(p.read_text())


class TestBuildPod:
    def test_default_lean_pod_is_lead_plus_implementer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        created = _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        assert created == ["demo-lead", "demo-implementer"]
        assert set(_ids(oc_dir)) == {"demo-lead", "demo-implementer"}

    def test_members_have_correct_meta_and_shared_session_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        for mid, role in (("demo-lead", "lead"), ("demo-implementer", "implementer")):
            m = _meta(oc_dir, mid)
            assert m["kind"] == "project"
            assert m["scope"] == "project"
            assert m["role"] == role
            assert m["pod"] == "demo"
            assert m["sessionKey"] == "agent:demo:default"
            assert m["modelSource"] == "policy"
            assert (oc_dir / "workspaces" / "projects" / mid / "SOUL.md").is_file()
            # Pod-member meta must round-trip through the AgentMeta model — a
            # regression for templateVersion being written as an int (which made
            # the first metadata write after provisioning raise ValidationError).
            from docket.core.models import AgentMeta

            assert AgentMeta.model_validate(m).template_version == str(_pod.POD_TEMPLATE_VERSION)

    def test_lead_soul_forbids_editing_implementer_has_codebase(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        lead = (oc_dir / "workspaces" / "projects" / "demo-lead" / "SOUL.md").read_text()
        impl = (oc_dir / "workspaces" / "projects" / "demo-implementer" / "SOUL.md").read_text()
        assert "NEVER edit code" in lead
        assert "inside" in impl and "/src/demo" in impl
        # No leftover shared-specialist language anywhere in the pod.
        assert "shared specialist" not in (lead + impl).lower()

    def test_full_pod_has_four_members(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.FULL_POD_ROLES)
        assert set(_ids(oc_dir)) == {
            "demo-lead",
            "demo-implementer",
            "demo-reviewer",
            "demo-tester",
        }


class TestPodCommand:
    def test_add_second_implementer_is_indexed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod.dispatch("demo", "add", ["implementer"])
        assert "demo-implementer-2" in _ids(oc_dir)

    def test_add_reviewer(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod.dispatch("demo", "add", ["reviewer"])
        assert "demo-reviewer" in _ids(oc_dir)

    def test_add_count_two_makes_two_implementers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod.dispatch("demo", "add", ["implementer", "--count", "2"])
        ids = _ids(oc_dir)
        assert "demo-implementer-2" in ids
        assert "demo-implementer-3" in ids

    def test_add_second_lead_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        with pytest.raises(typer.Exit):
            _pod.dispatch("demo", "add", ["lead"])

    def test_remove_member(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod.dispatch("demo", "add", ["reviewer"])
        _pod.dispatch("demo", "remove", ["demo-reviewer"])
        assert "demo-reviewer" not in _ids(oc_dir)
        assert not (oc_dir / "workspaces" / "projects" / "demo-reviewer").exists()

    def test_remove_rejects_foreign_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        with pytest.raises(typer.Exit):
            _pod.dispatch("demo", "remove", ["other-lead"])

    def test_member_ids_lists_lead_first(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.FULL_POD_ROLES)
        assert _pod.pod_member_ids("demo")[0] == "demo-lead"


class TestParsePodRoles:
    def test_default_is_lean(self) -> None:
        assert _pod.parse_pod_roles([]) == ("lead", "implementer")

    def test_pod_full(self) -> None:
        assert _pod.parse_pod_roles(["--pod", "full"]) == _pod.pod.FULL_POD_ROLES

    def test_with_adds_roles(self) -> None:
        assert _pod.parse_pod_roles(["--with", "reviewer,tester"]) == (
            "lead",
            "implementer",
            "reviewer",
            "tester",
        )

    def test_with_equals_form_and_unknown_ignored(self) -> None:
        assert _pod.parse_pod_roles(["--with=reviewer,wizard"]) == (
            "lead",
            "implementer",
            "reviewer",
        )


class TestDeletePod:
    def test_delete_pod_removes_all_members(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket import cli

        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.FULL_POD_ROLES)
        # Non-TTY → _delete_pod skips the interactive confirm.
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        cli._delete_pod("demo", _pod.pod_member_ids("demo"))
        assert _ids(oc_dir) == []
        assert not (oc_dir / "workspaces" / "projects" / "demo-lead").exists()


class TestParseAddArgs:
    """FD-1: `--verify` parsing in `_parse_add_args`."""

    def test_role_only(self) -> None:
        assert _pod._parse_add_args(["implementer"]) == ("implementer", 1, "")

    def test_count_only(self) -> None:
        assert _pod._parse_add_args(["implementer", "--count", "2"]) == ("implementer", 2, "")

    def test_verify_space_form(self) -> None:
        assert _pod._parse_add_args(["implementer", "--verify", "npm test"]) == (
            "implementer",
            1,
            "npm test",
        )

    def test_verify_equals_form(self) -> None:
        assert _pod._parse_add_args(["implementer", "--verify=npm test"]) == (
            "implementer",
            1,
            "npm test",
        )

    def test_verify_and_count_combined(self) -> None:
        assert _pod._parse_add_args(["implementer", "--count", "2", "--verify", "make check"]) == (
            "implementer",
            2,
            "make check",
        )

    def test_no_verify_defaults_empty(self) -> None:
        assert _pod._parse_add_args(["reviewer"]) == ("reviewer", 1, "")


class TestPodAddVerify:
    """FD-1: `docket pod <project> add --verify` sets `verifyCmd` + TOOLS.md."""

    def test_add_implementer_with_verify_sets_meta(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod.dispatch("demo", "add", ["implementer", "--verify", "npm test"])
        m = _meta(oc_dir, "demo-implementer-2")
        assert m["verifyCmd"] == "npm test"

    def test_add_implementer_with_verify_writes_tools_md(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod.dispatch("demo", "add", ["implementer", "--verify", "npm test"])
        tools = (oc_dir / "workspaces" / "projects" / "demo-implementer-2" / "TOOLS.md").read_text()
        assert "Verification Gate" in tools
        assert "npm test" in tools

    def test_add_without_verify_omits_tools_md_section(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        tools = (oc_dir / "workspaces" / "projects" / "demo-implementer" / "TOOLS.md").read_text()
        assert "Verification Gate" not in tools

    def test_verify_ignored_for_non_implementer_role(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod.dispatch("demo", "add", ["reviewer", "--verify", "npm test"])
        m = _meta(oc_dir, "demo-reviewer")
        assert "verifyCmd" not in m


class TestPodSetVerify:
    """FD-1: `docket pod <project> set-verify <member-id> "<cmd>"`."""

    def test_set_verify_updates_meta(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod.dispatch("demo", "set-verify", ["demo-implementer", "npm", "test"])
        m = _meta(oc_dir, "demo-implementer")
        assert m["verifyCmd"] == "npm test"

    def test_set_verify_updates_tools_md(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod.dispatch("demo", "set-verify", ["demo-implementer", "make", "check"])
        tools = (oc_dir / "workspaces" / "projects" / "demo-implementer" / "TOOLS.md").read_text()
        assert "make check" in tools

    def test_set_verify_rejects_non_implementer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.FULL_POD_ROLES)
        with pytest.raises(typer.Exit):
            _pod.dispatch("demo", "set-verify", ["demo-reviewer", "npm", "test"])

    def test_set_verify_rejects_foreign_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        with pytest.raises(typer.Exit):
            _pod.dispatch("demo", "set-verify", ["other-implementer", "npm", "test"])

    def test_set_verify_missing_cmd_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        with pytest.raises(typer.Exit):
            _pod.dispatch("demo", "set-verify", ["demo-implementer"])

    def test_set_verify_missing_member_id_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        with pytest.raises(typer.Exit):
            _pod.dispatch("demo", "set-verify", [])
