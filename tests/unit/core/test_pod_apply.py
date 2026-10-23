"""Unit coverage for ``core.pod_apply``'s pure helpers -- see
``tests/integration/test_recipes.py`` for the end-to-end ``plan_apply``/``apply`` behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.core import orchestrator as _orch
from docket.core import pod
from docket.core import pod_apply as _pod_apply

SUBJECT = "docket.core.pod_apply"


def _seed_fixture_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str) -> None:
    """A minimal two-role pod (lead + implementer) in an isolated ``DOCKET_HOME`` --
    ``plan_apply``'s existing-pod lookup (``_dispatch.pod_pipeline``) needs one to resolve
    against, even for a manifest that never reaches roles/policies/settings."""
    from docket.cli import _pod as _cli_pod

    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    _cli_pod.build_pod(project, pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")


def _unit(step_id: str, *, role: str | None, agent: str | None, skipped: bool) -> _orch.PlannedUnit:
    return _orch.PlannedUnit(
        step_id=step_id,
        role=role,
        agent=agent,
        archetype=None,
        member_id=None if skipped else "proj-implementer",
        gate=None,
        retries=None,
        timeout=None,
        skipped=skipped,
    )


class TestUnresolvablePipelineSteps:
    """The shared helper ``docket pod set pipeline`` and ``apply`` both use."""

    def test_no_problems_for_a_fully_resolved_plan(self) -> None:
        plan = _orch.ExecutionPlan(
            pipeline_name="p",
            nodes=(_unit("build", role="implementer", agent=None, skipped=False),),
        )
        assert _pod_apply.unresolvable_pipeline_steps(plan, "proj") == []

    def test_reports_a_skipped_role_step(self) -> None:
        plan = _orch.ExecutionPlan(
            pipeline_name="p",
            nodes=(_unit("vet", role="security-vetter", agent=None, skipped=True),),
        )
        problems = _pod_apply.unresolvable_pipeline_steps(plan, "proj")
        assert problems == ["step 'vet': role 'security-vetter' not in pod 'proj'"]

    def test_reports_an_agent_step_targeting_a_foreign_pod(self) -> None:
        plan = _orch.ExecutionPlan(
            pipeline_name="p",
            nodes=(_unit("build", role=None, agent="other-implementer", skipped=False),),
        )
        problems = _pod_apply.unresolvable_pipeline_steps(plan, "proj")
        assert problems == ["step 'build': agent 'other-implementer' is not a member of pod 'proj'"]

    def test_a_parallel_group_checks_every_child(self) -> None:
        group = _orch.PlannedGroup(
            step_id="fanout",
            children=(
                _unit("a", role="implementer", agent=None, skipped=False),
                _unit("b", role="missing-role", agent=None, skipped=True),
            ),
        )
        plan = _orch.ExecutionPlan(pipeline_name="p", nodes=(group,))
        problems = _pod_apply.unresolvable_pipeline_steps(plan, "proj")
        assert problems == ["step 'b': role 'missing-role' not in pod 'proj'"]


class TestSummarizeRecipe:
    """``summarize_recipe`` derives what a directory brings from its contents, never a
    declared field (ADR 0013 §1 rule 1) -- ``plan_apply`` refuses a declared ``scope:`` the
    same way it refuses any other unrecognized top-level key."""

    def test_a_policies_only_directory(self, tmp_path: Path) -> None:
        policies_dir = tmp_path / "policies"
        policies_dir.mkdir()
        (policies_dir / "one.yaml").write_text(
            "kind: policy\nname: one\nthen: allow\n", encoding="utf-8"
        )

        summary = _pod_apply.summarize_recipe(tmp_path)

        assert summary.roles == 0
        assert summary.policies == 1
        assert summary.plugins == 0
        assert summary.skills == 0
        assert summary.members == 0
        assert summary.settings == 0
        assert summary.pipeline == ""
        assert summary.description == ""
        assert summary.render() == (
            "roles 0 · policies 1 · members 0 · pipeline none · plugins 0 · skills 0 · settings 0"
        )

    def test_plan_apply_rejects_a_declared_scope_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = "scoped"
        _seed_fixture_pod(tmp_path, monkeypatch, project)
        recipe_dir = tmp_path / "recipe"
        recipe_dir.mkdir()
        (recipe_dir / "pod.yaml").write_text(
            "kind: pod\nname: x\nscope: policies\n", encoding="utf-8"
        )

        with pytest.raises(_pod_apply.PodApplyError, match="scope"):
            _pod_apply.plan_apply(project, recipe_dir)

        assert not _cfg.pod_config_dir(project).exists()


class TestRolesInEveryConfigFormat:
    """`roles/` takes `.yaml`, `.yml` and `.json`, the file set `pod validate` counts."""

    def test_a_yml_and_a_json_role_are_planned_and_applied(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = "formats"
        _seed_fixture_pod(tmp_path, monkeypatch, project)
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

        assert sorted(i.name for i in plan.items if i.kind == "role") == ["from-json", "from-yml"]
        _pod_apply.apply(plan)
        roles = json.loads((_cfg.pod_config_dir(project) / "roles.json").read_text())["roles"]
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
        review = _pod_apply.classify_directory(root)
        assert [(i.kind, i.name) for i in review.runs] == [("role-loosens", "reviewer")]


class TestRecipeExporters:
    """A recipe may name an observability destination without carrying one (ADR 0014 rule
    7): `apply` records the names and reports state, and never activates or writes an
    exporter document. See `tests/integration/test_recipes.py` for the end-to-end CLI path."""

    def test_summarize_recipe_reads_and_renders_the_declared_names(self, tmp_path: Path) -> None:
        (tmp_path / "pod.yaml").write_text(
            "kind: pod\nname: x\nexporters: [langfuse]\n", encoding="utf-8"
        )

        summary = _pod_apply.summarize_recipe(tmp_path)

        assert summary.exporters == ("langfuse",)
        assert summary.render() == (
            "roles 0 · policies 0 · members 0 · pipeline none · plugins 0 · skills 0 · "
            "settings 0 · exporters langfuse"
        )

    def test_apply_records_the_names_and_writes_no_exporter_document(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = "observed"
        _seed_fixture_pod(tmp_path, monkeypatch, project)
        recipe_dir = tmp_path / "recipe"
        recipe_dir.mkdir()
        (recipe_dir / "pod.yaml").write_text(
            "kind: pod\nname: x\nexporters: [langfuse]\n", encoding="utf-8"
        )

        plan = _pod_apply.plan_apply(project, recipe_dir)
        assert plan.exporters == ("langfuse",)
        assert all(item.action == "skip" for item in plan.items)

        result = _pod_apply.apply(plan)

        assert result.exporters == ("langfuse",)
        assert pod.PodSettings.load_for(project).exporters == ("langfuse",)
        assert not _cfg.EXPORTERS_FILE.exists()

    def test_plan_apply_rejects_a_credential_shaped_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = "shaped"
        _seed_fixture_pod(tmp_path, monkeypatch, project)
        recipe_dir = tmp_path / "recipe"
        recipe_dir.mkdir()
        (recipe_dir / "pod.yaml").write_text(
            "kind: pod\nname: x\nexporters:\n  - endpoint: https://example.test\n",
            encoding="utf-8",
        )

        with pytest.raises(_pod_apply.PodApplyError, match="exporters"):
            _pod_apply.plan_apply(project, recipe_dir)

        assert not _cfg.EXPORTERS_FILE.exists()
        assert pod.PodSettings.load_for(project).exporters == ()

    def test_plan_apply_rejects_an_unknown_exporter_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = "unknownexp"
        _seed_fixture_pod(tmp_path, monkeypatch, project)
        recipe_dir = tmp_path / "recipe"
        recipe_dir.mkdir()
        (recipe_dir / "pod.yaml").write_text(
            "kind: pod\nname: x\nexporters: [nope]\n", encoding="utf-8"
        )

        with pytest.raises(_pod_apply.PodApplyError, match="exporters"):
            _pod_apply.plan_apply(project, recipe_dir)

        assert pod.PodSettings.load_for(project).exporters == ()


class TestPrepare:
    """A team's `prepare:` is applied as the pod's setting and reviewed as a command."""

    def _recipe(self, tmp_path: Path, text: str) -> Path:
        recipe = tmp_path / "recipe"
        recipe.mkdir()
        (recipe / "pod.yaml").write_text("kind: pod\nname: x\n" + text, encoding="utf-8")
        return recipe

    def test_apply_stores_it_as_the_pods_setting_and_export_writes_it_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_fixture_pod(tmp_path, monkeypatch, "prep")
        recipe = self._recipe(tmp_path, "kind: pod\nname: x\nprepare: make deps\n")
        plan = _pod_apply.plan_apply("prep", recipe)
        assert [(i.kind, i.name, i.action) for i in plan.items] == [("setting", "prepare", "add")]
        _pod_apply.apply(plan)
        assert pod.PodSettings.load_for("prep").prepare == "make deps"
        out = tmp_path / "out"
        _pod_apply.export_pod("prep", out)
        manifest = (out / "pod.yaml").read_text(encoding="utf-8")
        assert "prepare: make deps" in manifest and "settings" not in manifest

    def test_a_blank_prepare_is_stored_as_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_fixture_pod(tmp_path, monkeypatch, "prep")
        _pod_apply.apply(_pod_apply.plan_apply("prep", self._recipe(tmp_path, "prepare: ''\n")))
        assert pod.PodSettings.load_for("prep").prepare == "none"

    def test_prepare_inside_settings_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_fixture_pod(tmp_path, monkeypatch, "prep")
        recipe = self._recipe(tmp_path, "settings:\n  prepare: make\n")
        with pytest.raises(_pod_apply.PodApplyError, match="top level"):
            _pod_apply.plan_apply("prep", recipe)

    @pytest.mark.parametrize("text", ["prepare: 3\n", "prepare: [a]\n", 'prepare: "a\\nb"\n'])
    def test_a_malformed_prepare_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str
    ) -> None:
        _seed_fixture_pod(tmp_path, monkeypatch, "prep")
        with pytest.raises(_pod_apply.PodApplyError):
            _pod_apply.plan_apply("prep", self._recipe(tmp_path, text))

    def test_a_declared_command_is_a_run_item_and_none_is_not(self, tmp_path: Path) -> None:
        declared = _pod_apply.classify_directory(self._recipe(tmp_path, "prepare: make deps\n"))
        assert [(i.kind, i.name, i.runs) for i in declared.runs] == [
            ("prepare", "prepare", "make deps")
        ]
        off = tmp_path / "off"
        off.mkdir()
        (off / "pod.yaml").write_text("kind: pod\nname: x\nprepare: none\n", encoding="utf-8")
        assert _pod_apply.classify_directory(off).runs == ()

    def test_a_repositorys_lockfile_command_is_a_run_item(self, tmp_path: Path) -> None:
        config = tmp_path / ".docket"
        config.mkdir()
        (tmp_path / "package-lock.json").write_text("{}")
        review = _pod_apply.classify_directory(config)
        assert [(i.kind, i.runs) for i in review.runs] == [("prepare", "npm ci")]
        team = config / "teams" / "web"
        team.mkdir(parents=True)
        assert [i.runs for i in _pod_apply.classify_directory(team).runs] == ["npm ci"]

    def test_a_lockfile_beside_an_ordinary_directory_is_not_reviewed(self, tmp_path: Path) -> None:
        (tmp_path / "package-lock.json").write_text("{}")
        recipe = tmp_path / "recipe"
        recipe.mkdir()
        assert _pod_apply.classify_directory(recipe).runs == ()


class TestProtects:
    """A team's `protects:` is applied as the pod's setting and exported back, never reviewed."""

    def _recipe(self, tmp_path: Path, text: str) -> Path:
        recipe = tmp_path / "recipe"
        recipe.mkdir()
        (recipe / "pod.yaml").write_text("kind: pod\nname: x\n" + text, encoding="utf-8")
        return recipe

    def test_apply_stores_the_list_and_export_writes_it_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_fixture_pod(tmp_path, monkeypatch, "guard")
        recipe = self._recipe(tmp_path, "kind: pod\nname: x\nprotects: ['src/api/*', Makefile]\n")
        plan = _pod_apply.plan_apply("guard", recipe)
        assert [(i.kind, i.name, i.action) for i in plan.items] == [("setting", "protects", "add")]
        _pod_apply.apply(plan)
        assert pod.PodSettings.load_for("guard").protects == ("src/api/*", "Makefile")
        out = tmp_path / "out"
        _pod_apply.export_pod("guard", out)
        manifest = (out / "pod.yaml").read_text(encoding="utf-8")
        assert "protects:" in manifest and "settings" not in manifest

    def test_an_empty_list_clears_the_patterns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_fixture_pod(tmp_path, monkeypatch, "guard")
        _pod_apply.apply(_pod_apply.plan_apply("guard", self._recipe(tmp_path, "protects: [a]\n")))
        (tmp_path / "recipe" / "pod.yaml").write_text(
            "kind: pod\nname: x\nprotects: []\n", encoding="utf-8"
        )
        _pod_apply.apply(_pod_apply.plan_apply("guard", tmp_path / "recipe"))
        assert pod.PodSettings.load_for("guard").protects == ()

    def test_protects_inside_settings_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_fixture_pod(tmp_path, monkeypatch, "guard")
        recipe = self._recipe(tmp_path, "settings:\n  protects: a\n")
        with pytest.raises(_pod_apply.PodApplyError, match="top level"):
            _pod_apply.plan_apply("guard", recipe)

    @pytest.mark.parametrize(
        "text", ["protects: a\n", "protects: [1]\n", "protects: ['/abs']\n", "protects: ['']\n"]
    )
    def test_a_malformed_protects_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str
    ) -> None:
        _seed_fixture_pod(tmp_path, monkeypatch, "guard")
        with pytest.raises(_pod_apply.PodApplyError, match="protects"):
            _pod_apply.plan_apply("guard", self._recipe(tmp_path, text))

    def test_protects_is_not_a_run_item(self, tmp_path: Path) -> None:
        review = _pod_apply.classify_directory(self._recipe(tmp_path, "protects: [a]\n"))
        assert review.runs == () and ("setting", "protects") in review.adds


def _repo_dir(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "dotdocket"
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return root


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
        review = _pod_apply.classify_directory(root)
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
        review = _pod_apply.classify_directory(root)
        assert expected in {(i.kind, i.name, i.runs) for i in review.runs}

    def test_a_gate_without_a_command_runs_nothing(self, tmp_path: Path) -> None:
        root = _repo_dir(
            tmp_path,
            {"pipeline.yaml": "name: p\nsteps:\n  - build: implementer\n    verify: true\n"},
        )
        assert _pod_apply.classify_directory(root).runs == ()

    def test_policies_and_restricting_roles_are_adds_only(self, tmp_path: Path) -> None:
        root = _repo_dir(
            tmp_path,
            {
                "policies/no-secrets.json": "{}",
                "roles/api-reviewer.yaml": "kind: role\nname: api-reviewer\ncannot: [write]\n",
            },
        )
        review = _pod_apply.classify_directory(root)
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
        review = _pod_apply.classify_directory(root)
        assert [(i.kind, i.name) for i in review.runs] == [("role-loosens", "reviewer")]

    def test_a_shell_in_allow_commands_is_refused(self, tmp_path: Path) -> None:
        root = _repo_dir(
            tmp_path, {"pod.yaml": "kind: pod\nname: x\nsettings:\n  allowCommands: [bash, make]\n"}
        )
        assert _pod_apply.classify_directory(root).refused == ("bash",)

    def test_shipped_recipes_are_exempt_and_other_directories_are_not(self, tmp_path: Path) -> None:
        shipped = next(p for p in _cfg.recipes_dir().iterdir() if p.is_dir())
        assert _pod_apply.is_shipped_recipe(shipped)
        assert not _pod_apply.is_shipped_recipe(tmp_path)


def test_repo_config_dir_prefers_the_pods_team_dir(tmp_path: Path) -> None:
    """A pod's `teams/<pod>/` wins over `.docket/`; without it the plain directory stands."""
    assert _pod_apply.repo_config_dir(tmp_path, "a") == tmp_path / ".docket"
    (tmp_path / ".docket" / "teams" / "a").mkdir(parents=True)
    assert _pod_apply.repo_config_dir(tmp_path, "a") == tmp_path / ".docket" / "teams" / "a"
    assert _pod_apply.repo_config_dir(tmp_path, "b") == tmp_path / ".docket"
    assert _pod_apply.repo_config_dir(tmp_path, "b", create=True) == (
        tmp_path / ".docket" / "teams" / "b"
    )


