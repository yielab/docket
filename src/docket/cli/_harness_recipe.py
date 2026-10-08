"""``docket exec --recipe NAME|DIR`` -- one recipe, one task, run in place (contract 1.1).

The recipe runs in an ephemeral pod whose Implementer works in the caller's workspace (see
``core.harness_pipeline``). Events stream through the same trace relay as a single-agent run;
the terminal result carries the task's hops in ``task``. ``--answers stdin`` lets a caller
answer an operator question the task parks on, and makes approvals wait instead of refusing.
"""

from __future__ import annotations

import queue
import signal
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from docket.cli import _exec as _h
from docket.cli import _harness_answers as _answers
from docket.core import evidence as _evidence
from docket.core import harness
from docket.core import harness_pipeline as _pipeline
from docket.core import pod_apply as _pod_apply
from docket.core import pod_provisioning as _pp
from docket.core import runs as _runs
from docket.core import trace as _trace
from docket.core.runtime_driver import TurnResult, UsageReport, UsageTotals
from docket.edges.adapters import docket_runtime as _dr
from docket.edges.adapters import system as _system

_QuestionQueue = queue.Queue[harness.AnswerLine | None]


def usage_error(opts: _h.ExecOptions) -> str | None:
    """The argument refusals for ``--recipe`` and the flags that only make sense with it."""
    recipe = opts.recipe
    if recipe is None:
        return "--verify needs --recipe" if opts.verify is not None else None
    if opts.contract != "1.1":
        return "--recipe needs --contract 1.1"
    if opts.role is not None:
        return "--recipe and --role are mutually exclusive; the recipe chooses the roles"
    if opts.max_tokens is not None:
        return "--max-tokens does not apply to --recipe runs"
    if opts.agent_id is not None:
        return "--agent-id does not apply to --recipe runs"
    try:
        _pod_apply.resolve_recipe(recipe)
    except _pod_apply.PodApplyError as exc:
        return f"unknown recipe {recipe!r}: {exc}"
    return None


def _answer_source(
    questions: _QuestionQueue, timeout: int | None
) -> Callable[[dict[str, Any]], harness.Answer | None]:
    """The answer for the open question, read from *questions*; ``None`` at EOF or timeout."""

    def _next(question: dict[str, Any]) -> harness.Answer | None:
        while True:
            try:
                line = questions.get(timeout=timeout)
            except queue.Empty:
                return None
            if line is None:
                return None
            if line.answer.questionId == question.get("id"):
                return line.answer
            print(
                "docket exec: answer line ignored: not the open question",
                file=sys.stderr,
                flush=True,
            )

    return _next


def _pod_usage(project: str) -> UsageReport:
    """Measured usage summed over every member of the ephemeral pod."""
    driver = _dr.default_driver()
    totals = UsageTotals()
    for member_id in _pp.pod_member_ids(project):
        member = driver.usage(member_id).totals
        totals.input_tokens += member.input_tokens
        totals.output_tokens += member.output_tokens
        totals.cache_read += member.cache_read
        totals.turns += member.turns
    return UsageReport(totals=totals)


def _published_verify(verify: Any) -> Any:
    """A hop's verify evidence without the internal ``touched`` key."""
    if isinstance(verify, dict):
        return {k: v for k, v in verify.items() if k != "touched"}
    return verify


def _verify_touched(hops: list[dict[str, Any]]) -> list[str]:
    """Absolute paths any hop's verify command created or changed."""
    found: list[str] = []
    for hop in hops:
        verify = hop.get("verify")
        if isinstance(verify, dict):
            found.extend(str(p) for p in verify.get("touched") or [])
    return found


def _hop_view(hop: dict[str, Any]) -> dict[str, Any]:
    artifact = hop.get("artifact") or {}
    return {
        "role": hop.get("role", ""),
        "stepId": hop.get("stepId", hop.get("role", "")),
        "ok": hop.get("ok", False),
        "verdict": artifact.get("verdict") if isinstance(artifact, dict) else None,
        "verify": _published_verify(hop.get("verify")),
        "evidence": hop.get("evidence"),
    }


def _task_evidence(run: _pipeline.RecipeRun | None) -> dict[str, Any] | None:
    """The run's evidence-v1 document, built by ``core.evidence`` (None when no task ran)."""
    task_id = run.task.get("id") if run is not None else None
    if run is None or not task_id:
        return None
    try:
        return _evidence.task_evidence(run.project, str(task_id)).model_dump(
            by_alias=True, mode="json"
        )
    except _evidence.EvidenceNotFound:
        return None


