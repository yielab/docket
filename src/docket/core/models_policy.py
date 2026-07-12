"""Model policy: registry loading, role→model resolution, validation, re-apply."""

from __future__ import annotations

import json
import re
from typing import Any

import docket.config as cfg
from docket.edges import store as _store

# Internal rank anchors: per-class defaults (used to seed each role's default
# model) and the fallback ceiling shown by `docket models`. NOT a user-facing
# vocabulary — "economy"/"standard"/"premium" are no longer accepted as model
# arguments or registry keys (user-facing tier names removed in 0.2.0, D-2
# exit; see ROADMAP.md D-2). This table is the sole surviving piece of the old
# tier system, kept private because the fallback chain still reads it.
_RANK_ANCHORS: dict[str, str] = {
    "economy": "anthropic/claude-haiku-4-5",
    "standard": "anthropic/claude-sonnet-4-6",
    "premium": "anthropic/claude-opus-4-6",
}

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
# SOURCE: OpenClaw 2026.2.23 catalog.  Recorded spend in `docket cost` comes from
# the daemon's session logs — this table only powers comparative estimates.
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
}

KNOWN_PRESETS: tuple[str, ...] = (
    "anthropic",
    "openai",
    "google",
    "openrouter-free",
    "openrouter",
)

PRESET_TABLE: dict[str, dict[str, str]] = {
    "anthropic": {
        "economy": "anthropic/claude-haiku-4-5",
        "standard": "anthropic/claude-sonnet-4-6",
        "premium": "anthropic/claude-opus-4-6",
        "key": "ANTHROPIC_API_KEY",
        "cost": "paid",
        "note": "Default. Strongest tool-use support.",
    },
    "openai": {
        "economy": "openai/gpt-4.1-nano",
        "standard": "openai/gpt-4.1-mini",
        "premium": "openai/gpt-4.1",
        "key": "OPENAI_API_KEY",
        "cost": "paid",
        "note": "GPT-4.1 family.",
    },
    "google": {
        "economy": "google/gemini-2.0-flash-lite",
        "standard": "google/gemini-2.5-flash",
        "premium": "google/gemini-2.5-flash",
        "key": "GOOGLE_AI_API_KEY",
        "cost": "paid",
        "note": "No distinct premium Gemini model yet; standard=premium.",
    },
    "openrouter-free": {
        "economy": "openrouter/google/gemini-flash-1.5-8b",
        "standard": "openrouter/meta-llama/llama-3.3-70b-instruct",
        "premium": "openrouter/deepseek/deepseek-r1",
        "key": "OPENROUTER_API_KEY",
        "cost": "free",
        "note": "Zero per-token cost on free-tier models. Free account at openrouter.ai.",
    },
    "openrouter": {
        "economy": "openrouter/google/gemini-flash-1.5-8b",
        "standard": "openrouter/anthropic/claude-3.5-haiku",
        "premium": "openrouter/anthropic/claude-3-opus",
        "key": "OPENROUTER_API_KEY",
        "cost": "paid",
        "note": "Unified access to 200+ models via one key.",
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

    if isinstance(reg.get("default"), str) and _MODEL_ID_RE.match(reg["default"]):
        default_model = reg["default"]

    role_models = _init_role_models(tiers)

    # Explicit per-role overrides win.
    for role, m in reg.get("roles", {}).items():
        if role in ROLE_CLASS and isinstance(m, str) and _MODEL_ID_RE.match(m):
            role_models[role] = m

    return role_models, tiers, default_model


def resolve_role_model(role: str, role_models: dict[str, str] | None = None) -> str:
    """Return the effective model for a role (loads registry if not supplied)."""
    if role_models is None:
        role_models, _, _ = load_registry()
    return role_models.get(role, cfg.DEFAULT_MODEL)


def is_role(role: str) -> bool:
    return role in ROLE_CLASS


def agent_role(agent_id: str) -> str:
    """Policy role for an agent: specialist id, pod-member role, or ``repo``.

    For pod members the meta carries a pod ``role`` (lead/implementer/…)
    which maps to a role→model policy key, so model re-resolution targets the
    right policy. Otherwise: specialist id, or ``repo`` for a plain project
    agent (every project agent is a repo agent).
    """
    from docket.edges.adapters import openclaw as _oc

    if cfg.is_specialist(agent_id):
        return agent_id
    pod_role = _oc.meta_get(agent_id, "role", "")
    if pod_role:
        from docket.core import pod

        return pod.POD_ROLE_POLICY.get(pod_role, pod_role)
    return "repo"


def agent_model_source(agent_id: str) -> str:
    """Return 'policy' or 'pinned' for this agent."""
    from docket.edges.adapters import openclaw as _oc

    src = _oc.meta_get(agent_id, "modelSource", "")
    if src:
        return src
    role = agent_role(agent_id)
    model = _oc.meta_get(agent_id, "model", "")
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

    # 2. Well-formed provider/model — accepted; warn if unpriced.
    if _MODEL_ID_RE.match(model):
        if model not in MODEL_PRICING:
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
    """Return '$inp/$out' (per-M-token) or 'n/a' for a model."""
    p = MODEL_PRICING.get(model)
    if p is None:
        return "n/a"
    return f"${p[0]:.2f}/${p[1]:.2f}"


def policy_agent_ids() -> list[str]:
    """All agent IDs governed by the role policy: project agents + installed specialists."""
    from docket.core.utils import project_ids

    ids: list[str] = list(project_ids())
    for spec in cfg.SPECIALIST_ORDER:
        if (cfg.OPENCLAW_DIR / "workspaces" / spec).is_dir():
            ids.append(spec)
    return ids


def reapply_role_policy() -> int:
    """Re-resolve every policy-following agent against the live role policy.

    Pinned agents are never touched. Returns count of agents updated.
    """
    from docket.edges.adapters import openclaw as _oc

    role_models, _, _ = load_registry()
    changed = 0
    for aid in policy_agent_ids():
        src = agent_model_source(aid)
        if src != "policy":
            continue
        role = agent_role(aid)
        target = role_models.get(role, cfg.DEFAULT_MODEL)
        current = _oc.meta_get(aid, "model", "")
        if target == current:
            continue
        try:
            _oc.set_model_both(aid, target)
        except KeyError:
            _oc.meta_set(aid, "model", target)
        _oc.meta_set(aid, "modelSource", "policy")
        changed += 1
    return changed


def write_registry(updates: dict[str, str], reset: bool = False) -> None:
    """Update docket-models.json via the store.py single-writer chokepoint (D-12).

    Key format: 'default', 'role.<name>'.
    reset=True clears all user overrides (deletes the file if empty).
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

    path.parent.mkdir(parents=True, exist_ok=True)
    _store.write_json(path, reg)
