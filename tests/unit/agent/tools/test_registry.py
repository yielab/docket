"""The tool registry's command classifier, redirects, allowlist and path containment."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support import home as _support_home
from tests.support import llm as _support_llm
from tests.support import pods as _support_pods

from docket.agent.tools.builtins.toolbox import PathEscapeError, resolve_within
from docket.agent.tools.registry import (
    ToolContext,
)
from docket.governance.gate import evaluate_tool_call
from docket.governance.security import classify_command
from docket.hops.application.builtin_tools import builtin_registry

SUBJECT = "docket.agent.tools.registry"


_isolate_gates = _support_home.isolate_gates


workspace = _support_pods.workspace_with_files


ctx = _support_llm.ctx_in_workspace


pod_input_policy = _support_pods.pod_input_policy


REPO_ROOT = Path(__file__).resolve().parents[4]


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

    @pytest.mark.parametrize("command", ['ls "unterminated', "echo it's", "echo \\"])
    def test_untokenizable_command_is_denied_as_syntax(self, command: str) -> None:
        verdict = classify_command(command)
        assert verdict.action == "deny"
        assert verdict.reason.startswith("syntax: ")
        assert verdict.reason.endswith("; fix the quoting and call again")

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
            assert verdict.reason.startswith("output redirect to "), command

    @pytest.mark.parametrize(
        "command", ["pytest -q", "pytest tests/unit -x", "python -m pytest", "python script.py"]
    )
    def test_the_test_runner_and_the_bare_interpreter_are_allowlisted(self, command: str) -> None:
        """`pytest` runs the same code `python3 -m pytest` does, so both verdicts agree."""
        assert classify_command(command).action == "allow"


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

    def test_the_shipped_policy_matches_the_same_shapes(self, tmp_path: Path) -> None:
        from docket.governance import policy as _policy
        from docket.kernel.home import Home, use_home

        def action(command: str) -> str:
            args = {"command": command}
            call = _policy.ToolCallFacts("bash", args, lambda: "")
            return _policy.policy_eval_detail(
                "implementer", "pre_tool_call", f"bash command={command!r}", call=call
            ).action

        with use_home(Home(tmp_path / ".docket")):
            _policy.install_policies()

            for command in ("git -c x=y push origin main", "git --no-pager push origin main"):
                assert action(command) == "require_approval", command
            assert action("git push origin feature/x") == "allow"


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
        "target", ["../escape.txt", "/etc/passwd", "~/x.txt", "$HOME/x.txt", "*.txt", "/dev/nullx"]
    )
    def test_a_target_outside_or_unresolvable_asks(self, workspace: Path, target: str) -> None:
        verdict = classify_command(f"echo x > {target}", roots=(workspace,))
        assert verdict.action == "ask", target
        assert verdict.bin_name == "echo"

    @pytest.mark.parametrize("command", ["echo x > /dev/null", "echo x 2>/dev/null >out.txt"])
    def test_a_discarding_redirect_is_allowed(self, workspace: Path, command: str) -> None:
        assert classify_command(command, roots=(workspace,)).action == "allow", command

    def test_a_discarding_redirect_needs_no_roots(self) -> None:
        assert classify_command("echo x > /dev/null").action == "allow"
        assert classify_command("ls missing 2>/dev/null", jailed=True).action == "allow"
        assert classify_command("echo x 2>/dev/null > notes.txt").action == "ask"

    def test_a_symlink_that_leaves_the_workspace_asks(
        self, workspace: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path.parent / f"{tmp_path.name}-outside"
        outside.mkdir()
        (workspace / "link").symlink_to(outside)
        assert classify_command("echo x > link/a.txt", roots=(workspace,)).action == "ask"

    def test_an_unfollowable_cd_makes_a_relative_target_unplaceable(self, workspace: Path) -> None:
        assert classify_command('cd "$D" && echo x > a.txt', roots=(workspace,)).action == "ask"

    def test_a_literal_cd_is_followed(self, workspace: Path) -> None:
        assert classify_command("cd src && echo x > a.txt", roots=(workspace,)).action == "allow"
        assert classify_command("cd .. && echo x > a.txt", roots=(workspace,)).action == "ask"

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

    def test_high_risk_and_opaque_still_ask_and_unparseable_is_still_denied_when_jailed(
        self,
    ) -> None:
        assert classify_command("git push origin production", jailed=True).action == "ask"
        assert classify_command("echo $(id)", jailed=True).action == "ask"
        assert classify_command('ls "unterminated', jailed=True).action == "deny"
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
    """`classify_command`'s `extra_bins` parameter -- `teams.pod_settings.PodSettings.allow_commands`'s
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
        assert classify_command('ls "oops').action == "deny"
