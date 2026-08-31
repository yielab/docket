"""Artifact-only contract for the canonical root ``docket`` distribution."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROJECT_URLS = {
    "Homepage, https://github.com/yielab/docket",
    "Issues, https://github.com/yielab/docket/issues",
    "Source, https://github.com/yielab/docket",
}


def _run(*args: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, check=True)


@pytest.mark.parametrize("suffix", [".whl", ".tar.gz"])
def test_root_artifacts_install_as_canonical_docket_without_source_tree(
    tmp_path: Path, suffix: str
) -> None:
    """Both release artifacts work at the declared direct-dependency floor."""
    artifacts = tmp_path / "artifacts"
    clean_cwd = tmp_path / "outside-source"
    clean_cwd.mkdir()
    cache = tmp_path / "uv-cache"
    env = {
        **os.environ,
        "DOCKET_HOME": str(tmp_path / "docket-home"),
        "UV_CACHE_DIR": str(cache),
        "PYTHONPATH": "",
    }

    _run("uv", "build", "--out-dir", str(artifacts), cwd=ROOT, env=env)
    artifact = next(artifacts.glob(f"docket-*{suffix}"))
    floors = tmp_path / "floors.txt"
    _run(
        "uv",
        "pip",
        "compile",
        "--resolution",
        "lowest-direct",
        "pyproject.toml",
        "-o",
        str(floors),
        cwd=ROOT,
        env=env,
    )
    environment = tmp_path / f"venv-{suffix.removeprefix('.').replace('.', '-')}"
    _run("uv", "venv", str(environment), "--python", "3.11", cwd=clean_cwd, env=env)
    python = environment / "bin" / "python"
    docket = environment / "bin" / "docket"
    _run("uv", "pip", "install", "--python", str(python), "-r", str(floors), cwd=clean_cwd, env=env)
    _run(
        "uv",
        "pip",
        "install",
        "--python",
        str(python),
        "--no-deps",
        str(artifact),
        cwd=clean_cwd,
        env=env,
    )

    version = _run(str(docket), "--version", cwd=clean_cwd, env=env)
    help_output = _run(str(docket), "--help", cwd=clean_cwd, env=env)
    init_help = _run(str(docket), "init", "--help", cwd=clean_cwd, env=env)
    metadata = _run(
        str(python),
        "-c",
        (
            "from importlib.metadata import metadata, version; "
            "from pathlib import Path; "
            "from docket import __version__; "
            "m = metadata('docket'); "
            "print(version('docket')); "
            "print(__version__); "
            "print(m['License-Expression']); "
            "print(m['Requires-Python']); "
            "print('|'.join(m.get_all('Project-URL') or ())); "
            "print('|'.join(m.get_all('License-File') or ())); "
            "print(Path(__import__('docket').__file__).resolve())"
        ),
        cwd=clean_cwd,
        env=env,
    )

    lines = metadata.stdout.splitlines()
    assert version.stdout.strip() == f"docket {lines[0]}"
    assert lines[:4] == ["0.2.0b1", "0.2.0-beta.1", "Apache-2.0", ">=3.11"]
    assert set(lines[4].split("|")) == PROJECT_URLS
    assert lines[5] == "LICENSE"
    assert Path(lines[6]).is_relative_to(environment)
    assert "Usage:" in help_output.stdout
    assert "initialize" in init_help.stdout.lower()

    _run("uv", "pip", "uninstall", "--python", str(python), "docket", cwd=clean_cwd, env=env)
    assert not docket.exists()
    absent = subprocess.run(
        [str(python), "-c", "import docket"],
        cwd=clean_cwd,
        env=env,
        text=True,
        capture_output=True,
    )
    assert absent.returncode != 0
    assert "No module named 'docket'" in absent.stderr
    metadata_absent = subprocess.run(
        [str(python), "-c", "from importlib.metadata import version; version('docket')"],
        cwd=clean_cwd,
        env=env,
        text=True,
        capture_output=True,
    )
    assert metadata_absent.returncode != 0
    assert "PackageNotFoundError" in metadata_absent.stderr
    _run(str(python), "-c", "import typer", cwd=clean_cwd, env=env)
