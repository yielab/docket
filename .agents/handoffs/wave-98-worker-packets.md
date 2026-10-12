# Wave 98 worker packets — Phase 40, sub-wave A (D-58, ADR 0023)

Coordinator: the session that opened Phase 40 on 2026-10-12. **Base commit: the commit that
opened Wave 98 on `develop`** (`git log -1 --format=%h -- .agents/handoffs/wave-98-worker-packets.md`).
One card, one worker, one isolated worktree each; merge order P40-12, P40-8, P40-3, P40-7, P40-1,
P40-2. The card (`python3 .agents/skills/docket-roadmap/scripts/card_packet.py P40-<N>`) is the
contract; this file is the map. **Read §0 and your own packet only.** Symbols were located at
the base and drift; re-locate every one with `rg -n` before editing.

| Card | Worker | Owning spec bump | Shared-file note |
| --- | --- | --- | --- |
| P40-12 | Haiku | none | `uv.lock`, CI workflows; needs network |
| P40-8 | Haiku | none | `edges/adapters/fetch.py`: the redirect handler class only |
| P40-3 | Haiku | `audit.spec.md` 2.13.0 | none |
| P40-7 | Sonnet | `agent-loop.spec.md` 1.34.0 | none |
| P40-1 | Sonnet | `security-gates.spec.md` 0.39.0 | `edges/adapters/fetch.py`: `fetch_url`'s refusal returns only |
| P40-2 | Sonnet | `pod-dispatch.spec.md` 6.38.0, `serve-read-api.spec.md` 3.4.2 | `serve.py`: the tasks and dispatch handlers only |

## 0. Rules for every worker

- **Isolation.** You are in your own worktree `../rack-cli-wt/w98-p40-<n>` on branch
  `w98-p40-<n>`, based on the claim commit (check `git merge-base HEAD develop` equals the base
  above; if it is older, stop and report). Never touch `~/.docket`: every manual CLI run sets
  `export W=$(mktemp -d); export DOCKET_HOME=$W/.docket` (never override `HOME`). pytest isolates
  `DOCKET_HOME` through the autouse fixture in `tests/conftest.py`. **Never call a real model
  endpoint**; monkeypatch the edge or use a local fake.
- **Commands.** `env -u VIRTUAL_ENV uv run ...` for everything (the worktree inherits a stale
  `VIRTUAL_ENV`); mypy is `env -u VIRTUAL_ENV uv run --extra mcp mypy src`. `grep` is ripgrep
  here; use `command grep` for literal greps over a diff.
