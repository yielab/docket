# TODO — active task board

> **This is docket's single standing TODO file.** It holds the executable cards for whatever phase is
> currently active in [ROADMAP.md](ROADMAP.md). Do **not** create per-phase task files — when a phase
> finishes, clear its cards (the phase record stays in ROADMAP) and append the next phase's cards here.
>
> **History lives elsewhere.** Every closed wave and phase section that used to sit in this file is
> archived verbatim in [docs/cycles-ended/](docs/cycles-ended/README.md) (`todo-waves.md`, with a
> SHA-256 manifest). This file holds only the usage rules, the active section and planned sections.
> Do not mine the archive for work.
>
> ---
>
> **Scheduling rule:** schedule by **file contention**, not phase number, and state ownership at
> **function** level when a file is hot (`core/tools.py` is the recurring hotspot: give one card a
> single lambda, forbid the file to another, let a third import it unchanged). A conflict is
> resolved by keeping both blocks and *importing the module* to assert nothing was lost, never by
> reading the diff and assuming.

## ▶ WAVE 116 — ACTIVE — what a joint run through Tack found (no phase; opened 2026-10-18)

> **Evidence.** On 2026-10-18 Tack ran three real tasks from its board on the operator's
> `~/.docket` (served from `e225b52e`): a development team (implementer on Sonnet 5.5), a content
> team and a research team (GPT-5.6). The rule of the run: nobody answers or grants anything
> outside the workflow. The development task is still parked on an approval; the other two
> delivered. Every task that stopped, stopped on a command any reader would call harmless. Full
> per-call trace tables, with the refused commands quoted in full, are in the gitignored
> `internal-docs/joint-run-2026-10-18/` (`trace-analysis-2026-10-18.md`, `backtick_cmd.txt`).
> The task-commit gap the run also hit was fixed before it ended (`e225b52e`).
>
> **Release.** Every card ships in `[Unreleased]`, as `0.2.0-beta.6` (declared, untagged). Batch A
> is what Tack asked for: tasks that run without a human for harmless work.
>
> | Batch | Cards | Ownership (no two lanes share a file or function) |
> | --- | --- | --- |
> | A | W116-1 → W116-2 (one worker, `security.classify_command`) · W116-3 (policy template) · W116-4 (role text, `bash` description) · W116-5 (`trace.trace_event`) · W116-6 (`dispatch._apply_result`) · W116-7 (`approval.approval_create`) — **closed 2026-10-18**, six Sonnet workers in hand-made worktrees, merges `141e8121` 7 · `a328c381` 3 · `67980b97` 4 · `f76494ad` 5 · `9c306fd0` 1+2 · `ffc0ce51` 6 | parallel |
> | B | W116-8 (inbox contract) · W116-9 (re-attach contract, asserts W116-6/7) · W116-10 (condensation) — **closed 2026-10-19**, three Sonnet workers, merges `7edd7bbb` 8 · `7f6d8e9f` 9 · `3e548efa` 10 | A merged |

### W116-1 — a quoted heredoc's body is data, not commands

**Status:** DONE 2026-10-18 (`9c306fd0`) · **Size:** M · **Read:** `docket-spec-work` skill
- **Trigger (deterministic):** `core/security.py::classify_command` treats `<<` as an input
  redirect only (`:68`), and `_logical_lines` (`:208`) splits the heredoc body into lines, so
  each body line is classified as a command. `_OPAQUE_MARKERS` (`:171`) is a substring scan of the
  whole text (`:469-474`). Reproduced:
  - Unjailed, `python3 - <<'EOF'\nprint(1)\nEOF` asks with `'print' is not on the curated allowlist`.
  - A backtick in the body asks with `command is not statically analysable (contains '`')`,
    jailed or not.
  - An apostrophe asks with `command could not be parsed (No closing quotation)`.
  - A TS arrow `() =>` parses as an output redirect.

  In the joint run, the development implementer's `green` step parked on this rule. The command
  was a `python3 - <<'EOF'` script rewriting a test file whose body held a TS template literal.
- **Goal:**
  - For a heredoc with a **quoted** delimiter (`<<'EOF'`, `<<"EOF"`, `<<\EOF`, and the `<<-`
    forms), the body is stdin data. It is removed before the opaque scan, before
    `_logical_lines`/`_split_segments`, and before binary classification.
  - The line that carries `<<` is classified as today.
  - `match_high_risk` still runs on the **full** text, body included.
- **Must not change:**
  - An **unquoted** delimiter keeps today's behaviour, because the shell expands `$(...)` and
    backticks in that body.
  - A heredoc fed to a shell (`bash`, `sh`, `zsh`, `dash`, `-c` forms) keeps its body classified
    as commands, because there the body *is* commands.
  - A heredoc whose delimiter never closes asks (fail closed).
