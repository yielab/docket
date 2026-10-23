"""serve — stdlib HTTP server for docket's read API.

These exercise the pure builders (build_status / render_metrics / render_health)
against a seeded fake DOCKET_HOME, plus a live round-trip through the threaded
HTTP server on port 0. The pure-function assertions are the contract guard:
they pin the /status.json JSON keys and the Prometheus metric line names so any
drift is caught.
"""

from __future__ import annotations

import json
import shutil
import threading
import urllib.request
from pathlib import Path
from threading import Thread
from typing import Any

import pytest
from tests.conftest import repoint_docket_home

import docket.serve as serve
from docket.serve import _DocketHandler

SUBJECT = "docket.serve"

META: dict[str, Any] = {
    "schemaVersion": 1,
    "kind": "project",
    "name": "My Shop",
    "type": "repo",
    "model": "anthropic/claude-sonnet-4-6",
}

# Agent registration + channel bindings live in fleet.json.
FLEET_CONFIG: dict[str, Any] = {
    "agents": [{"id": "myshop"}],
    "bindings": [
        {"agentId": "myshop", "channel": "telegram", "peerKind": "group", "peerId": "-100123"}
    ],
    "defaults": {"model": ""},
    "security": {"gatesEnabled": False, "isolationEnabled": False},
}


@pytest.fixture()
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Seed a temp DOCKET_HOME with one project agent + fleet.json."""
    home = tmp_path / ".docket"
    home.mkdir()
    ws = home / "workspaces" / "projects" / "myshop"
    (ws / "memory").mkdir(parents=True)
    (ws / ".docket-meta.json").write_text(json.dumps(META))
    session = home / "sessions" / "agent%3Amyshop%3Amyshop"
    session.mkdir(parents=True)
    (session / "session.json").write_text(
        json.dumps(
            {
                "sessionKey": "agent:myshop:myshop",
                "created": "2026-06-19T08:00:00Z",
                "updated": "2026-06-20T09:30:00Z",
                "messages": [],
            }
        )
    )
    (home / "fleet.json").write_text(json.dumps(FLEET_CONFIG))

    repoint_docket_home(monkeypatch, home)
    return home


# ── build_status ──────────────────────────────────────────────────────────────


class TestBuildStatus:
    def test_top_level_keys(self, fake_home: Path) -> None:
        st = serve.build_status()
        assert set(st.keys()) == {
            "apiVersion",
            "timestamp",
            "channels",
            "agents",
            "totalCostUsd",
        }

    def test_api_version_field(self, fake_home: Path) -> None:
        assert serve.build_status()["apiVersion"] == serve.SERVE_API_VERSION

    def test_channels_from_acl(self, fake_home: Path) -> None:
        assert serve.build_status()["channels"] == ["telegram"]

    def test_agent_record_shape(self, fake_home: Path) -> None:
        agents = serve.build_status()["agents"]
        assert len(agents) == 1
        a = agents[0]
        assert set(a.keys()) == {
            "id",
            "name",
            "kind",
            "scope",
            "model",
            "registered",
            "bindings",
            "lastActivity",
            "costUsd",
            "budgetUsd",
        }
        assert a["id"] == "myshop"
        assert a["name"] == "My Shop"
        assert a["kind"] == "project"
        assert a["registered"] is True
        assert a["lastActivity"] == "2026-06-20"
        assert a["bindings"] == [{"channel": "telegram"}]

    def test_last_activity_never_when_empty(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Remove the agent's only session so last_activity falls back to the sentinel.
        shutil.rmtree(fake_home / "sessions")
        assert serve.build_status()["agents"][0]["lastActivity"] == "never"

    def test_timestamp_format(self, fake_home: Path) -> None:
        ts = serve.build_status()["timestamp"]
        assert ts.endswith("Z") and "T" in ts and len(ts) == 20


# ── render_metrics ────────────────────────────────────────────────────────────


class TestRenderMetrics:
    def test_metric_names_present(self, fake_home: Path) -> None:
        text = serve.render_metrics()
        for name in (
            "docket_agents_total",
            "docket_agent_cost_usd",
            "docket_agent_turns_total",
            "docket_cost_usd_total",
            "docket_approvals_pending_total",
            "docket_tasks_started_total",
            "docket_questions_total",
            "docket_decision_latency_seconds",
        ):
            assert name in text

    def test_help_and_type_headers(self, fake_home: Path) -> None:
        text = serve.render_metrics()
        assert "# HELP docket_agents_total Number of project agents" in text
        assert "# TYPE docket_agents_total gauge" in text

    def test_agents_total_value(self, fake_home: Path) -> None:
        lines = serve.render_metrics().splitlines()
        assert "docket_agents_total 1" in lines

    def test_per_agent_labels(self, fake_home: Path) -> None:
        lines = serve.render_metrics().splitlines()
        cost_line = next(line for line in lines if line.startswith("docket_agent_cost_usd{"))
        assert 'agent="myshop"' in cost_line
        assert 'model="anthropic/claude-sonnet-4-6"' in cost_line
        turns_line = next(line for line in lines if line.startswith("docket_agent_turns_total{"))
        assert 'agent="myshop"' in turns_line

    def test_no_trailing_newline(self, fake_home: Path) -> None:
        assert not serve.render_metrics().endswith("\n")

    def test_exposition_follows_the_text_format_with_two_agents(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agents = [
            {"id": "alpha", "model": "m1", "costUsd": 0, "turns": 3},
            {"id": "beta", "model": "m2", "costUsd": 0, "turns": 5},
        ]
        monkeypatch.setattr(
            serve, "_cost_json", lambda: {"agents": agents, "totalUsd": 0, "totalTurns": 8}
        )
        text = serve.render_metrics()
        _assert_text_format_0_0_4(text)
        assert 'docket_agent_turns_total{agent="alpha"} 3' in text
        assert 'docket_agent_turns_total{agent="beta"} 5' in text


def _assert_text_format_0_0_4(text: str) -> None:
    """The Prometheus 0.0.4 rules this server relies on: a family appears once, HELP then TYPE
    before its first sample, and every sample of a family sits together under that header."""
    family: str | None = None
    declared: dict[str, str] = {}
    helped: set[str] = set()
    closed: set[str] = set()
    for line in text.splitlines():
        if line.startswith("# HELP "):
            name = line.split()[2]
            assert name not in helped, f"{name}: HELP twice"
            assert name not in closed, f"{name}: family split in two"
            helped.add(name)
            if family is not None:
                closed.add(family)
            family = name
        elif line.startswith("# TYPE "):
            name, kind = line.split()[2:4]
            assert name == family and name in helped, f"{name}: TYPE without its HELP first"
            assert name not in declared, f"{name}: TYPE twice"
            declared[name] = kind
        else:
            sample = line.split("{")[0].split(" ")[0]
            assert family is not None and family in declared, f"{sample}: sample before HELP/TYPE"
            suffixes = ("_sum", "_count") if declared[family] == "summary" else ()
            assert sample == family or sample in {family + s for s in suffixes}, (
                f"{sample}: sample outside its family {family}"
            )


# ── render_health ─────────────────────────────────────────────────────────────


class TestRenderHealth:
    def test_health_body(self, fake_home: Path) -> None:
        body = json.loads(serve.render_health())
        assert set(body) == {"status", "apiVersion", "dispatch"}
        assert body["status"] == "ok"
        assert body["apiVersion"] == serve.SERVE_API_VERSION

    def test_health_dispatch_block(self, fake_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The dispatch block reports the flag, in-flight pods, the stop state and the pool size."""
        stop = threading.Event()
        monkeypatch.setattr(serve, "_sweep_stop", stop)
        monkeypatch.setattr(serve, "_sweep_inflight", {"demo": None})
        assert json.loads(serve.render_health(True))["dispatch"] == {
            "on": True,
            "inflight": ["demo"],
            "stopping": False,
            "workers": serve.cfg.DISPATCH_SWEEP_WORKERS,
        }
        stop.set()
        assert json.loads(serve.render_health())["dispatch"]["stopping"] is True


