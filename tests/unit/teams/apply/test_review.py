"""Unit coverage for ``teams.apply.plan``'s pure helpers -- see
``tests/integration/test_recipes.py`` for the end-to-end ``plan_apply``/``apply`` behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support.git import repo_dir as _repo_dir
from tests.support.pods import seed_fixture_pod as _seed_fixture_pod

import docket.kernel.templates as _templates
from docket.teams import pod_settings as _pod_settings
from docket.teams.apply import model as _model
from docket.teams.apply import plan as _pod_apply
from docket.teams.apply import review as _review
from docket.teams.apply import write as _write

SUBJECT = "docket.teams.apply.review"


class TestPrepare:
    """A team's `prepare:` is applied as the pod's setting and reviewed as a command."""

    def _recipe(self, tmp_path: Path, text: str) -> Path:
        recipe = tmp_path / "recipe"
        recipe.mkdir()
        (recipe / "pod.yaml").write_text("kind: pod\nname: x\n" + text, encoding="utf-8")
        return recipe

    def test_apply_stores_it_as_the_pods_setting_and_export_writes_it_back(
        self, tmp_path: Path
    ) -> None:
        with _seed_fixture_pod(tmp_path, "prep"):
            recipe = self._recipe(tmp_path, "kind: pod\nname: x\nprepare: make deps\n")
            plan = _pod_apply.plan_apply("prep", recipe)
            assert [(i.kind, i.name, i.action) for i in plan.items] == [
                ("setting", "prepare", "add")
            ]
            _write.apply(plan)
            assert _pod_settings.PodSettings.load_for("prep").prepare == "make deps"
            out = tmp_path / "out"
            _write.export_pod("prep", out)
            manifest = (out / "pod.yaml").read_text(encoding="utf-8")
            assert "prepare: make deps" in manifest and "settings" not in manifest

    def test_a_blank_prepare_is_stored_as_none(self, tmp_path: Path) -> None:
        with _seed_fixture_pod(tmp_path, "prep"):
            _write.apply(_pod_apply.plan_apply("prep", self._recipe(tmp_path, "prepare: ''\n")))
            assert _pod_settings.PodSettings.load_for("prep").prepare == "none"

    def test_prepare_inside_settings_is_refused(self, tmp_path: Path) -> None:
        with _seed_fixture_pod(tmp_path, "prep"):
            recipe = self._recipe(tmp_path, "settings:\n  prepare: make\n")
            with pytest.raises(_model.PodApplyError, match="top level"):
                _pod_apply.plan_apply("prep", recipe)

    @pytest.mark.parametrize("text", ["prepare: 3\n", "prepare: [a]\n", 'prepare: "a\\nb"\n'])
    def test_a_malformed_prepare_is_refused(self, tmp_path: Path, text: str) -> None:
        with _seed_fixture_pod(tmp_path, "prep"), pytest.raises(_model.PodApplyError):
            _pod_apply.plan_apply("prep", self._recipe(tmp_path, text))

    def test_a_declared_command_is_a_run_item_and_none_is_not(self, tmp_path: Path) -> None:
        declared = _review.classify_directory(self._recipe(tmp_path, "prepare: make deps\n"))
        assert [(i.kind, i.name, i.runs) for i in declared.runs] == [
            ("prepare", "prepare", "make deps")
        ]
        off = tmp_path / "off"
        off.mkdir()
        (off / "pod.yaml").write_text("kind: pod\nname: x\nprepare: none\n", encoding="utf-8")
        assert _review.classify_directory(off).runs == ()

    def test_a_repositorys_lockfile_command_is_a_run_item(self, tmp_path: Path) -> None:
        config = tmp_path / ".docket"
        config.mkdir()
        (tmp_path / "package-lock.json").write_text("{}")
        review = _review.classify_directory(config)
        assert [(i.kind, i.runs) for i in review.runs] == [("prepare", "npm ci")]
        team = config / "teams" / "web"
        team.mkdir(parents=True)
        assert [i.runs for i in _review.classify_directory(team).runs] == ["npm ci"]

    def test_a_lockfile_beside_an_ordinary_directory_is_not_reviewed(self, tmp_path: Path) -> None:
        (tmp_path / "package-lock.json").write_text("{}")
        recipe = tmp_path / "recipe"
        recipe.mkdir()
        assert _review.classify_directory(recipe).runs == ()


class TestClassifyDirectory:
    """A directory splits into adds and what runs on this machine."""

    def test_a_run_step_and_an_mcp_server_are_run_items(self, tmp_path: Path) -> None:
        root = _repo_dir(
            tmp_path,
            {
                "pipeline.yaml": "name: p\nsteps:\n  - id: migrate\n    run: sh scripts/migrate.sh\n",
                "mcp-servers/db.yaml": "kind: mcp-server\nname: db\ncommand: npx\nargs: [-y, '@acme/db-mcp@1.4.2']\n",
                "pod.yaml": "kind: pod\nname: x\nsettings:\n  network: open\n  allowCommands: [make]\n",
            },
        )
        review = _review.classify_directory(root)
        got = {(i.kind, i.name, i.runs) for i in review.runs}
        assert ("pipeline-step", "migrate", "sh scripts/migrate.sh") in got
        assert ("mcp-server", "db", "npx -y @acme/db-mcp@1.4.2") in got
        assert ("allow-commands", "allowCommands", "make") in got
        assert ("network", "network", "open") in got

    @pytest.mark.parametrize(
        ("step", "expected"),
        [
            ("  - build: implementer\n    verify: make check\n", ("verify", "build", "make check")),
            (
                "  - build: implementer\n    gate: {external: ./ci.sh}\n",
                ("gate", "build", "./ci.sh"),
            ),
            (
                "  - id: build\n    role: implementer\n    gate: {type: mechanical, command: make check}\n",
                ("verify", "build", "make check"),
            ),
            (
                "  - id: fan\n    parallel:\n      - id: lint\n        role: implementer\n"
                "        gate: {external: ./lint.sh}\n",
                ("gate", "lint", "./lint.sh"),
            ),
        ],
        ids=["short-verify", "short-external", "canonical-mechanical", "inside-parallel"],
    )
    def test_a_gate_command_is_a_run_item(
        self, tmp_path: Path, step: str, expected: tuple[str, str, str]
    ) -> None:
        root = _repo_dir(tmp_path, {"pipeline.yaml": "name: p\nsteps:\n" + step})
        review = _review.classify_directory(root)
        assert expected in {(i.kind, i.name, i.runs) for i in review.runs}

    def test_a_gate_without_a_command_runs_nothing(self, tmp_path: Path) -> None:
        root = _repo_dir(
            tmp_path,
            {"pipeline.yaml": "name: p\nsteps:\n  - build: implementer\n    verify: true\n"},
        )
        assert _review.classify_directory(root).runs == ()

    def test_policies_and_restricting_roles_are_adds_only(self, tmp_path: Path) -> None:
        root = _repo_dir(
            tmp_path,
            {
                "policies/no-secrets.json": "{}",
                "roles/api-reviewer.yaml": "kind: role\nname: api-reviewer\ncannot: [write]\n",
            },
        )
        review = _review.classify_directory(root)
        assert review.runs == ()
        assert ("policy", "no-secrets") in review.adds and ("role", "api-reviewer") in review.adds

    def test_a_role_that_drops_a_builtin_denial_is_a_run_item(self, tmp_path: Path) -> None:
        root = _repo_dir(
            tmp_path,
            {
                "roles/reviewer.yaml": "kind: role\nname: reviewer\nmodel: cheap\ndescription: x\n",
                "roles/reviewer.md": "Review.",
            },
        )
        review = _review.classify_directory(root)
        assert [(i.kind, i.name) for i in review.runs] == [("role-loosens", "reviewer")]

    def test_a_shell_in_allow_commands_is_refused(self, tmp_path: Path) -> None:
        root = _repo_dir(
            tmp_path, {"pod.yaml": "kind: pod\nname: x\nsettings:\n  allowCommands: [bash, make]\n"}
        )
        assert _review.classify_directory(root).refused == ("bash",)

    def test_shipped_recipes_are_exempt_and_other_directories_are_not(self, tmp_path: Path) -> None:
        shipped = next(p for p in _templates.RECIPES_DIR.iterdir() if p.is_dir())
        assert _review.is_shipped_recipe(shipped)
        assert not _review.is_shipped_recipe(tmp_path)


def test_repo_config_dir_prefers_the_pods_team_dir(tmp_path: Path) -> None:
    """A pod's `teams/<pod>/` wins over `.docket/`; without it the plain directory stands."""
    assert _review.repo_config_dir(tmp_path, "a") == tmp_path / ".docket"
    (tmp_path / ".docket" / "teams" / "a").mkdir(parents=True)
    assert _review.repo_config_dir(tmp_path, "a") == tmp_path / ".docket" / "teams" / "a"
    assert _review.repo_config_dir(tmp_path, "b") == tmp_path / ".docket"
    assert _review.repo_config_dir(tmp_path, "b", create=True) == (
        tmp_path / ".docket" / "teams" / "b"
    )


