"""Two pods share one service: one waits for a person while the other finishes its task.

``docket start --dispatch`` sweeps a ledger pod and a gallery pod, each with its own repository
and worktrees. The ledger's Implementer meets a gated command and parks for approval; the
gallery task runs to ``done`` meanwhile and shares no trace, worktree or path with the parked
one. The operator then approves the ledger task from the CLI and the sweep finishes it. Only
the model is faked; it answers each pod from that pod's own list of replies.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from tests.support import e2e_oracles as oracles
from tests.support.e2e import Service, World
from tests.support.model_server import FakeModel, Reply, Request, Step, call, fail, say, write_file

PIPELINE = """name: two-pods
steps:
  - plan: lead
  - implement: implementer
  - review: reviewer
    verdict: [APPROVE, REQUEST-CHANGES]
"""

PARKED_POD = "ledger"
FREE_POD = "gallery"
GATED = "rm -rf build"
ROLES = ("lead", "implementer", "reviewer")

LEDGER_RUN = [
    ("hop_started", "lead", "plan"),
    ("hop_finished", "lead", "ok"),
    ("hop_started", "implementer", "implement"),
    ("hop_finished", "implementer", "fail"),
    ("approval_required", "implementer", ""),
    ("session_end", "lead", "waiting_approval"),
    ("approval_resumed", "lead", ""),
    ("hop_started", "implementer", "implement"),
    ("hop_finished", "implementer", "ok"),
    ("verification", "implementer", "skipped"),
    ("hop_started", "reviewer", "review"),
    ("hop_finished", "reviewer", "approve"),
    ("session_end", "lead", "done"),
]
GALLERY_RUN = [
    ("hop_started", "lead", "plan"),
    ("hop_finished", "lead", "ok"),
    ("hop_started", "implementer", "implement"),
    ("hop_finished", "implementer", "ok"),
    ("verification", "implementer", "skipped"),
    ("hop_started", "reviewer", "review"),
    ("hop_finished", "reviewer", "approve"),
    ("session_end", "lead", "done"),
]


def by_pod(**replies: Sequence[Step]) -> Callable[[Request], Reply]:
    """One role's step: the next reply of the pod the request names in its system prompt."""
    queues = {pod: iter(steps) for pod, steps in replies.items()}

    def step(request: Request) -> Reply:
        pod = next((p for p in queues if f"of the **{p}**" in request.system_text), None)
        chosen = next(queues[pod], None) if pod else None
        if chosen is None:
            return fail(400, f"fake model: no reply left for {pod or 'an unknown pod'}")
        return chosen(request) if callable(chosen) else chosen

    return step


def _team() -> dict[str, list[Step]]:
    asked = call("bash", command=GATED)
    return {
        "lead": [by_pod(**{PARKED_POD: [say("Plan: ledger.")], FREE_POD: [say("Plan: gallery.")]})],
        "implementer": [
            by_pod(
                **{
                    PARKED_POD: [asked, asked, write_file("ledger.txt", "ledger\n"), say("done.")],
                    FREE_POD: [write_file("gallery.txt", "gallery\n"), say("done.")],
                }
            )
        ],
        "reviewer": [by_pod(**{PARKED_POD: [say("APPROVE")], FREE_POD: [say("APPROVE")]})],
    }


def _git(repo: Path, w: World, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], env=w.env, check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def _head(repo: Path, w: World) -> str:
    return _git(repo, w, "rev-parse", "HEAD")


def _provision_the_gallery(w: World) -> Path:
    """Give the world a second repository and register the gallery pod on it."""
    repo = w.root / "gallery-repo"
    repo.mkdir()
    (repo / "README.md").write_text("# gallery\n", encoding="utf-8")
    for args in (("init", "-q", "-b", "main"), ("add", "-A"), ("commit", "-q", "-m", "initial")):
        _git(repo, w, *args)
    spec = {"id": FREE_POD, "blueprint": "build", "codebase": str(repo)}
    spec_file = w.root / "gallery-pod.json"
    spec_file.write_text(json.dumps(spec), encoding="utf-8")
    w.docket("init", "--from", str(spec_file))
    w.docket("pod", "set", "pipeline", str(w.pipeline), "--pod", FREE_POD)
    return repo


def _task_in(w: World, pod: str, task_id: str) -> dict[str, Any]:
    shown = w.docket("task", "show", task_id, "--pod", pod, "--json").json()
    assert isinstance(shown, dict)
    return shown


def _run_states(svc: Service) -> dict[str, str]:
    _, runs = svc.get("/runs")
    return {r["project"]: r["state"] for r in runs["runs"]}


