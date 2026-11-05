"""Whether a pod's declared search service answers: one ``GET`` of its base URL, informational."""

from __future__ import annotations

from docket.kernel.service import ServiceConfig
from docket.platform.service_http import ServiceRequest, call_operation
from docket.teams import services as _services

# How long the search service has to answer a `GET` of its base URL.
PROBE_TIMEOUT_S = 2.0


def search_service(project: str) -> ServiceConfig | None:
    """The service named ``search`` that *project* resolves (its own, else the operator's)."""
    return next(
        (s for s in _services.load_services(project) if s.name == _services.SEARCH_SERVICE), None
    )


def service_answers(config: ServiceConfig) -> bool:
    """True when a ``GET`` of *config*'s base URL gets any HTTP status within ``PROBE_TIMEOUT_S``.
    It sends no credential; a refusal, a timeout or a failed connection is no answer."""
    outcome = call_operation(
        ServiceRequest(
            method="GET",
            base_url=config.baseUrl,
            hosts=tuple(config.hosts),
            timeout=PROBE_TIMEOUT_S,
        )
    )
    return outcome.ok or (not outcome.refusal and outcome.error.startswith("HTTP "))
