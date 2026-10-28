"""Role archetypes: versioned, declarative role definitions.

A role archetype is data, not code: name, scope, model class, SOUL/AGENTS prose
templates, a gate contract, a tool profile, and an enforced tool
denylist. `teams/pod.py` resolves pod roles against this registry instead of a
hardcoded 4-tuple, so a new role is data, never a hardcoded string in
`teams/pod.py`/`interfaces/cli/commands/pod.py`.

`tool_profile` is prose -- descriptive, never enforced (a real gap: a Reviewer
was once *told* "read-only" in SOUL.md but handed the full tool registry
anyway). `denied_tools` closes that gap as data: built-in tool names a role
may never call. `registry_for_role` is the sole consumer -- it removes exactly
those names via `ToolRegistry.without()`, called once per turn by
`agent/loop.py` before advertising tools or dispatching a call. No caller
ever branches on a role's name.

Built-in archetypes (`BUILTIN_ARCHETYPES`) reproduce today's four pod roles --
lead, implementer, reviewer, tester (golden-tested; see
`tests/integration/test_archetypes.py`). `STARTER_ARCHETYPES` ships six more:
researcher, analyst, writer, critic, operator, monitor.

`model_class` (cheap|strong) slots into the role->model policy
(`teams/model_selection.py`): an archetype's model row is its own name; a
pod-scoped archetype with no row resolves through its own `model_class`
against the live rank anchors instead.

`token_budget` is the role's context-compiler budget -- how many approximate
tokens of prior-hop carryover `agent/context.py` may thread into that role's
hop prompt. It lives on the archetype, not a second registry, so identity and
resource budget cannot drift apart; defaults to 6000 when unset.

A pod's own archetypes overlay the built-ins through `<pod>/config/roles.json`,
tolerant on load (a malformed entry is skipped, never crashes a live fleet;
`docket pod validate` explains why). The authoring format is a standalone YAML
file (`docket pod update <file.yaml>`), merged into that JSON overlay. Built-in/starter archetypes stay
Python literals here, matching the project's convention of generating
workspace prose inline rather than loading shipped template files.

See specs/functional/role-archetypes.spec.md for the full schema (closed vs.
open fields), the built-in/starter tables, and the user-overlay contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docket.agent.tools.registry import ToolKind
from docket.kernel.errors import CanonicalFormRefused
from docket.kernel.home import current_home
from docket.platform import mkdir_private, read_json, read_modify_write
from docket.teams.builtin_roles import (
    _STARTER_AGENTS_TEMPLATE,
    BUILTIN_ARCHETYPES,
    STARTER_ARCHETYPES,
)
from docket.teams.role_schema import (
    MODEL_CLASSES,
    ArchetypeError,
    RoleArchetype,
    from_wire,
    render,
)

# Keys only the canonical wire form carries, each with the short-form key to write instead: a role
# file that has one is refused (the canonical form is the in-memory model and the persisted
# `roles.json`, never an authored file).
_ROLE_CANONICAL_ONLY_KEYS: dict[str, str] = {
    "modelClass": "model",
    "deniedTools": "cannot",
    "gateContract": "verdict, verify or approval",
    "soulTemplate": "instructions",
    "agentsTemplate": "instructions (a `## AGENTS` heading splits it)",
}
_AGENTS_HEADING_RE = re.compile(r"(?m)^## AGENTS[ \t]*$\n?")


@dataclass(frozen=True)
class ArchetypeRegistry:
    """Built-ins + starter library + the pod overlay, merged (the pod wins by name).
    ``project`` records which pod's overlay this was resolved with, so ``source_of``
    can report ``pod:<project>``."""

    archetypes: dict[str, RoleArchetype] = field(default_factory=dict)
    project: str = ""

    def get(self, name: str) -> RoleArchetype | None:
        return self.archetypes.get(name)

    def __contains__(self, name: object) -> bool:
        return name in self.archetypes

    def role_names(self) -> tuple[str, ...]:
        return tuple(self.archetypes.keys())

    def items(self) -> list[tuple[str, RoleArchetype]]:
        return list(self.archetypes.items())

    def source_of(self, name: str) -> str:
        """'built-in' | 'starter' | 'pod:<project>' | '' (unknown) -- for
        `docket pod roles`. A role the pod overlay defines is reported as the pod's,
        even when it shadows a built-in or starter name."""
        if name not in self.archetypes:
            return ""
        if self.project:
            raw_pod = _read_overlay_raw(_pod_roles_file(self.project))
            if name in raw_pod.get("roles", {}):
                return f"pod:{self.project}"
        if name in BUILTIN_ARCHETYPES:
            return "built-in"
        if name in STARTER_ARCHETYPES:
            return "starter"
        return ""


def _pod_roles_file(project: str) -> Path:
    """The role overlay this ``project``'s pod resolves above the built-ins --
    ``pod_config_dir(project)/roles.json``, shape ``{"roles": {name: archetype}}``."""
    return current_home().pod_config_dir(project) / "roles.json"


def _read_overlay_raw(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return read_json(path)
    except Exception:
        return {}


def _overlay_problems(path: Path) -> list[tuple[str, str]]:
    """Return ``(role, reason)`` pairs for a malformed overlay entry at ``path`` (the
    file path itself for an unreadable file)."""
    if not path.exists():
        return []
    try:
        raw = read_json(path)
    except Exception as exc:
        return [(str(path), f"unreadable/malformed: {exc}")]
    roles = raw.get("roles", {})
    if not isinstance(roles, dict):
        return [(str(path), "'roles' is not an object")]
    problems: list[tuple[str, str]] = []
    for name, doc in roles.items():
        try:
            from_wire(str(name), doc)
        except ArchetypeError as exc:
            problems.append((str(name), str(exc)))
    return problems


def load_registry(project: str = "") -> ArchetypeRegistry:
    """Built-ins + starter library, overlaid -- when *project* is given -- by that pod's own
    overlay (nearest wins: pod > starter > built-in). Not cached; a malformed entry in the
    overlay is skipped."""
    archetypes: dict[str, RoleArchetype] = dict(BUILTIN_ARCHETYPES)
    archetypes.update(STARTER_ARCHETYPES)

    if project:
        for name, doc in _read_overlay_raw(_pod_roles_file(project)).get("roles", {}).items():
            try:
                archetypes[name] = from_wire(name, doc)
            except ArchetypeError:
                continue

    return ArchetypeRegistry(archetypes, project=project)


def find_overlay_problems(project: str) -> list[tuple[str, str]]:
    """Return ``(role, reason)`` pairs for a malformed entry in *project*'s overlay that
    ``load_registry`` silently skips -- for ``docket setup --fix``. Read-only."""
    return _overlay_problems(_pod_roles_file(project))


# The capability each built-in tool name represents. `registry_for_role` maps a
# role's `denied_tools` through this to decide which *kinds* that role may not
# hold, so a capability denial survives arriving under an unfamiliar name (an
# MCP-adapted tool is namespaced `mcp__<server>__<tool>`, which no denylist can
# spell out in advance).
#
# Deliberately a static map rather than a lookup into the registry being
# narrowed. Deriving the kind from `base` would make the denial conditional on
# the denied built-in still being *present* there — so a caller that narrowed
# the registry first (`DocketDriver.registry_factory` exists precisely to inject
# a narrower tool set) would silently stop deriving `write`, and a Reviewer
# would regain a write-capable MCP tool. The denial must depend only on the
# role's own data, never on what the incoming registry happens to contain.
#
# `test_role_tools_and_identity.py` pins this against `builtin_registry()` so
# the two cannot drift.
BUILTIN_TOOL_KINDS: dict[str, ToolKind] = {
    "read": "read",
    "glob": "read",
    "grep": "read",
    "fetch": "read",
    "skill": "read",
    "consult": "read",
    "write": "write",
    "edit": "write",
    "bash": "exec",
}


def validate_archetype_dict(name: str, doc: dict[str, Any]) -> list[str]:
    """Validate a candidate archetype definition without raising. Returns a list of
    human-readable error strings (empty = valid). Used by `docket pod validate` and `docket pod update`
    to give a full error report instead of stopping at the first problem."""
    errors: list[str] = []
    try:
        arch = from_wire(name, doc)
    except ArchetypeError as exc:
        return [str(exc)]

    sample_variables = {
        "project": "sample-project",
        "role": arch.name,
        "memberId": f"sample-project-{arch.name}",
        "sessionKey": "agent:sample-project:default",
        "objective": "sample objective",
        "codebase": "",
        "codebaseOrConfigured": "(no codebase configured)",
        "codebaseOrIt": "it",
        "stack": "",
        "workDir": "/tmp/sample-project",
        "requiredStartupFile": "WORKFLOW_AUTO.md",
    }
    try:
        render(arch.soul_template, sample_variables)
    except ArchetypeError as exc:
        errors.append(f"soulTemplate: {exc}")
    try:
        render(arch.agents_template, sample_variables)
    except ArchetypeError as exc:
        errors.append(f"agentsTemplate: {exc}")
    return errors


def parse_yaml_file(path: str) -> dict[str, Any]:
    """Parse a standalone archetype YAML file (the `docket pod update <file>` input)."""
    try:
        import yaml as _yaml  # type: ignore[import-untyped]
    except ImportError:
        raise ArchetypeError("PyYAML not installed — run: pip install pyyaml") from None
    from pathlib import Path as _Path

    p = _Path(path)
    if not p.is_file():
        raise ArchetypeError(f"file not found: {path}")
    try:
        doc = _yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ArchetypeError(f"YAML parse error: {exc}") from exc
    if not isinstance(doc, dict):
        raise ArchetypeError(f"archetype file must be a mapping (got {type(doc).__name__})")
    return doc


def _split_instructions_markdown(text: str) -> tuple[str, str | None]:
    """Split on an optional literal ``## AGENTS`` heading line into (soulTemplate,
    agentsTemplate); `agentsTemplate` is `None` when the heading is absent -- see
    role-archetypes.spec.md ("Wire format")."""
    match = _AGENTS_HEADING_RE.search(text)
    if match is None:
        return text.rstrip("\n") + "\n", None
    soul = text[: match.start()].rstrip("\n") + "\n"
    agents = text[match.end() :].lstrip("\n")
    return soul, agents


def normalize_role(short: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    """Turn a short-form role document into the canonical wire dict `from_wire` accepts;
    reads the `instructions` Markdown file (default ``<name>.md``) against *base_dir*.
    See role-archetypes.spec.md ("Wire format") for the full field mapping."""
    if not isinstance(short, dict):
        raise ArchetypeError("role definition must be a mapping")

    doc = dict(short)
    kind = doc.pop("kind", None)
    if kind is not None and kind != "role":
        raise ArchetypeError(f"expected kind: role, got kind: {kind!r}")

    name = str(doc.get("name", ""))
    canonical: dict[str, Any] = {"name": name}

    if "description" in doc:
        canonical["description"] = doc.pop("description")

    if "model" in doc:
        model = doc.pop("model")
        if model not in MODEL_CLASSES:
            raise ArchetypeError(
                f"archetype {name!r}: model must be one of {sorted(MODEL_CLASSES)} "
                f"(got {model!r}); to run one hop on a specific model, set `model:` on its pipeline step"
            )
        canonical["modelClass"] = model

    cannot = [str(tool) for tool in doc.pop("cannot", [])]
    canonical["deniedTools"] = cannot

    gate_keys = [key for key in ("verdict", "verify", "approval") if key in doc]
    if len(gate_keys) > 1:
        raise ArchetypeError(
            f"archetype {name!r}: exactly one of verdict/verify/approval may be set "
            f"(got {', '.join(gate_keys)})"
        )
    if "verdict" in doc:
        regexes = [str(marker) for marker in doc.pop("verdict")]
        canonical["gateContract"] = {"kind": "verdict", "regexes": regexes}
    elif "verify" in doc:
        doc.pop("verify")
        canonical["gateContract"] = {"kind": "mechanical"}
    elif "approval" in doc:
        doc.pop("approval")
        canonical["gateContract"] = {"kind": "approval"}
    else:
        canonical["gateContract"] = {"kind": "none"}

    instructions = doc.pop("instructions", f"{name}.md")
    md_path = base_dir / instructions
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ArchetypeError(
            f"archetype {name!r}: cannot read instructions file {md_path}: {exc}"
        ) from exc
    soul, agents = _split_instructions_markdown(text)
    canonical["soulTemplate"] = soul
    canonical["agentsTemplate"] = agents if agents is not None else _STARTER_AGENTS_TEMPLATE

    for key in ("scope", "version", "tokenBudget", "toolProfile", "hopInstruction"):
        if key in doc:
            canonical[key] = doc.pop(key)
    canonical.setdefault("scope", "pod")
    canonical.setdefault("version", 1)
    canonical.setdefault("tokenBudget", 6000)

    unknown = sorted(set(doc) - {"name"})
    if unknown:
        raise ArchetypeError(
            f"archetype {name!r}: unknown key(s) {', '.join(repr(k) for k in unknown)}"
        )

    return canonical


def to_short_role(arch: RoleArchetype) -> tuple[dict[str, Any], str]:
    """Inverse of `normalize_role`: the short-form document and its paired instructions
    Markdown text, the shape `teams.apply.plan._export_roles` writes as `<name>.yaml`/
    `<name>.md`."""
    doc: dict[str, Any] = {"kind": "role", "name": arch.name}
    if arch.description:
        doc["description"] = arch.description
    doc["model"] = arch.model_class
    if arch.denied_tools:
        doc["cannot"] = list(arch.denied_tools)
    gate = arch.gate_contract
    if gate.kind == "verdict":
        doc["verdict"] = list(gate.regexes)
    elif gate.kind == "mechanical":
        doc["verify"] = True
    elif gate.kind == "approval":
        doc["approval"] = True
    doc["instructions"] = f"{arch.name}.md"
    if arch.scope != "pod":
        doc["scope"] = arch.scope
    if arch.version != 1:
        doc["version"] = arch.version
    if arch.token_budget != 6000:
        doc["tokenBudget"] = arch.token_budget
    if arch.tool_profile:
        doc["toolProfile"] = arch.tool_profile
    if arch.hop_instruction:
        doc["hopInstruction"] = arch.hop_instruction

    soul = arch.soul_template.rstrip("\n") + "\n"
    if arch.agents_template == _STARTER_AGENTS_TEMPLATE:
        markdown = soul
    else:
        markdown = f"{soul}\n## AGENTS\n\n{arch.agents_template}"
    return doc, markdown


def canonical_key_refusal(doc: dict[str, Any]) -> str:
    """The message refusing a canonical key in an authored role, naming the short-form key to
    write instead; ``""`` when *doc* carries none."""
    keys = [key for key in _ROLE_CANONICAL_ONLY_KEYS if key in doc]
    if not keys:
        return ""
    return "a role is written in the short form; " + "; ".join(
        f"replace `{key}` with `{_ROLE_CANONICAL_ONLY_KEYS[key]}`" for key in keys
    )


class CanonicalRoleRefused(ArchetypeError, CanonicalFormRefused):
    """A role file carries a canonical-only key."""


def load_role_file(path: str) -> dict[str, Any]:
    """Parse a role YAML file written in the short form into the canonical wire dict `from_wire`
    accepts. `kind: role` is accepted and stripped; a canonical key is refused, naming the
    short-form key to use."""
    doc = parse_yaml_file(path)
    refusal = canonical_key_refusal(doc)
    if refusal:
        raise CanonicalRoleRefused(f"{path}: {refusal}")
    return normalize_role(doc, Path(path).parent)


def add_user_archetype(doc: dict[str, Any], project: str) -> RoleArchetype:
    """Validate `doc` and merge it into *project*'s own overlay. `doc` must carry a
    top-level `name`; naming an existing archetype overrides it."""
    name = str(doc.get("name", "")).strip()
    if not name:
        raise ArchetypeError("archetype definition must have a top-level 'name'")
    arch = from_wire(name, doc)  # raises ArchetypeError on any invalid field

    path = _pod_roles_file(project)

    def _fn(current: dict[str, Any]) -> dict[str, Any]:
        current.setdefault("roles", {})[name] = arch.to_wire()
        return current

    # path.parent is pod_config_dir(project); every directory this creates is 0700.
    mkdir_private(path.parent)
    read_modify_write(path, _fn)
    return arch