def _status(svc: Service, pod: str, task_id: str) -> str:
    code, shown = svc.get(f"/tasks/{pod}/{task_id}")
    return str(shown["status"]) if code == 200 else ""


def _post(svc: Service, pod: str, text: str) -> str:
    code, created = svc.post(f"/tasks/{pod}", {"description": text})
    assert (code, created["status"]) == (201, "pending"), created
    return str(created["task"])


def _everything_of(w: World, pod: str, task_id: str) -> str:
    """The pod's trace as JSON text plus the audit rows that name the pod."""
    events = json.dumps(oracles.trace_events(w, pod, task_id))
    rows = [r for r in oracles.audit_rows(w) if f"project={pod}" in str(r["detail"])]
    return events + json.dumps(rows)


def test_one_pod_waits_for_a_person_while_the_other_finishes(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(script=_team(), repeat_last=True)
    w = world(model)
    w.make_pod(PIPELINE, pod=PARKED_POD)
    w.docket("pod", "set", "pipeline", str(w.pipeline), "--pod", PARKED_POD)
    gallery_repo = _provision_the_gallery(w)
    ledger_head, gallery_head = w.head(), _head(gallery_repo, w)

    with w.service() as svc:
        ledger = _post(svc, PARKED_POD, "Record the ledger entry")
        gallery = _post(svc, FREE_POD, "Hang the gallery photo")
        w.wait_for(lambda: _status(svc, FREE_POD, gallery) == "done", 30, "the gallery task")
        w.wait_for(lambda: _status(svc, PARKED_POD, ledger) == "waiting_approval", 30, "the park")
        _, parked = svc.get(f"/tasks/{PARKED_POD}/{ledger}")
        w.wait_for(
            lambda: _run_states(svc) == {PARKED_POD: "waiting_approval", FREE_POD: "succeeded"},
            30,
            "one run parked and the other succeeded",
        )
        escalation = parked["escalations"][-1]
        assert escalation.startswith("esc-")
        heard = {role: len(model.by_role(role)) for role in ROLES}
        assert heard == {"lead": 2, "implementer": 3, "reviewer": 1}

        w.docket("task", "answer", escalation, "--option", "approve_task", "--pod", PARKED_POD)
        w.wait_for(lambda: _status(svc, PARKED_POD, ledger) == "done", 30, "the ledger task")

    assert oracles.trace_skeleton(w, FREE_POD, gallery) == GALLERY_RUN
    assert oracles.trace_skeleton(w, PARKED_POD, ledger) == LEDGER_RUN
    ledger_tree = Path(w.task(ledger)["task"]["worktree"]["path"])
    gallery_tree = Path(_task_in(w, FREE_POD, gallery)["task"]["worktree"]["path"])
    assert (ledger_tree / "ledger.txt").exists() and not (ledger_tree / "gallery.txt").exists()
    assert (gallery_tree / "gallery.txt").exists() and not (gallery_tree / "ledger.txt").exists()
    assert ledger_tree.parent.parent.name == f"{PARKED_POD}-implementer"
    assert gallery_tree.parent.parent.name == f"{FREE_POD}-implementer"
    assert not (ledger_tree / "build").exists()

    ledger_record = _everything_of(w, PARKED_POD, ledger)
    gallery_record = _everything_of(w, FREE_POD, gallery)
    for mine, other_pod, other_task, other_tree, other_repo in (
        (ledger_record, FREE_POD, gallery, gallery_tree, gallery_repo),
        (gallery_record, PARKED_POD, ledger, ledger_tree, w.repo),
    ):
        for foreign in (other_pod, other_task, str(other_tree), str(other_repo)):
            assert foreign not in mine, f"{foreign} leaked across pods"
    for asked in model.requests:
        text = json.dumps(asked.body)
        foreign = FREE_POD if f"of the **{PARKED_POD}**" in asked.system_text else PARKED_POD
        assert (
            foreign not in text and str(gallery_repo if foreign == FREE_POD else w.repo) not in text
        )

    assert {role: len(model.by_role(role)) for role in ROLES} == {
        "lead": 2,
        "implementer": 6,
        "reviewer": 2,
    }
    oracles.assert_checkout_untouched(w, ledger_head)
    assert (_head(gallery_repo, w), _git(gallery_repo, w, "status", "--porcelain")) == (
        gallery_head,
        "",
    )
    oracles.assert_sentinel_untouched(w)
    oracles.assert_audit_covers_tool_calls(w, PARKED_POD, ledger, refused=1)
    oracles.assert_audit_covers_tool_calls(w, FREE_POD, gallery)
    oracles.assert_transitions_legal(["pending", "waiting_approval", "done"])
    oracles.assert_transitions_legal(["pending", "done"])
    oracles.assert_log_verifies(w)
