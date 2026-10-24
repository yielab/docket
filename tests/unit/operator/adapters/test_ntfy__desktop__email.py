"""Ntfy, desktop, and email delivery dialects (`edges/adapters/channels/{ntfy,desktop,email}.py`)
and their registration in `sink_for`.
"""

from __future__ import annotations

import os
import shutil
import smtplib
import socket
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import pytest

from docket.kernel.operator_contract import ApprovalView, make_event
from docket.operator import adapters as channels
from docket.operator import channel as _channel
from docket.operator.adapters import desktop, email, ntfy

SUBJECT = "docket.operator.adapters.ntfy"


class _ChannelSpecLike:
    def __init__(self, config: dict[str, str]) -> None:
        self.config = config
        self.dialect = ""
        self.secret: str | None = None


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
    from docket.operator.notify import render_data

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


def _fake_binary(tmpdir: str, name: str, body: str) -> str:
    script_path = f"{tmpdir}/{name}"
    with open(script_path, "w") as f:
        f.write(body)
    os.chmod(script_path, 0o755)
    return script_path


class TestDesktopDeliver:
    def test_calls_notify_send_with_title_and_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(desktop.sys, "platform", "linux")
        tmpdir = tempfile.mkdtemp()
        _fake_binary(tmpdir, "notify-send", '#!/bin/sh\necho "$@" >> /tmp/test-notify.txt\n')
        monkeypatch.setenv("PATH", tmpdir)
        spec = _ChannelSpecLike({})
        event = _event_approval()
        result = desktop.deliver(spec, event, secret=None, timeout=5.0)
        assert result.ok is True
        shutil.rmtree(tmpdir)

    def test_calls_osascript_on_macos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(desktop.sys, "platform", "darwin")
        tmpdir = tempfile.mkdtemp()
        _fake_binary(tmpdir, "osascript", '#!/bin/sh\necho "$@" >> /tmp/test-notify.txt\n')
        monkeypatch.setenv("PATH", tmpdir)
        spec = _ChannelSpecLike({})
        event = _event_approval()
        result = desktop.deliver(spec, event, secret=None, timeout=5.0)
        assert result.ok is True
        shutil.rmtree(tmpdir)

    def test_missing_notify_send_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(desktop.sys, "platform", "linux")
        monkeypatch.setenv("PATH", "")
        spec = _ChannelSpecLike({})
        event = _event_approval()
        result = desktop.deliver(spec, event, secret=None, timeout=5.0)
        assert result.ok is False
        assert "not found" in result.error

    def test_missing_osascript_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(desktop.sys, "platform", "darwin")
        monkeypatch.setenv("PATH", "")
        spec = _ChannelSpecLike({})
        event = _event_approval()
        result = desktop.deliver(spec, event, secret=None, timeout=5.0)
        assert result.ok is False
        assert "not found" in result.error

    def test_nonzero_exit_is_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(desktop.sys, "platform", "linux")
        tmpdir = tempfile.mkdtemp()
        _fake_binary(tmpdir, "notify-send", "#!/bin/sh\nexit 1\n")
        monkeypatch.setenv("PATH", tmpdir)
        spec = _ChannelSpecLike({})
        event = _event_approval()
        result = desktop.deliver(spec, event, secret=None, timeout=5.0)
        assert result.ok is False
        shutil.rmtree(tmpdir)

    def test_canary_not_in_minimal_event_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(desktop.sys, "platform", "linux")
        tmpdir = tempfile.mkdtemp()
        output_file = f"{tmpdir}/output.txt"
        _fake_binary(tmpdir, "notify-send", f'#!/bin/sh\necho "$@" >> {output_file}\n')
        monkeypatch.setenv("PATH", tmpdir)
        spec = _ChannelSpecLike({})
        event = _event_minimal_with_canary()
        desktop.deliver(spec, event, secret=None, timeout=5.0)
        if os.path.exists(output_file):
            with open(output_file) as f:
                output = f.read()
            assert "CANARY_7f3" not in output
        shutil.rmtree(tmpdir)


class FakeSMTP:
    def __init__(self, host: str, port: int, timeout: float = 0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def ehlo(self) -> None:
        pass

    def has_extn(self, name: str) -> bool:
        return True

    def starttls(self) -> None:
        pass

    def login(self, user: str, password: str) -> None:
        pass

    def send_message(self, msg: Any) -> None:
        pass

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *_args: object) -> None:
        pass


