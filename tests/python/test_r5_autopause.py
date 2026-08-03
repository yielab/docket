"""R-5: budget honesty — auto-pause, the paused-flag type bug, labelled estimates.

Covers, per the ROADMAP Phase 14 R-5 card:

  * ``AgentMeta.coerce_paused``/``is_paused()`` — the typed accessor that fixes the
    string/bool display bug (a writer storing a real ``bool`` while old display code
    compared it against the string ``"true"``, which a Python ``True`` never equals).
  * The pause writer: ``core/dispatch.py``'s per-hop budget gate marks the pod's Lead
    ``paused=True, pausedReason="budget"`` once the cap is reached.
  * Claim-time refusal: ``_claim_next_task`` refuses every claim for a paused pod
    outright (a ``paused_refused`` trace event, no wasted turn) until resumed.
  * ``docket profile <id> --resume`` clears both fields, writes an audit entry, and
    (for a pod Lead) unblocks the pod's budget-blocked tasks.
  * The token-based estimate fallback (``core/utils.estimate_cost_usd`` /
    ``core/dispatch.pod_gating_cost``) that lets gating trip even when the daemon
    recorded no cost at all — always labelled, never contaminating recorded spend.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest
from typer.testing import CliRunner

import docket.config as _cfg
from docket.cli import _pod
from docket.cli import app as _app
from docket.core import dispatch as _dispatch
from docket.core import models_policy as _mp
from docket.core import pod as _podcore
from docket.core import runtime_driver as _rd
from docket.core import utils as _utils
from docket.core.models import AgentMeta
from docket.edges.adapters import openclaw as _oc

# ── hermetic environment (mirrors test_dispatch.py) ───────────────────────────────


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
    monkeypatch.setattr(_cfg, "TRACES_DIR", oc_dir / "traces", raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", oc_dir / "audit.log", raising=True)
    monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_oc, "meta_path", _cfg.meta_path, raising=True)


def _fake_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    """Register/unregister mutate agents.list directly (no real openclaw)."""
    monkeypatch.setattr(_pod.shutil, "which", lambda _name: "/usr/bin/openclaw")

    def _register(agent_id: str, workspace: str, model: str) -> tuple[bool, str]:
        raw = json.loads(_cfg.CONFIG_FILE.read_text())
        raw.setdefault("agents", {}).setdefault("list", []).append(
            {"id": agent_id, "model": model, "metadata": {}}
        )
        _cfg.CONFIG_FILE.write_text(json.dumps(raw))
        return (True, "")

    monkeypatch.setattr(_oc, "register_agent_cli", _register)


def _seed_pod(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project: str = "demo",
    roles: tuple[str, ...] = _podcore.DEFAULT_POD_ROLES,
) -> Path:
    oc_dir = tmp_path / ".openclaw"
    (oc_dir / "workspaces" / "projects").mkdir(parents=True)
    (oc_dir / "openclaw.json").write_text(
        json.dumps({"agents": {"list": []}, "bindings": [], "channels": {}})
    )
    _point_at(oc_dir, monkeypatch)
    _fake_daemon(monkeypatch)
    _pod.build_pod(project, roles, codebase=f"/src/{project}")
    return oc_dir


class _RecordingRunner:
    """Stub matching agent_run's signature; records calls, returns canned results."""

    def __init__(self, *, ok: bool = True, cost: float = 0.0):
        self.calls: list[tuple[str, str, str, int, dict[str, str] | None]] = []
        self.ok = ok
        self.cost = cost

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> _rd.TurnResult:
        self.calls.append((agent_id, session_key, message, timeout, env))
        return _rd.TurnResult(self.ok, f"done by {agent_id}", self.cost, {"output": "x"})


def _write_session(oc_dir: Path, agent_id: str, *, input_tokens: int, output_tokens: int) -> None:
    """Seed a docket-native session (``core/session.py``'s on-disk shape) with
    real measured token counts and no cost figure.

    Phase 19 P19-7a repointed ``aggregate_cost`` at ``DocketDriver``
    (``edges.adapters.docket_runtime.default_driver()``), not the ACL's
    ``OpenClawDriver`` -- this now writes the format it actually reads.
    ``DocketDriver`` *never* reports a USD cost (see
    ``core/runtime_driver.py``'s ``TurnResult.cost_usd`` docstring), which is
    exactly the "tokens without cost" shape this R-5 suite was originally
    written against for the daemon -- the estimate-fallback behaviour under
    test is unchanged, only the driver reporting it is. *oc_dir* is unused
    (kept so every existing call site is untouched); the write goes through
    ``_cfg.SESSIONS_DIR``, which this suite already isolates per test via
    conftest.py's autouse ``_isolate_docket_home``.
    """
    from urllib.parse import quote

    session_key = f"agent:{agent_id}:default"
    sdir = _cfg.SESSIONS_DIR / quote(session_key, safe="")
    sdir.mkdir(parents=True, exist_ok=True)
    record = {
        "sessionKey": session_key,
        "created": "2026-07-30T00:00:00Z",
        "updated": "2026-07-30T00:00:00Z",
        "messages": [],
        "usage": {
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "cachedTokens": 0,
            "turns": 1,
        },
    }
    (sdir / "session.json").write_text(json.dumps(record))


