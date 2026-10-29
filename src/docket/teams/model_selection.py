"""Model policy: registry loading, role→model resolution, validation, re-apply."""

from __future__ import annotations

import json
import re
from typing import Any, NamedTuple

from docket.kernel.errors import InvalidInput
from docket.kernel.home import current_home
from docket.models import catalog as _provider
from docket.platform import write_json
from docket.teams import builtin_roles as _builtin_roles
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod
from docket.teams import prompt_tests as _prompt_tests
from docket.teams import prompts as _prompts
from docket.teams import roles as _arch
from docket.teams.fleet import project_ids

ALL_ROLES: tuple[str, ...] = (
    "lead",
    "implementer",
    "reviewer",
    "tester",
    "researcher",
    "analyst",
    "writer",
    "critic",
    "operator",
    "monitor",
)

# cheap = high-volume / low reasoning; strong = reasoning-dense. The class of each of the ten
# named roles is its archetype's own `modelClass`.
ROLE_CLASS: dict[str, str] = {
    name: arch.model_class
    for name, arch in {
        **_builtin_roles.BUILTIN_ARCHETYPES,
        **_builtin_roles.STARTER_ARCHETYPES,
    }.items()
}

# The row a project agent that is not a pod member follows.
REPO_AGENT_ROLE = "implementer"

_MODEL_ID_RE = re.compile(r"^[a-z0-9_-]+/[A-Za-z0-9._:/-]+$")


def rank_anchors() -> dict[str, str]:
    """Seed values for each rank (shown by `docket setup model`), read from the `anthropic`
    provider's own preset -- NOT a runtime fallback chain. Raises ``DocumentError`` when that
    preset lacks an anchor."""
    return _provider.rank_anchors_of(_provider.load_catalog())


def presets() -> list[tuple[str, _provider.Preset]]:
    """Every ``(provider_name, Preset)`` pair the catalog carries, in catalog order (built-in
    documents load in filename order; a provider's own ``presets:`` list keeps its declared
    order) -- the source ``preset_table()``/``known_presets()`` derive from."""
    catalog = _provider.load_catalog()
    return [(name, preset) for name, spec in catalog.entries.items() for preset in spec.presets]


def is_local_provider(prefix: str) -> bool:
    """True for a provider prefix the catalog marks ``local: true`` -- a genuinely zero
    per-token cost (llama.cpp/LM Studio/vLLM/Ollama), never a fabricated non-zero figure."""
    spec = _provider.load_catalog().get(prefix)
    return bool(spec and spec.local)


def is_marketplace(prefix: str) -> bool:
    """True for a prefix the catalog marks ``marketplace: true``: its per-model pricing
    changes too often for a snapshot, so it reports "n/a (bring your own)" rather than a
    stale or invented number."""
    spec = _provider.load_catalog().get(prefix)
    return bool(spec and spec.marketplace)


def price_for(model: str) -> tuple[float, float, float, float] | None:
    """``(input, output, cacheRead, cacheWrite)`` USD-per-MTok for *model*, read from the
    catalog's own model row, or ``None`` when there is no priced row -- callers must not treat
    that as "$0" (see ``pricing_label``)."""
    provider, _, model_id = model.partition("/")
    spec = _provider.load_catalog().get(provider)
    if spec is None:
        return None
    row = next((r for r in spec.models if r.id == model_id), None)
    if row is None or row.price is None:
        return None
    return (row.price.input, row.price.output, row.price.cache_read, row.price.cache_write)


def prices_as_of(model: str) -> str:
    """The snapshot date of *model*'s provider, or ``""`` when the provider is unknown or
    carries no ``pricesAsOf`` (never priced, or entirely unpriced)."""
    provider, _, _model_id = model.partition("/")
    spec = _provider.load_catalog().get(provider)
    return spec.prices_as_of if spec else ""


def _preset_cost_label(provider_name: str, preset: _provider.Preset) -> str:
    """ "free"/"paid" for the presets listing -- free when the provider is a local endpoint or
    the preset's own standard rank prices at $0 (a stable free router); every other preset is a
    real paid route even where docket does not track its exact per-model price."""
    if is_local_provider(provider_name):
        return "free"
    standard_id = preset.ranks.get("standard", "")
    price = price_for(f"{provider_name}/{standard_id}") if standard_id else None
    return "free" if price == (0.0, 0.0, 0.0, 0.0) else "paid"


