"""Declarative guardrail policy engine. A policy is JSON or YAML at ``$POLICIES_DIR/*``, written
in the one short form a person authors (``kind: policy``, ``appliesTo``, ``on``, ``when``,
``then``) that :func:`normalize_policy` and :func:`read_policy` turn into the in-memory canonical
dict ``{id, applies_to, hook, match, action, message}``; a canonical key in a file is refused.
``policy_eval`` returns the winning action (most restrictive wins); ``policy_eval_detail`` the
full :class:`PolicyHit` for attribution. A file that fails validation is never silently skipped:
it evaluates as ``block`` within its readable scope, attributed to the file (fail closed, spec
requirement 7). Never emits traces itself.
Live-path wiring: ``pre_input`` runs once at task enqueue; ``pre_output`` on every hop's output;
``pre_tool_call`` in-turn inside ``agent/tools/registry.py``'s ``dispatch_tool`` chokepoint, where a
``when`` predicate can also see the call itself via :class:`ToolCallFacts`."""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import docket.governance.plugin_api as _plugin_api
import docket.kernel.templates as _templates
from docket.governance import plugins as _plugins
from docket.governance import policy_command as _command
from docket.kernel.errors import InvalidInput
from docket.kernel.home import current_home

VALID_HOOKS: frozenset[str] = frozenset({"pre_input", "pre_tool_call", "pre_output"})
VALID_ACTIONS: frozenset[str] = frozenset({"allow", "warn", "redact", "require_approval", "block"})

# Short-form -> canonical mappings (ADR 0010).
_ON_TO_HOOK: dict[str, str] = {
    "input": "pre_input",
    "toolCall": "pre_tool_call",
    "output": "pre_output",
}
_THEN_TO_ACTION: dict[str, str] = {
    "allow": "allow",
    "warn": "warn",
    "ask": "require_approval",
    "block": "block",
    "redact": "redact",
}
_WHEN_PREDICATE_KEYS: frozenset[str] = frozenset(
    {"tool", "path", "matches", "branch", "plugin", "command"}
)
_WHEN_MODIFIER_KEYS: frozenset[str] = frozenset({"with"})  # meaningful only beside "plugin"
_POLICY_GLOBS: tuple[str, ...] = ("*.json", "*.yaml", "*.yml")

# Most-restrictive-wins ranking.
_RANK: dict[str, int] = {
    "block": 4,
    "require_approval": 3,
    "redact": 2,
    "warn": 1,
    "allow": 0,
}

# The id every task-restriction document evaluates and audits under.
TASK_POLICY_ID = "task-restriction"

# The block-only documents the running turn's task carries, set by ``task_policies``.
_TASK_POLICIES: ContextVar[tuple[dict[str, Any], ...]] = ContextVar("_TASK_POLICIES", default=())

# Policy ids skipped when source=operator (--trusted).
_INJECTION_IDS: frozenset[str] = frozenset({"prompt-injection"})


def _validate_when(when: Any, label: str) -> str:
    """Validate a canonical ``when`` predicate mapping (or one ``anyOf`` item): '' if valid,
    else the error. Unknown keys are reported against the five leaf predicates -- ``anyOf`` is
    the OR container, not a predicate itself."""
    if not isinstance(when, dict):
        return f"{label}: when must be a mapping"
    unknown = set(when.keys()) - _WHEN_PREDICATE_KEYS - _WHEN_MODIFIER_KEYS - {"anyOf"}
    if unknown:
        return (
            f"{label}: unknown predicate key(s) {sorted(unknown)} "
            "(valid: tool, path, matches, branch, plugin, command)"
        )
    command = when.get("command")
    if command is not None:
        err = _command.validate_command(command, label)
        if err:
            return err
    matches = when.get("matches")
    if matches is not None:
        try:
            re.compile(str(matches), re.IGNORECASE | re.MULTILINE)
        except re.error as exc:
            return f"{label}: when.matches does not compile: {exc}"
    plugin = when.get("plugin")
    if plugin is not None and not str(plugin).strip():
        return f"{label}: when.plugin must be a non-empty string"
    with_ = when.get("with")
    if with_ is not None and not isinstance(with_, dict):
        return f"{label}: when.with must be a mapping"
    if "with" in when and not plugin:
        return f"{label}: when.with requires when.plugin"
    any_of = when.get("anyOf")
    if any_of is not None:
        if not isinstance(any_of, list) or not any_of:
            return f"{label}: when.anyOf must be a non-empty list"
        for item in any_of:
            err = _validate_when(item, label)
            if err:
                return err
    return ""