def test_repo_root_of_a_team_dir_is_the_codebase(tmp_path: Path) -> None:
    """The reviewed-repository key is the codebase for both directory shapes."""
    assert _review.repo_root(tmp_path / ".docket" / "teams" / "a") == tmp_path
    assert _review.repo_root(tmp_path / ".docket") == tmp_path


class TestReviewDecision:
    """The review rule's verdict for a directory, an optional accept code and a repo root."""

    def _runs(self, tmp_path: Path) -> Path:
        return _repo_dir(
            tmp_path, {"pod.yaml": "kind: pod\nname: x\nsettings:\n  allowCommands: [make]\n"}
        )

    def test_nothing_to_run_and_shipped_recipes_go(self, tmp_path: Path) -> None:
        plain = _repo_dir(tmp_path, {"policies/p.json": "{}"})
        assert _review.review_decision(tmp_path, "a", plain, None).status == "go"
        shipped = next(p for p in _templates.RECIPES_DIR.iterdir() if p.is_dir())
        assert _review.review_decision(tmp_path, "a", shipped, "bogus").status == "go"

    def test_run_items_need_the_code_then_accept_it(self, tmp_path: Path) -> None:
        directory = self._runs(tmp_path)
        first = _review.review_decision(tmp_path, "a", directory, None)
        assert first.status == "needs_code" and len(first.code) == 16
        assert _review.review_decision(tmp_path, "a", directory, first.code).status == "accepted"
        assert _review.review_decision(tmp_path, "a", directory, "0" * 16).status == "code_mismatch"

    def test_a_shell_is_refused_before_any_code_matters(self, tmp_path: Path) -> None:
        directory = _repo_dir(
            tmp_path, {"pod.yaml": "kind: pod\nname: x\nsettings:\n  allowCommands: [bash]\n"}
        )
        assert _review.review_decision(tmp_path, "a", directory, "x").status == "refused"

    def test_a_remembered_review_goes(self, tmp_path: Path) -> None:
        from docket.governance import review as _reviewed

        directory = self._runs(tmp_path)
        _reviewed.remember(tmp_path, "a", _review.classify_directory(directory).runs)
        assert _review.review_decision(tmp_path, "a", directory, None).status == "go"

    def test_a_second_pod_on_the_same_codebase_keeps_the_first_approval(
        self, tmp_path: Path
    ) -> None:
        """Pod b's approval does not make pod a ask again; a returning set still goes."""
        from docket.governance import review as _reviewed

        directory = self._runs(tmp_path)
        items = _review.classify_directory(directory).runs
        _reviewed.remember(tmp_path, "a", items)
        _reviewed.remember(tmp_path, "b", items)
        assert _review.review_decision(tmp_path, "a", directory, None).status == "go"
        assert _review.review_decision(tmp_path, "b", directory, None).status == "go"
        assert _review.review_decision(tmp_path, "c", directory, None).status == "needs_code"
