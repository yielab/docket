"""Command classifier verdicts for wrappers and deleting flags of allowlisted bins."""

from __future__ import annotations

from pathlib import Path

import pytest

from docket.governance.security import (
    CommandSegment,
    classify_command,
    command_segments,
    match_high_risk,
)

SUBJECT = "docket.governance.security"


@pytest.mark.parametrize(
    "command",
    [
        "env rm -rf x",
        "env FOO=1 -i rm -rf x",
        "echo a | xargs rm",
        "echo a | xargs -n1 -I{} rm {}",
        "nice -n 5 rm x",
        "nohup rm x",
        "timeout 5 rm x",
        "time rm x",
        "command rm x",
        "stdbuf -oL rm x",
        "setsid rm x",
        "setsid pytest",
        "env env env env env env env rm x",
        "find . -delete",
        "find . -exec rm {} +",
        "find . -execdir rm {} ;",
        "find . -fprint out.txt",
        "awk 'BEGIN{system(\"rm x\")}'",
        "awk '{print > \"f\"}' in",
        "awk '{print >> \"f\"}' in",
        "awk '{print | \"sh\"}' in",
    ],
)
def test_unsafe_behind_allowlisted_name_asks(command: str) -> None:
    """A dangerous operation behind an allowlisted wrapper or flag still asks."""
    assert classify_command(command).action == "ask"


@pytest.mark.parametrize(
    "command",
    [
        "env",
        "env FOO=1",
        "env FOO=1 pytest",
        "xargs",
        "echo a | xargs grep foo",
        "timeout 5 pytest",
        "find . -name '*.py'",
        "awk '{print $1}' f",
        "python3 -c 'print(1)'",
        "mkdir -p a && touch a/b && cp a/b a/c && mv a/c a/d",
    ],
)
def test_benign_wrapped_commands_stay_allowed(command: str) -> None:
    """Wrappers around allowlisted bins and plain find/awk remain allowed."""
    assert classify_command(command).action == "allow"


def test_jailed_find_delete_is_not_asked(tmp_path: Path) -> None:
    """Inside a working jail the allowlist stands down, so find -delete and env rm are allowed."""
    for command in ("find . -delete", "env rm -rf x", "echo a | xargs rm"):
        assert classify_command(command, roots=(tmp_path,), jailed=True).action == "allow"


_PY_BODY = (
    "python3 - <<'EOF'\n"
    "import re\n"
    "# it's a template\n"
    "s = `x ${tz}` + '() => {'\n"
    "open(p, 'w').write(s)\n"
    "EOF"
)


@pytest.mark.parametrize("jailed", [True, False])
def test_quoted_heredoc_body_is_data(tmp_path: Path, jailed: bool) -> None:
    """A quoted-delimiter body with a backtick, `${`, an apostrophe and `=>` is not classified."""
    verdict = classify_command(_PY_BODY, roots=(tmp_path,), jailed=jailed)
    assert verdict.action == "allow", verdict.reason


@pytest.mark.parametrize("opener", ["<<'EOF'", '<<"EOF"', "<<\\EOF", "<<-'EOF'"])
def test_every_quoted_heredoc_spelling_cuts_the_body(tmp_path: Path, opener: str) -> None:
    """The quoted, backslashed and dash forms all hide the body."""
    command = f"python3 - {opener}\n`x` it's\nEOF"
    assert classify_command(command, roots=(tmp_path,), jailed=True).action == "allow"


@pytest.mark.parametrize("jailed", [True, False])
def test_unquoted_heredoc_body_is_still_classified(tmp_path: Path, jailed: bool) -> None:
    """The shell expands an unquoted body, so a backtick there still asks."""
    command = "python3 - <<EOF\nx `id` y\nEOF"
    assert classify_command(command, roots=(tmp_path,), jailed=jailed).action == "ask"


@pytest.mark.parametrize("jailed", [True, False])
def test_heredoc_fed_to_a_shell_keeps_its_body_as_commands(tmp_path: Path, jailed: bool) -> None:
    """A body a shell will run is classified, so a high-risk class still asks."""
    command = "bash <<'EOF'\ngit push origin main\nEOF"
    verdict = classify_command(command, roots=(tmp_path,), jailed=jailed)
    assert verdict.action == "ask" and verdict.risk_class


def test_heredoc_piped_to_a_shell_keeps_its_body_as_commands(tmp_path: Path) -> None:
    """A body piped on to a shell is commands too."""
    command = "cat <<'EOF' | sh\ngit push origin main\nEOF"
    assert classify_command(command, roots=(tmp_path,), jailed=True).action == "ask"


def test_quoted_heredoc_redirect_inside_the_roots_is_allowed(tmp_path: Path) -> None:
    """`cat <<'EOF' > notes/x.md` places its redirect and cuts the body."""
    (tmp_path / "notes").mkdir()
    command = "cat <<'EOF' > notes/x.md\nit's `data`\nEOF"
    assert classify_command(command, roots=(tmp_path,), jailed=True).action == "allow"


