from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from docket.kernel import mcp as _mcp
from docket.kernel.errors import InvalidInput
from docket.kernel.records import RecordSet
from docket.teams import pod

# The same name shape `observability.exporter.ExporterSpec` validates -- checked here too so a
# credential-shaped string or a URL is refused for what it is, before a catalog lookup
# (`Catalog.get` on a non-string would raise `TypeError` on the dict membership test).

ApplyAction = Literal["add", "replace", "skip"]


class PodApplyError(InvalidInput):
    """*dir*, or something inside it, cannot be applied to this pod -- an unresolvable role,
    an invalid setting, or a pipeline step the resulting roster cannot run. Raised only by
    ``plan_apply``, before anything is written."""


class PodApplyRefused(PodApplyError):
    """A manifest asks for two things that cannot both hold (a pod-wide setting a bound pipeline
    would silently ignore); a usage error, exit 2."""


@dataclass(frozen=True)
class ApplyItem:
    """One planned change: ``kind`` (role/policy/plugin/member/pipeline/setting), the thing
    named, and whether applying it would add, replace, or skip (already matches disk)."""

    kind: Literal[
        "role",
        "prompt",
        "policy",
        "plugin",
        "skill",
        "mcp-server",
        "service",
        "records",
        "member",
        "pipeline",
        "routine",
        "setting",
    ]
    name: str
    action: ApplyAction
    note: str = ""


@dataclass(frozen=True)
class _RoleWrite:
    """One role's files for the pod overlay's ``roles/``: each relative path with its source
    bytes, the role document first (``teams.roles.role_overlay_files``)."""

    files: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True)
class _PromptWrite:
    """One prompt file for the pod overlay: its path under ``prompts/`` and its source bytes."""

    rel: str
    source: bytes


@dataclass(frozen=True)
class _PolicyWrite:
    name: str
    text: str


@dataclass(frozen=True)
class _PluginWrite:
    name: str
    source: bytes


@dataclass(frozen=True)
class _NamedPipelineWrite:
    name: str
    source: bytes


@dataclass(frozen=True)
class _RoutineWrite:
    name: str
    source: bytes


@dataclass(frozen=True)
class _SkillWrite:
    """One skill's complete file set to write into the pod's own ``config/skills/<name>/`` --
    every relative path (POSIX-separated) inside the skill's own directory paired with its
    bytes, ``SKILL.md`` included."""

    name: str
    files: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True)
class _McpServerWrite:
    """The complete pod-scoped server list to write: the pod's existing servers with each
    recipe-declared one added or replaced by name."""

    servers: tuple[_mcp.McpServerConfig, ...]


@dataclass(frozen=True)
class _ServiceWrite:
    """One ``services/`` file for the pod overlay: its file name and source bytes."""

    name: str
    source: bytes


@dataclass(frozen=True)
class _RecordsWrite:
    """One ``records/`` file for the pod overlay: its file name, source bytes and the set it
    declares, whose table is created or extended when the file is written."""

    name: str
    source: bytes
    record_set: RecordSet


@dataclass(frozen=True)
class _MemberWrite:
    member: pod.PodMember
    codebase: str
    stack: str
    description: str
    project_key: str
    work_dir: str
    blueprint_name: str


@dataclass(frozen=True)
class _PipelineWrite:
    text: str
    digest: str


@dataclass(frozen=True)
class _SettingWrite:
    key: str
    value: float | int | str


@dataclass(frozen=True)
class ApplyPlan:
    """The full set of planned items plus the data ``apply`` needs to write them --
    opaque to a caller beyond ``items`` and ``has_changes``."""

    project: str
    directory: Path
    items: tuple[ApplyItem, ...]
    exporters: tuple[str, ...] = field(default=())
    _role_writes: tuple[_RoleWrite, ...] = field(default=())
    _prompt_writes: tuple[_PromptWrite, ...] = field(default=())
    _policy_writes: tuple[_PolicyWrite, ...] = field(default=())
    _plugin_writes: tuple[_PluginWrite, ...] = field(default=())
    _named_pipeline_writes: tuple[_NamedPipelineWrite, ...] = field(default=())
    _routine_writes: tuple[_RoutineWrite, ...] = field(default=())
    _skill_writes: tuple[_SkillWrite, ...] = field(default=())
    _mcp_server_write: _McpServerWrite | None = field(default=None)
    _service_writes: tuple[_ServiceWrite, ...] = field(default=())
    _records_writes: tuple[_RecordsWrite, ...] = field(default=())
    _member_writes: tuple[_MemberWrite, ...] = field(default=())
    _pipeline_write: _PipelineWrite | None = field(default=None)
    _setting_writes: tuple[_SettingWrite, ...] = field(default=())

    def has_changes(self) -> bool:
        return any(item.action != "skip" for item in self.items)


@dataclass(frozen=True)
class ApplyResult:
    """What ``apply`` actually did -- the same items ``plan_apply`` returned, now written.
    ``exporters`` is this pod's recorded destination names (ADR 0014 rule 7) -- reported, not
    activated; the CLI renders each one's state from ``observability.exporter.activation_state``."""

    project: str
    items: tuple[ApplyItem, ...]
    exporters: tuple[str, ...] = ()
