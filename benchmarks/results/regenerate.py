#!/usr/bin/env python3
"""Regenerate the public Wave 29 adoption baseline from an exact Git commit."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "1.0.0"
BASELINE_ID = "wave29-adoption"
STARTER_ID = "starter"
C4_IDS = (
    "allowed",
    "policy-denied",
    "approval-denied",
    "approval-granted",
    "malformed-handoff",
    "hard-crash-resume",
    "corrupt-primary-recovery",
)
TIMING_EXCLUSIONS = (
    "attempt.approval_latency_ms",
    "aggregate.approval_latency_ms.total",
    "measurements.elapsed_ms",
)
CREDENTIAL_KEYS = (
    "ANTHROPIC_API_KEY",
    "DOCKET_LLM_API_KEY",
    "DOCKET_LLM_BASE_URL",
    "OPENAI_API_KEY",
    "SMOKE_LOCAL_API_KEY",
)


class RegenerationError(RuntimeError):
    """A bounded, actionable baseline-regeneration failure."""


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
        + b"\n"
    )


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RegenerationError(f"{path} must contain one JSON object")
    return value


def _write_object(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(value))


def _run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int = 600,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()
        raise RegenerationError(f"{' '.join(args[:3])} failed: {detail}")
    return result


def _isolated_env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    for key in CREDENTIAL_KEYS:
        env.pop(key, None)
    home = root / "operator-home"
    temp = root / "tmp"
    cache = root / "uv-cache"
    docket_home = root / "docket-home"
    for path in (home, temp, cache):
        path.mkdir(parents=True, exist_ok=True)
    env.update(
        {
            "DOCKET_HOME": str(docket_home),
            "DOCKET_SERVICE_MANAGER": "none",
            "HOME": str(home),
            "NO_COLOR": "1",
            "PYTHONPATH": "",
            "TMPDIR": str(temp),
            "UV_CACHE_DIR": str(cache),
        }
    )
    env.pop("VIRTUAL_ENV", None)
    return env


def _resolve_commit(source_commit: str, env: dict[str, str]) -> str:
    result = _run(
        ["git", "rev-parse", "--verify", f"{source_commit}^{{commit}}"],
        cwd=ROOT,
        env=env,
        timeout=30,
    )
    commit = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RegenerationError("source commit did not resolve to a full SHA-1")
    return commit


def _archive_source(commit: str, destination: Path, env: dict[str, str]) -> Path:
    archive = destination / "source.tar"
    source = destination / "source"
    _run(
        ["git", "archive", "--format=tar", "--output", str(archive), commit],
        cwd=ROOT,
        env=env,
        timeout=60,
    )
    source.mkdir()
    shutil.unpack_archive(str(archive), str(source), "tar")
    return source


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_and_install(source: Path, work: Path, env: dict[str, str]) -> tuple[Path, Path, str]:
    uv = shutil.which("uv", path=env.get("PATH"))
    if uv is None:
        raise RegenerationError("uv is required to build the exact release artifact")
    artifacts = work / "artifacts"
    _run([uv, "build", "--out-dir", str(artifacts)], cwd=source, env=env, timeout=600)
    wheels = sorted(artifacts.glob("docket-*.whl"))
    sdists = sorted(artifacts.glob("docket-*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise RegenerationError("root build must produce exactly one docket wheel and one sdist")

    venv = work / "artifact-venv"
    _run(
        [uv, "venv", str(venv), "--python", "3.11"],
        cwd=work,
        env=env,
        timeout=120,
    )
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    _run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            "--requirement",
            str(source / "examples" / "starter" / "requirements.lock"),
        ],
        cwd=work,
        env=env,
        timeout=600,
    )
    _run(
        [uv, "pip", "install", "--python", str(python), "--no-deps", str(wheels[0])],
        cwd=work,
        env=env,
        timeout=180,
    )
    inspected = _run(
        [
            str(python),
            "-c",
            (
                "import json, pathlib, platform, docket; "
                "print(json.dumps({'module': docket.__file__, "
                "'python': platform.python_version()}))"
            ),
        ],
        cwd=work,
        env=env,
        timeout=30,
    )
    installation = json.loads(inspected.stdout)
    if str(installation["python"]).split(".")[:2] != ["3", "11"]:
        raise RegenerationError("artifact environment is not Python 3.11")
    if not Path(str(installation["module"])).resolve().is_relative_to(venv.resolve()):
        raise RegenerationError("docket was not imported from the artifact environment")
    return python, wheels[0], _sha256(wheels[0])


def _rewrite_c4_provenance(
    source: Path,
    python: Path,
    raw: Path,
    manifest: dict[str, Any],
    commit: str,
    artifact_sha256: str,
    version: str,
    env: dict[str, str],
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    collected: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    entries = manifest.get("entries")
    if not isinstance(entries, list) or len(entries) != len(C4_IDS):
        raise RegenerationError("C4 driver did not emit all seven scenario entries")
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("paths"), dict):
            raise RegenerationError("C4 driver emitted a malformed entry")
        scenario_id = str(entry.get("scenario_id"))
        if scenario_id not in C4_IDS:
            raise RegenerationError(f"unexpected C4 scenario: {scenario_id}")
        paths = entry["paths"]
        scenario_path = raw / str(paths["scenario"])
        home = raw / str(paths["home"])
        jsonl = raw / str(paths["jsonl"])
        aggregate = raw / str(paths["aggregate"])
        scenario = _read_object(scenario_path)
        scenario["source"] = {"commit": commit, "artifact_sha256": artifact_sha256}
        runtime = scenario.get("runtime")
        if not isinstance(runtime, dict):
            raise RegenerationError("C4 scenario omitted runtime provenance")
        runtime["version"] = version
        _write_object(scenario_path, scenario)
        _run(
            [
                str(python),
                str(source / "benchmarks" / "harness.py"),
                "run",
                "--scenario",
                str(scenario_path),
                "--docket-home",
                str(home),
                "--jsonl",
                str(jsonl),
                "--aggregate",
                str(aggregate),
            ],
            cwd=source,
            env=env,
            timeout=60,
        )
        records = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()]
        if len(records) != 1 or not isinstance(records[0], dict):
            raise RegenerationError(f"{scenario_id} did not emit exactly one attempt")
        evidence = _read_object(raw / str(paths["evidence"]))
        collected[scenario_id] = (records[0], evidence)
    return collected


def _run_c4_matrix(
    source: Path,
    python: Path,
    work: Path,
    repetitions: int,
    commit: str,
    artifact_sha256: str,
    version: str,
    env: dict[str, str],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[int]]:
    attempts: dict[str, list[dict[str, Any]]] = {key: [] for key in C4_IDS}
    evidence: dict[str, list[dict[str, Any]]] = {key: [] for key in C4_IDS}
    elapsed: list[int] = []
    for ordinal in range(1, repetitions + 1):
        raw = work / f"c4-matrix-{ordinal}"
        started = time.monotonic()
        _run(
            [
                str(python),
                str(source / "benchmarks" / "scenarios" / "run.py"),
                "--output",
                str(raw),
                "--repetitions",
                "1",
            ],
            cwd=source,
            env=env,
            timeout=600,
        )
        elapsed.append(round((time.monotonic() - started) * 1000))
        matrix = _read_object(raw / "manifest.json")
        collected = _rewrite_c4_provenance(
            source, python, raw, matrix, commit, artifact_sha256, version, env
        )
        for scenario_id, (attempt, proof) in collected.items():
            attempts[scenario_id].append(attempt)
            evidence[scenario_id].append(proof)

    selected: dict[str, dict[str, Any]] = {}
    selected_evidence: dict[str, dict[str, Any]] = {}
    for scenario_id in C4_IDS:
        normalized = [copy.deepcopy(item) for item in attempts[scenario_id]]
        for item in normalized:
            item["approval_latency_ms"] = None
        if any(_canonical(item) != _canonical(normalized[0]) for item in normalized[1:]):
            raise RegenerationError(f"{scenario_id} changed across deterministic repetitions")
        if any(
            _canonical(item) != _canonical(evidence[scenario_id][0])
            for item in evidence[scenario_id][1:]
        ):
            raise RegenerationError(f"{scenario_id} evidence changed across repetitions")
        selected[scenario_id] = attempts[scenario_id][0]
        selected_evidence[scenario_id] = evidence[scenario_id][0]
    return selected, selected_evidence, elapsed


def _starter_run(source: Path, python: Path, run_root: Path, env: dict[str, str]) -> dict[str, int]:
    starter = run_root / "starter"
    workspace = run_root / "workspace"
    home = run_root / "docket-home"
    shutil.copytree(source / "examples" / "starter", starter)
    workspace.mkdir(parents=True)
    (workspace / "README.md").write_text("# Docket starter workspace\n", encoding="utf-8")
    target = workspace / "starter-output.txt"
    target.write_bytes(b"starter pending\n")
    run_env = dict(env)
    for key in CREDENTIAL_KEYS:
        run_env.pop(key, None)
    run_env.update(
        {
            "ALL_PROXY": "http://127.0.0.1:9",
            "DOCKET_HOME": str(home),
            "DOCKET_LOG_DIR": str(run_root / "logs"),
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "NO_PROXY": "127.0.0.1,localhost",
            "PIP_NO_INDEX": "1",
            "UV_OFFLINE": "1",
            "all_proxy": "http://127.0.0.1:9",
            "http_proxy": "http://127.0.0.1:9",
            "https_proxy": "http://127.0.0.1:9",
            "no_proxy": "127.0.0.1,localhost",
        }
    )
    result = _run(
        [str(python), "starter.py", "--workspace", str(workspace)],
        cwd=starter,
        env=run_env,
        input_text="deny\ngrant\n",
        timeout=180,
    )
    if "STARTER JOURNEY PASS" not in result.stdout or "Traceback" in result.stdout:
        raise RegenerationError("starter did not complete its denied/granted journey")
    match = re.search(r"^STARTER LOOPBACK http://127\.0\.0\.1:(\d+)/v1$", result.stdout, re.M)
    if match is None or int(match.group(1)) == 8081:
        raise RegenerationError("starter did not use an isolated non-8081 loopback port")
    if target.read_bytes() != b"docket starter approved\n":
        raise RegenerationError("starter grant did not produce the contracted mutation")
    sessions = sorted(home.glob("sessions/*/session.json"))
    if len(sessions) != 1:
        raise RegenerationError("starter did not retain exactly one provider session")
    usage = _read_object(sessions[0]).get("usage")
    if not isinstance(usage, dict):
        raise RegenerationError("starter session omitted provider-reported usage")
    return {
        "input_tokens": int(usage["inputTokens"]),
        "output_tokens": int(usage["outputTokens"]),
    }


def _run_starter(
    source: Path,
    python: Path,
    work: Path,
    repetitions: int,
    env: dict[str, str],
) -> tuple[dict[str, int], list[int]]:
    usage_samples: list[dict[str, int]] = []
    elapsed: list[int] = []
    for ordinal in range(1, repetitions + 1):
        started = time.monotonic()
        usage_samples.append(_starter_run(source, python, work / f"starter-{ordinal}", env))
        elapsed.append(round((time.monotonic() - started) * 1000))
    if any(sample != usage_samples[0] for sample in usage_samples[1:]):
        raise RegenerationError("starter usage changed across deterministic repetitions")
    return usage_samples[0], elapsed


def _attempt_id(record: dict[str, Any]) -> str:
    identity = {
        "attempt_ordinal": record["attempt_ordinal"],
        "measurement_class": record["measurement_class"],
        "runtime": record["runtime"],
        "scenario": record["scenario"],
        "source": record["source"],
    }
    return "sha256:" + hashlib.sha256(_canonical(identity)[:-1]).hexdigest()


def _starter_attempts(
    c4_attempts: dict[str, dict[str, Any]], usage: dict[str, int]
) -> list[dict[str, Any]]:
    denied = copy.deepcopy(c4_attempts["approval-denied"])
    granted = copy.deepcopy(c4_attempts["approval-granted"])
    for ordinal, record in enumerate((denied, granted), start=1):
        record["scenario"]["id"] = STARTER_ID
        record["attempt_ordinal"] = ordinal
        record["attempt_id"] = _attempt_id(record)
        record["prevented_policy_violations"] = 0
    denied["usage"] = {
        "basis": "provider_reported",
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }
    denied["tool_calls"] = {"total": 0, "executed": 0}
    granted["usage"] = {
        "basis": "provider_reported",
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "total_tokens": usage["input_tokens"] + usage["output_tokens"],
    }
    granted["tool_calls"] = {"total": 1, "executed": 1}
    return [denied, granted]


def _aggregate(
    source: Path,
    python: Path,
    jsonl: Path,
    aggregate: Path,
    env: dict[str, str],
) -> None:
    _run(
        [
            str(python),
            str(source / "benchmarks" / "harness.py"),
            "aggregate",
            "--jsonl",
            str(jsonl),
            "--aggregate",
            str(aggregate),
        ],
        cwd=source,
        env=env,
        timeout=60,
    )


def _summary(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    completions = sum(int(record["completed"]) for record in attempts)
    stop_reasons = Counter(str(record["stop_reason"]) for record in attempts)
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
        "failed_attempts": [
            {
                "scenario_id": record["scenario"]["id"],
                "attempt_ordinal": record["attempt_ordinal"],
                "stop_reason": record["stop_reason"],
            }
            for record in attempts
            if not record["completed"]
        ],
    }


def _publish_group(
    stage: Path,
    source: Path,
    python: Path,
    scenario_id: str,
    attempts: list[dict[str, Any]],
    evidence: dict[str, Any],
    elapsed: list[int],
    env: dict[str, str],
) -> dict[str, Any]:
    group = stage / scenario_id
    group.mkdir(parents=True)
    jsonl = group / "attempts.jsonl"
    jsonl.write_bytes(b"".join(_canonical(record) for record in attempts))
    aggregate = group / "aggregate.json"
    _aggregate(source, python, jsonl, aggregate, env)
    evidence_path = group / "evidence.json"
    measurements = group / "measurements.json"
    _write_object(evidence_path, evidence)
    _write_object(measurements, {"basis": "wall_clock_matrix_run", "elapsed_ms": elapsed})
    return {
        "scenario_id": scenario_id,
        "attempts": len(attempts),
        "completions": sum(int(record["completed"]) for record in attempts),
        "jsonl": f"{scenario_id}/attempts.jsonl",
        "aggregate": f"{scenario_id}/aggregate.json",
        "evidence": f"{scenario_id}/evidence.json",
        "measurements": f"{scenario_id}/measurements.json",
    }


def regenerate(source_commit: str, output: Path, repetitions: int) -> None:
    if repetitions != 3:
        raise RegenerationError("the published Wave 29 baseline requires exactly three repetitions")
    output = output.expanduser().resolve()
    if output.exists():
        raise RegenerationError(f"output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="docket-wave29-") as raw_temp:
        work = Path(raw_temp)
        env = _isolated_env(work / "environment")
        commit = _resolve_commit(source_commit, env)
        source = _archive_source(commit, work, env)
        version = (source / "VERSION").read_text(encoding="utf-8").strip()
        python, wheel, artifact_sha256 = _build_and_install(source, work, env)
        c4_attempts, c4_evidence, c4_elapsed = _run_c4_matrix(
            source, python, work, repetitions, commit, artifact_sha256, version, env
        )
        starter_usage, starter_elapsed = _run_starter(source, python, work, repetitions, env)
        starter_attempts = _starter_attempts(c4_attempts, starter_usage)

        stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
        try:
            entries: list[dict[str, Any]] = []
            all_attempts: list[dict[str, Any]] = []
            entries.append(
                _publish_group(
                    stage,
                    source,
                    python,
                    STARTER_ID,
                    starter_attempts,
                    {
                        "scenario_id": STARTER_ID,
                        "repetitions": repetitions,
                        "artifact_installed": True,
                        "decisions": ["denied", "granted"],
                        "journey_passed": True,
                        "port_8081_used": False,
                    },
                    starter_elapsed,
                    env,
                )
            )
            all_attempts.extend(starter_attempts)
            for scenario_id in C4_IDS:
                record = c4_attempts[scenario_id]
                entries.append(
                    _publish_group(
                        stage,
                        source,
                        python,
                        scenario_id,
                        [record],
                        c4_evidence[scenario_id],
                        c4_elapsed,
                        env,
                    )
                )
                all_attempts.append(record)
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "baseline_id": BASELINE_ID,
                "source": {
                    "commit": commit,
                    "artifact": {
                        "filename": wheel.name,
                        "package": "docket",
                        "version": version,
                        "sha256": artifact_sha256,
                    },
                },
                "repetitions": repetitions,
                "entries": entries,
                "summary": _summary(all_attempts),
                "comparison": {
                    "excluded_fields": list(TIMING_EXCLUSIONS),
                    "tolerance_ms": 5_000,
                },
            }
            _write_object(stage / "manifest.json", manifest)
            os.replace(stage, output)
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        regenerate(args.source_commit, args.output, args.repetitions)
    except (OSError, ValueError, RegenerationError, subprocess.SubprocessError) as exc:
        print(f"regeneration error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
