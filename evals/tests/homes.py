"""A throwaway docket home holding pods made by `docket init` and task queues written to them."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tests.support.tasks import task

from docket.kernel.home import Home
from docket.tasks.domain.task import HopResult, TaskRecord

HASH_IDENTITY = "a" * 64
HASH_HOP = "b" * 64
_ENV = {
    "PATH": os.environ.get("PATH", ""),
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.test",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.test",
    "GIT_CONFIG_NOSYSTEM": "1",
    "DOCKET_SERVICE_MANAGER": "none",
    "NO_COLOR": "1",
}


def stamp(days_ago: float) -> str:
    when = datetime.now(UTC) - timedelta(days=days_ago)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def hop(
    role: str = "implementer",
    *,
    model: str = "anthropic/model-a",
    verdict: str | None = None,
    cycle: int | None = None,
    identity: str = HASH_IDENTITY,
    **extra: Any,
) -> HopResult:
    layers = [{"layer": "identity", "sha256": identity}, {"layer": "hop", "sha256": HASH_HOP}]
    fields: dict[str, Any] = {
        "role": role,
        "ok": True,
        "model": model,
        "prompt_manifest": {"layers": layers},
        "cycle": cycle,
        **extra,
    }
    if verdict is not None:
        fields["artifact"] = {"summary": "review", "verdict": verdict}
    return HopResult(**fields)


def finished(
    days_ago: float, *, done: bool = True, hops: list[HopResult] | None = None, **fields: Any
) -> TaskRecord:
    """A terminal task completed `days_ago` days back."""
    return task(
        status="done" if done else "failed",
        completed_at=stamp(days_ago),
        hops=hops if hops is not None else [hop()],
        **fields,
    )


def empty_repo(path: Path) -> str:
    """A git repository with one empty commit; its path."""
    path.mkdir(parents=True)
    for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "seed"]):
        subprocess.run(["git", *args], cwd=path, env=_ENV, capture_output=True, check=True)
    return str(path)


def make_home(root: Path, pods: dict[str, list[TaskRecord]], *, codebase: str = "") -> Path:
    """A docket home under `root`: each pod made by `docket init`, its queue set to the tasks."""
    home = root / "docket-home"
    home.mkdir(parents=True, exist_ok=True)
    env = {**_ENV, "DOCKET_HOME": str(home), "HOME": str(root)}
    for pod, records in pods.items():
        repo = codebase or empty_repo(root / f"repo-{pod}")
        spec = {"id": pod, "blueprint": "build", "codebase": repo, "stack": "shell"}
        spec_file = root / f"{pod}.json"
        spec_file.write_text(json.dumps({**spec, "description": "A pod."}), encoding="utf-8")
        command = [sys.executable, "-m", "docket", "init", "--from", str(spec_file)]
        subprocess.run(
            command, cwd=repo, env=env, capture_output=True, text=True, check=True, timeout=120
        )
        queue = Home(home).workspace_dir(f"{pod}-lead") / "TASK_LIST.json"
        body = {"tasks": [r.model_dump(by_alias=True, mode="json") for r in records], "rev": 1}
        queue.write_text(json.dumps(body), encoding="utf-8")
    return home


def success_series(wins_recent: int, wins_prior: int, n: int = 40) -> list[TaskRecord]:
    """`n` tasks in the last 7 days with `wins_recent` done, `n` in the 28 days before."""
    recent = [finished(1 + i * 0.1, done=i < wins_recent) for i in range(n)]
    prior = [finished(10 + i * 0.4, done=i < wins_prior) for i in range(n)]
    return recent + prior
