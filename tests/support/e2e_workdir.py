"""A pod on a working directory that is not a repository, for the e2e worlds that need one."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

from docket.kernel.templates import RECIPES_DIR
from tests.support.e2e import World
from tests.support.model_server import FakeModel


def workdir_pod(
    world: Callable[..., World],
    model: FakeModel,
    *,
    blueprint: str = "routine",
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


def outward_pack(w: World, send_tool: str) -> Path:
    """The ``outward`` policy pack with a role overlay that gives the Actor *send_tool* beside
    ``read`` and ``glob``, as the recipe's README tells an operator to write it."""
    pack = w.root / "outward-pack"
    shutil.copytree(RECIPES_DIR / "outward", pack)
    roles = pack / "roles"
    roles.mkdir()
    (roles / "actor.yaml").write_text(
        "kind: role\nname: actor\ndescription: sends the approved draft through the pod's send tool\n"
        f"model: strong\ncannot: [write, edit, bash]\ntools: [read, glob, {send_tool}]\n"
        "instructions: actor.md\n",
        encoding="utf-8",
    )
    (roles / "actor.md").write_text(
        "You are the Actor. Send the approved draft.md once with your send tool.\n",
        encoding="utf-8",
    )
    return pack
