"""Model registry (docket-models.json) malformed-entry visibility.

`load_registry` itself stays silently tolerant of a malformed `rankAnchors`/`default`/`roles`
entry (model-profiles.spec.md's User registry overlay contract) -- this covers the separate,
read-only `find_registry_problems` surface `docket setup` reports through instead.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

import docket.kernel.templates as _templates
from docket.kernel.home import Home, current_home, use_home
from docket.teams import model_selection as _mp

SUBJECT = "docket.teams.model_selection"


@contextmanager
def _point_at(
    tmp_path: Path,
) -> Iterator[Path]:
    home = tmp_path / ".docket"
    with use_home(Home(home)):
        yield home


class TestFindRegistryProblems:
    def test_no_file_has_no_problems(self, tmp_path: Path) -> None:
        with _point_at(tmp_path):
            assert _mp.find_registry_problems() == []

    def test_well_formed_registry_has_no_problems(self, tmp_path: Path) -> None:
        with _point_at(tmp_path):
            current_home().config_dir.mkdir(parents=True, exist_ok=True)
            current_home().model_registry_file.write_text(
                json.dumps(
                    {
                        "default": "anthropic/claude-sonnet-4-6",
                        "rankAnchors": {"standard": "anthropic/claude-sonnet-4-6"},
                        "roles": {"reviewer": "anthropic/claude-haiku-4-5"},
                    }
                )
            )
            assert _mp.find_registry_problems() == []

    def test_unknown_rank_anchor_is_named(self, tmp_path: Path) -> None:
        with _point_at(tmp_path):
            current_home().config_dir.mkdir(parents=True, exist_ok=True)
            current_home().model_registry_file.write_text(
                json.dumps({"rankAnchors": {"deluxe": "anthropic/claude-sonnet-4-6"}})
            )
            problems = _mp.find_registry_problems()
            assert problems == [("rankAnchors.deluxe", "unknown rank anchor")]

    def test_bad_model_id_in_default_is_named(self, tmp_path: Path) -> None:
        with _point_at(tmp_path):
            current_home().config_dir.mkdir(parents=True, exist_ok=True)
            current_home().model_registry_file.write_text(json.dumps({"default": "not-a-model-id"}))
            problems = _mp.find_registry_problems()
            assert len(problems) == 1
            assert problems[0][0] == "default"
            assert "not-a-model-id" in problems[0][1]

    def test_unknown_role_is_named(self, tmp_path: Path) -> None:
        with _point_at(tmp_path):
            current_home().config_dir.mkdir(parents=True, exist_ok=True)
            current_home().model_registry_file.write_text(
                json.dumps({"roles": {"astrologer": "anthropic/claude-haiku-4-5"}})
            )
            problems = _mp.find_registry_problems()
            assert problems == [("roles.astrologer", "unknown role")]

    def test_malformed_json_is_reported_by_file(self, tmp_path: Path) -> None:
        with _point_at(tmp_path):
            current_home().config_dir.mkdir(parents=True, exist_ok=True)
            current_home().model_registry_file.write_text("{not json")
            problems = _mp.find_registry_problems()
            assert len(problems) == 1
            assert problems[0][0] == str(current_home().model_registry_file)


class TestResolveStepModel:
    """A pipeline step's own ``model`` (pipeline-format.spec.md Steps Req. 10) resolved for
    one hop -- model-profiles.spec.md's "Where a member's model comes from" requirement 3."""

    def test_rank_word_resolves_to_the_live_anchor(self, tmp_path: Path) -> None:
        with _point_at(tmp_path):
            _, tiers, _ = _mp.load_registry()
            assert _mp.resolve_step_model("cheap") == tiers["economy"]
            assert _mp.resolve_step_model("strong") == tiers["standard"]

    def test_literal_with_unknown_provider_is_refused_by_name(self, tmp_path: Path) -> None:
        with _point_at(tmp_path), pytest.raises(ValueError, match="nope"):
            _mp.resolve_step_model("nope/x")


