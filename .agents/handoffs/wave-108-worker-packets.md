# Wave 108 worker packets — close every carried item (no phase)

Coordinator: the session that closed Phases 41 and 42 on 2026-10-13. The owner asked to close
every item carried out of every phase and to clean the roadmap. A read-only verification
(2026-10-13, HEAD `7e28ad07`) found the items below still open; everything else carried in
ROADMAP is closed or a trigger-deferred decision. Base commit: the Wave 108 claim commit on
`develop` (`git log -1 --format=%h -- .agents/handoffs/wave-108-worker-packets.md`).
Worktrees and branches: `../rack-cli-wt/w108-<n>`, branch `w108-<n>`. All four run in parallel;
the function-level ownership below is what makes that safe. Symbols drift: re-locate every one
with `rg -n` before editing.

| Card | Owns | Spec versions |
| --- | --- | --- |
| W108-1 | `cli/_task.py` (`task cancel`, `task diff`/`_worktree`), the cancel path in `core/` it needs | cli-interface 2.7.0 |
| W108-2 | `edges/adapters/system.py` jail grants (`_GIT_WRITABLE_PARTS`, `_mount_dirs` and its helpers), `src/docket/jail.py` if needed, `tests/integration/test_escape_matrix.py` | security-gates 0.51.0 |
| W108-3 | `cli/_exec.py`, `cli/_harness_answers.py`, `edges/adapters/docket_runtime.py::_pod_cache_dir` | harness-mode 1.10.0 |
| W108-4 | `core/profile.py`, `core/dispatch.py::_hop_env` (rename only), `cli/_inbox.py` question rendering | operator-loop 1.7.0 |

Nobody but W108-4 edits `core/dispatch.py::_hop_env`; nobody but W108-2 edits the jail grant
functions in `system.py`; W108-3 may *call* `system.trust_worktree`/`jail_launch` unchanged.

## 0. Rules for every worker

**Exactly §0 of [wave-98-worker-packets.md](wave-98-worker-packets.md)**, with `w108-<n>` in
place of `w98-p40-<n>`, last-updated 2026-10-13, and this base commit. Read that section and your
own packet only. Additions:
- **Prose docs:** `README.md`, `docs/*.md` prose and `docs/adr/` are the integrator's. List every
  sentence your change makes false as `file:line` in the return (notably
  `docs/SECURITY-SIMPLE.md` "What is still open").
- Real-kernel tests go in `tests/integration/` with a `SUBJECT` and skip cleanly when the backend
  is absent. Run `scripts/maint/pytest-without-sandbox.sh -q` as well as the plain suite.
- Return: decision, files changed, RED reason on the base, gates with exit codes, the CHANGELOG
  line you would write, now-false prose locators, later follow-ups.

## W108-1 — a parked task can be cancelled; `task diff` uses the trusted git dirs (Sonnet)

1. **Cancel a `waiting_input` task.** Today `docket task cancel <id>` on a task parked in
   `waiting_input` exits 1 "Nothing is in flight to cancel" (`cli/_task.py`, `_LIVE_RUN_STATES =
   ("queued","running")`); the only exit is `task answer --decline`. Make `task cancel` cancel a
   parked task (`waiting_input`, and `waiting_approval` if it has the same gap — check and say):
   the task ends `cancelled` (whatever terminal state an operator cancel already writes for a live
   run; reuse it, do not invent one), its pending question/approval is cleared so `docket inbox`
   no longer lists it, an audit entry is written the same way a live-run cancel writes one
   (channel `cli`), and no hop runs. Reuse the existing finalize/cancel helpers; locate them in
   `core/runs.py`, `core/answers.py`, `core/dispatch.py` (do not touch `_hop_env`).
   RED: a test that parks a task (fixture state, no model), runs `task cancel`, and asserts exit
   0, the task's terminal state, the inbox empty, one audit entry.
2. **`task diff` trusts the recorded git dirs.** `cli/_task.py::_worktree`/the diff path calls
   `system.git_diff(path, ...)` without `system.trust_worktree(...)`, so git reads the `.git`
   file the agent could rewrite. The task record already holds `gitDir`/`commonDir`; register
   them before any git call on a task worktree from the CLI (every CLI-side git call on a task
   worktree, not only diff: grep `_task.py` and `cli/` for `git_` calls on `wt["path"]`). The
   printed hint `git -C <path> diff` should become a command that names the recorded dirs
   (`git --git-dir=<gitDir> --work-tree=<path> diff ...`) or be dropped if that is unwieldy; say
   which. RED: a test that rewrites the worktree's `.git` file to point elsewhere and asserts
   `task diff` still diffs the recorded repository (or refuses), never the planted one.
