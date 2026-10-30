"""A pod on a working directory that is not a repository, for the e2e worlds that need one."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from tests.support.e2e import World
from tests.support.model_server import FakeModel


def workdir_pod(
    world: Callable[..., World],
    model: FakeModel,
    *,
    blueprint: str = "content",
    pipeline_yaml: str | None = None,
    isolation: str = "off",
) -> tuple[World, Path]:
    """A world whose pod is *blueprint* on a fresh, non-repository working directory, and that
    directory. *pipeline_yaml* is written to ``w.pipeline``; without it the blueprint's runs.
    *isolation* ``on`` keeps what ``init`` detected; ``off`` turns the jail off."""
    w = world(model)
    w.pod = "e2e-work"
    work_dir = add_workdir_pod(w, w.pod, blueprint)
    if pipeline_yaml is not None:
        w.pipeline.write_text(pipeline_yaml, encoding="utf-8")
    if isolation == "off":
        w.docket("setup", "sandbox", "off")
    return w, work_dir


def add_workdir_pod(w: World, pod: str, blueprint: str) -> Path:
    """Register pod *pod* on a fresh working directory of its own and return that directory."""
    work_dir = w.root / f"workdir-{pod}"
    work_dir.mkdir()
    spec_file = w.root / f"{pod}.json"
    spec_file.write_text(
        json.dumps(
            {
                "id": pod,
                "blueprint": blueprint,
                "workDir": str(work_dir),
                "description": "A working-directory world.",
            }
        ),
        encoding="utf-8",
    )
    w.docket("init", "--from", str(spec_file))
    return work_dir
