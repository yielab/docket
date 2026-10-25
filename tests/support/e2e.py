"""The world an end-to-end test runs docket in: a repo, a home, a fake model and a CLI.

A ``World`` acts on docket only through ``docket`` (one ``python -m docket`` subprocess) or
``service`` (HTTP to a ``docket start`` subprocess). Settings reach docket only as environment
variables; nothing in the test process patches or calls docket. The model is the one faked part.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.support.model_server import FakeModel

SENTINEL_NAME = ".e2e-sentinel"
SENTINEL_TEXT = "untouched\n"
_TASK_ID = re.compile(r"\btask-[0-9a-f]+\b")
_START_LINE = re.compile(r"docket start\s+port=(\d+)")
_PASSTHROUGH = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "SYSTEMROOT")
_GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "e2e",
    "GIT_AUTHOR_EMAIL": "e2e@example.test",
    "GIT_COMMITTER_NAME": "e2e",
    "GIT_COMMITTER_EMAIL": "e2e@example.test",
    "GIT_CONFIG_NOSYSTEM": "1",
}


@dataclass(frozen=True)
class Result:
    """The outcome of one docket invocation."""

    args: tuple[str, ...]
    code: int
    out: str
    err: str

    def json(self) -> Any:
        return json.loads(self.out)

    def describe(self) -> str:
        return f"docket {' '.join(self.args)} -> exit {self.code}\n--- out\n{self.out}\n--- err\n{self.err}"


class Service:
    """A running ``docket start`` and its HTTP API, reached with the bearer token."""

    def __init__(self, process: subprocess.Popen[str], port: int, token: str) -> None:
        self.process = process
        self.port = port
        self.token = token
        self.url = f"http://127.0.0.1:{port}"

    def _call(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.url + path, data=data, method=method)
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        return status, (json.loads(raw) if raw else None)

    def get(self, path: str) -> tuple[int, Any]:
        """``(status, parsed JSON)`` of an authorized GET."""
        return self._call("GET", path)

    def post(self, path: str, body: Any = None) -> tuple[int, Any]:
        """``(status, parsed JSON)`` of an authorized POST with a JSON body."""
        return self._call("POST", path, {} if body is None else body)


class World:
    """One repo, one docket home, one fake home directory and the env that ties them."""

    def __init__(
        self, root: Path, model: FakeModel, *, env: Mapping[str, str] | None = None
    ) -> None:
        self.root = root
        self.model = model
        self.repo = root / "repo"
        self.home = root / "docket-home"
        self.user_home = root / "user-home"
        self.pod = "e2e"
        self.pipeline = root / "pipeline.yaml"
        self.env: dict[str, str] = {
            **{k: os.environ[k] for k in _PASSTHROUGH if k in os.environ},
            **_GIT_IDENTITY,
            "DOCKET_HOME": str(self.home),
            "HOME": str(self.user_home),
            "DOCKET_LLM_BASE_URL": model.base_url,
            "DOCKET_LLM_API_KEY": "e2e",
            "DISPATCH_RETRY_BACKOFF_S": "0",
            "DOCKET_SERVICE_MANAGER": "none",
            "NO_COLOR": "1",
            "PYTHONUNBUFFERED": "1",
            **(env or {}),
        }
        self.home.mkdir(parents=True)
        self.user_home.mkdir(parents=True)
        (self.user_home / SENTINEL_NAME).write_text(SENTINEL_TEXT, encoding="utf-8")
        self._make_repo()

    @property
    def sentinel(self) -> Path:
        """The file in the fake home that no run may touch."""
        return self.user_home / SENTINEL_NAME

    def git(self, *args: str) -> str:
        """Run git in the checkout and return its stripped output."""
        done = subprocess.run(
            ["git", "-C", str(self.repo), *args],
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
        )
        return done.stdout.strip()

    def _make_repo(self) -> None:
        (self.repo / "checks").mkdir(parents=True)
        (self.repo / "README.md").write_text("# e2e repo\n", encoding="utf-8")
        (self.repo / "app.txt").write_text("broken\n", encoding="utf-8")
        (self.repo / "checks" / "verify.sh").write_text(
            "grep -qx fixed app.txt\n", encoding="utf-8"
        )
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "initial")

    def head(self) -> str:
        """The commit ``HEAD`` points at in the checkout."""
        return self.git("rev-parse", "HEAD")

    def docket(
        self,
        *args: str,
        check: bool = True,
        timeout: float = 60,
        stdin: str | None = None,
    ) -> Result:
        """Run ``python -m docket *args`` in the repo; a failure raises with both streams."""
        done = subprocess.run(
            [sys.executable, "-m", "docket", *args],
            cwd=self.repo,
            env=self.env,
            input=stdin if stdin is not None else "",
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        result = Result(tuple(args), done.returncode, done.stdout, done.stderr)
        if check and result.code != 0:
            raise AssertionError(result.describe())
        return result

    def make_pod(self, pipeline_yaml: str, *, pod: str = "e2e", isolation: str = "off") -> None:
        """Provision the four-member ``agentic-product`` pod and write its pipeline file."""
        self.pod = pod
        spec = {
            "id": pod,
            "blueprint": "agentic-product",
            "codebase": str(self.repo),
            "stack": "shell",
            "description": "An end-to-end world.",
        }
        spec_file = self.root / "pod.json"
        spec_file.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        self.pipeline.write_text(pipeline_yaml, encoding="utf-8")
        if isolation == "off":
            self.docket("init", "--from", str(spec_file))
            self.docket("setup", "sandbox", "off")
        else:
            self.docket("init", pod, "--blueprint", "agentic-product")
            status = self.docket("setup", "sandbox", "status", "--json").json()
            assert status["isolationEnabled"] is True, f"init did not turn isolation on: {status}"

    def add_task(self, text: str, *flags: str) -> str:
        """Queue a task and return its id."""
        result = self.docket("task", "add", text, "--pod", self.pod, *flags)
        found = _TASK_ID.search(result.out + result.err)
        assert found, f"no task id in the output of task add:\n{result.describe()}"
        listed = self.docket("task", "list", "--pod", self.pod, "--json").json()["tasks"]
        return next(t["id"] for t in listed if t["id"].startswith(found.group(0)))

    def task(self, task_id: str) -> dict[str, Any]:
        """The task record, as ``docket task show --json`` prints it."""
        shown = self.docket("task", "show", task_id, "--pod", self.pod, "--json").json()
        assert isinstance(shown, dict)
        return shown

    @contextlib.contextmanager
    def service(self, *, dispatch: bool = True, interval: int = 1) -> Iterator[Service]:
        """Run ``docket start`` on a free port, wait until it listens, stop it on exit."""
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        token_file = self.root / "service.token"
        token_file.unlink(missing_ok=True)
        command = [sys.executable, "-m", "docket", "start", "--port", str(port)]
        command += ["--interval", str(interval), "--token-file", str(token_file)]
        if dispatch:
            command.append("--dispatch")
        process = subprocess.Popen(
            command,
            cwd=self.repo,
            env=self.env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            assert process.stdout is not None
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    raise AssertionError(f"docket start exited early with {process.returncode}")
                if (found := _START_LINE.search(line)) and int(found.group(1)) == port:
                    break
            else:
                raise AssertionError("docket start never printed its port line")
            self.wait_for(token_file.exists, what="the service token file")
            service = Service(process, port, token_file.read_text(encoding="utf-8").strip())
            yield service
        finally:
            self._stop(process)

    def _stop(self, process: subprocess.Popen[str]) -> None:
        """Stop the service with ``docket stop``; reaping it here lets the stop see it gone."""
        stopper = None
        try:
            if process.poll() is None:
                command = [sys.executable, "-m", "docket", "stop", "--wait", "10"]
                stopper = subprocess.Popen(
                    command,
                    cwd=self.repo,
                    env=self.env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise AssertionError("docket start did not exit after docket stop") from None
            if stopper is not None:
                said, _ = stopper.communicate(timeout=30)
                assert stopper.returncode == 0, f"docket stop failed:\n{said}"
        finally:
            if stopper is not None and stopper.poll() is None:
                stopper.kill()
                stopper.communicate()
            if process.stdout is not None:
                process.stdout.close()

    def wait_for(
        self, predicate: Callable[[], object], timeout: float = 30, what: str = ""
    ) -> None:
        """Poll *predicate* until it is truthy; raise naming *what* at the deadline."""
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                raise AssertionError(
                    f"timed out after {timeout:g}s waiting for {what or 'a condition'}"
                )
            time.sleep(0.1)
