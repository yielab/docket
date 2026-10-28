from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from docket.kernel.errors import InvalidInput
from docket.teams import prompts as _prompts

SCOPES: frozenset[str] = frozenset({"pod"})
MODEL_CLASSES: frozenset[str] = frozenset({"cheap", "strong"})
GATE_KINDS: frozenset[str] = frozenset({"none", "verdict", "mechanical", "approval"})

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_FLOOR_RE = re.compile(r"^(identity|task|hop)/[a-z][a-z0-9-]*$")


class ArchetypeError(InvalidInput):
    """Invalid archetype definition, reference, or template."""


@dataclass(frozen=True)
class GateContract:
    """Closed typed union over the four gate-contract kinds; `regexes` applies only to
    `kind == "verdict"` (e.g. reviewer APPROVE/REQUEST-CHANGES, tester PASS/FAIL). Real,
    consumed data: `pipeline.domain.plan.resolve_gate` falls back to it when a step omits its own."""

    kind: str
    regexes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in GATE_KINDS:
            raise ArchetypeError(
                f"unknown gate contract kind {self.kind!r}; valid: {sorted(GATE_KINDS)}"
            )
        for pattern in self.regexes:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ArchetypeError(
                    f"gate contract regex {pattern!r} does not compile: {exc}"
                ) from exc

    def to_wire(self) -> dict[str, Any]:
        doc: dict[str, Any] = {"kind": self.kind}
        if self.regexes:
            doc["regexes"] = list(self.regexes)
        return doc


@dataclass(frozen=True)
class RoleArchetype:
    """A versioned, declarative role definition. Field names below are Python
    (snake_case); the wire/YAML format uses camelCase (`modelClass`, `soulTemplate`,
    `agentsTemplate`, `gateContract`, `toolProfile`) — see `from_wire`/`to_wire`."""

    name: str
    version: int
    scope: str  # closed: "pod"
    model_class: str  # closed: "cheap" | "strong"
    soul_template: str  # open prose; $-style variables, see `render`
    agents_template: str  # open prose; $-style variables, see `render`
    gate_contract: GateContract  # closed kind, see GateContract
    tool_profile: str  # open prose (not enforced; descriptive only)
    description: str = ""  # open one-line prose, shown by `docket pod roles`
    # This role's context-compiler token budget — see
    # the module docstring's "token_budget" paragraph and `agent/context.py`.
    token_budget: int = 6000
    # Built-in tool names this role may never call —
    # see the module docstring's "Per-role tool sets" section. Open (like
    # `tool_profile`), not validated against the live tool registry: a name
    # that does not exist in a given registry is simply a no-op removal for
    # `ToolRegistry.without()`. Empty (the default) means "no narrower than
    # whatever registry the caller hands in" — today's behavior, preserved
    # for any archetype that does not opt in.
    denied_tools: tuple[str, ...] = ()
    # This role's own hop-message instruction footer (see
    # `resolve_hop_instruction` below and `hops/application/compose.py`'s hop-message
    # builder). Open prose, like `tool_profile`/`description` — "" (the
    # default) means "no declared instruction", not "no instruction at all":
    # a gated role still gets one generated from `gate_contract`.
    hop_instruction: str = ""
    # Prompts (`<layer>/<name>`) whose tests a model must not fail to run this role
    # (model-profiles.spec.md, "Prompt variants and the floor"). Empty means no floor.
    floor: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or not _NAME_RE.match(self.name):
            raise ArchetypeError(
                f"invalid archetype name {self.name!r} "
                "(lowercase letters/digits/hyphens, starting with a letter)"
            )
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ArchetypeError(f"archetype {self.name!r}: version must be a positive integer")
        if self.scope not in SCOPES:
            raise ArchetypeError(
                f"archetype {self.name!r}: unknown scope {self.scope!r}; valid: {sorted(SCOPES)}"
            )
        if self.model_class not in MODEL_CLASSES:
            raise ArchetypeError(
                f"archetype {self.name!r}: unknown modelClass {self.model_class!r}; "
                f"valid: {sorted(MODEL_CLASSES)}"
            )
        if not self.soul_template.strip():
            raise ArchetypeError(f"archetype {self.name!r}: soulTemplate must not be blank")
        if not self.agents_template.strip():
            raise ArchetypeError(f"archetype {self.name!r}: agentsTemplate must not be blank")
        if (
            not isinstance(self.token_budget, int)
            or isinstance(self.token_budget, bool)
            or self.token_budget <= 0
        ):
            raise ArchetypeError(f"archetype {self.name!r}: tokenBudget must be a positive integer")
        for ref in self.floor:
            if not _FLOOR_RE.match(ref):
                raise ArchetypeError(
                    f"archetype {self.name!r}: floor entry {ref!r} must be <layer>/<name> "
                    "with layer identity, task or hop"
                )

    def to_wire(self) -> dict[str, Any]:
        """Serialize to the camelCase wire format (`docket pod roles`, overlay persistence)."""
        doc: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
            "scope": self.scope,
            "modelClass": self.model_class,
            "soulTemplate": self.soul_template,
            "agentsTemplate": self.agents_template,
            "gateContract": self.gate_contract.to_wire(),
            "toolProfile": self.tool_profile,
            "tokenBudget": self.token_budget,
        }
        if self.description:
            doc["description"] = self.description
        if self.denied_tools:
            doc["deniedTools"] = list(self.denied_tools)
        if self.hop_instruction:
            doc["hopInstruction"] = self.hop_instruction
        if self.floor:
            doc["floor"] = list(self.floor)
        return doc


