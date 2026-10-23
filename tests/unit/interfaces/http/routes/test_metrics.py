"""serve — stdlib HTTP server for docket's read API.

These exercise the pure builders (build_status / render_metrics / render_health)
against a seeded fake DOCKET_HOME, plus a live round-trip through the threaded
HTTP server on port 0. The pure-function assertions are the contract guard:
they pin the /status.json JSON keys and the Prometheus metric line names so any
drift is caught.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tests.support import home as _support_home

from docket.interfaces.http.routes import metrics

fake_home = _support_home.fake_home

SUBJECT = "docket.interfaces.http.routes.metrics"

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


# ── render_metrics ────────────────────────────────────────────────────────────


class TestRenderMetrics:
    def test_metric_names_present(self, fake_home: Path) -> None:
        text = metrics.render_metrics()
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
        text = metrics.render_metrics()
        assert "# HELP docket_agents_total Number of project agents" in text
        assert "# TYPE docket_agents_total gauge" in text

    def test_agents_total_value(self, fake_home: Path) -> None:
        lines = metrics.render_metrics().splitlines()
        assert "docket_agents_total 1" in lines

    def test_per_agent_labels(self, fake_home: Path) -> None:
        lines = metrics.render_metrics().splitlines()
        cost_line = next(line for line in lines if line.startswith("docket_agent_cost_usd{"))
        assert 'agent="myshop"' in cost_line
        assert 'model="anthropic/claude-sonnet-4-6"' in cost_line
        turns_line = next(line for line in lines if line.startswith("docket_agent_turns_total{"))
        assert 'agent="myshop"' in turns_line

    def test_no_trailing_newline(self, fake_home: Path) -> None:
        assert not metrics.render_metrics().endswith("\n")

    def test_exposition_follows_the_text_format_with_two_agents(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agents = [
            {"id": "alpha", "model": "m1", "costUsd": 0, "turns": 3},
            {"id": "beta", "model": "m2", "costUsd": 0, "turns": 5},
        ]
        monkeypatch.setattr(
            metrics, "_cost_json", lambda: {"agents": agents, "totalUsd": 0, "totalTurns": 8}
        )
        text = metrics.render_metrics()
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