- **Non-goals:** here-strings (`<<<`); checking path arguments; changing `SAFE_BINS`.
- **Files/functions:** `core/security.py`: a helper that cuts quoted-delimiter bodies;
  `classify_command`, `_logical_lines`, `_split_segments`.
- **Acceptance:** the oracle is the verdict and reason from `classify_command`.

  | Case | Jailed | Unjailed |
  | --- | --- | --- |
  | `python3 - <<'EOF'` whose body holds `` ` ``, `${`, `'` and `=>` | allow | allow |
  | The same with an unquoted `<<EOF` and a backtick in the body | ask | ask |
  | `bash <<'EOF'\ngit push origin main\nEOF` | ask (high-risk class) | ask (high-risk class) |
  | `cat <<'EOF' > notes/x.md` inside the roots | allow | — |
  | A heredoc with no closing delimiter | ask | ask |

  The refused command from the run (`backtick_cmd.txt`, private paths replaced by a temp root) is
  a fixture: jailed it allows, except for the policy layer, which W116-3 owns.
- **RED test:** `tests/unit/core/test_security.py`, default lane, using the table above. It fails
  today on the first row.
- **Spec:** `specs/functional/security-gates.spec.md` (0.60.0), §"Tool-approval gates" and the
  §"In-turn tool-call gate" examples.

### W116-2 — a refused redirect names the rule, not the binary

**Status:** DONE 2026-10-18 (`9c306fd0`) · **Size:** S · **Depends:** W116-1 (same function; same worker, after it)
- **Trigger (deterministic):** jailed, every binary is redirect-sensitive (`security.py:507`). An
  output redirect that `_redirects_stay_inside` (`:299`) cannot place makes `classify_command`
  emit `'<bin>' is not on the curated allowlist` (`:519-522`), and that binary may well be on the
  list. This is the mislabel `66ce844d` fixed for `/dev/null`.

  In the run it fired three times on `cat`:
  - The `red` step parked on `cat > /tmp/c.test.ts <<'EOF'`.
  - Two earlier tasks were denied on `cd src/lib/geo && cat > x.test.ts <<'EOF'`, where any `cd`
    makes placement give up (`:310`).
- **Goal:**
  - The reason names what fired: `output redirect to <target> is outside the workspace`, or
    `output redirect after cd cannot be placed`.
  - A `cd` to a **literal** relative or absolute path that resolves inside the roots is followed,
    so a later relative redirect is placed against it.
  - A `cd` with any expansion, `-`, or no argument still stops placement.
- **Files/functions:** `core/security.py::_redirects_stay_inside`, plus the `changed_directory`
  bookkeeping in `classify_command` (`:492-524`).
- **Acceptance (jailed, root = a temp dir with a `sub/` directory):**
  - `cd sub && cat > x.ts <<'EOF'..EOF` allows.
  - `cd sub/../.. && echo x > y` asks, naming the target outside the workspace.
  - `cat > /tmp/c.ts` asks with `output redirect to /tmp/c.ts is outside the workspace`.
  - `cd "$D" && echo x > y` asks, naming placement after `cd`.
  - No verdict for a `SAFE_BINS` binary contains `not on the curated allowlist`. A parametrized
    test over `SAFE_BINS` is the oracle.
- **RED test:** `tests/unit/core/test_security.py`; the first case fails today.
- **Spec:** `security-gates.spec.md`, in the same bump as W116-1.

### W116-3 — `block-destructive` matches a write to `.env`, not two words in one call

**Status:** DONE 2026-10-18 (`a328c381`) · **Size:** S
- **Trigger (deterministic):** the shipped `templates/policies/block-destructive.yaml` has the
  alternatives `(?:\.env\b.*write|write.*\.env\b)` and the same pair for `.ssh/`. They are matched
  `IGNORECASE | MULTILINE` (`core/policy.py:542`) against the rendered call. In that rendering a
  bash command's newlines are escaped, so `.*` spans a whole heredoc.

  In the run's `green` park (`policy_id=block-destructive`), the pattern matched from
  `open(p,'w').write(s)` on one line to `process.env` fifteen lines later.
- **Goal:** the `.env`/`.ssh/` alternatives fire when a write *targets* such a path:
  - a redirect to it;
  - `tee`, `cp` or `mv` onto it;
  - `sed -i` on it;
  - the `write`/`edit` tool with that path.

  They do not fire when the two words merely appear in one call. First establish the exact
  rendered text for a `bash` call and for a `write` call (`core/policy.py` around `:400-411`),
  then write the pattern against that text.
- **Non-goals:** a structured predicate or a new policy dialect.
- **Acceptance:** the oracle is the policy evaluation on each rendered call, through the public
  evaluation function.
  - Fires on: `echo k=v > .env`, `cat >> config/.env`, `tee .env`, `sed -i s/a/b/ .env`,
    `cp x ~/.ssh/authorized_keys`, and `write` with path `.env`.
  - Does not fire on: the run's heredoc script (neutralized), or `grep -r process.env src/`.
  - Every other alternative keeps its current behaviour: the existing template tests pass
    unchanged.
- **Operator step, no migration (D-57):** `install_policies` never overwrites an installed copy
  (`policy.py:581`, by contract). The CHANGELOG entry tells the operator to replace
  `~/.docket/policies/block-destructive.yaml`. The maintainer does that on this machine.
- **RED test:** the policy template tests under `tests/unit/core/` (default lane); the heredoc
  case fails today.
- **Spec:** `security-gates.spec.md`, §"Policy engine on the live path" (baseline policies).

### W116-4 — the roles that write are told to write with `write` and `edit`

**Status:** DONE 2026-10-18 (`67980b97`) · **Size:** S
- **Trigger (measured, joint run):**
  - Nothing in `core/archetypes.py::_IMPLEMENTER_BODY` (`:308`), `_WRITER_BODY` (`:484`) or the
    `bash` description (`core/tools.py:1019`) prefers the file tools. Both roles have them
    (`denied_tools=()`).
  - The development implementer created or changed files through bash heredocs four times; three
    of those calls parked.
  - Each was a write that `write`/`edit` performs root-confined, with no gate.
  - The `red` park cost 100,573 input tokens before it stopped, and 39,664 more on resume.
- **Goal:**
  - One sentence in both role bodies and in the `bash` description: create or change files with
    `write`/`edit`, not `cat >`, heredocs or `sed -i`; inspect with `read`/`grep`/`glob`; use
    `bash` to run things.
  - `POD_TEMPLATE_VERSION` (`core/pod_provisioning.py:44`) goes 4 → 5, so `pod update` reports
    existing members stale.
- **Non-goals:** enforcing it. W116-1/2 make bash correct; this makes it rare.
- **Acceptance:**
  - The rendered SOUL of an implementer and of a content-blueprint writer carries the sentence.
  - The registry's `bash` schema description carries it.
  - `pod update` on a v4 member reports it stale.
  - Goldens: if any case renders a SOUL or the tool list, regenerate it and explain each line.
- **Real-run evidence (maintainer, optional):** re-post the development task and count bash file
  writes.
- **RED test:** `tests/unit/core/test_archetypes.py` and `tests/unit/core/test_tools.py`.
- **Spec:** `specs/functional/role-archetypes.spec.md` (1.25.0).

### W116-5 — redaction keeps a trace payload valid JSON

**Status:** DONE 2026-10-18 (`f76494ad`) · **Size:** S
- **Trigger (deterministic):** `core/trace.py::trace_event` redacts the *serialized* payload
  (`:260`), then falls back to `{"text": ...}` when it no longer parses (`:262-264`). The pattern
  `[A-Z][A-Z0-9_]{5,40}_(?:API_KEY|SECRET|TOKEN|KEY)\s*[=:]\s*\S+` eats the closing `"`, `,` and
  `}`. So `redact(json.dumps({"error": "x FAKE_API_TOKEN=abc", "usage": {...}}))` is invalid JSON
  (reproduced).

  Both parked hops of the development task lost their structured `hop_finished`. Their usage could
  only be recovered by regex.
- **Goal:**
  - Parse first, redact every string value recursively, then serialize.
  - A payload that is not JSON is still redacted as text.
  - Check every other writer that redacts serialized JSON the same way (`core/audit.py`,
    `core/approval.py::_redact`), and fix any that does.
- **Acceptance:** a `hop_finished` whose `error` holds `FOO_API_TOKEN=abc` is stored as an object.
  - `usage` stays intact and the value is replaced.
  - A stored secret's exact value nested two levels deep is replaced.
  - A plain-text payload is redacted as before.
  - The oracle is the JSONL line parsed back.
- **RED test:** `tests/unit/core/test_trace.py`; the first case fails today.
- **Spec:** `specs/functional/trace-store.spec.md` (1.10.0), redaction requirement.

### W116-6 — `inputExpiryHours` reaches the questions it promises to expire

**Status:** DONE 2026-10-18 (`ffc0ce51`) · **Size:** S
- **Trigger (deterministic; the seventh unwired-setting instance):**
  - `PodSettings.input_expiry_hours` (`core/pod.py:334`, default 72) has a writer (`pod set`) and
    a display, but no reader on the dispatch path.
  - `_run_input_step` reads only the step's own `expiresHours` (`core/dispatch.py:3224`).
  - A consultation parks with `expiresAt: null` and waits forever.
  - `docs/CONFIGURATION.md` (around `:1075`, `:1197`) promises an unanswered question expires to
    `blocked` after `inputExpiryHours`.
  - `pod-dispatch.spec.md:753` says the setting is "read only by the input-step execution", which
    is false.
- **Decision:** wire it rather than delete it. Docs and spec already promise it, the sweep exists
  (`core/answers.py::sweep_expired_questions`), and an unbounded wait contradicts the re-attach
  contract W116-9 writes down.
- **Goal:** when `_apply_result` (`dispatch.py:3616`, `task["question"] = ...` at `:3635`) parks a
  question without `expiresAt`, it stamps now plus the pod's `inputExpiryHours`. A step's own
  `expiresHours` still wins. Expiry stays `blocked`, `blockedReason: "input_expired"`, never
  `failed`.
- **Acceptance:** the oracle is the `TASK_LIST.json` record and `GET /tasks/<pod>/<id>`.
  - A pod with `inputExpiryHours=1`: a parked consultation carries `expiresAt` of about now + 1 h.
  - An `input` step with `expiresHours: 2` carries about 2 h.
  - The sweep after the deadline leaves the task `blocked`/`input_expired`, and
    `POST .../retry` reopens it.
- **RED test:** `tests/integration/test_consult_park.py`; the first case fails today.
- **Spec:** `pod-dispatch.spec.md` (6.57.0): correct the `:753` sentence. `operator-loop.spec.md`
  §7.

### W116-7 — every approval records its own deadline

**Status:** DONE 2026-10-18 (`141e8121`) · **Size:** S
- **Trigger (deterministic):** a pre-hop gate approval (`requireApprovalRoles`, a pipeline
  approval gate, an enqueue-time `require_approval`) is created with no `expiresAt`.
  `core/approval.py::_expiry_deadline` (`:555`) falls back to `created + APPROVAL_TIMEOUT`
  (900 s). So `ApprovalView.expiresAt` is `null` while the record is denied 15 minutes later.

  A client re-attaching after a restart cannot tell how long it has.
- **Goal:**
  - `approval_create` (`:202`) always stores `expiresAt`: the given value, else
    `created + APPROVAL_TIMEOUT`.
  - The fallback in `_expiry_deadline` is deleted (D-57), unless a test proves another writer
    still omits the field.
- **Acceptance:** a pre-hop gate approval's record, `GET /approvals` view and inbox item all carry
  `expiresAt = created + 900 s`. `TestExpirySweepDenies` in
  `tests/integration/test_approval_gated_dispatch.py` passes unchanged.
- **RED test:** `tests/unit/core/test_approval.py`.
- **Spec:** `security-gates.spec.md` §"Approval tokens and approval packs";
  `serve-read-api.spec.md` (3.10.1), approval view.

### W116-8 — `GET /inbox` carries a consultation's options

**Status:** DONE 2026-10-19 (`7edd7bbb`) · **Size:** M · **Depends:** batch A merged
- **Trigger (deterministic):** `TaskView.question` is typed `Question`
  (`core/operator_contract.py:314`). A consultation's `kind`, `options` and `recommendation`
  (`QuestionV11`) survive in memory for notifications (`core/inbox.py::_task_question`) but are
  dropped from `GET /inbox`, MCP `inbox` and `inbox --json`. Tack reads `GET /tasks/<pod>/<id>`
  to offer the options, and its captured fixture records the gap.
- **Goal:**
  - The inbox item's question carries the v1.1 fields when the stored question has them.
  - The inbox schema under `docs/contracts/` is bumped to describe them.
  - Text output and notifications are unchanged.
- **Non-goals:** the memory-entries follow-up below. It needs the same contract bump: fold it in
  only if the integrator says so, otherwise run it after this card.
- **Acceptance:** for a parked consultation with two options:
  - the `GET /inbox` item has `kind`, every option's `id`/`label`, and `recommendation`;
  - `inbox --json` is equal to it;
  - answering with an `optionId` taken from the inbox resumes the task (existing test).

  The oracles are the HTTP body validated against the bumped schema, and `test_consult_park`.
- **RED test:** `tests/integration/test_serve_inbox*.py` or a new file; it fails today on `options`.
- **Spec:** `operator-loop.spec.md` (1.9.0) and `serve-read-api.spec.md` (3.10.1).

### W116-9 — the re-attach contract is written down and pinned

**Status:** DONE 2026-10-19 (`7f6d8e9f`) · **Size:** S · **Depends:** W116-6, W116-7
- **Trigger (explicit request):** after its runner restarted and abandoned live tasks, Tack asked
  which re-attach contract it may rely on. The behaviour holds today from durable state, but:
  - `specs/api/operator-api.spec.md` (5.8.0) lists "stop and resume rules of the daemon" in scope
    and has no section for them;
  - no test checks `approvalToken`/`question` on `GET /tasks/<pod>/<id>`;
  - no test answers across a server restart;
  - nothing tells a client that `failed` + `stale_claim` is transient under `--dispatch`, or that
    an `idempotencyKey` binds to its pod for good (a retry after a failure returns the failed
    task).
- **Goal:** a section "Re-attaching after a restart" in the operator API spec, with these rules
  and a test for each:
  - `GET /tasks/<pod>/<id>` serves any task from disk.
  - A token or question is answerable after either process restarts.
  - Answers do not start a sweep; the next tick (30 s) or `POST /dispatch/<pod>` does.
  - Use one `idempotencyKey` per attempt.
  - Expiry and its final states are as stated (W116-6/7).
  - `stale_claim` is resumed by the next sweep.
- **Acceptance (integration, temp `DOCKET_HOME`, stub endpoint):**
  - A task parked `waiting_approval` under one server instance: a fresh instance over the same
    home returns its `approvalToken` and `expiresAt`, a grant moves it to `pending`, and the next
    sweep resumes it at the gated hop.
  - The same for `waiting_input` through `POST /tasks/<id>/answer`.
  - A consultation's `question.options` appear on `GET /tasks/<pod>/<id>`.
  - The oracles are the HTTP bodies and `TASK_LIST.json`.
  - No `src/` change is expected; a failing test is a defect fixed in this card.
- **RED test:** `tests/integration/test_serve_reattach.py` (default lane).
- **Spec:** `operator-api.spec.md`, new section, minor bump.

### W116-10 — condensation keeps the cached prefix

**Status:** DONE 2026-10-19 (`3e548efa`) · **Size:** M · **Read:** `docket-context-runtime` skill
- **Trigger (the mechanism is deterministic; the size is an estimate, so measure first):**
  - `core/session.py::condense_history` (`:317`) recomputes its cut on every request and moves it
    one result at a time (keep 2, 6,000 characters).
  - So the first changed message usually sits right after system + tools, and the provider's
    cached prefix ends there.
  - Joint run, development implementer `red` step: 7 of 11 follow-up calls missed the prefix
    (cache reads fell to 2,876 and 4,157 tokens), and the hop wrote 42,942 tokens to cache.
  - Estimate across the three tasks: about 52.6k of 129.7k uncached input (~41%) re-processed
    earlier content.
- **Goal:** condense in batches with hysteresis. Once the whole results exceed the budget, cut down
  to a low-water mark, so the projection stays byte-identical for several calls and moves only at
  a batch boundary.
- **Non-goals:**
  - Changing K or the 6,000 budget beyond the low-water mark.
  - Moving the Anthropic `cache_control` breakpoint (P44-9), unless the bench shows it misplaced.
- **Acceptance:**
  1. **Unit:** over a sequence of growing histories, every message before the newest
     assistant/tool pair is identical between consecutive projections, except at batch
     boundaries. The test asserts the count of those boundaries.
  2. **Bench:** `scripts/maint/context_replay.py` over the recorded `red` and research steps
     (private copies) reports prefix-stable calls and counted tokens (the new-token rule) before
     and after. Adopt only if counted tokens fall on both. The numbers go in the card's close note,
     labelled as estimates.
  3. **Risk to watch:** condensing earlier can cause re-reads. The research step re-read three
     condensed files at calls 9-11. A real run (maintainer-approved) counts re-reads before this
     card closes.
- **RED test:** `tests/unit/core/test_session.py` (prefix stability); it fails today.
- **Close note (2026-10-19, estimates from the replay bench over the joint run's recorded steps):** counted tokens did not rise on any step; the researcher step fell (prefix-stable calls 8/14 to 9/14, prefix-aware counted 11,750 to 9,970), the implementer step was unchanged (3/5) because its first result alone exceeds the 6,000 budget and forces a boundary, the writer step unchanged. The unit test shows the mechanism on 2,000-character results: 9 prefix changes over 12 histories down to 5. Acceptance 3 (re-read count on a real run) is open: it is measured in the next joint run with Tack.
- **Spec:** `specs/functional/session-history.spec.md` (1.8.0), condensation requirement.

## ◇ Phase 44 closed 2026-10-18

> Phase 44 (context in layers and a budget that counts new tokens, D-64,
> [ADR 0028](docs/adr/0028-context-in-layers-and-a-budget-that-counts-new-tokens.md)) closed
> 2026-10-18: ten cards over Waves 112-115 and a paid real rerun, archived in
> [docs/cycles-ended/todo-waves.md](docs/cycles-ended/todo-waves.md). Acceptance partly met: no
> step reaches the budget, the critic keeps its verdict and sends 0.20 of before, the researcher
> 0.43; the two implementers send 0.77 and 0.80 (follow-up below). The rerun's four defects are
> fixed (`a20af9bf`, `66ce844d`, `e831923d`, `ce8c41a7`). No phase is planned; the follow-ups with
> named triggers stay in the section below.

## ◇ FOLLOW-UPS WITH TRIGGERS — found in Phases 43-44 (not cards; triage when a trigger fires)

- **Found integrating Wave 116 batch A (2026-10-18).**
  - **Shell keywords are classified as binaries when unjailed.** `for t in a; do ...; done` asks
    with `'for' is not on the curated allowlist` (also `do`, `done`, `if`, `then`, `while`).
    Jailed, the allowlist stands down and the loop runs. Pre-existing; the run's parked command
    ends in such a loop, so it still asks without the sandbox. Trigger: an operator running
    without isolation reports it.
  - **`security-gates.spec.md` keeps a paragraph that verifies the old `.env\b.*write`
    alternatives** ("Two `block-destructive.json` alternatives were verified..."), now
    describing a pattern that no longer exists. Delete it with the next spec touch.
  - **Worker worktrees lack the `mcp` extra**, so `mypy src` (anyio) and `gen_cli_docs.py`
    (`click`) fail there; every worker reported it. Packet §0 should say `uv run --extra mcp`
    for those two gates.
- **Found in the 2026-10-18 joint run (Wave 116 evidence).**
  - **Gateway models have no context window.** All 49 `request_fit` events said
    `unknown_window`: `templates/providers/05-ai-gateway.yaml` declares no model rows with
    `contextWindow`, so request-fit compaction can never act for gateway-routed models.
    - Largest request: 14,233 tokens.
    - Trigger: a gateway-routed request refused for size, or a step whose largest request passes
      half the model's documented window.
    - Then: record `contextWindow` from the gateway's `/models` probe, or declare the rows.
  - **A parked turn is paid twice.**
    - The development `red` step spent 100,573 input tokens before parking.
    - Its `approve_task` grant went unused: the re-run hop never re-issued the call.
    - The resume added a compaction call (9,065 in) and a cold first call.
    - Trigger: after W116-1..4, a real run that still parks on a write.
    - Then: weigh resuming the session over re-running the hop (operator-loop §2 item 6 keeps
      this a non-goal today).
  - **Hop language drift.** The resumed Sonnet `red` step wrote its final report in Chinese, and
    that report became the `green` step's handoff. This happened once.
    - Trigger: a second occurrence.
    - Then: a pod `language` setting rendered into the handoff instruction.
  - **Task commit subjects are cut mid-word.** `core/dispatch.py::_pin_hop_tree` takes the
    description's first line at 72 characters (`...with a Sources sectio`). Cut at a word boundary
    when that function is next touched.
  - **Two measurement gaps.**
    - `edges/adapters/llm.py::request_part_bytes` uses ASCII-escaped `json.dumps`, so a non-ASCII
      part counts high: 18,037 B against 11,367 B of UTF-8, measured.
    - `llm_call` carries no per-call `cacheWrite`; only hop totals do.
    - Fix both with the next measurement card.
  - **No `node_modules` in a task worktree is pod configuration, not docket.** Under a task's
    `network: none`, the agent turn cannot install dependencies. A pipeline `run:` step keeps the
    pod's network posture (see below), so it can install them before the implementer. Five of the
    `red` step's 12 calls went on finding this out. Reported to the client.

- **Found at the Phase 44 close.** The two implementer steps of the real rerun did not send under
  half (0.77, 0.80): every request shrank to a fifth to a third, but the trajectories grew (12 and
  20 calls against 8 and 5), partly from retrying a toolchain the jail could not load (now a grant
  and a 126 message). Trigger: a real implementer run with the needed grants declared that still
  sends over half of its 03:38 counterpart; then measure which calls repeat before cutting
  anything. No grant is declared on this machine's live home (the operator's call). The rerun's
  pod names are in already-pushed history (ADR 0027, the operator API spec, a test); the tree
  no longer carries them, and rewriting public history is the maintainer's call.

- **Found in Wave 115 (Phase 44).** Pending memory entries show in `docket inbox` (text and
  `--json`) but not in `GET /inbox`, MCP `inbox`, notifications or Telegram `/status`: that needs
  an operator-v1 inbox contract bump and `notify.py`/`telegram.py` edits (operator-loop item 7's
  "`GET /inbox` equals `inbox --json`" was already broken by approved-ready tasks).
- **Found in Wave 114 (Phase 44).** `core/telemetry.py` has no structural key for
  `memory_update` (the generic handler serves it); members stamped `POD_TEMPLATE_VERSION` 4 before
  P44-7's method line show stale to `pod update` by text comparison (v4 never shipped);
  `scripts/smoke_workflow.py`'s memory scenario now seeds MEMORY.md directly and needs a live run.
- **Found in Wave 113 (Phase 44).** `_resolve_hop_instructions` still opens "You are the
  Implementer..." (SOUL says it); recipe roles using `${codebaseOrConfigured}` (secure-build
  security-vetter) still render a path; `cli/_agents._create_workspace` (standalone agents)
  still writes HEARTBEAT/promise text; `repo_map.SKIPPED_DIRS` mirrors `toolbox.SKIPPED_DIRS`
  (pinned by an equality test); a condensation notice carries the call's full path; pod read
  routes do not carry `tokenBudget`.
