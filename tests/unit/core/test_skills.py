"""Agent Skills discovery and frontmatter parsing (`core/skills.py`).

Pins the Agent Skills shape (ADR 0013 §3 rule 8): `SKILL.md` frontmatter naming a skill and
describing it in one sentence, and the three-scope, nearest-wins discovery order a live turn's
`# Skills` prompt section and the `skill` tool both read from.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core import audit as _audit
from docket.core import skills as _skills

SUBJECT = "docket.core.skills"


def _write_skill(directory: Path, name: str, description: str = "Reads like a sentence.") -> Path:
    skill_dir = directory / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\nBody text.\n", encoding="utf-8"
    )
    return skill_file


class TestParseSkillFile:
    def test_a_valid_file_parses(self, tmp_path: Path) -> None:
        skill_file = _write_skill(tmp_path, "security-review", "Reviews a diff for security bugs.")

        meta = _skills.parse_skill_file(skill_file, scope="global")

        assert meta.name == "security-review"
        assert meta.description == "Reviews a diff for security bugs."
        assert meta.directory == skill_file.parent
        assert meta.scope == "global"

    def test_missing_frontmatter_raises(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "bad-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("# No frontmatter here\n", encoding="utf-8")

        with pytest.raises(_skills.SkillError, match="frontmatter"):
            _skills.parse_skill_file(skill_file)

    def test_name_disagreeing_with_directory_raises(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "on-disk-name"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\nname: different-name\ndescription: A sentence.\n---\nBody.\n", encoding="utf-8"
        )

        with pytest.raises(_skills.SkillError, match="name"):
            _skills.parse_skill_file(skill_file)

    def test_missing_description_raises(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "no-description"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("---\nname: no-description\n---\nBody.\n", encoding="utf-8")

        with pytest.raises(_skills.SkillError, match="description"):
            _skills.parse_skill_file(skill_file)


class TestDiscoverSkills:
    def test_nearest_scope_wins_by_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The same skill name in all three scopes: codebase wins over pod, pod wins over
        global -- proven by a distinguishing description at each scope."""
        codebase = tmp_path / "repo"
        _write_skill(codebase / ".docket" / "skills", "shared", "codebase version")
        project = "nearest-demo"
        _write_skill(_cfg.pod_config_dir(project) / "skills", "shared", "pod version")
        monkeypatch.setattr(_cfg, "SKILLS_DIR", tmp_path / "global-skills", raising=True)
        _write_skill(_cfg.SKILLS_DIR, "shared", "global version")

        found = _skills.discover_skills(project, codebase)

        assert found["shared"].description == "codebase version"
        assert found["shared"].scope == "codebase"

    def test_pod_scope_wins_over_global(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = "pod-wins-demo"
        _write_skill(_cfg.pod_config_dir(project) / "skills", "shared", "pod version")
        monkeypatch.setattr(_cfg, "SKILLS_DIR", tmp_path / "global-skills", raising=True)
        _write_skill(_cfg.SKILLS_DIR, "shared", "global version")

        found = _skills.discover_skills(project, None)

        assert found["shared"].description == "pod version"
        assert found["shared"].scope == "pod"

    def test_an_invalid_skill_is_skipped_and_audited_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The fail-closed negative: a name/directory mismatch never raises into discovery,
        the skill is simply absent, and exactly one `skills.invalid` audit line records why."""
        monkeypatch.setattr(_cfg, "SKILLS_DIR", tmp_path / "global-skills", raising=True)
        skill_dir = _cfg.SKILLS_DIR / "on-disk-name"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: different-name\ndescription: A sentence.\n---\nBody.\n", encoding="utf-8"
        )

        found = _skills.discover_skills("", None)

        assert found == {}
        entries = [e for e in _audit.read_audit() if e["action"] == "skills.invalid"]
        assert len(entries) == 1
        assert "on-disk-name" in entries[0]["detail"]

    def test_no_skills_anywhere_is_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "SKILLS_DIR", tmp_path / "empty-global", raising=True)

        assert _skills.discover_skills("", None) == {}