def _validate_doc(p: dict[str, Any], label: str) -> str:
    """Validate one canonical policy document; '' if valid, else the error. The single owner of
    "what a valid policy is": ``validate_policy``, the evaluator's fail-closed check and doctor
    all call this, so validator and evaluator can never disagree (spec requirement 7)."""
    required = {"id", "applies_to", "hook", "action"}
    missing = required - set(p.keys())
    if missing:
        return f"{label}: missing fields: {missing}"
    if p.get("hook") not in VALID_HOOKS:
        return (
            f"{label}: unknown hook '{p.get('hook')}' (valid: pre_input, pre_tool_call, pre_output)"
        )
    if p.get("action") not in VALID_ACTIONS:
        return f"{label}: unknown action '{p.get('action')}'"

    # A document fires on a `match` (the text regex), a `when` (structured predicates
    # over the tool call), or both -- it must carry at least one.
    match = p.get("match")
    when = p.get("when")
    if match is None and when is None:
        return f"{label}: match or when is required"
    if match is not None:
        if not isinstance(match, dict) or match.get("type") not in ("regex",):
            return f"{label}: match.type must be 'regex'"
        pattern = match.get("pattern")
        if not pattern:
            return f"{label}: match.pattern is required"
        try:
            re.compile(str(pattern), re.IGNORECASE | re.MULTILINE)
        except re.error as exc:
            return f"{label}: match.pattern does not compile: {exc}"
    if when is not None:
        err = _validate_when(when, label)
        if err:
            return err
    return ""


# The canonical keys an authored policy must not carry, each with the short-form spelling to use.
_CANONICAL_ONLY_KEYS: dict[str, str] = {
    "id": "name",
    "applies_to": "appliesTo",
    "hook": "on",
    "action": "then",
    "match": "when: {matches: ...}",
}


def canonical_key_refusal(doc: dict[str, Any]) -> str:
    """The message refusing a canonical key in an authored policy, naming the short-form key to
    write instead; ``""`` when *doc* carries none."""
    keys = [key for key in _CANONICAL_ONLY_KEYS if key in doc]
    if not keys:
        return ""
    return "a policy is written in the short form; " + "; ".join(
        f"replace `{key}` with `{_CANONICAL_ONLY_KEYS[key]}`" for key in keys
    )


def normalize_policy(short: dict[str, Any]) -> dict[str, Any]:
    """Normalize one short-form policy document to the in-memory canonical
    ``{id, applies_to, hook, match, action, message}`` shape (plus an optional structured
    ``when``) that :func:`_validate_doc` and :func:`policy_eval_detail` evaluate. A canonical
    key is refused, naming the short-form key to use. Pure: no I/O."""
    doc = dict(short)
    refusal = canonical_key_refusal(doc)
    if refusal:
        raise InvalidInput(refusal)

    # A top-level `kind: policy` is accepted and stripped; any other value is refused, naming
    # the expected one.
    kind = doc.pop("kind", None)
    if kind is not None and kind != "policy":
        raise InvalidInput(f"expected kind: policy, got kind: {kind!r}")

    canonical: dict[str, Any] = dict(doc)

    # `name` -> `id`; `appliesTo` -> `applies_to`; `on: input|toolCall|output` -> `hook`,
    # defaulting to `pre_tool_call` when neither `on` nor `hook` is given; `then:
    # allow|warn|ask|block|redact` -> `action`, with `ask` mapping to `require_approval`.
    if "name" in doc:
        canonical["id"] = doc["name"]
        del canonical["name"]
    if "appliesTo" in doc:
        canonical["applies_to"] = doc["appliesTo"]
        del canonical["appliesTo"]
    if "on" in doc:
        canonical["hook"] = _ON_TO_HOOK.get(doc["on"], doc["on"])
        del canonical["on"]
    elif "hook" not in canonical:
        canonical["hook"] = "pre_tool_call"
    if "then" in doc:
        canonical["action"] = _THEN_TO_ACTION.get(doc["then"], doc["then"])
        del canonical["then"]

    # `when: {tool?, path?, matches?, branch?, anyOf?}` is copied through -- except that a
    # `when` whose only key is `matches` collapses into `match: {type: regex, pattern: ...}`
    # instead, so a plain regex policy's canonical form is byte-identical whether it was
    # written short or long (the round trip the shipped templates rely on).
    when = doc.get("when")
    if isinstance(when, dict):
        when = dict(when)
        matches = when.pop("matches", None)
        if matches is not None and not when:
            canonical["match"] = {"type": "regex", "pattern": matches}
            canonical.pop("when", None)
        else:
            if matches is not None:
                when["matches"] = matches
            canonical["when"] = when

    return canonical


