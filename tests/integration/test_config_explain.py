"""`docket config explain <agent>` -- effective configuration, with provenance.

Composes existing resolvers only (model policy, `core.identity`'s prompt composer,
role/tool denial, the guardrail policy engine, `core.pod.PodSettings`, and
`core.dispatch.effective_pipeline_source`); writes nothing and adds no new core
surface. See specs/data/cli-json-shapes.spec.md, "`docket config explain <agent>
--json`". The oracle case (`TestConfigExplainMatchesRealDispatch`) cross-checks the
report against what a real pod dispatch (FakeDriver) actually used for the hop.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from tests.conftest import repoint_docket_home
from tests.fakes import FakeDriver

import docket.config as _cfg
from docket.cli import _config, _pod
from docket.core import archetypes as _archetypes
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import mcp_tools as _mcp_tools
from docket.core import pod
from docket.core import policy as _policy
from docket.edges import store as _store

SUBJECT = "docket.cli._config"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _seed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project: str = "demo",
    roles: tuple[str, ...] = pod.DEFAULT_POD_ROLES,
) -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    _pod.build_pod(project, roles, codebase=f"/src/{project}")
    return home


def _explain_json(agent_id: str, capsys: pytest.CaptureFixture[str]) -> dict:
    capsys.readouterr()
    _config.dispatch("explain", [agent_id, "--json"])
    return json.loads(capsys.readouterr().out)


def _explain_text(agent_id: str, capsys: pytest.CaptureFixture[str]) -> str:
    capsys.readouterr()
    _config.dispatch("explain", [agent_id])
    return capsys.readouterr().out


class TestConfigExplainUnknownAgent:
    def test_unknown_agent_refuses_before_anything_else(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        with pytest.raises(typer.Exit) as exc:
            _config.dispatch("explain", ["nope"])
        assert exc.value.exit_code == 1
        assert "not found" in capsys.readouterr().err

    def test_unknown_config_action_refuses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        with pytest.raises(typer.Exit) as exc:
            _config.dispatch("bogus", ["demo-lead"])
        assert exc.value.exit_code == 1
        assert "Unknown config action" in capsys.readouterr().err


class TestConfigExplainMatchesRealDispatch:
    """The card's oracle: every reported value matches what a real dispatch hop
    (through FakeDriver) actually used."""

    def test_model_pod_settings_and_pipeline_match_the_dispatched_hop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        implementer = pod.member_id("demo", "implementer")
        _fleet.set_model_both(implementer, "anthropic/claude-opus-4-6")
        _fleet.meta_set(implementer, "modelSource", "pinned")

        lead = pod.member_id("demo", "lead")
        _fleet.meta_set(lead, "budgetUsd", 5.0)
        _fleet.meta_set(lead, "maxReworkCycles", 2)
        _fleet.meta_set(lead, "turnTimeoutS", 111)
        _fleet.meta_set(lead, "verifyTimeoutS", 42)
        _fleet.meta_set(lead, "approvalMode", "refuse")
        _fleet.meta_set(lead, "allowCommands", "curl")

        _dispatch.enqueue_task("demo", "do the thing")
        runner = FakeDriver(cost=0.01)
        results = _dispatch.dispatch_pod("demo", runner=runner)
        assert results[0].status == "done"

        # The implementer hop actually received this pod's configured timeout
        # and approval-mode -- confirms the settings below are not just stored,
        # they are what a real dispatch used.
        impl_calls = [c for c in runner.calls if c[0] == implementer]
        assert impl_calls, "implementer hop never ran"
        _, _, _, timeout, env = impl_calls[0]
        assert timeout == 111
        assert (env or {}).get("DOCKET_APPROVAL_MODE") == "refuse"

        report = _explain_json(implementer, capsys)
        assert report["id"] == implementer
        assert report["role"] == "implementer"
        assert report["pod"] == "demo"
        assert report["model"] == {"value": "anthropic/claude-opus-4-6", "source": "pinned"}
        assert report["podSettings"]["budgetUsd"] == {"value": 5.0, "source": "set"}
        assert report["podSettings"]["maxReworkCycles"] == {"value": 2, "source": "set"}
        assert report["podSettings"]["turnTimeoutS"] == {"value": 111, "source": "set"}
        assert report["podSettings"]["verifyTimeoutS"] == {"value": 42, "source": "set"}
        assert report["podSettings"]["approvalMode"] == {"value": "refuse", "source": "set"}
        assert report["podSettings"]["allowCommands"] == {"value": "curl", "source": "set"}
        assert report["pipeline"] == {"source": _dispatch.effective_pipeline_source("demo")}
        # Implementer is full-repo -- the archetype denies nothing.
        assert report["tools"]["denied"] == []
        assert report["roleScope"] == "built-in"

    def test_lead_model_follows_policy_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        lead = pod.member_id("demo", "lead")
        report = _explain_json(lead, capsys)
        assert report["model"]["source"] == "policy"
        assert report["model"]["value"] == _fleet.meta_get(lead, "model", _cfg.DEFAULT_MODEL)


class TestConfigExplainToolDenial:
    def test_reviewer_denied_tools_match_its_archetype(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, roles=("lead", "implementer", "reviewer"))
        reviewer = pod.member_id("demo", "reviewer")
        report = _explain_json(reviewer, capsys)
        denied = {d["name"]: d["scope"] for d in report["tools"]["denied"]}
        assert denied == {"write": "built-in", "edit": "built-in", "bash": "built-in"}
        assert "write" not in report["tools"]["allowed"]
        assert "read" in report["tools"]["allowed"]
        assert report["roleScope"] == "built-in"


class TestConfigExplainTextUnchangedWithNoPodScope:
    """The byte-identity oracle: human-readable `config explain` output is unchanged
    when nothing has pod scope, pinning the exact lines `_render_human` touches."""

    def test_implementer_text_matches_the_base_exactly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        text = _explain_text(pod.member_id("demo", "implementer"), capsys)
        assert (
            "  Tools allowed: bash, consult, edit, fetch, glob, grep, read, skill, write\n" in text
        )
        assert "  Tools denied:  (none)\n" in text
        assert "  MCP servers:   (none configured)\n" in text

    def test_reviewer_text_matches_the_base_exactly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, roles=("lead", "implementer", "reviewer"))
        text = _explain_text(pod.member_id("demo", "reviewer"), capsys)
        assert "  Tools allowed: consult, fetch, glob, grep, read, skill\n" in text
        assert "  Tools denied:  bash, edit, write\n" in text


class TestConfigExplainScopeLabels:
    """Every resolved value in `--json` names which scope -- built-in, global (the
    operator's `~/.docket` overlay), or pod (this pod's own `config/`) -- produced it."""

    def test_pod_overlay_shadowed_role_policy_server_and_denial(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch, roles=("lead", "implementer", "reviewer"))

        # The pod's own overlay shadows the built-in `reviewer` archetype.
        _archetypes.add_user_archetype(
            {
                "name": "reviewer",
                "scope": "pod",
                "modelClass": "cheap",
                "soulTemplate": "# shadowed reviewer\n${role}",
                "agentsTemplate": "# shadowed reviewer agents\n${role}",
                "gateContract": {"kind": "verdict", "regexes": ["APPROVE", "REQUEST-CHANGES"]},
                "deniedTools": ["write", "edit", "bash"],
            },
            project="demo",
        )

        # One global policy (the shipped baseline) and one pod-only policy, both
        # applying to reviewer.
        result = _policy.install_policies()
        assert result.installed  # sanity: the shipped baseline actually installed
        pod_policies_dir = _cfg.pod_config_dir("demo") / "policies"
        pod_policies_dir.mkdir(parents=True)
        (pod_policies_dir / "pod-only.json").write_text(
            json.dumps(
                {
                    "id": "pod-only",
                    "applies_to": ["reviewer"],
                    "hook": "pre_tool_call",
                    "match": {"type": "regex", "pattern": "x"},
                    "action": "warn",
                }
            )
        )

        # One MCP server, declared read, selected by this pod alone.
        _mcp_tools.add_mcp_server(
            _mcp_tools.McpServerConfig(name="search", command="stub", kind="read")
        )
        lead = pod.member_id("demo", "lead")
        _fleet.meta_set(lead, "mcpServers", "search")
        _fleet.meta_set(lead, "deniedTools", "fetch")

        reviewer = pod.member_id("demo", "reviewer")
        report = _explain_json(reviewer, capsys)

        assert report["roleScope"] == "pod"

        scopes_by_id = {p["id"]: p["scope"] for p in report["policies"]}
        assert scopes_by_id["pod-only"] == "pod"
        assert any(scope == "global" for pid, scope in scopes_by_id.items() if pid != "pod-only")

        assert report["tools"]["mcpServers"] == [
            {"name": "search", "kind": "read", "scope": "pod", "isolate": True}
        ]

        denied = {d["name"]: d["scope"] for d in report["tools"]["denied"]}
        assert denied["fetch"] == "pod"
        # The shadowed archetype's own denials are pod-scoped too, since the
        # archetype itself resolved from this pod's overlay.
        assert denied["write"] == "pod"

    def test_pod_only_denial_is_labeled_pod_even_for_a_built_in_role(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Negative case: an unshadowed built-in role plus a pod-only `deniedTools`
        setting -- `bash` avoids the kind-cascade so only one name is denied."""
        _seed(tmp_path, monkeypatch)
        lead = pod.member_id("demo", "lead")
        _fleet.meta_set(lead, "deniedTools", "bash")
        implementer = pod.member_id("demo", "implementer")
        report = _explain_json(implementer, capsys)
        assert report["roleScope"] == "built-in"
        assert report["tools"]["denied"] == [{"name": "bash", "scope": "pod"}]


