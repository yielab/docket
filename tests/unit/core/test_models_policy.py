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


class TestResolveStepModel:
    """A pipeline step's own ``model`` (pipeline-format.spec.md Steps Req. 10) resolved for
    one hop -- model-profiles.spec.md's "Model intent per agent" requirement 4."""

    def test_rank_word_resolves_to_the_live_anchor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _point_at(tmp_path, monkeypatch)
        _, tiers, _ = _mp.load_registry()
        assert _mp.resolve_step_model("cheap") == tiers["economy"]
        assert _mp.resolve_step_model("strong") == tiers["standard"]

    def test_literal_with_unknown_provider_is_refused_by_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _point_at(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="nope"):
            _mp.resolve_step_model("nope/x")


class TestResolveRoleModelInPodScope:
    """A pod-scoped archetype resolves through its pod's registry against the live anchors;
    an unknown role falls back to the registry's own default, never the compiled-in literal."""

    def _registry_on_local(self, home: Path) -> None:
        home.mkdir(parents=True, exist_ok=True)
        _cfg.MODEL_REGISTRY_FILE.write_text(
            json.dumps(
                {
                    "default": "local/x",
                    "rankAnchors": {
                        "economy": "local/x",
                        "standard": "local/x",
                        "premium": "local/x",
                    },
                    "roles": {},
                }
            ),
            encoding="utf-8",
        )

    def test_pod_scoped_archetype_resolves_against_the_live_anchors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.core import archetypes as _arch
        from docket.core import config_docs as _config_docs

        home = _point_at(tmp_path, monkeypatch)
        monkeypatch.setattr(_cfg, "ARCHETYPE_REGISTRY_FILE", tmp_path / "docket-roles.json")
        self._registry_on_local(home)
        role_file = _cfg.recipes_dir() / "secure-build" / "roles" / "security-vetter.yaml"
        _arch.add_user_archetype(_config_docs.load_document(role_file, kind="role").doc, "p")

        assert _mp.resolve_role_model("security-vetter", project="p") == "local/x"

    def test_unknown_role_falls_back_to_the_registry_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _point_at(tmp_path, monkeypatch)
        monkeypatch.setattr(_cfg, "ARCHETYPE_REGISTRY_FILE", tmp_path / "docket-roles.json")
        self._registry_on_local(home)

        assert _mp.resolve_role_model("nobody-here") == "local/x"


class TestOneRoleVocabulary:
    """The policy speaks archetype names: one vocabulary for a member, its archetype and its row."""

    def test_policy_roles_are_the_archetype_names(self) -> None:
        from docket.core import archetypes as _arch

        names = set(_arch.BUILTIN_ARCHETYPES) | set(_arch.STARTER_ARCHETYPES)
        assert set(_mp.ALL_ROLES) == names
        assert set(_mp.ROLE_CLASS) == names

    def test_implementer_reads_its_own_row(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _point_at(tmp_path, monkeypatch)
        home.mkdir(parents=True, exist_ok=True)
        _cfg.MODEL_REGISTRY_FILE.write_text(
            json.dumps({"roles": {"implementer": "openai/gpt-4.1"}}), encoding="utf-8"
        )
        assert _mp.resolve_role_model("implementer") == "openai/gpt-4.1"

    def test_a_retired_role_key_is_ignored_and_reported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _point_at(tmp_path, monkeypatch)
        home.mkdir(parents=True, exist_ok=True)
        _cfg.MODEL_REGISTRY_FILE.write_text(
            json.dumps({"roles": {"programmer": "openai/gpt-4.1"}}), encoding="utf-8"
        )
        assert _mp.resolve_role_model("implementer") != "openai/gpt-4.1"
        assert _mp.find_registry_problems() == [("roles.programmer", "unknown role")]
        _cfg.MODEL_REGISTRY_FILE.unlink()
        _mp.write_registry({"role.programmer": "x/y"})
        assert "programmer" not in json.loads(_cfg.MODEL_REGISTRY_FILE.read_text()).get("roles", {})
