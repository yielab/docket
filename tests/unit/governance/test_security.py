"""Command classifier verdicts for wrappers and deleting flags of allowlisted bins."""

from __future__ import annotations

from pathlib import Path

import pytest

from docket.governance.security import classify_command

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
