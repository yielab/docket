"""A short-form target becomes a `role:` or an `agent:` by the role names the caller passes.
See specs/functional/pipeline-format.spec.md ("Short form" Requirements 3 and 90)."""

from __future__ import annotations

import pytest

from docket.pipeline.domain.spec import load_pipeline

SUBJECT = "docket.pipeline.domain.short_form"

_BASE = frozenset({"lead", "implementer", "reviewer"})
_WITH_CRITIC = _BASE | {"critic"}


def _only_step(target: str, roles: frozenset[str]) -> dict[str, str | None]:
    loaded = load_pipeline(f"name: p\nsteps:\n  - vet: {target}\n", roles=roles)
    assert loaded.spec is not None, loaded.errors
    (step,) = loaded.spec.steps
    return {"role": step.role, "agent": step.agent}


@pytest.mark.parametrize("target", ["shop-critic", "shop-critic-2"])
def test_a_member_id_of_a_known_role_is_an_agent_step(target: str) -> None:
    assert _only_step(target, _WITH_CRITIC) == {"role": None, "agent": target}


@pytest.mark.parametrize("target", ["shop-critic", "shop-critic-2"])
def test_the_same_target_without_that_role_stays_a_role(target: str) -> None:
    assert _only_step(target, _BASE) == {"role": target, "agent": None}


@pytest.mark.parametrize("roles", [_BASE, _WITH_CRITIC])
def test_a_bare_role_name_is_a_role_either_way(roles: frozenset[str]) -> None:
    assert _only_step("critic", roles) == {"role": "critic", "agent": None}


def test_a_hyphenated_role_name_is_a_role_and_its_member_id_an_agent() -> None:
    roles = _BASE | {"security-vetter"}
    assert _only_step("security-vetter", roles) == {"role": "security-vetter", "agent": None}
    assert _only_step("shop-security-vetter-2", roles) == {
        "role": None,
        "agent": "shop-security-vetter-2",
    }


def test_a_parallel_child_reads_the_same_role_names() -> None:
    text = "name: p\nsteps:\n  - fan:\n      parallel:\n        - a: shop-critic\n        - b: reviewer\n"
    loaded = load_pipeline(text, roles=_WITH_CRITIC)
    assert loaded.spec is not None, loaded.errors
    first, second = loaded.spec.steps[0].parallel or []
    assert (first.agent, first.role) == ("shop-critic", None)
    assert (second.role, second.agent) == ("reviewer", None)
