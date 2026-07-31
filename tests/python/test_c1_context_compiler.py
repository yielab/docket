"""ROADMAP Phase 17 C-1: the context compiler (`core/context.py`).

Pure-function unit tests for the module that supersedes Phase 14 R-7's blind
byte cap. Covers:

  * TestEstimateTokens  — the chars/token approximation itself (reuses
    `config.CONTEXT_BYTES_PER_TOKEN`, the same ratio `maintain check`
    already uses -- not a second, independently-tunable one).
  * TestBudgetForRole   — resolving a role name against the live archetype
    registry (`core/archetypes.py`), and the fallback for an unregistered
    role or a defensively-invalid budget.
  * TestHopShare        — the recency-weighted per-hop carryover share
    (same halving series R-7 used, now denominated in tokens).
  * TestCompileArtifact — the heart of the card: an artifact that already
    fits is returned unchanged; `HandoffArtifact.DROP_ORDER` fields are shed
    one at a time, in order, before `summary` is ever touched; `summary` is
    never silently dropped, only truncated with a visible marker as the
    last resort; the result never exceeds its budget (mod the documented
    zero-budget marker-can't-fit edge case R-7 itself already accepted).

`core/dispatch.py`'s `_hop_message` (the one production caller) has its own
integration coverage in `tests/python/test_r7_hop_carryover.py` and
`tests/python/test_w5_handoff_artifacts.py`.
"""

from __future__ import annotations

import docket.config as _cfg
from docket.core import archetypes as _arch
from docket.core import context as _ctx
from docket.core.handoff import HandoffArtifact

# ── estimate_tokens ──────────────────────────────────────────────────────────


class TestEstimateTokens:
    def test_empty_string_is_zero_tokens(self) -> None:
        assert _ctx.estimate_tokens("") == 0

    def test_uses_the_documented_bytes_per_token_ratio(self) -> None:
        text = "x" * 40
        assert (
            _ctx.estimate_tokens(text) == len(text.encode("utf-8")) // _cfg.CONTEXT_BYTES_PER_TOKEN
        )

    def test_reuses_the_existing_config_ratio_not_a_second_one(self) -> None:
        """The whole point of reusing `config.CONTEXT_BYTES_PER_TOKEN` (rather
        than inventing a second ratio) is that changing the one config value
        changes both `maintain check`'s and this module's estimate together."""
        text = "y" * 100
        before = _ctx.estimate_tokens(text)
        try:
            _cfg.CONTEXT_BYTES_PER_TOKEN = 10
            after = _ctx.estimate_tokens(text)
        finally:
            _cfg.CONTEXT_BYTES_PER_TOKEN = 4
        assert before == 25
        assert after == 10

    def test_utf8_multibyte_text_counted_in_bytes_not_characters(self) -> None:
        # "é" is 2 bytes in UTF-8 -- the estimate must reflect that, not the
        # 1-character length Python's `len()` would report.
        text = "é" * 8  # 16 bytes
        assert _ctx.estimate_tokens(text) == 16 // _cfg.CONTEXT_BYTES_PER_TOKEN


# ── budget_for_role ──────────────────────────────────────────────────────────


