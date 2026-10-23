"""`docket pod show` -- the pod and a member's effective configuration, with provenance.

Composes existing resolvers only (model policy, `core.identity`'s prompt composer,
role/tool denial, the guardrail policy engine, `core.pod.PodSettings`, and
`core.dispatch.effective_pipeline_source`); writes nothing and adds no new core
surface. See specs/data/cli-json-shapes.spec.md, "`docket pod show --json`". The oracle
case (`TestPodShowMatchesRealDispatch`) cross-checks the reports against what a real pod
dispatch (FakeDriver) actually used for the hop.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from tests.fakes import FakeDriver
from tests.pods import build_pod
from typer.testing import CliRunner

from docket.cli import _pod
from docket.core import archetypes as _archetypes
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import mcp_tools as _mcp_tools
from docket.core import pod, pod_report
from docket.core import policy as _policy
from docket.edges import store as _store
from docket.kernel.home import Home, current_home, use_home

SUBJECT = "docket.cli._pod_show"

_runner = CliRunner()


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


@contextmanager
def _seed(
    tmp_path: Path,
    project: str = "demo",
    roles: tuple[str, ...] = pod.DEFAULT_POD_ROLES,
) -> Iterator[Path]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        build_pod(project, roles, codebase=f"/src/{project}")
        yield home


def _show(*args: str, project: str = "demo") -> tuple[int, str]:
    result = _runner.invoke(_pod.pod_app, ["show", *args, "--pod", project])
    return result.exit_code, result.output


def _explain_json(agent_id: str, capsys: pytest.CaptureFixture[str]) -> dict:
    project = pod.pod_of(agent_id)
    if not project:
        return pod_report.member_report(agent_id)
    code, out = _show(agent_id, "--json", project=project)
    assert code == 0, out
    return json.loads(out)


def _explain_text(agent_id: str, capsys: pytest.CaptureFixture[str]) -> str:
    code, out = _show(agent_id)
    assert code == 0, out
    return out


class TestPodShowRefusals:
    def test_a_name_that_is_not_a_member_refuses(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            code, _out = _show("nope")
            assert code == 1

    def test_no_pod_refuses(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            code, _out = _show(project="ghost")
            assert code == 1


class TestPodShowMatchesRealDispatch:
    """The card's oracle: every reported value matches what a real dispatch hop
    (through FakeDriver) actually used."""

    def test_model_pod_settings_and_pipeline_match_the_dispatched_hop(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path):
            implementer = pod.member_id("demo", "implementer")
            _fleet.set_model_both(implementer, "anthropic/claude-opus-4-6")

            lead = pod.member_id("demo", "lead")
            _fleet.meta_set(lead, "budgetUsd", 5.0)
            _fleet.meta_set(lead, "maxReworkCycles", 2)
            _fleet.meta_set(lead, "turnTimeoutS", 111)
            _fleet.meta_set(lead, "verifyTimeoutS", 42)
            _fleet.meta_set(lead, "approvalMode", "refuse")
            _fleet.meta_set(lead, "allowCommands", "curl")

            _dispatch.enqueue_task_once("demo", "do the thing", channel="cli")
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
            assert report["model"] == {"value": "anthropic/claude-opus-4-6", "source": "policy"}
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
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path):
            lead = pod.member_id("demo", "lead")
            report = _explain_json(lead, capsys)
            assert report["model"]["source"] == "policy"
            assert report["model"]["value"] == _fleet.meta_get(
                lead, "model", current_home().default_model
            )


class TestPodShowToolDenial:
    def test_reviewer_denied_tools_match_its_archetype(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path, roles=("lead", "implementer", "reviewer")):
            reviewer = pod.member_id("demo", "reviewer")
            report = _explain_json(reviewer, capsys)
            denied = {d["name"]: d["scope"] for d in report["tools"]["denied"]}
            assert denied == {"write": "built-in", "edit": "built-in", "bash": "built-in"}
            assert "write" not in report["tools"]["allowed"]
            assert "read" in report["tools"]["allowed"]
            assert report["roleScope"] == "built-in"


class TestPodShowTextUnchangedWithNoPodScope:
    """The byte-identity oracle: human-readable `config explain` output is unchanged
    when nothing has pod scope, pinning the exact lines `_render_human` touches."""

    def test_implementer_text_matches_the_base_exactly(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            _seed(tmp_path),
            use_home(
                dataclasses.replace(current_home(), fetch_allowed_domains=("api.example.test",))
            ),
        ):
            text = _explain_text(pod.member_id("demo", "implementer"), capsys)
            assert (
                "  Tools allowed: bash, consult, edit, fetch, glob, grep, read, skill, write\n"
                in text
            )
            assert "  Tools denied:  (none)\n" in text
            assert "  MCP servers:   (none configured)\n" in text

    def test_reviewer_text_matches_the_base_exactly(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            _seed(tmp_path, roles=("lead", "implementer", "reviewer")),
            use_home(
                dataclasses.replace(current_home(), fetch_allowed_domains=("api.example.test",))
            ),
        ):
            text = _explain_text(pod.member_id("demo", "reviewer"), capsys)
            assert "  Tools allowed: consult, fetch, glob, grep, read, skill\n" in text
            assert "  Tools denied:  bash, edit, write\n" in text


class TestPodShowScopeLabels:
    """Every resolved value in `--json` names which scope -- built-in, global (the
    operator's `~/.docket` overlay), or pod (this pod's own `config/`) -- produced it."""

    def test_pod_overlay_shadowed_role_policy_server_and_denial(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            _seed(tmp_path, roles=("lead", "implementer", "reviewer")),
            use_home(
                dataclasses.replace(current_home(), fetch_allowed_domains=("api.example.test",))
            ),
        ):
            # The pod's own overlay shadows the built-in `reviewer` archetype.
            _archetypes.add_user_archetype(
                {
                    "name": "reviewer",
                    "scope": "pod",
                    "modelClass": "cheap",
                    "soulTemplate": "# shadowed reviewer\n${role}",
                    "agentsTemplate": "# shadowed reviewer agents\n${role}",
                    "gateContract": {
                        "kind": "verdict",
                        "regexes": ["APPROVE", "REQUEST-CHANGES"],
                    },
                    "deniedTools": ["write", "edit", "bash"],
                },
                project="demo",
            )

            # One global policy (the shipped baseline) and one pod-only policy, both
            # applying to reviewer.
            result = _policy.install_policies()
            assert result.installed  # sanity: the shipped baseline actually installed
            pod_policies_dir = current_home().pod_config_dir("demo") / "policies"
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
            assert report["model"]["source"] == "pod overlay"

            scopes_by_id = {p["id"]: p["scope"] for p in report["policies"]}
            assert scopes_by_id["pod-only"] == "pod"
            assert any(
                scope == "global" for pid, scope in scopes_by_id.items() if pid != "pod-only"
            )

            assert report["tools"]["mcpServers"] == [
                {"name": "search", "kind": "read", "scope": "pod"}
            ]

            denied = {d["name"]: d["scope"] for d in report["tools"]["denied"]}
            assert denied["fetch"] == "pod"
            # The shadowed archetype's own denials are pod-scoped too, since the
            # archetype itself resolved from this pod's overlay.
            assert denied["write"] == "pod"

    def test_pod_only_denial_is_labeled_pod_even_for_a_built_in_role(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Negative case: an unshadowed built-in role plus a pod-only `deniedTools`
        setting -- `bash` avoids the kind-cascade so only one name is denied."""
        with _seed(tmp_path):
            lead = pod.member_id("demo", "lead")
            _fleet.meta_set(lead, "deniedTools", "bash")
            implementer = pod.member_id("demo", "implementer")
            report = _explain_json(implementer, capsys)
            assert report["roleScope"] == "built-in"
            assert report["tools"]["denied"] == [{"name": "bash", "scope": "pod"}]


