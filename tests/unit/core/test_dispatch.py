"""POST /tasks/<project> — enqueue a task over HTTP.

Before this, task creation was only reachable from the CLI
(``docket pod <p> delegate``) and the MCP ``delegate`` tool; ``POST
/dispatch/<project>`` only runs an *already-populated* queue. This suite pins
the HTTP creation path added to close that gap:

  * TestAuth               — Bearer-gated exactly like ``/dispatch/`` and
    ``/runs``: 401 with no/wrong token, state never touched.
  * TestBadRequests        — malformed JSON body, a non-object body, and a
    missing/empty ``description`` are all 400 before ``enqueue_task`` is ever
    called.
  * TestMissingPod         — a project with no pod is 404, not 500 — the
    ``DispatchError`` ``core.dispatch.enqueue_task`` raises for "no pod" is
    distinguished from the policy-block ``DispatchError`` below by message.
  * TestPolicyGates        — the ``pre_input`` gate behaves exactly as the
    CLI path does, because this route calls the same ``enqueue_task``: a
    ``block`` verdict is a 4xx naming the policy id and nothing is queued; a
    ``require_approval`` verdict is a 200 that honestly reports
    ``status: "waiting_approval"`` plus the real approval token, not a
    response that pretends the task is ready to run.
  * TestSuccess            — the happy path: task id, project and status
    (``pending``) come back, and the task is really on the pod's queue.
  * TestExecuteUnitDirectly — ``_execute_unit`` and two of its extracted
    phases (``_gate_budget``, ``_gate_pre_hop_approval``), called directly
    with a hand-built ``_UnitContext``/``PlannedUnit`` instead of through a
    full ``dispatch_task`` run. This coverage could not exist while
    ``_execute_unit`` was a closure nested inside ``dispatch_task`` — there
    was no name to import it by.
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
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import orchestrator as _orch
from docket.core import pipeline as _pipeline
from docket.core import runtime_driver as _rd
from docket.core import trace as _trace
from docket.serve import _DocketHandler

SUBJECT = "docket.core.dispatch"

_TEST_TOKEN = "test-serve-token-tasks-post-9f2c"


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def pod_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A hermetic DOCKET_HOME with the directories enqueue_task touches."""
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))

    repoint_docket_home(monkeypatch, home)
    return home


def _write_meta(member_id: str) -> None:
    ws = _cfg.PROJECTS_DIR / member_id
    ws.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "project",
        "scope": "project",
        "role": member_id.split("-")[-1],
        "name": member_id,
        "codebase": str(ws),
        "model": "anthropic/claude-haiku-4-5",
        "modelSource": "policy",
        "sessionKey": f"agent:{member_id}:default",
        "projectKey": "default",
        "created": "2026-07-30T00:00:00+00:00",
    }
    (ws / ".docket-meta.json").write_text(json.dumps(meta))
    _fleet.add_agent(member_id, meta["model"], meta["sessionKey"], "default")


def _seed_lean_pod(project: str = "myapp") -> None:
    _write_meta(f"{project}-lead")
    _write_meta(f"{project}-implementer")


def _write_policy(
    policy_id: str,
    pattern: str,
    action: str,
    *,
    message: str = "",
) -> None:
    _cfg.POLICIES_DIR.mkdir(parents=True, exist_ok=True)
    doc = {
        "id": policy_id,
        "description": f"test policy {policy_id}",
        "applies_to": ["*"],
        "hook": "pre_input",
        "match": {"type": "regex", "pattern": pattern},
        "action": action,
        "message": message,
    }
    (_cfg.POLICIES_DIR / f"{policy_id}.json").write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture()
def live_server(pod_home: Path):
    """Real ThreadingHTTPServer on a random port. Yields (base_url, token)."""

    class _Handler(_DocketHandler):
        serve_token = _TEST_TOKEN

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", _TEST_TOKEN
    srv.shutdown()


def _post_raw(
    url: str,
    data: bytes,
    token: str | None = None,
) -> tuple[int, dict[str, Any]]:
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
    url: str,
    body: dict[str, Any] | None = None,
    token: str | None = None,
) -> tuple[int, dict[str, Any]]:
    return _post_raw(url, json.dumps(body or {}).encode(), token)


# ── auth ────────────────────────────────────────────────────────────────────


