"""Shared dependency and scenario contract for the Wave 28 adapter lanes."""

from __future__ import annotations

import dataclasses
import tomllib
from pathlib import Path

import pytest

from tests.fixtures.runtime_adapters.scenarios import (
    ADVERTISED_TOOLS,
    FINAL_SUMMARY,
    PLANTED_BYPASSES,
    SCENARIOS,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "runtime_adapters"


def test_shared_scenarios_are_immutable_and_cover_the_governance_oracle() -> None:
    assert ADVERTISED_TOOLS == ("read_state", "mutate_state")
    assert PLANTED_BYPASSES == ("native_bash", "native_file_editor")
    assert FINAL_SUMMARY
    assert tuple(scenario.name for scenario in SCENARIOS) == (
        "allow_read",
        "unknown_native_bash",
        "unknown_native_file_editor",
        "policy_denied_mutation",
        "approval_denied_mutation",
        "approval_granted_mutation",
        "reported_token_budget",
    )
    assert {scenario.expected_decision for scenario in SCENARIOS} == {
        "allow",
        "invalid_call",
        "gate_denied",
        "approval_denied",
    }
    assert {scenario.expected_stop for scenario in SCENARIOS} == {
        "final_message",
        "token_budget",
    }
    assert sum(scenario.expected_mutations for scenario in SCENARIOS) == 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        SCENARIOS[0].name = "changed"


@pytest.mark.parametrize(
    ("fixture", "python_range", "dependency"),
    (
        ("openhands", ">=3.12,<3.13", "openhands-sdk==1.44.1"),
        ("pydantic_ai", ">=3.11,<3.12", "pydantic-ai==2.37.0"),
    ),
)
def test_adapter_dependency_projects_are_disjoint_and_exactly_pinned(
    fixture: str, python_range: str, dependency: str
) -> None:
    project_dir = FIXTURES / fixture
    project = tomllib.loads((project_dir / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["requires-python"] == python_range
    assert project["project"]["dependencies"] == [dependency]
    assert project["tool"]["uv"]["package"] is False

    lock = (project_dir / "uv.lock").read_text(encoding="utf-8")
    package, version = dependency.split("==", 1)
    assert f'name = "{package}"' in lock
    assert f'version = "{version}"' in lock
