"""Harness contract 1.2: ``docket exec`` and ``docket setup harness`` on the operator's own setup,
driven as real subprocesses against a loopback stub that records every request."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import uuid
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import record_isolation_off

SUBJECT = "docket.cli._exec"

REPO_ROOT = Path(__file__).resolve().parents[2]
SECRET = "setup-home-integration-secret-0123456789"
ENV_SECRET = "env-sourced-integration-secret-9876543210"


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    if not root.is_dir():
        return {}
    return {
        str(p.relative_to(root)): (p.stat().st_mtime_ns, p.stat().st_size)
        for p in sorted(root.rglob("*"))
    }


def _digest_real_home() -> dict[str, str]:
    home = Path.home() / ".docket"
    if not home.is_dir():
        return {}
    out: dict[str, str] = {}
    for path in sorted(home.rglob("*")):
        if path.is_file():
            try:
                out[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                out[str(path)] = "<unreadable>"
    return out


@pytest.fixture(scope="module", autouse=True)
def _real_docket_home_is_untouched() -> Iterator[None]:
    before = _digest_real_home()
    yield
    assert _digest_real_home() == before


class _Stub:
    """A loopback OpenAI-compatible server answering every POST with one final message and
    recording every request (method, path, headers), GET included."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        requests = self.requests

        class _Handler(BaseHTTPRequestHandler):
            def _record(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length else b""
                requests.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "headers": dict(self.headers),
                        "body": body.decode("utf-8", "replace"),
                    }
                )

            def do_GET(self) -> None:
                self._record()
                self.send_response(404)
                self.end_headers()

            def do_POST(self) -> None:
                self._record()
                payload = json.dumps(
                    {
                        "model": "stubby/served-id",
                        "choices": [
                            {
                                "message": {"role": "assistant", "content": "done"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, fmt: str, *args: object) -> None:  # pragma: no cover
                return None

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture()
def stub() -> Iterator[_Stub]:
    server = _Stub()
    yield server
    server.stop()


def _seed_setup(
    setup: Path,
    base_url: str,
    *,
    roles: dict[str, str] | None = None,
    default: str | None = None,
    secrets: dict[str, str] | None = None,
) -> Path:
    setup.mkdir(parents=True)
    block = {
        "name": "stubby",
        "baseUrl": base_url,
        "auth": {"type": "bearer", "credentials": ["STUBBY_API_KEY"]},
        "models": [{"id": "m1"}, {"id": "m2"}],
    }
    (setup / "docket-providers.json").write_text(json.dumps({"providers": {"stubby": block}}))
    registry: dict[str, Any] = {}
    if roles:
        registry["roles"] = roles
    if default:
        registry["default"] = default
    (setup / "docket-models.json").write_text(json.dumps(registry))
    if secrets is not None:
        (setup / "secrets.json").write_text(json.dumps(secrets))
    return setup


def _env(
    tmp_path: Path, setup: Path | None, *, docket_home: bool = True, **extra: str
) -> dict[str, str]:
    env = os.environ.copy()
    for name in (
        "DOCKET_HOME",
        "DOCKET_SETUP_HOME",
        "DOCKET_LLM_BASE_URL",
        "DOCKET_LLM_API_KEY",
        "DOCKET_NO_TRACE",
        "STUBBY_API_KEY",
        "VIRTUAL_ENV",
    ):
        env.pop(name, None)
    if docket_home:
        home = tmp_path / "caller-home"
        record_isolation_off(home)
        env["DOCKET_HOME"] = str(home)
    if setup is not None:
        env["DOCKET_SETUP_HOME"] = str(setup)
    env["DOCKET_KEYRING_SERVICE"] = f"docket-test-{uuid.uuid4().hex}"
    env["DOCKET_TOOL_MAX_OUTPUT_CHARS"] = "2500"
    env.update(extra)
    return env


def _docket(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "docket", *args],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def _exec(workspace: Path, env: dict[str, str], *extra: str) -> subprocess.CompletedProcess[str]:
    args = ["exec", "--contract", "1.2", "--workspace", str(workspace), "--task", "say done"]
    return _docket([*args, *extra], env)


def _lines(stdout: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def test_a_12_run_without_a_base_url_uses_the_setup_homes_provider_and_default(
    tmp_path: Path, stub: _Stub
) -> None:
    setup = _seed_setup(
        tmp_path / "setup",
        stub.base_url,
        roles={"implementer": "stubby/m1"},
        secrets={"STUBBY_API_KEY": SECRET},
    )
    proc = _exec(_workspace(tmp_path), _env(tmp_path, setup))

    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = _lines(proc.stdout)
    assert {line["v"] for line in lines} == {"1.2.0"}
    result = lines[-1]
    assert result["status"] == "ok"
    assert result["model"] == {
        "requested": "stubby/m1",
        "served": "stubby/served-id",
        "source": "setup default",
    }
    posts = [r for r in stub.requests if r["method"] == "POST"]
    assert posts and all(r["headers"].get("Authorization") == f"Bearer {SECRET}" for r in posts)
    assert json.loads(posts[0]["body"])["model"] == "m1"
    assert SECRET not in proc.stdout and SECRET not in proc.stderr


def test_a_12_run_never_writes_under_the_setup_home(tmp_path: Path, stub: _Stub) -> None:
    setup = _seed_setup(
        tmp_path / "setup", stub.base_url, default="stubby/m2", secrets={"STUBBY_API_KEY": SECRET}
    )
    before = _snapshot(setup)
    proc = _exec(_workspace(tmp_path), _env(tmp_path, setup))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _lines(proc.stdout)[-1]["model"]["requested"] == "stubby/m2"
    assert _snapshot(setup) == before


def test_an_explicit_model_under_12_is_recorded_explicit(tmp_path: Path, stub: _Stub) -> None:
    setup = _seed_setup(
        tmp_path / "setup", stub.base_url, default="stubby/m2", secrets={"STUBBY_API_KEY": SECRET}
    )
    proc = _exec(_workspace(tmp_path), _env(tmp_path, setup), "--model", "stubby/m1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    model = _lines(proc.stdout)[-1]["model"]
    assert (model["requested"], model["source"]) == ("stubby/m1", "explicit")


def test_an_unreadable_keyring_credential_refuses_naming_the_provider_and_sends_nothing(
    tmp_path: Path, stub: _Stub
) -> None:
    setup = _seed_setup(
        tmp_path / "setup", stub.base_url, default="stubby/m1", secrets={"STUBBY_API_KEY": ""}
    )
    env = _env(tmp_path, setup, PATH=str(Path(sys.executable).parent))
    proc = _exec(_workspace(tmp_path), env)

    assert proc.returncode == 2
    result = _lines(proc.stdout)[-1]
    assert (result["v"], result["status"]) == ("1.2.0", "refused")
    assert "provider 'stubby' keeps credential STUBBY_API_KEY in the OS keyring" in result["error"]
    assert "DOCKET_SECRETS_BACKEND=file" in result["error"]
    assert stub.requests == []


def test_a_missing_credential_refuses_and_sends_nothing(tmp_path: Path, stub: _Stub) -> None:
    setup = _seed_setup(tmp_path / "setup", stub.base_url, default="stubby/m1")
    proc = _exec(_workspace(tmp_path), _env(tmp_path, setup))
    assert proc.returncode == 2
    assert "provider 'stubby' needs credential STUBBY_API_KEY" in _lines(proc.stdout)[-1]["error"]
    assert stub.requests == []


def test_no_model_set_up_refuses_with_the_setup_command(tmp_path: Path, stub: _Stub) -> None:
    setup = _seed_setup(tmp_path / "setup", stub.base_url, secrets={"STUBBY_API_KEY": SECRET})
    proc = _exec(_workspace(tmp_path), _env(tmp_path, setup))
    assert proc.returncode == 2
    assert "docket setup model set implementer PROVIDER/ID" in _lines(proc.stdout)[-1]["error"]
    assert stub.requests == []


def test_the_12_probe_with_docket_home_unset_is_the_docket_home_refusal(tmp_path: Path) -> None:
    proc = _exec(tmp_path, _env(tmp_path, None, docket_home=False))
    assert proc.returncode == 2
    result = _lines(proc.stdout)[-1]
    assert result["v"] == "1.2.0"
    assert result["error"] == (
        "DOCKET_HOME is not set; harness mode never runs against the default home"
    )


def test_contract_11_without_a_base_url_is_still_refused(tmp_path: Path, stub: _Stub) -> None:
    setup = _seed_setup(
        tmp_path / "setup", stub.base_url, default="stubby/m1", secrets={"STUBBY_API_KEY": SECRET}
    )
    args = [
        "exec",
        "--contract",
        "1.1",
        "--workspace",
        str(_workspace(tmp_path)),
        "--task",
        "x",
        "--model",
        "stubby/m1",
    ]
    proc = _docket(args, _env(tmp_path, setup))
    assert proc.returncode == 2
    assert "DOCKET_LLM_BASE_URL is required" in _lines(proc.stdout)[-1]["error"]
    assert stub.requests == []


def test_the_readiness_json_makes_no_network_call_and_prints_no_secret(
    tmp_path: Path, stub: _Stub
) -> None:
    setup = _seed_setup(
        tmp_path / "setup",
        stub.base_url,
        roles={"implementer": "stubby/m1"},
        secrets={"STUBBY_API_KEY": SECRET},
    )
    before = _snapshot(setup)
    env = _env(tmp_path, setup, OPENROUTER_API_KEY=ENV_SECRET)
    proc = _docket(["setup", "harness", "--json"], env)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert stub.requests == []
    for secret in (SECRET, ENV_SECRET):
        assert secret not in proc.stdout and secret not in proc.stderr
    doc = json.loads(proc.stdout)
    assert (doc["v"], doc["ready"], doc["reason"]) == ("1.2.0", True, "")
    assert doc["setup_home"] == str(setup)
    assert doc["default_model"] == "stubby/m1"
    assert {"model": "stubby/m1", "provider": "stubby"} in doc["models"]
    by_name = {p["name"]: p for p in doc["providers"]}
    assert by_name["stubby"]["credential"]["source"] == "store"
    assert by_name["openrouter"]["credential"]["source"] == "env"
    assert _snapshot(setup) == before


def test_the_readiness_json_reports_not_ready_with_the_run_refusal(tmp_path: Path) -> None:
    setup = _seed_setup(tmp_path / "setup", "http://127.0.0.1:9/v1", default="stubby/m1")
    proc = _docket(["setup", "harness", "--json"], _env(tmp_path, setup))
    assert proc.returncode == 1
    doc = json.loads(proc.stdout)
    assert doc["ready"] is False
    assert doc["reason"].startswith("provider 'stubby' needs credential STUBBY_API_KEY")