def _task_status(
    record: dict[str, Any], hops: list[dict[str, Any]], error: str
) -> tuple[harness.HarnessResultStatus, harness.BlockedInfo | None, str]:
    """The result status, blocked detail and reason for one recipe task's final record."""
    state = str(record.get("status", ""))
    if state == "done":
        return "ok", None, ""
    reason = str(record.get("reason", "")) or error
    refused = next(
        (str(h.get("error", "")) for h in hops if "approval_unavailable" in str(h.get("error"))),
        "",
    )
    if refused:
        return "blocked", harness.blocked_info(refused), reason
    if state in ("waiting_input", "waiting_approval", "blocked"):
        return "blocked", None, reason
    if state == "cancelled":
        return "cancelled", None, reason
    return "failed", None, reason


def _finish(
    token: str,
    workspace: Path,
    written: harness.WrittenFiles,
    approvals: harness.ApprovalLedger,
    run: _pipeline.RecipeRun | None,
    error: str,
    baseline: dict[str, tuple[str, int, int]] | None = None,
) -> int:
    record = run.task if run is not None else {}
    hops = run.hops if run is not None else []
    status, blocked, reason = _task_status(record, hops, error)
    turn = TurnResult(status == "ok", "", 0.0, {}, "" if status == "ok" else reason)
    usage = _pod_usage(run.project) if run is not None else UsageReport(totals=UsageTotals())
    task = harness.HarnessTask(
        status=str(record.get("status", "")),
        hops=[_hop_view(h) for h in hops],
        evidence=_task_evidence(run),
        brief=record.get("brief"),
    )
    result = harness.result_from_v11(
        turn,
        usage,
        _runs.get_run(token) or {},
        files=_h._touched_files(workspace, written.changes, baseline, _verify_touched(hops)),
        task=task,
        limits=harness.Limits(),
        approvals=approvals.finish(cancelled=status == "cancelled"),
    ).model_copy(update={"status": status, "error": reason, "blocked": blocked})
    print(result.model_dump_json())
    print(f"docket exec: run {token} finished status={status}", file=sys.stderr)
    return 0 if status == "ok" else 1


def run_recipe(
    opts: _h.ExecOptions,
    *,
    token: str,
    workspace: Path,
    task: str,
    emit: Callable[[dict[str, Any]], None],
) -> int:
    """Run the ``--recipe`` named in *opts* in place for *task* under *token*; print the one
    terminal result."""
    recipe = opts.recipe or ""
    model = opts.model or ""
    timeout_raw = opts.timeout
    timeout = int(timeout_raw) if timeout_raw is not None else _h._DEFAULT_TIMEOUT
    verify_cmd = opts.verify or ""
    answers_raw = opts.answers
    answer_timeout_raw = opts.answer_timeout
    questions: _QuestionQueue = queue.Queue()
    stdin_answers = answers_raw == "stdin"
    answer_timeout = int(answer_timeout_raw) if answer_timeout_raw is not None else None
    baseline = _system.git_worktree_fingerprint(str(workspace))
    written = harness.WrittenFiles()
    approvals = harness.ApprovalLedger()
    box: list[_pipeline.RecipeRun] = []
    error = ""

    def _invoke() -> list[Any]:
        nonlocal error
        try:
            run = _pipeline.run_recipe_task(
                workspace,
                recipe,
                task,
                model=model,
                approval_mode="wait" if stdin_answers else "refuse",
                timeout=timeout,
                verify_cmd=verify_cmd,
                next_answer=_answer_source(questions, answer_timeout) if stdin_answers else None,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            status = "failed"
            return [_h._RunOutcome(token, status, error, TurnResult(False, "", 0.0, {}, error))]
        box.append(run)
        status = "done" if run.task.get("status") == "done" else "failed"
        return [_h._RunOutcome(token, status, "", TurnResult(status == "done", "", 0.0, {}))]

    def _handle_sigterm(signum: int, frame: object) -> None:
        _runs.cancel_run(token)

    old_handler = signal.signal(signal.SIGTERM, _handle_sigterm)
    try:
        with (
            _answers.guard(answers_raw, answer_timeout_raw, token, questions, approvals),
            _trace.subscribe(emit),
            _trace.subscribe(written.observe),
            _trace.subscribe(approvals.observe),
        ):
            _runs.execute(token, _invoke)
    finally:
        signal.signal(signal.SIGTERM, old_handler)

    return _finish(token, workspace, written, approvals, box[0] if box else None, error, baseline)