class TestBudgetForRole:
    def test_builtin_role_resolves_its_archetypes_token_budget(self) -> None:
        assert (
            _ctx.budget_for_role("implementer")
            == _arch.BUILTIN_ARCHETYPES["implementer"].token_budget
        )
        assert _ctx.budget_for_role("reviewer") == _arch.BUILTIN_ARCHETYPES["reviewer"].token_budget
        assert _ctx.budget_for_role("tester") == _arch.BUILTIN_ARCHETYPES["tester"].token_budget
        assert _ctx.budget_for_role("lead") == _arch.BUILTIN_ARCHETYPES["lead"].token_budget

    def test_unregistered_role_falls_back_to_the_default(self) -> None:
        assert _ctx.budget_for_role("no-such-role-anywhere") == _ctx.DEFAULT_TOKEN_BUDGET

    def test_every_builtin_and_starter_archetype_has_a_positive_budget(self) -> None:
        for name, found in {**_arch.BUILTIN_ARCHETYPES, **_arch.STARTER_ARCHETYPES}.items():
            assert found.token_budget > 0, name

    def test_defensively_falls_back_for_a_non_positive_budget(self) -> None:
        """`RoleArchetype.__post_init__` already rejects a non-positive
        `tokenBudget` for anything built the normal way (`from_wire`, or a
        plain constructor call) -- this exercises `budget_for_role`'s own
        defensive fallback for the one way around that: bypassing the
        frozen dataclass's `__init__` after construction."""
        arch = _arch.BUILTIN_ARCHETYPES["implementer"]
        object.__setattr__(arch, "token_budget", 0)
        try:
            assert _ctx.budget_for_role("implementer") == _ctx.DEFAULT_TOKEN_BUDGET
        finally:
            object.__setattr__(arch, "token_budget", 8000)


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
        """notes -> diff_ref -> files_changed -> verdict, one at a time,
        stopping the moment the render fits -- pinned against
        `HandoffArtifact.DROP_ORDER` itself, not a hardcoded tuple, so this
        test breaks (loudly) if the order is ever changed there."""
        assert HandoffArtifact.DROP_ORDER == ("notes", "diff_ref", "files_changed", "verdict")

        art = HandoffArtifact(
            summary="s",
            verdict="approve",
            files_changed=["a.py", "b.py"],
            diff_ref="/repo/worktree",
            notes="took two tries",
        )
        full = art.render()
        # Budget that fits everything except the full render -- forces at
        # least one field to be shed.
        budget = _ctx.estimate_tokens(full) - 1
        compiled = _ctx.compile_artifact(art, budget_tokens=budget)
        assert compiled.dropped_fields == ("notes",)
        assert "Notes:" not in compiled.text
        assert "Verdict: approve" in compiled.text  # least-valuable shed first, only

    def test_sheds_every_droppable_field_before_touching_summary(self) -> None:
        art = HandoffArtifact(
            summary="the real content that must survive",
            verdict="approve",
            files_changed=["a.py"],
            diff_ref="/repo",
            notes="n",
        )
        # A budget that only the bare summary fits -- every droppable field
        # must go, in order, none of them left behind.
        budget = _ctx.estimate_tokens(art.summary)
        compiled = _ctx.compile_artifact(art, budget_tokens=budget)
        assert compiled.dropped_fields == ("notes", "diff_ref", "files_changed", "verdict")
        assert compiled.text == art.summary
        assert compiled.summary_truncated is False

    def test_empty_fields_are_skipped_not_reported_as_dropped(self) -> None:
        """A field that was already empty (the honest state of `notes`/
        `diff_ref`/`files_changed` today -- dispatch has no producer for them
        yet, see `core/handoff.py`) is never claimed as "dropped": there was
        nothing there to shed."""
        art = HandoffArtifact(summary="x" * 10_000)  # only summary is set
        compiled = _ctx.compile_artifact(art, budget_tokens=1)
        # Nothing was droppable -- straight to summary truncation.
        assert compiled.dropped_fields == ()
        assert compiled.summary_truncated is True

    def test_summary_is_never_silently_dropped_only_truncated_with_a_marker(self) -> None:
        art = HandoffArtifact(summary="A" * 5000, notes="expendable")
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
        """For any budget that can actually fit the truncation marker itself,
        the compiled result's own token estimate never exceeds it."""
        art = HandoffArtifact(summary="C" * 3000, verdict="fail", files_changed=["x.py"], notes="n")
        for budget in (2000, 500, 100, 50):
            compiled = _ctx.compile_artifact(art, budget_tokens=budget)
            assert compiled.tokens <= budget

    def test_near_zero_budget_still_bounded_and_deterministic(self) -> None:
        """A budget too small to even fit the truncation marker (documented,
        pragmatic compromise R-7's own zero-budget case already accepted --
        you cannot say "N bytes omitted" in fewer bytes than the sentence
        itself needs) still produces a real, marked, deterministic result --
        never a silent "no truncation happened", and never a crash."""
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
