"""Model policy: registry loading, role→model resolution, validation, re-apply."""

from __future__ import annotations

import json
import re
from typing import Any

import docket.config as cfg
from docket.edges import store as _store

# Internal rank anchors: per-class defaults (used to seed each role's default
# model) and the seed values `docket models` displays alongside the policy
# table. NOT a user-facing vocabulary — "economy"/"standard"/"premium" are no
# longer accepted as model arguments or registry keys. This table is the sole
# surviving piece of the old tier system, kept private because role-default
# seeding still reads it. It is NOT a runtime fallback chain — nothing in
# docket degrades a request to a cheaper model on failure; `docket models`
# labels it "rank anchors", never "fallback".
#
# Registry-overridable: a user's docket-models.json MAY carry a top-level
# ``rankAnchors`` map (``{"economy": "...", "standard": "...", "premium":
# "..."}``) that overrides these Anthropic defaults before role defaults are
# derived — see `load_registry`. This is how a fleet on a non-Anthropic
# preset stops showing Claude residue in the anchor display.
_RANK_ANCHORS: dict[str, str] = {
    "economy": "anthropic/claude-haiku-4-5",
    "standard": "anthropic/claude-sonnet-4-6",
    "premium": "anthropic/claude-opus-4-6",
}

# Provider prefixes that never carry a per-token dollar cost — a local
# OpenAI-compatible endpoint (llama.cpp / LM Studio / vLLM / Ollama, all of
# which speak the same /v1 surface `core/provider.py` registers). Priced as
# "$0 (local)", never "n/a" (there is no missing data — the true cost is
# zero) and never a fabricated non-zero figure.
LOCAL_PROVIDERS: tuple[str, ...] = ("local", "ollama", "lmstudio")

# Providers whose per-model pricing docket deliberately does NOT hardcode: a
# marketplace router (OpenRouter) re-prices per underlying model and account
# tier, changes often, and isn't something a manual snapshot table can track
# honestly. Anything under these prefixes that isn't an explicit MODEL_PRICING
# row (the stable OpenRouter free router below is the exception) reports the informative
# "unpriced, bring your own" label instead of a stale or invented number.
UNPRICED_MARKETPLACE_PROVIDERS: tuple[str, ...] = ("openrouter", "ai-gateway")

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

# Pricing snapshot: input, output, cache_read, cache_write (per M tokens).
# A manual snapshot, not a live price feed. `docket cost` reports real,
# measured token counts (`core/session.py`'s MeasuredUsage) but never a
# dollar figure of its own -- this table only powers comparative *estimates*
# (see CLAUDE.md's standing no-fabricated-dollar-figures rule).
MODEL_PRICING_AS_OF = "2026-06-11"
MODEL_PRICING: dict[str, tuple[float, float, float, float]] = {
    "anthropic/claude-haiku-4-5": (0.80, 4.00, 0.08, 1.00),
    "anthropic/claude-haiku-3-5": (0.80, 4.00, 0.08, 1.00),
    "anthropic/claude-sonnet-4-6": (3.00, 15.00, 0.30, 3.75),
    "anthropic/claude-sonnet-4-5": (3.00, 15.00, 0.30, 3.75),
    "anthropic/claude-opus-4-6": (15.00, 75.00, 1.50, 18.75),
    "openai/gpt-4.1-nano": (0.10, 0.40, 0.0, 0.0),
    "openai/gpt-4.1-mini": (0.40, 1.60, 0.0, 0.0),
    "openai/gpt-4.1": (2.00, 8.00, 0.0, 0.0),
    "openai/gpt-4o": (2.50, 10.00, 0.0, 0.0),
    "google/gemini-2.0-flash-lite": (0.075, 0.30, 0.0, 0.0),
    "google/gemini-2.5-flash": (0.15, 0.60, 0.0, 0.0),
    "google/gemini-2.5-flash-lite": (0.10, 0.40, 0.0, 0.0),
    # OpenRouter's capability-aware free router. The actual model can change
    # between calls, so only the stable router id is pinned and priced here.
    "openrouter/openrouter/free": (0.0, 0.0, 0.0, 0.0),
    # Local OpenAI-compatible endpoint (core/provider.py's DEFAULT_MODEL_ID) —
    # genuinely zero per-token cost, not an estimate. pricing_label() also
    # short-circuits on LOCAL_PROVIDERS, so this row is belt-and-suspenders
    # for any code path that reads MODEL_PRICING directly.
    "local/qwen3-30b-a3b": (0.0, 0.0, 0.0, 0.0),
}

