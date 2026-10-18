# Wave 116 worker packets — what a joint run through an external board found

Coordinator: the session that wrote Wave 116 to `TODO.md` on 2026-10-18. **Base commit: the
commit that added this file on `develop`**
(`git log -1 --format=%h -- .agents/handoffs/wave-116-worker-packets.md`). One card, one worker,
one isolated worktree each; W116-1 and W116-2 share one worker, in that order. The card
(`python3 .agents/skills/docket-roadmap/scripts/card_packet.py W116-<n>`) is the contract; this
file is the map. **Read §0 and your own packet only.** Line numbers were located on `develop` at
`e225b52e` and drift; re-locate every symbol with `rg -n` before editing.

| Batch | Card | Worker | Owns | Owning spec |
| --- | --- | --- | --- | --- |
| A | W116-1, then W116-2 | Sonnet | `core/security.py` (`classify_command`, `_logical_lines`, `_split_segments`, `_redirects_stay_inside`, one new helper); `tests/unit/core/test_security.py` | security-gates |
| A | W116-3 | Sonnet | `templates/policies/block-destructive.yaml`; its tests under `tests/unit/core/test_policy.py` | security-gates (baseline policies) |
| A | W116-4 | Sonnet | `core/archetypes.py::_IMPLEMENTER_BODY`, `_WRITER_BODY`; `core/tools.py` the `bash` description string only; `core/pod_provisioning.py::POD_TEMPLATE_VERSION` | role-archetypes |
| A | W116-5 | Sonnet | `core/trace.py::trace_event`, `redact` (and a recursive helper); `tests/unit/core/test_trace.py` | trace-store |
| A | W116-6 | Sonnet | `core/dispatch.py::_apply_result` (the `task["question"]` write only); `tests/integration/test_consult_park.py` | pod-dispatch, operator-loop §7 |
| A | W116-7 | Sonnet | `core/approval.py::approval_create`, `_expiry_deadline`; `tests/unit/core/test_approval.py` | security-gates (approval tokens), serve-read-api |

Merge order is the table order. The integrator owns `CHANGELOG.md`, `TODO.md`, `ROADMAP.md`,
`README.md`, `specs/README.md`, `docs/adr/` and `docs/commands.md`, and renumbers spec changelog
entries when two cards bump one spec (W116-1/2, W116-3 and W116-7 all touch
`security-gates.spec.md`: each writes its entry under the version it believes is next; the
integrator orders them on merge).

## 0. Rules for every worker

- **Isolation.** You are in your own worktree on your own branch, based on the base commit. Run
  `git merge-base HEAD <base-sha>` **before your first edit and again before committing**; it
  must print `<base-sha>` exactly, otherwise stop and report. Audit your commit with
  `git diff --stat <base-sha>..HEAD`, never `git diff --stat HEAD`. **Never touch `~/.docket`**;
  it is the operator's live home with a running server. Every manual CLI run sets
  `export W=$(mktemp -d); export DOCKET_HOME=$W/.docket` (two statements; **never override
  `HOME`**). pytest isolates `DOCKET_HOME` through the autouse fixture in `tests/conftest.py`.
  **Never call a real model endpoint.** A hop in a test runs against the stub server in
  `tests/integration/llm_stub.py` (fixture `llm_server`); the keyless provider document is
  `tests/conftest.py::register_local_provider`.
- **Commands.** `env -u VIRTUAL_ENV uv run ...` for everything. `grep` is ripgrep here; use
  `command grep` for literal greps over the diff. Never `pkill`/`killall` anything: sibling
  workers run suites at the same time, and a live `docket start` is running on this machine.
- **Never `git stash`, in any form** (no `stash push`, no tagged stash). Set work aside with a
  WIP commit if you must.
- **Spec first, test first.** Patch the owning spec (version, last-updated date, changelog entry,
  requirement text), write the RED test, run it and record the failure reason, then implement the
  smallest change. One-line test docstrings; no card ids or dates in test files.
- **Layers.** `cli/ -> core/ -> edges/`, inward only. `core/` never prints and never imports
  `ui.py`. Docket-owned JSON goes through `edges/store.py`. Every tool call still goes through
  `core/tools.py::dispatch_tool`.
- **Ownership.** Edit only the files and functions your card names, the owning spec and its
  tests. A change you need elsewhere is a locator in "Later follow-ups", not an edit.
