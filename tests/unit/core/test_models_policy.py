"""Model registry (docket-models.json) malformed-entry visibility.

`load_registry` itself stays silently tolerant of a malformed `rankAnchors`/`default`/`roles`
entry (model-profiles.spec.md's User registry overlay contract) -- this covers the separate,
read-only `find_registry_problems` surface `docket doctor` reports through instead.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.core import models_policy as _mp

SUBJECT = "docket.core.models_policy"


def _point_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    repoint_docket_home(monkeypatch, home)
    return home


class TestFindRegistryProblems:
    def test_no_file_has_no_problems(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _point_at(tmp_path, monkeypatch)
        assert _mp.find_registry_problems() == []

    def test_well_formed_registry_has_no_problems(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _point_at(tmp_path, monkeypatch)
        home.mkdir(parents=True, exist_ok=True)
        _cfg.MODEL_REGISTRY_FILE.write_text(
            json.dumps(
                {
                    "default": "anthropic/claude-sonnet-4-6",
                    "rankAnchors": {"standard": "anthropic/claude-sonnet-4-6"},
                    "roles": {"reviewer": "anthropic/claude-haiku-4-5"},
                }
            )
        )
        assert _mp.find_registry_problems() == []

    def test_unknown_rank_anchor_is_named(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _point_at(tmp_path, monkeypatch)
        home.mkdir(parents=True, exist_ok=True)
        _cfg.MODEL_REGISTRY_FILE.write_text(
            json.dumps({"rankAnchors": {"deluxe": "anthropic/claude-sonnet-4-6"}})
        )
        problems = _mp.find_registry_problems()
        assert problems == [("rankAnchors.deluxe", "unknown rank anchor")]

    def test_bad_model_id_in_default_is_named(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _point_at(tmp_path, monkeypatch)
        home.mkdir(parents=True, exist_ok=True)
        _cfg.MODEL_REGISTRY_FILE.write_text(json.dumps({"default": "not-a-model-id"}))
        problems = _mp.find_registry_problems()
        assert len(problems) == 1
        assert problems[0][0] == "default"
        assert "not-a-model-id" in problems[0][1]

    def test_unknown_role_is_named(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = _point_at(tmp_path, monkeypatch)
        home.mkdir(parents=True, exist_ok=True)
        _cfg.MODEL_REGISTRY_FILE.write_text(
            json.dumps({"roles": {"astrologer": "anthropic/claude-haiku-4-5"}})
        )
        problems = _mp.find_registry_problems()
        assert problems == [("roles.astrologer", "unknown role")]

    def test_malformed_json_is_reported_by_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _point_at(tmp_path, monkeypatch)
        home.mkdir(parents=True, exist_ok=True)
        _cfg.MODEL_REGISTRY_FILE.write_text("{not json")
        problems = _mp.find_registry_problems()
        assert len(problems) == 1
        assert problems[0][0] == str(_cfg.MODEL_REGISTRY_FILE)
