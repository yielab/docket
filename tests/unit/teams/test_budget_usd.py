"""``budgetUsd`` has one stored type: a float that is never negative (defect 67).

Provisioning used to write it as the string ``"5.0"`` while ``pod set`` wrote the float ``5.0``, so
the same pod's meta held either depending on how the budget arrived.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from tests.support.pods import build_pod

from docket.kernel.home import current_home
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod
from docket.teams import pod_provisioning as _pp
from docket.teams.models import AgentMeta
from docket.teams.pod_settings import PodSettings

SUBJECT = "docket.teams.models"


def _stored_budget(project: str) -> object:
    meta = current_home().meta_path(_pod.member_id(project, "lead"))
    return json.loads(meta.read_text())["budgetUsd"]


def test_provisioning_stores_the_budget_as_a_float() -> None:
    build_pod("demo", _pod.DEFAULT_POD_ROLES, codebase="/src/demo", budget_usd=5.0)

    stored = _stored_budget("demo")

    assert stored == 5.0
    assert isinstance(stored, float)


def test_a_flat_from_spec_stores_the_same_type() -> None:
    budget = _pp.parse_budget_usd("5")
    build_pod("demo", _pod.DEFAULT_POD_ROLES, codebase="/src/demo", budget_usd=budget)

    assert isinstance(_stored_budget("demo"), float)


def test_provisioning_and_pod_set_agree_on_the_stored_form() -> None:
    build_pod("demo", _pod.DEFAULT_POD_ROLES, codebase="/src/demo", budget_usd=5.0)
    provisioned = _stored_budget("demo")

    _fleet.meta_set(
        _pod.member_id("demo", "lead"), "budgetUsd", PodSettings.coerce("budgetUsd", "7")
    )

    assert type(_stored_budget("demo")) is type(provisioned) is float


def test_the_meta_refuses_a_negative_budget() -> None:
    with pytest.raises(ValidationError):
        AgentMeta.model_validate({"kind": "project", "budgetUsd": -1})
