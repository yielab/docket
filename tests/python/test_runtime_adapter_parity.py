"""Merged installed-artifact parity contract for W28-C4."""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from dataclasses import asdict, dataclass
from pathlib import Path

import pytest

from tests.fixtures.runtime_adapters.scenarios import (
    ADVERTISED_TOOLS,
    PLANTED_BYPASSES,
    SCENARIOS,
    GovernanceScenario,
)
from tests.python.test_pydantic_ai_adapter import _scenario_source
from tests.python.test_runtime_openhands_adapter import _invoke as _invoke_openhands

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "packages" / "docket-runtime"
FIXTURES = ROOT / "tests" / "fixtures" / "runtime_adapters"
GOVERNED_SCENARIOS = tuple(
    scenario for scenario in SCENARIOS if scenario.tool_name in ADVERTISED_TOOLS
)


@dataclass(frozen=True)
class InstalledAdapterMatrix:
    wheel: dict[str, Path]
    sdist: dict[str, Path]
    base_python: Path


def _run(*args: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr or result.stdout
    return result


def _install_adapter(
    *,
    adapter: str,
    artifact: Path,
    artifact_name: str,
    base: Path,
    env: dict[str, str],
) -> Path:
    fixture = FIXTURES / adapter
    venv = base / f"{adapter}-{artifact_name}"
    install_env = {**env, "UV_PROJECT_ENVIRONMENT": str(venv)}
    _run(
        "uv",
        "sync",
        "--frozen",
        "--no-install-project",
        "--project",
        str(fixture),
        cwd=base,
        env=install_env,
    )
    python = venv / "bin" / "python"
    _run(
        "uv",
        "pip",
        "install",
        "--python",
        str(python),
        str(artifact),
        cwd=base,
        env=install_env,
    )
    return python


@pytest.fixture(scope="module")
def installed_adapter_matrix(
    tmp_path_factory: pytest.TempPathFactory,
) -> InstalledAdapterMatrix:
    """Build wheel/sdist once, then install both into each disjoint fixture."""
    base = tmp_path_factory.mktemp("w28-c4-installed-matrix")
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

    installed: dict[str, dict[str, Path]] = {"wheel": {}, "sdist": {}}
    for artifact_name, artifact in (("wheel", wheel), ("sdist", sdist)):
        for adapter in ("openhands", "pydantic_ai"):
            installed[artifact_name][adapter] = _install_adapter(
                adapter=adapter,
                artifact=artifact,
                artifact_name=artifact_name,
                base=base,
                env=env,
            )

    base_venv = base / "base-runtime"
    _run("uv", "venv", str(base_venv), "--python", "3.11", cwd=base, env=env)
    base_python = base_venv / "bin" / "python"
    _run(
        "uv",
        "pip",
        "install",
        "--python",
        str(base_python),
        str(wheel),
        cwd=base,
        env=env,
    )

    assert not list(build_tmp.glob("docket-runtime-build-*"))
    return InstalledAdapterMatrix(
        wheel=installed["wheel"],
        sdist=installed["sdist"],
        base_python=base_python,
    )


def _invoke_pydantic_ai(
    python: Path, *, scenario: GovernanceScenario, tmp_path: Path
) -> dict[str, object]:
    outside = tmp_path / "pydantic-outside-checkout"
    outside.mkdir(parents=True)
    env = {
        **os.environ,
        "DOCKET_HOME": str(tmp_path / "pydantic-docket-home"),
        "PYTHONPATH": "",
        "W28_WORKSPACE": str(tmp_path / "pydantic-workspace"),
    }
    result = subprocess.run(
        [str(python), "-c", _scenario_source(scenario, parity=True)],
        cwd=outside,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    line = next(line for line in result.stdout.splitlines() if line.startswith("W28_RESULT="))
    return json.loads(line.removeprefix("W28_RESULT="))


def _normalized_pair(
    matrix: InstalledAdapterMatrix,
    *,
    artifact_name: str,
    scenario: GovernanceScenario,
    tmp_path: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    pythons = getattr(matrix, artifact_name)
    openhands = _invoke_openhands(
        pythons["openhands"],
        tmp_path=tmp_path / "openhands",
        mode="adapter",
        scenario=asdict(scenario),
    )["normalized"]
    pydantic_ai = _invoke_pydantic_ai(
        pythons["pydantic_ai"],
        scenario=scenario,
        tmp_path=tmp_path,
    )["normalized"]
    assert isinstance(openhands, dict)
    assert isinstance(pydantic_ai, dict)
    return openhands, pydantic_ai


def _assert_shared_oracle(outcome: dict[str, object]) -> None:
    assert outcome["advertised_tools"] == sorted(ADVERTISED_TOOLS)
    assert not set(outcome["advertised_tools"]) & set(PLANTED_BYPASSES)
    chain = outcome["audit_chain"]
    assert isinstance(chain, dict)
    assert chain["break"] is None
    assert chain["legacy"] == 0
    if chain["exists"]:
        assert chain["chained"] == chain["lines"]


@pytest.mark.parametrize("scenario", GOVERNED_SCENARIOS, ids=lambda case: case.name)
def test_wheel_adapters_have_identical_governed_execution_outcomes(
    installed_adapter_matrix: InstalledAdapterMatrix,
    scenario: GovernanceScenario,
    tmp_path: Path,
) -> None:
    openhands, pydantic_ai = _normalized_pair(
        installed_adapter_matrix,
        artifact_name="wheel",
        scenario=scenario,
        tmp_path=tmp_path,
    )
    _assert_shared_oracle(openhands)
    _assert_shared_oracle(pydantic_ai)
    assert pydantic_ai == openhands


@pytest.mark.parametrize("repetition", range(2))
def test_rebuilt_sdist_repeats_exactly_once_approved_mutation_parity(
    installed_adapter_matrix: InstalledAdapterMatrix,
    repetition: int,
    tmp_path: Path,
) -> None:
    scenario = next(case for case in SCENARIOS if case.name == "approval_granted_mutation")
    openhands, pydantic_ai = _normalized_pair(
        installed_adapter_matrix,
        artifact_name="sdist",
        scenario=scenario,
        tmp_path=tmp_path / str(repetition),
    )
    _assert_shared_oracle(openhands)
    _assert_shared_oracle(pydantic_ai)
    assert openhands["handler_calls"] == ["mutate_state"]
    assert pydantic_ai == openhands


def test_base_artifact_keeps_framework_dependencies_optional_and_actionable(
    installed_adapter_matrix: InstalledAdapterMatrix, tmp_path: Path
) -> None:
    source = textwrap.dedent(
        """
        import importlib

        import docket_runtime

        assert docket_runtime.Runtime
        expected = {
            "docket_runtime.adapters.openhands": "openhands",
            "docket_runtime.adapters.pydantic_ai": "pydantic_ai",
        }
        for module, missing in expected.items():
            try:
                importlib.import_module(module)
            except ModuleNotFoundError as exc:
                assert exc.name == missing, (module, exc.name)
            else:
                raise AssertionError(f"{module} imported without optional dependency {missing}")
        """
    )
    outside = tmp_path / "base-outside-checkout"
    outside.mkdir()
    _run(
        str(installed_adapter_matrix.base_python),
        "-c",
        source,
        cwd=outside,
        env={**os.environ, "PYTHONPATH": ""},
    )
