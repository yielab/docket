"""The ``external`` gate: a fake verifier script run after the Implementer hop, its exit mapped to
pass / fail / needs_human / error, its reasons file read, screened and carried into the retry.

Specs: pipeline-format.spec.md "Gates" item 5, pod-dispatch.spec.md "Generalized gate execution"
item 6 and "Bounded hop prompts" item 9.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from tests.support.fakes import FakeDriver
from tests.support.home import record_isolation_off
from tests.support.llm import implementer_messages as _implementer_messages
from tests.support.pods import build_pod

from docket.governance import secrets as _secrets
from docket.hops.gates import post_hop as _post_hop
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.home import Home, use_home
from docket.pipeline.domain import spec as _pipeline
from docket.tasks.application import answers as _answers
from docket.tasks.application import queue as _queue
from docket.tasks.application import sweep as _sweep
from docket.teams import fleet as _fleet

SUBJECT = "docket.tasks"

REASON = "zz-unique-reason-5521"

_PLAIN = """\
name: gated
steps:
  - id: plan
    role: lead
  - id: build
    role: implementer
    gate: {{type: external, command: "sh {script}"{timeout}}}
{on}"""

_ON_RETRY = "    on:\n      fail: {goto: build, max: 2}\n"


@contextmanager
def _seed(
    tmp_path: Path,
) -> Iterator[None]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        record_isolation_off(home)
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        _fleet.meta_set("demo-implementer", "codebase", str(tmp_path))
        # The member's own check must never run for an external gate.
        _fleet.meta_set("demo-implementer", "verifyCmd", f"touch {tmp_path / 'verifycmd-ran'}")
        yield


def _script(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "verifier.sh"
    path.write_text(body, encoding="utf-8")
    return path


def _spec(script: Path, on: str = "", timeout: str = "") -> _pipeline.PipelineSpec:
    loaded = _pipeline.load_pipeline(_PLAIN.format(script=script, on=on, timeout=timeout))
    assert loaded.ok, loaded.errors
    assert loaded.spec is not None
    return loaded.spec


@contextmanager
def _run(tmp_path: Path, body: str, **kw: str) -> Iterator[tuple[Any, FakeDriver]]:
    with _seed(tmp_path):
        script = _script(tmp_path, body)
        _queue.enqueue_task_once("demo", "Ship it", channel="cli")
        driver = FakeDriver()
        res = _sweep.dispatch_pod("demo", runner=driver, spec=_spec(script, **kw))[0]
        yield res, driver


def _build_hops(res: Any) -> list[Any]:
    return [h for h in res.hops if h.step_id == "build"]


def _reasons_script(payload: str, code: int) -> str:
    return f"cat > \"$DOCKET_GATE_REASONS_FILE\" <<'EOF'\n{payload}\nEOF\nexit {code}\n"


class TestExitMapping:
    def test_exit_zero_passes_and_runs_only_the_gate_command(self, tmp_path: Path) -> None:
        with _run(tmp_path, "echo fine\nexit 0\n") as (res, _driver):
            assert res.status == "done", res.reason
            verify = _build_hops(res)[0].verify
            assert verify["label"] == "pass"
            assert verify["exitCode"] == 0
            assert "fine" in verify["outputTail"]
            assert not (tmp_path / "verifycmd-ran").exists()

    def test_the_verifier_sees_the_task_coordinates(self, tmp_path: Path) -> None:
        body = 'echo "task=$DOCKET_TASK_ID file=$DOCKET_GATE_REASONS_FILE"\nexit 0\n'
        with _run(tmp_path, body) as (res, _driver):
            tail = _build_hops(res)[0].verify["outputTail"]
            assert f"task={res.task_id}" in tail
            path = _post_hop._gate_reasons_path("demo", res.task_id, "build")
            assert f"file={path}" in tail

    @pytest.mark.parametrize(
        ("code", "label", "kind"),
        [
            (1, "fail", "gate_failed"),
            (2, "needs_human", "gate_needs_human"),
            (7, "error", "gate_error"),
        ],
    )
    def test_an_unrouted_non_pass_fails_the_task_with_its_own_kind(
        self, tmp_path: Path, code: int, label: str, kind: str
    ) -> None:
        with _run(tmp_path, f"echo out\nexit {code}\n") as (res, _driver):
            assert res.status == "failed"
            assert res.failure_kind == kind
            verify = _build_hops(res)[0].verify
            assert verify["label"] == label
            assert verify["exitCode"] == code
            assert _queue.read_tasks("demo")[0]["failureKind"] == kind

    def test_the_exit_code_cannot_be_forged_from_inside_the_command(self, tmp_path: Path) -> None:
        # The command (agent-written tests, in practice) plants a "0" anywhere docket might read
        # a code from and makes it unwritable, then fails: the label comes from the process.
        body = (
            'for f in "$DOCKET_GATE_EXIT_FILE" "$DOCKET_GATE_REASONS_FILE.exit"; do\n'
            '  [ -n "$f" ] && printf 0 > "$f" && chmod 400 "$f"\n'
            "done\nexit 1\n"
        )
        with _run(tmp_path, body) as (res, _):
            assert res.status == "failed"
            assert _build_hops(res)[0].verify["label"] == "fail"
            assert _build_hops(res)[0].verify["exitCode"] == 1

    def test_a_timeout_is_error_not_fail(self, tmp_path: Path) -> None:
        with _run(tmp_path, "sleep 30\n", timeout=", timeout: 1") as (res, _driver):
            assert res.status == "failed"
            assert res.failure_kind == "gate_error"
            assert _build_hops(res)[0].verify["label"] == "error"

    def test_a_routed_error_is_not_an_unrouted_failure(self, tmp_path: Path) -> None:
        with _run(tmp_path, "exit 7\n", on="    on:\n      error: stop\n") as (res, _driver):
            assert res.status == "done"
            assert _build_hops(res)[0].verify["label"] == "error"

    def test_a_missing_command_is_error(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            spec = _pipeline.load_pipeline(
                "name: g\nsteps:\n  - id: build\n    role: implementer\n"
                "    gate: {external: 'definitely-not-a-command-zz9'}\n"
            ).spec
            assert spec is not None
            _queue.enqueue_task_once("demo", "Ship it", channel="cli")
            res = _sweep.dispatch_pod("demo", runner=FakeDriver(), spec=spec)[0]

            assert res.failure_kind in ("gate_error", "gate_failed")
            assert _build_hops(res)[0].verify["label"] == "error"


class TestReasons:
    def test_reasons_are_carried_into_the_retry_under_gate_failed(self, tmp_path: Path) -> None:
        payload = json.dumps(
            {
                "reasons": [
                    {"summary": REASON, "path": "src/a.py", "line": 12, "severity": "high"},
                    {"summary": "second", "detail": "more words"},
                ]
            }
        )
        flag = tmp_path / "flag"
        body = f"test -f {flag} && exit 0\ntouch {flag}\n" + _reasons_script(payload, 1)
        with _run(tmp_path, body, on=_ON_RETRY) as (res, driver):
            assert res.status == "done", res.reason
            first, second = _build_hops(res)
            assert first.verify["label"] == "fail"
            assert first.verify["reasons"][0]["summary"] == REASON
            assert "reasonsInvalid" not in first.verify or not first.verify["reasonsInvalid"]
            messages = _implementer_messages(driver)
            assert len(messages) == 2
            assert REASON not in messages[0]
            section = messages[1].split("--- GATE FAILED: build ---", 1)[1]
            assert REASON in section
            assert "src/a.py:12" in section
            assert "high" in section
            assert second.verify["label"] == "pass"

    @pytest.mark.parametrize(
        "payload",
        ["not json at all", '{"reasons": "nope"}', '{"reasons": [{"no_summary": 1}]}', "[1]"],
    )
    def test_unusable_reasons_set_reasons_invalid_and_the_tail_stands_in(
        self, tmp_path: Path, payload: str
    ) -> None:
        flag = tmp_path / "flag"
        body = f"test -f {flag} && exit 0\ntouch {flag}\necho {REASON}\n" + _reasons_script(
            payload, 1
        )
        with _run(tmp_path, body, on=_ON_RETRY) as (res, driver):
            first = _build_hops(res)[0]
            assert first.verify["reasonsInvalid"] is True
            assert "reasons" not in first.verify
            assert (
                REASON in _implementer_messages(driver)[1].split("--- GATE FAILED: build ---", 1)[1]
            )

    def test_reasons_over_64_kib_are_invalid(self, tmp_path: Path) -> None:
        body = (
            'printf \'{"reasons": [{"summary": "\' > "$DOCKET_GATE_REASONS_FILE"\n'
            "head -c 70000 /dev/zero | tr '\\0' 'a' >> \"$DOCKET_GATE_REASONS_FILE\"\n"
            'printf \'"}]}\' >> "$DOCKET_GATE_REASONS_FILE"\n'
            "echo tailtext\nexit 1\n"
        )
        with _run(tmp_path, body) as (res, _driver):
            verify = _build_hops(res)[0].verify
            assert verify["reasonsInvalid"] is True
            assert "reasons" not in verify
            assert "tailtext" in verify["outputTail"]

    def test_a_pre_existing_reasons_file_is_deleted_and_never_read(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            task = _queue.enqueue_task_once("demo", "Ship it", channel="cli")[0]
            planted = _post_hop._gate_reasons_path("demo", task["id"], "build")
            planted.parent.mkdir(parents=True, exist_ok=True)
            planted.write_text(json.dumps({"reasons": [{"summary": "PLANTED"}]}), encoding="utf-8")
            script = _script(
                tmp_path,
                'test -e "$DOCKET_GATE_REASONS_FILE" && echo STILL-THERE || echo GONE\nexit 1\n',
            )
            res = _sweep.dispatch_pod("demo", runner=FakeDriver(), spec=_spec(script))[0]

            verify = _build_hops(res)[0].verify
            assert "GONE" in verify["outputTail"]
            assert "reasons" not in verify
            assert not verify.get("reasonsInvalid")

    def test_reasons_are_redacted(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            canary = "zzqx-unleakable-reason-canary-77"
            _secrets.save_secrets({"LEAKY_KEY": canary})
            payload = json.dumps({"reasons": [{"summary": f"token {canary} leaked"}]})
            script = _script(tmp_path, _reasons_script(payload, 1))
            _queue.enqueue_task_once("demo", "Ship it", channel="cli")
            res = _sweep.dispatch_pod("demo", runner=FakeDriver(), spec=_spec(script))[0]

            persisted = json.dumps(_queue.read_tasks("demo")[0]["hops"])
            assert canary not in persisted
            assert "[REDACTED]" in persisted
            assert res.status == "failed"

    def test_reasons_pass_the_untrusted_content_screen(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.agent.tools import screening as _tools

        seen: list[str] = []
        real = _tools.screen_tool_result

        def spy(role: str, outcome: Any, **kw: Any) -> Any:
            seen.append(outcome.content or outcome.error)
            return real(role, outcome, **kw)

        monkeypatch.setattr(_tools, "screen_tool_result", spy)
        payload = json.dumps({"reasons": [{"summary": REASON}]})
        with _run(tmp_path, _reasons_script(payload, 1)):
            assert any(REASON in text for text in seen)


def _bind(project: str, text: str) -> None:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    path = _pod.pod.bound_pipeline_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _fleet.meta_set(_pod.pod.member_id(project, "lead"), "pipeline", digest)


_SEAM = """\
name: seam
steps:
  - id: plan
    role: lead
  - build: implementer
    gate: {{external: "sh {script}"}}
    on:
      pass: stop
      fail: {{goto: build, max: 2}}
      needs_human: ask
  - id: ask
    input: {{from: build}}
    on:
      answered: {{goto: build, max: 1}}
      declined: fail
