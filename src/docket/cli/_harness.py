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
import shutil
import signal
import sys
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import docket.config as _cfg
from docket.cli import _harness_answers as _answers
from docket.cli import _harness_recipe as _recipe
from docket.core import harness
from docket.core import policy as _policy
from docket.core import runs as _runs
from docket.core import trace as _trace
from docket.core.operator_contract import QuestionV11
from docket.core.runtime_driver import (
    DOCKET_APPROVAL_MODE,
    DOCKET_TURN_TOKEN_BUDGET,
    TurnResult,
    UsageReport,
    UsageTotals,
)
from docket.edges import store as _store
from docket.edges.adapters import docket_runtime as _dr
from docket.edges.adapters import system as _system

_DEFAULT_TIMEOUT = 300
_DEFAULT_ROLE = "implementer"

# An opt-in v1.1 wire contract. "1.0" stays the default and is
# byte-identical to before this flag existed.
_CONTRACT_VERSIONS: dict[str, str] = {
    "1.0": harness.HARNESS_CONTRACT_VERSION,
    "1.1": harness.HARNESS_CONTRACT_V11,
}


def _flag(args: list[str], name: str) -> str | None:
    """Return the value after ``--name`` (or ``--name=value``), else None."""
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def _flags(args: list[str], name: str) -> list[str]:
    """Every value given to ``--name`` (or ``--name=value``), in order."""
    values: list[str] = []
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            values.append(args[i + 1])
        elif a.startswith(name + "="):
            values.append(a.split("=", 1)[1])
    return values


def _v11_usage_error(
    token_file_raw: str | None,
    max_tokens_raw: str | None,
    policy_raws: list[str],
    contract_raw: str,
) -> str | None:
    """Validate ``--token-file``, ``--max-tokens`` and ``--policy``; all need ``--contract 1.1``."""
    if token_file_raw is None and max_tokens_raw is None and not policy_raws:
        return None
    if contract_raw != "1.1":
        return "--token-file, --max-tokens and --policy need --contract 1.1"
    if max_tokens_raw is not None:
        try:
            if int(max_tokens_raw) <= 0:
                raise ValueError
        except ValueError:
            return f"--max-tokens must be a positive integer, got {max_tokens_raw!r}"
    if token_file_raw is not None and not Path(token_file_raw).expanduser().parent.is_dir():
        return f"--token-file directory does not exist: {token_file_raw!r}"
    names = [Path(p).name for p in policy_raws]
    if len(set(names)) != len(names):
        return "--policy file names must be unique; each is copied into the policies directory"
    return None


def _write_token_file(path: Path, token: str) -> None:
    """Write ``{"v", "token", "pid"}`` to *path* atomically, readable by its owner only."""
    body = json.dumps({"v": harness.HARNESS_CONTRACT_V11, "token": token, "pid": os.getpid()})
    staging = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(body)
    os.replace(staging, path)


def _task_text(task_text: str | None, task_file_raw: str | None) -> str:
    """The task message: the ``--task`` text, or the ``--task-file`` contents."""
    if task_file_raw is None:
        assert task_text is not None  # narrowed by _usage_error
        return task_text
    return Path(task_file_raw).expanduser().read_text(encoding="utf-8")


def _policy_problem(policy_paths: list[Path]) -> str | None:
    for policy_path in policy_paths:
        problem = _policy.validate_policy(policy_path)
        if problem:
            return f"invalid --policy: {problem}"
    return None


def _workspace_relative(root: Path, raw: str, base: Path) -> str | None:
    """*raw* as a POSIX path relative to *root* (the resolved workspace), or ``None`` when it
    names a place outside the workspace."""
    candidate = Path(raw) if Path(raw).is_absolute() else base / raw
    try:
        return candidate.resolve().relative_to(root).as_posix()
    except ValueError:
        return None


