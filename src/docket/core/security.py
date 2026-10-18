"""Security-gate logic: docket's own command classifier + approval/isolation config.

``dispatch_tool`` (``core/tools.py``) keeps ``pre_tool_call`` and
``classify_command`` below unconditionally live -- no "enable the gate"
step, no daemon-side exec-approval mechanism (there is no daemon). Only
docket's own workspace-isolation and network state is configurable
(``core/fleet.py``'s ``FleetSecurity``, ``docket setup sandbox``,
``docket setup sandbox network``) -- not whether calls are gated, only whether
execution is sandboxed and what network the sandbox has. Also owns
``match_high_risk``, the argument-aware allow/ask/deny classifier used by
the live gate and ``edges/adapters/system.py``'s ``run_verify_cmd``.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from docket.core import fleet as _fleet

# Curated set of common, lower-risk binaries `classify_command` allows
# unattended. Destructive/sensitive bins (rm, dd, docker, systemctl, ...) and
# shell interpreters are deliberately OMITTED so they fall through to `ask`.
# NOTE: a bin listed here (e.g. git, npm) can still have a HIGH_RISK_PATTERNS
# class attached for documentation/visibility (`docket setup sandbox classes`) — see
# `HighRiskClass`'s docstring for why that does not exclude it from this list.
#
# `cd`/`pwd`/`true`/`false`/`test`/`[` are shell builtins with no filesystem
# side effect beyond the invoking shell's own state -- unlike `export`,
# `source`, `.`, `eval` and `exec`, none of them changes what a later segment
# resolves to. `echo` joins them for the same low-risk reason but is
# redirect-sensitive: see _REDIRECT_SENSITIVE_BINS below.
SAFE_BINS: tuple[str, ...] = (
    "ls", "cat", "head", "tail", "wc", "sort", "uniq", "cut", "tr", "nl",
    "grep", "egrep", "rg", "fd", "find", "file", "stat", "tree", "realpath",
    "dirname", "basename",
    "sed", "awk", "jq", "yq", "diff", "comm",
    "git", "node", "npm", "npx", "pnpm", "yarn", "python", "python3", "pip", "pip3", "pytest",
    "go", "cargo", "rustc", "make", "cmake",
    "date", "env", "printf", "which", "xargs", "tee", "less",
    "nice", "nohup", "timeout", "time", "command", "stdbuf",
    "mkdir", "touch", "cp", "mv", "ln",
    "cd", "pwd", "echo", "true", "false", "test", "[",
)  # fmt: skip

# `echo`'s argument is often model-composed text, so redirecting it (`>`/`>>`/
# `&>`) is an unattended arbitrary-path write in a way a bare `echo hi` is not.
# Adding `echo` to SAFE_BINS above must not also unlock that -- a redirected
# invocation of a bin in this set still asks, by the same generic "not on the
# curated allowlist" path (`classify_command` below), verbatim identical to
# the verdict `echo` got before it was ever added to SAFE_BINS. The one
# exception is a target `classify_command` can place inside the caller's
# workspace roots (`_redirects_stay_inside`): that write is the `write` tool
# by another name, and the file tools already confine to the same roots.
# `cd`, `pwd` and the rest do not take free-form model-composed content, so
# they are not here.
_REDIRECT_SENSITIVE_BINS: frozenset[str] = frozenset({"echo"})

# Output-writing redirects only -- `<` (input) does not let arbitrary content
# reach a file the way `>`/`>>`/`>|`/`&>`/`&>>`/`>&` do. A descriptor prefix
# (`2>`) lexes as the digit then the operator, so it needs no entry. `>&` is
# a file redirect unless its target is a descriptor number (`2>&1`), which
# `_split_segments` tells apart.
_OUTPUT_REDIRECT_OPS: frozenset[str] = frozenset({">", ">>", ">|", "&>", "&>>", ">&"})
_INPUT_REDIRECT_OPS: frozenset[str] = frozenset({"<", "<<", "<<<", "<>"})

# A redirect target the shell would expand before opening (a variable, a home
# prefix, a glob) is not the path docket would resolve, so it cannot be placed.
_UNPLACEABLE_TARGET_CHARS: frozenset[str] = frozenset("$~*?[{")

# Writing to it discards the output, so no root is needed to place it (`2>/dev/null`).
_DISCARD_TARGET = "/dev/null"

# After one of these runs, a later relative redirect target no longer resolves
# against the workspace root the `bash` tool started in.
_DIRECTORY_CHANGERS: frozenset[str] = frozenset({"cd", "pushd", "popd"})


@dataclass(frozen=True)
class HighRiskClass:
    """A named, documented high-risk action class.

    ``pattern`` is matched case-insensitively against the full command
    string, not just a binary name. ``bins`` names overlapping SAFE_BINS
    members for visibility only (``docket setup sandbox classes``) -- it does
    **not** exclude them: excluding e.g. ``git``/``npm`` wholesale would
    force every benign invocation to ask too, so ``classify_command`` below
    enforces per-argument instead (``git push origin production`` asks;
    ``git status`` does not). See specs/functional/security-gates.spec.md
    item 5.
    """

    name: str
    description: str
    pattern: str
    bins: tuple[str, ...] = ()


# Seed list of high-risk action classes: money-movement, prod-deploy, and
# secret-access. Intentionally small and named — a policy foundation, not
# exhaustive coverage. Not user-configurable yet; a config-file override is
# a natural follow-up. All three classes are fully enforced via
# `classify_command` (argument-aware).
HIGH_RISK_PATTERNS: tuple[HighRiskClass, ...] = (
    HighRiskClass(
        name="money-movement",
        description="Payment/financial operations: charges, refunds, payouts, transfers",
        pattern=(
            r"\bstripe\b|\bpaypal\b|\bbraintree\b|charge\s+customer|refund.*amount"
            r"|wire\s+transfer|bank\s+transfer|\bpayout\b"
        ),
    ),
    HighRiskClass(
        name="prod-deploy",
        description="Production deploys and release pushes",
        pattern=(
            r"git\s+(?:-{1,2}[A-Za-z][\w.-]*(?:=\S*)?(?:\s+[^-\s]\S*)?\s+)*push\s+"
            r".*\b(main|master|production|prod)\b|npm\s+publish"
            r"|docker\s+(push|stop)\b|terraform\s+apply|kubectl\s+(apply|delete|rollout)"
            r"|helm\s+upgrade"
        ),
        bins=("git", "npm"),
    ),
    HighRiskClass(
        name="secret-access",
        description="Secret/credential writes and key generation",
        pattern=(
            r"vault\s+(write|kv\s+put)|ssh-keygen|openssl\s+genrsa"
            r"|kubectl\s+(create|apply).*secret|aws.*secretsmanager.*put-secret"
        ),
    ),
)


def match_high_risk(command: str) -> HighRiskClass | None:
    """Return the first HIGH_RISK_PATTERNS class matching *command*, else None.

    The single classification entry point: wired into ``run_verify_cmd``
    (refuses outright before the shell ever starts) and dispatch's
    ``pre_output`` scan; ``classify_command`` below also calls this to
    decide ``ask`` for a live tool call, the check ``dispatch_tool`` enforces.
    See specs/functional/security-gates.spec.md.
    """
    for cls in HIGH_RISK_PATTERNS:
        if re.search(cls.pattern, command, re.IGNORECASE):
            return cls
    return None


# ── argument-aware command classification ────────────────────────────────
#
# `core/tools.py`'s `dispatch_tool` runs every tool call itself, so this
# classifier has a real enforcement point downstream. What follows is
# deliberately NOT a restoration of the old bare-binary-name classifier
# described in `match_high_risk`'s docstring above: that granularity made
# `git push origin production` indistinguishable from `git status`. This one
# reads the whole command line, including every segment behind a `;`, `&&`
# or pipe.

# Shell operators that start a new command. Anything after one of these is a
# separate binary invocation and must be classified on its own — `ls && rm -rf
# /` is not an `ls`.
_COMMAND_SEPARATORS: frozenset[str] = frozenset({";", "&&", "||", "|", "&", "(", ")", "\n"})

# Substrings that make a command line impossible to classify statically: the
# real binary is produced at runtime. Their presence forces an approval rather
# than a guess.
_OPAQUE_MARKERS: tuple[str, ...] = ("$(", "`", "${", "eval ", "exec ")


@dataclass(frozen=True)
class CommandVerdict:
    """What docket decided about one shell command, and why.

    ``action`` is allow/ask/deny; ``ask`` routes to ``core/approval.py``,
    which fails closed on timeout, so an unclassifiable command never
    silently runs. ``reason`` is written for a human approver, naming the
    specific binary or risk class that caused the verdict.
    """

    action: str
    reason: str
    bin_name: str = ""
    risk_class: str = ""

    @property
    def blocked(self) -> bool:
        """True when the command may not run as-is (denied, or awaiting a human)."""
        return self.action != "allow"


@dataclass(frozen=True)
class _Segment:
    """One binary invocation of a command line, with what its output redirects name."""

    tokens: list[str]
    redirects: int  # output redirect operators attached to this invocation
    targets: tuple[str, ...]  # the token after each one; fewer than ``redirects`` when one had none

    @property
    def redirected(self) -> bool:
        return self.redirects > 0


def _logical_lines(command: str) -> list[str]:
    """Split *command* at every unquoted, unescaped newline, where the shell starts a new
    command (a quoted newline stays text, a backslash-newline continues the line); ``shlex``
    with ``whitespace_split`` swallows a newline as whitespace and never yields it."""
    lines: list[str] = []
    current: list[str] = []
    quote = ""
    escaped = False
    for ch in command:
        if escaped:
            escaped = False
            if ch in "\r\n":
                current.pop()  # drop the backslash: the two lines are one command
                current.append(" ")
            else:
                current.append(ch)
            continue
        if ch == "\\" and quote != "'":
            escaped = True
            current.append(ch)
            continue
        if quote:
            if ch == quote:
                quote = ""
            current.append(ch)
            continue
        if ch in "'\"":
            quote = ch
            current.append(ch)
            continue
        if ch in "\r\n":
            lines.append("".join(current))
            current = []
            continue
        current.append(ch)
    lines.append("".join(current))
    return [line for line in lines if line.strip()]


def _split_segments(command: str) -> list[_Segment]:
    """Split a shell command into per-invocation token lists, plus the output redirects attached
    to each -- kept internal, used only by ``classify_command``."""
    tokens: list[str] = []
    for line in _logical_lines(command):
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens.extend(lexer)  # ValueError on unbalanced quotes; deliberately not caught here
        tokens.append("\n")  # a line boundary is a command separator, below

    segments: list[_Segment] = []
    current: list[str] = []
    redirects = 0
    targets: list[str] = []
    expecting_target = duplicating = False
    for token in tokens:
        if token in _COMMAND_SEPARATORS:
            if current:
                segments.append(_Segment(current, redirects, tuple(targets)))
            current, redirects, targets, expecting_target = [], 0, [], False
            continue
        # Redirections attach to the current invocation rather than starting a
        # new one, but the target is not a binary -- drop the operator and let
        # the path stay as an argument, recording it as the redirect's target.
        if token in _OUTPUT_REDIRECT_OPS or token in _INPUT_REDIRECT_OPS:
            expecting_target = token in _OUTPUT_REDIRECT_OPS
            duplicating = token == ">&"
            if expecting_target:
                redirects += 1
            continue
        if expecting_target:
            expecting_target = False
            if duplicating and (token.isdigit() or token == "-"):
                redirects -= 1  # `2>&1` copies a descriptor; no file is opened
            else:
                targets.append(token)
        current.append(token)
    if current:
        segments.append(_Segment(current, redirects, tuple(targets)))

    cleaned: list[_Segment] = []
    for segment in segments:
        idx = 0
        while idx < len(segment.tokens) and re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*=.*", segment.tokens[idx]
        ):
            idx += 1
        if idx < len(segment.tokens):
            cleaned.append(_Segment(segment.tokens[idx:], segment.redirects, segment.targets))
    return cleaned


def _redirects_stay_inside(
    segment: _Segment, roots: tuple[Path, ...], changed_directory: bool
) -> bool:
    """True when every output redirect names ``/dev/null`` or a path inside *roots* (relative
    to ``roots[0]``, symlinks followed). False for a path with no roots, a target the shell would
    rewrite, an operator without a target, or an earlier ``cd``."""
    if len(segment.targets) != segment.redirects:
        return False
    placed = [target for target in segment.targets if target != _DISCARD_TARGET]
    if not placed:
        return True
    if not roots or changed_directory:
        return False
    try:
        bounds = [root.resolve() for root in roots]
    except OSError:
        return False
    for target in placed:
        if not target or _UNPLACEABLE_TARGET_CHARS & set(target):
            return False
        candidate = Path(target) if os.path.isabs(target) else roots[0] / target
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError):
            return False
        if not any(resolved.is_relative_to(bound) for bound in bounds):
            return False
    return True


# Command wrappers: the wrapper is allowlisted, the command it runs is what gets classified.
# `setsid` is not one: a new session leaves the process group that cancellation kills.
# Value is the set of options that consume the next token when written without `=`/attached value.
_WRAPPER_ARG_OPTS: dict[str, frozenset[str]] = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}),
    "xargs": frozenset(
        {"-I", "-n", "-L", "-P", "-s", "-d", "-E", "-a", "-e", "-l", "--max-args", "--max-procs",
         "--delimiter", "--arg-file", "--max-lines", "--max-chars", "--eof", "--replace"}
    ),
    "nice": frozenset({"-n", "--adjustment"}),
    "nohup": frozenset(),
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    "time": frozenset(),
    "command": frozenset(),
    "stdbuf": frozenset({"-i", "-o", "-e", "--input", "--output", "--error"}),
}  # fmt: skip
_MAX_WRAPPER_DEPTH = 8
_FIND_ACTION_FLAGS: frozenset[str] = frozenset(
    {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}
)
_AWK_BINS: frozenset[str] = frozenset({"awk", "gawk", "mawk", "nawk"})
_AWK_WRITE_RE = re.compile(r"\bprintf?\b[^;{}]*?>")
_ENV_ASSIGN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")


def _wrapped_command(bin_name: str, tokens: list[str]) -> list[str] | None:
    """The command *tokens* (after the wrapper's own arguments) hand to the shell, ``[]`` when the
    wrapper runs nothing (or only echoes), ``None`` when its options cannot be read safely."""
    takes_arg = _WRAPPER_ARG_OPTS[bin_name]
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        if tok == "--":
            idx += 1
            break
        if bin_name == "env" and _ENV_ASSIGN_RE.fullmatch(tok):
            idx += 1
            continue
        if not tok.startswith("-") or tok == "-":
            break
        if bin_name == "time" and tok not in ("-p", "--portability"):
            return None
        if bin_name == "command" and tok in ("-v", "-V"):
            return []
        if tok in takes_arg:
            idx += 2
            continue
        if bin_name == "env" and (tok.startswith("-S") or tok.startswith("--split-string")):
            return None
        idx += 1
    rest = tokens[idx:]
    if bin_name == "timeout" and rest:
        rest = rest[1:]  # the DURATION operand
    return rest


def _unwrap(tokens: list[str]) -> list[str] | None:
    """Peel command wrappers off *tokens* and return the command that really runs (the last
    wrapper's own tokens when it runs nothing); ``None`` when too deep or unreadable."""
    for _ in range(_MAX_WRAPPER_DEPTH):
        bin_name = os.path.basename(tokens[0])
        if bin_name not in _WRAPPER_ARG_OPTS:
            return tokens
        inner = _wrapped_command(bin_name, tokens[1:])
        if inner is None:
            return None
        if not inner:
            return tokens
        tokens = inner
    return None


def _executes_or_writes(bin_name: str, tokens: list[str]) -> str | None:
    """Why an allowlisted ``find``/``awk`` invocation deletes, executes or writes, else ``None``."""
    args = tokens[1:]
    if bin_name == "find":
        hit = sorted(_FIND_ACTION_FLAGS.intersection(args))
        return f"find {hit[0]}" if hit else None
    if bin_name in _AWK_BINS:
        program = " ".join(
            tok
            for i, tok in enumerate(args)
            if not (tok.startswith("-F") or args[i - 1 : i] == ["-F"])
        )
        if (
            "system(" in program
            or "|" in program.replace("||", "")
            or _AWK_WRITE_RE.search(program)
        ):
            return f"{bin_name} program that runs a command or writes a file"
    return None


def classify_command(
    command: str,
    extra_bins: frozenset[str] = frozenset(),
    roots: tuple[Path, ...] = (),
    jailed: bool = False,
) -> CommandVerdict:
    """Decide whether *command* may run unattended. First match wins: empty
    -> deny; opaque (command substitution/``eval``/``exec``) or
    untokenizable -> ask, since the binary that will run is not knowable; a
    high-risk class matching the full line -> ask, naming it (argument-aware:
    ``git`` is allowlisted, but ``git push origin production`` still asks);
    any segment's binary off ``SAFE_BINS`` (and off *extra_bins*) -> ask,
    naming it (every segment is checked, so a safe binary cannot smuggle an
    unsafe one in behind ``;``/``&&``); a redirect-sensitive SAFE_BINS entry
    (``echo``) used with an output redirect -> ask, by that same
    not-on-the-allowlist path, so adding it to SAFE_BINS did not also unlock
    unattended arbitrary-path writes -- unless every target resolves inside
    *roots* (``_redirects_stay_inside``), the workspace the file tools are
    already confined to; otherwise -> allow.

    *extra_bins* is a caller-supplied, per-pod extension of the membership
    check only (``core.pod.PodSettings.allow_commands``) -- it never widens
    the opaque-marker check or the high-risk-class check above, both of which
    still run against the full command line first. Every member of
    *extra_bins* is treated as redirect-sensitive, the same conservative rule
    ``echo`` gets, since docket cannot know whether a pod-supplied binary's
    argument is model-composed text. The default, empty *extra_bins* leaves
    every prior verdict byte-identical, as does the default, empty *roots*:
    with nowhere to place a target, a sensitive redirect always asks.

    *jailed* (the call will run inside the execution envelope) stands the
    allowlist down: a binary off it is allowed. The opaque check, the
    high-risk classes and redirect containment (now for every binary) still
    apply, so only the allowlist's approval noise goes.

    Does not catch: a safe binary used destructively within its own remit
    (``git reset --hard``), writes through a redirect outside the workspace
    for a binary that is not redirect-sensitive (path containment in
    ``core/tools.py`` covers file tools, not shell redirects), or anything a
    script on the allowlist does once started. A gate, not a sandbox --
    sandboxed exec (``ToolContext.sandbox``) is a separate, opt-in mechanism
    this classifier neither provides nor requires.
    """
    text = command.strip()
    if not text:
        return CommandVerdict("deny", "empty command")

    lowered = text.lower()
    for marker in _OPAQUE_MARKERS:
        if marker in lowered:
            return CommandVerdict(
                "ask", f"command is not statically analysable (contains {marker.strip()!r})"
            )

    try:
        segments = _split_segments(text)
    except ValueError as ex:
        return CommandVerdict("ask", f"command could not be parsed ({ex})")
    if not segments:
        return CommandVerdict("deny", "no binary found in command")

    risk = match_high_risk(text)
    if risk is not None:
        return CommandVerdict(
            "ask",
            f"matches high-risk action class {risk.name!r}: {risk.description}",
            bin_name=os.path.basename(segments[0].tokens[0]),
            risk_class=risk.name,
        )

    changed_directory = False
    for segment in segments:
        effective = _unwrap(segment.tokens)
        if effective is None:
            return CommandVerdict(
                "ask", "command wrapper could not be read", bin_name=segment.tokens[0]
            )
        bin_name = os.path.basename(effective[0])
        if not jailed:
            reason = _executes_or_writes(bin_name, effective)
            if reason is not None:
                return CommandVerdict(
                    "ask", f"{reason} is not safe to run unattended", bin_name=bin_name
                )
        off_allowlist = bin_name not in SAFE_BINS and bin_name not in extra_bins
        redirect_sensitive = (
            jailed or bin_name in _REDIRECT_SENSITIVE_BINS or bin_name in extra_bins
        )
        if jailed and off_allowlist:
            off_allowlist = False
        if (
            not off_allowlist
            and segment.redirected
            and redirect_sensitive
            and not _redirects_stay_inside(segment, roots, changed_directory)
        ):
            off_allowlist = True
        if off_allowlist:
            return CommandVerdict(
                "ask", f"{bin_name!r} is not on the curated allowlist", bin_name=bin_name
            )
        if bin_name in _DIRECTORY_CHANGERS:
            changed_directory = True

    return CommandVerdict(
        "allow",
        "all binaries allowlisted, no high-risk class matched",
        bin_name=os.path.basename(segments[0].tokens[0]),
    )


def apply_workspace_isolation() -> None:
    """Record that per-agent Docker sandbox isolation is desired.

    The Docker capability check at ``docket setup sandbox on`` time is the
    caller's responsibility. Writes fleet.json's isolation mode, read by
    ``DocketDriver`` on every turn to decide real landlock, seatbelt or docker containment
    when a backend is usable, or an audited refusal instead of an
    unsandboxed run when none is.
    """
    _fleet.set_sandbox_isolation(mode="non-main")


def disable_workspace_isolation() -> None:
    """Turn the recorded sandbox-isolation mode off (mode: off)."""
    _fleet.disable_sandbox_isolation()
