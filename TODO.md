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
> follow-ups below. **Planned: Phase 56** (ADR 0036 decisions 13-14, accepted 2026-10-30; 15-16 proposed the same
> day): an external service is declared, not programmed; a pod keeps records; a mechanical gate belongs to its step;
> twenty-one cards P56-1..P56-21 over five waves, starting on the maintainer's go. Phases 52 to 54
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

## ○ PHASE 56 PLANNED — an external service is declared, a pod keeps records (D-77 amendments, ADR 0036 decisions 13-16)

> Planned 2026-10-30 from the maintainer's request after the Phase 55 real run: a pod reaches an external
> service nobody programmed in advance, configured by a document or by commands, with no MCP bridge per
> service and no further MCP implementation work. Scope accepted by the maintainer the same day
> ([ADR 0036](docs/adr/0036-a-pod-works-outward.md) "Amendment", decision 13): a header token for auth
> (OAuth later, see the amendment); JSON and text; the call runs in docket's process, not the jail; every
> method (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`); operations written by hand **and** imported from an
> OpenAPI document; an MCP server and a service never share a name; the quota counts per service. Phase 55
> closed 2026-10-30; the cards start on the maintainer's go. Each card's trigger is that request; no metric is invented.
>
> Widened 2026-10-30 by a second request of the maintainer: fold the standard teams work in, without oversizing it,
> and give a pod somewhere to keep the data of the business (reports, listings, compilations, a register, captured
> data), not docket's own state ([ADR 0036](docs/adr/0036-a-pod-works-outward.md) "Second amendment", decisions
> 15-16, **proposed**; open choices in ROADMAP §7.1). P56-10 is the one teams change a non-code pod needs now;
> P56-11..P56-14 are the records; P56-3 and P56-5 carry decision 16. Widened again the same day, on the
> maintainer's "include what was left out", then "no leftovers, no compatibility, docket has no users":
> P56-15 (one judge, `critic` and `tester` deleted), P56-16 (the old home layout, the `roles.json` shim and
> lenient metadata deleted), P56-17..P56-20 (the short form and `init --with` on every role, records over
> HTTP, OpenAPI 2), and P56-21 (the blueprints are the four team shapes; a recipe carries only what a blueprint
> cannot). Two items stay follow-ups with their reasons, under "Standard teams and records".

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
- **No compatibility (the maintainer, 2026-10-30: docket has no users).** A card deletes what it replaces:
  no shim, no alias, no default that keeps an old call working, no "kept for compatibility", no test that
  pins the old shape. A spec version bumps MAJOR when a name or a field goes; the spec says what is, not
  what was. A card's acceptance names the `rg` that proves nothing of the old name remains.
- **Records (P56-11..P56-14).** The owning spec is new: `specs/functional/pod-records.spec.md` (P56-11
  creates it). Tools are `rec__<set>__add` and `rec__<set>__update` (`write`), `rec__query` (`read`) and
  `rec__export` (`write`); none is `send`. Only `platform/records_store.py` imports `sqlite3`. A record's
  `_task`, `_session`, `_step` and `_at` come from the hop, never from the model.

### P56-1 — make room: `config_docs.py` and `apply/plan.py` shed code to siblings

**Status:** DONE (merged 414d4a25, 2026-10-30) · **Size:** S · **Model:** Sonnet · **Kind:** pure move

- **Trigger:** `teams/config_docs.py` is at 700 lines and `teams/apply/plan.py` at 699 (the module cap is
  700, `tests/architecture/`); P56-3 must add a kind to both.
- **Goal (as shipped):** `plan_mcp_servers` moved from `apply/plan.py` (699 to 657 lines) to `teams/apply/external.py`
  (new); the five short-form models (`RoleDocument`, `PipelineDocument`, the policy models, `PodDocument`,
  `RoutineDocument`) moved from `config_docs.py` (700 to 525) to `teams/config_models.py` (new). The 4-line
  `_validate_mcp_server` stayed: it cannot move without a `config_docs`/`external` import cycle.
- **Non-goals:** any behaviour change; the `service` kind (P56-3).
- **Acceptance:** `uv run pytest --co -q` collects the same ids; `tests/architecture/` and
  `tests/unit/teams/` pass unchanged. A pure move adds no test.
- **Gate:** static gates, `tests/unit/teams tests/integration/teams tests/architecture`.
- **Contention:** Wave 1, parallel with P56-2.

### P56-2 — `docket setup secret set|list|remove`: a secret stored under any name

**Status:** DONE (merged a5f9936f, 2026-10-30) · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec + CLI

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

**Status:** DONE (merged 785fb644, 2026-10-30) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec + data + CLI

- **Trigger:** ADR 0036 decision 13.
- **Goal:** `kernel/service.py` holds the typed config (`ServiceConfig`: name, `baseUrl`, `auth:
  {header, value}` where value may hold `${secret:<name>}`, `hosts` (extra hosts allowed, default none),
  `timeout`, `idempotencyHeader` (optional, a header name; decision 16), `operations`; `Operation`: name, method, path with `{param}` placeholders, `params` (name,
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
- **Change:** `kernel/service.py` (new), `teams/services.py` (new), `teams/config_docs.py` (the kind; ~175 lines of headroom
  after P56-1), `teams/apply/external.py` (the service planner joins `plan_mcp_servers` there), `kernel/home.py`, the schema in `templates/schemas` and
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

**Status:** DONE (merged 71459928 with P56-5, 2026-10-30) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec

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

**Status:** DONE (merged 71459928; decision-16 headers, the service timeout and the three guards in the follow-up merge, 2026-10-30) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec

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
  Decision 16: every call carries `X-Docket-Task: <task id>`; a `send` operation of a service that
  declares `idempotencyHeader` carries it with the first 32 hex digits of a SHA-256 over the task id,
  step id, service, operation and the body as canonical JSON (sorted keys). The tool builds both
  headers from the hop, never from the model's arguments.
- **Non-goals:** the quota and approval options (P56-6).
- **Spec:** `service-client.spec.md` ("Tools"), `role-archetypes.spec.md` (MINOR: the `svc__` name).
- **Change:** `agent/tools/service_tools.py` (new), `hops/application/driver_support.py`, `teams/roles.py`,
  `teams/role_composer.py`, `teams/apply/check.py`.
- **Acceptance (RED first):** `tests/unit/teams/test_role_composer.py`: a role naming `svc__crm` sees its
  read operations and the send ones it names; one without the name sees none.
  `tests/integration/agent/tools/test_service_tools.py` through `DocketDriver` and a fake model against a
  local service: a `read` call returns the body; the request carried the stored token; the token is in
  neither the trace nor the audit; an unknown secret leaves the service out naming the header; the fake
  server saw `X-Docket-Task` equal to the task id; two identical `send` calls in one step carried the same
  idempotency key and the same call from another task a different one.
- **Gate:** the files, `tests/unit/agent tests/unit/teams`, the e2e lane.
- **Contention:** Wave 3, parallel with P56-6 and P56-7.

### P56-6 — writes are handled apart: a quota per service and no blanket approval for `DELETE`

**Status:** DONE (merged 96f9d7b7, 2026-10-30; the audit detail of a service call and the `deletes` mark of a DELETE tool shipped in P56-5) · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec

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

**Status:** DONE (merged 2b5b1509, 2026-10-30) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec + CLI

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

**Status:** DONE (merged eba9f9bd, 2026-10-30) · **Size:** M · **Model:** Sonnet · **Kind:** test + recipe

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
  `docs/CONFIGURATION.md` lists `services.json` and `records.sqlite`. `docs/AGENT-TEAMS.md` also describes
  a pod's records (the document, the four tools, what the jail can and cannot write) and the four
  blueprints (`build`, `respond`, `operate`, `routine`: roster, pipeline, workspace kind) with the recipes
  each takes (`tdd`, `intake`; `outward`; `ops-approval`; `records`), plus one table that maps the
  standard teams of a digital business (software, ops, support, growth, revenue, finance, insight) to a
  shape, the recipes to apply and what the operator adds (prose, a service or MCP declaration, a policy):
  a department is an instance, never a shipped blueprint. The code pod is lead, implementer and a `strong`
  reviewer, and `critic`/`tester` appear nowhere (P56-15). The
  integrator runs one real task against the local model and a local fake service (park, approve, one
  call), as P55-15 does, and one `records` capture-then-report task. No count, no saving.
- **Gate:** the README agent-lane files on the committed tree, `gen_cli_docs.py --check`.
- **Contention:** Wave 5, after every other card merged.

### P56-10 — a mechanical gate is the step's, not the implementer's

**Status:** PARKED (left: a producer of hop evidence for a non-implementer role; the verify sentence and the evidence reader shipped, merged 2026-10-30) · ready, Phase 55 closed 2026-10-30 · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** the maintainer's request of 2026-10-30 (standard teams for any industry: an `operator` doing
  operations or finance work under a mechanical gate, the "operate" shape). Reproduction from the code:
  a step whose role is `operator` and whose gate runs a command gets a verify plan
  (`hops/application/compose.py:518`, every role but the Lead), but only `role == "implementer"` is told
  the command (`compose.py:84`); and `post_hop.py:473-477` (`_latest_implementer_evidence`) hands a
  downstream hop only the implementer's evidence, so a critic after an operator receives none.
- **Goal:** the verify sentence goes to any role whose hop has a verify plan; the latest evidence is the
  latest successful hop's that has evidence, whatever its role. The implementer's text and evidence are
  unchanged byte for byte.
- **Non-goals:** ports, scratch and the `verifyCmd` member setting (`teams/member_workspace.py:162-204`);
  the `implementer-rework` prompt; the Lead as the pod's front door; merging reviewer and critic (all
  deferred under "Standard teams and records").
- **Spec:** `pod-dispatch.spec.md` (MINOR: the verify sentence and the downstream evidence name the step,
  not the role).
- **Change:** `hops/application/compose.py:76-86`, `hops/gates/post_hop.py:473-477` and its callers.
- **Acceptance (RED first):** `tests/integration/hops/test_verify_gate.py` gains two cases through the
  driver with a fake model on a pod with an `operator` step gated by a command: the operator's hop
  message holds the command sentence; the critic step after it receives the operator's evidence. The
  existing implementer cases pass unchanged (the oracle that nothing else moved).
- **Gate:** the file, `tests/unit/hops`, `tests/integration/hops/test_verify_gate.py`, the goldens
  (`tests/golden/run.sh verify-all`, unchanged).
- **As shipped (partial):** any hop whose step has a verify command is told it; `post_hop._latest_evidence` reads the
  latest successful hop's evidence whatever its role (`pod-dispatch` 11.9.0, `role-archetypes` 5.1.0). The second
  acceptance case (a step after an operator receives its evidence) is not reachable: `hop_diff_probe`
  (`teams/workspace/worktree.py`) produces evidence only for `role == "implementer"` and the spec's "Implementer diff
  producer" req 1 says so. Deciding which roles of an "operate" pod get evidence needs a card of its own (none exists
  yet; it is the maintainer's call, P56-21's `operate` blueprint is where it would show); until then the reader is consumer-side machinery without a non-implementer producer.
- **Contention:** Wave 2, on `compose.py` after P56-15; parallel with P56-3, P56-4 and P56-11 (no shared file or spec).

### P56-11 — the records store: one SQLite file per pod, one writer

**Status:** DONE (merged 14243c12 with P56-12, 2026-10-30) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** the maintainer's request of 2026-10-30 (decision 15): a pod that compiles reports, keeps a
  register or captures data needs somewhere to keep it. Nothing in `src/docket` stores tabular data today
  (no `sqlite3` import).
- **Goal:** `platform/records_store.py`, stdlib `sqlite3` only, WAL and a busy timeout:
  `ensure_table(set, columns, key)` creates a table, adds a missing column (`ALTER TABLE ADD COLUMN`) and
  refuses a removed, renamed or retyped one naming it, changing nothing; `add(set, values, meta)` checks
  each value against its column's type and, when the set has a key, returns the existing row with
  `created: false` instead of a second one; `update(set, match, values, meta)` by `_id` or key, declared
  columns only; `query(sql, max_rows, max_chars)` on a separate `mode=ro` connection whose
  `set_authorizer` allows only reads and functions and whose `set_progress_handler` stops it at a time
  bound, returning columns, rows and how many were cut; `export(sql, path, fmt)` writes CSV or Markdown and
  returns the row count. Implicit columns `_id`, `_at`, `_task`, `_session`, `_step`, `_updated_at`. A
  test like `tests/architecture/test_task_queue_writers.py` pins `sqlite3` to this one module.
- **Non-goals:** the document, tools and CLI (P56-12, P56-13); deleting rows; anything shared between pods.
- **Spec:** `specs/functional/pod-records.spec.md` (new, 1.0.0: "The store", "Queries"), its row in
  `specs/README.md`.
- **Change:** `platform/records_store.py` (new), `platform/__init__.py`,
  `tests/architecture/test_records_writer.py` (new).
- **Acceptance (RED first):** `tests/integration/platform/test_records_store.py` on a temporary file:
  `"abc"` into an `integer` column is refused naming the column; two adds with one key leave one row and
  the second says `created: false`; an added column keeps the rows; a dropped column is refused and the
  table is unchanged; `DELETE`, `UPDATE`, `ATTACH` and `PRAGMA` through `query` are refused and the data
  is unchanged; a `WITH` query and a join work; 300 rows under a bound of 200 report 100 cut; a recursive
  CTE that never ends is stopped by the time bound; `export` writes a CSV whose header is the columns.
- **Gate:** the files, `tests/unit/platform`, `tests/architecture`.
- **Contention:** Wave 2, parallel with P56-3 and P56-4 (new files only; its own spec).

### P56-12 — the `kind: records` document and `docket pod records`

**Status:** DONE (merged 14243c12, 2026-10-30) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec + data + CLI

- **Trigger:** decision 15.
- **Goal:** `kernel/records.py` holds the typed config (`RecordSet`: name `^[a-z][a-z0-9_]*$`,
  description, optional `key` naming a column, `columns` of name, type `string|integer|number|boolean|date`,
  `required`, description; at most 40 columns; a name starting `_` refused). `teams/records.py` loads a
  pod's `records/` directory (pod-scoped only), validates it, carries it through `pod update` (which calls
  `ensure_table` and plans "adds column x" or refuses naming the column) and writes it back in
  `pod export`. `Home.pod_records_path(project)` is `pods_dir/<pod>/records.sqlite` (`kernel/home.py:567`,
  beside `pod_memory_path`). `docket pod records` lists a pod's sets with their row counts; `docket pod
  records <set> [--sql "<SELECT>"] [--limit N] [--csv FILE]` shows rows through the same read-only query.
  `config_docs.py` gains only the kind's registry line; its validation lives in `teams/records.py`.
- **Non-goals:** the tools (P56-13); a global set; deleting a set or its rows.
- **Spec:** `pod-records.spec.md` ("The document", "The CLI"), `config-format.spec.md` (MINOR: the kind),
  `cli-interface.spec.md` (MINOR, its own section; P56-7 edits another).
- **Change:** `kernel/records.py` (new), `teams/records.py` (new), `teams/config_docs.py` (one entry),
  `teams/apply/external.py` (the plan entry), `kernel/home.py`, `interfaces/cli/commands/pod_records.py`
  (new) and its registration in `pod.py:220`; the schema via `scripts/gen_config_schemas.py`, completion
  goldens, `docs/commands.md` (generated).
- **Acceptance (RED first):** `tests/unit/teams/test_records_doc.py`: a valid document round-trips; a `_x`
  column, an unknown type and a `key` that is no column are each refused naming the field.
  `tests/integration/interfaces/test_pod_records_cli.py`: `pod update` with a `records/` directory creates
  the table; a column added to the document keeps the rows; a column removed is refused and the table is
  unchanged; `pod records leads --sql "DELETE FROM leads"` exits 1 and the rows remain; `--csv` writes the
  file; `pod export` writes `records/` back.
- **Gate:** the files, `tests/unit/teams tests/integration/teams`, `gen_config_schemas.py --check`, goldens,
  `gen_cli_docs.py --check`, `validate-specs.sh`.
- **Contention:** Wave 3, parallel with P56-5, P56-6 and P56-7 (no shared source file).

### P56-13 — a pod's records are tools a role names

**Status:** DONE (merged 06899b82, 2026-10-30) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** decision 15.
- **Goal:** `agent/tools/records_tools.py` builds, per set, `rec__<set>__add` and `rec__<set>__update`
  (kind `write`, parameters the set's columns as a JSON schema) and, per pod, `rec__query` (kind `read`:
  `sql`, `limit`) and `rec__export` (kind `write`: `sql`, `format: csv|md`, `path` resolved inside the
  hop's working directory by the `write` tool's resolution and refused outside it). docket fills `_task`,
  `_session` and `_step` from the hop; an argument with one of those names is refused. Output is bounded by
  `DOCKET_TOOL_MAX_OUTPUT_CHARS`. Loaded per turn beside the MCP and service tools
  (`hops/application/driver_support.py:93-110`); every call passes `dispatch_tool`. A role's allow-list
  names `rec__<set>`, `rec__query`, `rec__export` or `rec` (all of the pod's); a role that denies `write`
  loses add, update and export by kind (`teams/roles.py:205`, `role_composer.py`), the read/act check
  (`teams/apply/check.py`) counts `rec__query` as a read, and the `minimal` surface keeps a named one
  (P55-13).
- **Non-goals:** `send` (records never leave the machine); an approval of its own (a policy `ask` on
  `rec__*` is the operator's choice through the existing path).
- **Spec:** `pod-records.spec.md` ("Tools"), `role-archetypes.spec.md` (MINOR: the `rec__` names; and its
  "Starter archetypes" table, which says `writer` denies nothing while the code, `builtin_roles.py:189`,
  and its own requirement at `:258` deny `bash`).
- **Change:** `agent/tools/records_tools.py` (new), `hops/application/driver_support.py`, `teams/roles.py`,
  `teams/role_composer.py`, `teams/apply/check.py`.
- **Acceptance (RED first):** `tests/unit/teams/test_role_composer.py`: a role denying `write` sees
  `rec__query` and no add, update or export. `tests/integration/agent/tools/test_records_tools.py` through
  `DocketDriver` and a fake model on a workdir pod with a `leads` set keyed by `email`: two adds with one
  email leave one row and the second result says `created: false`; the row's `_task` is the task id; an
  add passing `_task` is refused; `rec__query` returns the row; `rec__export` writes `report.csv` in the
  workdir, returns the count, and the rows are not in the tool output; `path: ../x` is refused; the roots
  the jail receives for that hop (the callers of `sandbox/landlock.py::_mount_dirs`) do not contain
  `records.sqlite`.
- **Gate:** the files, `tests/unit/agent tests/unit/teams`, the e2e lane (new tools).
- **Contention:** Wave 4, parallel with P56-8 (P56-8 edits only the e2e file and the recipe README).

### P56-14 — the `records` recipe: a set, a capture pipeline and a schedule for a `routine` pod

**Status:** TODO (after P56-13 and P56-21) · **Size:** S · **Model:** Sonnet · **Kind:** recipe + test

- **Trigger:** decision 15; the `routine` shape has nothing that keeps data until a set is declared.
- **Goal:** `templates/recipes/records/`: no members (the roster is the `routine` blueprint's, P56-21),
  one example set (`records/entries.yaml`), a `capture` pipeline (the analyst adds rows from the task's
  input, the reviewer checks the count against the input), an example weekly routine that creates a task
  on the blueprint's compile → draft → review pipeline, and a README that says which blueprint it is for.
  The reviewer holds no record write (it denies `write`).
- **Spec:** none new (`role-archetypes.spec.md`'s recipe rule: a recipe's documents validate).
- **Change:** `templates/recipes/records/` (new), `tests/e2e/test_workdir_pod.py`, `docs/recipes.md`
  (generated by `scripts/gen_recipe_docs.py`).
- **Acceptance (RED first):** in `tests/e2e/test_workdir_pod.py`, a world on the `routine` blueprint with
  the `records` recipe applied and a fake model: a capture task with a repeated key leaves one row; a
  task on the blueprint's pipeline leaves `report.md` holding the row; `docket pod records entries` shows
  it; a reviewer call to `rec__entries__add` is denied.
- **Gate:** the e2e lane, `gen_recipe_docs.py --check`, `tests/integration/teams/test_archetypes.py`.
- **Contention:** Wave 5, after P56-21 on the e2e file and `docs/recipes.md`; P56-9 follows it.

### P56-15 — one judge: `reviewer` absorbs `critic`, and the tester is deleted

**Status:** DONE (merged 2f908a52, 2026-10-30) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec + data + tests

- **Trigger:** the maintainer's request of 2026-10-30 (rethink the code team; no legacy roles, docket has
  no users). From the code: `reviewer` and `critic` are one shape (a verdict, no `write`/`edit`/`bash`;
  `teams/builtin_roles.py:101-110,191-203`) with two prose variants and two marker pairs, and the
  reviewer is `cheap` while it judges a `strong` implementer; the tester (`:112-127`) denies `write` and
  `edit`, so it runs the suite the implementer's mechanical gate already ran and opines; a tester `FAIL`
  is terminal.
- **Goal:** three built-in archetypes: `lead`, `implementer`, `reviewer`. The reviewer is `strong`, keeps
  `APPROVE | REQUEST-CHANGES`, and its identity and hop prose judge "the work of the step before: code,
  text or data", so it serves a content or research pod as the critic did; the parity baseline
  (`tests/integration/teams/test_pod_role_workspace_parity.py`) is re-frozen for the reviewer **in the
  same commit as the prose**, with the diff in the commit body (a declared change, never a hidden one).
  `critic` and `tester` are deleted everywhere: the archetypes and `BUILTIN_ROLE_ORDER`
  (`builtin_roles.py:131`), the prompts (`templates/prompts/identity/critic.md`, `identity/tester.md`,
  `hop/tester.md`), `FULL_POD_ROLES` and `PIPELINE_ORDER` (`teams/pod.py:27,282`), `_TESTER_PATTERN` and
  the tester step of `default_pipeline()` (`pipeline/domain/spec.py:416,438-466`), the `verdict_rework`
  branch for the tester and the `tester_verdict_failed` event (`tasks/application/record.py:212-218`,
  `observability/trace.py:65,82`, `observability/projection.py:58,78`), `compose.py:112` (`reviewer`
  alone), `_RETRY_ROLES` (`kernel/home.py:16`), the cheap/strong lists (`teams/model_selection.py:24-29`),
  the `research` and `content` blueprints and their pipelines (`teams/blueprints.py:153-181,232,241`) and
  the `agentic-product` blueprint's roster and text (`:257-265`), the help at `agents.py:589`, the
  docstrings at `teams/roles.py:18`, `role_schema.py:25,230`, `hops/application/sweep.py:1`. Recipes:
  `outward`, `research-review`, `spec-first` and `reflexion` name `reviewer` where they named `critic`;
  `tdd` and `reflexion` lose their `- test: tester` step (the implementer's gate runs the suite);
  `dual-review` becomes two reviewer members if the pod document can repeat a role (the duplicate-role
  indexing of `workspace-structure.spec.md`), otherwise the recipe is deleted, never kept half-working.
- **Non-goals:** renaming `reviewer`; a new marker pair; touching ADRs (history) or `docs/cycles-ended/`.
- **Spec:** `role-archetypes.spec.md` (MAJOR: three built-ins, five starters, the reviewer's class and
  prose, the parity baseline re-frozen), `model-profiles.spec.md` (MINOR: `:55,549`),
  `pipeline-format.spec.md` ("Zero migration": three steps, MINOR), `pod-dispatch.spec.md` (PATCH: the
  tester lines), `trace-store.spec.md` (MAJOR: `tester_verdict_failed` removed from the vocabulary),
  `pod-blueprints.spec.md` (the recipes table), `workspace-structure.spec.md` and `docket-meta.spec.md`
  (the presets).
- **Change, by the model (eight files):** `teams/builtin_roles.py`, `teams/pod.py`,
  `pipeline/domain/spec.py`, `teams/blueprints.py`, `hops/application/compose.py`,
  `tasks/application/record.py`, `templates/prompts/identity/reviewer.md`, `templates/prompts/hop/reviewer.md`.
  **By a script** (`scripts/maint/one_judge_no_tester.py`, run once, then finished by hand, then deleted
  with the phase): the three prompt deletions, the one-line tuple and docstring edits above, the recipe
  renames, `docs/recipes.md` and `docs/commands.md` regenerated, and the rename or deletion in the 20 test
  files naming `critic` and 53 naming `tester` (a test *about* the tester is deleted with it; one that
  counted four hops counts three).
- **Acceptance (RED first):** `tests/unit/teams/test_pod.py`: the full roster is three roles and
  `pod_pipeline` of a full pod has three hops; `tests/integration/teams/test_archetypes.py`: the
  registry holds exactly `lead implementer reviewer researcher analyst writer operator monitor`, the
  reviewer is `strong`, every shipped recipe validates; `tests/e2e/test_solo_run.py`'s sibling for a full
  pod: a task on `--pod full` ends after the reviewer's APPROVE with three hops; a content pod's reviewer
  hop message names no diff or code. **The no-leftovers oracle:**
  `rg -n "critic|tester" src specs docs tests README.md -g '!docs/cycles-ended/**' -g '!docs/adr/**'`
  prints nothing. The goldens that list a full pod are edited by line, never regenerated.
- **Gate:** the named files, `tests/unit/teams tests/unit/pipeline tests/unit/tasks tests/unit/observability
  tests/integration/teams`, the goldens, the e2e lane. The integrator runs `tests/agent` once at the close
  (README prose names the roles).
- **As shipped:** `dual-review` was deleted (a pod document cannot repeat a role): 17 recipes. The recorded
  model output in `tests/fixtures/task-records/task_list_2026-10-24*.json` still says "Tester"; a recording is
  not edited.
- **Contention:** Wave 1, alone on its files; P56-10 follows it on `compose.py` in Wave 2; P56-17 follows
  it on `spec.py` in Wave 5.

### P56-16 — no legacy: the old home layout, the `roles.json` shim and lenient metadata are deleted

**Status:** TODO (Wave 5, after P56-12 on `home.py` and P56-18 on `agents.py`) · **Size:** M · **Model:** Sonnet · **Kind:** deletion + spec

- **Trigger:** the maintainer's rule of 2026-10-30: docket has no users, so nothing is kept for
  compatibility. Measured: `rg -n -i "legacy|compatib|old layout" src/docket` finds the old single-level
  home layout (`kernel/layout.py:77-115` `legacy_entries`, `is_legacy`, `migrate`, `LayoutConflict`;
  `kernel/home.py:294,300,572` branch on it; `docket init` migrates, `interfaces/cli/commands/agents.py:297-298`),
  the `roles.json` shim (`teams/apply/lock.py:31,218-222`, `teams/apply/write.py:335`) and three models
  that keep unknown keys "so a future field added by one docket version survives another"
  (`teams/fleet.py:17,39`, `teams/conversations.py:47,64`, `teams/models.py:32,36`;
  `tasks/application/run_cancellation.py:106` the same by hand). The "OpenAI-compatible" wire is a
  protocol name, not compatibility code, and stays.
- **Goal:** one home layout (`config/`, `state/`), no migration: a home with old-layout entries is refused
  by `docket init` naming the entries, not moved; `roles.json` is nothing docket knows; the three models
  are `extra="forbid"` and an unknown key is refused naming it and the file; `_set_cancellation_lifecycle`
  writes the record's known keys only. Every deleted function's test goes with it.
- **Non-goals:** `pod.session_key` (`teams/pod.py:79-83`: its docstring says "kept for compatibility",
  but the value renders `${sessionKey}` in every identity template; reword the docstring, keep the
  function); the zero-migration default pipeline (a default, not a shim).
- **Spec:** `workspace-structure.spec.md` (MAJOR: `:361` and the layout section), `docket-meta.spec.md` and
  `docket-store.spec.md` (MINOR: unknown keys refused), `cli-interface.spec.md` (PATCH: `init`).
- **Change (eight files):** `kernel/layout.py`, `kernel/home.py`, `interfaces/cli/commands/agents.py`,
  `teams/apply/lock.py`, `teams/apply/write.py`, `teams/fleet.py`, `teams/conversations.py`,
  `teams/models.py`; tests `tests/integration/kernel/test_home_layout.py`, `tests/unit/kernel/test_home.py`,
  `tests/unit/teams/apply/test_lock.py`, `tests/integration/teams/test_applied_lock.py` lose their
  legacy cases.
- **Acceptance (RED first):** `tests/integration/kernel/test_home_layout.py`: `docket init` on a home
  holding `fleet.json` at its root exits 1 naming the file and moves nothing; `tests/unit/teams/test_fleet.py`:
  a `fleet.json` record with an unknown key is refused naming the key; `tests/unit/teams/apply/test_lock.py`:
  a pod directory holding `roles.json` gets no note and the file is ignored. **The oracle:**
  `rg -n -i "legacy|compatib|old layout|forward-compatible" src/docket` prints only the wire's
  "OpenAI-compatible" lines.
- **Gate:** the files, `tests/unit/kernel tests/integration/kernel tests/unit/teams tests/integration/teams`,
  `tests/architecture`.
- **Contention:** Wave 5, parallel with P56-14 and P56-17 (no shared file).

### P56-17 — the short form knows every role's member ids, not four

**Status:** TODO (after P56-13) · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** the maintainer's request of 2026-10-30 (pods of starter roles). Reproduction:
  `pipeline/domain/short_form.py:33,58-68` recognizes a member id only when its role part is one of the
  four base roles, so a step `- vet: shop-critic` is read as a role named `shop-critic`, which no pod has,
  and the pipeline fails at run time instead of load time.
- **Goal:** `load_pipeline(text, *, roles: frozenset[str])` (`pipeline/domain/spec.py:372`) takes the role
  names the caller knows, **required, no default**: `_BASE_ROLES` is deleted and the short-form member-id
  check uses the given names. Every caller in `teams/` and `hops/` passes `load_registry(project).names()`
  (`teams/apply/plan.py:248,402`, `teams/config_docs.py:398,651`, `teams/apply/check.py:166`,
  `teams/apply/review.py:149,153`, `teams/apply/recipes.py:186`, `hops/application/steps.py:67,95`). The
  `pipeline` context still imports nothing above it: the names come in as data.
- **Non-goals:** validating that the member exists (that is `pod_full_roster`'s, at run time).
- **Spec:** `pipeline-format.spec.md` (PATCH: the short-form target rule names "a role the registry
  knows", not the four).
- **Change:** `short_form.py`, `spec.py`, and the six caller files above (eight files).
- **Acceptance (RED first):** `tests/unit/pipeline/domain/test_short_form__targets.py` (new): with roles
  including `critic`, `- vet: shop-critic` becomes `agent: shop-critic` and `- vet: shop-critic-2` too;
  without, it stays a role; `- vet: critic` is a role either way. `tests/integration/teams/test_pod_roles_from_archetypes.py`:
  `pod update` of a pipeline targeting a starter-role member id plans an agent step.
- **Gate:** the files, `tests/unit/pipeline tests/unit/teams`, `tests/architecture`.
- **Contention:** Wave 5 (`apply/check.py` after P56-13, `config_docs.py` after P56-12, `apply/plan.py`
  after P56-1, `spec.py` after P56-15); parallel with P56-14 and P56-16 (no shared file).

### P56-18 — `docket init --with` takes any archetype and refuses a name it does not know

**Status:** DONE (merged 1f5ac64b, 2026-10-30) · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec + CLI

- **Trigger:** the maintainer's request of 2026-10-30. Reproduction: `pod_roles`
  (`interfaces/cli/commands/pod.py:47-63`) normalizes each `--with` name through `normalize_role` and
  **silently drops** one it cannot normalize; a starter or operator-defined role (`analyst`, a pod's own
  `liaison`) is accepted only if `normalize_role` knows it, and a typo (`analist`) vanishes with no message.
- **Goal:** `pod_roles` resolves names against `load_registry()` (built-ins, starters and the operator's
  `config/roles/`), keeps the given order, and refuses an unknown name with exit 2 naming it and the known
  names; the lean pair stays the base (the Lead is the pod's anchor record: its workspace holds the queue,
  `teams/settings.py:21-26`, and the settings, `:29`). The help text says "any role `docket pod roles`
  lists".
- **Non-goals:** a pod without a Lead member (see the follow-up); blueprints.
- **Spec:** `cli-interface.spec.md` (PATCH, the `init` section).
- **Change:** `interfaces/cli/commands/pod.py:47-63`, `interfaces/cli/commands/agents.py:358-365` (the
  `--pod/--with` branch compares to `_bp.DEFAULT_BLUEPRINT`, not the literal `"software"`, so P56-21 need
  not reopen the file), completion goldens if the help changes, `docs/commands.md` (generated).
- **Acceptance (RED first):** `tests/integration/interfaces/test_init_with_roles.py` (new): `init --with
  analyst,critic` provisions lead, implementer, analyst, critic in that order; `--with analist` exits 2
  naming `analist` and provisions nothing (the oracle: no workspace directory exists after); a role from
  the operator's `config/roles/` is accepted.
- **Gate:** the file, `tests/unit/teams`, goldens, `gen_cli_docs.py --check`.
- **Contention:** Wave 4 (`pod.py` after P56-12's registration line); parallel with P56-8, P56-13, P56-19
  and P56-20.

### P56-19 — a pod's records are read over the HTTP API

**Status:** DONE (merged 0fa601cf, 2026-10-30) · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec + HTTP

- **Trigger:** decision 15, and the plan of record (Tack) as the reader of a pod's compilations; this is
  how another pod or system reads records without a shared file (the amendment keeps a set to one pod).
- **Goal:** `GET /pods/<pod>/records` lists the sets with their columns and row counts; `GET
  /pods/<pod>/records/<set>?limit=N&sql=<SELECT>` returns rows through the same read-only query as
  `rec__query` (the authorizer, the row and time bounds; `sql` optional, default the whole set newest
  first), both behind the Bearer token like `/pods/<pod>`. A refused statement is 400 naming the reason;
  an unknown set 404.
- **Non-goals:** writing records over HTTP (a task does that); records in `/tasks` or `/inbox` payloads.
- **Spec:** `serve-read-api.spec.md` (MINOR, 5.3.0: the two routes), `operator-api.spec.md` (MINOR).
- **Change:** `interfaces/http/routes/pods.py` (54 lines), `interfaces/http/routes/table.py:41-43`
  (`overlap=True`, as `/pods/<pod>/corrections`), `pod-records.spec.md` ("Over HTTP", a pointer).
- **Acceptance (RED first):** `tests/integration/interfaces/http/test_pod_records_api.py` (new) on a pod
  with a `leads` set and two rows: the list names the set and `2`; the rows route returns both and honours
  `limit=1`; `sql=DELETE FROM leads` is 400 and the rows remain; no token is 401; an unknown set is 404.
- **Gate:** the file, `tests/unit/interfaces`, the e2e lane (the HTTP API changed).
- **Contention:** Wave 4; parallel with P56-8, P56-13, P56-18 and P56-20.

### P56-20 — an OpenAPI 2 (Swagger) document imports too

**Status:** DONE (merged f6503eee, 2026-10-30) · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** the maintainer's request of 2026-10-30 (a data layer behind a declared service):
  PostgREST, the generated REST face of a Postgres schema, publishes OpenAPI 2.0, and P56-7 reads 3 only.
- **Goal:** `teams/services_openapi.py` accepts `swagger: "2.0"`: `host` + `basePath` + the first of
  `schemes` give the suggested `baseUrl` when `--base-url` is absent; a parameter `in: body` with a schema
  is the JSON body; `in: formData` is skipped and listed; `$ref` resolves against `definitions`; path and
  query parameters map as in 3. Everything else is the 3 path.
- **Non-goals:** fetching the document; auth schemes beyond a header; OpenAPI 3.1 differences.
- **Spec:** `service-client.spec.md` ("From OpenAPI", MINOR).
- **Change:** `teams/services_openapi.py`, `tests/fixtures/openapi/postgrest.json` (new, a hand-written
  2.0 document of two tables and one `/rpc/<fn>`).
- **Acceptance (RED first):** `tests/unit/teams/test_services_openapi.py`: `GET /leads` with `select`
  and `order` query params is a read operation; `POST /rpc/refund` with a body parameter is a send with
  that schema; a `formData` operation is skipped and listed; the `baseUrl` is `https://host/basePath`.
- **Gate:** the file, `tests/unit/teams`.
- **Contention:** Wave 4, alone on `services_openapi.py` after P56-7.

### P56-21 — the blueprints are the four team shapes; a recipe carries only what a blueprint cannot

**Status:** TODO (Wave 5, after P56-8 and P56-18) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec + data + tests

- **Trigger:** the maintainer's request of 2026-10-30 (standard teams for any industry) and the
  no-leftovers rule. From the code: the five blueprints (`teams/blueprints.py:220-260`: `software`,
  `research`, `content`, `ops`, `agentic-product`) are rosters by department, two of them the same code
  pod; and a blueprint and a recipe carry the same things twice: `outward` ships a roster, a pipeline, a
  policy pack **and** the `actor` role as a recipe-only overlay (`templates/recipes/outward/roles/actor.yaml`),
  while a blueprint ships a roster and a pipeline. The standard-teams analysis
  (`internal-docs/strategy/equipos-estandar-empresa-digital-2026-10-30.es.md` §8.4) found four pipeline
  shapes behind every department.
- **Goal:** four blueprints, one per shape, and nothing else in the registry (`DEFAULT_BLUEPRINT` is
  `build`):
  - `build` (codebase; lead, implementer, reviewer): `default_pipeline()`;
  - `respond` (workdir; lead, researcher, writer, reviewer, actor): intake → research → draft → review
    (verdict, rework to draft) → act;
  - `operate` (workdir; lead, monitor, operator, reviewer): watch → propose → `approval` gate → act
    (mechanical gate) → review;
  - `routine` (workdir; lead, analyst, writer, reviewer): compile → draft → review; the `records` recipe
    (P56-14) adds the set, the `capture` pipeline and the schedule.

  `actor` becomes the sixth starter archetype (strong; `tools: [read, glob]`, `cannot: [write, edit,
  bash]`; its `send` tool is whatever service operation or MCP tool the operator's role overlay names,
  as `outward`'s README says today): `templates/prompts/identity/actor.md` from the recipe's `actor.md`;
  the recipe's `roles/` directory is deleted. **A recipe carries only what a blueprint cannot:** `outward`
  shrinks to its policy pack (`ask` on send, the send quota) and README, its pipeline deleted (it is
  `respond`'s); `ops-approval` to its approval policy and README (`operate` has the operator); `intake`
  stays (an intake step on a `build` pod). `_research_pipeline`, `_content_pipeline`, `_ops_pipeline` and
  the five names are deleted; `docket init --blueprint <shape>` lists the four.
- **Non-goals:** department recipes (`support`, `finance`, …): a department is a shape plus the
  operator's prose, connectors and policy, documented as a table in P56-9, not shipped as prose nobody
  ran; user-authored blueprints (unchanged); the blueprint format (a Python literal, as ADR 0012 says).
- **Spec:** `pod-blueprints.spec.md` (MAJOR: "Built-in blueprints" at `:87,618`, "The recipe library" at
  `:535`), `role-archetypes.spec.md` (MINOR: `actor` in the starter table), `workspace-structure.spec.md`
  (PATCH: the presets name `build`).
- **Change, by the model (eight files):** `teams/blueprints.py`, `teams/builtin_roles.py`,
  `templates/recipes/outward/pod.yaml`, `templates/recipes/ops-approval/pod.yaml`,
  `tests/unit/teams/test_blueprints.py`, `tests/e2e/test_workdir_pod.py` (`content` → `routine`, the
  P56-8 world → `respond` with the `outward` policy pack), `tests/e2e/test_two_pods_one_parked.py:117`
  (`agentic-product` → `build`), `tests/integration/teams/test_archetypes.py`. By hand after:
  `identity/actor.md` moved, `outward/pipeline.yaml` and `outward/roles/` deleted, the two READMEs,
  `docs/recipes.md` (`gen_recipe_docs.py`), `docs/AGENT-TEAMS.md`, goldens edited by line.
- **Acceptance (RED first):** `tests/unit/teams/test_blueprints.py`: the registry is exactly `build
  respond operate routine`; `get_blueprint("software")` and `("content")` raise naming the four; each
  shape's pipeline loads and its steps' roles are in its roster; `respond`'s act step's role is `actor`.
  `tests/integration/teams/test_archetypes.py`: `actor` is a starter, strong, denies write/edit/bash; the
  `outward` and `ops-approval` recipes validate and carry no pipeline and no `roles/`.
  `tests/e2e/test_workdir_pod.py`: a `respond` pod with the `outward` pack applied runs P56-8's world
  unchanged in behaviour (park, approve, one call); a `routine` pod runs compile → draft → review on a
  workdir. **The oracle:**
  `rg -n "agentic-product|research-default|content-default|ops-default|_research_pipeline|_content_pipeline|_ops_pipeline|recipes/outward/roles" src specs docs tests -g '!docs/cycles-ended/**' -g '!docs/adr/**'`
  prints nothing, and `rg -n "blueprint" src/docket/interfaces/cli/commands/agents.py` names no shape by
  literal (P56-18 made it `_bp.DEFAULT_BLUEPRINT`).
- **Gate:** the files, `tests/unit/teams tests/integration/teams`, `gen_recipe_docs.py --check`, goldens,
  the e2e lane.
- **Contention:** Wave 5, after P56-8 (the e2e file) and P56-18 (`agents.py`); `blueprints.py` and
  `builtin_roles.py` after P56-15 (Wave 1); parallel with P56-16 and P56-17 (no shared file); P56-14
  follows it (the `routine` blueprint is its roster).

### Phase 56 wave table

| Wave | Cards | Boundary |
| --- | --- | --- |
| 1 | P56-1 · P56-2 · P56-15 | `config_docs.py`, `apply/plan.py` → `apply/external.py` · `setup_secret.py`, `secrets.py`, `setup_notify.py` · `builtin_roles.py`, `teams/pod.py`, `spec.py`, `blueprints.py`, `compose.py:112`, `record.py`, the reviewer prompts, and the script's one-liners, recipes and tests |
| 2 | P56-3 · P56-4 · P56-10 · P56-11 | `kernel/service.py`, `teams/services.py`, `config_docs.py`, `home.py`, `setup_service.py` · `platform/service_http.py` (shared: the new spec, separate sections) · `compose.py:76-86`, `post_hop.py` · `platform/records_store.py` (its own spec) |
| 3 | P56-5 · P56-6 · P56-7 · P56-12 | `service_tools.py`, `driver_support.py`, `roles.py`, `role_composer.py`, `apply/check.py` · `quota.py`, `approval.py`, `gate.py` · `services_openapi.py`, `setup_service.py` · `kernel/records.py`, `teams/records.py`, `config_docs.py`, `apply/external.py`, `home.py`, `pod_records.py` |
| 4 | P56-8 · P56-13 · P56-18 · P56-19 · P56-20 | the e2e file and the `outward` README · `records_tools.py`, `driver_support.py`, `roles.py`, `role_composer.py`, `apply/check.py` · CLI `pod.py`, `agents.py` · HTTP `routes/pods.py`, `table.py` · `services_openapi.py` |
| 5 | P56-16 · P56-17 · P56-21, then P56-14, then P56-9 | `layout.py`, `home.py`, `agents.py:297`, `lock.py`, `write.py`, `fleet.py`, `conversations.py`, `models.py` · `short_form.py`, `spec.py` and the six loader callers · `blueprints.py`, `builtin_roles.py`, the `outward`/`ops-approval` recipes, two e2e files · the `records` recipe and `test_workdir_pod.py` · docs, then the real run |

Five waves, twenty-one cards. P56-15 goes first because every later card that names a role must see the
final three; it owns the only script of the phase. P56-21 closes the shapes: after it, a blueprint is a
roster and a pipeline, a recipe is what a blueprint cannot carry, and nothing is shipped twice.

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
  - Phase 56 Wave 2 merge run (2026-10-30), both passed alone: `test_consult_wait.py::TestAnsweredInPlace::
    test_a_decline_tells_the_model_to_decide_itself` (a third test of that class, so the class now has three flakes
    under load: that is its trigger), and `tests/integration/product/test_runtime_execution_envelope.py`, 8 setup
    errors from `uv build` exiting 2 in a parallel worker.
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

**Standard teams and records (deferred from Phase 56, 2026-10-30; analysis in
`internal-docs/strategy/equipos-estandar-empresa-digital-2026-10-30.es.md` §8 and
`capa-de-datos-para-docket-2026-10-30.es.md`).**

- **A pod without a Lead member.** Not a blocker, so not a card: the Lead is the pod's *anchor record*
  (its workspace holds the queue, `teams/settings.py:21-26`, the settings and budget, `:29`,
  `teams/member_workspace.py:214`; `pre_input` is evaluated and session events traced as `"lead"`,
  `tasks/application/queue.py:72`, `governance/approval.py:73`), but no pipeline step has to use it: the
  `outward` recipe's pipeline already runs researcher, writer, critic, actor. Making the pod the subject is
  a persisted-state change (the queue's and settings' location). Trigger: a measured cost of the idle Lead
  member (its workspace, its row in `status`), or a pod whose operator refuses a Lead at all.
- **Measuring the three-role full pod against the four-role one** (P56-15 ships the change on the
  maintainer's request; this is the evidence it did not wait for). Trigger: a maintainer go, since the
  comparison spends hosted-model tokens on `fab-dev`: the same tasks under both rosters, measured tokens
  and escaped defects.
- **A port for docket's task store** (`TaskRepository` takes the concrete `JsonTaskStore`,
  `tasks/application/repository.py:48`). Not business data, and a port with one implementation is the
  "unwired machinery" this project refuses. Trigger: a queue the one file cannot carry (measured).

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
