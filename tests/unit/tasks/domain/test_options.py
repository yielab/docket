"""validate_task_options: shape and narrowing checks for the addressable-task fields."""

from __future__ import annotations

from typing import Any

import pytest

from docket.governance import policy as _policy
from docket.hops.workspace import prepare as _prepare
from docket.tasks.domain import options as _to
from docket.teams.settings import builtin_tool_names

SUBJECT = "docket.tasks.domain.options"


# The rules the enqueue path hands in: the real tool names, policy check and prepare check.
_RULES = _to.OptionRules(
    known_tools=builtin_tool_names(),
    check_policy=_policy.task_policy_document,
    check_prepare=_prepare.check_command,
)


def _ok(**kw: Any) -> _to.TaskOptions:
    return _to.validate_task_options(rules=_RULES, **kw)


def test_unset_fields_are_omitted_from_the_record() -> None:
    assert _ok().as_record() == {}


def test_every_field_round_trips_verbatim() -> None:
    record = _ok(
        external_ref="A-1",
        idempotency_key="k",
        base_ref="main",
        pipeline="tdd",
        gate={"command": "make test", "timeoutS": 30, "map": {"3": "needs_human"}},
        max_tokens=100,
        restrictions={"deniedTools": ["fetch", "write"], "network": "none", "policies": []},
    ).as_record()
    assert record == {
        "externalRef": "A-1",
        "idempotencyKey": "k",
        "baseRef": "main",
        "pipeline": "tdd",
        "gate": {"command": "make test", "timeoutS": 30, "map": {"3": "needs_human"}},
        "maxTokens": 100,
        "restrictions": {"deniedTools": ["fetch", "write"], "network": "none", "policies": []},
    }


def test_a_gate_keeps_only_the_keys_it_was_given() -> None:
    assert _ok(gate={"command": "x"}).as_record() == {"gate": {"command": "x"}}


@pytest.mark.parametrize(
    "kw",
    [
        {"external_ref": ""},
        {"external_ref": "x" * 201},
        {"external_ref": 3},
        {"idempotency_key": ""},
        {"base_ref": 1},
        {"pipeline": " "},
        {"gate": {"command": ""}},
        {"gate": {"command": "x", "timeoutS": 0}},
        {"gate": {"command": "x", "extra": 1}},
        {"gate": {"command": "x", "map": {"two": "fail"}}},
        {"gate": {"command": "x", "map": {"2": "maybe"}}},
        {"max_tokens": 0},
        {"max_tokens": True},
        {"max_tokens": 1.5},
        {"restrictions": []},
        {"restrictions": {"bogus": 1}},
        {"restrictions": {"deniedTools": "fetch"}},
        {"restrictions": {"policies": ["not a document"]}},
    ],
)
def test_a_wrong_shape_raises_options_error_not_restriction_error(kw: dict[str, Any]) -> None:
    with pytest.raises(_to.TaskOptionsError) as err:
        _ok(**kw)
    assert not isinstance(err.value, _to.TaskRestrictionError)


@pytest.mark.parametrize(
    "restrictions",
    [
        {"network": "open"},
        {"network": "anything"},
        {"deniedTools": ["no_such_tool"]},
        {
            "policies": [
                {
                    "kind": "policy",
                    "name": "p",
                    "appliesTo": ["*"],
                    "when": {"tool": "bash"},
                    "then": "warn",
                }
            ]
        },
        {
            "policies": [
                {"kind": "policy", "name": "p", "appliesTo": ["*"], "when": {"tool": "bash"}}
            ]
        },
        {"policies": [{"name": "p"}]},
    ],
)
def test_a_widening_restriction_raises_restriction_error(restrictions: dict[str, Any]) -> None:
    with pytest.raises(_to.TaskRestrictionError):
        _ok(restrictions=restrictions)


def test_a_block_policy_is_accepted_in_short_or_canonical_form() -> None:
    short = {
        "kind": "policy",
        "name": "p",
        "appliesTo": ["*"],
        "when": {"tool": "bash"},
        "then": "block",
    }
    canonical = {
        "id": "q",
        "applies_to": "*",
        "hook": "pre_tool_call",
        "when": {"tool": "bash"},
        "action": "block",
    }
    assert _ok(restrictions={"policies": [short, canonical]}).restrictions is not None


@pytest.mark.parametrize("value", ["npm ci", "", "none"])
def test_prepare_is_kept_verbatim_even_when_blank(value: str) -> None:
    assert _ok(prepare=value).as_record() == {"prepare": value}


@pytest.mark.parametrize("value", ["a\nb", "a\x00b", "x" * 1001, 3, ["a"]])
def test_a_malformed_prepare_is_refused(value: Any) -> None:
    with pytest.raises(_to.TaskOptionsError):
        _ok(prepare=value)
