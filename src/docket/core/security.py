"""Security-gate logic — pure assembly of exec-approval config.

docket configures; the OpenClaw daemon enforces. These helpers build the
exec-approval config and decide what to seed, returning structured results
the CLI renders. All openclaw-owned reads/writes — exec-approvals.json, the
daemon ``openclaw approvals set`` apply, approvals.exec routing, and the
sandbox-isolation config — go through the ACL (``edges/adapters/openclaw.py``).

This module owns only the pure assembly: resolving the curated safe-bin
allowlist to absolute paths and merging it into the exec-approval document while
preserving existing config.
"""

from __future__ import annotations

import os
import re
import shutil
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from docket.edges.adapters import openclaw as _oc

# Curated set of common, lower-risk binaries that skip the approval prompt.
# Destructive/sensitive bins (rm, dd, docker, systemctl, ...) and shell
# interpreters are deliberately OMITTED so they fall through the allowlist gate.
# NOTE: a bin listed here can still be excluded from the *seeded* allowlist at
# runtime if it also appears in a HIGH_RISK_PATTERNS class's `bins` — see
# `high_risk_bins()` / `resolve_safe_bin_paths()` below.
SAFE_BINS: tuple[str, ...] = (
    "ls", "cat", "head", "tail", "wc", "sort", "uniq", "cut", "tr", "nl",
    "grep", "egrep", "rg", "fd", "find", "file", "stat", "tree", "realpath",
    "dirname", "basename",
    "sed", "awk", "jq", "yq", "diff", "comm",
    "git", "node", "npm", "npx", "pnpm", "yarn", "python3", "pip", "pip3",
    "go", "cargo", "rustc", "make", "cmake",
    "date", "env", "printf", "which", "xargs", "tee", "less",
    "mkdir", "touch", "cp", "mv", "ln",
)  # fmt: skip


@dataclass(frozen=True)
class HighRiskClass:
    """A named, documented high-risk action class.

    ``pattern`` is a case-insensitive regex matched against a full command
    string (e.g. ``"git push origin production"``), not just a binary name —
    the daemon's exec-allowlist can only gate by binary path (confirmed via
    ``openclaw approvals allowlist --help``: entries are bare glob paths like
    ``/usr/bin/uptime``, with no argument-aware matching and no denylist
    concept). Because of that, the only way to *honestly* guarantee a
    high-risk invocation of an otherwise-curated binary always asks is to
    never admit that binary into the seeded allowlist at all — ``bins`` names
    exactly the SAFE_BINS members this class can be performed through, and
    `high_risk_bins()` / `resolve_safe_bin_paths()` exclude them wholesale.
    ``pattern`` remains useful on its own via `match_high_risk`/`is_high_risk`
    for any caller that has an actual command string to classify.
    """

    name: str
    description: str
    pattern: str
    bins: tuple[str, ...] = ()


# Seed list of high-risk action classes: money-movement, prod-deploy, and
# secret-access. Intentionally small and named — a policy foundation, not
# exhaustive coverage. Not user-configurable yet (see FD-3 "out of scope");
# a config-file override is a natural follow-up.
HIGH_RISK_PATTERNS: tuple[HighRiskClass, ...] = (
    HighRiskClass(
        name="money-movement",
        description="Payment/financial operations: charges, refunds, payouts, transfers",
        pattern=(
            r"\bstripe\b|\bpaypal\b|\bbraintree\b|charge\s+customer|refund.*amount"
            r"|wire\s+transfer|bank\s+transfer|\bpayout\b"
        ),
    ),
    HighRiskClass(
        name="prod-deploy",
        description="Production deploys and release pushes",
        pattern=(
            r"git\s+push\s+.*\b(main|master|production|prod)\b|npm\s+publish"
            r"|docker\s+(push|stop)\b|terraform\s+apply|kubectl\s+(apply|delete|rollout)"
            r"|helm\s+upgrade"
        ),
        bins=("git", "npm"),
    ),
    HighRiskClass(
        name="secret-access",
        description="Secret/credential writes and key generation",
        pattern=(
            r"vault\s+(write|kv\s+put)|ssh-keygen|openssl\s+genrsa"
            r"|kubectl\s+(create|apply).*secret|aws.*secretsmanager.*put-secret"
        ),
    ),
)


def high_risk_bins() -> frozenset[str]:
    """SAFE_BINS members capable of performing a high-risk action class.

    These are excluded from the seeded exec allowlist regardless of their
    SAFE_BINS membership (see `resolve_safe_bin_paths`) — allowlist status
    must never bypass a high-risk match.
    """
    out: set[str] = set()
    for cls in HIGH_RISK_PATTERNS:
        out.update(cls.bins)
    return frozenset(out)


def match_high_risk(command: str) -> HighRiskClass | None:
    """Return the first HIGH_RISK_PATTERNS class matching *command*, else None."""
    for cls in HIGH_RISK_PATTERNS:
        if re.search(cls.pattern, command, re.IGNORECASE):
            return cls
    return None


def is_high_risk(command: str) -> bool:
    """True if *command* matches any HIGH_RISK_PATTERNS class."""
    return match_high_risk(command) is not None


