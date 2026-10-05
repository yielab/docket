"""Operator events and their delivery (`core/notify.py`).

Covers the pure diff/render functions (`diff_events`, `render_data`, `render_text`,
`build_test_event`) and the impure `flush` orchestrator (dedupe across two flushes, the
content-level canary, and delivery failure bookkeeping), against a fake `sink_for` -- never a
real channel adapter.
"""

from __future__ import annotations

import types
from typing import Any

import pytest

from docket.core import notify as _notify
from docket.core.operator_contract import (
    ApprovalView,
    InboxView,
    Question,
    QuestionV11,
    TaskBrief,
    TaskView,
)

SUBJECT = "docket.core.notify"


def _task(
    *,
    id: str = "t1",
    pod: str = "alpha",
    status: str = "waiting_input",
    reason: str | None = None,
    question: Question | None = None,
    approval_token: str | None = None,
    a2a_state: str = "INPUT_REQUIRED",
    brief: TaskBrief | None = None,
) -> TaskView:
    return TaskView(
        id=id,
        pod=pod,
        status=status,
        a2a_state=a2a_state,
        reason=reason,
        question=question,
        approval_token=approval_token,
        brief=brief,
    )


def _approval(
    *,
    token: str = "tok-1",
    pod: str = "alpha",
    role: str = "implementer",
    action: str = "git push origin main",
    policy: str = "prod-approval",
    state: str = "pending",
    created_at: str = "",
    expires_at: str | None = None,
) -> ApprovalView:
    return ApprovalView(
        token=token,
        pod=pod,
        role=role,
        action=action,
        policy=policy,
        state=state,
        created_at=created_at,
        expires_at=expires_at,
    )


def _question(id: str = "q-abc123456789") -> Question:
    return Question(
        id=id,
        task_id="t1",
        pod="alpha",
        step="implementer",
        message="Which environment?",
        requested_schema={"type": "object", "properties": {"env": {"type": "string"}}},
        created_at="2026-09-28T00:00:00Z",
    )


