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
> **Scheduling rule:** schedule by **file contention**, not phase number. Cards that edit the same
> files run one after the other, and work that would touch the same files twice belongs to one card.
> Parallel lanes are allowed only when they share no file, spec, persisted state or live environment;
> finishing a card well matters more than running two at once.
>
> **NO ACTIVE WAVE.** Phases 52 and 53 (D-73 to D-75, ADRs 0033 to 0035) closed 2026-10-29; their
> sections are archived and what they leave open is under "Phases 52 and 53" in the follow-ups below.
> Phase 51 closed 2026-10-25 (D-72, [ADR 0032](docs/adr/0032-one-escalation-record-and-one-resolve.md));
> its loose ends are under "Escalations". The integration branch is `develop`. A new phase starts from a
> measured trigger or a maintainer request. **Phase 54** (D-76, a native Anthropic Messages dialect)
> is planned below and waits for a go.

## How work runs on this board (read before claiming a card)

1. **One card is one worker run.** Its steps are ordered; each step ends green and committed. A run
   that does not finish parks at its last green commit and the card's Status names what is left; the
   next run continues the same card. A card is never split into sub-cards to make it fit.
2. **Claim.** Set Status to `IN-PROGRESS (@who)`; one owner per card. The worker gets a worktree made
   by hand from the integration branch's current head (`git worktree add -b <branch>
   .claude/worktrees/<card> <sha>`), and its own `DOCKET_HOME` and temp directory in the scratchpad.
3. **Read bounded.** `python3 .agents/skills/docket-roadmap/scripts/card_packet.py <CARD-ID>`, then
   the card's own read list. Never all of `ROADMAP.md`, `TODO.md`, `CLAUDE.md` or a spec directory.
   A task worktree has no `internal-docs/` (gitignored); a card needs only itself and tracked files.
4. **The layer rule** is ADR 0030's table, enforced by `tests/architecture/`: the contexts are layered
   `platform < governance < agent < models < observability < pipeline < teams < sandbox < operator <
   tasks < hops` and a context imports only those below it; `kernel` imports nothing outside itself;
   a `domain/` is pure; only `interfaces/` talks to the user; `bootstrap.py` is the only module that
   names a concrete adapter. Two invariants never move: every tool call passes `dispatch_tool`
   (`agent/tools/registry.py`), and docket-owned JSON is written only by `platform/store.py`.
5. **The testing budget, the same for every card.**
   1. Per commit: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run
      pytest --co -q` (about 10 s). No test runs.
   2. While iterating: only the tests of what the step changed, by path, each under `timeout 120`.
   3. The card's gate, as the card names it, in a few minutes.
   4. A pure move or rename adds no test: `pytest --co` and `tests/architecture` are its check. A
      behaviour change adds a failing test first, placed by lane (`specs/test-framework.md`).
   5. After each merge the integrator runs the default suite once, in parallel (`uv run pytest -n auto
      --dist loadfile -q --tb=line -p no:cacheprovider > <file>`, about 85 s), reads only the `FAILED`
      lines, fixes by cause and re-runs `--lf`. Never a second full run for the same merge. What
      each check costs, measured, is in `.agents/skills/docket-spec-work/references/validation.md`.
   6. Goldens, the agent lane, `scripts/maint/pytest-without-sandbox.sh`, the escape matrix,
      `validate-specs.sh`, the generated-docs checks and the real run: once, at
      the phase close. The agent lane (about 5 min) runs on a committed tree: its release check
      refuses any uncommitted path.
   7. **Stop rule:** a check that fails again after one fix stops the step. Park with the failing line
      and the hypothesis. No third attempt, no "until green", no background process or polling, no
      `git stash` (a WIP commit sets work aside).
   8. **A script is a means, not a deliverable.** A one-shot script (planner, path rewriter,
      converter) exists to save effort on the card's goal. Write it once, run it, review its output,
      and finish by hand whatever it did not cover. If it is wrong after one fix, stop improving it
      and do the remainder by bounded edits. Polishing, generalizing or testing a throwaway script is
      out of scope; it is never committed unless the card says so.
