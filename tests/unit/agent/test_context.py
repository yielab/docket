"""The context compiler (`agent/context.py`).

Pure-function tests: `estimate_tokens`'s chars/token approximation,
`budget_for_role`'s archetype-registry resolution, the per-hop carryover
share, and `compile_artifact`'s `DROP_ORDER` contract (fields shed one at a
time before `summary`, which is truncated rather than dropped).
"""

from __future__ import annotations

import docket.kernel.templates as _templates
from docket.agent import context as _ctx
from docket.agent import ports as _ports
from docket.kernel.handoff import HandoffArtifact, render_diff_omitted
from docket.kernel.home import Home, use_home
from docket.teams import builtin_roles as _builtin_roles
from docket.teams import config_docs as _config_docs
from docket.teams import roles as _arch

SUBJECT = "docket.agent.context"


# ── budget_for_role ──────────────────────────────────────────────────────────


class TestBudgetForRole:
    def test_builtin_role_resolves_its_archetypes_token_budget(self) -> None:
        assert (
            _ctx.budget_for_role("implementer")
            == _builtin_roles.BUILTIN_ARCHETYPES["implementer"].token_budget
        )
        assert (
            _ctx.budget_for_role("reviewer")
            == _builtin_roles.BUILTIN_ARCHETYPES["reviewer"].token_budget
        )
        assert (
            _ctx.budget_for_role("tester")
            == _builtin_roles.BUILTIN_ARCHETYPES["tester"].token_budget
        )
        assert (
            _ctx.budget_for_role("lead") == _builtin_roles.BUILTIN_ARCHETYPES["lead"].token_budget
        )

    def test_unregistered_role_falls_back_to_the_default(self) -> None:
        assert _ctx.budget_for_role("no-such-role-anywhere") == _ctx.DEFAULT_TOKEN_BUDGET

    def test_every_builtin_and_starter_archetype_has_a_positive_budget(self) -> None:
        for name, found in {
            **_builtin_roles.BUILTIN_ARCHETYPES,
            **_builtin_roles.STARTER_ARCHETYPES,
        }.items():
            assert found.token_budget > 0, name

    def test_defensively_falls_back_for_a_non_positive_budget(self) -> None:
        """`RoleArchetype.__post_init__` already rejects a non-positive `tokenBudget` for anything built the normal way (`from_wire`, or a plain constructor call) -- this exercises `budget_for_role`'s own defensive fallback for the one way around that: bypassing the frozen dataclass's `__init__` after construction."""
        arch = _builtin_roles.BUILTIN_ARCHETYPES["implementer"]
        object.__setattr__(arch, "token_budget", 0)
        try:
            assert _ctx.budget_for_role("implementer") == _ctx.DEFAULT_TOKEN_BUDGET
        finally:
            object.__setattr__(arch, "token_budget", 8000)

    def test_a_registered_archetype_budget_ignores_any_window_argument(self) -> None:
        """An archetype's own declared token_budget is data set on purpose -- a resolved
        model window must never override it, unlike the unregistered-role fallback below."""
        assert (
            _ctx.budget_for_role(
                "implementer", context_window_tokens=1_000_000, max_output_tokens=8_192
            )
            == _builtin_roles.BUILTIN_ARCHETYPES["implementer"].token_budget
        )

    def test_unregistered_role_with_no_window_still_falls_back_to_the_default(self) -> None:
        """Every existing caller omits the window kwargs -- confirms they keep resolving
        plain DEFAULT_TOKEN_BUDGET, byte-for-byte, with the new signature in place."""
        assert (
            _ctx.budget_for_role("no-such-role-anywhere", context_window_tokens=None)
            == _ctx.DEFAULT_TOKEN_BUDGET
        )

    def test_unregistered_role_with_a_large_window_gets_a_window_share(self) -> None:
        """Once a caller does supply a window, the unregistered-role fallback may exceed
        DEFAULT_TOKEN_BUDGET -- this capability is added but not wired into any existing
        caller (dispatch.py's hop composition, session.py's compaction default)."""
        budget = _ctx.budget_for_role(
            "no-such-role-anywhere", context_window_tokens=200_000, max_output_tokens=8_192
        )
        assert budget > _ctx.DEFAULT_TOKEN_BUDGET

    def test_pod_scoped_archetype_resolves_its_token_budget(self, tmp_path) -> None:
        """A pod-scoped role with a declared tokenBudget is resolved when project= is passed."""
        home = tmp_path / "docket-home"
        home.mkdir()

        role_file = _templates.RECIPES_DIR / "secure-build" / "roles" / "security-vetter.yaml"
        doc = _config_docs.load_document(role_file)
        with use_home(Home(home)):
            _arch.add_user_archetype(doc.doc, "mypod")

            found_budget = _ctx.budget_for_role("security-vetter", project="mypod")
        assert found_budget > 0

    def test_pod_scoped_call_with_global_role_still_returns_builtin(self) -> None:
        """When a global role (like 'implementer') exists and project= is passed but
        no pod override exists, the global registry is still consulted."""
        global_budget = _ctx.budget_for_role("implementer")
        pod_budget = _ctx.budget_for_role("implementer", project="nonexistent-pod")
        assert pod_budget == global_budget