# ── AgentMeta.coerce_paused / is_paused ────────────────────────────────────────────


class TestCoercePaused:
    def test_real_bool_true(self) -> None:
        assert AgentMeta.coerce_paused(True) is True

    def test_real_bool_false(self) -> None:
        assert AgentMeta.coerce_paused(False) is False

    def test_legacy_string_true_lowercase(self) -> None:
        assert AgentMeta.coerce_paused("true") is True

    def test_legacy_string_true_titlecase(self) -> None:
        # str(True) in Python is "True" — this is exactly what a real bool
        # round-trips to through meta_get's str() coercion.
        assert AgentMeta.coerce_paused("True") is True

    def test_legacy_string_false(self) -> None:
        assert AgentMeta.coerce_paused("false") is False
        assert AgentMeta.coerce_paused("False") is False

    def test_absent_defaults_false(self) -> None:
        assert AgentMeta.coerce_paused("") is False

    def test_unrelated_string_is_false_not_an_error(self) -> None:
        assert AgentMeta.coerce_paused("yes") is False

    def test_instance_accessor_reflects_pydantic_coercion(self) -> None:
        # pydantic's own bool validator already coerces "true"/"false" on
        # model_validate — is_paused() is the one accessor everyone should
        # call rather than re-deriving this.
        meta = AgentMeta.model_validate({"kind": "project", "paused": "true"})
        assert meta.is_paused() is True
        meta2 = AgentMeta.model_validate({"kind": "project", "paused": False})
        assert meta2.is_paused() is False


# ── the display bug itself: docket info must show a real bool correctly ──────────


