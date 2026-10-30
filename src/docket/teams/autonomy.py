"""Autonomy levels: the table of what a pause does when nobody is there, and the level a task has.

A level is a policy over escalations, not a second gate. The built-in ``kind: autonomy`` document
(``templates/autonomy/default.yaml``) maps each escalation kind at each level to a policy and an
expiry; ``policy_for`` reads it. The level of a task is its requested one, narrowed to the ceiling
its pod's profile allows. The pod settings ``consultMode`` and ``approvalMode`` are aliases of the
``consult`` and ``approval`` rows: set explicitly they win, unset the table answers. See
security-gates.spec.md "Autonomy levels".
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from docket.kernel import templates as _templates
from docket.kernel.errors import InvalidInput
from docket.teams import fleet as _fleet
from docket.teams import pod_settings as _pod_settings

__all__ = [
    "DEFAULT_DOCUMENT",
    "KINDS",
    "LEVELS",
    "AutonomyDocument",
    "AutonomyError",
    "LevelAboveCeiling",
    "approval_policy_for",
    "check_level",
    "consult_mode_for",
    "default_level",
    "effective_level",
    "load_autonomy_document",
    "policy_for",
    "table_denies_approval",
]

LEVELS: tuple[str, ...] = ("L3", "L4", "L5")
KINDS: tuple[str, ...] = ("approval", "consult", "input", "gate", "check_changed", "wait")

DEFAULT_DOCUMENT: Path = _templates.AUTONOMY_TEMPLATES_DIR / "default.yaml"

_ATTENDED = "attended"
_LIGHTS_OUT = "lights-out"
_CEILING = {_ATTENDED: "L3", _LIGHTS_OUT: "L5"}
_DEFAULT = {_ATTENDED: "L3", _LIGHTS_OUT: "L4"}


class AutonomyError(InvalidInput):
    """A ``kind: autonomy`` document that cannot be read or does not hold the whole table."""


class LevelAboveCeiling(InvalidInput):
    """A requested level above what the pod's profile admits (HTTP 422)."""


