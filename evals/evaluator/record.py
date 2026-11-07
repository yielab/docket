"""One trial: a clean world, the scripted operator, the frozen evidence, and one record line.

`run_trial` builds the world, delivers the instruction with `docket task add`, lets the operator
drive the task, freezes the trace, audit log, diff and sessions, runs `hidden/` on a copy of the
agent's worktree and appends a `TrialRecord` to `trials.jsonl`. A remote key reaches neither the
frozen files nor the record: both pass through `scrub`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, cast

from docket.governance.secrets import redact
from docket.kernel.home import Home, current_home, use_home
from docket.kernel.ports import process_port
from evals.evaluator.graders import GradeContext, grade, passed
from evals.evaluator.operator import run_operator
from evals.evaluator.task import Graders
from evals.evaluator.taxonomy import classify
from evals.evaluator.verify import RECORDS_ENV, run_hidden
from evals.evaluator.world import TrialWorld, build_world

SCHEMA = 1
TRIALS_FILE = "trials.jsonl"
_DOCKET_ROOT = Path(__file__).resolve().parents[2]
_PROMPT_LAYERS = ("identity", "hop")
_SESSION_FILE = "session.json"
MEMORY_FILE = "MEMORY.md"


@dataclass(frozen=True)
class TrialSpec:
    """Everything one trial needs, as plain values; a task's loader fills it in, not this module."""

    task: str
    version: int
    suite: str
    seed: Path
    hidden: Path
    instruction: str
    isolation: bool
    provider: str
    model: str
    max_tokens: int
    operator: Mapping[str, str]
    limits: Mapping[str, float] = field(default_factory=dict)
    blueprint: str = "build"
    pipeline: str | None = None
    base_url: str = ""
    credential: str = ""
    credential_env: Mapping[str, str] = field(default_factory=dict)
    epoch: int = 0
    memory: Mapping[str, str] = field(default_factory=dict)
    task_max_tokens: int | None = None
    label: str | None = None
    apply: tuple[str, ...] = ()
    fetch_domains: tuple[str, ...] = ()
    records: tuple[str, ...] = ()


@dataclass
class TrialRecord:
    """The record of one trial; `schema` versions the line. `graders` maps a grader's name to its
    status, reason and whether it is required; `passed` is true when every required one passed."""

    task: str
    suite: str
    model: str
    docket_commit: str
    epoch: int
    prompt_hashes: dict[str, dict[str, str]]
    graders: dict[str, Any]
    failure_class: str | None
    tokens: dict[str, dict[str, int]]
    wall_s: float
    asks: list[dict[str, str]]
    denials: int
    trace_skeleton: list[list[str]]
    transcript_path: str
    verifier: dict[str, Any]
    status: str
    reason: str = ""
    passed: bool = False
    schema: int = SCHEMA


class _EnvCredentials:
    """The one part of the process port `redact` reads: credential-shaped variables of this
    process. The evaluator is an entry point that binds no docket adapter, so it supplies this."""

    def credential_env_values(self, names: tuple[str, ...], suffixes: tuple[str, ...]) -> list[str]:
        found = (v.strip() for k, v in os.environ.items() if k in names or k.endswith(suffixes))
        return [v for v in found if v]


