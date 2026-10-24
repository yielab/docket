"""Unit coverage for ``teams.config_docs``'s envelope dispatch -- see
``tests/integration/test_validate_cli.py`` for the ``docket pod validate`` command itself."""

from __future__ import annotations

import importlib.util
import json
import types
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

import docket.kernel.templates as _templates
from docket.kernel.errors import InvalidInput
from docket.teams import config_docs
from docket.teams import role_schema as _role_schema
from docket.teams import roles as _archetypes

SUBJECT = "docket.teams.config_docs"

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_SCHEMA_DIR = REPO_ROOT / "docs" / "contracts" / "config-v1"
PACKAGE_SCHEMA_DIR = REPO_ROOT / "src" / "docket" / "templates" / "schemas"


def test_an_unknown_kind_raises_naming_every_known_kind(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("kind: banana\nname: whatever\n", encoding="utf-8")

    with pytest.raises(config_docs.ConfigDocError) as exc_info:
        config_docs.load_document(path)

    error = exc_info.value
    assert error.valid == config_docs.KINDS
    assert set(config_docs.KINDS) == {
        "role",
        "pipeline",
        "policy",
        "pod",
        "provider",
        "exporter",
        "channel",
        "mcp-server",
    }
    assert str(error) == (
        f"{path}:1 kind: unknown kind 'banana' "
        "(valid: role, pipeline, policy, pod, provider, exporter, channel, mcp-server)"
    )


def test_a_role_file_without_kind_loads_when_the_caller_names_the_kind(tmp_path: Path) -> None:
    (tmp_path / "custom-role.md").write_text("You are the custom role.\n", encoding="utf-8")
    path = tmp_path / "custom-role.yaml"
    path.write_text("name: custom-role\nmodel: cheap\n", encoding="utf-8")

    document = config_docs.load_document(path, kind="role")

    assert document.kind == "role"
    assert document.name == "custom-role"
    assert document.doc == _archetypes.load_role_file(str(path))


def test_a_file_without_kind_in_no_known_location_gets_the_kind_error(tmp_path: Path) -> None:
    path = tmp_path / "vetter.yaml"
    path.write_text("name: vetter\nmodel: cheap\n", encoding="utf-8")

    with pytest.raises(config_docs.ConfigDocError) as exc_info:
        config_docs.load_document(path)

    assert exc_info.value.field == "kind"
    assert exc_info.value.valid == config_docs.KINDS


@pytest.mark.parametrize(
    ("kind", "text", "short_key"),
    [
        ("role", "name: r\nmodelClass: cheap\nsoulTemplate: x\n", "model"),
        ("role", "kind: role\nname: r\ndeniedTools: [write]\n", "cannot"),
        ("policy", "id: p\napplies_to: ['*']\nhook: pre_tool_call\naction: block\n", "appliesTo"),
        (
            "policy",
            "kind: policy\nname: p\nmatch: {type: regex, pattern: x}\nthen: block\n",
            "when",
        ),
        ("pipeline", "kind: pipeline\nname: p\nsteps:\n  - id: a\n    role: lead\n", "- a: <role>"),
    ],
)
def test_a_canonical_document_is_refused_naming_the_short_form_key(
    tmp_path: Path, kind: str, text: str, short_key: str
) -> None:
    path = tmp_path / f"{kind}.yaml"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(config_docs.ConfigDocError) as exc_info:
        config_docs.load_document(path, kind=kind)

    assert short_key in str(exc_info.value)
    assert isinstance(exc_info.value, InvalidInput)


def test_a_short_form_role_with_a_bad_model_reports_the_model_not_a_missing_kind(
    tmp_path: Path,
) -> None:
    (tmp_path / "vetter.md").write_text("You vet.\n", encoding="utf-8")
    path = tmp_path / "vetter.yaml"
    path.write_text("kind: role\nname: vetter\nmodel: gpt-5\n", encoding="utf-8")

    with pytest.raises(config_docs.ConfigDocError) as exc_info:
        config_docs.load_document(path)

    assert exc_info.value.field == "model"
    assert exc_info.value.valid == ("cheap", "strong")


def test_the_model_class_error_points_at_the_pipeline_step_not_at_setup_model(
    tmp_path: Path,
) -> None:
    from docket.teams import roles as archetypes

    with pytest.raises(_role_schema.ArchetypeError) as exc_info:
        archetypes.normalize_role({"name": "vetter", "model": "gpt-5"}, tmp_path)

    assert "docket setup model set" not in str(exc_info.value)
    assert "pipeline step" in str(exc_info.value)


def test_a_role_template_naming_an_unknown_variable_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "typo.yaml"
    path.write_text(
        "kind: role\nname: typo\nscope: pod\nmodelClass: cheap\n"
        "soulTemplate: You are ${typo}.\nagentsTemplate: Protocol.\n",
        encoding="utf-8",
    )

    with pytest.raises(config_docs.ConfigDocError) as exc_info:
        config_docs.load_document(path)

    assert "soulTemplate" in str(exc_info.value)
    assert "typo" in str(exc_info.value)


def _load_gen_config_schemas_script() -> types.ModuleType:
    script = REPO_ROOT / "scripts" / "gen_config_schemas.py"
    spec = importlib.util.spec_from_file_location("_p28_8_gen_config_schemas", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _recipe_files(pattern_dir: str, glob: str) -> list[Path]:
    files: list[Path] = []
    for recipe_dir in sorted(p for p in _templates.RECIPES_DIR.iterdir() if p.is_dir()):
        sub = recipe_dir / pattern_dir
        if sub.is_dir():
            files.extend(sorted(sub.glob(glob)))
        elif pattern_dir == "." and (recipe_dir / glob).is_file():
            files.append(recipe_dir / glob)
    return files


def test_generated_schemas_are_pinned_validate_every_recipe_and_reject_a_bad_policy() -> None:
    module = _load_gen_config_schemas_script()

    # 1. Every generated schema is byte-identical to both committed copies (the pin).
    schemas: dict[str, dict[str, object]] = {}
    for kind in module.KINDS:
        rendered = module.render(kind)
        assert rendered == (DOCS_SCHEMA_DIR / f"{kind}.schema.json").read_text(encoding="utf-8")
        assert rendered == (PACKAGE_SCHEMA_DIR / f"{kind}.schema.json").read_text(encoding="utf-8")
        schemas[kind] = json.loads(rendered)

    validators = {kind: Draft202012Validator(schema) for kind, schema in schemas.items()}

    # 2. Every shipped recipe file validates against its kind's schema.
    for role_file in _recipe_files("roles", "*.yaml"):
        validators["role"].validate(yaml.safe_load(role_file.read_text(encoding="utf-8")))
    for pipeline_file in _recipe_files(".", "pipeline.yaml"):
        validators["pipeline"].validate(yaml.safe_load(pipeline_file.read_text(encoding="utf-8")))
    for policy_file in _recipe_files("policies", "*.yaml"):
        validators["policy"].validate(yaml.safe_load(policy_file.read_text(encoding="utf-8")))
    for pod_file in _recipe_files(".", "pod.yaml"):
        validators["pod"].validate(yaml.safe_load(pod_file.read_text(encoding="utf-8")))

    # 3. An unknown `then` value is rejected at the `then` path, not silently ignored.
    errors = list(
        validators["policy"].iter_errors({"kind": "policy", "name": "x", "then": "bogus"})
    )
    assert errors and list(errors[0].path) == ["then"]


def test_a_pipeline_error_is_not_masked_by_an_unquoted_on_key(tmp_path: Path) -> None:
    # YAML reads a bare `on:` as the key True; the envelope model must not turn that into the
    # reported error and hide the pipeline's own.
    path = tmp_path / "p.yaml"
    path.write_text(
        "kind: pipeline\nname: p\nsteps:\n  - build: implementer\n"
        "    on:\n      fail: {goto: nowhere, max: 1}\n",
        encoding="utf-8",
    )
    (result,) = config_docs.validate_path(path)
    assert result.error is not None
    message = str(result.error)
    assert "nowhere" in message and message.count(str(path)) == 1, message
