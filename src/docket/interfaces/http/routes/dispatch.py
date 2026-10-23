"""``POST /dispatch/<pod>`` -- start a pod's pipeline from a webhook, recorded in the run registry."""

from __future__ import annotations

import json

from docket.governance import audit as _audit
from docket.interfaces.http.exchange import HttpExchange
from docket.kernel import threads as _threads
from docket.kernel.home import current_home
from docket.pipeline.application import steps as _steps
from docket.pipeline.domain import spec as _pipeline
from docket.tasks.application import runs as _runs
from docket.tasks.application import sweep as _sweep
from docket.tasks.domain import task as _task


def post_dispatch(h: HttpExchange, project: str) -> None:
    if not project:
        h._send_json_error("Missing project", 400)
        return
    if h._reject_bad_project_id(project):
        return

    # The request body (a plain {name: value} JSON object) is the
    # webhook's params — bound into the pod's effective pipeline's
    # declared `variables` namespace (pipeline.domain.spec.resolve_variables)
    # before anything is dispatched. A missing body (no Content-Length)
    # is the same as `{}`, so an omitted body still behaves as a
    # no-params dispatch.
    params = h._read_json_object()
    if params is None:
        return
    try:
        effective = _steps.effective_pipeline(project, None)
        variables = _pipeline.resolve_variables(effective, params)
    except _pipeline.VariableError as exc:
        h._send_json_error(str(exc), 400)
        return
    except _task.DispatchError as exc:
        msg = str(exc)
        h._send_json_error(msg, 404 if msg.startswith("no pod for") else 400)
        return

    # The run record is created — and its id handed back to
    # the caller — BEFORE any dispatch work is attempted. The actual
    # pipeline still runs async (this endpoint must not block on a real
    # agent turn), but its outcome always lands in the run registry
    # instead of vanishing behind a fire-and-forget thread.
    record = _runs.create_run("webhook", project, variables=variables)
    _audit.audit_log("run.dispatch", f"run={record['id']} project={project} channel=http")

    def _run(proj: str = project, run_id: str = record["id"]) -> None:
        _runs.execute(
            run_id,
            lambda: _sweep.dispatch_pod(
                proj,
                turn_timeout=current_home().dispatch_turn_timeout_s,
                verify_timeout=current_home().dispatch_verify_timeout_s,
                variables=variables,
            ),
        )

    _threads.start_thread(_run)
    resp_body = json.dumps(
        {"ok": True, "run": record["id"], "project": project, "status": "dispatched"}
    ).encode()
    h._send(resp_body, "application/json")
