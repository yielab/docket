"""Structured handoff artifacts (`kernel/handoff.py`).

Pure-function tests: `HandoffArtifact.render()`/`dropped()`/`from_output()`'s existing
contract, plus this card's addition -- `parse_brief` (the last fenced ```json block that
validates as a `TaskBrief`, `None` on any other outcome), `render_brief`'s fixed field order,
and `HandoffArtifact.brief` never being shed by a token-budgeted consumer (it is excluded from
`DROP_ORDER`, the same posture `summary` already has).
"""

from __future__ import annotations

import pytest

from docket.agent import context as _ctx
from docket.kernel.brief import TaskBrief
from docket.kernel.handoff import (
    HandoffArtifact,
    cap_diff,
    parse_brief,
    parse_handoff_call,
    render_brief,
)

SUBJECT = "docket.kernel.handoff"

# ── parse_brief ───────────────────────────────────────────────────────────────


class TestParseBrief:
    def test_a_single_valid_fence_parses(self) -> None:
        text = (
            "Some reasoning.\n\n"
            '```json\n{"objective": "add a widget", "acceptance": ["it renders"]}\n```\n'
            "READY"
        )
        brief = parse_brief(text)
        assert brief is not None
        assert brief.objective == "add a widget"
        assert brief.acceptance == ["it renders"]

    def test_the_last_of_two_fences_wins(self) -> None:
        text = (
            '```json\n{"objective": "the wrong one"}\n```\n'
            "On reflection:\n"
            '```json\n{"objective": "the right one"}\n```\n'
        )
        brief = parse_brief(text)
        assert brief is not None
        assert brief.objective == "the right one"

    def test_no_fence_returns_none(self) -> None:
        assert parse_brief("just prose, no fence, then READY") is None

    def test_invalid_json_returns_none_not_a_raise(self) -> None:
        assert parse_brief("```json\n{not valid json\n```") is None

    def test_a_non_object_payload_returns_none(self) -> None:
        assert parse_brief('```json\n["a", "list", "not", "an", "object"]\n```') is None

    def test_a_schema_mismatch_returns_none_not_a_raise(self) -> None:
        # `objective` is required and non-empty -- an empty one fails TaskBrief's own
        # validator, which must degrade to None here, never propagate as an exception.
        assert parse_brief('```json\n{"objective": ""}\n```') is None

    def test_an_unknown_field_returns_none(self) -> None:
        # TaskBrief is `extra="forbid"` -- a field the schema doesn't know about is a
        # real validation failure, degrading the same as any other one.
        text = '```json\n{"objective": "ok", "notAField": true}\n```'
        assert parse_brief(text) is None

    def test_a_resources_prefix_violation_returns_none(self) -> None:
        text = '```json\n{"objective": "ok", "resources": ["not-a-valid-prefix"]}\n```'
        assert parse_brief(text) is None


# ── render_brief ──────────────────────────────────────────────────────────────


class TestRenderBrief:
    def test_objective_only_renders_just_the_objective_line(self) -> None:
        brief = TaskBrief(objective="do the thing")
        assert render_brief(brief) == "Objective: do the thing"

    def test_every_field_renders_in_a_fixed_order(self) -> None:
        brief = TaskBrief(
            objective="add rate limiting",
            acceptance=["429 after 100 req/min"],
            context=["existing middleware lives in api/mw.py"],
            constraints=["no new dependency"],
            assumptions=["Redis is already provisioned"],
            questions=["which endpoint?"],
            resources=["secret:REDIS_URL"],
            expected_risky_actions=["restart the service"],
        )
        rendered = render_brief(brief)
        for label in (
            "Objective:",
            "Acceptance:",
            "Context:",
            "Constraints:",
            "Assumptions:",
            "Resources:",
            "Expected risky actions:",
            "Questions:",
        ):
            assert label in rendered
        # Fixed order: Acceptance before Context before Constraints before
        # Assumptions before Resources before Expected risky actions before Questions.
        order = [
            rendered.index(label)
            for label in (
                "Acceptance:",
                "Context:",
                "Constraints:",
                "Assumptions:",
                "Resources:",
                "Expected risky actions:",
                "Questions:",
            )
        ]
        assert order == sorted(order)

    def test_an_empty_list_field_contributes_no_section(self) -> None:
        brief = TaskBrief(objective="minimal", acceptance=[])
        assert "Acceptance:" not in render_brief(brief)


# ── HandoffArtifact.brief ───────────────────────────────────────────────────


