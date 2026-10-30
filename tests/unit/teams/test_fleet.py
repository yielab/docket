"""``teams.fleet``: the registry and the agent metadata refuse a key their model does not declare,
naming the key and the file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docket.kernel.errors import InvalidInput
from docket.kernel.home import current_home
from docket.teams import fleet as _fleet

SUBJECT = "docket.teams.fleet"


def _write_fleet(doc: dict[str, object]) -> Path:
    path = current_home().fleet_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))
    return path


@pytest.mark.parametrize(
    ("doc", "key"),
    [
        ({"agents": [{"id": "a", "futureKey": 1}]}, "futureKey"),
        ({"bindings": [{"agentId": "a", "futureKey": 1}]}, "futureKey"),
        ({"security": {"futureKey": 1}}, "futureKey"),
        ({"agents": [], "futureKey": 1}, "futureKey"),
    ],
)
def test_a_fleet_record_with_an_unknown_key_is_refused_naming_the_key_and_the_file(
    doc: dict[str, object], key: str
) -> None:
    path = _write_fleet(doc)

    with pytest.raises(InvalidInput) as caught:
        _fleet.load_fleet()

    assert key in str(caught.value)
    assert str(path) in str(caught.value)


def test_a_fleet_of_declared_keys_loads() -> None:
    _write_fleet({"agents": [{"id": "a"}], "bindings": [], "security": {"profile": "unset"}})

    assert [agent.id for agent in _fleet.load_fleet().agents] == ["a"]


def test_meta_set_refuses_an_undeclared_key_naming_the_key_and_the_file() -> None:
    path = current_home().meta_path("demo-lead")
    path.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps({"kind": "project", "name": "demo lead"})
    path.write_text(original)

    with pytest.raises(InvalidInput) as caught:
        _fleet.meta_set("demo-lead", "budgetUSD", 5)

    assert "budgetUSD" in str(caught.value)
    assert str(path) in str(caught.value)
    assert path.read_text() == original


def test_meta_set_still_writes_a_pod_setting_and_the_pod_key() -> None:
    path = current_home().meta_path("demo-lead")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"kind": "project", "pod": "demo"}))

    _fleet.meta_set("demo-lead", "approvalMode", "park")

    assert json.loads(path.read_text()) == {
        "kind": "project",
        "pod": "demo",
        "approvalMode": "park",
    }


def test_agent_meta_declares_every_pod_setting_key() -> None:
    from docket.teams.models import AgentMeta
    from docket.teams.pod_settings import PodSettings

    declared = {field.alias or name for name, field in AgentMeta.model_fields.items()}

    assert {*PodSettings.KEYS, *PodSettings.RECORDED_KEYS, "pod"} <= declared
