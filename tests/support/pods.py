"""Test-side pod seeding: provision a fresh pod's members without going through `docket init`."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from rich.markup import escape

import docket.kernel.templates as _templates
from docket.agent import ports as _rd
from docket.hops.application import sweep as _sweep
from docket.interfaces.cli.commands import pod as _pod
from docket.interfaces.cli.render import ui
from docket.kernel.home import Home, current_home, use_home
from docket.operator import channel as _channel
from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain import spec as _pipeline
from docket.pipeline.domain import step as _step
from docket.pipeline.domain.spec import PipelineSpec, load_pipeline
from docket.platform import store as _store
from docket.tasks.application import queue as _queue
from docket.tasks.application import record as _record
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.task import TaskRecord
from docket.teams import fleet as _fleet
from docket.teams import pod
from docket.teams import pod_provisioning as _pp
from tests.support.fakes import FakeDriver, landlock_host
from tests.support.home import point_config_at, record_isolation_off
from tests.support.roles import ROLE_NAMES


def build_pod(
    project: str,
    roles: tuple[str, ...],
    *,
    codebase: str = "",
    stack: str = "",
    description: str = "",
    project_key: str = "default",
    work_dir: str = "",
    blueprint_name: str = "",
    budget_usd: float | None = None,
) -> list[str]:
    """Provision a pod's members and return their ids; a provisioning failure warns and
    returns ``[]``."""
    try:
        created = _pp.provision_members(
            project,
            roles,
            codebase=codebase,
            stack=stack,
            description=description,
            project_key=project_key,
            work_dir=work_dir,
            blueprint_name=blueprint_name,
            budget_usd=budget_usd,
        )
    except _pp.PodProvisionError as exc:
        ui.warn(f"  pod provisioning failed: {exc}")
        return []
    for m in created:
        ui.success(escape(f"  {m.member_id}  [{m.role}]  {m.model}"))
    return [m.member_id for m in created]


META: dict[str, Any] = {
    "schemaVersion": 1,
    "kind": "project",
    "name": "My Shop",
    "type": "repo",
    "model": "anthropic/claude-sonnet-4-6",
    "stack": "Node.js",
    "codebase": "/home/testuser/Sites/myshop",
    "sessionKey": "agent:myshop:default",
    "projectKey": "default",
}


GATED_IMPLEMENTER_PIPELINE_YAML = """\
name: gated-default
steps:
  - lead: lead
  - implementer: implementer
    approval: true
  - reviewer: reviewer
    verdict: [APPROVE, REQUEST-CHANGES]
    on: {REQUEST-CHANGES: {goto: implementer, max: 1}}
"""


_ASK_PIPELINE_YAML = """\
name: ask
steps:
  - lead: lead
  - ask:
      input:
        from: lead
  - implementer: implementer
"""


_POD_INPUT_BLOCK = """kind: policy
name: block-canary
appliesTo: ["*"]
on: input
when:
  matches: 'CANARY-PHRASE'