class TestDiffEventsPure:
    def test_new_waiting_input_task_emits_task_input_required(self) -> None:
        inbox = InboxView(needs_you=[_task()])
        events, snapshot = _notify.diff_events({}, inbox, now="2026-09-28T00:00:00Z")
        assert [e.kind for e in events] == ["task.input_required"]
        assert snapshot["items"]["task:alpha:t1"] == "waiting_input:"

    def test_unchanged_item_emits_nothing_on_second_diff(self) -> None:
        inbox = InboxView(needs_you=[_task()])
        _events, snapshot = _notify.diff_events({}, inbox, now="2026-09-28T00:00:00Z")
        events2, _snapshot2 = _notify.diff_events(snapshot, inbox, now="2026-09-28T00:01:00Z")
        assert events2 == []

    def test_waiting_approval_task_emits_approval_requested(self) -> None:
        inbox = InboxView(needs_you=[_task(status="waiting_approval", approval_token="tok-9")])
        events, _snapshot = _notify.diff_events({}, inbox, now="2026-09-28T00:00:00Z")
        assert [e.kind for e in events] == ["approval.requested"]

    def test_standalone_approval_emits_approval_requested_once(self) -> None:
        inbox = InboxView(needs_you=[_approval()])
        events, snapshot = _notify.diff_events({}, inbox, now="2026-09-28T00:00:00Z")
        assert len(events) == 1
        assert events[0].kind == "approval.requested"
        assert events[0].subject == "approval:tok-1"
        events2, _snapshot2 = _notify.diff_events(snapshot, inbox, now="2026-09-28T00:01:00Z")
        assert events2 == []

    def test_new_question_on_the_same_task_emits_again(self) -> None:
        inbox1 = InboxView(needs_you=[_task(question=_question("q-first0000"))])
        _events1, snapshot1 = _notify.diff_events({}, inbox1, now="2026-09-28T00:00:00Z")
        inbox2 = InboxView(needs_you=[_task(question=_question("q-second0000"))])
        events2, _snapshot2 = _notify.diff_events(snapshot1, inbox2, now="2026-09-28T00:01:00Z")
        assert [e.kind for e in events2] == ["task.input_required"]

    def test_failed_task_maps_rejected_vs_failed(self) -> None:
        rejected = _task(status="failed", a2a_state="REJECTED")
        failed = _task(id="t2", status="failed", a2a_state="FAILED")
        events, _snapshot = _notify.diff_events(
            {}, InboxView(failed=[rejected, failed]), now="2026-09-28T00:00:00Z"
        )
        kinds = {e.subject: e.kind for e in events}
        assert kinds["task:alpha:t1"] == "task.rejected"
        assert kinds["task:alpha:t2"] == "task.failed"

    def test_done_since_task_emits_task_completed(self) -> None:
        inbox = InboxView(done_since=[_task(status="done", a2a_state="COMPLETED")])
        events, _snapshot = _notify.diff_events({}, inbox, now="2026-09-28T00:00:00Z")
        assert [e.kind for e in events] == ["task.completed"]

    def test_approval_expiring_fires_once_at_80_percent(self) -> None:
        approval = _approval(created_at="2026-09-28T00:00:00Z", expires_at="2026-09-28T00:10:00Z")
        inbox = InboxView(needs_you=[approval])
        events_early, _snap_early = _notify.diff_events({}, inbox, now="2026-09-28T00:05:00Z")
        assert "approval.expiring" not in [e.kind for e in events_early]

        events_late, snapshot_late = _notify.diff_events({}, inbox, now="2026-09-28T00:08:30Z")
        expiring_kinds = [e.kind for e in events_late if e.kind == "approval.expiring"]
        assert len(expiring_kinds) == 1
        assert "tok-1" in snapshot_late["expiring"]

        events_again, _snap_again = _notify.diff_events(
            snapshot_late, inbox, now="2026-09-28T00:09:00Z"
        )
        assert "approval.expiring" not in [e.kind for e in events_again]


class TestRenderDataContentLevels:
    def test_approval_minimal_never_carries_the_command(self) -> None:
        approval = _approval(action="git push origin CANARY_7f3")
        data = _notify.render_data(approval, "minimal")
        assert "action" not in data
        assert "CANARY_7f3" not in repr(data)

    def test_approval_actions_carries_the_command(self) -> None:
        approval = _approval(action="git push origin CANARY_7f3")
        data = _notify.render_data(approval, "actions")
        assert data["action"] == "git push origin CANARY_7f3"

    def test_task_minimal_never_carries_the_question_text(self) -> None:
        task = _task(question=_question())
        data = _notify.render_data(task, "minimal")
        assert "question" not in data
        assert "Which environment?" not in repr(data)
        assert data["questionId"] == "q-abc123456789"

    def test_task_conversation_carries_the_question_and_brief(self) -> None:
        brief = TaskBrief(objective="Ship the thing")
        task = _task(question=_question(), brief=brief)
        data = _notify.render_data(task, "conversation")
        assert data["question"] == "Which environment?"
        assert data["brief"]["objective"] == "Ship the thing"

    def test_task_actions_still_omits_the_question(self) -> None:
        task = _task(question=_question())
        data = _notify.render_data(task, "actions")
        assert "question" not in data


def _consult_question(label: str = "Iterative") -> QuestionV11:
    return QuestionV11.model_validate(
        {
            "id": "q-consult00001",
            "taskId": "t1",
            "pod": "alpha",
            "step": "implementer",
            "message": "Which design?",
            "requestedSchema": {"type": "object", "properties": {"note": {"type": "string"}}},
            "createdAt": "2026-10-05T00:00:00Z",
            "kind": "decision",
            "options": [
                {"id": "iterative", "label": label, "description": "SECRETDESC"},
                {"id": "bigbang", "label": "Big bang", "description": "all"},
            ],
            "recommendation": {"optionId": "iterative", "rationale": "SECRETWHY"},
        }
    )


