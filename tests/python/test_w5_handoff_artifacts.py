"""W-5: structured handoff artifacts replace raw-text hop concatenation.

Before this card, ``core/dispatch.py``'s ``_hop_message`` threaded a prior
hop's *raw* ``output`` string straight into the next hop's prompt. This suite
covers the typed replacement:

  * TestHandoffArtifactModel   — ``core/handoff.py``'s ``HandoffArtifact`` in
    isolation: ``render()``'s default-vs-populated shape, ``from_legacy_output``,
    ``dropped()``, and the model's own invariants (frozen, no extra fields).
  * TestHopResultArtifactBackfill — every ``HopResult`` always carries a real
    artifact, whether built explicitly or backfilled from ``output`` alone
    (``__post_init__``) — the same shape every pre-W-5 hand-built test hop
    (``_hop()`` helpers across the suite) still produces.
  * TestHopRecordRoundTrip     — the persisted-queue-file shape: a new-format
    record round-trips its artifact exactly; a pre-W-5 record with no
    ``artifact`` key at all (or a malformed one) degrades to
    ``from_legacy_output`` — the card's explicit backward-compatibility
    requirement.
  * TestDispatchBuildsTypedArtifacts — end to end through a real
    ``dispatch_task`` call: a verdict-gated hop's artifact carries a real
    ``verdict`` (not just raw text), the next hop's composed message is built
    from the *rendered* artifact, and (ROADMAP Phase 17 C-1) the token-budget
    compiler that replaced R-7's blind byte cap still checks that rendered
    text, not the summary alone.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import docket.config as _cfg
from docket.cli import _pod
from docket.core import context as _context
from docket.core import dispatch as _dispatch
from docket.core import handoff as _handoff

from .fakes import FakeDriver

# ── HandoffArtifact: the pure model ──────────────────────────────────────────


class TestHandoffArtifactModel:
    def test_render_is_exactly_summary_when_nothing_else_set(self) -> None:
        art = _handoff.HandoffArtifact(summary="did the thing")
        assert art.render() == "did the thing"

    def test_render_appends_labelled_sections_in_fixed_order(self) -> None:
        art = _handoff.HandoffArtifact(
            summary="did the thing",
            verdict="approve",
            files_changed=["a.py", "b.py"],
            diff_ref="/repo/worktree",
            notes="took two tries",
        )
        assert art.render() == (
            "did the thing\n"
            "Verdict: approve\n"
            "Files changed: a.py, b.py\n"
            "Diff ref: /repo/worktree\n"
            "Notes: took two tries"
        )

    def test_render_omits_empty_optional_fields(self) -> None:
        art = _handoff.HandoffArtifact(summary="s", files_changed=[], notes="")
        assert art.render() == "s"

    def test_from_legacy_output_is_summary_only(self) -> None:
        art = _handoff.HandoffArtifact.from_legacy_output("raw text")
        assert art.summary == "raw text"
        assert art.files_changed == []
        assert art.diff_ref is None
        assert art.verdict is None
        assert art.notes == ""
        assert art.render() == "raw text"

    def test_dropped_resets_only_the_named_field(self) -> None:
        art = _handoff.HandoffArtifact(summary="s", verdict="approve", notes="n")
        dropped = art.dropped("notes")
        assert dropped.notes == ""
        assert dropped.verdict == "approve"
        assert dropped.summary == "s"
        # The original is untouched (frozen model, dropped() returns a copy).
        assert art.notes == "n"

    def test_dropped_rejects_summary(self) -> None:
        art = _handoff.HandoffArtifact(summary="s")
        with pytest.raises(ValueError):
            art.dropped("summary")

    def test_dropped_rejects_unknown_field(self) -> None:
        art = _handoff.HandoffArtifact(summary="s")
        with pytest.raises(ValueError):
            art.dropped("nonexistent")

    def test_drop_order_never_includes_summary(self) -> None:
        assert "summary" not in _handoff.HandoffArtifact.DROP_ORDER
        # Every other field is covered — a budgeting consumer can shed all of
        # them and still be left with a valid (if minimal) artifact.
        assert set(_handoff.HandoffArtifact.DROP_ORDER) == {
            "notes",
            "diff_ref",
            "files_changed",
            "verdict",
        }

    def test_model_is_frozen(self) -> None:
        art = _handoff.HandoffArtifact(summary="s")
        with pytest.raises(ValidationError):
            art.summary = "other"  # type: ignore[misc]

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _handoff.HandoffArtifact(summary="s", bogus="x")  # type: ignore[call-arg]

    def test_model_dump_round_trips_via_model_validate(self) -> None:
        art = _handoff.HandoffArtifact(summary="s", verdict="pass", files_changed=["a.py"])
        restored = _handoff.HandoffArtifact.model_validate(art.model_dump())
        assert restored == art


# ── HopResult: artifact always populated, whatever the construction path ────


def _hop(role: str, output: str, member_id: str = "") -> _dispatch.HopResult:
    return _dispatch.HopResult(
        role=role, member_id=member_id or f"demo-{role}", ok=True, output=output, cost_usd=0.0
    )


class TestHopResultArtifactBackfill:
    def test_hand_built_hop_backfills_artifact_from_output(self) -> None:
        hop = _hop("lead", "the plan")
        assert isinstance(hop.artifact, _handoff.HandoffArtifact)
        assert hop.artifact.summary == "the plan"
        assert hop.rendered_artifact() == "the plan"

    def test_explicit_artifact_is_not_overwritten(self) -> None:
        art = _handoff.HandoffArtifact(summary="custom", verdict="approve")
        hop = _dispatch.HopResult(
            role="reviewer", member_id="demo-reviewer", ok=True, output="raw", artifact=art
        )
        assert hop.artifact is art
        assert hop.rendered_artifact() == "custom\nVerdict: approve"

    def test_empty_output_backfills_to_empty_artifact(self) -> None:
        hop = _hop("lead", "")
        assert hop.artifact is not None
        assert hop.artifact.summary == ""
        assert hop.rendered_artifact() == ""


# ── Persisted-record round trip (the "hops[]" shape in TASK_LIST.json) ──────


class TestHopRecordRoundTrip:
    def test_hop_record_persists_and_restores_artifact_exactly(self) -> None:
        art = _handoff.HandoffArtifact(
            summary="s", verdict="fail", files_changed=["x.py"], notes="n"
        )
        hop = _dispatch.HopResult(
            role="tester", member_id="demo-tester", ok=True, output="s", artifact=art
        )
        rec = _dispatch._hop_record(hop)
        assert rec["artifact"] == art.model_dump()
        # verification_skipped is a this-run-only signal, not part of the
        # durable record (see HopResult's own docstring) -- not persisted.
        assert "verification_skipped" not in rec

        restored = _dispatch._hop_from_record(rec)
        assert restored.artifact == art

    def test_legacy_record_with_no_artifact_key_degrades_to_summary(self) -> None:
        # Simulates a hop persisted by dispatch before this card landed.
        rec: dict[str, Any] = {
            "role": "implementer",
            "member": "demo-implementer",
            "ok": True,
            "output": "old raw text",
            "costUsd": 0.01,
            "error": "",
            "attempts": 1,
            "stepId": "implementer",
        }
        restored = _dispatch._hop_from_record(rec)
        assert restored.artifact is not None
        assert restored.artifact.summary == "old raw text"
        assert restored.artifact.verdict is None
        assert restored.rendered_artifact() == "old raw text"

    def test_malformed_persisted_artifact_degrades_gracefully(self) -> None:
        rec: dict[str, Any] = {
            "role": "implementer",
            "member": "demo-implementer",
            "ok": True,
            "output": "raw",
            "artifact": {"not": "a valid HandoffArtifact shape"},
        }
        restored = _dispatch._hop_from_record(rec)
        assert restored.artifact is not None
        assert restored.artifact.summary == "raw"

    def test_null_artifact_value_degrades_gracefully(self) -> None:
        rec: dict[str, Any] = {
            "role": "implementer",
            "member": "demo-implementer",
            "ok": True,
            "output": "raw",
            "artifact": None,
        }
        restored = _dispatch._hop_from_record(rec)
        assert restored.artifact is not None
        assert restored.artifact.summary == "raw"


# ── End to end: dispatch_task builds and threads real artifacts ─────────────


def _point_at(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "DOCKET_HOME", home, raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", home / "fleet.json", raising=True)
    monkeypatch.setattr(_cfg, "WORKSPACES_DIR", home / "workspaces", raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", home / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", home / "docket-models.json", raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", home / "traces", raising=True)


def _seed_pod(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str = "demo", *, full: bool = False
) -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    _point_at(home, monkeypatch)
    roles = _pod.pod.FULL_POD_ROLES if full else _pod.pod.DEFAULT_POD_ROLES
    _pod.build_pod(project, roles, codebase=f"/src/{project}")
    return home


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.setenv("DOCKET_NO_TRACE", "0")


class TestDispatchBuildsTypedArtifacts:
    def test_two_hop_dispatch_produces_typed_artifacts_not_strings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task: dict[str, Any] = {"id": "t1", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("demo", task, runner=FakeDriver())

        assert res.status == "done"
        assert [h.role for h in res.hops] == ["lead", "implementer"]
        for hop in res.hops:
            assert isinstance(hop.artifact, _handoff.HandoffArtifact)
            # The artifact is a real structured object, not a bare string --
            # the card's own "not a string" acceptance criterion.
            assert not isinstance(hop.artifact, str)
            assert hop.artifact.summary == hop.output

    def test_verdict_gated_hop_artifact_carries_the_parsed_verdict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, full=True)

        class _Runner:
            def __call__(
                self,
                agent_id: str,
                session_key: str,
                message: str,
                timeout: int,
                env: dict[str, str] | None = None,
            ) -> Any:
                from docket.core.runtime_driver import TurnResult

                role = agent_id.rsplit("-", 1)[-1]
                text = {
                    "lead": "plan",
                    "implementer": "did it",
                    "reviewer": "APPROVE - looks solid",
                    "tester": "PASS - works",
                }[role]
                return TurnResult(True, text, 0.01, {})

        task: dict[str, Any] = {"id": "t2", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("demo", task, runner=_Runner())
        assert res.status == "done"

        reviewer_hop = next(h for h in res.hops if h.role == "reviewer")
        tester_hop = next(h for h in res.hops if h.role == "tester")
        assert reviewer_hop.artifact is not None
        assert reviewer_hop.artifact.verdict == "approve"
        assert tester_hop.artifact is not None
        assert tester_hop.artifact.verdict == "pass"

        # Non-verdict-gated hops carry no verdict at all.
        lead_hop = next(h for h in res.hops if h.role == "lead")
        assert lead_hop.artifact is not None
        assert lead_hop.artifact.verdict is None

    def test_next_hop_message_is_built_from_rendered_artifact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The tester's prompt must reflect the reviewer's *artifact* -- which
        now includes a structural "Verdict: approve" line the raw reviewer
        text alone never contained -- proving the next hop's message is built
        from HandoffArtifact.render(), not straight from HopResult.output."""
        _seed_pod(tmp_path, monkeypatch, full=True)

        from docket.core.runtime_driver import TurnResult

        calls: list[tuple[str, str]] = []

        class _Runner:
            def __call__(
                self,
                agent_id: str,
                session_key: str,
                message: str,
                timeout: int,
                env: dict[str, str] | None = None,
            ) -> Any:
                role = agent_id.rsplit("-", 1)[-1]
                calls.append((role, message))
                text = {
                    "lead": "plan",
                    "implementer": "did it",
                    "reviewer": "APPROVE - looks solid",
                    "tester": "PASS - works",
                }[role]
                return TurnResult(True, text, 0.01, {})

        task: dict[str, Any] = {"id": "t3", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("demo", task, runner=_Runner())
        assert res.status == "done"

        tester_message = next(msg for role, msg in calls if role == "tester")
        assert "APPROVE - looks solid" in tester_message
        assert "Verdict: approve" in tester_message

    def test_budget_checks_the_rendered_artifact_and_sheds_verdict_before_summary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A verdict-bearing artifact's *rendered* text (summary + the
        appended ``Verdict:`` line) is what ROADMAP Phase 17 C-1's compiler
        checks against budget -- not the summary alone. Unlike the R-7 blind
        byte cap this replaced, the compiler sheds the less-valuable
        ``verdict`` field first (``HandoffArtifact.DROP_ORDER``) rather than
        truncating ``summary`` -- so the reviewer's actual review text
        reaches the tester intact even though the artifact didn't fit as-is.
        """
        _seed_pod(tmp_path, monkeypatch, full=True)
        # Force every prior hop's carryover share down to just enough room
        # for the reviewer's raw summary (208 bytes -> 52 tokens) but not its
        # full rendered artifact (summary + "\nVerdict: approve" -> 225 bytes
        # -> 56 tokens).
        monkeypatch.setattr(_context, "hop_share", lambda rank, total: 53)

        from docket.core.runtime_driver import TurnResult

        calls: list[tuple[str, str]] = []

        class _Runner:
            def __call__(
                self,
                agent_id: str,
                session_key: str,
                message: str,
                timeout: int,
                env: dict[str, str] | None = None,
            ) -> Any:
                role = agent_id.rsplit("-", 1)[-1]
                calls.append((role, message))
                text = {
                    "lead": "plan",
                    "implementer": "did it",
                    "reviewer": "APPROVE " + ("x" * 200),
                    "tester": "PASS - works",
                }[role]
                return TurnResult(True, text, 0.01, {})

        task: dict[str, Any] = {"id": "t4", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("demo", task, runner=_Runner())
        assert res.status == "done"
        reviewer_hop = next(h for h in res.hops if h.role == "reviewer")
        assert reviewer_hop.artifact is not None
        assert reviewer_hop.artifact.verdict == "approve"
        # The full rendered text (summary + "\nVerdict: approve") is longer
        # than the raw summary alone -- the budget check must see *that*.
        rendered_len = len(reviewer_hop.rendered_artifact().encode("utf-8"))
        assert rendered_len > len(reviewer_hop.artifact.summary.encode("utf-8"))

        tester_message = next(msg for role, msg in calls if role == "tester")
        assert "APPROVE " + ("x" * 200) in tester_message
        assert "Verdict: approve" not in tester_message

    def test_resume_recovers_persisted_artifact_after_a_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A task resumed from a persisted (post-crash) hop history must
        thread the *persisted artifact* into later hops' prompts, not just
        raw text -- proving --resume recovers the structured record."""
        _seed_pod(tmp_path, monkeypatch, full=True)
        task = _dispatch.enqueue_task("demo", "work")

        from docket.core.runtime_driver import TurnResult

        class _ReviewerOnlyRunner:
            def __call__(
                self,
                agent_id: str,
                session_key: str,
                message: str,
                timeout: int,
                env: dict[str, str] | None = None,
            ) -> Any:
                role = agent_id.rsplit("-", 1)[-1]
                text = {"lead": "plan", "implementer": "did it", "reviewer": "APPROVE - solid"}[
                    role
                ]
                return TurnResult(True, text, 0.01, {})

        # Drive the pipeline through the Reviewer only (simulating a crash
        # right before the Tester hop) by dispatching with a spec-free run
        # but a runner that would raise for "tester" -- simpler: reuse the
        # real dispatch_pod/_persist_hop path via three completed hops, then
        # hand-build the resume_from list the way a real crash-and-restart
        # would load it (through the persisted-record round trip).
        prior_hops = [
            _dispatch.HopResult(
                role="lead", member_id="demo-lead", ok=True, output="plan", cost_usd=0.0
            ),
            _dispatch.HopResult(
                role="implementer",
                member_id="demo-implementer",
                ok=True,
                output="did it",
                cost_usd=0.0,
            ),
            _dispatch.HopResult(
                role="reviewer",
                member_id="demo-reviewer",
                ok=True,
                output="APPROVE - solid",
                cost_usd=0.0,
                artifact=_handoff.HandoffArtifact(summary="APPROVE - solid", verdict="approve"),
            ),
        ]
        # Round-trip through the persisted-record shape, exactly like a real
        # crash-and-`--resume` would load them from TASK_LIST.json.
        records = [_dispatch._hop_record(h) for h in prior_hops]
        resumed_hops = [_dispatch._hop_from_record(r) for r in records]

        calls: list[tuple[str, str]] = []

        class _TesterRunner:
            def __call__(
                self,
                agent_id: str,
                session_key: str,
                message: str,
                timeout: int,
                env: dict[str, str] | None = None,
            ) -> Any:
                role = agent_id.rsplit("-", 1)[-1]
                calls.append((role, message))
                return TurnResult(True, "PASS - works", 0.01, {})

        res = _dispatch.dispatch_task(
            "demo", task, runner=_TesterRunner(), resume_from=resumed_hops
        )
        assert res.status == "done"
        assert [h.role for h in res.hops] == ["lead", "implementer", "reviewer", "tester"]

        tester_message = next(msg for role, msg in calls if role == "tester")
        # The resumed reviewer hop's *persisted artifact* (not a fresh parse
        # of raw text) is what reached the tester's prompt.
        assert "APPROVE - solid" in tester_message
        assert "Verdict: approve" in tester_message
