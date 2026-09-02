"""Public support-boundary truth contract for W28-C4."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
COMPATIBILITY = ROOT / "COMPATIBILITY.md"
RUNTIME_SPEC = ROOT / "specs" / "api" / "runtime-library.spec.md"
ADAPTER_EXAMPLE = ROOT / "examples" / "runtime_adapters.py"

EXPECTED_TESTED_CONFIGURATIONS = [
    {
        "adapter": "OpenHands SDK",
        "package": "openhands-sdk",
        "version": "1.44.1",
        "python": "3.12",
    },
    {
        "adapter": "PydanticAI",
        "package": "pydantic-ai",
        "version": "2.37.0",
        "python": "3.11",
    },
]
EXPECTED_OUTSIDE_PROOF = [
    "ACP",
    "native/provider tools",
    "plugins/MCP",
    "arbitrary framework configurations",
]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_runtime_spec_records_final_cross_adapter_contract_and_evidence() -> None:
    spec = _text(RUNTIME_SPEC)
    assert "**Version**: 2.2.0" in spec
    assert "OpenHands SDK" in spec and "1.44.1" in spec
    assert "PydanticAI" in spec and "2.37.0" in spec
    assert "installed" in spec.lower() and "wheel" in spec.lower() and "sdist" in spec.lower()
    assert "JSONL" in spec and "identity" in spec.lower()
    assert "A2A" in spec and "OTLP" in spec
    assert "### Version 2.2.0 (2026-09-01)" in spec


def test_readme_and_compatibility_name_only_the_tested_adapter_configurations() -> None:
    for path in (README, COMPATIBILITY):
        public = _text(path)
        assert "OpenHands SDK" in public and "1.44.1" in public, path
        assert "PydanticAI" in public and "2.37.0" in public, path
        assert "exclusively Docket-backed" in public, path
        assert "native/provider tools" in public, path
        assert "plugins/MCP" in public, path
        assert "arbitrary framework configurations" in public, path

    readme = _text(README)
    assert "examples/runtime_adapters.py" in readme
    compatibility = _text(COMPATIBILITY)
    assert "ACP" in compatibility
    assert "A2A" in compatibility and "OTLP" in compatibility


def test_compact_adapter_example_exposes_machine_checkable_support_truth() -> None:
    result = subprocess.run(
        [sys.executable, str(ADAPTER_EXAMPLE), "--truth-json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    truth = json.loads(result.stdout)
    assert truth == {
        "tested_configurations": EXPECTED_TESTED_CONFIGURATIONS,
        "governance_boundary": "relevant tools exclusively Docket-backed",
        "outside_proof": EXPECTED_OUTSIDE_PROOF,
        "transport": {
            "a2a_used": False,
            "otlp_used": False,
            "trace": "JSONL preserves project, session, role, call, and decision identity",
        },
    }


def test_public_adapter_prose_rejects_broad_or_remote_protocol_claims() -> None:
    public = "\n".join(_text(path) for path in (README, COMPATIBILITY, RUNTIME_SPEC))
    forbidden = (
        r"\b(?:all|any|every)\s+OpenHands\b",
        r"\b(?:all|any|every)\s+PydanticAI\b",
        r"\bACP[- ]governed\b",
        r"\bsubscription[- ]required\b",
    )
    for pattern in forbidden:
        assert re.search(pattern, public, flags=re.IGNORECASE) is None, pattern

    for line in public.splitlines():
        lower = line.lower()
        if "framework-neutral" in lower:
            assert "not framework-neutral" in lower or "no framework-neutral" in lower
        if "a2a" in lower or "otlp" in lower:
            assert any(
                boundary in lower
                for boundary in ("absent", "not used", "no a2a", "no otlp", "outside")
            ), line
