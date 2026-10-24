"""The question a consultation parked, kept on disk until the operator answers it.

``tasks`` writes it when a hop parks, ``hops`` takes it back when the hop ends; both reach it
through the platform facade, so neither context imports the other for it.
"""

from __future__ import annotations

import contextlib
import re
from pathlib import Path

from pydantic import ValidationError

from docket.kernel.home import current_home
from docket.kernel.operator_contract import QuestionV11
from docket.platform.store import read_json, write_json

PARK_TOKEN_PREFIX = "consult:"

_QUESTION_ID = re.compile(r"q-[0-9a-f]{1,32}")


def is_question_id(question_id: str) -> bool:
    """Whether *question_id* is one ``new_question_id`` could have minted."""
    return _QUESTION_ID.fullmatch(question_id) is not None


def _parked_file(question_id: str) -> Path:
    return current_home().consult_parked_dir / f"{question_id}.json"


def write_parked(question: QuestionV11) -> None:
    """Persist *question* under its id (0600, atomic)."""
    write_json(_parked_file(question.id), question.model_dump(by_alias=True, mode="json"))


def parked_question(token: str) -> QuestionV11 | None:
    """Take the question ``park_token`` persisted for *token*: read once, then removed. ``None``
    when *token* is not a consult token or its question is absent or invalid."""
    if not token.startswith(PARK_TOKEN_PREFIX):
        return None
    question_id = token[len(PARK_TOKEN_PREFIX) :]
    if not is_question_id(question_id):
        return None
    path = _parked_file(question_id)
    data = read_json(path)
    for leftover in (path, path.with_suffix(path.suffix + ".bak")):
        with contextlib.suppress(OSError):
            leftover.unlink()
    try:
        return QuestionV11.model_validate(data) if data else None
    except ValidationError:
        return None
