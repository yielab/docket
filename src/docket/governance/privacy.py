"""Named privacy classes and levels for what a trace export may share beyond bare
structure (ADR 0015). Pure data plus two lookups -- imports only ``kernel``
so both ``observability/spans.py`` and ``observability/exporter.py`` can depend on it without a cycle."""

from __future__ import annotations

from collections.abc import Sequence

from docket.kernel.errors import InvalidInput

# Every content class an exported span can carry beyond structure, in the order ADR 0015's
# table lists them. "structure" itself is not a member here: it is always sent and is never
# named on an exporter document.
CONTENT_CLASSES: tuple[str, ...] = (
    "toolArguments",
    "errors",
    "toolResults",
    "completions",
    "prompts",
    "instructions",
)

# Every attribute a handler can emit that is NOT bare structure, mapped to its content class.
# An attribute absent from this table is structure -- always sent, never gated. The export
# allowlist (`observability/spans.py`) enforces it, and `describe` lists it, so this is the one
# copy. Its order within a class is the order `describe` lists them in.
ATTRIBUTE_CLASSES: dict[str, str] = {
    "gen_ai.tool.call.arguments": "toolArguments",
    "docket.approval.action": "toolArguments",
    "docket.error.message": "errors",
    "gen_ai.tool.call.result": "toolResults",
    "gen_ai.output.messages": "completions",
    "gen_ai.system_instructions": "instructions",
    "docket.session.input": "prompts",
    "docket.escalation.prompt": "prompts",
    "docket.escalation.answer": "prompts",
    "docket.session.output": "completions",
}

# An attribute whose content mixes classes per message part (ADR 0015 §2 rule 3): it is gated
# part by part at projection, so it has no single class in `ATTRIBUTE_CLASSES`. `describe` still
# lists it under the class its parts can carry.
MIXED_ATTRIBUTES: dict[str, str] = {
    "gen_ai.input.messages": "prompts",
}

_ACTIONS: frozenset[str] = frozenset({"toolArguments", "errors"})
_CONVERSATION: frozenset[str] = _ACTIONS | frozenset({"toolResults", "completions", "prompts"})
_FULL: frozenset[str] = _CONVERSATION | frozenset({"instructions"})

# A level is a named, monotonic set of classes -- minimal ⊂ actions ⊂ conversation ⊂ full.
LEVELS: dict[str, frozenset[str]] = {
    "minimal": frozenset(),
    "actions": _ACTIONS,
    "conversation": _CONVERSATION,
    "full": _FULL,
}


def resolve(privacy: str | None, share: Sequence[str] | None) -> tuple[str, frozenset[str]]:
    """Resolve an exporter's ``privacy:`` level or its explicit ``share:`` list to
    ``(label, classes)`` -- neither given resolves to ``minimal``, and ``share`` returns
    the level name it happens to equal, or ``"custom"``. Raises ``ValueError`` on a bad input."""
    if privacy is not None and share is not None:
        raise InvalidInput("'privacy' and 'share' are mutually exclusive")
    if privacy is not None:
        if privacy not in LEVELS:
            valid = ", ".join(LEVELS)
            raise InvalidInput(f"'{privacy}' is not a known privacy level (valid: {valid})")
        return privacy, LEVELS[privacy]
    if share is not None:
        classes = frozenset(share)
        for cls in classes:
            if cls not in CONTENT_CLASSES:
                valid = ", ".join(CONTENT_CLASSES)
                raise InvalidInput(f"'{cls}' is not a known privacy class (valid: {valid})")
        for label, level_classes in LEVELS.items():
            if level_classes == classes:
                return label, classes
        return "custom", classes
    return "minimal", LEVELS["minimal"]


def describe(classes: frozenset[str]) -> list[tuple[str, bool, tuple[str, ...]]]:
    """One ``(class, granted, attribute_names)`` tuple per content class, in
    ``CONTENT_CLASSES`` order, for a CLI's "leaves this host" listing."""
    return [(cls, cls in classes, _attributes_of(cls)) for cls in CONTENT_CLASSES]


def _attributes_of(cls: str) -> tuple[str, ...]:
    """The mixed attributes first, then the gated ones, both in table order, for one class."""
    mixed = tuple(attr for attr, owner in MIXED_ATTRIBUTES.items() if owner == cls)
    return mixed + tuple(attr for attr, owner in ATTRIBUTE_CLASSES.items() if owner == cls)