class TestHandoffArtifactBrief:
    def test_brief_defaults_to_none(self) -> None:
        assert HandoffArtifact(summary="plain hop, no brief").brief is None

    def test_from_output_carries_no_brief(self) -> None:
        assert HandoffArtifact.from_output("raw text").brief is None

    def test_render_appends_a_brief_section_when_present(self) -> None:
        brief = TaskBrief(objective="add a widget", acceptance=["widget renders"])
        artifact = HandoffArtifact(summary="I looked into it.", brief=brief)
        rendered = artifact.render()
        assert rendered.startswith("I looked into it.")
        assert "Brief:" in rendered
        assert "Objective: add a widget" in rendered
        assert "widget renders" in rendered

    def test_render_omits_the_brief_section_when_absent(self) -> None:
        assert "Brief:" not in HandoffArtifact(summary="nothing special").render()

    def test_dropped_refuses_to_shed_brief(self) -> None:
        brief = TaskBrief(objective="add a widget")
        artifact = HandoffArtifact(summary="x", brief=brief)
        try:
            artifact.dropped("brief")
        except ValueError:
            pass
        else:
            raise AssertionError("dropped('brief') should have raised ValueError")

    def test_brief_is_excluded_from_drop_order(self) -> None:
        assert "brief" not in HandoffArtifact.DROP_ORDER

    def test_compile_artifact_never_sheds_brief_even_under_a_tiny_budget(self) -> None:
        brief = TaskBrief(objective="add a widget", acceptance=["widget renders"])
        artifact = HandoffArtifact(
            summary="a very long summary " * 200,
            files_changed=["a.py", "b.py"],
            diff_ref="feature-branch",
            verdict="approve",
            brief=brief,
        )
        compiled = _ctx.compile_artifact(artifact, budget_tokens=1)
        # Every droppable field was shed and summary itself was truncated -- but the
        # brief's own content must still be present in the final rendered text, since
        # it is excluded from DROP_ORDER and `render()` always includes it when set.
        assert "Objective: add a widget" in compiled.text
        assert set(compiled.dropped_fields) == {"diff_ref", "files_changed", "verdict"}


class TestDiff:
    def test_render_puts_the_diff_once_right_after_the_summary(self) -> None:
        art = HandoffArtifact(summary="done", diff="--- new file: n.md\nbody\n", verdict="approve")
        assert art.render() == "done\nDiff:\n--- new file: n.md\nbody\n\nVerdict: approve"
        assert art.render().count("body") == 1

    def test_no_diff_renders_the_summary_unchanged(self) -> None:
        assert HandoffArtifact(summary="done").render() == "done"

    def test_dropped_diff_resets_to_empty(self) -> None:
        assert HandoffArtifact(summary="s", diff="d").dropped("diff").diff == ""

    def test_cap_diff_leaves_a_fitting_text_alone(self) -> None:
        assert cap_diff("abc", 3) == "abc"

    def test_cap_diff_cuts_and_says_how_much_is_missing(self) -> None:
        assert cap_diff("abcdef", 4) == "abcd\n[diff cut at 4 characters; 2 more not shown]"


class TestDiffOmittedMarker:
    """`render(diff_omitted=N)` says a diff was shed and where to find it, in the diff's place."""

    def test_the_marker_takes_the_place_of_the_diff_block(self) -> None:
        art = HandoffArtifact(summary="done", files_changed=["a.py"], verdict="x")
        assert art.render(diff_omitted=1234).splitlines() == [
            "done",
            "[diff omitted: 1234 chars over budget; run git diff in the worktree]",
            "Verdict: x",
            "Files changed: a.py",
        ]

    def test_a_present_diff_wins_over_the_marker(self) -> None:
        art = HandoffArtifact(summary="done", diff="+x")
        assert "diff omitted" not in art.render(diff_omitted=5)

    def test_the_default_render_is_unchanged(self) -> None:
        assert HandoffArtifact(summary="done").render() == "done"


# ── the handoff call and the artifact fields it fills ─────────────────────────


class TestParseHandoffCall:
    def test_the_published_field_names_are_read(self) -> None:
        call = parse_handoff_call(
            {
                "summary": "done",
                "filesChanged": ["a.py"],
                "verdict": "approve",
                "assumptions": ["x"],
                "questions": ["y"],
            }
        )

        assert call is not None
        assert (call.summary, call.files_changed, call.verdict) == ("done", ["a.py"], "approve")
        assert (call.assumptions, call.questions) == (["x"], ["y"])

    @pytest.mark.parametrize("args", [None, {}, {"assumptions": "not a list"}])
    def test_no_call_or_one_that_breaks_the_schema_is_none(self, args: dict | None) -> None:  # type: ignore[type-arg]
        assert parse_handoff_call(args) is None


class TestAssumptionsAndQuestions:
    def test_they_render_after_the_verdict_and_never_when_empty(self) -> None:
        art = HandoffArtifact(
            summary="s", verdict="approve", assumptions=["A1"], questions=["Q1", "Q2"]
        )

        assert art.render() == "s\nVerdict: approve\nAssumptions:\n- A1\nQuestions:\n- Q1\n- Q2"
        assert HandoffArtifact(summary="s").render() == "s"

    def test_an_empty_pair_is_absent_from_the_dump(self) -> None:
        assert "assumptions" not in HandoffArtifact(summary="s").model_dump()
        assert HandoffArtifact(summary="s", questions=["q"]).model_dump()["questions"] == ["q"]
