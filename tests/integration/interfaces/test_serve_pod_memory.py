"""GET /pods/<p>/memory: the accepted pod memory over HTTP, the same elements as the CLI's list."""

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