_HOOK_TO_ON: dict[str, str] = {v: k for k, v in _ON_TO_HOOK.items()}
_ACTION_TO_THEN: dict[str, str] = {v: k for k, v in _THEN_TO_ACTION.items()}


def to_short_policy(canonical: dict[str, Any]) -> dict[str, Any]:
    """Inverse of :func:`normalize_policy`: the short-form document for one already-canonical
    policy dict. ``hook`` collapses back to ``on`` only when it differs from the
    ``pre_tool_call`` default. Pure: no I/O."""
    doc = dict(canonical)
    short: dict[str, Any] = {"kind": "policy"}
    if "id" in doc:
        short["name"] = doc.pop("id")
    if "description" in doc:
        short["description"] = doc.pop("description")
    if "applies_to" in doc:
        short["appliesTo"] = doc.pop("applies_to")

    hook = doc.pop("hook", "pre_tool_call")
    if hook != "pre_tool_call":
        short["on"] = _HOOK_TO_ON.get(hook, hook)

    match = doc.pop("match", None)
    when = doc.pop("when", None)
    if isinstance(match, dict) and match.get("type") == "regex":
        merged = dict(when) if isinstance(when, dict) else {}
        merged["matches"] = match.get("pattern")
        short["when"] = merged
    elif when is not None:
        short["when"] = when

    action = doc.pop("action", None)
    short["then"] = _ACTION_TO_THEN.get(action, action)

    if "message" in doc:
        short["message"] = doc.pop("message")

    short.update(doc)
    return short


def read_policy(path: Path) -> dict[str, Any]:
    """Parse one short-form policy file -- JSON or YAML -- into the canonical dict every caller
    evaluates. The single reader ``validate_policy``, the evaluator's per-file loop, and the
    CLI's list/show/validate share."""
    # Try JSON first: a policy written as JSON must read without PyYAML, and this function is
    # bundled verbatim into the embeddable substrate, which deliberately carries no PyYAML
    # dependency -- reading an existing file must never newly require one. Only a genuine
    # short-form/YAML-syntax file pays the PyYAML cost, and only where it is installed (the
    # full CLI always has it).
    text = path.read_text(encoding="utf-8")
    try:
        doc: Any = json.loads(text)
    except ValueError:
        import yaml as _yaml  # type: ignore[import-untyped]

        class _PolicyLoader(_yaml.SafeLoader):  # type: ignore[misc]
            pass

        # YAML 1.1's default resolver treats a bare on/off/yes/no as a boolean, which would
        # silently turn the short form's own `on:` key into `{True: ...}` instead of `{"on":
        # ...}` unless every author remembered to quote it. No policy field is ever a real
        # boolean, so dropping the resolver costs nothing.
        _PolicyLoader.yaml_implicit_resolvers = {
            first: [r for r in resolvers if r[0] != "tag:yaml.org,2002:bool"]
            for first, resolvers in _yaml.SafeLoader.yaml_implicit_resolvers.items()
        }
        doc = _yaml.load(text, Loader=_PolicyLoader)
    if not isinstance(doc, dict):
        raise InvalidInput(f"{path}: policy document must be a mapping")
    return normalize_policy(doc)


def validate_policy(path: Path) -> str:
    """Validate one policy file: '' if valid, else an error message. Wired into ``docket
    pod validate`` and shared with the evaluator's fail-closed check via ``_validate_doc``."""
    try:
        p = read_policy(path)
    except Exception as exc:
        return f"Cannot parse {path}: {exc}"
    return _validate_doc(p, str(path))


