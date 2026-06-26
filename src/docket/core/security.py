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
import shutil
import uuid
from dataclasses import dataclass, field
from typing import Any

from docket.edges.adapters import openclaw as _oc

# Curated set of common, lower-risk binaries that skip the approval prompt.
# Destructive/sensitive bins (rm, dd, docker, systemctl, ...) and shell
# interpreters are deliberately OMITTED so they fall through the allowlist gate.
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
