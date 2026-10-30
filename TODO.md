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
> **NO ACTIVE WAVE.** Phase 55 (D-77, [ADR 0036](docs/adr/0036-a-pod-works-outward.md)) closed 2026-10-30: a pod
> works outward, on its own schedule; its section is archived and what it leaves open is under "Phase 55" in the
> follow-ups below. **Planned: Phase 56** (ADR 0036 decisions 13-14, accepted 2026-10-30): an external service is
> declared, not programmed; nine cards P56-1..P56-9 over four waves, starting on the maintainer's go. Phases 52 to 54
> closed 2026-10-29. The integration branch is `develop`. A new phase starts from a measured trigger or a maintainer
> request.

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

## ○ PHASE 56 PLANNED — an external service is declared, not programmed (D-77 amendment, ADR 0036 decision 13)

> Planned 2026-10-30 from the maintainer's request after the Phase 55 real run: a pod reaches an external
> service nobody programmed in advance, configured by a document or by commands, with no MCP bridge per
> service and no further MCP implementation work. Scope accepted by the maintainer the same day
> ([ADR 0036](docs/adr/0036-a-pod-works-outward.md) "Amendment", decision 13): a header token for auth
> (OAuth later, see the amendment); JSON and text; the call runs in docket's process, not the jail; every
> method (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`); operations written by hand **and** imported from an
> OpenAPI document; an MCP server and a service never share a name; the quota counts per service. Phase 55
> closed 2026-10-30; the cards start on the maintainer's go. Each card's trigger is that request; no metric is invented.

### How a Phase 56 card runs (read before claiming one)

- The rules of Phase 55's cards hold: spec first, RED test, smallest change, the spec row bumped in
  `specs/README.md`, goldens edited by line and never regenerated, `uv run --all-extras mypy src` in a
  worktree. The owning spec is new: `specs/functional/service-client.spec.md` (P56-3 creates it; the
  other cards each own one section, named on the card).
- **A tool named `svc__<service>__<operation>`.** Every card uses this name and the access rule:
  `GET` defaults to `read` and may be declared `send`; `POST`, `PUT`, `PATCH` and `DELETE` are always
  `send`, and a document that declares one of them `read` is refused naming the operation.
- **Writes are handled apart (the maintainer: "las que editan tendrían un manejo especial").** A
  writing operation is a `send`: it reaches only a role whose own `tools` list names it (the pipeline
  puts it on one acting agent, as the `outward` actor), a person approves the whole call (P55-4),
  it is audited `tool.send` and counted by its service's quota. A `DELETE` offers only `approve_once`
  and `deny`, never "approve for this task". An agent that vets the call before the person (a critic
  step) is a pipeline choice, as in the `outward` recipe, not code.
- **Nothing leaves the machine in a test.** The fake service is `http.server` on `127.0.0.1` inside the
  test, listed in the service document so the loopback refusal lets it through.

### P56-1 — make room: `config_docs.py` and `apply/plan.py` lose their mcp-server code to a sibling

**Status:** TODO · ready, Phase 55 closed 2026-10-30 · **Size:** S · **Model:** Sonnet · **Kind:** pure move

- **Trigger:** `teams/config_docs.py` is at 700 lines and `teams/apply/plan.py` at 699 (the module cap is
  700, `tests/architecture/`); P56-3 must add a kind to both.
- **Goal:** move the `mcp-server` validation (`config_docs.py:444-447`, the `_MODEL_FOR_KIND` entry stays)
  and `plan.py::_plan_mcp_servers` (`:287-`) into `teams/apply/external.py` (new), callers unchanged in
  behaviour; leave both modules under 650 lines.
- **Non-goals:** any behaviour change; the `service` kind (P56-3).
- **Acceptance:** `uv run pytest --co -q` collects the same ids; `tests/architecture/` and
  `tests/unit/teams/` pass unchanged. A pure move adds no test.
- **Gate:** static gates, `tests/unit/teams tests/integration/teams tests/architecture`.
- **Contention:** Wave 1, parallel with P56-2.

### P56-2 — `docket setup secret set|list|remove`: a secret stored under any name

**Status:** TODO · ready, Phase 55 closed 2026-10-30 · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec + CLI

- **Trigger:** P55-10 follow-up: a `secret:<name>` reference resolves only names something writes;
  `interfaces/cli/commands/setup_notify.py:125` `store_secret` is the one writer and only provider add and
  notify call it, so a service token today needs `secrets.json` edited by hand.
- **Goal:** `setup secret set <name>` reads the value from a hidden prompt or from stdin (`--stdin`), never
  from an argument, never echoes it, and writes through the existing store (or the keyring backend);
  `setup secret list` prints names and dates only; `setup secret remove <name>`. `store_secret` moves to
  `governance/secrets.py` (one writer), `setup_notify.py` calls it there.
- **Non-goals:** rotating, expiring or scoping a secret per pod.
- **Spec:** `api-keys.spec.md` (MINOR), `cli-interface.spec.md` (MINOR).
- **Change:** `interfaces/cli/commands/setup_secret.py` (new), `governance/secrets.py`, `setup_notify.py:125`,
  the `setup` group registration, completion goldens (the new lines), `docs/commands.md` (generated).
- **Acceptance (RED first):** `tests/integration/interfaces/test_setup_secret_cli.py`: a value piped with
  `--stdin` is stored and `secret_value(name)` returns it; neither stdout, stderr nor the audit holds the
  value; `list` shows the name and not the value; `remove` deletes it; a value passed as an argument is
  refused (exit 2) and nothing is written.
- **Gate:** the file, `tests/unit/governance`, goldens, `gen_cli_docs.py --check`.
- **Contention:** Wave 1, parallel with P56-1.

### P56-3 — the `kind: service` document and `docket setup service add|list|remove`

**Status:** TODO (after P56-1) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec + data + CLI

- **Trigger:** ADR 0036 decision 13.
- **Goal:** `kernel/service.py` holds the typed config (`ServiceConfig`: name, `baseUrl`, `auth:
  {header, value}` where value may hold `${secret:<name>}`, `hosts` (extra hosts allowed, default none),
  `timeout`, `operations`; `Operation`: name, method, path with `{param}` placeholders, `params` (name,
  in: path|query, type string|integer|number|boolean, required), `body` (a JSON schema object or none),
  `access`, description). `teams/services.py` loads and validates the document (the access rule above;
  unknown keys refused; a `${secret:...}` reference kept as written, never resolved here), the global file
  under the home (`kernel/home.py`, `services.json`, through `platform/store.py`) and a pod's
  `services/` directory carried by `pod update` and `pod export`. `setup service add <file.yaml>`,
  `list`, `remove <name>`. A service whose name equals an MCP server's, global or pod-scoped, is refused
  in both directions (the maintainer's answer to question 1).
- **Non-goals:** making a call (P56-4); tools (P56-5); OpenAPI (P56-7).
- **Spec:** `service-client.spec.md` (new, 1.0.0: "The document", "Access"), `config-format.spec.md`
  (MINOR: the kind), `cli-interface.spec.md` (MINOR).
- **Change:** `kernel/service.py` (new), `teams/services.py` (new), `teams/config_docs.py` (the kind),
  `teams/apply/external.py` (from P56-1), `kernel/home.py`, the schema in `templates/schemas` and
  `docs/contracts/config-v1` (via `scripts/gen_config_schemas.py`), `interfaces/cli/commands/setup_service.py`
  (new), goldens, `docs/commands.md`.
- **Acceptance (RED first):** `tests/unit/teams/test_services.py`: a valid document round-trips; `POST`
  declared `read` is refused naming the operation; a path placeholder without its param is refused; a
  `${secret:crm}` value round-trips unresolved. `tests/integration/interfaces/test_setup_service_cli.py`:
  `add`, `list`, `remove`; a name taken by an MCP server is refused and nothing is written; `pod update`
  carries `services/` and `pod export` writes it back.
- **Gate:** the files, `tests/unit/teams tests/integration/teams`, `gen_config_schemas.py --check`, goldens,
  `gen_cli_docs.py --check`, `validate-specs.sh`.
- **Contention:** Wave 2, parallel with P56-4.

### P56-4 — the HTTP executor and its perimeter

**Status:** TODO · ready, Phase 55 closed 2026-10-30 · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** ADR 0036 decision 13: the call runs in docket's process (the maintainer: not the jail), so
  the perimeter is the service's host.
- **Goal:** `platform/service_http.py::call_operation(request) -> ToolOutcome`, where the request carries
  the resolved method, URL, headers and body (the caller resolves the secret; `platform` imports no
  `governance`). Guards: the host must be the `baseUrl` host or one listed in `hosts`; a redirect off them
  is refused (the `fetch` handler, `platform/fetch.py:182-216`); the host's resolved addresses that are
  private, loopback or link-local are refused unless that host is listed explicitly; path params are
  percent-encoded, never concatenated; header values with CR/LF are refused; time and size bounded like
  `fetch` (`Home.fetch_timeout_s`, `fetch_max_response_bytes`); a JSON response is returned as compact
  JSON, any other as text; a non-2xx is a failed outcome with the status and the head of the body; the
  auth header value never appears in the outcome (redacted if the server echoes it).
- **Non-goals:** retries, pagination, multipart or binary bodies, OAuth.
- **Spec:** `service-client.spec.md` ("The call", "The perimeter"); P56-3 creates the file, so this card's
  RED test and section land on the merged spec; if it merges first it creates the file with only its
  sections and P56-3 adds its own.
- **Change:** `platform/service_http.py` (new), `platform/__init__.py` (the export).
- **Acceptance (RED first):** `tests/integration/platform/test_service_http.py` against an `http.server`
  on `127.0.0.1` listed in `hosts`: `GET` with a query returns the JSON; `POST` sends the JSON body and
  the header; a `{id}` holding `../x` is encoded; a redirect to another host is refused; an unlisted
  loopback host is refused before any socket; an oversized response is cut and says so; a 404 is a
  failed outcome naming 404; a header with a newline is refused.
- **Gate:** the file, `tests/unit/platform`, `tests/architecture`.
- **Contention:** Wave 2, parallel with P56-3 (shares only the spec file, in separate sections).

### P56-5 — a service's operations are tools a role names

**Status:** TODO (after P56-3 and P56-4) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** ADR 0036 decision 13.
- **Goal:** `agent/tools/service_tools.py` builds one `Tool` per operation (`svc__<service>__<op>`, kind =
  access, a JSON-schema of its params and body, description from the document), loaded per turn beside
  `_load_mcp_tools` (`hops/application/driver_support.py:93-110`), with the secret resolved there through
  `governance/secrets.py::secret_value`; an unknown secret leaves that service out for the turn, reported
  like an unavailable MCP server and naming the header, never the value. Every call passes `dispatch_tool`.
  A role's `tools` list names `svc__<service>__<op>` or `svc__<service>` (`teams/roles.py:228-251`,
  `allow_list_names`, `unknown_allow_list_tools`); a `send` operation reaches only a role naming it
  (`teams/role_composer.py`, the P55-3 rule) and the `minimal` surface keeps a named one (P55-13); the
  read/act check (`teams/apply/check.py`) counts a service `read` operation like a read MCP tool.
- **Non-goals:** the quota and approval options (P56-6).
- **Spec:** `service-client.spec.md` ("Tools"), `role-archetypes.spec.md` (MINOR: the `svc__` name).
- **Change:** `agent/tools/service_tools.py` (new), `hops/application/driver_support.py`, `teams/roles.py`,
  `teams/role_composer.py`, `teams/apply/check.py`.
- **Acceptance (RED first):** `tests/unit/teams/test_role_composer.py`: a role naming `svc__crm` sees its
  read operations and the send ones it names; one without the name sees none.
  `tests/integration/agent/tools/test_service_tools.py` through `DocketDriver` and a fake model against a
  local service: a `read` call returns the body; the request carried the stored token; the token is in
  neither the trace nor the audit; an unknown secret leaves the service out naming the header.
- **Gate:** the files, `tests/unit/agent tests/unit/teams`, the e2e lane.
- **Contention:** Wave 3, parallel with P56-6 and P56-7.

### P56-6 — writes are handled apart: a quota per service and no blanket approval for `DELETE`

**Status:** TODO (after P56-3) · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** the maintainer's answers: the quota counts per service; writing operations get a handling
  of their own.
- **Goal:** a policy `limit` takes `service: <name>` beside `kind` and `tool` (`governance/quota.py:22-72`):
  it counts that service's `send` operations; the outward recipe's `send-quota.yaml` shows it. An approval
  of a `DELETE` operation offers `approve_once` and `deny` only (`governance/approval.py:49-53`, the
  options built per call); `approve_task` sent for it is refused. The `tool.send` audit row of a service
  call names the method and host.
- **Non-goals:** a quota per operation; changing `approve_task` for other tools.
- **Spec:** `security-gates.spec.md` (MINOR), `service-client.spec.md` ("Writes").
- **Change:** `governance/quota.py`, `governance/approval.py`, `governance/gate.py` (the audit detail only),
  `templates/recipes/outward/policies/send-quota.yaml`.
- **Acceptance (RED first):** `tests/unit/governance/test_quota.py`: `service: crm, count: 1` blocks the
  second crm send and not a send of another service; `tests/unit/governance/test_approval.py`: a `DELETE`
  approval lists two options and refuses `approve_task`.
- **Gate:** the files, `tests/unit/governance tests/integration/governance`.
- **Contention:** Wave 3, parallel with P56-5 and P56-7.

### P56-7 — operations imported from an OpenAPI document

**Status:** TODO (after P56-3) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec + CLI

- **Trigger:** the maintainer's answer: operations by hand **and** from OpenAPI.
- **Goal:** `setup service add <name> --from-openapi <file> [--operations id,id] [--base-url URL]
  [--auth-header H --secret NAME]` reads an OpenAPI 3 document (JSON or YAML, a local file; no network)
  and writes a `kind: service` document: one operation per selected `operationId`, params from path and
  query parameters, the body from a JSON request body, `access` by the rule above. An operation it cannot
  map (a non-JSON body, a `$ref` it cannot resolve locally, a missing `operationId`) is skipped and listed,
  never guessed. The written document is ordinary: editable, applied by `pod update`.
- **Non-goals:** OpenAPI 2, fetching the document over the network, auth schemes beyond a header.
- **Spec:** `service-client.spec.md` ("From OpenAPI"), `cli-interface.spec.md` (PATCH).
- **Change:** `teams/services_openapi.py` (new), `interfaces/cli/commands/setup_service.py`, goldens,
  `docs/commands.md`.
- **Acceptance (RED first):** `tests/unit/teams/test_services_openapi.py` on a small fixture
  (`tests/fixtures/openapi/crm.yaml`): `GET /clients` becomes a read operation with its query params,
  `POST /clients` a send with its body, a multipart operation is skipped and listed, `--operations`
  narrows; the CLI writes a document that `teams/services.py` loads.
- **Gate:** the files, goldens, `gen_cli_docs.py --check`.
- **Contention:** Wave 3; continues `setup_service.py` after P56-3.

### P56-8 — the e2e world: a pod reads from and writes to a declared service

**Status:** TODO (after P56-5 and P56-6) · **Size:** M · **Model:** Sonnet · **Kind:** test + recipe

- **Trigger:** ADR 0036 decision 13; the e2e lane is the oracle.
- **Goal:** in `tests/e2e/test_workdir_pod.py`, a world with a local fake service (`http.server` on
  `127.0.0.1`, listed in `hosts`) declared by a document with a read and a `POST` operation, its token
  stored with `setup secret set --stdin`, and the `outward` pipeline: the researcher reads through the
  service; the actor's `POST` parks; `task show` shows the whole call; `approve_once` and a run send it
  once (the server's log has one entry carrying the token header); the token is in no trace, audit or
  inbox line; a second `POST` over a `service:` quota of one is refused. The `outward` README gains the
  service shape beside the MCP shapes.
- **Spec:** none new (each card owns its section).
- **Change:** `tests/e2e/test_workdir_pod.py`, `templates/recipes/outward/README.md`, `docs/recipes.md`
  (generated by `scripts/gen_recipe_docs.py`).
- **Gate:** the e2e lane, `gen_recipe_docs.py --check`.
- **Contention:** Wave 4.

### P56-9 — the docs say what shipped, and the real run

**Status:** TODO (at the close) · **Size:** S · **Model:** Haiku (docs) and the integrator (run)
**Kind:** docs + live evidence

- **Goal:** `docs/AGENT-TEAMS.md` and `docs/SECURITY-SIMPLE.md` describe a declared service (the document,
  the access rule, `DELETE`, the perimeter at the host, the secret never seen by the model);
  `docs/CONFIGURATION.md` lists `services.json`. The integrator runs one real task against the local
  model and a local fake service (park, approve, one call), as P55-15 does. No count, no saving.
- **Gate:** the README agent-lane files on the committed tree, `gen_cli_docs.py --check`.
- **Contention:** Wave 4, after every other card merged.

### Phase 56 wave table

| Wave | Cards | Boundary |
| --- | --- | --- |
| 1 | P56-1 · P56-2 | `config_docs.py`, `apply/plan.py` → `apply/external.py` · `setup_secret.py`, `secrets.py`, `setup_notify.py` |
| 2 | P56-3 · P56-4 | `kernel/service.py`, `teams/services.py`, `config_docs.py`, `home.py`, `setup_service.py` · `platform/service_http.py` (shared: the new spec, separate sections) |
| 3 | P56-5 · P56-6 · P56-7 | `service_tools.py`, `driver_support.py`, `roles.py`, `role_composer.py`, `apply/check.py` · `quota.py`, `approval.py`, `gate.py` · `services_openapi.py`, `setup_service.py` |
| 4 | P56-8 · P56-9 | the e2e file and the recipe README · docs, then the real run |

## ◇ FOLLOW-UPS WITH TRIGGERS (not cards; triage when a trigger fires)

> Re-checked against the code on 2026-10-24; paths are current. Removed as no longer true: notification
> dedup is persisted (`operator/notify.py`), the `kind:`-less canonical-document advisory is gone, and
> `_create_workspace` no longer exists. Decisions that belong to the maintainer are in ROADMAP §7.1.

**Toolchain read grants (dropped from Phase 48).** A sibling project's gates failed with exit 126 under the
jail until each toolchain under `$HOME` (`~/.nvm`, `~/.pyenv`, `~/.cargo`) was granted by hand with
`docket setup sandbox read add`. Trigger: a second pod whose first jailed gate fails that way. Next:
`docket setup` proposes the grants for the toolchains it finds.

**Phase 55 Wave 1 (merged 2026-10-30).** Loose ends, none a card yet; the first two belong to the later cards
that already own the files.
- *Specs that lag.* `trace-store.spec.md` items 30-32 say every `process_*` payload carries `pgid`; MCP events carry
  none. `audit.spec.md` (~line 77) omits `pod.network_widen` / `pod.network_narrow`. P55-12 or the next card that
  edits either spec.
- *Required variables supplied by tasks.* `dispatch_pod`'s up-front check refuses a `required` pipeline variable that
  only tasks supply. P55-9 (routines) meets it first.
- *Smaller.* `docket task cancel` does not kill a `hop` MCP session directly (it closes at hop end); a top-level
  `networkGrant` in `pod.yaml` is an unknown-key error, not a skip (only under `settings`).
- *Flakes under load, seen once each and passing alone:* `test_run.py::TestForegroundApprovalPrompt` (two tests),
  `test_consult_wait.py::TestAnsweredInPlace::test_an_option_answer_goes_back_to_the_model_in_the_same_turn`,
  `test_end_to_end.py` approval-mode tests. A second failure of the same test is its trigger.
- *Phase 55 Wave 2, P55-3.* The `outward` recipe's policy `ask` names one tool, `mcp__outbox__send`
  (`when.tool` matches an exact name), so a send tool of another name is not asked about: a kind predicate or a default
  `ask` for every `send` tool belongs with P55-4. `--kind` stays an operator assertion, not verified against the server.
  A pipeline step that runs a role from the pod's existing registry (not in the applied directory) is not checked by
  the read/act rule.
- *Phase 55 Wave 2, P55-6.* `docket task show` "Waiting on you", the foreground `run` progress view and Telegram
  `/status` do not special-case a `wait`. `serve-read-api.spec.md` (the `kind` label list) and `a2a-binding.spec.md`
  (`escalationKind`) still list five kinds. `docket_escalations_total` counts a probe-resolved wait as `by=person`. A
  `stale_claim` between wake and claim drops the wait, so the next claim parks the step again. A monitor-only `docket
  start` never runs a probe (only a dispatching sweep does). Tack's maintainer is told: `wait` is an additive
  `EscalationKind`, `machine` an additive `EscalationPolicy`, the task is `waiting_input` with a2a state `WORKING`, a
  timed-out wait with no route is `blocked` / `wait_expired`, and `POST /escalations/<id>` `{optionId: "resume"}` ends
  it early. The e2e lane took 344 s once on this host against about 42 s measured before; its slowest tests are 13 s,
  so it was host load, not a test; re-measure if it repeats.
- *Phase 55 Wave 3.*
  - P55-2: the refusal golden is not added. `tests/golden/run.sh` derives the command from the case id and
    `setup model set` validates the model id (it contains `/`) before the role; a CLI unit test in
    `tests/unit/interfaces/cli/commands/test_setup_model.py` plus checking the role first would fix both. The refusal
    hint and `setup model list` name only the ten built-in roles; `known_role_names()` reads every overlay per call.
  - P55-4: `task show --json` carries no `call` (deliberate). The `Authorization` redaction pattern needs a token of
    about 20 characters after "Bearer". `outward` and `call` are additive to `operator-v2`; tell Tack's maintainer.
  - P55-9: `docs/CONFIGURATION.md` and `kernel/layout.py` do not list `docket-routines.json`;
    `pod-blueprints.spec.md` omits `routines/` from the `pod update` list; the recipe summary line does not name
    routines; cron day-of-month and day-of-week are ANDed, as in the existing parser; `tzdata` is not a declared
    dependency; no `--tz`-aware `HH:MM` form. A routine fires only under `docket start --dispatch`.
    `teams/apply/plan.py` sits at 699 of 700 lines: the next card touching it moves code out first. A routine skip is
    traced as `step_skipped` because `EVENT_TYPES` is closed.
- *Phase 55 Wave 4.*
  - P55-10, a gap in the flow: nothing user-facing stores a secret under an arbitrary name such as `crm` (provider add
    and notify write only their own names; `setup_notify.store_secret` is the one writer), so a `secret:crm` reference
    needs `secrets.json` or the keyring edited by hand. Recommended: a `docket setup secret set <name>` command that
    reads the value from stdin or a prompt and never echoes it; needs the maintainer's go as a card. Sessions and the
    model's own reply carry raw tool output (the model sees it); not checked. `setup --fix` (not bare `setup`) carries
    the literal-credential warning; there is no CLI golden for `--secret` (run.sh replays readonly cases only).
  - P55-8: the check and the increment of a quota are not atomic (two concurrent sends in one pod could both pass at
    count-1); an unreadable counter counts as empty; `pod policies` and `check` do not show quotas;
    `teams/config_docs.py` sits at 700 lines.
  - A flake, once: `test_consult_wait.py::TestAnsweredInPlace::test_an_answer_by_the_task_goes_through_the_same_record`
    failed in the full run and passed alone (the file's other test is already on the list above).
- *Declarative external services (planned as Phase 56).* The maintainer wants a pod to reach
  an external service from a `kind: service` document or commands (base URL, auth from the secret store, operations as
  read/send tools through `dispatch_tool`), with no program written per service and no more MCP implementation work. It
  reverses ADR 0036's "no native HTTP tool": written as decision 13 in the amendment of
  [ADR 0036](docs/adr/0036-a-pod-works-outward.md) (proposed 2026-10-30, not accepted; no new ADR). Sketch and open
  questions in `internal-docs/design/site-credentials-for-a-pod.md` (Addendum). Scope accepted 2026-10-30: Phase 56
  above.
- *To investigate, important: a pod logging in to a site nobody configured.* Per-service MCP bridges and `secret:<name>`
  are fixed when a server is registered; a task that ends in a `send` at a new site that needs a login has no per-site
  credential the model never sees. Raised by the maintainer 2026-10-30. Analysis, seven open questions and a suggested
  path (ADR first, then `docket setup secret set`, then a per-site grant like the network grant, then a real run with a
  throwaway account) are in `internal-docs/design/site-credentials-for-a-pod.md`. No card yet.
- *Phase 55 close (the repeated real run, 2026-10-30).* `docket run` does not wake a `wait` whose time has passed
  ("No pending tasks"); only the dispatch service's sweep does, as the spec says; a person expecting `run` to finish
  it is surprised (trigger: a second report). In one fresh home `setup provider add local ...` left the roles on
  `anthropic/*` until `setup model preset local` ran; an earlier fresh home applied the preset by itself: reproduce
  before a card. A stdio MCP server under isolation needs its script, interpreter and venv readable, and fails with
  `mcp_client.unavailable: ExceptionGroup` while python's "Permission denied" goes only to stderr (trigger: the next
  operator who meets it). P55-14 keys its note by task and role, not step, and splits the approval's `action` on
  `; call=` rather than reading a typed field; `task show --json` carries no `approval_unused`. P55-13 adds no trace
  line when the surface drops a role-named built-in (the closed event set has none that fits).
- *Live evidence, P55-5 (2026-10-30).* A real Playwright MCP server (0.0.83, headless system Chrome) driven through
  docket's MCP layer against a local page: under `lifetime: hop` navigate, snapshot and click by ref keep one session
  (the click ran, the page title changed); under `call` the snapshot after a navigate is `about:blank` and no ref
  exists. Not a model-driven pod run. That server's click argument is `target`, not `ref`.

**Phase 54 (closed 2026-10-29).** Two items wait for their triggers.
- *Dated model ids.* The native `/models` lists `claude-haiku-4-5-20251001`, and the probe matches ids
  exactly, so `claude-haiku-4-5` never gets an observed output cap and a call without a declared
  `--max-tokens` fails by design. Trigger: a second operator who meets that refusal. Next: the probe
  matches a catalog id to the dated id that starts with it.
- *Names.* `openai_http.py` and `OpenAIChatClient` hold both wires and still carry the first one's name;
  ADR 0011, ADR 0014 and two specs quote them. Trigger: a third dialect or the next edit of either module.

**Outward work (ADR 0036, deferred with triggers; the cards are Phase 55).**

- **HTTP/SSE MCP transport** (`mcp-client.spec.md:50`). Trigger: the first real pod whose connector
  exists only hosted.
- **A per-pod `fetch` allowlist** (`kernel/home.py:278`, one list for the machine). Trigger: two pods
  on one machine that need different hosts.
- **`lifetime: task` for an MCP server.** Trigger: a recorded run in which a following hop needed the
  previous hop's session.
- **A structured-output gate** (a result that must match a schema). Trigger: a recorded run whose
  critic approved a malformed list.
- **Pod memory with non-path subjects** (`workspace-structure.spec.md:158-169`: a subject is a
  repository path; a workdir pod's "the client prefers a formal tone" has no home). Trigger: a recorded
  workdir run whose Lead repeats a correction a person already made.

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

- **P52-12, a wait on a machine is an escalation.** Absorbed by P55-6 (ADR 0036 decision 5): a `wait` step is
  an escalation of kind `wait` the sweep settles on time or on a probe; the wait on a machine is one case of it.
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