KNOWN_PRESETS: tuple[str, ...] = (
    "anthropic",
    "openai",
    "google",
    "openrouter-free",
    "openrouter",
    "ai-gateway",
    "local",
)

PRESET_TABLE: dict[str, dict[str, str]] = {
    "anthropic": {
        "economy": "anthropic/claude-haiku-4-5",
        "standard": "anthropic/claude-sonnet-4-6",
        "premium": "anthropic/claude-opus-4-6",
        "key": "ANTHROPIC_API_KEY",
        "cost": "paid",
        "note": "Requires an explicitly registered OpenAI-compatible endpoint; key alone is insufficient.",
    },
    "openai": {
        "economy": "openai/gpt-4.1-nano",
        "standard": "openai/gpt-4.1-mini",
        "premium": "openai/gpt-4.1",
        "key": "OPENAI_API_KEY",
        "cost": "paid",
        "note": "GPT-4.1 family; requires a registered compatible endpoint before use.",
    },
    "google": {
        "economy": "google/gemini-2.0-flash-lite",
        "standard": "google/gemini-2.5-flash",
        "premium": "google/gemini-2.5-flash",
        "key": "GOOGLE_AI_API_KEY",
        "cost": "paid",
        "note": "Requires a registered compatible endpoint; key alone is insufficient.",
    },
    "openrouter-free": {
        "economy": "openrouter/openrouter/free",
        "standard": "openrouter/openrouter/free",
        "premium": "openrouter/openrouter/free",
        "key": "OPENROUTER_API_KEY",
        "cost": "free",
        "note": (
            "Experimental zero-cost router; model selection and availability can change per call. "
            "Free account at openrouter.ai."
        ),
    },
    "openrouter": {
        "economy": "openrouter/anthropic/claude-haiku-4.5",
        "standard": "openrouter/anthropic/claude-sonnet-4.6",
        "premium": "openrouter/anthropic/claude-opus-4.6",
        "key": "OPENROUTER_API_KEY",
        "cost": "paid",
        "note": "Unified access to 200+ models via one key.",
    },
    "ai-gateway": {
        "economy": "ai-gateway/anthropic/claude-haiku-4.5",
        "standard": "ai-gateway/anthropic/claude-sonnet-4.6",
        "premium": "ai-gateway/anthropic/claude-opus-4.6",
        "key": "AI_GATEWAY_API_KEY",
        "cost": "paid",
        "note": "Vercel AI Gateway with unified routing and observability.",
    },
    "local": {
        "economy": "local/qwen3-30b-a3b",
        "standard": "local/qwen3-30b-a3b",
        "premium": "local/qwen3-30b-a3b",
        "key": "",
        "cost": "free",
        "note": (
            "Local OpenAI-compatible endpoint (llama.cpp/LM Studio/vLLM/Ollama) — no API key, "
            "no per-token cost. Register your endpoint first: docket models provider "
            "[name] [base_url]."
        ),
    },
}


