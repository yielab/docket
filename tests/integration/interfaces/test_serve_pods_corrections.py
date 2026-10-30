"""GET /pods/<p>/corrections: the corrections ledger over HTTP, cursored by `since`."""

from __future__ import annotations

from urllib.parse import quote

from tests.support import http as _support_http
from tests.support import pods as _support_pods
from tests.support.http import get as _get

from docket.tasks.application import corrections as _corrections
from docket.teams import pod_provisioning as _pp

live_server = _support_http.live_server

pod_home = _support_pods.pod_home

SUBJECT = "docket.interfaces.http.server"

_TEST_TOKEN = "test-serve-token"
_TS = ["2026-10-01T10:00:00+00:00", "2026-10-01T10:00:05+00:00", "2026-10-01T10:00:09+00:00"]


def _record_three(project: str) -> None:
    for i, ts in enumerate(_TS):
        _corrections.record(
            project,
            "deny_reason",
            task_id=f"job-{i}",
            role="reviewer",
            text=f"reason {i}",
            source="cli",
            _now=ts,
        )


def test_corrections_since_filters_by_timestamp(live_server: tuple[str, str]) -> None:
    """`since` returns only records after the cursor, and `next` is the last returned ts."""
    url, token = live_server
    _pp.provision_pod("demo", "build", location="/src/demo")
    _record_three("demo")

    status, body = _get(f"{url}/pods/demo/corrections?since={quote(_TS[1])}", token)
    assert status == 200
    assert [c["taskId"] for c in body["corrections"]] == ["job-2"]
    assert body["next"] == "2026-10-01T10:00:09Z"

    status, body = _get(f"{url}/pods/demo/corrections", token)
    assert status == 200
    assert [c["taskId"] for c in body["corrections"]] == ["job-0", "job-1", "job-2"]
    assert body["next"] == "2026-10-01T10:00:09Z"


def test_corrections_next_keeps_cursor_when_nothing_is_new(live_server: tuple[str, str]) -> None:
    """With nothing after `since`, the body is empty and `next` echoes the given cursor."""
    url, token = live_server
    _pp.provision_pod("demo", "build", location="/src/demo")
    _record_three("demo")

    status, body = _get(f"{url}/pods/demo/corrections?since={quote(_TS[2])}", token)
    assert status == 200
    assert body == {"corrections": [], "next": "2026-10-01T10:00:09Z"}


def test_pod_without_ledger_returns_empty_list(live_server: tuple[str, str]) -> None:
    """A provisioned pod with no corrections ledger answers an empty list, not an error."""
    url, token = live_server
    _pp.provision_pod("quiet", "build", location="/src/quiet")

    status, body = _get(f"{url}/pods/quiet/corrections", token)
    assert status == 200
    assert body == {"corrections": [], "next": ""}


def test_unknown_pod_returns_404(live_server: tuple[str, str]) -> None:
    """A pod that was never provisioned answers 404."""
    url, token = live_server

    status, body = _get(f"{url}/pods/ghost/corrections", token)
    assert status == 404
    assert body["ok"] is False


def test_bad_since_returns_400(live_server: tuple[str, str]) -> None:
    """A `since` that is not an ISO-8601 timestamp answers 400."""
    url, token = live_server
    _pp.provision_pod("demo", "build", location="/src/demo")

    status, body = _get(f"{url}/pods/demo/corrections?since=yesterday", token)
    assert status == 400
    assert body["ok"] is False


def test_corrections_without_token_returns_401(live_server: tuple[str, str]) -> None:
    """The corrections route requires the bearer token."""
    url, _ = live_server

    status, body = _get(f"{url}/pods/demo/corrections")
    assert status == 401
    assert body["ok"] is False


def test_offset_since_is_normalised_to_utc(live_server: tuple[str, str]) -> None:
    """A `since` with an offset selects the same records, and the same next, as its UTC instant."""
    url, token = live_server
    _pp.provision_pod("demo", "build", location="/src/demo")
    _record_three("demo")

    _, utc = _get(f"{url}/pods/demo/corrections?since=2026-10-01T10:00:05Z", token)
    status, offset = _get(f"{url}/pods/demo/corrections?since=2026-10-01T12:00:05%2B02:00", token)
    assert status == 200
    assert offset == utc
    assert [c["taskId"] for c in offset["corrections"]] == ["job-2"]


def test_since_compares_sub_second_records_by_instant(live_server: tuple[str, str]) -> None:
    """A record half a second after `since` is delivered, not dropped by a string compare."""
    url, token = live_server
    _pp.provision_pod("demo", "build", location="/src/demo")
    _corrections.record(
        "demo",
        "deny_reason",
        task_id="job-half",
        role="reviewer",
        text="reason",
        source="cli",
        _now="2026-10-01T10:00:00.500000+00:00",
    )

    status, body = _get(f"{url}/pods/demo/corrections?since=2026-10-01T10:00:00Z", token)
    assert status == 200
    assert [c["taskId"] for c in body["corrections"]] == ["job-half"]


def test_naive_since_returns_400(live_server: tuple[str, str]) -> None:
    """A `since` with no offset is refused, not compared as if it were UTC."""
    url, token = live_server
    _pp.provision_pod("demo", "build", location="/src/demo")

    status, body = _get(f"{url}/pods/demo/corrections?since=2026-10-01T10:00:05", token)
    assert status == 400
    assert body["ok"] is False
