"""Memory runtime-contract + `docket add` UX-helper + arg parsing.

Guards the fix for the failure where agents looped forever because the openclaw
post-compaction audit demanded WORKFLOW_AUTO.md / memory/<date>.md that docket
never created, and never learned their codebase path.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

from docket.cli._agents import _parse_add_args
from docket.core import memory as _mem
from docket.core import provisioning as _prov


class TestUxHelpers:
    def test_slugify(self) -> None:
        assert _prov.slugify("My Shop API") == "my-shop-api"
        assert _prov.slugify("  ai-site-generator  ") == "ai-site-generator"

    def test_suggest_project_name_is_codebase_dirname(self) -> None:
        assert _prov.suggest_project_name("/home/ox/Sites/ai-site-generator") == (
            "ai-site-generator"
        )

    def test_default_codebase_is_cwd(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        assert _prov.default_codebase() == Path.cwd()

    def test_detect_stack_python(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        assert _prov.detect_stack(tmp_path) == "Python"

    def test_detect_stack_node(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{}")
        assert _prov.detect_stack(tmp_path) == "Node.js"

    def test_detect_stack_unknown(self, tmp_path: Path) -> None:
        assert _prov.detect_stack(tmp_path) == ""


class TestSeedContract:
    def test_creates_the_audited_files_and_memory_md(self, tmp_path: Path) -> None:
        _mem.seed_contract(tmp_path, project="demo", codebase="/src/demo", stack="Python")
        assert (tmp_path / _mem.REQUIRED_STARTUP_FILE).is_file()
        assert (tmp_path / _mem.MEMORY_FILE).is_file()
        assert (tmp_path / _mem.today_memory_relpath()).is_file()

    def test_workflow_auto_anchors_codebase_and_wrong_dir_note(self, tmp_path: Path) -> None:
        _mem.seed_contract(tmp_path, project="demo", codebase="/src/demo", stack="Go")
        text = (tmp_path / _mem.REQUIRED_STARTUP_FILE).read_text()
        assert "/src/demo" in text
        assert "wrong directory" in text.lower()
        # Must NOT hardcode a concrete daily filename (it would go stale next day).
        assert not re.search(r"memory/\d{4}-\d{2}-\d{2}\.md", text)
        assert "memory/YYYY-MM-DD.md" in text

    def test_daily_matches_runtime_regex(self, tmp_path: Path) -> None:
        _mem.seed_contract(tmp_path, project="demo", codebase="/src/demo")
        rel = _mem.today_memory_relpath()
        assert re.fullmatch(r"memory/\d{4}-\d{2}-\d{2}\.md", rel)
        assert (tmp_path / rel).is_file()

    def test_does_not_clobber_existing_daily_or_memory(self, tmp_path: Path) -> None:
        (tmp_path / "memory").mkdir()
        daily = tmp_path / _mem.today_memory_relpath()
        daily.write_text("real work logged today\n")
        (tmp_path / _mem.MEMORY_FILE).write_text("curated by the agent\n")
        _mem.seed_contract(tmp_path, project="demo", codebase="/src/demo")
        assert daily.read_text() == "real work logged today\n"
        assert (tmp_path / _mem.MEMORY_FILE).read_text() == "curated by the agent\n"

    def test_refreshes_workflow_auto(self, tmp_path: Path) -> None:
        _mem.seed_contract(tmp_path, project="demo", codebase="/old/path")
        _mem.seed_contract(tmp_path, project="demo", codebase="/new/path")
        text = (tmp_path / _mem.REQUIRED_STARTUP_FILE).read_text()
        assert "/new/path" in text and "/old/path" not in text

    def test_seeds_with_specific_day(self, tmp_path: Path) -> None:
        _mem.seed_contract(tmp_path, project="demo", codebase="/src", day=_dt.date(2026, 1, 2))
        assert (tmp_path / "memory" / "2026-01-02.md").is_file()

    def test_workflow_auto_carries_resume_and_durability_contract(self, tmp_path: Path) -> None:
        # The runtime-forced re-read file must tell a just-reset agent to resume an
        # in-flight task and to write tasks down *before* starting — the fix for
        # accepted work being silently dropped across a context reset.
        _mem.seed_contract(tmp_path, project="demo", codebase="/src/demo")
        text = (tmp_path / _mem.REQUIRED_STARTUP_FILE).read_text().lower()
        assert "resume" in text
        assert "before you greet" in text or "greet" in text
        assert "unwritten task" in text
        assert "heartbeat.md" in text


class TestHeartbeatSeed:
    def test_ledger_teaches_write_before_start_and_resume(self) -> None:
        body = _mem.heartbeat_seed("demo-lead")
        assert "# HEARTBEAT.md — demo-lead" in body
        assert "## Active Tasks" in body
        # Durability + resume language a weak model needs to see.
        assert "before" in body.lower()
        assert "resume" in body.lower()
        # The fill-in template shows the exact task shape (checklist) to record.
        assert "- [ ]" in body


class TestContractOk:
    def test_true_after_seed(self, tmp_path: Path) -> None:
        _mem.seed_contract(tmp_path, project="demo", codebase="/src")
        assert _mem.contract_ok(tmp_path) is True

    def test_false_when_missing(self, tmp_path: Path) -> None:
        assert _mem.contract_ok(tmp_path) is False

    def test_false_when_stale_or_legacy_content(self, tmp_path: Path) -> None:
        # A file exists but predates the contract marker (the real docket-lead case).
        (tmp_path / _mem.REQUIRED_STARTUP_FILE).write_text(
            "# Auto-generated workflow steps\n- [ ] Initialize project\n"
        )
        assert _mem.contract_ok(tmp_path) is False


class TestParseAddArgs:
    def test_empty(self) -> None:
        assert _parse_add_args([]) == (None, None, None)

    def test_from_flag_space(self) -> None:
        assert _parse_add_args(["--from", "spec.json"]) == ("spec.json", None, None)

    def test_from_flag_equals(self) -> None:
        assert _parse_add_args(["--from=spec.yaml"]) == ("spec.yaml", None, None)

    def test_codebase_flag(self) -> None:
        assert _parse_add_args(["--codebase", "/src/x"]) == (None, "/src/x", None)
        assert _parse_add_args(["--path=/src/y"]) == (None, "/src/y", None)

    def test_name_flag(self) -> None:
        assert _parse_add_args(["--name", "My App"]) == (None, None, "My App")

    def test_positional_name_then_path(self) -> None:
        assert _parse_add_args(["myapp", "/src/myapp"]) == (None, "/src/myapp", "myapp")

    def test_flags_win_over_positionals(self) -> None:
        assert _parse_add_args(["pos-name", "--name", "Flag Name"]) == (None, None, "Flag Name")

    def test_pod_flags_do_not_leak_into_positionals(self) -> None:
        assert _parse_add_args(["blog", "--pod", "full"]) == (None, None, "blog")
        assert _parse_add_args(["blog", "/src/blog", "--with", "reviewer,tester"]) == (
            None,
            "/src/blog",
            "blog",
        )
