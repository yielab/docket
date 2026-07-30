"""Declarative guardrail policy engine.

Policies live at ``$POLICIES_DIR/*.json``. Each policy is::

    { "id": str, "applies_to": ["role"|"*"], "hook": str,
      "match": {"type":"regex","pattern":str}, "action": str, "message": str }

Hooks:    pre_input | pre_tool_call | pre_output
Actions:  allow | warn | redact | require_approval | block

``policy_eval`` returns the winning action (most restrictive wins). The CLI's
``policies test`` path calls ``policy_test`` which is a dry-run with no trace
side-effects, so this module never emits traces (matching DOCKET_NO_TRACE=1).

Policy files are docket-owned artefacts (not openclaw config), so this module
reads them directly rather than through the ACL.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import docket.config as _cfg

VALID_HOOKS: frozenset[str] = frozenset({"pre_input", "pre_tool_call", "pre_output"})
VALID_ACTIONS: frozenset[str] = frozenset({"allow", "warn", "redact", "require_approval", "block"})

# Most-restrictive-wins ranking.
_RANK: dict[str, int] = {
    "block": 4,
    "require_approval": 3,
    "redact": 2,
    "warn": 1,
    "allow": 0,
}

# Policy ids skipped when source=operator (--trusted).
_INJECTION_IDS: frozenset[str] = frozenset({"prompt-injection"})


def validate_policy(path: Path) -> str:
    """Validate one policy file. Return '' if valid, else an error message.

    2026-07-30 (CL-2 dead-code register): the CLI doesn't call this yet —
    `cli/_policies.py`'s `_list()`/`_show()` do their own generic JSON parse,
    they don't schema-check. Kept rather than removed because it is not
    actually unexercised: `tests/python/test_cd3_high_risk.py` and
    `test_m5_gates_policy.py` call it directly as the schema-validity guard
    over the shipped `high-risk-*.json` templates — real regression coverage
    a plain JSON parse doesn't give. Wiring a `docket policies validate`
    command (mirroring `docket roles validate`) is the natural next step, but
    that is new CLI surface (a completions-golden change) and this is a
    no-behaviour-change cleanup card, so it is left as tested-but-unwired
    rather than added here.
    """
    try:
        with path.open(encoding="utf-8") as f:
            p: dict[str, Any] = json.load(f)
    except Exception as exc:
        return f"Cannot parse {path}: {exc}"

    required = {"id", "applies_to", "hook", "match", "action"}
    missing = required - set(p.keys())
    if missing:
        return f"{path}: missing fields: {missing}"
    if p.get("hook") not in VALID_HOOKS:
        return (
            f"{path}: unknown hook '{p.get('hook')}' (valid: pre_input, pre_tool_call, pre_output)"
        )
    if p.get("action") not in VALID_ACTIONS:
        return f"{path}: unknown action '{p.get('action')}'"
    match = p.get("match") or {}
    if not isinstance(match, dict) or match.get("type") not in ("regex",):
        return f"{path}: match.type must be 'regex'"
    if not match.get("pattern"):
        return f"{path}: match.pattern is required"
    return ""


def policy_files() -> list[Path]:
    """Return the installed policy JSON files in sorted order."""
    if not _cfg.POLICIES_DIR.is_dir():
        return []
    return sorted(_cfg.POLICIES_DIR.glob("*.json"))


def policy_eval(role: str, hook: str, text: str, *, trusted: bool = False) -> str:
    """Return the winning action for (role, hook, text); most restrictive wins.

    trusted: skip injection/untrusted-input policies (source=operator).
    Trace side-effects are intentionally omitted; the CLI only ever runs the dry-run path.
    """
    if not _cfg.POLICIES_DIR.is_dir():
        return "allow"

    best_action = "allow"
    best_rank = 0

    for path in policy_files():
        try:
            with path.open(encoding="utf-8") as f:
                p: dict[str, Any] = json.load(f)
        except Exception:
            continue
        if p.get("hook") != hook:
            continue
        applies = p.get("applies_to", []) or []
        if "*" not in applies and role not in applies:
            continue
        if trusted and p.get("id") in _INJECTION_IDS:
            continue
        pattern = (p.get("match") or {}).get("pattern", "")
        if not pattern:
            continue
        try:
            if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
                action = str(p.get("action", "allow"))
                rank = _RANK.get(action, 0)
                if rank > best_rank:
                    best_rank = rank
                    best_action = action
        except re.error:
            continue

    return best_action


def policy_test(hook: str, role: str, text: str) -> str:
    """Dry-run the evaluator (no trace emission)."""
    return policy_eval(role, hook, text)
