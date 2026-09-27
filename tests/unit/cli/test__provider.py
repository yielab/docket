"""`docket models provider` -- the `add` shortcut builds the same document a file would.

`_build_shortcut_spec` is the seam between the hand-parsed shortcut and `core/provider.py`:
a `--credential NAME` makes a hosted bearer document; no credential makes a local one whose
defaults come from the built-in `local` document, never from a constant kept here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

from docket.cli import _provider

SUBJECT = "docket.cli._provider"


class TestShortcutSpec:
    def test_credential_makes_a_hosted_bearer_document(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repoint_docket_home(monkeypatch, tmp_path / ".docket")
        pos, opts = _provider._parse_opts(
            ["hosted", "https://api.example/v1", "--model", "m", "--credential", "HOSTED_API_KEY"]
        )

        spec = _provider._build_shortcut_spec(pos, opts)

        assert spec.name == "hosted"
        assert spec.base_url == "https://api.example/v1"
        assert spec.auth.type == "bearer"
        assert spec.auth.credentials == ["HOSTED_API_KEY"]
        assert spec.local is False
        assert [row.id for row in spec.models] == ["m"]

    def test_bare_add_takes_its_defaults_from_the_builtin_local_document(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repoint_docket_home(monkeypatch, tmp_path / ".docket")

        spec = _provider._build_shortcut_spec([], {})

        assert spec.name == "local"
        assert spec.base_url == "http://127.0.0.1:8080/v1"
        assert spec.auth.type == "none"
        assert spec.local is True