- **Comments.** Docstrings at most three lines; no narrative comments. Run
  `env -u VIRTUAL_ENV uv run python scripts/maint/comment_lint.py --check <touched files>` and
  `env -u VIRTUAL_ENV uv run python scripts/maint/measure_function_spans.py --check`.
- **Goldens.** `env -u VIRTUAL_ENV bash tests/golden/run.sh verify-all` must pass unchanged.
  Only W116-4 may recapture a case, and it explains every changed line.
- **Gates before the return:** `env -u VIRTUAL_ENV uv run ruff check . && env -u VIRTUAL_ENV uv
  run ruff format --check . && env -u VIRTUAL_ENV uv run mypy src`; `env -u VIRTUAL_ENV uv run
  pytest -q -p no:cacheprovider`; the goldens; `bash scripts/validate-specs.sh`; `env -u
  VIRTUAL_ENV uv run python scripts/gen_cli_docs.py --check`. `scripts/metrics.py --check` is the
  integrator's (it fails on a branch that adds tests).
- **Privacy (this repo is public).** Nothing committed names the measured projects, their pods,
  their repositories, the verifier, a home path, a username or a key. Say "the development
  team", "the content team", "the research team". Before committing: `git diff --cached |
  command grep -niE '/home/|/tmp/claude|@gmail|sk-'` must print nothing, and neither must a
  grep for the private names your prompt gives you (they are not written in this file).
- **Commit** on your branch with `git -c core.hooksPath=/dev/null commit`, subject `Type:
  description` (Fix:/Add:), ASCII, **no AI mention and no Co-Authored-By trailer**, a body that
  names the spec version and the RED reason. Do not merge, do not push, do not touch `develop`.
- **Return** the delta shape of `.agents/skills/docket-roadmap/references/multi-agent-delivery.md`
  "Worker return", with the CHANGELOG line you would have written. No logs.

## Batch A

### W116-1 then W116-2 — heredoc bodies and redirect reasons (Sonnet, one worker)

- `classify_command(command, *, roots=(), jailed=False, ...)`: read the signature first. `roots`
  are `Path`s. The opaque scan is at the top (`_OPAQUE_MARKERS`), then `match_high_risk(text)`,
  then `_split_segments` over `_logical_lines`, then per-segment binary and redirect checks with
  the `changed_directory` flag.
- The reproduction table in the card is the RED test; parametrize over jailed True/False.
- Heredoc grammar to honour: `<<WORD`, `<<-WORD`, `<<'WORD'`, `<<"WORD"`, `<<\WORD`; the body
  starts on the next line and ends at a line equal to WORD (for `<<-`, leading tabs stripped).
  Quoted or backslashed means no expansion. Two heredocs on one line take their bodies in order.
  Do not implement here-strings (`<<<`).
- "A heredoc fed to a shell": the receiving segment's binary is `bash`/`sh`/`zsh`/`dash`/`ksh`,
  or the segment unwraps (`_unwrap`) to one. Then the body stays classified as commands.
- W116-2's message strings are in the card; the placement rule follows a literal `cd <path>`
  only (no `$`, no backtick, no `~` unless you resolve it, no `-`, not bare).
- The `SAFE_BINS` oracle: for every bin in `SAFE_BINS`, `classify_command(f"{bin} > /tmp/x",
  roots=(root,), jailed=True).reason` does not contain `not on the curated allowlist`.
- Spec: `specs/functional/security-gates.spec.md` 0.60.0, §"Tool-approval gates" requirement on
  statically analysable commands, and §"Exec sandbox for the `bash` tool" where the jailed
  redirect rule is written. One bump covers both cards; two changelog lines.
- The full refused command is not in the tree (private). Build your fixture from the card's
  description: a `python3 - <<'EOF'` script with `open(p,'w').write(s)`, a TS template literal
  with backticks and `${tz}`, an apostrophe in a comment, and `() => {`.

### W116-3 — the `.env`/`.ssh` alternatives in `block-destructive` (Sonnet)

- First print the rendered text the policy engine matches for a `bash` call and for a `write`
  call: `core/policy.py` around `:400-411` (`rendered=text`) and the `matches` evaluation at
  `:542`. Put that rendering in the test so the pattern is written against reality.
- The template is `src/docket/templates/policies/block-destructive.yaml`; the operator's copy is
  not touched by code (`install_policies` skips existing files, by contract). Your CHANGELOG line
  tells the operator to replace their copy.
- Existing tests for the template: `rg -n "block-destructive" tests/`. Keep every other
  alternative's tests passing unchanged.
- Spec: `security-gates.spec.md` §"Policy engine on the live path", the baseline policies
  paragraph; add the requirement that these alternatives fire on a write targeting the path.

### W116-4 — write with `write` and `edit` (Sonnet)

- `_IMPLEMENTER_BODY` (`core/archetypes.py` ~`:308`), `_WRITER_BODY` (~`:484`); the `bash`
  tool description in `core/tools.py` (~`:1019`, a string inside `builtin_registry` or its
  helper). Edit no other tool description.
- `POD_TEMPLATE_VERSION` in `core/pod_provisioning.py`; find who compares it (`rg -n
  POD_TEMPLATE_VERSION src tests`) and add the stale-report assertion to the existing test for
  `pod update`.
- Goldens: run them first to learn which cases render a SOUL or the tool list. If one changes,
  recapture that case only (`bash tests/golden/run.sh` has the per-case command) and list every
  changed line in your return.
- Spec: `specs/functional/role-archetypes.spec.md` 1.25.0, the Implementer and Writer
  requirement text, and §"Per-role tool sets".

### W116-5 — redaction keeps JSON valid (Sonnet)

- `core/trace.py::trace_event` (~`:245-265`): today `redact(payload)` runs on the serialized
  string, then `json.loads`. Reproduction: `redact(json.dumps({"error": "x FAKE_API_TOKEN=abc",
  "usage": {"input": 1}}))` does not parse. Change the order: parse, redact strings recursively
  (dict values, list items, nested), serialize. A non-JSON payload is redacted as text as today.
- Check `core/audit.py` and `core/approval.py::_redact` for the same shape; if one redacts a
  serialized JSON document, fix it the same way and say so. If it redacts a plain string field,
  leave it.
- Existing redaction tests: `tests/unit/core/test_trace.py` (`TestRedaction` or similar); add
  the three cases from the card there.
- Spec: `specs/functional/trace-store.spec.md` 1.10.0, §"Redaction".

### W116-6 — `inputExpiryHours` reaches parked questions (Sonnet)

- The write is `task["question"] = res.question` in `core/dispatch.py::_apply_result`
  (~`:3616`, write at ~`:3635`). Stamp `expiresAt` there when the question has none, from the
  pod's settings: find how `_apply_result` or its caller reaches `PodSettings`
  (`core/pod.py::PodSettings`, field `input_expiry_hours`, alias `inputExpiryHours`); the
  approval path already reads `approvalExpiryHours` at ~`:1903-1917`, copy that access pattern.
- The input-step path (`_run_input_step`, ~`:3205`) already honours the step's `expiresHours`;
  its question arrives with `expiresAt` set, so your stamp must not overwrite it.
- The sweep is `core/answers.py::sweep_expired_questions` (~`:377`); it already blocks a task
  with `input_expired`. Do not change it.
- Tests: `tests/integration/test_consult_park.py` has the parked-consultation fixtures; add the
  three cases from the card there. The time assertion is "within a minute of now + N hours".
- Spec: `specs/functional/pod-dispatch.spec.md` 6.57.0: correct the sentence at ~`:753`
  ("read only by the input-step execution") and add the requirement under §"Parked approvals"
  or the consult section; `specs/functional/operator-loop.spec.md` 1.9.0 §7 one line.

### W116-7 — every approval records `expiresAt` (Sonnet)

- `core/approval.py::approval_create` (~`:202`): when `expires_at` is `None`, store
  `created + config.APPROVAL_TIMEOUT` as ISO 8601 UTC. `_expiry_deadline` (~`:555`) then never
  needs its fallback: delete the fallback and the docstring sentence about it (D-57) once the
  test proves every pending record carries the field. `create_pregrant` (~`:284`) has its own
  `expires_at`; leave it.
- Find every writer: `rg -n "approval_create\(" src/`. If one passes `expires_at=None`
  deliberately for a reason, report it rather than guessing.
- Tests: `tests/unit/core/test_approval.py` (`TestExpiryStillFailCloses` is the neighbour);
  `tests/integration/test_approval_gated_dispatch.py::TestExpirySweepDenies` must pass unchanged.
  The view oracle: `GET /approvals` through the serve test client, or the `ApprovalView` builder
  in `core/inbox.py`/`core/operator_contract.py`, whichever is the public path.
- Spec: `security-gates.spec.md` §"Approval tokens and approval packs";
  `specs/data/serve-read-api.spec.md` 3.10.1, the approval view fields.