class _SmtpStub:
    """A plain SMTP server on 127.0.0.1 that records what a client sends. It offers STARTTLS
    only when told to, and accepts AUTH only so a test can see whether a client attempted it."""

    def __init__(self, *, starttls: bool = False) -> None:
        self.starttls = starttls
        self.messages: list[str] = []
        self.commands: list[str] = []
        self._server = socket.socket()
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(4)
        self.port = self._server.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.close()
        self._thread.join(timeout=2)

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            with conn:
                self._session(conn)

    def _session(self, conn: socket.socket) -> None:
        conn.settimeout(3)
        stream = conn.makefile("rwb")

        def reply(line: str) -> None:
            stream.write(line.encode() + b"\r\n")
            stream.flush()

        reply("220 stub ready")
        try:
            while True:
                raw = stream.readline()
                if not raw:
                    return
                line = raw.decode().rstrip("\r\n")
                self.commands.append(line.split(" ", 1)[0].upper())
                verb = line.split(" ", 1)[0].upper()
                if verb == "EHLO":
                    if self.starttls:
                        reply("250-stub")
                        reply("250 STARTTLS")
                    else:
                        reply("250 stub")
                elif verb == "DATA":
                    reply("354 go")
                    body: list[str] = []
                    while (data := stream.readline().decode().rstrip("\r\n")) != ".":
                        body.append(data)
                    self.messages.append("\n".join(body))
                    reply("250 queued")
                elif verb == "QUIT":
                    reply("221 bye")
                    return
                else:
                    reply("250 ok")
        except (OSError, TimeoutError):
            return


@pytest.fixture
def smtp_stub() -> Any:
    stub = _SmtpStub()
    yield stub
    stub.close()


class TestEmailDeliver:
    def _spec(self, port: int | str, **config: str) -> _ChannelSpecLike:
        base = {
            "smtpHost": "127.0.0.1",
            "port": str(port),
            "from": "docket@example.test",
            "to": "recv@example.test",
        }
        return _ChannelSpecLike({**base, **config})

    def test_the_shipped_template_keys_deliver_without_a_secret(self, smtp_stub: _SmtpStub) -> None:
        result = email.deliver(
            self._spec(smtp_stub.port), _event_approval(), secret=None, timeout=5.0
        )
        assert result.ok is True, result.error
        assert "AUTH" not in smtp_stub.commands
        (message,) = smtp_stub.messages
        assert "From: docket@example.test" in message
        assert "To: recv@example.test" in message
        assert "Subject: [docket]" in message

    def test_the_built_in_email_document_names_the_keys_the_dialect_reads(
        self, smtp_stub: _SmtpStub
    ) -> None:
        shipped = _channel.load_catalog().get("email")
        assert shipped is not None
        filled = {
            k: {"to": "recv@example.test", "from": "docket@example.test", "smtpHost": "127.0.0.1"}[
                k
            ]
            for k in shipped.config
        }
        spec = shipped.model_copy(update={"config": {**filled, "port": str(smtp_stub.port)}})
        result = email.deliver(spec, _event_approval(), secret=None, timeout=5.0)
        assert result.ok is True, result.error
        assert len(smtp_stub.messages) == 1

    def test_a_secret_is_never_sent_to_a_server_without_starttls(
        self, smtp_stub: _SmtpStub
    ) -> None:
        spec = self._spec(smtp_stub.port, user="login")
        result = email.deliver(spec, _event_approval(), secret="password123", timeout=5.0)
        assert result.ok is False
        assert "STARTTLS" in result.error
        assert "AUTH" not in smtp_stub.commands
        assert smtp_stub.messages == []

    def test_a_channel_naming_a_secret_that_did_not_resolve_fails(
        self, smtp_stub: _SmtpStub
    ) -> None:
        spec = self._spec(smtp_stub.port)
        spec.secret = "SMTP_PASSWORD"
        result = email.deliver(spec, _event_approval(), secret=None, timeout=5.0)
        assert result.ok is False
        assert "SMTP_PASSWORD" in result.error
        assert smtp_stub.messages == []

    def test_login_uses_the_user_key_and_falls_back_to_from(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logins: list[str] = []

        class Recorder(FakeSMTP):
            def login(self, user: str, password: str) -> None:
                logins.append(user)

        monkeypatch.setattr(smtplib, "SMTP", lambda *_a, **_kw: Recorder("h", 587))
        email.deliver(self._spec(587, user="login"), _event_approval(), secret="p", timeout=5.0)
        email.deliver(self._spec(587), _event_approval(), secret="p", timeout=5.0)
        assert logins == ["login", "docket@example.test"]

    def test_missing_host_returns_error(self) -> None:
        spec = _ChannelSpecLike({"from": "a@example.test", "to": "recv@example.test"})
        result = email.deliver(spec, _event_approval(), secret=None, timeout=5.0)
        assert result.ok is False
        assert "smtpHost" in result.error

    def test_missing_from_or_to_returns_error(self) -> None:
        spec = _ChannelSpecLike({"smtpHost": "127.0.0.1", "port": "587"})
        result = email.deliver(spec, _event_approval(), secret=None, timeout=5.0)
        assert result.ok is False
        assert "from" in result.error and "to" in result.error

    def test_invalid_port_returns_error(self) -> None:
        result = email.deliver(self._spec("invalid"), _event_approval(), secret=None, timeout=5.0)
        assert result.ok is False
        assert "port" in result.error

    def test_canary_not_in_minimal_event_text(self, smtp_stub: _SmtpStub) -> None:
        result = email.deliver(
            self._spec(smtp_stub.port), _event_minimal_with_canary(), secret=None, timeout=5.0
        )
        assert result.ok is True, result.error
        assert smtp_stub.messages
        assert "CANARY_7f3" not in smtp_stub.messages[0]


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