- **Found in Wave 112 (Phase 44).** The prospective budget check compares the whole calibrated
  input estimate plus reserve against the counted budget, so a heavily cached step is refused
  early; discount by the previous call's cache reads if a real run is refused with room left.
  `glob`/`grep` still walk vendored trees before filtering (pathlib cannot prune); measure before
  changing. In an in-place task on an already dirty tree, the first writing hop's `diff` carries
  the operator's own changes once (task worktrees start clean). The bench scales cached tokens by
  the sent ratio; P44-4 may need a cache-aware projection.
- **The Lead plans with the codebase path, the Implementer is rooted in the task worktree**
  (measurement 3: `tool.refused` on `read` of the codebase path, audit seq 6-7 of the throwaway
  home). The Lead's hop should name the task worktree, or the handoff should rewrite the path.
  Reproduce with any local-model dispatch in a worktree pod before scheduling.
- **Parallel tasks in a pod** -- trigger in ADR 0027 point 10. The task record and the claim
  are already per task; a card would add a `maxParallelTasks` pod setting and a bounded pool in
  `dispatch_pod`.
- **Warm workspace** -- trigger in ADR 0027 point 10 (measured 6.5 s + 15.5 s, 829 MB).
- **A task's `network: none` cuts the agent turn only** (P43-4): `verifyCmd` and `run:` steps keep
  the pod's posture; the spec says so. A parallel group's merge in `_run_group_node` drops
  `_UnitOutcome.failure_kind`, so a budget stop inside a group loses `budget`.