class TestResolveRoleModelInPodScope:
    """A pod-scoped archetype resolves through its pod's registry against the live anchors;
    an unknown role falls back to the registry's own default, never the compiled-in literal."""

    def _registry_on_local(self, home: Path) -> None:
        current_home().config_dir.mkdir(parents=True, exist_ok=True)
        current_home().model_registry_file.write_text(
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

    def test_pod_scoped_archetype_resolves_against_the_live_anchors(self, tmp_path: Path) -> None:
        from docket.teams import config_docs as _config_docs
        from docket.teams import roles as _arch

        with _point_at(tmp_path) as home:
            self._registry_on_local(home)
            role_file = _templates.RECIPES_DIR / "secure-build" / "roles" / "security-vetter.yaml"
            _arch.add_user_archetype(_config_docs.load_document(role_file).doc, "p")

            assert _mp.resolve_role_model("security-vetter", project="p") == "local/x"

    def test_unknown_role_falls_back_to_the_registry_default(self, tmp_path: Path) -> None:
        with _point_at(tmp_path) as home:
            self._registry_on_local(home)

            assert _mp.resolve_role_model("nobody-here") == "local/x"


class TestOneRoleVocabulary:
    """The policy speaks archetype names: one vocabulary for a member, its archetype and its row."""

    def test_policy_roles_are_the_archetype_names(self) -> None:
        from docket.teams import builtin_roles as _builtin_roles

        names = set(_builtin_roles.BUILTIN_ARCHETYPES) | set(_builtin_roles.STARTER_ARCHETYPES)
        assert set(_mp.ALL_ROLES) == names
        assert set(_mp.ROLE_CLASS) == names

    def test_each_role_resolves_to_the_rank_its_archetype_declares(self, tmp_path: Path) -> None:
        """Analyst resolves on the economy rank and critic on the standard rank, and the
        archetype's own `modelClass` says the same: one class per role."""
        from docket.teams import builtin_roles as _builtin_roles

        with _point_at(tmp_path):
            _, tiers, _ = _mp.load_registry()
            declared = {**_builtin_roles.BUILTIN_ARCHETYPES, **_builtin_roles.STARTER_ARCHETYPES}
            assert _mp.resolve_role_model("analyst") == tiers["economy"]
            assert _mp.resolve_role_model("critic") == tiers["standard"]
            for role in _mp.ALL_ROLES:
                rank = "economy" if declared[role].model_class == "cheap" else "standard"
                assert _mp.resolve_role_model(role) == tiers[rank], role
                assert _mp.ROLE_CLASS[role] == declared[role].model_class, role

    def test_implementer_reads_its_own_row(self, tmp_path: Path) -> None:
        with _point_at(tmp_path):
            current_home().config_dir.mkdir(parents=True, exist_ok=True)
            current_home().model_registry_file.write_text(
                json.dumps({"roles": {"implementer": "openai/gpt-4.1"}}), encoding="utf-8"
            )
            assert _mp.resolve_role_model("implementer") == "openai/gpt-4.1"

    def test_a_retired_role_key_is_ignored_and_reported(self, tmp_path: Path) -> None:
        with _point_at(tmp_path):
            current_home().config_dir.mkdir(parents=True, exist_ok=True)
            current_home().model_registry_file.write_text(
                json.dumps({"roles": {"programmer": "openai/gpt-4.1"}}), encoding="utf-8"
            )
            assert _mp.resolve_role_model("implementer") != "openai/gpt-4.1"
            assert _mp.find_registry_problems() == [("roles.programmer", "unknown role")]
            current_home().model_registry_file.unlink()
            _mp.write_registry({"role.programmer": "x/y"})
            assert "programmer" not in json.loads(
                current_home().model_registry_file.read_text()
            ).get("roles", {})


class TestReapplyRolePolicy:
    """Re-resolution follows the same rule as a fresh resolution: the registry default, never
    the compiled-in model, for a pod-scoped archetype with no row."""

    def test_pod_scoped_archetype_follows_the_registry_default(self, tmp_path: Path) -> None:
        from docket.platform import store as _store
        from docket.teams import fleet as _fleet

        with _point_at(tmp_path):
            current_home().config_dir.mkdir(parents=True, exist_ok=True)
            current_home().model_registry_file.write_text(
                json.dumps({"default": "local/local-model"}), encoding="utf-8"
            )
            aid = "demo-security-vetter"
            path = current_home().meta_path(aid)
            path.parent.mkdir(parents=True, exist_ok=True)
            _store.write_json(
                path,
                {
                    "schemaVersion": 1,
                    "kind": "project",
                    "scope": "project",
                    "role": "security-vetter",
                    "pod": "demo",
                    "model": current_home().default_model,
                },
            )

            assert _mp.reapply_role_policy() == [
                _mp.RoleRepoint(
                    aid,
                    "demo",
                    "security-vetter",
                    current_home().default_model,
                    "local/local-model",
                )
            ]
            assert _fleet.meta_get(aid, "model", "") == "local/local-model"


class TestRankAnchorsFailLoudly:
    """A catalog whose `anthropic` preset lacks a rank anchor is a document error, not a KeyError."""

    @pytest.mark.parametrize(
        ("presets", "missing"),
        [
            ([], "economy"),
            ([{"name": "anthropic", "ranks": {"standard": "m"}}], "economy"),
            ([{"name": "anthropic", "ranks": {"economy": "m"}}], "standard"),
            ([{"name": "other", "ranks": {"economy": "m", "standard": "m"}}], "economy"),
        ],
    )
    def test_load_registry_names_the_missing_anchor(
        self,
        tmp_path: Path,
        presets: list[dict[str, object]],
        missing: str,
    ) -> None:
        from docket.kernel.errors import DocumentError
        from docket.models import catalog as _provider

        with _point_at(tmp_path):
            builtin = _provider.load_catalog().get("anthropic")
            assert builtin is not None
            broken = _provider.ProviderSpec.model_validate(
                {**builtin.model_dump(by_alias=True), "presets": presets}
            )
            _provider.save_provider(broken)

            with pytest.raises(DocumentError) as excinfo:
                _mp.load_registry()

            assert missing in str(excinfo.value)
            assert str(current_home().providers_file) in str(excinfo.value)
