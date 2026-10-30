"""POST /pods — provisioning over HTTP.

Unlike most routes, not a thin wrapper over a pre-existing `core/` function: the real
provisioning path prints through `ui.py`, and `serve.py` never imports `docket.cli`.
`teams.pod_provisioning.provision_pod` is the UI-free extraction of that path's decisions and
effects; `docket pod add`'s pod path and this route both call it, so the two cannot drift apart.
Covers auth (401), bad requests (400, nothing touched), the happy path (workspaces really exist on
disk), idempotence (409, existing pod untouched), rollback (a real induced mid-provisioning
failure leaves no workspace/fleet-registration/orphaned allocation, proven by on-disk/fleet
state), the shared-path pin, and override threading (`pod`/`budget`/`verifyCmd`). See
specs/data/serve-read-api.spec.md "POST /pods".
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest
from tests.support import http as _support_http
from tests.support import pods as _support_pods
from tests.support.http import get as _get
from tests.support.http import post as _post
from tests.support.http import post_raw as _post_raw

from docket.hops.application import report as _pod_report
from docket.hops.application import steps as _steps
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.home import current_home
from docket.kernel.threads import new_thread
from docket.platform import store as _store
from docket.teams import fleet as _fleet
from docket.teams import member_workspace as _member_workspace
from docket.teams import pod_provisioning as _pp

live_server = _support_http.live_server

pod_home = _support_pods.pod_home

SUBJECT = "docket.interfaces.http.server"

_TEST_TOKEN = "test-serve-token"


def _ids() -> list[str]:
    return [a.id for a in _fleet.list_agents()]


def _ws(member_id: str) -> Path:
    return current_home().projects_dir / member_id


# ── auth ─────────────────────────────────────────────────────────────────────


class TestAuth:
    def test_no_auth_returns_401(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        status, body = _post(f"{url}/pods", {"name": "demo", "location": "/src/demo"})
        assert status == 401
        assert body["ok"] is False

    def test_wrong_token_returns_401(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        status, _body = _post(
            f"{url}/pods", {"name": "demo", "location": "/src/demo"}, token="wrong"
        )
        assert status == 401

    def test_no_auth_creates_nothing(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        _post(f"{url}/pods", {"name": "demo", "location": "/src/demo"})
        assert _ids() == []


# ── bad requests ─────────────────────────────────────────────────────────────


class TestBadRequests:
    def test_invalid_json_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post_raw(f"{url}/pods", b"{not json", token)
        assert status == 400
        assert body["ok"] is False

    def test_non_object_body_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post_raw(f"{url}/pods", b"[1, 2, 3]", token)
        assert status == 400
        assert body["ok"] is False

    def test_missing_name_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post(f"{url}/pods", {"location": "/src/demo"}, token)
        assert status == 400
        assert "name" in body["error"].lower()

    def test_empty_name_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, _body = _post(f"{url}/pods", {"name": "", "location": "/src/demo"}, token)
        assert status == 400

    def test_unknown_blueprint_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post(
            f"{url}/pods",
            {"name": "demo", "location": "/src/demo", "blueprint": "wizard-pod"},
            token,
        )
        assert status == 400
        assert "wizard-pod" in body["error"] or "unknown blueprint" in body["error"].lower()
        assert _ids() == []

    def test_invalid_pod_field_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, _body = _post(
            f"{url}/pods", {"name": "demo", "location": "/src/demo", "pod": "medium"}, token
        )
        assert status == 400
        assert _ids() == []

    def test_non_numeric_budget_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, _body = _post(
            f"{url}/pods",
            {"name": "demo", "location": "/src/demo", "budget": "lots"},
            token,
        )
        assert status == 400
        assert _ids() == []

    def test_invalid_verify_cmd_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, _body = _post(
            f"{url}/pods",
            {"name": "demo", "location": "/src/demo", "verifyCmd": "line one\nline two"},
            token,
        )
        assert status == 400
        assert _ids() == []

    def test_path_traversal_project_id_returns_400_and_creates_nothing(
        self, live_server: tuple[str, str], tmp_path: Path
    ) -> None:
        # A project id with path-separator/parent-directory characters must
        # never reach `provision_pod`'s workspace-path construction. Oracle
        # is the filesystem: no path anywhere under the test's temp root may
        # contain "escaped", and no such agent is registered.
        url, token = live_server
        codebase = tmp_path / "codebase"
        codebase.mkdir()
        status, _body = _post(
            f"{url}/pods", {"name": "../../escaped", "location": str(codebase)}, token
        )
        assert status == 400
        assert _ids() == []
        escaped_paths = [p for p in tmp_path.rglob("*") if "escaped" in p.name]
        assert escaped_paths == [], f"escaped paths created on disk: {escaped_paths}"


# ── success ──────────────────────────────────────────────────────────────────


class TestSuccess:
    def test_default_blueprint_creates_lead_and_implementer(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        status, body = _post(f"{url}/pods", {"name": "demo", "location": "/src/demo"}, token)
        assert status == 201
        assert body["ok"] is True
        assert body["project"] == "demo"
        assert body["blueprint"] == "build"
        ids = sorted(m["id"] for m in body["members"])
        assert ids == ["demo-implementer", "demo-lead"]
        for m in body["members"]:
            assert m["role"] in ("lead", "implementer")
            assert m["model"]

    def test_workspaces_actually_exist_on_disk(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        _post(f"{url}/pods", {"name": "demo", "location": "/src/demo"}, token)
        for mid in ("demo-lead", "demo-implementer"):
            ws = _ws(mid)
            assert ws.is_dir()
            for f in ("SOUL.md", "AGENTS.md", "HEARTBEAT.md", ".docket-meta.json"):
                assert (ws / f).is_file(), f"{mid}: missing {f}"
        assert sorted(_ids()) == ["demo-implementer", "demo-lead"]

    def test_explicit_blueprint_is_honoured(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post(f"{url}/pods", {"name": "myops", "blueprint": "operate"}, token)
        assert status == 201
        assert body["blueprint"] == "operate"
        assert sorted(m["role"] for m in body["members"]) == [
            "lead",
            "monitor",
            "operator",
            "reviewer",
        ]


# ── idempotence ──────────────────────────────────────────────────────────────


class TestIdempotence:
    def test_existing_project_returns_409_and_is_untouched(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        _pod.build_pod_from_blueprint("demo", "build", location="/src/demo")
        before = sorted(_ids())

        status, body = _post(f"{url}/pods", {"name": "demo", "location": "/other/path"}, token)

        assert status == 409
        assert body["ok"] is False
        assert sorted(_ids()) == before
        # The original codebase was not overwritten by the second call's path.
        raw = json.loads((_ws("demo-lead") / ".docket-meta.json").read_text())
        assert raw["codebase"] == "/src/demo"

    def test_concurrent_same_project_loser_cannot_rollback_winner(
        self, pod_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A loser that fails after allocation must not undo the winner: without a critical
        section it could allocate the same resources then fail and roll them back; with
        serialization it instead waits and gets ``PodAlreadyExistsError``."""
        winner_at_first_member = threading.Event()
        loser_at_first_member = threading.Event()
        winner_paused = False
        real_write = _member_workspace.write_member_workspace

        def staged_write(*args: Any, **kwargs: Any) -> None:
            nonlocal winner_paused
            member = args[0]
            name = threading.current_thread().name
            if name == "winner" and not winner_paused:
                winner_paused = True
                winner_at_first_member.set()
                loser_at_first_member.wait(timeout=0.5)
            elif name == "loser":
                loser_at_first_member.set()
                if member.role == "implementer":
                    raise OSError("loser failed after allocation")
            return real_write(*args, **kwargs)

        monkeypatch.setattr(_member_workspace, "write_member_workspace", staged_write)
        outcomes: dict[str, object] = {}

        def provision() -> None:
            name = threading.current_thread().name
            try:
                outcomes[name] = _pp.provision_pod("race", "build", location="/src/race")
            except Exception as exc:
                outcomes[name] = exc

        winner = new_thread(target=provision, name="winner")
        loser = new_thread(target=provision, name="loser")
        winner.start()
        assert winner_at_first_member.wait(timeout=2)
        loser.start()
        winner.join(timeout=5)
        loser.join(timeout=5)

        assert not winner.is_alive()
        assert not loser.is_alive()
        assert isinstance(outcomes["winner"], _pp.PodProvisionResult)
        assert isinstance(outcomes["loser"], _pp.PodAlreadyExistsError)
        assert sorted(_ids()) == ["race-implementer", "race-lead", "race-reviewer"]
        allocation = _store.read_json(current_home().port_alloc_file)
        assert "race" in allocation["allocations"]
        scratch = current_home().pod_scratch_dir("race")
        assert scratch.is_dir()
        implementer = json.loads((_ws("race-implementer") / ".docket-meta.json").read_text())
        assert implementer["scratchDir"] == str(scratch)
        assert implementer["portRangeStart"] == allocation["allocations"]["race"]