class TestPodShowNonPodAgent:
    def test_agent_with_no_pod_reports_null_pipeline_and_pod_settings(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path) as home:
            ws = home / "workspaces" / "solo"
            ws.mkdir(parents=True)
            _store.write_json(
                current_home().meta_path("solo"),
                {"kind": "project", "role": "", "model": "", "name": "solo"},
            )
            report = _explain_json("solo", capsys)
            assert report["pod"] == ""
            assert report["pipeline"] is None
            assert report["podSettings"] is None


class TestPodShowPolicies:
    def test_baseline_policies_apply_to_every_role(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path):
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
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path):
            policies_dir = current_home().policies_dir
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


class TestPodShowInvalidPodSettingsRefuses:
    def test_bad_stored_value_refuses(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _seed(tmp_path):
            lead = pod.member_id("demo", "lead")
            meta_path = current_home().meta_path(lead)
            meta = json.loads(meta_path.read_text())
            meta["turnTimeoutS"] = "not-a-number"
            meta_path.write_text(json.dumps(meta))

            implementer = pod.member_id("demo", "implementer")
            code, out = _show(implementer)
            assert code == 1
            assert "turnTimeoutS" in out
            code, out = _show()
            assert code == 1
            assert "turnTimeoutS" in out


class TestPodShowProvider:
    """`report["provider"]` names the resolved provider's scope, dialect, base URL,
    credential source and the model's limits with their sources -- model-profiles.spec.md, "Provider
    catalog" requirement 7."""

    def test_agent_on_a_global_provider_document(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from docket.core import provider as _prov

        with _seed(tmp_path):
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
                "contextWindowSource": "declared",
                "maxTokensSource": "declared",
                "source": "declared",
                "observedAt": "",
            }

    def test_observed_and_unknown_limits_name_their_source(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from docket.core import provider as _prov
        from docket.core.llm import ModelLimits
        from docket.edges.adapters.llm import ProbeResult

        with _seed(tmp_path):
            spec = _prov.ProviderSpec(
                name="bench",
                baseUrl="http://127.0.0.1:8081/v1",
                auth=_prov.AuthSpec(type="none"),
                models=[_prov.ModelRow(id="qwen"), _prov.ModelRow(id="other")],
            )
            _prov.save_provider(spec)
            _prov.record_observed_models(
                spec,
                ProbeResult(
                    status=200, model_ids=["qwen"], limits={"qwen": ModelLimits(32768, None)}
                ),
            )
            lead = pod.member_id("demo", "lead")
            _fleet.meta_set(lead, "model", "bench/qwen")
            observed = _explain_json(lead, capsys)["provider"]["model"]
            assert observed["contextWindow"] == 32768
            assert observed["maxTokens"] is None
            assert (observed["contextWindowSource"], observed["maxTokensSource"]) == (
                "observed",
                "unknown",
            )
            assert observed["source"] == "observed"
            assert observed["observedAt"] == _prov.observed_at("bench") != ""

            _fleet.meta_set(lead, "model", "bench/other")
            unknown = _explain_json(lead, capsys)["provider"]["model"]
            assert (unknown["contextWindow"], unknown["maxTokens"]) == (None, None)
            assert unknown["source"] == "unknown"


class TestPodShowPod:
    """The pod view names each member's verify command and the approval mode the dispatcher
    resolves, pinned to ``core.dispatch.pod_approval_mode`` itself."""

    def test_pod_view_names_the_verify_command_and_the_dispatchers_approval_mode(
        self, tmp_path: Path
    ) -> None:
        with _seed(tmp_path):
            implementer = pod.member_id("demo", "implementer")
            _fleet.meta_set(implementer, "verifyCmd", "make check")
            code, out = _show("--json")
            assert code == 0, out
            report = json.loads(out)
            by_id = {m["id"]: m for m in report["members"]}
            assert by_id[implementer]["verifyCmd"] == "make check"
            assert report["approvalMode"]["effective"] == _dispatch.pod_approval_mode(
                "demo", caller_default="park"
            )
            assert report["approvalMode"]["source"] == "unset"

    @pytest.mark.parametrize("mode", ["wait", "park", "refuse"])
    def test_an_explicit_approval_mode_is_what_the_dispatcher_uses(
        self, tmp_path: Path, mode: str
    ) -> None:
        with _seed(tmp_path):
            _fleet.meta_set(pod.member_id("demo", "lead"), "approvalMode", mode)
            report = json.loads(_show("--json")[1])
            assert report["approvalMode"] == {"effective": mode, "source": "set"}
            assert _dispatch.pod_approval_mode("demo") == mode

    def test_settings_carry_their_source(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            _fleet.meta_set(pod.member_id("demo", "lead"), "budgetUsd", 7.0)
            report = json.loads(_show("--json")[1])
            assert report["settings"]["budgetUsd"] == {"value": 7.0, "source": "set"}
            assert report["settings"]["maxReworkCycles"]["source"] == "default"
