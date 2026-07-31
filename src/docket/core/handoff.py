"""Structured handoff artifacts exchanged between pipeline hops (ROADMAP Phase 16 W-5).

Before this card, ``core/dispatch.py``'s ``_hop_message`` composed the next hop's
prompt by concatenating each prior hop's *raw* text output, cropped only by
R-7's byte-budget cap (``_hop_carryover_budget``/``_truncate_carryover``). That
worked, but it left a downstream consumer nothing to reason about except an
opaque blob of text: no notion of which part of a hop's reply is a one-line
verdict, which is the file list a code change touched, or which fields are
safe to shed first once a token budget gets tight.

``HandoffArtifact`` is the typed replacement — exactly the shape this card was
asked to ship (``summary``, ``files_changed``, ``diff_ref``, ``verdict``,
``notes``), plus a declared drop order so a size-constrained consumer never
has to invent one. **This card gates Phase 17's C-1** (the context compiler):
the artifact shape is the deliverable, not how thoroughly every field is
populated today.

``core/dispatch.py`` attaches one to every ``HopResult`` (see that module's
docstring) and composes the next hop's message from ``HandoffArtifact.render()``
— never from a hop's raw output directly — then applies the *same* R-7
byte-budget cap to the rendered text that it always applied to raw output, so
the bounded-prompt guarantee is unchanged. The artifact is persisted alongside
its hop record so ``--resume`` recovers it exactly; a task queued before this
card has hops with no persisted ``artifact`` at all — ``from_legacy_output``
is the documented degrade path for that case (treat the old raw text as
``summary``, every other field at its default).

**What dispatch populates today, honestly:**

- ``summary`` — always the hop's full raw reply text. The information content
  is unchanged from before this card; only the container is now typed.
- ``verdict`` — the parsed gate marker (e.g. ``"approve"``, ``"fail"``) for a
  hop gated by a ``VerdictGate`` (Reviewer/Tester, or any W-8 verdict-gated
  archetype). ``None`` for every other hop: Lead, a ``MechanicalGate``- or
  ``ApprovalGate``-gated hop, or an unparseable verdict.
- ``files_changed`` / ``diff_ref`` — populated for an **Implementer** hop
  (ROADMAP Phase 16 follow-up W-5b) via a real git probe:
  ``core/dispatch.py``'s ``_implementer_diff_probe`` resolves the member's
  working tree the same way the mechanical verify gate does (worktree →
  shared codebase → the member's own workspace dir, via
  ``core.pod.resolve_member_cwd``) and, when that tree is a real git
  repository and a ``git`` binary is on ``PATH``, calls
  ``edges/adapters/system.py``'s ``git_changed_files``/``git_current_branch``.
  ``files_changed`` is the working tree's uncommitted changes (staged,
  unstaged, untracked — not a diff against a fixed base ref); ``diff_ref`` is
  the member's current branch name, a reference a caller can hand to
  ``git diff``/``git log`` against the pod's base branch. Both stay at their
  empty default for every non-Implementer hop, a ``workdir`` (non-codebase)
  pod, a workspace that is not a git repository, or a host with no ``git``
  binary — an honest degrade, never an exception, never a crash mid-dispatch.
- ``notes`` — free-form and **reserved**: the schema carries it (and
  ``DROP_ORDER`` accounts for it) so a future producer never needs a schema
  migration, but nothing in dispatch writes it today. Always ``""`` unless a
  caller builds an artifact by hand.

This module is deliberately pure — no filesystem I/O, no subprocess, no import
of ``core/dispatch.py`` — the same "leaf" shape as ``core/pipeline.py``.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field


class HandoffArtifact(BaseModel):
    """One hop's structured output, handed to the next hop instead of raw text.

    ``DROP_ORDER`` is the field-shedding order a size-constrained consumer
    (Phase 17's context compiler) should follow, least valuable first.
    ``summary`` is deliberately absent from it — it is the artifact's minimum
    viable content and is never dropped outright, only truncated (dispatch's
    existing byte-budget cap still applies to ``render()``'s output, the same
    way it always applied to a hop's raw text).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str
    files_changed: list[str] = Field(default_factory=list)
    diff_ref: str | None = None
    verdict: str | None = None
    #: Free-form and reserved (W-5b): the schema and DROP_ORDER account for it
    #: so a future producer needs no migration, but dispatch writes nothing
    #: here today — always "" unless a caller builds an artifact by hand.
    notes: str = ""

    #: Least-valuable-first shedding order for a token-budgeted consumer.
    DROP_ORDER: ClassVar[tuple[str, ...]] = ("notes", "diff_ref", "files_changed", "verdict")

    #: The "reset to empty" value for each droppable field — used by ``dropped()``.
    _EMPTY_VALUES: ClassVar[dict[str, Any]] = {
        "notes": "",
        "diff_ref": None,
        "files_changed": [],
        "verdict": None,
    }

    @classmethod
    def from_legacy_output(cls, output: str) -> HandoffArtifact:
        """Degrade a pre-artifact hop's raw text into an artifact.

        A task queued/persisted before this card has hops whose only recorded
        content is ``output`` — a plain string, no ``artifact`` key at all.
        ``core/dispatch.py``'s ``_hop_from_record`` calls this for exactly
        that case so ``--resume`` (and any in-memory replay) treats the old
        raw text as ``summary`` — the card's explicit backward-compatibility
        requirement. ``HopResult.__post_init__`` calls this same path for any
        hop constructed without an explicit artifact, so a hand-built
        ``HopResult`` (as many existing tests use) degrades identically.
        """
        return cls(summary=output)

    def render(self) -> str:
        """Deterministic text block for a hop's prompt.

        When only ``summary`` is set (every other field at its default — true
        for every hop today except a verdict-gated one), this returns exactly
        ``summary`` unchanged, so a hop with nothing else to report composes
        byte-identically to the pre-artifact raw-text behaviour. Extra
        fields, when present, are appended as their own labelled lines in a
        fixed, deterministic order — independent of which field actually
        holds content, so ``render()`` never reorders itself based on data.
        """
        lines = [self.summary]
        if self.verdict is not None:
            lines.append(f"Verdict: {self.verdict}")
        if self.files_changed:
            lines.append(f"Files changed: {', '.join(self.files_changed)}")
        if self.diff_ref is not None:
            lines.append(f"Diff ref: {self.diff_ref}")
        if self.notes:
            lines.append(f"Notes: {self.notes}")
        return "\n".join(lines)

    def dropped(self, field: str) -> HandoffArtifact:
        """Return a copy with *field* reset to empty (a budgeting consumer's helper).

        *field* must name one of ``DROP_ORDER``'s entries — ``summary`` can
        never be dropped this way (it is not in ``DROP_ORDER``); passing it,
        or any other unknown name, raises ``ValueError`` rather than silently
        discarding the artifact's one required field. Phase 17's C-1 is the
        intended caller: shed fields in ``DROP_ORDER`` order (calling this
        once per field) until the rendered artifact fits its token budget.
        """
        if field not in self._EMPTY_VALUES:
            raise ValueError(f"{field!r} is not a droppable HandoffArtifact field")
        return self.model_copy(update={field: self._EMPTY_VALUES[field]})
