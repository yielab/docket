"""Security-gate logic: docket's own command classifier + approval/isolation config.

``dispatch_tool`` (``agent/tools/registry.py``) keeps ``pre_tool_call`` and
``classify_command`` below unconditionally live -- no "enable the gate"
step, no daemon-side exec-approval mechanism (there is no daemon). Only
docket's own workspace-isolation and network state is configurable
(``teams/fleet.py``'s ``FleetSecurity``, ``docket setup sandbox``,
``docket setup sandbox network``) -- not whether calls are gated, only whether
execution is sandboxed and what network the sandbox has. Also owns
``match_high_risk``, the argument-aware allow/ask/deny classifier used by
the live gate and ``sandbox/launch.py``'s ``run_command``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from docket.governance.command_lexer import (
    Segment,
    cut_quoted_heredocs,
    ends_in_background,
    split_segments,
    unwrap,
)

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
#
# Each pattern is searched in three forms of a command (see `_command_forms`): the raw text, each
# invocation with its quoting undone, and each invocation with its options dropped, so an option
# before the verb (`kubectl -n prod apply`, `vault -address=x kv put`) or a quoted word
# (`"vault" kv put`, `api.s""tripe.com`) does not hide the verb. A verb may be preceded by one
# option's value (`kubectl prod apply` once `-n` is dropped), hence `(?:\s+\S+)?`.
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
            r"\bgit\b(?:\s+\S+)*?\s+push\b.*(?:\b(?:main|master|production|prod)\b|--(?:all|mirror)\b)"
            r"|\b(npm|pnpm|yarn)(?:\s+\S+)?\s+publish\b|\bcargo\s+publish\b|\btwine\s+upload\b"
            r"|\b(docker|podman)(?:\s+\S+)?\s+(push|stop)\b|\b(docker|podman)\b.*\s--push\b"
            r"|\b(terraform|tofu)(?:\s+\S+)?\s+(apply|destroy)\b"
            r"|\bkubectl(?:\s+\S+)?\s+(apply|delete|replace|rollout)\b"
            r"|\bhelm(?:\s+\S+)?\s+(upgrade|install)\b"
            r"|\b(flyctl|fly)(?:\s+\S+)?\s+deploy\b|\bvercel\b.*(\bdeploy\b|--prod\b)"
            r"|\bgh(?:\s+\S+)?\s+release\s+(create|delete|upload)\b"
            r"|\bheroku\b.*\b(releases:rollback|promote)\b|\bansible-playbook\b"
        ),
        bins=("git", "npm"),
    ),
    HighRiskClass(
        name="secret-access",
        description="Secret/credential writes and key generation",
        pattern=(
            r"\bvault(?:\s+\S+)?\s+(write|kv\s+put|token\s+create)\b|ssh-keygen"
            r"|\bopenssl\b.*\b(genrsa|genpkey|ecparam)\b|\bopenssl\s+req\b.*\s-newkey\b"
            r"|\bgpg\b.*--(full-|quick-)?(gen-key|generate-key)\b"
            r"|\bkubectl(?:\s+\S+)?\s+(create|apply)\b.*secret"
            r"|\baws\b.*\b(secretsmanager|ssm)\b.*\b(put|create|update)-?"
        ),
    ),
)


def _command_forms(command: str) -> list[str]:
    """The texts a high-risk pattern is searched in: *command* as written, then each invocation
    with its quoting undone and with its options dropped (``command_segments``). A command the
    lexer cannot read is searched as written only."""
    forms = [command]
    try:
        segments = command_segments(command)
    except ValueError:
        return forms
    for segment in segments:
        words = [segment.program, *segment.args]
        forms.append(" ".join(words))
        forms.append(" ".join(w for w in words if not w.startswith("-")))
    return forms


def match_high_risk(command: str) -> HighRiskClass | None:
    """Return the first HIGH_RISK_PATTERNS class matching *command*, else None.

    The single classification entry point: wired into ``run_command``
    (refuses outright before the shell ever starts) and dispatch's
    ``pre_output`` scan; ``classify_command`` below also calls this to
    decide ``ask`` for a live tool call, the check ``dispatch_tool`` enforces.
    See specs/functional/security-gates.spec.md.
    """
    forms = _command_forms(command)
    for cls in HIGH_RISK_PATTERNS:
        if any(re.search(cls.pattern, form, re.IGNORECASE) for form in forms):
            return cls
    return None


# ── argument-aware command classification ────────────────────────────────
#
# `agent/tools/registry.py`'s `dispatch_tool` runs every tool call itself, so this
# classifier has a real enforcement point downstream. What follows is
# deliberately NOT a restoration of the old bare-binary-name classifier
# described in `match_high_risk`'s docstring above: that granularity made
# `git push origin production` indistinguishable from `git status`. This one
# reads the whole command line, including every segment behind a `;`, `&&`
# or pipe.

# Substrings that make a command line impossible to classify statically: the
# real binary is produced at runtime. Their presence forces an approval rather
# than a guess.
_OPAQUE_MARKERS: tuple[str, ...] = ("$(", "`", "${", "eval ", "exec ")

# A trailing `&` starts a child the call does not wait for; the governed way is the `bash` tool's
# `background` argument.
_BACKGROUND_REASON = "background a process with bash background=true"


@dataclass(frozen=True)
class CommandVerdict:
    """What docket decided about one shell command, and why.

    ``action`` is allow/ask/deny; ``ask`` routes to ``governance/approval.py``,
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


