"""Security-gate logic: docket's own command classifier + approval/isolation config.

``dispatch_tool`` (``core/tools.py``) keeps ``pre_tool_call`` and
``classify_command`` below unconditionally live -- no "enable the gate"
step, no daemon-side exec-approval mechanism (there is no daemon). Only
docket's own approval-routing and workspace-isolation state is configurable
(``core/fleet.py``'s ``FleetSecurity``, ``docket gates enable/disable``,
``docket gates isolate``) -- not whether calls are gated, only where a
prompt routes and whether execution is sandboxed. Also owns
``match_high_risk``, the argument-aware allow/ask/deny classifier used by
the live gate and ``edges/adapters/system.py``'s ``run_verify_cmd``.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass

from docket.core import fleet as _fleet

# Curated set of common, lower-risk binaries `classify_command` allows
# unattended. Destructive/sensitive bins (rm, dd, docker, systemctl, ...) and
# shell interpreters are deliberately OMITTED so they fall through to `ask`.
# NOTE: a bin listed here (e.g. git, npm) can still have a HIGH_RISK_PATTERNS
# class attached for documentation/visibility (`docket gates classes`) — see
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
    "git", "node", "npm", "npx", "pnpm", "yarn", "python3", "pip", "pip3",
    "go", "cargo", "rustc", "make", "cmake",
    "date", "env", "printf", "which", "xargs", "tee", "less",
    "mkdir", "touch", "cp", "mv", "ln",
    "cd", "pwd", "echo", "true", "false", "test", "[",
)  # fmt: skip

# `echo`'s argument is often model-composed text, so redirecting it (`>`/`>>`/
# `&>`) is an unattended arbitrary-path write in a way a bare `echo hi` is not.
# Adding `echo` to SAFE_BINS above must not also unlock that -- a redirected
# invocation of a bin in this set still asks, by the same generic "not on the
# curated allowlist" path (`classify_command` below), verbatim identical to
# the verdict `echo` got before it was ever added to SAFE_BINS. `cd`, `pwd` and
# the rest do not take free-form model-composed content, so they are not here.
_REDIRECT_SENSITIVE_BINS: frozenset[str] = frozenset({"echo"})

# Output-writing redirects only -- `<` (input) and a bare `2>` (stderr) do not
# let arbitrary content reach a file the way `>`/`>>`/`&>` do.
_OUTPUT_REDIRECT_OPS: frozenset[str] = frozenset({">", ">>", "&>"})


@dataclass(frozen=True)
class HighRiskClass:
    """A named, documented high-risk action class.

    ``pattern`` is matched case-insensitively against the full command
    string, not just a binary name. ``bins`` names overlapping SAFE_BINS
    members for visibility only (``docket gates classes``) -- it does
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
            r"git\s+push\s+.*\b(main|master|production|prod)\b|npm\s+publish"
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