class TestRenderOptions:
    def test_conversation_carries_options_and_recommendation_id_only(self) -> None:
        data = _notify.render_data(_task(question=_consult_question()), "conversation")
        assert data["options"] == [
            {"id": "iterative", "label": "Iterative"},
            {"id": "bigbang", "label": "Big bang"},
        ]
        assert data["recommendation"] == {"optionId": "iterative"}
        assert "SECRETWHY" not in repr(data)
        assert "SECRETDESC" not in repr(data)

    @pytest.mark.parametrize("level", ["minimal", "actions"])
    def test_lower_levels_carry_neither(self, level: str) -> None:
        data = _notify.render_data(_task(question=_consult_question()), level)
        assert "options" not in data
        assert "recommendation" not in data
        assert "Iterative" not in repr(data)

    def test_a_plain_question_adds_no_options(self) -> None:
        data = _notify.render_data(_task(question=_question()), "conversation")
        assert "options" not in data
        assert "recommendation" not in data

    def test_labels_lose_control_characters_and_are_truncated(self) -> None:
        label = "A\x1b[31mB\nC" + "x" * 500
        data = _notify.render_data(_task(question=_consult_question(label)), "conversation")
        shown = data["options"][0]["label"]
        assert "\x1b" not in shown
        assert "\n" not in shown
        assert len(shown) <= 80

    def test_text_lists_each_option_marks_the_recommended_and_names_the_reply(self) -> None:
        data = _notify.render_data(_task(question=_consult_question()), "conversation")
        event = _notify.make_event(
            "task.input_required",
            "alpha",
            "task:alpha:t1",
            data,
            time="2026-10-05T00:00:00Z",
            version="v",
        )
        _title, body = _notify.render_text(event)
        assert "iterative - Iterative (recommended)" in body
        assert "bigbang - Big bang" in body
        assert "reply: /answer t1 <id>" in body

    def test_minimal_text_has_no_option_lines(self) -> None:
        data = _notify.render_data(_task(question=_consult_question()), "minimal")
        event = _notify.make_event(
            "task.input_required",
            "alpha",
            "task:alpha:t1",
            data,
            time="2026-10-05T00:00:00Z",
            version="v",
        )
        _title, body = _notify.render_text(event)
        assert "iterative" not in body
        assert "/answer" not in body


class TestRenderTextAndTestEvent:
    def test_render_text_includes_available_fields(self) -> None:
        approval = _approval(action="git push origin main")
        event = _notify.make_event(
            "approval.requested",
            "alpha",
            "approval:tok-1",
            _notify.render_data(approval, "actions"),
            time="2026-09-28T00:00:00Z",
            version="pending:tok-1",
        )
        title, body = _notify.render_text(event)
        assert "approval.requested" in title
        assert "git push origin main" in body

    def test_build_test_event_shape(self) -> None:
        spec = types.SimpleNamespace(name="webhook")
        event = _notify.build_test_event(spec, now="2026-09-28T00:00:00Z")
        assert event.type == "dev.docket.channel.test"
        assert event.subject == "channel:webhook"
        assert event.data["channel"] == "webhook"


def _spec(
    *,
    name: str = "chan",
    dialect: str = "fake",
    enabled: bool = True,
    capabilities: list[str] | None = None,
    on: list[str] | None = None,
    content: str = "minimal",
    secret: str | None = None,
) -> Any:
    return types.SimpleNamespace(
        name=name,
        dialect=dialect,
        enabled=enabled,
        capabilities=capabilities if capabilities is not None else ["notify"],
        on=on if on is not None else ["needs_you"],
        content=content,
        secret=secret,
    )


class _RecordingDeliver:
    def __init__(self, ok: bool = True, error: str = "") -> None:
        self.ok = ok
        self.error = error
        self.calls: list[Any] = []

    def __call__(self, spec: Any, event: Any, *, secret: str | None, timeout: float) -> Any:
        self.calls.append((spec, event, secret, timeout))
        return types.SimpleNamespace(ok=self.ok, error=self.error)