- **Two enqueue entry points** (P43-1): `enqueue_task` returns the task, `enqueue_task_once`
  returns `(task, created)`; fold into one when the remaining callers (`telegram.py`, `_mcp.py`)
  are next touched. A raced duplicate `idempotencyKey` under `require_approval` can leave an
  orphan approval token.
- **`trace-store.spec.md` requirement 6 says "exactly"** but the code's `EVENT_TYPES` has members
  the list never named (found by P43-2); re-derive the list from the frozenset.
- **A team's skills** (P43-7): `core/skills.py` reads only `<codebase>/.docket/skills`; a repository
  keeping `teams/<pod>/` has no per-team skills scope. `init --help` and `--name` do not mention
  teams, and the `docket pod update .docket` hint in `cli/_agents.py::_changed_since_review` is
  not team-aware.
- **Queue counts twice** (P43-6): `core/pod_report.py::task_counts` and the inline Counter in
  `cli/_status.py` (~lines 138-164) compute the same mapping; point `status` at `task_counts`.
  `pod_report._caller_default` reads `sys.stdin.isatty()`, so under `docket start` the report's
  approval default depends on the daemon's stdin.
- **`POST /pods/<p>/apply` edges** (P43-8): a pod with no recorded codebase reviews against
  `directory.parent`; an all-skip apply writes no `pod.apply` audit entry (pre-existing rule).