class TestInfoDisplaysPausedCorrectly:
    META: ClassVar[dict[str, object]] = {
        "schemaVersion": 1,
        "kind": "project",
        "name": "My Shop",
        "model": "anthropic/claude-sonnet-4-6",
        "modelSource": "policy",
        "sessionKey": "agent:myshop:default",
        "projectKey": "default",
    }

    def _setup(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, paused_value: object) -> Path:
        oc_dir = tmp_path / ".openclaw"
        ws = oc_dir / "workspaces" / "projects" / "myshop"
        ws.mkdir(parents=True)
        meta = {**self.META, "paused": paused_value, "pausedReason": "budget"}
        (ws / ".docket-meta.json").write_text(json.dumps(meta))
        (oc_dir / "openclaw.json").write_text(json.dumps({"agents": {"list": []}, "bindings": []}))
        _point_at(oc_dir, monkeypatch)
        return oc_dir

    def test_real_bool_true_shows_paused_in_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The exact bug: a writer stores a real JSON boolean `true`; the old
        # `raw.get("paused", "") == "true"` compare is never true for a bool,
        # so this used to silently render as not-paused.
        self._setup(tmp_path, monkeypatch, True)
        runner = CliRunner()
        result = runner.invoke(_app, ["info", "myshop", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["paused"] is True

    def test_legacy_string_true_shows_paused_in_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Regression for the type bug from the other direction: a genuinely
        # old Bash-era record stored the string "true".
        self._setup(tmp_path, monkeypatch, "true")
        runner = CliRunner()
        result = runner.invoke(_app, ["info", "myshop", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["paused"] is True

    def test_not_paused_shows_false(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._setup(tmp_path, monkeypatch, False)
        runner = CliRunner()
        result = runner.invoke(_app, ["info", "myshop", "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["paused"] is False

    def test_human_readable_shows_paused_status_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._setup(tmp_path, monkeypatch, True)
        runner = CliRunner()
        result = runner.invoke(_app, ["info", "myshop"])
        assert result.exit_code == 0, result.output
        assert "PAUSED" in result.output
        assert "budget" in result.output


# ── docket profile <id> --resume ──────────────────────────────────────────────────


class TestProfileResume:
    META: ClassVar[dict[str, object]] = {
        "schemaVersion": 1,
        "kind": "project",
        "name": "My Shop",
        "model": "anthropic/claude-sonnet-4-6",
        "modelSource": "policy",
        "sessionKey": "agent:myshop:default",
        "projectKey": "default",
        "paused": True,
        "pausedReason": "budget",
    }

    def _setup(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        oc_dir = tmp_path / ".openclaw"
        ws = oc_dir / "workspaces" / "projects" / "myshop"
        ws.mkdir(parents=True)
        (ws / ".docket-meta.json").write_text(json.dumps(self.META))
        (oc_dir / "openclaw.json").write_text(
            json.dumps(
                {
                    "agents": {"list": [{"id": "myshop", "model": self.META["model"]}]},
                    "bindings": [],
                }
            )
        )
        _point_at(oc_dir, monkeypatch)
        return oc_dir

    def test_resume_clears_paused_fields(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = self._setup(tmp_path, monkeypatch)
        runner = CliRunner()
        result = runner.invoke(_app, ["profile", "myshop", "--resume"])
        assert result.exit_code == 0, result.output
        raw = json.loads(
            (oc_dir / "workspaces" / "projects" / "myshop" / ".docket-meta.json").read_text()
        )
        assert AgentMeta.coerce_paused(raw.get("paused")) is False
        assert raw.get("pausedReason", "") == ""

    def test_resume_writes_audit_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = self._setup(tmp_path, monkeypatch)
        runner = CliRunner()
        result = runner.invoke(_app, ["profile", "myshop", "--resume"])
        assert result.exit_code == 0, result.output
        audit_text = (oc_dir / "audit.log").read_text()
        entries = [json.loads(line) for line in audit_text.splitlines() if line.strip()]
        assert any(e["action"] == "profile.resume" and "myshop" in e["detail"] for e in entries)

    def test_resume_on_unpaused_agent_is_a_harmless_noop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = tmp_path / ".openclaw"
        ws = oc_dir / "workspaces" / "projects" / "myshop"
        ws.mkdir(parents=True)
        meta = {**self.META, "paused": False, "pausedReason": ""}
        (ws / ".docket-meta.json").write_text(json.dumps(meta))
        (oc_dir / "openclaw.json").write_text(json.dumps({"agents": {"list": []}, "bindings": []}))
        _point_at(oc_dir, monkeypatch)
        runner = CliRunner()
        result = runner.invoke(_app, ["profile", "myshop", "--resume"])
        assert result.exit_code == 0, result.output


# ── dispatch: pause on cap breach + claim-time refusal ────────────────────────────


class TestAutoPauseDispatch:
    def test_cap_breach_pauses_lead_and_blocks_task(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "Too expensive")
        monkeypatch.setattr(_dispatch, "pod_budget", lambda _p: 1.0)
        monkeypatch.setattr(_dispatch, "pod_recorded_cost", lambda _p: 5.0)

        results = _dispatch.dispatch_pod("demo", runner=_RecordingRunner())
        assert results[0].status == "blocked"

        lead_id = _podcore.member_id("demo", "lead")
        meta = _oc.meta_read(lead_id)
        assert meta.is_paused() is True
        assert meta.paused_reason == "budget"

    def test_paused_pod_refuses_claim_at_next_dispatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "One")
        _dispatch.enqueue_task("demo", "Two")
        monkeypatch.setattr(_dispatch, "pod_budget", lambda _p: 1.0)
        monkeypatch.setattr(_dispatch, "pod_recorded_cost", lambda _p: 5.0)
        _dispatch.dispatch_pod("demo", runner=_RecordingRunner())

        # Second dispatch: the pod is now paused — nothing should even be
        # claimed (task "Two" stays exactly "pending", untouched), and no
        # further agent turn should run (no wasted cost).
        runner = _RecordingRunner()
        results = _dispatch.dispatch_pod("demo", runner=runner)
        assert results == []
        assert runner.calls == []
        tasks = {t["description"]: t["status"] for t in _dispatch.read_tasks("demo")}
        assert tasks["Two"] == "pending"

        trace_files = list((oc_dir / "traces" / "demo").glob("*.jsonl"))
        events = [json.loads(line) for tf in trace_files for line in tf.read_text().splitlines()]
        assert any(e["event_type"] == "paused_refused" for e in events)

    def test_resume_clears_pause_and_unblocks_pod_tasks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "Too expensive")
        monkeypatch.setattr(_dispatch, "pod_budget", lambda _p: 1.0)
        monkeypatch.setattr(_dispatch, "pod_recorded_cost", lambda _p: 5.0)
        _dispatch.dispatch_pod("demo", runner=_RecordingRunner())
        assert _dispatch.read_tasks("demo")[0]["status"] == "blocked"

        runner = CliRunner()
        result = runner.invoke(_app, ["profile", _podcore.member_id("demo", "lead"), "--resume"])
        assert result.exit_code == 0, result.output

        lead_id = _podcore.member_id("demo", "lead")
        assert _oc.meta_read(lead_id).is_paused() is False
        assert _dispatch.read_tasks("demo")[0]["status"] == "pending"

        # Budget is still (mock-)exceeded, so a fresh dispatch blocks (and
        # re-pauses) again rather than actually running — resume un-sticks
        # the queue, it doesn't forgive the cap.
        _dispatch.dispatch_pod("demo", runner=_RecordingRunner())
        assert _dispatch.read_tasks("demo")[0]["status"] == "blocked"
        assert _oc.meta_read(lead_id).is_paused() is True


# ── estimate fallback for gating ───────────────────────────────────────────────────


class TestEstimateFallback:
    def test_estimate_cost_usd_known_model(self) -> None:
        totals = _utils.CostTotals(input_tokens=1_000_000, output_tokens=1_000_000)
        est = _utils.estimate_cost_usd("anthropic/claude-haiku-4-5", totals)
        in_rate, out_rate, _cr, _cw = _mp.MODEL_PRICING["anthropic/claude-haiku-4-5"]
        assert est == pytest.approx(in_rate + out_rate)

    def test_estimate_cost_usd_unknown_model_returns_none(self) -> None:
        totals = _utils.CostTotals(input_tokens=1000, output_tokens=1000)
        assert _utils.estimate_cost_usd("some-vendor/unknown-model", totals) is None

    def test_pod_gating_cost_prefers_recorded_when_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        monkeypatch.setattr(_dispatch, "pod_recorded_cost", lambda _p: 3.5)
        spent, estimated = _dispatch.pod_gating_cost("demo")
        assert spent == 3.5
        assert estimated is False

    def test_pod_gating_cost_falls_back_to_estimate_when_recorded_is_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed_pod(tmp_path, monkeypatch)
        lead_id = _podcore.member_id("demo", "lead")
        _oc.meta_set(lead_id, "model", "anthropic/claude-haiku-4-5")
        _write_session(oc_dir, lead_id, input_tokens=1_000_000, output_tokens=1_000_000)

        spent, estimated = _dispatch.pod_gating_cost("demo")
        assert estimated is True
        assert spent == pytest.approx(4.8)  # 1M*$0.80/M + 1M*$4.00/M

    def test_dispatch_pauses_pod_using_estimate_when_daemon_recorded_no_cost(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The bug this card exists to close: with real (unmocked) cost
        aggregation, a daemon that never writes usage.cost.total leaves
        recorded spend at 0 forever — the cap must still trip, from tokens."""
        oc_dir = _seed_pod(tmp_path, monkeypatch)
        lead_id = _podcore.member_id("demo", "lead")
        _oc.meta_set(lead_id, "model", "anthropic/claude-haiku-4-5")
        _oc.meta_set(lead_id, "budgetUsd", "1")
        _write_session(oc_dir, lead_id, input_tokens=1_000_000, output_tokens=1_000_000)
        _dispatch.enqueue_task("demo", "Too expensive")

        results = _dispatch.dispatch_pod("demo", runner=_RecordingRunner())
        assert results[0].status == "blocked"
        assert "estimated" in results[0].reason
        assert _oc.meta_read(lead_id).is_paused() is True


# ── recorded spend is never contaminated by an estimate ───────────────────────────


class TestRecordedSpendNeverContaminated:
    def test_aggregate_cost_stays_zero_when_daemon_recorded_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed_pod(tmp_path, monkeypatch)
        lead_id = _podcore.member_id("demo", "lead")
        _write_session(oc_dir, lead_id, input_tokens=1_000_000, output_tokens=1_000_000)
        # aggregate_cost (what `docket cost` reports) must stay exactly the
        # daemon's own figure — 0.0 here — never the estimate, even though
        # plenty of tokens (and a known price) exist to estimate from.
        assert _utils.aggregate_cost(lead_id).cost_usd == 0.0

    def test_docket_cost_reports_none_recorded_not_a_dollar_figure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed_pod(tmp_path, monkeypatch)
        lead_id = _podcore.member_id("demo", "lead")
        _oc.meta_set(lead_id, "model", "anthropic/claude-haiku-4-5")
        _write_session(oc_dir, lead_id, input_tokens=1_000_000, output_tokens=1_000_000)

        runner = CliRunner()
        result = runner.invoke(_app, ["cost", lead_id])
        assert result.exit_code == 0, result.output
        assert "none recorded" in result.output
        # The estimate ($4.80 for these tokens/model) must never appear here
        # dressed up as a cost figure.
        assert "4.80" not in result.output

    def test_docket_cost_json_cost_field_stays_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed_pod(tmp_path, monkeypatch)
        lead_id = _podcore.member_id("demo", "lead")
        _oc.meta_set(lead_id, "model", "anthropic/claude-haiku-4-5")
        _write_session(oc_dir, lead_id, input_tokens=1_000_000, output_tokens=1_000_000)

        runner = CliRunner()
        result = runner.invoke(_app, ["cost", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        agent_row = next(a for a in data["agents"] if a["id"] == lead_id)
        assert agent_row["costUsd"] == 0.0
