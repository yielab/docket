"""P19-2: the gated tool registry, its chokepoint, and the built-in tools.

Three things are pinned here, in order of how much they matter:

1. **The command classifier is argument-aware.** `git` is allowlisted and
   `git push origin production` is a production deploy; a gate that cannot tell
   those apart is the gap docket has documented as deferred since Phase 13.
2. **There is exactly one path to tool execution.** A test walks the source
   tree to prove no module reaches around `dispatch_tool` into the handlers.
3. **Containment holds at the handler**, not only at the chokepoint, so a
   future caller cannot escape it by accident.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import ClassVar

import pytest

import docket.config as _cfg
from docket.core import tools as core_tools
from docket.core.llm import ToolCall
from docket.core.security import classify_command, split_command_segments
from docket.core.tools import (
    Tool,
    ToolContext,
    ToolRegistry,
    ToolResult,
    builtin_registry,
    dispatch_tool,
)
from docket.edges.adapters import toolbox
from docket.edges.adapters.toolbox import PathEscapeError, ToolOutcome, resolve_within

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _isolate_gates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """P19-3: `dispatch_tool` now also consults `core/policy.py` and, on an
    `ask` verdict, blocks on `core/approval.py`'s real store. Isolate both so
    this file's tests (which predate the policy hook and don't care about it)
    never read a developer's real ``~/.openclaw/policies``, and set the
    in-turn timeout to 0 so a gated call nothing ever grants resolves
    immediately (fail-closed to denied) instead of really waiting.
    """
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
    """The headline capability: the daemon's allowlist gates by binary path and
    structurally cannot do any of this."""

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


class TestSegmentSplitting:
    def test_operators_start_new_segments(self) -> None:
        assert split_command_segments("ls -la && git status") == [
            ["ls", "-la"],
            ["git", "status"],
        ]

    def test_env_prefix_is_stripped(self) -> None:
        assert split_command_segments("A=1 B=2 ls") == [["ls"]]

    def test_unbalanced_quotes_raise(self) -> None:
        with pytest.raises(ValueError):
            split_command_segments('ls "oops')


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
        assert out.ok and out.content.startswith("alpha")

    def test_read_window(self, workspace: Path) -> None:
        out = toolbox.read_file((workspace,), "notes.md", offset=2, limit=1)
        assert out.content == "beta"

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


class TestDispatchChokepoint:
    def test_unknown_tool_is_denied_with_a_readable_reason(self, ctx: ToolContext) -> None:
        res = dispatch_tool(_call("teleport"), ctx, builtin_registry())
        assert res.denied and "unknown tool" in res.reason
        assert not res.executed
        assert "read" in res.reason  # lists what IS available

    def test_unparseable_arguments_fail_closed(self, ctx: ToolContext) -> None:
        res = dispatch_tool(_call("read", "{not json"), ctx, builtin_registry())
        assert res.denied and not res.executed

    def test_missing_required_argument_is_denied_before_any_side_effect(
        self, ctx: ToolContext
    ) -> None:
        res = dispatch_tool(_call("write", '{"path": "x.txt"}'), ctx, builtin_registry())
        assert res.denied and "content" in res.reason
        assert not (ctx.roots[0] / "x.txt").exists()

    def test_allowed_call_executes(self, ctx: ToolContext) -> None:
        res = dispatch_tool(_call("read", '{"path": "notes.md"}'), ctx, builtin_registry())
        assert res.ok and res.executed and res.decision == "allow"
        assert res.content.startswith("alpha")

    def test_gated_command_is_not_executed(self, ctx: ToolContext) -> None:
        """P19-3: an `ask` verdict now blocks on the real approval store
        (`_isolate_gates` above pins TOOL_APPROVAL_TIMEOUT to 0) rather than
        just being reported, so with nothing ever granting it, it resolves
        to a fail-closed deny before `dispatch_tool` returns."""
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
        """A refusal and a failed run are different events; the audit log has to
        be able to tell them apart."""
        refused = dispatch_tool(_call("bash", '{"command": "rm x"}'), ctx, builtin_registry())
        failed = dispatch_tool(_call("read", '{"path": "nope.md"}'), ctx, builtin_registry())
        # P19-3: an `ask` verdict resolves before dispatch_tool returns (see
        # test_gated_command_is_not_executed) -- unresolved here too.
        assert (refused.decision, refused.executed) == ("deny", False)
        assert (failed.decision, failed.executed, failed.ok) == ("allow", True, False)


class TestResultReportedBackToTheModel:
    def test_denial_is_spoken_not_silent(self) -> None:
        res = ToolResult(ok=False, decision="deny", reason="no such tool")
        assert res.as_tool_output() == "REFUSED: no such tool"

    def test_pending_approval_is_spoken(self) -> None:
        res = ToolResult(ok=False, decision="ask", reason="needs a human")
        assert res.as_tool_output().startswith("AWAITING APPROVAL")

    def test_success_returns_the_content_verbatim(self) -> None:
        assert ToolResult(ok=True, content="body").as_tool_output() == "body"

    def test_failure_surfaces_the_error(self) -> None:
        res = ToolResult(ok=False, error="not a file: x", executed=True)
        assert "not a file: x" in res.as_tool_output()


class TestRegistry:
    def test_builtins_present(self) -> None:
        assert builtin_registry().names() == ["bash", "edit", "glob", "grep", "read", "write"]

    def test_specs_carry_schemas_the_model_can_use(self) -> None:
        specs = {s.name: s for s in builtin_registry().specs()}
        assert specs["bash"].parameters["required"] == ["command"]
        assert specs["read"].description

    def test_without_narrows_the_set(self) -> None:
        readonly = builtin_registry().without("write", "edit", "bash")
        assert "write" not in readonly and "read" in readonly
        assert len(readonly) == 3

    def test_a_narrowed_registry_denies_the_removed_tool(self, ctx: ToolContext) -> None:
        readonly = builtin_registry().without("write")
        res = dispatch_tool(_call("write", '{"path":"x","content":"y"}'), ctx, readonly)
        assert res.denied and not (ctx.roots[0] / "x").exists()


class TestSinglePathToExecution:
    """The architectural invariant, checked against the tree rather than
    asserted in prose: if a second module can call a handler directly, the gate
    is optional, and an optional gate is not a gate."""

    ALLOWED_IMPORTERS: ClassVar[set[str]] = {"core/tools.py", "edges/adapters/toolbox.py"}

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
        """`evaluate_tool_call` must be called from inside `dispatch_tool` — a
        gate invoked by callers instead is a gate callers can skip."""
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
        """toolbox.py must not grow its own gate: two places that can decide
        means one of them will be forgotten.

        Checks *identifiers*, not raw text — the module docstring legitimately
        says the words "approval" and "policy" while explaining that it holds
        neither, and a substring scan would force that explanation out of the
        file to stay green.
        """
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
