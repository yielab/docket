"""``teams.prompts``: a prompt file is front matter plus a body, and one loader resolves it."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import docket.kernel.templates as _templates
from docket.kernel.home import current_home
from docket.teams import prompts
from docket.teams.workspace.repo_view import RepoView

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


_REVIEWER = "---\nkind: prompt\nname: reviewer\nversion: {version}\nlayer: hop\nfor: reviewer\n---\n{text}\n"


def _put(directory: Path, file: str, version: str, text: str) -> None:
    path = directory / "hop" / file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_REVIEWER.format(version=version, text=text), encoding="utf-8")


@pytest.mark.parametrize(
    ("text", "kind", "layer", "name", "major"),
    [
        ("implementer", "role", "", "implementer", None),
        ("implementer@2", "role", "", "implementer", 2),
        ("prompt:hop/implementer", "prompt", "hop", "implementer", None),
        ("prompt:hop/implementer@12", "prompt", "hop", "implementer", 12),
    ],
)
def test_a_reference_names_its_kind_name_and_major(
    text: str, kind: str, layer: str, name: str, major: int | None
) -> None:
    ref = prompts.parse_reference(text)

    assert (ref.kind, ref.layer, ref.name, ref.major) == (kind, layer, name, major)
    assert str(ref) == text


@pytest.mark.parametrize("text", ["", "Implementer", "role:implementer", "implementer@x", "a b"])
def test_a_malformed_reference_is_refused(text: str) -> None:
    with pytest.raises(prompts.PromptError, match="not a reference"):
        prompts.parse_reference(text)


def test_with_no_other_scope_a_prompt_resolves_to_the_shipped_one() -> None:
    loaded = prompts.resolve_prompt("hop", "reviewer", project="acme")

    assert loaded == prompts.shipped_prompt("hop", "reviewer")
    assert loaded.scope == "shipped"


def test_the_pod_overlay_beats_the_operator_which_beats_what_ships() -> None:
    home = current_home()
    _put(home.prompts_dir, "reviewer.md", "1.1.0", "OPERATOR")
    assert prompts.resolve_prompt("hop", "reviewer", project="acme").text == "OPERATOR"
    assert prompts.resolve_prompt("hop", "reviewer", project="acme").scope == "operator"

    _put(home.pod_config_dir("acme") / "prompts", "reviewer.md", "1.2.0", "POD")

    loaded = prompts.resolve_prompt("hop", "reviewer", project="acme")
    assert (loaded.text, loaded.scope) == ("POD", "pod")
    assert prompts.resolve_prompt("hop", "reviewer", project="other").text == "OPERATOR"


def test_a_reference_takes_the_newest_file_of_its_major() -> None:
    directory = current_home().prompts_dir
    _put(directory, "reviewer.md", "1.4.0", "ONE-FOUR")
    _put(directory, "reviewer@1.5.0.md", "1.5.0", "ONE-FIVE")
    _put(directory, "reviewer@2.0.0.md", "2.0.0", "TWO")

    assert prompts.resolve_prompt("hop", "reviewer", major=1).text == "ONE-FIVE"
    assert prompts.resolve_prompt("hop", "reviewer", major=2).text == "TWO"
    assert prompts.resolve_prompt("hop", "reviewer").text == "TWO"


def test_a_major_no_file_holds_is_refused_naming_the_reference() -> None:
    with pytest.raises(prompts.PromptError, match=r"no prompt prompt:hop/reviewer@3"):
        prompts.resolve_prompt("hop", "reviewer", major=3)


def test_a_file_that_does_not_parse_is_skipped_for_the_next_scope() -> None:
    home = current_home()
    (home.prompts_dir / "hop").mkdir(parents=True)
    (home.prompts_dir / "hop" / "reviewer.md").write_text("no front matter")

    assert prompts.resolve_prompt("hop", "reviewer").scope == "shipped"


def test_the_repository_is_read_through_the_view_and_only_with_one() -> None:
    text = _REVIEWER.format(version="1.3.0", text="REPOSITORY")
    served = {".docket/prompts/hop/reviewer.md": text.encode()}
    view = RepoView("a" * 40, served.get, lambda _rel: [])

    loaded = prompts.resolve_prompt("hop", "reviewer", view=view)

    assert (loaded.text, loaded.scope) == ("REPOSITORY", "repository")
    assert prompts.resolve_prompt("hop", "reviewer").scope == "shipped"


def test_a_repository_prompt_of_another_major_falls_through() -> None:
    served = {
        ".docket/prompts/hop/reviewer.md": _REVIEWER.format(version="2.0.0", text="TWO").encode()
    }
    view = RepoView("a" * 40, served.get, lambda _rel: [])

    assert prompts.resolve_prompt("hop", "reviewer", view=view, major=1).scope == "shipped"


_VARIANT = (
    "---\nkind: prompt\nname: implementer\nversion: {version}\nlayer: hop\nfor: implementer\n"
    "modelClass: {klass}\n---\n{text}\n"
)


def _variant(directory: Path, file: str, klass: str, text: str, version: str = "1.0.0") -> str:
    path = directory / "hop" / file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_VARIANT.format(version=version, klass=klass, text=text), encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_a_cheap_model_gets_the_cheap_file_and_a_strong_one_the_any_file() -> None:
    directory = current_home().prompts_dir
    cheap = _variant(directory, "implementer.cheap.md", "cheap", "SHORT")
    anyone = _variant(directory, "implementer.md", "any", "FULL", version="2.0.0")

    for_cheap = prompts.resolve_prompt("hop", "implementer", model_class="cheap")
    for_strong = prompts.resolve_prompt("hop", "implementer", model_class="strong")
    for_unknown = prompts.resolve_prompt("hop", "implementer")

    assert (for_cheap.text, for_cheap.sha256) == ("SHORT", cheap)
    assert (for_strong.text, for_strong.sha256) == ("FULL", anyone)
    assert for_unknown.sha256 == anyone


def test_a_file_of_another_class_is_never_offered() -> None:
    _variant(current_home().prompts_dir, "implementer.strong.md", "strong", "BIG")

    assert prompts.resolve_prompt("hop", "implementer", model_class="cheap").scope == "shipped"
    assert prompts.resolve_prompt("hop", "implementer").scope == "shipped"
    assert prompts.resolve_prompt("hop", "implementer", model_class="strong").text == "BIG"


def test_the_nearest_scope_wins_before_the_class_does() -> None:
    home = current_home()
    _variant(home.prompts_dir, "implementer.cheap.md", "cheap", "OPERATOR-CHEAP")
    _variant(home.pod_config_dir("acme") / "prompts", "implementer.md", "any", "POD-ANY")

    loaded = prompts.resolve_prompt("hop", "implementer", project="acme", model_class="cheap")

    assert (loaded.text, loaded.scope) == ("POD-ANY", "pod")


def test_a_repository_variant_is_read_before_its_plain_file() -> None:
    served = {
        ".docket/prompts/hop/implementer.md": _VARIANT.format(
            version="1.0.0", klass="any", text="PLAIN"
        ).encode(),
        ".docket/prompts/hop/implementer.cheap.md": _VARIANT.format(
            version="1.0.0", klass="cheap", text="CHEAP"
        ).encode(),
    }
    view = RepoView("a" * 40, served.get, lambda _rel: [])

    assert prompts.resolve_prompt("hop", "implementer", view=view, model_class="cheap").text == (
        "CHEAP"
    )
    assert prompts.resolve_prompt("hop", "implementer", view=view, model_class="strong").text == (
        "PLAIN"
    )
