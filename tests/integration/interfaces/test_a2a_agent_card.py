"""The A2A agent card's skill says what each pod does (a2a-binding, "Agent card")."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.support.pods import build_pod
from tests.support.pods import seed_empty_home as _seed

from docket.interfaces.http.routes import a2a
from docket.teams import blueprints as _blueprints
from docket.teams import pod_provisioning as _pp

SUBJECT = "docket.interfaces.http.routes.a2a"


class _Exchange:
    def __init__(self) -> None:
        self.headers = {"Host": "docket.test:7399"}
        self.sent: list[dict[str, Any]] = []

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        self.sent.append(payload)


def _skills() -> dict[str, dict[str, Any]]:
    exchange = _Exchange()
    a2a.get_agent_card(exchange, "")  # type: ignore[arg-type]
    return {s["id"]: s for s in exchange.sent[0]["skills"]}


def test_a_respond_pod_skill_carries_the_blueprint_text_what_it_delivers_and_its_name(
    tmp_path: Path,
) -> None:
    with _seed(tmp_path):
        _pp.provision_pod("desk", "respond")

        skill = _skills()["desk"]

    assert _blueprints.get_blueprint("respond").description in skill["description"]
    assert "report" in skill["description"]
    assert skill["tags"] == ["respond"]


def test_a_build_pod_skill_delivers_a_branch(tmp_path: Path) -> None:
    with _seed(tmp_path):
        _pp.provision_pod("code", "build", location="/src/code")

        skill = _skills()["code"]

    assert "branch" in skill["description"]
    assert skill["tags"] == ["build"]


def test_a_pod_with_no_blueprint_reads_as_it_always_did(tmp_path: Path) -> None:
    with _seed(tmp_path):
        build_pod("plain", ("lead", "implementer"), codebase="/src/plain")

        skill = _skills()["plain"]

    assert skill["description"] == "Runs tasks in the plain pod."
    assert skill["tags"] == []