def _inside_workspace(
    workspace: Path, changes: Iterable[harness.FileChange]
) -> list[harness.FileChange]:
    root = workspace.resolve()
    inside: list[harness.FileChange] = []
    for change in changes:
        rel = _workspace_relative(root, change.path, workspace)
        if rel is not None:
            inside.append(harness.FileChange(path=rel, op=change.op))
    return inside


def _touched_files(
    workspace: Path,
    written: Iterable[harness.FileChange],
    baseline: dict[str, tuple[str, int, int]] | None = None,
    verify_touched: Iterable[str] = (),
) -> list[harness.FileChange]:
    """The run's write/edit calls plus ``git status`` paths, minus those unchanged since
    *baseline* or produced by a verify command; own calls are never dropped."""
    skip = set(verify_touched)
    base = baseline or {}
    git_changes = [
        harness.file_change_from_status(code, path)
        for path, (code, _size, _mtime) in _system.git_worktree_fingerprint(str(workspace)).items()
        if path not in skip and base.get(path) != (code, _size, _mtime)
    ]
    return harness.merge_file_changes(
        _inside_workspace(workspace, written), _inside_workspace(workspace, git_changes)
    )


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
        "                          [--contract 1.0|1.1]\n"
        "       docket harness status TOKEN",
        file=sys.stderr,
    )
    return 1


# ── run ───────────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


_PACK_KEYS = frozenset({"rationale", "options", "rationaleBlocked"})


def _event_line(
    contract_version: str, token: str, seq: int, record: dict[str, Any]
) -> harness.HarnessEvent | harness.HarnessEventV11:
    if contract_version == harness.HARNESS_CONTRACT_V11:
        return harness.HarnessEventV11(
            token=token, seq=seq, ts=str(record.get("ts", "")), event=record
        )
    if record.get("event_type") == "approval_requested" and isinstance(record.get("payload"), dict):
        # The approval pack is additive in 1.1; contract 1.0 is frozen, so its stream omits it.
        payload = {k: v for k, v in record["payload"].items() if k not in _PACK_KEYS}
        record = {**record, "payload": payload}
    return harness.HarnessEvent(token=token, seq=seq, ts=str(record.get("ts", "")), event=record)


def _final_result(
    contract_version: str,
    turn: TurnResult,
    usage_report: UsageReport,
    run_rec: dict[str, Any],
    *,
    files: list[harness.FileChange] | None = None,
    max_tokens: int | None = None,
    approvals: list[harness.ApprovalEntry] | None = None,
    question: QuestionV11 | None = None,
) -> harness.HarnessResult | harness.HarnessResultV11:
    if contract_version == harness.HARNESS_CONTRACT_V11:
        return harness.result_from_v11(
            turn,
            usage_report,
            run_rec,
            files=files or [],
            limits=harness.Limits(maxTokens=max_tokens),
            approvals=approvals or [],
            question=question,
        )
    return harness.result_from(turn, usage_report, run_rec)


# Paths that name this process's stdin. ``--answers stdin`` owns stdin, so a
# task read from any of them would race the answer reader for the same bytes.
_STDIN_TASK_FILES = ("-", "/dev/stdin", "/proc/self/fd/0")


def _answers_usage_error(
    answers_raw: str | None,
    answer_timeout_raw: str | None,
    task_file_raw: str | None,
    contract_raw: str,
) -> str | None:
    """Validate ``--answers`` and ``--answer-timeout``; both need ``--contract 1.1``."""
    if answers_raw is None and answer_timeout_raw is None:
        return None
    if contract_raw != "1.1":
        return "--answers and --answer-timeout need --contract 1.1"
    if answers_raw is None:
        return "--answer-timeout needs --answers stdin"
    if answers_raw != "stdin":
        return f"--answers must be 'stdin', got {answers_raw!r}"
    if task_file_raw in _STDIN_TASK_FILES:
        return "--answers stdin conflicts with --task-file reading stdin; pass --task instead"
    if answer_timeout_raw is not None:
        try:
            if int(answer_timeout_raw) <= 0:
                raise ValueError
        except ValueError:
            return f"--answer-timeout must be a positive integer, got {answer_timeout_raw!r}"
    return None


