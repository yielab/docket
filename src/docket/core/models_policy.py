"""Model policy: registry loading, role→model resolution, validation, re-apply."""

from __future__ import annotations

import json
import re
from typing import Any

import docket.config as cfg
from docket.core import provider as _provider
from docket.edges import store as _store

ALL_ROLES: tuple[str, ...] = (
    "manager",
    "programmer",
    "reviewer",
    "tester",
    "knowledge",
    "security",
    "repo",
)

# cheap = high-volume / low reasoning-density; strong = reasoning-dense.
ROLE_CLASS: dict[str, str] = {
    "manager": "cheap",
    "reviewer": "cheap",
    "tester": "cheap",
    "knowledge": "cheap",
    "programmer": "strong",
    "security": "strong",
    "repo": "strong",
    # portfolio-manager coordinates fleet metadata across pods, not code — cheap class.
    "portfolio-manager": "cheap",
}

# Old/short model-id → current canonical model-id. Unrelated to the retired
# tier vocabulary (no entry here resolves through a tier name any more).
MODEL_ALIASES: dict[str, str] = {
    "anthropic/claude-haiku-3-5": "anthropic/claude-haiku-4-5",
    "anthropic/claude-haiku-3": "anthropic/claude-haiku-4-5",
    "anthropic/claude-sonnet-3-5": "anthropic/claude-sonnet-4-6",
    "anthropic/claude-sonnet-4": "anthropic/claude-sonnet-4-6",
    "anthropic/claude-opus-3": "anthropic/claude-opus-4-6",
    "anthropic/claude-opus-4": "anthropic/claude-opus-4-6",
}

_MODEL_ID_RE = re.compile(r"^[a-z0-9_-]+/[A-Za-z0-9._:/-]+$")


def rank_anchors() -> dict[str, str]:
    """Seed values for each rank (what `docket models` shows as "rank anchors"), read from the
    built-in `anthropic` provider's own preset -- NOT a runtime fallback chain; nothing in
    docket degrades a request to a cheaper model on failure."""
    spec = _provider.load_catalog().get("anthropic")
    if spec is None:
        return {}
    preset = next((p for p in spec.presets if p.name == "anthropic"), None)
    if preset is None:
        return {}
    return {rank: f"anthropic/{model_id}" for rank, model_id in preset.ranks.items()}


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
    ``docket models preset`` validates against."""
    return tuple(preset.name for _provider_name, preset in presets())


def _init_role_models(tiers: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for role in ALL_ROLES:
        cls = ROLE_CLASS.get(role, "strong")
        result[role] = tiers["economy"] if cls == "cheap" else tiers["standard"]
    return result


def _init_role_overrides_from_tiers(profiles: dict[str, Any]) -> dict[str, str]:
    """Derive per-role overrides from legacy tier-anchor values (migration helper)."""
    tiers = dict(rank_anchors())
    for tier in ("economy", "standard", "premium"):
        m = profiles.get(tier)
        if isinstance(m, str) and _MODEL_ID_RE.match(m):
            tiers[tier] = m
    return _init_role_models(tiers)


def migrate_legacy_profiles() -> str | None:
    """One-shot migration: legacy ``profiles:`` tier overrides -> ``roles:``.
    Idempotent -- a no-op once ``profiles:`` is gone or ``roles:`` exists
    (left as residual for ``docket doctor``; see ``has_residual_profiles_key``).
    Returns a summary to print (this module never prints), or ``None`` if unchanged."""
    path = cfg.MODEL_REGISTRY_FILE
    if not path.exists():
        return None
    try:
        reg: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    profiles = reg.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        return None
    if reg.get("roles"):
        return None  # roles: already present — leave profiles: for doctor to flag

    reg["roles"] = _init_role_overrides_from_tiers(profiles)
    del reg["profiles"]
    _store.write_json(path, reg)
    return (
        "Migrated legacy 'profiles:' tier overrides in docket-models.json to "
        "'roles:' (one-time). The 'profiles:' key is no longer read."
    )


def has_residual_profiles_key() -> bool:
    """True if docket-models.json still has a residual ``profiles:`` key
    (used by ``docket doctor``): the one-shot migration found ``roles:``
    already present and left ``profiles:`` untouched, or hasn't run yet."""
    path = cfg.MODEL_REGISTRY_FILE
    if not path.exists():
        return False
    try:
        reg: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return bool(reg.get("profiles"))


def load_registry() -> tuple[dict[str, str], dict[str, str], str]:
    """Return (role_models, tiers, default_model) from docket-models.json.
    Falls back to built-in defaults on any read/parse error; self-migrates a
    legacy ``profiles:`` key first (see ``migrate_legacy_profiles``).

    ``tiers`` are registry-overridable via ``rankAnchors``, applied *before*
    role defaults are derived so an overridden anchor reshapes every
    cheap/strong-class role default too. Malformed entries (unknown anchor,
    bad model id) are silently ignored, like ``default``/``roles`` below.
    """
    migrate_legacy_profiles()  # silent, idempotent — see the CLI layer for the warning

    tiers = dict(rank_anchors())
    default_model = cfg.DEFAULT_MODEL

    path = cfg.MODEL_REGISTRY_FILE
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
    ``load_registry`` silently ignores -- for ``docket doctor``. *key* is the file path
    itself for an unreadable file, else a dotted ``rankAnchors.<x>``/``roles.<x>``/``default``."""
    path = cfg.MODEL_REGISTRY_FILE
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


def resolve_role_model(role: str, role_models: dict[str, str] | None = None) -> str:
    """Return the effective model for a role (loads registry if not supplied).

    ``role`` may be a pod *archetype* name with no row of its own (a
    starter-library/user-defined role with no ``policy_role`` set); those
    fall through to ``_resolve_via_archetype_class``, resolving via the
    archetype's ``modelClass`` against live rank anchors -- this is what lets
    ``modelClass`` slot into policy instead of collapsing to
    ``cfg.DEFAULT_MODEL``. The four legacy pod roles are unaffected: their
    ``policy_role`` override already has a row in ``role_models``.
    """
    if role_models is None:
        role_models, _, _ = load_registry()
    if role in role_models:
        return role_models[role]
    return _resolve_via_archetype_class(role)


def _resolve_via_archetype_class(role: str) -> str:
    """Resolve a model for a role unknown to ``ALL_ROLES`` via its archetype's modelClass."""
    from docket.core import archetypes as _arch

    arch = _arch.load_registry().get(role)
    if arch is None:
        return cfg.DEFAULT_MODEL
    _, tiers, _ = load_registry()
    return tiers["economy"] if arch.model_class == "cheap" else tiers["standard"]


