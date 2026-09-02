"""Whole-journey RED contract for Wave 29 adversarial benchmark scenarios."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "benchmarks" / "scenarios" / "run.py"
CASES = ROOT / "benchmarks" / "scenarios" / "cases"
HARNESS = ROOT / "benchmarks" / "harness.py"
SCHEMA = ROOT / "benchmarks" / "schema.json"

SCENARIOS = {
    "allowed",
    "policy-denied",
    "approval-denied",
    "approval-granted",
    "malformed-handoff",
    "hard-crash-resume",
    "corrupt-primary-recovery",
}
MUTATING = {"allowed", "approval-granted", "hard-crash-resume"}
DENIED = {"policy-denied", "approval-denied"}
ACTION_ORACLES = {
    "allowed": {"pipeline.run"},
    "policy-denied": {"pipeline.run"},
    "approval-denied": {"pipeline.run", "approval.deny"},
    "approval-granted": {"pipeline.run", "approval.grant"},
    "malformed-handoff": {"pipeline.run"},
    "hard-crash-resume": {"pipeline.run", "pipeline.run.resume"},
    "corrupt-primary-recovery": {"runs.list"},
}
SECRET_SENTINELS = (
    "sk-ant-c4-secret-sentinel",
    "sk-proj-c4-secret-sentinel",
    "c4-provider-token-sentinel",
)
ENTRY_KEYS = {"scenario_id", "repetition", "port", "paths"}
PATH_KEYS = {
    "home",
    "workspace",
    "before",
    "target",
    "scenario",
    "jsonl",
    "aggregate",
    "evidence",
}
EVIDENCE_KEYS = {
    "scenario_id",
    "repetition",
    "public_actions",
    "write_count",
    "before_sha256",
    "after_sha256",
    "malformed_primary_sha256",
}


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
        + b"\n"
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{path} must contain one JSON object"
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert values and all(isinstance(value, dict) for value in values)
    return values


def _under(root: Path, raw: object) -> Path:
    assert isinstance(raw, str) and raw
    relative = Path(raw)
    assert not relative.is_absolute() and ".." not in relative.parts
    resolved = (root / relative).resolve()
    assert resolved.is_relative_to(root.resolve())
    return resolved


def _locator_file(home: Path, locator: object) -> Path:
    assert isinstance(locator, str) and locator
    return _under(home, locator.split("#", 1)[0])


def _require_red_targets() -> None:
    expected = [DRIVER, *(CASES / f"{name}.json" for name in sorted(SCENARIOS))]
    missing = [str(path.relative_to(ROOT)) for path in expected if not path.is_file()]
    assert not missing, "RED: adversarial scenario files are not implemented: " + ", ".join(missing)


def _run_matrix(tmp_path: Path) -> tuple[Path, dict[str, Any], bytes]:
    _require_red_targets()
    output = tmp_path / "scenario-output"
    fake_home = tmp_path / "forbidden-shared-home"
    temp = tmp_path / "tmp"
    cache = tmp_path / "cache"
    temp.mkdir()
    cache.mkdir()
    env = {
        **os.environ,
        "DOCKET_HOME": str(fake_home),
        "HOME": str(tmp_path / "operator-home"),
        "TMPDIR": str(temp),
        "UV_CACHE_DIR": str(cache),
        "ANTHROPIC_API_KEY": SECRET_SENTINELS[0],
        "OPENAI_API_KEY": SECRET_SENTINELS[1],
        "DOCKET_LLM_API_KEY": SECRET_SENTINELS[2],
        "HTTP_PROXY": "http://127.0.0.1:1",
        "HTTPS_PROXY": "http://127.0.0.1:1",
        "ALL_PROXY": "http://127.0.0.1:1",
        "NO_PROXY": "127.0.0.1,localhost",
    }
    result = subprocess.run(
        [sys.executable, str(DRIVER), "--output", str(output), "--repetitions", "3"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    manifest_path = output / "manifest.json"
    raw_manifest = manifest_path.read_bytes()
    manifest = _object(manifest_path)
    assert raw_manifest == _canonical(manifest)
    assert not fake_home.exists(), "scenario driver leaked into the inherited shared DOCKET_HOME"
    return output, manifest, raw_manifest


def test_public_adversarial_and_recovery_matrix_isolated_and_c3_valid(tmp_path: Path) -> None:
    """Seven public journeys repeated three times emit stable, inspectable C3 evidence."""
    output, manifest, raw_manifest = _run_matrix(tmp_path)
    assert set(manifest) == {"schema_version", "repetitions", "entries"}
    assert manifest["schema_version"] == "1.0.0"
    assert manifest["repetitions"] == 3
    entries = manifest["entries"]
    assert isinstance(entries, list) and len(entries) == len(SCENARIOS) * 3

    counts: Counter[str] = Counter()
    ports: set[int] = set()
    roots: set[Path] = set()
    normalized: defaultdict[str, list[tuple[bytes, bytes]]] = defaultdict(list)
    schema = _object(SCHEMA)
    validator = Draft202012Validator(schema)

    for entry in entries:
        assert isinstance(entry, dict) and set(entry) == ENTRY_KEYS
        scenario_id = entry["scenario_id"]
        repetition = entry["repetition"]
        port = entry["port"]
        assert scenario_id in SCENARIOS
        assert isinstance(repetition, int) and 1 <= repetition <= 3
        assert isinstance(port, int) and 1024 <= port <= 65535 and port != 8081
        counts[scenario_id] += 1
        assert port not in ports
        ports.add(port)

        paths = entry["paths"]
        assert isinstance(paths, dict) and set(paths) == PATH_KEYS
        resolved = {name: _under(output, raw) for name, raw in paths.items()}
        assert resolved["home"].is_dir() and resolved["workspace"].is_dir()
        assert resolved["home"] not in roots and resolved["workspace"] not in roots
        roots.update({resolved["home"], resolved["workspace"]})
        assert all(path.exists() for path in resolved.values())

        evidence = _object(resolved["evidence"])
        assert set(evidence) == EVIDENCE_KEYS
        assert evidence["scenario_id"] == scenario_id
        assert evidence["repetition"] == repetition
        actions = evidence["public_actions"]
        assert isinstance(actions, list) and set(actions) == ACTION_ORACLES[scenario_id]

        before = resolved["before"].read_bytes()
        after = resolved["target"].read_bytes()
        assert evidence["before_sha256"] == _sha256(before)
        assert evidence["after_sha256"] == _sha256(after)
        if scenario_id in MUTATING:
            assert after != before and evidence["write_count"] == 1
        else:
            assert after == before and evidence["write_count"] == 0

        attempts = _jsonl(resolved["jsonl"])
        assert len(attempts) == 1
        attempt = attempts[0]
        aggregate = _object(resolved["aggregate"])
        validator.validate(attempt)
        validator.validate(aggregate)
        assert attempt["scenario"] == {"id": scenario_id, "seed": 29, "version": "1.0.0"}
        assert attempt["measurement_class"] == "deterministic"
        assert attempt["attempt_ordinal"] == 1
        assert attempt["cost"] is None

        expected_completed = scenario_id in {
            "allowed",
            "approval-granted",
            "hard-crash-resume",
            "corrupt-primary-recovery",
        }
        assert attempt["completed"] is expected_completed
        assert attempt["prevented_policy_violations"] == (1 if scenario_id in DENIED else 0)
        assert attempt["handoff_failures"] == (1 if scenario_id == "malformed-handoff" else 0)
        if scenario_id in {"approval-denied", "approval-granted"}:
            assert isinstance(attempt["approval_latency_ms"], int)
            assert attempt["approval_latency_ms"] >= 0
        else:
            assert attempt["approval_latency_ms"] is None

        recovery = attempt["recovery"]
        if scenario_id == "hard-crash-resume":
            assert recovery["stale_claim_observed"] is True
            assert recovery["retained_hops"] >= 1
            assert recovery["resumed_to_terminal"] is True
            snapshot = _object(
                _locator_file(resolved["home"], attempt["locators"]["recovery_snapshot"])
            )
            task_doc = _object(_locator_file(resolved["home"], attempt["locators"]["task"]))
            stale = snapshot["tasks"][0]
            terminal = task_doc["tasks"][0]
            assert stale["failureKind"] == "stale_claim"
            assert terminal["hops"][: len(stale["hops"])] == stale["hops"]
        else:
            assert recovery == {
                "stale_claim_observed": False,
                "retained_hops": 0,
                "resumed_to_terminal": False,
            }

        for key in ("run", "task", "session", "trace"):
            assert _locator_file(resolved["home"], attempt["locators"][key]).is_file()
        for audit_locator in attempt["locators"]["audit"]:
            assert _locator_file(resolved["home"], audit_locator).is_file()

        if scenario_id == "corrupt-primary-recovery":
            primary = resolved["home"] / "docket-runs.json"
            backup = resolved["home"] / "docket-runs.json.bak"
            quarantine = resolved["home"] / "docket-runs.json.corrupt"
            assert _object(primary) == _object(backup)
            assert quarantine.read_bytes() and not list(resolved["home"].glob("*.tmp"))
            assert evidence["malformed_primary_sha256"] == _sha256(quarantine.read_bytes())
            assert primary.stat().st_mode & 0o777 == 0o600
        else:
            assert evidence["malformed_primary_sha256"] is None

        rebuilt = resolved["aggregate"].with_name("aggregate-rebuilt.json")
        rebuilt_result = subprocess.run(
            [
                sys.executable,
                str(HARNESS),
                "aggregate",
                "--jsonl",
                str(resolved["jsonl"]),
                "--aggregate",
                str(rebuilt),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert rebuilt_result.returncode == 0, rebuilt_result.stdout + rebuilt_result.stderr
        assert rebuilt.read_bytes() == resolved["aggregate"].read_bytes()
        normalized[scenario_id].append(
            (resolved["jsonl"].read_bytes(), resolved["aggregate"].read_bytes())
        )

    assert counts == Counter(dict.fromkeys(SCENARIOS, 3))
    assert all(len(set(results)) == 1 for results in normalized.values())

    published = raw_manifest + b"".join(
        path.read_bytes()
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name in {"attempts.jsonl", "aggregate.json", "evidence.json"}
    )
    for sentinel in (*SECRET_SENTINELS, str(tmp_path), str(output)):
        assert sentinel.encode() not in published
