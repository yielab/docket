"""``docket pod validate`` over directories: invalid files first, a note for a kind-less file."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from docket.cli import _pod

SUBJECT = "docket.cli._pod_config"

_GOOD_ROLE = (
    "kind: role\n"
    "name: security-vetter\n"
    "scope: pod\n"
    "modelClass: cheap\n"
    "soulTemplate: You vet things.\n"
    "agentsTemplate: Vetting protocol.\n"
)


def _validate(path: Path) -> tuple[int, str]:
    result = CliRunner().invoke(_pod.pod_app, ["validate", str(path)])
    return result.exit_code, result.output


def test_a_directory_with_one_good_role_and_one_bad_kind_file_exits_one(tmp_path: Path) -> None:
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    (roles_dir / "good.yaml").write_text(_GOOD_ROLE, encoding="utf-8")
    (roles_dir / "bad.yaml").write_text("kind: banana\nname: whatever\n", encoding="utf-8")

    rc, out = _validate(tmp_path)

    assert rc == 1
    assert "bad.yaml" in out
    assert "good.yaml" in out
    assert out.index("bad.yaml") < out.index("good.yaml")


_ROLE_WITHOUT_KIND = (
    "name: plain-vetter\n"
    "scope: pod\n"
    "modelClass: cheap\n"
    "soulTemplate: You vet things.\n"
    "agentsTemplate: Vetting protocol.\n"
)


def test_a_role_file_without_kind_loads_ok_with_a_note(tmp_path: Path) -> None:
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    (roles_dir / "plain.yaml").write_text(_ROLE_WITHOUT_KIND, encoding="utf-8")

    rc, out = _validate(tmp_path)

    assert rc == 0
    assert "ok " in out
    assert "no 'kind:'" in out


def test_a_short_form_role_without_kind_is_refused_naming_the_kind_key(tmp_path: Path) -> None:
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    (roles_dir / "plain.yaml").write_text("name: plain\nmodel: cheap\n", encoding="utf-8")

    rc, out = _validate(tmp_path)

    assert rc == 1
    assert "kind" in out and "short-form" in out


def test_a_role_template_with_an_unknown_variable_fails_validation(tmp_path: Path) -> None:
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    (roles_dir / "typo.yaml").write_text(
        _GOOD_ROLE.replace("You vet things.", "You vet ${typo}."), encoding="utf-8"
    )

    rc, out = _validate(tmp_path)

    assert rc == 1
    assert "soulTemplate" in out


_REFUSED_PIPELINES = {
    "group-run": (
        "  - id: a\n    role: lead\n  - id: g\n    run: echo hi\n    parallel:\n"
        "      - id: c\n        role: reviewer\n",
        "'run'",
    ),
    "run-and-input": (
        "  - id: a\n    role: lead\n  - id: ask\n    run: echo hi\n    input:\n      from: a\n",
        "'input'",
    ),
    "forward-bad-max": (
        "  - id: a\n    role: implementer\n    gate: {type: mechanical}\n"
        "    on:\n      fail: {goto: b, max: 0}\n  - id: b\n    role: tester\n",
        "'max'",
    ),
    "child-on": (
        "  - id: a\n    role: lead\n  - id: g\n    parallel:\n"
        "      - id: c\n        role: reviewer\n        on:\n          pass: nowhere\n",
        "'on'",
    ),
    "child-input": (
        "  - id: a\n    role: lead\n  - id: g\n    parallel:\n"
        "      - id: c\n        input:\n          from: ghost\n",
        "'input'",
    ),
}


@pytest.mark.parametrize("name", sorted(_REFUSED_PIPELINES))
def test_pod_validate_refuses_a_pipeline_the_executor_cannot_run(tmp_path: Path, name: str) -> None:
    body, field = _REFUSED_PIPELINES[name]
    pipelines = tmp_path / "pipelines"
    pipelines.mkdir()
    (pipelines / "p.yaml").write_text("kind: pipeline\nname: p\nsteps:\n" + body, encoding="utf-8")

    rc, out = _validate(tmp_path)

    assert rc == 1
    assert field in out
