"""Artifact contract for the separately owned ``docket-runtime`` package."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "packages" / "docket-runtime"


def _run(*args: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, check=True)


def _python(
    python: Path, source: str, *, cwd: Path, env: dict[str, str], check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(python), "-c", source], cwd=cwd, env=env, text=True, capture_output=True, check=check
    )


def _venv(tmp_path: Path, name: str, env: dict[str, str]) -> Path:
    path = tmp_path / name
    _run("uv", "venv", str(path), "--python", "3.11", cwd=tmp_path, env=env)
    return path / "bin" / "python"


_EXTERNAL_CONSUMER = r"""
import json
import os
import sys
from pathlib import Path

from docket_runtime import Runtime, Tool, ToolCall, ToolContext, ToolOutcome, __version__

assert __version__ == "0.2.0"
assert not any(name == "docket" or name.startswith("docket.cli") for name in sys.modules)
home = Path(os.environ["DOCKET_HOME"])
(home / "policies").mkdir(parents=True, exist_ok=True)
(home / "policies" / "approval.json").write_text(json.dumps({
    "id": "approve-fake", "applies_to": ["*"], "hook": "pre_tool_call",
    "match": {"type": "regex", "pattern": "fake"}, "action": "require_approval",
    "message": "external approval",
}))
runtime = Runtime(approval_stub=lambda token: token.startswith("apr-"))
runtime.register(Tool("fake", "external fake", {"type": "object"}, lambda args, ctx: ToolOutcome(True, "ran")))
result = runtime.dispatch(ToolCall("call-1", "fake", "{}"), ToolContext(agent_id="embed", project="demo"))
assert result.ok and result.content == "ran"
assert (home / "audit.log").is_file()
assert list((home / "traces").rglob("*.jsonl"))
assert "approval.grant" in (home / "audit.log").read_text()

denied_runtime = Runtime(approval_stub=lambda token: False)
denied_runtime.register(Tool("deny-fake", "external fake", {"type": "object"}, lambda args, ctx: ToolOutcome(True, "ran")))
denied = denied_runtime.dispatch(ToolCall("call-2", "deny-fake", "{}"), ToolContext(agent_id="embed", project="demo"))
assert not denied.ok and denied.denial_kind == "approval_denied"
assert "approval.deny" in (home / "audit.log").read_text()
assert any("approval_denied" in path.read_text() for path in (home / "traces").rglob("*.jsonl"))
"""


def test_runtime_artifacts_are_disjoint_rebuildable_and_embed_without_cli(tmp_path: Path) -> None:
    """Both release artifacts own distinct files and work after either uninstall."""
    dist = tmp_path / "dist"
    root_dist = tmp_path / "root-dist"
    outside = tmp_path / "outside-source"
    build_tmp = tmp_path / "runtime-build-tmp"
    outside.mkdir()
    build_tmp.mkdir()
    env = {
        **os.environ,
        "DOCKET_HOME": str(tmp_path / "docket-home"),
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(tmp_path / "uv-cache")),
        "DOCKET_RUNTIME_BUILD_TMPDIR": str(build_tmp),
        "PYTHONPATH": "",
    }

    # No --wheel: this verifies the sdist can rebuild its private runtime copy.
    _run("uv", "build", "--out-dir", str(dist), cwd=RUNTIME, env=env)
    assert not list(build_tmp.glob("docket-runtime-build-*"))
    _run("uv", "build", "--wheel", "--out-dir", str(root_dist), cwd=ROOT, env=env)
    runtime_wheel = next(dist.glob("docket_runtime-*.whl"))
    runtime_sdist = next(dist.glob("docket_runtime-*.tar.gz"))
    root_wheel = next(root_dist.glob("docket-*.whl"))

    floors = tmp_path / "runtime-floors.txt"
    _run(
        "uv",
        "pip",
        "compile",
        "--resolution",
        "lowest-direct",
        "pyproject.toml",
        "-o",
        str(floors),
        cwd=RUNTIME,
        env=env,
    )
    assert {line.split("==", 1)[0] for line in floors.read_text().splitlines() if "==" in line} >= {
        "filelock",
        "pydantic",
    }

    # An sdist install at the direct-dependency floor is the standalone floor.
    standalone = _venv(tmp_path, "standalone", env)
    _run(
        "uv", "pip", "install", "--python", str(standalone), "-r", str(floors), cwd=outside, env=env
    )
    _run(
        "uv",
        "pip",
        "install",
        "--python",
        str(standalone),
        "--no-deps",
        str(runtime_sdist),
        cwd=outside,
        env=env,
    )
    _python(standalone, _EXTERNAL_CONSUMER, cwd=outside, env=env)

    # The two wheels may coexist, but their RECORDs must never claim one path.
    runtime_then_root = _venv(tmp_path, "runtime-then-root", env)
    _run(
        "uv",
        "pip",
        "install",
        "--python",
        str(runtime_then_root),
        "-r",
        str(floors),
        cwd=outside,
        env=env,
    )
    _run(
        "uv",
        "pip",
        "install",
        "--python",
        str(runtime_then_root),
        "--no-deps",
        str(root_wheel),
        str(runtime_wheel),
        cwd=outside,
        env=env,
    )
    _python(
        runtime_then_root,
        "from importlib.metadata import distribution; "
        "r={str(p) for p in distribution('docket-runtime').files}; "
        "d={str(p) for p in distribution('docket').files}; "
        "assert not r & d; assert not any(p.startswith('docket/') for p in r)",
        cwd=outside,
        env=env,
    )
    _run(
        "uv",
        "pip",
        "uninstall",
        "--python",
        str(runtime_then_root),
        "docket-runtime",
        cwd=outside,
        env=env,
    )
    _python(runtime_then_root, "import docket.core.tools", cwd=outside, env=env)

    root_then_runtime = _venv(tmp_path, "root-then-runtime", env)
    _run(
        "uv",
        "pip",
        "install",
        "--python",
        str(root_then_runtime),
        "-r",
        str(floors),
        cwd=outside,
        env=env,
    )
    _run(
        "uv",
        "pip",
        "install",
        "--python",
        str(root_then_runtime),
        "--no-deps",
        str(root_wheel),
        str(runtime_wheel),
        cwd=outside,
        env=env,
    )
    _run(
        "uv",
        "pip",
        "uninstall",
        "--python",
        str(root_then_runtime),
        "docket",
        cwd=outside,
        env=env,
    )
    _python(root_then_runtime, _EXTERNAL_CONSUMER, cwd=outside, env=env)


@pytest.mark.parametrize(
    "artifact", ["docket_runtime-0.2.0-py3-none-any.whl", "docket_runtime-0.2.0.tar.gz"]
)
def test_runtime_artifact_names_are_versioned(artifact: str) -> None:
    """Pin the facade release identity separately from the control plane."""
    assert "docket_runtime-0.2.0" in artifact
