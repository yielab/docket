"""Public truth contract for Docket support and single-maintainer governance."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE = ROOT / "GOVERNANCE.md"
SUPPORT = ROOT / "SUPPORT.md"


def _text(path: Path) -> str:
    assert path.is_file(), f"RED: public policy is missing: {path.name}"
    return path.read_text(encoding="utf-8")


def _claim_violations(text: str) -> set[str]:
    lowered = text.lower()
    checks = {
        "multiple-maintainers": r"(?:we have|there are) multiple active maintainers",
        "lts": r"(?:offers?|provides?|includes?) (?:an? )?(?:lts|long-term support)",
        "guaranteed-compatibility": r"(?<!not )guarantee(?:d|s)? (?:backward )?compatibility",
        "foundation": r"governed by (?:a|the) foundation",
    }
    return {name for name, pattern in checks.items() if re.search(pattern, lowered)}


def _assert_local_links_resolve(path: Path, text: str) -> None:
    for raw in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
        target = raw.split("#", 1)[0]
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        resolved = (path.parent / target).resolve()
        assert resolved.is_relative_to(ROOT)
        assert resolved.exists(), f"broken repository link in {path.name}: {raw}"


def test_governance_states_current_authority_and_maintainer_path() -> None:
    text = _text(GOVERNANCE)
    lowered = text.lower()
    assert "one active maintainer" in lowered
    assert "@santiagoyie" in lowered
    assert "final decision authority" in lowered
    assert "release authority" in lowered
    for criterion in (
        "sustained contributions",
        "code review",
        "security model",
        "explicit invitation",
        "explicit acceptance",
    ):
        assert criterion in lowered
    assert "recuse" in lowered
    assert "security.md" in lowered


def test_support_states_actual_matrix_and_beta_deprecation_rule() -> None:
    text = _text(SUPPORT)
    lowered = text.lower()
    assert re.search(r"\|\s*`main`\s*\|\s*supported\s*\|", lowered)
    assert re.search(r"\|\s*older tags\s*\|\s*not supported\s*\|", lowered)
    assert "pre-1.0" in lowered
    assert "one published beta" in lowered
    assert "no lts" in lowered or "no long-term support" in lowered
    assert "no separate response-time commitment" in lowered
    assert "security.md" in lowered


def test_succession_is_triggered_bounded_and_does_not_invent_a_successor() -> None:
    text = _text(GOVERNANCE)
    lowered = text.lower()
    assert "90 consecutive days" in lowered
    assert "transfer" in lowered
    assert "archive" in lowered
    assert "no successor is currently designated" in lowered
    assert "automatically" not in lowered or "does not automatically" in lowered


def test_policy_links_resolve_and_claims_remain_bounded() -> None:
    documents = {GOVERNANCE: _text(GOVERNANCE), SUPPORT: _text(SUPPORT)}
    for path, text in documents.items():
        _assert_local_links_resolve(path, text)
        assert not _claim_violations(text)
        assert not re.search(r"(?:respond|acknowledge|fix|resolve)\s+within\s+\d+", text.lower())


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        ("There are multiple active maintainers.", "multiple-maintainers"),
        ("Docket provides LTS for release branches.", "lts"),
        ("We guarantee backward compatibility.", "guaranteed-compatibility"),
        ("The project is governed by a foundation.", "foundation"),
    ],
)
def test_counterexample_claims_are_rejected(claim: str, expected: str) -> None:
    assert expected in _claim_violations(claim)
