"""The ``prompt`` kind: a Markdown file whose YAML front matter declares what the text is for and
which variables it takes, and the one loader that resolves a prompt to its text and hash.

A prompt is the text a role's identity or hop is given, written as a file instead of a Python
literal (specs/functional/config-format.spec.md, "The ``prompt`` kind"). ``parse_prompt`` is the
only parser: the front matter is validated by ``PromptDocument`` (which also generates
``prompt.schema.json``), and every ``${name}`` placeholder of the body must be a key of
``inputs``. ``shipped_prompt`` reads ``templates/prompts/<layer>/<name>.md`` and ``role_prompt``
resolves a role's own declared text, so a hop's wording has a name, a version and a hash wherever
it came from.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from string import Template
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from docket.kernel import templates as _templates
from docket.kernel.errors import InvalidInput

Layer = Literal["identity", "task", "hop"]
OutputSchema = Literal["handoff/v1"]
InputType = Literal["string", "text", "int", "bool", "list"]


SHIPPED = "shipped"
POD = "pod"

_NAME = r"^[a-z][a-z0-9-]*$"
_SEMVER = r"^\d+\.\d+\.\d+$"


class PromptError(InvalidInput):
    """*path* (at *line*, in *field*) is not a valid prompt, or no such prompt exists."""

    def __init__(self, message: str, *, path: Path | str = "", line: int = 0, field: str = ""):
        super().__init__(message)
        self.path = Path(path) if path else None
        self.line = line
        self.field = field

    def __str__(self) -> str:
        if self.path is None:
            return self.message
        return (
            f"{self.path}:{self.line} {self.message}"
            if self.line
            else f"{self.path} {self.message}"
        )


class PromptDocument(BaseModel):
    """The front matter of a prompt file, the schema of ``prompt.schema.json``."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["prompt"]
    name: str = Field(pattern=_NAME)
    description: str | None = None
    version: str = Field(pattern=_SEMVER)
    layer: Layer
    for_role: str = Field(alias="for", pattern=_NAME)
    modelClass: Literal["cheap", "strong", "any"] = "any"
    inputs: dict[str, InputType] = Field(default_factory=dict)
    output: OutputSchema | None = None
    tests: str | None = None

    @field_validator("tests")
    @classmethod
    def _beside_the_prompt(cls, value: str | None) -> str | None:
        if value is not None and (value.startswith("/") or ".." in Path(value).parts):
            raise InvalidInput("must be a relative path beside the prompt")
        return value


@dataclass(frozen=True)
class Prompt:
    """One parsed prompt file: its front matter and its text (the body, trailing newlines cut)."""

    name: str
    version: str
    layer: str
    for_role: str
    model_class: str
    inputs: dict[str, str]
    output: str | None
    tests: str | None
    text: str
    front_matter: dict[str, Any]


@dataclass(frozen=True)
class LoadedPrompt:
    """What the loader returns: the text a consumer renders, its identity and where it came from.
    ``sha256`` hashes ``text`` as UTF-8 before any substitution."""

    name: str
    version: str
    layer: str
    scope: str
    text: str
    sha256: str


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _key_line(front: list[str], key: str) -> int:
    """The file line of top-level *front* key *key*; the first front matter line when absent."""
    for index, line in enumerate(front):
        if re.match(rf"{re.escape(key)}\s*:", line):
            return index + 2
    return 2


def _split(text: str, path: Path) -> tuple[list[str], list[str]]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise PromptError(
            "a prompt starts with a front matter block (a first line `---`)", path=path, line=1
        )
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r\n") == "---":
            return lines[1:index], lines[index + 1 :]
    raise PromptError("the front matter is not closed by a line `---`", path=path, line=1)


def _describe(error: Any) -> tuple[str, str]:
    """(field, message) of one pydantic error, naming the offending value for a vocabulary."""
    field = str(error["loc"][0]) if error["loc"] else ""
    kind = error["type"]
    if kind == "missing":
        return field, "required key is missing"
    if kind == "extra_forbidden":
        return field, "unknown key"
    message = str(error["msg"])
    if kind != "value_error" and len(error["loc"]) == 1:
        return field, f"{message}, got {error['input']!r}"
    return field, message


def parse_prompt(text: str, path: Path | str = "<prompt>") -> Prompt:
    """Parse *text*, the content of the prompt file *path*. Raises ``PromptError`` naming the file
    and line for a bad front matter or a ``${name}`` the front matter does not declare."""
    where = Path(path)
    front, body_lines = _split(text, where)
    try:
        raw = yaml.safe_load("".join(front))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 2 if mark is not None else 2
        raise PromptError(f"front matter is not valid YAML: {exc}", path=where, line=line) from exc
    if not isinstance(raw, dict):
        raise PromptError("the front matter must be a mapping", path=where, line=2)
    try:
        document = PromptDocument.model_validate(raw)
    except ValidationError as exc:
        field, message = _describe(exc.errors()[0])
        raise PromptError(
            f"{field}: {message}", path=where, line=_key_line(front, field), field=field
        ) from exc
    body = "".join(body_lines)
    body_line = len(front) + 3
    for match in Template.pattern.finditer(body):
        line = body_line + body.count("\n", 0, match.start())
        if match.group("invalid") is not None:
            raise PromptError("malformed placeholder", path=where, line=line)
        name = match.group("named") or match.group("braced")
        if name is not None and name not in document.inputs:
            raise PromptError(f"undeclared variable ${{{name}}}", path=where, line=line)
    return Prompt(
        name=document.name,
        version=document.version,
        layer=document.layer,
        for_role=document.for_role,
        model_class=document.modelClass,
        inputs=dict(document.inputs),
        output=document.output,
        tests=document.tests,
        text=body.rstrip("\n"),
        front_matter=raw,
    )


def load_prompt_file(path: str | Path) -> Prompt:
    """Read and parse the prompt file *path*."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptError(f"cannot read file: {exc}", path=p) from exc
    return parse_prompt(text, p)


def substitute(text: str, variables: dict[str, str]) -> str:
    """*text* with each ``${name}`` replaced from *variables*; a name not supplied is an error,
    never a literal ``${typo}``."""
    try:
        return Template(text).substitute(variables)
    except KeyError as exc:
        raise PromptError(f"template references unknown variable: {exc}") from exc
    except ValueError as exc:
        raise PromptError(f"template is malformed: {exc}") from exc


@cache
def shipped_prompt(layer: str, name: str) -> LoadedPrompt:
    """The prompt ``templates/prompts/<layer>/<name>.md`` that ships with docket."""
    path = _templates.PROMPT_TEMPLATES_DIR / layer / f"{name}.md"
    if not path.is_file():
        raise PromptError(f"no shipped prompt {layer}/{name}")
    prompt = load_prompt_file(path)
    if prompt.layer != layer or prompt.name != name:
        raise PromptError(
            f"declares {prompt.layer}/{prompt.name} but ships as {layer}/{name}", path=path, line=2
        )
    return LoadedPrompt(
        prompt.name, prompt.version, layer, SHIPPED, prompt.text, _sha256(prompt.text)
    )


def role_prompt(role: str, layer: str, text: str, version: int) -> LoadedPrompt:
    """*role*'s own declared *text* for *layer*: the shipped prompt of that name when the text is
    the same, else a pod override named for the role, at the role's *version* as ``MAJOR.0.0``."""
    if (_templates.PROMPT_TEMPLATES_DIR / layer / f"{role}.md").is_file():
        shipped = shipped_prompt(layer, role)
        if shipped.text == text:
            return shipped
    return LoadedPrompt(role, f"{version}.0.0", layer, POD, text, _sha256(text))