class TestResolveWindowShareTokens:
    def test_absent_window_returns_the_floor(self) -> None:
        assert (
            _ctx.resolve_window_share_tokens(
                context_window_tokens=None, max_output_tokens=None, floor_tokens=6000
            )
            == 6000
        )

    def test_non_positive_window_returns_the_floor(self) -> None:
        assert (
            _ctx.resolve_window_share_tokens(
                context_window_tokens=0, max_output_tokens=None, floor_tokens=6000
            )
            == 6000
        )

    def test_a_small_registered_window_stays_at_the_floor(self) -> None:
        """Today's only deployed window (16384 tokens, 8192 reserved for output) must
        resolve to exactly today's floor -- the whole point of a floor, not a ceiling."""
        assert (
            _ctx.resolve_window_share_tokens(
                context_window_tokens=16_384,
                max_output_tokens=8_192,
                floor_tokens=6000,
                reserved_tokens=_ctx.TOOL_SCHEMA_RESERVE_TOKENS,
            )
            == 6000
        )

    def test_a_large_registered_window_clears_the_floor(self) -> None:
        result = _ctx.resolve_window_share_tokens(
            context_window_tokens=200_000,
            max_output_tokens=8_192,
            floor_tokens=6000,
            reserved_tokens=_ctx.TOOL_SCHEMA_RESERVE_TOKENS,
        )
        assert result > 6000
        assert result == max(
            6000, int((200_000 - 8_192 - _ctx.TOOL_SCHEMA_RESERVE_TOKENS) * _ctx.WINDOW_SHARE)
        )

    def test_reserves_never_go_negative(self) -> None:
        """An output reserve larger than the window must not underflow to a negative budget."""
        assert (
            _ctx.resolve_window_share_tokens(
                context_window_tokens=1000,
                max_output_tokens=5000,
                floor_tokens=6000,
            )
            == 6000
        )


# ── hop_share ────────────────────────────────────────────────────────────────


class TestHopShare:
    def test_most_recent_hop_gets_half_the_total(self) -> None:
        assert _ctx.hop_share(0, 8000) == 4000

    def test_each_older_rank_halves_again(self) -> None:
        assert _ctx.hop_share(1, 8000) == 2000
        assert _ctx.hop_share(2, 8000) == 1000
        assert _ctx.hop_share(3, 8000) == 500

    def test_sum_across_any_number_of_ranks_never_reaches_the_total(self) -> None:
        total = 8192
        for n in (1, 2, 3, 10, 50):
            shares = [_ctx.hop_share(r, total) for r in range(n)]
            assert sum(shares) < total


# ── compile_artifact ─────────────────────────────────────────────────────────


