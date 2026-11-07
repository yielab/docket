"""A real failed task of a docket home, made a candidate task a person can finish.

`promote` reads the home read-only (pods through the CLI, the stored task through the queue file)
and writes `<out>/<cand-id>/`: a `task.yaml` whose `origin` names the task and its failure kind,
the instruction, a `repo/` seed taken from the task's base commit when the pod's codebase still has
it, an empty `hidden/` holding one TODO check that fails, no `solution/`, and `candidate.md` with
the pointer to the trace. Its suite is `candidates`, which the loader refuses: a candidate is not
a task until a person writes the hidden check and the solution and moves it into a real suite.
Everything written passes the credential redaction and a home-path and user-name rule.
"""

from __future__ import annotations

import contextlib
import getpass
import io
import re
import subprocess
import tarfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from evals.evaluator.online import HomeError, Pod, list_pods, read_queue
from evals.evaluator.record import scrub
from evals.evaluator.task import INSTRUCTION_MAX

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "tasks" / "candidates"
SUITE = "candidates"
WALL_SECONDS = 600
SEED_LIMIT_BYTES = 1_000_000
_PATH = re.compile(r"(?:/home|/Users)/[^/\s\"'`:;,)]+")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_TODO_CHECK = (
    "def test_todo() -> None:\n"
    '    raise AssertionError("TODO: replace this with the check that tells a fixed repository '
    'from the failure")\n'
)


class PromoteError(RuntimeError):
    """A task that cannot be promoted; the message is one line for the operator."""


def user_names() -> set[str]:
    """Names to remove wherever they appear: this account and the owner of the home directory."""
    names = {Path.home().name}
    with contextlib.suppress(KeyError, OSError):
        names.add(getpass.getuser())
    return {n for n in names if len(n) >= 2}


def clean(text: str, names: set[str] | None = None) -> str:
    """Redact credentials and addresses, then drop home paths and the user's names."""
    text = scrub(text)
    text = _EMAIL.sub("[EMAIL]", text)
    text = _PATH.sub("<home>", text)
    for name in sorted(names if names is not None else user_names(), key=len, reverse=True):
        text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", "<user>", text)
    return text


def _find(tasks: list[dict[str, Any]], ref: str) -> dict[str, Any]:
    bare = ref.removeprefix("task-")
    exact = [t for t in tasks if t.get("id") in (ref, f"task-{bare}")]
    found = exact or [
        t for t in tasks if str(t.get("id", "")).removeprefix("task-").startswith(bare)
    ]
    if not found:
        raise PromoteError(f"no task {ref!r} in the pod")
    if len(found) > 1:
        raise PromoteError(f"{ref!r} names {len(found)} tasks; give more of the id")
    return found[0]


def _base_commit(record: Mapping[str, Any]) -> str:
    for hop in record.get("hops", []):
        commit = (hop.get("evidence") or {}).get("baseCommit")
        if commit:
            return str(commit)
    return str(record.get("baseRef") or "")


def _seed(codebase: str, ref: str, dest: Path, names: set[str]) -> str:
    """Extract `ref` of the repository at `codebase` into `dest`, cleaned; return why not, or ''."""
    if not ref:
        return "the task records no base commit"
    if not codebase or not Path(codebase).is_dir():
        return "the pod's codebase is not on this machine"
    done = subprocess.run(
        ["git", "-C", codebase, "archive", "--format=tar", ref],
        capture_output=True,
        check=False,
    )
    if done.returncode != 0:
        return f"git could not archive {ref[:12]} from the codebase"
    with tarfile.open(fileobj=io.BytesIO(done.stdout), mode="r:") as archive:
        archive.extractall(dest, filter="data")
    for path in sorted(dest.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        if path.stat().st_size > SEED_LIMIT_BYTES:
            path.unlink()
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if (cleaned := clean(text, names)) != text:
            path.write_text(cleaned, encoding="utf-8")
    return ""


def _instruction(description: str, names: set[str]) -> tuple[str, bool]:
    text = clean(description.strip(), names)
    if len(text) <= INSTRUCTION_MAX:
        return text, False
    return text[: INSTRUCTION_MAX - 3].rstrip() + "...", True


def _notes(
    pod: Pod, record: Mapping[str, Any], bare: str, why_no_seed: str, cut: bool, names: set[str]
) -> str:
    sessions = [
        h["trace"]
        for h in record.get("hops", [])
        if isinstance(h.get("trace"), dict) and h["trace"]
    ]
    lines = [
        f"# Candidate from a failed task of pod {pod.name}",
        "",
        f"- Trace: `docket task trace {bare} --pod {pod.name} --json` in the home it came from.",
        f"- Failure kind: {record.get('failureKind') or 'none recorded'}",
        f"- Reason: {clean(str(record.get('reason') or 'none recorded'), names)}",
    ]
    lines += [f"- Hop session: {clean(str(s.get('session', '')), names)}" for s in sessions]
    if why_no_seed:
        lines.append(f"- No seed: {why_no_seed}; `repo/` holds only `.gitkeep`.")
    if cut:
        lines.append(f"- The instruction was cut to {INSTRUCTION_MAX} characters.")
    lines += [
        "",
        "To finish it: write the check that tells a fixed repository from the failure in `hidden/`,",
        "add a `solution/` that passes it, move the directory into a suite under `evals/tasks/`,",
        "set `suite` and `shape` to match, and run `check-solutions` on it.",
        "",
    ]
    return "\n".join(lines)


def promote(task_ref: str, pod_name: str, home: Path, out: Path = DEFAULT_OUT) -> Path:
    """Write the candidate directory for a failed task of `pod_name`; return it."""
    try:
        pods = {p.name: p for p in list_pods(home)}
    except HomeError as error:
        raise PromoteError(str(error)) from error
    if pod_name not in pods:
        raise PromoteError(f"no pod {pod_name!r} in the home")
    pod = pods[pod_name]
    record = _find(read_queue(home, pod), task_ref)
    if record.get("status") != "failed":
        raise PromoteError(f"task {task_ref!r} is {record.get('status')}, not failed")
    bare = str(record["id"]).removeprefix("task-")
    candidate = out / f"cand-{bare[:8]}"
    if candidate.exists():
        raise PromoteError(f"{candidate.name} exists in the output directory; remove it first")
    names = user_names()
    instruction, cut = _instruction(str(record.get("description") or ""), names)
    if not instruction:
        raise PromoteError("the task has no description to use as an instruction")
    kind = record.get("failureKind") or "none recorded"
    spec = {
        "id": candidate.name,
        "version": 1,
        "suite": SUITE,
        "shape": "build",
        "origin": clean(
            f"task {bare} of pod {pod.name} ended failed (failure kind: {kind})", names
        ),
        "instruction": instruction,
        "pod": {"blueprint": "build", "isolation": False},
        "operator": {"approval": "approve_once"},
        "graders": {"required": ["outcome.hidden_tests"], "report": ["process.tokens"]},
        "limits": {"wall_seconds": WALL_SECONDS},
    }
    (candidate / "repo").mkdir(parents=True)
    (candidate / "hidden").mkdir()
    why = _seed(pod.codebase, _base_commit(record), candidate / "repo", names)
    if why:
        (candidate / "repo" / ".gitkeep").write_text("", encoding="utf-8")
    (candidate / "task.yaml").write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    (candidate / "hidden" / "test_todo.py").write_text(_TODO_CHECK, encoding="utf-8")
    (candidate / "candidate.md").write_text(
        _notes(pod, record, bare, why, cut, names), encoding="utf-8"
    )
    return candidate