6. **Baselines only shrink.** A baseline file is rewritten (`--write`) only after the violations are
   gone, and its diff is deletions only. A new guard is trusted only after it was seen failing on a
   planted case.
7. **No behaviour change** unless the card says so: the HTTP API 6 tests, the CLI goldens and the
   `docket_runtime` facade stay byte for byte. **No re-export or shim:** a replaced name is
   deleted in the same change, with no alias or compatibility reader.
8. **Central files are integrator-owned:** `TODO.md`, `ROADMAP.md`, `README.md` metric counts and
   `CHANGELOG.md`. A worker reports what shipped; it does not edit them.
9. **Commits:** `Type: description`, ASCII only, a detailed body, no AI or assistant attribution.
   Scrub `/home/<user>` paths and real names from every diff.

**Status:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs X)` · `PARKED (left: X)` · `DONE`.
**Size:** S ≈ one short run · M ≈ one run · L ≈ one long run that may park once · XL ≈ two cards'
scope in one pass over the same files, parks at least once.
**Branch model (D-52):** card branches base on and merge into the integration branch (`develop`).
`main` moves only
by a fast-forward from `develop` when the maintainer cuts a release. Tags and release jobs originate
from `main`.

## ▶ PHASE 54 — the native Anthropic Messages dialect (D-76) · PLANNED, waits for a go

> **Why.** The built-in `anthropic` document speaks Anthropic's OpenAI-compatibility layer, which
> drops `cache_control` and reports no cache field: every Haiku and Sonnet request on `fab-dev` pays
> its whole prefix. Measured 2026-10-29 with two identical requests of about 8,400 tokens: compat
> reported `prompt_tokens` 8417 twice and no cache field; `/v1/messages` reported
> `cache_creation_input_tokens` 8410, then `cache_read_input_tokens` 8410. What share of a hosted
> run's input is a repeated prefix is **not measured** (the compat layer reports nothing); the same
> request builder gives 77.5 % to 83.1 % cache hits against local llama.cpp over six smoke runs.
> Tokens are measured, dollars are not: no card claims a saving.
>
> **Shape.** One Sonnet card owns the code, the wire's spec and the tests, because the encoder, the
> decoder, the fake server and the seam test exchange the same shapes and splitting them would make
> two workers rediscover one contract. One Haiku card owns the prose, which shares no file with it
> and runs in parallel. The integrator records the real bodies first and runs the live measurement
> last. Nothing above `models/adapters/` changes: the turn, the tools, the gates and `ModelProfile`
> talk to the `ChatBackend` port (`agent/ports.py`) and never see a wire shape.

**Integrator, before the spawn (two Haiku calls and one refused, about 9k tokens):** **done 2026-10-29**,
recorded under `tests/fixtures/anthropic-messages/`, byte for byte as returned: `tool-use.json` (one
`bash` call, `input {"command": "ls"}`; the block also carries `caller`, which the encoder never sends
back), `end-turn-cached.json` (the next step of the same conversation: `input_tokens` 6,
`cache_creation_input_tokens` 69, `cache_read_input_tokens` 8986) and `error-unknown-model.json`
(HTTP **404** `not_found_error`, not a 400). The status code is not in the body, so the test states it.
These fixtures are what the decoder is tested against, so no decode test invents a body.

**Wave 1** (parallel; merge P54-1 first, then P54-2):

| Card | Model | Size | Owns |
| --- | --- | --- | --- |
| P54-1 | Sonnet | L | `models/adapters/`, `catalog.py:209`, `01-anthropic.yaml`, `model_server.py`, model-profiles spec, the tests |
| P54-2 | Haiku | S | ADR 0011, `docs/MODEL-GATEWAYS.md`, `docs/README.md`, `cli-json-shapes.spec.md` |

**Integrator, after both merges:** the default suite once and the e2e lane (the wire changed); then
the operator step and the live measurement of P54-1's last acceptance item; then the close (spec
index rows, ROADMAP status, archive this section).

### P54-1 — a second dialect, `anthropic-messages`, on the same client

**Status:** TODO · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** the maintainer's request (2026-10-29) and the measurement in the section header,
  which meets ADR 0011's deferral trigger (`docs/adr/0011-provider-catalog.md:148-152`) as far as it
  can be measured before the dialect exists.
- **Goal:**
  1. `ProviderSpec.dialect` (`models/catalog.py:209`) is `Literal["openai-chat",
     "anthropic-messages"]`.
  2. `OpenAIChatClient` (`models/adapters/openai_http.py:52`) becomes one client that takes its
     wire from the dialect: the request path, `build_payload`, `decode_response` and
     `request_part_bytes`. The transport, the timeouts, the error handling, `_headers`,
     `estimate_input_tokens` and `Retry-After` stay one copy. `_DIALECTS` (`:325`) maps each dialect
     to its wire; `client_for` (`:336`) is unchanged. Rename the class only if the name would lie
     (`ChatClient`), and then in the same change everywhere it is named, with no alias.
  3. A new `models/adapters/anthropic_wire.py` encodes and decodes `POST {baseUrl}/messages`:

     | docket | `anthropic-messages` |
     | --- | --- |
     | `system` messages | the top-level `system`, as text blocks; not in `messages` |
     | assistant `tool_calls` | `tool_use` blocks `{id, name, input}`, `input` the parsed `arguments` object (a string that does not parse is sent as `{}`); an empty assistant text is no block |
     | `tool` messages | `tool_result` blocks `{tool_use_id, content}`; consecutive results in one `user` message |
     | `ToolSpec` | `{name, description, input_schema}` |
     | `tool_choice` name | `{"type": "tool", "name": ...}`; none sends no key |
     | `max_tokens` | required: the request's value, else the endpoint's `max_output_tokens`; with neither, the call fails before sending (`nonzero_exit`), naming the model and `docket setup provider add <provider> --model <id> --max-tokens N`; never an invented number |
     | `temperature`, `top_p` | only when declared, as today |
     | `stop_reason` | `tool_use` → `tool_calls`, `end_turn` and `stop_sequence` → `stop`, `max_tokens` → `length`, any other value verbatim |
     | `content[]` of the reply | text blocks joined into `content`; `tool_use` blocks into `ToolCall`s with `arguments` the compact JSON of `input` |
     | `usage` | `input_tokens` = `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`; `cached_tokens` = read; `cache_write_tokens` = creation (both subsets of input, as `TokenUsage` says) |
     | cache markers | `cache_control: {"type": "ephemeral"}` on the last `system` block and on the last block of the last message: the same two places as requirement 8, for every model on this dialect |

  4. `529` (Anthropic's "overloaded") joins `_RETRYABLE_STATUS` (`openai_wire.py:25`).
  5. `templates/providers/01-anthropic.yaml` moves to `dialect: anthropic-messages`, `auth: {type:
     header, header: x-api-key}`, keeps `anthropic-version: "2023-06-01"`, and its preset note stops
     saying caching is missing.
- **Non-goals:** streaming, thinking blocks, structured outputs, server tools, images; a gateway's
  `cache_control` passthrough (OpenRouter and the AI gateway stay `openai-chat`, requirement 8
  unchanged); more than two cache breakpoints; `scripts/maint/context_replay.py`, which keeps
  encoding the OpenAI shape; the probe's matching of dated model ids (see Risks); the live home.
- **Spec:** `specs/functional/model-profiles.spec.md` 6.2.0 → 6.3.0 (MINOR). "Provider catalog"
  requirement 1 (the enum), 5 (two adapters), 8 (the markers are the `openai-chat` rule) and a new
  requirement 10, "The `anthropic-messages` dialect", holding the table above. Amend first.
- **Change** (nine files; two are one-line edits):
  - new `src/docket/models/adapters/anthropic_wire.py`;
  - `src/docket/models/adapters/openai_http.py` (`OpenAIChatClient`, `probe_models`'s use of
    `_headers`, `_DIALECTS`);
  - `src/docket/models/adapters/openai_wire.py:25`;
  - `src/docket/models/catalog.py:209`;
  - `src/docket/templates/providers/01-anthropic.yaml`;
  - `tests/support/model_server.py`: `POST /v1/messages` beside `/v1/chat/completions` (`:231`),
    decoding into the same `Request` the scripts read (`tool_result(call_id)`, the role line) and
    encoding `say`, `call`, `calls` and `fail` in the Anthropic shape, with a `usage` the test sets;
  - new `tests/unit/models/adapters/test_anthropic_wire.py` (`SUBJECT` the new module), over the
    integrator's fixtures;
  - `tests/contracts/test_model_wire_contract.py`: the same reply builders read back through the
    client on the new dialect;
  - the spec.
- **Acceptance:**
  - Encode: a conversation of system, user, an assistant turn with two tool calls and empty text,
    two tool results and a user nudge encodes to `system` blocks, then user / assistant (two
    `tool_use`, no text block) / user (two `tool_result` then the nudge text); the cache markers sit on
    the last system block and the last block only. Encoding it twice gives the same bytes.
  - Decode, on each recorded fixture: the `tool_use` body gives `ToolCall`s whose `arguments` parse
    back to the recorded `input`; the cached body gives `input_tokens` = the sum of the three fields
    and `cached_tokens` = the read count; the error body gives `ok=False` with the message.
  - Round trip: a `tool_use` decoded and encoded again in the next request gives the same
    `tool_use` block, so the prefix stays byte-identical across steps.
  - The seam, through the real producer and parser: `DocketDriver().run_turn` for a pod member on a
    `kind: provider` document with `dialect: anthropic-messages` against the fake server runs a
    `bash` call and a closing tool, the request carried `x-api-key` and no `Authorization`, and the
    `llm_call` trace event carries the `cachedTokens` the fake reported (place it beside
    `tests/integration/agent/test_bash_background.py::TestTheTurnLeavesNoOrphan`, which shows the
    pattern, in a new file under `tests/integration/models/llm_port/`; it is the tenth file and only
    a test).
  - `max_tokens` unknown: the call fails before any request reaches the fake, naming `--max-tokens`.
  - `openai-chat` unchanged: `tests/integration/models/llm_port/` and the existing contract tests
    pass untouched, the anthropic-marked compat bodies included.
  - The built-in catalog still loads all fourteen documents (a document that fails validation is
    skipped silently, so assert `anthropic` is present and on the new dialect).
  - Live, by the integrator after the merge: one Haiku smoke run on the new dialect shows
    `cachedTokens` > 0 on its second and later `llm_call` events; the figure is reported as tokens.
- **Gate:** static per commit; `tests/unit/models/adapters/`, `tests/integration/models/`,
  `tests/contracts/test_model_wire_contract.py`, `tests/architecture/`; the e2e lane once (about
  42 s, the wire changed). Not the full suite.
- **Risks:** a wrong `usage` mapping corrupts budgets and `docket log` silently, hence the decode
  test on a real body. Haiku 4.5 has no observed `maxTokens` in the live home
  (`state/provider-models.json` holds `claude-sonnet-4-6` only; the native `/models` lists dated
  ids), so after this card the Lead fails loudly until the operator declares it; the probe matching
  dated ids is a follow-up, not this card. Recent Claude models refuse `temperature` and `top_p`
  together; docket sends neither unless a document declares them.
- **Contention:** none with P54-2. `openai_http.py`, `openai_wire.py` and `model_server.py` are
  nobody else's in this wave.

### P54-2 — the docs say there are two dialects

**Status:** TODO · **Size:** S · **Model:** Haiku · **Kind:** docs

- **Trigger:** P54-1 changes what is true about the anthropic provider; AGENTS.md: the prose changes
  in the same work.
- **Goal:**
  - `docs/adr/0011-provider-catalog.md`: a closing section "Amendment (2026-10-29): a second
    dialect" of at most twelve lines. It says the deferral at `:148-152` was resolved by D-76, with
    the measurement from this section's header; D-18's reading at `:218` stands; D-42's cut of a
    second dialect is reversed for `anthropic-messages` only; the refused list from D-76's ROADMAP
    row. The body of the ADR is not edited.
  - `docs/MODEL-GATEWAYS.md:110-114` and `docs/README.md:170-175`: the direct `anthropic` provider
    speaks Anthropic's Messages API and uses its prompt cache; the compatibility layer's limits stay
    true for anyone who registers it by hand; gateways still speak `openai-chat`.
  - `specs/data/cli-json-shapes.spec.md:383`: `"dialect": "string (openai-chat | anthropic-messages)"`,
    with a PATCH version bump.
  - `README.md:24` stays: it says "any OpenAI-compatible model", which is still true; do not widen it.
- **Non-goals:** a new guide; any figure in dollars; numbers beyond the ones D-76 states.
- **Spec:** `cli-json-shapes.spec.md` PATCH only.
- **Change:** the four files above.
- **Acceptance:** every sentence checked against model-profiles requirement 10 as P54-1 amends it
  (read the card's table if the spec is not merged yet); `scripts/maint/comment_lint.py --check` and
  `bash scripts/validate-specs.sh` (the spec index carries the version) pass.
- **Gate:** the two checks above; no test runs.
- **Contention:** none with P54-1; merge after it so the prose never describes a dialect the code
  does not have.

## ◇ FOLLOW-UPS WITH TRIGGERS (not cards; triage when a trigger fires)

> Re-checked against the code on 2026-10-24; paths are current. Removed as no longer true: notification
> dedup is persisted (`operator/notify.py`), the `kind:`-less canonical-document advisory is gone, and
> `_create_workspace` no longer exists. Decisions that belong to the maintainer are in ROADMAP §7.1.

**Toolchain read grants (dropped from Phase 48).** A sibling project's gates failed with exit 126 under the
jail until each toolchain under `$HOME` (`~/.nvm`, `~/.pyenv`, `~/.cargo`) was granted by hand with
`docket setup sandbox read add`. Trigger: a second pod whose first jailed gate fails that way. Next:
`docket setup` proposes the grants for the toolchains it finds.

**Fired, waiting for a maintainer go (the measurement spends hosted-model tokens).**

- **The implementer sends 0.65 of what the backend counts** (Phase 45 real runs on `fab-dev`,
  2026-10-20: 14 and 13 calls, largest request about 7,000 estimated tokens; reviewer 0.62, tester 0.80
  and 0.90). The Phase 44 trigger ("a real implementer run with its grants declared that still sends
  over half") fired. Next: P52-1 measures which calls repeat on the recorded traces (no live run
  needed); P53-4 (which absorbed P52-5) acts on the figure.

**Model adaptation and context (ADR 0033, deferred with triggers; the cards are Phase 52).**

- **Reasoning kept inside the turn** (`ChatMessage.reasoning`, resent only in the active tool
  loop; `reasoning_content` is dropped today in `models/adapters/openai_wire.py::decode_response`).
  Trigger: a profile that declares `reasoning: interleaved`.
- **Lifecycle condensation** (a `read` superseded by a later `read` or an `edit` of the same file
  is evicted first, in batches aligned to steps). Trigger: after P52-2 (which absorbed P52-8), the bench `--repeats`
  still shows re-reads on the recorded implementer steps.
- **A bounded model escalation** on a step (`escalate: {on: [verify_failed, no_progress], model:
  strong, max: 1}`), audited. Trigger: the `strong-plan-cheap-edit` recipe (P52-6) fails
  `verifyCmd` on a measured share of real runs.
- **A lazy MCP catalog** (`mcp_describe(server, tool)`, the tool list kept stable within a turn).
  Trigger: a pod whose MCP schemas exceed its built-in ones (`request_part_bytes["tools"]`).
- **A native Anthropic dialect** (1 h TTL, `cache_control` on tools, signed thinking blocks; the
  provider note already defers it). Trigger: direct use without the gateway, which caches today.

**Escalations (left at the Phase 51 close, 2026-10-25; ADR 0032).**

- **Approval, gate and `check_changed` follow-ups still run inside `resolve`** (`approval_grant`
  and the task-grant audit in `tasks/application/escalations.py`), not on the claim path; P51-6
  stopped at PARTIAL because deferring them breaks `approved_ready`, which reads pregrants and
  `gateOverridePipelineIndex`, and P51-9's "Also" list named the move. Trigger: a change to
  `approved_ready` or to the claim path.
- **Settled escalations written before P51-11 stay in the flat `escalations/` directory**; no
  migration is written. A scan of the live directory still opens them (`platform/store.py::list_escalations`
  reads the flat folder for `pending` and unfiltered scans). Trigger: an operator whose pre-P51-11
  records slow the inbox; then move them under `settled/` once.
- **`GET /escalations?since=` reads every settled file** (`operator/inbox.py::escalation_views`
  calls `list_escalations(since_seq=...)` with no state, so `settled/` is scanned on each poll).
  Trigger: a poller whose `settled/` directory is large; then index by `seq` or bound the scan.
- **docket follows an enclosing git repository when a pod path is not itself one**
  (`platform/git.py::git_is_repo` answers `rev-parse --git-dir`, true anywhere inside a work tree),
  so it would prepare and branch the enclosing repository. Only the live-eval and smoke worlds
  refuse that today (`specs/test-framework.md`). Trigger: a pod registered on a subdirectory or
  a nested path that is not a repo.
- **`scripts/render-doc-assets.py:275` prints a made-up approval token** (`token=apr-...`) and the
  `waiting_approval` line, shapes Phase 51 removed. Trigger: the maintainer re-captures the README
  assets (a classifier-refused step); then render the escalation id and `waiting_input`.

**Test suite under load (found at the Phase 47 close, 2026-10-24; each passes alone).**

- **Timing flakes seen once each:**
  `test_retries_and_timeouts.py::TestRetryDoesNotTripStaleClaimSweep`, and the foreground approval
  deny test (its fake approval timeout was raised from 5 s to 60 s, `1a704359`). Trigger: a second
  failure of the same test. Then replace its wall-clock wait with an event.
- **Docstring budget:** `comment_lint.py` counts 209 long definition docstrings at the close against 205
  on `develop` (most moved or renamed code). Trigger: the next card that edits one of those modules
  trims its own.
- **Two contract files set the merge run's floor** (measured 2026-10-28, `--durations=0`):
  `tests/contracts/test_a2a_http.py` 60 s and `test_escalation_http.py` 35 s of the 84 s run. Each
  test's function-scoped `parked` fixture runs a real `docket run` and starts a service (about 3 s
  of setup per test), and `--dist loadfile` keeps a file on one worker. Trigger: the merge run
  passes 120 s, or a card adds a test to either file. Then share one parked world per module for
  the read-only tests.

**Runtime and dispatch (from real runs).**

- **A refused task is resumed on every 30 s sweep tick** (`dispatch_refused` is in
  `RESUMABLE_FAILURE_KINDS`, `tasks/domain/state.py`; operator-api §6 by design). Trigger: the audit log
  fills with one task's refusals, or a second operator asks. Then resume only when the cause changed.
- **A parked turn is paid twice**: the resumed hop re-sends the whole prompt (4,157 input tokens before
  the park, 8,181 after; 100,573 in the 2026-10-18 joint run). Trigger: a third run that parks on the
  same shape. Then weigh resuming the session over re-running the hop (operator-loop §2 item 6).
- **A hop refused before any call records an empty model** (`hop_finished.model == ""`, a `""` key in
  `usage.byModel`). Trigger: a reader of `byModel` that trips on it.
- **Provider rows lag the models in use:** Anthropic advertises dated ids while the template rows use
  aliases (limits stay `unknown`), and no row prices `claude-sonnet-5-5` or `claude-opus-5-5`
  (`task show` prints `cost: -`). Trigger: a run on an alias id whose window matters, or an operator
  asking for the estimate.
- **Hop language drift:** a resumed step once wrote its report in another language, which became the
  next handoff. Trigger: a second occurrence; then a pod `language` setting.
- **The Lead plans with the codebase path while the Implementer is rooted in the task worktree**
  (`tool.refused` on `read`). Trigger: reproduce with a local-model dispatch in a worktree pod.
- **The prospective budget check ignores cache reads**, so a heavily cached step is refused early.
  Trigger: a real run refused with room left. `glob`/`grep` walk vendored trees before filtering;
  measure before changing.
- **A task's `network: none` cuts the agent turn only**; `verifyCmd` and `run:` steps keep the pod's
  posture (stated in the spec).
- **Cancel over HTTP reports `cancelled` once the stop is requested**; the task stays `running` until
  the executor notices. The slow-stub cancel path has no test.
- **Not examined:** each Phase 45 run's trace carries two `approval_denied` events beside its park.
- **Real-Docker tests exceed their duration ceiling under load** (`test_network_lockdown`,
  `test_sandboxed_exec`, the escape matrix's docker cases): they pass alone. A flake, measured
  2026-10-14.

**Workspace and checks.**

- **`docket setup` without `--fix` writes:** its report re-seeds `WORKFLOW_AUTO.md`
  (`interfaces/cli/commands/setup_check.py`). A check that writes is a defect. Trigger: the next edit
  of that file.
- **A file a check reaches only through `make` or `npm run` is protected only through the default
  files it reads**, and **a gitignored file is invisible to the check**. Trigger: a real gate whose
  script lives behind a target, or a repository that ignores a file its gate reads.
- **Prepare:** only `node_modules` is cached (`.venv` is not relocatable); `node_modules/.cache` is
  read-only in the jail; eviction can break a running task's link (resume prepares again); prepare is
  not cancellable (bounded by `PREPARE_TIMEOUT_S`); `hops/workspace/prepare.py::linked_entries` accepts
  any cache entry, not only the task's codebase. Trigger: a real run that hits one of them.
- **Shell keywords are classified as binaries when unjailed** (`for`, `do`, `done`, `if`, `then`,
  `while` ask in `governance/security`). Trigger: an operator without isolation reports it.

**Configuration.**

- **A tool deny per team member** (a read-only researcher): `tool_profile` is prose, the only denial is
  the pod-wide `deniedTools`. Trigger: a recipe or pod that needs one member without write tools.
- **Delete the old-layout reader** (`kernel/layout.py::is_legacy` and the legacy branches of `Home`).
  Trigger: the next minor release. First move what still seeds or reads an old-layout home:
  `tests/support/home.py` and `pods.py`, `benchmarks/harness.py`, `benchmarks/scenarios/run.py`, the
  adoption benchmark tests, and the old paths named in `scripts/gen_cli_docs.py`,
  `scripts/render-doc-assets.py` and `docs/commands.md`.
- **Parallel tasks in a pod:** ADR 0027 point 10 holds the trigger; a card would add a
  `maxParallelTasks` pod setting and a bounded pool in dispatch.
- **A team's skills:** `hops/workspace/skills.py` reads only `<codebase>/.docket/skills`; a repository
  keeping `teams/<pod>/` has no per-team skills scope.

**Channels, inbox and the HTTP API.**

- **`docket start`'s periodic notify flush ignores `FlushReport.error`** (`interfaces/http/server.py:200`).
- **Enabling the `email` channel checks nothing**; with no `to`, `from` or `smtpHost`, every delivery
  fails into the health record. Trigger: an operator enables it.
- **Pending memory entries show in `docket inbox` but not in `GET /inbox`, MCP `inbox`, notifications or
  Telegram `/status`.** Needs an operator-v1 inbox contract bump.
- **`GET /pods` (the list) was not checked** for the invalid-settings failure fixed on `/pods/<p>`.
- **`POST /pods/<p>/apply` with every item skipped writes no `pod.apply` audit entry.**
- **The corrections cursor needs `+` percent-encoded in `since`**; a pod whose Lead was removed but
  whose ledger remains answers `404`.
- **The `openhands` and `pydantic_ai` adapters never pass `cache_write_tokens`**
  (`packages/docket-runtime/src/docket_runtime/adapters/`). Trigger: someone reads that usage.

**Prompts and pod state.**

- `hops/application/compose.py::_resolve_hop_instructions` still opens "You are the Implementer..."
  (SOUL says it); recipe roles using `${codebaseOrConfigured}` render a path; `repo_map.SKIPPED_DIRS`
  mirrors `toolbox.SKIPPED_DIRS` (pinned by an equality test); pod read routes do not carry
  `tokenBudget`; the condensation notice carries the call's full path.
- **Every member of a pod shares the base session key `agent:<pod>:<key>`** (`teams/pod.py`); no turn
  reads it today. Trigger: a turn that does.
- **Three readers of the implementer's codebase** (`rg -n "def _pod_codebase|def _codebase|def
  task_diff" src`); one helper when next touched.