class TestConfigExplainNonPodAgent:
    def test_agent_with_no_pod_reports_null_pipeline_and_pod_settings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = _seed(tmp_path, monkeypatch)
        ws = home / "workspaces" / "solo"
        ws.mkdir(parents=True)
        _store.write_json(
            _cfg.meta_path("solo"),
            {"kind": "specialist", "role": "", "model": "", "name": "solo"},
        )
        report = _explain_json("solo", capsys)
        assert report["pod"] == ""
        assert report["pipeline"] is None
        assert report["podSettings"] is None


class TestConfigExplainPolicies:
    def test_baseline_policies_apply_to_every_role(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        result = _policy.install_policies()
        assert result.installed  # sanity: templates actually exist in this checkout

        lead = pod.member_id("demo", "lead")
        report = _explain_json(lead, capsys)
        ids = {p["id"] for p in report["policies"]}

        def _stem(name: str) -> str:
            for ext in (".json", ".yaml", ".yml"):
                if name.endswith(ext):
                    return name[: -len(ext)]
            return name

        assert ids == {_stem(name) for name in result.installed}

    def test_role_scoped_policy_is_excluded_for_other_roles(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        policies_dir = _cfg.POLICIES_DIR
        policies_dir.mkdir(parents=True)
        (policies_dir / "implementer-only.json").write_text(
            json.dumps(
                {
                    "id": "implementer-only",
                    "applies_to": ["implementer"],
                    "hook": "pre_tool_call",
                    "match": {"type": "regex", "pattern": "x"},
                    "action": "warn",
                }
            )
        )
        implementer = pod.member_id("demo", "implementer")
        lead = pod.member_id("demo", "lead")
        impl_report = _explain_json(implementer, capsys)
        lead_report = _explain_json(lead, capsys)
        assert "implementer-only" in {p["id"] for p in impl_report["policies"]}
        assert "implementer-only" not in {p["id"] for p in lead_report["policies"]}


class TestConfigExplainInvalidPodSettingsRefuses:
    def test_bad_stored_value_refuses_like_pod_config_get(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        lead = pod.member_id("demo", "lead")
        meta_path = _cfg.meta_path(lead)
        meta = json.loads(meta_path.read_text())
        meta["turnTimeoutS"] = "not-a-number"
        meta_path.write_text(json.dumps(meta))

        implementer = pod.member_id("demo", "implementer")
        with pytest.raises(typer.Exit) as exc:
            _config.dispatch("explain", [implementer])
        assert exc.value.exit_code == 1
        assert "turnTimeoutS" in capsys.readouterr().err


class TestConfigExplainProvider:
    """`report["provider"]` names the resolved provider's scope, dialect, base URL,
    credential source and exact model row -- model-profiles.spec.md, "Provider
    catalog" requirement 7."""

    def test_agent_on_a_global_provider_document(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from docket.core import provider as _prov

        _seed(tmp_path, monkeypatch)
        _prov.save_provider(
            _prov.ProviderSpec(
                name="bench",
                baseUrl="http://127.0.0.1:8081/v1",
                auth=_prov.AuthSpec(type="none"),
                models=[_prov.ModelRow(id="qwen", contextWindow=16384, maxTokens=4096)],
            )
        )
        lead = pod.member_id("demo", "lead")
        _fleet.meta_set(lead, "model", "bench/qwen")

        report = _explain_json(lead, capsys)

        provider = report["provider"]
        assert provider["name"] == "bench"
        assert provider["scope"] == "global"
        assert provider["dialect"] == "openai-chat"
        assert provider["baseUrl"] == "http://127.0.0.1:8081/v1"
        assert provider["credential"] == {"name": "", "source": "none"}
        assert provider["model"] == {
            "id": "qwen",
            "contextWindow": 16384,
            "maxTokens": 4096,
            "source": "row",
        }
