"""Command: serve — local HTTP endpoints for dashboards / monitoring.

Endpoint list, JSON/Prometheus schemas, and the auth model per endpoint: see
specs/data/serve-read-api.spec.md. Binds to 127.0.0.1 by default; ``run_serve``'s ``bind`` can
widen that, but nothing here recommends or automates it -- treat any non-loopback bind as an
explicit, on-you decision (no network ACL here, only the bearer token). A random Bearer token
(``DOCKET_SERVE_TOKEN`` pins a fixed one) gates every /approvals, /runs, /tasks, /traces, /pods
and /dispatch request, checked with ``secrets.compare_digest`` (never ``==``); printed at startup
or written to a 0600 file via ``--token-file``/``token_file=`` when stdout is unsafe (e.g. a
systemd journal).
Every dispatch is recorded in ``core.runs`` before it starts and folded to a terminal state when it
finishes, so "done"/"failed"/"never ran" stay distinguishable; no call site swallows it silently."""

from __future__ import annotations
