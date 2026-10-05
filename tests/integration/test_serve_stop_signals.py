"""SUBJECT: docket.serve.run_serve -- a second stop signal abandons a blocked sweep (subprocess)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

SUBJECT = "docket.serve"

_DRIVER = textwrap.dedent(
    """
    import threading
    import docket.core.dispatch as d
    from docket import serve

    release = threading.Event()
    d.dispatchable_pods = lambda: ["pod-x"]

    def _blocked(project, **kw):
        print("SWEEP-BLOCKED", flush=True)
        release.wait(60)
        return []

    d.dispatch_pod = _blocked
    serve.run_serve(port=0, interval=3600, dispatch=True)
    """
)


def _read_until(proc: subprocess.Popen[str], needle: str) -> list[str]:
    seen: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        seen.append(line.rstrip())
        if needle in line:
            return seen
    raise AssertionError(f"never saw {needle!r}; got {seen}")


def test_second_sigint_abandons_a_blocked_sweep(tmp_path: Path) -> None:
    home = tmp_path / "home"
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "DOCKET_HOME": str(home),
        "DOCKET_SERVE_TOKEN": "t",
        "PYTHONUNBUFFERED": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, "-c", _DRIVER],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _read_until(proc, "SWEEP-BLOCKED")
        proc.send_signal(signal.SIGINT)
        _read_until(proc, "signal again to abandon")
        time.sleep(1)
        assert proc.poll() is None, "the first signal must wait for the in-flight sweep"
        proc.send_signal(signal.SIGINT)
        code = proc.wait(timeout=20)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert code == 130
    runs = json.loads((home / "docket-runs.json").read_text())["runs"]
    assert len(runs) == 1
    assert runs[0]["cancellation"]["requestedAt"]
