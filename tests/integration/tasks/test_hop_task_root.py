"""``hops/application/compose.py::_hop_message`` names the task's root and carries the repository map."""

from __future__ import annotations

from pathlib import Path

from tests.support.pods import build_pod, seed_empty_home

from docket.hops.application import compose as _compose
from docket.kernel.brief import TaskBrief
from docket.kernel.handoff import HandoffArtifact
from docket.tasks.domain.parts import Worktree
from docket.tasks.domain.task import HopResult, TaskRecord
from docket.teams import roles as _arch

SUBJECT = "docket.tasks.application.queue"

_TASK = TaskRecord(description="ship the feature")


def _tree(directory: Path) -> Worktree:
    return Worktree(dir=str(directory), branch="b", base_commit="")


def _repo_with_files(root: Path) -> Path:
    import subprocess

    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("x = 1\n")
    (root / "src" / "util.py").write_text("y = 2\n")
    (root / "README.md").write_text("hi\n")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    return root


_LINE = (
    "Working directory: the repository root (your tools start there; give paths relative to it)."
)


_WORKDIR_LINE = (
    "Working directory: the pod's working directory (your tools start there; give paths "
    "relative to it)."
)


def _commit(root: Path) -> str:
    import subprocess

    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"],
        check=True,
    )
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def _lead_hop() -> HopResult:
    brief = TaskBrief(objective="add a flag", context=["edit src/app.py"])
    return HopResult(
        role="lead",
        member_id="p-lead",
        ok=True,
        output="the plan",
        artifact=HandoffArtifact(summary="the plan", brief=brief),
    )


