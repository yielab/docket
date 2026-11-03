"""``budgetTokens`` has one stored type, however the budget arrives: an integer above 0."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from tests.support.pods import build_pod

from docket.kernel.home import current_home
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod
from docket.teams import pod_provisioning as _pp
from docket.teams.models import AgentMeta, unknown_keys_text
from docket.teams.pod_settings import PodSettings

SUBJECT = "docket.teams.models"


def _stored_budget(project: str) -> object:
    meta = current_home().meta_path(_pod.member_id(project, "lead"))
    return json.loads(meta.read_text())["budgetTokens"]


def test_provisioning_stores_the_budget_as_an_integer() -> None:
    build_pod("demo", _pod.DEFAULT_POD_ROLES, codebase="/src/demo", budget_tokens=500000)

    stored = _stored_budget("demo")

    assert stored == 500000
    assert type(stored) is int


def test_a_flat_from_spec_stores_the_same_type() -> None:
    budget = _pp.budget_tokens_from({"budgetTokens": "500000"})
    build_pod("demo", _pod.DEFAULT_POD_ROLES, codebase="/src/demo", budget_tokens=budget)

    assert type(_stored_budget("demo")) is int


def test_provisioning_and_pod_set_agree_on_the_stored_form() -> None:
    build_pod("demo", _pod.DEFAULT_POD_ROLES, codebase="/src/demo", budget_tokens=500000)
    provisioned = _stored_budget("demo")

    _fleet.meta_set(
        _pod.member_id("demo", "lead"), "budgetTokens", PodSettings.coerce("budgetTokens", "700000")
    )

    assert type(_stored_budget("demo")) is type(provisioned) is int


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "x", "1.5", ""])
def test_a_spec_value_that_is_not_a_positive_whole_number_is_refused(bad: object) -> None:
    with pytest.raises(_pp.BudgetTokensError, match="budgetTokens"):
        _pp.budget_tokens_from({"budgetTokens": bad})


def test_a_spec_without_a_budget_means_no_cap() -> None:
    assert _pp.budget_tokens_from({}) is None


def test_a_spec_that_still_carries_budget_usd_is_refused_naming_budget_tokens() -> None:
    with pytest.raises(_pp.BudgetTokensError, match="budgetTokens"):
        _pp.budget_tokens_from({"budgetUsd": 5, "budgetTokens": 1000})


@pytest.mark.parametrize("bad", [0, -1])
def test_the_meta_refuses_a_budget_that_is_not_above_zero(bad: int) -> None:
    with pytest.raises(ValidationError):
        AgentMeta.model_validate({"kind": "project", "budgetTokens": bad})


def test_a_stored_budget_usd_is_refused_naming_budget_tokens() -> None:
    with pytest.raises(ValidationError) as caught:
        AgentMeta.model_validate({"kind": "project", "budgetUsd": 5})

    assert "budgetTokens" in unknown_keys_text(caught.value)
