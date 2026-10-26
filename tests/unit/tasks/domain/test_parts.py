"""The nested shapes of a task record: each dumps under its writer's keys and reads them back.

Pure: no disk, no patches.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from docket.tasks.domain import parts as _parts

SUBJECT = "docket.tasks.domain.parts"

_WORKTREE = {
    "dir": "/w/t",
    "branch": "docket/demo/t",
    "baseCommit": "abc",
    "baseRef": "main",
    "gitDir": "/c/.git/worktrees/t",
    "commonDir": "/c/.git",
}
_ANSWER = {
    "questionId": "q-1",
    "step": "implementer",
    "message": "Which store?",
    "action": "accept",
    "content": {"answer": "sqlite"},
    "channel": "cli",
    "actor": "me",
    "answeredAt": "2026-10-24T00:00:00+00:00",
    "kind": "decision",
    "createdAt": "2026-10-23T00:00:00+00:00",
    "optionId": "sqlite",
}


def _dump(model: Any) -> dict[str, Any]:
    dumped: dict[str, Any] = model.model_dump(by_alias=True, mode="json")
    return dumped


class TestRoundTrip:
    @pytest.mark.parametrize(
        ("cls", "raw"),
        [
            (_parts.Worktree, _WORKTREE),
            (_parts.Worktree, {"dir": "", "branch": "", "baseCommit": "", "fallbackReason": "x"}),
            (_parts.Worktree, {**_WORKTREE, "prunedAt": "2026-10-24T00:00:00+00:00"}),
            (
                _parts.Prepared,
                {"command": "npm ci", "source": "lockfile", "lockHash": "h", "cacheHit": False},
            ),
            (_parts.Answer, _ANSWER),
            (
                _parts.TaskUsage,
                {
                    "input": 3,
                    "cached": 2,
                    "cacheWrite": 1,
                    "output": 4,
                    "byModel": {"local/x": {"input": 3, "cached": 2, "cacheWrite": 1, "output": 4}},
                },
            ),
        ],
    )
    def test_a_shape_dumps_the_keys_it_was_read_from(
        self, cls: type[_parts.Worktree], raw: dict[str, Any]
    ) -> None:
        assert _dump(cls.model_validate(raw)) == raw


class TestAbsentKeys:
    def test_an_unset_worktree_key_is_absent_not_null(self) -> None:
        dumped = _dump(_parts.Worktree(dir="/w", branch="b", base_commit="c"))
        assert dumped == {"dir": "/w", "branch": "b", "baseCommit": "c"}

    def test_an_answer_without_an_option_has_no_option_key_and_keeps_empty_content(self) -> None:
        raw = {k: v for k, v in _ANSWER.items() if k not in ("optionId", "content")}
        dumped = _dump(_parts.Answer.model_validate(raw))
        assert "optionId" not in dumped
        assert dumped["content"] is None


class TestClosed:
    def test_a_key_the_writer_never_wrote_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            _parts.Prepared.model_validate(
                {"command": "c", "source": "s", "lockHash": "h", "cacheHit": True, "extra": 1}
            )

    def test_the_field_name_is_accepted_beside_the_alias(self) -> None:
        answer = _parts.Answer(
            question_id="q-1",
            step="s",
            message="m",
            action="accept",
            channel="cli",
            actor="me",
            answered_at="t",
            created_at="t",
            option_id="yes",
        )
        assert _dump(answer)["optionId"] == "yes"
