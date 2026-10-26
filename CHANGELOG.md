# Changelog

All notable changes to **docket** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **One escalation record, one `resolve` verb (D-72, ADR 0032, Phase 51).** Every pause (a gated
  tool call, a consult, an `input` step, a gate, a changed check) is one durable `Escalation`
  record written by `platform/store.py`. `docket task answer <escalation-id> --option <id>`, `POST
  /escalations/<id>`, the MCP `resolve` tool, Telegram `/answer` and the A2A facade all call the
  same `resolve`, and `GET /escalations?since=` and `docket inbox` list them. The trace carries one
  event family (`escalation_asked`, `escalation_delivered`, `escalation_resolved`,
  `escalation_expired`, `escalation_decided`) and one renderer serves the inbox, `task show`, the
  progress view, Telegram and notifications, with option ids always present. Breaking for a client
  of the retired shapes: contract `operator-v2`, operator API 7.0.0, MCP server 2.0.0, Telegram
  integration 5.0.0, operator loop 3.0.x.
- **Per-task autonomy (`L3|L4|L5`).** `docket task add --autonomy` and `autonomy` on `POST /tasks`
  say what happens to a pause when nobody is there; the level only narrows and the pod profile is
  the ceiling. `consultMode: decide` answers a consult in the turn with the model's recommendation;
  `lights-out` requires it. The table is the `kind: autonomy` document.
- **A2A facade.** `POST /a2a` and `GET /.well-known/agent.json` expose tasks and their pending
  escalation to an A2A client, over the same records and `resolve`.
- **The live smoke refuses a world inside a git work tree** and can run with the jail on.

- **The task is one typed record behind one store (D-70, Phase 49).** `TaskRecord` and `HopResult`
  are pydantic models; a pod's queue is read and written only through `TaskRepository` over
  `JsonTaskStore`, and every CLI command, HTTP route, Telegram handler, MCP tool, hop and test reads
  attributes instead of `dict.get`. The 19 closures that wrote the queue by hand are gone, as are
  `read_tasks`, `_normalize_task`, `hop_record` and `hop_from_record`. The stored JSON is unchanged
  except for the keys listed under Removed; a queue written before them still loads.
- **Answers, consult answers, expired-question sweeps and pre-grants now re-sync the
  `HEARTBEAT.md` ledger too, and `hops` reads and writes the task as a `TaskRecord`.** The
  claim's gate override reaches `dispatch_task` as its `gate_override_index` argument instead of a
  key put back on a copy of the task (pod-dispatch spec 10.1.1).
- **Every write of a pod's queue re-syncs the `HEARTBEAT.md` dispatch ledger.** `retry_task`,
  `unblock_pod`, the stale sweep and reclaim, enqueue and the stored worktree and prepare records
  now go through `TaskRepository`, which regenerates the ledger after the write; before, only the
  claim, hop persist, finalize, claim refresh and a few cancellations did, so a retry left a stale
  entry until the next sync (pod-dispatch spec 10.1.0).
- The `pydantic` floor is `>=2.12`: a task record leaves an unset key out of its stored JSON with
  `Field(exclude_if=...)`, which 2.12 introduced.
- **`docket init` turns workspace isolation on where the machine can jail (D-67).** When no
  choice is recorded and Landlock or Seatbelt is detected, init records it on and audits
  `gates.isolate` as `on (detected <backend>)`. Without a backend it records nothing and says so;
  a recorded choice is never changed. `docket setup sandbox on|off` is unchanged.
- **Workspace contract v5: no seed names a daily log.** `WORKFLOW_AUTO.md`, `MEMORY.md` and
  `HEARTBEAT.md` told an agent to keep `memory/YYYY-MM-DD.md`, which docket never reads, writes or
  composes. The instruction is gone and `CONTRACT_VERSION` is 5, so `docket setup --fix`
  re-seeds a v4 `WORKFLOW_AUTO.md`; `memory/` stays an empty directory.
- **The tree is organised by context (ADR 0030, D-66).** `src/docket/` is `kernel`, the context
  packages and `interfaces/`; no module is over 700 lines. The oversized modules were split by
  `scripts/maint/refactor/move.py`; the turn loop's state became budget, compaction and tool-step
  collaborators (`agent/loop_*.py`); the HTTP handler became a route table over per-resource
  modules with one bearer check (`interfaces/http/routes/`). `bootstrap.py` builds the store,
  sandbox, driver, channels, app and server from a `Home`. Phase 47 then layered the contexts
  (`platform < governance < agent < models < observability < pipeline < teams < sandbox <
  operator < tasks < hops`): each module moved to the context whose data it reads, an upward
  import is a violation, and other contexts are reached through public names and ports in
  `kernel/ports.py` instead of private names. Function-local `docket.*` imports fell from 209 to
  1 (a named cycle), and the import-contract baseline from 748 lines to 1 (the Telegram adapter).
  The tests mirror the contexts (`tests/integration/<context>/`), each helper has one name, no
  test file imports another or patches another module's private name, and every test file passes
  run alone. The refactor tools (`scripts/maint/refactor/`, `refactor_gate.sh`, libcst) are
  deleted; `tests/architecture/` is the record. Every golden is byte-identical.
- **An authored configuration file has one form, the `kind:` short form.** A role, pipeline or
  policy file written in the canonical form (`id:`/`role:` steps, `applies_to`/`match`/`action`
  policies) is refused with exit 2 and a message naming the short key to write; the canonical
  form is only what docket persists. The short form gained the spellings only the canonical form
  had (`parallel:` groups, `archetype` and `when` on a step, `verify: {command, timeout}`,
  `gate: {external, timeout, exitMap}`). A file without `kind:` still loads where its location
  or the command names the kind.
- **`maxReworkCycles` is refused beside a bound pipeline** instead of being accepted and ignored:
  `pod set maxReworkCycles` on a pod with a pipeline, `pod set pipeline` on a pod that stores one,
  and a `pod.yaml` that declares both exit 2. `pod show` reports the pipeline's own bounds.
- **The baseline policies read the parsed command.** A rephrased command no longer slips past
  them: options before the verb (`kubectl -n prod apply`), quoting (`"rm" -rf`), short and long
  flags (`git push -f`), wrappers (`env`, `xargs`, `find -delete`) and write targets by any program
  (`ln -sf`, `install`, `dd`, `tee -a`) are seen. Measured on a 310-row corpus
  (`tests/fixtures/policy-corpus/corpus.yaml`): 82 tool calls that passed now ask, none is
  weaker, and the rows still allowed carry one of five named limits in the security spec (opaque
  code in an allowlisted interpreter with isolation off is the main one).

### Fixed

- **The MCP `queue` tool no longer says only a blocked task can be retried.** `retry_task_id`
  re-queues a `blocked` or a `failed` task, as `docket task retry` does; the refusal now reads
  "not a failed or blocked task" (mcp-server spec 1.9.6).
- **A task run under `docket run --pipeline <file>` keeps that pipeline.** Its claim recorded
  source `default` and nothing else, so answering a question the file's pipeline parked looked up
  the step in the pod's pipeline and failed with "not parked at step", and the next claim ran the
  pod's pipeline. The claim now records source `file` and keeps the spec as `pipelineSpec`; the
  answer and a later claim with no file replay it, and a later claim under a file runs that file.
- **An idle sweep tick writes no run record.** `docket start --dispatch` created one run per pod per
  30 s tick whether or not it had anything to claim: 85,540 empty records and 47 MB in a week on a
  real home, with rewrites that missed the 10 s store lock. A pod with nothing to claim is skipped.
- **`docket stop` no longer advises `kill -9` for a service that is still exiting**: it now outwaits
  the service's own wait for abandoned sweeps.
- **Tests can no longer write into the developer's `~/.docket`**: a thread started without the
  test's context fell back to the real home (eight test pods were found there).
- **A verdict a step's `on:` map names is routed, a passing one included**, as pipeline-format
  says; the mechanical and external gates already did, the verdict gate let a passing value
  advance first. The `intake` recipe no longer needs a placeholder marker for it.
- A resuming sweep (`docket start --dispatch`) re-claimed a task it had just refused, in a loop
  with no pause, until the refusal was cleared: one `dispatch_refused` task (isolation off under a
  `lights-out` profile) wrote 2,164 audit and trace entries in 3 seconds and held a core at 85%.
  A task is now claimed at most once per dispatch run. Found by the Phase 46 real run; the loop
  was already in `develop`.

### Added

- **`when.command` in a policy** matches the parsed command: `program`, `verb` (found past
  options), `args` (short and long spellings, globs) and `writes` (redirect targets and the
  operands of the programs that write), on every segment after unwrapping. `matches` stays for
  text with no structure. The classifier's high-risk classes are also found past options and
  quoting, and name more deploy and secret tools (`tofu`, `podman`, `flyctl`, `vercel`, `gh
  release`, `cargo publish`, `twine`, `aws ssm`/`secretsmanager` writes).
- **Six more secret shapes are redacted** by `secret-pii-redact` and by the trace redactor:
  GitHub `github_pat_`/`ghu_`/`ghr_` tokens, AWS `AKIA`/`ASIA` key ids, `*_PASSWORD=` assignments,
  JWTs, private-key blocks and `Authorization` credentials.
- `scripts/maint/live-dispatch-baseline.sh` records one real dispatch through the HTTP API (task,
  trace, diff, raw trace files) so a phase's real run and a before/after comparison use one
  command.
- `scripts/maint/measure_dead_code.py` counts the definitions no file names, those only a test names
  and the groups of identical function bodies under `src/docket`; `tests/guards/test_dead_code.py`
  holds the three totals to `dead_code_baseline.txt`, which may only shrink.
- **A model's limits come from the provider's `/models`.** `setup provider add` and, once a day,
  the `docket start --dispatch` sweep read what each operator-registered provider publishes
  (Anthropic `max_input_tokens`/`max_tokens`, the gateway's `context_window`/`max_tokens`,
  llama.cpp `meta.n_ctx`, OpenRouter `context_length`/`top_provider.max_completion_tokens`) and
  record it with the date in `provider-models.json`. A request's window and output cap resolve
  per limit as declared (a document's row or `--ctx`/`--max-tokens`) > observed > unknown; a
  value the provider does not publish (absent, null or 0) is `unknown`, never filled in.
  `setup provider show` prints WINDOW/OUTPUT with each limit's source and `pod show --json`
  carries `contextWindowSource`/`maxTokensSource`/`observedAt`. Found by the joint run: 49 of 49
  `request_fit` events said `unknown_window` for gateway models.
- **A change that edits its own check goes to a person.** When a task's pipeline ends `done` and
  its diff (committed, uncommitted and untracked) touches a protected path, the task parks
  `waiting_approval` with an approval of kind `check_changed` and `checkChanged: [paths]`, under
  every profile, lights-out included; approving ends it `done`, denying fails it with
  `failureKind: "check_changed"`. Protected paths are the defaults (lockfiles, `package.json`,
  `pyproject.toml`, `Cargo.toml`, lint/type/test configuration, `.docket/`, CI workflows), the
  team's `protects:` in `pod.yaml` (adds only), and every tracked file a gate, `verifyCmd` or `run:`
  step names. The review digest now also covers the contents of the files a reviewed command
  names, so `pod update` and `docket run` ask again after such a file changes; every existing
  approval is asked once more (D-57).
- **docket prepares the worktree it makes for a task (API version 6).** Before a claimed task's
  first hop, dispatch runs the task's `prepare`, else the team's `prepare:` in `pod.yaml`, else the
  command for the lockfile at the worktree root (`npm ci`, `pnpm install --frozen-lockfile`,
  `yarn install --immutable`, `uv sync --frozen`, `poetry install`, `cargo fetch`); `""` or
  `none` turns it off. With isolation on the install runs in the jail with the network open for
  that launch only; hops and gates keep the pod's network. `node_modules` is kept once per
  codebase and lockfile under `~/.docket/cache/prepare/` (three entries per codebase) and linked
  into each worktree, read-only inside the jail. A failed install fails the task with
  `failureKind: "prepare"` and no hop; a `prepare` trace event records command, source, cache
  hit, seconds and exit. A team's or derived command is reviewed as kind `prepare`. Found by
  A sibling project's first code run through a team: a fresh worktree had no `eslint` or `vitest`.
- **The sandbox can read the operator's toolchain.** `docket setup sandbox read add <path>`
  grants every jail read and execute (never write) on a path such as a version manager's Node
  or the system Python's user site; `read remove` drops it, and `docket setup sandbox --json`
  lists them as `readOnly`. A pod's `readOnly` setting keeps only some of them (`none` keeps
  nothing) and can never add a path. `add` refuses docket's home, the operator's home and any
  ancestor of either. Found by the Phase 44 real rerun: `npm`/`npx` under `~/.nvm` exited 126
  inside the jail and `pytest` in the user site could not load, so no JS or user-site Python
  gate could pass with isolation on.
- **A task's usage carries its cache figures.** `task["usage"]` (on `GET /tasks/<pod>` and
  `GET /tasks/<pod>/<id>`) sums `cached` and `cacheWrite` beside `input` and `output`, as each
  `byModel` entry already did, so a consumer counts new tokens as `input - cached + output`
  where it reads the totals.
- **The operator controls pod memory (P44-8).** `docket pod memory list [--status] [--json]`,
  `approve`, `refuse --reason`, `revert` and `reset [--yes]`, each audited; `docket inbox` lists
  pending memory entries under "Needs you" with the command that approves or refuses each one.
- **Pod memory (P44-7, ADR 0028 point 7).** A step's reply may end with a `## Memory` section of
  typed facts (`generated`, `command`, `pitfall`, `convention`). docket verifies each one itself:
  a `generated` path that exists at the task's commit and a `command` whose exit status is in the
  task's trace are accepted; `pitfall` and `convention`, and everything from a task that called
  `fetch`, wait for the operator; instructions, URLs and override wording are refused. Accepted
  facts are stored once per pod and reach every later prompt of that pod last, behind an
  untrusted-data frame. Every change is traced (`memory_update`) and audited.
- **Prompt-cache markers for Anthropic models (P44-9).** A request to a model whose id starts with
  `claude` (directly or behind a gateway) marks `cache_control` on the system message and the last
  message; every other model's request is byte-unchanged.
- **Measurable without reconstruction (P44-10).** Each `llm_call` trace event carries `request`,
  the request's size by part (system, tools, tool results, assistant, user) in bytes and estimated
  tokens, counted by the adapter from the body it sent; a task's `byModel` carries `cached` and
  `cacheWrite`; task reads carry `tokenBudget`, the per-step budget docket enforces (API 5,
  additive).
- **A replay bench for context and budget work (Phase 44, P44-1, ADR 0028).**
  `scripts/maint/context_replay.py` reports calls, sent, cached and counted tokens per recorded
  step under the old and new budget rule, re-projects requests through named policies (an
  estimate, labelled), and anonymizes recorded steps into shape-preserving fixtures
  (`tests/fixtures/context-replay/v1`).
- **An addressable task (Phase 43, P43-1, ADR 0027).** `POST /tasks/<pod>` and `docket task add`
  take `externalRef`, `idempotencyKey`, `baseRef`, `pipeline`, `gate`, `maxTokens` and
  `restrictions`, stored verbatim on the task. A repeated `idempotencyKey` returns the queued task
  (`200`, `created: false`) and enqueues nothing; a new task answers `201`. A restriction that
  would widen the pod's limits is `422`. `GET /tasks/<pod>?externalRef=&status=` filters and
  `GET /tasks/<pod>/<id>` returns one record.
- **A task's worktree starts from its `baseRef` (P43-2).** A ref that cannot be honoured fails the
  task at claim with `failureKind: base_ref` and no hop, instead of running in place; no
  directory or branch is left behind. A `baseRef` starting with `-` is refused.
- **Pipeline and gate per task (P43-3).** A task's `pipeline` names a pod-local
  `pipelines/<name>.yaml` or a shipped recipe; an unknown name fails the task with
  `failureKind: pipeline` before any hop. A task's `gate` runs after the last implementer step's
  own gate and routes through the same `on:` labels. The claim records `pipelineSource` and
  `gateApplied`.
- **Task restrictions and a token budget reach the live hop (P43-4).** `deniedTools`,
  `network: none` and block-only `policies` narrow every hop of the task and are audited as
  `policy_id='task-restriction'`; `maxTokens` caps the task's measured usage and fails it with
  `failureKind: budget`. Enqueue and the hop validate task policies through one function.
- **`hop_started` and `hop_finished` trace events (P43-5).** One pair per hop: the start names
  the planned model, the finish the served one with usage, verdict, gate and duration. Hop
  records carry `model` and `provider`, and a settled task carries `usage` keyed by served model.
- **A pod is readable over HTTP (P43-6).** `GET /pods` lists the dispatchable pods with their
  queue counts; `GET /pods/<p>` returns the `pod show --json` report plus `profile`,
  `pipelineSource` and `repoConfigDir`; `POST /pods` with `ensure: true` answers `200`
  `created: false` on an existing pod and touches nothing. The report readers moved from
  `cli/_pod_show.py` to `core/pod_report.py` (same shape).
- **Several teams in one repository (P43-7).** `.docket/teams/<pod>/` holds one team per pod:
  `docket init --name <pod>`, `pod update`/`export`/`validate` and `docket run` use it, `init`
  without a matching name exits 2 naming the teams, and `pod export` writes `teams/<pod>/` once
  the repository keeps `teams/`.
- **`POST /pods/<p>/apply` (P43-8).** Applies a directory on this machine to a pod under the
  review rule: `dryRun`, `accept` with the review code (`409` with `reviewCode` and `runs`
  without it), `pod.apply` audited with `channel=http`. The review decision is one core function
  shared with the CLI.
- **`GET /pods/<p>/corrections?since=` (P43-9).** Reads the corrections ledger by cursor; `since`
  is normalised to UTC (a naive timestamp is `400`), `next` is UTC `Z`.
- **Cancel, retry and diff over HTTP (P43-10).** `POST /tasks/<pod>/<id>/cancel` (optional
  `reason`), `POST .../retry` and `GET .../diff` (`{task, branch, baseCommit, head, patch,
  untracked, worktreePresent}`: the branch patch from the codebase, so it survives worktree
  removal; `409` with `reason` for a task that ran in place). The cancel decision moved to
  `core.dispatch.cancel_task`; `docket task diff` prints the branch patch and takes `--json`.
- **A daemon a supervisor can run (P43-11).** The dispatch sweep stops between tasks on the first
  stop signal and resumes stale claims on every sweep; `POST /tasks/<pod>` starts that pod's
  sweep when dispatch is on; `docket start --bind <addr>` sets the listen address; `/health`
  reports `apiVersion` and a `dispatch` block (`on`, `inflight`, `stopping`, `workers`).

### Removed

- **The `completed` task count.** `status --json` (`tasks`) and `GET /pods` (`queue`) counted a
  `completed` key that summed `done` with a status that does not exist. The counts are now one key
  per task status (`pending`, `running`, `waitingInput`, `waitingApproval`, `blocked`, `failed`,
  `done`, `cancelled`), so `completed` becomes `done` and `blocked` and `cancelled` appear
  (cli-json-shapes spec 4.0.0). Breaking.
- **The `claimId` and `source` keys of a task record, and the `in_progress` task status.** Nothing
  read `claimId` (a stale claim is read from `claimPid` and `claimedAt`) or `source` (`channel`
  says where a task came from), and nothing ever wrote `in_progress`. `GET /tasks/<pod>?status=
  in_progress` is a `400` like any unknown value.
- Four spent one-off maintenance scripts that nothing called: `remove_harness_mode.py`,
  `split_cli_registry.py`, `move_pod_report.py` and `strip_spec_changelogs.py`.
- **The `inPlace` meta key**, which nothing wrote; `_ensure_task_worktree` no longer reads it.
- **The per-member daily-log pipeline (P44-7).** Daily logs under `memory/`, their seeding at
  provisioning and their distillation into MEMORY.md are gone: nothing wrote them in a pod task.
  `docket pod reset` resets the ledger and the member's templates and no longer distills or
  clears memory; `--no-distill-first` is gone. `lastActivity` now reads the agent's newest session.
- **`docket exec`, `docket setup harness` and the harness contract (P43-12, ADR 0027).** The
  command, the contracts 1.0 to 1.2 (schemas, fixtures, `--recipe` runs, the stdin answer
  stream, the in-place ephemeral pod, the `harness` approval channel) and their docs and tests
  are deleted; a program uses the HTTP routes of `specs/api/operator-api.spec.md`. A retired
  name is an ordinary unknown command (exit 2). Ten commands remain. Breaking.

### Changed

- The `docket start` banner lists every route the server answers, printed from the route table
  (`interfaces/http/routes/table.py`), where it named 6 of them.
- The shipped `anthropic` provider template no longer declares `contextWindow`/`maxTokens`
  (prices, `pricesAsOf` and presets stay: no provider publishes them). `setup provider add
  --ctx/--max-tokens` no longer default to 16384/8192; absent means observed, else unknown.
  `pod show --json` `provider.model.source` is `declared | observed | unknown` (was `row | none`).