class _Cell(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    policy: Literal["person", "recommendation", "deny", "fail", "machine"]
    on_expiry: Literal["deny", "block"] = Field(alias="onExpiry")


class AutonomyDocument(BaseModel):
    """A ``kind: autonomy`` document: ``rows[kind][level]`` is the policy and expiry of one cell,
    and every one of the eighteen cells must be present."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: Literal["autonomy"]
    name: str
    description: str = ""
    rows: dict[str, dict[str, _Cell]]

    @model_validator(mode="after")
    def _the_whole_table(self) -> AutonomyDocument:
        for kind in self.rows:
            if kind not in KINDS:
                raise InvalidInput(f"rows.{kind}: not an escalation kind ({', '.join(KINDS)})")
        for kind in KINDS:
            levels = self.rows.get(kind)
            if levels is None:
                raise InvalidInput(f"rows.{kind} is missing")
            for level in levels:
                if level not in LEVELS:
                    raise InvalidInput(f"rows.{kind}.{level}: not a level ({', '.join(LEVELS)})")
            for level in LEVELS:
                if level not in levels:
                    raise InvalidInput(f"rows.{kind} is missing level {level}")
        return self

    def cell(self, kind: str, level: str) -> tuple[str, str]:
        """The ``(policy, on_expiry)`` of *kind* at *level*."""
        found = self.rows[kind][level]
        return found.policy, found.on_expiry


def load_autonomy_document(path: str | Path) -> AutonomyDocument:
    """Read *path* as a ``kind: autonomy`` document; ``AutonomyError`` names the file and the
    problem for anything unreadable, misshapen or incomplete."""
    p = Path(path)
    try:
        import yaml as _yaml  # type: ignore[import-untyped]
    except ImportError:
        raise AutonomyError(f"{p}: PyYAML not installed -- run: pip install pyyaml") from None
    try:
        raw: Any = _yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, _yaml.YAMLError) as exc:
        raise AutonomyError(f"{p}: cannot read the document: {exc}") from exc
    if not isinstance(raw, dict):
        raise AutonomyError(f"{p}: the document must be a mapping")
    try:
        return AutonomyDocument.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        raise AutonomyError(f"{p}: {where}: {first['msg']}") from exc
    except InvalidInput as exc:
        raise AutonomyError(f"{p}: {exc.message}") from exc


@functools.lru_cache(maxsize=1)
def _table() -> AutonomyDocument:
    return load_autonomy_document(DEFAULT_DOCUMENT)


def policy_for(kind: str, level: str) -> tuple[str, str]:
    """The ``(policy, on_expiry)`` of an escalation of *kind* at *level*."""
    if kind not in KINDS:
        raise InvalidInput(f"unknown escalation kind {kind!r} ({', '.join(KINDS)})")
    if level not in LEVELS:
        raise InvalidInput(f"unknown level {level!r} (L3, L4 or L5)")
    return _table().cell(kind, level)


def _profile_of(project: str) -> str:
    """``lights-out`` when the fleet or the pod says so; unreadable pod settings read as
    ``attended``, the profile whose ceiling a person still validates under."""
    if _fleet.get_profile() == _LIGHTS_OUT:
        return _LIGHTS_OUT
    try:
        return _pod_settings.PodSettings.load_for(project).profile
    except _pod_settings.PodSettingsError:
        return _ATTENDED


def default_level(project: str) -> str:
    """The level a task with none takes: ``L3`` attended, ``L4`` lights-out."""
    return _DEFAULT[_profile_of(project)]


def check_level(project: str, requested: str) -> str:
    """*requested* when it is a level the pod's profile admits; ``InvalidInput`` for a value that is
    no level, ``LevelAboveCeiling`` for one above the ceiling."""
    if requested not in LEVELS:
        raise InvalidInput(f"autonomy must be L3, L4 or L5, not {requested!r}")
    profile = _profile_of(project)
    ceiling = _CEILING[profile]
    if LEVELS.index(requested) > LEVELS.index(ceiling):
        raise LevelAboveCeiling(
            f"autonomy {requested} is above this pod's ceiling {ceiling} "
            f"(profile {profile}); set the pod profile to lights-out for L5"
        )
    return requested


def effective_level(project: str, requested: str | None) -> str:
    """The level a pause of a task that asked for *requested* is decided at: that level narrowed
    to the pod's ceiling now, else the profile's default."""
    if requested not in LEVELS:
        return default_level(project)
    ceiling = _CEILING[_profile_of(project)]
    return min(requested, ceiling, key=LEVELS.index)


def consult_mode_for(project: str, level: str) -> Literal["park", "decide"]:
    """What a consult does at *level*: the pod's ``consultMode`` when it is set, else the
    ``consult`` row (``recommendation`` decides, anything else parks)."""
    if _pod_settings.is_explicit(project, "consultMode"):
        return _pod_settings.PodSettings.load_for(project).consult_mode
    return "decide" if policy_for("consult", level)[0] == "recommendation" else "park"


def approval_policy_for(project: str, level: str) -> str:
    """The policy of a tool ``ask`` at *level*: an explicit pod ``approvalMode`` (``refuse`` is
    ``deny``, ``wait`` and ``park`` are ``person``) wins over the ``approval`` row."""
    if _pod_settings.is_explicit(project, "approvalMode"):
        mode = _pod_settings.PodSettings.load_for(project).approval_mode
        return "deny" if mode == "refuse" else "person"
    return policy_for("approval", level)[0]


def table_denies_approval(project: str, level: str) -> bool:
    """Whether the table, not a pod setting, denies a tool ``ask`` at *level*."""
    if _pod_settings.is_explicit(project, "approvalMode"):
        return False
    return policy_for("approval", level)[0] == "deny"
