"""Artifact-installed RED contract for the OpenHands SDK adapter."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

import pytest
from tests.fixtures.runtime_adapters.scenarios import (
    SCENARIOS,
    GovernanceScenario,
)
from tests.support.cli import run as _run
from tests.support.runtime_adapters import invoke_openhands

LANE = "release"
REASON = "Prevents the OpenHands SDK adapter from losing governance-scenario parity, or from depending on network or credentials once installed from a built artifact."
RETIRE_WHEN = "the OpenHands adapter is dropped, or its parity is proven instead by test_runtime_adapter_parity.py alone."

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / "packages" / "docket-runtime"
FIXTURE = ROOT / "tests" / "fixtures" / "runtime_adapters" / "openhands"


@dataclass(frozen=True)
class OpenHandsArtifacts:
    wheel_python: Path
    sdist_python: Path


@pytest.fixture(scope="module")
def openhands_artifacts(tmp_path_factory: pytest.TempPathFactory) -> OpenHandsArtifacts:
    base = tmp_path_factory.mktemp("w28-c2-openhands-artifacts")
    dist = base / "dist"
    build_tmp = base / "build-tmp"
    build_tmp.mkdir()
    env = {
        **os.environ,
        "DOCKET_RUNTIME_BUILD_TMPDIR": str(build_tmp),
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(base / "uv-cache")),
        "PYTHONPATH": "",
    }
    _run("uv", "build", "--out-dir", str(dist), cwd=RUNTIME, env=env)
    wheel = next(dist.glob("docket_runtime-*.whl"))
    sdist = next(dist.glob("docket_runtime-*.tar.gz"))

    pythons: list[Path] = []
    for name, artifact in (("wheel", wheel), ("sdist", sdist)):
        venv = base / name
        fixture_env = {**env, "UV_PROJECT_ENVIRONMENT": str(venv)}
        _run("uv", "sync", "--frozen", "--no-dev", cwd=FIXTURE, env=fixture_env)
        python = venv / "bin" / "python"
        _run(
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            str(artifact),
            cwd=base,
            env=fixture_env,
        )
        pythons.append(python)

    assert not list(build_tmp.glob("docket-runtime-build-*"))
    return OpenHandsArtifacts(wheel_python=pythons[0], sdist_python=pythons[1])


def test_pinned_openhands_agent_uses_credential_free_loopback_fixture(
    openhands_artifacts: OpenHandsArtifacts, tmp_path: Path
) -> None:
    payload = invoke_openhands(openhands_artifacts.wheel_python, tmp_path=tmp_path, mode="probe")
    assert payload["requests"] == 1


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.name)
def test_openhands_adapter_matches_shared_governance_scenarios(
    openhands_artifacts: OpenHandsArtifacts,
    tmp_path: Path,
    scenario: GovernanceScenario,
) -> None:
    invoke_openhands(
        openhands_artifacts.wheel_python,
        tmp_path=tmp_path,
        mode="adapter",
        scenario=asdict(scenario),
    )


def test_openhands_adapter_rebuilt_sdist_matches_wheel_outside_checkout(
    openhands_artifacts: OpenHandsArtifacts, tmp_path: Path
) -> None:
    scenario = next(case for case in SCENARIOS if case.name == "approval_granted_mutation")
    payload = invoke_openhands(
        openhands_artifacts.sdist_python,
        tmp_path=tmp_path,
        mode="adapter",
        scenario=asdict(scenario),
    )
    assert payload["stop_reason"] == "final_message"