- **Corrections cursor** (P43-9): a client must percent-encode `+` in `since` (a raw `+` decodes
  to a space and is `400`); a pod whose Lead was removed but whose ledger remains answers `404`
  (existence is `dispatchable_pods()`, the same rule as `GET /pods`).
- **Dead after the harness deletion** (P43-12, proven by `rg`): the `inPlace` meta key has no
  writer (reader `core/dispatch.py::_ensure_task_worktree`, `docs/CONFIGURATION.md`,
  `specs/data/docket-meta.spec.md`; `tests/unit/core/test_task_worktrees.py` sets it by hand);
  the `verify["touched"]` key (`dispatch.py` around `_evaluate_mechanical_gate`,
  `system.git_worktree_fingerprint`, `core/evidence.py`) only fed the harness `files`; evidence
  1.0.0 (`task_evidence(..., "1.0.0")`, `EVIDENCE_V1`, `docs/contracts/evidence-v1`,
  `scripts/gen_evidence_schema.py`) has no `src` caller. Delete under D-57 when the next card
  touches `core/dispatch.py` or `core/evidence.py`.
- **Cancel over HTTP reports `cancelled` once the stop is requested** (P43-10): the task stays
  `running` in the store until the executor notices; a consumer polls `GET /tasks/<pod>/<id>`.
  The slow-stub cancel path is not covered by a test (the test seeds a run record).