@pytest.mark.parametrize("jailed", [True, False])
def test_unclosed_heredoc_asks(tmp_path: Path, jailed: bool) -> None:
    """A quoted heredoc whose delimiter never closes fails closed."""
    command = "python3 - <<'EOF'\nprint(1)\n"
    assert classify_command(command, roots=(tmp_path,), jailed=jailed).action == "ask"


def test_high_risk_text_inside_a_quoted_body_still_asks(tmp_path: Path) -> None:
    """The high-risk scan reads the full text, body included."""
    command = "python3 - <<'EOF'\ngit push origin production\nEOF"
    assert classify_command(command, roots=(tmp_path,), jailed=True).action == "ask"


def test_refused_redirect_names_the_rule_not_the_binary(tmp_path: Path) -> None:
    """An outside redirect says so, for a binary that is on the allowlist."""
    verdict = classify_command("cat > /tmp/c.ts", roots=(tmp_path,), jailed=True)
    assert verdict.action == "ask"
    assert verdict.reason == "output redirect to /tmp/c.ts is outside the workspace"


def test_literal_cd_is_followed_for_a_relative_redirect(tmp_path: Path) -> None:
    """`cd sub && cat > x.ts <<'EOF'` places x.ts under sub."""
    (tmp_path / "sub").mkdir()
    command = "cd sub && cat > x.ts <<'EOF'\nbody `x`\nEOF"
    assert classify_command(command, roots=(tmp_path,), jailed=True).action == "allow"


def test_cd_out_of_the_roots_asks_naming_the_target(tmp_path: Path) -> None:
    """A followed cd that leaves the roots makes the redirect outside."""
    (tmp_path / "sub").mkdir()
    verdict = classify_command("cd sub/../.. && echo x > y", roots=(tmp_path,), jailed=True)
    assert verdict.action == "ask"
    assert verdict.reason == "output redirect to y is outside the workspace"


@pytest.mark.parametrize("cd", ['cd "$D"', "cd -", "cd", "cd ~", "pushd sub"])
def test_cd_with_an_expansion_stops_placement(tmp_path: Path, cd: str) -> None:
    """An unplaceable cd names the placement, not the binary."""
    (tmp_path / "sub").mkdir()
    verdict = classify_command(f"{cd} && echo x > y", roots=(tmp_path,), jailed=True)
    assert verdict.action == "ask"
    assert verdict.reason == "output redirect after cd cannot be placed"


def test_cd_in_a_subshell_or_after_or_is_not_followed(tmp_path: Path) -> None:
    """A cd that may not take effect for the redirect stops placement."""
    (tmp_path / "sub").mkdir()
    for command in (
        "(cd sub); echo x > ../z",
        "cd sub || echo x > ../z",
        "cd sub | cat; echo x > ../z",
        "cd sub & echo x > ../z",
    ):
        verdict = classify_command(command, roots=(tmp_path,), jailed=True)
        assert verdict.action == "ask", command


def test_no_safe_bin_verdict_blames_the_allowlist_for_a_redirect(tmp_path: Path) -> None:
    """Every SAFE_BINS redirect refusal names the redirect."""
    from docket.governance.security import SAFE_BINS

    for name in sorted(SAFE_BINS):
        verdict = classify_command(f"{name} > /tmp/x", roots=(tmp_path,), jailed=True)
        assert "not on the curated allowlist" not in verdict.reason, name


@pytest.mark.parametrize("jailed", [True, False])
@pytest.mark.parametrize("reader", ["source /dev/stdin", ". /dev/stdin"])
def test_heredoc_sourced_as_shell_keeps_its_body(tmp_path: Path, reader: str, jailed: bool) -> None:
    """A body read by `source` or `.` runs as commands, so the opaque marker still asks."""
    command = f"{reader} <<'EOF'\n$(id)\nEOF"
    assert classify_command(command, roots=(tmp_path,), jailed=jailed).action == "ask"


def test_cd_propagates_past_a_later_pipeline(tmp_path: Path) -> None:
    """A pipe in a later command does not stop a leading cd being followed."""
    (tmp_path / "sub").mkdir()
    command = (
        f"cd {tmp_path} && python3 - <<'EOF'\np='x'\nEOF\n"
        "cat > sub/x.ts <<'EOF'\nhello\nEOF\n"
        'for t in a b; do TZ=$t npx vitest run x 2>&1 | grep -E "Tests|FAIL"; done\n'
        "npx tsc 2>&1 | tail -5"
    )
    assert classify_command(command, roots=(tmp_path,), jailed=True).action == "allow"
    assert (
        classify_command("cd sub && cat x | wc > y", roots=(tmp_path,), jailed=True).action
        == "allow"
    )