def preset_table() -> dict[str, dict[str, str]]:
    """Same shape as the old hand-kept preset table: preset name -> economy/standard/premium
    (full ``provider/model`` ids), ``key`` (the provider's first credential name, or ``""``),
    ``cost`` and ``note`` -- derived from the catalog instead of duplicated here."""
    catalog = _provider.load_catalog()
    table: dict[str, dict[str, str]] = {}
    for provider_name, preset in presets():
        spec = catalog.get(provider_name)
        if spec is None:
            continue
        key = spec.auth.credentials[0] if spec.auth.credentials else ""
        table[preset.name] = {
            "economy": f"{provider_name}/{preset.ranks.get('economy', '')}",
            "standard": f"{provider_name}/{preset.ranks.get('standard', '')}",
            "premium": f"{provider_name}/{preset.ranks.get('premium', '')}",
            "key": key,
            "cost": _preset_cost_label(provider_name, preset),
            "note": preset.note,
        }
    return table


def known_presets() -> tuple[str, ...]:
    """Every preset name the catalog carries, in catalog order -- the menu
    ``docket setup model preset`` validates against."""
    return tuple(preset.name for _provider_name, preset in presets())


def _init_role_models(tiers: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for role in ALL_ROLES:
        cls = ROLE_CLASS.get(role, "strong")
        result[role] = tiers["economy"] if cls == "cheap" else tiers["standard"]
    return result


def load_registry() -> tuple[dict[str, str], dict[str, str], str]:
    """Return (role_models, tiers, default_model) from docket-models.json.
    Falls back to built-in defaults on any read/parse error.

    ``tiers`` are registry-overridable via ``rankAnchors``, applied *before*
    role defaults are derived so an overridden anchor reshapes every
    cheap/strong-class role default too. Malformed entries (unknown anchor,
    bad model id) are silently ignored, like ``default``/``roles`` below.
    """
    tiers = dict(rank_anchors())
    default_model = current_home().default_model

    path = current_home().model_registry_file
    if not path.exists():
        return _init_role_models(tiers), tiers, default_model

    try:
        reg: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _init_role_models(tiers), tiers, default_model

    for anchor, m in reg.get("rankAnchors", {}).items():
        if anchor in tiers and isinstance(m, str) and _MODEL_ID_RE.match(m):
            tiers[anchor] = m

    if isinstance(reg.get("default"), str) and _MODEL_ID_RE.match(reg["default"]):
        default_model = reg["default"]

    role_models = _init_role_models(tiers)

    # Explicit per-role overrides win.
    for role, m in reg.get("roles", {}).items():
        if role in ROLE_CLASS and isinstance(m, str) and _MODEL_ID_RE.match(m):
            role_models[role] = m

    return role_models, tiers, default_model


def find_registry_problems() -> list[tuple[str, str]]:
    """Return ``(key, reason)`` pairs for a malformed ``docket-models.json`` entry that
    ``load_registry`` silently ignores -- for ``docket setup --fix``. *key* is the file path
    itself for an unreadable file, else a dotted ``rankAnchors.<x>``/``roles.<x>``/``default``."""
    path = current_home().model_registry_file
    if not path.exists():
        return []
    try:
        reg: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [(str(path), f"unreadable/malformed JSON: {exc}")]
    if not isinstance(reg, dict):
        return [(str(path), "not a JSON object")]

    problems: list[tuple[str, str]] = []

    raw_rank_anchors = reg.get("rankAnchors", {})
    if isinstance(raw_rank_anchors, dict):
        for anchor, m in raw_rank_anchors.items():
            if anchor not in ("economy", "standard", "premium"):
                problems.append((f"rankAnchors.{anchor}", "unknown rank anchor"))
            elif not (isinstance(m, str) and _MODEL_ID_RE.match(m)):
                problems.append((f"rankAnchors.{anchor}", f"not a valid model id: {m!r}"))
    else:
        problems.append(("rankAnchors", "'rankAnchors' is not an object"))

    default = reg.get("default")
    if default is not None and not (isinstance(default, str) and _MODEL_ID_RE.match(default)):
        problems.append(("default", f"not a valid model id: {default!r}"))

    roles = reg.get("roles", {})
    if isinstance(roles, dict):
        for role, m in roles.items():
            if role not in ROLE_CLASS:
                problems.append((f"roles.{role}", "unknown role"))
            elif not (isinstance(m, str) and _MODEL_ID_RE.match(m)):
                problems.append((f"roles.{role}", f"not a valid model id: {m!r}"))
    else:
        problems.append(("roles", "'roles' is not an object"))

    return problems


def resolve_role_model(
    role: str, role_models: dict[str, str] | None = None, *, project: str = ""
) -> str:
    """Return the effective model for a role (loads registry if not supplied).

    ``role`` may be a pod-scoped archetype name with no row of its own; it
    falls through to ``_resolve_via_archetype_class``, resolving via the
    archetype's ``modelClass`` against live rank anchors.
    """
    if role_models is None:
        role_models, _, _ = load_registry()
    if role in role_models:
        return role_models[role]
    return _resolve_via_archetype_class(role, project)


def _resolve_via_archetype_class(role: str, project: str = "") -> str:
    """Resolve a role outside ``ALL_ROLES`` via its archetype's modelClass, looked up in
    *project*'s registry; an unknown role falls back to the registry's own default model."""
    arch = _arch.load_registry(project).get(role)
    _, tiers, default_model = load_registry()
    if arch is None:
        return default_model
    return tiers["economy"] if arch.model_class == "cheap" else tiers["standard"]


def model_class_of(model: str) -> str | None:
    """The prompt class of *model*: ``cheap`` for the ``economy`` rank anchor, ``strong`` for the
    ``standard`` and ``premium`` anchors, ``None`` for any other model (never guessed from the id).
    See model-profiles.spec.md "Prompt variants and the floor" requirement 1."""
    _, tiers, _ = load_registry()
    if model == tiers["economy"]:
        return "cheap"
    return "strong" if model in (tiers["standard"], tiers["premium"]) else None


def floor_refusal(role: str, project: str, model: str) -> str | None:
    """Why *role* refuses *model*: it declares a ``floor`` prompt whose recorded test for *model*
    (on the prompt text *model*'s class resolves) is ``fail``; ``None`` when it does not. There is
    no fallback model. See model-profiles.spec.md "Prompt variants and the floor" requirement 4."""
    arch = _arch.load_registry(project).get(role)
    if arch is None:
        return None
    for ref in arch.floor:
        layer, _, name = ref.partition("/")
        try:
            loaded = _prompts.resolve_prompt(
                layer, name, project=project, model_class=model_class_of(model)
            )
        except _prompts.PromptError:
            continue
        found = _prompt_tests.recorded(model, loaded.sha256)
        if found is not None and found.get("result") == _prompt_tests.FAIL:
            return (
                f"model {model} failed the floor test of prompt {ref} "
                f"(sha256 {loaded.sha256[:12]}); run docket pod test {ref} --force after a fix, "
                "or change the role's model"
            )
    return None


def resolve_step_model(model: str) -> str:
    """Resolve a pipeline step's own ``model`` (pipeline-format.spec.md "Steps" Req. 10) to a
    literal ``provider/id`` for one hop. ``cheap``/``strong`` resolve against the live rank
    anchors (``economy``/``standard``); any other value is returned unchanged once its
    ``<provider>/...`` prefix is confirmed present in the provider catalog -- raises naming the
    provider otherwise, so a caller can refuse before any hop runs. See model-profiles.spec.md
    "Where a member's model comes from" requirement 3."""
    if model in ("cheap", "strong"):
        _, tiers, _ = load_registry()
        return tiers["economy"] if model == "cheap" else tiers["standard"]
    provider = model.split("/", 1)[0]
    if _provider.load_catalog().get(provider) is None:
        raise InvalidInput(f"unknown provider {provider!r} in step model {model!r}")
    return model


def role_why(role: str) -> str:
    """The one-line reason shown beside a role: its archetype's own description."""
    arch = _arch.load_registry().get(role)
    return arch.description if arch is not None else ""


def is_role(role: str) -> bool:
    return role in ROLE_CLASS


def agent_role(agent_id: str) -> str:
    """Policy role for an agent: its pod-member archetype name, else ``REPO_AGENT_ROLE``."""

    return _fleet.meta_get(agent_id, "role", "") or REPO_AGENT_ROLE


def validate_model(model: str) -> tuple[str, list[str]]:
    """Validate and canonicalise a model name. Returns (canonical_model,
    warnings); raises ValueError on hard failure."""
    warnings: list[str] = []

    # 1. Well-formed provider/model — accepted; warn if unpriced (never for a
    #    local endpoint, which is honestly priced at $0, not "unknown").
    if _MODEL_ID_RE.match(model):
        provider = model.split("/", 1)[0]
        if is_local_provider(provider):
            pass
        elif price_for(model) is None:
            if is_marketplace(provider):
                warnings.append(
                    f"Model '{model}' routes through a marketplace provider whose per-model "
                    "pricing changes often — docket does not track it; cost will show as "
                    "'n/a (bring your own)'."
                )
            else:
                warnings.append(
                    f"Model '{model}' is not in docket's pricing table — cost will show as n/a."
                )
        return model, warnings

    # 2. Malformed.
    role_models, _, _ = load_registry()
    lines = "\n".join(
        f"  {r:<12} {role_models.get(r, current_home().default_model)}" for r in ALL_ROLES
    )
    raise InvalidInput(
        f"Invalid model: '{model}'\n"
        "Use a full provider/model ID (e.g. anthropic/claude-sonnet-4-6).\n"
        f"Current role policy:\n{lines}\n"
        "Change a role's model: docket setup model set <role> <provider/model>"
    )


def pricing_label(model: str) -> str:
    """Return '$inp/$out' (per-M-token), '$0 (local)', or 'n/a' for a model.
    Never fabricates "$0.00" for unpriced data -- that returns 'n/a' (or a
    marketplace variant); local providers are the one true-$0 case."""
    provider = model.split("/", 1)[0] if "/" in model else model
    if is_local_provider(provider):
        return "$0 (local)"
    p = price_for(model)
    if p is not None:
        return f"${p[0]:.2f}/${p[1]:.2f}"
    if is_marketplace(provider):
        return "n/a (bring your own)"
    return "n/a"


def policy_agent_ids() -> list[str]:
    """All agent IDs governed by the role policy: the project agents."""

    return list(project_ids())


class RoleRepoint(NamedTuple):
    """One agent ``reapply_role_policy`` moved to another model."""

    agent_id: str
    pod: str
    role: str
    before: str
    after: str


def reapply_role_policy() -> list[RoleRepoint]:
    """Re-resolve every agent against the live role policy; returns each agent it moved."""

    role_models, _, _ = load_registry()
    changed: list[RoleRepoint] = []
    for aid in policy_agent_ids():
        role = agent_role(aid)
        pod = _pod.pod_of(aid) or ""
        target = resolve_role_model(role, role_models, project=pod)
        current = _fleet.meta_get(aid, "model", "")
        if target == current:
            continue
        try:
            _fleet.set_model_both(aid, target)
        except KeyError:
            _fleet.meta_set(aid, "model", target)
        changed.append(RoleRepoint(aid, pod, role, current, target))
    return changed


def write_registry(updates: dict[str, str], reset: bool = False) -> None:
    """Update docket-models.json via the store.py single-writer chokepoint.

    Key format: 'default', 'role.<name>', 'rank.<economy|standard|premium>'.
    'rank.*' persists a registry-overridable anchor so a non-Anthropic
    preset also replaces displayed anchors, not just roles. reset=True
    clears all user overrides."""
    path = current_home().model_registry_file
    try:
        reg: dict[str, Any] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        reg = {}

    if reset:
        reg = {}
    else:
        for k, v in updates.items():
            if k == "default":
                reg["default"] = v
            elif k.startswith("role."):
                role = k[5:]
                if role in ROLE_CLASS:
                    reg.setdefault("roles", {})[role] = v
            elif k.startswith("rank."):
                anchor = k[5:]
                if anchor in ("economy", "standard", "premium"):
                    reg.setdefault("rankAnchors", {})[anchor] = v

    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, reg)
