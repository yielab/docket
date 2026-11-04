"""``POST /pods/<pod>/apply`` -- apply a directory on this machine to a pod."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from docket.governance import audit as _audit
from docket.interfaces.http.exchange import HttpExchange
from docket.tasks.application import queue as _queue
from docket.teams import fleet
from docket.teams import pod as _pod_core
from docket.teams.apply import model as _model
from docket.teams.apply import plan as _pod_apply
from docket.teams.apply import review as _review


def post_pod_apply(h: HttpExchange, project: str) -> None:
    """Apply a directory on this machine to a pod, under the review rule of ADR 0024
    section 6 (operator-api.spec.md)."""
    if h._reject_bad_project_id(project):
        return
    if project not in _queue.dispatchable_pods():
        h._send_json_error(f"Unknown pod: {project}", 404)
        return
    body = h._read_json_object(blank=True)
    if body is None:
        return
    lead = _pod_core.member_id(project, "lead")
    workdir = _review.is_workdir(project)
    root_value = fleet.meta_get(lead, "workDir" if workdir else "codebase", "")
    if not root_value:
        recorded = "workDir" if workdir else "codebase"
        h._send_json_error(
            f"pod {project} has no recorded {recorded}; docket pod update reviews a "
            "directory against the repository the pod was made from",
            400,
        )
        return
    root = Path(root_value)
    directory_value = body.get("directory")
    dry_run, accept = body.get("dryRun", False), body.get("accept")
    if directory_value is not None and not isinstance(directory_value, str):
        h._send_json_error("directory must be a string", 400)
        return
    if not isinstance(dry_run, bool) or not (accept is None or isinstance(accept, str)):
        h._send_json_error("dryRun must be a boolean and accept a string", 400)
        return
    if directory_value is None and workdir:
        h._send_json_error(
            f"directory is required: pod '{project}' works in a folder and has no repository "
            "to read .docket/ from",
            400,
        )
        return
    if directory_value is None:
        directory_value = str(_review.repo_config_dir(root, project))
    elif not Path(directory_value).is_absolute():
        h._send_json_error("directory must be an absolute path", 400)
        return
    directory = Path(directory_value)
    if not directory_value or not directory.is_dir():
        h._send_json_error(f"directory not found: {directory_value}", 400)
        return
    try:
        outcome = _pod_apply.apply_directory(
            project, directory, root, accept=accept, dry_run=dry_run, channel="http"
        )
    except _model.PodApplyError as exc:
        h._send_json_error(str(exc), 400)
        return
    if outcome.status == "refused":
        names = ", ".join(outcome.refused)
        h._send_json_error(f"allowCommands names refused commands: {names}", 409)
    elif outcome.status in ("needs_code", "code_mismatch"):
        payload: dict[str, Any] = {"ok": False}
        if outcome.status == "needs_code":
            payload["error"] = "this directory runs commands on this machine; pass accept"
            payload["reviewCode"] = outcome.code
        else:
            payload["error"] = "the directory changed what runs on this machine since that code"
        payload["runs"] = [asdict(i) for i in outcome.runs]
        h._send_json(payload, 409)
    else:
        if outcome.status == "applied" and not any(i.action != "skip" for i in outcome.items):
            _audit.audit_log(
                "pod.apply",
                f"project={project} dir={directory} "
                f"items={';'.join(f'{i.kind}:{i.name}:{i.action}' for i in outcome.items)} "
                f"channel=http changed=0 skipped={len(outcome.items)}",
            )
        h._send_json(
            {
                "ok": True,
                "project": project,
                "items": [asdict(i) for i in outcome.items],
                "dryRun": outcome.status == "planned",
            }
        )