- The serve API version is `5` (`GET /status.json` `apiVersion`); docket declares
  `0.2.0-beta.6`. The published install lines move when the release is cut.
- A `POST /tasks/<pod>` that creates a task answers `201` (was `200`).
- `docket task diff` shows the task branch's commits against its base, not the worktree's
  uncommitted changes (`_pin_implementer_tree` commits every real run).
- `docket.config` is gone. Every setting is a field of `docket.kernel.home.Home`, read with
  `current_home()` and built once from the environment by `Home.from_environ`; the templates that
  ship in the wheel are found by `docket.kernel.templates`. No environment variable changed.

### Fixed

- A `task retry` after a failed branch of a parallel review group re-runs the group instead of
  ending the task `done` with the failed gate unmet: resume counted a group finished when every
  child had any persisted hop, failed ones included. Found by the Phase 45 real run.
- A known output cap larger than a hop's remaining token budget no longer refuses the hop before
  any call: the budget reserve and the `max_tokens` sent are cut to what the budget leaves after
  the estimated input (at least 256). Found by the Phase 45 real run: with Anthropic's observed
  128,000 cap, the reviewer hop was refused with 127,735 tokens left and 2,861 of input.
- The built-in `anthropic` provider sends `anthropic-version: 2023-06-01`, which Anthropic's
  `/v1/models` requires (it answered 400 to the registration probe, so no limit was ever
  observed for an Anthropic model). Found by the Phase 45 real run.
- `llm_call` request bytes measured a JSON body with non-ASCII escaped to `\uXXXX`, inflating a
  non-ASCII part by about 60% (18,037 B reported against 11,367 B); the request body is now sent
  and measured as UTF-8. An `llm_call` record carries `cacheWriteTokens` when the backend reports
  cache writes.
- **Pin commit subjects are cut at a word boundary**, and a parallel group that fails keeps its
  failing child's `failureKind` (a budget stop inside a group now says `budget`).
- **Approvals are kept per codebase and team, as a set.** `reviewed-repos.json` is keyed by
  codebase and pod and keeps every approved set, so a second team on the same codebase no longer
  replaces the first team's approval, and returning to an earlier approved set asks nothing;
  `repo.allow` audits `pod=`. The old one-entry file is not read, so its operator is asked once
  more (D-57). `POST /pods/<p>/apply` refuses 400 for a pod with no recorded codebase instead of
  reviewing against the directory's parent, and the changed-since-review hint names
  `.docket/teams/<pod>` when the repository keeps teams.
- **`GET /inbox` carries a consultation's options (W116-8).** `TaskView.question` was typed
  as the v1.0 `Question`, so `GET /inbox`, the MCP `inbox` tool and `docket inbox --json` dropped
  a parked consultation's `kind`, `options` and `recommendation` that `GET /tasks/<pod>/<id>`
  served; a client had to read every task twice. The three surfaces now carry them, and the
  operator-v1 `inbox` and `task` schemas describe the v1.1 question (operator-loop 1.10.0,
  serve-read-api 3.11.0).
- **The re-attach contract is written down and pinned (W116-9).** `operator-api.spec.md` 5.9.0
  states what a client may rely on after its runner or docket restarts: tasks served from disk
  with their token or question, tokens and questions answerable across restarts, answers that
  start no sweep, one `idempotencyKey` per attempt, expiry by cross-reference, `stale_claim`
  resumed by the next sweep. Seven integration tests drive a second server over the same home.
- **Condensation moves in batches (W116-10).** `condense_history` recomputed its cut on every
  request and moved it one result at a time once results outgrew 6,000 characters, so the first
  changed message sat right after the system prompt and the provider's cached prefix ended
  there. The cut now drops whole results to a 3,000-character low-water mark and holds until
  they pass the budget again, still as a pure function of the messages (session-history 1.9.0).
- **A quoted heredoc's body is data, not commands (W116-1).** The classifier read every line of
  a heredoc body as a command, so a `python3 - <<'EOF'` script holding a backtick, `${`, an
  apostrophe or `=>` asked for approval. With a quoted delimiter (`<<'EOF'`, `<<"EOF"`,
  `<<\EOF`) the shell expands nothing, so the body is cut before classification; the high-risk
  classes still read the full text. An unquoted heredoc, one fed to a shell (`bash`, `sh`,
  `source /dev/stdin`, ...) and one that never closes still ask. Found by a real task that parked
  on exactly this script.
- **A refused redirect names the rule, not the binary (W116-2).** Inside the jail an output
  redirect that could not be placed was reported as `'cat' is not on the curated allowlist`,
  with `cat` on the list. The reason now says `output redirect to <target> is outside the
  workspace` or `output redirect after cd cannot be placed`, and a `cd` to a literal path inside
  the workspace is followed when placing a later relative redirect, unless the `cd` itself runs
  in a pipeline or subshell.
- **`block-destructive` gates a write to `.env` or `.ssh/`, not two words in one call
  (W116-3).** The old `.env\b.*write` alternatives matched across a whole rendered bash command
  (newlines are escaped), so a script holding `.write(s)` and, fifteen lines on, `process.env`
  parked a task. They now fire on a redirect, `tee`/`cp`/`mv`, `sed -i` or the `write`/`edit`
  tool targeting such a path. **Operator step:** docket never overwrites an installed policy, so
  replace `~/.docket/policies/block-destructive.yaml` with the shipped template for the fix to
  take effect.
- **The roles that write are told to write with `write` and `edit` (W116-4).** The Implementer
  and Writer bodies and the `bash` tool description now say: create or change files with
  `write`/`edit`, not `cat >`, heredocs or `sed -i`; inspect with `read`/`grep`/`glob`; use
  `bash` to run things. `POD_TEMPLATE_VERSION` 4 to 5, so `pod update` reports existing members
  stale.
- **Redaction keeps a trace payload valid JSON (W116-5).** Secret-shaped strings were replaced
  in the serialized payload, where one pattern ate the closing quote and brace, so the record
  fell back to `{"text": ...}` and a parked hop's `hop_finished` lost its structured `usage`.
  Strings are now redacted inside the parsed value.
- **`inputExpiryHours` reaches the questions it promises to expire (W116-6).** The pod setting
  had a writer, a display and a documented promise, and no reader on the dispatch path, so a
  parked consultation waited forever. A question parked without its own deadline now expires
  after the pod's `inputExpiryHours` (default 72 h) to `blocked`/`input_expired`; an `input`
  step's `expiresHours` still wins.
- **Every pending approval records `expiresAt` (W116-7).** A pre-hop gate approval stored no
  deadline, showed `expiresAt: null` and was denied 15 minutes later by a fallback in the
  sweep. The record now carries `created + APPROVAL_TIMEOUT` unless the creator gave one, the
  sweep reads only that field, and a client re-attaching after a restart can tell how long it
  has.
- **A research or content team's work reaches the task branch.** Only the Implementer's hop
  committed the tree it left, so a pipeline without one (researcher, then critic) ended `done`
  with the report untracked and the branch at its base. In a task worktree, any hop that hands
  on a diff now commits it on the task branch.
- **`2>/dev/null` no longer asks for approval.** An output redirect to exactly `/dev/null`
  counts as placed, jailed or not, with or without the turn's roots. A jailed `ls x 2>/dev/null`
  had asked, with a reason blaming `ls`.

- **Condensed history no longer makes a step re-read what it just read.** Old tool results
  stay whole while all whole results fit in 6,000 characters; only past that do they become
  one-line notices. The Phase 44 rerun found a model making one call per round re-reading a
  README and a script in a loop until the no-progress stop ended the step.
- **A condensed result no longer invites a re-read.** Its notice says the result was already
  seen and asks for a new call only for exact text still needed; "call <tool> again if needed"
  had read as an invitation.
- **A jailed command that cannot execute says why.** A `bash` call that exits 126 inside the
  jail reports that the jail could not execute it, that a retry will not help, and that the
  operator grants a toolchain with `docket setup sandbox read add <path>`. In the Phase 44
  rerun an implementer retried `npm`/`npx` after each 126 without learning why.
- **A step no longer re-sends every earlier tool result (P44-4).** Results older than the last
  two become one-line notices and large old `write`/`edit` arguments become character counts, in
  the request only (`session.json` keeps every byte). With bounded tool output, the replay bench
  estimates 0.25 / 0.49 / 0.63 / 0.37 of today's sent tokens on four recorded steps.
- **The prompt in layers, stable first (P44-6).** The system prompt is byte-identical between
  tasks of one member: no roots, no HEARTBEAT.md or TOOLS.md, MEMORY.md only when it holds
  more than its template. The working directory and a repository map arrive in the task message;
  member templates carry one short method block and no private-file reads, absolute paths or
  completion promise (`POD_TEMPLATE_VERSION` 4, applied by `docket pod update`). The downstream
  checkout note that pointed at an origin path the prompt no longer carries is gone.
- **The turn budget counts new tokens (P44-2).** Counted = input minus cache reads plus output;
  a paid final reply that crosses the budget is kept; a model with no registered output bound
  reserves `DEFAULT_MAX_OUTPUT_TOKENS` (4096) so the prospective check runs; input estimates are
  scaled by the last measured ratio; a hop's `usage` carries `input`, `cached`, `cacheWrite`,
  `output` and a task's `maxTokens` uses the same count. The pod's dollar estimate no longer
  charges cache reads or cache writes twice.
- **Tool output has a budget (P44-3).** `glob`/`grep` print sorted, root-relative paths and skip
  vendored directories; `read` returns a numbered window of at most 400 lines and 6,000
  characters with a remaining-lines footer (window chosen on the replay bench); `glob`, `grep`,
  `read` and `fetch` share the tool output cap; `fetch` is offered only while
  `FETCH_ALLOWED_DOMAINS` is set, so a default install no longer lists it.