def checked_task_document(canonical: dict[str, Any]) -> dict[str, Any]:
    """A canonical task-restriction document (as ``task_policy_document`` returned it, carried to
    the turn in ``DOCKET_TASK_POLICIES``) validated again as a block policy under
    ``TASK_POLICY_ID``; raises ``InvalidInput`` for anything invalid or whose action is not
    ``block``."""
    canonical = dict(canonical)
    canonical["id"] = TASK_POLICY_ID
    error = _validate_doc(canonical, TASK_POLICY_ID)
    if error:
        raise InvalidInput(error)
    if canonical["action"] != "block":
        raise InvalidInput(f"a task policy may only block, got action {canonical['action']!r}")
    return canonical


def task_policy_document(doc: Any) -> dict[str, Any]:
    """*doc* (short form) as a validated canonical block policy under ``TASK_POLICY_ID``;
    raises ``ValueError`` for anything invalid or whose action is not ``block``."""
    if not isinstance(doc, dict):
        raise InvalidInput("a task policy must be a mapping")
    return checked_task_document(normalize_policy(doc))


def denied_tools_document(names: Sequence[str]) -> dict[str, Any]:
    """One ``pre_tool_call`` block document naming every tool in *names* (``when.anyOf``)."""
    return {
        "id": TASK_POLICY_ID,
        "applies_to": ["*"],
        "hook": "pre_tool_call",
        "action": "block",
        "message": "tool denied by this task's restrictions",
        "when": {"anyOf": [{"tool": name} for name in names]},
    }


@contextmanager
def task_policies(documents: Sequence[dict[str, Any]]) -> Iterator[None]:
    """Evaluate *documents* (already ``task_policy_document``-checked) after the file policies for
    the duration of the block, in this context only."""
    token = _TASK_POLICIES.set(tuple(documents))
    try:
        yield
    finally:
        _TASK_POLICIES.reset(token)


def _pod_policies_dir(project: str) -> Path | None:
    """This pod's own policy directory under ``pod_config_dir``, or ``None`` for no pod."""
    if not project:
        return None
    return current_home().pod_config_dir(project) / "policies"


def _glob_policy_files(directory: Path) -> list[Path]:
    """Every policy file directly under *directory* -- JSON or YAML -- sorted by name."""
    files: list[Path] = []
    for pattern in _POLICY_GLOBS:
        files.extend(directory.glob(pattern))
    return sorted(files)


def policy_files(project: str = "") -> list[Path]:
    """Installed policy files (JSON or YAML): the global set, then *project*'s own pod
    directory when given, each sorted -- a pod file only ever adds to the combined evaluation."""
    files: list[Path] = []
    # Each directory is checked independently -- an operator with no fleet-wide policies
    # installed must still get their pod's own.
    if current_home().policies_dir.is_dir():
        files.extend(_glob_policy_files(current_home().policies_dir))
    pod_dir = _pod_policies_dir(project)
    if pod_dir is not None and pod_dir.is_dir():
        files.extend(_glob_policy_files(pod_dir))
    return files


@dataclass
class PolicyHit:
    """The winning policy for one ``policy_eval_detail`` call.

    ``policy_id``/``message`` are ``""`` for the no-match default (``action="allow"``) so a caller
    can always safely bucket/attribute a trip by ``policy_id`` without a None-check."""

    action: str = "allow"
    policy_id: str = ""
    message: str = ""


@dataclass(frozen=True)
class ToolCallFacts:
    """The facts a ``when`` predicate can test, beside the hook's rendered text. ``worktree_root``
    reaches a plugin's ``PolicyContext`` unchanged; it plays no part in the built-in predicates."""

    tool: str
    # Raw call arguments; the `path` predicate reads whichever of path/file_path/file this
    # carries.
    args: dict[str, Any]
    # A zero-argument branch getter, called at most once per `policy_eval_detail` call and
    # only when some loaded policy declares a `branch` predicate.
    branch_of: Callable[[], str]
    worktree_root: str = ""


def _path_arg(args: dict[str, Any]) -> str | None:
    """The path a call's ``path`` predicate tests against: whichever of ``path``/``file_path``/
    ``file`` the arguments carry, or ``None`` when none do (the predicate then never matches)."""
    for key in ("path", "file_path", "file"):
        if key in args:
            return str(args[key])
    return None


