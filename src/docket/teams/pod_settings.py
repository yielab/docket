from __future__ import annotations

import re
from pathlib import Path
from typing import Any, ClassVar, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator
from pydantic import ValidationError as _PydanticValidationError

from docket.agent.tools import mcp_tools as _mcp_tools
from docket.governance import security as _security
from docket.hops.workspace import prepare as _prepare
from docket.hops.workspace import protected_paths as _protected
from docket.kernel.errors import InvalidInput
from docket.pipeline.application import schedule as _schedule
from docket.teams import fleet as _fleet
from docket.teams import roles as _archetypes
from docket.teams.pod import member_id


class PodSettingsError(InvalidInput):
    """A pod setting's value is invalid: bad type, out of range, or unknown key."""


# alias -> attribute, so the CLI and dispatch never hardcode a second copy of
# this mapping next to PodSettings.KEYS.
_SETTING_FIELD_BY_ALIAS: dict[str, str] = {
    "budgetUsd": "budget_usd",
    "maxReworkCycles": "max_rework_cycles",
    "turnTimeoutS": "turn_timeout_s",
    "verifyTimeoutS": "verify_timeout_s",
    "approvalMode": "approval_mode",
    "approvalExpiryHours": "approval_expiry_hours",
    "inputExpiryHours": "input_expiry_hours",
    "allowCommands": "allow_commands",
    "pipeline": "pipeline",
    "schedule": "schedule",
    "projectInstructions": "project_instructions",
    "mcpServers": "mcp_servers",
    "deniedTools": "denied_tools",
    "requireVerify": "require_verify",
    "maxConsultationsPerTask": "max_consultations_per_task",
    "network": "network",
    "profile": "profile",
    "readOnly": "read_only",
    "prepare": "prepare",
    "protects": "protects",
}

# allowCommands validation: no path segment, no shell metacharacter -- this is
# the same charset a bare basename can use, nothing that could resolve to a
# different binary or escape the allowlist check it feeds.
_INVALID_BIN_NAME_CHARS = re.compile(r"[^A-Za-z0-9_.+-]")
# Opaque/scope-changing shell names: allowlisting these would let a pod
# smuggle an arbitrary binary in behind a name docket cannot statically
# classify, the same reason classify_command keeps them off SAFE_BINS.
_OPAQUE_COMMAND_NAMES: frozenset[str] = frozenset({"eval", "exec", "source", ".", "export"})


