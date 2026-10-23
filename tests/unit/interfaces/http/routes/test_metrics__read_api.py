"""Stable read API — contract shape pinning.

These tests are the machine-readable counterpart to specs/data/serve-read-api.spec.md.
Any test break here is a breaking API change and must bump SERVE_API_VERSION.

Acceptance criteria:
  - /status.json emits a documented, versioned shape
  - /metrics emits a documented set of metric names
  - The contract spec file exists
  - suite green
"""

from __future__ import annotations

SUBJECT = "docket.interfaces.http.routes.metrics"
