"""From a loaded task to trials: `spec_for` fills a `TrialSpec`, `run_task` runs the epochs graded."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from evals.evaluator.record import TrialRecord, TrialSpec, run_trial
from evals.evaluator.task import Task

DEFAULT_TURN_S = 120
DEFAULT_VERIFY_S = 300


def spec_for(
    task: Task,
    *,
    provider: str,
    model: str,
    max_tokens: int,
    epoch: int,
    base_url: str = "",
    credential: str = "",
    credential_env: Mapping[str, str] | None = None,
) -> TrialSpec:
    """The trial of *task* by *model* on *provider* at *epoch*; the task decides the rest."""
    spec = task.spec
    operator: dict[str, str] = {"approval": spec.operator.approval}
    if spec.operator.consult is not None:
        operator["consult"] = spec.operator.consult
    return TrialSpec(
        task=spec.id,
        version=spec.version,
        suite=spec.suite,
        seed=task.repo,
        hidden=task.hidden,
        instruction=spec.instruction,
        isolation=spec.pod.isolation,
        provider=provider,
        model=model,
        max_tokens=max_tokens,
        operator=operator,
        limits={
            "wall_s": float(spec.limits.wall_seconds),
            "turn_s": float(min(DEFAULT_TURN_S, spec.limits.wall_seconds)),
            "verify_s": float(DEFAULT_VERIFY_S),
        },
        blueprint=spec.pod.blueprint,
        base_url=base_url,
        credential=credential,
        credential_env=dict(credential_env or {}),
        epoch=epoch,
        pipeline=(task.path / spec.pipeline).read_text(encoding="utf-8") if spec.pipeline else None,
        memory={
            role: (task.path / rel).read_text(encoding="utf-8")
            for role, rel in spec.pod.memory.items()
        },
        task_max_tokens=spec.limits.max_tokens,
    )


def run_task(task: Task, out_dir: Path, *, epochs: int, **model_kwargs: Any) -> list[TrialRecord]:
    """Run *task* for *epochs* epochs, graded by its own graders; one record per epoch, in order.
    *model_kwargs* are `spec_for`'s keywords after the epoch: provider, model, max_tokens and so on."""
    if epochs < 1:
        raise ValueError("epochs must be at least 1")
    return [
        run_trial(spec_for(task, epoch=epoch, **model_kwargs), out_dir, graders=task.spec.graders)
        for epoch in range(epochs)
    ]