class TestCompileArtifact:
    def test_artifact_within_budget_is_returned_unchanged(self) -> None:
        art = HandoffArtifact(summary="did the thing")
        compiled = _ctx.compile_artifact(art, budget_tokens=1000)
        assert compiled.text == "did the thing"
        assert compiled.truncated is False
        assert compiled.dropped_fields == ()
        assert compiled.summary_truncated is False
        assert compiled.original_tokens == compiled.tokens

    def test_fields_are_shed_in_declared_drop_order(self) -> None:
        """diff -> diff_ref -> files_changed -> assumptions -> questions -> verdict, one at a time, stopping the moment the render fits -- pinned against `HandoffArtifact.DROP_ORDER` itself, not a hardcoded tuple, so this test breaks (loudly) if the order is ever changed there."""
        assert HandoffArtifact.DROP_ORDER == (
            "diff",
            "diff_ref",
            "files_changed",
            "assumptions",
            "questions",
            "verdict",
        )

        art = HandoffArtifact(
            summary="s",
            verdict="approve",
            files_changed=["a.py", "b.py"],
            diff_ref="/repo/worktree",
            diff="--- new file: a.py\nprint(1)\n",
        )
        full = art.render()
        # Budget that fits everything except the full render -- forces at
        # least one field to be shed.
        budget = _ports.estimate_tokens(full) - 1
        compiled = _ctx.compile_artifact(art, budget_tokens=budget)
        assert compiled.dropped_fields == ("diff",)
        assert "Diff:" not in compiled.text
        assert "Diff ref: /repo/worktree" in compiled.text  # least-valuable shed first, only

    def test_sheds_every_droppable_field_before_touching_summary(self) -> None:
        art = HandoffArtifact(
            summary="the real content that must survive",
            verdict="approve",
            files_changed=["a.py"],
            diff_ref="/repo",
            diff="d",
        )
        # A budget that only the bare summary fits -- every droppable field must go, in order,
        # none of them left behind; the omitted-diff line does not count against it.
        marker = render_diff_omitted(len(art.diff))
        budget = _ports.estimate_tokens(art.summary)
        compiled = _ctx.compile_artifact(art, budget_tokens=budget)
        assert compiled.dropped_fields == ("diff", "diff_ref", "files_changed", "verdict")
        assert compiled.text == f"{art.summary}\n{marker}"
        assert compiled.summary_truncated is False

    def test_empty_fields_are_skipped_not_reported_as_dropped(self) -> None:
        """A field that was already empty (the honest state of `diff_ref`/`files_changed` today -- dispatch has no producer for them yet, see `kernel/handoff.py`) is never claimed as "dropped": there was nothing there to shed."""
        art = HandoffArtifact(summary="x" * 10_000)  # only summary is set
        compiled = _ctx.compile_artifact(art, budget_tokens=1)
        # Nothing was droppable -- straight to summary truncation.
        assert compiled.dropped_fields == ()
        assert compiled.summary_truncated is True

    def test_summary_is_never_silently_dropped_only_truncated_with_a_marker(self) -> None:
        art = HandoffArtifact(summary="A" * 5000, diff="expendable")
        compiled = _ctx.compile_artifact(art, budget_tokens=5)
        assert compiled.summary_truncated is True
        assert compiled.text != ""
        assert "[... summary truncated:" in compiled.text
        assert "bytes omitted ...]" in compiled.text

    def test_truncated_summary_marker_records_the_exact_omitted_byte_count(self) -> None:
        art = HandoffArtifact(summary="B" * 500)
        compiled = _ctx.compile_artifact(art, budget_tokens=25)  # 100 bytes
        marker_n = int(compiled.text.split("truncated: ")[1].split(" bytes")[0])
        kept = len(compiled.text.encode("utf-8")) - len(
            f"\n[... summary truncated: {marker_n} bytes omitted ...]\n"
        )
        assert marker_n + kept == 500

    def test_result_stays_within_budget_for_reasonable_budgets(self) -> None:
        """For any budget that can actually fit the truncation marker itself, the compiled result's own token estimate never exceeds it."""
        art = HandoffArtifact(summary="C" * 3000, verdict="fail", files_changed=["x.py"])
        for budget in (2000, 500, 100, 50):
            compiled = _ctx.compile_artifact(art, budget_tokens=budget)
            assert compiled.tokens <= budget

    def test_near_zero_budget_still_bounded_and_deterministic(self) -> None:
        """A budget too small to even fit the truncation marker (documented, pragmatic compromise already accepted for this same edge case in the predecessor's zero-budget case -- you cannot say "N bytes omitted" in fewer bytes than the sentence itself needs) still produces a real, marked, deterministic result -- never a silent "no truncation happened", and never a crash."""
        art = HandoffArtifact(summary="D" * 50)
        for budget in (1, 0):
            compiled = _ctx.compile_artifact(art, budget_tokens=budget)
            assert compiled.summary_truncated is True
            assert "[... summary truncated:" in compiled.text
            assert "bytes omitted ...]" in compiled.text

    def test_truncated_property_true_only_when_something_was_shed_or_cut(self) -> None:
        art = HandoffArtifact(summary="small")
        fits = _ctx.compile_artifact(art, budget_tokens=1000)
        assert fits.truncated is False

        forced = _ctx.compile_artifact(art, budget_tokens=0)
        assert forced.truncated is True


class TestOmittedDiffIsAnnounced:
    """A diff shed by the budget leaves one line saying so and where to look."""

    def test_the_marker_names_the_dropped_size_and_the_command(self) -> None:
        art = HandoffArtifact(summary="did it", diff="+" * 400, files_changed=["a.py"])
        budget = _ports.estimate_tokens(art.render()) - 1
        compiled = _ctx.compile_artifact(art, budget_tokens=budget)
        assert compiled.dropped_fields == ("diff",)
        assert compiled.text.splitlines() == [
            "did it",
            "[diff omitted: 400 chars over budget; run git diff in the worktree]",
            "Files changed: a.py",
        ]

    def test_it_survives_summary_truncation(self) -> None:
        art = HandoffArtifact(summary="A" * 5000, diff="expendable")
        compiled = _ctx.compile_artifact(art, budget_tokens=60)
        assert compiled.summary_truncated is True
        assert "[diff omitted: 10 chars over budget;" in compiled.text
        assert compiled.tokens <= 60

    def test_an_artifact_that_never_had_a_diff_gets_no_marker(self) -> None:
        art = HandoffArtifact(summary="S" * 5000, files_changed=["a.py"])
        compiled = _ctx.compile_artifact(art, budget_tokens=60)
        assert "diff omitted" not in compiled.text

    def test_an_artifact_that_fits_keeps_its_diff_and_no_marker(self) -> None:
        compiled = _ctx.compile_artifact(HandoffArtifact(summary="s", diff="+x"), 1000)
        assert "Diff:\n+x" in compiled.text and "diff omitted" not in compiled.text