def from_wire(name: str, doc: dict[str, Any]) -> RoleArchetype:
    """Parse one archetype from its camelCase wire form (overlay JSON or a user YAML file).
    Raises `ArchetypeError` on any missing/invalid field."""
    if not isinstance(doc, dict):
        raise ArchetypeError(f"archetype {name!r}: definition must be a mapping")

    doc_kind = doc.get("kind")
    if doc_kind is not None and doc_kind != "role":
        raise ArchetypeError(f"archetype {name!r}: expected kind: role, got kind: {doc_kind!r}")

    if "policyRole" in doc:
        raise ArchetypeError(f"archetype {name!r}: unknown key 'policyRole'")

    doc_name = doc.get("name", name)
    if doc_name != name:
        raise ArchetypeError(
            f"archetype key {name!r} does not match its own name field {doc_name!r}"
        )

    gate_doc = doc.get("gateContract", {})
    if not isinstance(gate_doc, dict):
        raise ArchetypeError(f"archetype {name!r}: gateContract must be a mapping")
    gate = GateContract(
        kind=str(gate_doc.get("kind", "none")),
        regexes=tuple(str(r) for r in gate_doc.get("regexes", [])),
    )

    try:
        version = int(doc.get("version", 1))
    except (TypeError, ValueError) as exc:
        raise ArchetypeError(f"archetype {name!r}: version must be an integer") from exc

    try:
        # 6000 = RoleArchetype.token_budget's own default — a doc that never
        # set one still parses instead of crashing (see the module docstring's "token_budget" paragraph).
        token_budget = int(doc.get("tokenBudget", 6000))
    except (TypeError, ValueError) as exc:
        raise ArchetypeError(f"archetype {name!r}: tokenBudget must be an integer") from exc

    return RoleArchetype(
        name=name,
        version=version,
        scope=str(doc.get("scope", "")),
        model_class=str(doc.get("modelClass", "")),
        soul_template=str(doc.get("soulTemplate", "")),
        agents_template=str(doc.get("agentsTemplate", "")),
        gate_contract=gate,
        tool_profile=str(doc.get("toolProfile", "")),
        description=str(doc.get("description", "")),
        token_budget=token_budget,
        denied_tools=tuple(str(t) for t in doc.get("deniedTools", [])),
        hop_instruction=str(doc.get("hopInstruction", "")),
        floor=tuple(str(ref) for ref in doc.get("floor", [])),
    )


def resolve_hop_instruction(archetype: RoleArchetype) -> str:
    """*archetype*'s own `hop_instruction` if declared, else one generated from its
    `gate_contract` (verdict/mechanical/approval); a `none`-kind gate generates none. See
    specs/functional/role-archetypes.spec.md ("Hop instructions")."""
    # `implementer`/`reviewer`/`tester` never reach this: `hops/application/compose.py`'s hop-message
    # builder keeps their own shipped text unconditionally. `lead` DOES reach this --
    # its built-in `hop_instruction` is the shipped `hop/lead` prompt, so this returns
    # it verbatim absent an overlay.
    if archetype.hop_instruction:
        return _prompts.role_prompt(
            archetype.name, "hop", archetype.hop_instruction, archetype.version
        ).text
    gc = archetype.gate_contract
    if gc.kind == "verdict" and gc.regexes:
        markers = " or ".join(f"`{m}`" for m in gc.regexes)
        return (
            f"The LAST line of your FINAL message must be exactly {markers}, "
            "with nothing else on that line. Reasons go above it."
        )
    if gc.kind == "mechanical":
        return "Complete the task; your work is verified mechanically before the pipeline advances."
    if gc.kind == "approval":
        return "Complete the task; a human must approve before the pipeline advances."
    return ""


def render(template: str, variables: dict[str, str]) -> str:
    """Substitute a `${var}`-style template against `variables` (strict, not
    `safe_substitute`): an unprovided variable is a real authoring bug, raised as
    `ArchetypeError` rather than silently writing a literal `${typo}`."""
    try:
        return _prompts.substitute(template, variables)
    except _prompts.PromptError as exc:
        raise ArchetypeError(exc.message) from exc