Spec: `specs/api/cli-interface.spec.md` 2.7.0 (and `cli-json-shapes` 1.32.0 only if a JSON field
changes).

## W108-2 — the Landlock jail stops granting every ref (Sonnet)

Today `edges/adapters/system.py` grants `objects`, `refs` and `logs` of the common git dir
read-write (`_GIT_WRITABLE_PARTS`), so an isolated agent can move any branch (`main`, a tag,
another task's branch) by writing a loose ref, with no code run. Narrow it:
- grant `refs`/`logs/refs` write **only beneath the task branch's own directory** (read the
  branch name the task worktree is on — dispatch names it `docket/<pod>/task-<id>`; verify in
  `core/pod_provisioning.py`), plus whatever git needs to commit on that branch from a linked
  worktree: the worktree's own gitdir (HEAD, index, logs/HEAD — already granted), `objects`, and
  the ref's lock file (created beside the ref, so the grant is the ref's parent directory —
  if that parent is shared with sibling task branches, prefer making it per-task, e.g. the
  grant covers exactly `refs/heads/docket/<pod>/` only if no narrower option works; measure and
  say which).
- `packed-refs` stays read-only; a git operation that needs to rewrite it fails inside the jail
  (fail closed) — state that in the spec.
- When the root is not a task worktree (no task branch known), grant no ref writes at all.
- Extend `tests/integration/test_escape_matrix.py` with rows: jailed `git update-ref
  refs/heads/main <sha>` fails; writing `refs/tags/x` fails; writing another task's branch ref
  fails (or, if the measured grant is the pod's directory, document that row as the accepted
  residue and assert main/tags only); a commit on the task's own branch inside the jail still
  succeeds. RED on the base for the main/tag rows.
- Keep the `.git`-directory-in-root refusal (exit 125) exactly as is.
Spec: `security-gates.spec.md` 0.51.0. Docker/Seatbelt paths: say whether they have the same
gap; do not change them unless the change is a one-line equivalent (Seatbelt rows run only in
macOS CI; you cannot run them here, so do not touch Seatbelt without a test that runs on Linux).

## W108-3 — `docket exec`: a cache dir, a per-run approval wait, no stray reader thread (Sonnet)

1. **Cache dir.** `docket exec` agents are `harness-<hex>` with no pod, so
   `docket_runtime._pod_cache_dir` returns None and the jail gets no cache root or HOME. Give an
   exec run a cache dir under the caller's `DOCKET_HOME` (created 0700; e.g.
   `<DOCKET_HOME>/cache/harness` or per agent — choose the one that survives across runs of the
   same workspace so a uv/pip cache is reused, and say why), passed the same way a pod's is.
   Never under the setup home (contract 1.2 reads it read-only). RED: a unit/integration test
   that the exec path hands `jail_launch`/`task_environment` a non-None cache dir.
2. **Approval wait per run.** `cli/_harness_answers.py::wait_budget` assigns the module global
   `config.TOOL_APPROVAL_TIMEOUT` and restores it. Pass the wait through the run instead (the
   `env` dict `run_turn` receives already carries `DOCKET_APPROVAL_MODE`; follow that seam to the
   reader of the timeout) so nothing global is mutated. RED: a test that asserts the global is
   untouched during a run and the run still honours the requested wait.
3. **Answer reader.** `_pump` reads `sys.stdin` on a daemon thread that is never joined and
   checks `stop` only between lines. Replace with a reader that stops when the run ends
   (`selectors`/`select` on the stdin fd with a short timeout, checking `stop`; POSIX only is
   fine since stdin is a pipe from the caller) and is joined before exit. RED: a test that a run
   ending with stdin still open leaves no live reader thread.
Spec: `harness-mode.spec.md` 1.10.0. Do not change the wire contract (schemas, fixtures).

## W108-4 — profile uses a public hop-env; the inbox indents a multi-line question (Haiku-sized, Sonnet)

1. `core/profile.py` calls the private `dispatch._hop_env`. Rename it to a public
   `dispatch.hop_env` (update every caller; it is in `core/dispatch.py` and maybe tests) — no
   behaviour change. A guard test is not needed; ruff/mypy are the evidence.
2. `cli/_inbox.py` renders `f"    Q: {item.question.message}"`, so lines after the first start
   at column 0. Indent every continuation line under the first (align with the text after
   `Q: `), and check the same for options/brief lines rendered beside it and for
   `core/notify.py`'s plain renderers if they share the shape (say what you found; change only
   the CLI view unless notify has the same defect, then fix it there too). RED: a test with a
   three-line question asserting every line is indented. If a golden changes, explain it.
