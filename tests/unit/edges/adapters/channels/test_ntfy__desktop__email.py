"""Ntfy, desktop, and email delivery dialects (`edges/adapters/channels/{ntfy,desktop,email}.py`)
and their registration in `sink_for`.
"""

from __future__ import annotations

import smtplib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import pytest

from docket.core.operator_contract import ApprovalView, make_event
from docket.edges.adapters import channels
from docket.edges.adapters.channels import desktop, email, ntfy

SUBJECT = "docket.edges.adapters.channels.ntfy"


class _ChannelSpecLike:
    def __init__(self, config: dict[str, str]) -> None:
        self.config = config
        self.dialect = ""


def _event_approval() -> Any:
    return make_event(
        "approval.requested",
        "alpha",
        "approval:tok-1",
        {"pod": "alpha", "token": "tok-1"},
        time="2026-09-28T00:00:00Z",
        version="pending:tok-1",
    )


def _event_input_required() -> Any:
    return make_event(
        "task.input_required",
        "alpha",
        "task:alpha:t1",
        {"pod": "alpha", "taskId": "t1"},
        time="2026-09-28T00:00:00Z",
        version="waiting_input:",
    )


def _event_minimal_with_canary() -> Any:
    """A minimal-content event whose underlying action is the literal CANARY_7f3 string."""
    approval = ApprovalView(
        token="tok-canary",
        pod="alpha",
        role="implementer",
        action="git push origin CANARY_7f3",
        policy="prod-approval",
        state="pending",
        created_at="2026-09-28T00:00:00Z",
    )
    # Build the event at minimal content level
    from docket.core.notify import render_data

    data = render_data(approval, "minimal")
    return make_event(
        "approval.requested",
        "alpha",
        "approval:tok-canary",
        data,
        time="2026-09-28T00:00:00Z",
        version="pending:tok-canary",
    )


