"""CD-6: Scheduled & webhook-triggered dispatch.

Acceptance criteria:
  - A scheduled time fires a dispatch
  - A webhook POST triggers a dispatch
  - Unauthorized requests are rejected
  - suite green
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import docket.config as _cfg
import docket.serve as _serve
from docket.core import schedule as _sched
from docket.serve import _DocketHandler

_TEST_TOKEN = "test-serve-token-cd6-xyz987"


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_schedule_state() -> None:
    """Clear the module-level _schedule_state between tests."""
    _serve._schedule_state.clear()
    yield
    _serve._schedule_state.clear()


@pytest.fixture()
def schedule_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    f = tmp_path / "docket-schedules.json"
    monkeypatch.setattr(_cfg, "SCHEDULE_FILE", f, raising=True)
    return f


@pytest.fixture()
def live_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Real server on a random port. Yields (base_url, token)."""
    # Minimal APPROVALS_DIR to satisfy any sweep that might run.
    d = tmp_path / "approvals"
    d.mkdir()
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", d, raising=True)

    class _Handler(_DocketHandler):
        serve_token = _TEST_TOKEN

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", _TEST_TOKEN
    srv.shutdown()


def _post(
    url: str,
    body: dict | None = None,  # type: ignore[type-arg]
    token: str | None = None,
) -> tuple[int, dict]:  # type: ignore[type-arg]
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Content-Length", str(len(data)))
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


# ── schedule spec parsing ──────────────────────────────────────────────────────


class TestScheduleParsing:
    def test_interval_seconds(self) -> None:
        assert _sched.parse_interval("@every 30s") == 30

    def test_interval_minutes(self) -> None:
        assert _sched.parse_interval("@every 5m") == 300

    def test_interval_hours(self) -> None:
        assert _sched.parse_interval("@every 2h") == 7200

    def test_invalid_interval_returns_none(self) -> None:
        assert _sched.parse_interval("every 5m") is None
        assert _sched.parse_interval("@every 5x") is None
        assert _sched.parse_interval("09:00") is None

    def test_daily_time_valid(self) -> None:
        assert _sched.parse_daily_time("09:00") == (9, 0)
        assert _sched.parse_daily_time("23:59") == (23, 59)
        assert _sched.parse_daily_time("0:00") == (0, 0)

    def test_daily_time_invalid(self) -> None:
        assert _sched.parse_daily_time("@every 5m") is None
        assert _sched.parse_daily_time("25:00") is None
        assert _sched.parse_daily_time("12:60") is None

    def test_unrecognised_spec_not_due(self) -> None:
        assert not _sched.is_schedule_due("unknown format", 0.0, time.time())


class TestScheduleDue:
    def test_interval_due_after_elapsed(self) -> None:
        now = time.time()
        assert _sched.is_schedule_due("@every 60s", now - 61, now)

    def test_interval_not_due_before_elapsed(self) -> None:
        now = time.time()
        assert not _sched.is_schedule_due("@every 60s", now - 30, now)

    def test_interval_due_from_zero(self) -> None:
        assert _sched.is_schedule_due("@every 60s", 0.0, time.time())

    def test_daily_due_when_last_run_before_target(self) -> None:
        import datetime as _dt

        now_dt = _dt.datetime.now(_dt.UTC)
        # target = yesterday at 00:01
        target = now_dt.replace(hour=0, minute=1, second=0, microsecond=0)
        if target > now_dt:
            target -= _dt.timedelta(days=1)
        last_before = target - _dt.timedelta(minutes=5)
        assert _sched.is_schedule_due("00:01", last_before.timestamp(), now_dt.timestamp())

    def test_daily_not_due_when_last_run_after_target(self) -> None:
        import datetime as _dt

        now_dt = _dt.datetime.now(_dt.UTC)
        target = now_dt.replace(hour=0, minute=1, second=0, microsecond=0)
        if target > now_dt:
            target -= _dt.timedelta(days=1)
        last_after = target + _dt.timedelta(minutes=5)
        assert not _sched.is_schedule_due("00:01", last_after.timestamp(), now_dt.timestamp())


