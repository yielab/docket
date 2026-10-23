"""POST /tasks/<project> — enqueue a task over HTTP.

See specs/data/serve-read-api.spec.md ("POST /tasks/<project>") for the
endpoint contract this suite pins. Test classes: TestAuth (Bearer-gated
like ``/dispatch/`` and ``/runs``), TestBadRequests (malformed/invalid
bodies are 400 before ``enqueue_task`` runs), TestMissingPod (no pod is
404, not 500), TestPolicyGates (``pre_input`` gate behaves as the CLI
path does, since this route calls the same ``enqueue_task``),
TestSuccess (happy path), and TestExecuteUnitDirectly (``_execute_unit``
and two extracted phases, called directly with a hand-built
``_UnitContext``/``PlannedUnit``).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import record_isolation_off
from tests.pods import build_pod

from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import orchestrator as _orch
from docket.core import pipeline as _pipeline
from docket.core import pod as _pod
from docket.core import runtime_driver as _rd
from docket.core import trace as _trace
from docket.core.llm import ChatResponse, TokenUsage, assistant
from docket.edges.adapters import docket_runtime as _drt
from docket.kernel import clock as _clock
from docket.kernel.home import Home, current_home, use_home
from docket.kernel.threads import ContextHTTPServer
from docket.serve import _DocketHandler

SUBJECT = "docket.core.dispatch"

_TEST_TOKEN = "test-serve-token-tasks-post-9f2c"


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def pod_home(tmp_path: Path) -> Iterator[Path]:
    """A hermetic DOCKET_HOME with the directories enqueue_task touches."""
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))

    with use_home(Home(home)):
        yield home


def _write_meta(member_id: str, extra: dict[str, Any] | None = None) -> None:
    ws = current_home().projects_dir / member_id
    ws.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "project",
        "scope": "project",
        "role": member_id.split("-")[-1],
        "name": member_id,
        "codebase": str(ws),
        "model": "anthropic/claude-haiku-4-5",
        "sessionKey": f"agent:{member_id}:default",
        "projectKey": "default",
        "created": "2026-07-30T00:00:00+00:00",
    }
    if extra:
        meta.update(extra)
    (ws / ".docket-meta.json").write_text(json.dumps(meta))
    _fleet.add_agent(member_id)


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
    current_home().policies_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "id": policy_id,
        "description": f"test policy {policy_id}",
        "applies_to": ["*"],
        "hook": "pre_input",
        "match": {"type": "regex", "pattern": pattern},
        "action": action,
        "message": message,
    }
    (current_home().policies_dir / f"{policy_id}.json").write_text(
        json.dumps(doc), encoding="utf-8"
    )


@pytest.fixture()
def live_server(pod_home: Path):
    """Real ThreadingHTTPServer on a random port. Yields (base_url, token)."""

    class _Handler(_DocketHandler):
        serve_token = _TEST_TOKEN

    srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
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

    def test_empty_project_segment_returns_400(self, live_server: tuple[str, str]) -> None:
        # Mirrors the /dispatch/ precedent (test_scheduled_and_webhook_dispatch.py's
        # test_webhook_missing_project_returns_400): a trailing slash is stripped
        # before routing, but the bare "/tasks" path still reaches auth and then
        # the handler's own "Missing project" 400, not a pre-auth 404.
        url, token = live_server
        status, body = _post(f"{url}/tasks/", {"description": "x"}, token)
        assert status == 400
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
        assert status == 201
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
        # run; it's an honest 201 reporting the real gated state.
        assert status == 201
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
    trusted=True -- matching the CLI/MCP callers, since enqueue_task's
    default (no `trusted` in the request body) preserves trusted=True."""

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
        assert status == 201
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
        assert status == 201
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