class _RecordingNtfyHandler(BaseHTTPRequestHandler):
    responses: ClassVar[list[int]] = []
    requests: ClassVar[list[dict[str, Any]]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        headers_ci = {k.lower(): v for k, v in self.headers.items()}
        type(self).requests.append(
            {"headers": headers_ci, "body": body.decode("utf-8", errors="replace")}
        )
        status = type(self).responses.pop(0)
        self.send_response(status)
        self.end_headers()
        self.wfile.write(b"")

    def log_message(self, *_args: object) -> None:
        return


def _ntfy_server(responses: list[int]) -> tuple[ThreadingHTTPServer, str]:
    class _Handler(_RecordingNtfyHandler):
        pass

    _Handler.responses = responses
    _Handler.requests = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, f"http://127.0.0.1:{port}"


class TestNtfyDeliver:
    def test_posts_with_title_and_priority_headers(self) -> None:
        srv, url = _ntfy_server([200])
        try:
            event = make_event(
                "task.completed",
                "alpha",
                "task:alpha:t1",
                {"pod": "alpha", "taskId": "t1"},
                time="2026-09-28T00:00:00Z",
                version="done:",
            )
            spec = _ChannelSpecLike({"server": url, "topic": "my-topic"})
            result = ntfy.deliver(spec, event, secret=None, timeout=5.0)
            assert result.ok is True
            handler_cls = srv.RequestHandlerClass
            req = handler_cls.requests[0]
            assert "title" in req["headers"]
            assert req["headers"]["priority"] == "default"
        finally:
            srv.shutdown()

    def test_high_priority_for_approval_requested(self) -> None:
        srv, url = _ntfy_server([200])
        try:
            event = _event_approval()
            spec = _ChannelSpecLike({"server": url, "topic": "my-topic"})
            ntfy.deliver(spec, event, secret=None, timeout=5.0)
            handler_cls = srv.RequestHandlerClass
            req = handler_cls.requests[0]
            assert req["headers"]["priority"] == "high"
        finally:
            srv.shutdown()

    def test_high_priority_for_input_required(self) -> None:
        srv, url = _ntfy_server([200])
        try:
            event = _event_input_required()
            spec = _ChannelSpecLike({"server": url, "topic": "my-topic"})
            ntfy.deliver(spec, event, secret=None, timeout=5.0)
            handler_cls = srv.RequestHandlerClass
            req = handler_cls.requests[0]
            assert req["headers"]["priority"] == "high"
        finally:
            srv.shutdown()

    def test_adds_authorization_header_when_secret_present(self) -> None:
        srv, url = _ntfy_server([200])
        try:
            event = _event_approval()
            spec = _ChannelSpecLike({"server": url, "topic": "my-topic"})
            ntfy.deliver(spec, event, secret="token123", timeout=5.0)
            handler_cls = srv.RequestHandlerClass
            req = handler_cls.requests[0]
            assert req["headers"]["authorization"] == "Bearer token123"
        finally:
            srv.shutdown()

    def test_omits_authorization_when_no_secret(self) -> None:
        srv, url = _ntfy_server([200])
        try:
            event = _event_approval()
            spec = _ChannelSpecLike({"server": url, "topic": "my-topic"})
            ntfy.deliver(spec, event, secret=None, timeout=5.0)
            handler_cls = srv.RequestHandlerClass
            req = handler_cls.requests[0]
            assert "authorization" not in req["headers"]
        finally:
            srv.shutdown()

    def test_missing_topic_returns_error(self) -> None:
        spec = _ChannelSpecLike({"server": "https://ntfy.sh"})
        event = _event_approval()
        result = ntfy.deliver(spec, event, secret=None, timeout=5.0)
        assert result.ok is False
        assert "topic" in result.error

    def test_non_2xx_status_is_failure(self) -> None:
        srv, url = _ntfy_server([500])
        try:
            spec = _ChannelSpecLike({"server": url, "topic": "my-topic"})
            result = ntfy.deliver(spec, _event_approval(), secret=None, timeout=5.0)
            assert result.ok is False
            assert result.status == 500
        finally:
            srv.shutdown()

    def test_network_error_returns_error(self) -> None:
        spec = _ChannelSpecLike({"server": "http://127.0.0.1:1", "topic": "my-topic"})
        event = _event_approval()
        result = ntfy.deliver(spec, event, secret=None, timeout=0.1)
        assert result.ok is False
        assert result.error

    def test_canary_not_in_minimal_event_text(self) -> None:
        srv, url = _ntfy_server([200])
        try:
            event = _event_minimal_with_canary()
            spec = _ChannelSpecLike({"server": url, "topic": "my-topic"})
            ntfy.deliver(spec, event, secret=None, timeout=5.0)
            handler_cls = srv.RequestHandlerClass
            req = handler_cls.requests[0]
            body = req["body"]
            headers_repr = repr(req["headers"])
            assert "CANARY_7f3" not in body
            assert "CANARY_7f3" not in headers_repr
        finally:
            srv.shutdown()


class TestDesktopDeliver:
    def test_calls_notify_send_with_title_and_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import tempfile

        tmpdir = tempfile.mkdtemp()
        script_path = f"{tmpdir}/notify-send"
        with open(script_path, "w") as f:
            f.write('#!/bin/sh\necho "$@" >> /tmp/test-notify.txt\n')
        import os

        os.chmod(script_path, 0o755)
        monkeypatch.setenv("PATH", tmpdir)
        spec = _ChannelSpecLike({})
        event = _event_approval()
        result = desktop.deliver(spec, event, secret=None, timeout=5.0)
        assert result.ok is True
        import shutil

        shutil.rmtree(tmpdir)

    def test_missing_notify_send_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PATH", "")
        spec = _ChannelSpecLike({})
        event = _event_approval()
        result = desktop.deliver(spec, event, secret=None, timeout=5.0)
        assert result.ok is False
        assert "not found" in result.error

    def test_nonzero_exit_is_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import tempfile

        tmpdir = tempfile.mkdtemp()
        script_path = f"{tmpdir}/notify-send"
        with open(script_path, "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        import os

        os.chmod(script_path, 0o755)
        monkeypatch.setenv("PATH", tmpdir)
        spec = _ChannelSpecLike({})
        event = _event_approval()
        result = desktop.deliver(spec, event, secret=None, timeout=5.0)
        assert result.ok is False
        import shutil

        shutil.rmtree(tmpdir)

    def test_canary_not_in_minimal_event_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import tempfile

        tmpdir = tempfile.mkdtemp()
        output_file = f"{tmpdir}/output.txt"
        script_path = f"{tmpdir}/notify-send"
        with open(script_path, "w") as f:
            f.write(f'#!/bin/sh\necho "$@" >> {output_file}\n')
        import os

        os.chmod(script_path, 0o755)
        monkeypatch.setenv("PATH", tmpdir)
        spec = _ChannelSpecLike({})
        event = _event_minimal_with_canary()
        desktop.deliver(spec, event, secret=None, timeout=5.0)
        if os.path.exists(output_file):
            with open(output_file) as f:
                output = f.read()
            assert "CANARY_7f3" not in output
        import shutil

        shutil.rmtree(tmpdir)


class FakeSMTP:
    def __init__(self, host: str, port: int, timeout: float = 0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.calls: list[str] = []

    def starttls(self) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login:{user}")

    def send_message(self, msg: Any) -> None:
        self.calls.append(f"send_message:{msg['To']}")

    def quit(self) -> None:
        self.calls.append("quit")

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *_args: object) -> None:
        pass


class TestEmailDeliver:
    def test_sends_via_smtp_with_correct_headers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_smtp_instance = FakeSMTP("localhost", 587)
        monkeypatch.setattr(smtplib, "SMTP", lambda *_a, **_kw: fake_smtp_instance)
        spec = _ChannelSpecLike(
            {
                "host": "localhost",
                "port": "587",
                "user": "test@example.com",
                "to": "recv@example.com",
            }
        )
        event = _event_approval()
        result = email.deliver(spec, event, secret="password123", timeout=5.0)
        assert result.ok is True
        assert "login:test@example.com" in fake_smtp_instance.calls
        assert "send_message:recv@example.com" in fake_smtp_instance.calls

    def test_missing_host_returns_error(self) -> None:
        spec = _ChannelSpecLike(
            {"port": "587", "user": "test@example.com", "to": "recv@example.com"}
        )
        event = _event_approval()
        result = email.deliver(spec, event, secret="password123", timeout=5.0)
        assert result.ok is False
        assert "host" in result.error

    def test_missing_user_or_to_returns_error(self) -> None:
        spec = _ChannelSpecLike({"host": "localhost", "port": "587"})
        event = _event_approval()
        result = email.deliver(spec, event, secret="password123", timeout=5.0)
        assert result.ok is False
        assert "user" in result.error or "to" in result.error

    def test_missing_secret_returns_error(self) -> None:
        spec = _ChannelSpecLike(
            {
                "host": "localhost",
                "port": "587",
                "user": "test@example.com",
                "to": "recv@example.com",
            }
        )
        event = _event_approval()
        result = email.deliver(spec, event, secret=None, timeout=5.0)
        assert result.ok is False
        assert "secret" in result.error

    def test_invalid_port_returns_error(self) -> None:
        spec = _ChannelSpecLike(
            {
                "host": "localhost",
                "port": "invalid",
                "user": "test@example.com",
                "to": "recv@example.com",
            }
        )
        event = _event_approval()
        result = email.deliver(spec, event, secret="password123", timeout=5.0)
        assert result.ok is False
        assert "port" in result.error

    def test_canary_not_in_minimal_event_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured_msg = None

        class CapturingSMTP(FakeSMTP):
            def send_message(self, msg: Any) -> None:
                nonlocal captured_msg
                captured_msg = msg
                super().send_message(msg)

        monkeypatch.setattr(smtplib, "SMTP", lambda *_a, **_kw: CapturingSMTP("localhost", 587))
        spec = _ChannelSpecLike(
            {
                "host": "localhost",
                "port": "587",
                "user": "test@example.com",
                "to": "recv@example.com",
            }
        )
        event = _event_minimal_with_canary()
        email.deliver(spec, event, secret="password123", timeout=5.0)
        if captured_msg:
            msg_str = str(captured_msg)
            assert "CANARY_7f3" not in msg_str


class TestSinkForNewDialects:
    def test_ntfy_dialect_resolves(self) -> None:
        spec = _ChannelSpecLike({})
        spec.dialect = "ntfy"
        assert channels.sink_for(spec) is ntfy.deliver

    def test_desktop_dialect_resolves(self) -> None:
        spec = _ChannelSpecLike({})
        spec.dialect = "desktop"
        assert channels.sink_for(spec) is desktop.deliver

    def test_email_dialect_resolves(self) -> None:
        spec = _ChannelSpecLike({})
        spec.dialect = "email"
        assert channels.sink_for(spec) is email.deliver
