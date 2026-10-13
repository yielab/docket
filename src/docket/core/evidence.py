"""evidence: what a finished task's hops kept, as one published model (1.0.0 and 1.1.0).

``task_evidence`` is the one builder. It reads the persisted task record and projects each hop
through these models; later surfaces (CLI, HTTP, harness) serve the result and never assemble it
themselves. Everything here is measured or recorded: tokens are the endpoint's counts, never an
estimate or a dollar figure, and the model carries no score or verdict about the evidence.
The internal ``verify["touched"]`` key never crosses into this contract.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer

from docket.core import dispatch as _dispatch

EVIDENCE_V1 = "1.0.0"
EVIDENCE_V1_1 = "1.1.0"
EvidenceVersion = Literal["1.0.0", "1.1.0"]


class EvidenceNotFound(LookupError):
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
    v: Literal["1.0.0"] = EVIDENCE_V1  # type: ignore[assignment]
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

    v: Literal["1.1.0"] = EVIDENCE_V1_1  # type: ignore[assignment]
    hops: list[HopEvidence11]  # type: ignore[assignment]
    directives: list[DirectiveEvidence] | None = None

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = cast("dict[str, Any]", handler(self))
        if self.directives is None:
            data.pop("directives", None)
        return data


def _as_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _hop_evidence(rec: dict[str, Any]) -> HopEvidence:
    """One persisted hop record -> ``HopEvidence``. Every optional block degrades to ``None`` when
    absent or malformed, so a record written before these fields existed still builds."""
    verify_raw = _as_dict(rec.get("verify"))
    verify: VerifyEvidence | None = None
    if verify_raw is not None:
        try:
            verify = VerifyEvidence.model_validate(
                {k: verify_raw[k] for k in ("cmd", "exitCode", "durationS", "outputTail")}
            )
        except (KeyError, ValueError):
            verify = None

    git = _as_dict(rec.get("evidence")) or {}
    diff_stat: DiffStat | None = None
    stat_raw = _as_dict(git.get("diffStat"))
    if stat_raw is not None:
        try:
            diff_stat = DiffStat.model_validate(stat_raw)
        except ValueError:
            diff_stat = None

    usage: UsageEvidence | None = None
    usage_raw = _as_dict(rec.get("usage"))
    if usage_raw is not None:
        try:
            usage = UsageEvidence.model_validate(usage_raw)
        except ValueError:
            usage = None

    trace: TraceLink | None = None
    trace_raw = _as_dict(rec.get("trace"))
    if trace_raw is not None:
        try:
            trace = TraceLink.model_validate(trace_raw)
        except ValueError:
            trace = None

    artifact = _as_dict(rec.get("artifact")) or {}
    verdict = artifact.get("verdict")
    role = str(rec.get("role", ""))
    commit, base_commit = git.get("commit"), git.get("baseCommit")
    return HopEvidence(
        role=role,
        step_id=str(rec.get("stepId", "") or role),
        ok=bool(rec.get("ok", False)),
        verdict=verdict if isinstance(verdict, str) else None,
        verify=verify,
        commit=commit if isinstance(commit, str) else None,
        base_commit=base_commit if isinstance(base_commit, str) else None,
        diff_stat=diff_stat,
        usage=usage,
        trace=trace,
    )


def _gate_evidence(rec: dict[str, Any]) -> GateEvidence | None:
    """The hop's external-gate block: only a ``verify`` that carries a ``label`` ran one."""
    verify = _as_dict(rec.get("verify"))
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


def _directives(records: list[dict[str, Any]]) -> list[DirectiveEvidence]:
    """Distinct ``(path, sha256)`` pairs the hops recorded, in first-seen order."""
    seen: dict[tuple[str, str], None] = {}
    for rec in records:
        files = _as_dict(rec.get("repoFiles")) or {}
        for path, digest in files.items():
            if isinstance(path, str) and isinstance(digest, str):
                seen.setdefault((path, digest))
    return [DirectiveEvidence(path=p, sha256=d) for p, d in seen]


def task_evidence(project: str, task_id: str, version: EvidenceVersion) -> TaskEvidence:
    """The one evidence builder: *task_id*'s record in pod *project* as the *version* document
    (``"1.0.0"`` never carries the 1.1.0 fields). Raises ``EvidenceNotFound`` for an unknown
    task and ``ValueError`` for an unknown version."""
    if version not in (EVIDENCE_V1, EVIDENCE_V1_1):
        raise ValueError(f"unknown evidence version {version!r}")
    for task in _dispatch.read_tasks(project):
        if task.get("id") == task_id:
            records = [h for h in task.get("hops", []) if isinstance(h, dict)]
            hops = [_hop_evidence(h) for h in records]
            status = str(task.get("status", ""))
            if version == EVIDENCE_V1:
                return TaskEvidence(pod=project, task_id=task_id, status=status, hops=hops)
            return TaskEvidence11(
                pod=project,
                task_id=task_id,
                status=status,
                hops=[
                    HopEvidence11(**dict(hop), gate=_gate_evidence(rec))
                    for hop, rec in zip(hops, records, strict=True)
                ],
                directives=_directives(records) or None,
            )
    raise EvidenceNotFound(f"no task {task_id!r} in pod {project!r}")
