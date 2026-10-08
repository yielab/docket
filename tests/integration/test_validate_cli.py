"""``docket pod validate`` over directories: invalid files first, a note for a kind-less file."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from docket.cli import _pod

SUBJECT = "docket.cli._pod_config"

_GOOD_ROLE = (
    "kind: role\n"
    "name: security-vetter\n"
    "scope: org\n"
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
    "scope: org\n"
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