def _redirects_stay_inside(
    segment: Segment, roots: tuple[Path, ...], base: Path | None
) -> str | None:
    """None when every output redirect names ``/dev/null`` or a path inside *roots* (relative to
    *base*, symlinks followed); otherwise the reason it cannot be placed. A *base* of None
    means an earlier ``cd`` the classifier could not follow."""
    if len(segment.targets) != segment.redirects:
        return "output redirect has no target"
    placed = [target for target in segment.targets if target != _DISCARD_TARGET]
    if not placed:
        return None
    if roots and base is None:
        return "output redirect after cd cannot be placed"
    try:
        bounds = [root.resolve() for root in roots]
    except OSError:
        return f"output redirect to {placed[0]} is outside the workspace"
    for target in placed:
        outside = f"output redirect to {target} is outside the workspace"
        if not roots or base is None or not target:
            return outside
        if _UNPLACEABLE_TARGET_CHARS & set(target):
            return f"output redirect to {target} cannot be placed (the shell rewrites it)"
        candidate = Path(target) if os.path.isabs(target) else base / target
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError):
            return outside
        if not any(resolved.is_relative_to(bound) for bound in bounds):
            return outside
    return None


def _followed_directory(effective: list[str], base: Path | None, follow: bool) -> Path | None:
    """Where a ``cd`` leaves the working directory: the literal target resolved against *base*,
    or None when it cannot be followed."""
    if not follow or base is None or effective[0] != "cd" or len(effective) != 2:
        return None
    target = effective[1]
    if not target or target == "-" or target.startswith("~") or "`" in target:
        return None
    if _UNPLACEABLE_TARGET_CHARS & set(target):
        return None
    try:
        return (Path(target) if os.path.isabs(target) else base / target).resolve()
    except (OSError, RuntimeError):
        return None


_FIND_ACTION_FLAGS: frozenset[str] = frozenset(
    {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}
)
_AWK_BINS: frozenset[str] = frozenset({"awk", "gawk", "mawk", "nawk"})
_AWK_WRITE_RE = re.compile(r"\bprintf?\b[^;{}]*?>")


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


# Programs whose non-option arguments are the paths they create, replace, edit in place or delete.
_PATH_WRITERS: frozenset[str] = frozenset(
    {
        "tee",
        "cp",
        "mv",
        "install",
        "ln",
        "rsync",
        "touch",
        "truncate",
        "rm",
        "unlink",
        "shred",
        "srm",
    }
)
_SED_IN_PLACE_RE = re.compile(r"-[nsEr]*i|--in-place")
_PERL_IN_PLACE_RE = re.compile(r"-[nplaF0-9]*i")


@dataclass(frozen=True)
class CommandSegment:
    """One invocation of a command line as ``command_segments`` reads it: the *program* (its
    basename, quoting undone, wrappers such as ``env`` or ``xargs`` peeled), the *args* after it,
    and the *writes* it makes to paths (its output redirect targets, plus the paths a known writer
    such as ``tee``, ``cp``, ``dd of=`` or ``sed -i`` is given)."""

    program: str
    args: tuple[str, ...]
    writes: tuple[str, ...]