- **`cli/_task.py::_pod_codebase`** is a second reader of the implementer's codebase beside
  `core/pod_report._codebase` and `core/dispatch.task_diff`; one core helper when next touched.
- **Real-Docker tests over their duration ceiling under load** (`test_network_lockdown.py`,
  `test_sandboxed_exec.py`, `test_escape_matrix.py[docker]`): pass alone, fail when five suites
  run at once. A flake, not a regression; measured 2026-10-14.

## How to use this board (read before claiming a task)

1. **Claim:** set Status → `IN-PROGRESS (@you)`. One agent per task.
2. **Read first (bounded):** use `$docket-roadmap` to load the active card, its named ROADMAP
   decision/section, the owning spec, and the card's own "Read" list. Do not ingest all of
   `ROADMAP.md`, `TODO.md`, or local `CLAUDE.md` as startup context.
3. **Layer rule (non-negotiable):** `cli/ → core/ → edges/`, inward only. docket-owned JSON goes
   **only** through `edges/store.py` (JSONL append logs are the one D-12 exemption), external
   protocols terminate in `edges/adapters/`, and there is no compatibility layer for the retired
   daemon. Every shell-out goes through `edges/adapters/`. `core/`/`edges/` never import `ui.py` or
   print (D-3 from Phase 12).
