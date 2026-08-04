"""Context compiler: fit a hop's prior-hop artifacts to a per-role token budget.

``core/dispatch.py``'s ``_hop_message`` calls this module, and only this
module, to truncate a hop's prompt — there is no second, layered truncation
mechanism anywhere else in the hop-composition path.

A prior hop further into the past gets a smaller share of the budget
(``hop_share``, a halving series denominated in tokens): each hop one step
further back gets half the share of the one before it, so the total content
carried forward across any number of prior hops never reaches the total
budget, while the most recent, most relevant hop is squeezed the least. Once
a hop's share is exceeded, ``compile_artifact`` sheds the artifact's own
less-valuable fields first, in ``HandoffArtifact.DROP_ORDER``'s declared
order (``notes`` -> ``diff_ref`` -> ``files_changed`` -> ``verdict``),
checking the budget after each drop and stopping the moment it fits.
``summary`` is never in ``DROP_ORDER`` — it is the artifact's minimum viable
content — so the worst case is an explicitly *marked* truncation of
``summary`` itself (``_truncate_summary``), never a silent drop and never an
empty section.

**No tokenizer dependency.** A new heavyweight dependency is out of scope
for this. ``estimate_tokens`` reuses the project's existing,
already-documented chars-per-token approximation
(``config.CONTEXT_BYTES_PER_TOKEN``, default 4 bytes/token — the same ratio
``cli/_agents.py``'s ``maintain check``/``maintain sessions`` already use for
their own context-size guards) rather than inventing a second,
independently-tunable ratio that could quietly drift from the first. This is
an honest approximation good enough to bound a prompt deterministically —
never claimed as an exact count, and never used to bill against.

Per-role budgets live on the role archetype itself
(``core/archetypes.py``'s ``RoleArchetype.token_budget``), not a second,
parallel registry — roles are declarative data for exactly this kind of
extension. ``budget_for_role`` resolves a role name against the live
archetype registry, falling back to ``DEFAULT_TOKEN_BUDGET`` for a role the
registry doesn't know (e.g. a hand-built test archetype that predates this
field, or a pipeline step targeting an unregistered role name).

This module is a pure leaf, the same shape as ``core/handoff.py``: no
filesystem I/O of its own beyond ``core/archetypes.py``'s existing registry
read, no subprocess, no import of ``core/dispatch.py``. ``core/dispatch.py``'s
``_hop_message`` is the one production caller — it composes the final hop
message (the task description, any rework note, then the recency-ordered
prior-hop carryover) from this module's ``compile_artifact``/``hop_share``,
and threads the result into its own ``_HopComposition`` trace record.

**Scope note:** ``_hop_message`` — the one call site this module wires into
— has no workspace input to give it (dispatch never reads the workspace
filesystem to build a hop's prompt), so this module does not accept or
invent one; adding an unused parameter ahead of a real caller would be
speculative generality. A future caller that needs workspace-aware
compilation extends this module then, with a real input to shape it around.
"""

from __future__ import annotations

from dataclasses import dataclass

import docket.config as cfg
from docket.core import archetypes as _arch
from docket.core.handoff import HandoffArtifact

#: Fallback token budget for a role with no archetype in the live registry,
#: or whose archetype resolves a non-positive ``token_budget`` (defensive —
#: ``RoleArchetype.__post_init__`` already rejects a non-positive
#: ``token_budget`` for anything built through ``from_wire``, but a
#: hand-built ``RoleArchetype`` in a test is not required to go through it).
DEFAULT_TOKEN_BUDGET = 6000

#: Visible marker used when ``summary`` itself must be truncated — the
#: consumer-facing proof that content was cut, never a silent shortening.
SUMMARY_TRUNCATION_MARKER = "\n[... summary truncated: {n} bytes omitted ...]\n"


def estimate_tokens(text: str) -> int:
    """Approximate *text*'s token count.

    ``len(text.encode("utf-8")) // config.CONTEXT_BYTES_PER_TOKEN`` — the
    same bytes-per-token approximation (default 4) ``cli/_agents.py``'s
    ``maintain check``/``maintain sessions`` already use for their own
    context-size guards. This is honestly an approximation, not a real count
    from the model's own tokenizer — good enough to bound a prompt
    deterministically, never used to bill against.
    """
    return len(text.encode("utf-8")) // cfg.CONTEXT_BYTES_PER_TOKEN


def budget_for_role(role: str) -> int:
    """The token budget the named role's archetype declares.

    Falls back to ``DEFAULT_TOKEN_BUDGET`` when *role* isn't in the live
    archetype registry (``core/archetypes.py.load_registry``), or resolves a
    non-positive ``token_budget``.
    """
    found = _arch.load_registry().get(role)
    if found is None or found.token_budget <= 0:
        return DEFAULT_TOKEN_BUDGET
    return found.token_budget