- **Every writing hop delivers what it produced (P44-5).** The handoff carries a capped `diff`
  (tracked changes plus new files' content, `HANDOFF_DIFF_MAX_CHARS`) for every role that changed
  the tree, so a reviewer or critic no longer re-reads it with tools.
- **A provider preset names the pods it moves.** The role table is the fleet's, so `docket setup
  provider add` with a preset re-pointed the policy-following members of every pod, other teams
  included, and said only which model each role now resolves to. It now prints each moved pod and
  role with the model before and after, and the `--no-preset` command that registers without
  moving them; `setup model set|preset|reset` print the same lines.

- **`pod update` says why a setting is skipped.** A `pod.yaml` setting equal to the pod's
  default planned a bare `[skip]`; the plan line now reads `[skip] setting: approvalMode (already
  the default)` and `--json` carries it as the item's `note`.

- **A pipeline step with two gates is refused instead of losing one.** In the short form,
  `verify: true` beside `gate: {external: ./ci.sh}` kept the verify gate and dropped the external
  check with no error. A step may carry one of `verdict`, `verify`, `approval` and `gate`; more is
  a load error naming the step and the keys (`step 'build': one gate per step (got verify,
  gate)`).

- **A team's `pipelines/` travels with `docket pod update` and `docket pod export`.** A task that
  names `pipeline: <name>` reads `<pod config>/pipelines/<name>.yaml`, but nothing put the file
  there: `update` skipped the directory and `export` dropped it, so every hop ran with the
  fleet's role table and lost its step `model:`. `update` now copies each file (validated; an
  invalid file or a name dispatch cannot resolve refuses the update), `export` writes them back,
  `pod validate` checks them, the recipe summary lists them, and their commands go through the
  same review as `pipeline.yaml`'s, named `<pipeline>/<step>`.

- **A repository's gate commands need the review code too.** `docket init`, `docket pod update`
  and `POST /pods/<p>/apply` asked the operator only for a pipeline's `run:` steps, so a
  `.docket/` could run any command through `verify: <cmd>` or `gate: {external: <cmd>}` with no
  review (ADR 0024 §6 already named verify commands). Both now appear under "Runs on this
  machine" as `verify command` and `external gate`, inside `parallel` groups too, and a
  repository already reviewed asks again once. The refusal also says "1 command that needs".

- **A budget names the models it cannot price instead of counting them as $0.** A model with no
  catalog price added nothing to the budget estimate, so `budgetUsd` stopped nothing on it (a
  real run spent 175k tokens on gateway models and reported $0 against a $3 cap). Docket still
  runs the hop but now warns: a `budget_warning` trace event (`unpriced_model`) before each such
  hop, and `budgetUnpriced` in `docket pod show`, `GET /pods/<p>` and `docket status`. Local
  models are never flagged. The estimate still prices a member's tokens at the member's model,
  not at a step's `model:` override.

- **`POST /pods` takes `name` and `location`, the body API 5 publishes.** ADR 0027 and
  `operator-api.spec.md` named those fields, while the route still read `project` and `path`, so
  Tack's ensure call failed with `400 project is required` and no run reached a team. `project`
  and `path` are removed from the request; the response still says `project`.

- `dispatch_refused` trace events were rejected as an unknown type and never written.

## [0.2.0-beta.5] - 2026-10-14

Harness contract 1.2: a program that runs docket through `docket exec` no longer needs to hold a
model key, endpoint or catalog. Under `--contract 1.2` the run uses the operator's own `docket
setup` (read-only, from `DOCKET_SETUP_HOME` or `~/.docket`), `--model` defaults to the role's
setup model, and `docket setup harness --json` answers offline whether that setup can serve a run.
Since `v0.2.0-beta.4` docket also gained one CLI surface of eleven commands, a hardened agent
boundary (Phase 40), and one execution envelope on Landlock, Seatbelt or a chosen Docker, with an
escape matrix that gates release (Phase 41). Phase 42 adds an external verification gate
(a pipeline step runs your verifier and routes on its exit status) and the `lights-out` profile,
which refuses an unattended dispatch unless isolation, a cut network and an external gate are all
in place. The jail was hardened again before the cut: commands no longer reach the shared temp
dir or another branch's refs, the classifier sees through `env`/`xargs`/`find -delete`, and the
Seatbelt backend now passes the escape matrix on macOS.

**Breaking changes.** docket has no installed base yet, so nothing removed below kept an alias:
the CLI is eleven top-level commands (ADR 0022; removed names exit 2), `docket harness run` is
`docket exec`, `pod apply` is `pod update`, the `bwrap` backend and the `isolate` field of
`kind: mcp-server` are gone, and a repository's run-on-this-machine commands need the
operator's OK (ADR 0024 section 6). Harness contracts 1.0 and 1.1 are unchanged.

### Added

- **An external verification gate (Phase 42, P42-2, ADR 0025).** A pipeline step can carry
  `gate: {type: external, command: CMD, exitMap: ..., timeout: ...}` (short form
  `gate: {external: CMD}`). After the hop, docket runs CMD in the pod's envelope and maps the
  process's own exit status to `pass`, `fail`, `needs_human` or `error` (default map 0/1/2;
  an unmapped code, a timeout, a refusal or a missing command is `error`). Each label routes
  through the step's `on:` map; an unrouted `fail`, `needs_human` or `error` fails the task as
  `gate_failed`, `gate_needs_human` or `gate_error`. The verifier may write reasons to
  `$DOCKET_GATE_REASONS_FILE` (JSON, at most 64 KiB); they are screened as untrusted, redacted,
  recorded on the hop and shown to the retried Implementer under `GATE FAILED`, including after
  a human answers an `input` step the gate routed to. docket never names a verifier and reads no
  verdict beyond the exit status.
- **The `lights-out` profile (Phase 42, P42-4, ADR 0025).** `docket setup profile lights-out`
  (fleet-wide) or `docket pod set profile lights-out` (one pod; a pod may only be stricter than
  the fleet) makes every dispatch refuse a task before its first hop unless isolation is on with
  a usable backend, the jail's network is a recorded `none`, every Implementer step has an
  external gate, and no variable docket injects for the pod is named in the secret store. A
  refusal is audited (`profile.refused`), names each fix, and settles `dispatch_refused`, so the
  task can be retried once the fix is in. `status` and `setup` show the profile and what it
  lacks. Nothing changes until an operator records the profile; `attended` is the default.
- **Evidence 1.1.0 (Phase 42, P42-5).** `docket task show --json` and serve's evidence route
  report `v: "1.1.0"`, adding `gate` (label, exit code, reasonsInvalid) to a hop that ran an
  external gate and `directives` (path and sha256 of each repository file composed from the
  base commit) to the task. The evidence embedded in a harness result stays `1.0.0`, byte for
  byte.

- **Harness contract 1.2: `docket exec` runs on the operator's own setup (ADR 0026, D-62).**
  `--contract 1.2` stamps every line `v: "1.2.0"`. With `DOCKET_LLM_BASE_URL` unset, the endpoint
  and credential come from the setup home (`DOCKET_SETUP_HOME`, default `~/.docket`): the provider
  catalog, the model registry and the credential store or keyring, read without a lock and never
  written. `--model` is optional; the result's `model.source` says `explicit` or `setup default`.
  A missing model, provider or credential, or a keyring lookup that fails (as inside a sandbox
  with no D-Bus), refuses with exit 2 before any request, naming the provider and the
  credential, never its value; the resolved key is redacted from traces and stripped from child
  environments. `docket setup harness --json` is the offline readiness and model list. A caller
  probes for 1.2 with `env -u DOCKET_HOME docket exec --contract 1.2 --workspace . --task probe`:
  1.2 answers with the `DOCKET_HOME` refusal, older builds with `--contract must be one of`.
  Schema in `docs/contracts/harness-v1.2/schema.json`.
- **Wave 102: the sandbox is visible (P41-7).** `docket init` ends with a `This machine` /
  `Sandbox` block, `docket status` opens with it (the `Isolation` row is gone from the text), and
  `docket setup sandbox` prints what this machine has (`Backend: landlock (kernel 6.14)`, or what
  is missing per platform; `--json` gains `platform`, `kernel`, `available`, `missing`, `line`,
  `hint`). `setup` counts a home with pods and no usable backend as an issue
  (`securityGates.sandboxUsable`), and `install.sh` prints the probe's one line.
- **Wave 102: `docket setup sandbox backend auto|docker` (P41-3).** Docker is used only when
  chosen; `auto` means Landlock on Linux and Seatbelt on macOS.
- **Wave 101: verify commands and `run:` steps run inside the sandbox (P41-4, ADR 0024).** With
  isolation on, a pod's `verifyCmd` and a pipeline `run:` step run in the same jail as the agent's
  `bash` (the task worktree writable, the pod's network) instead of on the host, and fail closed
  when no backend is usable (`[verify not run: ...]`). One function, `system.jail_launch`, builds
  every jailed command. Isolation off is unchanged.
- **Wave 101: a per-pod cache directory and a hidden home (P41-5).** Each pod has a cache directory
  (0700) beside its scratch directory; a jailed command runs with `HOME`, `XDG_CACHE_HOME`,
  `XDG_CONFIG_HOME`, `UV_CACHE_DIR`, `PIP_CACHE_DIR` and `npm_config_cache` pointing at it, and
  the directory is writable in the jail, so `uv`, `pip` and `npm` work with the real home denied.
- **Wave 101: a Seatbelt sandbox for macOS (P41-2).** On macOS `/usr/bin/sandbox-exec` with one
  fixed deny-by-default profile (system paths readable, the roots and the temp dir writable, git
  hooks and config not writable, network cut under `none`) is probed after Landlock and before
  bwrap and docker, for `bash`, verify, `run:` steps and stdio MCP servers;
  `DOCKET_SANDBOX_BACKEND=seatbelt` selects it. Not yet run on a real Mac (P41-8's CI job will).
- **Wave 100: a Linux sandbox that needs no package (P41-1, ADR 0024).** `python -m docket.jail`
  confines a command with Landlock (the roots and the temp dir writable, system paths readable,
  the home and `DOCKET_HOME` unreadable) and, under network `none`, a seccomp filter that refuses
  IPv4/IPv6 sockets; it fails closed (exit 125, nothing run) when the kernel cannot enforce it.
  It is probed before bwrap and docker and selectable with `DOCKET_SANDBOX_BACKEND=landlock`;
  `DOCKET_SANDBOX_PROBE=none` hides it for tests that simulate a host with no backend.
- **Wave 100: a repository's commands need your OK (P40-5, D-59).** `docket init` splits a
  `.docket/` into what it adds to the team and what it runs on this machine (`run:` steps, MCP
  server commands, plugins, `allowCommands`, `network: open`, a role that drops a built-in
  denial). On a terminal it asks once and remembers the answer in `~/.docket/reviewed-repos.json`
  (0600, audited `repo.allow`) until those commands change; off a terminal it creates nothing and
  exits 2 with the items and a 16-hex code that `docket init --accept <code>` allows exactly.
  A repository can never allowlist `sh`, `bash`, `zsh`, `dash`, `sudo`, `ssh`, `nc` or `socat`.
- **Wave 100: `docket run` picks repository changes up (P40-13).** Before dispatching it applies
  what the repository added (`-> Updated from the repository: ...`); a changed command asks on a
  terminal and, off one, runs with the version you allowed. `docket status` shows the allowed
  commands and any change waiting for your OK. `start`, `exec` and dispatch never re-read the
  repository (pinned by a guard).

- **`docket --version` names the commit from a checkout.** A source tree prints
  `docket 0.2.0b4 (git 23591894, dirty)` -- the short HEAD sha, and `dirty` when `git status`
  reports changes -- so a tree 96 commits past the tag is no longer indistinguishable from the
  wheel the tag built. An installed wheel prints the bare version as before.
- **`docket init` is a real Typer command.** Its two arguments (`[PROJECT] [LOCATION]`) and
  eight options (`--blueprint`, `--pod full`, `--with`, `--codebase`, `--name`, `--from`,
  `--recipe`, `--no-apply`) are declared on the command: `init --help` is one screen that lists
  each with its meaning (the blueprint rosters and the `--from` file format stay in
  `specs/functional/pod-blueprints.spec.md`), `setup shell` completes them, and a `--pod`
  value other than `full`, `--from` beside any other option, or a third positional is a usage
  error (exit 2) like an undefined option. `cmd_init` builds one `InitRequest`; `run_init`
  provisions from it; the hand parsers (`_parse_add_args`, `parse_pod_roles`) are gone.
  `setup shell` offers pod names after `--pod` only on commands that carry the shared
  `--pod/-p` option, so `init --pod` completes nothing.
- **The invocation linter checks two more things.** A bare `FOO` or `$X` where a verb goes is
  a finding (`docket task FOO`), not a placeholder, and the rest of a `<a|b>` line must fit at
  least one of the named verbs (`docket pod <apply|export> a b c` is a finding). `init` is no
  longer exempt: its options are on the live tree.
  A header in the plain console voice (`docket - Apply plan myapp`, what a piped command prints)
  is output, not an invocation, inside a fenced block too.

### Removed

- **Wave 102: the `bwrap` sandbox backend and the `isolate` field of `kind: mcp-server` (P41-3,
  ADR 0024).** With them go `setup mcp add --no-isolate`, doctor's unjailed-MCP warning, `config
  explain`'s `isolate` and the recipes' unjailed-server note; an `isolate:` key is an unknown-key
  error, and every stdio MCP server starts in the turn's jail when isolation is on.

### Fixed

- **The Seatbelt profile lets a jailed command start on macOS.** Every command jailed by the
  Seatbelt backend died of SIGABRT before it ran (`command exited -6 [sandbox: seatbelt]`): macOS 26 aborts a process that cannot
  list the root directory, and the profile denied it. The profile now allows reading `/` itself
  (its entry names, not its subtree) and `/opt`, without which Homebrew's git could not load
  its libraries. Bisected on the macOS runner; the home stays unreadable. Security Gates 0.55.0.
- **A virtualenv's `python3` runs inside the jail.** Both jails granted the venv (`sys.prefix`)
  but not the interpreter it points at (`sys.base_prefix`), which uv and pyenv install under the
  home: under Seatbelt `python3` could not start, and under Landlock it only started by falling
  back to a system Python of the same minor version. Both now read `sys.base_prefix`.
- **The sdist builds and installs with uv 0.13.** It shipped the repository-only `benchmarks/`
  directory, whose trace fixture is named with `:`, a member name uv 0.13 refuses to extract.
  `benchmarks/` is now excluded like `Formula/`, and no sdist member may contain `:` (CLI
  Interface 2.7.2).
- **The typer floor is `>=0.17.5`.** typer 0.16.0-0.17.4 accept Click 8.3+ and then pass a
  missing required argument through as `None`: `docket task answer` with no id crashed (exit 1)
  instead of a usage error (exit 2). 0.17.5 caps Click below 8.3 and 0.18 supports it.
- **The classifier sees through wrappers (Wave 108).** With isolation off, `env rm -rf x`,
  `echo x | xargs rm`, `find . -delete` and an `awk` program calling `system(` ran unasked
  because the leading name was allowlisted. `env`, `xargs`, `nice`, `nohup`, `timeout`, `time`,
  `command` and `stdbuf` are now classified by the command they run; `find` with a deleting or
  executing action and an `awk` program that runs a command or writes a file ask. `setsid` stays
  off the allowlist (a new session escapes the process group a cancel kills). Interpreters stay
  allowlisted: without the sandbox the allowlist is not a containment boundary
  (security-gates 0.51.0).
- **The jail no longer lets an agent move another branch (Wave 108).** On every backend
  (Landlock, Docker, Seatbelt) a linked task worktree's jail keeps the common dir's `refs`,
  `logs/refs` and `packed-refs` read-only and re-opens only the task branch's ref and reflog
  directory (`refs/heads/docket/<pod>/`), so a jailed `git update-ref refs/heads/main` or a tag
  write fails while a commit on the task's branch works. A linked worktree that is not a docket
  task gets no ref write; a main checkout under Docker or Seatbelt is unchanged
  (security-gates 0.52.0, 0.53.0).
- **The jail no longer writes the shared temp dir (Wave 108).** Landlock and Seatbelt granted
  the system temp dir (`/tmp` on Linux) read-write, so a jailed command could write anything
  under it, a repository there included. Each jailed launch now gets a private 0700 temp dir
  (`<cache dir>/tmp`, else `DOCKET_HOME/jail-tmp/<hash>`) exported as `TMPDIR`/`TMP`/`TEMP`,
  stdio MCP servers included; Docker keeps the container's own `/tmp` (security-gates 0.54.0).
- **A parked task can be cancelled (Wave 108).** `docket task cancel` ends a task waiting for
  an answer or an approval as `cancelled`, takes it out of the inbox, denies a pending approval
  and audits `task.cancel`; before, the only exit was `task answer --decline`.
- **Host-side git on a task worktree trusts only the recorded git dirs (Wave 108).**
  `docket task diff` registers the task's recorded `gitDir`/`commonDir` before running git, and
  the diff hint in `task show` names both through `GIT_DIR`/`GIT_COMMON_DIR`/`GIT_WORK_TREE`, so
  neither reads the `.git` or `commondir` file the agent could rewrite.
- **`docket exec` (Wave 108).** A jailed run gets a per-workspace cache dir under the caller's
  `DOCKET_HOME` as its home; `--answer-timeout` reaches the wait through the run's env
  (`DOCKET_APPROVAL_TIMEOUT`, including every hop of a `--recipe` run) instead of mutating
  `config.TOOL_APPROVAL_TIMEOUT`; the stdin answer reader stops with the run and is joined
  (harness-mode 1.10.0).
- **`docket setup --fix --json` reports every check the text report runs (Wave 108).** Eight
  missing checks gained stable keys, so `healthy` cannot be true while the text counts an issue;
  the text report now counts a home with project agents and no delivering channel as an issue,
  as the JSON did (cli-json-shapes 1.32.0).
- **Smaller fixes (Wave 108).** `POST /dispatch/<project>` answers 404/400 instead of dropping
  the connection when a pod's bound pipeline cannot be resolved (serve-read-api 3.6.0);
  `task prune --traces --pod X` removes only that pod's terminal run records; the generated
  AGENTS.md drops the retired "write it to HEARTBEAT.md" line (template version 5); `docket
  inbox` indents every continuation line of a multi-line question, held command or label
  (operator-loop 1.7.0); `core/profile.py` uses the public `dispatch.hop_env`;
  `docs/assets/isolation.png` shows the Landlock sandbox report.

- **The network is no longer reported as cut while it is open (Phase 42, P42-7).** With
  isolation off, `docket setup sandbox`, `docket setup`, `docket status` and `docket pod show`
  printed the network as `none` (with an `ok`) although nothing was jailed and egress was open.
  They now say `none (<scope>), not enforced: isolation off, egress is open`, and the JSON of
  `setup` and `setup sandbox` carries `networkEnforced`.
- **A verifier that asks for a human is now answerable (Phase 42 live run).** The parked
  question shows the gate's reasons, the operator's answer reaches the Implementer it sends the
  task back to, and `pod validate` refuses a gated step that routes to the `input` step right after
  it without routing `pass`, which re-parked the task after a passing retry.
- **`docket pod validate` shows a pipeline's real error.** With an unquoted `on:` key anywhere,
  every error was reported as "Input should be a valid string", and the path was printed twice.
- **A short-form `input` step keeps an unquoted `on:` map.** YAML reads a bare `on:` as the
  boolean `True`; the input short form dropped it, so `- ask: {input: ..., on: ...}` loaded with
  no routes.

- **Wave 103: the Landlock jail keeps git hooks and config read-only (P41-8).** It granted a
  repository's whole git dir, so an isolated agent on Linux could write `.git/hooks` or
  `.git/config` and the operator's next git command would run it. The jail now grants only
  `objects`, `refs` and `logs` (and a linked worktree's own git dir), and refuses a root that
  holds a `.git` directory (exit 125, nothing run; use a worktree or `docket setup sandbox backend
  docker`). Host-side git in a task worktree names the git dirs docket recorded and never reads
  the worktree's `.git` file. `tests/integration/test_escape_matrix.py` runs every escape row on
  each available backend and gates release on Linux and macOS.

- **Wave 100: a sandboxed `bash` call with no usable backend runs nothing.** It used to fall
  back to the host with a `[sandbox: none]` marker; since the gate now allows off-allowlist
  binaries on the promise of a jail, it returns `not run: no sandbox backend is usable`.
- **The quick start and configuration guide** showed a bare `pod apply` applying `.docket/`;
  with no argument it re-renders stale member instructions (ADR 0022), so they now say
  `docket pod update .docket`.

- **Phase 40, Wave 99: the agent boundary, continued.** The docket process marks itself
  non-dumpable on Linux (`docket exec`, `docket start`, every turn), so an unjailed `bash` call,
  verify command or `run:` step can no longer read docket's credentials from
  `/proc/<pid>/environ`; the flag resets across `execve`, so children stay debuggable
  (security-gates 0.40.0). `fetch`'s timeout is a wall-clock deadline over the body read, so a
  server that drips bytes fails at the deadline, and the per-call timeout is clamped to four
  times `FETCH_TIMEOUT_S` (0.41.0). An approval's actor and reason are capped at 512 characters
  in the audit log and trace (audit 2.14.0), and refusals of unbound Telegram chats are one
  audit entry per chat per poll batch with a count (telegram-integration 2.7.0), so neither can
  rotate the audit log away. The unauthenticated `/status.json` carries each binding's channel
  but no longer the Telegram chat id that is the bot's authorization boundary (serve-read-api
  3.5.0; `apiVersion` unchanged). Directories docket creates are 0700 whatever the umask.
- **Phase 40, Wave 98: the agent boundary (D-58, ADR 0023).** A file tool's path escape and a
  `fetch` allowlist refusal are audited as `tool.refused` (tool, kind, attempted path or host,
  never content), so `docket log` shows a repository trying to leave the workspace or reach an
  unlisted host (security-gates 0.39.0). Every enqueue persists the `channel` it arrived by
  (`cli`, `http`, `telegram`, `mcp`) beside the unchanged `source`, and audits `task.enqueue`;
  `POST /dispatch/<project>` audits `run.dispatch` (pod-dispatch 6.38.0, serve-read-api 3.4.2).
  `docket log verify` detects a truncated tail: each append writes a sibling `audit.head` with
  the last `seq` and hash, and a log that ends below it is a break; deleting both files together
  is still indistinguishable from a fresh install (audit 2.13.0). The repository's
  `AGENTS.md` and skills index compose after the runtime contract, each behind a fixed frame
  naming it untrusted repository text to follow for style only; a containment aid, not a
  defence (agent-loop 1.34.0). The chat, model probe, OTLP exporter, ntfy and webhook requests
  refuse a redirect to another scheme, host or port instead of re-sending their credential.
  Supply chain: the `code-intel` recipe pins `ast-grep-mcp` to a commit and says it runs on
  the host, `pyjwt` is 2.15.1, CI syncs with `--locked` and pins every action by commit.
- **Security audit (2026-10-12), nine defects closed.** A newline inside a `bash` command now
  starts a new segment for the classifier (only the first line was classified; the shell ran
  both). `git -c k=v push origin main` and any global option between `git` and `push` match
  `prod-deploy` in the classifier and the shipped policy. An approval token from HTTP, Telegram,
  MCP or the CLI is checked against the minted `apr-<uuid4>` form before it becomes a path
  (a bearer holder or bound chat could grant and rewrite a pending-shaped JSON file anywhere on
  disk). The bwrap jail masks `DOCKET_HOME` (a jailed `bash` could read `secrets.json`, every
  pod's sessions and traces). `edges/store.py` creates its temp file exclusively, 0600 from the
  first byte, and never follows a planted symlink on the `.tmp`/`.bak`/`.corrupt` names. One
  raising Telegram update no longer wedges the poller on its batch. A non-object or deeply
  nested JSON body on the control plane is a 400, not a dropped connection. Trace redaction
  scrubs env-sourced credential values and bare vendor tokens. `docket init` installs the
  shipped policy templates (a fresh home had none, so every screen was a no-op); every
  untrusted-text screen evaluates the calling pod's own `on: input` policies; a skill's body is
  screened like a fetched page. security-gates 0.38.0, trace-store 1.7.0, mcp-client 1.10.0,
  agent-loop 1.33.0, telegram-integration 2.6.0.
- **A caller that dies no longer leaves `docket exec --answers stdin` waiting out its timeout.**
  End of stdin closes the answer stream: an approval waiting at that moment is denied at once
  and the run ends `blocked` (`approval_unavailable`), a later gated call is refused the same
  way, and the result's `approvals` entry reads `unanswered`. A silent caller that keeps stdin
  open still gets `--answer-timeout`. Harness-mode spec 1.8.0, security-gates 0.37.0.
- **A `blocked` result's `stop_reason` says `approval_unavailable`, not `invalid_output`.**
  `TurnResult` carries the turn loop's own stop reason through the driver; `failure_kind` stays
  the fallback for a driver that gives none.
- **`echo "..." > file` inside the workspace runs unattended.** The classifier receives the
  turn's roots and allows a redirect-sensitive binary whose every redirect target resolves inside
  them (relative to the workspace, symlinks followed, no earlier `cd`, no shell expansion); any
  other target asks as before. `>|`, `&>>` and `>&`-to-a-path are now recognised as output
  redirects (they were invisible to the classifier). `pytest` and `python` join the curated
  allowlist beside `python3`; the `allowCommands` examples now use `uv,tox`.
- **`docket exec --model`** documents that `PROVIDER` selects no endpoint under
  `DOCKET_LLM_BASE_URL` and only names the `<PROVIDER>_API_KEY` fallback credential.
- **An Implementer's uncommitted work is now what the checks and the merge see.** An agent
  normally leaves its work uncommitted, and docket recorded the task worktree's HEAD -- the base
  commit -- as the hop's `commit`. So the `anti-tautology` and `mutation` recipes diffed the base
  against itself and passed ("nothing to check"), the `git merge <branch>` that `docket task
  show` prints was "Already up to date", the COMMIT column contradicted `diffStat`, and `docket
  task prune` removed (without `--force`) a worktree whose only work was new files. When an
  Implementer hop ends ok, docket now commits its tree on the task branch (hooks and signing off,
  the operator's identity else `docket`), or pins it in a branchless snapshot commit for an
  in-place task; `diffStat` diffs the base against that commit, the `changed` predicate reads
  it, and both recipes fail on an empty `DOCKET_HEAD_COMMIT` (pod-dispatch spec 6.37.0).

- **`docket status` knows a parked question and the sandbox.** `status --json` carries
  `tasks.waitingInput`, a pod holding a `waiting_input` task is `waiting` (it stayed `ready`
  while `inbox` showed the question), the `Tasks:` line reads `N waiting input`, and the
  `status --all` table's waiting column sums both kinds. The `Isolation:` line and the JSON
  `isolation` value report the posture `docket setup sandbox` set (`on (bwrap, network open)`,
  `off (default); bwrap found, network open`) instead of a fixed phrase.
- **Help and messages tell the truth.** The `task approve|deny|answer|retry|cancel` examples
  pass `task-04ff`, not a timestamp; `pod set <key> <bad>` says `invalid value` (only the read
  of a bad stored value says `invalid stored value`); `task add`'s forecast pluralises
  (`2 policies`, `1 role gate`); a policy interruption is described by its predicate kinds
  (`tool bash on path src/**`, `commands matching its pattern`), never by the regex text.
- **`setup provider add` records the model the endpoint advertises.** A custom endpoint added
  without `--model` takes the first advertised id from the one registration probe instead of
  `local-model`, and the success line names it; with nothing advertised, `local-model` stays
  and the line says so. `--model` still wins; a catalog entry and a 401/404 are unchanged.
- **`docket run`'s progress view names the task and the hop.** The session lines read
  `▶ task-04ff… …` / `■ task-04ff… finished — status=<s>` (the task's short id from the session
  id) and an indented `  ▶ <hop> …` line prints as each hop starts; it printed `▶ lead …` once
  for the whole run and never named the hop that parked. Approval lines and stdout are unchanged.
- **The operator's decision reaches the record.** `docket task approve <apr-token>` (the form
  the progress view prints) now ends with the run hint like the task-ref form, its pod read from
  the approval record. `docket task deny --reason` puts the reason on the failed task
  (`reason: approval denied: <reason>`, shown by the inbox's Failed entry) and the `deny_reason`
  correction is keyed by the task id the gate stored under the record's `context`, so
  `task show` lists it; it was keyed by a top-level field no gate wrote, and the task's reason
  was the fixed `approval denied`. `POST /approvals/<token>` with `reason` carries it the same way.

### Changed

- **A gate that sends a task back says why (Phase 42, P42-1).** A backward `on:` route out of a
  gate that did not pass (for example `until: verify`) now gives the target's next hop a
  `--- GATE FAILED: <step id> ---` section with the gate's redacted output tail. Before, the
  Implementer retried without seeing why its verify command failed. A forward route, a backward
  `pass` route and a verdict rework compose the same messages as before.
- **Repository instructions come from the task's base commit (Phase 42, P42-3).** In a task
  worktree, the codebase's `AGENTS.md`, every `projectInstructions` file and the skills under
  `.docket/skills/` are read with host-side git from the commit the worktree was created from,
  not from the agent-writable worktree, so an Implementer can no longer rewrite what the
  Reviewer and Tester are told in the same task. A file added by the task is not read until it
  is merged. Without a task worktree nothing changes. The turn result carries the path and
  sha256 of each file served (`TurnResult.repo_files`).

- **Wave 100: the gate inside the sandbox, and network `none` (P41-6, ADR 0024).** Inside a
  working jail the command gate allows any binary except a high-risk class, a command it cannot
  read statically, or a redirect outside the roots; outside it the allowlist applies as before.
  The sandbox's network defaults to `none` (`docket setup sandbox network open` grants it); with
  isolation off nothing can cut the network, so only a recorded `none` refuses a turn.
- **`docket pod apply` is `docket pod update`** (P40-13), with `--accept`; a repository
  directory goes through the same review as `init`. `pod apply` is an ordinary unknown command.

- **The public visuals are re-captured from a real run of the eleven-command CLI** (2026-10-09,
  local 16k-context model, `scripts/maint/capture-doc-journey.sh`): `hero.gif`, `isolation.png`
  and `governance.png` show the plain console voice a transcript carries (`ok`, `->`, `!`), the
  new `pod show` and `log verify` output, and the gate scene shows the Lead's parked consultation
  answered with `task answer` before the Implementer's push parks under `high-risk-deploy`.
  The renderer colours the plain-voice prefixes; `docs/assets/README.md` records the run. The
  quick start's output blocks are refreshed from the same run (plain voice, stated up front),
  the workflow guide's dispatch and trace samples match the current lines, and the quick start,
  agent-teams and security guides embed the two still images where they apply.
- **Documentation describes the eleven-command surface in prose, not only in code spans.**
  `docs/AGENT-TEAMS.md`, `WORKFLOW-GUIDE.md`, `CONFIGURATION.md`, `DOCKET.md`,
  `SECURITY-SIMPLE.md`, `troubleshooting.md`, the docs index and one CONTRIBUTING line no
  longer speak of `serve`, `doctor`, `harness run`, `config explain`, `models provider`,
  `audit verify`, `exporters`, `set-verify`, a positional pod id, `apr-` tokens on the operator
  surface or the org specialists; `DOCKET.md`'s exec section is headed `docket exec`.

- **Help is grouped and spoken once.** `docket --help` shows the tagline and the eleven commands
  in three panels (Daily, The pod, Machine); `-h` works at every level; the bare `docket` prints
  the tagline, the five daily commands and `Not set up yet? docket setup`; an unknown command
  word suggests the live commands and group verbs it could mean (`docket add x` names
  `docket task add` and `docket pod add`); `setup shell bash|zsh` renders the completion
  scripts from the live command tree (every group's verbs and long options, pod names after
  `--pod`, task ids after `task <verb>`). Three guards keep it: every leaf prints an `Example:`,
  every reader emits one JSON document under `--json`, and no verb prompts off a terminal.
- **Every documented invocation is checked against the live tree.** `scripts/maint/
  lint_cli_invocations.py` parses every `docket ...` line in a code span or fenced block of the
  README, CONTRIBUTING, `docs/`, the specs (not their changelogs), the templates and every leaf's
  `Example:` line, and refuses a verb, option or positional count the Click tree does not have;
  `tests/guards/test_cli_invocations_true.py` runs it in process.
- **`scripts/maint/rewrite_cli_names.py`** rewrites invocations of removed command names across
  docs, templates, scripts, specs and tests from one table (`--dry-run`, `--write`, `--check`,
  `--unmappable`, `--self-check`); `tests/guards/test_no_removed_cli_names.py` fails on any
  surviving invocation under the swept roots.
- **`docket task` is the task group.** `task add "<text>" [--priority] [--brief]` queues (what
  `delegate` did) and ends with the `docket run` hint; `task list [--json]` is the queue with
  status, cost and each task's worktree path; `task show <ref> [--json]` is one task's whole
  story (hops, evidence, runs, corrections, the interruption forecast) and, for a task with a
  worktree, its path, branch, base commit and the exact diff and merge commands; `task diff`
  runs that diff; `task trace <ref> [--tail] [--export] [--json]` names tools on tool-call lines
  and `--tail` ends when the session ends; `task prune [--traces --days N]` removes finished
  worktrees and expired traces and run records. `task approve|deny <ref>` resolve the task's
  own pending approval (`--for "<cmd>"` records the pre-grant `pod pregrant` wrote), `task
  answer <ref> [text] [--option] [--field] [--decline]` answers a parked question (prompting on a
  terminal, as `chat` did), `task retry <ref>` re-queues a failed or blocked task and `task
  cancel <ref>` stops the run in flight or settles a stale claim. Every ref is a full id, the
  short id, an unambiguous prefix or a run id (`core/task_ref.py`); an ambiguous prefix lists
  the candidates and exits 1. After a state change the hint is `docket run`, or "docket is
  running and will pick it up" when the service holds the pod.
- **`docket pod` is a real group, resolved like every other command** (`--pod`, `DOCKET_POD`,
  then the directory). Roster: `pod show [MEMBER] [--json]` (members with role, model and its
  source, workspace and verify command; the settings with their source; the approval mode the
  dispatcher will use; config of record and drift: `config explain` and `pod config get` in
  one), `pod add ROLE [--count] [--verify]`, `pod remove ID [--yes]` (the Lead is refused),
  `pod reset ID [--yes]` (distils memory first and fails closed, then rebuilds the workspace
  files), `pod set KEY VALUE [--member]` / `pod unset KEY [--member]` (every `PodSettings`
  key; `verify --member` writes a member's verify command; `set budgetUsd` lifts a budget
  pause), `pod delete [--confirm NAME]` (the name typed on a terminal, `--confirm` off one; a
  member id is refused). Configuration: `pod apply [NAME|DIR|FILE] [--dry-run] [--json]` (a
  recipe by name, a directory, or a single `kind:` document; no argument re-syncs
  instructions), `pod export [DIR] [--force]`, `pod validate [PATH]` (one validator for every
  `kind:` document or directory), `pod plan [--pipeline FILE]` (from the real executor),
  `pod check "<text>" --role R [--hook] [--tool]` (would the pod's rules allow this),
  `pod recipes|roles|policies [NAME] [--json]` (`--plugins` on `policies`).
- **`docket setup` is the first run.** Bare `setup` prints the readiness report (model
  endpoint, notifications, sandbox, shell completion, background service) with the command that
  fixes each piece; on a terminal it then asks only for what is missing, required first, and
  prints every command it runs; piped, it exits 1 while the endpoint is missing and writes
  nothing. `--json` emits the report, `--fix` repairs. `setup provider add <name>` stores the
  credential, probes `/models` and applies the provider's preset in one step; `setup model`,
  `setup sandbox` (bare is a read) and `setup shell bash|zsh` are real sub-apps.
- **Telegram in one step.** `docket setup notify enable telegram --chat <id>` stores the bot
  token, sets the actors and binds every pod's Lead; nothing is sent unless `--test`. `setup
  notify` carries the channel catalog, `bind`/`unbind`, `privacy` and `flush`; `setup export`
  the exporter verbs; `setup mcp list|add|remove` the external tool servers.
- **`docket run`.** Runs the pod's pending tasks through its pipeline with Typer-declared
  options; `--dry-run` prints the executor's plan and starts nothing; `--resume` reclaims stale
  claims and clears a budget pause; with no model endpoint it refuses naming `docket setup`.
  A run ends with one summary line and one `Next:` line.
- **`docket start` / `docket stop`.** `start` is the background service (`--http`, `--telegram`,
  `--dispatch`, `--mcp` for the stdio MCP server) and records its pid in `$DOCKET_HOME/serve.pid`;
  `stop` sends the two-stage stop and `status` reports whether the service runs.
- **One pod resolver.** `docket status` and `docket add` pick the pod from `--pod`, then
  `DOCKET_POD`, then the registered codebase containing the working directory (deepest wins);
  a miss is one error naming the directory and the fix (`cli/_target.py::resolve_pod`).
- **One interaction contract.** `cli/_contract.py` owns confirmation (TTY `y/N` or a typed
  name; off a TTY, refuse naming `--yes` or `--confirm <name>`), JSON emission, required values
  and the closing `Next:` line (silenced by `DOCKET_NO_HINTS=1`).
- **One task reference.** `core/task_ref.py::resolve_task` turns a full id, the short id the
  queue prints, any unambiguous prefix or a run id into one task across a pod or all pods;
  an ambiguous prefix lists every candidate with its pod. Not yet wired into a command.
- **A failed task is retryable** (`core/dispatch.py::retry_task`, audited `task.retry`), and
  `dispatch --resume` reclaims a `running` task whose claimant process is gone or whose lease
  exceeds `turnTimeoutS + verifyTimeoutS` (audited `task.reclaimed`; claims record `claimPid`).

### Changed

- **Every document names the eleven-command surface.** The README and the quick start follow the
  daily loop (`setup`, `init`, `task add`, `run`, `status`, `inbox`, `task approve`) and define a
  pod where the first `docket pod` command appears; the guides, the reference docs, the recipe
  READMEs, the channel and exporter templates and 25 specs were rewritten by
  `scripts/maint/rewrite_cli_names.py` and by hand where no one-to-one form existed;
  `cli-interface.spec.md` 2.0.0 is one section per command. A spec's changelog is the record and
  keeps the names of its day.
- **The pod has no positional id and no action word.** `docket pod <project> <action>` is gone;
  `pod show` replaces `config explain <agent>` and `pod <p> config get`, `pod set budgetUsd`
  replaces `profile --budget`, `pod set verify --member` replaces `pod <p> set-verify`, and
  `pod apply <file>` installs the single role or policy document `roles add`/`policies add`
  installed. `policies init` and the whole-registry `roles validate` have no replacement
  (`docket setup` installs the baseline policies; `pod validate` checks a document).
- **The per-agent model pin is gone.** Three layers remain (policy, pod overlay, pipeline
  step); `.docket-meta.json` no longer carries `modelSource` and a meta written with it is read
  without it.
- **`log`, `exec`, `status`, `inbox`.** `docket log [N] [--json]` and `log verify` replace
  `audit`; `docket exec` replaces `harness run` with the same NDJSON events, result line and exit
  codes 0/1/2 (`harness status` is gone; Tack's probe changes one argv word). `status` shows the
  pod's tokens with the labelled estimate, the done/failed/aborted counts and latency, the last
  run and "approved, ready" tasks; `status --all --json` carries the inventory `snapshot` printed.
  `inbox` takes declared options only, prints the exact `docket task approve|deny|answer <id>`
  line on every item and never cuts a held command.
- **One console voice.** `ui.py` is the only module that knows symbols, colour roles, headers,
  sections and tables; output is plain ASCII (`ok`/`x`/`!`/`->`) with no colour when stdout
  is piped or `NO_COLOR` is set. A shrink-only guard counts Rich markup literals outside `ui.py`.
- **The model policy speaks archetype names.** `docket models` lists `lead`, `implementer`,
  `reviewer`, `tester`, `researcher`, `analyst`, `writer`, `critic`, `operator` and `monitor`;
  the `manager`/`programmer`/`knowledge`/`security`/`repo` rows and the role document's
  `policyRole` key are gone (an unknown key is refused). An old `docket-models.json` is not
  rewritten: unknown role keys are ignored and reported by `doctor`; re-run `docket models preset`.
- **`cli/__init__.py` is a registry.** It holds the Typer app, the callback and one registration
  per command (177 lines, was 2,759); every command body lives in its group module
  (`_task`, `_pod`, `_pod_config`, `_status`, `_log`, `_setup*`, `_service`, `_exec`, `_remove`),
  moved byte for byte by `scripts/maint/split_cli_registry.py`. No behaviour or text changed;
  a layout guard keeps every registry function at ten lines or fewer.
- **Bare `docket gates isolate` no longer enables isolation** (it prints the posture and usage,
  exit 2, writes and audits nothing) and **bare `docket notify` no longer delivers** (usage,
  exit 2). An unknown action is a usage error (exit 2).

### Removed

Every name below is an ordinary unknown command now (exit 2); nothing answers to it, suggests
it or remembers it (ADR 0022 decision 4). One line per old name, with what replaced it:

- `delegate`, `pod <p> delegate` -> `task add`
- `dispatch`, `pod <p> dispatch`, `pipeline run` -> `run` (`--pipeline FILE` for a one-off pipeline)
- `approve`, `deny`, `chat`, `pod <p> answer`, `pod <p> pregrant` -> `task approve|deny|answer <id>` (`task approve <id> --for "<cmd>"` is the pre-grant; the `apr-` token left the surface)
- `runs list|show|cancel|prune`, `trace tail|export|ingest|expire`, `pod <p> queue|evidence|corrections|explain|worktrees` -> `task list|show|diff|retry|cancel|trace|prune`
- `cost`, `metrics`, `snapshot` -> `status` (the labelled estimate and the outcome counts; `status --all --json` carries the inventory)
- `audit`, `audit verify` -> `log`, `log verify`
- `add`, `info`, `delete <agent>`, `maintain`, `profile`, `pod <p> list|add|remove|set-verify` -> `pod show|add|remove|reset|set|unset` (`maintain check|sessions` and the context-footprint warning have no replacement)
- `pod <p> config`, `config explain`, `profile --budget` -> `pod show`, `pod set|unset`
- `pod <p> apply|export|sync`, `validate`, `roles validate`, `policies validate`, `pipeline validate|plan` -> `pod apply|export|validate|plan`
- `policies test` -> `pod check`
- `recipes`, `roles`, `policies` (list, show, add), `plugins` -> `pod recipes|roles|policies [name]` (`add <file>` is `pod apply <file>`; `--plugins` on `policies`; `policies init` has no replacement)
- `delete <pod>`, `profile --resume` -> `pod delete`, `run --resume`
- `models`, `models provider`, `keys` -> `setup model`, `setup provider` (`add --credential`, `rotate`)
- `channels`, `wire`, `unwire`, `notify`, `conversations` -> `setup notify` (`bind|unbind`, `flush`, `show telegram`)
- `exporters` -> `setup export`
- `gates` -> `setup sandbox status|on|off|network|classes`
- `mcp servers`, `mcp serve` -> `setup mcp list|add|remove`, `start --mcp`
- `completions` -> `setup shell bash|zsh`
- `doctor` -> `setup` (`setup --fix`)
- `serve` -> `start [--dispatch] [--telegram] [--mcp]`, `stop`
- `harness run`, `harness status` -> `exec` (same contract 1.0/1.1, events and exit codes; a run id resolves through `task show`)
- `list`, `info` (the read views), `context`, `logs`, `edit` -> nothing; `pod show <member>` prints the workspace path
- `scope` -> nothing; the session key is derived
- `persona` -> nothing; the persona layer went with it
- `profile <id> <model>` (the per-agent pin, `modelSource`) -> nothing; a model comes from the role policy, a pod role overlay or a step's `model:`
- `help` -> `--help` / `-h` at every level
- `init --portfolio`, the org specialists and the portfolio manager -> nothing
- With them: the positional pod id (`docket pod <project> <action>`) and `--project`; the operator-set session scope; the `SOUL.md` persona block and `AgentMeta.persona`; `EDITOR`/`VISUAL` from the environment table; the `docket init` home bootstrap (`init` builds the team and points at `setup`); `kind: specialist` and `scope: org`.
- **The org specialists (`manager`, `knowledge`, `security`) and the opt-in portfolio manager.**
  No reader on the live path ever ran one. `docket init` provisions the pod only,
  `init --portfolio` is a usage error, `list`/`snapshot`/`doctor` and `/status.json` show pod
  members only (`SERVE_API_VERSION` 4), and `kind: specialist` / `scope: org` no longer exist.

### Fixed

- **The record decides.** A dispatch that parked is recorded `waiting_input`/`waiting_approval`,
  never `succeeded`; `runs show` exits 1 for a failed or unknown run; `doctor` counts only
  lines marked with a cross as critical and its footer names `docket doctor --fix`; `metrics`
  counts success/failure/aborted from the terminal task status each `session_end` records
  instead of a payload no dispatch ever wrote (it always read 0/0/0).
- **`models preset` (and `set`/`reset`) re-resolved a pod-scoped archetype to the compiled-in
  Anthropic default.** `reapply_role_policy` read the role table directly; it now resolves each
  policy-following agent through the same resolver a fresh provisioning uses, so a member whose
  archetype has no row follows the registry default. Found on the live home the day the role
  vocabulary changed.
- **The Homebrew formula installed docket without its dependencies.** Homebrew's pip runs with
  `--no-deps`, so `brew install docket-cli` produced a `docket` that died on `import typer`.
  The sixteen packages of the runtime closure are now `resource` blocks (built from sdists;
  `rust` is a build dependency for pydantic-core, `libyaml` for PyYAML), the release lane
  checks that every pyproject dependency has one, and `scripts/update-homebrew-sha.sh`
  rewrites only the asset digest, never a resource's. The formula's own `test do` block also
  expected `0.2.0-beta.4` where the package reports its PEP 440 form `0.2.0b4`; it now
  normalises. Found on 2026-10-07, same install.
- **The Homebrew formula downloaded `.../download/v/docket-v.tar.gz` (404).** `url` interpolated
  `#{version}` before `version` was declared, so every `brew install docket-cli` since
  `v0.2.0-beta.1` failed at download. The URL now names the version literally, as Homebrew
  expects, `scripts/update-homebrew-sha.sh` rewrites it at release time, and the release lane
  refuses an interpolated version. Found by the first real Homebrew install, 2026-10-07.
- **Homebrew 7 refuses an untrusted tap.** `brew install docket-cli` right after `brew tap` fails
  with `Refusing to load formula ... from untrusted tap`; the README, the quick start and the
  installer header now show `brew trust yielab/docket-cli` between the two.

## [0.2.0-beta.4] - 2026-10-06

The team lives in the repository. A `.docket/` directory next to the code (roles, pipeline,
policies, settings, skills) is the team's configuration of record, applied by `docket init` or
`docket pod <p> apply`; eighteen shipped recipes cover teams, policy packs, methodology pipelines,
checks and tools. Since `v0.2.0-beta.3` docket also gained a provider catalog of fourteen built-in
`kind: provider` documents, OpenTelemetry and Langfuse export with privacy levels, an operator
loop in which a gated task parks and waits in one inbox with notification channels, agent
consultations and evidence-v1, one git worktree per task, a network lockdown mode and an
execution envelope whose workspace isolation is opt-in (`docket gates isolate on`).

**Breaking changes.** docket has no installed base yet, so every compatibility path was removed
outright: `docket auth` is gone (use `docket keys add` and `docket models provider add`), tier
names (`economy`/`standard`/`premium`) are not accepted anywhere, removed commands are ordinary
unknown commands (exit 2), and the `serve` API is version 3. See Removed below.

### Added

- **Console alone tells nobody, and docket now says so.** `console` is a silent channel dialect
  (`core.channel.SILENT_DIALECTS`); `Catalog.delivering()` names the enabled channels that reach
  an operator away from the terminal. `docket doctor` gains a `Notifications:` check, counted as
  an issue once a pod exists (`checks.notifications {ok, delivering}` in `--json`);
  `docket serve --dispatch` warns once at startup, `docket init` after the created summary and
  `docket pod <p> dispatch` after a flush that found events, all with one text naming
  `docket channels enable desktop` and `ntfy --set topic=<topic>`. On a TTY with a desktop
  session, `init` offers `Enable desktop notifications now? [Y/n]` and, on yes, enables it and
  sends one test notification; nothing is ever enabled without that yes. The quick start's
  "Run unattended" now opens with picking a channel.
  - Found by the first real park -> flush run: the same parked approval reached `desktop` and
    `ntfy` twice, once through its task and once standalone, because `_park_call` never
    recorded the task on the approval. It now does (`context.taskId`), and the inbox also folds
    an approval whose token a waiting task holds, so one decision is one notification.
  - A consult's options can be answered from the CLI: `docket pod <p> answer --option <id>`,
    and `docket chat` lists the options and prompts for one (Enter takes the recommended).
    `docket inbox` prints a waiting task's question, its options and the `docket chat` hint,
    and a parked task's held action with the `docket approve`/`deny` hint (what the standalone
    approval line showed before it was folded into its task).
    Found live: the Lead asked a two-option question that Telegram and HTTP could answer and
    the CLI could not, and the inbox showed only the task's description.
  - The built-in `desktop` channel now fires for a failed task too (`on: [needs_you,
    task.failed]`), the subscription `ntfy` already shipped; a task that fails while you are
    away is something that needs you. A completed task still notifies nobody by default:
    `docket inbox` lists it under "Done".

- **The items carried out of Phases 36-38 (Waves 89-90, no phase).**
  - `docket pod <p> worktrees prune [--dry-run] [--force]` removes finished tasks' worktrees and
    merged branches, keeping (and naming) dirty, unmerged and `dispatch --resume`-able ones;
    `--force` removes the worktree, keeps an unmerged branch and audits it.
  - A second SIGINT/SIGTERM makes `docket serve` abandon in-flight sweeps: it requests
    cancellation of each sweep run, exits 130/143, and the task ends `cancelled`.
  - `approve_task` grants a parked pod call for the rest of its task, bound to the role that
    asked: `docket approve <token> --option approve_task`, Telegram `/approve <token> task`,
    `POST /approvals/<token>` `option`, MCP `approvals_grant(option=)`. Each later hop of that role
    gets one single-use pre-grant; at most 20 per task, dropped at a terminal status.
  - Channel notifications at the `conversation` level carry a question's options and the
    recommended id, and Telegram `/answer <task> <option id>` picks one.
  - A `run:` step can carry `env:` (refused for `PATH`, `LD_*`, `PYTHON*`, `DOCKET_*` and
    credential names; the task coordinates win; values never reach the trace). The
    `anti-tautology` and `mutation` recipes declare their overrides there.
  - `docket doctor` lists every unjailed MCP server, global and per pod, and, when Docker is the
    backend, warns if the jail image has no `git`; `config explain` shows `isolate` per server and
    `recipes show --json` `unjailed_mcp_servers`.
  - A harness consult's `question.taskId` is the run token, not the session key.

- **The execution envelope (Phase 38, D-55, ADR 0020).** With isolation on, an agent's
  processes run in a jail, and nothing docket holds leaks into them.
  - Workspace isolation is opt-in (`docket gates isolate on`; ADR 0021, see Changed). bwrap is
    tried first, then Docker (`DOCKET_SANDBOX_BACKEND` still forces one). With isolation on and
    no usable backend a turn is refused before any model call, naming both fixes (install
    bubblewrap, or `docket gates isolate off`). `docket doctor` and `gates isolate on` probe the real
    backend. Inside the jail a task worktree's git dir and the repository's common dir are
    writable, so an agent can commit; `.git/hooks`, `.git/config` and `config.worktree` stay
    read-only, so the jail cannot plant code the host's next `git` would run.
  - `docket gates network none|open` and a pod `network` setting (`none` only narrows) cut the
    jail's network: bwrap drops `--share-net`, Docker runs `--network none`. The default stays
    open. `network none` with isolation off is refused at turn start.
  - stdio MCP servers start in the same jail as `bash` (the turn's roots and network mode) unless
    declared `isolate: false` (`docket mcp servers add --no-isolate`, audited, shown by `doctor`;
    a recipe's `kind: mcp-server` document may declare it too). `code-intel`'s `ast-grep` server
    does, because `uvx` cannot write its cache in the jail.
  - `fetch` results pass the `pre_input` hook like MCP results (`fetch.result_blocked` /
    `fetch.result_warn`), through one shared screening function.
  - `verifyCmd`, `run:` steps and an unjailed `bash` no longer inherit docket's credentials
    (`DOCKET_LLM_API_KEY`, every provider-catalog credential name, `TELEGRAM_BOT_TOKEN`, every
    stored secret name).
  - `docket serve --dispatch` sweeps each pod in its own worker (`DISPATCH_SWEEP_WORKERS`,
    default 4), so one pod's blocking hop no longer stalls the others. Stopping `serve` waits for
    in-flight sweeps.
  - A refused isolation or network posture settles the task `dispatch_refused` after one attempt
    (it was retried as a transient error).

- **Verification-ready execution (Phase 37, D-54, ADR 0019).** What a task brings back is its own,
  screened and checkable by something other than docket.
  - One git worktree per task: at claim, a repo Implementer's task runs in
    `<implementer workspace>/tasks/<taskId>` on branch `docket/<pod>/<taskId>`, created from the
    codebase HEAD and recorded on the task as `worktree {dir, branch, baseCommit}`. Evidence
    `baseCommit` is that recorded commit, so a task's `diffStat` no longer counts earlier, unmerged
    tasks. `docket add`/`init` creates no worktree, and the per-member worktree and its
    `worktreeDir`/`worktreeBranch` meta are gone. Finished worktrees stay until the member is
    removed; the operator merges the branch.
  - MCP tool results pass the `pre_input` hook as untrusted input before they reach the model:
    `block` refuses the result naming the policy and server, `redact` scrubs it, `warn` passes it;
    each hit is audited (`mcp_client.tool_result_blocked` / `_warn`).
  - Command steps (`run:`) receive `DOCKET_TASK_ID`, `DOCKET_BASE_COMMIT` and
    `DOCKET_HEAD_COMMIT`, taken from the latest successful Implementer hop's evidence.
  - A `no_progress` stop: a turn ends when `AGENT_LOOP_NO_PROGRESS_ROUNDS` (default 3, `0`
    disables) consecutive tool rounds only repeat calls and results already seen in the turn.
  - Recipes may ship `kind: mcp-server` documents under `mcp-servers/` (read/write declared as
    `access:`). `docket pod <p> apply` installs them for that pod only, and nothing else does. A
    turn's stdio MCP servers start in the turn's root.
  - Five recipes: `anti-tautology` (new or changed tests must fail on the base commit),
    `mutation` (mutmut on the changed source files, 80% threshold), `spec-writer` and
    `cross-family-review` (two pinned models from different providers), and `code-intel`
    (ast-grep and a language server as read-only MCP servers). docket runs these checks and records
    their output; it never scores them.
  - Known limits: `mutation` scopes by file, not line, and is Python-only; `anti-tautology`
    compares whole test files; the check recipes' overrides are read from the docket process
    environment; finished task worktrees have no retention policy; `fetch` results are not
    screened.

- **Consultation packs and evidence-v1 (Phase 36, D-53, ADR 0018).** An agent can now ask the
  operator a structured question and an operator can see what a task did, from one builder on
  every surface.
  - `consult` is a built-in `read` tool: the model asks a `decision`-kind question with options and
    an optional recommendation (operator-v1.1 `QuestionV11`, schemas under
    `docs/contracts/operator-v1.1/`). In a single harness turn it is a `question_asked` event
    answered on stdin by `questionId` with an `optionId`; under `refuse` the turn ends `blocked`
    with the question on the v1.1 result. In a pod hop it parks the task `waiting_input` and
    `answer_task` re-enters the same role with the answer. `maxConsultationsPerTask` caps it task-wide.
  - Approval packs: a gated call carries a screened, 500-character-bounded `rationale` taken from the
    model's preceding text, and three options (`approve_once`, `approve_task`, `deny`).
    `approve_task` pre-grants identical calls within the turn only. `docket approve|deny --reason`,
    HTTP `reason` and a harness `content.reason` record why, with an `actor`, in the audit entry.
  - evidence-v1 (`core/evidence.py`, `docs/contracts/evidence-v1/`): per-hop measured usage and a
    trace link for a task, read through `docket pod <p> evidence <task> [--json]`,
    `GET /tasks/<p>/<id>/evidence` and the harness result's `task.evidence`. All three come from
    one builder. Usage is `null` when the endpoint reports zero.
  - Corrections ledger: deny reasons, Reviewer `REQUEST-CHANGES` texts and declined answers append to
    `<DOCKET_HOME>/corrections/<project>.jsonl`, read with `docket pod <p> corrections`.
  - Escalation metrics: `docket_tasks_started_total`, `docket_questions_total{kind,outcome}` and
    `docket_decision_latency_seconds` on `/metrics`, and `docket metrics --escalation`. They are
    lifetime-of-current-storage counts, not monotonic totals.
  - Harness `files` no longer lists paths that were already dirty before the run or that the verify
    command produced (P35-12).
  - Known limits: the parked consult question crosses to the answering process through an in-process
    registry (out of process it fails closed); `approve_task` does not survive a parked and resumed
    hop; a single-turn consult's `question.taskId` is the session key; options are not rendered in
    Telegram or channel notifications.

- **Harness contract 1.1 is complete for an external supervisor (Phase 35, D-51, ADR 0017).**
  `docket harness run --contract 1.1` (opt-in; `--contract 1.0` stays byte-identical) adds
  process lifecycle events for `bash` (`process_started`/`process_exited`, with `pgid` and
  `exitCode` or `signal`); `--answers stdin` with `--answer-timeout` for approvals and recipe
  questions; `files` on the result (written and edited paths, plus `git status` in a git
  workspace); `--token-file`, `--max-tokens`, `--policy`; `--recipe NAME|DIR` with `--verify`,
  reporting the hops in a `task` block; and `approvals` on the result, so a denied or timed-out
  approval is visible without changing `status` or the exit code. The committed schema is
  `docs/contracts/harness-v1.1/schema.json`, and an integration test validates every line of a
  real subprocess run against it. Approval mode for a recipe run travels as the ephemeral pod's
  setting, not an environment variable.
- **Mechanisms for the recipe runner (Phase 35, P35-7).** `core/harness_pipeline.py` runs one
  recipe in place on an ephemeral pod for one task, through the same dispatch the pod uses.
- **Fixes (Phase 35).** Pod dispatch keeps its evidence (verify output, commit, base and
  diffstat); `requireVerify` makes a missing verify command fail a hop instead of advancing; a
  `guardrail_block` event carries the action, not the policy id; pod-scoped roles get their own
  token budget. Process groups for `bash` are cancellable by `docket runs cancel` and by SIGTERM
  on the harness.

- **The operator loop: tasks park instead of blocking, and every human touchpoint speaks one
  contract (Phase 34, D-50, ADR 0016).** An unattended pod's gated tool call no longer blocks a
  hop for 120s with nobody watching: `approvalMode: park` (the default for `serve --dispatch`'s
  sweep and a non-interactive `dispatch`; an interactive TTY still resolves to `wait`) records
  the exact call and moves the task to `waiting_approval` so the sweep moves on to the next pod
  in the same pass, and granting it re-runs the hop carrying a single-use pre-grant matched by a
  stable argument digest. A pipeline `input` step (`{ask: {input: {from: <step>}}}`) can instead
  park a task `waiting_input` to ask a real question, shaped as an MCP elicitation request/
  result; the opt-in `intake` recipe wires this to a Lead's typed `TaskBrief`
  (`objective`/`acceptance`/`resources`/`questions`, verdict `READY`/`NEEDS-INPUT`/`REJECT`) with
  a deterministic pre-flight check of named secrets/paths/verify commands before the Implementer
  ever runs. `docket inbox` (also `GET /inbox`, the MCP `inbox` tool, and Telegram's `/status`)
  is a pure, derived view across every pod's tasks and approvals; nothing is pushed anywhere
  until an operator enables a `kind: channel` document (`docket channels
  list|show|enable|disable|content|test|add|remove|export`) — seven dialects ship, all off
  except `console`, each declaring `content: minimal|actions|conversation` under the same
  confirmed-and-audited widening shape Phase 33 used for exporter privacy, and every
  notification is a CloudEvents 1.0 envelope, with `webhook` signing deliveries per Standard
  Webhooks. Parked work is answered from `docket pod <p> answer`, `docket chat <task-id>`,
  `POST /tasks/<id>/answer`, the MCP `task_answer` tool, or Telegram's new fifth verb
  `/answer <task-id> <text>` (still inbound-only, still screened by `pre_input`) — every one of
  these resolves through the single `core.answers.answer_task` function. `docket pod <p> explain
  interruptions` forecasts what could pause a task before it runs, and `docket pod <p> pregrant
  <task-id> "<command>"` pre-approves an exact, whitespace-normalized command (a rephrased one
  still asks). Every task view now carries an `a2aState` alongside docket's own `status`, mapped
  onto A2A 1.0.0's `TaskState` enum, though docket does not itself become an A2A server this
  phase. Measured on the phase's own `--scenario operator-loop` oracle: `sweepBlockedSeconds`
  fell from roughly 12-13s to under 1s deterministically once `park` shipped, confirming the
  blocking wait is gone — though under the local live model the same scenario still measured
  138s, because the sweep remains one worker walking pods serially, a different and unfixed cost
  left deferred with its own trigger. Two known limits: `channels-health.json` records delivery
  counters that no CLI surface reads back yet, and mid-turn session resume (in place of a hop
  re-run) stays deferred pending a measured trigger.
- **Export privacy levels: you choose what leaves, and see it first (Phase 33, D-49, ADR 0015).**
  Each `kind: exporter` document says what it shares beyond structure: `privacy: minimal` (the
  default for every built-in), `actions` (tool arguments, error text), `conversation` (prompts,
  replies, tool results) or `full` (plus the system prompt), or an exact `share:` list;
  `contentMaxChars` bounds each value. Content leaves only through an allowlist, filtered per
  message part, and is captured into the local trace only while some enabled exporter grants
  it, so at `minimal` everywhere the local trace is what it was without exporters.
  `docket exporters privacy <name> <level>` widens only after listing what starts leaving and to
  which host (a TTY confirmation, or `--yes`) and records `exporter.privacy` in the audit log;
  `docket exporters preview <name>` shows what a destination would receive from a real local
  session, offline. `list` gains `SHARES`, `show` a "Leaves this host" block, and every exported
  session carries `docket.privacy`. At `conversation`, Langfuse shows each generation's
  Input/Output, each tool's result, and the trace's own Input and Output (the session's task and
  its last answer, carried on the root and aliased by the built-in `langfuse` document), verified live with canaries at three levels; at
  `minimal` no canary reached the collector, Langfuse or the local trace. Compared with the
  pre-release `payload: metadata` default, an approval's command line and error text no longer
  leave at `minimal`. Export pipelines start once per process, so a running
  `docket serve` applies a level change after a restart.
- **Traces can go to OpenTelemetry and Langfuse (Phase 32, D-48, ADR 0014).** A destination is
  a `kind: exporter` document (`core/exporter.py`): endpoint, auth (`bearer`/`header`/`basic`/
  `none`, credential *names* only, never values), `resource`, `aliases` and which event types to
  send. Five ship in the wheel under `templates/exporters/`, all disabled: `otel-collector`,
  `jaeger`, `langfuse`, `honeycomb`, `phoenix`; a global override inherits every field it does
  not set. The one wire dialect, `otlp-http` (`edges/adapters/exporters/otlp_http.py`), is
  deterministic OTLP JSON hand-rolled over stdlib `urllib` with a retry on 429/502/503/504 that
  honours `Retry-After`; D-24's cut of the OpenTelemetry SDK stands. Every turn starts the bounded
  export pipeline lazily, flushes it on every return path (bounded by `EXPORT_FLUSH_TIMEOUT_S`
  even if a destination hangs) and writes per-exporter health counters; zero enabled exporters
  costs one catalog read. `docket exporters list|show|enable|disable|test|add|remove|export` is
  the CLI surface: `enable` resolves the declared credentials (prompting on a TTY, naming
  `docket keys add <NAME>` off one), probes the endpoint, and writes only the minimal override.
  `docket config explain` and `docket doctor` report each exporter; a `pod.yaml` may name
  `exporters:`, which `apply` and `docket recipes show` report and never activate. One session
  is one trace: every hop's model calls keep their own span ids (the key includes the role and
  the call's timestamp, not only its iteration, which each hop restarts at 1), so does each hop
  and each verification result, and the root is sent once, when the session ends, so a
  destination that upserts by span id keeps every generation, every hop and one root, and
  Langfuse's trace Input/Output show the task and the final answer rather than the first hop's. Verified live: a 4-hop dispatch against a Docker
  `otel-collector` produced 29 `gen_ai.chat` spans matching `docket trace`'s 29 `llm_call` lines
  and 39 `execute_tool` spans; replaying that dispatch's trace now gives 29 distinct generation
  ids and one root, where before the fix Langfuse kept 12; a real dispatch reached Langfuse's own
  dashboard with timing and token counts. See
  `observability-export.spec.md` §"External verification".
- **The model's own call is a trace event.** Every chat-completions exchange (each turn
  iteration, plus the compaction summarizer's own call) is a durable `llm_call` trace record
  carrying model, provider, measured latency and token counts, never a dollar figure.
  `ChatResponse` gains `model`, `provider`, `latency_ms`; the trace record gains an optional
  `task_id`; the store gets its first owning spec, `trace-store.spec.md`. `core/telemetry.py`
  projects trace records into a neutral span model with ids derived from the session id, never
  random, and `trace_ingest` notifies subscribers before appending so a live consumer sees a
  driver-projected session in order.
- **A recipe library of three kinds, and a recipe that says what it brings.** Twelve recipes
  ship: the three teams, four policy packs that change no roster (`git-safety`, `no-egress`,
  `secrets-guard`, `prod-approval`; every rule stated with the structured `tool`/`path`/`anyOf`
  predicates rather than free text, and `secure-build`'s and `ops-approval`'s own policies
  rewritten the same way), and five methodology pipelines that are the practice (`tdd`,
  `spec-first`, `reflexion`, `dual-review`, `frugal`). What a recipe brings is derived from its
  directory, never declared: `docket validate <dir>`, `docket pod <p> apply --dry-run`,
  `docket init --recipe` and the new `docket recipes list|show` print the same summary line.
  `pod.yaml` gains an optional `description`; a recipe name resolves against a directory path,
  your own `~/.docket/recipes/<name>/`, then the shipped library; `apply` records the pod's
  `configSource` after every validated apply, an all-`skip` one included, so composing recipes
  and applying the exported `.docket/` leaves the record naming the repository. The page
  `docs/recipes.md` is generated from the recipes and checked in CI.
- **Skills, in the Agent Skills shape.** `skills/<name>/SKILL.md` (front matter `name` +
  `description`, the body on demand) is discovered from three scopes, nearest wins by name: the
  repository's `.docket/skills/`, the pod's own `config/skills/` (a recipe's `skills/` is applied
  there and exported back), and `~/.docket/skills/`. The system prompt carries a `# Skills` index
  of screened descriptions; a new built-in `skill` tool of kind `read` returns the body or a file
  inside the skill's directory through the same chokepoint, deniable per role. `secure-build`
  ships `security-review`, `tdd` ships `test-first`, `spec-first` ships `writing-a-spec`.
  `docket config explain` lists the skills an agent sees.
- **`AGENTS.md` is read by default.** When a pod's `projectInstructions` is unset and the
  codebase root holds `AGENTS.md`, the file every other coding agent reads is composed as the
  project-instructions section: screened through `pre_input` as untrusted, capped, reported; an
  explicit `projectInstructions` list replaces the default. `docket config explain` names the
  files and their source.
- **`docket pod <p> apply <name>` takes a shipped recipe by name.** The argument resolves as a
  directory if one exists there, else as one of the shipped recipes (`secure-build`,
  `research-review`, `ops-approval`), exactly as `docket init --recipe` resolves it, so a recipe
  can be applied onto an existing pod without a path into the installed package.
- **The team lives in the repo.** A repository's `.docket/` directory (the same shape every
  shipped recipe and `docket pod <p> export` write: `pod.yaml`, `roles/`, `pipeline.yaml`,
  `policies/`, `plugins/`) is the team's configuration of record. `docket init` discovers it,
  validates every document before provisioning anything, and applies it after the pod exists;
  `docket init --recipe <name|dir>` starts from a shipped or local recipe the same way (mutually
  exclusive with a present `.docket/`); `--no-apply` provisions only. Nothing is applied without
  an operator command: dispatch, `serve`, schedules and the harness never read the directory.
- **A pod knows where its team came from.** `apply` records `configSource` and `configDigest`
  (written by nothing else; `pod config set` and a `pod.yaml` `settings` mapping refuse them),
  `docket pod <p> export` defaults to `<codebase>/.docket/` like `apply`, and `docket config
  explain <agent>` reports the source, the digest and `drift: yes|no`.
- **A pipeline step names its model.** `model: cheap|strong|<provider>/<id>` on a step, in the
  canonical and the short form, wins for that hop only and is never written to the agent's
  metadata; `docket pipeline plan` prints it and `validate`/`plan` refuse an unknown provider
  naming the step.
- **One field says what a role may not do.** `editRights` is retired from the role wire
  format: a stored overlay that still carries it loads and drops it, `roles show` never writes
  it, `roles list` loses the column, and `docket validate` prints a `note:` for a file that
  still declares it. `deniedTools` (`cannot` in the short form) is the only capability statement.
- **`config explain` says where a model goes, and `doctor` checks the provider catalog.**
  `docket config explain <agent> --json` carries a `provider` block (name, scope, dialect, base
  URL, the credential's name and source, the exact model row's limits) and the human view prints
  it under the model line, never a value; `docket doctor` names a malformed global provider
  document by file and field, in the human pass and under `--json`. The configuration guide,
  model-gateways page, troubleshooting page and quick start describe the catalog, `export`, the
  `Retry-After` ceiling and the evaluation-only/beta status Anthropic and Google give their
  OpenAI-compatible layers.
- **Registration verifies with the credential, and a provider round-trips through the CLI.**
  `docket models provider add <file.yaml>` (or the `add <name> <url> --model <id>
  [--credential NAME]` shortcut) probes `<url>/models` with the resolved credential and
  classifies the answer: only a transport failure refuses; 401/403 registers and names the
  missing or rejected credential; 404 registers and says the route is unserved; a 200 that
  advertises ids the document lacks prints them as suggestions. `list`, `show [--json]`,
  `remove` and `export` complete the round trip (`export` -> fresh home -> `add` -> identical
  `show --json`), and `docket models preset <name>` prints one readiness line naming the
  credential as present or missing.
- **A provider can authenticate by header and send static headers.** `auth: {type: header,
  header: api-key, credentials: [AZURE_KEY]}` sends the credential under that header (Azure
  OpenAI, a multi-workspace Anthropic key) and `headers:` adds static headers to every request;
  `Authorization`, `Content-Type` and `Accept` are refused at load. A bearer document's request
  is byte-identical to before.
- **Fourteen providers ship as built-in documents, and every table derives from them.**
  `templates/providers/` holds `anthropic`, `openai`, `google`, `openrouter`, `ai-gateway`,
  `groq`, `mistral`, `deepseek`, `xai`, `cerebras`, `together`, `ollama`, `lmstudio` and
  `local`; presets, prices (with `pricesAsOf`), key-format prefixes, credential names and base
  URLs are read from the catalog, so `docket models preset anthropic|openai|google` applies
  without a prior `provider add` and a stored key alone readies a built-in hosted provider. A
  provider absent from the catalog resolves only under `DOCKET_LLM_BASE_URL`.
- **A retry waits as long as the provider asked, up to a ceiling.** A retryable HTTP failure
  carries the endpoint's `Retry-After` (seconds or HTTP-date) through `TurnResult.retry_after_s`;
  the dispatch backoff is `min(max(2s x attempt, Retry-After), DISPATCH_RETRY_MAX_WAIT_S)`
  (default 60 s) and the `hop_retry` trace event records it.
- **A model provider is a `kind: provider` document.** `core/provider.py` holds the catalog:
  built-in documents under `templates/providers/` and the
  operator's own in `~/.docket/docket-providers.json`, nearest-wins by name. A document names
  its credentials (`auth.credentials`) and never holds a value; `resolve_endpoint` reads the
  catalog and the exact model row's limits. A pre-catalog `fleet.json -> providers` block is
  migrated once on first use (a literal `apiKey` moves into the secret store under
  `<NAME>_API_KEY`, audited `provider.migrate`), and `docket validate <file>` accepts
  `kind: provider`.
- **A policy can call a Python predicate the operator applied, never one the agent wrote.**
  `when: {plugin: <name>, with: {...}}` runs a `@predicate` from `~/.docket/plugins/` or the
  pod's own `config/plugins/` -- the only two places ever imported; a file in the codebase is
  invisible until `docket pod <p> apply` copies it with its sha256. An unknown name, a raise, a
  non-bool return or a call over its budget denies, naming the plugin; every call is audited as
  `policy.plugin`. `docket plugins list [--pod <p>]` shows name, scope, file and hash. The
  public API is `docket.plugins` (`PLUGIN_API_VERSION = "1.0.0"`).
- **Schemas an editor can use, and export in the short form.** `docs/contracts/config-v1/`
  holds generated JSON Schemas for the four kinds, pinned byte-for-byte and shipped with the
  package; `docket pod <p> export` now writes short-form YAML (a `.md` beside each role, `kind:`
  and `name:` on `pod.yaml`) with a `# yaml-language-server: $schema=` header and a `.schemas/`
  copy, and applying an export plans every item `skip`. The shipped recipes and the
  configuration guide show only the v1 short form.
- **Outcomes route the pipeline, and every loop has a bound.** A step's `on:` map sends any
  gate outcome -- a verdict marker, `pass`/`fail` of a verify command -- to `fail`, `stop`, a
  later step or an earlier one; a backward edge needs `max`, and `validate`/`plan` refuse a
  missing bound or an unreachable step. `until: verify` with `max` retries a step until its
  verify command passes. Every routing decision is a `route_taken` trace event; the shipped
  recipes and the one-rework-edge form are byte-identical.
- **A step can be skipped, and a step can be a command.** `when: {changed: "src/**"}`,
  `when: {var: name, is: value}` or `when: {memberPresent: role}` skips a step (`step_skipped`
  trace event, no hop). `- lint: {run: "ruff check ."}` runs a command in the pod's worktree
  with no agent turn and no model tokens, classified like any shell-out (an unlisted command
  asks, or fails under `approvalMode refuse`); its exit code, or a single upper-case last
  output line, is the outcome its `on:` map reads. `plan` prints both.
- **Every configuration file can say what it is, and one command validates them all.** A
  role, pipeline, policy or `pod.yaml` may start with `kind:` and `name:`; `docket validate
  [dir|file]` checks every document under a directory (default `.docket/`) and prints
  `file:line field: message (valid: a, b, c; did you mean "b"?)`, exit 1 on any invalid file.
  A file without `kind:` still loads, with one deprecation note per command.
- **Policies read as "when this, then that".** A policy may be short-form YAML (`kind: policy`,
  `appliesTo`, `on: input|toolCall|output`, `when`, `then: allow|warn|ask|block|redact`) with
  structured predicates over the call itself -- `tool`, `path` (glob over the path argument),
  `matches` (regex over the rendered text), `branch` (glob over the worktree branch), `anyOf`
  for OR -- evaluated inside the same chokepoint. The six shipped templates are now short-form
  YAML; every existing JSON policy keeps loading unchanged. `docket policies test` takes
  `--arg key=value`.
- **A pipeline step reads as "who, what is checked, where it goes".** `- build: implementer`
  plus `verify: true`, `verdict: [APPROVE, REQUEST-CHANGES]`, `approval: <message>` or
  `on: {REQUEST-CHANGES: {goto: build, max: 1}}`; the canonical form is unchanged and still
  what `plan` prints. The three shipped recipes are written in the short form.
- **A role file carries only what is enforced.** `cannot: [write, edit, bash]`, one of
  `verdict`/`verify`/`approval`, `model: cheap|strong`, and `instructions: <file.md>` whose
  Markdown becomes the role's prose (an optional `## AGENTS` section supplies the red lines);
  `editRights` is derived from `cannot`, never authored.
- **A pod exports its own scope, and the round trip is the proof.** `docket pod <p> export <dir>
  [--force]` writes the pod's role overlay, its policies, its bound pipeline and a `pod.yaml` of
  members and non-default settings, never anything global; applying that directory to a fresh pod
  in a fresh home reproduces the same `config explain --json`. `apply` also carries a recipe's
  `policies/*.json` into the pod, so the shipped recipes need no manual copy.
- **A recipe applies to any pod in one command.** `docket pod <p> apply [<dir>] [--dry-run]
  [--json]` (default `<codebase>/.docket/`) reads `roles/*.yaml`, `policies/*.json`,
  `pipeline.yaml` and a three-key `pod.yaml` (`members`, `settings`, `pipeline`), validates
  everything before writing anything, is idempotent, and audits once as `pod.apply`. The three
  shipped recipes carry a `pod.yaml` and their README's "Apply it" is that one command.
- **Every resolved value says which scope it came from.** `docket config explain <agent> --json`
  labels the role, each policy file, each loaded MCP server and each denied tool with `scope:
  built-in | global | pod`, and `docket doctor` names a malformed pod role overlay entry or an
  invalid pod policy file by pod, item and reason.
- **A pod chooses its MCP servers and denies tools for every role in it.** `docket pod <p> config
  set mcpServers a,b` limits a pod to those catalog servers (unset means all; an unknown or stale
  name is refused at write and refuses the dispatch naming it), and `set deniedTools fetch`
  removes a built-in tool from every role of that pod on top of each role's own denials.
- **The Lead's instruction is data.** The `lead` archetype carries a `hopInstruction` (shown by
  `docket roles show lead`); a global or pod overlay of `lead`, or a pipeline step's own
  `instructions`, now changes what the Lead is told. Research, content and ops pods' Leads plan
  for their real next role instead of an Implementer they do not have.
- **A pod has its own role overlay and its own policies.** `docket roles add|list|show --pod <p>`
  write and resolve `~/.docket/workspaces/pods/<p>/config/roles.json` above the global overlay for
  that pod alone, and `docket policies list|test|validate --pod <p>` fold that pod's
  `config/policies/*.json` into the same most-restrictive-wins evaluation, so a pod's policies can
  only add restrictions. Both reach a member's live turn, including a standalone one.
- **An MCP server declares its kind and its exposed tools.** `docket mcp servers add <name> --kind
  read|write --tools a,b -- <cmd>`: a server declared `read` now reaches a read-only role instead of
  being dropped with everything else; `--tools` limits which advertised tools register. Undeclared
  servers keep the fail-closed `write` default.
- **A pod's dispatch settings are a typed, validated, writable configuration surface.**
  `docket pod <p> config [get|set|unset] <key> [<value>]` (with `--json` on `get`) covers nine
  keys — `budgetUsd`, `maxReworkCycles`, `turnTimeoutS`, `verifyTimeoutS`, `approvalMode`,
  `allowCommands`, `pipeline`, `schedule` and `projectInstructions` — validated at write and
  audited as `pod.config`. An invalid stored value now refuses dispatch naming the key, instead of
  silently falling back to a default, and `docket profile --budget` writes `budgetUsd` as a
  number, not a string.
- **An unattended dispatch can refuse instead of waiting on nobody.** Setting a pod's
  `approvalMode` to `refuse` makes a hop that would otherwise block on a human approval fail the
  task at once, naming the tool and policy, instead of sitting on the approval timeout under an
  unwatched schedule or serve sweep. The default (`wait`) is unchanged.
- **A pod can allow its own tool binaries.** `allowCommands` names extra bash binaries that pod's
  agents may run without an approval prompt, scoped to that pod and validated at write: a path, a
  shell metacharacter, an opaque name (`eval`, `source`, ...) or a high-risk-class binary
  (`git`, `npm`) is refused, and a redirected call still asks.
- **A pipeline file can be a pod's default for every trigger.** `docket pod <p> config set
  pipeline <file>` validates the file, plans it against the pod's roster, and stores a
  docket-owned copy with its hash; that pipeline then runs for a manual dispatch, a
  `serve --dispatch` sweep, a schedule, and a webhook or MCP dispatch alike, not only a
  manually-passed `--file`. `unset pipeline` restores the blueprint default, and
  `docket pipeline plan` prints a `Source:` line naming which one would run.
- **Custom roles can carry their own hop instructions, and pipeline steps can be parameterized.**
  A role archetype's `hopInstruction` (or one generated from its gate contract when unset) now
  reaches a custom role's hop, and a pipeline step's own `instructions` field overrides it. Step
  instructions may reference `${name}` variables, resolved from repeatable `docket pipeline run
  --var key=value` flags as well as from a webhook payload; an unresolved variable refuses the
  run instead of sending the literal placeholder.
- **`docket config explain <agent>` shows the effective configuration with provenance.** One
  read-only command (with `--json`) reports the resolved model and endpoint, each prompt
  section's size and fit status, the agent's tools after role denials plus the configured MCP
  servers, the policies that apply to the role, the effective pipeline and its source, and
  budgets, timeouts, `approvalMode` and `allowCommands` — each value tagged with what set it
  (meta, policy, pin, pod setting, env or default).
- **An operator-owned `INSTRUCTIONS.md` composes into every agent's prompt and survives
  regeneration.** docket never writes it. `docket pod <p> sync [--dry-run]` re-renders `SOUL.md`,
  `AGENTS.md` and `TOOLS.md` from the current role archetype and metadata for any pod member whose
  template or archetype has gone stale, showing a diff first with `--dry-run`; `docket doctor`
  flags pod members that are out of date.
- **A pod can opt an agent into reading its own codebase's project instructions.** Setting
  `projectInstructions` to one or more relative paths (for example `AGENTS.md`) composes those
  files into the prompt right after `INSTRUCTIONS.md`; each one is screened as untrusted input by
  the `pre_input` policy hook, a missing file shows a visible marker instead of failing silently,
  and a path that would escape the codebase root is refused when the setting is written. Unset
  (the default), nothing changes.
- **Old runs, resolved approvals and closed conversations are pruned automatically and on
  demand.** The trace-retention window now also bounds `docket-runs.json`, the approval store and
  `docket-conversations.json`; only terminal records are removed, and live or pending ones are
  never touched. `docket runs prune [--days N] [--dry-run]` and `docket conversations prune
  [--days N] [--dry-run]` run it on demand.
- **Three shipped recipes** — `secure-build` (implementer plus a security-vetter verdict gate),
  `research-review` and `ops-approval` — ship in `templates/recipes/`: role, pipeline, an
  optional policy pack and a README with the exact commands to apply them. Each is validated in
  CI, and `secure-build` is proven end to end by a dispatch to `done` on the fake driver.

### Changed

- **Workspace isolation is opt-in (ADR 0021).** A fresh install runs tools on the host and needs
  no sandbox; `docket gates isolate on` jails `bash` and stdio MCP servers in bwrap (Linux) or
  Docker, and once on a turn with no backend is still refused. `gates status` and `doctor` read
  `off (default)`. Requirements are documented in `docs/SECURITY-SIMPLE.md`.
- **Unknown `docket gates` and `docket context` subcommands exit 2.** `gates` used to print its
  usage and exit 0, and `context` silently fell through to `show`; both now name the unknown
  subcommand and exit 2.
- **`docket audit verify` reports an unchained line as a break.** A line without `seq`/
  `prev_hash` used to be counted as "legacy", skipped, and treated as a chain restart; it now
  fails verification at that line, like any other break.
- **The `serve` API version is 3.** `/status.json` (and the MCP `status` tool) no longer carry a
  `gateway` field, `/health` answers `{"status":"ok"}`, and the `docket_gateway_up` metric is
  gone. The undocumented bare `/status` route is gone; use `/status.json`.
- **The docs open with the newcomer path.** The quick start is rebuilt as install → register a
  model → create the team (recipe, plain, or a committed `.docket/`) → run a task → read the
  record → export, edit, validate, apply → run unattended, with the terminal output of one real
  run; the docs index leads with the tagline and a start-here order; the configuration guide
  gains a complete `.docket/` example and the export→validate→apply loop, states that a broken
  policy fails closed and that a pod selects its MCP servers; the agent-teams guide drops the
  retired edit-rights column for the denied-tools one; every recipe README prints a command a
  user can type; the site navigation lists Configuration and the Workflow guide.
- **The README carries one pitch: agent teams as configuration, your rules, in YAML.** The
  front door opens with three sections -- the team you define (the `.docket/` directory and a
  role and a pipeline in their short form), the run, and the gate and the record -- each
  showing an asset captured from one real run, stating its limit beside the capability and
  ending in the command that proves it, followed by the quick start, which now starts from a
  shipped recipe and ends by writing the team back to the repository. The five-pain intro, the
  eight guarantees and the sixteen-bullet feature list are folded into those sections or
  relocated (best practices to the quick start, the tested adapter list to COMPATIBILITY.md,
  which is now its only owner). The package, module and site descriptions carry the same
  tagline. The prose tests that pinned the old headings were rebuilt from the new README's own
  rules rather than carried forward.
- **Non-software pods run their blueprint pipeline.** `docket pod <p> dispatch`, `docket pipeline
  plan|run` without `--file`, `POST /dispatch/<p>`, the `serve --dispatch` sweep, schedules and
  Telegram `/delegate` now resolve the Lead's `blueprint` and run that blueprint's full roster and
  gates. A research, content or ops pod used to run only its Lead; it now runs more hops and spends
  more tokens per dispatch pass. Software and agentic-product pods, and any pod whose Lead has no or
  an unknown blueprint, behave exactly as before.
- **`docket models` no longer claims prices can be overridden in `docket-models.json`**; no
  pricing overlay is read.

- **A prompt's context budget follows the resolved model's context window instead of a fixed
  ~24 KB for every model.** A 200k-window endpoint now fits a full identity/memory/task-ledger
  prompt that a fixed budget used to truncate; a 16k-window endpoint keeps today's behaviour.
  `CONTEXT_TOKEN_BUDGET` and an archetype's `tokenBudget` still work as explicit overrides, and
  `docket maintain check` plus each turn's `prompt_composed` trace event report the effective
  budget and what set it.
- **A truncated or omitted prompt section is always marked, never silent.** An oversized
  `SOUL.md` used to be able to push `HEARTBEAT.md`, `AGENTS.md`, `TOOLS.md` and `MEMORY.md` out of
  the prompt with nothing to say so; the runtime contract and task-ledger state are now protected
  ahead of `SOUL.md`, an oversized section is truncated with a visible marker, and every
  composition's `prompt_composed` trace event lists each section's size and whether it was full,
  truncated or omitted.
- **There is one default model of record.** `docket-models.json`'s `default` is now the only
  source; the separate, sometimes-diverging `fleet.json` default is no longer read. A
  provider's display name derives from `--model` unless `--name` is given, instead of every entry
  showing the shipped local model's caption.
- **Built-in role templates no longer instruct an agent to do something the runtime forbids.**
  The generated `AGENTS.md` text stops telling agents to write `HEARTBEAT.md` directly (private
  state is read-only on the live path); `WORKFLOW_AUTO.md` is now labelled as the manual-path
  contract it actually is.

### Fixed

- The jail could rewrite git metadata the host later runs: a submodule's hooks and config, a
  linked worktree's `.git` file and its `gitdir`/`commondir`, and `info/attributes` are now
  read-only, and a missing `hooks/` dir or attributes file is created empty first so the jail
  cannot create it.
- A jailed `git commit` failed whenever the operator's identity came from the environment or a
  non-default `HOME`, and always under Docker: the jail now receives the operator's git identity
  (never a credential).
- No inbox view, `/inbox` response or channel notification ever carried a parked task's
  `question` or `brief`: the fields existed and nothing filled them.
- A parked consult whose question lived only in the dispatching process stuck its task in
  `waiting_approval` when answered elsewhere; the question is now persisted (0600) and a missing
  one fails the task `consult_question_missing`.
- `git_branch_merged` read every branch checked out in a worktree as unmerged (it ignored git's
  `+` marker).

- `glob` and `grep` no longer return or read files outside their roots through a symlink, a
  symlinked directory, or a `..` in the pattern.
- The key-shaped redaction pattern no longer matches inside a word: `task=<id>` was redacted to
  `ta[REDACTED]`.
- **A task paused on a question is a warning, not an error.** `docket pod <p> dispatch` rendered
  `waiting_input` with the error marker; it now renders like `waiting_approval` (found in the
  Phase 36 live run).

- **A canonical role file that says `kind: role` loads as written.** `load_role_file` treated
  the `kind:` key as proof of the short form and normalized a canonical document, dropping its
  `deniedTools`/`gateContract`/templates and then failing on a missing `<name>.md`; a document
  carrying a canonical-only key now passes through, and one mixing both forms is refused naming
  the keys.
- **`docket init` counts the members a `.docket/` or `--recipe` added.** The closing `created
  with N members` line and the id list reported the blueprint roster only; they now report the
  pod as it stands after the apply step.
- **A recipe's own role no longer routes to the hosted default on a local fleet.** A role a
  recipe applied into a pod's overlay (`security-vetter`, `model: strong`) was resolved against
  the global role registry only, so it fell to the compiled-in `anthropic/claude-sonnet-4-6`
  while every other member followed `docket models preset local`; the first dispatch then hit
  the hosted vendor with no key (HTTP 401). Found by running the product for the new assets.
  `resolve_role_model` now looks the archetype up in the member's pod registry and an unknown
  role falls back to the registry's own `default`. `docket pod <p> apply` and `docket init` also
  print the plan's `[add]`/`[replace]`/`[skip]` actions again; Rich had been reading them as
  style tags and dropping them.
- **A `cd` prefix no longer turns an allowed command into an approval.** `cd`, `pwd`, `echo`,
  `true`, `false`, `test` and `[` joined the bash allowlist, so `cd <worktree> && git status`
  runs like `git status`; an unattended implementer hop used to time out three times on exactly
  that shape and fail. `echo` with an output redirect still asks, and `export`/`source`/`.` still
  ask. `docket policies test pre_tool_call` now evaluates through the live gate's own function,
  so it can no longer report `allow` for a command the gate asks about.
- **`GET /traces/<project>` delivers every event exactly once across session files.** An event
  written in a second the cursor had already partly delivered, to a session file that sorts
  earlier, was dropped while another was delivered twice. Events from the still-open second are
  now held back until it closes; the cursor format is unchanged.
- **`docket help <command>` prints that command's usage**, or exits 1 naming an unknown command.
- **`docs/contracts/harness-v1/schema.json` validates as JSON Schema.** Its nested `$ref`s
  pointed at definitions the document did not contain, so a standard validator failed on
  `#/definitions/HarnessResult`. The contract stays `1.0.0`; no field changed.
- **The HTTP control plane sends `Cache-Control: no-store`**, as its spec always said; a bare
  `POST /approvals`, `/tasks` or `/dispatch` is authenticated before it is answered `400`; and a
  request body over 1 MiB is refused `413` without being read.
- **Resolving an approval the other way answers `409`, not `404`.** Denying an approval that was
  already granted (or the reverse) raised the same error as an unknown token, so
  `POST /approvals/<token>` said the token did not exist. It now answers `409` naming the decision
  that won. The same seam made one cancellation test flaky when the in-turn cancellation denied
  first; the test now accepts either winner and still proves the tool never ran.
- **`docket cost <id> --json` returns that agent only.** It used to return the whole fleet and
  exit 0 even for an id that does not exist; an unknown id now exits 1 with nothing on stdout.
  `docket roles`, `gates`, `keys`, `policies` and `maintain` reject an unrecognised `--flag` with
  exit 2 instead of silently ignoring it.
- **`POST /pods` and `docket init --from` validate the project id.** A project id such as
  `../../x` used to provision workspaces and fleet registrations outside `DOCKET_HOME/workspaces`.
  `core/provisioning.py::validate_project_id` (lowercase alphanumeric segments joined by single
  hyphens, at most 64 characters) now runs first in `provision_pod`; the HTTP routes answer `400`
  and the declarative file exits 1 for an invalid id.
- **`docket mcp servers add <name> -- <command>` works from the real CLI.** Click consumed the
  `--` separator before the handler saw it, so the command's own help example always failed with
  "Missing '--' separator".
- **An approval granted or denied over MCP resumes or fails the dispatch task it gated**, the same
  as `docket approve`/`docket deny`, the HTTP route and Telegram. A task decided over MCP used to
  stay `waiting_approval`.
- **`docket maintain <id> rebuild` no longer deletes `memory/*.md`**, and refuses a pod member with
  exit 1 instead of overwriting its role prompt, `TOOLS.md` and `HEARTBEAT.md` with the legacy
  flat-agent templates.
- **A `verifyCmd` that times out is killed as a whole process group**, so a command that
  backgrounds work no longer leaves orphaned processes behind after the hop moves on.
- **`POST /approvals/<token>` accepts only `http` or `tack` as `channel`.** A Bearer holder used
  to be able to record a decision as `cli`, `mcp`, `telegram` or even `timeout`, forging another
  surface's provenance in the hash-chained audit log and in `docket_approvals_total`.
- **`docket list --json` and `docket info --json` emit `budgetUsd` as a number or `null`** (they
  emitted the stored string, or `""`), and `docket snapshot` emits `lastActivity: "never"`, the
  same sentinel `/status.json` uses.
- **`docket doctor`'s budget check and `docket cost`'s high-cost warning can fire.** Both compared
  recorded spend, which `DocketDriver` always reports as 0.0, so neither ever triggered. They now
  read the same recorded-or-estimated figure the dispatch budget gate uses, labelled as an
  estimate when it is one.
- **A broken policy file now fails closed.** An unloadable policy JSON, an uncompilable regex
  pattern, or an unknown `action` used to make every call on that hook evaluate to `allow`; each
  now makes every call in that file's readable scope (or, if the JSON itself cannot be parsed,
  all hooks) resolve to a block naming the file — across the live gate and `docket policies
  test`. `docket policies validate` now compiles every regex instead of accepting a pattern it
  never checks, `docket policies test pre_tool_call` takes `--tool <name>` so a non-`bash` tool
  is not misclassified against the command allowlist, and `docket doctor` reports a broken policy
  file as an error.
- **`docket doctor` reports a broken schedule, model-policy entry or overlay role by name instead
  of silently skipping it**, and `serve` logs a skipped schedule once per sweep.
  `docket pod <p> config set schedule "<spec>"` validates and writes a schedule (previously
  writable only by hand-editing the file), and `unset` removes it.
- **`docket delete` removes a pod member's merged branch and its provisioning lock directory.** A
  merged `docket/<pod>/<member>` branch and stale lock entries used to survive teardown; an
  unmerged branch is still kept, with the command to remove it printed. Newly created workspace
  and pod directories are now `0700`.
- **A deterministic dispatch refusal now fails the task instead of orphaning it.** A refusal
  raised inside a claimed task — an unknown pod member, an invalid stored setting, a membership
  mismatch — used to leave the task `running` with no process behind it and no way to resume; it
  now ends that task `failed` with the refusal as its reason, and `--resume` picks it up from its
  last persisted hop. A pod's membership is now read from each agent's own recorded metadata
  rather than guessed from its id string, which is what could raise that refusal for a hyphenated
  custom role name in the first place.
- **An approval's trace event is now filed under its pod, not the individual agent id** —
  matching where `docket trace <project>` and `docket metrics` already look for one.

### Removed

- `fleet.json`'s `security.isolationEnabled` field and `core.fleet.get_isolation_mode()`;
  `security.isolationMode` is the only isolation state.
- **Every compatibility path is gone.** docket has no installed base to migrate, so code that only
  kept an old name, flag, route or file shape working was deleted.
  - **Command aliases:** `show`, `rm`, `remove`, `telegram`, `key`, `secret`, `log`, `usage`,
    `check`, `security`, `export`, `completion` and `policy` are unknown commands. Use `info`,
    `delete`, `wire`, `keys`, `logs`, `cost`, `doctor`, `gates`, `snapshot`, `completions` and
    `policies`.
  - **Removed-command notices:** `auth`, `team`, `workflow`/`wf`, `eval`/`evals`, `model`,
    `tier`, `billing`, `credits`, `monitor`/`mon`, `memory`/`mem`, `smart`, `ai`, `mode`,
    `terminal`/`term` and the top-level `reset`, `repair`, `fix`, `cleanup` and `clean` no longer
    print a notice; they are plain unknown commands.
  - **Flags and subcommands:** the hidden `--debug` flag and hidden `_json` command;
    `docket gates enable`/`disable` and `gates ... --force`; `docket init --gates`/`--no-gates`
    and `init --path` (use `--codebase`); `docket profile <id> policy` (use `default`);
    `docket models ls` (use `list`); the trailing count in `docket pod <p> add <role> <N>` (use
    `--count`/`-n`); `docket maintain --distill-first` (distilling first is the default;
    `--no-distill-first` remains); `--json` in place of `docket audit`'s count argument (the
    `--json` flag is unchanged); `programmer` as
    a pod role alias for `implementer` (`programmer` stays a role-policy key for
    `docket models set`).
  - **Approval-routing posture:** the `approvalRoutingState`/`approvalRoutingMode` flag that
    nothing on the live path read, and the "Approval routing" line in `docket gates status`. The
    tool-call gate is always on; `docket gates` manages only isolation (`status`, `isolate`,
    `classes`).
  - **Migrations of old files:** a `defaults.model` or `providers` block in `fleet.json`, a
    `profiles:` key in `docket-models.json`, the old Anthropic model-id aliases (`claude-3.x` to
    `4.x`), and an exporter's `payload`/`payloadMaxChars` keys are no longer read or converted.
  - **`docket doctor` checks:** stale model names, the `profiles:` key, a stray workspace `.env`,
    leftover global specialist workspaces, metadata backfill, and quarantining a model-written
    `IDENTITY.md`/`BOOTSTRAP.md` into `.docket-archive/`. `doctor --json` drops the `fzf`,
    `approvalRouting`, `routingMode`, `modelConfig` and `modelRegistry` keys. The doctor footer
    now points at `docket maintain [id] check` instead of the removed `docket repair`.
  - **The `gateway` field** in `docket snapshot`, `/status.json` and the MCP `status` tool, which
    always read `inactive`.
  - **fzf:** the agent picker is the numbered one; fzf was never invoked and is no longer an
    optional Homebrew dependency.
  - **`SITES_DIR` and `DOCKET_LOG_DIR`:** `docket init` no longer creates `~/Sites` or
    `/tmp/docket`; nothing wrote there.
  - **`docket install`** in the install script and Homebrew caveats: there is no such command;
    first-time setup is `docket init`.
- **`docket auth` is gone.** Store a key with `docket keys add <NAME>`; register an endpoint
  with `docket models provider add`. `docket keys setup` walks the provider catalog instead of a
  fixed five-provider list.
- **docket no longer writes an API key into every workspace's `.env` file.** Stored keys are
  resolved only where they are read; `keys add` under the `keyring` backend either stores through
  `secret-tool` or refuses with an honest message instead of silently doing nothing.

## [0.2.0-beta.3] - 2026-09-18

The first beta with harness mode: `docket harness run` executes one governed agent turn for an
external plan-of-record and reports it as a versioned NDJSON contract. It also carries the changes
below since `v0.2.0-beta.2`, including one exit-status change: a pod dispatch or pipeline run whose
task fails now exits 1.

### Added

- **`docket harness run` and `docket harness status`** — a non-interactive entry point that runs
  one agent for one turn, to completion, in a workspace and `DOCKET_HOME` the caller supplies.
  stdout carries newline-delimited events and one versioned result and nothing else; every log goes
  to stderr. The wire contract's JSON schema is published at `docs/contracts/harness-v1/schema.json`,
  generated from the models and pinned byte-for-byte by a test, with NDJSON fixtures for the ok,
  blocked, cancelled and refused shapes at `tests/fixtures/harness-contract/v1/`. Exit status is 0
  for a completed turn, 1 for one that ran and ended badly, and 2 for a refusal before any turn
  began — the one deliberate exception to docket's otherwise
  flat return convention, because a program parsing stdout cannot read a printed message.
- **A synchronous trace subscriber seam.** `core/trace.py::subscribe` hands each sink the exact
  record about to be appended, after redaction and before the write. With no subscribers the path
  is byte-identical.

### Changed

- **A tool call that needs approval can now be refused immediately instead of waited on.** A
  caller with nobody to ask gets a typed, terminal `approval_unavailable` result naming the tool,
  the call and the policy that stopped it, in milliseconds rather than after a two-minute timeout
  repeated up to three times. The default remains unchanged: an ordinary caller still waits.
- **Cancellation now reaches an in-flight `bash` command.** `docket runs cancel` terminalizes a run
  whose hop is sitting inside a long-running shell command, killing the process group the way a
  timeout already did. Every other tool handler keeps the previous rule that an already-running
  handler may finish.
- **`docket gates enable`/`disable` help text now says what the commands do.** They record an
  approval-routing posture that `docket gates status` and `docket doctor` report; nothing on the
  live path reads it, and every `ask` verdict is answered the same way by the CLI, HTTP, MCP and
  Telegram channels regardless of it. The previous text said the flag changed where a verdict was
  delivered.
- **`docket maintain <id> sessions` no longer says sessions are never compacted.** They compact on
  the turn path once history exceeds the role budget.
- **`docket pod <project> dispatch` and `docket pipeline run` exit 1 when a task fails.** The exit
  status now matches the run record: a dispatch whose run ends `failed` exits 1, so
  `docket pod x dispatch && ...` no longer continues past a failed task. `blocked` and
  `waiting_approval` are expected pauses and still exit 0.
- **The release build pins its backend to `hatchling==1.32.0`.** hatchling 1.32.1 writes the
  unnormalized version (`0.2.0-beta.2`) into wheel metadata, where earlier releases carried the
  normalized `0.2.0b2`.

### Fixed

- **Pod output no longer drops task ids and roles, and model text can no longer crash it.** Output
  from `docket pod`, `docket trace <session>` and `docket models preset` passed data through
  terminal markup: every `[<task-id>]` and `[<role>]` was silently erased, and a task description
  or model reply containing a closing tag such as `[/bold]` aborted the command with a markup
  error (for `delegate`, after the task was already queued). All of it now prints literally.
- **Trace redaction no longer slows quadratically on long repetitive text.** Two of the
  secret-shape patterns behind `core/trace.py`'s redaction backtracked on a long run of
  alphanumeric characters (base64, a hex dump, a minified bundle), the shape a tool result takes
  near the default output ceiling: 40,000 characters took about ten seconds to redact. The
  patterns are now bounded and match exactly the same secrets.
- **The `local` preset's note names the real command,** `docket models provider add <name>
  <base-url>`; it omitted `add`, and its bracketed placeholders were erased on screen.

### Removed

- **The `security.gatesEnabled` key in `fleet.json` is no longer read or written.** Nothing had ever
  read it. An existing `fleet.json` that carries the key still loads.

### Notes

- `docket harness status` on a finished run reports the outcome but cannot recover the served model
  or the blocked rule detail, which existed only in the turn's in-memory result.

- The development history — every closed wave and phase section of `TODO.md` and `ROADMAP.md`,
  the roadmap decision changelog, and superseded coordinator handoffs — is archived verbatim under
  [docs/cycles-ended/](docs/cycles-ended/README.md) with a SHA-256 manifest
  (`scripts/maint/split_board.py check`). This file remains the user-facing release changelog.

## [0.2.0-beta.2] - 2026-09-07

This provenance-complete beta publishes the current root wheel, source distribution, versioned
installer archive, checksums, SPDX SBOM, and GitHub build provenance attestation. It includes the
Wave 29 recovery, starter, adoption-evidence, governance, and public-release work described below.

### Added
- **Reproducible adoption evidence (W29-C6).** An exact-commit generator builds and installs the
  root wheel on Python 3.11, repeats the starter and seven governance/recovery fixtures three times,
  and publishes canonical attempts, aggregates, provenance, privacy checks, and an explicitly
  limited public report under `benchmarks/results/wave29/` and `docs/ADOPTION-EVIDENCE.md`. Its
  JSON Schema publication oracle is a declared test-only dependency installed by the floor harness,
  without expanding Docket's runtime dependency set. CI jobs
  that validate the pinned source fetch complete Git history so provenance remains resolvable. The
  exact-artifact builder pins its managed Python and Hatchling closure, then canonicalizes wheel
  compression with checksum-verified zlib-ng so clean environments reproduce the published hash.
- **Provisioning startup contract** (`core/memory.py`): every agent workspace is now seeded with
  the files the OpenClaw runtime re-reads after each compaction — `WORKFLOW_AUTO.md` (anchors the
  codebase path, the read order, and a "answer about the product, not your scaffolding" directive)
  plus a curated `MEMORY.md` (with a *What this project is* product summary) and today's dated
  memory log. Fixes agents that looped after compaction demanding files that never existed, and
  that answered "what is this project about" with their own pod/workspace metadata.
- `docket doctor` now heals any agent whose startup contract is **missing or stale** (detected via
  an embedded contract-version marker), not just absent.
- **docket takes the runtime (Phase 19, decision D-19).** docket now owns the whole agent turn,
  not just what happens between turns. `core/llm.py` + `edges/adapters/llm.py` (P19-1) is a
  zero-new-dependency OpenAI-compatible chat-completions client (stdlib `urllib`) — any endpoint
  that speaks that wire format works, hosted or local. `core/tools.py` (P19-2/P19-3) is the gated
  tool registry and the single chokepoint every tool call now passes through (an AST test
  enforces it), with `pre_input`/`pre_tool_call`/`pre_output` policy hooks all actually
  evaluated — four templates shipped since Phase 11 and never once evaluated finally run.
  `core/session.py` (P19-4) gives every session durable turn history with compaction that never
  splits a tool-call/tool-result pair. `core/agent_loop.py` (P19-5), wired to dispatch through a
  new `DocketDriver` (`edges/adapters/docket_runtime.py`), is the bounded turn loop itself: max
  iterations, max tool calls, wall-clock timeout, and a measured-token budget.
- **Sandboxed exec** (P19-9) — the `bash` tool gained an opt-in sandbox (`docker` or `bwrap`
  backend, `ToolContext.sandbox`, default `"off"`), never true of the daemon's own exec path.
- **MCP client** (P19-10, `core/mcp_tools.py` + `edges/adapters/mcp_client.py`) — external MCP
  tool servers adapt into ordinary registry entries, gated exactly like a built-in and namespaced
  `mcp__<server>__<tool>` so a remote server cannot shadow `bash`. `docket mcp servers
  add/list/remove` (P19-13) makes configuring one just data, not code.
- **`fetch` tool** (P19-11) — a domain-allowlisted, size-capped, timeout-bounded HTTP fetch,
  refusing every domain by default until it is opted in (`FETCH_ALLOWED_DOMAINS`); the inspectable
  half of the network-egress story (`bash` can still reach the network through interpreters and
  package managers on the curated allowlist — a documented, open gap, not a closed one).
- **Per-role tool sets + docket-owned identity** (P19-12) — a role's tool registry is composed
  from its archetype via `ToolRegistry.without()`, so e.g. a Reviewer's registry has no
  `write`/`edit`/`bash` to call at all — structural, not instruction-level.
- **docket-owned Telegram channel** (P19-8, `core/telegram.py`) — docket itself is now the bot,
  long-polling the Bot API and routing `/approve`, `/deny`, `/status`, `/delegate` through the
  existing approval store and pod-delegation APIs. Closes a real gap: previously a Telegram reply
  answered the daemon's own, separate exec-approval prompt, which docket never saw and could not
  audit (Phase 15 G-5 spiked a bridge and found none). Every Telegram decision now writes the same
  audit entry a CLI or HTTP one does, tagged `channel="telegram"`.
- **Guardrail + loop metrics** (Phase 20, P20-2) — four new families on the existing Prometheus
  surface: `docket_tool_calls_total{decision}`, `docket_policy_hits_total{policy_id,hook,action}`,
  `docket_approvals_total{channel,outcome}`, `docket_turn_duration_seconds`. Recomputed from
  durable records at scrape time rather than an in-memory counter, so a `docket serve` restart
  never zeroes them and there is no second, driftable source of truth.
- **`docket-runtime`, a standalone embeddable package** (Phase 21, `packages/docket-runtime/`) —
  the turn loop, the gated tool registry, the policy engine, the approval store and the audit
  chain, packaged separately from the CLI so a product can embed the guardrails instead of
  reinventing them. Builds from the same source tree as the control plane, so the two cannot
  drift apart; a clean install pulls only `pydantic` and `filelock`. Deliberately not a hosted
  runtime — no multi-tenancy, external-caller auth, queues, or streaming; the embedding product
  owns its own serving layer.
- **`agentic-product` pod blueprint** (P21-5) — a fifth named pod shape alongside
  software/research/content/ops, added as a row in the existing blueprint registry.

### Changed
- **Documentation: the Telegram channel is a command surface, not a chat.** The README
  advertised "conversational dispatch — message the Lead directly", which never existed: plain
  prose is answered with an "unrecognized command" reply. Two further claims in the same section
  were also false — that a gated action "pings the wired group" (nothing is ever pushed;
  `send_message` has exactly one call site, the reply inside `poll_once`, and `core/approval.py`
  holds no reference to the module), and a setup snippet using `docket serve` when the poll loop
  only starts under `--telegram`. Corrected across `README.md`, `docs/commands.md` and
  `docs/QUICK-START-DOCKET.md`. The functional spec was accurate throughout — it has always
  required "exactly four verbs" and that any other text be treated as unrecognized — so this was
  prose drifting from a correct spec, not a spec gap.
- **`specs/functional/telegram-integration.spec.md`** now states the inbound-only property as a
  requirement rather than leaving it implicit, plus that `/delegate` answers with a task id and
  not the pipeline's output, with both added to Non-Goals. Pinned by an AST guard
  (`TestInboundOnly`) that fails if any module outside the reply path calls `send_message`, or if
  the approval store ever reaches the Telegram module — the boundary can still be moved, but not
  silently.
- **License: MIT → Apache 2.0.** Sole-copyright-holder relicense, effective from this commit
  forward; applies to the current state of the repository, not a rewrite of historical commits.
- `docket add` is repo-only and detects the codebase from the current directory (or a `path`
  argument / `--codebase`, not re-prompted), suggesting the project name from the codebase
  directory. Generated `AGENTS.md` uses the runtime-recognized `Session Startup` / `Red Lines`
  section headings so the post-compaction re-injection actually fires. Memory day math is UTC.
- **The external OpenClaw daemon is deleted, not abstracted (Phase 19 P19-6/P19-7, decision
  D-19).** A clean break with no compatibility layer and no migration: `~/.openclaw/`,
  `openclaw.json`, auth-profiles, the Anti-Corruption Layer module (`edges/adapters/openclaw.py`),
  every `openclaw` binary shell-out, and the `openclaw-gateway.service` systemd unit are all gone.
  docket's own state root is now `~/.docket/` (`DOCKET_HOME`), holding a docket-owned `fleet.json`
  (agent registration, channel bindings, gate/isolation flags, provider endpoints) in place of
  `openclaw.json`. A pre-existing install's files at the old daemon-relative paths are simply not
  read again — `docket install` re-creates a docket-native home from scratch.
  `edges/adapters/system.py`'s `gateway_active`/`restart_gateway` are kept as honest,
  always-inactive/no-op stubs so the ~20 call sites that used to restart the gateway after a
  mutating command need no individual rewrite.
- **Approval routing gained a fourth channel.** Approvals are answerable via CLI, HTTP, **MCP**
  (a client answering through `docket mcp serve`), or Telegram — all four audit-logged with the
  channel they came from, closing the Telegram gap described above.
- **The high-risk command classifier is now argument-aware** (`core/security.py`'s
  `classify_command`, wired into `core/tools.py`'s chokepoint) — it reads the whole command line,
  including every segment behind a `;`, `&&`, `||`, or pipe, so `git status` is allowed while
  `git push origin production` asks. This resolves, on every path docket itself dispatches, the
  previously-documented limitation that a binary-path-only allowlist could not distinguish the
  two; per-argument enforcement had been an explicit, tracked backlog item since Phase 13.

### Removed
- The `repo` vs `task` agent-type concept (the `AgentType` enum, the meta `type` field, and every
  `type` echo in `list`/`info`/`serve`/`snapshot` output and the read-API spec). Every project
  agent is a repo agent.
- `docket context` `search` / `index` / `snapshot` / `compress` subcommands and their artifacts
  (`.memory-index.json`, per-agent `SNAPSHOT.md`, `memory/archive/`). The OpenClaw runtime does
  semantic memory search itself; `context` is now just `show` / `project`.
- `docket workflow` — the Lobster YAML surface (`core/lobster.py`, `cli/_workflow.py`) — and its
  `wf` alias (ROADMAP D-16). docket was linting a dialect it could not fully execute: the
  validator silently ignored four constructs its own generated template emitted. Running
  `docket workflow`/`wf` now prints a removed-command notice pointing at the eventual `docket
  pipeline validate`/`plan`/`run` surface (`core/pipeline.py`, Phase 16 W-1/W-2); existing
  `<workspace>/workflows/*.lobster.yml` files are left on disk, untouched but no longer read.
- **The OpenClaw daemon dependency itself (Phase 19).** No external `openclaw` binary, no daemon
  process, no daemon-owned exec-approval prompt docket could not see. docket runs the agent turn
  itself now — see Changed, above, for what replaced each piece of daemon-owned state.
- `docket eval` — the specialist-role eval harness (`tests/evals/`, `cli/_eval.py`) (CL-J). It
  was dead code: wired to the deleted OpenClaw daemon (`WORKSPACE` under
  `$HOME/.openclaw/workspaces/<role>`, `openclaw agent --local --json`) and skipped silently
  rather than failing, which is why the drift went unnoticed. Unlike `docket workflow`/`docket
  team`, there is no replacement command — no CLI entry point runs a single agent turn to
  repoint the harness at, so it was deleted outright rather than redesigned. Running `docket
  eval`/`docket evals` now prints a removed-command notice. `docket doctor` no longer prints an
  eval-results advisory section, and the `docket eval --tier` carve-out in the tier-name removal
  rule (model-profiles.spec.md) no longer applies — tier names now have zero surviving
  user-facing use anywhere.

## [0.2.0-beta.1] - 2026-07-03

**Four feature waves land together in this release, none of which had been cut before now:**
Phase 10 (agent pods — provisioning, real dispatch, the opt-in Portfolio Manager), Phase 11
(competitive differentiation, CD-1…CD-8 — runtime-resource isolation, a mechanical verify
gate, governance/HITL, the scheduled/webhook control plane, the versioned read API),
**Phase 12 (Consolidation & hardening)** — the audit-driven pass that closed gaps the other two
left behind: a single enforced JSON-writer chokepoint, ACL-only OpenClaw shell-outs, no UI
printing from `core`/`edges`, retirement of the never-dispatched `docket team` command, a hard
exit on the deprecated tier-name vocabulary, deletion of an unused role-drift engine, a
4,194→1,702-line split of the CLI's largest module, a re-armed CI drift guard, and a spec/docs
truth pass — and **Phase 13 (Close the differentiation gaps)** — a second audit-driven pass
that found Phase 11's CD-1/CD-2/CD-3/CD-4 had already built most of what a fresh competitive
read asked for, and closed the five real residual gaps instead of rebuilding: pod resources now
reach the Implementer's actual process environment (not just TOOLS.md prose), `verifyCmd` is
settable via a public flag, the Tester hop is structurally gated on PASS/FAIL, a built-in
high-risk action-class policy always routes money-movement/secret-access actions to approval,
every approval (any channel) is now audit-logged, and exec-approval gates are **on by default**
for new installs. Full detail: `ROADMAP.md` (Phase 10/11/12/13 sections),
`internal-docs/architecture-audit.md`, and TODO.md's CH-0…CH-13 / FD-0…FD-7 cards.

> *Section consolidated 2026-07-02, extended 2026-07-03: duplicate `Added`/`Changed` headings
> merged, and the Phase 10 (agent pods) + Phase 11 (competitive differentiation, CD-1…CD-8)
> feature waves — previously missing entirely — backfilled. Two stale Bash-era claims corrected
> in place (noted inline). Phase 13 (FD-0…FD-7) folded in on 2026-07-03, the day this version
> was actually tagged.*

### Added

- **Agent pods (Phase 10).** `docket add <project>` now provisions an **isolated pod** of
  project-scoped agents — Lead + Implementer by default; `--pod full` or `--with
  reviewer,tester` for the rest — each member with its own workspace and `.docket-meta.json`.
  `docket pod <project>` manages members (`add <role> [--count N]` / `remove <member-id>` /
  listing). **programmer/reviewer/tester are no longer global shared specialists** — they are
  per-pod roles; `scope` (org vs project) is a first-class metadata axis, and `docket doctor`
  flags leftover pre-pod global role workspaces and backfills `scope` on legacy metadata.
- **Real pod dispatch.** `docket pod <project> delegate "<task>"` / `queue` / `dispatch` run a
  per-pod task queue (one queue per Lead — never shared across pods) through a hop pipeline
  (Implementer, then optional Reviewer/Tester) with per-hop cost recorded; `docket serve
  --dispatch` runs it as a background loop.
- **Org Portfolio Manager (opt-in).** `docket install --portfolio` provisions a single
  `scope: org` planning/visibility agent over fleet metadata (never project code).
- **Pod runtime-resource isolation** (CD-1, completed by Phase 13's FD-0) — each pod gets a
  **disjoint port range** and a private scratch dir, injected into the Implementer's **real
  dispatch subprocess environment** (`DOCKET_PORT_BASE`, `DOCKET_PORT_COUNT`,
  `DOCKET_SCRATCH_DIR`) — not just documented as TOOLS.md prose the agent has to read and
  remember to follow — shown by `docket pod <p>`, and reclaimed on `docket delete`/`pod remove`.
- **Git-worktree Implementer isolation** for repo pods (CD-5) — the Implementer works in a
  dedicated `git worktree`/branch, torn down with the pod; documented fallback when the daemon
  can't target a worktree.
- **Deterministic pre-merge verification gate** (CD-2, completed by Phase 13's FD-1/FD-2) — an
  opt-in per-pod `verifyCmd` — now settable via a public `docket pod <project> add --verify
  "<cmd>"` / `set-verify <member-id> "<cmd>"` (previously only an internal debug command could
  set it) — runs in the Implementer's workspace before a dispatched task can be marked done;
  non-zero exit blocks completion and emits a redacted `verification_failed` trace event; unset
  ⇒ visibly logged skip. If the pod has a Tester, its hop is now **also** gated: the first
  non-blank line of its report must read `PASS`/`FAIL` (case-insensitive); `FAIL` or unparseable
  output blocks the pipeline (`tester_verdict_failed`) instead of the Tester's word being taken
  on faith.
- **Policy template presets** (CD-3) — `templates/policies/*.json` ships curated,
  human-reviewable policy presets (`block-destructive`, `high-risk-payment`,
  `high-risk-deploy`, `high-risk-credentials`, `prompt-injection`, `secret-pii-redact`) an
  operator can inspect/apply via `docket policies show` / `policies test`.
- **Built-in high-risk action-class policy** (Phase 13's FD-3 — distinct from the CD-3 policy
  *templates* above) — `core/security.py`'s `HIGH_RISK_PATTERNS` (money-movement, prod-deploy,
  secret-access) is wired directly into what `docket gates enable` seeds, visible read-only via
  `docket gates classes`. Money-movement and secret-access are **fully enforced today** (their
  bins were never on the curated allowlist to begin with). Prod-deploy's overlap with `git`/`npm`
  is **documented policy, not daemon-enforced** — the OpenClaw exec-allowlist gates by binary
  path only, so excluding those two constantly-used bins wholesale to force enforcement would
  also block benign use (`git status`, `npm test`); per-argument enforcement is a tracked
  backlog item, not shipped behavior.
- **Headless approval channel** (CD-4, completed by Phase 13's FD-4/FD-5) — token-guarded `GET
  /approvals` + `POST /approvals/<token>` on `docket serve` (local-bind by default) alongside
  `docket approve/deny`; fail-closed expiry preserved. Every grant/deny, on **any** channel
  (CLI, HTTP, Telegram), now writes an `audit_log()` entry tagged with the channel — previously
  only a trace event was recorded. This closed condition is what unblocked **gates-on-by-default
  for new installs** (`docket install`, `--no-gates` to opt out) — see Changed, below.
- **Scheduled & webhook-triggered dispatch** (CD-6) — cron-like schedules and a token-guarded
  `POST /dispatch/<project>` endpoint turn the `serve --dispatch` poller into an event-driven
  control plane.
- **Versioned read-only API** (CD-8) — `/status.json`, `/metrics` (Prometheus text format),
  `/health` documented and contract-pinned in `specs/data/serve-read-api.spec.md`, so external
  dashboards can consume docket state; mutation stays in the CLI.
- **Lobster workflow `validate` + `plan`** (CD-7) — schema/lint a workflow and render the
  resolved pipeline docket would hand the daemon, explicitly without executing it.
- **`docket eval [--live] [--tier <t>] [--role <r>] [--recommend]`** — real specialist-role
  eval harness. Each of the six roles has a structural mode (fast SOUL.md contract check) and a
  live mode (`DOCKET_EVAL_LIVE=1`) that sends a golden task via `openclaw agent --local --json`
  and checks the response against acceptance criteria. Results are stored in
  `tests/evals/results/YYYY-MM-DD.jsonl`; `docket eval --recommend` and `docket doctor`
  surface per-role suggestions. Infrastructure failures (quota, auth, timeout) are SKIP —
  evals stay non-blocking in CI.
- **`docket cost --history [id] [--days N] [--json]`** — daily per-agent cost/turn/token
  series bucketed by session timestamp, cached in `.cost-history.json`, with a regression flag
  for any day costing more than 2× its trailing 3-day average.
- **Template/prompt versioning** — `_create_workspace` stamps `TEMPLATE_VERSION` into each
  agent's `.docket-meta.json`; `docket doctor` flags agents on stale templates and points at
  `docket maintain <id> rebuild`.
- **Declarative provisioning** — `docket add --from <agents.yaml|agents.json>` provisions a
  whole fleet from a spec file; idempotent, so a fleet file can be re-applied and kept in git.
  Example specs in `examples/configs/`.
- **`docket completions <bash|zsh>`** — emits a shell completion script (`eval "$(docket
  completions bash)"`) completing commands, subcommands, and live agent ids. Generated at
  runtime from the live Typer command registry (Phase 12 CH-8), so it cannot silently desync
  from the router the way the original hand-maintained literals did.
- **`scripts/metrics.py`** — LOC / command / test / spec counters with `--json` and `--check`
  (a CI step fails the build when the README's quoted numbers drift from the tree). Replaces
  the original `scripts/metrics.sh`, which counted the Bash `lib/` tree deleted at the M6
  cutover and had been silently blind ever since (Phase 12 CH-9).
- **`NOTICE`** — trademark/affiliation statement ("Independent project. Not affiliated with or
  endorsed by OpenClaw or the OpenClaw Foundation"), mirrored at the top of the README.
- **`COMPATIBILITY.md`** — OpenClaw version / schema support matrix, platform requirements, and
  break-reporting policy; linked from the README's Compatibility section.

### Changed

- **Exec-approval gates are now on by default for new installs** (Phase 13, FD-5) — `docket
  install` applies conservative exec-approval defaults + a curated allowlist automatically;
  `--no-gates` is the explicit opt-out (previously `--gates` was required to opt in). The
  security-gates spec's own blocking condition — a headless (non-Telegram) approval channel —
  was already met by CD-4's CLI/HTTP channels; this flip and the FD-4 audit-log parity above are
  what closed the remaining gap honestly before flipping the default. Docker workspace isolation
  (`docket gates isolate on`) remains a separate, still-opt-in layer.
- **Bash → Python rewrite (M6 cutover).** docket is now a Python package (`src/docket/`)
  built on Typer + Rich + Pydantic (plus pydantic-settings and filelock), installed via
  `uv`/pip. `bin/docket` is now a thin Bash launcher that execs `python -m docket "$@"`; all
  command logic moved to Python and the entire Bash `lib/` (commands, helpers, core) was
  removed. The code is organized in three layers — `cli/` (Typer commands) → `core/` (Pydantic
  models + pure services) → `edges/` (atomic JSON store + adapters) — with
  `edges/adapters/openclaw.py` as an **Anti-Corruption Layer**: the single module allowed to
  know the `openclaw.json` / auth-profiles / provider-config formats. Templates moved from
  `lib/templates/` to `src/docket/templates/` and ship in the wheel. Command aliases and
  removed-command notices live in `src/docket/__main__.py`.
  - **User-facing behavior is unchanged.** A golden suite (`tests/golden/run.sh verify-all`,
    17 cases at the M6 cutover, 16 as of this release — Phase 12 CH-4 retired one command)
    diffs CLI output byte-for-byte against frozen goldens, and every surviving command and
    alias still works exactly as before.
  - **Testing/tooling:** the Bash unit/lifecycle tests are replaced by a `pytest`
    suite (`tests/python/` — 416 tests at cutover, 739 as of this release), the golden parity
    suite, and the eval harness. New quality gates
    `ruff check` + `ruff format --check` + `mypy --strict` run in CI. CI jobs are now
    `python`, `golden`, `shell`, and `macos`.
  - The remaining shell surface is just the launcher, `install.sh`/`uninstall.sh`,
    `scripts/*.sh`, and the golden/eval harnesses (all ShellCheck-linted).

- **README repositioned around the ops layer** — leads with the one-line positioning
  ("cost-aware ops layer for OpenClaw agent fleets"), a pain-first *Why*, a 60-second tour,
  and a *How it relates to OpenClaw* differentiation table, with the command reference demoted
  below the fold. Replaces the prior feature-firehose ordering. The "actively used in real
  environments" line is replaced with an honest authorship note.

- `sync_session_key` now warns and skips (instead of aborting) when `openclaw.json` is absent,
  so one missing config can't halt a multi-agent provision.
- **CI lint gate raised** from `-S error` to `-S warning` (with curated excludes for
  cross-file shared vars and dynamic `source`), and the `SC2155`/`SC2188`/`SC2164`/`SC2076`/
  `SC2010`/`SC2011`/`SC2046`/`SC2115`/`SC2050` warning backlog cleared so the gate stays green.
- **Test harness hardened** — counter increments use `n=$((n + 1))` instead of `((n++))`
  (which returns non-zero at 0 and would abort a `set -e` harness); direct unit tests added
  for the `load_model_registry` overlay. *(Bash-era entry; the harness is now pytest.)*
- **`docket doctor --json` is now a usable health probe** — exits non-zero when the report is
  unhealthy (previously always exited 0), so it can gate monitoring/CI. JSON payload unchanged
  (`healthy`/`issues` were already present).
- **docket-owned JSON now has a single writer** (Phase 12 CH-1) — every write goes through
  `edges/store.py`'s atomic + filelocked + 0600 chokepoint (append-only JSONL logs in
  `core/trace.py`/`core/audit.py` are the sole, documented exemption). Closes 8+ places that
  had hand-rolled their own atomic-write logic, several without the filelock or `.bak`
  rotation the chokepoint provides.
- **`openclaw` binary shell-outs now go through the Anti-Corruption Layer** (Phase 12 CH-2) —
  `edges/adapters/openclaw.py` gained typed wrappers (`openclaw_version`, `agents_add`,
  `auth_setup_token`, `auth_paste_token`, `onboard`); `core/utils.py` no longer imports
  `subprocess` at all.
- **`core/` and `edges/` no longer print** (Phase 12 CH-3) — `core/provider.py` and
  `system.restart_gateway()` return typed results (`ProviderRegistration`, `RestartResult`);
  the `cli/` layer renders them. A new `cli/_provider.py` hosts the interactive provider flow
  that used to live in `core/`.
- **`cli/__init__.py` split from 4,194 to 1,702 lines** (Phase 12 CH-7) — `keys`/`auth` moved
  to `cli/_keys.py`, `context` to `cli/_context.py`, `workflow` to `cli/_workflow.py`, `cost`
  to `cli/_cost.py`, and agent add/info/delete/maintain to `cli/_agents.py`. No behavior
  change; goldens stayed byte-identical through every extraction stage.

### Removed

- **`docket team`** (Phase 12 CH-4, D-11) — the org-wide manual task queue never had a
  dispatcher; nothing ever executed a queued task. Running any `docket team <subcommand>` now
  prints a removed-command notice mapping to the real, executing replacement: `docket pod
  <project> delegate/queue/dispatch`. Any pre-existing
  `~/.openclaw/workspaces/manager/TASK_LIST.json` is left on disk, untouched but no longer
  read. The opt-in Portfolio Manager (`docket install --portfolio`) covers the cross-pod view
  `team` used to gesture at.
- **Tier names as model input** (Phase 12 CH-6, D-2 exit) — `economy`/`standard`/`premium` are
  no longer accepted anywhere a model or role value is expected; `docket profile <id> premium`
  and `docket models set premium <model>` now fail with an error naming a full
  `provider/model` id. A legacy `profiles:` key in `~/.openclaw/docket-models.json`
  auto-migrates to `roles:` once on load (`docket doctor` flags a residual `profiles:` key if
  `roles:` was already present and the migration left it alone).
- **`core/drift.py`** (Phase 12 CH-5) — the role-success-rate drift engine had exactly one
  caller (the opt-in `serve --dispatch` sweep) and fed a Telegram notification that was never
  implemented. Deleted along with its 3 dedicated config knobs. Unrelated to, and does not
  affect, `docket doctor`'s config-drift check (meta ↔ `openclaw.json`) or template-version
  staleness detection, both of which are unchanged.

### Security docs

- **`SECURITY.md` expanded** — explicit threat model (what runs with what privileges), the
  approval-gate model, a homelab-vs-public-VPS guidance box, secret-storage backends as
  first-class safety features, a "what docket does NOT protect against" list, and a 90-day
  responsible-disclosure timeline.

### Fixed

- **`docket --version` after install** — the installer never copied `VERSION` to the
  install prefix, so installed users got `docket (version unknown)`. `VERSION` is now
  shipped beside `lib/` and the launcher checks `$LIB_DIR/VERSION` in the installed layout.
- **Brittle installer source-patching** — `install.sh` no longer rewrites the `LIB_DIR=`
  line with `sed` (which broke silently on any whitespace change). `bin/docket` now
  auto-detects the installed (`<prefix>/lib/docket-cli`) vs repo (`<repo>/lib`) layout at
  runtime, and honors a `DOCKET_LIB_DIR` override for packagers/tests.
- **`uninstall.sh` left files behind** — it removed `lib/docket` while `install.sh` installed
  to `lib/docket-cli`. Paths now match; legacy `lib/docket` is also cleaned up, and `DOCKET_PREFIX`
  is honored to mirror the installer.
- **`docket team upgrade` in installed layout** — read templates from `$DOCKET_CLI_ROOT/lib/templates`,
  which doesn't exist once installed; now uses `$LIB_DIR/templates`.
- **README-numbers CI drift guard re-armed** (Phase 12 CH-9) — `scripts/spec-coverage.sh` and
  the original `scripts/metrics.sh` both counted the deleted Bash `lib/` tree and had been
  silently broken since the M6 cutover, masked by a `|| true` on the CI step. The new
  `scripts/metrics.py --check` counts the real Python tree and Typer registry and now actually
  fails CI on drift; `spec-coverage.sh` was deleted outright rather than rewritten, since a
  faithful rewrite would immediately red-flag documentation gaps that a later fix (CH-11)
  closed separately.
- **Documentation and specification drift** (Phase 12 CH-0, CH-10, CH-11) — a full-repo audit
  found and fixed a batch of stale claims accumulated across Phases 10–11: `docs/commands.md`
  was missing sections for 8 real commands (`keys`, `auth`, `gates`, `audit`, `eval`,
  `snapshot`, `completions`, `context`); its alias table had drifted from `__main__.py`'s real
  `_ALIASES`/`_REMOVED` dicts; `docket doctor` was described as read-only despite having
  `--fix`; `specs/functional/workflow-integration.spec.md` documented a `.yaml` extension that
  was never real (the actual extension is `.lobster.yml`) and invented return codes the
  command never used; several docs (`AGENT-TEAMS.md`, `WORKFLOW-GUIDE.md`, `DOCKET.md`) still
  described the retired `docket team` as live; `QUICK-START-DOCKET.md` and `DOCKET.md` had the
  `docket context` argument order backwards. All corrected; see `internal-docs/architecture-audit.md`
  for the full findings this phase worked from.
- **Spec/data truth pass for Phase 13's changes** (FD-6) — `specs/data/docket-meta.spec.md` and
  `specs/api/cli-interface.spec.md` updated for the `--verify`/`set-verify` surface and
  env-injection behavior; a new `specs/functional/pod-dispatch.spec.md` documents the dispatch
  pipeline's hop order, gates, and failure semantics — no spec previously owned that contract;
  `specs/functional/security-gates.spec.md` brought current for the real approval-channel set,
  the high-risk action-class policy's honest (partial) enforcement scope, and the
  gates-on-by-default status.

## [0.1.0] - 2026-06-10

First tagged release. Establishes the security and write-safety baseline
("a tool I'd run on a real machine") on top of the existing agent-lifecycle CLI.

### Added

- **`docket gates`** command (`status` / `enable` / `disable` / `isolate`) — opt-in
  exec-approval enforcement on the OpenClaw daemon's native primitives: conservative
  defaults (`security: allowlist`, `ask: on-miss`, `askFallback: deny`) with a curated
  safe-bin allowlist, plus `docket install --gates`.
- **Approval routing** — `docket gates enable` writes `approvals.exec` (`mode: session`) so an
  agent's gated prompts reach its own channel, answerable via `/approve`.
- **Workspace isolation** — `docket gates isolate on` applies the daemon's Docker sandbox
  (`agents.defaults.sandbox`), Docker-gated and reversible.
- **Secret storage backends** — pluggable `file` (default, 0600 JSON) or `keyring`
  (`DOCKET_SECRETS_BACKEND=keyring`, libsecret); keyring keeps no plaintext values at rest.
- **`docket keys rotate`** and key-age hygiene (0600 `secrets.meta.json` sidecar); `docket doctor`
  flags keys past the rotation threshold (`DOCKET_KEY_MAX_AGE_DAYS`, default 90d).
- **`docket doctor`** security section — exec-approval policy, approval routing, isolation,
  config-permission hardening, the `openclaw security audit` summary, and the active secret backend.
- **`docket --version`** / `-V`, a `VERSION` file, and this changelog.
- Write-safety primitives `json_atomic_write` and `with_docket_lock` (`flock`).

### Changed

- **Scoped secret distribution** — `docket keys` syncs only the provider key an agent's model
  needs (not every key to every agent); custom/shared secrets still fan out. Atomic `.env`
  writes that preserve user-authored lines.
- All JSON writers (`meta_set`, `upsert_binding`, `remove_binding`, `remove_agent_config`,
  `oc_set`) now write atomically (validate → `.bak` → tmp → `os.replace` → 0600) under an
  exclusive `flock`, so a crash or concurrent invocation can't corrupt or lose state.
- `meta_get` / `oc_get` warn loudly when a state file exists but won't parse, instead of
  silently returning the default.
- `docket install` Step 6 hardens `openclaw.json` / `secrets.json` permissions to `600`.

### Fixed

- **Code injection in `keys.sh`** — secret values are never interpolated into Python source
  (passed via env/argv/stdin); regression-tested with a hostile value.
- `docket doctor` aborted before later checks under `set -e`/pipefail when no sandbox browser
  process was running; all sections now run to completion.
- Cleared one `shellcheck` error (SC2199, array membership test in `maintain`).

### Security

- Phase 0 (security hardening) and Phase 1 (write-safety) of the [ROADMAP](ROADMAP.md) are
  complete. Exec-approval enforcement and Docker isolation ship **opt-in** by design; on-by-default
  is deferred pending per-agent headless approval routing (see `specs/functional/security-gates.spec.md`).

[Unreleased]: https://github.com/yielab/docket/compare/v0.2.0-beta.4...HEAD
[0.2.0-beta.4]: https://github.com/yielab/docket/compare/v0.2.0-beta.3...v0.2.0-beta.4
[0.2.0-beta.3]: https://github.com/yielab/docket/compare/v0.2.0-beta.2...v0.2.0-beta.3
[0.2.0-beta.2]: https://github.com/yielab/docket/compare/v0.2.0-beta.1...v0.2.0-beta.2
[0.2.0-beta.1]: https://github.com/yielab/docket/compare/v0.1.0...v0.2.0-beta.1
[0.1.0]: https://github.com/yielab/docket/releases/tag/v0.1.0
