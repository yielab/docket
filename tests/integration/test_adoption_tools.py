"""The adoption benchmark's tools fail safe: output placement is staged, regeneration is clean-tree.

Loads `benchmarks/harness.py` and `benchmarks/results/regenerate.py` in process, because the
repository-local scripts are not packages.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SUBJECT = "docket.kernel.handoff"

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_failure_to_place_the_second_output_restores_the_first(tmp_path: Path) -> None:
    harness = _load("benchmark_harness_under_test", ROOT / "benchmarks" / "harness.py")
    jsonl = tmp_path / "attempts.jsonl"
    jsonl.write_bytes(b"PRIOR JSONL\n")
    blocked = tmp_path / "aggregate.json"
    blocked.mkdir()

    with pytest.raises(harness.BenchmarkError, match="could not place"):
        harness._atomic_write_pair(jsonl, b"NEW JSONL\n", blocked, b"NEW AGGREGATE\n")

    assert jsonl.read_bytes() == b"PRIOR JSONL\n"
    assert [path.name for path in tmp_path.iterdir() if path.name.startswith(".")] == []


def test_both_outputs_are_placed_together(tmp_path: Path) -> None:
    harness = _load("benchmark_harness_under_test", ROOT / "benchmarks" / "harness.py")
    jsonl, aggregate = tmp_path / "attempts.jsonl", tmp_path / "aggregate.json"

    harness._atomic_write_pair(jsonl, b"A\n", aggregate, b"B\n")

    assert (jsonl.read_bytes(), aggregate.read_bytes()) == (b"A\n", b"B\n")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["aggregate.json", "attempts.jsonl"]


def test_regeneration_refuses_a_dirty_tree_before_building_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    regenerate = _load(
        "benchmark_regenerate_under_test", ROOT / "benchmarks" / "results" / "regenerate.py"
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    identity = ["-c", "user.name=t", "-c", "user.email=t@t"]
    (repo / "tracked.txt").write_text("one\n", encoding="utf-8")
    for args in (["init", "-q"], ["add", "tracked.txt"], [*identity, "commit", "-q", "-m", "x"]):
        subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)
    (repo / "tracked.txt").write_text("two\n", encoding="utf-8")
    monkeypatch.setattr(regenerate, "ROOT", repo)
    output = tmp_path / "out"

    with pytest.raises(regenerate.RegenerationError, match="uncommitted changes"):
        regenerate.regenerate("HEAD", output, 3)

    assert not output.exists()
