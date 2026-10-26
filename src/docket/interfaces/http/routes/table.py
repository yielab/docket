"""The route table: every ``(method, pattern)`` the server answers, in match order.

Authentication is a column here, not a line inside each handler: a row with ``auth`` has its
Bearer token checked (``interfaces.http.auth``) before the handler runs. Order matters because the
first match wins -- ``/tasks/<pod>/<id>/diff`` has to come before ``/tasks/<pod>``, which would
swallow it. The startup banner lists these rows, so a new route shows up there by being added here."""

from __future__ import annotations

from docket.interfaces.http.routes import (
    a2a,
    dispatch,
    escalations,
    health,
    inbox,
    metrics,
    pod_apply,
    pod_create,
    pods,
    runs,
    task_control,
    task_create,
    tasks,
    traces,
)
from docket.interfaces.http.routing import Route

GET_ROUTES: tuple[Route, ...] = (
    Route("GET", "/status.json", health.get_status, auth=False),
    Route("GET", "/metrics", metrics.get_metrics, auth=False),
    Route("GET", "/health", health.get_health, auth=False),
    Route("GET", "/.well-known/agent.json", a2a.get_agent_card),
    Route("GET", "/inbox", inbox.get_inbox),
    Route("GET", "/escalations", escalations.get_escalations),
    Route("GET", "/runs", runs.get_runs),
    Route("GET", "/runs/<id>", runs.get_run),
    Route("GET", "/tasks/<pod>/<id>/diff", tasks.get_task_diff, overlap=True),
    Route("GET", "/tasks/<pod>/<id>/evidence", tasks.get_task_evidence, overlap=True),
    Route("GET", "/tasks/<pod>/<id>", tasks.get_tasks, bare=True, label="/tasks/<pod>[/<id>]"),
    Route("GET", "/pods/<pod>/corrections", pods.get_pod_corrections, overlap=True),
    Route("GET", "/pods", pods.get_pods),
    Route("GET", "/pods/<pod>", pods.get_pod),
    Route("GET", "/traces/<pod>", traces.get_traces, bare=True),
)

POST_ROUTES: tuple[Route, ...] = (
    Route("POST", "/a2a", a2a.post_a2a),
    Route("POST", "/escalations/<id>", escalations.post_escalation, bare=True),
    Route("POST", "/tasks/<id>/pregrants", task_control.post_task_pregrant),
    Route("POST", "/tasks/<pod>/<id>/cancel", task_control.post_task_cancel),
    Route("POST", "/tasks/<pod>/<id>/retry", task_control.post_task_retry),
    Route("POST", "/tasks/<pod>", task_create.post_task, bare=True),
    Route("POST", "/dispatch/<pod>", dispatch.post_dispatch, bare=True),
    Route("POST", "/pods/<pod>/apply", pod_apply.post_pod_apply, overlap=True),
    Route("POST", "/pods", pod_create.post_pod),
)

ROUTES: tuple[Route, ...] = GET_ROUTES + POST_ROUTES
