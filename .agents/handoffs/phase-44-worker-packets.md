# Phase 44 worker packets — context in layers and a budget that counts new tokens (ADR 0028)

Coordinator: the session that planned Phase 44 on 2026-10-18. **Base commit: the commit that
opened Phase 44 on `develop`** (`git log -1 --format=%h -- .agents/handoffs/phase-44-worker-packets.md`).
One card, one worker, one isolated worktree each. The card
(`python3 .agents/skills/docket-roadmap/scripts/card_packet.py P44-<n>`) is the contract; this
file is the map. **Read §0 and your own packet only.** Symbols were located on `develop` at
`5dda9d37` and drift; re-locate every one with `rg -n` before editing.

| Wave | Card | Worker | Owns in hot files | Owning spec |
| --- | --- | --- | --- | --- |
| 112 | P44-1 | Sonnet | new files only | test-framework (only if needed) |
| 112 | P44-2 | Sonnet | `agent_loop.py` budget methods; `dispatch.py::_hop_usage`, `_task_token_budget` | agent-loop, cost-tracking, operator-api |
| 112 | P44-3 | Haiku | `tools.py::builtin_registry` + four tool descriptions; `toolbox.py` glob/grep/read | agent-loop, security-gates |
| 112 | P44-5 | Sonnet | `dispatch.py::_implementer_diff_probe`, `_build_hop_result`; `handoff.py` | pod-dispatch |
| 113 | P44-4 | Sonnet | `agent_loop.py` request building; bench hook table | session-history, agent-loop |
| 113 | P44-6 | Sonnet | `identity.py`, `archetypes.py`, `dispatch.py::_hop_message` | workspace-structure, role-archetypes, agent-loop |
| 113 | P44-10 | Haiku | `agent_loop.py::_trace_llm_call`; `dispatch.py::_finalize_task` (`byModel`) | trace-store, operator-api |
| 114 | P44-7 | Sonnet | new `pod_memory.py`; one call in `_finalize_task` | workspace-structure, agent-loop, trace-store |
| 114 | P44-9 | Sonnet | `edges/adapters/llm.py` request builder | agent-loop or provider spec |
| 115 | P44-8 | Sonnet | `inbox.py`, `cli/_pod.py` | operator-loop, cli-interface |

Merge order inside a wave is the card order in the table. The integrator orders every spec
changelog (`agent-loop.spec.md` is bumped by P44-2 and P44-3 in Wave 112: each worker writes its
entry under its own version, the integrator renumbers on merge) and owns `CHANGELOG.md`,
`TODO.md`, `ROADMAP.md`, `README.md`, `specs/README.md`, `docs/adr/`. Wave 112 seam the
integrator wires at merge: P44-3's output rules as a `--policy` hook in P44-1's bench.

## 0. Rules for every worker

- **Isolation.** You are in your own worktree on your own branch, based on the base commit. Run
  `git merge-base HEAD <base-sha>` **before your first edit and again before committing**; it
  must print `<base-sha>` exactly, otherwise stop and report. Audit your commit with
  `git diff --stat <base-sha>..HEAD`, never `git diff --stat HEAD`. Never touch `~/.docket`
  (P44-1 only *reads* the files its prompt names). Every manual CLI run sets
  `export W=$(mktemp -d); export DOCKET_HOME=$W/.docket` (two statements; **never override
  `HOME`**). pytest isolates `DOCKET_HOME` through the autouse fixture in `tests/conftest.py`.
  **Never call a real model endpoint.** A hop in a test runs against the stub server in
  `tests/integration/llm_stub.py` (fixture `llm_server` via `tests/integration/conftest.py`);
  the keyless provider document is `tests/conftest.py::register_local_provider`.
- **Commands.** `env -u VIRTUAL_ENV uv run ...` for everything. `grep` is ripgrep here; use
  `command grep` for literal greps over the diff. Never `pkill`/`killall` anything: sibling
  workers run suites at the same time.
- **Never `git stash`.** Set work aside with a WIP commit if you must.
- **Spec first, test first.** Patch the owning spec (version, last-updated date, changelog entry,
  requirement text), write the RED test, run it and record the failure reason, then implement the
  smallest change. One-line test docstrings; no card ids or dates in test files.
- **Layers.** `cli/ -> core/ -> edges/`, inward only. `core/` never prints and never imports
  `ui.py`. Every shell-out goes through `edges/adapters/system.py`. Docket-owned JSON goes through
  `edges/store.py`. Every tool call still goes through `core/tools.py::dispatch_tool`.
- **Ownership.** Edit only the files and functions your card names, the owning spec and its
  tests. A change you need elsewhere is a locator in "Later follow-ups", not an edit.
