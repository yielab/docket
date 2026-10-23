# Security Gates Specification

**Version**: 1.1.3
**Status**: Implemented. Every tool call a docket turn makes passes one gate (the command
classifier plus `pre_tool_call` policies); approvals live in one store answered over CLI, HTTP,
MCP and Telegram. The exec jail is opt-in and fails closed when on without a usable backend.
**Last Updated**: 2026-10-23

## Purpose

This specification defines docket's tool-approval, policy, workspace-isolation, sandbox and
network-egress contracts. One dispatcher, `dispatch_tool`, gates every tool call; the fleet record
(`fleet.json` `security`) holds the isolation, network and profile posture; docket's approval store
owns every grant and denial. There is no external enforcer and no bridge to one.

## Scope

This specification covers:

- The tool-call gate: the argument-aware command classifier, `pre_tool_call` policies, and what an
  `ask` verdict does (wait, park, or refuse)
- The approval store and its channels (CLI, HTTP, MCP, Telegram), the grant/deny race, expiry,
  single-use pre-grants and approval packs
- The high-risk action classes (`money-movement`, `prod-deploy`, `secret-access`) and every place
  they apply
- The guardrail policy engine: the `pre_input`, `pre_tool_call` and `pre_output` hooks, the policy
  document format, predicate plugins, pod policies and task restrictions
- File-tool containment and workspace isolation
- The exec jail (Landlock, Seatbelt, Docker) under `bash`, verify commands, `run:` steps, the
  prepare install and stdio MCP servers, and the honest report of whether a call ran in one
- Network egress: the `fetch` tool and the network lockdown mode
- Credentials kept out of task processes, protected paths and the reviewed digest, and the
  `lights-out` profile

This specification does NOT cover Telegram transport (telegram-integration.spec.md), which is one
approval channel among four; the dispatch state machine a gated task moves through
(`waiting_approval`, `resolve_waiting_approval`, pod-dispatch.spec.md); or the audit entry format
and chain (audit.spec.md).

## Requirements

### Tool-approval gates

1. A command whose binary is not on the curated allowlist (`SAFE_BINS`; `rm`, `dd`, `docker`,
   `systemctl` are off it) **MUST** require approval before it runs. The gate is `dispatch_tool`'s
   command classifier plus `pre_tool_call` policies, active on every tool call docket dispatches;
   nothing turns it off. `git` and `npm` are on the allowlist, so `git status` does not ask, but
   `classify_command` matches `HIGH_RISK_PATTERNS` against the whole command line before it
   consults `SAFE_BINS`, so `git push origin main` asks, and the `high-risk-deploy` `pre_tool_call`
   policy asks on the same call independently (see "High-risk action classes").
   - **Segments.** Every segment behind `;`, `&&`, `||` and `|` is classified. An unquoted,
     unescaped newline (`\n`, `\r\n`) **MUST** start a new segment exactly like `;`, since
     `/bin/sh` starts a new command there; a newline inside quotes stays text and a
     backslash-newline is a continuation.
   - **Builtins.** `cd`, `pwd`, `true`, `false`, `test`, `[` and `echo` are on `SAFE_BINS` and
     **MUST NOT** force approval merely because they lead a segment, so `cd <path> && git status`
     reads as `cd` (allowed) then `git status` (allowed). `export`, `source`, `.`, `eval` and
     `exec` stay off the allowlist because they change what a later segment resolves to. `pytest`
     and `python` are on it beside `python3`: the bare test runner runs the same code
     `python3 -m pytest` does.
   - **Redirects.** `echo` is redirect-sensitive: a bare `echo hi` is allowed, but `echo ... >`,
     `>>` or `&>` asks, naming the redirect (`output redirect to <target> is outside the
     workspace`, or `output redirect after cd cannot be placed`) and never the binary, because its
     argument is often model-composed text and a redirect turns that into an unattended
     arbitrary-path write. The exception is a redirect docket can place: `classify_command` takes
     the turn's `roots`, and when every output-redirect target of the segment resolves inside them
     the redirect is the `write` tool by another name (the file tools are confined to the same
     roots, and every role that may not write is denied `bash`) and **MUST** be allowed, for
     `echo` and for a pod's extra bins alike. Placement: a relative target resolves against
     `roots[0]` (the `bash` cwd), symlinks followed; an earlier `cd <literal path>` is followed; a
     `cd` with an expansion, `-` or no argument, any `pushd`/`popd`, a `cd` that is a pipeline
     element or backgrounded, or a command containing `(` or `||` stops placement (a pipe in a
     later segment does not); a target holding `$`, `~`, a glob or a brace, or an operator without
     a target, cannot be placed. A target written exactly `/dev/null` discards the output and
     **MUST** count as placed with or without roots, jailed or not (`ls x 2>/dev/null`); every jail
     grants it (`DEFAULT_RW_FILES`). Every output-redirect spelling counts: `>`, `>>`, `>|`, `&>`,
     `&>>` and `>&` to a path; `2>&1` copies a descriptor and opens nothing. Without roots
     (`docket pod check`, a `run:` step's classification) any other redirect by a
     redirect-sensitive binary asks.
   - **Heredocs.** A heredoc whose delimiter is quoted or backslashed (`<<'EOF'`, `<<"EOF"`,
     `<<\EOF`, and the `<<-` forms) carries stdin data, not commands: `classify_command` cuts the
     body and its closing delimiter line before the opaque-marker scan, the line split and binary
     classification, so a backtick, `${`, apostrophe or `=>` in the body asks nothing. The line
     carrying `<<` is classified as usual, `match_high_risk` still reads the full text including
     the body, an unquoted delimiter keeps its body classified (the shell expands it), a heredoc
     fed to a shell (`bash`, `sh`, `zsh`, `dash`, `ksh`, `source` or `.` as in `source /dev/stdin`,
     or a wrapper of one, anywhere on the carrying line) keeps its body classified as commands, and
     a quoted heredoc with no closing delimiter asks. Here-strings (`<<<`) are not heredocs.
   - **Wrappers and deleting flags.** A segment led by `env` (after its `VAR=value` and option
     arguments), `xargs` (after its options), `nice`, `nohup`, `timeout <duration>`, `time`,
     `command` or `stdbuf` is classified by the command it runs, recursively to a depth of eight
     (deeper, or options it cannot read, asks), so `env rm -rf x` and `echo x | xargs rm` ask
     exactly as `rm` does; a wrapper that runs nothing (`env`, `env FOO=1`, `xargs`, which echoes,
     `command -v x`) is allowed. `find` with `-delete`, `-exec`, `-execdir`, `-ok`, `-okdir`,
     `-fprint`, `-fprint0`, `-fprintf` or `-fls` asks, and so does an `awk` (`gawk`, `mawk`,
     `nawk`) program containing `system(`, a `|` or a `print`/`printf` redirect. These checks stand
     down inside a working jail, like the allowlist itself. They are not a containment boundary:
     without the jail an allowlisted interpreter (`python3`, `node`, `make`, `sed -i` and the like)
     can write or delete anything the operator can, and `tee`, `cp`, `mv`, `mkdir`, `touch` and
     `ln` stay allowed as ordinary development writes. The jail is the boundary.
   - **The dry run.** `docket pod check "<text>" --role <role>` evaluates an `exec` tool through
     `evaluate_tool_call`, the function `dispatch_tool` calls, never a second copy of the
     classifier and policy merge, with the pod's own policies and the pod's `allowCommands`
     (read as the live gate reads them: empty when the stored settings are unreadable) folded in.
     It runs without the turn's roots and the jail flag, so it reports the verdict of an unjailed
     call with no workspace.
   - **A pod's extra bins.** A pod **MAY** extend the allowlist for its own turns with
     `allowCommands` (`docket pod set allowCommands <bin>[,<bin>...]`, comma-separated exact
     basenames). `classify_command` takes them as `extra_bins` (default empty, which changes no
     verdict). An extra bin joins the `SAFE_BINS` membership check only: the opaque-marker check
     and the high-risk classes still read the full command line first, so `uv run tox && git push
     origin main` asks with `tox` and `uv` allowlisted. Every extra bin is redirect-sensitive, the
     rule `echo` gets, since docket cannot know whether a pod-supplied binary's argument is
     model-composed text. `PodSettings` refuses on write a value containing a path separator or
     shell metacharacter, the names `eval`, `exec`, `source`, `.` and `export`, and any name in a
     high-risk class's `bins` (`git`, `npm`), which stay governed by the classes alone; a name
     already on `SAFE_BINS` is redundant and dropped silently. Only the turn of an agent in that
     pod carries the setting (In-turn tool-call gate 13), and a `pre_tool_call` `block` or
     `require_approval` on the same binary still wins (In-turn tool-call gate 3).
   - **A repository may not allowlist a shell.** A repository's `.docket/` whose `allowCommands`
     names `sh`, `bash`, `zsh`, `dash`, `sudo`, `ssh`, `nc` or `socat` **MUST NOT** be applied,
     because a shell runs whatever follows it and the classifier never sees that: `docket init`
     refuses it (exit 2) before provisioning, `docket pod update` refuses it (exit 2), the HTTP
     apply route refuses it, and `docket run` warns and runs with the pod as it is. The operator's
     own `docket pod set allowCommands` is not subject to this.
   - **Inside the jail the allowlist stands down (ADR 0024).**
     `classify_command(command, extra_bins, roots, jailed=False)` takes `jailed`, which
     `evaluate_tool_call` sets when `ToolContext.sandbox == "auto"` (a turn whose isolation
     resolved to a real backend; a turn without one is refused before it starts, so this is the
     decision `run_bash` acts on). When `jailed`, a binary off `SAFE_BINS` and `extra_bins` is
     allowed instead of asking. Unchanged in both modes: the not-statically-analysable `ask`
     (command substitution, `eval`, `exec`, unparseable text), every high-risk class, the
     empty-command `deny`, and redirect containment (an output redirect whose targets do not all
     resolve inside `roots` or name `/dev/null` still asks, for every binary when jailed). Every
     host-side caller (dispatch's `run:` steps, `docket pod check`) leaves `jailed` false. Policies
     apply in both modes.
2. Approvals in docket's store **MUST** be answerable over a headless channel: the CLI
   (`docket task approve`, `docket task deny`), HTTP (`POST /approvals/<token>` under
   `docket start`), MCP (the `approvals_grant` and `approvals_deny` tools) and Telegram (a bound
   chat's `/approve` or `/deny`, answered by `docket start --telegram`'s poll loop with no
   interactive session). The `docket run` progress view's own prompt is a further CLI caller.
   Every caller makes the same grant or deny and then calls `resolve_waiting_approval`, so a
   decision **MUST** genuinely resume or fail the dispatch task it gated, not merely flip the
   record (pod-dispatch.spec.md). One approval implementation, several callers.
   A pending record **MUST** make its one terminal transition (`granted` or fail-closed `denied`)
   under the store's locked read-modify-write: concurrent decisions, the expiry sweep included,
   have exactly one winner. Only that winner emits the matching trace and audit event; a
   duplicate decision emits neither.
   The loser's error **MUST** say why it lost: an unknown or malformed token is `ApprovalError`
   (HTTP `404`); repeating the decision that already won (already granted, already denied,
   expired) is `ApprovalNoop` (HTTP `409`); the opposite decision on a resolved record
   (deny-after-grant, grant-after-deny) is `ApprovalConflict`, an `ApprovalError` subclass (so
   every `except ApprovalError` still catches it) carrying the winning state, whose message names
   that state (HTTP `409`, not the missing-token `404`). Every channel's caller reports which
   decision won from these exceptions, never a generic failure indistinguishable from an unknown
   token.
3. A gate with no approver **MUST** fail closed. An in-turn wait resolves to denied at its timeout
   (In-turn tool-call gate 5). A **pending** record in the store **MUST** resolve to **denied**
   once past its own `expiresAt` through `approval_sweep_expired`, which runs only while
   `docket start` is up. When that record gates a dispatch task, the resolution **MUST** also fail
   the waiting task terminally (`failureKind: "approval_denied"`).
4. Every grant and denial through docket's store **MUST** be recorded in the audit log
   (`approval.grant`, `approval.deny`), tagged with the channel it came through: `cli`, `http`,
   `mcp`, `telegram`, `tack` (an HTTP caller's own tag), `timeout` (the expiry sweep, or an
   in-turn wait that timed out), or `cancellation` (an in-turn wait that observed run
   cancellation). The HTTP route accepts only `http` and `tack` from its caller, so it cannot claim
   another surface's channel or the fail-closed `timeout`; `create_pregrant` accepts only the
   closed `APPROVAL_CHANNELS` set (`cli`, `http`, `mcp`, `telegram`, `timeout`, `tack`).
5. An in-turn tool approval's stored `action` **MUST** include the redacted rendered tool call in
   addition to the classifier or policy reason. Every approval channel reads this same record, so
   an operator **MUST** be able to tell, for example, project test execution from a shell call
   targeting private workspace state before deciding. The record **MUST NOT** store an unredacted
   secret, and the action is cut at 1,000 characters.

### Workspace isolation (opt-in)

1. File tools **MUST NOT** read or write outside the turn's roots (the agent's workspace and
   codebase, or the task worktree). `resolve_within` resolves every path argument and refuses one
   outside every root; a call with no roots refuses every path rather than defaulting to the
   whole filesystem. A `bash` command's text is not path-checked; only the jail contains it (Exec
   sandbox 3).
2. Path traversal out of the roots (`..`, an absolute path elsewhere, a symlink out) **MUST** be
   rejected with `PathEscapeError`; "File-tool containment" covers symlinks met during a walk.
3. Workspace isolation is **opt-in** (ADR 0021): a `DOCKET_HOME` with no recorded choice
   (`fleet.json` `security.isolationMode` unset) runs tools on the host, exactly as an explicit
   off does. `docket setup sandbox on` records on and succeeds only when `sandbox_availability()`
   finds a backend (otherwise it exits 1 and records nothing); `docket setup sandbox off` records
   an explicit off; both are audited (`gates.isolate`). `docket setup sandbox` and `docket setup`
   show `off (default)`, `on` or `off`. The requirement a host must meet to turn it on is one
   backend: Landlock (Linux 5.13+), Seatbelt (macOS), or a reachable docker daemon once the
   operator chose it. No backend is ever needed while isolation is off.
