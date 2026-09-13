"""POST /pods — provisioning over HTTP.

Unlike most routes, not a thin wrapper over a pre-existing `core/` function: the real
provisioning path prints through `ui.py`, and `serve.py` never imports `docket.cli`.
`core.pod_provisioning.provision_pod` is the UI-free extraction of that path's decisions and
effects; `docket add`'s pod path and this route both call it, so the two cannot drift apart.
Covers auth (401), bad requests (400, nothing touched), the happy path (workspaces really exist on
disk), idempotence (409, existing pod untouched), rollback (a real induced mid-provisioning
failure leaves no workspace/fleet-registration/orphaned allocation, proven by on-disk/fleet
state), the shared-path pin, and override threading (`pod`/`budget`/`verifyCmd`). See
specs/data/serve-read-api.spec.md "POST /pods".
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.cli import _pod
from docket.core import fleet as _fleet
from docket.core import pod_provisioning as _pp
from docket.edges import store as _store
from docket.serve import _DocketHandler

SUBJECT = "docket.core"

_TEST_TOKEN = "test-serve-token-pods-p22-5"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


@pytest.fixture()
def pod_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    (home / "approvals").mkdir()
    repoint_docket_home(monkeypatch, home)
    return home


@pytest.fixture()
def live_server(pod_home: Path):  # type: ignore[no-untyped-def]
    class _Handler(_DocketHandler):
        serve_token = _TEST_TOKEN

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", _TEST_TOKEN
    srv.shutdown()


def _post_raw(url: str, data: bytes, token: str | None = None) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Content-Length", str(len(data)))
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _post(
    url: str, body: dict[str, Any] | None = None, token: str | None = None
) -> tuple[int, dict[str, Any]]:
    return _post_raw(url, json.dumps(body if body is not None else {}).encode(), token)


def _ids() -> list[str]:
    return [a.id for a in _fleet.list_agents()]


def _ws(member_id: str) -> Path:
    return _cfg.PROJECTS_DIR / member_id


# ── auth ─────────────────────────────────────────────────────────────────────


class TestAuth:
    def test_no_auth_returns_401(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        status, body = _post(f"{url}/pods", {"project": "demo", "path": "/src/demo"})
        assert status == 401
        assert body["ok"] is False

    def test_wrong_token_returns_401(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        status, _body = _post(
            f"{url}/pods", {"project": "demo", "path": "/src/demo"}, token="wrong"
        )
        assert status == 401

    def test_no_auth_creates_nothing(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        _post(f"{url}/pods", {"project": "demo", "path": "/src/demo"})
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

    def test_missing_project_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post(f"{url}/pods", {"path": "/src/demo"}, token)
        assert status == 400
        assert "project" in body["error"].lower()

    def test_empty_project_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, _body = _post(f"{url}/pods", {"project": "", "path": "/src/demo"}, token)
        assert status == 400

    def test_unknown_blueprint_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post(
            f"{url}/pods",
            {"project": "demo", "path": "/src/demo", "blueprint": "wizard-pod"},
            token,
        )
        assert status == 400
        assert "wizard-pod" in body["error"] or "unknown blueprint" in body["error"].lower()
        assert _ids() == []

    def test_invalid_pod_field_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, _body = _post(
            f"{url}/pods", {"project": "demo", "path": "/src/demo", "pod": "medium"}, token
        )
        assert status == 400
        assert _ids() == []

    def test_non_numeric_budget_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, _body = _post(
            f"{url}/pods",
            {"project": "demo", "path": "/src/demo", "budget": "lots"},
            token,
        )
        assert status == 400
        assert _ids() == []

    def test_invalid_verify_cmd_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, _body = _post(
            f"{url}/pods",
            {"project": "demo", "path": "/src/demo", "verifyCmd": "line one\nline two"},
            token,
        )
        assert status == 400
        assert _ids() == []


# ── success ──────────────────────────────────────────────────────────────────


class TestSuccess:
    def test_default_blueprint_creates_lead_and_implementer(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        status, body = _post(f"{url}/pods", {"project": "demo", "path": "/src/demo"}, token)
        assert status == 201
        assert body["ok"] is True
        assert body["project"] == "demo"
        assert body["blueprint"] == "software"
        ids = sorted(m["id"] for m in body["members"])
        assert ids == ["demo-implementer", "demo-lead"]
        for m in body["members"]:
            assert m["role"] in ("lead", "implementer")
            assert m["model"]

    def test_workspaces_actually_exist_on_disk(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        _post(f"{url}/pods", {"project": "demo", "path": "/src/demo"}, token)
        for mid in ("demo-lead", "demo-implementer"):
            ws = _ws(mid)
            assert ws.is_dir()
            for f in ("SOUL.md", "AGENTS.md", "HEARTBEAT.md", ".docket-meta.json"):
                assert (ws / f).is_file(), f"{mid}: missing {f}"
        assert sorted(_ids()) == ["demo-implementer", "demo-lead"]

    def test_explicit_blueprint_is_honoured(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post(f"{url}/pods", {"project": "myops", "blueprint": "ops"}, token)
        assert status == 201
        assert body["blueprint"] == "ops"
        assert sorted(m["role"] for m in body["members"]) == ["lead", "monitor", "operator"]


# ── idempotence ──────────────────────────────────────────────────────────────


class TestIdempotence:
    def test_existing_project_returns_409_and_is_untouched(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        _pod.build_pod_from_blueprint("demo", "software", location="/src/demo")
        before = sorted(_ids())

        status, body = _post(f"{url}/pods", {"project": "demo", "path": "/other/path"}, token)

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
        real_write = _pp._write_member_workspace

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

        monkeypatch.setattr(_pp, "_write_member_workspace", staged_write)
        outcomes: dict[str, object] = {}

        def provision() -> None:
            name = threading.current_thread().name
            try:
                outcomes[name] = _pp.provision_pod("race", "software", location="/src/race")
            except Exception as exc:
                outcomes[name] = exc

        winner = threading.Thread(target=provision, name="winner")
        loser = threading.Thread(target=provision, name="loser")
        winner.start()
        assert winner_at_first_member.wait(timeout=2)
        loser.start()
        winner.join(timeout=5)
        loser.join(timeout=5)

        assert not winner.is_alive()
        assert not loser.is_alive()
        assert isinstance(outcomes["winner"], _pp.PodProvisionResult)
        assert isinstance(outcomes["loser"], _pp.PodAlreadyExistsError)
        assert sorted(_ids()) == ["race-implementer", "race-lead"]
        allocation = _store.read_json(_cfg.PORT_ALLOC_FILE)
        assert "race" in allocation["allocations"]
        scratch = _cfg.pod_scratch_dir("race")
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
        runtime = _cfg.PODS_DIR / "flaky"
        scratch_marker = runtime / ".scratch" / "keep.txt"
        workdir_marker = runtime / "workdir" / "keep.txt"
        scratch_marker.parent.mkdir(parents=True)
        workdir_marker.parent.mkdir(parents=True)
        scratch_marker.write_text("preserve scratch")
        workdir_marker.write_text("preserve workdir")

        calls = {"n": 0}
        real_write = _pp._write_member_workspace

        def flaky_write(*args: Any, **kwargs: Any) -> None:
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("disk full (induced failure)")
            return real_write(*args, **kwargs)

        monkeypatch.setattr(_pp, "_write_member_workspace", flaky_write)

        with pytest.raises(_pp.PodProvisionError):
            _pp.provision_pod("flaky", "software", location="/src/flaky")

        assert calls["n"] == 2
        assert scratch_marker.read_text() == "preserve scratch"
        assert workdir_marker.read_text() == "preserve workdir"
        assert "flaky" not in _store.read_json(_cfg.PORT_ALLOC_FILE).get("allocations", {})

    def test_core_level_rollback_leaves_nothing_behind(
        self, pod_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Force the SECOND member's real workspace write to fail (the Lead is created first) and
        prove nothing survives: no workspace dir, no fleet registration, no allocation."""
        calls = {"n": 0}
        real_write = _pp._write_member_workspace

        def flaky_write(*args: Any, **kwargs: Any) -> None:
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("disk full (induced failure)")
            return real_write(*args, **kwargs)

        monkeypatch.setattr(_pp, "_write_member_workspace", flaky_write)

        with pytest.raises(_pp.PodProvisionError):
            _pp.provision_pod("flaky", "software", location="/src/flaky")

        # The Lead really was created (call #1 succeeded) and then rolled back.
        assert calls["n"] == 2
        assert not _ws("flaky-lead").exists()
        assert not _ws("flaky-implementer").exists()
        assert _ids() == []
        alloc = _store.read_json(_cfg.PORT_ALLOC_FILE)
        assert "flaky" not in alloc.get("allocations", {})
        assert not _cfg.pod_scratch_dir("flaky").exists()

    def test_http_route_reports_500_and_leaves_nothing_behind(
        self, live_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        url, token = live_server
        calls = {"n": 0}
        real_write = _pp._write_member_workspace

        def flaky_write(*args: Any, **kwargs: Any) -> None:
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("disk full (induced failure)")
            return real_write(*args, **kwargs)

        monkeypatch.setattr(_pp, "_write_member_workspace", flaky_write)

        status, body = _post(f"{url}/pods", {"project": "flaky", "path": "/src/flaky"}, token)

        assert status == 500
        assert body["ok"] is False
        assert calls["n"] == 2
        assert not _ws("flaky-lead").exists()
        assert not _ws("flaky-implementer").exists()
        assert _ids() == []
        alloc = _store.read_json(_cfg.PORT_ALLOC_FILE)
        assert "flaky" not in alloc.get("allocations", {})


# ── docket add and POST /pods share one code path ───────────────────────────


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

        # The CLI path: what cli/_agents.py::run_add calls for the interactive
        # flow (build_pod_from_blueprint is a thin rendering wrapper over
        # provision_pod).
        cli_created = _pod.build_pod_from_blueprint(
            "cliproj", "software", location="/src/cliproj", source="interactive"
        )
        assert cli_created

        # The HTTP path.
        status, _body = _post(
            f"{url}/pods", {"project": "httpproj", "path": "/src/httpproj"}, token
        )
        assert status == 201

        assert len(seen) == 2
        assert seen[0]["kwargs"]["source"] == "interactive"
        assert seen[1]["kwargs"]["source"] == "http"
        # Both real pods were actually created through the one intercepted call.
        assert sorted(_ids()) == [
            "cliproj-implementer",
            "cliproj-lead",
            "httpproj-implementer",
            "httpproj-lead",
        ]


# ── pod/budget/verifyCmd overrides thread through ───────────────────────────


class TestOverridesThreaded:
    def test_pod_full_gives_the_four_role_roster(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post(
            f"{url}/pods", {"project": "demo", "path": "/src/demo", "pod": "full"}, token
        )
        assert status == 201
        assert sorted(m["role"] for m in body["members"]) == [
            "implementer",
            "lead",
            "reviewer",
            "tester",
        ]

    def test_budget_overrides_blueprint_default(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, _body = _post(
            f"{url}/pods", {"project": "myresearch", "blueprint": "research", "budget": 42}, token
        )
        assert status == 201
        raw = json.loads((_ws("myresearch-lead") / ".docket-meta.json").read_text())
        assert float(raw["budgetUsd"]) == 42.0

    def test_verify_cmd_applied_to_implementer_only(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, _body = _post(
            f"{url}/pods",
            {"project": "demo", "path": "/src/demo", "verifyCmd": "npm test"},
            token,
        )
        assert status == 201
        impl_meta = json.loads((_ws("demo-implementer") / ".docket-meta.json").read_text())
        assert impl_meta["verifyCmd"] == "npm test"
        lead_meta = json.loads((_ws("demo-lead") / ".docket-meta.json").read_text())
        assert "verifyCmd" not in lead_meta
