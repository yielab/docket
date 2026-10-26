"""evidence: what a finished task's hops kept, as one published model (1.1.0).

``task_evidence`` is the one builder. It reads the persisted task record and projects each hop
through these models; later surfaces (CLI, HTTP) serve the result and never assemble it
themselves. Everything here is measured or recorded: tokens are the endpoint's counts, never an
estimate or a dollar figure, and the model carries no score or verdict about the evidence.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer

from docket.kernel.errors import InvalidInput, NotFound
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.task import HopResult

EVIDENCE_V1_1: Literal["1.1.0"] = "1.1.0"
EvidenceVersion = Literal["1.1.0"]


class EvidenceNotFound(NotFound):
    """No task with this id exists in the pod's queue."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class VerifyEvidence(_Model):
    cmd: str
    exit_code: int = Field(alias="exitCode")
    duration_s: float = Field(alias="durationS")
    output_tail: str = Field(alias="outputTail")


class DiffStat(_Model):
    files: int
    insertions: int
    deletions: int


class UsageEvidence(_Model):
    input: int
    output: int


class TraceLink(_Model):
    """``session`` is the identifier ``docket task trace <ref>`` and the trace reader accept;
    ``project`` is the identifier ``GET /traces/<project>`` accepts. ``firstTs``/``lastTs`` are
    the second-resolution window of this hop's events within that session's file."""

    project: str
    session: str
    first_ts: str = Field(alias="firstTs")
    last_ts: str = Field(alias="lastTs")


class HopEvidence(_Model):
    role: str
    step_id: str = Field(alias="stepId")
    ok: bool
    verdict: str | None = None
    verify: VerifyEvidence | None = None
    commit: str | None = None
    base_commit: str | None = Field(None, alias="baseCommit")
    diff_stat: DiffStat | None = Field(None, alias="diffStat")
    usage: UsageEvidence | None = None
    trace: TraceLink | None = None


class TaskEvidence(_Model):
    """The shared shape; ``TaskEvidence11`` is the only published document and pins ``v``."""

    v: str
    pod: str
    task_id: str = Field(alias="taskId")
    status: str
    hops: list[HopEvidence]


class GateEvidence(_Model):
    """The label and raw exit of an external gate; no verdict about the work is added."""

    label: str
    exit_code: int = Field(alias="exitCode")
    reasons_invalid: bool = Field(alias="reasonsInvalid")


class DirectiveEvidence(_Model):
    path: str
    sha256: str


class HopEvidence11(HopEvidence):
    """``gate`` is absent, never ``null``, on a hop that ran no external gate."""

    gate: GateEvidence | None = None

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = cast("dict[str, Any]", handler(self))
        if self.gate is None:
            data.pop("gate", None)
        return data


class TaskEvidence11(TaskEvidence):
    """``directives`` is absent, never ``null``, when no hop composed a repository file."""

    v: Literal["1.1.0"] = EVIDENCE_V1_1
    hops: list[HopEvidence11]  # type: ignore[assignment]
    directives: list[DirectiveEvidence] | None = None

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = cast("dict[str, Any]", handler(self))
        if self.directives is None:
            data.pop("directives", None)
        return data


def _hop_evidence(hop: HopResult) -> HopEvidence:
    """One stored hop -> ``HopEvidence``. Every optional block degrades to ``None`` when absent or
    malformed, so a record written before these fields existed still builds."""
    verify: VerifyEvidence | None = None
    if hop.verify is not None:
        try:
            verify = VerifyEvidence.model_validate(
                {k: hop.verify[k] for k in ("cmd", "exitCode", "durationS", "outputTail")}
            )
        except (KeyError, ValueError):
            verify = None

    git = hop.evidence or {}
    diff_stat: DiffStat | None = None
    if git.get("diffStat") is not None:
        try:
            diff_stat = DiffStat.model_validate(git["diffStat"])
        except ValueError:
            diff_stat = None

    usage: UsageEvidence | None = None
    if hop.usage is not None:
        try:
            usage = UsageEvidence.model_validate(
                {key: hop.usage[key] for key in ("input", "output") if key in hop.usage}
            )
        except ValueError:
            usage = None

    trace: TraceLink | None = None
    if hop.trace is not None:
        try:
            trace = TraceLink.model_validate(hop.trace)
        except ValueError:
            trace = None

    commit, base_commit = git.get("commit"), git.get("baseCommit")
    return HopEvidence(
        role=hop.role,
        step_id=hop.step_id or hop.role,
        ok=hop.ok,
        verdict=hop.artifact.verdict if hop.artifact is not None else None,
        verify=verify,
        commit=commit if isinstance(commit, str) else None,
        base_commit=base_commit if isinstance(base_commit, str) else None,
        diff_stat=diff_stat,
        usage=usage,
        trace=trace,
    )


def _gate_evidence(hop: HopResult) -> GateEvidence | None:
    """The hop's external-gate block: only a ``verify`` that carries a ``label`` ran one."""
    verify = hop.verify
    if verify is None or not isinstance(verify.get("label"), str):
        return None
    try:
        return GateEvidence.model_validate(
            {
                "label": verify["label"],
                "exitCode": verify["exitCode"],
                "reasonsInvalid": bool(verify.get("reasonsInvalid", False)),
            }
        )
    except (KeyError, ValueError):
        return None


def _directives(hops: list[HopResult]) -> list[DirectiveEvidence]:
    """Distinct ``(path, sha256)`` pairs the hops recorded, in first-seen order."""
    seen: dict[tuple[str, str], None] = {}
    for hop in hops:
        for path, digest in hop.repo_files.items():
            seen.setdefault((path, digest))
    return [DirectiveEvidence(path=p, sha256=d) for p, d in seen]


def task_evidence(project: str, task_id: str, version: EvidenceVersion) -> TaskEvidence:
    """The one evidence builder: *task_id*'s record in pod *project* as the *version* document.
    Raises ``EvidenceNotFound`` for an unknown task and ``ValueError`` for an unknown version."""
    if version != EVIDENCE_V1_1:
        raise InvalidInput(f"unknown evidence version {version!r}")
    task = TaskRepository.for_pod(project).get(task_id)
    if task is not None:
        return TaskEvidence11(
            pod=project,
            task_id=task_id,
            status=task.status.value,
            hops=[
                HopEvidence11(**dict(_hop_evidence(hop)), gate=_gate_evidence(hop))
                for hop in task.hops
            ],
            directives=_directives(task.hops) or None,
        )
    raise EvidenceNotFound(f"no task {task_id!r} in pod {project!r}")