def _init_role_models(tiers: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for role in ALL_ROLES:
        cls = ROLE_CLASS.get(role, "strong")
        result[role] = tiers["economy"] if cls == "cheap" else tiers["standard"]
    return result


def _init_role_overrides_from_tiers(profiles: dict[str, Any]) -> dict[str, str]:
    """Derive per-role overrides from legacy tier-anchor values (migration helper)."""
    tiers = dict(_RANK_ANCHORS)
    for tier in ("economy", "standard", "premium"):
        m = profiles.get(tier)
        if isinstance(m, str) and _MODEL_ID_RE.match(m):
            tiers[tier] = m
    return _init_role_models(tiers)


def migrate_legacy_profiles() -> str | None:
    """One-shot migration: legacy ``profiles:`` tier-anchor overrides → ``roles:``.

    Runs at most once per registry: if ``docket-models.json`` has a ``profiles:``
    key but no ``roles:`` key yet, derive equivalent per-role overrides from the
    tier-anchor values (mirroring the class-based defaults ``_init_role_models``
    would have produced) and write them under ``roles:``, then drop ``profiles:``.
    Idempotent — a no-op once ``profiles:`` is gone or ``roles:`` already exists
    (in which case ``profiles:`` is left alone as a residual key for
    ``docket doctor`` to flag; see ``has_residual_profiles_key``).

    Returns a human-readable summary for the caller to print via ``ui.warn``
    (this module never prints — CLI layer decides), or ``None`` if nothing
    changed.
    """
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
    """True if docket-models.json still has a (post-migration residual) ``profiles:`` key.

    Used by ``docket doctor``. Residual means the one-shot migration in
    ``migrate_legacy_profiles`` found ``roles:`` already present and left
    ``profiles:`` untouched, or the write-back has not happened yet.
    """
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

    Falls back to built-in defaults on any read/parse error. Self-migrates a
    legacy ``profiles:`` key (see ``migrate_legacy_profiles``) before reading.

    ``tiers`` (the rank anchors) are registry-overridable via a top-level
    ``rankAnchors`` map — applied *before* role defaults are derived, so an
    overridden anchor reshapes every cheap/strong-class role default too, and
    the value `docket models` displays next to it is never stale Claude
    residue for a fleet on another provider. Malformed entries
    (unknown anchor name, not a well-formed model id) are silently ignored,
    matching the tolerance already applied to ``default``/``roles`` below.
    """
    migrate_legacy_profiles()  # silent, idempotent — see the CLI layer for the warning

    tiers = dict(_RANK_ANCHORS)
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


def resolve_role_model(role: str, role_models: dict[str, str] | None = None) -> str:
    """Return the effective model for a role (loads registry if not supplied).

    ``role`` is usually a named policy role (``ALL_ROLES``), but MAY also be a
    pod *archetype* name that has no row of its own there — a starter-library
    or user-defined role like ``researcher``, whose ``policy_role`` was left
    unset. Those fall through to
    ``_resolve_via_archetype_class``, which resolves the model via the
    archetype's own declared ``modelClass`` (cheap|strong) against the live
    rank anchors — this is what lets `modelClass` genuinely *slot into* this
    policy instead of every unlisted role silently collapsing to
    ``cfg.DEFAULT_MODEL``. The four legacy pod roles are unaffected: their
    archetypes carry a ``policy_role`` override (``manager``/``programmer``/
    ``reviewer``/``tester``) that already has a row in ``role_models``, so
    they never reach this fallback.
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


def is_role(role: str) -> bool:
    return role in ROLE_CLASS


def agent_role(agent_id: str) -> str:
    """Policy role for an agent: specialist id, pod-member role, or ``repo``.

    For pod members the meta carries a pod ``role`` (lead/implementer/…)
    which maps to a role→model policy key, so model re-resolution targets the
    right policy. Otherwise: specialist id, or ``repo`` for a plain project
    agent (every project agent is a repo agent).
    """
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
    """Validate and canonicalise a model name.

    Returns (canonical_model, warnings). Raises ValueError on hard failure.
    """
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
        if provider in LOCAL_PROVIDERS:
            pass
        elif model not in MODEL_PRICING:
            if provider in UNPRICED_MARKETPLACE_PROVIDERS:
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

    Never returns a fabricated "$0.00" for a model docket has no pricing
    data for — that path returns 'n/a' (or the marketplace-specific variant)
    instead. Local providers are the one case where $0 is the *true* cost,
    not a placeholder for missing data.
    """
    provider = model.split("/", 1)[0] if "/" in model else model
    if provider in LOCAL_PROVIDERS:
        return "$0 (local)"
    p = MODEL_PRICING.get(model)
    if p is not None:
        return f"${p[0]:.2f}/${p[1]:.2f}"
    if provider in UNPRICED_MARKETPLACE_PROVIDERS:
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

    Pinned agents are never touched. Returns count of agents updated.
    """
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
    The 'rank.*' form persists a registry-overridable rank anchor — used by
    `docket models preset` so a non-Anthropic preset also replaces the
    anchor values `docket models` displays, not just the roles. reset=True
    clears all user overrides (deletes the file if empty).
    """
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
                if anchor in _RANK_ANCHORS:
                    reg.setdefault("rankAnchors", {})[anchor] = v

    path.parent.mkdir(parents=True, exist_ok=True)
    _store.write_json(path, reg)