# ── rollback on a real induced partial failure ──────────────────────────────


class TestRollback:
    def test_rollback_preserves_preexisting_pod_runtime(
        self, pod_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A new allocation must not make pre-existing runtime attempt-owned."""
        runtime = current_home().pods_dir / "flaky"
        scratch_marker = runtime / ".scratch" / "keep.txt"
        workdir_marker = runtime / "workdir" / "keep.txt"
        scratch_marker.parent.mkdir(parents=True)
        workdir_marker.parent.mkdir(parents=True)
        scratch_marker.write_text("preserve scratch")
        workdir_marker.write_text("preserve workdir")

        calls = {"n": 0}
        real_write = _member_workspace.write_member_workspace

        def flaky_write(*args: Any, **kwargs: Any) -> None:
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("disk full (induced failure)")
            return real_write(*args, **kwargs)

        monkeypatch.setattr(_member_workspace, "write_member_workspace", flaky_write)

        with pytest.raises(_pp.PodProvisionError):
            _pp.provision_pod("flaky", "build", location="/src/flaky")

        assert calls["n"] == 2
        assert scratch_marker.read_text() == "preserve scratch"
        assert workdir_marker.read_text() == "preserve workdir"
        assert "flaky" not in _store.read_json(current_home().port_alloc_file).get(
            "allocations", {}
        )

    def test_core_level_rollback_leaves_nothing_behind(
        self, pod_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Force the SECOND member's real workspace write to fail (the Lead is created first) and
        prove nothing survives: no workspace dir, no fleet registration, no allocation."""
        calls = {"n": 0}
        real_write = _member_workspace.write_member_workspace

        def flaky_write(*args: Any, **kwargs: Any) -> None:
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("disk full (induced failure)")
            return real_write(*args, **kwargs)

        monkeypatch.setattr(_member_workspace, "write_member_workspace", flaky_write)

        with pytest.raises(_pp.PodProvisionError):
            _pp.provision_pod("flaky", "build", location="/src/flaky")

        # The Lead really was created (call #1 succeeded) and then rolled back.
        assert calls["n"] == 2
        assert not _ws("flaky-lead").exists()
        assert not _ws("flaky-implementer").exists()
        assert _ids() == []
        alloc = _store.read_json(current_home().port_alloc_file)
        assert "flaky" not in alloc.get("allocations", {})
        assert not current_home().pod_scratch_dir("flaky").exists()

    def test_http_route_reports_500_and_leaves_nothing_behind(
        self, live_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        url, token = live_server
        calls = {"n": 0}
        real_write = _member_workspace.write_member_workspace

        def flaky_write(*args: Any, **kwargs: Any) -> None:
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("disk full (induced failure)")
            return real_write(*args, **kwargs)

        monkeypatch.setattr(_member_workspace, "write_member_workspace", flaky_write)

        status, body = _post(f"{url}/pods", {"name": "flaky", "location": "/src/flaky"}, token)

        assert status == 500
        assert body["ok"] is False
        assert calls["n"] == 2
        assert not _ws("flaky-lead").exists()
        assert not _ws("flaky-implementer").exists()
        assert _ids() == []
        alloc = _store.read_json(current_home().port_alloc_file)
        assert "flaky" not in alloc.get("allocations", {})


# ── docket pod add and POST /pods share one code path ───────────────────────────


class TestSharedProvisioningPath:
    def test_cli_and_http_both_call_the_same_core_function(
        self, live_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Intercept `provision_pod` itself (still delegating to the real implementation) and
        observe both the CLI's pod-provisioning entry point and the HTTP route resolve to it --
        proof the two surfaces cannot silently diverge, since there is only one function."""
        url, token = live_server
        real_provision_pod = _pp.provision_pod
        seen: list[dict[str, Any]] = []

        def spy(*args: Any, **kwargs: Any) -> _pp.PodProvisionResult:
            seen.append({"args": args, "kwargs": dict(kwargs)})
            return real_provision_pod(*args, **kwargs)

        monkeypatch.setattr(_pp, "provision_pod", spy)

        # The CLI path: what interfaces/cli/commands/agents.py::run_add calls for the interactive
        # flow (build_pod_from_blueprint is a thin rendering wrapper over
        # provision_pod).
        cli_created = _pod.build_pod_from_blueprint(
            "cliproj", "build", location="/src/cliproj", source="interactive"
        )
        assert cli_created

        # The HTTP path.
        status, _body = _post(
            f"{url}/pods", {"name": "httpproj", "location": "/src/httpproj"}, token
        )
        assert status == 201

        assert len(seen) == 2
        assert seen[0]["kwargs"]["source"] == "interactive"
        assert seen[1]["kwargs"]["source"] == "http"
        # Both real pods were actually created through the one intercepted call.
        assert sorted(_ids()) == [
            "cliproj-implementer",
            "cliproj-lead",
            "cliproj-reviewer",
            "httpproj-implementer",
            "httpproj-lead",
        ]


# ── pod/budget/verifyCmd overrides thread through ───────────────────────────


class TestOverridesThreaded:
    def test_pod_full_gives_the_four_role_roster(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post(
            f"{url}/pods", {"name": "demo", "location": "/src/demo", "pod": "full"}, token
        )
        assert status == 201
        assert sorted(m["role"] for m in body["members"]) == [
            "implementer",
            "lead",
            "reviewer",
        ]

    def test_budget_overrides_blueprint_default(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, _body = _post(
            f"{url}/pods", {"name": "myresearch", "blueprint": "respond", "budget": 42}, token
        )
        assert status == 201
        raw = json.loads((_ws("myresearch-lead") / ".docket-meta.json").read_text())
        assert float(raw["budgetUsd"]) == 42.0

    def test_verify_cmd_applied_to_implementer_only(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, _body = _post(
            f"{url}/pods",
            {"name": "demo", "location": "/src/demo", "verifyCmd": "npm test"},
            token,
        )
        assert status == 201
        impl_meta = json.loads((_ws("demo-implementer") / ".docket-meta.json").read_text())
        assert impl_meta["verifyCmd"] == "npm test"
        lead_meta = json.loads((_ws("demo-lead") / ".docket-meta.json").read_text())
        assert "verifyCmd" not in lead_meta


# ── ensure ───────────────────────────────────────────────────────────────────


class TestEnsure:
    def test_ensure_returns_the_existing_pod_unchanged(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        first_status, first = _post(
            f"{url}/pods", {"name": "demo", "location": "/src/demo", "ensure": True}, token
        )
        before = (current_home().fleet_file).read_bytes()
        status, body = _post(
            f"{url}/pods", {"name": "demo", "location": "/other/path", "ensure": True}, token
        )
        assert (first_status, first["created"]) == (201, True)
        assert (status, body) == (200, {"ok": True, "created": False, "project": "demo"})
        assert current_home().fleet_file.read_bytes() == before
        raw = json.loads((_ws("demo-lead") / ".docket-meta.json").read_text())
        assert raw["codebase"] == "/src/demo"

    def test_the_adr_0027_body_creates_then_ensures(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        body = {"name": "web-dev", "location": "/src/web", "blueprint": "build", "ensure": True}
        first_status, first = _post(f"{url}/pods", body, token)
        status, again = _post(f"{url}/pods", body, token)
        assert (first_status, first["created"], first["project"]) == (201, True, "web-dev")
        assert {m["role"] for m in first["members"]} == {"lead", "implementer"}
        assert (status, again) == (200, {"ok": True, "created": False, "project": "web-dev"})

    def test_the_v4_project_and_path_fields_are_gone(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post(f"{url}/pods", {"project": "demo", "path": "/src/demo"}, token)
        assert (status, body["error"]) == (400, "name is required")
        assert _ids() == []

    def test_without_ensure_an_existing_pod_stays_409(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        _post(f"{url}/pods", {"name": "demo", "location": "/src/demo"}, token)
        status, _body = _post(f"{url}/pods", {"name": "demo", "ensure": False}, token)
        assert status == 409

    def test_non_boolean_ensure_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, _body = _post(f"{url}/pods", {"name": "demo", "ensure": "yes"}, token)
        assert status == 400
        assert _ids() == []


# ── reading pods ─────────────────────────────────────────────────────────────


class TestReadPods:
    def test_unauthenticated_reads_return_401(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        assert _get(f"{url}/pods")[0] == 401
        assert _get(f"{url}/pods/demo")[0] == 401

    def test_list_names_each_pod_with_its_queue(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        _post(f"{url}/pods", {"name": "demo", "location": "/src/demo"}, token)
        status, body = _get(f"{url}/pods", token)
        assert status == 200
        (row,) = body["pods"]
        assert (row["name"], row["codebase"], row["members"]) == ("demo", "/src/demo", 2)
        assert row["profile"] == "attended"
        assert row["queue"]["pending"] == 0

    def test_empty_fleet_lists_no_pods(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        assert _get(f"{url}/pods", token) == (200, {"pods": []})

    def test_pod_carries_the_show_report_plus_profile_and_sources(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        _post(f"{url}/pods", {"name": "demo", "location": "/src/demo"}, token)
        status, body = _get(f"{url}/pods/demo", token)
        assert status == 200
        assert set(_pod_report.pod_report("demo")) <= set(body)
        assert body["profile"] == {"name": "attended", "violations": []}
        assert body["pipelineSource"] == _steps.effective_pipeline_source("demo")
        assert body["repoConfigDir"] == "/src/demo/.docket"

    def test_repo_config_dir_names_the_pods_team_dir(
        self, live_server: tuple[str, str], tmp_path: Path
    ) -> None:
        """A repository keeping `.docket/teams/<pod>/` reports that directory."""
        url, token = live_server
        (tmp_path / "repo" / ".docket" / "teams" / "demo").mkdir(parents=True)
        _post(f"{url}/pods", {"name": "demo", "location": str(tmp_path / "repo")}, token)
        _, body = _get(f"{url}/pods/demo", token)
        assert body["repoConfigDir"] == str(tmp_path / "repo" / ".docket" / "teams" / "demo")

    def test_pod_carries_its_effective_read_only_grants(
        self, live_server: tuple[str, str], tmp_path: Path
    ) -> None:
        """`readOnly` is the machine's grants the pod keeps; `settings.readOnly` its choice."""
        from docket.teams import fleet as _fleet

        url, token = live_server
        node, py = tmp_path / "node", tmp_path / "py"
        node.mkdir()
        py.mkdir()
        _fleet.add_read_only(str(node))
        _fleet.add_read_only(str(py))
        _post(f"{url}/pods", {"name": "demo", "location": "/src/demo"}, token)
        _, body = _get(f"{url}/pods/demo", token)
        assert body["readOnly"] == [str(node.resolve()), str(py.resolve())]
        _fleet.meta_set("demo-lead", "readOnly", str(py.resolve()))
        _, body = _get(f"{url}/pods/demo", token)
        assert body["readOnly"] == [str(py.resolve())]
        assert body["settings"]["readOnly"]["value"] == str(py.resolve())

    def test_a_pod_with_invalid_settings_answers_with_the_json_error(
        self, live_server: tuple[str, str]
    ) -> None:
        """Stored settings that no longer validate are the pod's fault, not a dropped socket."""
        url, token = live_server
        _post(f"{url}/pods", {"name": "demo", "location": "/src/demo"}, token)
        _fleet.meta_set("demo-lead", "approvalMode", "sometimes")
        status, body = _get(f"{url}/pods/demo", token)
        assert status == 500
        assert body["ok"] is False
        assert "approvalMode" in body["error"]

    def test_unknown_pod_returns_404(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _get(f"{url}/pods/nope", token)
        assert status == 404
        assert body["ok"] is False

    def test_bad_pod_id_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        assert _get(f"{url}/pods/bad%20id", token)[0] == 400
