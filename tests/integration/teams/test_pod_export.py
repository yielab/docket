"""A pod's export applies back as itself, and `apply` records where its configuration came from.

`docket pod export` writes this pod's own scope (never the global one) as a directory that
`docket pod update` re-plans as all `skip`; `apply` records `configSource`/`configDigest`, and
`pod show --json` reports `drift` against them. See pod-blueprints.spec.md ("Pod manifests:
apply").
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import typer
from tests.support.cli import invoke_pod
from tests.support.cli import pod_cli as _pod_cli
from tests.support.pods import build_pod
from tests.support.pods import seed_fixture_pod as _seed_fixture_pod

import docket.kernel.templates as _templates
from docket.governance import audit as _audit
from docket.governance import policy as _policy
from docket.interfaces.cli.commands import pod as _pod
from docket.interfaces.cli.commands import pod_settings as _commands_pod_settings
from docket.kernel.home import Home, current_home, use_home
from docket.teams import pod
from docket.teams import pod_settings as _pod_settings
from docket.teams.apply import lock as _lock
from docket.teams.apply import model as _model
from docket.teams.apply import plan as _pod_apply
from docket.teams.apply import write as _write

SUBJECT = "docket.teams.apply.write"

RECIPES_DIR = _templates.RECIPES_DIR


# ── export_pod: the round trip is the proof ──────────────────────────────────


def _explain_json(agent_id: str, capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    shown = invoke_pod(["show", agent_id, "--pod", _pod.pod.pod_of(agent_id) or "", "--json"])
    assert shown.exit_code == 0, shown.output
    return json.loads(shown.stdout)  # type: ignore[no-any-return]


def _normalized(report: dict[str, object], project: str) -> dict[str, object]:
    """Drop *project*'s own name plus each pod's own `configSource`/`configDigest` (a
    different applied directory per pod, asserted separately by the caller) and its
    `workspace` path -- an equal-length pod's report should then match exactly."""
    text = json.dumps(report).replace(project, "PROJECT")
    normalized: dict[str, object] = json.loads(text)
    normalized.pop("workspace", None)
    normalized.pop("configSource", None)
    normalized.pop("configDigest", None)
    return normalized


