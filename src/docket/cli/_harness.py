"""``docket harness`` -- run one agent, one turn loop, to completion, for a
caller that owns the workspace and the ``DOCKET_HOME``. See
``docs/adr/0001-harness-mode.md`` and ``specs/api/harness-mode.spec.md``.

stdout is a wire protocol: newline-delimited JSON (``core.harness``'s
``HarnessEvent`` lines, then exactly one ``HarnessResult`` line) and nothing
else. Every human-facing word goes to stderr. ``ui.info``/``ui.success``/
``ui.warn`` write to stdout and are forbidden in this module -- a stray
``print`` here corrupts the stream an external consumer parses.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import signal
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import docket.config as _cfg
from docket.core import harness
from docket.core import runs as _runs
from docket.core import trace as _trace
from docket.core.runtime_driver import DOCKET_APPROVAL_MODE, TurnResult, UsageReport, UsageTotals
from docket.edges import store as _store
from docket.edges.adapters import docket_runtime as _dr

_DEFAULT_TIMEOUT = 300
_DEFAULT_ROLE = "implementer"


def _flag(args: list[str], name: str) -> str | None:
    """Return the value after ``--name`` (or ``--name=value``), else None."""
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def run_harness(sub: str | None, args: list[str]) -> int:
    """Dispatch ``docket harness <sub> ...``. Returns a process exit code."""
    sub = (sub or "").lower()
    if sub == "run":
        return _run(args)
    if sub == "status":
        return _status(args)
    print(
        "usage: docket harness run --workspace DIR (--task TEXT | --task-file PATH) "
        "--model PROVIDER/ID [--role implementer] [--timeout S] [--agent-id ID]\n"
        "       docket harness status TOKEN",
        file=sys.stderr,
    )
    return 1


# ── run ───────────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _usage_error(
    workspace_raw: str | None,
    task_text: str | None,
    task_file_raw: str | None,
    model: str | None,
    timeout_raw: str | None,
) -> str | None:
    if not workspace_raw:
        return "--workspace is required"
    if bool(task_text) == bool(task_file_raw):
        if not task_text and not task_file_raw:
            return "one of --task or --task-file is required"
        return "--task and --task-file are mutually exclusive"
    if not model:
        return "--model is required"
    if timeout_raw is not None:
        try:
            int(timeout_raw)
        except ValueError:
            return f"--timeout must be an integer, got {timeout_raw!r}"
    return None


# The task_id/status shape core.runs.execute() duck-types against, carrying
# the real TurnResult alongside for result_from(). Mirrors the wrapper
# tests/integration/test_cooperative_run_cancellation.py already proves
# against the same driver call -- a second, real caller of the same pattern.
@dataclass
class _RunOutcome:
    """execute()'s duck-typed shape -- see the comment above."""

    task_id: str
    status: str  # "done" | "failed" | "cancelled" -- only the latter two matter to execute()
    reason: str
    turn: TurnResult


