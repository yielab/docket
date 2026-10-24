"""Unit coverage for ``teams.apply.plan``'s pure helpers -- see
``tests/integration/test_recipes.py`` for the end-to-end ``plan_apply``/``apply`` behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.support.git import repo_dir as _repo_dir
from tests.support.pods import seed_fixture_pod as _seed_fixture_pod

from docket.kernel.home import current_home
from docket.teams import pod_settings as _pod_settings
from docket.teams.apply import model as _model
from docket.teams.apply import plan as _pod_apply
from docket.teams.apply import recipes as _recipes
from docket.teams.apply import review as _review
from docket.teams.apply import write as _write

SUBJECT = "docket.teams.apply.plan"


class TestRolesInEveryConfigFormat:
    """`roles/` takes `.yaml`, `.yml` and `.json`, the file set `pod validate` counts."""

    def test_a_yml_and_a_json_role_are_planned_and_applied(self, tmp_path: Path) -> None:
        project = "formats"
        with _seed_fixture_pod(tmp_path, project):
            recipe_dir = tmp_path / "recipe"
            (recipe_dir / "roles").mkdir(parents=True)
            base = {
                "kind": "role",
                "scope": "pod",
                "modelClass": "cheap",
                "soulTemplate": "You vet.",
                "agentsTemplate": "Protocol.",
            }
            (recipe_dir / "roles" / "from-yml.yml").write_text(
                "\n".join(f"{k}: {v}" for k, v in {**base, "name": "from-yml"}.items()),
                encoding="utf-8",
            )
            (recipe_dir / "roles" / "from-json.json").write_text(
                json.dumps({**base, "name": "from-json"}), encoding="utf-8"
            )

            plan = _pod_apply.plan_apply(project, recipe_dir)

            assert sorted(i.name for i in plan.items if i.kind == "role") == [
                "from-json",
                "from-yml",
            ]
            _write.apply(plan)
            roles = json.loads((current_home().pod_config_dir(project) / "roles.json").read_text())[
                "roles"
            ]
            assert {"from-yml", "from-json"} <= set(roles)

    def test_a_json_role_that_drops_a_builtin_denial_is_a_run_item(self, tmp_path: Path) -> None:
        root = _repo_dir(
            tmp_path,
            {
                "roles/reviewer.json": json.dumps(
                    {"kind": "role", "name": "reviewer", "model": "cheap", "description": "x"}
                ),
                "roles/reviewer.md": "Review.",
            },
        )
        review = _review.classify_directory(root)
        assert [(i.kind, i.name) for i in review.runs] == [("role-loosens", "reviewer")]


class TestRecipeExporters:
    """A recipe may name an observability destination without carrying one (ADR 0014 rule
    7): `apply` records the names and reports state, and never activates or writes an
    exporter document. See `tests/integration/test_recipes.py` for the end-to-end CLI path."""

    def test_summarize_recipe_reads_and_renders_the_declared_names(self, tmp_path: Path) -> None:
        (tmp_path / "pod.yaml").write_text(
            "kind: pod\nname: x\nexporters: [langfuse]\n", encoding="utf-8"
        )

        summary = _recipes.summarize_recipe(tmp_path)

        assert summary.exporters == ("langfuse",)
        assert summary.render() == (
            "roles 0 · policies 0 · members 0 · pipeline none · plugins 0 · skills 0 · "
            "settings 0 · exporters langfuse"
        )

    def test_apply_records_the_names_and_writes_no_exporter_document(self, tmp_path: Path) -> None:
        project = "observed"
        with _seed_fixture_pod(tmp_path, project):
            recipe_dir = tmp_path / "recipe"
            recipe_dir.mkdir()
            (recipe_dir / "pod.yaml").write_text(
                "kind: pod\nname: x\nexporters: [langfuse]\n", encoding="utf-8"
            )

            plan = _pod_apply.plan_apply(project, recipe_dir)
            assert plan.exporters == ("langfuse",)
            assert all(item.action == "skip" for item in plan.items)

            result = _write.apply(plan)

            assert result.exporters == ("langfuse",)
            assert _pod_settings.PodSettings.load_for(project).exporters == ("langfuse",)
            assert not current_home().exporters_file.exists()

    def test_plan_apply_rejects_a_credential_shaped_entry(self, tmp_path: Path) -> None:
        project = "shaped"
        with _seed_fixture_pod(tmp_path, project):
            recipe_dir = tmp_path / "recipe"
            recipe_dir.mkdir()
            (recipe_dir / "pod.yaml").write_text(
                "kind: pod\nname: x\nexporters:\n  - endpoint: https://example.test\n",
                encoding="utf-8",
            )

            with pytest.raises(_model.PodApplyError, match="exporters"):
                _pod_apply.plan_apply(project, recipe_dir)

            assert not current_home().exporters_file.exists()
            assert _pod_settings.PodSettings.load_for(project).exporters == ()

    def test_plan_apply_rejects_an_unknown_exporter_name(self, tmp_path: Path) -> None:
        project = "unknownexp"
        with _seed_fixture_pod(tmp_path, project):
            recipe_dir = tmp_path / "recipe"
            recipe_dir.mkdir()
            (recipe_dir / "pod.yaml").write_text(
                "kind: pod\nname: x\nexporters: [nope]\n", encoding="utf-8"
            )

            with pytest.raises(_model.PodApplyError, match="exporters"):
                _pod_apply.plan_apply(project, recipe_dir)

            assert _pod_settings.PodSettings.load_for(project).exporters == ()


class TestProtects:
    """A team's `protects:` is applied as the pod's setting and exported back, never reviewed."""

    def _recipe(self, tmp_path: Path, text: str) -> Path:
        recipe = tmp_path / "recipe"
        recipe.mkdir()
        (recipe / "pod.yaml").write_text("kind: pod\nname: x\n" + text, encoding="utf-8")
        return recipe

    def test_apply_stores_the_list_and_export_writes_it_back(self, tmp_path: Path) -> None:
        with _seed_fixture_pod(tmp_path, "guard"):
            recipe = self._recipe(
                tmp_path, "kind: pod\nname: x\nprotects: ['src/api/*', Makefile]\n"
            )
            plan = _pod_apply.plan_apply("guard", recipe)
            assert [(i.kind, i.name, i.action) for i in plan.items] == [
                ("setting", "protects", "add")
            ]
            _write.apply(plan)
            assert _pod_settings.PodSettings.load_for("guard").protects == ("src/api/*", "Makefile")
            out = tmp_path / "out"
            _write.export_pod("guard", out)
            manifest = (out / "pod.yaml").read_text(encoding="utf-8")
            assert "protects:" in manifest and "settings" not in manifest

    def test_an_empty_list_clears_the_patterns(self, tmp_path: Path) -> None:
        with _seed_fixture_pod(tmp_path, "guard"):
            _write.apply(_pod_apply.plan_apply("guard", self._recipe(tmp_path, "protects: [a]\n")))
            (tmp_path / "recipe" / "pod.yaml").write_text(
                "kind: pod\nname: x\nprotects: []\n", encoding="utf-8"
            )
            _write.apply(_pod_apply.plan_apply("guard", tmp_path / "recipe"))
            assert _pod_settings.PodSettings.load_for("guard").protects == ()

    def test_protects_inside_settings_is_refused(self, tmp_path: Path) -> None:
        with _seed_fixture_pod(tmp_path, "guard"):
            recipe = self._recipe(tmp_path, "settings:\n  protects: a\n")
            with pytest.raises(_model.PodApplyError, match="top level"):
                _pod_apply.plan_apply("guard", recipe)

    @pytest.mark.parametrize(
        "text", ["protects: a\n", "protects: [1]\n", "protects: ['/abs']\n", "protects: ['']\n"]
    )
    def test_a_malformed_protects_is_refused(self, tmp_path: Path, text: str) -> None:
        with (
            _seed_fixture_pod(tmp_path, "guard"),
            pytest.raises(_model.PodApplyError, match="protects"),
        ):
            _pod_apply.plan_apply("guard", self._recipe(tmp_path, text))

    def test_protects_is_not_a_run_item(self, tmp_path: Path) -> None:
        review = _review.classify_directory(self._recipe(tmp_path, "protects: [a]\n"))
        assert review.runs == () and ("setting", "protects") in review.adds


_FAST = "name: fast\nsteps:\n  - build: implementer\n    verify: make check\n"


class TestPodLocalPipelines:
    """``pipelines/<name>.yaml`` travels with ``update`` and ``export``; dispatch reads the copy."""

    def test_update_copies_the_file_where_a_task_resolves_it(self, tmp_path: Path) -> None:
        from docket.hops.application import steps as _steps

        with _seed_fixture_pod(tmp_path, "demo"):
            root = _repo_dir(tmp_path, {"pipelines/fast.yaml": _FAST})
            plan = _pod_apply.plan_apply("demo", root)
            assert ("pipeline", "pipelines/fast.yaml", "add") in {
                (i.kind, i.name, i.action) for i in plan.items
            }
            _write.apply(plan, channel="cli")
            path, source = _steps._task_pipeline_file("demo", "fast") or (None, None)
            assert source == "pod:fast" and path is not None
            assert path.read_text() == _FAST and oct(path.stat().st_mode & 0o777) == "0o600"
            again = _pod_apply.plan_apply("demo", root)
            assert ("pipeline", "pipelines/fast.yaml", "skip") in {
                (i.kind, i.name, i.action) for i in again.items
            }

    def test_export_writes_it_back_byte_for_byte(self, tmp_path: Path) -> None:
        with _seed_fixture_pod(tmp_path, "demo"):
            root = _repo_dir(tmp_path, {"pipelines/fast.yaml": _FAST})
            _write.apply(_pod_apply.plan_apply("demo", root), channel="cli")
            out = tmp_path / "exported"
            _write.export_pod("demo", out)
            assert (out / "pipelines" / "fast.yaml").read_text() == _FAST

    @pytest.mark.parametrize(
        ("name", "text", "message"),
        [
            ("fast.yaml", "name: fast\nsteps: []\n", "pipelines/fast.yaml"),
            ("Fast.yaml", _FAST, "not a pipeline name"),
        ],
        ids=["invalid", "bad-name"],
    )
    def test_a_file_dispatch_could_not_run_is_refused(
        self, tmp_path: Path, name: str, text: str, message: str
    ) -> None:
        with _seed_fixture_pod(tmp_path, "demo"):
            root = _repo_dir(tmp_path, {f"pipelines/{name}": text})
            with pytest.raises(_model.PodApplyError, match=message):
                _pod_apply.plan_apply("demo", root)

    def test_its_commands_need_the_review(self, tmp_path: Path) -> None:
        root = _repo_dir(
            tmp_path,
            {"pipelines/fast.yaml": _FAST + "  - id: migrate\n    run: make migrate\n"},
        )
        review = _review.classify_directory(root)
        got = {(i.kind, i.name, i.runs) for i in review.runs}
        assert ("verify", "fast/build", "make check") in got
        assert ("pipeline-step", "fast/migrate", "make migrate") in got
        assert ("pipeline", "pipelines/fast.yaml") in review.adds

    def test_summary_and_validate_name_it(self, tmp_path: Path) -> None:
        from docket.teams import config_docs as _config_docs

        root = _repo_dir(tmp_path, {"pipelines/fast.yaml": _FAST})
        summary = _recipes.summarize_recipe(root)
        assert summary.pipelines == ("fast",)
        assert summary.render().endswith(" · pipelines fast")
        results = _config_docs.validate_path(root)
        assert [(r.path.name, r.error) for r in results] == [("fast.yaml", None)]


class TestSkippedSettingsSayWhy:
    """A setting the pod already holds by default plans ``skip`` with the reason."""

    def test_a_default_value_is_noted_and_a_set_one_is_not(self, tmp_path: Path) -> None:
        with _seed_fixture_pod(tmp_path, "demo"):
            root = _repo_dir(
                tmp_path, {"pod.yaml": "kind: pod\nname: x\nsettings:\n  approvalMode: wait\n"}
            )
            [item] = [i for i in _pod_apply.plan_apply("demo", root).items if i.kind == "setting"]
            assert (item.action, item.note) == ("skip", "already the default")
            root = _repo_dir(
                tmp_path / "b",
                {"pod.yaml": "kind: pod\nname: x\nsettings:\n  maxReworkCycles: 4\n"},
            )
            _write.apply(_pod_apply.plan_apply("demo", root), channel="cli")
            [item] = [i for i in _pod_apply.plan_apply("demo", root).items if i.kind == "setting"]
            assert (item.action, item.note) == ("skip", "")