def test_repo_root_of_a_team_dir_is_the_codebase(tmp_path: Path) -> None:
    """The reviewed-repository key is the codebase for both directory shapes."""
    assert _pod_apply.repo_root(tmp_path / ".docket" / "teams" / "a") == tmp_path
    assert _pod_apply.repo_root(tmp_path / ".docket") == tmp_path


class TestReviewDecision:
    """The review rule's verdict for a directory, an optional accept code and a repo root."""

    def _runs(self, tmp_path: Path) -> Path:
        return _repo_dir(
            tmp_path, {"pod.yaml": "kind: pod\nname: x\nsettings:\n  allowCommands: [make]\n"}
        )

    def test_nothing_to_run_and_shipped_recipes_go(self, tmp_path: Path) -> None:
        plain = _repo_dir(tmp_path, {"policies/p.json": "{}"})
        assert _pod_apply.review_decision(tmp_path, "a", plain, None).status == "go"
        shipped = next(p for p in _cfg.recipes_dir().iterdir() if p.is_dir())
        assert _pod_apply.review_decision(tmp_path, "a", shipped, "bogus").status == "go"

    def test_run_items_need_the_code_then_accept_it(self, tmp_path: Path) -> None:
        directory = self._runs(tmp_path)
        first = _pod_apply.review_decision(tmp_path, "a", directory, None)
        assert first.status == "needs_code" and len(first.code) == 16
        assert _pod_apply.review_decision(tmp_path, "a", directory, first.code).status == "accepted"
        assert (
            _pod_apply.review_decision(tmp_path, "a", directory, "0" * 16).status == "code_mismatch"
        )

    def test_a_shell_is_refused_before_any_code_matters(self, tmp_path: Path) -> None:
        directory = _repo_dir(
            tmp_path, {"pod.yaml": "kind: pod\nname: x\nsettings:\n  allowCommands: [bash]\n"}
        )
        assert _pod_apply.review_decision(tmp_path, "a", directory, "x").status == "refused"

    def test_a_remembered_review_goes(self, tmp_path: Path) -> None:
        from docket.core import reviewed_repos as _reviewed

        directory = self._runs(tmp_path)
        _reviewed.remember(tmp_path, "a", _pod_apply.classify_directory(directory).runs)
        assert _pod_apply.review_decision(tmp_path, "a", directory, None).status == "go"

    def test_a_second_pod_on_the_same_codebase_keeps_the_first_approval(
        self, tmp_path: Path
    ) -> None:
        """Pod b's approval does not make pod a ask again; a returning set still goes."""
        from docket.core import reviewed_repos as _reviewed

        directory = self._runs(tmp_path)
        items = _pod_apply.classify_directory(directory).runs
        _reviewed.remember(tmp_path, "a", items)
        _reviewed.remember(tmp_path, "b", items)
        assert _pod_apply.review_decision(tmp_path, "a", directory, None).status == "go"
        assert _pod_apply.review_decision(tmp_path, "b", directory, None).status == "go"
        assert _pod_apply.review_decision(tmp_path, "c", directory, None).status == "needs_code"


