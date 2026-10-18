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