def _run(args: list[str]) -> int:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]

    workspace_raw = _flag(args, "--workspace")
    task_text = _flag(args, "--task")
    task_file_raw = _flag(args, "--task-file")
    model = _flag(args, "--model")
    role = _flag(args, "--role") or _DEFAULT_ROLE
    timeout_raw = _flag(args, "--timeout")
    agent_id = _flag(args, "--agent-id") or f"harness-{uuid.uuid4().hex[:12]}"

    problem = _usage_error(workspace_raw, task_text, task_file_raw, model, timeout_raw)
    if problem:
        return _refuse(problem)

    assert workspace_raw is not None and model is not None  # narrowed by _usage_error
    workspace = Path(workspace_raw).expanduser()
    home_default = Path.home() / ".docket"
    refusal = harness.preflight(os.environ, home_default, workspace)
    if refusal is not None:
        return _refuse(refusal.reason)

    if task_file_raw is not None:
        try:
            task = Path(task_file_raw).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            return _refuse(f"could not read --task-file {task_file_raw!r}: {exc}")
    else:
        assert task_text is not None
        task = task_text

    timeout = int(timeout_raw) if timeout_raw is not None else _DEFAULT_TIMEOUT

    try:
        meta = harness.agent_meta_for(agent_id, workspace, model, role)
    except ValueError as exc:
        return _refuse(str(exc))

    session_key = f"agent:{agent_id}:default"
    _cfg.workspace_dir(agent_id).mkdir(parents=True, exist_ok=True)
    _store.write_json(_cfg.meta_path(agent_id), meta)

    run = _runs.create_run("cli", agent_id, variables={"model": model})
    token = str(run["id"])
    print(
        f"docket harness: run {token} agent={agent_id} model={model} role={role}", file=sys.stderr
    )

    seq = 0

    def _emit(record: dict[str, Any]) -> None:
        nonlocal seq
        line = harness.HarnessEvent(
            token=token, seq=seq, ts=str(record.get("ts", "")), event=record
        )
        print(line.model_dump_json())
        seq += 1

    _emit(
        {
            "ts": _now_iso(),
            "project": agent_id,
            "session_id": session_key,
            "agent_role": role,
            "event_type": "harness_start",
            "payload": {
                "token": token,
                "pid": os.getpid(),
                "model": model,
                "workspace": str(workspace),
            },
        }
    )

    def _handle_sigterm(signum: int, frame: object) -> None:
        _runs.cancel_run(token)

    old_handler = signal.signal(signal.SIGTERM, _handle_sigterm)
    driver = _dr.default_driver()
    env = {DOCKET_APPROVAL_MODE: "refuse"}

    try:
        with _trace.subscribe(_emit):
            _trace.trace_event(
                agent_id, session_key, role, "session_start", json.dumps({"source": "harness"})
            )

            def _invoke() -> list[_RunOutcome]:
                turn = driver.run_turn(
                    agent_id,
                    session_key,
                    task,
                    timeout,
                    env,
                    trace_project=agent_id,
                )
                if turn.failure_kind == "run_cancelled":
                    status = "cancelled"
                elif not turn.ok:
                    status = "failed"
                else:
                    status = "done"
                return [_RunOutcome(token, status, turn.error, turn)]

            results = _runs.execute(token, _invoke)

            final_status = results[0].status if results else "failed"
            _trace.trace_event(
                agent_id,
                session_key,
                role,
                "session_end",
                json.dumps({"status": final_status}),
            )
    finally:
        signal.signal(signal.SIGTERM, old_handler)

    run_rec = _runs.get_run(token) or {}
    if results:
        turn = results[0].turn
    else:
        turn = TurnResult(
            False, "", 0.0, {}, str(run_rec.get("error", "")) or "harness run did not complete"
        )

    usage_report = driver.usage(agent_id)
    result = harness.result_from(turn, usage_report, run_rec)
    print(result.model_dump_json())
    print(f"docket harness: run {token} finished status={result.status}", file=sys.stderr)

    if result.status == "ok":
        return 0
    if result.status == "refused":
        return 2
    return 1


def _refuse(reason: str) -> int:
    print(harness.refusal_result(reason).model_dump_json())
    return 2


# ── status ────────────────────────────────────────────────────────────────────


# Real token counts are recoverable here (the durable session is still on
# disk); model.served and any blocked rule detail are not -- those lived
# only in the ephemeral TurnResult the original run invocation held, and
# nothing persists them. Honest gap, not a bug.
def _terminal_result_from_run(run: dict[str, Any]) -> harness.HarnessResult:
    """Best-effort reconstruction of a terminal result from a run record."""
    state = str(run.get("state", ""))
    status_map: dict[str, harness.HarnessResultStatus] = {
        "succeeded": "ok",
        "failed": "failed",
        "cancelled": "cancelled",
    }
    status: harness.HarnessResultStatus = status_map.get(state, "failed")
    variables = run.get("variables") or {}
    project = str(run.get("project", ""))
    usage_report: UsageReport = (
        _dr.default_driver().usage(project) if project else UsageReport(totals=UsageTotals())
    )
    totals = usage_report.totals
    return harness.HarnessResult(
        token=str(run.get("id", "")),
        status=status,
        error=str(run.get("error", "")),
        model=harness.ModelInfo(requested=str(variables.get("model", ""))),
        usage=harness.UsageInfo(
            input_tokens=totals.input_tokens,
            output_tokens=totals.output_tokens,
            cached_tokens=totals.cache_read,
            turns=totals.turns,
        ),
        run_state=state,
    )


def _status(args: list[str]) -> int:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    if not args:
        print("usage: docket harness status TOKEN", file=sys.stderr)
        return 1

    token = args[0]
    run = _runs.get_run(token)
    if run is None:
        print(
            json.dumps({"v": harness.HARNESS_CONTRACT_VERSION, "token": token, "state": "unknown"})
        )
        return 0

    state = str(run.get("state", ""))
    if state in ("succeeded", "failed", "cancelled"):
        result = _terminal_result_from_run(run)
        print(
            json.dumps(
                {
                    "v": harness.HARNESS_CONTRACT_VERSION,
                    "token": token,
                    "state": "finished",
                    "result": json.loads(result.model_dump_json()),
                }
            )
        )
    else:
        print(json.dumps({"v": harness.HARNESS_CONTRACT_VERSION, "token": token, "state": "live"}))
    return 0
