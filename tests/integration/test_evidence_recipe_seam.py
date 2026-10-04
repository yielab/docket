"""Seam: one task's evidence is identical through a real ``--recipe`` harness run and the
CLI ``docket pod <p> evidence <task> --json`` read against the same ``DOCKET_HOME``.

``test_evidence_surfaces.py`` compares the in-process builders; this one runs the real harness
subprocess so the ``task.evidence`` block of the terminal result is the value under test.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from tests.integration.test_harness_cli import (
    REPO_ROOT,
    _AnsweredRun,
    _child_env,
    _final_response,
    _real_docket_home_is_untouched,  # noqa: F401 - module-scoped guard, re-used here
    llm_server,  # noqa: F401 - fixture, re-used here
)

SUBJECT = "docket.core.evidence"


def test_harness_recipe_task_evidence_equals_the_cli_json_of_the_same_home(
    tmp_path: Path,
    llm_server: Any,  # noqa: F811
) -> None:
    server = llm_server(
        [
            _final_response("ready\nREADY"),
            _final_response("built"),
            _final_response("APPROVE"),
        ]
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    env = _child_env(tmp_path / "home", server.base_url)
    stderr = tmp_path / "stderr.txt"
    args = [
        "run",
        "--workspace",
        str(workspace),
        "--task",
        "evidence please",
        "--model",
        "local/x",
        "--contract",
        "1.1",
        "--verify",
        "true",
        "--recipe",
        "intake",
    ]
    returncode, lines = _AnsweredRun(args, env, stderr).finish(timeout=120)
    assert returncode == 0, stderr.read_text(encoding="utf-8")

    harness_doc = lines[-1]["task"]["evidence"]
    assert harness_doc is not None
    cli = subprocess.run(
        [
            sys.executable,
            "-m",
            "docket",
            "pod",
            harness_doc["pod"],
            "evidence",
            harness_doc["taskId"],
            "--json",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert cli.returncode == 0, cli.stderr
    assert json.loads(cli.stdout) == harness_doc