4. **No-behavior-change rule, except where a card says otherwise:** the golden suite
   (`bash tests/golden/run.sh verify-all`) must stay byte-identical unless a card explicitly adds new
   CLI surface — those cards say so and require regenerated goldens with the diff explained.
   **Regenerating a golden to paper over an unintended behaviour change is never acceptable**; W-6 in
   particular must prove the four legacy roles still emit byte-identical workspaces.
5. **Definition of done (per task):** acceptance criteria pass · a pytest covers it (add/refresh a
   golden case if output changes) · `uv run ruff check . && uv run ruff format --check . && uv run
   mypy src && uv run pytest` green · `bash tests/golden/run.sh verify-all` green ·
   `bash scripts/validate-specs.sh` green · `uv run python scripts/gen_cli_docs.py --check` green
   (regenerate `docs/commands.md` whenever a Typer docstring or help text changes) · `uv run pytest
   tests/agent` green when prose or an artifact moved · the integrator re-measures
   `scripts/metrics.py --check` per batch (card branches that add tests fail it by design) · the
   card's own spec updated with a version bump + changelog entry (integrator-applied in a
   multi-agent wave), **Status line matching what actually shipped** · committed `Type: description`
   (no Claude/Co-Authored-By trailer) · public-repo privacy scrubbed (grep the diff for real names /
   `/home/<user>` paths before committing).
6. **Central files:** `ROADMAP.md`, `TODO.md` and `README.md`'s metric counts are maintained by the
   integrator, **not** by card branches. Phase 14 lost time to roll-up checkboxes and README test
   counts conflicting on nearly every merge; cards now report what they shipped instead of editing
   the board.

**Status legend:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs X)` · `DONE`
**Size:** S ≈ ½ day · M ≈ 1–2 days · L ≈ 3–5 days (split before claiming if L)
**Branch model (D-52, amending D-31):** **`develop`** is the integration branch. Every card
branch or isolated worktree bases on `develop` and is integrated into `develop` without
rewriting history. **`main`** stays the canonical public/default and release lineage: it moves
only by a fast-forward (or a merge) from `develop`, when the maintainer cuts a release or
decides `main` has fallen too far behind. Tags and release jobs still originate from `main`.
`platform` may remain as a synchronized historical ref, but it is not a release source.

---