def scrub(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    """*value* with every string in it stripped of credential shapes and of each exact *secrets* value.
    Strings are cleaned one by one, so a JSON structure stays valid."""
    with process_port.use(cast(Any, _EnvCredentials())):
        return _scrub(value, secrets)


def _scrub(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        text = redact(value, personal=False)
        for secret in secrets:
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return text
    if isinstance(value, dict):
        return {k: _scrub(v, secrets) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(v, secrets) for v in value]
    return value


def append_record(path: Path, record: TrialRecord, secrets: tuple[str, ...] = ()) -> None:
    """Append *record*, scrubbed, as one JSON line to *path*."""
    line = json.dumps(scrub(asdict(record), secrets), sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as out:
        out.write(line + "\n")


def docket_commit() -> str:
    """The commit of the docket checkout this evaluator runs from, or `unknown`."""
    done = subprocess.run(
        ["git", "-C", str(_DOCKET_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.strip() if done.returncode == 0 else "unknown"


def run_trial(
    spec: TrialSpec, out_dir: Path, *, graders: Graders | None = None, keep_world: bool = False
) -> TrialRecord:
    """Run *spec* once, grade it with *graders*, append its record to `out_dir/trials.jsonl` and
    return it. A trial with no graders is recorded as not passed."""
    if not spec.instruction or len(spec.instruction) > 500:
        raise ValueError("the instruction must be 1 to 500 characters")
    secrets = tuple(v for v in (spec.credential, *spec.credential_env.values()) if v)
    out_dir = out_dir.resolve()  # docket runs from the world, never from this cwd
    out_dir.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="trial-", dir=out_dir))
    started = time.monotonic()
    try:
        record = _run(spec, scratch, out_dir, secrets, started, graders)
    finally:
        if not keep_world:
            shutil.rmtree(scratch, ignore_errors=True)
    append_record(out_dir / TRIALS_FILE, record, secrets)
    return record


def _run(
    spec: TrialSpec,
    scratch: Path,
    out_dir: Path,
    secrets: tuple[str, ...],
    started: float,
    graders: Graders | None,
) -> TrialRecord:
    world = build_world(
        scratch / "world",
        seed=spec.seed,
        provider=spec.provider,
        model=spec.model,
        max_tokens=spec.max_tokens,
        isolation=spec.isolation,
        base_url=spec.base_url,
        credential=spec.credential,
        blueprint=spec.blueprint,
        pipeline=spec.pipeline,
        credential_env=spec.credential_env,
    )
    for target in spec.apply:
        world.docket("pod", "update", target, "--pod", world.pod)
    if spec.fetch_domains:
        world.docket("pod", "set", "fetchDomains", ",".join(spec.fetch_domains), "--pod", world.pod)
    head_before = world.head()
    for role, text in spec.memory.items():
        (_member_workspace(world, role) / MEMORY_FILE).write_text(text, encoding="utf-8")
    budget = ["--max-tokens", str(spec.task_max_tokens)] if spec.task_max_tokens else []
    task_id = world.add_task(spec.instruction, *budget)
    outcome = run_operator(
        world,
        task_id,
        spec.operator,
        wall_s=float(spec.limits.get("wall_s", 600)),
        turn_timeout_s=int(spec.limits.get("turn_s", 120)),
    )
    label = f"{spec.task}-v{spec.version}-e{spec.epoch}-{int(time.time())}"
    frozen = out_dir / "frozen" / label
    events = world.events(task_id)
    transcript = _freeze(world, task_id, events, frozen, secrets)
    verifier = run_hidden(
        world.worktree(task_id),
        spec.hidden,
        scratch / "verify",
        timeout_s=float(spec.limits.get("verify_s", 300)),
        env=_export_records(world, spec.records, scratch / "records"),
    )
    stored = world.stored_task(task_id)
    tokens = _tokens(stored)
    wall_s = round(time.monotonic() - started, 2)
    graded: dict[str, Any] = {}
    if graders is not None:
        graded = grade(
            graders,
            GradeContext(
                frozen=frozen,
                pod=world.pod,
                status=outcome.status,
                statuses=outcome.statuses,
                verifier=verifier,
                repo=world.worktree(task_id),
                tokens=tokens,
                asks=[asdict(a) for a in outcome.asks],
                wall_s=wall_s,
                world=world,
                head_before=head_before,
                check_checkout=spec.blueprint == "build",
                label=spec.label,
            ),
        )
    return TrialRecord(
        task=f"{spec.task}@{spec.version}",
        suite=spec.suite,
        model=f"{spec.provider}/{spec.model}",
        docket_commit=docket_commit(),
        epoch=spec.epoch,
        prompt_hashes=_prompt_hashes(stored),
        graders=graded,
        failure_class=classify(outcome, stored, events, verifier, graded),
        tokens=tokens,
        wall_s=wall_s,
        asks=[asdict(a) for a in outcome.asks],
        denials=_denials(events),
        trace_skeleton=world.skeleton(task_id),
        transcript_path=str(transcript),
        verifier=asdict(verifier),
        status=outcome.status,
        reason=outcome.reason,
        passed=passed(graded),
    )


def _export_records(world: TrialWorld, sets: tuple[str, ...], dest: Path) -> dict[str, str]:
    """Write each record set as `docket pod records <set> --json` prints it to `dest/<set>.json`
    and name the directory in `EVAL_RECORDS`, which the hidden checks read; no sets, no variable."""
    if not sets:
        return {}
    dest.mkdir(parents=True)
    for name in sets:
        shown = world.docket("pod", "records", name, "--pod", world.pod, "--json")
        (dest / f"{name}.json").write_text(shown.out, encoding="utf-8")
    return {RECORDS_ENV: str(dest)}


def _member_workspace(world: TrialWorld, role: str) -> Path:
    """The workspace of the pod's member for *role*, found by its id `<pod>-<role>`; raises if absent."""
    agent_id = f"{world.pod}-{role}"
    with use_home(Home(world.home)):
        workspace = current_home().workspace_dir(agent_id)
    if not workspace.is_dir():
        raise ValueError(f"the pod has no member {agent_id!r} with a workspace for role {role!r}")
    return workspace


def _freeze(
    world: TrialWorld,
    task_id: str,
    events: list[dict[str, Any]],
    dest: Path,
    secrets: tuple[str, ...],
) -> Path:
    """Write the trace, audit log, diff and sessions under *dest*, scrubbed; return the sessions dir."""
    dest.mkdir(parents=True)
    _write_lines(dest / "trace.jsonl", events, secrets)
    audit = [json.loads(x) for x in world.docket("log", "--json").out.splitlines() if x.strip()]
    _write_lines(dest / "audit.jsonl", audit, secrets)
    diff = world.docket("task", "diff", task_id, "--pod", world.pod, check=False).out
    (dest / "diff.patch").write_text(scrub(diff, secrets), encoding="utf-8")
    sessions = dest / "sessions"
    sessions.mkdir()
    for found in sorted((world.home / "state" / "sessions").glob(f"*{task_id}*/{_SESSION_FILE}")):
        text = found.read_text(encoding="utf-8")
        try:
            body = json.dumps(scrub(json.loads(text), secrets), indent=1)
        except ValueError:
            body = scrub(text, secrets)
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", found.parent.name)
        (sessions / f"{name}.json").write_text(body, encoding="utf-8")
    return sessions


def _write_lines(path: Path, rows: list[dict[str, Any]], secrets: tuple[str, ...]) -> None:
    lines = (json.dumps(scrub(row, secrets), sort_keys=True) for row in rows)
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def _prompt_hashes(stored: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """`{role: {layer: sha256}}` from the hops' manifests, as docket froze them; never recomputed."""
    hashes: dict[str, dict[str, str]] = {}
    for hop in stored.get("hops", []):
        layers = (hop.get("promptManifest") or {}).get("layers", [])
        found = {x["layer"]: x["sha256"] for x in layers if x.get("layer") in _PROMPT_LAYERS}
        if found:
            hashes.setdefault(str(hop.get("role", "")), {}).update(found)
    return hashes


def _tokens(stored: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    """Measured tokens summed by role over the task's hops."""
    totals: dict[str, dict[str, int]] = {}
    for hop in stored.get("hops", []):
        role = totals.setdefault(str(hop.get("role", "")), {"input": 0, "output": 0})
        for key in role:
            role[key] += int((hop.get("usage") or {}).get(key, 0))
    return totals


def _denials(events: list[dict[str, Any]]) -> int:
    """Tool calls policy refused outright; a call parked for approval is an ask, not a denial."""
    return sum(
        1
        for e in events
        if e.get("event_type") == "tool_result"
        and e["payload"].get("decision") == "deny"
        and e["payload"].get("denialKind") != "approval_parked"
    )