4. `sandbox_availability()` reads the fleet's `sandboxBackend` (`auto` by default, written by
   `docket setup sandbox backend auto|docker`, audited `gates.backend`). `auto` is landlock on
   Linux and seatbelt on macOS and nothing else; `docker` is docker only (a reachable daemon) and
   the only case docker is probed; a host with neither resolves to `none`.
   `DOCKET_SANDBOX_BACKEND` (`landlock`|`seatbelt`|`docker`|`none`) forces the choice. The jail
   mounts the git dir and common dir of every root that is inside a git repository or linked
   worktree read-write (landlock `--rw`, docker `-v`), so a jailed `git add` + `git commit`
   succeeds there while a write to a host path outside the roots fails. The docker jail is only as
   capable as `DOCKET_SANDBOX_IMAGE` (default `alpine:3.20`, for which docket ships no image): a
   jailed `git commit` needs an image with `git`, and python-based recipes need `python3`.
   `docket setup` probes the image once (`command -v git`) when docker is the backend in use and
   isolation is on, and warns with the fix.
   The repository's `hooks/` and `config`, the worktree's `config.worktree`, and
   `info/attributes` are re-bound read-only on top (docker `:ro`, a seatbelt deny rule), after the
   read-write mounts they shadow. Landlock cannot take a right from a sub-path of a granted root,
   so it grants the git dir's writable parts instead of the git dir: the common dir is read-only
   except its `objects` and the task branch's own ref directory (below), plus `objects`, `refs`
   and `logs` of each submodule git dir under `modules/`, and in a linked worktree the worktree's
   own git dir (`<common>/worktrees/<name>`, holding the index, `HEAD` and `logs`) is read-write.
   `hooks`, `config`, `info/attributes` and `packed-refs` are never writable there. Refs: the jail
   grants write only to `refs/heads/<branch-parent>/` and `logs/refs/heads/<branch-parent>/` of
   the common dir, where `<branch-parent>` is the parent directory of the task branch
   (`docket/<pod>/<task-id>`, so `docket/<pod>/`, which holds the ref and the lock file git creates
   beside it). The branch is read from the worktree git dir's `HEAD` at launch and accepted only
   when it is `refs/heads/docket/<pod>/<name>` and `<name>` equals the worktree git dir's own
   directory name; otherwise, and for any root that is not a linked task worktree, no ref is
   writable. So a jailed `git update-ref refs/heads/main`, a tag, or any branch outside
   `docket/<pod>/` fails; the sibling task branches of the same pod stay writable (accepted
   residue: Landlock cannot grant one file plus its lock). `packed-refs` is read-only: a git
   operation that must rewrite it (pack-refs, deleting a packed branch) fails inside the jail.
   Docker and seatbelt narrow the same way for a **linked worktree** root: the common dir's
   `refs`, `logs/refs` and `packed-refs` are overlaid read-only (an absent `packed-refs` is created
   empty first), then the task branch's ref and reflog directories are re-opened read-write after
   the overlays (a later `-v` bind in docker, a later `(allow file-read* file-write* ...)` rule in
   the seatbelt profile, where the last matching rule wins). A linked worktree that is not a task
   worktree reopens nothing. A **main checkout** root (a `.git` directory, which Landlock refuses
   and docker/seatbelt run in) keeps its refs writable, since it is the operator's own checkout and
   the agent commits on its branch. Two things stay writable under Landlock and are covered on the
   host instead: the root's `.git` file and the worktree git dir's `config.worktree`, `gitdir` and
   `commondir` (Exec sandbox 13). A root that holds a `.git` **directory** (a main checkout used in
   place) cannot be guarded by Landlock at all, since the directory is inside a writable root, so
   the Landlock jail refuses to run there: exit 125, the reason on stderr, nothing run. Use a git
   worktree as the root, or choose docker. A root below a main checkout's top (git dir outside the
   root) runs, but a commit there fails closed, because `index` and `HEAD` live at the top of that
   git dir. The same read-only rules apply, only when present, to every submodule git dir under
   `modules/` of the git dir and common dir (any depth, found by walking for a directory holding
   `HEAD`, never by running git): its `hooks`, `config`, `config.worktree` and
   `info/attributes`, plus the submodule checkout's `.git` file (located through the `worktree`
   line of that config). Under docker and seatbelt, in a linked worktree the root's `.git` file
   and the admin files `<common>/worktrees/<name>/gitdir` and `commondir` are read-only too, so the
   jail cannot repoint the host's next git command at a directory it controls. Objects, refs,
   index, logs and `HEAD` stay writable. A `hooks/` directory or `info/attributes` file missing
   when the jail starts is created empty on the host first and then bound read-only, so the jail
   cannot create it. A submodule added inside the jail after it starts is not covered; the jail is
   built once per call.

### Enablement

1. The tool-call gate (the policy engine plus the argument-aware command classifier) **MUST** be
   active on every tool call docket dispatches. There is nothing to enable, and `docket init` has
   no option that skips it.
2. There is no approval-routing setting. An `ask` verdict always sits in docket's own approval
   store, where the CLI, HTTP, MCP and Telegram channels answer it identically. `docket setup
   sandbox` with any verb other than `status`, `on`, `off`, `backend`, `network`, `classes` or
   `read` **MUST** be a usage error (exit 2), and an unrecognised flag (e.g. `--force`) **MUST**
   exit 2. Bare `docket setup sandbox` is a read and exits 0.
3. There **MUST** be a way to verify gate status: `docket setup` (`--json`:
   `securityGates.toolCallGate` is `"always-on"`) and `docket setup sandbox` (`--json`: `gate` is
   `"always active"`) report the gate as always active, plus the isolation posture.

### High-risk action classes

1. `HIGH_RISK_PATTERNS` **MUST** be a small, built-in, named list of high-risk action classes:
   `money-movement`, `prod-deploy` and `secret-access`. Each class's pattern **MUST** be matched,
   case-insensitively, against the full command string (`"git push origin production"`), not
   just the invoked binary name. It is a small seed, not exhaustive coverage, and it is not
   configurable.
2. On every path docket controls, a high-risk match **MUST** take effect regardless of whether the
   invoked binary is on the curated allowlist; allowlist membership **MUST NOT** bypass a match.
   `classify_command` checks the classes before the allowlist, and `run_command` refuses a match
   outright (a stronger outcome than `ask`).
3. **Money-movement** and **secret-access** **MUST** be treated as fully enforced: none of their
   named bins (`stripe`, `paypal`, `ssh-keygen`, `vault`, ...) is on `SAFE_BINS`, so
   `classify_command` routes any matching invocation to `ask`.
4. **Prod-deploy** **MUST** be described as fully enforced too. Two of its bins (`git`, `npm`) are
   on the allowlist, but every tool call of every turn passes `dispatch_tool`, which classifies a
   `bash` call's full command line with `classify_command` (telling `git push origin main` from
   `git status` by argument, not binary) and separately evaluates the `high-risk-deploy`
   `pre_tool_call` template. Both are argument-aware and both apply to every call.
5. The full high-risk class list (name, description, pattern, and which allowlisted bins a class
   overlaps, which the classifier's argument-awareness still gates) **MUST** be visible, read-only,
   via `docket setup sandbox classes`. This command **MUST NOT** change any configuration.

### Docket-launched process classification

`match_high_risk` is the classifier's one entry point outside `classify_command`. This section is
where it applies to commands docket itself launches.

1. **Scope: which of docket's own subprocess calls are classification targets.** Exactly one
   docket function runs a free-form, operator-composed command string through a shell:
   `run_command`, used for a member's
   `verifyCmd`, a pipeline's `run:` steps and a task's prepare install command. On the host it is
   the one `shell=True` call docket makes; in a jail it is `/bin/sh -c` inside the jail. Every
   other subprocess call builds a fixed argv itself (a `docker info` probe, a
   `git -C <dir> rev-parse ...` plumbing call, a `--version` probe) and carries no classifiable
   command string. `run_command` **MUST** therefore be the one classification point among
   docket's own subprocess calls; the fixed-argv calls are out of scope by design, not overlooked.
2. `run_command` **MUST** classify its command against `match_high_risk` before any subprocess
   starts. A match **MUST** fail closed (the shell command **MUST NOT** be started at all) and the
   returned message **MUST** name the matched class and point at `docket setup sandbox classes`.
   Refusing outright is the only honest posture here: the command runs synchronously inside a
   dispatch hop with no interactive approver reachable, the same fail-closed rule
   `TOOL_APPROVAL_TIMEOUT` and `approval_sweep_expired` apply when nobody answers. A `run:` step
   is also classified with `classify_command` (with the pod's `allowCommands`) before it runs; a
   non-`allow` verdict gates it like an approval step (pod-dispatch.spec.md).
3. The `pre_output` guardrail scan (Policy engine 3) **MUST** also classify each hop's real output
   against `match_high_risk`, independently of the policy engine. It inspects what a hop *reports
   having run*, which can name a command that never reached `dispatch_tool` as a distinct call
   (one embedded in free text), so it is a second, independent signal beside the in-turn gate.
4. A `HIGH_RISK_PATTERNS` match on a hop's output **MUST NOT** downgrade an already-stronger
   `policy_eval_detail` verdict (`redact`, `block` and `require_approval` all outrank a bare
   `allow`); it **MUST** only raise a plain `allow` to `warn`. It **MUST NOT** go further than
   `warn`: there is no live approver to ask after the fact (the hop has already run, the reasoning
   behind `pre_output`'s require_approval-behaves-like-warn rule), and `HIGH_RISK_PATTERNS` is a
   built-in list, not an operator-authored policy, so a match here **MUST NOT** be described as
   redacting or blocking anything by itself. It is a visibility signal (a `guardrail_check` trace
   event whose policy is `high-risk:<class-name>`), not an enforcement action, and **MUST NOT** be
   claimed as one in user-facing material.
5. **Additive, not the gate.** The two classification points above (`run_command`'s refusal, the
   `pre_output` scan) add to the in-turn gate; they are not where a hop's tool calls are gated.
   `dispatch_tool`'s classifier and the `high-risk-deploy` `pre_tool_call` template gate every
   call before it runs.

### Policy engine on the live path

1. `docket init` **MUST** install the baseline policy templates into `$POLICIES_DIR` whenever it
   provisions (idempotent: an existing file is left untouched, never overwritten), through the same
   producer `docket setup` uses (`install_policies`). An empty `$POLICIES_DIR` makes every hook
   evaluation `allow`, so this step is what makes the rest of this section possible.
2. The `pre_input` hook **MUST** be evaluated exactly once per task, when the task is enqueued
   (`enqueue_task_once`), against the task's raw description, with role `"lead"` (the pipeline's fixed
   entry point). It **MUST NOT** be re-evaluated before every hop: doing so would re-trip the same
   `"*"`-scoped policy at every role for one piece of incoming text. An operator's task is trusted
   by default (the `prompt-injection` policy is skipped for it); `POST /tasks` may set `trusted`.
   - `block` **MUST** reject the task before it is written to the pod's queue (`DispatchError`
     `task rejected by guardrail policy '<id>' at enqueue[: <message>]`; nothing persisted) and
     **MUST** close out a self-contained trace session (`session_start` → `guardrail_check` →
     `guardrail_block` → `session_end`, status `aborted`): a rejected task is never dispatched, so
     nothing else would ever terminate that trace file.
   - `require_approval` **MUST** persist the task straight into `waiting_approval` with a real
     approval record (`context: {"taskId", "pipelineIndex": 0}`), resolved like the pod's own
     pre-hop gate (grant → `pending` plus a hop-0 gate override; deny → terminal
     `failureKind: "approval_denied"`).
   - `redact` **MUST** scrub the stored task description (`redact`) before it is persisted.
   - `warn` and `allow` **MUST NOT** change task status or the stored description; `warn` **MUST**
     still emit a `guardrail_check` trace event.
3. The `pre_output` hook **MUST** be evaluated on **every** hop's real output, after the agent
   turn returns and before that output is embedded in the carried-forward `HandoffArtifact` or the
   persisted hop result.
   - `redact` **MUST** scrub the hop's output in place before it is stored or handed on.
   - `block` **MUST** fail the hop the way a failed agent turn does (the pipeline stops there;
     later hops **MUST NOT** run).
   - `warn` and `allow` **MUST** pass the output through unchanged.
   - `require_approval` is not a `pre_output` outcome: the hop has already run, so there is no
     "before" moment left to gate; an operator who wants a human before a role runs uses a pipeline
     `approval` gate or the `pre_input` enqueue gate. A `pre_output` policy declaring
     `require_approval` **MUST** behave exactly like `warn` (logged, not gated).
   - The same evaluation **MUST** classify the hop's output against `match_high_risk`
     (Docket-launched process classification 3-4).
4. Every non-`allow` verdict on either hook **MUST** emit a `guardrail_check` trace event
   (`payload: {hook, policy, action}`), visible through `docket task trace`. A `block` verdict
   **MUST** additionally emit `guardrail_block` with the same payload: `policy` is the tripped
   policy's id and `action` is the verdict (`"block"`). The HTTP `/metrics` counter
   `docket_policy_hits_total` tallies `guardrail_check` events (by policy, hook and action) and the
   gate's `tool.*` audit entries; it does not read `guardrail_block`, so a block is counted once.
5. `pre_tool_call` **MUST NOT** be evaluated by the dispatch flow between hops: `enqueue_task_once` and
   `dispatch_task` orchestrate hops and stay outside every tool call made during a turn.
   `pre_tool_call` fires inside the turn, in `dispatch_tool` ("In-turn tool-call gate").
6. `docket pod validate [PATH]` **MUST** check policies through the one config validator, with
   `validate_policy` as the policy check: required fields, a valid hook and action, a compilable
   pattern. A policy file, or a directory whose `policies/` holds them (`$DOCKET_HOME` checks the
   installed set), is the argument. Exit code `1` if any checked file is invalid.
7. **A broken policy fails closed.** One validator owns policy validity, and the evaluator applies
   the same check on every read: a policy file that cannot be parsed, or that fails validation
   (missing required fields, unknown hook or action, a `match.type` other than `regex`, an empty
   or uncompilable pattern), **MUST NOT** be silently skipped. It **MUST** evaluate as a `block`
   verdict, scoped to the file's declared `hook` and `applies_to` when that much is readable and to
   every hook and role when the document itself is unreadable, with `PolicyHit.policy_id` naming
   the broken file and `message` naming the reason, so the existing non-`allow` audit and trace
   paths attribute the denial to the file. The trusted-input skip of the `prompt-injection` policy
   applies only when the file's `id` is readable and matches; brokenness never widens it.
   `docket setup` **MUST** report each broken policy file as an issue.
8. `docket pod check "<text>" --role <role> [--hook <hook>]` **MUST** accept `--tool <name>`
   (default `bash`; `--hook` defaults to `pre_tool_call` and an unknown hook is a usage error,
   exit 2). At `pre_tool_call` the name is resolved against the built-in tool registry (unknown →
   usage error, exit 2, naming the valid tools); an `exec`-kind tool evaluates through
   `evaluate_tool_call` (classifier plus policy hook, Tool-approval gates 1), and any other kind
   evaluates the declarative hook alone on the given text, reporting that the command classifier
   does not apply, because the live gate classifies `exec` tools only. Another hook evaluates the
   policies alone.
9. **A pod has its own policies, and they only add.** `policy_files`, `policy_eval`,
   `policy_eval_detail` and `policy_test` **MUST** accept a `project` parameter (default `""`).
   When set, the files in that pod's own policy directory (the pod's `config/policies/`) **MUST**
   join the global `$POLICIES_DIR` set in the same most-restrictive-wins evaluation; concatenation
   is the whole mechanism, since the winner is decided by rank, not read order. A pod file
   **MUST NOT** be able to override a global `block` or `require_approval`: it can only add a more
   restrictive verdict, or agree. `project=""` **MUST** see the global set only. A pod policy file
   that fails validation **MUST** fail closed through requirement 7, attributed to that file.
   `docket pod policies` and `docket pod check` **MUST** resolve the pod as every pod command does
   (`--pod <p>`, `DOCKET_POD`, the pod whose codebase contains the cwd) and fold that pod's
   directory in; outside any pod they see the global set only. Callers that pass the pod: the
   in-turn gate (In-turn tool-call gate 4), the screening of `fetch`, MCP and gate-reason text,
   instruction and memory screening, the enqueue-time `pre_input` gate (requirement 2), the
   `pre_output` scan (requirement 3), a Telegram `/delegate` description, an approval's rationale
   and grant or deny reason (the pod of the approval record), and an answer's content. Every
   screen that judges text on a pod's behalf **MUST** pass that pod.