- **Comments.** Docstrings at most three lines; no narrative comments. Run
  `env -u VIRTUAL_ENV uv run python scripts/maint/comment_lint.py --check <touched files>` and
  `env -u VIRTUAL_ENV uv run python scripts/maint/measure_function_spans.py --check`.
- **Goldens.** `env -u VIRTUAL_ENV bash tests/golden/run.sh verify-all` must pass unchanged
  (only P44-8 recaptures one, and explains every changed line).
- **Gates before the return:** `env -u VIRTUAL_ENV uv run ruff check . && env -u VIRTUAL_ENV uv
  run ruff format --check . && env -u VIRTUAL_ENV uv run mypy src`; `env -u VIRTUAL_ENV uv run
  pytest -q -p no:cacheprovider`; the goldens; `bash scripts/validate-specs.sh`; `env -u
  VIRTUAL_ENV uv run python scripts/gen_cli_docs.py --check`. `scripts/metrics.py --check` is the
  integrator's (it fails on a branch that adds tests).
- **Privacy (this repo is public).** Nothing committed names the measured project, its pods or
  its repository, a home path, a username or a key. Before committing: `git diff --cached |
  command grep -nE '/home/|/tmp/claude|@gmail|sk-'` must print nothing, plus the extra names
  your prompt gives you.
- **Commit** on your branch with `git -c core.hooksPath=/dev/null commit`, subject `Type:
  description` (Fix:/Add:), ASCII, **no AI mention and no Co-Authored-By trailer**, a body that
  names the spec version and the RED reason. Do not merge, do not push, do not touch `develop`.
- **Return** the delta shape of `.agents/skills/docket-roadmap/references/multi-agent-delivery.md`
  "Worker return", with the CHANGELOG line you would have written. No logs.

## Wave 112

### P44-1 — replay bench (Sonnet)

- Session layout: `core/session.py` (`load_session`; `messages` plus one cumulative `usage`
  total). **Per-call usage is not in the session**: it is in the trace, one `llm_call` event per
  call (`payload.inputTokens`, `outputTokens`, `cachedTokens`, `iteration`, `finishReason`,
  `model`), matched by `task_id` and `agent_role`. The bench takes a session file and the
  matching `llm_call` records; the anonymized fixture keeps both (only `llm_call` events, no
  other trace content).
- Estimates use `config.CONTEXT_BYTES_PER_TOKEN`; a re-projected request is
  `measured_input x new_bytes / old_bytes` for that call, printed as an estimate.
- The verdict line: the critic's pipeline gate (`core/orchestrator.py::parse_verdict`); reuse it.
- `--policy` is a small table of name -> callable over a request's messages; ship it with
  `baseline` only. Later cards add one entry each.
- Anonymizer: deterministic (seeded by a hash of the input), path segments mapped
  segment-by-segment so repetition is preserved, verdict line and tool names kept, every other
  string replaced by same-length filler. The test runs on the committed fixtures only.

### P44-2 — new-token budget (Sonnet)

- Every budget read of `total_tokens` in `core/agent_loop.py` moves to `counted_tokens`; keep
  `total_tokens` for display only if a caller needs it, otherwise delete it (D-57).
- The over-budget refusal in `call_backend_and_handle_response` stays for a reply **with** tool
  calls; a reply without tool calls is appended and returned through the normal success path.
- Calibration lives on `_TurnState` (ratio after the first measured call), applied inside the
  estimate used by `preflight_request` and `prospective_budget_error`; never below 1.
- Usage parsing in `edges/adapters/llm.py`: OpenAI shape `prompt_tokens_details.cached_tokens`
  (reads) exists; add cache writes where the body reports them (`cache_write_tokens` in
  `prompt_tokens_details`, or `cache_creation_input_tokens`), else 0.
- `core/session.py`'s usage model gains `cacheWriteTokens` (accumulated like `cachedTokens`).

### P44-3 — tool output budget (Haiku)

- `_truncate` already exists in `toolbox.py`; `grep_files` uses it, `glob_files` does not.
- Relative paths: `p.relative_to(base_root)` where `base_root` is `roots[0].resolve()`; a match
  under a second root prints relative to that root.
- `READ_DEFAULT_LINES = 400`; numbered as `f"{n:>6}\t{line}"`; an explicit `offset`/`limit` is
  also numbered. The footer only when lines remain.
- `fetch` offering: in `builtin_registry`, register `_fetch_tool` only when
  `docket.config.FETCH_ALLOWED_DOMAINS` is non-empty, read at call time. Find every test that
  expects `fetch` in the default registry and give it an allowlist through `monkeypatch`.