Spec: `operator-loop.spec.md` 1.7.0 (or the spec that owns the inbox view — check
`specs/README.md`).

## Second batch (opened after a second verification of the items parked at the Phase 26 close)

Base: the commit that adds this section (`git log -1 --format=%h -- .agents/handoffs/wave-108-worker-packets.md`).
Same §0 rules. Ownership: W108-5 owns `serve.py::_handle_post_dispatch`, `cli/_agents.py::_create_workspace`
text, `scripts/smoke_workflow.py`, `core/runs.py::prune_terminal` and its one caller in the `task prune`
command (W108-1 owns the rest of `cli/_task.py`; touch only the prune function). W108-6 owns
`cli/_setup_check.py`.

| Card | Owns | Spec versions |
| --- | --- | --- |
| W108-5 | the four small fixes below | http-api / control-plane spec minor for (1); cli-interface 2.7.1 for (4) (W108-1 takes 2.7.0; if yours merges first the integrator renumbers) |
| W108-6 | `docket setup --fix --json` parity | the spec that owns `setup --fix` / doctor (check `specs/README.md`), minor |

## W108-5 — four small parked fixes (Sonnet)

1. **Webhook and a broken bound pipeline.** `POST /dispatch/<project>` (`serve.py::_handle_post_dispatch`)
   calls `effective_pipeline`/`resolve_variables` and catches only `VariableError`; a `DispatchError`
   from `_pod_settings`/`_bound_pipeline` escapes, so the client gets a dropped connection and the
   server a traceback. Map it like `POST /tasks/<p>` does (`serve.py`, the `DispatchError` -> 404/400
   mapping there): no pod -> 404, otherwise 400 with the error text. RED: an HTTP test against a pod
   whose bound pipeline file is missing.
2. **Retired HEARTBEAT instruction.** `cli/_agents.py::_create_workspace` writes into AGENTS.md
   "Before starting multi-step work, write it to {HEARTBEAT_FILE} ...". Dispatch maintains the
   ledger mechanically and the pod templates dropped this line (`core/pod_provisioning.py`
   `POD_TEMPLATE_VERSION` comment). Delete it; if a template/contract version gates existing
   workspaces, bump it the way the pod templates did. Golden diffs must be explained line by line.
3. **Smoke script.** `scripts/smoke_workflow.py` still runs `pod <p> set-verify ...`, a removed
   command. Use the current verb (`docket pod set ...` / `pod update` — check `docket pod --help`).
4. **`task prune --traces --pod X` deletes every pod's run records.** `core/runs.py::prune_terminal`
   takes no project. Scope it to the pod when one is given (and say what an unscoped call does —
   keep it fleet-wide only if the spec says so). RED: two pods' terminal runs, prune one, the
   other's survive.

## W108-6 — `setup --fix --json` reports every check the text report runs (Sonnet)

`docket setup --fix` (`cli/_setup_check.py::run_check`) runs ~20 checks for the text report;
`_check_json` builds the JSON from a subset and leaves out nine (model registry entries, archetype
overlay, schedule config, provider coverage, exporters, guardrail policies, pod config overlays, pod
sync, runtime contract), so `healthy: true` can coexist with text issues. Make each check one
function returning data (name, status, issues, fixed) that both renderers consume, so the JSON and
the text cannot disagree; add the missing checks to the JSON under stable keys (document them in
`cli-json-shapes.spec.md`, minor bump; W108-1 may take 1.32.0 — use 1.33.0). RED: a home with a
broken pod config overlay where the text report counts an issue and the JSON says healthy.
Keep each function under the 150-line span ceiling.

## Third batch — W108-7 (base: the commit that adds this section)

Same §0 rules. Owns `src/docket/core/security.py` (`SAFE_BINS` neighbours, `classify_command` and
its helpers) and `tests/unit/core/test_security.py`. Spec: `security-gates.spec.md` — W108-2 takes
0.51.0, you take 0.52.0 (the integrator renumbers if you merge first).

## W108-7 — the classifier sees through wrappers and deleting flags (Sonnet)