### Policy format v1 (ADR 0010)

A policy document is canonical JSON (`applies_to`, `hook`, `match.type: regex`, `action:
require_approval`) or the short form below, and a policy can test structured facts of a tool call
beside its rendered text.

1. `policy_files` **MUST** glob `*.json`, `*.yaml` and `*.yml` in every policy directory it reads
   (the global `$POLICIES_DIR`, then a pod's own `config/policies/`), each directory sorted by name
   across all three extensions together. `install_policies` **MUST** copy a shipped template
   whatever its extension.
2. `normalize_policy(short: dict) -> dict` **MUST** be a pure function mapping a short-form document
   to the canonical shape `{id, applies_to, hook, match, action, message}`, plus an optional
   structured `when` (requirement 4). A top-level `kind: policy` **MUST** be accepted and
   stripped; any other `kind` value **MUST** be refused, naming the expected one. `name` maps to
   `id`; `appliesTo` to `applies_to`; `on: input|toolCall|output` to `hook` (`pre_input`,
   `pre_tool_call`, `pre_output`), defaulting to `pre_tool_call` when neither `on` nor `hook` is
   given; `then: allow|warn|ask|block|redact` to `action`, with `ask` mapping to
   `require_approval` and the rest to themselves. A document already in canonical form **MUST**
   come back unchanged but for a `kind` key. Loading **MUST** disable YAML's implicit
   `on`/`off`/`yes`/`no` boolean resolution for a policy document, since the short form's own `on:`
   key would otherwise parse as the boolean `True` on a bare value, and no policy field is ever a
   boolean.
3. `read_policy(path) -> dict` **MUST** be the single reader that `validate_policy`, the
   evaluator's per-file loop, `docket pod policies` and `docket pod validate` share: it parses the
   file as YAML (JSON stays valid YAML, so a canonical file needs no change) and returns
   `normalize_policy` of the result.
4. A canonical policy **MAY** carry a structured `when` mapping instead of, or beside, `match`:
   `{tool?, path?, matches?, branch?, plugin?, anyOf?: [...]}`. Keys are implicit AND; `anyOf` is
   OR over its items, itself AND'd with any sibling keys. `tool` **MUST** equal the call's tool
   name; `path` **MUST** be an `fnmatch` glob over whichever of the call's `path`, `file_path` or
   `file` arguments is present (absent on the call, the predicate never matches); `matches`
   **MUST** be the same regex-over-rendered-text test `match.pattern` is; `branch` **MUST** be an
   `fnmatch` glob over the worktree's current branch; `plugin` is "Predicate plugins". A `when`
   whose only key is `matches` **MUST** normalize to plain `match: {type: regex, pattern: ...}`,
   so a plain regex policy's canonical form is byte-identical whether written short or long. The
   validator **MUST** check `when` the way it checks `match`: a policy **MUST** carry a `match` or
   a `when` (a document with neither has nothing to fire on); an unknown `when` key **MUST** be
   rejected naming the predicates; an uncompilable `when.matches` **MUST** be rejected as an
   uncompilable `match.pattern` is; a `when.anyOf` that is not a non-empty list **MUST** be
   rejected.
5. `ToolCallFacts(tool, args, branch_of, worktree_root="")` **MUST** carry what a `when` predicate
   can test beside the hook's rendered text: the call's tool name, its raw arguments, a
   zero-argument `branch_of` getter, and the worktree root a plugin receives. `policy_eval_detail`,
   `policy_eval` and `policy_test` **MUST** accept a `call: ToolCallFacts | None = None` keyword.
   `branch_of` **MUST** be invoked at most once per `policy_eval_detail` call, and only when a
   loaded policy's `branch` predicate is actually evaluated, so a call against a codebase with no
   such policy **MUST NOT** shell out to read the branch. A `tool`, `path` or `branch` predicate
   **MUST NOT** match when `call` is `None` (the text-only hooks `pre_input` and `pre_output`, and
   a non-`exec` dry run with no `--arg`); `matches` **MUST** still evaluate against the rendered
   text regardless of `call`.
6. `evaluate_tool_call` **MUST** build one `ToolCallFacts` per call: `tool` and `args` from the
   call being evaluated, `branch_of` a lazy read of the current branch of `roots[0]` (`""` with no
   roots), `worktree_root` `roots[0]` (`""` with none), and pass it as `policy_eval_detail`'s
   `call`.
7. `docket pod check "<text>" --role <role>` **MUST** accept repeatable `--arg key=value` flags
   building a `ToolCallFacts` (`branch_of` always `""` in a dry run, since there is no worktree to
   read one from) for the `pre_tool_call` hook, on both the `exec`-kind path
   (`evaluate_tool_call`, `args = {"command": text, **call_args}`) and the declarative-only path
   (`policy_eval_detail(..., call=...)`), so `docket pod check "" --role implementer --tool write
   --arg path=.github/x.yml` reports the verdict a `when.path` predicate on `write` would give a
   live call, with an empty `<text>` accepted (a predicate-only test has no rendered text). A
   malformed `--arg` is a usage error (exit 2).
8. Every shipped policy template **MUST** be short-form YAML, installed under its own file name
   (`block-destructive.yaml`), with the id, pattern, applies-to, action and message its policy
   suite pins.

### Predicate plugins (ADR 0010)

A closed predicate vocabulary cannot express a rule that needs project knowledge ("ask when a
migration file is touched outside the tree of the app that owns it" has no path but a fragile
regex). The `plugin` predicate calls operator-applied Python instead of an expression language,
under the trust boundary a policy's place demands: a policy runs inside the gate on every tool
call the agent makes, so a plugin loaded from the codebase the agent edits would let the agent
rewrite its own gate for the next turn.

1. `docket.plugins` **MUST** be the only module a plugin file imports for the API: it carries
   `PLUGIN_API_VERSION`, the `@predicate(name)` decorator, and the frozen
   `ToolCall(tool, args, rendered)` and `PolicyContext(role, project, branch, worktree_root)`
   types a predicate receives. It **MUST NOT** import anything else from docket, since a plugin
   is operator code loaded by convention, not part of the policy engine.
2. The plugin loader's `discover(project: str = "") -> dict[str, LoadedPredicate]` **MUST** search
   only `$PLUGINS_DIR` (global, default `$DOCKET_HOME/plugins`) and, when *project* is given, that
   pod's own `config/plugins/`, **never** a codebase path. Each `*.py` file **MUST** be imported
   from its file location, draining `docket.plugins.REGISTRY` after each file; a duplicate
   predicate name across files **MUST** raise `PluginError` naming both files. A cache keyed by a
   file's `(mtime_ns, size)` **MUST** skip re-importing an unchanged file, so a live turn does not
   re-import on every call.
3. The loader's `evaluate(pred, call, ctx, with_, *, budget_ms=250) -> tuple[bool, str]` **MUST**
   never raise: a predicate that raises, returns a non-`bool`, or exceeds *budget_ms* (wall clock
   measured around the call; Python cannot pre-empt a running predicate, so the budget denies only
   after the fact) **MUST** return `(False, <reason>)` naming what went wrong; a normal `bool`
   return **MUST** carry `reason=""`. Every call **MUST** write one `policy.plugin` audit entry
   naming the predicate, its scope, its sha256 and the resulting `verdict` (`allow` or `deny`).
4. A canonical policy's `when` **MAY** carry `plugin: <name>` with an optional `with: <mapping>`,
   validated like the other predicate keys (`when.plugin` **MUST** be a non-empty string;
   `when.with`, when present, **MUST** be a mapping and **MUST NOT** appear without
   `when.plugin`; the unknown-key error names all five predicates).
5. The policy evaluator **MUST** resolve `discover(project)` for a `plugin` predicate and evaluate
   the named entry. An unknown name, or any `PluginError` from `discover`, **MUST** fail the whole
   policy closed as `block`, naming the plugin and the two scopes searched, regardless of the
   policy's own `then:`; a policy that names a plugin nobody applied **MUST NOT** ever silently
   allow. A plugin that `evaluate` denies with a non-empty reason **MUST** likewise fail the policy
   closed as `block`, naming the reason; a plugin `evaluate` returns `(False, "")` for **MUST** be
   an ordinary non-match (the predicate did not fire), never a failure. This fail-closed behaviour
   **MUST** win wherever the `plugin` key appears in the predicate tree, including inside `anyOf`,
   so it cannot be neutralized by an always-true sibling.
6. `evaluate_tool_call` **MUST** pass its `ToolCallFacts.worktree_root` (`roots[0]` when the call
   has roots, else `""`) through to a plugin's `PolicyContext.worktree_root` unchanged.
7. `docket pod policies --plugins [--pod <p>]` **MUST** print every predicate `discover` returns
   for that scope (name, scope, file, sha256), global first, then the pod's own; `"No plugins
   applied."` when empty. A predicate present only under a codebase's own `.docket/plugins/`
   **MUST NOT** appear: only `$PLUGINS_DIR` and a pod's own directory are ever searched.
8. `docket pod update` **MUST** copy a recipe's `plugins/*.py` into that pod's own
   `config/plugins/`, by sha256 (an installed copy with the same hash is left alone, any other
   content is replaced), the same by-hash copy it gives policies. A later edit to the codebase's
   own copy **MUST** change nothing until the operator applies again.

### In-turn tool-call gate

`dispatch_tool` is the only path to a tool's handler. Every docket turn
(`DocketDriver.run_turn` → `run_agent_turn`) dispatches every tool call through it, so every
`pre_tool_call` policy and the command classifier apply to every call a pod-dispatch hop makes.

1. **Rendering a call for the policy engine.** `render_tool_call(name, args)` renders one tool call
   as `"<name> <key>=<json-value> <key>=<json-value> ..."`, keys in the call's own argument order,
   each value `json.dumps`-encoded. This shape **MUST** be treated as a contract: every shipped
   `pre_tool_call` pattern is matched against it.
   The shipped `block-destructive` template's `.env` and `.ssh/` alternatives match a write
   *target*, not two words anywhere in the call (a `bash` render escapes newlines, so `.*` between
   a verb and a path would span a whole script): a redirect (`>`, `>>`) whose path ends in `.env`;
   `tee`, `cp`, `mv` or `sed -i` with a path argument ending in `.env` in the same command
   segment; `.ssh/` after the same verbs or a redirect; and `^(write|edit) path="...(.env|.ssh/...)"`.
   `grep -r process.env src/`, and a script that merely contains `.write(` and `process.env`, do
   not fire.
2. `evaluate_tool_call` **MUST** be the single point that consults
   `policy_eval_detail(ctx.role, "pre_tool_call", render_tool_call(tool.name, args), ...)`,
   beside the command classifier; no second call site may gate a tool call. A policy `action`
   **MUST** map onto the tool `Decision` vocabulary: `block` → `deny`, `require_approval` → `ask`,
   `warn`/`redact`/`allow` → `allow`. A `warn` or `redact` hit **MUST NOT** pass unrecorded: it
   **MUST** still write an audit entry (`tool.warn`, `tool.redact`) even though the call proceeds.
3. The command classifier's verdict and the policy engine's verdict **MUST** be combined
   most-restrictive-wins (`deny` > `ask` > `allow`), the ranking the engine itself uses between
   competing policies. Either side alone can decide: a `block-destructive` `require_approval` on
   an otherwise-allowlisted `write` call binds exactly as a classifier `ask` on an unmatched `bash`
   command does. One exception: an `ask` on the `consult` built-in **MUST** resolve to `allow`
   (the verdict keeps the raw `policy_id` and `policy_action`), because the consultation is itself
   the human's decision and asking approval to ask would put one decision to the operator twice.
   A `deny` on `consult` still denies.
4. `ToolContext` **MUST** carry `role` and `project` (both default `""`), feeding
   `policy_eval_detail`'s `applies_to` matching and the approval record. Every shipped template
   uses `applies_to: ["*"]`, which **MUST** match an empty role, so a bare `ToolContext()` is not
   exempt from any installed policy. `project` also selects which pod's own policy directory joins
   the call's evaluation (Policy engine 9): `evaluate_tool_call` **MUST** pass
   `project=ctx.project`. `DocketDriver.run_turn` **MUST** resolve `project` as the dispatch hop's
   own trace project when it has one, else the calling agent's pod, else the agent id, so a
   standalone pod-member turn sees its pod's policies and a non-pod agent sees the global set.
5. An `ask` verdict (with `approval_mode="wait"`, requirement 11) **MUST** block the call
   synchronously on the real approval store: `dispatch_tool` calls `approval_create` (project
   `"operator"` and role `"tool"` when the context has none; `context: {"tool", "callId",
   "argsDigest"}`) and then `wait_for_approval`, which **MUST NOT** return until the record is
   granted, denied, or its own timeout elapses.
   - The timeout is `TOOL_APPROVAL_TIMEOUT` (default 120 s) unless the hop supplies its own
     approval timeout. It is a separate, shorter knob than `APPROVAL_TIMEOUT` (900 s), which bounds
     a record's life in the store: a task sitting in `waiting_approval` costs only wall clock,
     while an in-turn wait blocks a live call, the model's turn and, under `docket start`, a worker
     slot. So it stays well under a hop's default timeout (300 s), leaving room for the tool to run
     after a grant.
   - The wait **MUST** poll, not busy-spin (`TOOL_APPROVAL_POLL_INTERVAL_S`, default 2 s).
   - A timeout **MUST** resolve the record to **denied** through the same fail-closed resolution
     `approval_sweep_expired` uses, never leaving it `pending`.
   - Granted: the call proceeds to the handler. Denied (explicitly, or by timeout): the handler
     **MUST NOT** run.
6. Every non-`allow` gate decision, and every `warn` or `redact` policy hit, **MUST** be audited
   (`tool.deny`, `tool.ask`, `tool.warn`, `tool.redact`) naming the tool, agent, role, project,
   `policy_id` and `policy_action`, with the rendered call passed through `redact` first, since a
   call's arguments can carry a secret (an API key in a `write`, a credential in a `bash`
   command). Approval resolution (grant, explicit deny, or timeout deny) is recorded by the
   store's own `approval.grant` and `approval.deny` entries, so a fully gated call leaves both the
   gate's decision and its resolution in `docket log`.