def resolve_step_model(model: str) -> str:
    """Resolve a pipeline step's own ``model`` (pipeline-format.spec.md "Steps" Req. 10) to a
    literal ``provider/id`` for one hop. ``cheap``/``strong`` resolve against the live rank
    anchors (``economy``/``standard``); any other value is returned unchanged once its
    ``<provider>/...`` prefix is confirmed present in the provider catalog -- raises naming the
    provider otherwise, so a caller can refuse before any hop runs. See model-profiles.spec.md
    "Model intent per agent" requirement 4."""
    if model in ("cheap", "strong"):
        _, tiers, _ = load_registry()
        return tiers["economy"] if model == "cheap" else tiers["standard"]
    provider = model.split("/", 1)[0]
    if _provider.load_catalog().get(provider) is None:
        raise ValueError(f"unknown provider {provider!r} in step model {model!r}")
    return model


def is_role(role: str) -> bool:
    return role in ROLE_CLASS


def agent_role(agent_id: str) -> str:
    """Policy role for an agent: specialist id, pod-member role, or ``repo``.
    Pod members map their meta ``role`` (lead/implementer/...) to a
    role->model policy key; otherwise specialist id or ``repo``."""
    from docket.core import fleet as _fleet

    if cfg.is_specialist(agent_id):
        return agent_id
    pod_role = _fleet.meta_get(agent_id, "role", "")
    if pod_role:
        from docket.core import pod

        return pod.policy_role_for(pod_role)
    return "repo"


def agent_model_source(agent_id: str) -> str:
    """Return 'policy' or 'pinned' for this agent."""
    from docket.core import fleet as _fleet

    src = _fleet.meta_get(agent_id, "modelSource", "")
    if src:
        return src
    role = agent_role(agent_id)
    model = _fleet.meta_get(agent_id, "model", "")
    if not model or model == resolve_role_model(role):
        return "policy"
    return "pinned"


def validate_model(model: str) -> tuple[str, list[str]]:
    """Validate and canonicalise a model name. Returns (canonical_model,
    warnings); raises ValueError on hard failure."""
    warnings: list[str] = []

    # 1. Known alias (old/short model id → current canonical id).
    if model in MODEL_ALIASES:
        resolved = MODEL_ALIASES[model]
        warnings.append(f"Model alias '{model}' → '{resolved}'.")
        return resolved, warnings

    # 2. Well-formed provider/model — accepted; warn if unpriced (never for a
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

    # 3. Malformed (includes the retired tier names economy/standard/premium).
    role_models, _, _ = load_registry()
    lines = "\n".join(f"  {r:<12} {role_models.get(r, cfg.DEFAULT_MODEL)}" for r in ALL_ROLES)
    raise ValueError(
        f"Invalid model: '{model}'\n"
        "Use a full provider/model ID (e.g. anthropic/claude-sonnet-4-6).\n"
        f"Current role policy:\n{lines}\n"
        "Change a role's model: docket models set <role> <provider/model>"
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
    """All agent IDs governed by the role policy: project agents + installed specialists."""
    from docket.core.utils import project_ids

    ids: list[str] = list(project_ids())
    for spec in cfg.SPECIALIST_ORDER:
        if (cfg.WORKSPACES_DIR / spec).is_dir():
            ids.append(spec)
    return ids


def reapply_role_policy() -> int:
    """Re-resolve every policy-following agent against the live role policy.
    Pinned agents are never touched. Returns count of agents updated."""
    from docket.core import fleet as _fleet

    role_models, _, _ = load_registry()
    changed = 0
    for aid in policy_agent_ids():
        src = agent_model_source(aid)
        if src != "policy":
            continue
        role = agent_role(aid)
        target = role_models.get(role, cfg.DEFAULT_MODEL)
        current = _fleet.meta_get(aid, "model", "")
        if target == current:
            continue
        try:
            _fleet.set_model_both(aid, target)
        except KeyError:
            _fleet.meta_set(aid, "model", target)
        _fleet.meta_set(aid, "modelSource", "policy")
        changed += 1
    return changed


def write_registry(updates: dict[str, str], reset: bool = False) -> None:
    """Update docket-models.json via the store.py single-writer chokepoint.

    Key format: 'default', 'role.<name>', 'rank.<economy|standard|premium>'.
    'rank.*' persists a registry-overridable anchor so a non-Anthropic
    preset also replaces displayed anchors, not just roles. reset=True
    clears all user overrides."""
    path = cfg.MODEL_REGISTRY_FILE
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
    _store.write_json(path, reg)