def resolve_command_action(command: str, allowlist_paths: Sequence[str] = ()) -> str:
    """Decide "ask" vs "allow" for one command string.

    A high-risk pattern match ALWAYS forces "ask", regardless of whether the
    invoked binary's resolved path appears in *allowlist_paths* — allowlist
    status must never bypass a high-risk match. In practice
    `resolve_safe_bin_paths` never admits a high-risk-capable bin into
    *allowlist_paths* to begin with, so this mirrors the same invariant at
    the single-command granularity, for any caller (tests, future dispatch-
    time checks) that has a live command string to classify.
    """
    if is_high_risk(command):
        return "ask"
    command = command.strip()
    if not command:
        return "ask"
    invoked = command.split()[0]
    for path in allowlist_paths:
        if path == invoked or os.path.basename(path) == os.path.basename(invoked):
            return "allow"
    return "ask"


@dataclass
class GateResult:
    """Outcome of applying exec-approval gates."""

    mode: str  # "applied-via-daemon" | "applied-direct"
    defaults_changed: bool
    seeded: list[str] = field(default_factory=list)
    bins: int = 0


def resolve_safe_bin_paths() -> list[str]:
    """Resolve the curated safe bins to absolute, symlink-resolved paths.

    Bins that are not on PATH are skipped (Bash ``command -v ... || continue``).
    Bins in `high_risk_bins()` (e.g. ``git``, ``npm``) are skipped even though
    they're SAFE_BINS members — the daemon's allowlist gates by binary path,
    not argument text, so a high-risk-capable binary can never be blanket-
    admitted without silently letting its high-risk invocations skip approval.
    """
    excluded = high_risk_bins()
    paths: list[str] = []
    for name in SAFE_BINS:
        if name in excluded:
            continue
        resolved = shutil.which(name)
        if not resolved:
            continue
        paths.append(os.path.realpath(resolved))
    return paths


def _make_allowlist(paths: list[str]) -> list[dict[str, str]]:
    return [{"id": str(uuid.uuid4()), "pattern": p} for p in paths]


def build_exec_approvals(
    existing: dict[str, Any],
    paths: list[str],
    agent_ids: list[str],
    *,
    force: bool,
) -> tuple[dict[str, Any], bool, list[str]]:
    """Merge curated gate defaults + per-agent allowlists into *existing*.

    Returns (merged_doc, defaults_changed, seeded_ids). Existing config
    (version / socket / agents) is preserved; defaults are only overwritten when
    empty unless *force*.
    """
    data: dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
    data.setdefault("version", 1)  # socket (if present) preserved untouched

    defaults = data.get("defaults") or {}
    defaults_changed = False
    if not defaults or force:
        data["defaults"] = {
            "security": "allowlist",
            "ask": "on-miss",
            "askFallback": "deny",
            "autoAllowSkills": False,
        }
        defaults_changed = True
    else:
        data["defaults"] = defaults

    agents = data.get("agents") or {}
    if not isinstance(agents, dict):
        agents = {}
    # Dedupe, ensure 'main' is present (dict.fromkeys keeps first-seen order).
    ids = list(dict.fromkeys([*agent_ids, "main"]))
    seeded: list[str] = []
    for aid in ids:
        a = agents.get(aid) or {}
        if not isinstance(a, dict):
            a = {}
        if not a.get("allowlist") or force:
            a["security"] = a.get("security") or "allowlist"
            a["ask"] = a.get("ask") or "on-miss"
            a["askFallback"] = a.get("askFallback") or "deny"
            a["allowlist"] = _make_allowlist(paths)
            seeded.append(aid)
        agents[aid] = a
    data["agents"] = agents
    return data, defaults_changed, seeded


def apply_exec_approval_gates(force: bool = False) -> GateResult:
    """Apply conservative exec-approval enforcement (opt-in).

    Writes defaults {security: allowlist, ask: on-miss, askFallback: deny} and
    seeds each agent the curated safe-bin allowlist. The merged file is applied
    via the daemon when reachable, else written directly.
    """
    paths = resolve_safe_bin_paths()
    existing = _oc.read_exec_approvals()
    agent_ids = _oc.all_agent_ids()

    merged, defaults_changed, seeded = build_exec_approvals(existing, paths, agent_ids, force=force)
    via_daemon = _oc.write_exec_approvals(merged)
    return GateResult(
        mode="applied-via-daemon" if via_daemon else "applied-direct",
        defaults_changed=defaults_changed,
        seeded=seeded,
        bins=len(paths),
    )


def disable_exec_approval_gates() -> bool:
    """Reset exec-approval defaults to empty so the daemon falls back to tools.exec.

    Returns False when there is nothing to disable (no exec-approvals file).
    Seeded allowlists are left in place.
    """
    if not _oc.exec_approvals_path().exists():
        return False
    data = _oc.read_exec_approvals()
    data["defaults"] = {}
    _oc.write_exec_approvals(data)
    return True


def apply_approval_routing() -> int:
    """Route exec-approval prompts to each agent's session channel.

    Writes approvals.exec = {enabled, mode:session}. Returns the count of
    Telegram-bound agents (informational).
    """
    _oc.set_approval_routing(enabled=True, mode="session")
    count = 0
    for aid in _oc.all_agent_ids():
        if _oc.get_binding(aid):
            count += 1
    return count


def disable_approval_routing() -> None:
    """Turn approval forwarding off (approvals.exec.enabled=false)."""
    _oc.disable_approval_routing()


def apply_workspace_isolation() -> None:
    """Enable per-agent Docker sandbox for non-main sessions.

    The Docker capability check and gateway restart are the caller's responsibility.
    """
    _oc.set_sandbox_isolation(mode="non-main", scope="agent", workspace_access="rw")


def disable_workspace_isolation() -> None:
    """Turn sandbox isolation off (mode: off)."""
    _oc.disable_sandbox_isolation()
