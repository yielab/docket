"""What models asks of its own adapters, bound once per entry (``bootstrap.bind_adapters``).

Provider registration probes a ``/models`` route; the socket work is the adapter's, and the
application layer names only the shape of the answer.
"""

from __future__ import annotations

from typing import Protocol

from docket.agent.ports import Endpoint
from docket.kernel.ports import Binding
from docket.models.application.probe import ProbeResult


class EndpointProber(Protocol):
    def probe_models(self, endpoint: Endpoint, timeout: float = 5.0) -> ProbeResult:
        """GET ``<base-url>/models`` with the endpoint's own credential headers; never raises."""
        ...


endpoint_prober_port: Binding[EndpointProber] = Binding("endpoint_prober")
endpoint_prober: EndpointProber = endpoint_prober_port.proxy()


def bind_endpoint_prober(adapter: EndpointProber) -> None:
    endpoint_prober_port.bind(adapter)
