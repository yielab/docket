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
# NOTE: a bin listed here (e.g. git, npm) can still have a HIGH_RISK_PATTERNS
# class attached for documentation/visibility (`docket gates classes`) — that
# does NOT exclude it from the seeded allowlist. See `high_risk_bins()`'s
# docstring for why: the daemon's allowlist gates by binary path, not
# argument text, so excluding a whole bin would also block its benign uses.
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
    string (e.g. ``"git push origin production"``), not just a binary name.

    ``bins`` names the SAFE_BINS members this class can be performed through,
    for documentation/visibility only (``docket gates classes``) — it does
    **not** exclude them from the seeded allowlist. The daemon's exec-
    allowlist can only gate by binary path (confirmed via
    ``openclaw approvals allowlist --help``: entries are bare glob paths like
    ``/usr/bin/uptime``, with no argument-aware matching and no denylist
    concept), so it genuinely cannot tell ``git push origin main`` apart from
    ``git status``. Excluding a bin like ``git``/``npm`` wholesale to force
    its high-risk invocations to ask would also force every benign invocation
    to ask — an unacceptable usability regression for tools used constantly.
    Per-argument enforcement of these classes is deferred pending a daemon-
    side capability that doesn't exist today (tracked as a backlog item,
    similar to the deferred S2 redaction work). ``match_high_risk``/
    ``is_high_risk``/``resolve_command_action`` remain useful now for any
    caller that has an actual command string to classify (tests, a future
    daemon hook, or docket's own subprocess call sites).
    """

    name: str
    description: str
    pattern: str
    bins: tuple[str, ...] = ()


# Seed list of high-risk action classes: money-movement, prod-deploy, and
# secret-access. Intentionally small and named — a policy foundation, not
# exhaustive coverage. Not user-configurable yet (see FD-3 "out of scope");
# a config-file override is a natural follow-up. NOTE: matching these
# patterns is currently advisory/visible only for classes whose bins overlap
# SAFE_BINS (git, npm) — see HighRiskClass's docstring for why full
# enforcement needs a daemon capability that doesn't exist yet. Classes with
# no SAFE_BINS overlap (money-movement, secret-access) are already fully
# enforced today, since their bins were never allowlisted to begin with.
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
    """SAFE_BINS members named by a HIGH_RISK_PATTERNS class, for visibility only.

    NOT used to exclude anything from the seeded exec allowlist (see
    HighRiskClass's docstring) — ``resolve_safe_bin_paths`` seeds these bins
    normally. Exposed for ``docket gates classes`` and for any future caller
    that wants to know which curated bins have a high-risk class attached.
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
    status must never bypass a high-risk match, for any caller that has an
    actual live command string to classify (tests, a future daemon hook, or
    docket's own subprocess call sites). This is the mechanism available
    *today*; it is not currently wired into the daemon's own allowlist gate,
    which can only key on binary path (see HighRiskClass's docstring) — so a
    live agent invocation of ``git``/``npm`` is not yet gated through this
    function at daemon-approval time.
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
    Every SAFE_BINS member is seeded here, including ``git``/``npm`` — see
    `high_risk_bins()`'s docstring for why they are *not* excluded despite
    having an attached HIGH_RISK_PATTERNS class.
    """
    paths: list[str] = []
    for name in SAFE_BINS:
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