def _split_segments_with_redirect_flags(command: str) -> list[tuple[list[str], bool]]:
    """Same walk as :func:`split_command_segments`, plus whether an output redirect
    attached to each segment -- kept internal, used only by ``classify_command``."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    tokens = list(lexer)  # ValueError on unbalanced quotes; deliberately not caught here

    segments: list[tuple[list[str], bool]] = []
    current: list[str] = []
    redirected = False
    for token in tokens:
        if token in _COMMAND_SEPARATORS:
            if current:
                segments.append((current, redirected))
            current, redirected = [], False
            continue
        # Redirections attach to the current invocation rather than starting a
        # new one, but the target is not a binary — drop the operator and let
        # the path stay as an argument.
        if token in (">", ">>", "<", "2>", "&>"):
            if token in _OUTPUT_REDIRECT_OPS:
                redirected = True
            continue
        current.append(token)
    if current:
        segments.append((current, redirected))

    cleaned: list[tuple[list[str], bool]] = []
    for segment, flag in segments:
        idx = 0
        while idx < len(segment) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", segment[idx]):
            idx += 1
        if idx < len(segment):
            cleaned.append((segment[idx:], flag))
    return cleaned


def split_command_segments(command: str) -> list[list[str]]:
    """Split a shell command into per-invocation token lists.

    ``ls -la && git push origin main`` -> ``[["ls", "-la"], ["git", "push",
    "origin", "main"]]``; leading ``VAR=value`` assignments are dropped so
    the binary is always the first token. Raises ``ValueError`` on input
    shlex cannot tokenize -- the caller treats that as unclassifiable, never
    as safe.
    """
    return [tokens for tokens, _redirected in _split_segments_with_redirect_flags(command)]


def classify_command(command: str) -> CommandVerdict:
    """Decide whether *command* may run unattended. First match wins: empty
    -> deny; opaque (command substitution/``eval``/``exec``) or
    untokenizable -> ask, since the binary that will run is not knowable; a
    high-risk class matching the full line -> ask, naming it (argument-aware:
    ``git`` is allowlisted, but ``git push origin production`` still asks);
    any segment's binary off ``SAFE_BINS`` -> ask, naming it (every segment
    is checked, so a safe binary cannot smuggle an unsafe one in behind
    ``;``/``&&``); a redirect-sensitive SAFE_BINS entry (``echo``) used with an
    output redirect -> ask, by that same not-on-the-allowlist path, so adding
    it to SAFE_BINS did not also unlock unattended arbitrary-path writes;
    otherwise -> allow.

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
        segment_pairs = _split_segments_with_redirect_flags(text)
    except ValueError as ex:
        return CommandVerdict("ask", f"command could not be parsed ({ex})")
    if not segment_pairs:
        return CommandVerdict("deny", "no binary found in command")

    risk = match_high_risk(text)
    if risk is not None:
        return CommandVerdict(
            "ask",
            f"matches high-risk action class {risk.name!r}: {risk.description}",
            bin_name=os.path.basename(segment_pairs[0][0][0]),
            risk_class=risk.name,
        )

    for segment, redirected in segment_pairs:
        bin_name = os.path.basename(segment[0])
        off_allowlist = bin_name not in SAFE_BINS
        if not off_allowlist and redirected and bin_name in _REDIRECT_SENSITIVE_BINS:
            off_allowlist = True
        if off_allowlist:
            return CommandVerdict(
                "ask", f"{bin_name!r} is not on the curated allowlist", bin_name=bin_name
            )

    return CommandVerdict(
        "allow",
        "all binaries allowlisted, no high-risk class matched",
        bin_name=os.path.basename(segment_pairs[0][0][0]),
    )


def apply_approval_routing() -> int:
    """Route gated-tool-call approval prompts to each agent's session channel.

    Writes fleet.json's approval-routing state to on/session. Returns the
    count of channel-bound agents (informational) -- a readiness signal, not
    a guarantee: a bound agent only receives a prompt once ``docket serve
    --telegram`` is running with a bot token configured.
    """
    _fleet.set_approval_routing(enabled=True, mode="session")
    count = 0
    for aid in _fleet.all_agent_ids():
        if _fleet.get_binding(aid):
            count += 1
    return count


def disable_approval_routing() -> None:
    """Turn approval-routing off in fleet.json."""
    _fleet.disable_approval_routing()


def apply_workspace_isolation() -> None:
    """Record that per-agent Docker sandbox isolation is desired.

    The Docker capability check at ``docket gates isolate on`` time is the
    caller's responsibility. Writes fleet.json's isolation mode, read by
    ``DocketDriver`` on every turn to decide real docker/bwrap containment
    when a backend is usable, or an audited refusal instead of an
    unsandboxed run when neither is.
    """
    _fleet.set_sandbox_isolation(mode="non-main")


def disable_workspace_isolation() -> None:
    """Turn the recorded sandbox-isolation mode off (mode: off)."""
    _fleet.disable_sandbox_isolation()