# Typed, validated view over the pod Lead's dispatch-configuration meta keys
# (budgetUsd/maxReworkCycles/turnTimeoutS/verifyTimeoutS -- see
# specs/data/docket-meta.spec.md). A missing/blank meta key uses the field
# default below, but a *present, malformed* stored value is never silently
# replaced by it: ``load_for``/``coerce`` raise ``PodSettingsError`` naming the
# key instead, and core/dispatch.py's readers let that propagate, so a bad
# stored value refuses dispatch rather than guessing at one. A later pod
# setting (approvalMode, pipeline, allowCommands) adds a field plus a
# ``KEYS``/alias entry here, never a second reader.
class PodSettings(BaseModel):
    """One pod's dispatch-config settings, validated from the Lead's meta."""

    model_config = ConfigDict(populate_by_name=True)

    budget_usd: float = Field(0.0, alias="budgetUsd", ge=0)
    max_rework_cycles: int = Field(1, alias="maxReworkCycles", ge=0)
    turn_timeout_s: int | None = Field(None, alias="turnTimeoutS", gt=0)
    verify_timeout_s: int | None = Field(None, alias="verifyTimeoutS", gt=0)
    # Whether an unattended hop waits on an `ask` verdict (today's behavior,
    # byte-identical), parks it durably for a human to resolve later, or
    # refuses it at once -- threaded into the hop's tool env as
    # DOCKET_APPROVAL_MODE (see core/dispatch.py's `_compose_hop` and
    # agent/tools/registry.py's `ToolContext.approval_mode`). The field default stays
    # "wait" (export/apply round-trips and goldens depend on it); "unset" --
    # which caller-scoped default applies (ADR 0016 SS2) -- is detected from
    # whether the Lead's meta carries this key at all
    # (core/dispatch.py's `pod_approval_mode_is_set`), never from this value.
    approval_mode: Literal["wait", "park", "refuse"] = Field("wait", alias="approvalMode")
    # Hours a park-mode approval record stays live before the fail-closed
    # sweep denies it (core/dispatch.py's `_compose_hop`, which stamps each
    # parked call's own `expiresAt`).
    approval_expiry_hours: int = Field(24, alias="approvalExpiryHours", ge=1)
    # Hours an `input` step's unanswered question stays live before it is
    # tagged `blockedReason: "input_expired"` (read by a later execution card;
    # unused by dispatch until then).
    input_expiry_hours: int = Field(72, alias="inputExpiryHours", ge=1)
    allow_commands: tuple[str, ...] = Field((), alias="allowCommands")
    # sha256 hex digest of the docket-owned bound-pipeline copy in the Lead's workspace
    # (``bound_pipeline_path``) -- never the operator's original file path. Set only by
    # ``docket pod set pipeline <file>``, which validates the file and
    # writes the copy before this ever gets written (see core/dispatch.py's
    # ``_blueprint_pipeline``, which verifies the copy still hashes to this value).
    pipeline: str | None = Field(None, alias="pipeline", pattern=r"^[0-9a-f]{64}$")
    # An `@every`/`HH:MM`/cron spec (pipeline/application/schedule.py). Mirrors the value the dedicated
    # `set schedule <spec>` CLI path (`interfaces/cli/commands/pod.py::_pod_config_set_schedule`) persists as
    # this pod's actual source of truth in `docket-schedules.json` -- see that function's
    # docstring for why this field exists alongside a second, non-meta store.
    schedule: str | None = Field(None, alias="schedule")
    # Relative paths (comma-joined in storage, like allowCommands) inside this pod's
    # codebase root, composed into a turn's system prompt right after INSTRUCTIONS.md
    # (agent/identity.py's opt-in section) -- the AGENTS.md/CLAUDE.md convention, but
    # never auto-discovered: unset (the default) composes byte-identically to today.
    # Validated here (not at codebase-resolution time) so a path that could only ever
    # escape the root -- absolute, home-relative, or containing a ".." segment -- is
    # refused at `set`, before this pod even has a resolved codebase root to check it
    # against; a plain `coerce` is enough because that check needs no filesystem
    # access, unlike `pipeline`'s dedicated CLI path (which must read and plan an
    # operator file) or `schedule`'s (which writes a second store).
    project_instructions: tuple[str, ...] = Field((), alias="projectInstructions")

    # This pod's own selection from the shared MCP server catalog
    # (agent/tools/mcp_tools.py::load_mcp_servers()). ``None`` (the default, and every
    # pod before this field existed) means "every configured server" -- today's
    # behavior, unchanged. A non-empty tuple names the exhaustive subset this
    # pod's turns load; agent/driver.py::_load_mcp_tools is the
    # sole reader (see its docstring for the live-turn refusal this feeds).
    # Validated against the *live* catalog at `set` time (below) -- not merely
    # syntactically -- because an unconfigured server name here is always a
    # mistake, unlike allowCommands/projectInstructions, whose validity does not
    # depend on any other docket-owned store.
    mcp_servers: tuple[str, ...] | None = Field(None, alias="mcpServers")
    # Built-in tool names this pod's every role additionally denies, unioned with
    # each role's own `denied_tools` by `teams.roles.registry_for_role` (see
    # role-archetypes.spec.md's "Per-role tool sets" requirement 7). Validated
    # against the same known tool-name universe `denied_tools` narrowing already
    # keys off (`teams.roles.BUILTIN_TOOL_KINDS`), so a typo is refused at
    # `set` instead of silently doing nothing at dispatch time.
    denied_tools: tuple[str, ...] = Field((), alias="deniedTools")

    # Whether an Implementer's unset verifyCmd (no verification gate) is
    # treated as skippable (the default, false) or as a required failure
    # (true). When true and verifyCmd is unset, the task fails with a
    # clear reason instead of silently advancing.
    require_verify: bool = Field(False, alias="requireVerify")
    # How many `consult` questions one task's turn may ask (tasks/application/consult.py); 0 disables.
    max_consultations_per_task: int = Field(3, alias="maxConsultationsPerTask", ge=0)

    # 'open' (the default: follow the global mode, itself 'none' unless granted) or 'none': cut this pod's jailed tool calls
    # off the network. It only ever narrows -- see ``effective_network``.
    network: str = Field("open", alias="network")

    # '' (every machine read-only jail grant), 'none', or the comma-joined grants this pod keeps.
    # It only ever narrows: ``coerce`` refuses a path the machine has not granted.
    read_only: str = Field("", alias="readOnly")

    # The install command a task's fresh worktree runs before its first hop (hops/workspace/prepare.py);
    # 'none' turns preparation off and '' leaves the choice to the worktree's lockfile.
    prepare: str = Field("", alias="prepare")

    # Globs a task may not change without a person (hops/workspace/protected_paths.py); they add to the
    # defaults and never remove one. Comma-joined in storage, like allowCommands.
    protects: tuple[str, ...] = Field((), alias="protects")

    # 'attended' (the default) or 'lights-out' (governance/profile.py): a pod may only move toward
    # stricter than the fleet's recorded profile -- ``coerce`` refuses a weaker write.
    profile: str = Field("attended", alias="profile")

    # Where this pod's team came from (ADR 0012): the absolute directory `teams.apply.plan.apply`
    # last applied, and a sha256 fingerprint of that directory's contents at that moment
    # (`teams.apply.plan.directory_digest`). Written only by `apply`, right after a plan that
    # wrote at least one item -- never by `docket pod set` (see `RECORDED_KEYS`) and
    # never carried in a `pod.yaml` `settings` mapping, since both are refused the same way any
    # key outside `KEYS` already is. `docket pod show` recomputes the digest
    # against the still-present directory to report drift.
    config_source: str = Field("", alias="configSource")
    config_digest: str = Field("", alias="configDigest", pattern=r"^(|[0-9a-f]{64})$")

    # Which observability destinations (`observability.exporter.load_catalog()` names) this pod's last
    # applied recipe named (ADR 0014 rule 7) -- recorded by `teams.apply.plan.apply`, exactly like
    # `configSource`/`configDigest` above, and never configurable directly (`pod set
    # exporters` is refused the same way). Names are already validated against the live catalog
    # by `plan_apply` before this is ever stored, so no catalog dependency is added here.
    exporters: tuple[str, ...] = Field((), alias="exporters")

    # Declaration order the CLI's ``config`` subcommand, ``load_for`` and
    # ``coerce`` all iterate, instead of a second hardcoded key list.
    KEYS: ClassVar[tuple[str, ...]] = (
        "budgetUsd",
        "maxReworkCycles",
        "turnTimeoutS",
        "verifyTimeoutS",
        "approvalMode",
        "approvalExpiryHours",
        "inputExpiryHours",
        "allowCommands",
        "pipeline",
        "schedule",
        "projectInstructions",
        "mcpServers",
        "deniedTools",
        "requireVerify",
        "maxConsultationsPerTask",
        "network",
        "profile",
        "readOnly",
        "prepare",
        "protects",
    )

    # Recorded by `apply`, not operator-settable -- deliberately outside `KEYS` so every
    # settable-key path (`coerce`, `pod set`'s fallthrough, a `pod.yaml` `settings` mapping)
    # already refuses them as unknown; `pod set` checks this tuple first only to give the
    # friendlier "written by apply" message instead of "unknown pod setting".
    RECORDED_KEYS: ClassVar[tuple[str, ...]] = ("configSource", "configDigest", "exporters")

    @field_validator("allow_commands", mode="before")
    @classmethod
    def _parse_allow_commands(cls, value: Any) -> tuple[str, ...]:
        """Comma-separated exact binary basenames. Rejects a path segment, a shell
        metacharacter, an opaque/scope-changing name, or a high-risk-class binary;
        a name already on ``SAFE_BINS`` is accepted but dropped (redundant)."""
        if value in (None, ""):
            return ()
        tokens = list(value) if isinstance(value, (list, tuple)) else str(value).split(",")
        high_risk_bins = {b for hrc in _security.HIGH_RISK_PATTERNS for b in hrc.bins}
        kept: dict[str, None] = {}
        for raw in tokens:
            name = str(raw).strip()
            if not name:
                continue
            if _INVALID_BIN_NAME_CHARS.search(name):
                raise InvalidInput(f"{name!r} is not a valid binary basename")
            if name in _OPAQUE_COMMAND_NAMES:
                raise InvalidInput(f"{name!r} is opaque/scope-changing, cannot be allowlisted")
            if name in high_risk_bins:
                raise InvalidInput(
                    f"{name!r} names a high-risk action class, cannot be allowlisted"
                )
            if name in _security.SAFE_BINS:
                continue  # already unattended-safe -- redundant, silently dropped
            kept.setdefault(name, None)
        return tuple(kept.keys())

    @field_validator("schedule", mode="before")
    @classmethod
    def _parse_schedule(cls, value: Any) -> str | None:
        """A recognized ``@every``/``HH:MM``/cron spec, or None. Rejects (naming the
        reason) exactly the specs ``pipeline.application.schedule.is_schedule_due`` would otherwise treat
        as silently never-due."""
        if value in (None, ""):
            return None
        text = str(value)
        reason = _schedule.describe_spec_error(text)
        if reason:
            raise InvalidInput(reason)
        return text

    # Rejects the only shapes that could ever resolve outside the codebase root this
    # pod's agents already have containment-checked access to (agent/tools/registry.py's
    # ``roots``). Purely syntactic -- no filesystem access -- so it refuses an
    # escaping value at `set` even before a codebase root exists to check it against.
    @field_validator("project_instructions", mode="before")
    @classmethod
    def _parse_project_instructions(cls, value: Any) -> tuple[str, ...]:
        """Comma-separated relative paths, like ``allow_commands``. Rejects (naming
        the path) an absolute, home-relative (``~``), or ``..``-containing value."""
        if value in (None, ""):
            return ()
        tokens = list(value) if isinstance(value, (list, tuple)) else str(value).split(",")
        kept: dict[str, None] = {}
        for raw in tokens:
            name = str(raw).strip()
            if not name:
                continue
            if "\x00" in name:
                raise InvalidInput(f"{name!r} contains a null byte")
            if name.startswith("~") or Path(name).is_absolute():
                raise InvalidInput(f"{name!r} is not a relative path inside the codebase root")
            if ".." in Path(name).parts:
                raise InvalidInput(f"{name!r} escapes the codebase root")
            kept.setdefault(name, None)
        return tuple(kept.keys())

    # Checked against `agent.tools.mcp_tools.load_mcp_servers()` right here -- a name absent
    # from the live catalog is refused (naming it) at `set` time, so a typo or a
    # since-removed server can never silently resolve to "load nothing" at dispatch
    # time.
    @field_validator("mcp_servers", mode="before")
    @classmethod
    def _parse_mcp_servers(cls, value: Any, info: ValidationInfo) -> tuple[str, ...] | None:
        """Comma-separated names from the global MCP catalog plus this pod's own pod-scoped
        servers (``context['project']``, and ``context['mcp_extra']`` for names a recipe is
        installing), or ``None`` (the default) for "every configured server"."""
        if value in (None, ""):
            return None
        tokens = list(value) if isinstance(value, (list, tuple)) else str(value).split(",")
        context = info.context or {}
        project = str(context.get("project", ""))
        catalog = {s.name for s in _mcp_tools.load_mcp_servers(project)}
        catalog.update(context.get("mcp_extra", ()))
        kept: dict[str, None] = {}
        for raw in tokens:
            name = str(raw).strip()
            if not name:
                continue
            if name not in catalog:
                owner = _mcp_tools.pod_scoped_owner(name, exclude=project)
                if owner:
                    raise InvalidInput(
                        f"{name!r} is an MCP server of another pod ({owner}); "
                        "a pod selects only global servers and its own"
                    )
                raise InvalidInput(
                    f"{name!r} is not a configured MCP server (docket setup mcp list)"
                )
            kept.setdefault(name, None)
        return tuple(kept.keys()) or None

    # Rejects (naming it) any name outside `teams.roles.BUILTIN_TOOL_KINDS` -- the
    # same known-tool universe `registry_for_role`'s kind-based narrowing already keys
    # off -- so a typo is refused here rather than silently denying nothing.
    @field_validator("denied_tools", mode="before")
    @classmethod
    def _parse_denied_tools(cls, value: Any) -> tuple[str, ...]:
        """Comma-separated built-in tool names, like ``allow_commands``."""
        if value in (None, ""):
            return ()
        tokens = list(value) if isinstance(value, (list, tuple)) else str(value).split(",")
        known = set(_archetypes.BUILTIN_TOOL_KINDS)
        kept: dict[str, None] = {}
        for raw in tokens:
            name = str(raw).strip()
            if not name:
                continue
            if name not in known:
                raise InvalidInput(
                    f"{name!r} is not a known tool name ({', '.join(sorted(known))})"
                )
            kept.setdefault(name, None)
        return tuple(kept.keys())

    @field_validator("network", mode="before")
    @classmethod
    def _parse_network(cls, value: Any) -> str:
        """``none`` or ``open``."""
        name = str(value).strip().lower()
        if name not in ("none", "open"):
            raise InvalidInput("must be 'none' or 'open'")
        return name

    @field_validator("read_only", mode="before")
    @classmethod
    def _parse_read_only(cls, value: Any) -> str:
        """``''``, ``none``, or absolute paths, comma-joined and deduplicated."""
        text = str(value or "").strip()
        if text.lower() == "none":
            return "none"
        paths = dict.fromkeys(p.strip() for p in text.split(",") if p.strip())
        for path in paths:
            if not Path(path).is_absolute():
                raise InvalidInput(f"{path!r} is not an absolute path")
        return ",".join(paths)

    @field_validator("prepare", mode="before")
    @classmethod
    def _parse_prepare(cls, value: Any) -> str:
        """One line of at most 1,000 characters, or ``none``."""
        return _prepare.check_command(value)

    @field_validator("protects", mode="before")
    @classmethod
    def _parse_protects(cls, value: Any) -> tuple[str, ...]:
        """Comma-separated path globs, at most ``MAX_PATTERNS``, each one ``check_pattern`` accepts."""
        if value in (None, ""):
            return ()
        tokens = list(value) if isinstance(value, (list, tuple)) else str(value).split(",")
        kept: dict[str, None] = {}
        for raw in tokens:
            if str(raw).strip():
                kept.setdefault(_protected.check_pattern(raw), None)
        if len(kept) > _protected.MAX_PATTERNS:
            raise InvalidInput(f"at most {_protected.MAX_PATTERNS} patterns")
        return tuple(kept.keys())

    @field_validator("profile", mode="before")
    @classmethod
    def _parse_profile(cls, value: Any) -> str:
        """``attended`` or ``lights-out``."""
        name = str(value).strip().lower()
        if name not in ("attended", "lights-out"):
            raise InvalidInput("must be 'attended' or 'lights-out'")
        return name

    @field_validator("exporters", mode="before")
    @classmethod
    def _parse_exporters(cls, value: Any) -> tuple[str, ...]:
        """Comma-separated exporter catalog names, like ``allow_commands`` -- already
        validated against the catalog by ``teams.apply.plan.plan_apply`` before this is ever
        stored, so this parser only reshapes the stored string back into a tuple."""
        if value in (None, ""):
            return ()
        tokens = list(value) if isinstance(value, (list, tuple)) else str(value).split(",")
        kept: dict[str, None] = {}
        for raw in tokens:
            name = str(raw).strip()
            if name:
                kept.setdefault(name, None)
        return tuple(kept.keys())

    @classmethod
    def _validated(
        cls,
        present: dict[str, str],
        *,
        project: str = "",
        mcp_extra: tuple[str, ...] = (),
        stored: bool = True,
    ) -> PodSettings:
        label = "invalid stored value" if stored else "invalid value"
        try:
            return cls.model_validate(present, context={"project": project, "mcp_extra": mcp_extra})
        except _PydanticValidationError as exc:
            first = exc.errors()[0]
            key = str(first["loc"][0]) if first["loc"] else "?"
            raise PodSettingsError(f"{key}: {label} {present.get(key)!r} ({first['msg']})") from exc

    @classmethod
    def load_for(cls, project: str) -> PodSettings:
        """Read and validate one pod Lead's stored settings, ``RECORDED_KEYS`` alongside
        ``KEYS`` (see class docs: never catch the raised error to substitute a default)."""
        lead_id = member_id(project, "lead")
        present = {
            k: v for k in (*cls.KEYS, *cls.RECORDED_KEYS) if (v := _fleet.meta_get(lead_id, k, ""))
        }
        return cls._validated(present, project=project)

    @classmethod
    def coerce(
        cls, key: str, value: str, *, project: str = "", mcp_extra: tuple[str, ...] = ()
    ) -> float | int | str:
        """Validate *value* for *key*; return the form to persist via ``teams.fleet.meta_set``.
        Never writes. *project*/*mcp_extra* widen ``mcpServers`` to that pod's own servers."""
        if key not in cls.KEYS:
            raise PodSettingsError(
                f"unknown pod setting {key!r}; valid keys: {', '.join(cls.KEYS)}"
            )
        settings = cls._validated({key: value}, project=project, mcp_extra=mcp_extra, stored=False)
        if (
            key == "profile"
            and settings.profile == "attended"
            and _fleet.get_profile() == "lights-out"
        ):
            raise PodSettingsError(
                "profile: 'attended' is weaker than the fleet's lights-out profile; "
                "a pod can only move toward stricter (docket setup profile attended first)"
            )
        if key == "readOnly" and settings.read_only not in ("", "none"):
            granted = {str(p) for p in _fleet.get_read_only_paths()}
            kept = [str(Path(p).resolve()) for p in settings.read_only.split(",")]
            missing = [p for p in kept if p not in granted]
            if missing:
                raise PodSettingsError(
                    f"readOnly: {missing[0]} is not a machine grant; a pod only narrows them "
                    f"(docket setup sandbox read add {missing[0]} first)"
                )
            return ",".join(dict.fromkeys(kept))
        return cast(
            "float | int | str", cls._stored_form(getattr(settings, _SETTING_FIELD_BY_ALIAS[key]))
        )

    @staticmethod
    def _stored_form(value: float | int | str | tuple[str, ...] | None) -> float | int | str | None:
        """A tuple-valued setting's meta-store form: comma-joined, matching how
        it is read back (``meta_get`` always returns a plain string)."""
        return ",".join(value) if isinstance(value, tuple) else value

    def value_and_source(self, key: str, project: str) -> tuple[float | int | str | None, str]:
        """This setting's value plus whether it is "set" (Lead meta) or
        "default" (this model's own default)."""
        lead_id = member_id(project, "lead")
        source = "set" if _fleet.meta_get(lead_id, key, "") else "default"
        return self._stored_form(getattr(self, _SETTING_FIELD_BY_ALIAS[key])), source


def effective_network(project: str | None) -> tuple[str, str]:
    """``(mode, scope)`` for a turn: ``none`` if the global mode or the pod's ``network`` says so,
    else ``open``. Scope is ``global``, ``pod`` or ``default`` (the unrecorded ``none``). A pod's
    ``open`` never widens a global ``none``; unreadable pod settings fail closed to ``none``."""
    global_none = _fleet.get_network_mode() == "none"
    if global_none and _fleet.network_mode_recorded():
        return "none", "global"
    if project is not None:
        try:
            if PodSettings.load_for(project).network == "none":
                return "none", "pod"
        except PodSettingsError:
            return "none", "pod"
    return ("none" if global_none else "open"), "default"


def effective_read_only(project: str | None) -> tuple[Path, ...]:
    """The read-only jail grants of a turn in *project*: the machine's, kept only where the pod's
    ``readOnly`` names them; unreadable pod settings fail closed to none."""
    granted = _fleet.get_read_only_paths()
    if project is None:
        return granted
    try:
        chosen = PodSettings.load_for(project).read_only
    except PodSettingsError:
        return ()
    if chosen == "":
        return granted
    kept = set(chosen.split(",")) if chosen != "none" else set()
    return tuple(p for p in granted if str(p) in kept)