def _usage_error(
    workspace_raw: str | None,
    task_text: str | None,
    task_file_raw: str | None,
    model: str | None,
    timeout_raw: str | None,
    contract_raw: str = "1.0",
) -> str | None:
    if contract_raw not in _CONTRACT_VERSIONS:
        return f"--contract must be one of {sorted(_CONTRACT_VERSIONS)}, got {contract_raw!r}"
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


def _execute_turn(
    driver: _dr.DocketDriver,
    *,
    token: str,
    agent_id: str,
    role: str,
    session_key: str,
    task: str,
    timeout: int,
    env: dict[str, str],
    answers_raw: str | None,
    answer_timeout_raw: str | None,
    emit: Callable[[dict[str, Any]], None],
    written: harness.WrittenFiles,
    approvals: harness.ApprovalLedger,
) -> list[_RunOutcome]:
    """Run the turn with the stdout relay and the written-files and approvals trackers subscribed,
    bracketed by the session's start and end trace events."""
    with (
        _answers.guard(answers_raw, answer_timeout_raw, token, ledger=approvals),
        _trace.subscribe(emit),
        _trace.subscribe(written.observe),
        _trace.subscribe(approvals.observe),
    ):
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
    return results or []


def _finish(
    driver: _dr.DocketDriver,
    *,
    token: str,
    agent_id: str,
    workspace: Path,
    contract_version: str,
    results: list[_RunOutcome],
    written: harness.WrittenFiles,
    approvals: harness.ApprovalLedger,
    max_tokens: int | None,
    baseline: dict[str, tuple[str, int, int]] | None = None,
) -> int:
    """Print the one terminal result line and map its status to the exit code."""
    run_rec = _runs.get_run(token) or {}
    if results:
        turn = results[0].turn
    else:
        turn = TurnResult(
            False, "", 0.0, {}, str(run_rec.get("error", "")) or "harness run did not complete"
        )

    usage_report = driver.usage(agent_id)
    v11 = contract_version == harness.HARNESS_CONTRACT_V11
    files = _touched_files(workspace, written.changes, baseline) if v11 else None
    entries = approvals.finish(cancelled=turn.failure_kind == "run_cancelled") if v11 else None
    result = _final_result(
        contract_version,
        turn,
        usage_report,
        run_rec,
        files=files,
        max_tokens=max_tokens,
        approvals=entries,
        question=approvals.last_question,
    )
    print(result.model_dump_json())
    print(f"docket harness: run {token} finished status={result.status}", file=sys.stderr)

    if result.status == "ok":
        return 0
    if result.status == "refused":
        return 2
    return 1


