"""Structured handoff artifacts replace raw-text hop concatenation.
``core/dispatch.py``'s ``_hop_message`` no longer threads a prior hop's raw ``output`` string
into the next hop's prompt. Covers: TestHandoffArtifactModel (``HandoffArtifact`` in isolation
-- ``render()``'s default-vs-populated shape, ``from_output``, ``dropped()``, and the
model's own invariants: frozen, no extra fields); TestHopResultArtifactBackfill (every
``HopResult`` always carries a real artifact, built explicitly or backfilled via
``__post_init__``); TestHopRecordRoundTrip (a new-format persisted record round-trips its
artifact exactly, and a missing/malformed ``artifact`` key degrades to ``from_output``);
and TestDispatchBuildsTypedArtifacts (end to end through ``dispatch_task``: a verdict-gated
hop's artifact carries a real ``verdict``, the next hop's message is built from the rendered
artifact, and the token-budget compiler checks that rendered text, not the summary alone).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from tests.support import home as _support_home
from tests.support.fakes import FakeDriver
from tests.support.llm import hop as _hop
from tests.support.pods import build_pod, spec

from docket.agent import context as _context
from docket.hops.application import executor as _executor
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel import handoff as _handoff
from docket.kernel.home import Home, use_home
from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import plan as _plan
from docket.tasks.application import queue as _queue
from docket.tasks.domain import task as _task
from docket.tasks.domain.task import TaskRecord

_hermetic = _support_home.trace_on_env

SUBJECT = "docket.hops.application.compose"

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
        )
        assert art.render() == (
            "did the thing\nVerdict: approve\nFiles changed: a.py, b.py\nDiff ref: /repo/worktree"
        )

    def test_render_omits_empty_optional_fields(self) -> None:
        art = _handoff.HandoffArtifact(summary="s", files_changed=[])
        assert art.render() == "s"

    def test_from_output_is_summary_only(self) -> None:
        art = _handoff.HandoffArtifact.from_output("raw text")
        assert art.summary == "raw text"
        assert art.files_changed == []
        assert art.diff_ref is None
        assert art.verdict is None
        assert art.render() == "raw text"

    def test_dropped_resets_only_the_named_field(self) -> None:
        art = _handoff.HandoffArtifact(summary="s", verdict="approve", files_changed=["a.py"])
        dropped = art.dropped("files_changed")
        assert dropped.files_changed == []
        assert dropped.verdict == "approve"
        assert dropped.summary == "s"
        # The original is untouched (frozen model, dropped() returns a copy).
        assert art.files_changed == ["a.py"]

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
            "diff",
            "diff_ref",
            "files_changed",
            "assumptions",
            "questions",
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


class TestHopResultArtifactBackfill:
    def test_hand_built_hop_backfills_artifact_from_output(self) -> None:
        hop = _hop("lead", "the plan")
        assert isinstance(hop.artifact, _handoff.HandoffArtifact)
        assert hop.artifact.summary == "the plan"
        assert hop.artifact.render() == "the plan"

    def test_explicit_artifact_is_not_overwritten(self) -> None:
        art = _handoff.HandoffArtifact(summary="custom", verdict="approve")
        hop = _task.HopResult(
            role="reviewer", member_id="demo-reviewer", ok=True, output="raw", artifact=art
        )
        assert hop.artifact is art
        assert hop.artifact.render() == "custom\nVerdict: approve"

    def test_empty_output_backfills_to_empty_artifact(self) -> None:
        hop = _hop("lead", "")
        assert hop.artifact is not None
        assert hop.artifact.summary == ""
        assert hop.artifact.render() == ""


# ── Persisted-record round trip (the "hops[]" shape in TASK_LIST.json) ──────


class TestHopRecordRoundTrip:
    def test_a_hop_dump_persists_and_restores_artifact_exactly(self) -> None:
        art = _handoff.HandoffArtifact(summary="s", verdict="fail", files_changed=["x.py"])
        hop = _task.HopResult(
            role="reviewer", member_id="demo-reviewer", ok=True, output="s", artifact=art
        )
        rec = hop.model_dump(by_alias=True, mode="json")
        assert rec["artifact"] == art.model_dump()
        # verification_skipped is a this-run-only signal, not part of the
        # durable record (see HopResult's own docstring) -- not persisted.
        assert "verification_skipped" not in rec

        restored = _task.HopResult.model_validate(rec)
        assert restored.artifact == art

    def test_a_record_with_no_artifact_key_degrades_to_summary(self) -> None:
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
        restored = _task.HopResult.model_validate(rec)
        assert restored.artifact is not None
        assert restored.artifact.summary == "old raw text"
        assert restored.artifact.verdict is None
        assert restored.artifact.render() == "old raw text"

    def test_malformed_persisted_artifact_degrades_gracefully(self) -> None:
        rec: dict[str, Any] = {
            "role": "implementer",
            "member": "demo-implementer",
            "ok": True,
            "output": "raw",
            "artifact": {"not": "a valid HandoffArtifact shape"},
        }
        restored = _task.HopResult.model_validate(rec)
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
        restored = _task.HopResult.model_validate(rec)
        assert restored.artifact is not None
        assert restored.artifact.summary == "raw"

    def test_record_with_no_verify_or_evidence_key_loads_with_both_none(self) -> None:
        # Simulates a hop record persisted before HopResult.verify/evidence existed --
        # neither key is present at all, not even as a null value.
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
        restored = _task.HopResult.model_validate(rec)
        assert restored.verify is None
        assert restored.evidence is None

    def test_verify_and_evidence_round_trip_exactly(self) -> None:
        verify = {"cmd": "pytest -q", "exitCode": 0, "durationS": 1.5, "outputTail": "3 passed"}
        evidence = {"commit": "a" * 40, "baseCommit": "b" * 40, "diffStat": {"files": 1}}
        hop = _task.HopResult(
            role="implementer",
            member_id="demo-implementer",
            ok=True,
            output="done",
            verify=verify,
            evidence=evidence,
        )
        rec = hop.model_dump(by_alias=True, mode="json")
        assert rec["verify"] == verify
        assert rec["evidence"] == evidence

        restored = _task.HopResult.model_validate(rec)
        assert restored.verify == verify
        assert restored.evidence == evidence


# ── End to end: dispatch_task builds and threads real artifacts ─────────────


@contextmanager
def _seed_pod(tmp_path: Path, project: str = "demo", *, full: bool = False) -> Iterator[Path]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        roles = _pod.pod.FULL_POD_ROLES if full else _pod.pod.DEFAULT_POD_ROLES
        build_pod(project, roles, codebase=f"/src/{project}")
        yield home


# A step after the Reviewer, so a hop exists that is shown the Reviewer's artifact.
_REVIEW_THEN_FINISH = spec(
    "name: review-then-finish\n"
    "steps:\n"
    "  - lead: lead\n"
    "  - implementer: implementer\n"
    "  - reviewer: reviewer\n"
    "    verdict: [APPROVE, REQUEST-CHANGES]\n"
    "  - finish: implementer\n"
)


class TestDispatchBuildsTypedArtifacts:
    def test_two_hop_dispatch_produces_typed_artifacts_not_strings(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            task = TaskRecord(id="t1", description="work")
            res = _executor.dispatch_task("demo", task, runner=FakeDriver())

            assert res.status == "done"
            assert [h.role for h in res.hops] == ["lead", "implementer"]
            for hop in res.hops:
                assert isinstance(hop.artifact, _handoff.HandoffArtifact)
                # The artifact is a real structured object, not a bare string --
                # the card's own "not a string" acceptance criterion.
                assert not isinstance(hop.artifact, str)
                assert hop.artifact.summary == hop.output

    def test_verdict_gated_hop_artifact_carries_the_parsed_verdict(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, full=True):

            class _Runner:
                def __call__(
                    self,
                    agent_id: str,
                    session_key: str,
                    message: str,
                    timeout: int,
                    env: dict[str, str] | None = None,
                ) -> Any:
                    from docket.agent.ports import TurnResult

                    role = agent_id.rsplit("-", 1)[-1]
                    text = {
                        "lead": "plan",
                        "implementer": "did it",
                        "reviewer": "APPROVE - looks solid",
                    }[role]
                    return TurnResult(True, text, 0.01, {})

            task = TaskRecord(id="t2", description="work")
            res = _executor.dispatch_task("demo", task, runner=_Runner())
            assert res.status == "done"

            reviewer_hop = next(h for h in res.hops if h.role == "reviewer")
            assert reviewer_hop.artifact is not None
            assert reviewer_hop.artifact.verdict == "approve"

            # Non-verdict-gated hops carry no verdict at all.
            lead_hop = next(h for h in res.hops if h.role == "lead")
            assert lead_hop.artifact is not None
            assert lead_hop.artifact.verdict is None

    def test_next_hop_message_is_built_from_rendered_artifact(self, tmp_path: Path) -> None:
        """The next hop's prompt must reflect the reviewer's artifact -- including a structural
        "Verdict: approve" line the raw reviewer text never contained -- proving the message
        is built from ``HandoffArtifact.render()``, not straight from ``HopResult.output``."""
        with _seed_pod(tmp_path, full=True):
            from docket.agent.ports import TurnResult

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
                    }[role]
                    return TurnResult(True, text, 0.01, {})

            task = TaskRecord(id="t3", description="work")
            res = _executor.dispatch_task("demo", task, runner=_Runner(), spec=_REVIEW_THEN_FINISH)
            assert res.status == "done"

            finish_message = [msg for role, msg in calls if role == "implementer"][-1]
            assert "APPROVE - looks solid" in finish_message
            assert "Verdict: approve" in finish_message

    def test_budget_checks_the_rendered_artifact_and_sheds_verdict_before_summary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A verdict-bearing artifact's rendered text (summary + ``Verdict:`` line) is what
        the token-budget compiler checks against budget, not the summary alone; it sheds the
        less-valuable ``verdict`` field first (``DROP_ORDER``) rather than truncating ``summary``."""
        with _seed_pod(tmp_path, full=True):
            # Force every prior hop's carryover share down to just enough room
            # for the reviewer's raw summary (208 bytes -> 52 tokens) but not its
            # full rendered artifact (summary + "\nVerdict: approve" -> 225 bytes
            # -> 56 tokens).
            monkeypatch.setattr(_context, "hop_share", lambda rank, total: 53)

            from docket.agent.ports import TurnResult

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
                    }[role]
                    return TurnResult(True, text, 0.01, {})

            task = TaskRecord(id="t4", description="work")
            res = _executor.dispatch_task("demo", task, runner=_Runner(), spec=_REVIEW_THEN_FINISH)
            assert res.status == "done"
            reviewer_hop = next(h for h in res.hops if h.role == "reviewer")
            assert reviewer_hop.artifact is not None
            assert reviewer_hop.artifact.verdict == "approve"
            # The full rendered text (summary + "\nVerdict: approve") is longer
            # than the raw summary alone -- the budget check must see *that*.
            rendered_len = len(reviewer_hop.artifact.render().encode("utf-8"))
            assert rendered_len > len(reviewer_hop.artifact.summary.encode("utf-8"))

            finish_message = [msg for role, msg in calls if role == "implementer"][-1]
            assert "APPROVE " + ("x" * 200) in finish_message
            assert "Verdict: approve" not in finish_message

    def test_resume_recovers_persisted_artifact_after_a_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A task resumed from a persisted (post-crash) hop history must
        thread the *persisted artifact* into later hops' prompts, not just
        raw text -- proving --resume recovers the structured record."""
        with _seed_pod(tmp_path, full=True):
            task = TaskRecord.model_validate(
                _queue.enqueue_task_once("demo", "work", channel="cli")[0]
            )

            from docket.agent.ports import TurnResult

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

            # Simulate a crash right before the step after the Reviewer: hand-build the
            # resume_from list of the three completed hops the way a real
            # crash-and-restart would load it (through the persisted-record round trip).
            prior_hops = [
                _task.HopResult(
                    role="lead", member_id="demo-lead", ok=True, output="plan", cost_usd=0.0
                ),
                _task.HopResult(
                    role="implementer",
                    member_id="demo-implementer",
                    ok=True,
                    output="did it",
                    cost_usd=0.0,
                ),
                _task.HopResult(
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
            records = [h.model_dump(by_alias=True, mode="json") for h in prior_hops]
            resumed_hops = [_task.HopResult.model_validate(r) for r in records]

            real_parse_verdict = _plan.parse_verdict

            def _reject_reparse(
                gate: _gates.VerdictGate, output: str, declared: str | None = None
            ) -> str | None:
                if output == "APPROVE - solid":
                    raise AssertionError("resume reparsed persisted reviewer prose")
                return real_parse_verdict(gate, output, declared)

            monkeypatch.setattr(_plan, "parse_verdict", _reject_reparse)

            calls: list[tuple[str, str]] = []

            class _FinishRunner:
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
                    return TurnResult(True, "finished", 0.01, {})

            res = _executor.dispatch_task(
                "demo",
                task,
                runner=_FinishRunner(),
                resume_from=resumed_hops,
                spec=_REVIEW_THEN_FINISH,
            )
            assert res.status == "done"
            assert [h.role for h in res.hops] == ["lead", "implementer", "reviewer", "implementer"]

            finish_message = next(msg for role, msg in calls if role == "implementer")
            # The resumed reviewer hop's *persisted artifact* (not a fresh parse
            # of raw text) is what reached the next hop's prompt.
            assert "APPROVE - solid" in finish_message
            assert "Verdict: approve" in finish_message


# ── the handoff call and the prompt manifest ─────────────────────────────────


def _reviewer_runner(reviewer: Any) -> Any:
    from docket.agent.ports import TurnResult

    texts = {"lead": "plan", "implementer": "did it"}

    def _run(
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> Any:
        role = agent_id.rsplit("-", 1)[-1]
        if role == "reviewer":
            return reviewer
        return TurnResult(True, texts[role], 0.01, {})

    return _run


class TestHandoffCallBuildsTheRecord:
    def test_the_call_supplies_summary_verdict_and_assumptions_and_the_gate_passes(
        self, tmp_path: Path
    ) -> None:
        from docket.agent.ports import TurnResult

        reviewer = TurnResult(
            True,
            "Looks fine.\nAPPROVE",
            0.01,
            {},
            closing_args={
                "summary": "Reviewed the diff.",
                "verdict": "approve",
                "assumptions": ["python 3.13", "no new deps"],
                "questions": ["rename the helper?"],
            },
        )
        with _seed_pod(tmp_path, full=True):
            res = _executor.dispatch_task(
                "demo", TaskRecord(id="h1", description="work"), runner=_reviewer_runner(reviewer)
            )

        assert res.status == "done"
        artifact = next(h for h in res.hops if h.role == "reviewer").artifact
        assert artifact is not None
        assert artifact.verdict == "approve"
        assert artifact.summary == "Reviewed the diff."
        assert artifact.assumptions == ["python 3.13", "no new deps"]
        assert artifact.questions == ["rename the helper?"]

    def test_the_call_wins_over_a_contradicting_marker_line(self, tmp_path: Path) -> None:
        from docket.agent.ports import TurnResult

        reviewer = TurnResult(
            True, "APPROVE", 0.01, {}, closing_args={"verdict": "request-changes"}
        )
        with _seed_pod(tmp_path, full=True):
            res = _executor.dispatch_task(
                "demo", TaskRecord(id="h2", description="work"), runner=_reviewer_runner(reviewer)
            )

        artifact = next(h for h in res.hops if h.role == "reviewer").artifact
        assert artifact is not None and artifact.verdict == "request-changes"

    def test_a_marker_line_alone_still_yields_the_verdict_and_nothing_else(
        self, tmp_path: Path
    ) -> None:
        from docket.agent.ports import TurnResult

        reviewer = TurnResult(True, "Fine.\nAPPROVE", 0.01, {})
        with _seed_pod(tmp_path, full=True):
            res = _executor.dispatch_task(
                "demo", TaskRecord(id="h3", description="work"), runner=_reviewer_runner(reviewer)
            )

        assert res.status == "done"
        artifact = next(h for h in res.hops if h.role == "reviewer").artifact
        assert artifact is not None
        assert (artifact.verdict, artifact.summary) == ("approve", "Fine.\nAPPROVE")
        assert artifact.assumptions == [] and artifact.questions == []

    def test_a_next_hop_is_shown_the_assumptions(self, tmp_path: Path) -> None:
        from docket.agent.ports import TurnResult

        reviewer = TurnResult(
            True, "APPROVE", 0.01, {}, closing_args={"verdict": "approve", "assumptions": ["A1"]}
        )
        seen: list[str] = []
        base = _reviewer_runner(reviewer)

        def runner(
            agent_id: str,
            session_key: str,
            message: str,
            timeout: int,
            env: dict[str, str] | None = None,
        ) -> Any:
            if agent_id.endswith("-implementer"):
                seen.append(message)
            return base(agent_id, session_key, message, timeout, env)

        with _seed_pod(tmp_path, full=True):
            _executor.dispatch_task(
                "demo",
                TaskRecord(id="h4", description="work"),
                runner=runner,
                spec=_REVIEW_THEN_FINISH,
            )

        assert "Assumptions:\n- A1" in seen[-1]


class TestPromptManifest:
    def test_a_hop_records_each_layers_hash_equal_to_the_shipped_prompts(
        self, tmp_path: Path
    ) -> None:
        from docket.teams import prompts as _prompts

        with _seed_pod(tmp_path, full=True):
            res = _executor.dispatch_task(
                "demo", TaskRecord(id="m1", description="work"), runner=FakeDriver()
            )

        reviewer = next(h for h in res.hops if h.role == "reviewer")
        layers = {entry["layer"]: entry for entry in reviewer.prompt_manifest["layers"]}
        hop = _prompts.shipped_prompt("hop", "reviewer")
        identity = _prompts.shipped_prompt("identity", "reviewer")
        assert (layers["hop"]["sha256"], layers["hop"]["version"], layers["hop"]["scope"]) == (
            hop.sha256,
            hop.version,
            "shipped",
        )
        assert layers["identity"]["sha256"] == identity.sha256
        assert layers["hop"]["tokens"] > 0
        assert set(reviewer.prompt_manifest) == {"layers", "model", "family", "class", "profile"}
        assert reviewer.prompt_manifest["profile"] == "hosted"

    def test_a_non_lead_hop_records_its_task_section_between_identity_and_hop(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path, full=True):
            res = _executor.dispatch_task(
                "demo", TaskRecord(id="m2", description="work"), runner=FakeDriver()
            )

        implementer = next(h for h in res.hops if h.role == "implementer")
        lead = next(h for h in res.hops if h.role == "lead")
        entries = implementer.prompt_manifest["layers"]
        assert [entry["layer"] for entry in entries] == ["identity", "task", "hop"]
        task = entries[1]
        assert (task["scope"], task["version"], task["tokens"] > 0) == ("task", "", True)
        assert "task" not in [entry["layer"] for entry in lead.prompt_manifest["layers"]]

    def test_the_manifest_is_dumped_as_prompt_manifest_and_read_back(self) -> None:
        manifest = {"layers": [], "model": "m", "family": "", "class": "any", "profile": "hosted"}
        hop = _task.HopResult(role="lead", output="x", prompt_manifest=manifest)

        dumped = hop.model_dump(by_alias=True)

        assert dumped["promptManifest"] == manifest
        assert _task.HopResult.model_validate(dumped).prompt_manifest == manifest

    def test_a_hop_persisted_before_the_manifest_loads_with_an_empty_one(self) -> None:
        hop = _task.HopResult.model_validate({"role": "lead", "output": "x", "ok": True})

        assert hop.prompt_manifest == {}
        assert "promptManifest" not in hop.model_dump(by_alias=True)