class TestLoadSchedules:
    def test_reads_schedules_from_file(self, schedule_file: Path) -> None:
        schedule_file.write_text(
            json.dumps({"schedules": {"proj1": "@every 5m", "proj2": "09:00"}}),
            encoding="utf-8",
        )
        result = _sched.load_schedules(schedule_file)
        assert result == {"proj1": "@every 5m", "proj2": "09:00"}

    def test_missing_file_returns_empty(self, schedule_file: Path) -> None:
        assert _sched.load_schedules(schedule_file) == {}

    def test_invalid_json_returns_empty(self, schedule_file: Path) -> None:
        schedule_file.write_text("not json", encoding="utf-8")
        assert _sched.load_schedules(schedule_file) == {}

    def test_missing_schedules_key_returns_empty(self, schedule_file: Path) -> None:
        schedule_file.write_text(json.dumps({"other": "data"}), encoding="utf-8")
        assert _sched.load_schedules(schedule_file) == {}


# ── _check_schedules integration ──────────────────────────────────────────────


class TestCheckSchedules:
    def test_due_project_triggers_dispatch(
        self, schedule_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        schedule_file.write_text(
            json.dumps({"schedules": {"projA": "@every 1s"}}),
            encoding="utf-8",
        )
        dispatched: list[str] = []
        monkeypatch.setattr(
            "docket.core.dispatch.dispatch_pod",
            lambda proj, **kw: dispatched.append(proj),
        )
        _serve._check_schedules(time.time())
        # Allow daemon thread to run
        deadline = time.time() + 2
        while not dispatched and time.time() < deadline:
            time.sleep(0.05)
        assert dispatched == ["projA"]

    def test_not_yet_due_project_skipped(
        self, schedule_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        schedule_file.write_text(
            json.dumps({"schedules": {"projB": "@every 3600s"}}),
            encoding="utf-8",
        )
        dispatched: list[str] = []
        monkeypatch.setattr(
            "docket.core.dispatch.dispatch_pod",
            lambda proj, **kw: dispatched.append(proj),
        )
        # last run was just now — not due
        _serve._schedule_state["projB"] = time.time()
        _serve._check_schedules(time.time())
        time.sleep(0.1)
        assert dispatched == []

    def test_state_updated_after_dispatch(
        self, schedule_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        schedule_file.write_text(
            json.dumps({"schedules": {"projC": "@every 1s"}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "docket.core.dispatch.dispatch_pod",
            lambda proj, **kw: None,
        )
        before = time.time()
        _serve._check_schedules(before)
        assert _serve._schedule_state.get("projC", 0.0) >= before


# ── POST /dispatch/<project> webhook ─────────────────────────────────────────


class TestWebhookDispatch:
    def test_webhook_triggers_dispatch(
        self,
        live_server: tuple[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        url, token = live_server
        dispatched: list[str] = []
        event = threading.Event()

        def _fake_dispatch_pod(proj: str, **kw: object) -> None:
            dispatched.append(proj)
            event.set()

        monkeypatch.setattr("docket.core.dispatch.dispatch_pod", _fake_dispatch_pod)

        status, body = _post(f"{url}/dispatch/myproject", token=token)
        assert status == 200
        assert body["ok"] is True
        assert body["project"] == "myproject"
        assert body["status"] == "dispatched"

        # Wait for the daemon thread to call dispatch
        assert event.wait(timeout=3), "dispatch_pod not called within 3 s"
        assert dispatched == ["myproject"]

    def test_webhook_no_auth_rejected(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        status, body = _post(f"{url}/dispatch/myproject")
        assert status == 401
        assert body["ok"] is False

    def test_webhook_wrong_token_rejected(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        status, _ = _post(f"{url}/dispatch/myproject", token="wrong")
        assert status == 401

    def test_webhook_missing_project_returns_404(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        # /dispatch/ with empty project segment → trailing slash stripped → not found
        status, body = _post(f"{url}/dispatch/", token=token)
        assert status == 404
        assert body["ok"] is False