class _PluginFailClosed(Exception):
    """A ``when.plugin`` predicate could not be evaluated -- unknown name, import failure, a
    raise, a non-bool return, or a budget overrun. Raised rather than returned so it wins
    wherever it appears in a predicate tree, including inside ``anyOf``."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _plugin_matches(
    when: dict[str, Any],
    call: ToolCallFacts | None,
    text: str,
    get_branch: Callable[[], str],
    role: str,
    project: str,
) -> bool:
    """Evaluate a ``when.plugin`` predicate. Raises ``_PluginFailClosed`` for an unapplied name
    or a plugin that fails; otherwise returns the plugin's own verdict."""
    name = str(when["plugin"])
    try:
        registry = _plugins.discover(project)
    except _plugins.PluginError:
        registry = {}
    pred = registry.get(name)
    if pred is None:
        raise _PluginFailClosed(f"plugin '{name}' is not applied in scope global or pod:{project}")
    tool_call = _plugin_api.ToolCall(
        tool=call.tool if call is not None else "",
        args=dict(call.args) if call is not None else {},
        rendered=text,
    )
    ctx = _plugin_api.PolicyContext(
        role=role,
        project=project,
        branch=get_branch(),
        worktree_root=call.worktree_root if call is not None else "",
    )
    verdict, reason = _plugins.evaluate(pred, tool_call, ctx, dict(when.get("with") or {}))
    if reason:
        raise _PluginFailClosed(f"plugin '{name}': {reason}")
    return verdict


def _predicate_matches(
    when: dict[str, Any],
    call: ToolCallFacts | None,
    text: str,
    get_branch: Callable[[], str],
    role: str = "",
    project: str = "",
) -> bool:
    """Evaluate one canonical ``when`` mapping: implicit AND across its keys, ``anyOf`` an OR
    over its items AND'd with any siblings. A failing ``plugin`` predicate raises
    ``_PluginFailClosed`` instead of returning, so the caller fails the whole policy closed."""
    # A `tool`/`path`/`branch` predicate never matches with `call is None` (a text-only hook);
    # `matches` always can, since it only needs the rendered text every hook already has.
    if "tool" in when and (call is None or call.tool != when["tool"]):
        return False
    if "path" in when:
        path_val = _path_arg(call.args) if call is not None else None
        if path_val is None or not fnmatch(path_val, str(when["path"])):
            return False
    if "matches" in when and not re.search(
        str(when["matches"]), text, re.IGNORECASE | re.MULTILINE
    ):
        return False
    if "branch" in when and (call is None or not fnmatch(get_branch(), str(when["branch"]))):
        return False
    if "command" in when and not (
        call is not None and _command.command_matches(when["command"], call.tool, call.args)
    ):
        return False
    if "plugin" in when and not _plugin_matches(when, call, text, get_branch, role, project):
        return False
    any_of = when.get("anyOf")
    if any_of:
        return any(
            _predicate_matches(item, call, text, get_branch, role, project) for item in any_of
        )
    return True


