"""A ``run`` command step's ``env:`` -- shape validation, short form, planning, and the
environment the command actually sees. See specs/functional/pipeline-format.spec.md
("Conditional steps and command steps") and pod-dispatch.spec.md."""

from __future__ import annotations

from typing import Any

import pytest

from docket.governance import secrets as _secrets
from docket.pipeline.domain.step import Step

SUBJECT = "docket.pipeline.domain.step"


def _errors(**kw: Any) -> str:
    with pytest.raises(ValueError) as info:
        Step(id="check", run="echo hi", **kw)
    return str(info.value)


class TestShape:
    def test_a_run_step_carries_env(self) -> None:
        step = Step(id="check", run="echo hi", env={"FOO": "bar"})
        assert step.env == {"FOO": "bar"}

    def test_env_on_a_role_step_is_refused(self) -> None:
        with pytest.raises(ValueError, match="env"):
            Step(id="build", role="implementer", env={"FOO": "bar"})

    @pytest.mark.parametrize(
        "name",
        ["PATH", "LD_PRELOAD", "PYTHONPATH", "BASH_ENV", "ENV", "DOCKET_BASE_COMMIT", "DOCKET_X"],
    )
    def test_reserved_names_are_refused(self, name: str) -> None:
        assert name in _errors(env={name: "x"})

    @pytest.mark.parametrize("name", ["foo", "1A", "A-B", ""])
    def test_malformed_names_are_refused(self, name: str) -> None:
        assert "env" in _errors(env={name: "x"})

    def test_non_string_values_are_refused(self) -> None:
        with pytest.raises(ValueError):
            Step(id="check", run="echo hi", env={"FOO": 1})  # type: ignore[dict-item]

    def test_a_credential_name_is_refused(self) -> None:
        assert "credential" in _errors(env={"TELEGRAM_BOT_TOKEN": "x"})

    def test_a_secret_store_name_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_secrets, "secrets_keys", lambda: ["MY_STORED_KEY"])
        assert "credential" in _errors(env={"MY_STORED_KEY": "x"})
