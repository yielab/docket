"""Declarative guardrail policy engine. Policies live at ``$POLICIES_DIR/*.json``::

    { "id": str, "applies_to": ["role"|"*"], "hook": str,
      "match": {"type":"regex","pattern":str}, "action": str, "message": str }
``policy_eval`` returns the winning action (most restrictive wins); ``policy_eval_detail`` the
full :class:`PolicyHit` for attribution. A file that fails validation is never silently skipped:
it evaluates as ``block`` within its readable scope, attributed to the file (fail closed, spec
requirement 7). Never emits traces itself; callers emit their own records.
Live-path wiring: ``pre_input`` runs once at task enqueue, not re-evaluated per hop (which would
re-gate the same task text at every role a ``"*"``-scoped policy applies to); ``pre_output`` runs
on every hop's real output before it is carried forward or persisted; ``pre_tool_call`` runs
in-turn inside ``core/tools.py``'s ``dispatch_tool`` chokepoint, for every tool call."""

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


def _validate_doc(p: dict[str, Any], label: str) -> str:
    """Validate one parsed policy document; '' if valid, else the error. The single owner of
    "what a valid policy is": ``validate_policy``, the evaluator's fail-closed check and doctor
    all call this, so validator and evaluator can never disagree (spec requirement 7)."""
    required = {"id", "applies_to", "hook", "match", "action"}
    missing = required - set(p.keys())
    if missing:
        return f"{label}: missing fields: {missing}"
    if p.get("hook") not in VALID_HOOKS:
        return (
            f"{label}: unknown hook '{p.get('hook')}' (valid: pre_input, pre_tool_call, pre_output)"
        )
    if p.get("action") not in VALID_ACTIONS:
        return f"{label}: unknown action '{p.get('action')}'"
    match = p.get("match") or {}
    if not isinstance(match, dict) or match.get("type") not in ("regex",):
        return f"{label}: match.type must be 'regex'"
    pattern = match.get("pattern")
    if not pattern:
        return f"{label}: match.pattern is required"
    try:
        re.compile(str(pattern), re.IGNORECASE | re.MULTILINE)
    except re.error as exc:
        return f"{label}: match.pattern does not compile: {exc}"
    return ""


def validate_policy(path: Path) -> str:
    """Validate one policy file: '' if valid, else an error message. Wired into ``docket
    policies validate`` and shared with the evaluator's fail-closed check via ``_validate_doc``."""
    try:
        with path.open(encoding="utf-8") as f:
            p: dict[str, Any] = json.load(f)
    except Exception as exc:
        return f"Cannot parse {path}: {exc}"
    return _validate_doc(p, str(path))


def policy_files() -> list[Path]:
    """Return the installed policy JSON files in sorted order."""
    if not _cfg.POLICIES_DIR.is_dir():
        return []
    return sorted(_cfg.POLICIES_DIR.glob("*.json"))


@dataclass
class PolicyHit:
    """The winning policy for one ``policy_eval_detail`` call.

    ``policy_id``/``message`` are ``""`` for the no-match default (``action="allow"``) so a caller
    can always safely bucket/attribute a trip by ``policy_id`` without a None-check."""

    action: str = "allow"
    policy_id: str = ""
    message: str = ""


def policy_eval_detail(role: str, hook: str, text: str, *, trusted: bool = False) -> PolicyHit:
    """Return the winning :class:`PolicyHit` for (role, hook, text); most restrictive wins.

    trusted: skip injection/untrusted-input policies (source=operator). Trace side-effects are
    intentionally omitted here -- this is the pure evaluator; a live-path caller or the CLI's
    dry-run (``policy_test``) decides what to do with the result."""
    if not _cfg.POLICIES_DIR.is_dir():
        return PolicyHit()

    best = PolicyHit()
    best_rank = 0

    def consider(action: str, policy_id: str, message: str) -> None:
        nonlocal best, best_rank
        rank = _RANK.get(action, 0)
        if rank > best_rank:
            best_rank = rank
            best = PolicyHit(action=action, policy_id=policy_id, message=message)

    for path in policy_files():
        try:
            with path.open(encoding="utf-8") as f:
                p: dict[str, Any] | None = json.load(f)
            if not isinstance(p, dict):
                p = None
        except Exception:
            p = None

        # Fail closed on a broken file (security-gates.spec.md, policy engine requirement 7):
        # a file the validator rejects blocks within its readable scope -- its declared hook
        # and applies_to when those parse, every hook and role when the JSON itself does not --
        # attributed to the file so the audit/trace record names what to fix.
        error = "unreadable JSON" if p is None else _validate_doc(p, path.name)
        if error:
            declared_hook = (p or {}).get("hook")
            hooks = {declared_hook} if declared_hook in VALID_HOOKS else VALID_HOOKS
            raw_applies = (p or {}).get("applies_to")
            applies = raw_applies if isinstance(raw_applies, list) and raw_applies else ["*"]
            if trusted and p is not None and p.get("id") in _INJECTION_IDS:
                continue
            if hook in hooks and ("*" in applies or role in applies):
                consider(
                    "block",
                    path.name,
                    f"policy file {path.name} is broken ({error}); failing closed",
                )
            continue

        assert p is not None  # a None p always carries an error above
        if p.get("hook") != hook:
            continue
        applies = p.get("applies_to", []) or []
        if "*" not in applies and role not in applies:
            continue
        if trusted and p.get("id") in _INJECTION_IDS:
            continue
        pattern = str((p.get("match") or {}).get("pattern", ""))
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            consider(
                str(p.get("action", "allow")),
                str(p.get("id", "")),
                str(p.get("message", "")),
            )

    return best


def policy_eval(role: str, hook: str, text: str, *, trusted: bool = False) -> str:
    """Return the winning action for (role, hook, text); most restrictive wins.

    Thin wrapper over :func:`policy_eval_detail` for callers that only need the action, kept so
    every existing caller/test is unaffected."""
    return policy_eval_detail(role, hook, text, trusted=trusted).action


def policy_test(hook: str, role: str, text: str) -> str:
    """Dry-run the evaluator (no trace emission)."""
    return policy_eval(role, hook, text)


@dataclass
class PolicyInstallResult:
    """Outcome of :func:`install_policies` — one entry per shipped template, in template order.

    ``entries`` preserves the exact iteration order the caller renders in, so a UI layer can
    render an interleaved "installed: x / skip (exists): y" list matching that order, rather than
    two separately-sorted groups."""

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
    if that distinction matters to the caller. Pure logic, no UI: this is the shared producer
    behind both ``docket policies init`` and `the workstation foundation bootstrap`'s own
    policy-provisioning step, so the two can never drift on what "installed" means."""
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