class TestTaskRootAndRepositoryMap:
    """The task message says the tools start at the repository root and carries the map."""

    def test_a_worktree_task_states_the_root_relatively_and_carries_the_map(
        self, tmp_path: Path
    ) -> None:
        worktree = _repo_with_files(tmp_path / "wt")
        task = _TASK.model_copy(update={"worktree": _tree(worktree)})

        message, comp = _compose._hop_message(task, "implementer", [])

        assert _LINE in message
        assert str(worktree) not in message and str(tmp_path) not in message
        assert "src/ (2 files)" in message
        assert "./ (1 file)" in message
        assert (
            message.index("## Task") < message.index("## Hop") < message.index("Working directory:")
        )
        assert comp.total_bytes == len(message.encode("utf-8"))

    def test_the_line_precedes_a_prior_artifact_in_the_hop_section(self, tmp_path: Path) -> None:
        worktree = _repo_with_files(tmp_path / "wt")
        task = _TASK.model_copy(update={"worktree": _tree(worktree)})
        hop = HopResult(role="lead", member_id="p-lead", ok=True, output="the plan")

        message, _ = _compose._hop_message(task, "implementer", [hop])

        assert message.index("Working directory:") < message.index("--- lead output ---")

    def test_the_lead_is_never_told_a_task_worktree(self, tmp_path: Path) -> None:
        worktree = _repo_with_files(tmp_path / "wt")
        task = _TASK.model_copy(update={"worktree": _tree(worktree)})

        message, _ = _compose._hop_message(task, "lead", [])

        assert (
            message
            == "You are the pod Lead. Decompose this task into a concrete plan for the Implementer (you never edit code yourself):\n\nship the feature"
        )

    def test_a_root_that_is_not_a_repository_gets_the_line_and_no_map(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        task = _TASK.model_copy(update={"worktree": _tree(plain)})

        message, _ = _compose._hop_message(task, "reviewer", [])

        assert _LINE in message and str(plain) not in message
        assert "Repository map" not in message

    def test_no_worktree_and_no_pod_adds_nothing(self) -> None:
        message, _ = _compose._hop_message(_TASK, "implementer", [])
        assert "Working directory" not in message

    def test_a_brief_bounds_the_map_to_the_paths_it_names(self, tmp_path: Path) -> None:
        worktree = _repo_with_files(tmp_path / "wt")
        task = _TASK.model_copy(update={"worktree": _tree(worktree)})

        message, _ = _compose._hop_message(task, "implementer", [_lead_hop()])

        assert "src/app.py\nsrc/util.py" in message
        assert "(2 files)" not in message and "README.md" not in message
        assert "`glob`" in message.split("\n\n## Hop\n", 1)[0]

    def test_the_task_section_does_not_change_when_a_hop_stages_a_new_file(
        self, tmp_path: Path
    ) -> None:
        import subprocess

        worktree = _repo_with_files(tmp_path / "wt")
        base = _commit(worktree)
        task = _TASK.model_copy(
            update={"worktree": Worktree(dir=str(worktree), branch="b", base_commit=base)}
        )
        prior = [_lead_hop()]

        first, _ = _compose._hop_message(task, "implementer", prior)
        (worktree / "src" / "new.py").write_text("z = 3\n")
        subprocess.run(["git", "-C", str(worktree), "add", "."], check=True)
        second, _ = _compose._hop_message(task, "reviewer", prior)

        assert "new.py" not in second
        assert first.split("\n\n## Hop\n", 1)[0] == second.split("\n\n## Hop\n", 1)[0]


class TestStructuredTaskPaths:
    def test_paths_bound_the_map_when_no_lead_brief_exists(self, tmp_path: Path) -> None:
        worktree = _repo_with_files(tmp_path / "wt")
        (worktree / "src" / "app").mkdir()
        (worktree / "src" / "app" / "main.py").write_text("m = 1\n")
        import subprocess

        subprocess.run(["git", "-C", str(worktree), "add", "."], check=True)
        task = TaskRecord.model_validate(
            {"description": "ship it", "task": {"paths": ["src/app/"], "doneWhen": "it ships"}}
        ).model_copy(update={"worktree": _tree(worktree)})

        message, _ = _compose._hop_message(task, "implementer", [])

        section = message.split("\n\n## Hop\n", 1)[0]
        assert "Done when: it ships" in section
        assert "src/app/main.py" in section
        assert "README.md" not in section and "src/util.py" not in section
        assert "(3 files)" not in section

    def test_a_task_without_paths_keeps_the_capped_map(self, tmp_path: Path) -> None:
        worktree = _repo_with_files(tmp_path / "wt")
        task = TaskRecord.model_validate(
            {"description": "ship it", "task": {"doneWhen": "it ships"}}
        ).model_copy(update={"worktree": _tree(worktree)})

        message, _ = _compose._hop_message(task, "implementer", [])

        assert "Repository map (tracked files by directory):" in message


class TestWorkdirPod:
    """A `workdir`-kind pod's root is a working directory: the hop says so and carries no map."""

    def test_every_role_is_told_the_working_directory_and_given_no_map(
        self, tmp_path: Path
    ) -> None:
        work_dir = _repo_with_files(tmp_path / "work")
        with seed_empty_home(tmp_path):
            build_pod(
                "demo",
                ("lead", "writer", "critic"),
                work_dir=str(work_dir),
                blueprint_name="content",
            )

            lead, _ = _compose._hop_message(_TASK, "lead", [], project="demo")
            assert "the role that follows in the pipeline" in lead and "Implementer" not in lead
            writer, _ = _compose._hop_message(_TASK, "writer", [_lead_hop()], project="demo")

        for message in (lead, writer):
            assert _WORKDIR_LINE in message
            assert "repository root" not in message and "Repository map" not in message
            assert "src/util.py" not in message and "README.md" not in message
            assert str(work_dir) not in message

    def test_a_codebase_pod_keeps_the_repository_line_and_map(self, tmp_path: Path) -> None:
        codebase = _repo_with_files(tmp_path / "code")
        with seed_empty_home(tmp_path):
            build_pod("demo", ("lead", "implementer"), codebase=str(codebase))

            lead, _ = _compose._hop_message(_TASK, "lead", [], project="demo")

        assert _LINE in lead and "Repository map (tracked files by directory):" in lead
        assert "plan for the Implementer" in lead

    def test_a_pod_overlay_of_the_lead_instruction_still_wins_on_a_workdir_pod(
        self, tmp_path: Path
    ) -> None:
        work_dir = _repo_with_files(tmp_path / "work")
        with seed_empty_home(tmp_path):
            build_pod("demo", ("lead", "writer"), work_dir=str(work_dir), blueprint_name="content")
            _arch.add_user_archetype(
                {
                    "name": "lead",
                    "version": 2,
                    "scope": "pod",
                    "modelClass": "cheap",
                    "soulTemplate": "x",
                    "agentsTemplate": "y",
                    "gateContract": {"kind": "none"},
                    "toolProfile": "coordination",
                    "hopInstruction": "You are the Lead. Plan for the Writer.",
                },
                "demo",
            )

            lead, _ = _compose._hop_message(_TASK, "lead", [], project="demo")

        assert lead.startswith("You are the Lead. Plan for the Writer.")
