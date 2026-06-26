"""Model policy: registry loading, role→model resolution, validation, re-apply."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import docket.config as cfg

TIER_ANCHORS: dict[str, str] = {
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
    "task",
)

# cheap = high-volume / low reasoning-density; strong = reasoning-dense.
ROLE_CLASS: dict[str, str] = {
    "manager": "cheap",
    "reviewer": "cheap",
    "tester": "cheap",
    "knowledge": "cheap",
    "task": "cheap",
    "programmer": "strong",
    "security": "strong",
    "repo": "strong",
    # Org Portfolio Manager (AA-6): a coordinator over fleet metadata, not code.
    "portfolio-manager": "cheap",
}

# Short-name aliases.
MODEL_ALIASES: dict[str, str] = {
    "anthropic/claude-haiku-3-5": "anthropic/claude-haiku-4-5",
    "anthropic/claude-haiku-3": "anthropic/claude-haiku-4-5",
    "anthropic/claude-sonnet-3-5": "anthropic/claude-sonnet-4-6",
    "anthropic/claude-sonnet-4": "anthropic/claude-sonnet-4-6",
    "anthropic/claude-opus-3": "anthropic/claude-opus-4-6",
    "anthropic/claude-opus-4": "anthropic/claude-opus-4-6",
    "haiku": "economy",
    "sonnet": "standard",
    "opus": "premium",
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

# Provider presets.
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


def load_registry() -> tuple[dict[str, str], dict[str, str], str]:
    """Return (role_models, tiers, default_model) from docket-models.json.

    Falls back to built-in defaults on any read/parse error.
    """
    tiers = dict(TIER_ANCHORS)
    default_model = cfg.DEFAULT_MODEL

    path = cfg.MODEL_REGISTRY_FILE
    if not path.exists():
        return _init_role_models(tiers), tiers, default_model

    try:
        reg: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _init_role_models(tiers), tiers, default_model

    # Pass 1: default model and rank anchors.
    if isinstance(reg.get("default"), str) and _MODEL_ID_RE.match(reg["default"]):
        default_model = reg["default"]
    for tier in ("economy", "standard", "premium"):
        m = reg.get("profiles", {}).get(tier)
        if isinstance(m, str) and _MODEL_ID_RE.match(m):
            tiers[tier] = m

    # Re-derive role defaults from the (possibly overridden) anchors.
    role_models = _init_role_models(tiers)

    # Pass 2: explicit per-role overrides win.
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
    """Policy role for an agent: specialist id, pod-member role, or project type.

    For pod members the meta carries a pod ``role`` (lead/implementer/…)
    which maps to a role→model policy key, so model re-resolution targets the
    right policy. Otherwise: specialist id, or project ``type`` (repo|task).
    """
    from docket.edges.adapters import openclaw as _oc

    if cfg.is_specialist(agent_id):
        return agent_id
    pod_role = _oc.meta_get(agent_id, "role", "")
    if pod_role:
        from docket.core import pod

        return pod.POD_ROLE_POLICY.get(pod_role, pod_role)
    return _oc.meta_get(agent_id, "type", "repo")


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


# ── model validation ───────────────────────────────────────────────────────────


def validate_model(model: str) -> tuple[str, list[str]]:
    """Validate and canonicalise a model name.

    Returns (canonical_model, warnings). Raises ValueError on hard failure.
    """
    warnings: list[str] = []

    # 1. Deprecated tier name.
    if model in TIER_ANCHORS:
        canonical = TIER_ANCHORS[model]
        warnings.append(
            f"Tier names are deprecated. '{model}' → {canonical}. "
            "Use the role policy (docket models) or a provider/model ID."
        )
        return canonical, warnings

    # 2. Alias (may resolve to a tier).
    if model in MODEL_ALIASES:
        resolved = MODEL_ALIASES[model]
        if resolved in TIER_ANCHORS:
            resolved = TIER_ANCHORS[resolved]
        warnings.append(f"Model alias '{model}' → '{resolved}'.")
        return resolved, warnings

    # 3. Well-formed provider/model — accepted; warn if unpriced.
    if _MODEL_ID_RE.match(model):
        if model not in MODEL_PRICING:
            warnings.append(
                f"Model '{model}' is not in docket's pricing table — cost will show as n/a."
            )
        return model, warnings

    # 4. Malformed.
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
    """Atomically update docket-models.json.

    Key format: 'default', 'role.<name>', 'tier.<name>'.
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
            elif k.startswith("tier."):
                tier = k[5:]
                if tier in ("economy", "standard", "premium"):
                    reg.setdefault("profiles", {})[tier] = v

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(reg, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