def hop_share(rank: int, total_budget: int) -> int:
    """One prior hop's slice of *total_budget*, by recency ``rank`` (0 = newest).

    A halving series (``total_budget >> (rank + 1)``): each hop one step
    further into the past gets half the share of the one before it, so the
    *total* carried forward across any number of prior hops never reaches
    ``total_budget`` (a partial geometric series, ratio 1/2) while the most
    recent, most relevant hop is squeezed the least.
    """
    return total_budget >> (rank + 1)


def _truncate_summary(summary: str, budget_tokens: int) -> tuple[str, bool]:
    """Truncate *summary* to fit *budget_tokens*, head + tail, an explicit marker.

    Only ever reached once every ``HandoffArtifact.DROP_ORDER`` field has
    already been shed and the bare ``summary`` alone still doesn't fit —
    ``summary`` is never dropped outright (see ``compile_artifact``), only
    truncated, and always visibly: the omitted middle is replaced with a
    ``[... summary truncated: N bytes omitted ...]`` marker recording exactly
    how many bytes were cut — never a silent cut.

    A *budget_tokens* of zero (or less) cannot even fit the marker itself;
    in that degenerate case the marker is still emitted in full (recording
    the entire input as omitted) rather than silently returning nothing —
    bounded and deterministic, not "no truncation happened."
    """
    max_bytes = max(budget_tokens, 0) * cfg.CONTEXT_BYTES_PER_TOKEN
    encoded = summary.encode("utf-8")
    if len(encoded) <= max_bytes:
        return summary, False

    # Reserve room for the marker using the *total* length as a safe upper
    # bound for its digit width — the real omitted count can only be
    # smaller, so the marker built from it below never ends up longer than
    # reserved.
    reserved = SUMMARY_TRUNCATION_MARKER.format(n=len(encoded)).encode("utf-8")
    remaining = max(max_bytes - len(reserved), 0)
    head_len = remaining // 2
    tail_len = remaining - head_len
    omitted = len(encoded) - head_len - tail_len
    marker = SUMMARY_TRUNCATION_MARKER.format(n=omitted)
    head = encoded[:head_len].decode("utf-8", errors="ignore")
    tail = encoded[len(encoded) - tail_len :].decode("utf-8", errors="ignore") if tail_len else ""
    return f"{head}{marker}{tail}", True


@dataclass(frozen=True)
class CompiledArtifact:
    """One prior hop's artifact, fit to a token budget — ``compile_artifact``'s result."""

    text: str
    budget_tokens: int
    tokens: int
    original_tokens: int
    dropped_fields: tuple[str, ...] = ()
    summary_truncated: bool = False

    @property
    def truncated(self) -> bool:
        """True if anything at all was shed or cut to make ``text`` fit."""
        return bool(self.dropped_fields) or self.summary_truncated


def compile_artifact(artifact: HandoffArtifact, budget_tokens: int) -> CompiledArtifact:
    """Fit *artifact*'s rendered text into *budget_tokens*.

    Deterministic, priority-ordered degradation, cheapest content lost first:

    1. If the artifact already renders within budget, return it unchanged —
       the common case (a small hop composes exactly as if there were no
       budget at all).
    2. Otherwise shed ``HandoffArtifact.DROP_ORDER`` fields one at a time
       (``notes``, then ``diff_ref``, then ``files_changed``, then
       ``verdict``), re-measuring after each drop and stopping the moment it
       fits. A field that is already empty (``notes`` is reserved but never
       populated by dispatch; ``files_changed``/``diff_ref`` are only
       populated for a successful Implementer hop, see `core/handoff.py`/
       `core/dispatch.py`) is skipped rather than reported as "dropped": there
       was nothing there to shed, so claiming otherwise in the trace would be
       dishonest. ``dropped_fields`` therefore only ever names a field that
       actually changed the rendered text.
    3. If it still doesn't fit with every droppable (and non-empty) field
       gone — only ``summary`` left — truncate ``summary`` itself via
       ``_truncate_summary``, with a visible marker. ``summary`` is never
       silently dropped: it is the one field ``DROP_ORDER`` deliberately
       excludes, so the worst case is an explicitly marked truncation, never
       an empty section.
    """
    rendered = artifact.render()
    original_tokens = estimate_tokens(rendered)
    if original_tokens <= budget_tokens:
        return CompiledArtifact(rendered, budget_tokens, original_tokens, original_tokens)

    current = artifact
    dropped: list[str] = []
    for field_name in HandoffArtifact.DROP_ORDER:
        if not getattr(current, field_name):
            continue  # already empty -- nothing to shed, nothing to report
        current = current.dropped(field_name)
        dropped.append(field_name)
        rendered = current.render()
        tokens = estimate_tokens(rendered)
        if tokens <= budget_tokens:
            return CompiledArtifact(
                rendered, budget_tokens, tokens, original_tokens, tuple(dropped)
            )

    truncated_summary, was_truncated = _truncate_summary(current.summary, budget_tokens)
    return CompiledArtifact(
        truncated_summary,
        budget_tokens,
        estimate_tokens(truncated_summary),
        original_tokens,
        tuple(dropped),
        was_truncated,
    )
