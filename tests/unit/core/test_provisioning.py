"""``core/provisioning.py`` — the id normaliser (`slugify`) and the id
validator (`validate_project_id`) enforced at the provisioning boundary.

`validate_project_id` accepts exactly what `slugify` can ever emit: lowercase
alphanumeric segments joined by single hyphens, non-empty, at most 64
characters. See specs/validation/input-validation.spec.md §1.
"""

from __future__ import annotations

import pytest

from docket.core import provisioning as _prov

SUBJECT = "docket.core.provisioning"


class TestValidateProjectId:
    @pytest.mark.parametrize("project", ["a", "docket-dev", "x1-y2"])
    def test_accepts_valid_ids(self, project: str) -> None:
        assert _prov.validate_project_id(project) == project

    @pytest.mark.parametrize(
        "project",
        [
            "",
            "../x",
            "a/b",
            "A",
            "a--b",
            "-a",
            "a-",
            "a" * 65,
            "a:b",
        ],
    )
    def test_rejects_invalid_ids(self, project: str) -> None:
        with pytest.raises(_prov.ProjectIdError):
            _prov.validate_project_id(project)

    def test_error_message_truncates_rejected_value_to_40_chars(self) -> None:
        long_bad = "A" * 200
        with pytest.raises(_prov.ProjectIdError) as exc_info:
            _prov.validate_project_id(long_bad)
        # The message must never echo more than 40 characters of the input.
        assert "A" * 41 not in str(exc_info.value)
        assert "A" * 40 in str(exc_info.value)

    @pytest.mark.parametrize(
        "name",
        ["My Shop API", "  ai-site-generator  ", "docket-dev", "Weird!!Name__2"],
    )
    def test_every_slugify_output_passes_validation(self, name: str) -> None:
        # Non-goal: no migration of existing pods -- every id `slugify` can
        # produce must already satisfy `validate_project_id`.
        slug = _prov.slugify(name)
        assert _prov.validate_project_id(slug) == slug