class TestCommandSegments:
    """``command_segments`` is the classifier's own reading of a command line, made public."""

    def test_quoting_is_undone_and_every_segment_behind_a_separator_is_returned(self) -> None:
        segments = command_segments("ls && \"rm\" -rf build; r''m x")

        assert [(s.program, s.args) for s in segments] == [
            ("ls", ()),
            ("rm", ("-rf", "build")),
            ("rm", ("x",)),
        ]

    def test_wrappers_are_peeled_to_the_program_that_runs(self) -> None:
        segments = command_segments("env FOO=1 nice -n 5 rm --recursive x | xargs -0 rm y")

        assert [(s.program, s.args) for s in segments] == [
            ("rm", ("--recursive", "x")),
            ("rm", ("y",)),
        ]

    @pytest.mark.parametrize(
        ("command", "writes"),
        [
            ("echo x > a.txt 2>> b.log", ("a.txt", "b.log")),
            ("tee -a /etc/passwd", ("/etc/passwd",)),
            ("cp src .env", ("src", ".env")),
            ("install -m600 /dev/null .env", ("/dev/null", ".env")),
            ("dd if=/dev/zero of=disk.img bs=1M", ("disk.img",)),
            ("sed -i s/a/b/ cfg.ini", ("s/a/b/", "cfg.ini")),
            ("perl -pi -e s/a/b/ cfg.ini", ("s/a/b/", "cfg.ini")),
            ("sed s/a/b/ cfg.ini", ()),
            ("ls build", ()),
        ],
    )
    def test_writes_are_redirect_targets_and_the_paths_a_known_writer_is_given(
        self, command: str, writes: tuple[str, ...]
    ) -> None:
        (segment,) = command_segments(command)

        assert isinstance(segment, CommandSegment)
        assert segment.writes == writes

    def test_a_heredoc_body_fed_to_a_non_shell_is_not_an_invocation(self) -> None:
        segments = command_segments("cat > x.sh <<'EOF'\nrm -rf /\nEOF")

        assert [s.program for s in segments] == ["cat"]

    def test_an_unreadable_command_raises(self) -> None:
        with pytest.raises(ValueError):
            command_segments("echo 'unclosed")


class TestHighRiskClassSeesPastOptionsAndQuoting:
    """An option before the verb, or a quoted word, does not hide a high-risk verb."""

    @pytest.mark.parametrize(
        ("command", "risk"),
        [
            ("kubectl -n prod apply -f d.yaml", "prod-deploy"),
            ("kubectl --context=prod delete deploy app", "prod-deploy"),
            ("terraform -chdir=infra apply -auto-approve", "prod-deploy"),
            ("helm -n prod upgrade app ./chart", "prod-deploy"),
            ("docker image push registry/app:1", "prod-deploy"),
            ("cargo publish", "prod-deploy"),
            ('git remote set-url origin x && git push origin ma""in', "prod-deploy"),
            ("vault -address=http://v:8200 kv put secret/app key=1", "secret-access"),
            ('"vault" kv put secret/app key=1', "secret-access"),
            ("kubectl -n prod create secret generic db --from-literal=p=1", "secret-access"),
            ("aws ssm put-parameter --name /db --value x", "secret-access"),
            ('curl https://api.s""tripe.com/v1/charges', "money-movement"),
        ],
    )
    def test_the_class_is_named(self, command: str, risk: str) -> None:
        found = match_high_risk(command)

        assert found is not None
        assert found.name == risk
        verdict = classify_command(command, jailed=True)
        assert (verdict.action, verdict.risk_class) == ("ask", risk)

    @pytest.mark.parametrize(
        "command",
        [
            "kubectl -n prod get pods",
            "helm -n prod list",
            "git push origin feature",
            "vault read x",
        ],
    )
    def test_a_read_or_a_feature_branch_is_not_a_class(self, command: str) -> None:
        assert match_high_risk(command) is None


_BACKGROUND_REASON = "background a process with bash background=true"


@pytest.mark.parametrize("jailed", [True, False])
@pytest.mark.parametrize(
    "command",
    [
        "sleep 30 &",
        "sleep 30 & ",
        "sleep 30 &\n",
        "echo hi &",
        "nohup sleep 47 > bg.log 2>&1 &",
        "echo hi; ls &",
        "sleep 30 & echo hi",
    ],
)
def test_a_lone_ampersand_asks_to_use_the_background_argument(
    tmp_path: Path, command: str, jailed: bool
) -> None:
    """A lone `&`, last or not, asks with the background reason, jailed or not."""
    verdict = classify_command(command, roots=(tmp_path,), jailed=jailed)
    assert (verdict.action, verdict.reason) == ("ask", _BACKGROUND_REASON)


@pytest.mark.parametrize("jailed", [True, False])
@pytest.mark.parametrize(
    "command",
    ["echo a && echo b", "ls 2>&1", "ls &> out.txt", "ls >&2", "echo 'a &'", 'echo "wait &"'],
)
def test_other_ampersands_are_not_the_background_operator(
    tmp_path: Path, command: str, jailed: bool
) -> None:
    """`&&`, `2>&1`, `&>`, `>&2` and a quoted `&` do not ask for the background reason."""
    verdict = classify_command(command, roots=(tmp_path,), jailed=jailed)
    assert verdict.reason != _BACKGROUND_REASON


def test_an_unclosed_quote_before_an_ampersand_keeps_the_parse_ask() -> None:
    """A command the lexer cannot read stays an ask for parsing, not for the background."""
    verdict = classify_command('echo "unclosed &')
    assert verdict.action == "ask"
    assert verdict.reason.startswith("command could not be parsed")
