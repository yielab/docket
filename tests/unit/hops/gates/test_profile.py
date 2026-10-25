"""The lights-out decision is a pure function over its facts (hops/gates/profile.py)."""

from __future__ import annotations

import dataclasses

from docket.hops.gates.profile import Facts, as_json, lights_out_violations

SUBJECT = "docket.hops.gates.profile"

_MET = Facts(
    isolation_on=True,
    backend="landlock",
    network_mode="none",
    network_scope="global",
    ungated_implementers=(),
    injected_secrets=(),
    consult_mode="decide",
)


def _requirements(facts: Facts) -> list[str]:
    return [v.requirement for v in lights_out_violations(facts)]


def test_all_met_has_no_violation() -> None:
    assert lights_out_violations(_MET) == []


def test_each_unmet_requirement_names_itself_and_a_fix() -> None:
    cases = {
        "isolation": dataclasses.replace(_MET, isolation_on=False),
        "network": dataclasses.replace(_MET, network_mode="open", network_scope="default"),
        "external-gate": dataclasses.replace(_MET, ungated_implementers=("build",)),
        "secrets": dataclasses.replace(_MET, injected_secrets=("MY_TOKEN",)),
        "consult": dataclasses.replace(_MET, consult_mode="park"),
    }
    for requirement, facts in cases.items():
        found = lights_out_violations(facts)
        assert [v.requirement for v in found] == [requirement]
        assert found[0].fix


def test_no_backend_is_an_isolation_violation() -> None:
    assert _requirements(dataclasses.replace(_MET, backend="none")) == ["isolation"]


def test_an_unrecorded_none_is_not_a_choice() -> None:
    assert _requirements(dataclasses.replace(_MET, network_scope="default")) == ["network"]
    assert _requirements(dataclasses.replace(_MET, network_scope="pod")) == []


def test_every_ungated_step_is_listed() -> None:
    facts = dataclasses.replace(_MET, ungated_implementers=("a", "b"))
    assert _requirements(facts) == ["external-gate", "external-gate"]


def test_a_consult_that_waits_for_a_person_names_the_setting_that_fixes_it() -> None:
    (found,) = lights_out_violations(dataclasses.replace(_MET, consult_mode="park"))

    assert found.requirement == "consult"
    assert found.detail == "a consultation would wait for a person"
    assert found.fix == "docket pod set consultMode decide"


def test_json_carries_requirement_and_fix_only() -> None:
    block = as_json(lights_out_violations(dataclasses.replace(_MET, isolation_on=False)))
    assert block["name"] == "lights-out"
    assert set(block["violations"][0]) == {"requirement", "fix"}
