"""Unit coverage for ``core.config_docs``'s envelope dispatch -- see
``tests/integration/test_validate_cli.py`` for the ``docket pod validate`` command itself."""

from __future__ import annotations

import importlib.util
import json
import types
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

import docket.config as _cfg
from docket.core import archetypes as _archetypes
from docket.core import config_docs

SUBJECT = "docket.core.config_docs"

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


def test_a_role_file_without_kind_loads_deprecated_and_matches_parse_yaml_file(
    tmp_path: Path,
) -> None:
    text = (
        "name: custom-role\n"
        "scope: org\n"
        "modelClass: cheap\n"
        "soulTemplate: You are the custom role.\n"
        "agentsTemplate: Custom role protocol.\n"
    )
    path = tmp_path / "custom-role.yaml"
    path.write_text(text, encoding="utf-8")

    document = config_docs.load_document(path, kind="role")

    assert document.kind == "role"
    assert document.name == "custom-role"
    assert document.deprecated is True
    assert document.doc == _archetypes.parse_yaml_file(str(path))


def _load_gen_config_schemas_script() -> types.ModuleType:
    script = REPO_ROOT / "scripts" / "gen_config_schemas.py"
    spec = importlib.util.spec_from_file_location("_p28_8_gen_config_schemas", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _recipe_files(pattern_dir: str, glob: str) -> list[Path]:
    files: list[Path] = []
    for recipe_dir in sorted(p for p in _cfg.recipes_dir().iterdir() if p.is_dir()):
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
