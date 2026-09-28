"""Named privacy classes and levels for what a trace export may share beyond bare
structure (ADR 0015). Pure data plus two lookups -- imports nothing from ``core/``
so both ``core/telemetry.py`` and ``core/exporter.py`` can depend on it without a cycle."""

from __future__ import annotations

from collections.abc import Sequence

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

# The illustrative attribute names ADR 0015 §1's table lists per class -- for CLI display
# only (`describe`). `core/telemetry.py::ATTRIBUTE_CLASSES` is the real enforcement table;
# this module never imports it, so the two are kept in sync by hand against the same ADR.
_CLASS_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    "toolArguments": ("gen_ai.tool.call.arguments", "docket.approval.action"),
    "errors": ("docket.error.message",),
    "toolResults": ("gen_ai.tool.call.result",),
    "completions": ("gen_ai.output.messages",),
    "prompts": ("gen_ai.input.messages",),
    "instructions": ("gen_ai.system_instructions",),
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
        raise ValueError("'privacy' and 'share' are mutually exclusive")
    if privacy is not None:
        if privacy not in LEVELS:
            valid = ", ".join(LEVELS)
            raise ValueError(f"'{privacy}' is not a known privacy level (valid: {valid})")
        return privacy, LEVELS[privacy]
    if share is not None:
        classes = frozenset(share)
        for cls in classes:
            if cls not in CONTENT_CLASSES:
                valid = ", ".join(CONTENT_CLASSES)
                raise ValueError(f"'{cls}' is not a known privacy class (valid: {valid})")
        for label, level_classes in LEVELS.items():
            if level_classes == classes:
                return label, classes
        return "custom", classes
    return "minimal", LEVELS["minimal"]


def describe(classes: frozenset[str]) -> list[tuple[str, bool, tuple[str, ...]]]:
    """One ``(class, granted, attribute_names)`` tuple per content class, in
    ``CONTENT_CLASSES`` order, for a CLI's "leaves this host" listing."""
    return [(cls, cls in classes, _CLASS_ATTRIBUTES[cls]) for cls in CONTENT_CLASSES]
