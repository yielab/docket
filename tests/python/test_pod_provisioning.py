"""Pod provisioning + the `docket pod` command (hermetic, no daemon)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer

import docket.config as _cfg
from docket.cli import _pod
from docket.core import audit as _audit
from docket.core import fleet as _fleet


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _point_at(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "DOCKET_HOME", home, raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", home / "fleet.json", raising=True)
    monkeypatch.setattr(_cfg, "WORKSPACES_DIR", home / "workspaces", raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", home / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", home / "docket-models.json", raising=True)
    # audit_log() has no kill switch, and pod add/remove/delete now write
    # entries — repoint AUDIT_LOG alongside everything else this pod sandbox owns.
    monkeypatch.setattr(_cfg, "AUDIT_LOG", home / "audit.log", raising=True)


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    _point_at(home, monkeypatch)
    return home


def _ids(home: Path) -> list[str]:
    return [a.id for a in _fleet.list_agents()]


def _meta(home: Path, member_id: str) -> dict:
    p = home / "workspaces" / "projects" / member_id / ".docket-meta.json"
    return json.loads(p.read_text())


class TestBuildPod:
    def test_default_lean_pod_is_lead_plus_implementer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        created = _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        assert created == ["demo-lead", "demo-implementer"]
        assert set(_ids(home)) == {"demo-lead", "demo-implementer"}

    def test_members_have_correct_meta_and_shared_session_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        for mid, role in (("demo-lead", "lead"), ("demo-implementer", "implementer")):
            m = _meta(home, mid)
            assert m["kind"] == "project"
            assert m["scope"] == "project"
            assert m["role"] == role
            assert m["pod"] == "demo"
            assert m["sessionKey"] == "agent:demo:default"
            assert m["modelSource"] == "policy"
            assert (home / "workspaces" / "projects" / mid / "SOUL.md").is_file()
            # Pod-member meta must round-trip through the AgentMeta model — a
            # regression for templateVersion being written as an int (which made
            # the first metadata write after provisioning raise ValidationError).
            from docket.core.models import AgentMeta

            assert AgentMeta.model_validate(m).template_version == str(_pod.POD_TEMPLATE_VERSION)

    def test_lead_soul_forbids_editing_implementer_has_codebase(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        lead = (home / "workspaces" / "projects" / "demo-lead" / "SOUL.md").read_text()
        impl = (home / "workspaces" / "projects" / "demo-implementer" / "SOUL.md").read_text()
        assert "NEVER edit code" in lead
        assert "inside" in impl and "/src/demo" in impl
        # No leftover shared-specialist language anywhere in the pod.
        assert "shared specialist" not in (lead + impl).lower()

    def test_full_pod_has_four_members(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.FULL_POD_ROLES)
        assert set(_ids(home)) == {
            "demo-lead",
            "demo-implementer",
            "demo-reviewer",
            "demo-tester",
        }


class TestPodCommand:
    def test_add_second_implementer_is_indexed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod.dispatch("demo", "add", ["implementer"])
        assert "demo-implementer-2" in _ids(home)

    def test_add_reviewer(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod.dispatch("demo", "add", ["reviewer"])
        assert "demo-reviewer" in _ids(home)

    def test_add_count_two_makes_two_implementers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod.dispatch("demo", "add", ["implementer", "--count", "2"])
        ids = _ids(home)
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
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod.dispatch("demo", "add", ["reviewer"])
        _pod.dispatch("demo", "remove", ["demo-reviewer"])
        assert "demo-reviewer" not in _ids(home)
        assert not (home / "workspaces" / "projects" / "demo-reviewer").exists()

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

        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.FULL_POD_ROLES)
        # Non-TTY → _delete_pod skips the interactive confirm.
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        cli._delete_pod("demo", _pod.pod_member_ids("demo"))
        assert _ids(home) == []
        assert not (home / "workspaces" / "projects" / "demo-lead").exists()

    def test_delete_pod_writes_one_agent_delete_audit_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pod teardown (docket delete <pod>) writes a single agent.delete line."""
        from docket import cli

        _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        cli._delete_pod("demo", _pod.pod_member_ids("demo"))

        entries = [e for e in _audit.read_audit() if e["action"] == "agent.delete"]
        assert len(entries) == 1
        assert entries[0]["detail"] == "demo pod (2 members)"
        for e in entries:
            assert "ANTHROPIC" not in e["detail"] and "sk-" not in e["detail"]


class TestParseAddArgs:
    """`--verify` parsing in `_parse_add_args`."""

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
    """`docket pod <project> add --verify` sets `verifyCmd` + TOOLS.md."""

    def test_add_implementer_with_verify_sets_meta(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod.dispatch("demo", "add", ["implementer", "--verify", "npm test"])
        m = _meta(home, "demo-implementer-2")
        assert m["verifyCmd"] == "npm test"

    def test_add_implementer_with_verify_writes_tools_md(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod.dispatch("demo", "add", ["implementer", "--verify", "npm test"])
        tools = (home / "workspaces" / "projects" / "demo-implementer-2" / "TOOLS.md").read_text()
        assert "Verification Gate" in tools
        assert "npm test" in tools

    def test_add_without_verify_omits_tools_md_section(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        tools = (home / "workspaces" / "projects" / "demo-implementer" / "TOOLS.md").read_text()
        assert "Verification Gate" not in tools

    def test_verify_ignored_for_non_implementer_role(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod.dispatch("demo", "add", ["reviewer", "--verify", "npm test"])
        m = _meta(home, "demo-reviewer")
        assert "verifyCmd" not in m


class TestPodSetVerify:
    """`docket pod <project> set-verify <member-id> "<cmd>"`."""

    def test_set_verify_updates_meta(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod.dispatch("demo", "set-verify", ["demo-implementer", "npm", "test"])
        m = _meta(home, "demo-implementer")
        assert m["verifyCmd"] == "npm test"

    def test_set_verify_updates_tools_md(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod.dispatch("demo", "set-verify", ["demo-implementer", "make", "check"])
        tools = (home / "workspaces" / "projects" / "demo-implementer" / "TOOLS.md").read_text()
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


class TestPodAddRemoveAudit:
    """`docket pod <p> add/remove` each write exactly one audit line."""

    def test_pod_add_writes_one_audit_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod.dispatch("demo", "add", ["reviewer"])

        entries = [e for e in _audit.read_audit() if e["action"] == "pod.add"]
        assert len(entries) == 1
        assert entries[0]["detail"] == "demo role=reviewer members=demo-reviewer"

    def test_pod_add_with_count_writes_one_audit_entry_for_all_members(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod.dispatch("demo", "add", ["implementer", "--count", "2"])

        entries = [e for e in _audit.read_audit() if e["action"] == "pod.add"]
        assert len(entries) == 1
        assert "demo-implementer-2" in entries[0]["detail"]
        assert "demo-implementer-3" in entries[0]["detail"]

    def test_pod_remove_writes_one_audit_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.FULL_POD_ROLES)
        _pod.dispatch("demo", "remove", ["demo-reviewer"])

        entries = [e for e in _audit.read_audit() if e["action"] == "pod.remove"]
        assert len(entries) == 1
        assert entries[0]["detail"] == "demo member=demo-reviewer role=reviewer"

    def test_pod_add_remove_never_log_secret_values(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES)
        _pod.dispatch("demo", "add", ["reviewer"])
        _pod.dispatch("demo", "remove", ["demo-reviewer"])

        for e in _audit.read_audit():
            assert "sk-" not in str(e.get("detail", ""))
            assert "API_KEY" not in str(e.get("detail", ""))
