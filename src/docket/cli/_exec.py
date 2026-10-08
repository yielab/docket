"""``docket exec`` -- run one agent, one turn loop, to completion, for a
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import typer

import docket.config as _cfg
from docket.cli import _harness_answers as _answers
from docket.cli import _harness_recipe as _recipe
from docket.core import harness
from docket.core import policy as _policy
from docket.core import runs as _runs
from docket.core import trace as _trace
from docket.core.dispatch import DispatchError
from docket.core.operator_contract import QuestionV11
from docket.core.runtime_driver import (
    DOCKET_APPROVAL_MODE,
    DOCKET_TASK_ID,
    DOCKET_TURN_TOKEN_BUDGET,
    TurnResult,
    UsageReport,
)
from docket.edges import store as _store
from docket.edges.adapters import docket_runtime as _dr
from docket.edges.adapters import system as _system


@dataclass
class ExecOptions:
    """The raw values of ``docket exec``'s options; validated by the usage checks, not by Typer."""

    workspace: str | None = None
    task: str | None = None
    task_file: str | None = None
    model: str | None = None
    role: str | None = None
    timeout: str | None = None
    agent_id: str | None = None
    contract: str = "1.0"
    answers: str | None = None
    answer_timeout: str | None = None
    token_file: str | None = None
    max_tokens: str | None = None
    policy: list[str] = field(default_factory=list)
    recipe: str | None = None
    verify: str | None = None


_DEFAULT_TIMEOUT = 300
_DEFAULT_ROLE = "implementer"

# An opt-in v1.1 wire contract. "1.0" stays the default and is
# byte-identical to before this flag existed.
_CONTRACT_VERSIONS: dict[str, str] = {
    "1.0": harness.HARNESS_CONTRACT_VERSION,
    "1.1": harness.HARNESS_CONTRACT_V11,
}


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
            try:
                turn = driver.run_turn(
                    agent_id,
                    session_key,
                    task,
                    timeout,
                    env,
                    trace_project=agent_id,
                )
            except DispatchError as exc:
                turn = TurnResult(False, "", 0.0, {}, str(exc), failure_kind="daemon_error")
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
            False, "", 0.0, {}, str(run_rec.get("error", "")) or "exec did not complete"
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
    print(f"docket exec: run {token} finished status={result.status}", file=sys.stderr)

    if result.status == "ok":
        return 0
    if result.status == "refused":
        return 2
    return 1


def run_exec(opts: ExecOptions) -> int:
    """Run one agent turn (or one recipe task) for *opts* and return the process exit code."""
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]

    workspace_raw = opts.workspace
    task_text = opts.task
    task_file_raw = opts.task_file
    model = opts.model
    role = opts.role or _DEFAULT_ROLE
    timeout_raw = opts.timeout
    agent_id = opts.agent_id or f"harness-{uuid.uuid4().hex[:12]}"
    contract_raw = opts.contract
    answers_raw = opts.answers
    answer_timeout_raw = opts.answer_timeout
    token_file_raw = opts.token_file
    max_tokens_raw = opts.max_tokens
    policy_raws = opts.policy
    recipe_raw = opts.recipe

    problem = (
        _usage_error(workspace_raw, task_text, task_file_raw, model, timeout_raw, contract_raw)
        or _answers_usage_error(answers_raw, answer_timeout_raw, task_file_raw, contract_raw)
        or _v11_usage_error(token_file_raw, max_tokens_raw, policy_raws, contract_raw)
        or _recipe.usage_error(opts)
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
    print(f"docket exec: run {token} agent={agent_id} model={model} role={role}", file=sys.stderr)

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
        return _recipe.run_recipe(opts, token=token, workspace=workspace, task=task, emit=_emit)

    def _handle_sigterm(signum: int, frame: object) -> None:
        _runs.cancel_run(token)

    old_handler = signal.signal(signal.SIGTERM, _handle_sigterm)
    driver = _dr.default_driver()
    # --answers stdin waits for the caller's answer line; otherwise nobody can answer.
    env = {DOCKET_APPROVAL_MODE: "wait" if answers_raw == "stdin" else "refuse"}
    env[DOCKET_TASK_ID] = token
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


def cmd_exec(
    workspace: str | None = typer.Option(
        None, "--workspace", help="Directory the agent works in (must exist)"
    ),
    task: str | None = typer.Option(None, "--task", help="The task text"),
    task_file: str | None = typer.Option(
        None, "--task-file", help="Read the task text from a file"
    ),
    model: str | None = typer.Option(None, "--model", help="PROVIDER/ID of the model to use"),
    role: str | None = typer.Option(None, "--role", help="Role to run as (default implementer)"),
    timeout: str | None = typer.Option(None, "--timeout", help="Wall-clock limit in seconds"),
    agent_id: str | None = typer.Option(
        None, "--agent-id", help="Name the agent instead of a random one"
    ),
    contract: str = typer.Option("1.0", "--contract", help="Wire contract version: 1.0 or 1.1"),
    answers: str | None = typer.Option(
        None, "--answers", help="'stdin': read answer lines from stdin (needs --contract 1.1)"
    ),
    answer_timeout: str | None = typer.Option(
        None, "--answer-timeout", help="Seconds to wait for an answer line (needs --answers stdin)"
    ),
    token_file: str | None = typer.Option(
        None, "--token-file", help="Write the run token and pid to this file (needs --contract 1.1)"
    ),
    max_tokens: str | None = typer.Option(
        None, "--max-tokens", help="Token budget for the turn (needs --contract 1.1)"
    ),
    policy: list[str] | None = typer.Option(
        None,
        "--policy",
        help="Policy file to install for the run, repeatable (needs --contract 1.1)",
    ),
    recipe: str | None = typer.Option(
        None,
        "--recipe",
        help="Run a recipe name or directory instead of one agent (needs --contract 1.1)",
    ),
    verify: str | None = typer.Option(None, "--verify", help="Verify command for a --recipe run"),
) -> None:
    """Run one agent for one task in a workspace you own, for programs.

    Streams newline-delimited JSON events on stdout and ends with exactly one
    versioned result line; every log goes to stderr. Needs DOCKET_HOME set to a
    caller-owned directory and DOCKET_LLM_BASE_URL set. A tool call that would need
    a human is denied at once. SIGTERM cancels the run. Exit 0 the result is ok,
    1 it failed, was blocked or cancelled, 2 refused before any run started.

    Example: docket exec --workspace . --task "fix the failing test" --model local/qwen
    """
    opts = ExecOptions(
        workspace=workspace,
        task=task,
        task_file=task_file,
        model=model,
        role=role,
        timeout=timeout,
        agent_id=agent_id,
        contract=contract,
        answers=answers,
        answer_timeout=answer_timeout,
        token_file=token_file,
        max_tokens=max_tokens,
        policy=list(policy or []),
        recipe=recipe,
        verify=verify,
    )
    raise typer.Exit(run_exec(opts))