def test_export_then_apply_round_trip_matches_pod_show(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Export -> apply into a fresh pod -> `pod show <member> --json` agrees once normalized;
    also covers the CLI's non-empty-directory refusal and its `--force` override."""
    source_project = "podsrc"
    target_project = "poddst"  # same length as source_project -- see `_normalized`
    with _seed_fixture_pod(tmp_path / "source", source_project):
        recipe_dir = RECIPES_DIR / "secure-build"
        _write.apply(_pod_apply.plan_apply(source_project, recipe_dir))
        _commands_pod_settings.set_setting(source_project, "approvalMode", "refuse")

        export_dir = tmp_path / "exported"
        assert _pod_cli("export", str(export_dir), "--pod", source_project).exit_code == 0
        assert (export_dir / "roles" / "security-vetter.yaml").is_file()
        assert (export_dir / "roles" / "security-vetter.md").is_file()
        assert (export_dir / "pipeline.yaml").is_file()
        assert (export_dir / "pod.yaml").is_file()
        # The export regenerates the policy as short-form YAML (not a byte copy of the recipe's
        # own file), so the two are compared by parsed content, not bytes.
        assert _policy.read_policy(
            export_dir / "policies" / "require-approval-secret-writes.yaml"
        ) == _policy.read_policy(recipe_dir / "policies" / "require-approval-secret-writes.yaml")

        assert _pod_cli("export", str(export_dir), "--pod", source_project).exit_code == 1
        # overwrites cleanly
        assert (
            _pod_cli("export", str(export_dir), "--pod", source_project, "--force").exit_code == 0
        )

        # Round trip: re-planning this pod's own export against itself plans every item `skip` --
        # the schema-header/regenerated-short-form export is still recognized as unchanged.
        reapply_plan = _pod_apply.plan_apply(source_project, export_dir)
        assert [item.action for item in reapply_plan.items] == ["skip"] * len(reapply_plan.items)

        source_report = _explain_json(f"{source_project}-security-vetter", capsys)

        with _seed_fixture_pod(tmp_path / "target", target_project):
            _write.apply(_pod_apply.plan_apply(target_project, export_dir))

            target_report = _explain_json(f"{target_project}-security-vetter", capsys)

            # Each pod's own configuration-of-record: the source pod was applied from `recipe_dir`,
            # the target pod from `export_dir` -- different directories, each still `drift: no`
            # since neither was edited after its own `apply`.
            assert source_report["configSource"] == str(recipe_dir.resolve())
            assert source_report["configDigest"] == _lock.source_digest(recipe_dir)
            assert source_report["drift"] == "no"
            assert target_report["configSource"] == str(export_dir.resolve())
            assert target_report["configDigest"] == _lock.source_digest(export_dir)
            assert target_report["drift"] == "no"

            assert _normalized(source_report, source_project) == _normalized(
                target_report, target_project
            )


def test_an_export_applied_back_unchanged_reads_as_not_drifted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Export a recipe-applied pod and apply the export to the same pod: every item plans
    `skip` yet the overlay hashes to what `applied.lock` records, so `drift` stays `no`. An
    edit to one exported role file then reads `yes` until the next apply."""
    project = "roundtrip"
    member = f"{project}-security-vetter"
    with _seed_fixture_pod(tmp_path, project):
        _write.apply(_pod_apply.plan_apply(project, RECIPES_DIR / "secure-build"))
        export_dir = tmp_path / "exported"
        assert _pod_cli("export", str(export_dir), "--pod", project).exit_code == 0

        _write.apply(_pod_apply.plan_apply(project, export_dir))
        assert _explain_json(member, capsys)["drift"] == "no"

        role_md = export_dir / "roles" / "security-vetter.md"
        role_md.write_text(role_md.read_text(encoding="utf-8") + "\nAn added rule.\n")
        assert _explain_json(member, capsys)["drift"] == "yes"

        _write.apply(_pod_apply.plan_apply(project, export_dir))
        assert _explain_json(member, capsys)["drift"] == "no"


def test_export_writes_only_this_pods_own_scope_never_global(tmp_path: Path) -> None:
    """A fleet-wide policy, installed alongside this pod's own pod-scoped role/policy, must
    never appear in an export."""
    project = "guardedexp"
    with _seed_fixture_pod(tmp_path, project):
        current_home().policies_dir.mkdir(parents=True, exist_ok=True)
        (current_home().policies_dir / "global-policy.json").write_text(
            json.dumps(
                {
                    "kind": "policy",
                    "name": "global-policy",
                    "appliesTo": ["*"],
                    "on": "toolCall",
                    "when": {"matches": "x"},
                    "then": "ask",
                }
            ),
            encoding="utf-8",
        )

        _write.apply(_pod_apply.plan_apply(project, RECIPES_DIR / "secure-build"))
        pod_policies_dir = current_home().pod_config_dir(project) / "policies"
        pod_policies_dir.mkdir(parents=True, exist_ok=True)
        policy_text = (
            RECIPES_DIR / "secure-build" / "policies" / "require-approval-secret-writes.yaml"
        ).read_text(encoding="utf-8")
        (pod_policies_dir / "require-approval-secret-writes.yaml").write_text(
            policy_text, encoding="utf-8"
        )
        _commands_pod_settings.set_setting(project, "approvalMode", "refuse")

        export_dir = tmp_path / "export-out"
        _write.export_pod(project, export_dir)

        assert sorted(p.name for p in (export_dir / "roles").iterdir()) == [
            "security-vetter.md",
            "security-vetter.yaml",
        ]
        assert sorted(p.name for p in (export_dir / "policies").iterdir()) == [
            "require-approval-secret-writes.yaml"
        ]
        # The export regenerates the policy as short-form YAML, so it is compared by parsed
        # content, not bytes.
        assert _policy.read_policy(
            export_dir / "policies" / "require-approval-secret-writes.yaml"
        ) == _policy.read_policy(Path(pod_policies_dir / "require-approval-secret-writes.yaml"))
        assert (export_dir / "pipeline.yaml").is_file()

        import yaml as _yaml

        manifest = _yaml.safe_load((export_dir / "pod.yaml").read_text(encoding="utf-8"))
        assert manifest == {
            "kind": "pod",
            "name": project,
            "members": ["implementer", "security-vetter"],
            "settings": {"approvalMode": "refuse"},
        }


# ── configSource/configDigest: the pod's configuration of record (ADR 0012 §2 rule 5) ──


def test_apply_records_config_source_and_digest_and_explain_reports_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`apply` records `configSource`/`configDigest`; editing the applied directory afterward
    makes `config explain --json` report `drift: yes` against the unchanged recorded digest."""
    project = "recorded"
    with _seed_fixture_pod(tmp_path, project):
        recipe_copy = tmp_path / "recipe-copy"
        shutil.copytree(RECIPES_DIR / "secure-build", recipe_copy)

        _write.apply(_pod_apply.plan_apply(project, recipe_copy))

        settings = _pod_settings.PodSettings.load_for(project)
        assert settings.config_source == str(recipe_copy.resolve())
        assert settings.config_digest == _lock.source_digest(recipe_copy)

        lead_id = pod.member_id(project, "lead")
        report = _explain_json(lead_id, capsys)
        assert report["configSource"] == str(recipe_copy.resolve())
        assert report["configDigest"] == settings.config_digest
        assert report["drift"] == "no"

        policy_file = recipe_copy / "policies" / "require-approval-secret-writes.yaml"
        policy_file.write_text(policy_file.read_text(encoding="utf-8") + "\n# edited\n", "utf-8")

        drifted_report = _explain_json(lead_id, capsys)
        assert drifted_report["configDigest"] == settings.config_digest  # recorded value unchanged
        assert drifted_report["drift"] == "yes"

        # Written only by `apply` -- `config set` refuses both by name, naming `apply` as the
        # writer (not the generic "unknown pod setting" message every other unknown key gets).
        capsys.readouterr()
        with pytest.raises(typer.Exit) as exc:
            _commands_pod_settings.set_setting(project, "configSource", "/tmp/whatever")
        assert exc.value.exit_code == 1
        assert "written by update" in capsys.readouterr().err

        # A `pod.yaml` `settings` mapping cannot carry them either -- refused the same way any
        # unknown setting already is, since both are deliberately outside `PodSettings.KEYS`.
        bad_dir = tmp_path / "bad-recipe"
        bad_dir.mkdir()
        (bad_dir / "pod.yaml").write_text(
            "kind: pod\nname: x\nsettings:\n  configDigest: " + "0" * 64 + "\n", encoding="utf-8"
        )
        with pytest.raises(_model.PodApplyError, match="configDigest"):
            _pod_apply.plan_apply(project, bad_dir)


def test_apply_records_config_source_from_every_validated_apply_all_skip_included(
    tmp_path: Path,
) -> None:
    """A second, byte-identical directory at another path still moves the recorded
    `configSource`/`configDigest` even though every item plans `skip` -- the record must not
    stay pointing at the first directory once a second one is applied (ADR 0013 §1 rule 3)."""
    project = "reconfigured"
    with _seed_fixture_pod(tmp_path, project):
        dir_a = tmp_path / "recipe-a"
        shutil.copytree(RECIPES_DIR / "secure-build", dir_a)
        _write.apply(_pod_apply.plan_apply(project, dir_a))

        dir_b = tmp_path / "recipe-b"
        shutil.copytree(RECIPES_DIR / "secure-build", dir_b)

        entries_before = [e for e in _audit.read_audit() if e["action"] == "pod.apply"]
        second_plan = _pod_apply.plan_apply(project, dir_b)
        assert [item.action for item in second_plan.items] == ["skip"] * len(second_plan.items)
        _write.apply(second_plan)
        entries_after = [e for e in _audit.read_audit() if e["action"] == "pod.apply"]
        assert entries_after == entries_before  # all-skip: no new audit entry

        settings = _pod_settings.PodSettings.load_for(project)
        assert settings.config_source == str(dir_b.resolve())
        assert settings.config_digest == _lock.source_digest(dir_b)


def test_export_default_dir_refuses_a_non_empty_codebase_docket_without_force(
    tmp_path: Path,
) -> None:
    """`docket pod export` with no argument defaults to `<codebase>/.docket` (ADR 0012 §2
    rule 5); a non-empty one there still refuses without `--force`."""
    project = "exportdefault"
    codebase = tmp_path / "codebase"
    codebase.mkdir()
    home = tmp_path / "home" / ".docket"
    (home / "state" / "workspaces" / "projects").mkdir(parents=True)
    (home / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        build_pod(project, pod.DEFAULT_POD_ROLES, codebase=str(codebase))

        default_dir = codebase / ".docket"
        default_dir.mkdir()
        (default_dir / "marker.txt").write_text("existing", encoding="utf-8")

        assert _pod_cli("export", "--pod", project).exit_code == 1
        assert not (default_dir / "pod.yaml").exists()

        assert _pod_cli("export", "--pod", project, "--force").exit_code == 0
        assert (default_dir / "pod.yaml").is_file()

        # The exported default directory re-applies as a no-op.
        reapply_plan = _pod_apply.plan_apply(project, default_dir)
        assert [item.action for item in reapply_plan.items] == ["skip"] * len(reapply_plan.items)