- **`memory_update` has no structural telemetry key**; members stamped `POD_TEMPLATE_VERSION` 4 show stale
  to `pod update` by text comparison; `scripts/smoke_workflow.py`'s memory scenario needs a live run.

**Phases 52 and 53 (closed 2026-10-29).** Triaged the same day: the brief redaction, the prompt `tests` file, a role's
unknown tool name, `pod test`'s handoff spec, the live-run key lookup and the stale docs were fixed; what stays waits
for its trigger.

- **P52-12, a wait on a machine is an escalation.** Trigger: one recorded Tack-driven run in which a task fails,
  re-polls or spends a hop waiting on CI, a deploy or a URL. Until then the wait sits in Tack (ADR 0034 decision 5).
- **P53-4 goal 3, the Lead's locators read into the Implementer's message.** Measured on three recorded smoke tasks
  (two local Qwen, one Haiku, `context_replay.py --repeats`): the Implementer read 1/1, 1/1 and 2/4 files the Lead had
  read, but all except one were files it then edited, whose exact text `edit` needs; "not edited after" was 0, 0 and
  1 file (682 bytes). Trigger: "not edited after" reaching 30 % of the Implementer's reads on recorded tasks of a real
  pod (the smoke repository has three files).
- **The model class comes only from the rank anchors** (`economy` is `cheap`, `standard` and `premium` are `strong`),
  so a non-anchor model such as the local Qwen resolves `any` and no `<name>.<class>.md` variant acts for it. No
  shipped prompt has a variant. Trigger: a variant written for a non-anchor model.