def policy_eval_detail(
    role: str,
    hook: str,
    text: str,
    *,
    trusted: bool = False,
    project: str = "",
    call: ToolCallFacts | None = None,
) -> PolicyHit:
    """Return the winning :class:`PolicyHit` for (role, hook, text); most restrictive wins.

    project: this call's pod, when it has one -- folds that pod's own policy files
    (``policy_files(project)``) into the same most-restrictive-wins evaluation as the global set;
    empty for a non-pod caller, which sees the global set only. trusted: skip injection/untrusted-
    input policies (source=operator). call: the tool name, arguments and a lazy branch getter a
    policy's structured ``when`` predicate can test, beside *text*; ``None`` for callers that
    only ever have text (``pre_input``, ``pre_output``, and a non-``exec`` dry run). Trace
    side-effects are intentionally omitted here -- this is the pure evaluator; a live-path caller
    or the CLI's dry-run (``policy_test``) decides what to do with the result."""
    best = PolicyHit()
    best_rank = 0
    branch_cache: dict[str, str] = {}

    def get_branch() -> str:
        if "value" not in branch_cache:
            branch_cache["value"] = call.branch_of() if call is not None else ""
        return branch_cache["value"]

    def consider(action: str, policy_id: str, message: str) -> None:
        nonlocal best, best_rank
        rank = _RANK.get(action, 0)
        if rank > best_rank:
            best_rank = rank
            best = PolicyHit(action=action, policy_id=policy_id, message=message)

    documents: list[tuple[str, dict[str, Any] | None, str]] = []
    for path in policy_files(project):
        try:
            documents.append((path.name, read_policy(path), ""))
        except Exception as exc:
            documents.append((path.name, None, f"unreadable: {exc}"))
    documents.extend((TASK_POLICY_ID, doc, "") for doc in _TASK_POLICIES.get())

    for label, p, unreadable in documents:
        # Fail closed on a broken file (security-gates.spec.md, policy engine requirement 7):
        # a file the validator rejects blocks within its readable scope -- its declared hook
        # and applies_to when those parse, every hook and role when the file itself does not --
        # attributed to the file so the audit/trace record names what to fix.
        error = unreadable if p is None else _validate_doc(p, label)
        if error:
            declared_hook = (p or {}).get("hook")
            hooks = {declared_hook} if declared_hook in VALID_HOOKS else VALID_HOOKS
            raw_applies = (p or {}).get("applies_to")
            applies = raw_applies if isinstance(raw_applies, list) and raw_applies else ["*"]
            if trusted and p is not None and p.get("id") in _INJECTION_IDS:
                continue
            if hook in hooks and ("*" in applies or role in applies):
                consider(
                    "block",
                    label,
                    f"policy file {label} is broken ({error}); failing closed",
                )
            continue

        assert p is not None  # a None p always carries an error above
        if p.get("hook") != hook:
            continue
        applies = p.get("applies_to", []) or []
        if "*" not in applies and role not in applies:
            continue
        if trusted and p.get("id") in _INJECTION_IDS:
            continue

        when = p.get("when")
        if isinstance(when, dict):
            try:
                fires = _predicate_matches(when, call, text, get_branch, role, project)
            except _PluginFailClosed as exc:
                consider("block", str(p.get("id", "")), exc.message)
                continue
        else:
            pattern = str((p.get("match") or {}).get("pattern", ""))
            fires = bool(re.search(pattern, text, re.IGNORECASE | re.MULTILINE))
        if fires:
            consider(
                str(p.get("action", "allow")),
                str(p.get("id", "")),
                str(p.get("message", "")),
            )

    return best


def policy_test(
    hook: str, role: str, text: str, *, project: str = "", call: ToolCallFacts | None = None
) -> str:
    """Dry-run the evaluator (no trace emission)."""
    return policy_eval_detail(role, hook, text, project=project, call=call).action


@dataclass
class PolicyInstallResult:
    """Outcome of :func:`install_policies` — one entry per shipped template, in template order.

    ``entries`` preserves the exact iteration order the caller renders in, so a UI layer can
    render an interleaved "installed: x / skip (exists): y" list matching that order, rather than
    two separately-sorted groups."""

    template_dir: Path
    policies_dir: Path
    entries: list[tuple[str, bool]] = field(default_factory=list)  # (filename, was_installed)

    @property
    def installed(self) -> list[str]:
        return [name for name, was_installed in self.entries if was_installed]

    @property
    def skipped(self) -> list[str]:
        return [name for name, was_installed in self.entries if not was_installed]


def install_policies() -> PolicyInstallResult:
    """Copy the baseline policy templates into ``$POLICIES_DIR`` (idempotent).

    An existing destination file is left untouched (skipped, never overwritten) — the same
    "install once, edit locally after that" contract ``docket setup`` keeps.
    Directory created 0700, each copied file 0600. Returns an empty ``entries`` list (not an
    error) when the template directory itself is missing; check ``template_dir.is_dir()`` first
    if that distinction matters to the caller. Pure logic, no UI: this is the shared producer
    behind the workstation foundation bootstrap's policy-provisioning step, so what "installed"
    means has one definition."""
    template_dir = _templates.POLICY_TEMPLATES_DIR
    result = PolicyInstallResult(
        template_dir=template_dir, policies_dir=current_home().policies_dir
    )
    if not template_dir.is_dir():
        return result

    current_home().policies_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(current_home().policies_dir, 0o700)

    for f in _glob_policy_files(template_dir):
        dest = current_home().policies_dir / f.name
        if dest.exists():
            result.entries.append((f.name, False))
        else:
            shutil.copy(f, dest)
            os.chmod(dest, 0o600)
            result.entries.append((f.name, True))

    return result