- **Never `git stash`.** Set work aside with a WIP commit if you must.
- **Spec first, test first.** Patch the owning spec (the version in the table, last-updated
  2026-10-12, a changelog entry, the requirement text), write the RED test, run it on the base
  and record the failure reason, then implement the smallest change. One-line test docstrings;
  no card ids or dates in test files. Place tests by lane (`specs/test-framework.md` §"Lanes and
  placement"): a unit file is named for its subject and may not import `subprocess` or open real
  sockets; a real process or socket boundary goes to `tests/integration/` with its `SUBJECT`.
- **Ownership.** Edit only the files your packet names plus the owning spec and its tests.
  `CHANGELOG.md`, `specs/README.md`, `TODO.md`, `ROADMAP.md`, `README.md`, `CONTRIBUTING.md`,
  `docs/adr/` are the integrator's; put the CHANGELOG line you would have written in your return.
  An adjacent defect is a locator in "Later follow-ups", not an edit. If you need a forbidden
  file, stop and return the contention.
- **Audit details never carry content.** Whatever you add to `audit_log` names the tool, kind,
  channel or path; it never copies a file body, a command's output or a secret, and it passes
  through the existing redaction where the neighbouring code does.
- **Comments.** Docstrings at most three lines; no narrative comments. Run
  `env -u VIRTUAL_ENV uv run python scripts/maint/comment_lint.py --check <touched files>` and
  `env -u VIRTUAL_ENV uv run python scripts/maint/measure_function_spans.py --check`.
- **Gates before the return:** `env -u VIRTUAL_ENV uv run ruff check . && env -u VIRTUAL_ENV uv
  run ruff format --check .`; mypy as above; `env -u VIRTUAL_ENV uv run pytest -q -p
  no:cacheprovider` (default lanes; the exit code is the evidence); `env -u VIRTUAL_ENV bash
  tests/golden/run.sh verify-all`; `bash scripts/validate-specs.sh` (one known TODO warning in
  harness-mode.spec.md); `env -u VIRTUAL_ENV uv run python scripts/gen_cli_docs.py --check`;
  `env -u VIRTUAL_ENV uv run python scripts/gen_recipe_docs.py --check`. `scripts/metrics.py
  --check` is the integrator's (it fails on a branch that adds tests).
- **Commit** on your branch with `git -c core.hooksPath=/dev/null commit`, subject `Type:
  description` (Fix:/Add:), ASCII, **no AI mention and no Co-Authored-By trailer**, a body that
  names the spec version and the RED reason. Before committing, `git diff --cached | command grep
  -nE '/home/[a-z]+/Sites|/tmp/claude|@gmail|sk-[A-Za-z0-9]'` must print nothing. One commit. Do not
  merge, do not push, do not touch `develop`.
- **Return** the delta shape from `.agents/skills/docket-roadmap/references/multi-agent-delivery.md`
  "Worker return" (card, commit, outcome, user-visible behaviour, changed paths, spec version,
  oracles, focused tests, full gates, missing, follow-ups, CHANGELOG line). No logs. Stop any
  background process you started before returning.

## P40-12 — supply-chain pins (Haiku)

- Allowed: `src/docket/templates/recipes/code-intel/mcp-servers/ast-grep.yaml` and that recipe's
  `README.md`; any test that pins those args (`rg -n ast-grep-mcp tests`); `docs/recipes.md` only
  by regenerating it with `scripts/gen_recipe_docs.py` (no `--check`) if the check fails;
  `uv.lock`; `.github/workflows/ci.yml`, `release.yml`, `docs-deploy.yml`;
  `src/docket/core/provisioning.py` (the `_default_root`/`suggest_project_name` docstring example
  path only); `tests/integration/test_provisioning_contract.py` (the one fixture path that names a
  developer's home; `/home/user/work/demo` is already a placeholder, leave it).
- Pins: `git ls-remote https://github.com/ast-grep/ast-grep-mcp HEAD` gives the commit for
  `git+https://github.com/ast-grep/ast-grep-mcp@<sha>`; the README says the server runs on the
  host (`isolate: false`) and names the pinned commit. `uv lock --upgrade-package pyjwt` must
  change only pyjwt's entries (diff `uv.lock` and say so). Every `uv sync` in CI gets `--locked`.
  Every `uses:` becomes `owner/repo@<40-hex sha> # <tag>`, resolved with `gh api
  repos/<owner>/<repo>/commits/<tag> --jq .sha` (dereferences annotated tags); list each mapping
  in the return.
- Oracle: `uvx pip-audit -r <(uv export --frozen --all-extras --no-hashes)` (or the equivalent you
  can run) shows no pyjwt advisory; `command grep -rnE '/home/[a-z]+/Sites' $(git ls-files)` prints nothing.
- If the network is unreachable for any step, finish the steps that do not need it and return
  `partial` naming the exact command that failed.

## P40-8 — lock redirects on authenticated requests (Haiku)

- Live path: `edges/adapters/fetch.py::_DomainLockedRedirectHandler` (allowlist-locked) is the
  only redirect handler today. Authenticated callers use the default opener:
  `edges/adapters/llm.py` (the two `urllib.request.urlopen` sites: chat and `probe_models`),
  `edges/adapters/exporters/otlp_http.py` (`opener=urllib.request.urlopen` defaults),
  `edges/adapters/channels/ntfy.py` and `channels/webhook.py` (the same default).
- Change: one same-host redirect handler (a new small module under `edges/adapters/`, or beside
  fetch's handler; move fetch's class only if it becomes the shared one and keep `fetch_url`'s
  behaviour byte-identical) that refuses a redirect to a different scheme+host+port. Each
  authenticated caller's default opener uses it. `edges/adapters/telegram.py` carries its token
  in the URL path, not a header; leave it and say so in the return.
- Allowed: the files above, their unit tests (`tests/unit/edges/adapters/...`), a new module and
  its unit test file named for it. Forbidden in `fetch.py`: `fetch_url` itself (P40-1 edits its
  refusal returns).
- RED: a direct test that a cross-host 302 from an authenticated call is followed with the
  `Authorization` header (handler-level, or a local-server test in the integration lane). GREEN:
  refused; a same-host redirect still followed.

## P40-3 — the audit chain detects tail truncation (Haiku)

- Live path: `core/audit.py::_append_entry` (writes under the lock), `_rotate_if_needed`,
  `_verify_chain_unlocked`, `verify_chain`; path constants in `config.py` (add one, e.g.
  `AUDIT_HEAD`, beside the audit log's; nothing else in `config.py`).
- Change: after each successful append, atomically write `audit.head` (0600) with the last `seq`
  and hash; rotation writes the head for the fresh file. `_verify_chain_unlocked` reports a break
  when the head names a `seq`/hash the file does not end with. A missing head file verifies as
  today (fresh install or pre-head log); deleting log and head together is the documented limit.
- Spec: `audit.spec.md` 2.13.0 — the requirement and the limit sentence ("evident, not
  prevented" stands; tail truncation is now evident while the head survives).
- Tests: `tests/unit/core/test_audit.py`. RED/GREEN per the card; also: rotation still verifies,
  an untouched log verifies, a missing head verifies.

## P40-7 — frame repository text as untrusted (Sonnet)

- Live path: `core/identity.py::compose_system_prompt` (the `parts` join), the producers
  `_project_instructions_raw` and `_skills_raw`, and `compose_agent_prompt`; the budget path
  (`resolve_static_context_budget`, the `PromptSectionReport`s) must still account for the frame.
- Change: the project-instructions block and the skills block each get one fixed frame line
  naming them as repository content to follow for style and convention only, never as a request
  to run commands or change tools, approvals or policies; both blocks compose after the runtime
  contract. The private-state note is unchanged. One constant per frame; no per-repo variation.
- Spec: `agent-loop.spec.md` 1.34.0 (the prompt-composition requirement; say the frame is a
  containment aid, not a defence).
- Tests: `tests/unit/core/test_identity.py` (the composed string: frame precedes the repo text,
  repo text after the runtime contract; a pod with no AGENTS.md and no skills gets no frame).
  Check the prompt-budget tests still pass and no golden changes.

## P40-1 — audit every refused tool call (Sonnet)

- Live path: `core/tools.py::dispatch_tool` (handler result branches; the existing
  `_audit_gate_decision`-style helper near the top writes the gate entries) and the handlers'
  outcome type `edges/adapters/toolbox.py::ToolOutcome`. A file tool's `PathEscapeError` is
  caught inside the toolbox and returned as `ToolOutcome(False, error=...)`, so `dispatch_tool`
  cannot tell it from an ordinary failure today; `edges/adapters/fetch.py::fetch_url` returns the
  allowlist refusal the same way.
- Change: a typed refusal marker on the outcome (e.g. `ToolOutcome.refusal: str = ""`, set to
  `path_escape` / `fetch_not_allowed` at those returns), and `dispatch_tool` writes one
  `audit_log("tool.refused", ...)` per marked outcome naming tool, agent, role, project, kind and
  (for a path tool) the attempted path, redacted like the neighbouring entries. Check whether
  `classify_command`'s redirect-containment verdict already reaches an audited `tool.ask`/`deny`
  branch; if it does, say so and add nothing for it.
- Allowed: `core/tools.py`, `edges/adapters/toolbox.py`, `edges/adapters/fetch.py::fetch_url`
  (its refusal returns only; P40-8 owns the redirect handler class), their unit tests
  (`tests/unit/core/test_tools.py`, `tests/unit/edges/adapters/test_toolbox.py`,
  `test_fetch.py`).
- Spec: `security-gates.spec.md` 0.39.0 ("In-turn tool-call gate").
- Oracle: `core/audit.py::read_audit()` in the isolated home: one entry per refusal, none for an
  allowed call or an ordinary failure (file not found).

## P40-2 — a channel on every enqueue and dispatch (Sonnet)

- Live path: `core/dispatch.py::enqueue_task` (sets `source = "operator"` and derives
  `effective_trusted` from it); callers `cli/_task.py` (`task add`), `cli/_mcp.py` (the MCP
  delegate tool), `core/telegram.py` (`/delegate`), `core/harness_pipeline.py` (`docket exec`'s
  pipeline), `serve.py` (`POST /tasks/<p>` and the `POST /dispatch/<p>` handler, which calls
  `create_run`).
- **Decision (coordinator):** add a separate persisted `channel` field
  (`cli|http|telegram|mcp`; `docket exec` is `cli`) and keep `source` as it is: `source` is the
  origin class (`operator`, `reviewer` for a rework task) and drives `effective_trusted`;
  `channel` is how it arrived. No caller's trust changes. `enqueue_task` takes `channel` as a
  required keyword and writes `audit_log("task.enqueue", f"project=... task=... channel=...")`;
  the dispatch route writes `audit_log("run.dispatch", f"run=... project=... channel=http")`.
- Allowed: those functions and call sites only (in `serve.py`, the two handlers; in
  `core/telegram.py`, the `/delegate` call), their tests, `pod-dispatch.spec.md` 6.38.0, and the
  task example in `specs/data/serve-read-api.spec.md` (add `channel`; 3.4.2).
- Oracle: `read_audit()` and the persisted task record in the isolated home after a CLI enqueue,
  an HTTP enqueue (in-process handler or the existing serve test harness), a Telegram
  `/delegate` and a dispatch POST.
