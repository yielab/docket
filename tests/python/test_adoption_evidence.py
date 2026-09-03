"""W29-C6 RED contract for the exact-artifact published adoption baseline."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[2]
REGENERATOR = ROOT / "benchmarks" / "results" / "regenerate.py"
BASELINE = ROOT / "benchmarks" / "results" / "wave29"
MANIFEST = BASELINE / "manifest.json"
REPORT = ROOT / "docs" / "ADOPTION-EVIDENCE.md"
HARNESS = ROOT / "benchmarks" / "harness.py"
SCHEMA = ROOT / "benchmarks" / "schema.json"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

SCENARIOS = {
    "starter",
    "allowed",
    "policy-denied",
    "approval-denied",
    "approval-granted",
    "malformed-handoff",
    "hard-crash-resume",
    "corrupt-primary-recovery",
}
FAILED_SCENARIOS = {
    "starter",
    "policy-denied",
    "approval-denied",
    "malformed-handoff",
}
MANIFEST_KEYS = {
    "schema_version",
    "baseline_id",
    "source",
    "repetitions",
    "entries",
    "summary",
    "comparison",
}
SOURCE_KEYS = {"commit", "artifact"}
ARTIFACT_KEYS = {"filename", "package", "version", "sha256"}
ENTRY_KEYS = {
    "scenario_id",
    "attempts",
    "completions",
    "jsonl",
    "aggregate",
    "evidence",
    "measurements",
}
SUMMARY_KEYS = {
    "scenarios",
    "attempts",
    "completions",
    "failures",
    "completion_rate",
    "usage",
    "tool_calls",
    "prevented_policy_violations",
    "approval_latency_observations",
    "recovery",
    "handoff_failures",
    "stop_reasons",
    "cost_usd",
    "failed_attempts",
}
COMPARISON_KEYS = {"excluded_fields", "tolerance_ms"}
TIMING_EXCLUSIONS = {
    "attempt.approval_latency_ms",
    "aggregate.approval_latency_ms.total",
    "measurements.elapsed_ms",
}
PUBLIC_SURFACES = (
    ROOT / "README.md",
    ROOT / "COMPATIBILITY.md",
    ROOT / "SECURITY.md",
    ROOT / "docs" / "README.md",
)
PLACEHOLDER_SOURCES = {"2" * 40, "3" * 64}


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
        + b"\n"
    )


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{path} must contain one JSON object"
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert records and all(isinstance(record, dict) for record in records)
    return records


def _require_red_targets() -> None:
    expected = (REGENERATOR, MANIFEST, REPORT)
    missing = [str(path.relative_to(ROOT)) for path in expected if not path.is_file()]
    assert not missing, "RED: Wave 29 publication targets are not implemented: " + ", ".join(
        missing
    )


def _under(root: Path, raw: object) -> Path:
    assert isinstance(raw, str) and raw
    relative = Path(raw)
    assert not relative.is_absolute() and ".." not in relative.parts
    resolved = (root / relative).resolve()
    assert resolved.is_relative_to(root.resolve())
    return resolved


def _manifest() -> dict[str, Any]:
    _require_red_targets()
    raw = MANIFEST.read_bytes()
    manifest = _object(MANIFEST)
    assert raw == _canonical(manifest)
    return manifest


def _entries(manifest: dict[str, Any], root: Path = BASELINE) -> list[dict[str, Any]]:
    entries = manifest["entries"]
    assert isinstance(entries, list) and len(entries) == len(SCENARIOS)
    assert all(isinstance(entry, dict) and set(entry) == ENTRY_KEYS for entry in entries)
    assert {entry["scenario_id"] for entry in entries} == SCENARIOS
    for entry in entries:
        for key in ("jsonl", "aggregate", "evidence", "measurements"):
            assert _under(root, entry[key]).is_file()
    return entries


def _all_attempts(entries: list[dict[str, Any]], root: Path = BASELINE) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    for entry in entries:
        records = _jsonl(_under(root, entry["jsonl"]))
        assert len(records) == entry["attempts"]
        assert sum(int(record["completed"]) for record in records) == entry["completions"]
        assert all(record["scenario"]["id"] == entry["scenario_id"] for record in records)
        attempts.extend(records)
    return attempts


def _derived_summary(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    completions = sum(int(record["completed"]) for record in attempts)
    stop_reasons = Counter(str(record["stop_reason"]) for record in attempts)
    failed = [
        {
            "scenario_id": record["scenario"]["id"],
            "attempt_ordinal": record["attempt_ordinal"],
            "stop_reason": record["stop_reason"],
        }
        for record in attempts
        if not record["completed"]
    ]
    costs = [record["cost"] for record in attempts]
    cost_usd: str | None = None
    if all(cost is not None for cost in costs):
        total = sum((Decimal(str(cost["usd"])) for cost in costs), Decimal("0"))
        cost_usd = f"{total:.6f}"
    return {
        "scenarios": len({record["scenario"]["id"] for record in attempts}),
        "attempts": len(attempts),
        "completions": completions,
        "failures": len(attempts) - completions,
        "completion_rate": {"numerator": completions, "denominator": len(attempts)},
        "usage": {
            "basis": "provider_reported",
            "input_tokens": sum(int(record["usage"]["input_tokens"]) for record in attempts),
            "output_tokens": sum(int(record["usage"]["output_tokens"]) for record in attempts),
            "total_tokens": sum(int(record["usage"]["total_tokens"]) for record in attempts),
        },
        "tool_calls": {
            "total": sum(int(record["tool_calls"]["total"]) for record in attempts),
            "executed": sum(int(record["tool_calls"]["executed"]) for record in attempts),
        },
        "prevented_policy_violations": sum(
            int(record["prevented_policy_violations"]) for record in attempts
        ),
        "approval_latency_observations": sum(
            int(record["approval_latency_ms"] is not None) for record in attempts
        ),
        "recovery": {
            "attempted": sum(
                int(record["recovery"]["stale_claim_observed"]) for record in attempts
            ),
            "resumed_to_terminal": sum(
                int(record["recovery"]["resumed_to_terminal"]) for record in attempts
            ),
        },
        "handoff_failures": sum(int(record["handoff_failures"]) for record in attempts),
        "stop_reasons": {key: stop_reasons[key] for key in sorted(stop_reasons)},
        "cost_usd": cost_usd,
        "failed_attempts": failed,
    }


def _normalized_file(path: Path) -> bytes:
    if path.name == "attempts.jsonl":
        records = _jsonl(path)
        for record in records:
            if record["approval_latency_ms"] is not None:
                record["approval_latency_ms"] = "<timing>"
        return b"".join(_canonical(record) for record in records)
    if path.name == "aggregate.json":
        value = _object(path)
        value["approval_latency_ms"]["total"] = "<timing>"
        return _canonical(value)
    if path.name == "measurements.json":
        value = _object(path)
        value["elapsed_ms"] = ["<timing>" for _ in value["elapsed_ms"]]
        return _canonical(value)
    return path.read_bytes()


def _normalized_tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): _normalized_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _run_regenerator(output: Path, source_commit: str, state: Path) -> None:
    home = state / "home"
    temp = state / "tmp"
    cache = state / "cache"
    for path in (temp, cache):
        path.mkdir(parents=True)
    env = dict(os.environ)
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DOCKET_LLM_API_KEY"):
        env.pop(key, None)
    env.update(
        {
            "DOCKET_HOME": str(home),
            "HOME": str(state / "operator-home"),
            "TMPDIR": str(temp),
            "UV_CACHE_DIR": str(cache),
            "PYTHONPATH": "",
        }
    )
    Path(env["HOME"]).mkdir()
    result = subprocess.run(
        [
            sys.executable,
            str(REGENERATOR),
            "--source-commit",
            source_commit,
            "--output",
            str(output),
            "--repetitions",
            "3",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=1_200,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not home.exists(), "regenerator retained temporary Docket state"


def _markdown_links(path: Path) -> list[Path]:
    targets: list[Path] = []
    for destination in re.findall(r"!?\[[^]]*]\(([^)]+)\)", path.read_text(encoding="utf-8")):
        destination = destination.strip().strip("<>")
        if not destination or destination.startswith("#") or "://" in destination:
            continue
        raw = unquote(destination.split("#", 1)[0].split("?", 1)[0])
        if raw:
            targets.append((path.parent / raw).resolve())
    return targets


def _overclaims(text: str) -> set[str]:
    lowered = text.lower()
    patterns = {
        "ranking": r"(?:ranks?|ranked) (?:above|below|first|best)|leaderboard",
        "competitor": r"(?:beats?|outperforms?) [a-z0-9]",
        "savings": r"(?:saved?|saves?) (?:us )?\$|\d+% (?:cheaper|savings)",
        "production-rate": r"production success rate (?:is|of) \d",
        "model-quality": r"proves? (?:live )?model quality",
        "priced-zero": r"(?:cost|price) (?:is|was) \$?0(?:\.0+)?\b",
    }
    return {name for name, pattern in patterns.items() if re.search(pattern, lowered)}


def test_committed_baseline_manifest_is_closed_complete_and_exactly_sourced() -> None:
    manifest = _manifest()
    assert set(manifest) == MANIFEST_KEYS
    assert manifest["schema_version"] == "1.0.0"
    assert manifest["baseline_id"] == "wave29-adoption"
    assert manifest["repetitions"] == 3

    source = manifest["source"]
    assert isinstance(source, dict) and set(source) == SOURCE_KEYS
    commit = source["commit"]
    artifact = source["artifact"]
    assert isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40,64}", commit)
    assert commit not in PLACEHOLDER_SOURCES
    resolved = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=ROOT, check=False
    )
    assert resolved.returncode == 0, "baseline source commit is not present in repository history"
    assert isinstance(artifact, dict) and set(artifact) == ARTIFACT_KEYS
    assert artifact["package"] == "docket" and artifact["version"] == VERSION
    assert isinstance(artifact["filename"], str) and artifact["filename"].endswith(".whl")
    assert re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])
    assert artifact["sha256"] not in PLACEHOLDER_SOURCES

    comparison = manifest["comparison"]
    assert isinstance(comparison, dict) and set(comparison) == COMPARISON_KEYS
    assert set(comparison["excluded_fields"]) == TIMING_EXCLUSIONS
    assert isinstance(comparison["tolerance_ms"], int)
    assert 0 < comparison["tolerance_ms"] <= 5_000
    _entries(manifest)


def test_every_attempt_is_c3_valid_rebuildable_and_present_in_summary(tmp_path: Path) -> None:
    manifest = _manifest()
    entries = _entries(manifest)
    validator = Draft202012Validator(_object(SCHEMA))
    attempts = _all_attempts(entries)
    assert len(attempts) == 9
    assert sum(int(record["completed"]) for record in attempts) == 5

    source = {
        "commit": manifest["source"]["commit"],
        "artifact_sha256": manifest["source"]["artifact"]["sha256"],
    }
    for entry in entries:
        jsonl = _under(BASELINE, entry["jsonl"])
        aggregate = _under(BASELINE, entry["aggregate"])
        for record in _jsonl(jsonl):
            validator.validate(record)
            assert record["source"] == source
        validator.validate(_object(aggregate))
        rebuilt = tmp_path / f"{entry['scenario_id']}-aggregate.json"
        result = subprocess.run(
            [
                sys.executable,
                str(HARNESS),
                "aggregate",
                "--jsonl",
                str(jsonl),
                "--aggregate",
                str(rebuilt),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert rebuilt.read_bytes() == aggregate.read_bytes()

    summary = manifest["summary"]
    assert isinstance(summary, dict) and set(summary) == SUMMARY_KEYS
    assert summary == _derived_summary(attempts)
    assert summary["scenarios"] == 8
    assert summary["attempts"] == 9
    assert summary["completions"] == 5
    assert summary["failures"] == 4
    assert summary["cost_usd"] is None
    assert {item["scenario_id"] for item in summary["failed_attempts"]} == FAILED_SCENARIOS


def test_two_exact_artifact_regenerations_match_committed_baseline_except_timing(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    source_commit = str(manifest["source"]["commit"])
    first = tmp_path / "first"
    second = tmp_path / "second"
    _run_regenerator(first, source_commit, tmp_path / "state-one")
    _run_regenerator(second, source_commit, tmp_path / "state-two")

    first_tree = _normalized_tree(first)
    second_tree = _normalized_tree(second)
    committed_tree = _normalized_tree(BASELINE)
    assert first_tree.keys() == second_tree.keys() == committed_tree.keys()
    assert first_tree == second_tree == committed_tree

    tolerance = int(manifest["comparison"]["tolerance_ms"])
    for relative in first_tree:
        if not relative.endswith("measurements.json"):
            continue
        left = _object(first / relative)["elapsed_ms"]
        right = _object(second / relative)["elapsed_ms"]
        assert len(left) == len(right) and left
        assert all(isinstance(value, int) and value >= 0 for value in [*left, *right])
        assert all(abs(a - b) <= tolerance for a, b in zip(left, right, strict=True))


def test_public_report_links_raw_evidence_and_states_only_measured_truth() -> None:
    manifest = _manifest()
    report = REPORT.read_text(encoding="utf-8")
    lowered = report.lower()
    for phrase in (
        "deterministic contract evidence",
        "does not measure model quality",
        "cost unavailable",
        "9 attempts",
        "5 completions",
        "4 failures",
    ):
        assert phrase in lowered
    for scenario in FAILED_SCENARIOS:
        assert scenario in report
    assert manifest["source"]["commit"] in report
    assert not _overclaims(report)

    linked = _markdown_links(REPORT)
    assert MANIFEST.resolve() in linked
    assert SCHEMA.resolve() in linked
    assert linked and all(path.is_relative_to(ROOT) and path.exists() for path in linked)
    for surface in PUBLIC_SURFACES:
        assert "ADOPTION-EVIDENCE.md" in surface.read_text(encoding="utf-8")


def test_published_evidence_contains_no_private_runtime_material() -> None:
    _require_red_targets()
    paths = [REPORT, *[path for path in BASELINE.rglob("*") if path.is_file()]]
    published = b"".join(path.read_bytes() for path in sorted(paths))
    patterns = (
        rb"/home/",
        rb"/Users/",
        rb"[A-Za-z]:\\Users\\",
        rb"\bapr-[0-9a-f]{8}-[0-9a-f-]{27,}\b",
        rb"\b(?:sk|pk)-(?:ant|live|proj|test)-[A-Za-z0-9/_+.-]{12,}",
        rb"(?:api[_-]?key|authorization|bearer)\s*[=:]\s*[^\s,;]{8,}",
        rb"RAW_(?:PROMPT|TOOL_ARGUMENT|SECRET)",
    )
    assert [pattern for pattern in patterns if re.search(pattern, published, re.IGNORECASE)] == []


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        ("Docket ranks first on our leaderboard.", "ranking"),
        ("Docket outperforms OtherTool.", "competitor"),
        ("This saved us $100 per run.", "savings"),
        ("The production success rate is 99%.", "production-rate"),
        ("These fixtures prove live model quality.", "model-quality"),
        ("Measured cost was $0.00.", "priced-zero"),
    ],
)
def test_public_claim_counterexamples_are_rejected(claim: str, expected: str) -> None:
    assert expected in _overclaims(claim)
