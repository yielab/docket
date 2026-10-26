"""SUBJECT: interfaces.http.routes.a2a_push -- a push config as a task-scoped webhook channel."""

from __future__ import annotations

import pytest
from tests.support.tasks import put_tasks, task

from docket.interfaces.http.routes import a2a_push
from docket.interfaces.http.routes.a2a_rpc import RpcError
from docket.operator import ChannelSpec, save_channel

SUBJECT = "docket.interfaces.http.routes.a2a_push"


class TestChannelFor:
    def test_it_is_an_enabled_notify_webhook_scoped_to_the_task(self) -> None:
        spec = a2a_push.channel_for("demo", "task-abc", {"url": "http://127.0.0.1:9/hook"})

        assert (spec.name, spec.dialect, spec.enabled) == ("a2a-task-abc", "webhook", True)
        assert spec.capabilities == ["notify"] and spec.content == "minimal"
        assert spec.config == {
            "url": "http://127.0.0.1:9/hook",
            "scopeTask": "task-abc",
            "scopePod": "demo",
        }
        assert set(spec.on) == {"needs_you", "task.completed", "task.failed", "task.rejected"}
        assert spec.secret is None

    @pytest.mark.parametrize("url", ["", "ftp://host/x", "file:///etc/passwd", "not a url", 5])
    def test_a_url_that_is_not_http_is_refused(self, url: object) -> None:
        with pytest.raises(RpcError) as refused:
            a2a_push.channel_for("demo", "task-abc", {"url": url})

        assert refused.value.code == -32602

    @pytest.mark.parametrize("field", ["token", "authentication"])
    def test_a_credential_field_is_refused_because_no_value_is_ever_stored(
        self, field: str
    ) -> None:
        with pytest.raises(RpcError) as refused:
            a2a_push.channel_for("demo", "task-abc", {"url": "http://h/x", field: {"a": "b"}})

        assert refused.value.code == -32602
        assert field in refused.value.message


class TestFinishedChannels:
    def _channel(self, pod: str, task_id: str) -> None:
        save_channel(a2a_push.channel_for(pod, task_id, {"url": "http://127.0.0.1:9/hook"}))

    def test_only_the_channels_of_terminal_tasks_are_named(self) -> None:
        open_task = task(status="running")
        done_task = task(status="done")
        failed_task = task(status="failed")
        cancelled_task = task(status="cancelled")
        put_tasks("demo", open_task, done_task, failed_task, cancelled_task)
        for record in (open_task, done_task, failed_task, cancelled_task):
            self._channel("demo", record.id)
        save_channel(
            ChannelSpec(
                kind="channel",
                name="a2a-not-ours",
                dialect="webhook",
                enabled=True,
                capabilities=["notify"],
                on=["needs_you"],
                config={"url": "http://127.0.0.1:9/x"},
            )
        )

        assert sorted(a2a_push.finished_channels()) == sorted(
            f"a2a-{r.id}" for r in (done_task, failed_task, cancelled_task)
        )
