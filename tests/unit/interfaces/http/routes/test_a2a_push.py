"""SUBJECT: interfaces.http.routes.a2a_push -- a push config as a task-scoped webhook channel."""

from __future__ import annotations

import pytest

from docket.interfaces.http.routes import a2a_push
from docket.interfaces.http.routes.a2a_rpc import RpcError

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
