"""GET /pods/<p>/memory: the pod memory over HTTP, the same elements as the CLI's list."""

from __future__ import annotations

import json
from typing import Any

from tests.support import http as _support_http
from tests.support import pods as _support_pods
from tests.support.http import get as _get
from typer.testing import CliRunner

from docket.interfaces.cli.app import app as _app
from docket.kernel.home import current_home
from docket.platform import store as _store
from docket.teams import memory as _pm
from docket.teams import pod_provisioning as _pp

live_server = _support_http.live_server

pod_home = _support_pods.pod_home

SUBJECT = "docket.interfaces.http.server"

_TEST_TOKEN = "test-serve-token"
_runner = CliRunner(env={"DOCKET_NO_HINTS": "1"})


def _entry(path: str, status: str) -> dict[str, Any]:
    return {
        "id": _pm.entry_id("pitfall", path, f"Note for {path}."),
        "kind": "pitfall",
        "subject": path,
        "note": f"Note for {path}.",
        "status": status,
        "reason": "ok" if status == "accepted" else "awaits operator approval",
        "provenance": {"task": "t1", "date": "2026-10-18", "commit": ""},
        "stale": False,
        "evidence": {},
    }


def _seed_three_statuses() -> None:
    entries = [
        _entry("dist/accepted.js", "accepted"),
        _entry("dist/pending.js", "pending"),
        _entry("dist/refused.js", "refused"),
    ]
    path = current_home().pod_memory_path("demo")
    path.parent.mkdir(parents=True, exist_ok=True)
    _store.write_json(path, {"entries": entries})


def test_memory_returns_only_the_accepted_entries_as_the_cli_lists_them(
    live_server: tuple[str, str],
) -> None:
    """Only the accepted entry is returned, and it equals the CLI's JSON element for it."""
    url, token = live_server
    _pp.provision_pod("demo", "build", location="/src/demo")
    _seed_three_statuses()

    status, body = _get(f"{url}/pods/demo/memory", token)
    assert status == 200
    assert set(body) == {"entries"}

    cli = json.loads(
        _runner.invoke(_app, ["pod", "memory", "list", "--json", "--pod", "demo"]).output
    )
    assert [e for e in cli if e["status"] == "accepted"] == body["entries"]
    assert [e["status"] for e in body["entries"]] == ["accepted"]


def test_memory_rows_carry_subject_stale_and_evidence_and_no_old_keys(
    live_server: tuple[str, str],
) -> None:
    """A tool row serves its subject, stale flag and evidence under the documented keys."""
    url, token = live_server
    _pp.provision_pod("demo", "build", location="/src/demo")
    tool = _pm.MemoryEntry(
        _pm.entry_id("tool", "pytest -q", "Runs tests."),
        "tool",
        "pytest -q",
        "Runs tests.",
        "accepted",
        "ok",
        {"task": "t1"},
        stale=False,
        evidence={"exit": 1},
    )
    path = current_home().pod_memory_path("demo")
    path.parent.mkdir(parents=True, exist_ok=True)
    _store.write_json(path, {"entries": [tool.to_dict()]})

    _, body = _get(f"{url}/pods/demo/memory", token)

    (row,) = body["entries"]
    assert (row["subject"], row["stale"], row["evidence"]) == ("pytest -q", False, {"exit": 1})
    assert not {"path", "tool", "command", "exit"} & set(row)


def test_memory_status_query_picks_the_entries_of_that_status(
    live_server: tuple[str, str],
) -> None:
    """`status=pending` serves the entries waiting for approval, oldest first, with their why."""
    url, token = live_server
    _pp.provision_pod("demo", "build", location="/src/demo")
    entries = [
        _entry("dist/accepted.js", "accepted"),
        _entry("dist/pending-a.js", "pending"),
        _entry("dist/pending-b.js", "pending"),
        _entry("dist/refused.js", "refused"),
    ]
    path = current_home().pod_memory_path("demo")
    path.parent.mkdir(parents=True, exist_ok=True)
    _store.write_json(path, {"entries": entries})

    _, default = _get(f"{url}/pods/demo/memory", token)
    assert [e["subject"] for e in default["entries"]] == ["dist/accepted.js"]

    status, pending = _get(f"{url}/pods/demo/memory?status=pending", token)
    assert status == 200
    assert [e["subject"] for e in pending["entries"]] == ["dist/pending-a.js", "dist/pending-b.js"]
    for row in pending["entries"]:
        assert row["reason"] == "awaits operator approval"
        assert row["provenance"]["task"] == "t1"

    _, refused = _get(f"{url}/pods/demo/memory?status=refused", token)
    assert [e["status"] for e in refused["entries"]] == ["refused"]


def test_memory_status_query_refuses_an_unknown_status_naming_the_three(
    live_server: tuple[str, str],
) -> None:
    """Any other `status` is a 400 that names `accepted`, `pending` and `refused`."""
    url, token = live_server
    _pp.provision_pod("demo", "build", location="/src/demo")

    status, body = _get(f"{url}/pods/demo/memory?status=stale", token)

    assert status == 400
    assert body["ok"] is False
    for name in ("accepted", "pending", "refused"):
        assert name in body["error"]


