"""Declarative guardrail policy engine.

Policies live at ``$POLICIES_DIR/*.json``. Each policy is::

    { "id": str, "applies_to": ["role"|"*"], "hook": str,
      "match": {"type":"regex","pattern":str}, "action": str, "message": str }

Hooks:    pre_input | pre_tool_call | pre_output
Actions:  allow | warn | redact | require_approval | block

``policy_eval`` returns the winning action (most restrictive wins); ``policy_eval_detail``
returns the full :class:`PolicyHit` (action + which policy id/message won), used by callers
that need to attribute a trip to a specific policy (``core/dispatch.py``'s live-path producer,
ROADMAP Phase 15 G-2). The CLI's ``policies test`` path calls ``policy_test`` which is a
dry-run with no trace side-effects, so this module itself never emits traces (matching
DOCKET_NO_TRACE=1) — callers that need a trace record emit it themselves.

Policy files are docket-owned artefacts (not openclaw config), so this module
reads them directly rather than through the ACL.

Live-path wiring (G-2, ROADMAP Phase 15): ``pre_input`` is evaluated once, at
task enqueue (``core/dispatch.py``'s ``enqueue_task``) — not re-evaluated before
every hop, which would re-gate the same task text at every role a "*"-scoped
policy applies to. ``pre_output`` is evaluated on every hop's real output,
before it is embedded in the carried-forward artifact or persisted hop record
(``core/dispatch.py``'s ``_execute_unit``). ``pre_tool_call`` (in-turn, inside a
daemon turn) stays daemon-gated — docket is not inside a turn to intercept a
tool call — and is never claimed as enforced here (ROADMAP §4.5).
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
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


@dataclass
class PolicyHit:
    """The winning policy for one ``policy_eval_detail`` call.

    ``policy_id``/``message`` are ``""`` for the no-match default (``action="allow"``) so a
    caller can always safely bucket/attribute a trip by ``policy_id`` without a None-check.
    """

    action: str = "allow"
    policy_id: str = ""
    message: str = ""


def policy_eval_detail(role: str, hook: str, text: str, *, trusted: bool = False) -> PolicyHit:
    """Return the winning :class:`PolicyHit` for (role, hook, text); most restrictive wins.

    trusted: skip injection/untrusted-input policies (source=operator).
    Trace side-effects are intentionally omitted here — this is the pure evaluator; a live-path
    caller (``core/dispatch.py``) or the CLI's dry-run (``policy_test``) decides what to do with
    the result.
    """
    if not _cfg.POLICIES_DIR.is_dir():
        return PolicyHit()

    best = PolicyHit()
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
                    best = PolicyHit(
                        action=action,
                        policy_id=str(p.get("id", "")),
                        message=str(p.get("message", "")),
                    )
        except re.error:
            continue

    return best


def policy_eval(role: str, hook: str, text: str, *, trusted: bool = False) -> str:
    """Return the winning action for (role, hook, text); most restrictive wins.

    Thin wrapper over :func:`policy_eval_detail` for callers that only need the action
    (e.g. the CLI's dry-run path) — kept so every existing caller/test is unaffected.
    """
    return policy_eval_detail(role, hook, text, trusted=trusted).action


def policy_test(hook: str, role: str, text: str) -> str:
    """Dry-run the evaluator (no trace emission)."""
    return policy_eval(role, hook, text)


@dataclass
class PolicyInstallResult:
    """Outcome of :func:`install_policies` — one entry per shipped template, in template order.

    ``entries`` preserves the exact iteration order the caller renders in (a file either
    installed this call or skipped because it already existed) so a UI layer can render an
    interleaved "installed: x / skip (exists): y" list matching that order, rather than two
    separately-sorted groups.
    """

    template_dir: Path
    policies_dir: Path
    entries: list[tuple[str, bool]] = field(default_factory=list)  # (filename, was_installed)

    @property
    def installed(self) -> list[str]:
        return [name for name, was_installed in self.entries if was_installed]

    @property
    def skipped(self) -> list[str]:
        return [name for name, was_installed in self.entries if not was_installed]


def install_policies() -> PolicyInstallResult:
    """Copy the baseline policy templates into ``$POLICIES_DIR`` (idempotent).

    An existing destination file is left untouched (skipped, never overwritten) — the same
    "install once, edit locally after that" contract ``docket policies init`` has always had.
    Directory created 0700, each copied file 0600. Returns an empty ``entries`` list (not an
    error) when the template directory itself is missing; check ``template_dir.is_dir()`` first
    if that distinction matters to the caller.

    Pure logic, no UI: this is the shared producer behind both ``docket policies init`` and
    ``docket install``'s own policy-provisioning step (ROADMAP Phase 15 G-2) — one
    implementation, two callers, so the two can never drift on what "installed" means.
    """
    template_dir = _cfg.policy_templates_dir()
    result = PolicyInstallResult(template_dir=template_dir, policies_dir=_cfg.POLICIES_DIR)
    if not template_dir.is_dir():
        return result

    _cfg.POLICIES_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(_cfg.POLICIES_DIR, 0o700)

    for f in sorted(template_dir.glob("*.json")):
        dest = _cfg.POLICIES_DIR / f.name
        if dest.exists():
            result.entries.append((f.name, False))
        else:
            shutil.copy(f, dest)
            os.chmod(dest, 0o600)
            result.entries.append((f.name, True))

    return result