# ── live HTTP round-trip (port 0) ─────────────────────────────────────────────


class TestHttpServer:
    def test_endpoints_over_socket(self, fake_home: Path) -> None:
        from docket.kernel.threads import ContextHTTPServer

        server = ContextHTTPServer(("127.0.0.1", 0), _DocketHandler)
        port = server.server_address[1]
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{port}"
            with urllib.request.urlopen(base + "/health", timeout=5) as r:
                assert json.loads(r.read().decode())["status"] == "ok"
            with urllib.request.urlopen(base + "/status.json", timeout=5) as r:
                status = json.loads(r.read().decode())
                assert status["agents"][0]["id"] == "myshop"
            with urllib.request.urlopen(base + "/metrics", timeout=5) as r:
                metrics = r.read().decode()
                assert metrics.startswith("# HELP docket_agents_total")
                assert metrics.endswith("\n")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


class TestTelegramHint:
    def test_unconfigured_bot_names_the_command_that_connects_it(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from docket.core import telegram as _telegram

        stop = threading.Event()

        def _unconfigured() -> Any:
            stop.set()
            return _telegram.PollSummary(ok=False, configured=False)

        monkeypatch.setattr(_telegram, "poll_once", _unconfigured)
        serve._telegram_poll_loop(stop)
        assert "docket setup notify enable telegram" in capsys.readouterr().out