def test_memory_without_token_returns_401(live_server: tuple[str, str]) -> None:
    """The memory route requires the bearer token."""
    url, _ = live_server

    status, body = _get(f"{url}/pods/demo/memory")
    assert status == 401
    assert body["ok"] is False


def test_unknown_pod_memory_returns_404(live_server: tuple[str, str]) -> None:
    """A pod that was never provisioned answers 404."""
    url, token = live_server

    status, body = _get(f"{url}/pods/ghost/memory", token)
    assert status == 404
    assert body["ok"] is False


def test_status_and_health_list_pod_memory_feature(live_server: tuple[str, str]) -> None:
    """`/status.json` and `/health` both advertise the podMemory feature."""
    url, _ = live_server

    _, status = _get(f"{url}/status.json")
    assert "podMemory" in status["features"]

    _, health = _get(f"{url}/health")
    assert "podMemory" in health["features"]


def _seed_pending() -> str:
    entry = _entry("dist/pending.js", "pending")
    path = current_home().pod_memory_path("demo")
    path.parent.mkdir(parents=True, exist_ok=True)
    _store.write_json(path, {"entries": [entry, _entry("dist/other.js", "pending")]})
    return str(entry["id"])


def test_approve_accepts_a_pending_entry_and_answers_it_as_the_list_serves_it(
    live_server: tuple[str, str],
) -> None:
    url, token = live_server
    _pp.provision_pod("demo", "build", location="/src/demo")
    entry_id = _seed_pending()

    status, body = _support_http.post(
        f"{url}/pods/demo/memory/{entry_id}", {"decision": "approve"}, token
    )

    assert status == 200
    assert (body["id"], body["status"]) == (entry_id, "accepted")
    _, listed = _get(f"{url}/pods/demo/memory", token)
    assert listed["entries"] == [body]
    _, pending = _get(f"{url}/pods/demo/memory?status=pending", token)
    assert [e["subject"] for e in pending["entries"]] == ["dist/other.js"]


def test_refuse_records_the_reason_and_needs_one(live_server: tuple[str, str]) -> None:
    url, token = live_server
    _pp.provision_pod("demo", "build", location="/src/demo")
    entry_id = _seed_pending()
    route = f"{url}/pods/demo/memory/{entry_id}"

    status, body = _support_http.post(route, {"decision": "refuse"}, token)
    assert status == 400
    assert "reason" in body["error"]

    status, body = _support_http.post(route, {"decision": "refuse", "reason": "stale"}, token)
    assert status == 200
    assert (body["status"], body["reason"]) == ("refused", "stale")


def test_a_decided_entry_is_409_and_unchanged(live_server: tuple[str, str]) -> None:
    url, token = live_server
    _pp.provision_pod("demo", "build", location="/src/demo")
    entry_id = _seed_pending()
    route = f"{url}/pods/demo/memory/{entry_id}"
    _support_http.post(route, {"decision": "approve"}, token)

    status, body = _support_http.post(route, {"decision": "refuse", "reason": "x"}, token)

    assert status == 409
    assert body["ok"] is False
    _, listed = _get(f"{url}/pods/demo/memory", token)
    assert [e["status"] for e in listed["entries"]] == ["accepted"]


def test_an_unknown_pod_or_entry_is_404(live_server: tuple[str, str]) -> None:
    url, token = live_server
    _pp.provision_pod("demo", "build", location="/src/demo")
    _seed_pending()

    assert (
        _support_http.post(f"{url}/pods/ghost/memory/mem-1", {"decision": "approve"}, token)[0]
        == 404
    )
    assert (
        _support_http.post(f"{url}/pods/demo/memory/mem-nope", {"decision": "approve"}, token)[0]
        == 404
    )


def test_a_bad_body_is_400_and_changes_nothing(live_server: tuple[str, str]) -> None:
    url, token = live_server
    _pp.provision_pod("demo", "build", location="/src/demo")
    entry_id = _seed_pending()
    route = f"{url}/pods/demo/memory/{entry_id}"

    for bad in ({}, {"decision": "revert"}, {"decision": "refuse", "reason": 3}, {"decision": 1}):
        assert _support_http.post(route, bad, token)[0] == 400
    assert _support_http.post_raw(route, b"[1]", token)[0] == 400
    assert _support_http.post_raw(route, b"{", token)[0] == 400
    _, pending = _get(f"{url}/pods/demo/memory?status=pending", token)
    assert len(pending["entries"]) == 2


def test_the_decision_needs_the_token(live_server: tuple[str, str]) -> None:
    url, _ = live_server

    status, _ = _support_http.post(f"{url}/pods/demo/memory/mem-1", {"decision": "approve"})

    assert status == 401


def test_status_and_health_list_the_memory_decide_feature(live_server: tuple[str, str]) -> None:
    url, _ = live_server

    assert "memoryDecide" in _get(f"{url}/status.json")[1]["features"]
    assert "memoryDecide" in _get(f"{url}/health")[1]["features"]
