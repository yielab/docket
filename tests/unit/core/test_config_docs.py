"""Unit coverage for ``core.config_docs``'s envelope dispatch -- see
``tests/integration/test_validate_cli.py`` for the ``docket validate`` command itself."""

from __future__ import annotations

from pathlib import Path

import pytest

from docket.core import archetypes as _archetypes
from docket.core import config_docs

SUBJECT = "docket.core.config_docs"


def test_an_unknown_kind_raises_naming_every_known_kind(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("kind: banana\nname: whatever\n", encoding="utf-8")

    with pytest.raises(config_docs.ConfigDocError) as exc_info:
        config_docs.load_document(path)

    error = exc_info.value
    assert error.valid == config_docs.KINDS
    assert set(config_docs.KINDS) == {"role", "pipeline", "policy", "pod"}
    assert (
        str(error) == f"{path}:1 kind: unknown kind 'banana' (valid: role, pipeline, policy, pod)"
    )


def test_a_role_file_without_kind_loads_deprecated_and_matches_parse_yaml_file(
    tmp_path: Path,
) -> None:
    text = (
        "name: custom-role\n"
        "scope: org\n"
        "modelClass: cheap\n"
        "editRights: none\n"
        "soulTemplate: You are the custom role.\n"
        "agentsTemplate: Custom role protocol.\n"
    )
    path = tmp_path / "custom-role.yaml"
    path.write_text(text, encoding="utf-8")

    document = config_docs.load_document(path, kind="role")

    assert document.kind == "role"
    assert document.name == "custom-role"
    assert document.deprecated is True
    assert document.doc == _archetypes.parse_yaml_file(str(path))