def _run(args: list[str]) -> int:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]

    workspace_raw = _flag(args, "--workspace")
    task_text = _flag(args, "--task")
    task_file_raw = _flag(args, "--task-file")
    model = _flag(args, "--model")
    role = _flag(args, "--role") or _DEFAULT_ROLE
    timeout_raw = _flag(args, "--timeout")
    agent_id = _flag(args, "--agent-id") or f"harness-{uuid.uuid4().hex[:12]}"
    contract_raw = _flag(args, "--contract") or "1.0"
    answers_raw = _flag(args, "--answers")
    answer_timeout_raw = _flag(args, "--answer-timeout")
    token_file_raw = _flag(args, "--token-file")
    max_tokens_raw = _flag(args, "--max-tokens")
    policy_raws = _flags(args, "--policy")
    recipe_raw = _flag(args, "--recipe")

    problem = (
        _usage_error(workspace_raw, task_text, task_file_raw, model, timeout_raw, contract_raw)
        or _answers_usage_error(answers_raw, answer_timeout_raw, task_file_raw, contract_raw)
        or _v11_usage_error(token_file_raw, max_tokens_raw, policy_raws, contract_raw)
        or _recipe.usage_error(args, contract_raw)
    )
    if problem:
        # An invalid --contract itself has no known version to stamp; every
        # other usage error stamps whatever contract the caller did select.
        return _refuse(
            problem, _CONTRACT_VERSIONS.get(contract_raw, harness.HARNESS_CONTRACT_VERSION)
        )

    contract_version = _CONTRACT_VERSIONS[contract_raw]

    assert workspace_raw is not None and model is not None  # narrowed by _usage_error
    workspace = Path(workspace_raw).expanduser()
    home_default = Path.home() / ".docket"
    refusal = harness.preflight(os.environ, home_default, workspace)
    if refusal is not None:
        return _refuse(refusal.reason, contract_version)

    try:
        task = _task_text(task_text, task_file_raw)
    except OSError as exc:
        return _refuse(f"could not read --task-file {task_file_raw!r}: {exc}", contract_version)

    policy_paths = [Path(p).expanduser() for p in policy_raws]
    if policy_problem := _policy_problem(policy_paths):
        return _refuse(policy_problem, contract_version)

    timeout = int(timeout_raw) if timeout_raw is not None else _DEFAULT_TIMEOUT
    max_tokens = int(max_tokens_raw) if max_tokens_raw is not None else None

    try:
        meta = harness.agent_meta_for(agent_id, workspace, model, role)
    except ValueError as exc:
        return _refuse(str(exc), contract_version)

    session_key = f"agent:{agent_id}:default"
    _cfg.workspace_dir(agent_id).mkdir(parents=True, exist_ok=True)
    _store.write_json(_cfg.meta_path(agent_id), meta)

    for policy_path in policy_paths:
        _cfg.POLICIES_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(policy_path, _cfg.POLICIES_DIR / policy_path.name)

    run = _runs.create_run("cli", agent_id, variables={"model": model})
    token = str(run["id"])
    if token_file_raw is not None:
        try:
            _write_token_file(Path(token_file_raw).expanduser(), token)
        except OSError as exc:
            return _refuse(
                f"could not write --token-file {token_file_raw!r}: {exc}", contract_version
            )
    print(
        f"docket harness: run {token} agent={agent_id} model={model} role={role}", file=sys.stderr
    )

    seq = 0

    def _emit(record: dict[str, Any]) -> None:
        nonlocal seq
        print(_event_line(contract_version, token, seq, record).model_dump_json())
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

    if recipe_raw is not None:
        return _recipe.run_recipe(args, token=token, workspace=workspace, task=task, emit=_emit)

    def _handle_sigterm(signum: int, frame: object) -> None:
        _runs.cancel_run(token)

    old_handler = signal.signal(signal.SIGTERM, _handle_sigterm)
    driver = _dr.default_driver()
    # --answers stdin waits for the caller's answer line; otherwise nobody can answer.
    env = {DOCKET_APPROVAL_MODE: "wait" if answers_raw == "stdin" else "refuse"}
    if max_tokens is not None:
        env[DOCKET_TURN_TOKEN_BUDGET] = str(max_tokens)
    written = harness.WrittenFiles()
    approvals = harness.ApprovalLedger()
    baseline = _system.git_worktree_fingerprint(str(workspace))

    try:
        results = _execute_turn(
            driver,
            token=token,
            agent_id=agent_id,
            role=role,
            session_key=session_key,
            task=task,
            timeout=timeout,
            env=env,
            answers_raw=answers_raw,
            answer_timeout_raw=answer_timeout_raw,
            emit=_emit,
            written=written,
            approvals=approvals,
        )
    finally:
        signal.signal(signal.SIGTERM, old_handler)

    return _finish(
        driver,
        token=token,
        agent_id=agent_id,
        workspace=workspace,
        contract_version=contract_version,
        results=results,
        written=written,
        approvals=approvals,
        max_tokens=max_tokens,
        baseline=baseline,
    )


def _refuse(reason: str, version: str = harness.HARNESS_CONTRACT_VERSION) -> int:
    print(harness.refusal_result(reason, version=version).model_dump_json())
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