7. Every denied, non-executed `ToolResult` **MUST** carry exactly one closed, privacy-safe denial
   kind: `invalid_call` for an unknown tool, undecodable arguments or missing required arguments;
   `gate_denied` for a classifier or policy denial; `approval_denied` for an explicit operator
   denial; `approval_timeout` for an unanswered approval that timed out; `approval_unavailable`
   for an `ask` refused under `approval_mode="refuse"` (requirement 11) or a consultation nobody
   can answer; `approval_parked` for a parked call ("Parked calls and single-use pre-grants") or
   a parked consultation; and `run_cancelled` for a cancellation before execution (requirement 9).
   A result that executes, including an allowed handler failure, **MUST** carry no denial kind.
   `as_tool_output()` **MUST** include the denial kind in the model-visible refusal
   (`REFUSED [<kind>]: <reason>`) without raw arguments, approval tokens or private values.
8. **Scope.** This section governs `dispatch_tool`. Every pod-dispatch hop resolves the default
   driver (`DocketDriver`), whose `run_turn` runs the agent loop, which dispatches every tool call
   through `dispatch_tool`; there is no other execution path for a tool call. A pod-dispatch hop is
   therefore gated by `pre_tool_call` and the command classifier on every call.
9. **Cooperative run cancellation.** `ToolContext` carries an optional
   `cancellation_check: Callable[[], bool]`, supplied only by an owned run. `dispatch_tool` checks
   it before the approval continuation and immediately before the handler. Cancellation before
   execution returns a denied, non-executed result with `denial_kind="run_cancelled"`; the
   model-visible form is exactly `REFUSED [run_cancelled]: run cancellation requested before
   execution` and contains no token, arguments or private value. A caller without the callback is
   unaffected.
10. A cancellation observed while an in-turn approval is pending **MUST** conditionally deny that
    record through the locked transition (channel `cancellation`). A concurrent grant or deny
    remains the winner if it committed first, but cancellation after a granted wait still prevents
    the handler. Cancellation is not an approval timeout and **MUST NOT** fabricate a second
    terminal decision, audit event or trace event.
11. **Approval modes.** `ToolContext.approval_mode` is `Literal["wait", "park", "refuse"]`,
    default `"wait"`. Under `"wait"` an `ask` waits (requirement 5). Under `"park"` it is parked
    ("Parked calls and single-use pre-grants"). Under `"refuse"`, an `ask` **MUST** still be
    audited through `tool.ask` exactly as `"wait"` audits it, **MUST NOT** create an approval
    record or call `wait_for_approval` at all (zero wait, not a zero-length one), and **MUST**
    return immediately with `decision="deny"`, `denial_kind="approval_unavailable"` and `reason`
    equal to the verdict's own reason. A matching pre-grant is consumed before any mode applies.
    `ToolResult.policy_id` is copied from the verdict's `policy_id` whenever its decision is not
    `allow`, in every mode; it stays `""` for an `allow` and for a structural refusal that never
    reached a verdict (`invalid_call`). The mode answers "can this caller wait for a human", not
    "let a human answer from somewhere else".
    - **Where the mode comes from.** Dispatch resolves each hop's mode: the pod's own
      `approvalMode` (`wait`, `park` or `refuse`) when the pod sets one, otherwise the caller's
      default (`park` for `docket start --dispatch` and a dispatch without a terminal, `wait` for
      a foreground dispatch on a terminal). A `park` or `refuse` mode reaches the driver as the
      internal `DOCKET_APPROVAL_MODE` key of `run_turn`'s `env`, which `DocketDriver` pops into
      this field; it is never read from the process environment, so exporting it does nothing.
      An unset or unrecognised value is `wait` (pod-dispatch.spec.md, "Unattended approval
      posture").
12. **Cancellation reaches an in-flight `bash` command.** The `bash` tool passes
    `ctx.cancellation_check` to `run_bash`'s optional `cancelled` parameter. Given one, `run_bash`
    waits in a short bounded poll instead of blocking for the whole timeout; a true callback
    **MUST** kill the running command exactly the way a timeout does (`docker_kill` under the
    docker backend, then the process-group kill) and **MUST** return a complete
    `ToolOutcome(ok=False, error="cancelled before completion")` carrying the same sandbox tag every
    other `bash` failure does. Every other handler (`read`, `write`, `edit`, `glob`, `grep`,
    `fetch`, an MCP-adapted tool) runs to completion once started (D-30), as does an HTTP request
    or Python call made from inside the shell command. A caller that passes no `cancelled` (the
    default) **MUST** see the uncancellable behaviour, including the timeout message.
13. **A pod's `allowCommands` reaches the live gate through `ToolContext`, never read inside the
    gate.** `ToolContext` carries `allow_commands: tuple[str, ...] = ()`; `evaluate_tool_call` is
    its one consumer, passing `classify_command(command, extra_bins=frozenset(ctx.allow_commands),
    ...)` for an `exec` tool. `DocketDriver.run_turn` fills it once per turn from the calling
    agent's pod's `PodSettings.allow_commands`, the value `docket pod show`, `docket pod set` and
    `docket pod unset` read and write, so there is one reader and one writer. A non-pod agent, or a
    pod whose stored settings fail `PodSettings` validation for any reason, **MUST** resolve to an
    empty tuple (fail closed to the plain `SAFE_BINS` allowlist) rather than raise out of
    `run_turn` or grant anything wider. An agent in one pod **MUST NOT** observe another pod's
    `allowCommands`.
14. **Every refusal inside a handler is audited as `tool.refused`.** A file tool's
    `PathEscapeError` and a `fetch` allowlist refusal are returned by the handler as a failed
    `ToolOutcome`, so the gate verdict never saw them. `ToolOutcome` carries a typed `refusal`
    (`""`, `path_escape` or `fetch_not_allowed`); `dispatch_tool` **MUST** write exactly one
    `tool.refused` audit entry for an outcome whose `refusal` is set, naming `tool`, `agent`,
    `role`, `project`, `kind` and, for a path tool, the attempted `path` argument (for `fetch`,
    the host). The entry **MUST NOT** carry any file content, command output or URL query, and the
    free text passes through the redactor. An allowed call and an ordinary failure (file not
    found, HTTP error) **MUST NOT** write one. The classifier's containment branch needs no entry
    here: it returns `ask` or `deny`, which `tool.ask` and `tool.deny` already record.

### File-tool containment — symlinks

The file tools `read`, `write`, `edit`, `glob` and `grep` are in-process path checks that **MUST
NOT** be circumvented by symlinks. Symlinks met during a walk (`glob` and `grep`) that resolve
outside the allowed roots **MUST** be skipped, not followed; `write` and `edit` with a
final-component symlink target **MUST** refuse if that symlink points outside.

1. **`glob` and `grep` skip symlink escapes.** When walking a root with a glob pattern, a matched
   path whose resolved form (after following symlinks) is outside the allowed roots **MUST** be
   skipped: the path never reaches the caller (no path in `glob`'s output, no match lines from it
   in `grep`'s). `resolve_within` checks the path argument itself; this covers a symlink met
   *during* the walk, whether it is the matched file or a directory on its path (`linkdir/*` where
   `linkdir` points outside). The same check stops a `..` in the pattern itself
   (`../*/workspaces/...`).
2. **Symlinks pointing inside the roots keep working.** `./link -> ./target` and
   `./link -> ../codebase/target` both remain valid as long as the resolved path is within some
   allowed root. The containment check **MUST** check only the resolved path, not the symlink
   itself.
3. **`write` and `edit` refuse to write through a final-component symlink to outside.** They
   resolve the path through `resolve_within`; if it points outside the roots, they fail with
   `PathEscapeError`.

### Exec sandbox for the `bash` tool (opt-in)

The tool-call gate decides whether a `bash` call may run at all; it is not a sandbox.
`resolve_within` checks only the path *arguments* file tools are given, never a `bash` command's
shell text. Once a command clears the gate, this section constrains what it can reach while it
runs: additive to the gate and to `resolve_within`, never a replacement for either.

1. **Backend detection is real, not assumed.** `sandbox_availability()` probes, on every call,
   which backend the host has *right now*:
   - **`landlock`**: the Linux kernel's own sandbox (`python -m docket.jail`, requirement 10).
     Requires a real ABI probe (`landlock_create_ruleset` with the VERSION flag returns >= 1); a
     kernel without Landlock, or one whose seccomp policy blocks the syscall, is unavailable, never
     assumed.
   - **`seatbelt`**: macOS `sandbox-exec` (requirement 12), the macOS counterpart of `landlock`;
     usable when the host is darwin and `/usr/bin/sandbox-exec` exists.
   - **`docker`**: a container, used only when the operator chose it (`sandboxBackend: docker`)
     and never probed or picked under `auto`. Requires not just the binary but a reachable daemon
     (a real `docker info` probe): "installed" **MUST NOT** be treated as "usable".
   - **`none`**: nothing usable. A turn that asked for isolation is refused (requirement 9); a
     single `bash` call that asked for a jail runs nothing (requirement 4).
   - `DOCKET_SANDBOX_BACKEND` (`landlock`|`seatbelt`|`docker`|`none`) **MUST** override the
     automatic choice, for tests and for an operator who wants to force or disable a backend.
     `DOCKET_SANDBOX_PROBE=none` makes the landlock and seatbelt probes report unavailable, as on a
     host without the kernel feature.
2. **Opt-in, default off.** `ToolContext.sandbox` (`"off"` | `"auto"`) defaults to `"off"`: the
   `bash` handler **MUST NOT** ask for a jail unless the caller sets `sandbox="auto"`. A jail can
   break a command the gate would allow (one that reads a path outside the roots for a legitimate
   reason), and a backend is not on every machine, so an operator verifies a backend on their
   hosts and then opts in fleet-wide with `docket setup sandbox on` (requirement 9).
3. **The jail is additive to `resolve_within`, never a replacement.** A `landlock` or `seatbelt`
   jail grants each of `ToolContext.roots` read-write and the system directories read-only, and
   nothing else: the operator's `$HOME` and `DOCKET_HOME` (`secrets.json`, every pod's sessions
   and traces, the audit log) are denied for read as well as write. A `docker` jail is stronger
   still: nothing outside the mounted roots exists inside the container. Both **MUST** hold at the
   same time as `resolve_within`'s check on file-tool calls: `sandbox="auto"` **MUST NOT** change
   what a `read`, `write`, `edit`, `glob` or `grep` call may touch, and a command's jail **MUST
   NOT** be treated as a substitute for gating that command.
4. **Honest capability reporting: two questions, two answers.**
   - *"Is a jail available?"* is a side-effect-free probe, `sandbox_availability()`, answerable
     with no command run. `docket setup` and `docket setup sandbox` report it (`--json`:
     `backend`, `kernel`, `available`, `missing`).
   - *"Did **this** command run in a jail?"* is per call. `run_bash` **MUST** report the backend
     actually used whenever `sandbox="auto"` was asked for, as a trailing `[sandbox: <backend>]`
     marker on the result. When no backend is usable at call time (forced `none` included),
     `sandbox="auto"` **MUST NOT** run the command: it returns
     `not run: no sandbox backend is usable [sandbox: none (<reasons>)]` with the real reason,
     because the gate allowed the command on the promise of a jail (Tool-approval gates 1).
     `sandbox="off"` **MUST NOT** emit the marker and **MUST NOT** change `run_bash`'s output in
     any other way.
   - A flag meaning "sandboxing is configured" **MUST NOT** be conflated with "this command ran in
     a jail" anywhere this is surfaced.
5. **A jail that fails to start MUST fail closed, not fall back to unsandboxed.** If
   `sandbox="auto"` resolves to a real backend but the launch raises (`OSError`: the binary
   vanished, permissions changed, the daemon died between probe and call), `run_bash` **MUST**
   return a failure naming the backend (`"sandbox (<backend>) failed to start: <error>"`) and
   **MUST NOT** retry the command unsandboxed. A jail that is claimed and absent is worse than
   none, because it is trusted.
6. **The environment is minimized inside a real jail, never inherited.** Under `landlock`,
   `seatbelt` or `docker` the jailed process **MUST NOT** receive the host environment. It gets
   only: `PATH` (landlock and seatbelt); the operator's git identity (`git_identity_env`: the four
   `GIT_AUTHOR_*`/`GIT_COMMITTER_*` variables when set, else `user.name`/`user.email` as host git
   resolves them in the root, so a jailed commit carries the operator's identity on every backend;
   never a credential); the pod cache variables (`HOME`, `XDG_CACHE_HOME`, `XDG_CONFIG_HOME`,
   `UV_CACHE_DIR`, `PIP_CACHE_DIR`, `npm_config_cache`) pointing at the pod's cache dir when the
   turn has one; `TMPDIR`, `TMP` and `TEMP` pointing at the launch's private temp dir (landlock and
   seatbelt); and whatever `ToolContext.env` explicitly injects (e.g. `DOCKET_SCRATCH_DIR`), which
   wins over all of these. Docker receives the same overlay as `-e` flags. `sandbox="off"` launches
   with `task_environment`, the host environment minus docket's credentials ("Credentials in task
   processes").
