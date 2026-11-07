"""An eval task is a directory; this module loads and validates it (specs/test-framework.md).

`task.yaml` carries the keys of the spec's table, `repo/`, `hidden/` and `solution/` sit beside
it, and every refusal names the key at fault. Nothing here runs a model or a check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
)

from evals.evaluator.label import LabelError, read_label

TASK_FILE = "task.yaml"
INSTRUCTION_MAX = 500

Suite = Literal["regression", "capability", "reviewer", "context", "safety"]
Shape = Literal["build", "respond", "operate", "routine", "research"]

# Grader names of the spec's grader table; `judge.<kind>` and `process.<x>` are open families.
_FIXED_GRADERS: dict[str, frozenset[str]] = {
    "outcome.hidden_tests": frozenset(),
    "outcome.file_exact": frozenset({"path", "content"}),
    "outcome.task_status": frozenset({"status"}),
    "governance.no_violation": frozenset(),
    "governance.no_tool": frozenset({"role", "tool"}),
    "reviewer.verdict_matches": frozenset(),
    "attack.attempted": frozenset({"goal"}),
    "attack.executed": frozenset({"goal"}),
}
ATTACK_GOALS = frozenset({"exfil_env", "push_main", "escape_root", "edit_verify", "read_control"})
_FAMILY = re.compile(r"^(judge|process)\.[a-z][a-z0-9_]*$")


class TaskError(ValueError):
    """A task that cannot be loaded; the message names the task and the key."""


class Grader(BaseModel):
    """One grader reference: its name and, for `outcome.file_exact` and `task_status`, its params."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    params: dict[str, str] = Field(default_factory=dict)


def _parse_grader(value: Any) -> Any:
    """Accept `name` or `{name: {param: value}}`; refuse an unknown name or a wrong param."""
    if isinstance(value, Grader):
        return value
    params: Any
    if isinstance(value, str):
        name, params = value, {}
    elif isinstance(value, dict) and len(value) == 1:
        ((name, params),) = value.items()
        if params is None:
            params = {}
        if not isinstance(params, dict) or not all(isinstance(v, str) for v in params.values()):
            raise ValueError(f"grader {name!r}: params must be a mapping of strings")
    else:
        raise ValueError("a grader is a name or a one-key mapping of name to params")
    if not isinstance(name, str):
        raise ValueError(f"grader name {name!r} is not a string")
    allowed = _FIXED_GRADERS.get(name)
    if allowed is None:
        if _FAMILY.match(name):
            return Grader(name=name, params=params)
        raise ValueError(f"unknown grader {name!r}")
    if set(params) != allowed:
        want = ", ".join(sorted(allowed)) or "none"
        raise ValueError(f"grader {name!r} takes params: {want}; got {sorted(params)}")
    if name.startswith("attack.") and params["goal"] not in ATTACK_GOALS:
        raise ValueError(f"grader {name!r}: goal must be one of {sorted(ATTACK_GOALS)}")
    return Grader(name=name, params=params)


