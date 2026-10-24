"""``docket pod validate`` over directories: invalid files first, a kind-less file still loads."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support.cli import invoke_pod

SUBJECT = "docket.interfaces.cli.commands.pod_config"

_GOOD_ROLE = "kind: role\nname: security-vetter\nscope: pod\nmodel: cheap\n"


def _put_role(roles_dir: Path, file: str, text: str, soul: str = "You vet things.") -> None:
    """Write the role document *text* as *file* with the instructions file it names beside it."""
    (roles_dir / file).write_text(text, encoding="utf-8")
    name = next(ln.split(": ")[1] for ln in text.splitlines() if ln.startswith("name: "))
    (roles_dir / f"{name}.md").write_text(f"{soul}\n", encoding="utf-8")


def _validate(path: Path) -> tuple[int, str]:
    result = invoke_pod(["validate", str(path)])
    return result.exit_code, result.output


def test_a_directory_with_one_good_role_and_one_bad_kind_file_exits_one(tmp_path: Path) -> None:
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    _put_role(roles_dir, "good.yaml", _GOOD_ROLE)
    (roles_dir / "bad.yaml").write_text("kind: banana\nname: whatever\n", encoding="utf-8")

    rc, out = _validate(tmp_path)

    assert rc == 1
    assert "bad.yaml" in out
    assert "good.yaml" in out
    assert out.index("bad.yaml") < out.index("good.yaml")


_ROLE_WITHOUT_KIND = "name: plain-vetter\nscope: pod\nmodel: cheap\n"


def test_a_role_file_without_kind_loads_ok_from_the_roles_directory(tmp_path: Path) -> None:
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    _put_role(roles_dir, "plain.yaml", _ROLE_WITHOUT_KIND)

    rc, out = _validate(tmp_path)

    assert rc == 0
    assert "ok " in out
    assert "no 'kind:'" not in out


def test_a_canonical_role_file_is_refused_naming_the_short_form_key(tmp_path: Path) -> None:
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    (roles_dir / "old.yaml").write_text(
        "kind: role\nname: old\nmodelClass: cheap\nsoulTemplate: x\n", encoding="utf-8"
    )

    rc, out = _validate(tmp_path)

    assert rc == 1
    assert "replace `modelClass` with `model`" in out


def test_a_role_template_with_an_unknown_variable_fails_validation(tmp_path: Path) -> None:
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    _put_role(roles_dir, "typo.yaml", _GOOD_ROLE, soul="You vet ${typo}.")

    rc, out = _validate(tmp_path)

    assert rc == 1
    assert "soulTemplate" in out


_REFUSED_PIPELINES = {
    "group-run": (
        "  - a: lead\n  - g:\n      run: echo hi\n      parallel:\n        - c: reviewer\n",
        "parallel group carries only",
    ),
    "run-and-input": (
        "  - a: lead\n  - ask:\n      run: echo hi\n      input:\n        from: a\n",
        "'input'",
    ),
    "forward-bad-max": (
        "  - a: implementer\n    verify: true\n"
        "    on:\n      fail: {goto: b, max: 0}\n  - b: tester\n",
        "'max'",
    ),
    "child-on": (
        "  - a: lead\n  - g:\n      parallel:\n"
        "        - c: reviewer\n          on:\n            pass: nowhere\n",
        "'on'",
    ),
    "child-input": (
        "  - a: lead\n  - g:\n      parallel:\n"
        "        - c:\n            input:\n              from: ghost\n",
        "'input'",
    ),
    "canonical-step": (
        "  - id: a\n    role: lead\n",
        "'- a: <role>'",
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
