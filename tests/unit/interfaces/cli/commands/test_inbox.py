"""``docket inbox``: renders `operator.inbox.build_inbox`, owns the on-disk cursor and puts the
exact `docket task ...` command on every item. `INBOX_CURSOR_FILE` is not one of
`tests/conftest.py`'s autouse-isolated paths, so every test repoints it explicitly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.support.pods import seed_lead_implementer_pod as _seed
from tests.support.tasks import pregrant as _pregrant
from tests.support.tasks import put_task, put_tasks, task
from typer.testing import CliRunner

from docket.governance import approval as _approval
from docket.interfaces.cli.app import app as _app
from docket.kernel.home import current_home
from docket.kernel.operator_contract import Option, QuestionV11, Recommendation
from docket.platform import store as _store
from docket.tasks.application import escalations as _escalations

SUBJECT = "docket.interfaces.cli.commands.inbox"

runner = CliRunner()


_SCHEMA = {"type": "object", "properties": {"note": {"type": "string"}}}


def _question(task_id: str, qid: str, message: str, *options: Option) -> QuestionV11:
    return QuestionV11(
        id=qid,
        task_id=task_id,
        pod="demo",
        step="lead",
        message=message,
        requested_schema=_SCHEMA,
        created_at="2026-09-28T00:00:00Z",
        kind="clarification",
        options=list(options),
    )


def _inbox(*args: str) -> Any:
    return runner.invoke(_app, ["inbox", *args])


class TestHumanView:
    def test_a_waiting_input_task_prints_its_question_options_and_answer_command(
        self, tmp_path: Path
    ) -> None:
        with _seed(tmp_path):
            question = _question(
                "task-q",
                "q-1",
                "Where is README.md?",
                Option(id="opt1", label="Root", description="At the root."),
                Option(id="opt2", label="Search", description="Search."),
            )
            question.recommendation = Recommendation(option_id="opt2", rationale="safer")
            put_task("demo", task(id="task-q", status="waiting_input", question=question))

            out = _inbox("--peek").output

            assert "Q: Where is README.md?" in out
            assert "opt2 (Search) (recommended)" in out
            assert "docket task answer task-q" in out

    def test_a_multi_line_question_indents_every_continuation_line(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            question = _question(
                "task-m",
                "q-2",
                "First line?\nSecond line.\nThird line.",
                Option(id="opt1", label="Root", description="At the root."),
            )
            put_task("demo", task(id="task-m", status="waiting_input", question=question))

            out = _inbox("--peek").output

            assert "    Q: First line?\n       Second line.\n       Third line.\n" in out
            assert not any(
                ln and not ln.startswith(" ") and "line" in ln for ln in out.splitlines()
            )

    def test_a_held_approval_prints_the_whole_command_and_both_decisions(
        self, tmp_path: Path
    ) -> None:
        with _seed(tmp_path):
            action = "tool call 'bash': git push origin production --force-with-lease " + "x" * 300
            token = _approval.approval_create(
                "demo", "implementer", action, context={"tool": "bash", "parked": True}
            )
            put_task("demo", task(id="task-a", status="waiting_approval", approval_token=token))

            out = _inbox("--peek").output

            assert action in out
            assert "docket task approve task-a" in out
            assert "docket task deny task-a" in out
            assert token not in out


class TestDecidedView:
    def _decide(self) -> None:
        question = QuestionV11(
            id="q-9",
            task_id="task-d",
            pod="demo",
            step="implementer",
            message="Which store?",
            requested_schema=_SCHEMA,
            created_at="2026-09-28T00:00:00Z",
            kind="decision",
            options=[
                Option(id="redis", label="Redis", description="fast"),
                Option(id="sqlite", label="SQLite", description="simple"),
            ],
            recommendation=Recommendation(option_id="sqlite", rationale="fewer services"),
        )
        _escalations.decided_consult(question, role="implementer", option_id="sqlite")

    def test_a_decision_the_pod_took_alone_is_printed_under_done(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            self._decide()

            out = _inbox("--peek").output

            assert "Done" in out and "decided consult" in out
            assert "sqlite" in out and "task-d" in out
            assert "Nothing needs you." not in out

    def test_json_carries_the_decisions_under_decided(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            self._decide()

            body = json.loads(_inbox("--json", "--peek").stdout)

            (decided,) = body["decided"]
            assert (decided["kind"], decided["state"], decided["task"]) == (
                "consult",
                "decided",
                "task-d",
            )


class TestJsonView:
    def test_items_carry_state_and_command_and_no_escape_codes(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            put_tasks(
                "demo",
                task(id="t-done", status="done", completed_at="2026-09-28T01:00:00+00:00"),
                task(id="t-failed", status="failed", reason="boom"),
            )

            result = _inbox("--json", "--peek")

            assert "\x1b" not in result.stdout
            body = json.loads(result.stdout)
            assert set(body) == {
                "needsYou",
                "failed",
                "doneSince",
                "running",
                "next",
                "escalations",
            }
            assert body["doneSince"][0]["state"] == "done"
            assert body["failed"][0]["command"] == "docket task retry t-failed"

    def test_a_granted_task_is_approved_ready_and_points_at_run(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            put_task("demo", task(id="t-ok"))
            _pregrant("demo", "t-ok")

            body = json.loads(_inbox("--json", "--peek").stdout)

            item = body["needsYou"][0]
            assert item["state"] == "approved_ready"
            assert item["command"] == "docket run --pod demo"

    def test_a_plain_pending_task_is_not_listed(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            put_task("demo", task(id="t-new"))
            assert json.loads(_inbox("--json", "--peek").stdout)["needsYou"] == []


class TestUsage:
    def test_an_unknown_flag_exits_2(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            result = _inbox("--bogus")
            assert result.exit_code == 2
            assert "--bogus" in result.output


class TestCursor:
    def test_a_plain_call_advances_it_and_a_repeat_shows_no_done_item(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            put_task("demo", task(id="t1", status="done", completed_at="2026-09-28T01:00:00+00:00"))

            first = json.loads(_inbox("--json").stdout)
            second = json.loads(_inbox("--json").stdout)

            assert [t["id"] for t in first["doneSince"]] == ["t1"]
            assert second["doneSince"] == []
            assert (
                _store.read_json(current_home().inbox_cursor_file)["since"]
                == "2026-09-28T01:00:00+00:00"
            )

    def test_peek_and_explicit_since_leave_no_cursor(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            put_task("demo", task(id="t1", status="done", completed_at="2026-09-28T01:00:00+00:00"))

            _inbox("--json", "--peek")
            body = json.loads(_inbox("--json", "--since", "2026-09-28T05:00:00+00:00").stdout)

            assert body["doneSince"] == []
            assert not current_home().inbox_cursor_file.exists()


class TestEscalations:
    def _park(self, **question: Any) -> QuestionV11:
        queued = _question(
            "task-q",
            "q-esc",
            "Where is README.md?",
            Option(id="opt1", label="Root", description="At the root."),
            Option(id="opt2", label="Search", description="Search."),
        )
        queued.recommendation = Recommendation(option_id="opt2", rationale="safer")
        put_task("demo", task(id="task-q", status="waiting_input", question=queued))
        _escalations.open_for_question(queued, kind="consult", role="lead", caused_by="c1")
        return queued

    def test_the_answer_line_names_the_recommended_option(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            self._park()

            out = _inbox("--peek").output

            assert "Q: Where is README.md?" in out
            assert "opt1 (Root)" in out and "opt2 (Search) (recommended)" in out
            assert "answer: docket task answer task-q --option opt2" in out
            assert "decline" not in out

    def test_the_json_carries_the_view_and_the_surfaces_own_command(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            self._park()

            body = json.loads(_inbox("--json", "--peek").stdout)

            (escalation,) = body["escalations"]
            assert escalation["kind"] == "consult" and escalation["state"] == "pending"
            assert escalation["affordances"]["options"] == ["opt1", "opt2", "decline"]
            assert escalation["command"] == "docket task answer task-q"
            assert "command" not in escalation["affordances"]
            assert body["needsYou"][0]["command"] == "docket task answer task-q"

    def test_a_pending_approval_escalation_points_at_answer_by_its_id(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            token = _approval.approval_create("demo", "implementer", "bash: rm -rf build")
            escalation = _escalations.open_for_approval(
                token, kind="approval", task_id="", caused_by="c1"
            )

            body = json.loads(_inbox("--json", "--peek").stdout)

            assert body["escalations"][0]["command"] == (
                f"docket task answer {escalation.id} --option approve_once"
            )
