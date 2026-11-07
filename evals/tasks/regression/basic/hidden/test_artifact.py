"""The artifact holds exactly the asked bytes and the change stays limited to it."""

import os
from pathlib import Path

REPO = Path(os.environ["EVAL_REPO"])


def test_artifact_is_exactly_the_asked_bytes() -> None:
    assert (REPO / "smoke-artifact.txt").read_bytes() == b"docket smoke ok\n"


def test_the_change_is_limited_to_the_artifact() -> None:
    names = {
        p.relative_to(REPO).as_posix()
        for p in REPO.rglob("*")
        if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts
    }
    assert names == {"README.md", "smoke-artifact.txt"}