### P44-5 — delivered handoffs (Sonnet)

- `git_changed_files` already lists untracked files; the diff body is `git diff <base>` for
  tracked files plus the content of each new file, in path order, cut at
  `HANDOFF_DIFF_MAX_CHARS` (config constant, 8000) with a marker.
- The base is the one `_implementer_diff_probe` already resolves (`baseCommit`); keep its
  evidence shape unchanged for the implementer.
- Render the diff in `HandoffArtifact.render` after the summary; `_hop_message`'s budget
  compiler sheds it first through `DROP_ORDER` (do not edit `_hop_message`).

## Wave 113 (base: the Wave 112 rollup commit)

Wave 112 shipped: `TokenUsage.counted_tokens`, hop usage `{input, cached, cacheWrite, output}`,
bounded `glob`/`grep`/`read` (`READ_DEFAULT_LINES` 400 and `READ_DEFAULT_CHARS` 6,000, unpadded
line numbers, chosen on the bench), `fetch` registered only with an allowlist, `HandoffArtifact.diff`
for every writing hop, and the bench `scripts/maint/context_replay.py` with policies `baseline` and
`tool-output` (run `--policy NAME` on `tests/fixtures/context-replay/v1`; the integrator runs it on
the private copies).

### P44-4 — condensation (Sonnet)

- The single request-building point is `core/agent_loop.py::_TurnState.messages_for_durable`
  (called from `fit_task_request` and the finalization path). Condense there, over the durable
  list, never in `core/session.py`'s writers: `session.json` keeps every byte.
- Keep each tool message and its `tool_call_id` (an endpoint rejects a result whose call is
  missing); replace only its `content`. A condensed `write`/`edit` argument keeps the arguments
  JSON valid: replace the large string value, keep the other keys.
- The notice is a pure function of the message and its matching call (tool name, path or
  command, line and character counts): the same input always yields the same bytes.
- The task message (`_TurnState.task_message_index`) and every user message stay whole.
- Bench: add `condense-k1`, `condense-k2`, `condense-k3` and a composed `phase44` (tool-output then
  the chosen K) to `POLICIES`; choose K from the numbers and put the table in the
  `session-history.spec.md` changelog entry.

### P44-6 — prompt layers (Sonnet)

- `core/identity.py::_runtime_startup_contract` stops rendering roots (tool restriction still
  comes from `ToolContext.roots`; only the prompt text moves). `_RUNTIME_CONTEXT_FILES` loses
  `HEARTBEAT.md` and `TOOLS.md` (every live turn is a pod hop since the harness was deleted;
  confirm with `rg -n "run_turn\(" src` before relying on it). MEMORY.md composes only when it holds
  text beyond its template.
- The roots and the repository map go in `core/dispatch.py::_hop_message`'s task section, ahead of
  the prior artifacts and outside their shedding: `Working directory: <root>` plus
  `core/repo_map.py::render_repo_map(root)` (directories with file counts from a new
  `edges/adapters/system.py::git_ls_files`, relative, capped by a config constant, skipping
  `toolbox.SKIPPED_DIRS`).
- Templates live in `core/archetypes.py` (search `promise>DONE`, `HEARTBEAT`, `memory/`,
  `codebase`); the MEMORY.md template's seeded `codebase:` path line goes too (absolute path).
  `POD_TEMPLATE_VERSION` 3 -> 4; prove with a test that `docket pod update` regenerates a v3
  member and leaves MEMORY.md byte-identical.

### P44-10 — measurement fields (Haiku)

- `core/agent_loop.py::_trace_llm_call` already receives `messages`; add the tool specs it needs
  and compute `request = {system, tools, toolResults, assistant, user}`, each
  `{bytes, estTokens}` with `config.CONTEXT_BYTES_PER_TOKEN`. Edit no other function in that file.
- `core/dispatch.py::_finalize_task` builds `byModel` (search `byModel`): add `cached` and
  `cacheWrite` from the hop usage P44-2 shipped. Edit no other function in that file.
- `tokenBudget`: the per-step budget comes from `edges/adapters/docket_runtime.py::_turn_token_budget`
  and its config default; expose the effective value on the task read routes in `serve.py`.

## Wave 114 (base: the Wave 113 rollup commit)

Wave 113 shipped: `core/session.py::condense_history` (K=2, request-only, wired in
`_TurnState.messages_for_durable`), the layered prompt (`core/identity.py`: SOUL, INSTRUCTIONS,
member AGENTS, contract without roots, repo text, skills, MEMORY last and only when
`memory_has_content`; `_RUNTIME_CONTEXT_FILES = (MEMORY_FILE,)`), `core/repo_map.py` and the task
block in `_hop_message`, `POD_TEMPLATE_VERSION` 4, and `ChatResponse.request_bytes` measured by
`edges/adapters/llm.py::request_part_bytes`.