class TestEnqueueAddressableOptions:
    def test_fields_are_stored_verbatim_and_unset_ones_are_absent(self, pod_home: Path) -> None:
        _seed_lean_pod()

        task = _dispatch.enqueue_task(
            "myapp", "x", channel="cli", external_ref="A-1", max_tokens=10, base_ref="main"
        )

        assert (task["externalRef"], task["maxTokens"], task["baseRef"]) == ("A-1", 10, "main")
        assert not {"idempotencyKey", "pipeline", "gate", "restrictions"} & set(task)
        assert _dispatch.read_tasks("myapp")[0]["externalRef"] == "A-1"

    def test_the_same_key_returns_the_queued_task_and_audits_once(self, pod_home: Path) -> None:
        from docket.core import audit as _audit

        _seed_lean_pod()
        first, created_first = _dispatch.enqueue_task_once(
            "myapp", "x", channel="cli", idempotency_key="k"
        )
        second, created_second = _dispatch.enqueue_task_once(
            "myapp", "other text", channel="http", idempotency_key="k"
        )

        assert (created_first, created_second) == (True, False)
        assert second["id"] == first["id"]
        assert len(_dispatch.read_tasks("myapp")) == 1
        assert len([e for e in _audit.read_audit() if e["action"] == "task.enqueue"]) == 1

    def test_a_widening_restriction_raises_the_subclass_and_persists_nothing(
        self, pod_home: Path
    ) -> None:
        _seed_lean_pod()

        with pytest.raises(_dispatch.TaskRestrictionError):
            _dispatch.enqueue_task("myapp", "x", channel="cli", restrictions={"network": "open"})
        with pytest.raises(_dispatch.DispatchError) as shape:
            _dispatch.enqueue_task("myapp", "x", channel="cli", max_tokens=0)

        assert not isinstance(shape.value, _dispatch.TaskRestrictionError)
        assert _dispatch.read_tasks("myapp") == []


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
    """Direct unit coverage of ``_execute_unit`` and two extracted phase
    functions -- reachable by name since they are module-level, not a
    closure only ``dispatch_task`` could call."""

    def test_gate_budget_blocks_before_any_hop_and_traces_it(
        self, pod_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_dispatch, "pod_gating_cost", lambda project: (10.0, False))
        ctx = _unit_context(cap=5.0)

        outcome = _dispatch._gate_budget(ctx, "implementer")

        assert outcome is not None
        assert outcome.kind == "blocked"
        assert "$10.00" in outcome.reason and "$5.00" in outcome.reason
        tf = current_home().traces_dir / "myapp" / "agent:myapp:task-1.jsonl"
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
        the hop ``verification_skipped``, end to end, with no
        ``dispatch_task`` loop involved."""
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


_UNPRICED = "ai-gateway/acme/model-x"


def _budget_warnings() -> list[dict[str, Any]]:
    tf = current_home().traces_dir / "myapp" / "agent:myapp:task-1.jsonl"
    events = _trace.read_trace(tf) if tf.exists() else []
    return [e["payload"] for e in events if e["event_type"] == "budget_warning"]


def _run_one_hop(cap: float, node: _orch.PlannedUnit) -> _dispatch._UnitOutcome:
    ctx = _unit_context(cap=cap, run=lambda *a, **k: _rd.TurnResult(True, "done", 0.0, {}))
    return _dispatch._execute_unit(
        ctx, node, prior_snapshot=[], rework_hop=None, check_approval=True, index_for_context=0
    )


class TestUnpricedModelUnderABudget:
    """A budget cannot stop spend it cannot price: dispatch warns and runs the hop."""

    @pytest.fixture(autouse=True)
    def _nothing_spent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_dispatch, "pod_gating_cost", lambda project: (0.0, False))

    def test_an_unpriced_member_model_warns_and_still_runs(self, pod_home: Path) -> None:
        _write_meta("myapp-implementer", {"model": _UNPRICED})
        outcome = _run_one_hop(5.0, _planned_unit("myapp-implementer"))
        assert outcome.kind == "advance"
        [warning] = _budget_warnings()
        assert warning["action"] == "unpriced_model"
        assert _UNPRICED in warning["reason"] and "$5.00" in warning["reason"]

    def test_a_step_model_is_the_one_checked(self, pod_home: Path) -> None:
        _write_meta("myapp-implementer")
        node = dataclasses.replace(_planned_unit("myapp-implementer"), model=_UNPRICED)
        _run_one_hop(5.0, node)
        assert [w["action"] for w in _budget_warnings()] == ["unpriced_model"]

    @pytest.mark.parametrize(
        ("cap", "model"),
        [(5.0, "anthropic/claude-haiku-4-5"), (5.0, "local/local-model"), (0.0, _UNPRICED)],
    )
    def test_no_warning_when_priced_local_or_uncapped(
        self, pod_home: Path, cap: float, model: str
    ) -> None:
        _write_meta("myapp-implementer", {"model": model})
        _run_one_hop(cap, _planned_unit("myapp-implementer"))
        assert _budget_warnings() == []

    def test_the_pod_lists_its_unpriced_models_only_under_a_budget(self, pod_home: Path) -> None:
        _write_meta("myapp-lead", {"model": "local/local-model"})
        _write_meta("myapp-implementer", {"model": _UNPRICED})
        assert _dispatch.unpriced_budget_models("myapp") == []
        _write_meta("myapp-lead", {"model": "local/local-model", "budgetUsd": 3})
        assert _dispatch.unpriced_budget_models("myapp") == [_UNPRICED]


class TestDeterministicRefusalFailsOnlyThatTask:
    """A claimed-task ``DispatchError`` (pod-dispatch.spec.md, "Deterministic refusal inside a
    claimed task") must settle as ``"failed"``, never propagate out of ``dispatch_pod``."""

    def test_dispatch_task_settles_a_cross_pod_refusal_as_failed(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        spec = _pipeline.PipelineSpec(
            name="alien-step",
            steps=[
                _pipeline.Step(id="lead", role="lead"),
                _pipeline.Step(id="alien", agent="ghost-lead"),
            ],
        )
        calls: list[str] = []

        def _runner(
            agent_id: str, session_key: str, message: str, timeout: int, env: dict[str, str] | None
        ) -> _rd.TurnResult:
            calls.append(agent_id)
            return _rd.TurnResult(True, "done", 0.0, {})

        task = {"id": "task-1", "description": "x", "status": "running"}

        result = _dispatch.dispatch_task("myapp", task, runner=_runner, spec=spec)

        assert result.status == "failed"
        assert "refusing cross-pod dispatch" in result.reason
        assert result.failure_kind == "dispatch_refused"
        # The lead step ran and its hop is preserved; the alien step never got a turn.
        assert [h.role for h in result.hops] == ["lead"]
        assert calls == ["myapp-lead"]

    def test_a_crash_is_not_caught_and_still_leaves_no_result(self, pod_home: Path) -> None:
        """A real crash (any exception other than DispatchError) must still propagate --
        catching it too would wrongly settle an orphaned claim as 'failed' instead of leaving
        it 'running' for the stale-claim sweep."""
        _seed_lean_pod("myapp")

        def _crasher(
            agent_id: str, session_key: str, message: str, timeout: int, env: dict[str, str] | None
        ) -> _rd.TurnResult:
            raise RuntimeError("simulated crash")

        task = {"id": "task-1", "description": "x", "status": "running"}

        with pytest.raises(RuntimeError, match="simulated crash"):
            _dispatch.dispatch_task("myapp", task, runner=_crasher)


class TestBaseRefRefusedAtClaim:
    """A task whose ``baseRef`` cannot be honoured fails at claim: no hop, ``failureKind``
    ``base_ref``, and the loop moves on to the next task."""

    def _runner(self, calls: list[str]) -> Any:
        def _run(
            agent_id: str, session_key: str, message: str, timeout: int, env: dict[str, str] | None
        ) -> _rd.TurnResult:
            calls.append(agent_id)
            return _rd.TurnResult(True, "done", 0.0, {})

        return _run

    def test_an_unhonourable_base_ref_fails_the_task_with_no_hop(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        _dispatch.enqueue_task("myapp", "needs a base", channel="cli")
        _dispatch.enqueue_task("myapp", "plain", channel="cli")
        queue = _dispatch.read_tasks("myapp")
        queue[0]["baseRef"] = "nope"
        from docket.edges import store as _store

        _store.write_json(_dispatch.pod_task_list_path("myapp"), {"tasks": queue})
        calls: list[str] = []

        results = _dispatch.dispatch_pod("myapp", runner=self._runner(calls))

        first, second = _dispatch.read_tasks("myapp")
        assert first["status"] == "failed"
        assert first["failureKind"] == "base_ref"
        assert "nope" in first["reason"]
        assert first["hops"] == []
        assert first["claimId"] is None
        assert first["completedAt"]
        assert "worktree" not in first
        assert second["status"] == "done"
        assert [r.status for r in results] == ["failed", "done"]
        assert all(a.startswith("myapp-") for a in calls) and calls

    def test_the_refusal_is_traced_as_dispatch_refused_naming_the_ref(
        self, pod_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DOCKET_NO_TRACE", "0")
        _seed_lean_pod("myapp")
        _dispatch.enqueue_task("myapp", "needs a base", channel="cli")
        queue = _dispatch.read_tasks("myapp")
        queue[0]["baseRef"] = "nope"
        from docket.edges import store as _store

        _store.write_json(_dispatch.pod_task_list_path("myapp"), {"tasks": queue})

        _dispatch.dispatch_pod("myapp", runner=self._runner([]))

        events = [
            e
            for f in _trace.project_trace_dir("myapp").glob("*.jsonl")
            for e in _trace.read_trace(f)
            if e.get("event_type") == "dispatch_refused"
        ]
        assert len(events) == 1
        assert "nope" in json.dumps(events[0])

    def test_base_ref_is_not_resumable(self) -> None:
        assert "base_ref" not in _dispatch.RESUMABLE_FAILURE_KINDS

    def test_refuse_claimed_task_settles_any_failure_kind(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        _put_task(
            "myapp",
            {
                "id": "t1",
                "description": "x",
                "status": "running",
                "claimId": "c",
                "hops": [{"role": "lead"}],
            },
        )

        res = _dispatch._refuse_claimed_task("myapp", {"id": "t1"}, "pipeline", "no such pipeline")

        (stored,) = _dispatch.read_tasks("myapp")
        assert (res.status, res.failure_kind, res.reason) == (
            "failed",
            "pipeline",
            "no such pipeline",
        )
        assert stored["status"] == "failed"
        assert stored["failureKind"] == "pipeline"
        assert stored["reason"] == "no such pipeline"
        assert stored["claimId"] is None
        assert stored["hops"] == [{"role": "lead"}]


class TestResumableFailureKinds:
    """``_eligible_for_claim``/``_apply_result`` treat ``dispatch_refused`` the same way they
    already treat ``stale_claim`` -- resumable, immediately, with no staleness math -- while an
    ordinary graded hop failure (no ``failureKind`` at all) stays non-resumable."""

    def test_dispatch_refused_is_eligible_only_with_resume(self) -> None:
        task = {"status": "failed", "failureKind": "dispatch_refused"}
        assert _dispatch._eligible_for_claim(task, resume=True) is True
        assert _dispatch._eligible_for_claim(task, resume=False) is False

    def test_a_plain_failed_task_is_never_eligible(self) -> None:
        task = {"status": "failed", "failureKind": ""}
        assert _dispatch._eligible_for_claim(task, resume=True) is False

    def test_apply_result_persists_a_failure_kind_when_the_result_carries_one(self) -> None:
        task: dict[str, Any] = {"status": "running", "failureKind": "stale_claim"}
        res = _dispatch.TaskResult(
            task_id="t1", status="failed", reason="boom", failure_kind="dispatch_refused"
        )

        _dispatch._apply_result(task, res)

        assert task["failureKind"] == "dispatch_refused"

    def test_apply_result_clears_a_stale_failure_kind_on_an_ordinary_result(self) -> None:
        task: dict[str, Any] = {"status": "running", "failureKind": "stale_claim"}
        res = _dispatch.TaskResult(task_id="t1", status="done", reason="")

        _dispatch._apply_result(task, res)

        assert "failureKind" not in task


class TestEffectivePipelineBlueprint:
    """``effective_pipeline(project, None)`` resolves the Lead's ``blueprint`` meta through
    ``core/blueprints.py::get_blueprint`` before falling back to the built-in default -- see
    pod-dispatch.spec.md "Pipeline order and participation"."""

    def test_research_pod_runs_its_blueprint_pipeline(self, pod_home: Path) -> None:
        _write_meta("myapp-lead", {"blueprint": "research"})
        for role in ("researcher", "analyst", "writer", "critic"):
            _write_meta(f"myapp-{role}")

        spec = _dispatch.effective_pipeline("myapp", None)

        assert [step.role for step in spec.steps] == [
            "lead",
            "researcher",
            "analyst",
            "writer",
            "critic",
        ]

    def test_research_pod_lead_message_names_the_researcher_not_the_implementer(
        self, pod_home: Path
    ) -> None:
        # A research pod has no Implementer -- its Lead must not tell the model
        # to plan for one. The research blueprint's `lead` step declares its
        # own `instructions` naming the Researcher, and `_hop_message` honors a
        # step override for `role: lead` (see role-archetypes.spec.md "Hop
        # instructions"), so this pipeline's Lead hop message never invents a
        # role the pod doesn't have.
        _write_meta("myapp-lead", {"blueprint": "research"})
        for role in ("researcher", "analyst", "writer", "critic"):
            _write_meta(f"myapp-{role}")

        spec = _dispatch.effective_pipeline("myapp", None)
        raw_step_instructions = _pipeline.step_instructions_by_id(spec)
        lead_instructions = raw_step_instructions.get("lead", "")

        message, _ = _dispatch._hop_message(
            {"description": "scan the market"},
            "lead",
            [],
            step_instructions=lead_instructions,
            project="myapp",
        )

        assert "Researcher" in message
        assert "Implementer" not in message

    def test_software_pod_is_unaffected(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")

        spec = _dispatch.effective_pipeline("myapp", None)

        assert [step.role for step in spec.steps] == [
            "lead",
            "implementer",
            "reviewer",
            "tester",
        ]

    def test_absent_blueprint_meta_falls_back_to_the_built_in_default(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")

        spec = _dispatch.effective_pipeline("myapp", None)

        assert spec == _pipeline.default_pipeline()

    def test_unknown_blueprint_falls_back_without_raising(self, pod_home: Path) -> None:
        _write_meta("myapp-lead", {"blueprint": "nope"})
        _write_meta("myapp-implementer")

        spec = _dispatch.effective_pipeline("myapp", None)

        assert [step.role for step in spec.steps] == [
            "lead",
            "implementer",
            "reviewer",
            "tester",
        ]

    def test_pod_rework_budget_patches_the_blueprint_pipeline_rework_edge(
        self, pod_home: Path
    ) -> None:
        _write_meta("myapp-lead", {"blueprint": "content", "maxReworkCycles": "3"})
        for role in ("writer", "critic"):
            _write_meta(f"myapp-{role}")

        spec = _dispatch.effective_pipeline("myapp", None)

        critic_step = next(step for step in spec.steps if step.id == "critic")
        assert isinstance(critic_step.gate, _pipeline.VerdictGate)
        assert critic_step.gate.rework is not None
        assert critic_step.gate.rework.max_cycles == 3

    def test_ops_pod_dispatch_reaches_waiting_approval_at_the_approval_step(
        self, pod_home: Path
    ) -> None:
        """The ``ops`` blueprint's Monitor step is gated by an ``ApprovalGate`` -- with a
        caller-spec-free dispatch now resolving the blueprint pipeline, an ops pod actually
        runs the Operator and then stops for sign-off, instead of running only the Lead."""
        _write_meta("myapp-lead", {"blueprint": "ops"})
        _write_meta("myapp-operator")
        _write_meta("myapp-monitor")

        def _run(
            member_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _rd.TurnResult:
            return _rd.TurnResult(True, f"done by {member_id}", 0.0, {})

        _dispatch.enqueue_task("myapp", "roll it out", channel="cli")
        results = _dispatch.dispatch_pod("myapp", runner=_run, spec=None)

        assert len(results) == 1
        assert results[0].status == "waiting_approval"
        assert results[0].approval_token


class TestBoundPipeline:
    """``PodSettings.pipeline`` binds a pipeline file as a pod's default for every
    caller-spec-free trigger, not only an explicit ``--file`` -- see
    pod-dispatch.spec.md, "Pipeline order and participation"."""

    _CUSTOM_YAML = (
        "name: custom-bound\n"
        "steps:\n"
        "  - id: kickoff\n"
        "    role: lead\n"
        "  - id: assemble\n"
        "    role: implementer\n"
        "    gate:\n"
        "      type: mechanical\n"
    )

    def _bind(self, project: str, text: str | None = None) -> str:
        """Seed a bound pipeline directly -- the docket-owned copy plus its Lead-meta hash --
        exactly what ``docket pod set pipeline <file>`` produces. Bypasses
        the CLI setter itself, which has its own integration coverage."""
        text = self._CUSTOM_YAML if text is None else text
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        path = _pod.bound_pipeline_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        _fleet.meta_set(_pod.member_id(project, "lead"), "pipeline", digest)
        return digest

    def test_effective_pipeline_resolves_the_bound_file_not_the_builtin_default(
        self, pod_home: Path
    ) -> None:
        _seed_lean_pod("myapp")
        self._bind("myapp")

        spec = _dispatch.effective_pipeline("myapp", None)

        assert [step.id for step in spec.steps] == ["kickoff", "assemble"]

    def test_a_serve_sweep_or_mcp_shaped_dispatch_runs_the_bound_files_steps(
        self, pod_home: Path
    ) -> None:
        """The exact call ``serve.py``'s sweep/schedule and ``cli/_mcp.py``'s dispatch tool
        both make -- ``dispatch_pod(project, ...)`` with no ``spec=`` kwarg -- so binding a
        pipeline changes every unattended trigger with zero changes to either caller."""
        _seed_lean_pod("myapp")
        self._bind("myapp")

        def _run(
            member_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> _rd.TurnResult:
            return _rd.TurnResult(True, f"done by {member_id}", 0.0, {})

        _dispatch.enqueue_task("myapp", "ship it", channel="cli")
        results = _dispatch.dispatch_pod("myapp", runner=_run, spec=None)

        assert len(results) == 1
        assert results[0].status == "done"
        assert [h.step_id for h in results[0].hops] == ["kickoff", "assemble"]

    def test_unbound_pod_is_unaffected(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")

        spec = _dispatch.effective_pipeline("myapp", None)

        assert spec == _pipeline.default_pipeline()

    def test_unset_restores_the_blueprint_default(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        self._bind("myapp")

        _fleet.meta_set(_pod.member_id("myapp", "lead"), "pipeline", None)

        spec = _dispatch.effective_pipeline("myapp", None)

        assert [step.role for step in spec.steps] == [
            "lead",
            "implementer",
            "reviewer",
            "tester",
        ]

    def test_a_hash_mismatch_refuses_loudly_instead_of_falling_back(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        self._bind("myapp")
        _pod.bound_pipeline_path("myapp").write_text("name: tampered\nsteps: []\n")

        with pytest.raises(_dispatch.DispatchError, match="no longer matches"):
            _dispatch.effective_pipeline("myapp", None)

    def test_a_missing_copy_refuses_loudly_instead_of_falling_back(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        self._bind("myapp")
        _pod.bound_pipeline_path("myapp").unlink()

        with pytest.raises(_dispatch.DispatchError, match="unreadable"):
            _dispatch.effective_pipeline("myapp", None)

    def test_bound_pipelines_own_rework_config_is_never_patched_by_pod_max_rework_cycles(
        self, pod_home: Path
    ) -> None:
        """A bound file's own rework config wins; the Lead's ``maxReworkCycles``
        patch applies only to the blueprint/built-in default."""
        _write_meta("myapp-lead", {"maxReworkCycles": "9"})
        _write_meta("myapp-implementer")
        custom = (
            "name: custom-rework\n"
            "steps:\n"
            "  - id: build\n"
            "    role: implementer\n"
            "  - id: check\n"
            "    role: implementer\n"
            "    gate:\n"
            "      type: verdict\n"
            '      pattern: "^(APPROVE|REQUEST-CHANGES)\\\\b"\n'
            "      passValues: [approve]\n"
            "      rework:\n"
            "        to: build\n"
            "        when: [request-changes]\n"
            "        maxCycles: 2\n"
        )
        self._bind("myapp", custom)

        spec = _dispatch.effective_pipeline("myapp", None)

        check_step = next(s for s in spec.steps if s.id == "check")
        assert isinstance(check_step.gate, _pipeline.VerdictGate)
        assert check_step.gate.rework is not None
        assert check_step.gate.rework.max_cycles == 2  # untouched -- never patched to 9

    def test_effective_pipeline_source_names_the_bound_file(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        digest = self._bind("myapp")

        assert (
            _dispatch.effective_pipeline_source("myapp")
            == f"bound pipeline (hash {digest[:12]}...)"
        )

    def test_effective_pipeline_source_names_the_blueprint_when_unbound(
        self, pod_home: Path
    ) -> None:
        _write_meta("myapp-lead", {"blueprint": "research"})
        for role in ("researcher", "analyst", "writer", "critic"):
            _write_meta(f"myapp-{role}")

        assert _dispatch.effective_pipeline_source("myapp") == "blueprint 'research'"

    def test_effective_pipeline_source_names_the_built_in_default(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")

        assert _dispatch.effective_pipeline_source("myapp") == "built-in default"


class TestPodSettingReaders:
    """Each Lead-meta setting reader routes through ``core.pod.PodSettings`` --
    a valid override reads through, and an invalid stored value refuses
    dispatch instead of silently substituting the field's default."""

    def test_pod_budget_reads_through(self, pod_home: Path) -> None:
        _write_meta("myapp-lead", {"budgetUsd": "12.5"})
        assert _dispatch.pod_budget("myapp") == 12.5

    def test_pod_budget_invalid_value_refuses(self, pod_home: Path) -> None:
        _write_meta("myapp-lead", {"budgetUsd": "not-a-number"})
        with pytest.raises(_dispatch.DispatchError, match="budgetUsd"):
            _dispatch.pod_budget("myapp")

    def test_pod_verify_timeout_invalid_value_refuses(self, pod_home: Path) -> None:
        _write_meta("myapp-lead", {"verifyTimeoutS": "0"})
        with pytest.raises(_dispatch.DispatchError, match="verifyTimeoutS"):
            _dispatch.pod_verify_timeout("myapp")

    def test_pod_approval_mode_defaults_to_wait(self, pod_home: Path) -> None:
        _write_meta("myapp-lead")
        assert _dispatch.pod_approval_mode("myapp") == "wait"

    def test_pod_approval_mode_reads_through(self, pod_home: Path) -> None:
        _write_meta("myapp-lead", {"approvalMode": "refuse"})
        assert _dispatch.pod_approval_mode("myapp") == "refuse"

    def test_pod_approval_mode_invalid_value_refuses(self, pod_home: Path) -> None:
        _write_meta("myapp-lead", {"approvalMode": "sometimes"})
        with pytest.raises(_dispatch.DispatchError, match="approvalMode"):
            _dispatch.pod_approval_mode("myapp")

    def test_pod_approval_mode_unset_resolves_through_caller_default(self, pod_home: Path) -> None:
        """ADR 0016 SS2: an unset pod ``approvalMode`` defers to the caller, not a fixed
        "wait" -- `serve --dispatch`'s sweep passes "park", a foreground TTY dispatch "wait"."""
        _write_meta("myapp-lead")
        assert _dispatch.pod_approval_mode("myapp", caller_default="park") == "park"
        assert _dispatch.pod_approval_mode("myapp", caller_default="wait") == "wait"

    def test_pod_approval_mode_explicit_value_wins_over_caller_default(
        self, pod_home: Path
    ) -> None:
        _write_meta("myapp-lead", {"approvalMode": "refuse"})
        assert _dispatch.pod_approval_mode("myapp", caller_default="park") == "refuse"

    def test_pod_approval_mode_is_set_false_when_unset(self, pod_home: Path) -> None:
        _write_meta("myapp-lead")
        assert _dispatch.pod_approval_mode_is_set("myapp") is False

    def test_pod_approval_mode_is_set_true_when_set(self, pod_home: Path) -> None:
        _write_meta("myapp-lead", {"approvalMode": "park"})
        assert _dispatch.pod_approval_mode_is_set("myapp") is True


class TestParkedApprovalToken:
    """``_parked_approval_token`` parses the ``approval_parked`` stop's ``key=value`` error
    string -- driven through the real producer so the two are proven against each other."""

    def test_round_trips_the_real_producer(self) -> None:
        from docket.core.agent_loop import approval_parked_error
        from docket.core.tools import ToolResult

        result = ToolResult(
            ok=False,
            decision="deny",
            tool="bash",
            call_id="c1",
            denial_kind="approval_parked",
            policy_id="prod-approval",
            reason="policy requires approval",
            approval_token="apr-abc123",
        )
        error = approval_parked_error(result)

        assert _dispatch._parked_approval_token(error) == "apr-abc123"

    def test_none_for_an_ordinary_failure(self) -> None:
        assert _dispatch._parked_approval_token("boom: connection reset") is None

    def test_none_when_the_prefix_matches_but_no_token_field_is_present(self) -> None:
        assert _dispatch._parked_approval_token("approval_parked: tool='bash'") is None


def _put_task(project: str, task: dict[str, Any]) -> None:
    from docket.edges import store as _store

    _store.write_json(_dispatch.pod_task_list_path(project), {"tasks": [task]})


def _audit_actions() -> list[str]:
    from docket.core import audit as _audit

    return [str(e.get("action")) for e in _audit.read_audit()]


class TestRetryFailedTask:
    """A ``failed`` task is re-queued by ``retry_task`` and the audit log records it."""

    def test_failed_task_goes_back_to_pending_with_its_hops(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        hop = {"role": "lead", "output": "plan", "ok": True}
        _put_task(
            "myapp",
            {
                "id": "task-1",
                "description": "x",
                "status": "failed",
                "reason": "verification failed",
                "hops": [hop],
            },
        )

        assert _dispatch.retry_task("myapp", "task-1") is True

        task = _dispatch.read_tasks("myapp")[0]
        assert task["status"] == "pending"
        assert task["hops"] == [hop]
        assert "task.retry" in _audit_actions()

    def test_a_done_task_is_not_retried(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        _put_task("myapp", {"id": "task-1", "description": "x", "status": "done"})

        assert _dispatch.retry_task("myapp", "task-1") is False
        assert _dispatch.read_tasks("myapp")[0]["status"] == "done"
        assert "task.retry" not in _audit_actions()


_GONE_PID = 2_000_000_000


class TestStaleClaimReclaim:
    """``--resume`` reclaims a ``running`` task whose claimant is gone, and only that one."""

    def _running(self, claim_pid: int, claimed_at: str) -> dict[str, Any]:
        return {
            "id": "task-1",
            "description": "x",
            "status": "running",
            "claimId": "c-1",
            "claimPid": claim_pid,
            "claimedAt": claimed_at,
        }

    def test_dead_claimant_is_reclaimed_and_audited(self, pod_home: Path) -> None:
        from tests.fakes import FakeDriver

        _seed_lean_pod("myapp")
        _put_task("myapp", self._running(_GONE_PID, _clock.iso()))

        results = _dispatch.dispatch_pod("myapp", runner=FakeDriver(), resume=True)

        assert [r.task_id for r in results] == ["task-1"]
        assert _dispatch.read_tasks("myapp")[0]["status"] == "done"
        assert "task.reclaimed" in _audit_actions()

    def test_live_claimant_inside_the_lease_is_left_alone(self, pod_home: Path) -> None:
        import os

        from tests.fakes import FakeDriver

        _seed_lean_pod("myapp")
        _put_task("myapp", self._running(os.getpid(), _clock.iso()))

        results = _dispatch.dispatch_pod("myapp", runner=FakeDriver(), resume=True)

        assert results == []
        assert _dispatch.read_tasks("myapp")[0]["status"] == "running"
        assert "task.reclaimed" not in _audit_actions()


class TestStopBetweenTasks:
    def test_dispatch_pod_stops_between_tasks_when_asked(self, pod_home: Path) -> None:
        """A stop that flips after the first claim ends the loop with the rest still pending."""
        from tests.fakes import FakeDriver

        _seed_lean_pod("myapp")
        _bind_one_step_pipeline("myapp")
        tasks = [{"id": f"task-{i}", "description": "x", "status": "pending"} for i in (1, 2, 3)]
        from docket.edges import store as _store

        _store.write_json(_dispatch.pod_task_list_path("myapp"), {"tasks": tasks})
        driver = FakeDriver()

        results = _dispatch.dispatch_pod(
            "myapp", runner=driver, stop=lambda: len(driver.calls) >= 1
        )

        assert len(results) == 1
        statuses = [t["status"] for t in _dispatch.read_tasks("myapp")]
        assert sorted(statuses) == ["done", "pending", "pending"]


_TWO_STEP_YAML = (
    "name: two\nsteps:\n  - id: kickoff\n    role: lead\n  - id: assemble\n    role: implementer\n"
)


def _bind_one_step_pipeline(project: str) -> None:
    text = "name: solo\nsteps:\n  - id: kickoff\n    role: lead\n"
    path = _pod.bound_pipeline_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    _fleet.meta_set(_pod.member_id(project, "lead"), "pipeline", digest)


def _write_pod_pipeline(project: str, name: str, text: str) -> None:
    target = current_home().pod_config_dir(project) / "pipelines"
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{name}.yaml").write_text(text, encoding="utf-8")


def _queue_task(project: str, **extra: Any) -> None:
    _put_task(project, {"id": "task-1", "description": "x", "status": "pending", **extra})


class TestTaskPipeline:
    """A task's own ``pipeline`` and ``gate`` are resolved at claim, per task."""

    def test_task_pipeline_name_selects_a_pod_local_pipeline(self, pod_home: Path) -> None:
        from tests.fakes import FakeDriver

        _seed_lean_pod("myapp")
        _bind_one_step_pipeline("myapp")
        _write_pod_pipeline("myapp", "two", _TWO_STEP_YAML)
        _queue_task("myapp", pipeline="two")

        results = _dispatch.dispatch_pod("myapp", runner=FakeDriver())

        assert [h.step_id for h in results[0].hops] == ["kickoff", "assemble"]
        assert _dispatch.read_tasks("myapp")[0]["pipelineSource"] == "pod:two"

    def test_a_task_without_a_pipeline_runs_the_pods_default(self, pod_home: Path) -> None:
        from tests.fakes import FakeDriver

        _seed_lean_pod("myapp")
        _bind_one_step_pipeline("myapp")
        _write_pod_pipeline("myapp", "two", _TWO_STEP_YAML)
        _queue_task("myapp")

        results = _dispatch.dispatch_pod("myapp", runner=FakeDriver())

        assert [h.step_id for h in results[0].hops] == ["kickoff"]
        stored = _dispatch.read_tasks("myapp")[0]
        assert stored["pipelineSource"] == "default"
        assert stored["gateApplied"] is False

    def test_a_shipped_recipe_name_resolves_its_pipeline(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        default = _dispatch.effective_pipeline("myapp", None)

        spec, source = _dispatch._task_pipeline("myapp", {"pipeline": "tdd"}, default)

        assert source == "recipe:tdd"
        assert spec.name == "tdd"

    def test_a_pod_local_pipeline_beats_a_recipe_of_the_same_name(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        _write_pod_pipeline("myapp", "tdd", _TWO_STEP_YAML.replace("name: two", "name: mine"))
        default = _dispatch.effective_pipeline("myapp", None)

        spec, source = _dispatch._task_pipeline("myapp", {"pipeline": "tdd"}, default)

        assert (source, spec.name) == ("pod:tdd", "mine")

    @pytest.mark.parametrize("name", ["nope", "../etc", "/etc", "a/b", "UPPER", "policies-only"])
    def test_an_unresolvable_name_is_refused(self, pod_home: Path, name: str) -> None:
        _seed_lean_pod("myapp")
        default = _dispatch.effective_pipeline("myapp", None)

        with pytest.raises(_dispatch.DispatchError):
            _dispatch._task_pipeline("myapp", {"pipeline": name}, default)

    def test_an_unknown_pipeline_fails_the_task_before_any_hop(self, pod_home: Path) -> None:
        from tests.fakes import FakeDriver

        _seed_lean_pod("myapp")
        _queue_task("myapp", pipeline="nope")
        driver = FakeDriver()

        results = _dispatch.dispatch_pod("myapp", runner=driver)

        stored = _dispatch.read_tasks("myapp")[0]
        assert driver.calls == []
        assert [r.status for r in results] == ["failed"]
        assert stored["status"] == "failed"
        assert stored["failureKind"] == "pipeline"
        assert "nope" in stored["reason"]
        assert stored["hops"] == []
        assert stored["claimId"] is None
        tf = current_home().traces_dir / "myapp" / "agent:myapp:task-1.jsonl"
        refused = [e for e in _trace.read_trace(tf) if e["event_type"] == "dispatch_refused"]
        assert len(refused) == 1
        assert "nope" in refused[0]["payload"]["reason"]

    def test_a_refused_task_does_not_stop_the_next_one(self, pod_home: Path) -> None:
        from tests.fakes import FakeDriver

        from docket.edges import store as _store

        _seed_lean_pod("myapp")
        _store.write_json(
            _dispatch.pod_task_list_path("myapp"),
            {
                "tasks": [
                    {
                        "id": "task-1",
                        "description": "x",
                        "status": "pending",
                        "priority": "high",
                        "pipeline": "nope",
                    },
                    {"id": "task-2", "description": "y", "status": "pending"},
                ]
            },
        )

        results = _dispatch.dispatch_pod("myapp", runner=FakeDriver())

        assert [(r.task_id, r.status) for r in results] == [
            ("task-1", "failed"),
            ("task-2", "done"),
        ]

    def test_a_pipeline_refusal_is_not_resumable(self, pod_home: Path) -> None:
        assert "pipeline" not in _dispatch.RESUMABLE_FAILURE_KINDS

    def test_a_pipeline_with_unresolved_variables_refuses_the_task(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        _write_pod_pipeline(
            "myapp",
            "needs",
            "name: needs\nvariables:\n  ticket: {required: true}\nsteps:\n"
            "  - id: kickoff\n    role: lead\n    instructions: work on ${ticket}\n",
        )
        _queue_task("myapp", pipeline="needs")

        _dispatch.dispatch_pod("myapp", runner=lambda *a, **k: _rd.TurnResult(True, "x", 0.0, {}))

        assert _dispatch.read_tasks("myapp")[0]["failureKind"] == "pipeline"


class TestTaskGate:
    def test_the_gate_maps_exit_codes_over_the_defaults(self) -> None:
        gate = _dispatch._task_gate(
            {"gate": {"command": "x", "timeoutS": 9, "map": {"3": "needs_human", "5": "fail"}}}
        )

        assert gate is not None
        assert gate.timeout == 9
        assert [gate.label_for(c) for c in (0, 1, 2, 3, 5, 4)] == [
            "pass",
            "fail",
            "needs_human",
            "needs_human",
            "fail",
            "error",
        ]

    def test_no_gate_is_none(self) -> None:
        assert _dispatch._task_gate({}) is None

    @pytest.mark.parametrize(
        "raw", ["true", {"command": ""}, {"command": "x", "map": {"0": "weird"}}, {"command": 3}]
    )
    def test_a_malformed_gate_is_refused(self, raw: Any) -> None:
        with pytest.raises(_dispatch.DispatchError):
            _dispatch._task_gate({"gate": raw})

    def test_the_gate_attaches_to_the_last_implementer_step(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        spec = _pipeline.PipelineSpec(
            name="p",
            steps=[
                _pipeline.Step(id="a", role="implementer"),
                _pipeline.Step(id="lead", role="lead"),
                _pipeline.Step(id="b", role="implementer"),
                _pipeline.Step(id="c", role="lead"),
            ],
        )
        plan = _orch.resolve_plan(spec, _dispatch.pod_full_roster("myapp"))

        assert _dispatch._task_gate_step_id(plan.runnable_nodes()) == "b"

    def test_without_an_implementer_the_gate_attaches_to_the_last_agent_step(
        self, pod_home: Path
    ) -> None:
        _seed_lean_pod("myapp")
        spec = _pipeline.PipelineSpec(
            name="p",
            steps=[_pipeline.Step(id="a", role="lead"), _pipeline.Step(id="r", run="true")],
        )
        plan = _orch.resolve_plan(spec, _dispatch.pod_full_roster("myapp"))

        assert _dispatch._task_gate_step_id(plan.runnable_nodes()) == "a"


class TestTaskRestrictionHelpers:
    """The hop's network is the narrower of pod and task; maxTokens counts persisted hop usage."""

    @pytest.mark.parametrize(
        ("pod_mode", "task_mode", "expected"),
        [
            ("open", None, "open"),
            ("open", "none", "none"),
            ("none", None, "none"),
            ("none", "none", "none"),
        ],
    )
    def test_hop_network_takes_the_narrower(
        self, pod_mode: str, task_mode: str | None, expected: str
    ) -> None:
        assert _dispatch._hop_network(pod_mode, task_mode) == expected

    def test_token_budget_is_the_cap_less_persisted_usage(self) -> None:
        task = {
            "maxTokens": 1000,
            "hops": [{"usage": {"input": 300, "output": 100}}, {"usage": None}, {"role": "x"}],
        }

        assert _dispatch._task_token_budget(task) == 600

    def test_token_budget_does_not_count_cache_reads(self) -> None:
        hop = {"usage": {"input": 30_000, "cached": 25_000, "cacheWrite": 0, "output": 100}}
        task = {"maxTokens": 10_000, "hops": [hop, hop]}

        assert _dispatch._task_token_budget(task) == 10_000 - 2 * 5_100

    def test_hop_usage_carries_the_cache_split(self) -> None:
        result = _rd.TurnResult(
            True,
            "ok",
            0.0,
            {},
            usage=TokenUsage(
                input_tokens=900, output_tokens=40, cached_tokens=700, cache_write_tokens=50
            ),
        )

        assert _dispatch._hop_usage(result) == {
            "input": 900,
            "cached": 700,
            "cacheWrite": 50,
            "output": 40,
        }

    def test_token_budget_goes_non_positive_when_spent(self) -> None:
        task = {"maxTokens": 100, "hops": [{"usage": {"input": 90, "output": 20}}]}

        assert _dispatch._task_token_budget(task) == -10

    @pytest.mark.parametrize("task", [{}, {"maxTokens": None}, {"maxTokens": True}])
    def test_no_cap_means_no_budget(self, task: dict[str, Any]) -> None:
        assert _dispatch._task_token_budget(task) is None


_HOP_STARTED_KEYS = {"task", "step", "role", "member", "model", "provider", "cycle", "attempt"}
_HOP_FINISHED_KEYS = _HOP_STARTED_KEYS | {"ok", "verdict", "gate", "usage", "durationMs", "error"}


class TestHopEvents:
    def test_hop_record_round_trips_model_and_provider(self) -> None:
        """A hop's model and provider survive the persisted record; an old record reads them empty."""
        hop = _dispatch.HopResult(
            role="lead", member_id="m", ok=True, model="local/x", provider="local"
        )
        rec = _dispatch._hop_record(hop)
        assert (rec["model"], rec["provider"]) == ("local/x", "local")
        back = _dispatch._hop_from_record(rec)
        assert (back.model, back.provider) == ("local/x", "local")
        old = _dispatch._hop_from_record({"role": "lead"})
        assert (old.model, old.provider) == ("", "")

    def test_a_two_hop_run_pairs_hop_events_and_sums_task_usage(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each hop writes one hop_started and one hop_finished, and the task sums its usage."""
        home = tmp_path / ".docket"
        (home / "workspaces" / "projects").mkdir(parents=True)
        (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
        with use_home(Home(home)):
            record_isolation_off(home)
            build_pod("demo", ("lead", "implementer"), codebase="/src/demo")
            monkeypatch.setenv("DOCKET_NO_TRACE", "0")
            backend = _ScriptedBackend(["lead plan", "implementer done"])
            driver = _drt.DocketDriver(backend_factory=lambda model: backend)
            monkeypatch.setattr(_drt, "default_driver", lambda: driver)
            task = _dispatch.enqueue_task("demo", "two hops", channel="cli")
            assert _dispatch.dispatch_pod("demo")[0].status == "done"

            events = [e for e in _trace_events("demo") if e["event_type"].startswith("hop_")]
            assert [e["event_type"] for e in events] == [
                "hop_started",
                "hop_finished",
                "hop_started",
                "hop_finished",
            ]
            for event in events:
                keys = (
                    _HOP_STARTED_KEYS
                    if event["event_type"] == "hop_started"
                    else _HOP_FINISHED_KEYS
                )
                assert set(event["payload"]) == keys
            started = [e["payload"] for e in events if e["event_type"] == "hop_started"]
            assert [p["model"] for p in started] == [
                "anthropic/claude-haiku-4-5",
                "anthropic/claude-sonnet-4-6",
            ]
            assert [p["provider"] for p in started] == ["anthropic", "anthropic"]
            finished = [e["payload"] for e in events if e["event_type"] == "hop_finished"]
            assert {(p["model"], p["provider"]) for p in finished} == {
                ("local/served-model", "local")
            }
            raw = json.loads(_dispatch.pod_task_list_path("demo").read_text())
            (stored,) = [t for t in raw["tasks"] if t["id"] == str(task["id"])]
            assert [(h["model"], h["provider"]) for h in stored["hops"]] == [
                ("local/served-model", "local"),
                ("local/served-model", "local"),
            ]
            assert stored["usage"] == {
                "input": 14,
                "cached": 0,
                "cacheWrite": 0,
                "output": 6,
                "byModel": {
                    "local/served-model": {"input": 14, "cached": 0, "cacheWrite": 0, "output": 6}
                },
            }

    def test_by_model_sums_cache_reads_and_writes_per_model(self, tmp_path: Path) -> None:
        """The task's usage and each byModel entry sum input, cached, cacheWrite and output."""
        home = tmp_path / ".docket"
        (home / "workspaces" / "projects").mkdir(parents=True)
        (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
        with use_home(Home(home)):
            record_isolation_off(home)
            build_pod("demo", ("lead", "implementer"), codebase="/src/demo")
            task = _dispatch.enqueue_task("demo", "usage", channel="cli")
            task_id = str(task["id"])
            hops = [
                _dispatch.HopResult(
                    role="lead",
                    member_id="m",
                    ok=True,
                    model="local/x",
                    provider="local",
                    usage={"input": 100, "cached": 60, "cacheWrite": 5, "output": 7},
                ),
                _dispatch.HopResult(
                    role="implementer",
                    member_id="m",
                    ok=True,
                    model="local/x",
                    provider="local",
                    usage={"input": 50, "cached": 10, "cacheWrite": 0, "output": 3},
                ),
            ]
            _dispatch._finalize_task(
                "demo", task_id, _dispatch.TaskResult(task_id=task_id, status="done", hops=hops)
            )
            raw = json.loads(_dispatch.pod_task_list_path("demo").read_text())
            (stored,) = [t for t in raw["tasks"] if t["id"] == task_id]
            assert stored["usage"] == {
                "input": 150,
                "cached": 70,
                "cacheWrite": 5,
                "output": 10,
                "byModel": {"local/x": {"input": 150, "cached": 70, "cacheWrite": 5, "output": 10}},
            }


class _ScriptedBackend:
    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)

    def complete(self, messages: Any, **_: Any) -> ChatResponse:
        return ChatResponse(
            ok=True,
            message=assistant(self._texts.pop(0)),
            finish_reason="stop",
            usage=TokenUsage(7, 3),
            model="served-model",
            provider="local",
        )


def _trace_events(project: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    traces_dir = current_home().traces_dir / project
    if traces_dir.is_dir():
        for f in traces_dir.glob("*.jsonl"):
            events.extend(_trace.read_trace(f))
    return events


class TestCancelTask:
    def _seed(self, status: str, **fields: Any) -> str:
        _seed_lean_pod()
        task = _dispatch.enqueue_task("myapp", "work", channel="cli")
        from docket.edges import store as _store

        def _fn(doc: dict[str, Any]) -> dict[str, Any]:
            for t in doc["tasks"]:
                t.update(status=status, **fields)
            return {"tasks": doc["tasks"]}

        _store.read_modify_write(_dispatch.pod_task_list_path("myapp"), _fn)
        return str(task["id"])

    def test_a_running_task_cancels_its_live_run_and_audits_once(
        self, pod_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An in-flight run with no task ids is the running task's: it is cancelled, one audit."""
        from docket.core import audit as _audit
        from docket.core import runs as _runs

        task_id = self._seed("running")
        monkeypatch.setattr(
            _runs,
            "list_runs",
            lambda project=None: [
                {"id": "run-a", "state": "running", "taskIds": []},
                {"id": "run-b", "state": "done", "taskIds": []},
                {"id": "run-c", "state": "running", "taskIds": ["other"]},
            ],
        )
        asked: list[str] = []
        sources: list[str] = []

        def _cancel(run_id: str, *, source: str = "cli") -> _runs.CancelOutcome:
            asked.append(run_id)
            sources.append(source)
            return _runs.CancelOutcome(ok=True, message=f"asked {run_id}")

        monkeypatch.setattr(_runs, "cancel_run", _cancel)

        outcome = _dispatch.cancel_task("myapp", task_id, channel="http", reason="why")

        assert asked == ["run-a"]
        assert sources == ["http"]
        assert outcome.status == "cancelled"
        assert outcome.cancelled_runs == ("run-a",)
        assert outcome.messages == ("asked run-a",)
        cancels = [e for e in _audit.read_audit() if e.get("action") == "task.cancel"]
        assert len(cancels) == 1
        assert "channel=http" in cancels[0]["detail"] and "reason=why" in cancels[0]["detail"]

    def test_a_refused_run_cancel_is_a_warning_not_a_cancellation(
        self, pod_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A run that will not cancel leaves the task unchanged and reports why."""
        from docket.core import runs as _runs

        task_id = self._seed("pending")
        monkeypatch.setattr(
            _runs,
            "list_runs",
            lambda project=None: [{"id": "run-a", "state": "queued", "taskIds": [task_id]}],
        )
        monkeypatch.setattr(
            _runs,
            "cancel_run",
            lambda run_id, *, source="cli": _runs.CancelOutcome(ok=False, message="nope"),
        )

        outcome = _dispatch.cancel_task("myapp", task_id, channel="cli")

        assert not outcome.cancelled
        assert outcome.status == "pending"
        assert outcome.warnings == ("nope",)

    def test_a_parked_task_is_cancelled_through_the_parked_path(self, pod_home: Path) -> None:
        """A task waiting for input ends cancelled and names where it was parked."""
        task_id = self._seed("waiting_input", question={"text": "which?"})

        outcome = _dispatch.cancel_task("myapp", task_id, channel="cli")

        assert (outcome.status, outcome.parked_from) == ("cancelled", "waiting_input")

    def test_a_stale_claim_is_settled_not_cancelled(self, pod_home: Path) -> None:
        """A running task whose claimant is gone ends failed and is reported as reclaimed."""
        task_id = self._seed("running", claimPid=2**22 + 1)

        outcome = _dispatch.cancel_task("myapp", task_id, channel="cli")

        assert outcome.reclaimed and outcome.cancelled
        assert outcome.status == "failed"

    def test_nothing_to_cancel_reports_the_status_and_unknown_raises(self, pod_home: Path) -> None:
        """A done task has nothing in flight; an unknown id is a TaskNotFoundError."""
        task_id = self._seed("done")

        outcome = _dispatch.cancel_task("myapp", task_id, channel="cli")

        assert not outcome.cancelled and outcome.status == "done"
        with pytest.raises(_dispatch.TaskNotFoundError):
            _dispatch.cancel_task("myapp", "task-nope", channel="cli")


class TestGroupResume:
    """A parallel group is finished only when every child's latest hop succeeded."""

    @staticmethod
    def _unit(step_id: str) -> _orch.PlannedUnit:
        return _orch.PlannedUnit(
            step_id=step_id,
            role=step_id,
            agent=None,
            archetype=None,
            member_id=f"demo-{step_id}",
            gate=None,
            retries=None,
            timeout=None,
        )

    def _group(self) -> _orch.PlannedGroup:
        return _orch.PlannedGroup(
            step_id="reviews", children=(self._unit("reviewer"), self._unit("tester"))
        )

    def test_a_failed_child_leaves_the_group_unfinished(self) -> None:
        prior = [
            _dispatch.HopResult(
                "reviewer", "demo-reviewer", False, error="budget", step_id="reviewer"
            ),
            _dispatch.HopResult("tester", "demo-tester", True, output="PASS", step_id="tester"),
        ]
        assert _dispatch._group_complete(self._group(), prior) is False

    def test_every_child_succeeded_finishes_the_group(self) -> None:
        prior = [
            _dispatch.HopResult(
                "reviewer", "demo-reviewer", True, output="APPROVE", step_id="reviewer"
            ),
            _dispatch.HopResult("tester", "demo-tester", True, output="PASS", step_id="tester"),
        ]
        assert _dispatch._group_complete(self._group(), prior) is True

    def test_a_child_that_failed_then_succeeded_counts_by_its_latest_hop(self) -> None:
        prior = [
            _dispatch.HopResult(
                "reviewer", "demo-reviewer", False, error="budget", step_id="reviewer"
            ),
            _dispatch.HopResult("tester", "demo-tester", True, output="PASS", step_id="tester"),
            _dispatch.HopResult(
                "reviewer", "demo-reviewer", True, output="APPROVE", step_id="reviewer"
            ),
        ]
        assert _dispatch._group_complete(self._group(), prior) is True