7. **Timeout and process-group kill hold under every backend.** `run_bash` starts the command in
   its own session so a hang with forked children can be killed as a whole; this **MUST** leave no
   orphan under a real jail:
   - **landlock** and **seatbelt**: the process-group `SIGKILL` **MUST** suffice on its own. The
     jail entry `exec`s the command in place, so it and everything it forks stay in the host
     process group that is signalled: a command that forks two background `sleep`s and hangs leaves
     zero matching processes after a timeout.
   - **docker**: the process-group kill alone **MUST NOT** be relied on. `docker run`'s CLI process
     is a thin client, and the command runs under `dockerd`, a separate process tree; killing only
     the CLI's group leaves the container running. The timeout handler **MUST** call
     `docker_kill(<container name>)` (a direct `docker kill`, which with the run's `--rm` also
     removes the container) before, or in addition to, killing the CLI's group.
8. **Under network `open` the jail leaves the network reachable.** `landlock_argv` passes
   `--net open` (no network rule), the seatbelt profile allows `network*`, and docker keeps the
   image's default bridge. An open jail **MUST NOT** be described as network isolation anywhere in
   user-facing material; the lockdown is "Network egress and the `fetch` tool" requirement 7.
9. **Who asks for the jail, and fail closed.** `ToolContext.sandbox` is `"off"` wherever a
   `ToolContext` is constructed directly. `DocketDriver.run_turn` is the one production caller
   that passes `"auto"`, and only when isolation is recorded on (`docket setup sandbox on`); a
   `DOCKET_HOME` with no recorded choice is not isolated, and its turns never probe for a backend.
   - **Fail closed when isolation is on and no backend is usable.** `DocketDriver.run_turn` probes
     `sandbox_availability()` itself before building the `ToolContext` (independently of the probe
     `run_bash` makes per call): if isolation is on and the probe says `none`, the turn **MUST** be
     refused outright (`DispatchError`, so pod dispatch settles the task `failed` with
     `dispatch_refused` after one attempt instead of retrying) and audited once
     (`isolation.refused`); no model call is made and no tool runs. A per-call failure only an
     operator reading raw tool output would see is not an acceptable substitute for "isolation is
     on" meaning something. The refusal names the fixes: use Linux 5.13+ (landlock) or macOS
     (seatbelt), choose docker with `docket setup sandbox backend docker`, or record
     `docket setup sandbox off`.
   - `docket setup` probes `sandbox_availability()` and reports the backend a turn would use, or
     that turns will be refused and the fixes; its `--json` `securityGates` carries `isolation`
     (`off (default)` | `on` | `off`), `sandboxBackend`, `sandboxUsable`, `dockerImageHasGit`,
     `network` and `networkEnforced`. `docket setup sandbox` reports the gate, the isolation state,
     the probed backend, the network mode and the read-only grants.
