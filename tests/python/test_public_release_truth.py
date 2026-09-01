"""W26-C11 public documentation and release-truth contract."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote

import filelock

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
QUICKSTART = ROOT / "docs" / "QUICK-START-DOCKET.md"
SPEC_INDEX = ROOT / "specs" / "README.md"
RUNTIME_PACKAGE = ROOT / "packages" / "docket-runtime"
RUNTIME_EXAMPLE = ROOT / "examples" / "runtime_embed.py"

PUBLIC_MARKDOWN = (
    README,
    ROOT / "COMPATIBILITY.md",
    ROOT / "SECURITY.md",
    ROOT / "docs" / "README.md",
    QUICKSTART,
    ROOT / "docs" / "MODEL-GATEWAYS.md",
    ROOT / "docs" / "SECURITY-SIMPLE.md",
    ROOT / "docs" / "commands.md",
    ROOT / "examples" / "configs" / "README.md",
)

INDEXED_SPECS = {
    "Agent Lifecycle": "functional/agent-lifecycle.spec.md",
    "Agent Loop": "functional/agent-loop.spec.md",
    "API Keys": "functional/api-keys.spec.md",
    "Audit": "functional/audit.spec.md",
    "Cost Tracking": "functional/cost-tracking.spec.md",
    "Model Profiles": "functional/model-profiles.spec.md",
    "Pipeline Format": "functional/pipeline-format.spec.md",
    "Pod Blueprints": "functional/pod-blueprints.spec.md",
    "Pod Dispatch": "functional/pod-dispatch.spec.md",
    "Role Archetypes": "functional/role-archetypes.spec.md",
    "Security Gates": "functional/security-gates.spec.md",
    "Session History": "functional/session-history.spec.md",
    "Session Scoping": "functional/session-scoping.spec.md",
    "Telegram Integration": "functional/telegram-integration.spec.md",
    "Workspace Structure": "functional/workspace-structure.spec.md",
    "CLI Interface": "api/cli-interface.spec.md",
    "MCP Client": "functional/mcp-client.spec.md",
    "Runtime Library": "api/runtime-library.spec.md",
    "MCP Server": "api/mcp-server.spec.md",
    "CLI JSON Shapes": "data/cli-json-shapes.spec.md",
    "docket-meta schema": "data/docket-meta.spec.md",
    "Serve Read API": "data/serve-read-api.spec.md",
    "Input Validation": "validation/input-validation.spec.md",
    "Test Framework": "test-framework.md",
    "User Stories": "acceptance/user-stories.md",
}


def _markdown_destinations(text: str) -> list[str]:
    return re.findall(r"!?\[[^]]*]\(([^)]+)\)", text)


def _local_target(source: Path, destination: str) -> Path | None:
    destination = destination.strip().strip("<>")
    if not destination or destination.startswith(("#", "/")):
        return None
    if re.match(r"^[a-z][a-z0-9+.-]*:", destination, flags=re.IGNORECASE):
        return None
    target = unquote(destination.split("#", 1)[0].split("?", 1)[0])
    if not target:
        return None
    return (source.parent / target).resolve()


def test_public_relative_markdown_links_resolve() -> None:
    """Every local link in the supported public corpus must name a real repository path."""
    broken: list[str] = []
    for source in PUBLIC_MARKDOWN:
        for destination in _markdown_destinations(source.read_text(encoding="utf-8")):
            target = _local_target(source, destination)
            if target is None:
                continue
            if not target.is_relative_to(ROOT) or not target.exists():
                broken.append(f"{source.relative_to(ROOT)} -> {destination}")

    assert broken == [], "broken repository-relative public link(s):\n" + "\n".join(broken)


def test_public_front_door_is_compact_and_visuals_are_reproducible() -> None:
    """The repository landing page and every retained terminal asset have one current owner."""

    readme = README.read_text(encoding="utf-8")
    lines = readme.splitlines()
    assert len(lines) <= 500, f"README is overcrowded at {len(lines)} lines"
    assert len(readme.split()) <= 4_000, "README duplicates detail owned by the public guides"

    required_headings = (
        "## Features",
        "## Quick start",
        "## Best practices",
        "## Known limits",
        "## Documentation",
        "## Contributing",
    )
    missing_headings = [heading for heading in required_headings if heading not in readme]
    assert missing_headings == [], f"README is missing front-door section(s): {missing_headings}"
    for duplicated_owner in (
        "## Command reference",
        "## Integrating with a control plane",
        "## What's next",
    ):
        assert duplicated_owner not in readme, f"README duplicates {duplicated_owner!r}"

    assets = ROOT / "docs" / "assets"
    expected_media = {"hero.gif", "isolation.png", "governance.png"}
    actual_media = {
        path.name for path in assets.iterdir() if path.suffix.lower() in {".gif", ".png"}
    }
    assert actual_media == expected_media, (
        f"public terminal assets must be minimal and fully owned: {actual_media}"
    )

    public_copy = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (README, ROOT / "docs" / "README.md", assets / "README.md")
    )
    for name in expected_media:
        assert name in public_copy, f"retained asset is not referenced: {name}"
    assert "openclaw" not in public_copy.lower(), "retired brand remains in public visual copy"

    renderer = ROOT / "scripts" / "render-doc-assets.py"
    assert renderer.is_file(), "all retained terminal visuals need one reproducible renderer"
    result = subprocess.run(
        [sys.executable, str(renderer), "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_public_commands_and_claims_match_shipped_boundaries() -> None:
    """Reject the exact stale command, installer, cancellation, and runtime claims from C11."""
    checks = (
        (
            ROOT / "examples" / "configs" / "README.md",
            r"docket add --from",
            "declarative provisioning belongs to `docket init --from`",
        ),
        (
            ROOT / "examples" / "configs" / "agents.yaml",
            r"docket add --from",
            "the checked-in example must name the canonical declarative entry point",
        ),
        (
            ROOT / "docs" / "commands.md",
            r"DEBUG=1\s+docket",
            "DEBUG=1 is inert and must not be runnable guidance",
        ),
        (
            README,
            r"raw\.githubusercontent\.com/yielab/docket/(?:main|platform)/install\.sh",
            "release installation must pin immutable tagged installer bytes",
        ),
        (
            README,
            r"kills the in-flight hop's process group",
            "cancellation is requested and observed cooperatively at safe boundaries",
        ),
        (
            README,
            r"It is the turn loop",
            "docket-runtime exposes a narrow gated-tool facade, not a second public turn loop",
        ),
    )
    offenders: list[str] = []
    for path, pattern, reason in checks:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if re.search(pattern, line, flags=re.IGNORECASE):
                offenders.append(f"{path.relative_to(ROOT)}:{line_number}: {reason}")

    readme = README.read_text(encoding="utf-8").lower()
    if "not published to any index" not in readme:
        offenders.append("README.md: runtime package publication limit is missing")
    if "cancel requested" not in readme or "safe checkpoint" not in readme:
        offenders.append("README.md: cooperative cancellation limit is incomplete")

    assert offenders == [], "stale or missing public truth:\n" + "\n".join(offenders)


def test_quickstart_has_one_ordered_artifact_to_governed_turn_route() -> None:
    """The public quickstart must lead from immutable install to inspectable governed output."""
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    text = QUICKSTART.read_text(encoding="utf-8")
    ordered_steps = (
        f"/releases/download/v{version}/",
        "docket models provider add",
        "docket models set programmer",
        "docket init",
        "docket pod myapp delegate",
        "docket pod myapp dispatch",
        "docket runs list",
        "docket trace",
    )
    missing = [step for step in ordered_steps if step not in text]
    assert missing == [], f"quickstart is missing release-to-first-turn step(s): {missing}"

    positions = [text.index(step) for step in ordered_steps]
    assert positions == sorted(positions), "quickstart release-to-first-turn route is out of order"


def test_public_install_names_match_artifact_metadata() -> None:
    """README, installer, and formula identities must describe the artifacts we actually build."""
    root_metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime_metadata = tomllib.loads(
        (RUNTIME_PACKAGE / "pyproject.toml").read_text(encoding="utf-8")
    )
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    readme = README.read_text(encoding="utf-8")
    installer = (ROOT / "install.sh").read_text(encoding="utf-8")
    formula = (ROOT / "Formula" / "docket-cli.rb").read_text(encoding="utf-8")

    assert root_metadata["project"]["name"] == "docket"
    assert runtime_metadata["project"]["name"] == "docket-runtime"
    assert "brew install docket-cli" in readme
    assert "**`docket-runtime`**" in readme
    assert f'DOCKET_VERSION="${{DOCKET_VERSION:-{version}}}"' in installer
    assert f'version "{version}"' in formula
    assert "docket-v#{version}.tar.gz" in formula


def _status_category(value: str) -> str:
    match = re.search(r"[A-Za-z]+", value.replace("**", ""))
    assert match is not None, f"status has no canonical category: {value!r}"
    return match.group(0).lower()


def test_spec_index_matches_current_headers_and_changelogs() -> None:
    """The public spec table must not lag the contracts it indexes."""
    rows: dict[str, tuple[str, str]] = {}
    for line in SPEC_INDEX.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", line)
        if match:
            rows[match.group(1)] = (match.group(2), match.group(3))

    problems: list[str] = []
    for label, relative in INDEXED_SPECS.items():
        path = ROOT / "specs" / relative
        text = path.read_text(encoding="utf-8")
        version_match = re.search(r"^\*\*Version\*\*:\s*(\S+)", text, flags=re.MULTILINE)
        status_match = re.search(r"^\*\*Status\*\*:\s*(.+)$", text, flags=re.MULTILINE)
        assert version_match and status_match, f"missing spec header metadata: {relative}"
        version = version_match.group(1)
        indexed = rows.get(label)
        if indexed is None:
            problems.append(f"{label}: missing index row")
            continue
        indexed_version, indexed_status = indexed
        if indexed_version != version:
            problems.append(f"{label}: index {indexed_version}, spec {version}")
        if _status_category(indexed_status) != _status_category(status_match.group(1)):
            problems.append(
                f"{label}: index status {indexed_status!r}, spec status {status_match.group(1)!r}"
            )
        if f"### Version {version}" not in text:
            problems.append(f"{label}: current version {version} has no changelog entry")

    assert problems == [], "spec index/header/changelog drift:\n" + "\n".join(problems)


def _run(*args: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=180,
        check=True,
    )


def test_runtime_embedding_example_runs_from_clean_artifact(tmp_path: Path) -> None:
    """The public example must consume only the installed narrow runtime facade."""
    assert RUNTIME_EXAMPLE.is_file(), "missing examples/runtime_embed.py public embedding example"

    dist = tmp_path / "dist"
    outside = tmp_path / "outside-checkout"
    build_tmp = tmp_path / "runtime-build-tmp"
    home = tmp_path / "docket-home"
    outside.mkdir()
    build_tmp.mkdir()
    env = {
        **os.environ,
        "DOCKET_HOME": str(home),
        "DOCKET_RUNTIME_BUILD_TMPDIR": str(build_tmp),
        "PYTHONPATH": "",
    }
    _run("uv", "build", "--wheel", "--out-dir", str(dist), cwd=RUNTIME_PACKAGE, env=env)
    wheel = next(dist.glob("docket_runtime-*.whl"))
    venv = tmp_path / "venv"
    _run("uv", "venv", str(venv), "--python", sys.executable, cwd=outside, env=env)
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    _run(
        "uv",
        "pip",
        "install",
        "--offline",
        "--python",
        str(python),
        "--no-deps",
        str(wheel),
        cwd=outside,
        env=env,
    )
    dependency_site = Path(filelock.__file__).resolve().parent.parent
    runtime_env = {**env, "PYTHONPATH": str(dependency_site)}
    result = _run(str(python), str(RUNTIME_EXAMPLE), cwd=outside, env=runtime_env)

    assert result.stdout == "RUNTIME EMBED PASS\n"
    assert (home / "audit.log").read_text(encoding="utf-8").strip()
    assert list((home / "traces").rglob("*.jsonl"))
    _run(
        str(python),
        "-c",
        "import importlib.util; assert importlib.util.find_spec('docket') is None",
        cwd=outside,
        env=runtime_env,
    )
