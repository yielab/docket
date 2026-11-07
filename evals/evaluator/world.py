"""The trial world: a clean docket home, a committed seed repository and a provider set through the CLI.

Built on `tests.support.e2e.World` so a trial drives docket the way an operator does, through
`python -m docket` subprocesses. Nothing in docket is patched or called in-process. The provider
and the model are registered with `setup provider add` and `setup model set`, the same commands a
person types; the world's environment carries no model setting of its own.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docket.tasks.domain.state import Status

# pytest's importlib mode (pyproject) does not put the repository root on sys.path, and `tests` is
# a sibling of `evals` there.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.support.e2e import World  # noqa: E402
from tests.support.e2e_oracles import skeleton_of  # noqa: E402

MIN_MAX_TOKENS = 4000
POD = "trial"
_TERMINAL = Status.TERMINAL


@dataclass(frozen=True)
class _Endpoint:
    """The one attribute `World` reads from its model; a real provider has no fake to hand it."""

    base_url: str


class TrialWorld(World):
    """A `World` whose `repo/` is a committed copy of a seed directory."""

    def __init__(
        self, root: Path, seed: Path, *, base_url: str, env: Mapping[str, str] | None = None
    ) -> None:
        self.seed = seed
        super().__init__(root, _Endpoint(base_url), env=env)

    def _make_repo(self) -> None:
        shutil.copytree(self.seed, self.repo, symlinks=True)
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "seed", "--allow-empty")

    def events(self, task_id: str) -> list[dict[str, Any]]:
        """The task's trace events, as `docket task trace --json` prints them."""
        shown = self.docket("task", "trace", task_id, "--pod", self.pod, "--json").json()
        return list(shown["events"])

    def skeleton(self, task_id: str) -> list[list[str]]:
        """The control flow of the task's trace: `(event, role, outcome)` per step."""
        return [list(step) for step in skeleton_of(self.events(task_id))]

    def worktree(self, task_id: str) -> Path:
        """The directory the agent worked in: the task's worktree, or the seed repository a folder
        pod (any blueprint but `build`) works in as its `workDir`."""
        worktree = self.task(task_id)["task"].get("worktree") or {}
        return Path(worktree["path"]) if worktree.get("path") else self.repo

    def status(self, task_id: str) -> str:
        """The task's status as the queue holds it."""
        return str(self.task(task_id)["task"]["status"])

    def is_terminal(self, task_id: str) -> bool:
        """Whether the task has settled (`done`, `failed` or `cancelled`)."""
        return self.status(task_id) in _TERMINAL


def build_world(
    root: Path,
    *,
    seed: Path,
    provider: str,
    model: str,
    max_tokens: int,
    isolation: bool,
    base_url: str = "",
    credential: str = "",
    context_window: int = 32768,
    blueprint: str = "build",
    pipeline: str | None = None,
    credential_env: Mapping[str, str] | None = None,
    env: Mapping[str, str] | None = None,
) -> TrialWorld:
    """A fresh world under *root*: *seed* committed as `repo/`, a *blueprint* pod, *model* on
    *provider* for every role. A custom endpoint gives *base_url* and, for the full tool surface, a
    *credential*; *credential_env* reaches only the `provider add` call."""
    if max_tokens < MIN_MAX_TOKENS:
        raise ValueError(f"max_tokens must be at least {MIN_MAX_TOKENS}, got {max_tokens}")
    world = TrialWorld(root, seed, base_url=base_url, env=env)
    for name in ("DOCKET_LLM_BASE_URL", "DOCKET_LLM_API_KEY", "VIRTUAL_ENV"):
        world.env.pop(name, None)
    world.env["PATH"] = without_virtualenvs(world.env.get("PATH", ""))
    world.pod = POD
    _provision(world, blueprint, pipeline, isolation)
    _register_model(
        world, provider, model, (base_url, credential), (max_tokens, context_window), credential_env
    )
    return world


def _provision(world: World, blueprint: str, pipeline: str | None, isolation: bool) -> None:
    spec: dict[str, str] = {
        "id": world.pod,
        "blueprint": blueprint,
        "description": "An eval trial.",
    }
    if blueprint == "build":
        spec["codebase"] = str(world.repo)
        spec["stack"] = "shell"
    else:
        spec["workDir"] = str(world.repo)
    spec_file = world.root / "pod.json"
    spec_file.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    if pipeline is not None:
        world.pipeline.write_text(pipeline, encoding="utf-8")
    world.docket("init", "--from", str(spec_file))
    if not isolation:
        world.docket("setup", "sandbox", "off")
        return
    status = world.docket("setup", "sandbox", "status", "--json").json()
    if status.get("isolationEnabled") is not True:
        raise RuntimeError(f"the task asks for isolation and this machine has none: {status}")


def without_virtualenvs(path: str) -> str:
    """*path* without the `bin` of any virtualenv: the runner's own venv lives outside the jail's
    roots, so a `python` found there fails at startup inside the trial."""
    kept = [
        d for d in path.split(os.pathsep) if d and not (Path(d).parent / "pyvenv.cfg").is_file()
    ]
    return os.pathsep.join(kept)


def provider_command(
    provider: str, model: str, endpoint: tuple[str, str], limits: tuple[int, int]
) -> list[str]:
    """The `provider add` call: a custom endpoint names its URL and window; a catalog provider
    (no URL) names only its model, and the catalog knows the window."""
    base_url, credential = endpoint
    max_tokens, context_window = limits
    command = ["setup", "provider", "add", provider]
    if base_url:
        command += [base_url, "--model", model, "--ctx", str(context_window)]
    else:
        command += ["--model", model]
    if credential:
        command += ["--credential", credential]
    return [*command, "--max-tokens", str(max_tokens), "--no-preset"]


def _register_model(
    world: World,
    provider: str,
    model: str,
    endpoint: tuple[str, str],
    limits: tuple[int, int],
    credential_env: Mapping[str, str] | None,
) -> None:
    command = provider_command(provider, model, endpoint, limits)
    saved = dict(world.env)
    world.env.update(credential_env or {})
    try:
        world.docket(*command)
    finally:
        world.env.clear()
        world.env.update(saved)
    roles = world.docket("setup", "model", "list", "--json").json()["roles"]
    for key in ("default", *(str(r["role"]) for r in roles)):
        world.docket("setup", "model", "set", key, f"{provider}/{model}")