10. **The Landlock jail (`python -m docket.jail`).** `landlock_argv(roots, command, network,
    read_only)` returns `[sys.executable, "-m", "docket.jail", "--rw", <path>..., "--ro",
    <path>..., ["--refuse", <reason>], "--net", none|open, "--", "/bin/sh", "-c", command]`; the
    first root is the cwd. The entry sets `PR_SET_NO_NEW_PRIVS`, then a Landlock ruleset that
    handles every filesystem right the probed ABI knows: read-write (read, write, make-*, remove,
    plus refer, truncate and ioctl-dev where the ABI has them) on the `--rw` paths, which include
    the launch's private temp dir (never the shared system temp dir); read and execute only on
    `/usr`, `/lib`, `/lib64`, `/bin`, `/sbin`, `/etc`, `/opt`, `sys.prefix`, `sys.base_prefix` (a
    venv's interpreter and stdlib), `/dev/zero`, `/dev/urandom` and the `--ro` paths; read-write on
    `/dev/null` and `/dev/tty`. Nothing else is granted, so the operator's home and `DOCKET_HOME`
    are denied for read as well as write. A listed path that does not exist is skipped. Under
    `--net none` the entry handles Landlock TCP bind and connect with no rule when the ABI is >= 4,
    and on x86_64 and aarch64 installs a seccomp filter (through `prctl`, no libseccomp) that
    returns `EPERM` for `socket(AF_INET|AF_INET6)`, for `io_uring_setup`, for any x32 syscall
    number, and for any syscall made under a different audit architecture than the host's. On
    another host architecture there is no filter, and `--net none` relies on Landlock alone.
    `--net open` installs no filter and handles no network right. The entry fails closed: if the
    ruleset cannot be enforced, or `--net none` can be enforced by neither layer, it exits 125
    naming the reason and runs nothing. It does not hide `/proc`. A Landlock rule cannot take a
    right away from a sub-path of a granted root, so the git dir goes in as `--ro`, and only the git
    dir's writable parts as `--rw` (Workspace isolation 4); a root holding a `.git` directory is
    passed `--refuse <reason>`, which exits 125 naming it and runs nothing.
11. **One jail builder for every command docket launches.** `jail_launch(roots, command, backend,
    *, network, env, extra_rw, cache_dir, read_only)` is the only place that turns a backend, the
    roots, `extra_rw` (read-write beside the roots, never the cwd), the pod cache dir (writable,
    and the jailed command's home and caches) and the read-only grants into an argv, a child
    environment (requirement 6; no host environment) and, for docker, a container name. `run_bash`
    and `run_command` (so `verifyCmd`, `run:` steps and the prepare install) all call it, so a
    `verifyCmd` or a `run:` command runs under exactly the jail a `bash` call of the same pod
    would. The decision is the turn's own: isolation recorded on and a usable backend, with the
    pod's network. **Fail closed**: with isolation on and no usable backend the command is not run,
    the verify gate fails (`[verify not run: ...]`) and the `run:` step fails; a jail that cannot
    start is a failure, never a retry on the host. With isolation off both run on the host with
    `task_environment`. The `match_high_risk` refusal stays ahead of any subprocess. Stdio MCP
    servers are jailed by the same backends whenever the turn is isolated, with no per-server
    opt-out; with isolation on and no usable backend the server is not spawned.
12. **The Seatbelt jail.** `seatbelt_argv(roots, command, network, read_only)` returns
    `["/usr/bin/sandbox-exec", "-p", <profile>, "/bin/sh", "-c", command]`. The profile is one
    fixed template: `(version 1)`, `(deny default)`; `process-exec*`, `process-fork`,
    `sysctl-read`, `mach-lookup`, `file-read-metadata` and signals to self allowed;
    `file-read-data` of the literal `/` (the root's entry names, not its subtree: macOS 26 aborts a
    process that cannot list it, with SIGABRT and no output); read-only `subpath` rules for `/usr`,
    `/bin`, `/sbin`, `/etc`, `/opt` (Homebrew's libraries), `/private/etc`, `/System/Library`,
    `/Library`, `sys.prefix`, `sys.base_prefix` and the read-only grants; read of
    `/dev/random|urandom`, read-write of `/dev/null|zero|tty|dtracehelper`; read-write `subpath`
    rules for each root, its repository dirs and the launch's private temp dir (never the real
    `$TMPDIR`); a `(deny file-write* ...)` for each guarded git path after the grants, then the
    re-opened task branch ref dirs; then `(deny network*)` or `(allow network*)`. Paths are quoted
    for the profile language (`\` and `"` escaped). The operator's home and `DOCKET_HOME` are
    unreadable. `sandbox-exec` is deprecated by Apple but still ships. `jail_launch` builds it like
    the `landlock` argv, so `bash`, verify and `run:` all reach it.
13. **Host-side git never reads what the jail can write.** `provision_task_worktree` records the
    worktree's `gitDir` and `commonDir` beside `dir`, `branch` and `baseCommit`. Resolving a task's
    worktree registers them (`trust_worktree`), and from then on every host-side git call for that
    path (status, the pin commit, diffs, the identity lookup) names them through `GIT_DIR`,
    `GIT_COMMON_DIR` and `GIT_WORK_TREE`, and `git_dirs` answers from the record when building the
    next jail. A `.git` file, `gitdir` or `commondir` the agent rewrote is therefore never
    followed. A worktree whose `config.worktree` exists while the shared config enables
    `extensions.worktreeConfig` is refused by those calls (the file can name a program to run),
    since Landlock cannot keep it unwritable. A task with no recorded `gitDir` (one that ran in
    place) is not covered.
14. **The operator grants the toolchain read-only.** A tool installed under the operator's home
    (a version manager's Node, the user site of the system Python) is unreadable in the jail, so a
    gate that needs it fails like a failing test. `docket setup sandbox read add <path>` records
    an absolute path in `fleet.json` `security.readOnly` (machine-wide, audited `gates.read`), and
    `docket setup sandbox read remove <path>` drops a recorded path, existing or not (exit 1 when
    it is not recorded). `add` is refused (exit 1, nothing written) for a relative or missing path,
    `DOCKET_HOME` or a path inside it, and the operator's home or any ancestor of it or of
    `DOCKET_HOME`. A recorded path is stored resolved. A pod may only narrow the machine's list,
    never widen it: its `readOnly` setting (`docket pod set readOnly ...` or a `pod.yaml` `settings`
    mapping) is unset (every machine grant), `none` (no grant), or a comma-separated list whose
    every path must already be a machine grant when it is written (`PodSettings.coerce` refuses any
    other, so a repository's team directory cannot add a path). A turn's grants are
    `effective_read_only(pod)`: the machine's list, kept only where the pod names it; a grant the
    operator later removes leaves every pod, and unreadable pod settings fail closed to none.
    Every jail docket starts while isolation is on reads and executes those paths and never writes
    them: `--ro` for Landlock, a read-only `subpath` for Seatbelt, a `:ro` bind mount for docker;
    `bash`, `verifyCmd`, `run:` steps and stdio MCP servers alike. A path removed from disk after
    it was recorded is skipped like any other missing grant. `docket setup sandbox` lists them,
    and its `--json` carries `readOnly` (a list, empty by default). With isolation off nothing
    changes.
    A jailed `bash` call that exits 126 (found but cannot execute) **MUST** say so in its error,
    after `command exited 126`: the jail could not execute it, a retry will not help, and the
    operator grants a toolchain with `docket setup sandbox read add <path>`. It is a message, not a
    new stop condition: the no-progress stop still bounds a model that keeps retrying.
15. **A prepared worktree is readable, never writable, and its install has the network
    (ADR 0029).** The install command of a task's worktree (pod-dispatch.spec.md, "Task
    preparation") is a docket-launched command like a `verifyCmd`: with isolation on it runs
    through `jail_launch` with the worktree writable and **the network open for that launch
    only**, whatever the pod's `network` records; with isolation off it runs on the host. Hops,
    `verifyCmd`, `run:` steps and gates keep the pod's `network`. The cache entry the install is
    kept in (`$DOCKET_HOME/cache/prepare/<codebase>/<entry>`) is added as a read-only root, as
    requirement 14's grants are, to every jailed command whose worktree holds a symlink into it
    (`linked_entries`): readable and executable, not writable, so a hop cannot alter what the next
    task of the codebase links. The entry is found from the worktree's own links, never from a
    setting a repository can write.

### Protected paths and the reviewed digest (ADR 0029)

A check is never defined by the change it checks. The rules below are pure functions over
repository-relative paths; pod-dispatch.spec.md "A change that edits its own check" is where a
task meets them.

1. **Defaults.** A path is protected when it matches one of: the lockfiles the prepare step knows
   (`package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `uv.lock`, `poetry.lock`, `Cargo.lock`),
   `package.json`, `pyproject.toml`, `Cargo.toml`, `.eslintrc*`, `eslint.config.*`,
   `tsconfig*.json`, `vitest.config.*`, `jest.config.*`, `ruff.toml`, `setup.cfg`, `tox.ini`,
   `pytest.ini`, `mypy.ini`, `.docket/**` and `.github/workflows/**`. A pattern without a `/` is
   matched against the file name at any depth (`web/package.json` is protected); a pattern with a
   `/` is matched against the whole repository-relative path, `*` matching across `/`. Matching is
   case-sensitive, on `/`-separated paths.
2. **The team's `protects`.** `PodSettings.protects` adds patterns, with the same matching; it
   never removes a default, and a pattern that matches nothing is not an error.
3. **Files a reviewed command names.** A command string is split like a shell would (quotes, and
   `&&`, `||`, `;` and `|` as separators); a token, or the part of `--flag=value` after the `=`,
   with a leading `./` removed, that is a tracked file of the repository is protected. Only files
   are named this way: `pytest tests/` names a directory and protects nothing, and a `make` or
   `npm run` target is covered only through the files it reads that the defaults already hold.
4. **The reviewed digest covers those files' contents.** The reviewed digest of a set of run items
   covers, for each tracked file those items' commands name (items of kind `allow-commands`,
   `network` and `role-loosens` name none), the file's git blob id as it stands in the codebase
   root. A file whose content changes, or which is added to or removed from the set, changes the
   digest and the 16-hex review code, so `docket pod update` and `docket run` ask the person again;
   the stored items are unchanged, so a refusal shows the same before/now lines. A root that is
   not a git repository contributes no files.

### Network egress and the `fetch` tool (D-23)

**The network default is `none`, but only a sandbox can enforce it.** With isolation off (the
default) a turn's network is open and the mode reads `none (default)`; nothing is refused until
the operator records `none` (global or pod) explicitly. No part of this spec, and no user-facing
material, may be read as saying otherwise.

1. **The open path, precisely.** `bash`'s command classifier routes `curl` and `wget` to `ask`,
   because neither is on `SAFE_BINS`. But `python3`, `node` and `git` **are** on the allowlist:
   `python3 -c "import urllib.request; ..."`, a `node` one-liner and `git clone <url>` **MUST NOT**
   be described as gated. They run unattended under the allowlist, like `git status` or `npm test`,
   because the classifier gates by binary and argument shape, not by whether a binary can also
   make network calls. They stay on the allowlist because agents need them constantly for
   ordinary work (the trade-off "High-risk action classes" makes for `git` and `npm`).
2. **`fetch`: an inspectable path, not a closed gate.** `fetch` (`fetch_url`) is a built-in,
   gated tool of kind `read`, offered to the model only while `FETCH_ALLOWED_DOMAINS` is non-empty
   (agent-loop.spec.md requirement 83). It enforces, inside the handler itself (mechanism, as
   `resolve_within` is for file paths):
   - **A domain allowlist** (`FETCH_ALLOWED_DOMAINS`, exact hostnames, comma-separated, **empty
     by default**). A host not on the list **MUST** be refused before any socket opens; `fetch`
     does not reach everywhere because egress is otherwise open, an operator opts a domain in.
   - **A response size cap** (`FETCH_MAX_RESPONSE_BYTES`, default 200,000 bytes). A response over
     the cap **MUST** be truncated with the truncation announced in the returned text, the
     announced-truncation contract every other built-in has.
   - **A wall-clock deadline** (`FETCH_TIMEOUT_S`, default 15 s). The deadline bounds the whole
     call, not each socket operation: the body is read in chunks and the call fails as timed out
     once the monotonic deadline passes, so a server dripping bytes cannot hold the call open. The
     deadline is checked between chunks; a single blocked read ends at the socket timeout, so the
     call returns at most one socket timeout past the deadline. The tool's own `timeout` argument
     is clamped to four times `FETCH_TIMEOUT_S` (60 s by default); a larger value is silently
     bounded, and a non-positive value falls back to `FETCH_TIMEOUT_S`.
   - **A redirect guard.** A redirect off the domain allowlist **MUST** be refused, not followed,
     or the allowlist would be decorative. `urllib`'s redirect-following is intercepted at its
     extension point (`HTTPRedirectHandler.redirect_request`) before a connection to the new host
     opens.
3. **Gated like every other built-in, no second execution path.** `fetch` is registered like
   `read`, `write` and `bash`, and every call passes `dispatch_tool` → `evaluate_tool_call`: a
   `pre_tool_call` policy can `block`, `require_approval`, `warn` or `redact` a `fetch` call,
   rendered `"fetch url=... timeout=..."` by `render_tool_call`. Being of kind `read`, a `fetch`
   call does not pass the exec command classifier (there is no shell command); its containment is
   the domain allowlist in the handler.
4. **`fetch` closes none of the open paths in requirement 1.** It exists so reaching for the
   network does not have to mean reaching for one of them. Cutting a jailed command's network is
   requirement 7.
5. **Scope.** This section governs `fetch_url` and the `fetch` tool registration. A default
   install reaches no domain through `fetch`, and nothing here changes what `bash`, `python3`,
   `node` or `git` may do; those stay as requirement 1 describes.
6. **`fetch` results pass `pre_input` like MCP results (ADR 0020).** The text of a successful
   `fetch` response and the error text of a failed one **MUST** be evaluated through
   `policy_eval_detail(ctx.role, "pre_input", text, trusted=False, project=ctx.project)` inside the
   `fetch` handler, so the pod's own policies apply; a result with no text (an empty response, or
   a fetch error before any text) passes unchanged and unaudited. A `block` or `require_approval`
   result **MUST** replace the outcome with `ok=False` naming the policy id, and **MUST** be audited
   (`fetch.result_blocked`, naming url and host). A `redact` result **MUST** return the text passed
   through `redact`, and a `warn` result **MUST** return it unchanged; both **MUST** be audited
   (`fetch.result_warn`). `allow`, or no hit, passes the outcome unchanged with no audit entry.
7. **The network lockdown mode (ADR 0020, default `none` per ADR 0024).** `none` is the default: a
   fresh home reports network `none`, `open` is an operator grant (`docket setup sandbox network
   open`), and a pod's `network` can only narrow it. The refusal below fires only when `none` was
   recorded explicitly (global or pod); the unrecorded default with isolation off runs, with the
   network open, because nothing can cut it. The global mode (`docket setup sandbox network
   none|open`, `fleet.json` `security.networkMode`, audited `gates.network`) and the pod setting
   `network` (`none`|`open`; `open` means follow the global mode) resolve through
   `effective_network`: `none` when either says `none`, so a pod's `open` never widens a global
   `none` and a pod's `none` narrows a global `open`; unreadable pod settings fail closed to
   `none`. Under `none`, `landlock_argv(..., network=False)` passes `--net none`, the seatbelt
   profile denies `network*`, and `docker_run_argv(..., network=False)` adds `--network none`;
   `ToolContext.network` carries it to `run_bash`. Only the sandbox can enforce it, so a turn whose
   effective mode is a recorded `none` with isolation off **MUST** be refused before any model
   call (`DispatchError`, as for the isolation refusal: one attempt, one `network.refused` audit
   entry naming the scope, task `dispatch_refused`), naming the setting and the two fixes.
   `fetch` runs in docket's own process and is untouched: its domain allowlist stays the
   inspectable path. `docket setup sandbox`, `docket setup` and `docket pod show` report the mode
   and scope.
   **Reporting the mode (one owner).** Only the sandbox cuts the network, so every surface that
   prints the mode (`docket setup sandbox` and its `--json`, the `docket setup sandbox network`
   confirmation, `docket status`'s sandbox phrase, `docket setup` and its `--json`, `docket pod
   show`'s `Network:` line) **MUST** take its wording from one posture function
   (`network_posture`; `global_posture` for the fleet record) and **MUST NOT** claim the network is
   cut unless isolation is on. With isolation off and mode `none` the line reads `none (<scope>),
   not enforced: isolation off, egress is open`, carries no `ok` marker, and the status phrase
   reads `network none (not enforced: isolation off)`. With isolation on the line reads
   `none (<scope>); jailed tool calls have no network`. The JSON surfaces carry `networkEnforced`
   (true only when isolation is on and the mode is `none`). `docket pod show --json` keeps
   `{mode, scope}`.

### Parked calls and single-use pre-grants (ADR 0016)

An in-turn `ask` may need to end the turn without blocking on a human answer, and a human's grant
of that exact call needs a way to reach a later, re-entered turn without asking again.

1. **Park.** Under `ToolContext.approval_mode == "park"`, `dispatch_tool`'s `ask` branch **MUST
   NOT** call `wait_for_approval`; it creates a pending approval record naming the exact call and
   returns immediately.
2. **The parked record.** `approval_create` is called with `context={"tool": <tool name>,
   "callId": <call id>, "argsDigest": <digest>, "parked": True}`, plus `project` and `role` when
   `ToolContext.project`/`.role` are non-empty and `taskId` when the turn serves a task.
   `<digest>` is `canonical_args_digest(tool.name, args)`, a stable SHA-256 digest of the tool's
   canonical-JSON arguments, independent of key order. The result's `decision` **MUST** be
   `"deny"`, `denial_kind` **MUST** be `"approval_parked"`, and `ToolResult.approval_token` carries
   the record's token.
3. **The record's own expiry.** When `ToolContext.approval_expires_at` (an ISO UTC string) is set,
   the parked record carries it as `expiresAt`; dispatch sets it for each parking hop from the
   pod's `approvalExpiryHours` (default 24). Otherwise the record's `expiresAt` is
   `created + APPROVAL_TIMEOUT` (Approval tokens 3). `approval_sweep_expired` resolves a pending
   record past its own `expiresAt` through the one fail-closed path; a parked call's timeout is
   not a second terminal path.
4. **Single-use pre-grants.** `create_pregrant(project, role, tool, args_digest, *, task_id=None,
   expires_at=None, channel, actor="")` persists a record already `state: "granted"`,
   `context={"kind": "pregrant", "tool": ..., "argsDigest": ..., ["taskId": ...]}`, audited
   `approval.pregrant`. `consume_pregrant(token)` atomically (the store's locked
   read-modify-write) marks it `consumedAt` and returns `True` exactly once, for a record still
   `granted`, never consumed, and not past its own `expiresAt` when one is set; every later call,
   or a call past expiry, returns `False` without changing the record. A successful consumption
   audits `approval.consume`.
5. **Where pre-grants are checked.** In `dispatch_tool`'s `ask` branch, **before** the
   `approval_mode` dispatch (`refuse`/`park`/`wait`), every entry of `ToolContext.pregrants` (a
   tuple of `Pregrant(token, tool, args_digest)`) whose `(tool, args_digest)` matches the call's
   `(tool.name, <digest>)` is tried against `consume_pregrant`; the first that consumes allows the
   call (`decision="allow"`, `ToolResult.approval_token` set to its token) and the handler runs.
   This applies **regardless of `approval_mode`**: a pre-grant answers a question already asked,
   so it wins even under `"refuse"`. A call whose canonical arguments match no pre-grant, or whose
   only match was consumed or is past its expiry, falls through to the ordinary mode handling.
6. **Unconsumed pre-grants expire too.** `approval_sweep_expired` also prunes a `granted`,
   unconsumed `context.kind == "pregrant"` record once past its own `expiresAt`: denied
   (fail-closed), audited `approval.deny` with `channel=timeout`. The record was born `granted`
   (its birth state, not a contested decision), so it is resolved directly rather than through the
   grant/deny race guard; a pre-grant swept this way is never consumable afterward.
7. **The turn loop.** The agent loop treats `denial_kind == "approval_parked"` as terminal for the
   batch, exactly like `"approval_unavailable"`: the turn stops with
   `stop_reason == "approval_parked"`, rendered by `approval_parked_error` in the same key=value
   shape `approval_unavailable_error` uses, plus `approval_token` (agent-loop.spec.md, "The
   approval_parked stop").

### Approval tokens and approval packs

1. **Tokens are validated before use.** An approval token **MUST** match the minted form
   `apr-<uuid4>` (`APPROVAL_TOKEN_RE`). A token of any other shape is refused, so no path under the
   approvals directory is ever built from caller text. The check sits where a token becomes a file
   name, so the HTTP route, Telegram, MCP and the CLI are covered without each validating on its
   own: a malformed token is `ApprovalError("Approval not found: <token>")`, never a path.
2. **Approval packs (ADR 0018).** An approval made for a gated tool call (wait and park modes)
   carries a pack on its record and on the `approval_requested` trace event, as additive fields:
   `rationale` and `options`.
   - `rationale` is the assistant text of the message that made the call (`ToolContext.rationale`,
     set by the agent loop per tool-call batch). It is screened with
     `policy_eval_detail("lead", "pre_input", text, trusted=False, project=ctx.project)`,
     redacted, and cut to 500
     characters. A `block` hit makes it `""` and adds `rationaleBlocked: true` to the trace
     payload. The key is always present for a gated call, `""` when there is no text. Approvals
     created outside a tool call carry neither key.
   - `options` is exactly three operator-v1.1 `Option`s, in order: `approve_once`,
     `approve_task`, `deny`.
   - `approve_task`: a grant that chose `approve_task` (`docket task approve --task`, HTTP or MCP
     `option: "approve_task"`, Telegram) records the option on the pending record before the grant.
     When the waiting call sees a granted record with that option, it creates a pre-grant for that
     exact call (`create_pregrant`, channel `cli`, the tool and canonical argument digest) and adds
     it to `ToolContext.pregrants`, so one identical later call in the same turn context runs
     without a new approval. It is single-use.
3. **Every approval records its own deadline.** `approval_create` always stores `expiresAt`: the
   caller's value, else `created + APPROVAL_TIMEOUT` (ISO 8601 UTC). The record, the
   `GET /approvals` view and the inbox item therefore carry the deadline the sweep enforces.

### Credentials in task processes (ADR 0020)

1. `task_environment(overlay, cache_dir=None)` returns the host environment minus
   `DOCKET_LLM_API_KEY`, `TELEGRAM_BOT_TOKEN`, every credential name any provider in the catalog
   (built-in or global) declares in `auth.credentials`, and every name in the secret store; then
   the pod cache variables when a cache dir is given; then `overlay` last, so an explicit value
   (`DOCKET_TASK_ID`) always arrives.
2. `run_command` (verify commands, `run:` steps, the prepare install) and `run_bash` with
   `sandbox="off"` both launch their child with this environment. The jailed paths forward no host
   environment at all (Exec sandbox 6).
3. Reading the secret store and the catalog for this never creates `DOCKET_HOME`.
4. `make_non_dumpable()` calls `prctl(PR_SET_DUMPABLE, 0)` through `ctypes` on Linux, so a
   same-uid process cannot read this process's `/proc/<pid>/environ` or `mem` (`EACCES`). It is a
   no-op off Linux and on any failure, never raises, and the flag resets across `execve`, so
   children stay debuggable. `docket start` (before its `--mcp` branch) and
   `DocketDriver.run_turn` call it before any task process is spawned. Hiding the environment from
   root is a non-goal.

### Profiles (ADR 0025)

1. **Two profiles.** `attended` (the default; nothing recorded) changes nothing. `lights-out` is a
   recorded operator choice that makes a pod's dispatch refuse to start unless the requirements
   below hold. The same binary runs both; the profile adds demands and moves no default (ADR 0021
   and ADR 0004 stand).
2. **Recording.** Globally: `fleet.json` `security.profile`, unset until `docket setup profile
   lights-out` writes `lights-out`; `docket setup profile attended` returns it to unset. Per pod:
   `PodSettings.profile` (`docket pod set profile lights-out|attended`). The effective profile is
   `lights-out` when either is `lights-out`, and when the pod's settings cannot be read. A pod can
   only move toward stricter, so `PodSettings.coerce("profile", "attended")` is refused while the
   global profile is `lights-out` (this covers `docket pod set` and a `pod.yaml` `settings`
   mapping). Writes are audited (`gates.profile`, `pod.config`).
3. **Requirements** (`lights_out_violations`, a pure function over a `Facts` record;
   `gather_facts` fills it from the existing readers and decides nothing). Each violation names
   its requirement and its fix:
   - `isolation`: isolation is on and `sandbox_availability().backend` is not `none` (the decision
     the driver makes before a turn);
   - `network`: the pod's effective network is `none` from a recorded choice (scope `global` or
     `pod`; the unrecorded default does not count);
   - `external-gate`: every planned step whose role is `implementer` (a role target, or an agent
     target whose recorded role is `implementer`) carries an external gate; a `parallel` group is
     walked;
   - `secrets`: no variable docket injects for the pod (the Implementer's port and scratch
     variables, and the `env` of each MCP server in the pod's effective set) is named in the
     secret store.
   There is no HTTP MCP server check: MCP servers are stdio only and run in the jail.
4. **Refuse, do not degrade.** `dispatch_task` evaluates the profile once, after the pipeline is
   planned and before any hop runs. A violation audits `profile.refused` (pod, task and the
   requirements), runs no hop and raises `DispatchError` naming each requirement and its fix; it
   folds into `failure_kind "dispatch_refused"`, which is resumable once the operator fixes the
   cause. This covers `docket run` and `docket start --dispatch`.
5. **One reader.** `docket setup` and `docket status` (and their `--json`, under `profile`) show
   each `lights-out` pod's violations from the same `gather_facts` + `lights_out_violations`
   call; recording `docket setup profile lights-out` lists the fleet-level gaps. With every
   effective profile `attended` they print nothing extra.

### Task restrictions (ADR 0027)

A task may carry `restrictions` (`deniedTools`, `network`, `policies`; their shape, and the refusal
of anything that would widen, are enforced at enqueue, operator-api.spec.md "Arguments"). They
narrow the hops of that one task and never widen anything.

1. **Narrow only.** The hop's denied set is the union of the role's `denied_tools`, the pod's
   `deniedTools` and the task's `deniedTools`; the hop's network is `none` when the pod, the global
   setting or the task says `none`; the task's policy documents evaluate in addition to the global
   and pod policies, never instead of them.
2. **Where it lands.** Dispatch hands the restrictions to the driver as three internal keys of
   `run_turn`'s `env` (`DOCKET_TASK_DENIED_TOOLS`, `DOCKET_TASK_NETWORK`, `DOCKET_TASK_POLICIES`),
   which `DocketDriver` pops like `DOCKET_APPROVAL_MODE`, so no tool sees them. `dispatch_tool` is
   unchanged: it evaluates `pre_tool_call` policies through `policy_eval_detail`, which also reads
   the turn's task policy documents (`task_policies`, set by the driver around the turn).
3. **`deniedTools` is a block policy, not a registry removal.** The driver turns the denied names
   into one `pre_tool_call` policy with `action: block` and id `task-restriction`, so a refused call
   is an audited `tool.deny` carrying `policy_id='task-restriction'`, and the hop continues with the
   refusal as the tool result. The set is closed by capability as `registry_for_role` does: every
   tool of a denied built-in's kind (an MCP tool is registered `write`) is named in the policy too.
4. **`policies` are block-only, re-checked at the hop.** Each document is normalised, validated
   with the policy validator, and its action **MUST** be `block`; a document that fails either
   check refuses the hop before it starts (`DispatchError`, so the task fails `dispatch_refused`).
   Whatever its own `id`, a task document evaluates under the id `task-restriction`, so the audit
   entry names the source.
5. **`network: "none"` fails closed.** The jail's network is `none` for the hop whatever the pod
   records. With isolation off nothing can cut the network, so the turn is refused up front and
   audited `network.refused` with scope `task`, as a recorded pod `none` is.
6. **Not covered.** `verifyCmd` and `run:` steps keep the pod's network posture; a per-task
   `allowCommands` does not exist; nothing here is a dollar budget.

## Interface Contracts

### `docket setup sandbox` command

```bash
# The tool-call gate (policy engine + high-risk command classifier) is always active; nothing
# below turns it on or off. These commands manage the isolation, backend, network and read-only
# posture recorded in fleet.json's security block.
docket setup sandbox [--json]          # a read, exit 0: gate (always active), isolation, the
                                       #   probed backend, network mode, read-only grants
docket setup sandbox status [--json]   # the same read
docket setup sandbox on                # record isolation on (audited gates.isolate); exit 1 and
                                       #   record nothing when no backend is usable
docket setup sandbox off               # record isolation off (audited gates.isolate)
docket setup sandbox backend auto      # record the backend choice (audited gates.backend);
docket setup sandbox backend docker    #   auto = landlock on Linux, seatbelt on macOS
docket setup sandbox network none      # record the global network mode (audited gates.network);
docket setup sandbox network open      #   see Network egress requirement 7
docket setup sandbox classes           # list the high-risk action classes, read-only
docket setup sandbox read add PATH     # record a read-only grant for every jail (audited
docket setup sandbox read remove PATH  #   gates.read); refusals per Exec sandbox requirement 14
docket setup profile [CHOICE]          # show, or record lights-out|attended (audited gates.profile)
# Any other verb, or an unrecognised flag, is a usage error: exit 2.
```

### Approval channels

```bash
# docket's approval store is the only approval system. Producers: the pod's require_approval gate
# and the pre_input enqueue gate (a dispatch task waiting_approval), and the in-turn tool-call
# gate (wait or park). See pod-dispatch.spec.md for the task side.
docket inbox                        # what is waiting for you, with the exact approve line
docket task approve <id>            # grant the approval a task holds; resumes the task it gated
docket task approve <id> --task     # also allow this exact call for the rest of the task
docket task deny <id>               # deny it; fails the task it gated, terminally
GET  /approvals                     # docket start: list pending approvals (bearer auth)
POST /approvals/<token>             # docket start: {"action": "grant"|"deny", "option"?,
                                    #   "reason"?, "channel"?: "http"|"tack"} (bearer auth)
# MCP (docket start --mcp): approvals_list, approvals_grant(token, option), approvals_deny(token)
# Telegram (docket start --telegram): /approve and /deny in a chat bound with
#   docket setup notify enable telegram or docket setup notify bind; channel "telegram".
#   See telegram-integration.spec.md.
```

### `docket pod policies`, `docket pod check` and `docket pod validate`

```bash
docket pod policies [POLICY_ID] [--json] [--plugins] [--pod <p>]
                                    # list the policies in force (id, hook, action, description),
                                    #   or show one; the pod's own directory is folded in;
                                    #   --plugins adds the predicate plugins section
docket pod check "<text>" --role <role> [--hook <hook>] [--tool <name>] [--arg key=value] [--pod <p>]
                                    # dry-run the evaluator (no trace written); --tool picks the
                                    #   built-in tool whose kind decides whether the command
                                    #   classifier applies (default bash); the pod's own policies
                                    #   are folded in
docket pod validate [PATH]          # schema-check a policy file, or a directory's policies/
```

## Examples

### A dispatch gate, granted and denied

A pod whose pipeline gives the `implementer` step an `approval` gate parks the task before that hop:
`docket run` reports it `waiting_approval` with its token, `docket inbox` shows the exact approve
line, `docket task approve <id>` grants it and the next `docket run` finishes the task. An
unanswered token fails closed: under `docket start`, `approval_sweep_expired` resolves it to
`denied` once past its `expiresAt`, and the task fails terminally (`failureKind:
"approval_denied"`) without anyone calling `docket task deny`.

### The enqueue-time gate

A `require_approval` `pre_input` policy that matches a task's description gates it before it is
ever claimable; the same resolution path, fed from a second source:

```bash
docket task add "URGENT WIRE the vendor before EOD"   # queued as waiting_approval
docket task approve task-9a1b                          # the task becomes pending
docket run                                             # runs it
```

A `block` match never reaches the queue: `docket task add "wipe the prod database tonight"` fails
with `task rejected by guardrail policy 'no-wipes' at enqueue: absolutely not`, nothing is
persisted, and the trace holds one closed session (`guardrail_check`, `guardrail_block`,
`session_end` with status `aborted`).

### High-risk action classes: examples

`docket setup sandbox classes` prints one row per class (`CLASS`, `DESCRIPTION`, `PATTERN`,
`ALLOWLISTED BINS`): `money-movement` and `secret-access` show `none allowlisted; always asks`,
`prod-deploy` shows `git, npm`. The footer reads `Every shell command is classified before it
runs; a match asks for approval.`

### Docket-launched process classification: examples

A verify command matching a high-risk class is refused before a shell starts:

```bash
docket pod add implementer --verify "stripe charge customer --amount 500 && uv run pytest"
docket run      # the task fails at the verify gate
```

The task's trace records a `verification_failed` event whose output names the class:

```text
[verify command refused: matches high-risk class 'money-movement' (Payment/financial operations: charges, refunds, payouts, transfers) -- see `docket setup sandbox classes`]
```

The subprocess is never started.

A hop that reports having run a high-risk command is flagged, not blocked, on the `pre_output`
path (no installed policy also matched, so the built-in `warn` floor fires):

```text
$ docket task trace <id>
  ... guardrail_check  {"hook": "pre_output", "policy": "high-risk:secret-access", "action": "warn"}
```

### In-turn tool-call gate: examples

These are `dispatch_tool` call shapes, since the gate works one tool call at a time inside a
turn; each is what the gate's test suite asserts, and what every real hop's calls go through.

The `block-destructive` policy gates an `rm -rf` call; with nobody answering, the wait times out
and the handler never runs:

```text
>>> dispatch_tool(ToolCall(id="c1", name="bash", arguments='{"command": "rm -rf /var/data"}'), ctx, registry)
ToolResult(decision='deny', executed=False, denial_kind='approval_timeout',
           policy_id='block-destructive', reason='approval timed out and was denied')
```

`high-risk-deploy` catches a production push by argument; the same tool with a feature branch is
untouched:

```text
>>> evaluate_tool_call(bash_tool, {"command": "git push origin main"}, ctx)
ToolVerdict(decision='ask', policy_id='high-risk-deploy', ...)
>>> evaluate_tool_call(bash_tool, {"command": "git push origin feature/x"}, ctx)
ToolVerdict(decision='allow', policy_id='', ...)
```

A `require_approval` policy asks, then executes once granted, through the same
`wait_for_approval` that fails a call closed on timeout:

```text
>>> dispatch_tool(ToolCall(id="c1", name="custom", arguments='{"x": "launch-codes"}'), ctx, registry)
# blocks; a concurrent grant (or the timeout) resolves it
ToolResult(decision='allow', executed=True, ok=True, ...)   # granted
ToolResult(decision='deny', executed=False, ...)            # denied, or unanswered past
                                                             #   TOOL_APPROVAL_TIMEOUT
```

Every gated call leaves an audit trail, not just a return value:

```text
$ docket log
  ... tool.ask      tool=bash agent=... role=implementer project=demo policy_id='block-destructive' policy_action='require_approval': ... call=bash command="rm -rf /var/data"
  ... approval.deny token=apr-... project=demo channel=timeout
```

### Exec sandbox: examples

These are `run_bash` call shapes; `DocketDriver.run_turn` passes `sandbox="auto"` for every `bash`
call of a turn while isolation is on and a backend is usable.

The default, `sandbox="off"`, carries no marker:

```text
>>> run_bash((workspace,), "printf %s hi", env={"X": "1"})
ToolOutcome(ok=True, content='hi', error='')
```

Asking for a jail on a host with a usable backend reports which one ran; a write outside the root
is contained by the jail itself, on top of the gate that let the command through:

```text
>>> run_bash((workspace,), 'echo breached > /etc/should-not-write; echo rc=$?', sandbox="auto")
ToolOutcome(ok=True,
            content='/bin/sh: 1: cannot create /etc/should-not-write: Permission denied\nrc=2\n\n[sandbox: landlock]',
            error='')
```

On a host with no usable backend the same call runs nothing:

```text
>>> run_bash((workspace,), "printf %s hi", sandbox="auto")
ToolOutcome(ok=False, content='', error='not run: no sandbox backend is usable [sandbox: none (landlock unavailable, docker not chosen or unreachable)]')
```

A jail that was asked for but fails to start is a reported failure, not an unsandboxed run:

```text
>>> run_bash((workspace,), "echo should-never-run", sandbox="auto")   # the jail entry vanishes mid-launch
ToolOutcome(ok=False, content='', error='sandbox (landlock) failed to start: [Errno 2] ...')
```

In a linked task worktree, git metadata the host would later trust is read-only while a commit
still works:

```text
>>> run_bash((wt,), "echo 'gitdir: /x/evil' > .git", sandbox="auto")   # ok=False; .git unchanged
>>> run_bash((sup,), "git -C sub config core.hooksPath /x", sandbox="auto")   # ok=False
>>> run_bash((wt,), "echo x > f && git add f && git commit -q -m m", sandbox="auto")   # ok=True
```

A timed-out command that forked children leaves nothing behind; under docker that needs
`docker_kill`, because `docker run`'s CLI process does not cover the container:

```text
>>> run_bash((workspace,), "sleep 20", timeout=1, sandbox="auto")   # DOCKET_SANDBOX_BACKEND=docker
ToolOutcome(ok=False, content='', error='command timed out after 1s [sandbox: docker]')
$ docker ps -a --filter name=docket-sbx- --format '{{.Names}}'
                                                                     # (empty: no orphan)
```

### Network egress and the `fetch` tool: examples

A host not on the allowlist is refused before any connection opens:

```text
>>> fetch_url("https://example.com/status")
ToolOutcome(ok=False, content='',
            error="'example.com' is not on the fetch domain allowlist (none configured); "
                  "add it to FETCH_ALLOWED_DOMAINS to permit it")
```

Once a domain is configured, the call succeeds, is size-capped, and a redirect off the allowlist is
refused rather than followed:

```text
# FETCH_ALLOWED_DOMAINS=api.example.com
>>> fetch_url("https://api.example.com/status")
ToolOutcome(ok=True, content='HTTP 200 application/json\n\n{"status": "ok"}', error='')

>>> fetch_url("https://api.example.com/huge-report")   # FETCH_MAX_RESPONSE_BYTES=200000
ToolOutcome(ok=True,
            content='HTTP 200 text/csv\n\n<first 200000 bytes>\n\n'
                    '[truncated: response exceeded 200000 bytes]',
            error='')

>>> fetch_url("https://api.example.com/redirects-offsite")   # 302 -> http://attacker.example/x
ToolOutcome(ok=False, content='',
            error="HTTP 302 from https://api.example.com/redirects-offsite: redirected to "
                  "'attacker.example', which is not on the fetch domain allowlist")
```

The open paths the allowlist does **not** cover, named so this is never read as "network egress
is gated":

```text
$ python3 -c "import urllib.request; urllib.request.urlopen('https://anywhere.example')"
# runs unattended: python3 is on SAFE_BINS; classify_command never sees the URL
$ node -e "require('https').get('https://anywhere.example')"
# runs unattended: same reason, for node
$ git clone https://anywhere.example/repo.git
# runs unattended: git is on SAFE_BINS
```

## Validation

### Pre-conditions

- No external runtime is required. The policy engine and high-risk classifier are active on every
  tool call, and every docket turn routes through that one chokepoint.

### Post-conditions

- Dangerous operations **MUST** be gated on every tool call docket dispatches, unconditionally,
  not contingent on an install flag.
- Grants and denials through docket's approval store **MUST** appear in the audit log, tagged with
  their channel (Tool-approval gates 4).
- A gate with no approver **MUST** resolve to denied: an in-turn call at its approval timeout; a
  store record past its `expiresAt` while `docket start` runs, failing the dispatch task waiting on
  it as part of that resolution.
- Every non-`allow` decision `dispatch_tool` makes (`deny`, `ask`, and a `warn` or `redact` hit
  that still allows the call) **MUST** appear in the audit log, with the gated call's rendered
  arguments passed through `redact` first.
- A default install (`FETCH_ALLOWED_DOMAINS` unset) **MUST** leave `fetch` unable to reach any host
  and **MUST NOT** offer it to the model at all: the registry leaves `fetch` out while the
  allowlist is empty (agent-loop.spec.md requirement 83).
- The escape matrix **MUST** pass on every backend the host has (landlock, docker when its daemon
  answers, seatbelt on macOS; a missing backend skips with a reason), on Linux and macOS in CI. It
  builds every jailed command through `jail_launch`, keeps every protected path outside every temp
  dir the jails grant, and gives each negative row three oracles: a marker the jailed command
  wrote proves it ran, the effect is absent afterwards, and the same attempt without the jail (the
  network open, for the connect row) has the effect. The rows are: a positive write inside the
  root; a positive `git add`/`commit`/`branch` inside a jailed task worktree; a seeded secret
  under a fake home is unreadable; a write outside the roots is refused;
  `<common>/hooks/pre-commit` and `<common>/config` cannot be written; a `config.worktree`, a
  rewritten `.git` file and a rewritten `commondir` never make dispatch's host-side git execute a
  planted `core.fsmonitor` (and `git_dirs` still returns the recorded dirs); a `connect` to a host
  listener fails under network `none` and succeeds when open; `/proc/<ppid>/environ` with a seeded
  key is unreadable (docker: `/proc/*/environ`); a `verifyCmd` run in the pod's envelope cannot
  write outside its worktree; a main checkout root is refused on landlock and has guarded hooks
  and config on docker and seatbelt; a jailed command reads a prepared cache entry and cannot
  write it (an unjailed control can); and a prepare launch reaches a listener while a hop under
  `network: none` does not.
- Real-docker tests build a `FROM alpine:3.20` + `apk add --no-cache git` image to prove a jailed
  commit in a linked worktree and `network none` against a host-side listener.

### Invariants

- A denied or timed-out request **MUST NOT** execute: `wait_for_approval` and
  `TOOL_APPROVAL_TIMEOUT` for an in-turn tool call, `resolve_waiting_approval` for a
  require_approval gate on a pod dispatch hop.
- Audit log entries **SHOULD NOT** be silently editable by the agent: the log carries a
  `seq`/`prev_hash` tamper-evidence chain (`docket log verify` detects an altered line), and there
  is no switch that turns auditing off (audit.spec.md).
- A high-risk pattern match **MUST NOT** be bypassed by allowlist status on any path docket
  controls. All three classes are fully enforced: a `git push origin main`-shaped command through
  `dispatch_tool`, which every pod-dispatch hop's calls pass, is gated by argument, by both the
  command classifier and the `high-risk-deploy` policy.
- A task rejected by a `pre_input` `block` policy **MUST NOT** be written to the pod's queue:
  `enqueue_task_once` **MUST** raise before the locked read-modify-write, not after. A `pre_output`
  `block` **MUST NOT** let a later pipeline step run; the hop that tripped it **MUST** be the
  task's last recorded hop when it fails.
- `pre_tool_call` **MUST NOT** be evaluated a second time by the hop-orchestration flow, and
  **MUST** be evaluated on every call through `dispatch_tool`. A call that reaches `dispatch_tool`
  and is not gated by `evaluate_tool_call` is the regression the gate's suite exists to catch.
- An `ask`-gated tool call **MUST NOT** execute before its approval resolves, and **MUST NOT** wait
  indefinitely: `wait_for_approval` **MUST** eventually return granted or denied, the latter for an
  explicit deny and for an unanswered timeout. A denied or timed-out call's handler **MUST NOT**
  run, proven by the handler's own execution flag, not just the returned decision.
- A `waiting_approval` dispatch task **MUST NOT** be resumable by anything other than a grant
  resolving that exact token (pod-dispatch.spec.md's claim-eligibility invariant); this spec owns
  the approval-store side only.
- A verify command matching a `HIGH_RISK_PATTERNS` class **MUST NOT** be started as a subprocess
  at all, provable by a test that asserts no process is launched for a high-risk command.
- A `HIGH_RISK_PATTERNS` match on a hop's output **MUST NOT** be described as blocking or redacting
  anything by itself: it is a `guardrail_check`-visible signal only, beneath whatever the installed
  policies decided.
- `ToolContext.sandbox="off"` (the default) **MUST** produce no sandbox marker, no jail argv and no
  jailed environment.
- `sandbox="auto"` resolving to a real backend that then fails to start (`OSError` on launch)
  **MUST NOT** run the command unsandboxed; it **MUST** be reported as a failure naming the
  backend, proven by asserting the command's own side effect never happens.
- A real exec jail **MUST NOT** weaken `resolve_within`'s containment for `read`, `write`, `edit`,
  `glob` and `grep`, and `resolve_within`'s containment **MUST NOT** be read as covering `bash`;
  the two are independent and both apply at once.
- A timed-out `bash` call under a real backend **MUST NOT** leave an orphan: no surviving process
  for landlock (a host-wide `pgrep` check), no surviving container for docker (a `docker ps`
  check); both are skipped, with a reason, on a host lacking the backend, never silently passing.
- A real exec jail's environment **MUST NOT** include the host environment (Exec sandbox 6).
  `sandbox="off"` **MUST** receive the host environment minus docket's credentials.
- `fetch` **MUST NOT** open a connection to a host absent from `FETCH_ALLOWED_DOMAINS`: the refusal
  happens before an opener is built, not merely before the content is returned.
- A redirect `fetch` follows **MUST NOT** land on a host absent from the allowlist: the allowlist
  governs the whole redirect chain, proven against a real HTTP 302 response.
- `fetch`'s response cap **MUST** be enforced with an announced truncation: a truncated result
  **MUST NOT** be indistinguishable from a response that was genuinely that short.
- `fetch` **MUST** be gated through `dispatch_tool` like every other built-in: a `pre_tool_call`
  policy that blocks a rendered `fetch` call **MUST** deny it before the handler runs. There is no
  second execution path and no second gate.

## Implementation

- `src/docket/core/tools.py`: `dispatch_tool`, `evaluate_tool_call`, `render_tool_call`,
  `ToolContext`, `ToolResult`, `ToolVerdict`, `Pregrant`, `screen_tool_result`, `builtin_registry`
  (the `bash`, `consult` and `fetch` registrations), the wait, park, pre-grant and `approve_task`
  handling, the `tool.*` audit entries
- `src/docket/core/security.py`: `SAFE_BINS`, `HighRiskClass`, `HIGH_RISK_PATTERNS`,
  `match_high_risk`, `classify_command`, `CommandVerdict`, `apply_workspace_isolation`,
  `disable_workspace_isolation`
- `src/docket/core/approval.py`: `approval_create`, `approval_get`, `approval_grant`,
  `approval_deny`, `approval_set_option`, `approval_options`, `wait_for_approval`,
  `approval_sweep_expired`, `create_pregrant`, `consume_pregrant`, `screen_rationale`,
  `APPROVAL_CHANNELS`, `APPROVAL_TOKEN_RE`, `APPROVAL_RATIONALE_MAX_CHARS`, `ApprovalError`,
  `ApprovalNoop`, `ApprovalConflict`
- `src/docket/core/policy.py`: `policy_files`, `policy_eval`, `policy_eval_detail`, `policy_test`,
  `normalize_policy`, `read_policy`, `validate_policy`, `install_policies`, `ToolCallFacts`,
  `PolicyHit`, `task_policies`, `TASK_POLICY_ID`, `denied_tools_document`,
  `task_policy_document`, the `when` and `plugin` predicate evaluation
- `src/docket/plugins.py`: the `docket.plugins` API (`PLUGIN_API_VERSION`, `predicate`,
  `ToolCall`, `PolicyContext`, `REGISTRY`)
- `src/docket/core/plugins.py`: `discover`, `evaluate`, `PluginError`, `LoadedPredicate`
- `src/docket/core/dispatch.py`: `enqueue_task_once` (the `pre_input` gate), `dispatch_task` (the
  `pre_output` scan, the profile check), `pod_approval_mode`, hop composition
  (`DOCKET_APPROVAL_MODE`, `DOCKET_APPROVAL_EXPIRES_AT`, the task restriction keys, the hop
  network), the verify, `run:` and prepare launches, `resolve_waiting_approval`
- `src/docket/core/runtime_driver.py`: `DOCKET_APPROVAL_MODE`, `DOCKET_TASK_DENIED_TOOLS`,
  `DOCKET_TASK_NETWORK`, `DOCKET_TASK_POLICIES`
- `src/docket/edges/adapters/docket_runtime.py`: `DocketDriver.run_turn` (isolation and network
  resolution, `isolation.refused`, `network.refused`, approval mode, `allow_commands`, project
  resolution, task policies, `make_non_dumpable`), `resolve_command_jail`
- `src/docket/edges/adapters/system.py`: `sandbox_availability`, `SandboxAvailability`,
  `landlock_available`, `seatbelt_available`, `docker_daemon_reachable`, `jail_launch`,
  `JailPolicy`, `landlock_argv`, `seatbelt_argv`, `seatbelt_profile`, `docker_run_argv`,
  `docker_kill`, `docker_image_has_git`, `git_identity_env`, `git_dirs`, `trust_worktree`,
  `task_environment`, `credential_names`, `run_command`, `make_non_dumpable`,
  `git_current_branch`
- `src/docket/edges/adapters/landlock.py`: `abi_version`, `plan_ruleset`, `socket_filter`,
  `DEFAULT_RO`, `DEFAULT_RO_FILES`, `DEFAULT_RW_FILES`
- `src/docket/jail.py`: the `python -m docket.jail` entry (`--rw`, `--ro`, `--refuse`, `--net`,
  exit 125)
- `src/docket/edges/adapters/toolbox.py`: `run_bash`, `resolve_within`, `PathEscapeError`,
  `ToolOutcome`, `glob_files`, `grep_files`
- `src/docket/edges/adapters/mcp_client.py`: the jailed stdio MCP launch
- `src/docket/edges/adapters/fetch.py`: `fetch_url`, the domain-locked redirect handler
- `src/docket/core/fleet.py`: `FleetSecurity`, `get_isolation_enabled`, `get_isolation_state`,
  `get_network_mode`, `get_sandbox_backend`, `add_read_only`, `remove_read_only`, `get_profile`,
  `set_profile`
- `src/docket/core/pod.py`: `PodSettings`, `effective_network`, `effective_read_only`, `pod_of`
- `src/docket/core/network_posture.py`: `network_posture`, `global_posture`
- `src/docket/core/profile.py`: `lights_out_violations`, `gather_facts`, `Facts`,
  `effective_profile`
- `src/docket/core/protected_paths.py`: `DEFAULT_PATTERNS`, `matches`, `command_files`
- `src/docket/core/reviewed_repos.py`: `review_code` and the reviewed digest
- `src/docket/core/prepare.py`: `LOCKFILES`, `linked_entries`
- `src/docket/core/pod_apply.py`: `REPO_REFUSED_COMMANDS`, `review_decision`, `apply_directory`
- `src/docket/core/pod_provisioning.py`: `provision_task_worktree`
- `src/docket/core/operator_contract.py`: `canonical_args_digest`
- `src/docket/core/archetypes.py`: `registry_for_role`
- `src/docket/core/agent_loop.py`: the `approval_parked` stop, `approval_parked_error`
- `src/docket/core/telegram.py`: the `/approve` and `/deny` handlers
- `src/docket/serve.py`: `GET /approvals`, `POST /approvals/<token>` and its channel set,
  `POST /tasks` (`trusted`), the expiry sweep, `/metrics` (`docket_policy_hits_total`)
- `src/docket/cli/_setup_sandbox.py`: `docket setup sandbox` and its verbs, `docket setup profile`,
  the `gates.*` audit entries
- `src/docket/cli/_setup_check.py`: `docket setup`'s security report and `securityGates`
- `src/docket/cli/_task.py`: `docket task approve`, `docket task deny`
- `src/docket/cli/_mcp.py`: `approvals_list`, `approvals_grant`, `approvals_deny`
- `src/docket/cli/_progress.py`: the `docket run` approval prompt
- `src/docket/cli/_pod_config.py`: `docket pod check`, `docket pod policies`,
  `docket pod validate`, `docket pod update`
- `src/docket/cli/_agents.py`: `docket init` (policy install, the repository shell refusal)
- `src/docket/cli/_run.py`: `docket run`'s re-apply of a repository directory
- `src/docket/cli/_service.py`: `docket start` (`make_non_dumpable`)
- `src/docket/cli/_status.py`: `docket status`'s profile and network lines
- `src/docket/kernel/home.py`: the `Home` members `tool_approval_timeout`,
  `tool_approval_poll_interval_s`, `approval_timeout`, `fetch_allowed_domains`,
  `fetch_max_response_bytes`, `fetch_timeout_s`, `policies_dir`, `plugins_dir`, `approvals_dir`,
  `sandbox_docker_image`, `jail_tmp_dir`, `prepare_cache_dir`, `pod_config_dir`
- `src/docket/templates/policies/`: the six shipped policy templates
- Tests that pin this spec: `tests/integration/test_pre_tool_call_policy.py`
  (`TestRenderToolCallShape`, `TestBlockDestructiveShippedTemplate`,
  `TestDispatchToolApprovalRouting`), `tests/integration/test_policy_engine.py`,
  `tests/integration/test_sandboxed_exec.py` (`TestSandboxOffIsUnchanged`,
  `TestHonestReportingIsDeterministic`, `TestChokepointWiring`, `TestRealLandlockJail`,
  `TestRealDockerJail`, `TestGitMetadataTheHostLaterRuns`, `TestJailedCommit`),
  `tests/integration/test_docket_driver.py` (`TestIsolationWiring`),
  `tests/integration/test_jail_landlock.py`, `tests/integration/test_escape_matrix.py` (the
  `release-journey` CI job), `tests/integration/test_envelope_commands.py`,
  `tests/integration/test_network_lockdown.py`, `tests/integration/test_lights_out_profile.py`,
  `tests/integration/test_task_credentials.py`, `tests/integration/test_process_non_dumpable.py`,
  `tests/unit/edges/adapters/test_fetch.py` (`TestDomainAllowlist`, `TestRedirects`),
  `tests/unit/core/test_approval.py`
