"""Operator events and their delivery (`operator/notify.py`).

Covers the pure diff/render functions (`diff_events`, `render_data`, `render_text`,
`build_test_event`) and the impure `flush` orchestrator (dedupe across two flushes, the
content-level canary, and delivery failure bookkeeping), against a fake `sink_for` -- never a
real channel adapter.
"""

from __future__ import annotations

import types
from typing import Any

import pytest

from docket.kernel.brief import TaskBrief
from docket.kernel.home import current_home
from docket.kernel.operator_contract import (
    EscalationAffordances,
    EscalationView,
    InboxView,
    QuestionV11,
    Resolution,
    TaskView,
)
from docket.operator import notify as _notify

SUBJECT = "docket.operator.notify"


def _task(
    *,
    id: str = "t1",
    pod: str = "alpha",
    status: str = "waiting_input",
    reason: str | None = None,
    escalation: str | None = None,
    a2a_state: str = "INPUT_REQUIRED",
    brief: TaskBrief | None = None,
) -> TaskView:
    return TaskView(
        id=id,
        pod=pod,
        status=status,
        a2a_state=a2a_state,
        reason=reason,
        escalation=escalation,
        brief=brief,
    )


def _approval(
    *,
    id: str = "esc-aaaaaaaaaaaa",
    pod: str = "alpha",
    role: str = "implementer",
    action: str = "git push origin main",
    created_at: str = "2026-09-28T00:00:00Z",
    expires_at: str | None = None,
    task: str = "",
) -> EscalationView:
    """A pending approval escalation, standalone unless it names a *task*."""
    return EscalationView.model_validate(
        {
            "id": id,
            "task": task,
            "pod": pod,
            "step": "",
            "role": role,
            "kind": "approval",
            "causedBy": "c1",
            "prompt": action,
            "options": [
                {"id": "approve_once", "label": "Approve once", "description": "x"},
                {"id": "approve_task", "label": "Approve for this task", "description": "x"},
                {"id": "deny", "label": "Deny", "description": "x"},
            ],
            "askedAt": created_at,
            "expiresAt": expires_at,
            "onExpiry": "deny",
            "affordances": {"resolveUrl": f"/escalations/{id}"},
        }
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
        inbox = InboxView(
            needs_you=[_task(status="waiting_approval", escalation="esc-bbbbbbbbbbbb")]
        )
        events, _snapshot = _notify.diff_events({}, inbox, now="2026-09-28T00:00:00Z")
        assert [e.kind for e in events] == ["approval.requested"]

    def test_standalone_approval_emits_approval_requested_once(self) -> None:
        inbox = InboxView(needs_you=[_approval()])
        events, snapshot = _notify.diff_events({}, inbox, now="2026-09-28T00:00:00Z")
        assert len(events) == 1
        assert events[0].kind == "approval.requested"
        assert events[0].subject == "escalation:esc-aaaaaaaaaaaa"
        events2, _snapshot2 = _notify.diff_events(snapshot, inbox, now="2026-09-28T00:01:00Z")
        assert events2 == []

    def test_new_question_on_the_same_task_emits_again(self) -> None:
        inbox1 = InboxView(needs_you=[_task(escalation="esc-111111111111")])
        _events1, snapshot1 = _notify.diff_events({}, inbox1, now="2026-09-28T00:00:00Z")
        inbox2 = InboxView(needs_you=[_task(escalation="esc-222222222222")])
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
        assert "esc-aaaaaaaaaaaa" in snapshot_late["expiring"]

        events_again, _snap_again = _notify.diff_events(
            snapshot_late, inbox, now="2026-09-28T00:09:00Z"
        )
        assert "approval.expiring" not in [e.kind for e in events_again]


def _decided(*, id: str = "esc-0123456789ab", level: str = "L5") -> EscalationView:
    return EscalationView(
        id=id,
        task="t1",
        pod="alpha",
        step="implement",
        role="implementer",
        kind="approval",
        caused_by="c1",
        prompt="git push origin main",
        asked_at="2026-09-28T00:00:00Z",
        on_expiry="deny",
        policy="deny",
        level=level,  # type: ignore[arg-type]
        state="decided",
        resolution=Resolution(option_id="deny", by="policy", channel="policy", at="2026-09-28Z"),
        affordances=EscalationAffordances(options=[], accepts_text=False, resolve_url=f"/{id}"),
    )


class TestDecidedEvents:
    def test_a_decision_the_pod_took_alone_emits_escalation_decided_once(self) -> None:
        inbox = InboxView(decided=[_decided()])

        events, snapshot = _notify.diff_events({}, inbox, now="2026-09-28T00:00:00Z")
        again, _ = _notify.diff_events(snapshot, inbox, now="2026-09-28T00:01:00Z")

        assert [(e.kind, e.pod, e.subject) for e in events] == [
            ("escalation.decided", "alpha", "escalation:esc-0123456789ab")
        ]
        assert again == []

    @pytest.mark.parametrize("level", ["minimal", "actions", "conversation"])
    def test_the_data_names_the_task_the_option_and_the_level_at_every_content_level(
        self, level: str
    ) -> None:
        (event,), _ = _notify.diff_events(
            {}, InboxView(decided=[_decided()]), now="2026-09-28T00:00:00Z"
        )

        data = _notify.render_data(event.item, level)

        assert data == {
            "pod": "alpha",
            "taskId": "t1",
            "escalationId": "esc-0123456789ab",
            "kind": "approval",
            "optionId": "deny",
            "level": "L5",
        }

    def test_the_text_says_what_was_decided_and_at_which_level(self) -> None:
        (event,), _ = _notify.diff_events(
            {}, InboxView(decided=[_decided()]), now="2026-09-28T00:00:00Z"
        )
        cloud = _notify.make_event(
            event.kind,
            event.pod,
            event.subject,
            _notify.render_data(event.item, "minimal"),
            time="t0",
            version="v1",
        )

        title, body = _notify.render_text(cloud)

        assert title == "docket: escalation.decided (alpha)"
        assert body == "task t1 -- approval decided deny at L5"

    def test_needs_you_does_not_hear_it_but_naming_the_kind_does(self) -> None:
        listens = types.SimpleNamespace(on=["escalation.decided"])
        needs_you = types.SimpleNamespace(on=["needs_you"])

        assert _notify._matches_on(listens, "escalation.decided") is True
        assert _notify._matches_on(needs_you, "escalation.decided") is False

    def test_a_channel_scoped_to_another_task_does_not_hear_it(self) -> None:
        scoped = types.SimpleNamespace(config={"scopeTask": "t9", "scopePod": "alpha"})

        assert _notify._in_scope(scoped, _decided()) is False
        assert _notify._in_scope(types.SimpleNamespace(config={}), _decided()) is True


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

    def test_a_pending_approval_names_itself_and_how_to_answer_it(self) -> None:
        data = _notify.render_data(_approval(), "minimal")
        assert data["escalationId"] == "esc-aaaaaaaaaaaa"
        assert data["respond"] == {
            "cli": "docket task answer esc-aaaaaaaaaaaa",
            "http": "/escalations/esc-aaaaaaaaaaaa",
        }
        assert "token" not in data
        assert [o["id"] for o in data["options"]] == ["approve_once", "approve_task", "deny"]

    def test_task_minimal_never_carries_the_question_text(self) -> None:
        task = _task(escalation="esc-0123456789ab")
        data = _notify.render_data(task, "minimal", _escalation_view())
        assert "question" not in data
        assert "Which design?" not in repr(data)
        assert data["escalationId"] == "esc-0123456789ab"

    def test_task_conversation_carries_the_question_and_brief(self) -> None:
        brief = TaskBrief(objective="Ship the thing")
        task = _task(escalation="esc-0123456789ab", brief=brief)
        data = _notify.render_data(task, "conversation", _escalation_view())
        assert data["question"] == "Which design?"
        assert data["brief"]["objective"] == "Ship the thing"

    def test_task_actions_still_omits_the_question(self) -> None:
        task = _task(escalation="esc-0123456789ab")
        data = _notify.render_data(task, "actions", _escalation_view())
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


def _escalation_view() -> EscalationView:
    question = _consult_question()
    return EscalationView.model_validate(
        {
            "id": "esc-0123456789ab",
            "task": "t1",
            "pod": "alpha",
            "step": "implementer",
            "role": "implementer",
            "kind": "consult",
            "causedBy": "c1",
            "prompt": question.message,
            "options": [
                *(o.model_dump(by_alias=True) for o in question.options),
                {"id": "decline", "label": "Decline", "description": "no"},
            ],
            "recommendation": question.recommendation.model_dump(by_alias=True),
            "askedAt": "2026-10-05T00:00:00Z",
            "onExpiry": "block",
            "affordances": {"resolveUrl": "/escalations/esc-0123456789ab"},
        }
    )


class TestRenderOptions:
    def _view(self, label: str = "Iterative") -> EscalationView:
        view = _escalation_view()
        options = [
            o.model_copy(update={"label": label}) if o.id == "iterative" else o
            for o in view.options
        ]
        return view.model_copy(update={"options": options})

    def test_conversation_carries_options_and_recommendation_id_only(self) -> None:
        data = _notify.render_data(
            _task(escalation="esc-0123456789ab"), "conversation", self._view()
        )
        assert data["options"] == [
            {"id": "iterative", "label": "Iterative"},
            {"id": "bigbang", "label": "Big bang"},
        ]
        assert data["recommendation"] == {"optionId": "iterative"}
        assert "SECRETWHY" not in repr(data)
        assert "SECRETDESC" not in repr(data)

    @pytest.mark.parametrize("level", ["minimal", "actions"])
    def test_lower_levels_carry_the_option_ids_and_nothing_else(self, level: str) -> None:
        data = _notify.render_data(_task(escalation="esc-0123456789ab"), level, self._view())
        assert data["options"] == [{"id": "iterative"}, {"id": "bigbang"}]
        assert data["recommendation"] == {"optionId": "iterative"}
        assert "Iterative" not in repr(data)
        assert "question" not in data
        assert "SECRETWHY" not in repr(data)

    def test_decline_is_never_one_of_the_options(self) -> None:
        data = _notify.render_data(
            _task(escalation="esc-0123456789ab"), "conversation", self._view()
        )
        assert "decline" not in repr(data)

    def test_a_task_with_no_pending_escalation_adds_no_options(self) -> None:
        data = _notify.render_data(_task(), "conversation")
        assert "options" not in data
        assert "recommendation" not in data
        assert "escalationId" not in data

    def test_labels_lose_control_characters_and_are_truncated(self) -> None:
        label = "A\x1b[31mB\nC" + "x" * 500
        data = _notify.render_data(
            _task(escalation="esc-0123456789ab"), "conversation", self._view(label)
        )
        shown = data["options"][0]["label"]
        assert "\x1b" not in shown
        assert "\n" not in shown
        assert len(shown) <= 80

    def test_text_lists_each_option_marks_the_recommended_and_names_the_reply(self) -> None:
        data = _notify.render_data(
            _task(escalation="esc-0123456789ab"), "conversation", self._view()
        )
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
        assert "reply: /answer esc-0123456789ab <id>" in body

    def test_minimal_text_names_the_ids_to_reply_with_but_no_label(self) -> None:
        data = _notify.render_data(_task(escalation="esc-0123456789ab"), "minimal", self._view())
        event = _notify.make_event(
            "task.input_required",
            "alpha",
            "task:alpha:t1",
            data,
            time="2026-10-05T00:00:00Z",
            version="v",
        )
        _title, body = _notify.render_text(event)
        assert "iterative (recommended)" in body
        assert "bigbang" in body
        assert "Iterative" not in body and "Big bang" not in body
        assert "reply: /answer esc-0123456789ab <id>" in body


class TestRenderTextAndTestEvent:
    def test_render_text_includes_available_fields(self) -> None:
        approval = _approval(action="git push origin main")
        event = _notify.make_event(
            "approval.requested",
            "alpha",
            "escalation:esc-aaaaaaaaaaaa",
            _notify.render_data(approval, "actions"),
            time="2026-09-28T00:00:00Z",
            version="pending",
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
    config: dict[str, str] | None = None,
) -> Any:
    return types.SimpleNamespace(
        config=config or {},
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
        from docket.operator import inbox as _inbox_mod

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
        inbox = InboxView(needs_you=[_approval(id="esc-cccccccccccc")])
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

    def test_a_channel_scoped_to_a_task_hears_only_that_task(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mine, other = _task(id="t1"), _task(id="t2")
        self._patch_inbox(monkeypatch, InboxView(needs_you=[mine, other, _approval()]))
        deliver = _RecordingDeliver(ok=True)
        scoped = _spec(name="scoped", config={"scopeTask": "t1", "scopePod": "alpha"})
        elsewhere = _spec(name="elsewhere", config={"scopeTask": "t1", "scopePod": "beta"})
        everything = _spec(name="everything")

        _notify.flush(
            [scoped, elsewhere, everything], lambda _spec: deliver, now="2026-09-28T00:00:00Z"
        )

        heard = sorted(
            (c[0].name, c[1].data.get("taskId") or c[1].data.get("escalationId"))
            for c in deliver.calls
        )
        assert heard == [
            ("everything", "esc-aaaaaaaaaaaa"),
            ("everything", "t1"),
            ("everything", "t2"),
            ("scoped", "t1"),
        ]

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
        from docket.platform import store as _store

        health = _store.read_json(current_home().channels_health_file)
        assert health["chan"]["lastError"] == "connection refused"
        # never retried on a later flush -- the snapshot was already saved
        report2 = _notify.flush([_spec()], lambda _spec: deliver, now="2026-09-28T00:01:00Z")
        assert report2.events == 0

    def test_an_inbox_that_raises_comes_back_as_an_error_not_an_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.operator import inbox as _inbox_mod

        def _boom(**_kw: Any) -> InboxView:
            raise OSError("pods dir unreadable")

        monkeypatch.setattr(_inbox_mod, "build_inbox", _boom)
        report = _notify.flush([_spec()], lambda _spec: None, now="2026-09-28T00:00:00Z")
        assert "pods dir unreadable" in report.error
        assert report.events == 0

    def test_a_snapshot_store_that_raises_comes_back_as_an_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_inbox(monkeypatch, InboxView(needs_you=[_approval()]))

        def _boom(_snapshot: dict[str, Any]) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(_notify, "_save_state", _boom)
        report = _notify.flush([_spec()], lambda _spec: None, now="2026-09-28T00:00:00Z")
        assert "disk full" in report.error

    def test_a_sink_factory_that_raises_fails_that_channel_and_the_others_still_deliver(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_inbox(monkeypatch, InboxView(needs_you=[_approval()]))
        deliver = _RecordingDeliver(ok=True)

        def _sink(spec: Any) -> Any:
            if spec.name == "broken":
                raise RuntimeError("no such dialect module")
            return deliver

        report = _notify.flush(
            [_spec(name="broken"), _spec(name="good")], _sink, now="2026-09-28T00:00:00Z"
        )
        assert (report.failed, report.delivered, report.error) == (1, 1, "")

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


class TestEscalationDelivered:
    """`flush` says which escalation a delivered notification carried: the trace gets
    `escalation_delivered` with the channel, and the event's data names the escalation."""

    def _store(self) -> None:
        from docket.kernel.operator_contract import Escalation
        from docket.platform import write_escalation

        view = _escalation_view()
        record = Escalation.model_validate(view.model_dump(by_alias=True, exclude={"affordances"}))
        write_escalation(record)

    def _inbox(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from docket.operator import inbox as _inbox_mod

        task = _task(escalation="esc-0123456789ab")
        inbox = InboxView(needs_you=[task], escalations=[_escalation_view()])
        monkeypatch.setattr(_inbox_mod, "build_inbox", lambda **_kw: inbox)

    def _delivered(self) -> list[dict[str, Any]]:
        from tests.support.trace import trace_events

        return [e for e in trace_events("alpha") if e["event_type"] == "escalation_delivered"]

    def test_a_delivered_notification_traces_the_escalation_and_the_channel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._store()
        self._inbox(monkeypatch)
        deliver = _RecordingDeliver(ok=True)

        _notify.flush([_spec(name="ntfy-main")], lambda _spec: deliver, now="2026-09-28T00:00:00Z")

        (sent,) = deliver.calls
        assert sent[1].data["escalationId"] == "esc-0123456789ab"
        (event,) = self._delivered()
        assert event["payload"]["escalation"] == "esc-0123456789ab"
        assert (event["payload"]["channel"], event["task_id"]) == ("ntfy-main", "t1")

    def test_each_channel_that_delivers_traces_its_own_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._store()
        self._inbox(monkeypatch)
        deliver = _RecordingDeliver(ok=True)

        _notify.flush(
            [_spec(name="one"), _spec(name="two")],
            lambda _spec: deliver,
            now="2026-09-28T00:00:00Z",
        )

        assert sorted(e["payload"]["channel"] for e in self._delivered()) == ["one", "two"]

    def test_a_failed_delivery_traces_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._store()
        self._inbox(monkeypatch)
        deliver = _RecordingDeliver(ok=False, error="boom")

        _notify.flush(
            [_spec()], lambda _spec: deliver, now="2026-09-28T00:00:00Z", sleep=lambda s: None
        )

        assert self._delivered() == []

    def test_a_notification_that_names_no_escalation_traces_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.operator import inbox as _inbox_mod

        inbox = InboxView(needs_you=[_task(status="blocked")])
        monkeypatch.setattr(_inbox_mod, "build_inbox", lambda **_kw: inbox)
        deliver = _RecordingDeliver(ok=True)

        _notify.flush([_spec()], lambda _spec: deliver, now="2026-09-28T00:00:00Z")

        assert "escalationId" not in deliver.calls[0][1].data
        assert self._delivered() == []