"""


class TestNeedsHumanSeam:
    """Real code on both sides: the gate parks the task on an ``input`` step, the real
    ``answer_task`` reopens it, and the retry's message still carries the gate's reasons."""

    def test_reasons_survive_the_input_steps_answer_and_resume(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            flag = tmp_path / "flag"
            payload = json.dumps({"reasons": [{"summary": REASON, "path": "x.py", "line": 3}]})
            script = _script(
                tmp_path, f"test -f {flag} && exit 0\ntouch {flag}\n" + _reasons_script(payload, 2)
            )
            _bind("demo", _SEAM.format(script=script))
            task = _queue.enqueue_task_once("demo", "Ship it", channel="cli")[0]
            driver = FakeDriver()

            first = _sweep.dispatch_pod("demo", runner=driver)[0]
            assert first.status == "waiting_input", first.reason
            assert len(_implementer_messages(driver)) == 1

            _answers.answer_task(
                "demo", task["id"], "accept", {"answer": "go"}, channel="cli", actor="op"
            )
            final = _sweep.dispatch_pod("demo", runner=driver)[0]

            assert final.status == "done", final.reason
            messages = _implementer_messages(driver)
            assert len(messages) == 2
            section = messages[1].split("--- GATE FAILED: build ---", 1)[1]
            assert REASON in section
            assert "x.py:3" in section

    def test_the_question_shows_the_gate_reasons_and_the_answer_reaches_the_retry(
        self, tmp_path: Path
    ) -> None:
        with _seed(tmp_path):
            flag = tmp_path / "flag"
            payload = json.dumps({"reasons": [{"summary": REASON}]})
            script = _script(
                tmp_path, f"test -f {flag} && exit 0\ntouch {flag}\n" + _reasons_script(payload, 2)
            )
            _bind("demo", _SEAM.format(script=script))
            task = _queue.enqueue_task_once("demo", "Ship it", channel="cli")[0]
            driver = FakeDriver()

            _sweep.dispatch_pod("demo", runner=driver)
            question = _queue.read_tasks("demo")[0]["question"]
            assert REASON in question["message"], "the operator must see why the verifier asked"

            note = "zz-operator-note-8812"
            _answers.answer_task(
                "demo", task["id"], "accept", {"answer": note}, channel="cli", actor="op"
            )
            _sweep.dispatch_pod("demo", runner=driver)
            retry = _implementer_messages(driver)[1].split("--- GATE FAILED: build ---", 1)[1]
            assert note in retry, "the answer must reach the hop it routes back to"

    def test_a_declined_answer_fails_the_task(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            script = _script(tmp_path, "exit 2\n")
            _bind("demo", _SEAM.format(script=script))
            task = _queue.enqueue_task_once("demo", "Ship it", channel="cli")[0]
            driver = FakeDriver()

            assert _sweep.dispatch_pod("demo", runner=driver)[0].status == "waiting_input"
            _answers.answer_task("demo", task["id"], "decline", None, channel="cli", actor="op")

            persisted = _queue.read_tasks("demo")[0]
            assert persisted["status"] == "failed"


def test_the_gate_a_dispatch_ran_is_the_gate_evidence_reports(tmp_path: Path) -> None:
    # Seam: dispatch writes hop.verify, evidence 1.1.0 reads it back; real code on both sides.
    from docket.tasks.application import evidence as _evidence

    with _run(tmp_path, "echo broke\nexit 1\n") as (res, _):
        doc = _evidence.task_evidence("demo", res.task_id, "1.1.0").model_dump(by_alias=True)
        gates = [h["gate"] for h in doc["hops"] if "gate" in h]
        assert gates == [{"label": "fail", "exitCode": 1, "reasonsInvalid": False}]
