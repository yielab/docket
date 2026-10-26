"""Webhook params bound into pipeline variables.

See specs/data/serve-read-api.spec.md for the ``variables`` field contract.
Two layers: ``pipeline.domain.spec.resolve_variables`` (pure resolution: caller
values win over a variable's ``default``, an undeclared key passes through,
a missing ``required`` variable raises :class:`~docket.pipeline.domain.spec.
VariableError` naming every missing name), and ``POST /dispatch/<project>``,
whose JSON body is resolved against the pod's effective pipeline via that
function before any run record is created -- a malformed body or missing
required variable is rejected 400 before the run record exists.
"""

from __future__ import annotations

import pytest
from tests.support.pods import spec_with_variables as _spec

from docket.pipeline.domain import spec as _pipeline

SUBJECT = "docket.pipeline.domain.spec"


# ── pipeline.domain.spec.resolve_variables (pure, no server) ────────────────────────


class TestResolveVariables:
    def test_no_declared_variables_passes_provided_through_unchanged(self) -> None:
        spec = _spec()
        assert _pipeline.resolve_variables(spec, {"foo": "bar"}) == {"foo": "bar"}

    def test_no_provided_values_at_all_defaults_to_empty(self) -> None:
        spec = _spec()
        assert _pipeline.resolve_variables(spec) == {}
        assert _pipeline.resolve_variables(spec, None) == {}

    def test_default_used_when_not_provided(self) -> None:
        spec = _spec(env=_pipeline.Variable(default="prod"))
        assert _pipeline.resolve_variables(spec, {}) == {"env": "prod"}

    def test_provided_value_wins_over_default(self) -> None:
        spec = _spec(env=_pipeline.Variable(default="prod"))
        assert _pipeline.resolve_variables(spec, {"env": "staging"}) == {"env": "staging"}

    def test_required_variable_provided_is_fine(self) -> None:
        spec = _spec(env=_pipeline.Variable(required=True))
        assert _pipeline.resolve_variables(spec, {"env": "staging"}) == {"env": "staging"}

    def test_required_variable_missing_raises_naming_it(self) -> None:
        spec = _spec(env=_pipeline.Variable(required=True))
        with pytest.raises(_pipeline.VariableError, match="env"):
            _pipeline.resolve_variables(spec, {})

    def test_multiple_missing_required_named_together(self) -> None:
        spec = _spec(
            env=_pipeline.Variable(required=True),
            region=_pipeline.Variable(required=True),
        )
        with pytest.raises(_pipeline.VariableError) as exc_info:
            _pipeline.resolve_variables(spec, {})
        assert "env" in str(exc_info.value)
        assert "region" in str(exc_info.value)

    def test_undeclared_key_passes_through_alongside_declared_ones(self) -> None:
        spec = _spec(env=_pipeline.Variable(default="prod"))
        result = _pipeline.resolve_variables(spec, {"extra": 42})
        assert result == {"env": "prod", "extra": 42}

    def test_explicit_null_counts_as_provided_not_missing(self) -> None:
        spec = _spec(env=_pipeline.Variable(required=True))
        assert _pipeline.resolve_variables(spec, {"env": None}) == {"env": None}
