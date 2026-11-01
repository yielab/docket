"""A pod that meets the lights-out profile (isolation on, network `none`, `consultMode: decide`)
still reaches a declared loopback service, because docket's own process makes the call; a service
whose host the document does not list is refused by the perimeter, and both calls are audited."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest
from tests.support.llm import RecordingScriptedBackend as _ScriptedBackend
from tests.support.llm import final as _final
from tests.support.llm import tool_calls as _tool_calls
from tests.support.loopback import RecordingHandler, recording_service
from tests.support.pods import build_pod
from tests.support.trace import audit_entries, trace_events
from tests.support.turns import tool_replies

from docket.hops.application.driver import DocketDriver
from docket.hops.gates import profile as _profile
from docket.kernel.service import ServiceConfig
from docket.sandbox import landlock
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod
from docket.teams import pod_settings as _pod_settings
from docket.teams import services as _services

SUBJECT = "docket.platform.service_http"

pytestmark = pytest.mark.skipif(
    not landlock.landlock_available(), reason="landlock is not available on this host"
)


class _Second(RecordingHandler):
    seen: ClassVar[list[dict[str, Any]]] = []


@contextmanager
def _second_loopback() -> Iterator[tuple[int, list[dict[str, Any]]]]:
    """A listener on 127.0.0.2 recording what it was sent; yields its port and the requests."""
    _Second.seen = []
    httpd = ThreadingHTTPServer(("127.0.0.2", 0), _Second)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[1], _Second.seen
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _service(name: str, base: str, hosts: list[str]) -> ServiceConfig:
    return ServiceConfig.model_validate(
        {
            "name": name,
            "baseUrl": base,
            "hosts": hosts,
            "operations": [
                {
                    "name": "get_contact",
                    "method": "GET",
                    "path": "/contacts/{id}",
                    "params": [{"name": "id", "in": "path", "type": "integer"}],
                }
            ],
        }
    )


@pytest.fixture
def lights_out_pod(tmp_path: Path) -> str:
    """A pod `demo` whose profile has no violation: isolation on, network none, decide."""
    code = tmp_path / "code"
    code.mkdir()
    _fleet.set_sandbox_isolation("on")
    _fleet.set_network_mode("none")
    _fleet.set_profile("lights-out")
    build_pod("demo", _pod.DEFAULT_POD_ROLES, codebase=str(code))
    _fleet.meta_set(
        "demo-lead", "consultMode", _pod_settings.PodSettings.coerce("consultMode", "decide")
    )
    return "demo-implementer"


def test_the_pod_passes_the_lights_out_profile(lights_out_pod: str) -> None:
    assert _profile.project_violations("demo", ()) == []


def test_a_listed_loopback_service_is_reached_and_an_unlisted_one_is_refused(
    lights_out_pod: str,
) -> None:
    with recording_service() as (base, seen), _second_loopback() as (port, other_seen):
        _services.add_service(_service("local", base, ["127.0.0.1"]))
        _services.add_service(_service("other", f"http://127.0.0.2:{port}", []))
        backend = _ScriptedBackend(
            [
                _tool_calls(
                    ("svc__local__get_contact", {"id": 7}),
                    ("svc__other__get_contact", {"id": 8}),
                ),
                _final("done"),
            ]
        )

        res = DocketDriver(backend_factory=lambda model: backend).run_turn(
            lights_out_pod, f"agent:{lights_out_pod}:default", "go", 60
        )

    assert res.ok, res.error
    assert [(s["method"], s["path"]) for s in seen] == [("GET", "/contacts/7")]
    assert other_seen == []
    reached, refused = tool_replies(backend)
    assert '"name":"Ana"' in reached
    assert "127.0.0.2" in refused and "hosts" in refused
    results = [e for e in trace_events("demo") if e["event_type"] == "tool_result"]
    assert [(e["payload"]["tool"], e["payload"]["ok"]) for e in results] == [
        ("svc__local__get_contact", True),
        ("svc__other__get_contact", False),
    ]
    (row,) = audit_entries("tool.refused")
    assert "tool=svc__other__get_contact" in row["detail"]
    assert "kind=service_not_allowed method=GET host='127.0.0.2'" in row["detail"]