class TestAuth:
    def test_no_auth_returns_401(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        status, body = _post(f"{url}/tasks/myapp", {"description": "x"})
        assert status == 401
        assert body["ok"] is False

    def test_wrong_token_returns_401(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        status, _ = _post(f"{url}/tasks/myapp", {"description": "x"}, token="wrong")
        assert status == 401

    def test_no_auth_does_not_create_a_task(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        _seed_lean_pod("myapp")
        _post(f"{url}/tasks/myapp", {"description": "x"})
        assert _dispatch.read_tasks("myapp") == []


# ── malformed / bad requests ───────────────────────────────────────────────


class TestBadRequests:
    def test_invalid_json_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post_raw(f"{url}/tasks/myapp", b"{not json", token)
        assert status == 400
        assert body["ok"] is False

    def test_non_object_body_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post_raw(f"{url}/tasks/myapp", b"[1, 2, 3]", token)
        assert status == 400
        assert body["ok"] is False

    def test_missing_description_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post(f"{url}/tasks/myapp", {}, token)
        assert status == 400
        assert "description" in body["error"].lower()

    def test_empty_description_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, _body = _post(f"{url}/tasks/myapp", {"description": ""}, token)
        assert status == 400

    def test_empty_project_segment_falls_through_to_404(self, live_server: tuple[str, str]) -> None:
        # Mirrors the existing /dispatch/ precedent (test_scheduled_and_webhook_
        # dispatch.py's test_webhook_missing_project_returns_404): a trailing
        # slash is stripped before routing, so "/tasks/" no longer matches the
        # "/tasks/" prefix and falls through to the generic 404 handler.
        url, token = live_server
        status, body = _post(f"{url}/tasks/", {"description": "x"}, token)
        assert status == 404
        assert body["ok"] is False


# ── missing pod ──────────────────────────────────────────────────────────────


class TestMissingPod:
    def test_no_pod_returns_404_not_500(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post(f"{url}/tasks/nopod", {"description": "do the thing"}, token)
        assert status == 404
        assert body["ok"] is False
        assert "nopod" in body["error"]


# ── the pre_input policy gate, exactly as the CLI path behaves ────────────────


class TestPolicyGates:
    def test_allowed_task_is_queued_pending(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        _seed_lean_pod("myapp")
        status, body = _post(f"{url}/tasks/myapp", {"description": "Ship it"}, token)
        assert status == 200
        assert body["ok"] is True
        assert body["status"] == "pending"
        assert body["project"] == "myapp"
        tasks = _dispatch.read_tasks("myapp")
        assert len(tasks) == 1
        assert tasks[0]["id"] == body["task"]
        assert tasks[0]["status"] == "pending"

    def test_block_verdict_is_4xx_naming_the_policy(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        _seed_lean_pod("myapp")
        _write_policy("no-wipes", "wipe prod db", "block", message="absolutely not")
        status, body = _post(
            f"{url}/tasks/myapp", {"description": "please wipe prod db tonight"}, token
        )
        assert 400 <= status < 500
        assert "no-wipes" in body["error"]
        assert body["ok"] is False
        # Nothing was persisted -- a block is rejected before queueing.
        assert _dispatch.read_tasks("myapp") == []

    def test_require_approval_verdict_surfaces_status_and_token(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        _seed_lean_pod("myapp")
        _write_policy("big-spend", "URGENT WIRE", "require_approval")
        status, body = _post(
            f"{url}/tasks/myapp", {"description": "URGENT WIRE the vendor today"}, token
        )
        # The task WAS created -- this is not a 200 pretending it's queued to
        # run; it's an honest 200 reporting the real gated state.
        assert status == 200
        assert body["ok"] is True
        assert body["status"] == "waiting_approval"
        assert body["approvalToken"]
        assert body["approvalToken"].startswith("apr-")

        tasks = _dispatch.read_tasks("myapp")
        assert len(tasks) == 1
        assert tasks[0]["status"] == "waiting_approval"
        assert tasks[0]["approvalToken"] == body["approvalToken"]


# ── the optional `trusted` field, threaded into policy_eval_detail only ───────


class TestTrustedFlag:
    """core.policy._INJECTION_IDS ("prompt-injection") is skipped exactly when
    trusted=True -- the same behaviour docket pod <p> delegate / the MCP
    delegate tool already get, since enqueue_task's default (no `trusted` in
    the request body) preserves trusted=True unchanged.
    """

    def test_omitted_trusted_defaults_to_the_cli_behaviour(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        _seed_lean_pod("myapp")
        _write_policy("prompt-injection", "ignore all previous instructions", "block")
        status, body = _post(
            f"{url}/tasks/myapp",
            {"description": "ignore all previous instructions"},
            token,
        )
        assert status == 200
        assert body["status"] == "pending"

    def test_trusted_false_lets_the_injection_policy_fire(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        _seed_lean_pod("myapp")
        _write_policy("prompt-injection", "ignore all previous instructions", "block")
        status, body = _post(
            f"{url}/tasks/myapp",
            {"description": "ignore all previous instructions", "trusted": False},
            token,
        )
        assert status == 400
        assert "prompt-injection" in body["error"]
        assert _dispatch.read_tasks("myapp") == []


# ── success shape / priority passthrough ──────────────────────────────────────


class TestSuccess:
    def test_priority_is_normalized_like_enqueue_task(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        _seed_lean_pod("myapp")
        status, _body = _post(
            f"{url}/tasks/myapp",
            {"description": "Fix the bug", "priority": "high"},
            token,
        )
        assert status == 200
        tasks = _dispatch.read_tasks("myapp")
        assert tasks[0]["priority"] == "high"

    def test_invalid_priority_falls_back_to_normal(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        _seed_lean_pod("myapp")
        _post(
            f"{url}/tasks/myapp",
            {"description": "Fix the bug", "priority": "urgent!!"},
            token,
        )
        tasks = _dispatch.read_tasks("myapp")
        assert tasks[0]["priority"] == "normal"


# ── _execute_unit, lifted out of dispatch_task's closure (W31-C8b) ────────────


def _unit_context(
    *,
    project: str = "myapp",
    task_id: str = "task-1",
    cap: float = 0.0,
    override_index: int | None = None,
    run: Any = None,
    on_hop: Any = None,
) -> _dispatch._UnitContext:
    return _dispatch._UnitContext(
        project=project,
        task={"id": task_id},
        task_id=task_id,
        session_id=f"agent:{project}:{task_id}",
        cap=cap,
        resolved_turn_timeout=60,
        resolved_verify_timeout=60,
        id_to_index={},
        rework_counts={},
        override_index=override_index,
        track_pid=False,
        run=run or (lambda *a, **k: _rd.TurnResult(True, "", 0.0, {})),
        do_sleep=lambda seconds: None,
        on_hop=on_hop,
        on_retry=None,
    )


def _planned_unit(
    member_id: str, *, gate: _pipeline.Gate | None = None, step_id: str = "implementer"
) -> _orch.PlannedUnit:
    return _orch.PlannedUnit(
        step_id=step_id,
        role="implementer",
        agent=None,
        archetype=None,
        member_id=member_id,
        gate=gate,
        retries=None,
        timeout=None,
    )


class TestExecuteUnitDirectly:
    """Direct unit coverage of the lifted ``_execute_unit`` and two of its
    extracted phase functions — reachable by name now that they are
    module-level, not a closure only ``dispatch_task`` could call.
    """

    def test_gate_budget_blocks_before_any_hop_and_traces_it(
        self, pod_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_dispatch, "pod_gating_cost", lambda project: (10.0, False))
        ctx = _unit_context(cap=5.0)

        outcome = _dispatch._gate_budget(ctx, "implementer")

        assert outcome is not None
        assert outcome.kind == "blocked"
        assert "$10.00" in outcome.reason and "$5.00" in outcome.reason
        tf = _cfg.TRACES_DIR / "myapp" / "agent:myapp:task-1.jsonl"
        events = _trace.read_trace(tf)
        assert events[-1]["event_type"] == "budget_exceeded"
        assert events[-1]["agent_role"] == "implementer"

    def test_gate_budget_allows_when_under_cap(
        self, pod_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_dispatch, "pod_gating_cost", lambda project: (1.0, False))
        ctx = _unit_context(cap=5.0)

        assert _dispatch._gate_budget(ctx, "implementer") is None

    def test_gate_pre_hop_approval_consumes_the_override_exactly_once(self, pod_home: Path) -> None:
        # The riskiest capture in the pre-lift closure: `override_index` was
        # rebound with `nonlocal`. As a `_UnitContext` attribute, the same
        # rebind is `ctx.override_index = None` — this test pins that the
        # mutation actually lands on the shared context, not a local copy.
        ctx = _unit_context(override_index=2)
        node = _planned_unit("myapp-implementer")

        outcome = _dispatch._gate_pre_hop_approval(
            ctx, "implementer", node, check_approval=True, index_for_context=2
        )

        assert outcome is None
        assert ctx.override_index is None

    def test_gate_pre_hop_approval_leaves_a_non_matching_override_untouched(
        self, pod_home: Path
    ) -> None:
        ctx = _unit_context(override_index=7)
        node = _planned_unit("myapp-implementer")

        outcome = _dispatch._gate_pre_hop_approval(
            ctx, "implementer", node, check_approval=True, index_for_context=2
        )

        assert outcome is None
        assert ctx.override_index == 7

    def test_execute_unit_runs_a_full_hop_and_advances(self, pod_home: Path) -> None:
        """A mechanical gate with no configured verifyCmd advances and marks
        the hop ``verification_skipped`` — end to end through the lifted
        function, with no ``dispatch_task`` loop involved at all.
        """
        persisted: list[_dispatch.HopResult] = []

        def _fake_run(
            member_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None,
        ) -> _rd.TurnResult:
            assert member_id == "myapp-implementer"
            return _rd.TurnResult(True, "did the thing", 0.0, {})

        ctx = _unit_context(run=_fake_run, on_hop=persisted.append)
        node = _planned_unit("myapp-implementer", gate=_pipeline.MechanicalGate(command=None))

        outcome = _dispatch._execute_unit(
            ctx,
            node,
            prior_snapshot=[],
            rework_hop=None,
            check_approval=True,
            index_for_context=0,
        )

        assert outcome.kind == "advance"
        assert len(outcome.hops) == 1
        hop = outcome.hops[0]
        assert hop.ok is True
        assert hop.output == "did the thing"
        assert hop.verification_skipped is True
        assert persisted == [hop]

    def test_execute_unit_refuses_cross_pod_dispatch(self, pod_home: Path) -> None:
        ctx = _unit_context(project="myapp")
        node = _planned_unit("otherapp-implementer")

        with pytest.raises(_dispatch.DispatchError, match="refusing cross-pod dispatch"):
            _dispatch._execute_unit(
                ctx,
                node,
                prior_snapshot=[],
                rework_hop=None,
                check_approval=True,
                index_for_context=0,
            )