then: block
message: canary
"""


_FLEET_CONFIG: dict[str, Any] = {
    "agents": [{"id": "myshop"}],
    "bindings": [],
    "defaults": {"model": "anthropic/claude-sonnet-4-6"},
    "security": {"gatesEnabled": False, "isolationEnabled": False},
}


_FULL_META: dict[str, Any] = {
    "schemaVersion": 1,
    "kind": "project",
    "type": "repo",
    "name": "My Shop",
    "model": "anthropic/claude-sonnet-4-6",
    "stack": "Node.js",
    "codebase": "/tmp/myshop",
    "sessionKey": "agent:myshop:default",
    "projectKey": "default",
    "templateVersion": str(current_home().template_version),
}


_SECURITY_VETTER_LONG: dict[str, object] = {
    "name": "security-vetter",
    "scope": "pod",
    "modelClass": "strong",
    "description": "read-only security pass over the implementer's change",
    "tokenBudget": 6000,
    "deniedTools": ["write", "edit", "bash"],
    "gateContract": {"kind": "verdict", "regexes": ["APPROVE", "REQUEST-CHANGES"]},
    "soulTemplate": (
        "# SOUL.md — ${project} · ${role}\n\n"
        "You are the **${role}** of the **${project}** pod.\n"
        "Codebase: ${codebaseOrConfigured} (stack: ${stack}).\n"
    ),
    "agentsTemplate": (
        "# AGENTS.md — ${project} · ${role}\n\n## Red Lines\n\nStay within the `${project}` pod.\n"
    ),
}


def canonical(value: object) -> bytes:
    return (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
        + b"\n"
    )


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{path} must contain one JSON object"
    return value


def under(root: Path, raw: object) -> Path:
    assert isinstance(raw, str) and raw
    relative = Path(raw)
    assert not relative.is_absolute() and ".." not in relative.parts
    resolved = (root / relative).resolve()
    assert resolved.is_relative_to(root.resolve())
    return resolved


def write_meta(member_id: str, extra: dict[str, Any] | None = None) -> None:
    ws = current_home().projects_dir / member_id
    ws.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "project",
        "scope": "project",
        "role": member_id.split("-")[-1],
        "name": member_id,
        "codebase": str(ws),
        "model": "anthropic/claude-haiku-4-5",
        "sessionKey": f"agent:{member_id}:default",
        "projectKey": "default",
        "created": "2026-07-30T00:00:00+00:00",
    }
    if extra:
        meta.update(extra)
    (ws / ".docket-meta.json").write_text(json.dumps(meta))
    _fleet.add_agent(member_id)


@contextmanager
def seed_pod(tmp_path: Path, project: str = "demo") -> Iterator[Path]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        build_pod(project, _pod.pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
        yield home


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


@contextmanager
def seed_pod_isolation_off(
    tmp_path: Path,
    project: str = "demo",
    roles: tuple[str, ...] = _pod.pod.DEFAULT_POD_ROLES,
) -> Iterator[Path]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        record_isolation_off(home)
        build_pod(project, roles, codebase=f"/src/{project}")
        yield home


def bind_pipeline(project: str, text: str) -> None:
    """Bind *text* as *project*'s own pipeline, so ``answer_task``'s own
    ``effective_pipeline(project, None)`` resolves the same steps a test's own
    ``dispatch_pod`` call ran through."""
    import hashlib

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    path = _pod.pod.bound_pipeline_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _fleet.meta_set(_pod.pod.member_id(project, "lead"), "pipeline", digest)


def bind_intake_pipeline(project: str) -> None:
    """Bind the real shipped ``intake`` recipe's pipeline so ``dispatch_pod`` and
    ``answer_task`` resolve the same steps (see ``_bind_pipeline`` above)."""
    text = (_templates.RECIPES_DIR / "intake" / "pipeline.yaml").read_text(encoding="utf-8")
    result = _pipeline.load_pipeline(text, roles=ROLE_NAMES)
    assert result.spec is not None, result.errors
    bind_pipeline(project, text)


def lead_ws(project: str = "demo") -> Path:
    return current_home().workspace_dir(f"{project}-lead")


def write_meta_overrides(agent_id: str, **overrides: object) -> Path:
    """Write a real `.docket-meta.json` for *agent_id* and return its workspace dir."""
    ws = current_home().workspace_dir(agent_id)
    ws.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {"kind": "project", "role": "implementer", "model": "test/model"}
    data.update(overrides)
    _store.write_json(current_home().meta_path(agent_id), data)
    return ws


def spec(text: str) -> _pipeline.PipelineSpec:
    loaded = _pipeline.load_pipeline(text, roles=ROLE_NAMES)
    assert loaded.ok, loaded.errors
    assert loaded.spec is not None
    return loaded.spec


def seed_lean_pod(project: str = "myapp") -> None:
    write_meta(f"{project}-lead")
    write_meta(f"{project}-implementer")


def write_policy(
    policy_id: str,
    hook: str,
    pattern: str,
    action: str,
    *,
    applies_to: list[str] | None = None,
    message: str = "",
) -> None:
    current_home().policies_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "kind": "policy",
        "name": policy_id,
        "description": f"test policy {policy_id}",
        "appliesTo": applies_to or ["*"],
        "on": hook,
        "when": {"matches": pattern},
        "then": action,
        "message": message,
    }
    (current_home().policies_dir / f"{policy_id}.json").write_text(
        json.dumps(doc), encoding="utf-8"
    )


def members() -> list[str]:
    return sorted(p.name for p in current_home().projects_dir.iterdir())


def setup_agent(tmp_path: Path, agent_id: str = "myshop") -> Path:
    oc_dir = tmp_path / ".docket"
    oc_dir.mkdir()
    ws = oc_dir / "workspaces" / "projects" / agent_id
    (ws / "memory").mkdir(parents=True)
    (ws / ".docket-meta.json").write_text(json.dumps(META))
    (ws / "SOUL.md").write_text("# SOUL\n")
    return oc_dir


@contextmanager
def seed_empty_home(
    tmp_path: Path,
) -> Iterator[Path]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        yield home


def ids(home: Path) -> list[str]:
    # Agent registration lives in fleet.json.
    del home  # kept for call-site compatibility; no longer the source
    return [a.id for a in _fleet.list_agents()]


def meta(home: Path, member_id: str) -> dict[str, Any]:
    p = Home(home).projects_dir / member_id / ".docket-meta.json"
    return json.loads(p.read_text())


def section(*lines: str) -> str:
    return "Done.\n\n## Memory\n" + "\n".join(lines) + "\n"


@contextmanager
def seed_fixture_pod(tmp_path: Path, project: str) -> Iterator[None]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        build_pod(project, pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
        yield


@pytest.fixture()
def pod_home(tmp_path: Path) -> Iterator[Path]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    (home / "approvals").mkdir()
    with use_home(Home(home)):
        yield home


def seed_parked_task(project: str = "demo") -> TaskRecord:
    """A real pod with a real ``waiting_input`` task, reached by actually dispatching
    through an ``input`` step -- mirrors ``tests/unit/core/test_answers.py``."""
    build_pod(project, _pod.pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
    bind_pipeline(project, _ASK_PIPELINE_YAML)
    _queue.enqueue_task_once(project, "needs a decision", channel="cli")
    _sweep.dispatch_pod(project, runner=FakeDriver())
    return TaskRepository.for_pod(project).list()[0]


def bind_demo_pipeline(text: str) -> None:
    path = _pod.pod.bound_pipeline_path("demo")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    _fleet.meta_set(_pod.pod.member_id("demo", "lead"), "pipeline", digest)


@pytest.fixture()
def pod_input_policy(tmp_path: Path) -> Iterator[Path]:
    """A home whose pod `mypod` carries one `on: input` block policy and no global ones."""

    home = tmp_path / "home"
    with use_home(Home(home)):
        policies = current_home().pod_config_dir("mypod") / "policies"
        policies.mkdir(parents=True)
        (policies / "block-canary.yaml").write_text(_POD_INPUT_BLOCK)
        current_home().policies_dir.mkdir(parents=True, exist_ok=True)
        yield home


@pytest.fixture
def workspace_with_files(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n")
    (tmp_path / "notes.md").write_text("alpha\nbeta\ngamma\n")
    return tmp_path


def unit(step_id: str, **extra: Any) -> _orch.PlannedUnit:
    fields: dict[str, Any] = {
        "step_id": step_id,
        "role": "implementer",
        "agent": None,
        "archetype": None,
        "member_id": "demo-implementer",
        "gate": None,
        "retries": None,
        "timeout": None,
    }
    return _orch.PlannedUnit(**{**fields, **extra})


@pytest.fixture()
def pod_home_bare(tmp_path: Path) -> Iterator[Path]:
    """A hermetic DOCKET_HOME with the directories enqueue_task_once touches."""
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))

    with use_home(Home(home)):
        yield home


def unit_context(
    *,
    project: str = "myapp",
    task_id: str = "task-1",
    cap: float = 0.0,
    override_index: int | None = None,
    run: Any = None,
    on_hop: Any = None,
) -> _record.UnitContext:
    return _record.UnitContext(
        project=project,
        task=TaskRecord(id=task_id, description=""),
        task_id=task_id,
        session_id=f"agent:{project}:{task_id}",
        cap=cap,
        resolved_turn_timeout=60,
        resolved_verify_timeout=60,
        id_to_index={},
        rework_counts={},
        override_index=override_index,
        track_pid=False,
        run=run or (lambda *a, **k: _rd.TurnResult(True, "", 0.0, {})),
        do_sleep=lambda seconds: None,
        on_hop=on_hop,
        on_retry=None,
    )


def planned_unit(
    member_id: str, *, gate: _gates.Gate | None = None, step_id: str = "implementer"
) -> _orch.PlannedUnit:
    return _orch.PlannedUnit(
        step_id=step_id,
        role="implementer",
        agent=None,
        archetype=None,
        member_id=member_id,
        gate=gate,
        retries=None,
        timeout=None,
    )


@contextmanager
def seed_lead_implementer_pod(tmp_path: Path, project: str = "demo") -> Iterator[Path]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        build_pod(project, ("lead", "implementer"), codebase=f"/src/{project}")
        yield home


@contextmanager
def seed_setup_check_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    full_workspace: bool = True,
    budget: str | None = None,
    register: bool = True,
    meta_model: str = "anthropic/claude-sonnet-4-6",
    secrets: dict[str, str] | None = None,
    notify: bool = True,
) -> Iterator[Path]:
    """Create a temp DOCKET_HOME with one myshop agent and repoint config; a healthy home
    has a channel that delivers beyond the console, so `desktop` is enabled unless asked not to."""
    home = tmp_path / ".docket"
    ws = home / "workspaces" / "projects" / "myshop"
    (ws / "memory").mkdir(parents=True)

    meta = {**_FULL_META, "model": meta_model}
    if budget is not None:
        meta["budgetUsd"] = budget
    (ws / ".docket-meta.json").write_text(json.dumps(meta))

    files = ("SOUL.md", "AGENTS.md", "TOOLS.md", "HEARTBEAT.md") if full_workspace else ("SOUL.md",)
    for f in files:
        (ws / f).write_text(f"# {f}\n")

    fleet = json.loads(json.dumps(_FLEET_CONFIG))
    if not register:
        fleet["agents"] = []
    fleet_file = home / "fleet.json"
    fleet_file.write_text(json.dumps(fleet))
    fleet_file.chmod(0o600)

    if secrets is not None:
        sfile = home / "secrets.json"
        sfile.write_text(json.dumps(secrets))
        sfile.chmod(0o600)

    with point_config_at(home), landlock_host():
        if notify:
            _channel.enable_channel("desktop")
        yield home


def bind_one_step_pipeline(project: str) -> None:
    text = "name: solo\nsteps:\n  - kickoff: lead\n"
    path = pod.bound_pipeline_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    _fleet.meta_set(pod.member_id(project, "lead"), "pipeline", digest)


def load(text: str) -> PipelineSpec:
    loaded = load_pipeline(text, roles=ROLE_NAMES)
    assert loaded.ok, loaded.errors
    assert loaded.spec is not None
    return loaded.spec


def spec_with_variables(**variables: _pipeline.Variable) -> _pipeline.PipelineSpec:
    return _pipeline.PipelineSpec(
        name="t",
        variables=variables,
        steps=[_step.Step(id="lead", role="lead")],
    )


def write_security_vetter_md(directory: Path) -> None:
    (directory / "security-vetter.md").write_text(
        _SECURITY_VETTER_LONG["soulTemplate"]  # type: ignore[operator]
        + "\n## AGENTS\n\n"
        + _SECURITY_VETTER_LONG["agentsTemplate"],  # type: ignore[operator]
        encoding="utf-8",
    )


def bind_ask_pipeline(project: str, text: str = _ASK_PIPELINE_YAML) -> None:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    path = _pod.pod.bound_pipeline_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _fleet.meta_set(_pod.pod.member_id(project, "lead"), "pipeline", digest)


@contextmanager
def parked_task_in_pod(
    tmp_path: Path,
) -> Iterator[TaskRecord]:
    """A real pod with a real ``waiting_input`` task, reached by actually dispatching
    through an ``input`` step -- mirrors ``tests/unit/core/test_answers.py``."""
    with seed_pod_isolation_off(tmp_path):
        bind_ask_pipeline("demo")
        _queue.enqueue_task_once("demo", "needs a decision", channel="cli")
        _sweep.dispatch_pod("demo", runner=FakeDriver())
        yield TaskRepository.for_pod("demo").list()[0]


@contextmanager
def seed_pod_at_codebase(tmp_path: Path, codebase: Path) -> Iterator[None]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        build_pod("demo", pod.DEFAULT_POD_ROLES, codebase=str(codebase))
        yield