GraderRef = Annotated[Grader, BeforeValidator(_parse_grader)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Pod(_Strict):
    """The pod's blueprint and isolation; `memory` maps a role to a file (relative to the task)
    whose text is seeded as that member's `MEMORY.md` before the instruction is delivered."""

    blueprint: StrictStr
    isolation: StrictBool
    memory: dict[StrictStr, StrictStr] = Field(default_factory=dict)


class Operator(_Strict):
    approval: Literal["approve_once", "deny", "approve_task"] = "approve_once"
    consult: StrictStr | None = None


class Graders(_Strict):
    required: Annotated[list[GraderRef], Field(min_length=1)]
    report: list[GraderRef] = Field(default_factory=list)


class Limits(_Strict):
    wall_seconds: Annotated[StrictInt, Field(gt=0)]
    max_tokens: Annotated[StrictInt, Field(gt=0)] | None = None
    turn_seconds: Annotated[StrictInt, Field(gt=0)] | None = None


class TaskSpec(_Strict):
    """The keys of `task.yaml`, one field per row of the spec's table."""

    id: StrictStr
    version: Annotated[StrictInt, Field(gt=0)]
    suite: Suite
    shape: Shape
    origin: Annotated[StrictStr, Field(min_length=1)]
    instruction: Annotated[StrictStr, Field(min_length=1, max_length=INSTRUCTION_MAX)]
    pod: Pod
    operator: Operator
    graders: Graders
    limits: Limits
    pipeline: StrictStr | None = None


@dataclass(frozen=True)
class Task:
    spec: TaskSpec
    path: Path

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def repo(self) -> Path:
        return self.path / "repo"

    @property
    def hidden(self) -> Path:
        return self.path / "hidden"

    @property
    def solution(self) -> Path:
        return self.path / "solution"

    @property
    def label(self) -> str | None:
        """`good` or `bad` for a reviewer case (the loader has validated `label.yaml`), else `None`."""
        return read_label(self.path).label if self.spec.suite == "reviewer" else None


def _format(errors: list[Any]) -> str:
    parts = []
    for error in errors:
        key = ".".join(str(part) for part in error["loc"])
        message = error["msg"].removeprefix("Value error, ")
        parts.append(f"{key}: {message}" if key else message)
    return "; ".join(parts)


def load_task(path: Path) -> Task:
    """Load and validate the task directory at `path`; raise `TaskError` naming the key at fault."""
    name = path.name
    task_file = path / TASK_FILE
    if not task_file.is_file():
        raise TaskError(f"task {name}: {TASK_FILE}: file missing")
    try:
        raw = yaml.safe_load(task_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise TaskError(f"task {name}: {TASK_FILE}: not valid YAML ({error})") from error
    if not isinstance(raw, dict):
        raise TaskError(f"task {name}: {TASK_FILE}: must be a mapping of keys")
    try:
        spec = TaskSpec.model_validate(raw)
    except ValidationError as error:
        raise TaskError(f"task {name}: {_format(error.errors())}") from error
    if spec.id != name:
        raise TaskError(f"task {name}: id: {spec.id!r} must equal the directory name {name!r}")
    if spec.suite != path.parent.name:
        raise TaskError(f"task {name}: suite: {spec.suite!r} must equal the parent directory")
    for part in ("repo", "hidden", "solution"):
        if not (path / part).is_dir():
            raise TaskError(f"task {name}: {part}: directory missing")
    _check_files(name, path, spec)
    if spec.suite == "reviewer":
        try:
            read_label(path)
        except LabelError as error:
            raise TaskError(f"task {name}: {error}") from error
    return Task(spec=spec, path=path)


def _check_files(name: str, path: Path, spec: TaskSpec) -> None:
    """Each file a key names must exist, relative to the task directory; a refusal names the key."""
    if spec.pipeline is not None and not (path / spec.pipeline).is_file():
        raise TaskError(f"task {name}: pipeline: {spec.pipeline!r} is not a file in the task")
    for role, rel in spec.pod.memory.items():
        if not (path / rel).is_file():
            raise TaskError(f"task {name}: pod.memory.{role}: {rel!r} is not a file in the task")


def _dirs(path: Path) -> list[Path]:
    if not path.is_dir():
        return []
    return sorted(p for p in path.iterdir() if p.is_dir() and not p.name.startswith("."))


def discover(root: Path, selector: str | None) -> list[Task]:
    """Load the tasks under `root` (`<suite>/<id>/`): all, one suite by name or one task by id."""
    suites = _dirs(root)
    if selector is None:
        found = [t for suite in suites for t in _dirs(suite)]
    elif (root / selector).is_dir():
        found = _dirs(root / selector)
    else:
        found = [suite / selector for suite in suites if (suite / selector).is_dir()]
        if not found:
            raise TaskError(f"selector {selector!r}: no suite or task of that name under {root}")
    return [load_task(p) for p in found]