- **Structured `task` intake** exists on `POST /tasks/<pod>` only; the CLI, MCP and Tack's runner do not send it.
  Trigger: Tack adopting it.
- **Decided, not open:** P52-2's bench oracle is "no step worse than the recorded request, and prefix stability not
  worse", met on the fixture (sent 0.25 to 0.66 of the baseline per step; stable 8/10, 3/4, 5/7, 6/7). The "+0.3 %
  to +3 %" was against the pre-P52-2 `condense_history`, which the bench's `phase44` policy now calls live, so it is no
  longer reproducible; the small-result rule stays. The re-ask, finalization and closing texts
  (`hops/application/runner.py`, `agent/loop_request.py`) are the harness's protocol, versioned with the code and the
  agent-loop spec, not role prompts. `smoke_workflow.py` calls an interpreter running a script (`PYTHONPATH=src python3
  x.py`) opaque on purpose: it can read any file, so the private-path check fails closed; `VAR=x` alone is parsed.

**Architecture and packaging.**

- **The runtime closure grows with any facade on a context the runtime imports** (measured in P47-8:
  agent 52 -> 75, teams 52 -> 157, governance 52 -> 101, observability 52 -> 60 files). Trigger: a
  proposed facade on one of them.
- **`FailureKind` enumerates only the four kinds the task state writes**; hop and gate kinds stay plain
  strings (pod-dispatch spec item 9). Trigger: the next change to those kinds.

**Tests.**

- A worker's `monkeypatch.undo()` once undid the autouse home isolation and wrote into the real
  `~/.docket`; the fixture guards `setattr`, not `undo`. Trigger: a second leak.
