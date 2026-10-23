"""Guard: scripts/maint/refactor/analyze.py measures a toy package exactly as recorded.

The expected JSON and target map beside the toy package were checked by hand against its
sources, so a change to the tool shows up as a diff in one named section.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
import tomllib
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO / "scripts" / "maint" / "refactor" / "analyze.py"
FIXTURES = Path(__file__).parent / "fixtures" / "refactor"
TOY_ROOT = FIXTURES / "toy"
EXPECTED = json.loads((FIXTURES / "toy.expected.json").read_text(encoding="utf-8"))


def _load() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("_refactor_analyze_guard", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ANALYZE = _load()

TOY = dataclasses.replace(
    ANALYZE.DOCKET,
    package="toy",
    core_prefix="toy.core",
    edges_prefix="toy.edges",
    call_graph_modules=("toy.core.engine",),
    hub_threshold=4,
    module_map=(
        ("toy.core.queue", "toy.tasks.queue"),
        ("toy.tasks.application.runs", "toy.tasks.runs"),
        ("toy.core.state", "toy.tasks.state"),
        ("toy.platform.store", "toy.platform.store"),
    ),
    definition_rules={
        "toy.core.engine": (
            (r"^(LIMIT|_lock|_pick|claim_next)$", "toy.tasks.claim"),
            (r"^(Shared|_fmt|render)$", "toy.view.render"),
        )
    },
)


@pytest.fixture(scope="module")
def toy_analysis() -> dict:
    return ANALYZE.analyze(TOY_ROOT, TOY)


@pytest.mark.parametrize("section", sorted(EXPECTED))
def test_toy_section_matches_the_recorded_json(toy_analysis: dict, section: str) -> None:
    assert toy_analysis[section] == EXPECTED[section]


def test_toy_analysis_has_no_section_the_record_lacks(toy_analysis: dict) -> None:
    assert sorted(toy_analysis) == sorted(EXPECTED)


def test_draft_map_is_byte_identical_to_the_recorded_map(toy_analysis: dict) -> None:
    text = ANALYZE.draft_map(TOY_ROOT, TOY, toy_analysis)
    assert text == (FIXTURES / "toy.target-map.toml").read_text(encoding="utf-8")


def test_draft_map_parses_in_the_schema_the_mover_reads(toy_analysis: dict) -> None:
    parsed = tomllib.loads(ANALYZE.draft_map(TOY_ROOT, TOY, toy_analysis))
    assert set(parsed) == {"module", "definition"}
    assert all(set(m) == {"from", "to"} for m in parsed["module"])
    assert all(set(d) == {"from", "to", "names"} for d in parsed["definition"])
    names = [n for d in parsed["definition"] for n in d["names"]]
    assert len(names) == len(set(names)) == 9


def test_metrics_command_prints_the_nine_numbers(capsys: pytest.CaptureFixture[str]) -> None:
    assert ANALYZE.main(["--root", str(TOY_ROOT), "--metrics"], profile=TOY) == 0
    printed = dict(line.split("=") for line in capsys.readouterr().out.split())
    assert {k: int(v) for k, v in printed.items()} == EXPECTED["metrics"]
    assert len(printed) == 9


def test_default_run_writes_json_and_markdown(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert ANALYZE.main(["--root", str(TOY_ROOT), "--out-dir", str(out)], profile=TOY) == 0
    assert json.loads((out / "analysis.json").read_text(encoding="utf-8")) == EXPECTED
    assert "cycle_largest" in (out / "analysis.md").read_text(encoding="utf-8")


def test_draft_map_command_writes_the_map(tmp_path: Path) -> None:
    out = tmp_path / "out"
    argv = ["--root", str(TOY_ROOT), "--out-dir", str(out), "--draft-map"]
    assert ANALYZE.main(argv, profile=TOY) == 0
    assert (out / "target-map.toml").read_text(encoding="utf-8") == (
        FIXTURES / "toy.target-map.toml"
    ).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def real_metrics() -> dict:
    return ANALYZE.analyze(REPO, ANALYZE.DOCKET)["metrics"]


def test_the_real_tree_yields_nine_integer_metrics(real_metrics: dict) -> None:
    assert len(real_metrics) == 9 and all(isinstance(v, int) for v in real_metrics.values())
    sources = (REPO / "src" / "docket").rglob("*.py")
    largest = max(len(p.read_text(encoding="utf-8").splitlines()) for p in sources)
    assert real_metrics["module_largest_lines"] == largest
