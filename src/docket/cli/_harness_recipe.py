"""``docket harness run --recipe NAME|DIR`` -- one recipe, one task, run in place (contract 1.1).

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

from docket.cli import _harness as _h
from docket.cli import _harness_answers as _answers
from docket.core import harness
from docket.core import harness_pipeline as _pipeline
from docket.core import pod_apply as _pod_apply
from docket.core import pod_provisioning as _pp
from docket.core import runs as _runs
from docket.core import trace as _trace
from docket.core.runtime_driver import TurnResult, UsageReport, UsageTotals
from docket.edges.adapters import docket_runtime as _dr

_QuestionQueue = queue.Queue[harness.AnswerLine | None]


def usage_error(args: list[str], contract_raw: str) -> str | None:
    """The argument refusals for ``--recipe`` and the flags that only make sense with it."""
    recipe = _h._flag(args, "--recipe")
    if recipe is None:
        return "--verify needs --recipe" if _h._flag(args, "--verify") is not None else None
    if contract_raw != "1.1":
        return "--recipe needs --contract 1.1"
    if _h._flag(args, "--role") is not None:
        return "--recipe and --role are mutually exclusive; the recipe chooses the roles"
    if _h._flag(args, "--max-tokens") is not None:
        return "--max-tokens does not apply to --recipe runs"
    if _h._flag(args, "--agent-id") is not None:
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
                "docket harness: answer line ignored: not the open question",
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


def _hop_view(hop: dict[str, Any]) -> dict[str, Any]:
    artifact = hop.get("artifact") or {}
    return {
        "role": hop.get("role", ""),
        "stepId": hop.get("stepId", hop.get("role", "")),
        "ok": hop.get("ok", False),
        "verdict": artifact.get("verdict") if isinstance(artifact, dict) else None,
        "verify": hop.get("verify"),
        "evidence": hop.get("evidence"),
    }


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
    run: _pipeline.RecipeRun | None,
    error: str,
) -> int:
    record = run.task if run is not None else {}
    hops = run.hops if run is not None else []
    status, blocked, reason = _task_status(record, hops, error)
    turn = TurnResult(status == "ok", "", 0.0, {}, "" if status == "ok" else reason)
    usage = _pod_usage(run.project) if run is not None else UsageReport(totals=UsageTotals())
    task = harness.HarnessTask(
        status=str(record.get("status", "")),
        hops=[_hop_view(h) for h in hops],
        brief=record.get("brief"),
    )
    result = harness.result_from_v11(
        turn,
        usage,
        _runs.get_run(token) or {},
        files=_h._touched_files(workspace, written.changes),
        task=task,
        limits=harness.Limits(),
    ).model_copy(update={"status": status, "error": reason, "blocked": blocked})
    print(result.model_dump_json())
    print(f"docket harness: run {token} finished status={status}", file=sys.stderr)
    return 0 if status == "ok" else 1


def run_recipe(
    args: list[str],
    *,
    token: str,
    workspace: Path,
    task: str,
    emit: Callable[[dict[str, Any]], None],
) -> int:
    """Run the ``--recipe`` named in *args* in place for *task* under *token*; print the one
    terminal result."""
    recipe = _h._flag(args, "--recipe") or ""
    model = _h._flag(args, "--model") or ""
    timeout_raw = _h._flag(args, "--timeout")
    timeout = int(timeout_raw) if timeout_raw is not None else _h._DEFAULT_TIMEOUT
    verify_cmd = _h._flag(args, "--verify") or ""
    answers_raw = _h._flag(args, "--answers")
    answer_timeout_raw = _h._flag(args, "--answer-timeout")
    questions: _QuestionQueue = queue.Queue()
    stdin_answers = answers_raw == "stdin"
    answer_timeout = int(answer_timeout_raw) if answer_timeout_raw is not None else None
    written = harness.WrittenFiles()
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
            _answers.guard(answers_raw, answer_timeout_raw, token, questions),
            _trace.subscribe(emit),
            _trace.subscribe(written.observe),
        ):
            _runs.execute(token, _invoke)
    finally:
        signal.signal(signal.SIGTERM, old_handler)

    return _finish(token, workspace, written, box[0] if box else None, error)