Measured 2026-10-13 at `ad2172f5`: with isolation off, `rm` asks (not on `SAFE_BINS`), but
`env rm -rf x` and `echo x | xargs rm` are classified by `env`/`xargs` and **allowed**, and
`find . -delete`, `find . -exec rm {} +` and `awk 'BEGIN{system("rm -rf x")}'` are allowed because
`find`/`awk` are allowlisted. The docs promise a dangerous operation not on the allowlist asks; these
are that operation behind an allowlisted name.
1. **Wrappers.** For a segment whose binary is a command wrapper (`env` after its `VAR=value` and
   option arguments, `xargs` after its options, plus `nice`, `nohup`, `timeout <dur>`, `time`,
   `command`, `stdbuf`, `setsid` if present — list what you handle), classify the wrapped command
   exactly as if it were the segment (recursively, bounded). `env` alone or `env VAR=x` with no
   command stays allowed. `xargs` with no command runs `echo`: allowed.
2. **Deleting or executing flags of allowlisted bins.** `find` with `-delete`, `-exec`, `-execdir`,
   `-ok`, `-okdir`, `-fprint`, `-fprint0`, `-fprintf`, `-fls` asks (or, for `-exec`/`-execdir`,
   classify the embedded command like a wrapper if that is simple and bounded; asking is acceptable).
   `awk`/`gawk` program text containing `system(` or a `|` pipe to a command or `print >`/`>>` to a
   file asks. `sed` with `e` command or `-i` outside the workspace roots: measure; if handling it is
   not bounded, leave it and list it.
3. Keep: interpreters (`python3`, `node`, `make`, …) stay allowlisted — the allowlist is not a
   containment boundary and the spec says so (add that sentence to the requirement text: without
   the sandbox, an allowlisted interpreter can write or delete anything the operator can; the
   sandbox is the boundary). `tee`, `cp`, `mv`, `mkdir`, `touch`, `ln` stay allowed (ordinary
   development writes); say so in the same spec sentence.
4. Inside a working jail the allowlist stands down except for high-risk classes (P41-6): check
   your change does not make a jailed `find -delete` inside the roots ask (it must not; the jail is
   the boundary there). RED on the base: `env rm -rf x`, `echo a | xargs rm`, `find . -delete`,
   `awk 'BEGIN{system("rm x")}'` each currently `allow` unjailed; after: `ask`. Plus green rows that
   `env FOO=1 pytest`, `xargs grep foo`, `find . -name '*.py'` stay `allow`.
List every now-false prose sentence (`docs/SECURITY-SIMPLE.md`, README known limits) as file:line.

## Fourth batch — W108-8 (base: the commit that adds this section)

Same §0 rules. Owns `edges/adapters/system.py::_mount_dirs`, `seatbelt_profile`, `_docker_prefix`
(and a helper beside `_task_ref_dirs`, which it reuses unchanged), `tests/unit/edges/adapters/test_system.py`
rows for those, and `tests/integration/test_escape_matrix.py` docker/seatbelt rows. Spec:
`security-gates.spec.md` 0.53.0.

## W108-8 — Docker and Seatbelt narrow ref writes the way Landlock does (Sonnet)

W108-2 (merged, security-gates 0.52.0) made the Landlock jail grant ref/reflog writes only under
`refs/heads/docket/<pod>/` of a linked task worktree (`_task_ref_dirs`). Docker and Seatbelt build
their mounts from `_mount_dirs` (rw roots + git dirs, then read-only guarded overlays), so a
jailed agent there can still `git update-ref refs/heads/main <sha>` or write a tag.
1. For a root that is a **linked task worktree** (the same test `_task_ref_dirs` applies: it
   returns a non-empty list), add the common dir's `refs`, `logs/refs` and `packed-refs` to the
   read-only overlays, and re-open the task's ref dirs (`_task_ref_dirs(common, gitdir)`)
   read-write **after** them: `_mount_dirs` grows a third list (e.g. `reopen`) emitted last.
   Seatbelt: SBPL's last matching rule wins, so emit `(allow file-read* file-write* (subpath …))`
   for each reopened dir after the `(deny file-write* …)` lines. Docker: a nested bind mount
   listed after its parent overrides it, so `-v ref_dir:ref_dir` after `-v refs:refs:ro`.
2. A linked worktree that is **not** a task worktree: refs read-only, nothing reopened (as in
   Landlock). A **main checkout** root (a `.git` directory — Landlock refuses it, Docker and
   Seatbelt run there and are the documented way out): unchanged, refs stay writable; say so in
   the spec (the operator's own checkout, the agent commits on its branch).
3. Tests: unit rows for the argv/profile ordering (no docker or sandbox-exec needed). Escape
   matrix rows for docker (this host has docker; skip cleanly without a daemon or without git
   in the image — see how existing docker rows skip): jailed `git update-ref refs/heads/main`
   and `refs/tags/x` fail; a commit on the task's own branch succeeds. Seatbelt rows the same
   way, skipped off darwin (they run in macOS CI). RED on the base for the docker main/tag rows.
