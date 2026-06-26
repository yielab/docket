"""CD-9: Positioning / docs truth pass.

Machine-readable audit: the public docs must lead with the verified differentiators
and make no unfalsifiable or savings-claim statements.

Acceptance criteria (from TODO.md):
  - docs lead with coordinated-context + isolation + governance
  - the ops/control-plane vs framework contrast line is present
  - the governed-fleet vs solo-assistant contrast line is present
  - no dollar-savings claims ("save" / "savings" in a cost context)
  - suite green
"""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).parent.parent.parent
README = _REPO / "README.md"
CLAUDE_MD = _REPO / "CLAUDE.md"


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _claude() -> str:
    return CLAUDE_MD.read_text(encoding="utf-8")


# ── TestNoDollarSavingsClaims ─────────────────────────────────────────────────


class TestNoDollarSavingsClaims:
    """No unfalsifiable cost-savings marketing language in public docs."""

    def _check_no_savings_claim(self, text: str, label: str) -> None:
        lines_with_savings = [
            (i + 1, line)
            for i, line in enumerate(text.splitlines())
            if "saving" in line.lower() or "save money" in line.lower()
            if not line.strip().startswith("#")  # allow headings that discuss the discipline
        ]
        # A line containing "saving" is only banned if it makes a forward claim
        # (e.g. "saves you $X", "will save costs").
        # Honest caveats like "treat savings comparisons as directional" are fine.
        bad = [
            (n, ln)
            for n, ln in lines_with_savings
            if any(
                phrase in ln.lower()
                for phrase in (
                    "save you",
                    "saves you",
                    "will save",
                    "can save",
                    "reduces your costs",
                    "cut your costs",
                )
            )
        ]
        assert bad == [], f"{label}: found dollar-savings claim(s):\n" + "\n".join(
            f"  line {n}: {ln}" for n, ln in bad
        )

    def test_readme_no_savings_claims(self) -> None:
        self._check_no_savings_claim(_readme(), "README.md")

    def test_claude_md_no_savings_claims(self) -> None:
        self._check_no_savings_claim(_claude(), "CLAUDE.md")


# ── TestThreePillarsPresent ───────────────────────────────────────────────────


class TestThreePillarsPresent:
    """The three verified differentiators must appear in the README."""

    def test_coordinated_context_pillar(self) -> None:
        text = _readme()
        assert "Lead" in text and ("context" in text or "orchestrat" in text), (
            "README should mention the Lead-owned context / coordination pillar"
        )

    def test_isolation_pillar_runtime_resources(self) -> None:
        text = _readme()
        assert "port" in text.lower() and (
            "scratch" in text.lower() or "isolation" in text.lower()
        ), "README should mention runtime-resource isolation (port ranges / scratch dirs)"

    def test_isolation_pillar_worktree(self) -> None:
        text = _readme()
        assert "worktree" in text.lower(), (
            "README should mention git worktree isolation for Implementers (CD-5)"
        )

    def test_governance_pillar_approval(self) -> None:
        text = _readme()
        assert "approval" in text.lower() and "gate" in text.lower(), (
            "README should mention approval gates (governance/HITL spine)"
        )

    def test_governance_pillar_audit(self) -> None:
        text = _readme()
        assert "audit" in text.lower(), "README should mention audit log (governance spine)"


# ── TestContrastLinesPresent ──────────────────────────────────────────────────


class TestContrastLinesPresent:
    """The explicit competitor contrast lines must appear."""

    def test_ops_control_plane_not_framework_contrast(self) -> None:
        text = _readme()
        assert "control plane" in text.lower() and "framework" in text.lower(), (
            "README must contain the 'ops/control plane, not an agent framework' contrast line"
        )

    def test_governed_fleet_not_solo_contrast(self) -> None:
        text = _readme()
        assert "solo" in text.lower() or "personal assistant" in text.lower(), (
            "README must contrast docket with 'solo personal assistant' (vs raw OpenClaw)"
        )

    def test_dashboard_feed_not_is_dashboard(self) -> None:
        text = _readme()
        # docket feeds dashboards; it is not itself a dashboard
        assert "dashboard" in text.lower(), (
            "README should mention the dashboard / read-API positioning (CD-8)"
        )
        # Must NOT claim to *be* the dashboard (only to feed one)
        bad_phrases = ["docket dashboard", "the docket ui", "docket's dashboard"]
        for phrase in bad_phrases:
            assert phrase not in text.lower(), (
                f"README must not position docket as a dashboard UI (found: {phrase!r})"
            )


# ── TestNewFeaturesDocumented ─────────────────────────────────────────────────


class TestNewFeaturesDocumented:
    """Phase-11 features (CD-1..CD-8) are mentioned in the README."""

    def test_cd1_runtime_resources_documented(self) -> None:
        assert "port" in _readme().lower()

    def test_cd5_worktree_documented(self) -> None:
        assert "worktree" in _readme().lower()

    def test_cd6_scheduled_dispatch_documented(self) -> None:
        text = _readme()
        assert "schedule" in text.lower() or "@every" in text

    def test_cd6_webhook_documented(self) -> None:
        text = _readme()
        assert "webhook" in text.lower() or "/dispatch/" in text

    def test_cd7_validate_documented(self) -> None:
        text = _readme()
        assert "validate" in text.lower()

    def test_cd7_plan_documented(self) -> None:
        text = _readme()
        assert "plan" in text.lower() or "dry-run" in text.lower()

    def test_cd8_status_json_documented(self) -> None:
        text = _readme()
        assert "/status.json" in text

    def test_cd8_metrics_documented(self) -> None:
        text = _readme()
        assert "/metrics" in text
