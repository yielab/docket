"""Unit coverage for ``teams.config_models``'s routine validators -- the error-to-field mapping
of ``load_document`` is covered in ``test_config_docs.py``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from docket.teams.config_models import RoutineDocument

SUBJECT = "docket.teams.config_models"

_ROUTINE = {
    "kind": "routine",
    "name": "morning",
    "schedule": "0 9 * * 1-5",
    "tz": "America/Bogota",
    "task": {"description": "read the overnight tickets"},
}


def test_a_routine_with_a_cron_schedule_and_a_known_zone_validates() -> None:
    document = RoutineDocument.model_validate(_ROUTINE)

    assert (document.schedule, document.tz) == ("0 9 * * 1-5", "America/Bogota")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schedule", "09:00"),
        ("schedule", "every day"),
        ("tz", "Mars/Olympus"),
        ("task", {"description": ""}),
    ],
)
def test_a_routine_with_a_bad_value_is_refused_at_that_field(field: str, value: object) -> None:
    with pytest.raises(ValidationError) as exc_info:
        RoutineDocument.model_validate({**_ROUTINE, field: value})

    assert exc_info.value.errors()[0]["loc"][0] == field