### P44-7 — pod memory store (Sonnet)

- Storage: `config.PODS_DIR / <pod> / "memory.json"` (add `config.pod_memory_path`), written only
  through `edges/store.py` (atomic, filelock, 0600). Shape: `{"entries": [...]}`, each entry
  `{id, kind, path|command, note, status: accepted|pending|refused, reason, provenance: {task,
  date, commit}}`; cap by count (config constant), oldest accepted dropped first.
- The hop's memory section: a trailing block the step result may end with (pick one fixed
  marker, e.g. a `## Memory` heading followed by `- generated: <path> -- <note>` lines; one line
  per entry, closed kinds only). Document the exact grammar in `workspace-structure.spec.md` and
  in the shared method block of the member templates (one line; P44-6 owns those templates and
  is merged, so you may edit that block only).
- Verification: `generated` -> the path exists at the task's commit (`git cat-file -e
  <commit>:<path>` through a new `edges/adapters/system.py` helper); `command` -> an exit status
  for that command in the task's trace (`process_exited`/`command_step` events; locate with rg).
  `pitfall`/`convention` -> `pending`. A hop whose trace has any `fetch` tool call -> every entry
  `pending`. Imperative free text (a note starting with a verb in the imperative, or containing
  "ignore", "always", "never run", URLs) -> `refused` with a reason; keep this rule small and
  explicit, and screen each note with the same pre-input screen the task intake uses (locate
  `_enqueue_pre_input_gate` in `core/dispatch.py` and reuse its screening call, do not copy it).
- Merge point: one call from `core/dispatch.py::_finalize_task` (nothing else in that file).
- Render: `core/identity.py` composes accepted entries as the last system section, behind the
  same untrusted frame as repository instructions (`REPO_INSTRUCTIONS_FRAME`-style constant of
  its own), capped (config constant); an entry whose path is gone from the hop's root is omitted.
- Every change writes a `memory_update` trace event (add it to `EVENT_TYPES`) and an audit entry.
- Delete the per-member daily-log seeding and the pod-task distillation that nothing feeds
  (`core/memory.py`, its callers and tests; D-57), keeping `pod reset`'s behaviour coherent and
  stated in the spec.

### P44-9 — `cache_control` for Anthropic models (Sonnet)

- Anthropic model = the endpoint's model id, after any `<vendor>/` prefix, starts with `claude`
  (covers the `anthropic` provider and `anthropic/...` on a gateway). No catalog field.
- In `edges/adapters/llm.py::build_payload` only: for such a model, the system message's content
  becomes one text part `{"type": "text", "text": ..., "cache_control": {"type": "ephemeral"}}`
  and the last message's content likewise (a tool message too). Every other model's payload is
  byte-identical to today (pin with a test over a recorded payload).
- `request_part_bytes` must still count the encoded parts.
- The real-gateway check is the integrator's, after merge, with maintainer approval: two calls
  with the same prefix, the second must report `cached_tokens > 0`.

## Wave 115 (base: the Wave 114 rollup commit)

Wave 114 shipped `core/pod_memory.py` with the typed API `list_entries(project, status)`,
`approve(project, id, *, actor)`, `refuse(project, id, reason, *, actor)`, `revert(project, id,
*, actor)`, `reset(project, *, actor)` (raise `PodMemoryError` on an unknown id or wrong state;
`revert` leaves a refused tombstone), entries in `config.pod_memory_path(pod)`, and
`cache_control` for Anthropic models (verified on the gateway).

### P44-8 — memory operator controls (Sonnet)

- `docket pod memory list [--status accepted|pending|refused] [--json]`, `docket pod memory
  approve <id>`, `refuse <id> --reason`, `revert <id>`, `reset` (confirmation, `--yes`), all
  under the existing `pod` group in `cli/_pod.py` (no new top-level command: D-57's eleven stay),
  the pod from `--pod/-p` or the cwd like every pod verb. Every action goes through the
  `core/pod_memory.py` API with `actor="cli"`; the API already audits.
- `docket inbox` lists pending memory entries beside parked tasks, in `core/inbox.py`'s existing
  view model (locate the parked-task view and add one item kind; do not fork the renderer).
  Approval from the inbox is the same `approve` call.
- Regenerate `docs/commands.md` with `scripts/gen_cli_docs.py`; recapture only the goldens whose
  help text changes and explain every line.