def _write_targets(program: str, args: tuple[str, ...]) -> tuple[str, ...]:
    """The paths the known writer *program* writes to, from its *args*."""
    operands = tuple(a for a in args if not a.startswith("-"))
    if program in _PATH_WRITERS:
        return operands
    if program == "dd":
        return tuple(a[3:] for a in args if a.startswith("of="))
    if program == "sed" and any(_SED_IN_PLACE_RE.match(a) for a in args):
        return operands
    if program == "perl" and any(_PERL_IN_PLACE_RE.match(a) for a in args):
        return operands
    return ()


def command_segments(command: str) -> list[CommandSegment]:
    """Read *command* the way ``classify_command`` does and return its invocations: every
    segment behind ``;``/``&&``/``||``/pipe, quoting undone, leading assignments and command
    wrappers peeled. Raises ``ValueError`` for a command the lexer cannot read (unbalanced
    quotes). A heredoc body that is not fed to a shell is not part of any invocation."""
    text, _unclosed = cut_quoted_heredocs(command.strip())
    found: list[CommandSegment] = []
    for segment in split_segments(text.strip()):
        effective = unwrap(segment.tokens) or segment.tokens
        program = os.path.basename(effective[0])
        args = tuple(effective[1:])
        found.append(
            CommandSegment(program, args, (*segment.targets, *_write_targets(program, args)))
        )
    return found


def classify_command(
    command: str,
    extra_bins: frozenset[str] = frozenset(),
    roots: tuple[Path, ...] = (),
    jailed: bool = False,
) -> CommandVerdict:
    """Decide whether *command* may run unattended. First match wins: empty
    -> deny; opaque (command substitution/``eval``/``exec``) or
    untokenizable -> ask, since the binary that will run is not knowable; a
    trailing ``&`` -> ask, since the child outlives the call (``bash`` has ``background``); a
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
    check only (``teams.pod_settings.PodSettings.allow_commands``) -- it never widens
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
    ``agent/tools/registry.py`` covers file tools, not shell redirects), or anything a
    script on the allowlist does once started. A gate, not a sandbox --
    sandboxed exec (``ToolContext.sandbox``) is a separate, opt-in mechanism
    this classifier neither provides nor requires.
    """
    text = command.strip()
    if not text:
        return CommandVerdict("deny", "empty command")

    full_text = text
    text, unclosed = cut_quoted_heredocs(text)
    if unclosed is not None:
        return CommandVerdict("ask", unclosed)
    text = text.strip()
    if not text:
        return CommandVerdict("deny", "no binary found in command")

    lowered = text.lower()
    for marker in _OPAQUE_MARKERS:
        if marker in lowered:
            return CommandVerdict(
                "ask", f"command is not statically analysable (contains {marker.strip()!r})"
            )

    try:
        segments = split_segments(text)
    except ValueError as ex:
        return CommandVerdict("ask", f"command could not be parsed ({ex})")
    if not segments:
        return CommandVerdict("deny", "no binary found in command")
    if ends_in_background(text):
        return CommandVerdict("ask", _BACKGROUND_REASON)

    risk = match_high_risk(full_text)
    if risk is not None:
        return CommandVerdict(
            "ask",
            f"matches high-risk action class {risk.name!r}: {risk.description}",
            bin_name=os.path.basename(segments[0].tokens[0]),
            risk_class=risk.name,
        )

    follow = "(" not in text and "||" not in text
    base: Path | None = roots[0].resolve() if roots else None
    for segment in segments:
        effective = unwrap(segment.tokens)
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
        if off_allowlist:
            return CommandVerdict(
                "ask", f"{bin_name!r} is not on the curated allowlist", bin_name=bin_name
            )
        if segment.redirected and redirect_sensitive:
            refusal = _redirects_stay_inside(segment, roots, base)
            if refusal is not None:
                return CommandVerdict("ask", refusal, bin_name=bin_name)
        if bin_name in _DIRECTORY_CHANGERS:
            base = _followed_directory(effective, base, follow and not segment.subshell)

    return CommandVerdict(
        "allow",
        "all binaries allowlisted, no high-risk class matched",
        bin_name=os.path.basename(segments[0].tokens[0]),
    )