_FAST = "name: fast\nsteps:\n  - build: implementer\n    verify: make check\n"


class TestPodLocalPipelines:
    """``pipelines/<name>.yaml`` travels with ``update`` and ``export``; dispatch reads the copy."""

    def test_update_copies_the_file_where_a_task_resolves_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.core import dispatch as _dispatch

        _seed_fixture_pod(tmp_path, monkeypatch, "demo")
        root = _repo_dir(tmp_path, {"pipelines/fast.yaml": _FAST})
        plan = _pod_apply.plan_apply("demo", root)
        assert ("pipeline", "pipelines/fast.yaml", "add") in {
            (i.kind, i.name, i.action) for i in plan.items
        }
        _pod_apply.apply(plan, channel="cli")
        path, source = _dispatch._task_pipeline_file("demo", "fast") or (None, None)
        assert source == "pod:fast" and path is not None
        assert path.read_text() == _FAST and oct(path.stat().st_mode & 0o777) == "0o600"
        again = _pod_apply.plan_apply("demo", root)
        assert ("pipeline", "pipelines/fast.yaml", "skip") in {
            (i.kind, i.name, i.action) for i in again.items
        }

    def test_export_writes_it_back_byte_for_byte(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_fixture_pod(tmp_path, monkeypatch, "demo")
        root = _repo_dir(tmp_path, {"pipelines/fast.yaml": _FAST})
        _pod_apply.apply(_pod_apply.plan_apply("demo", root), channel="cli")
        out = tmp_path / "exported"
        _pod_apply.export_pod("demo", out)
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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, text: str, message: str
    ) -> None:
        _seed_fixture_pod(tmp_path, monkeypatch, "demo")
        root = _repo_dir(tmp_path, {f"pipelines/{name}": text})
        with pytest.raises(_pod_apply.PodApplyError, match=message):
            _pod_apply.plan_apply("demo", root)

    def test_its_commands_need_the_review(self, tmp_path: Path) -> None:
        root = _repo_dir(
            tmp_path,
            {"pipelines/fast.yaml": _FAST + "  - id: migrate\n    run: make migrate\n"},
        )
        review = _pod_apply.classify_directory(root)
        got = {(i.kind, i.name, i.runs) for i in review.runs}
        assert ("verify", "fast/build", "make check") in got
        assert ("pipeline-step", "fast/migrate", "make migrate") in got
        assert ("pipeline", "pipelines/fast.yaml") in review.adds

    def test_summary_and_validate_name_it(self, tmp_path: Path) -> None:
        from docket.core import config_docs as _config_docs

        root = _repo_dir(tmp_path, {"pipelines/fast.yaml": _FAST})
        summary = _pod_apply.summarize_recipe(root)
        assert summary.pipelines == ("fast",)
        assert summary.render().endswith(" · pipelines fast")
        results = _config_docs.validate_path(root)
        assert [(r.path.name, r.error) for r in results] == [("fast.yaml", None)]


class TestSkippedSettingsSayWhy:
    """A setting the pod already holds by default plans ``skip`` with the reason."""

    def test_a_default_value_is_noted_and_a_set_one_is_not(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_fixture_pod(tmp_path, monkeypatch, "demo")
        root = _repo_dir(
            tmp_path, {"pod.yaml": "kind: pod\nname: x\nsettings:\n  approvalMode: wait\n"}
        )
        [item] = [i for i in _pod_apply.plan_apply("demo", root).items if i.kind == "setting"]
        assert (item.action, item.note) == ("skip", "already the default")
        root = _repo_dir(
            tmp_path / "b", {"pod.yaml": "kind: pod\nname: x\nsettings:\n  maxReworkCycles: 4\n"}
        )
        _pod_apply.apply(_pod_apply.plan_apply("demo", root), channel="cli")
        [item] = [i for i in _pod_apply.plan_apply("demo", root).items if i.kind == "setting"]
        assert (item.action, item.note) == ("skip", "")
