"""Pod targeting: the one place a command learns which pod it acts on."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import typer

import docket.config as _cfg
from docket.core.utils import project_ids
from docket.edges import store

POD_OPTION_HELP = (
    "Pod name; default: DOCKET_POD, then the pod whose codebase contains the current directory"
)


class TargetError(Exception):
    """No single pod could be chosen."""


def pod_option() -> Any:
    return typer.Option(None, "--pod", "-p", help=POD_OPTION_HELP)


def _pod_for_directory(directory: Path) -> tuple[str | None, list[str]]:
    """Resolve the most-specific registered pod containing ``directory``. Metadata is
    the authority: every member repeats the same codebase/workDir, so results dedup
    by pod id; a nested cwd chooses the longest matching root."""
    try:
        cwd = directory.expanduser().resolve()
    except OSError:
        cwd = directory.expanduser().absolute()

    matches: dict[str, int] = {}
    for aid in project_ids():
        raw = store.read_json(_cfg.meta_path(aid))
        pod_id = str(raw.get("pod", ""))
        if not pod_id:
            continue
        root_s = str(raw.get("workDir") or raw.get("codebase") or "")
        if not root_s:
            continue
        try:
            root = Path(root_s).expanduser().resolve()
            cwd.relative_to(root)
        except (OSError, ValueError):
            continue
        matches[pod_id] = max(matches.get(pod_id, 0), len(root.parts))

    if not matches:
        return None, []
    best_depth = max(matches.values())
    best = sorted(project for project, depth in matches.items() if depth == best_depth)
    return (best[0] if len(best) == 1 else None), best


def resolve_pod(explicit: str | None, *, env: Mapping[str, str], cwd: Path) -> str:
    """Return the pod name: ``--pod``, then ``DOCKET_POD``, then the deepest registered
    codebase containing ``cwd``. Raises ``TargetError`` when none or several match."""
    if explicit:
        return explicit
    named = env.get("DOCKET_POD", "").strip()
    if named:
        return named
    pod, matches = _pod_for_directory(cwd)
    if pod is not None:
        return pod
    if matches:
        raise TargetError(
            f"Several pods match {cwd} at the same depth: {', '.join(matches)}. Pass --pod <name>."
        )
    raise TargetError(
        f"No pod for {cwd} (looked for a registered codebase containing it). "
        "Run 'docket init' here, or pass --pod <name>."
    )