class TestFlush:
    def _patch_inbox(self, monkeypatch: pytest.MonkeyPatch, inbox: InboxView) -> None:
        from docket.core import inbox as _inbox_mod

        monkeypatch.setattr(_inbox_mod, "build_inbox", lambda **_kw: inbox)

    def test_two_flushes_over_the_same_state_deliver_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        inbox = InboxView(needs_you=[_approval()])
        self._patch_inbox(monkeypatch, inbox)
        deliver = _RecordingDeliver(ok=True)
        report1 = _notify.flush([_spec()], lambda _spec: deliver, now="2026-09-28T00:00:00Z")
        assert report1.events == 1
        assert report1.delivered == 1

        report2 = _notify.flush([_spec()], lambda _spec: deliver, now="2026-09-28T00:01:00Z")
        assert report2.events == 0
        assert report2.delivered == 0
        assert len(deliver.calls) == 1

    def test_new_parked_approval_yields_exactly_one_approval_requested(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        inbox = InboxView(needs_you=[_approval(token="tok-parked")])
        self._patch_inbox(monkeypatch, inbox)
        deliver = _RecordingDeliver(ok=True)
        _notify.flush([_spec()], lambda _spec: deliver, now="2026-09-28T00:00:00Z")
        assert len(deliver.calls) == 1
        sent_event = deliver.calls[0][1]
        assert sent_event.type == "dev.docket.approval.requested"

    def test_content_level_canary_across_two_channels(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        approval = _approval(action="git push origin CANARY_7f3")
        self._patch_inbox(monkeypatch, InboxView(needs_you=[approval]))
        deliver = _RecordingDeliver(ok=True)
        minimal_spec = _spec(name="minimal-chan", content="minimal")
        actions_spec = _spec(name="actions-chan", content="actions")
        _notify.flush(
            [minimal_spec, actions_spec], lambda _spec: deliver, now="2026-09-28T00:00:00Z"
        )
        assert len(deliver.calls) == 2
        by_channel = {call[0].name: call[1] for call in deliver.calls}
        assert "CANARY_7f3" not in repr(by_channel["minimal-chan"].data)
        assert by_channel["actions-chan"].data["action"] == "git push origin CANARY_7f3"

    def test_failed_delivery_is_recorded_and_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_inbox(monkeypatch, InboxView(needs_you=[_approval()]))
        deliver = _RecordingDeliver(ok=False, error="connection refused")
        report = _notify.flush(
            [_spec()],
            lambda _spec: deliver,
            now="2026-09-28T00:00:00Z",
            sleep=lambda _seconds: None,
        )
        assert report.failed == 1
        assert report.delivered == 0
        import docket.config as _cfg
        from docket.edges import store as _store

        health = _store.read_json(_cfg.CHANNELS_HEALTH_FILE)
        assert health["chan"]["lastError"] == "connection refused"
        # never retried on a later flush -- the snapshot was already saved
        report2 = _notify.flush([_spec()], lambda _spec: deliver, now="2026-09-28T00:01:00Z")
        assert report2.events == 0

    def test_a_dialect_with_no_sink_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_inbox(monkeypatch, InboxView(needs_you=[_approval()]))
        report = _notify.flush([_spec()], lambda _spec: None, now="2026-09-28T00:00:00Z")
        assert report.skipped == 1
        assert report.delivered == 0

    def test_disabled_or_non_notify_channel_receives_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_inbox(monkeypatch, InboxView(needs_you=[_approval()]))
        deliver = _RecordingDeliver(ok=True)
        disabled = _spec(name="off", enabled=False)
        no_notify = _spec(name="decide-only", capabilities=["decide"])
        report = _notify.flush(
            [disabled, no_notify], lambda _spec: deliver, now="2026-09-28T00:00:00Z"
        )
        assert report.events == 1
        assert deliver.calls == []
