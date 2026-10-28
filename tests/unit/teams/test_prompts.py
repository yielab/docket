"""``teams.prompts``: a prompt file is front matter plus a body, and one loader resolves it."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import docket.kernel.templates as _templates
from docket.teams import prompts

SUBJECT = "docket.teams.prompts"

_HEAD = """---
kind: prompt
name: greeter
version: 1.2.3
layer: hop
for: implementer
modelClass: strong
inputs:
  who: string
output: handoff/v1
tests: greeter.tests.yaml
---
"""


def _write(tmp_path: Path, text: str, name: str = "greeter.md") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_a_prompt_file_parses_into_its_front_matter_and_body(tmp_path: Path) -> None:
    path = _write(tmp_path, _HEAD + "Hello ${who}.\n\n")

    prompt = prompts.load_prompt_file(path)

    assert (prompt.name, prompt.version, prompt.layer, prompt.for_role) == (
        "greeter",
        "1.2.3",
        "hop",
        "implementer",
    )
    assert (prompt.model_class, prompt.output, prompt.tests) == (
        "strong",
        "handoff/v1",
        "greeter.tests.yaml",
    )
    assert prompt.inputs == {"who": "string"}
    assert prompt.text == "Hello ${who}."


def test_model_class_defaults_to_any_and_output_and_tests_may_be_absent(tmp_path: Path) -> None:
    head = "---\nkind: prompt\nname: p\nversion: 1.0.0\nlayer: identity\nfor: lead\n---\nbody\n"

    prompt = prompts.load_prompt_file(_write(tmp_path, head))

    assert (prompt.model_class, prompt.output, prompt.tests, prompt.inputs) == (
        "any",
        None,
        None,
        {},
    )


def test_an_undeclared_variable_is_a_load_error_naming_the_file_and_line(tmp_path: Path) -> None:
    path = _write(tmp_path, _HEAD + "Hello ${who}.\nand ${undeclared} here\n")

    with pytest.raises(prompts.PromptError) as exc_info:
        prompts.load_prompt_file(path)

    error = exc_info.value
    assert error.line == 14
    assert str(error) == f"{path}:14 undeclared variable ${{undeclared}}"


def test_a_malformed_placeholder_is_a_load_error_with_its_line(tmp_path: Path) -> None:
    path = _write(tmp_path, _HEAD + "price: $ 5\n")

    with pytest.raises(prompts.PromptError) as exc_info:
        prompts.load_prompt_file(path)

    assert exc_info.value.line == 13
    assert "malformed placeholder" in str(exc_info.value)


def test_a_doubled_dollar_sign_is_literal_text_not_a_variable(tmp_path: Path) -> None:
    prompt = prompts.load_prompt_file(_write(tmp_path, _HEAD + "costs $$5\n"))

    assert prompts.substitute(prompt.text, {}) == "costs $5"


def test_an_unknown_output_schema_is_refused_naming_the_line(tmp_path: Path) -> None:
    path = _write(tmp_path, _HEAD.replace("handoff/v1", "nonsense/v9") + "x\n")

    with pytest.raises(prompts.PromptError) as exc_info:
        prompts.load_prompt_file(path)

    assert exc_info.value.field == "output"
    assert exc_info.value.line == 10
    assert "nonsense/v9" in str(exc_info.value)
    assert "handoff/v1" in str(exc_info.value)


@pytest.mark.parametrize(
    ("old", "new", "field"),
    [
        ("layer: hop", "layer: banana", "layer"),
        ("version: 1.2.3", "version: 1.2", "version"),
        ("modelClass: strong", "modelClass: huge", "modelClass"),
        ("who: string", "who: tensor", "inputs"),
        ("tests: greeter.tests.yaml", "tests: ../escape.yaml", "tests"),
        ("name: greeter", "name: Greeter", "name"),
        ("for: implementer", "for: implementer\nbogus: 1", "bogus"),
    ],
)
def test_a_front_matter_field_outside_its_vocabulary_is_refused(
    tmp_path: Path, old: str, new: str, field: str
) -> None:
    path = _write(tmp_path, (_HEAD.replace(old, new)) + "x\n")

    with pytest.raises(prompts.PromptError) as exc_info:
        prompts.load_prompt_file(path)

    assert exc_info.value.field == field


@pytest.mark.parametrize(
    "text", ["just a body\n", "---\n- a\n- b\n---\nbody\n", "---\nkind: prompt\n"]
)
def test_a_file_without_a_closed_mapping_front_matter_is_refused(tmp_path: Path, text: str) -> None:
    with pytest.raises(prompts.PromptError):
        prompts.load_prompt_file(_write(tmp_path, text))


def test_a_missing_required_key_is_refused_naming_it(tmp_path: Path) -> None:
    text = "---\nkind: prompt\nname: p\nlayer: hop\nfor: lead\n---\nbody\n"

    with pytest.raises(prompts.PromptError) as exc_info:
        prompts.load_prompt_file(_write(tmp_path, text))

    assert exc_info.value.field == "version"


def test_substitute_is_strict_about_a_missing_variable() -> None:
    assert prompts.substitute("hi ${a}", {"a": "x"}) == "hi x"
    with pytest.raises(prompts.PromptError, match="b"):
        prompts.substitute("hi ${b}", {"a": "x"})


def test_a_shipped_prompt_loads_with_its_hash_and_scope() -> None:
    loaded = prompts.shipped_prompt("hop", "reviewer")

    assert (loaded.name, loaded.layer, loaded.scope) == ("reviewer", "hop", "shipped")
    assert loaded.text.startswith("You are the Reviewer.")
    assert loaded.sha256 == hashlib.sha256(loaded.text.encode("utf-8")).hexdigest()
    assert loaded.version.count(".") == 2


def test_every_shipped_prompt_parses_and_sits_in_the_directory_of_its_layer() -> None:
    files = sorted(_templates.PROMPT_TEMPLATES_DIR.glob("*/*.md"))

    assert len(files) >= 15
    for path in files:
        prompt = prompts.load_prompt_file(path)
        assert prompt.layer == path.parent.name, path
        assert prompt.name == path.stem, path


def test_a_missing_shipped_prompt_is_a_prompt_error() -> None:
    with pytest.raises(prompts.PromptError, match="no shipped prompt"):
        prompts.shipped_prompt("hop", "no-such-prompt")


def test_a_role_text_equal_to_the_shipped_prompt_resolves_to_the_shipped_one() -> None:
    shipped = prompts.shipped_prompt("hop", "lead")

    loaded = prompts.role_prompt("lead", "hop", shipped.text, 1)

    assert loaded == shipped


def test_a_role_text_that_differs_resolves_to_a_pod_override_with_its_own_hash() -> None:
    loaded = prompts.role_prompt("lead", "hop", "my own words", 3)

    assert (loaded.name, loaded.layer, loaded.scope, loaded.version) == (
        "lead",
        "hop",
        "pod",
        "3.0.0",
    )
    assert loaded.text == "my own words"
    assert loaded.sha256 == hashlib.sha256(b"my own words").hexdigest()


def test_a_role_with_no_shipped_prompt_of_that_name_is_a_pod_override() -> None:
    assert prompts.role_prompt("custom-role", "hop", "text", 1).scope == "pod"
