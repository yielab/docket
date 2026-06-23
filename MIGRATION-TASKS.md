# Migration Task Board — Bash → Python

> Executable task board for the migration in ARCHITECTURE-AUDIT.md (§8 build-vs-wrap)
> and MIGRATION-PLAN-PYTHON.md (architecture + branch roadmap). Each task is
> **self-contained** so a separate agent can claim and complete it independently.
>
> **Branch model:** all work on `python-core` (cut from `develop`), via short-lived
> `pc/<task-id>` branches that PR into `python-core`. M0/M1/M2 also merge up to
> `develop` behind the dispatcher seam (see plan §6). Rebase on `develop` weekly.

## How to use this board (read before claiming a task)

1. **Claim:** set Status → `IN-PROGRESS (@you)`. One agent per task.
2. **Read first (always):** `ARCHITECTURE-AUDIT.md`, `MIGRATION-PLAN-PYTHON.md`,
   and the task's own "Read" list. Honor the plan's **"we will NOT" list** — no
   FastAPI, no DI framework, no plugin system, no async, flat packages.
3. **Parity rule (non-negotiable):** a ported command is done only when it matches
   the M0 golden output byte-for-byte (or normalized JSON). **Port to parity
   first; refactor for elegance only after M6.** Do not add features.
4. **One boundary rule:** only `edges/adapters/openclaw.py` may know the
   `openclaw.json` shape or call the `openclaw` CLI. Any other module importing
   that knowledge is a bug.
5. **Done:** Status → `DONE`, open PR into `python-core`, check the acceptance
   gate boxes, link the PR.

**Status legend:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs Tx.y)` · `DONE`
**Size:** S ≈ ½ day · M ≈ 1–2 days · L ≈ 3–5 days (consider splitting before claiming)

**Task template fields:** Milestone · Depends on · Parallel-safe with · Read ·
Do · Out of scope · Deliverables · Acceptance gate · Size · Status

---

## Dependency map (what unblocks what)

```
M0 (T0.1→T0.2→T0.3/T0.4→T0.5)         contract freeze, gates everything
        │
M1  T1.1→T1.2 ; T1.1→T1.3→T1.4 ; T1.1→T1.5     skeleton + seam
        │
M2  T2.1,T2.2 ∥ → T2.3 → T2.4 → T2.5 → T2.6 ; T2.3→T2.7   data layer + ACL  ← high value
        │
M3  T3.0 → (T3.1..T3.7 all parallel)            read-only cmds (T3.7 = auth status)
        │
M4  (T4.1..T4.8 mostly parallel, each needs T2.*)   writer cmds (T4.8 = auth setup/login/key)
        │
M5  T5.1 ∥ T5.2 ∥ T5.3 ∥ T5.4 ∥ T5.6 ; T5.5 last   edges + extras (T5.6 = provider add)
        │
M6  T6.1 → T6.2 → T6.3,T6.4 → T6.5              cutover
```
`∥` = can run in parallel. Anything in M3+ depends on **all of M2**.

---

# M0 — Contract freeze (golden tests against current Bash)

> Goal: capture today's CLI behavior as executable goldens so every later port is
> provably identical. Merges to `develop` directly — pure addition, zero risk.

### T0.1 — Golden-test harness
- **Milestone:** M0 · **Depends on:** — · **Parallel-safe with:** T0.2
- **Read:** `bin/docket`, `lib/core/router.sh`, `tests/test-lifecycle.sh`, `specs/data/cli-json-shapes.spec.md`
- **Do:** build a runner (`tests/golden/run.sh` or `conftest`-style) that executes
  `docket <cmd> [args]` inside a throwaway `HOME=$(mktemp -d)`, captures stdout,
  stderr, exit code, and any mutated JSON files; **normalizes volatile fields**
  (timestamps, tmp paths, durations, ordering) via a documented scrubber so output
  is deterministic.
- **Out of scope:** capturing actual goldens (T0.3/T0.4), any Python.
- **Deliverables:** `tests/golden/run.sh`, `tests/golden/scrub.py`, README in `tests/golden/`.
- **Acceptance gate:** [ ] running the same command twice yields identical scrubbed output; [ ] scrubber rules documented; [ ] no real `~/.openclaw` touched.
- **Size:** M · **Status:** TODO

### T0.2 — Deterministic fixture world
- **Milestone:** M0 · **Depends on:** — · **Parallel-safe with:** T0.1
- **Read:** `lib/commands/install.sh`, `lib/helpers/workspace.sh`, `specs/data/docket-meta.spec.md`
- **Do:** script that seeds a fake `~/.openclaw` (specialists + 2–3 project agents,
  bindings, costs, sessions) deterministically — no daemon/systemctl/network. Stub
  `openclaw`, `systemctl`, `docker` as fake binaries on `PATH` returning canned output.
- **Deliverables:** `tests/golden/fixtures/seed.sh`, `tests/golden/fakes/{openclaw,systemctl,docker}`.
- **Acceptance gate:** [ ] seed is byte-reproducible; [ ] read-only commands run green against it with zero external deps.
- **Size:** M · **Status:** TODO

### T0.3 — Goldens: read-only commands
- **Milestone:** M0 · **Depends on:** T0.1, T0.2 · **Parallel-safe with:** T0.4
- **Do:** capture goldens for `list`, `info`, `cost`, `doctor`, `scope` (show),
  `context` (show/search), `team status`, `auth status`, `help`. Cover `--json` where it exists +
  human output + a couple error paths (bad id).
- **Deliverables:** `tests/golden/cases/readonly/*.golden` + case manifest.
- **Acceptance gate:** [ ] each command has ≥1 happy + ≥1 error golden; [ ] re-run is stable.
- **Size:** M · **Status:** TODO

### T0.4 — Goldens: writer commands (before/after state)
- **Milestone:** M0 · **Depends on:** T0.1, T0.2 · **Parallel-safe with:** T0.3
- **Do:** for `add`, `delete`, `profile`, `models`, `keys`, `maintain`, `scope set`,
  `wire`/`unwire` — capture stdout/exit **and** the resulting `.docket-meta.json` +
  `openclaw.json` diff as goldens. Each case resets to fixture state first.
- **Deliverables:** `tests/golden/cases/writers/*.golden` (incl. state diffs).
- **Acceptance gate:** [ ] state-diff goldens deterministic; [ ] each writer has happy + 1 edge case.
- **Size:** L · **Status:** TODO

### T0.5 — CI: golden job on current Bash
- **Milestone:** M0 · **Depends on:** T0.3, T0.4 · **Read:** `.github/workflows/ci.yml`
- **Do:** add a CI job running the golden suite against the Bash CLI; make it a
  required check on `python-core` and `develop`.
- **Acceptance gate:** [ ] job green on current code; [ ] fails loudly on an intentional output change (prove it).
- **Size:** S · **Status:** TODO

---

# M1 — Python skeleton + dispatcher seam

> Goal: Python package + CI live alongside Bash; `bin/docket` routes ported
> commands to Python, everything else to Bash. **Zero behavior change.**

### T1.1 — Package skeleton + tooling
- **Milestone:** M1 · **Depends on:** — · **Read:** plan §3–§4
- **Do:** `pyproject.toml` (PEP 621, entry point `docket = docket.cli:app`), `uv`
  lockfile, `src/docket/` layout (`cli/ core/ edges/ edges/adapters/`), `ruff` +
  `mypy` (strict) config, empty `py.typed`. Pin Python 3.11+.
- **Out of scope:** any command logic.
- **Deliverables:** `pyproject.toml`, `uv.lock`, `src/docket/**/__init__.py`, `ruff.toml`/`[tool.ruff]`, mypy config.
- **Acceptance gate:** [ ] `uv run docket --help` prints a Typer help; [ ] `ruff check` + `mypy` clean on the skeleton.
- **Size:** S · **Status:** TODO

### T1.2 — Python CI job
- **Milestone:** M1 · **Depends on:** T1.1 · **Read:** `.github/workflows/ci.yml`
- **Do:** CI job: `ruff check`, `ruff format --check`, `mypy`, `pytest`. Runs next
  to existing shell CI. Cache `uv`.
- **Acceptance gate:** [ ] green on skeleton; [ ] required check on `python-core`.
- **Size:** S · **Status:** TODO

### T1.3 — Typer app + command stubs
- **Milestone:** M1 · **Depends on:** T1.1 · **Read:** `lib/core/router.sh` (alias table)
- **Do:** register all 33 command names in Typer (preserve aliases; incl. `auth`). Each stub
  exits with a clear "not yet ported" code the dispatcher recognizes. Mirror
  `docket <cmd> --help` text structure.
- **Deliverables:** `src/docket/cli/__init__.py` + per-group modules with stubs.
- **Acceptance gate:** [ ] every current command name resolves; [ ] aliases preserved; [ ] help lists them.
- **Size:** M · **Status:** TODO

### T1.4 — Dispatcher seam in `bin/docket`
- **Milestone:** M1 · **Depends on:** T1.3 · **Read:** `bin/docket`
- **Do:** introduce a single source-of-truth **ported-commands registry** (e.g.
  `lib/core/ported.list` or env). `bin/docket`: if command ∈ registry → exec the
  Python entry point; else → existing Bash path. Empty registry now = all Bash.
- **Out of scope:** porting any command (registry starts empty).
- **Deliverables:** updated `bin/docket`, `lib/core/ported.list` (empty), short doc comment.
- **Acceptance gate:** [ ] all M0 goldens still green (no behavior change); [ ] adding a name to the registry provably routes to Python (test with one stub).
- **Size:** M · **Status:** TODO

### T1.5 — `config.py` (paths + settings parity)
- **Milestone:** M1 · **Depends on:** T1.1 · **Parallel-safe with:** T1.3/T1.4 · **Read:** `lib/core/config.sh`
- **Do:** port paths, env overrides, `MODEL_PROFILES`/`MODEL_PRICING` tables,
  Telegram mappings into typed settings (Pydantic `BaseSettings`/plain). No logic,
  just config + a parity test asserting values equal `config.sh`.
- **Deliverables:** `src/docket/config.py`, `tests/test_config_parity.py`.
- **Acceptance gate:** [ ] every path/table value matches `config.sh`; [ ] env overrides honored.
- **Size:** M · **Status:** TODO

---

# M2 — Data layer + Anti-Corruption Layer (highest value)

> Goal: collapse the 136 JSON heredocs **and** the OpenClaw surfaces (30
> `openclaw.json` touch points + `auth-profiles.json` + `models.providers` config)
> into a typed store + one ACL. Route Bash through them. Merges to `develop`. This
> is the landing that kills the architectural smell.

### T2.1 — Pydantic model: `.docket-meta.json`
- **Milestone:** M2 · **Depends on:** T1.1 · **Parallel-safe with:** T2.2 · **Read:** `specs/data/docket-meta.spec.md`, `lib/core/schema.sh`
- **Do:** `AgentMeta` model covering all fields (kind, type/role, name, codebase,
  stack, model, modelSource, sessionKey, projectKey, description, …) + a
  `schema_version` field and a forward/back migration hook stub.
- **Deliverables:** `src/docket/core/models.py` (meta portion), unit tests for round-trip + validation errors.
- **Acceptance gate:** [ ] parses every fixture meta file; [ ] rejects the same inputs `AGENT_SCHEMA` rejects.
- **Size:** M · **Status:** TODO

### T2.2 — Pydantic model: `openclaw.json` (ACL types)
- **Milestone:** M2 · **Depends on:** T1.1 · **Parallel-safe with:** T2.1 · **Read:** grep `openclaw.json` across `lib/` (30 files), `specs/data/`
- **Do:** model the subset docket reads/writes: agent registration, Telegram
  bindings, channels, metadata (session keys), gates/security config. Lenient on
  unknown keys (preserve on write — never drop fields docket doesn't model).
- **Deliverables:** models in `core/models.py`, round-trip test proving **unknown keys survive** a read→write.
- **Acceptance gate:** [ ] real fixture `openclaw.json` round-trips losslessly; [ ] unknown keys preserved.
- **Size:** M · **Status:** TODO

### T2.3 — `store.py` (atomic + locked persistence)
- **Milestone:** M2 · **Depends on:** T2.1 · **Read:** `lib/helpers/json.sh` (port its good logic)
- **Do:** typed read/write for both JSON sources: atomic `tmp`+`os.replace`,
  `filelock`, rolling `.bak`, `0600`, refuse-invalid-JSON. Generic over a Pydantic
  model. This is the only module that opens these files for writing.
- **Deliverables:** `src/docket/edges/store.py` + unit tests.
- **Acceptance gate:** [ ] write is atomic (kill-mid-write leaves old file intact — test it); [ ] invalid model refuses write; [ ] perms 0600.
- **Size:** M · **Status:** TODO

### T2.4 — `adapters/openclaw.py` — THE Anti-Corruption Layer
- **Milestone:** M2 · **Depends on:** T2.2, T2.3 · **Read:** all 30 `openclaw.json` touch points, `lib/helpers/service.sh`, `lib/helpers/auth.sh`, `lib/commands/auth.sh`, `scripts/wire-local-provider.sh`
- **Do:** the single module that knows OpenClaw. Expose docket-domain methods over
  **all three OpenClaw-owned surfaces**: (a) `openclaw.json` — `register_agent`,
  `remove_agent`, `get_binding`, `upsert_binding`, `set_session_metadata`,
  `list_agents`, gate read/write; (b) **auth profiles** (`auth-profiles.json` via
  `openclaw models auth`) — `read_auth_profiles`, `has_model_auth`, setup/login/key
  flows; (c) **provider registration** (`models.providers.*` via
  `openclaw config set`) — `register_provider` (the wire-local-provider logic).
  Plus `restart_gateway` via CLI/systemctl. Inventory every distinct operation the
  Bash performs and cover them. **No OpenClaw-format knowledge may exist elsewhere.**
- **Deliverables:** `src/docket/edges/adapters/openclaw.py`, an operation-coverage
  checklist mapping each old touch point → new method, unit tests with fake `openclaw`.
- **Acceptance gate:** [ ] checklist maps all 30 `openclaw.json` touch points **+** auth-profile **+** provider ops; [ ] grep proves no `openclaw.json`/`auth-profiles.json`/`models.providers` literal outside this module (in Python); [ ] round-trip preserves unknown keys; [ ] "OpenClaw owns the credential format" — docket never persists raw credentials.
- **Size:** L (consider splitting auth/provider into a sub-task if it grows) · **Status:** TODO

### T2.5 — `sync.py` (dual-source sync)
- **Milestone:** M2 · **Depends on:** T2.3, T2.4 · **Read:** `sync_session_key` + `meta_set` callers
- **Do:** the logic that keeps `.docket-meta.json` and `openclaw.json` consistent
  (session key, registration, scope). Single function set both call sites use.
- **Deliverables:** `src/docket/core/sync.py` + tests proving both sources end consistent.
- **Acceptance gate:** [ ] set-session-key updates both sources atomically; [ ] partial-failure leaves a recoverable state (documented).
- **Size:** M · **Status:** TODO

### T2.6 — Bash→Python JSON bridge (`docket _json`)
- **Milestone:** M2 · **Depends on:** T2.3, T2.4 · **Read:** all `meta_get`/`meta_set` + heredoc call sites
- **Do:** a hidden `docket _json <verb> ...` subcommand exposing store/ACL reads &
  writes, then **replace the 136 inline heredocs** in `lib/` with calls to it.
  Behavior identical; one tested code path for JSON.
- **Deliverables:** `cli/_json.py`, edited `lib/**/*.sh` (heredocs removed), grep proof of `python3 -c`/heredoc count → ~0 in `lib/`.
- **Acceptance gate:** [ ] all M0 goldens green; [ ] `grep -rc "python3" lib/` drops to near zero; [ ] no perf regression on `list`/`doctor` (note timing).
- **Size:** L · **Status:** TODO

### T2.7 — Concurrency / lost-update test suite
- **Milestone:** M2 · **Depends on:** T2.3 · **Parallel-safe with:** T2.4–T2.6
- **Do:** spawn N parallel writers against the store; assert no lost updates, no
  corruption, lock fairness/fallback when `flock` absent.
- **Deliverables:** `tests/test_store_concurrency.py`.
- **Acceptance gate:** [ ] 100 concurrent writes preserve all updates; [ ] graceful no-flock fallback covered.
- **Size:** M · **Status:** TODO

---

# M3 — Read-only commands (ported to Python)

> Each: implement the Typer command using `core` + `edges`, add its name to the
> ported registry (T1.4), prove byte-parity with its M0 golden. All parallel after T3.0.

### T3.0 — `ui.py` shared output layer
- **Milestone:** M3 · **Depends on:** T1.1 · **Read:** `lib/helpers/output.sh`, `lib/helpers/picker.sh`
- **Do:** Rich-based `info/success/warn/error/header/dim`, table helpers, and the
  fzf/numbered `pick_project` fallback. Match current text/format exactly.
- **Acceptance gate:** [ ] output matches `output.sh` formatting in goldens; [ ] picker fzf + numbered fallback both work.
- **Size:** M · **Status:** TODO

### T3.7 — `auth status` (read-only part of the new auth command)
- **Milestone:** M3 · **Depends on:** all M2 (esp. T2.4 auth methods), T3.0 · **Read:** `lib/commands/auth.sh`, `lib/helpers/auth.sh`
- **Do:** port `docket auth status` (and bare `docket auth` summary): list configured
  profiles via the ACL, flag billing/usage-disabled ones, report whether any is
  usable. Read-only — interactive setup/login/key go to T4.8.
- **Acceptance gate:** [ ] matches `auth status` golden; [ ] reads only through the ACL.
- **Size:** S · **Status:** TODO

### T3.1 `list` · T3.2 `info` · T3.3 `cost` · T3.5 `scope show` · T3.6 `context show/search`
- **Milestone:** M3 · **Depends on:** all M2, T3.0 · **Parallel-safe with:** each other
- **Do (each):** port the one command; read via store/ACL; format via `ui.py`; add
  to ported registry; delete the corresponding Bash `cmd_*` only at M6 (not now).
- **Deliverables (each):** `src/docket/cli/<cmd>.py` + per-command pytest.
- **Acceptance gate (each):** [ ] matches M0 golden byte-for-byte (happy + error); [ ] registry routes it to Python; [ ] mypy/ruff clean.
- **Size:** S–M each · **Status:** TODO

### T3.4 — `doctor` (large — split if needed)
- **Milestone:** M3 · **Depends on:** all M2, T3.0 · **Read:** `lib/commands/doctor.sh` (920 lines)
- **Do:** port health checks + auto-fixes. Likely split into `doctor/checks/*`.
  Each check independently testable.
- **Acceptance gate:** [ ] matches doctor goldens; [ ] each check unit-tested; [ ] auto-fix parity verified against fixtures.
- **Size:** L · **Status:** TODO

---

# M4 — Writer commands (ported to Python)

> Each needs all of M2. Verify against M0 **state-diff** goldens (T0.4). Mostly parallel.

- **T4.1 `add`** (L — `lib/commands/add.sh` + `workspace.sh`: workspace scaffold, templates, stack detect, registration, sync)
- **T4.2 `delete`** (M — teardown both sources + workspace, confirmations)
- **T4.3 `profile`** (S — pin/unpin model, modelSource)
- **T4.4 `models`** (M — role→model policy, presets, re-resolve policy-followers; `lib/commands/models.sh`)
- **T4.5 `keys`** (M — central key store + sync to agents; `lib/commands/keys.sh`, `secrets.sh`, `redact.sh`)
- **T4.6 `maintain`** (L — clean/reset/rebuild/check/sessions sublevels)
- **T4.7 small writers** (M — `edit`, `wire`/`unwire`, `snapshot`, `mode`, `scope set`, `team delegate/queue/done`, `workflow`)
- **T4.8 `auth setup/login/key`** (M — interactive flows: subscription via setup-token, API key via paste-token, the setup chooser; all via the ACL auth methods from T2.4. Interactive → can't fully golden; cover with a scripted/mocked `openclaw` and assert the resulting profile state. `lib/commands/auth.sh`, `lib/helpers/auth.sh`)
- **Each — Milestone:** M4 · **Depends on:** all M2 (+T4.1 before T4.2 for fixtures)
- **Note for T4.1 `add`:** the per-agent **model-auth guard** (checks real auth, points to `docket auth`) must be ported too — verify against the updated `add.sh`.
- **Deliverables (each):** `src/docket/cli/<cmd>.py` + tests; add to ported registry.
- **Acceptance gate (each):** [ ] stdout + **resulting JSON state** match T0.4 goldens; [ ] `restart_gateway` called where the Bash did; [ ] ACL is the only openclaw.json writer.
- **Status:** TODO

---

# M5 — Edges & extras

### T5.1 — `adapters/system.py`
- **Depends on:** T1.1 · **Read:** `lib/helpers/service.sh`, scattered `systemctl`/`docker`/`git` calls
- **Do:** typed wrappers for systemctl (incl. non-systemd/macOS fallback), docker, git; central `restart_gateway`. Mockable.
- **Acceptance gate:** [ ] each wrapper unit-tested with fakes; [ ] macOS/no-systemd path covered.
- **Size:** M · **Status:** TODO

### T5.2 — `serve.py` (stdlib, **not** FastAPI)
- **Depends on:** all M2, T5.1 · **Read:** `lib/commands/serve.sh`
- **Do:** `http.server` + `prometheus_client` for `/status.json`, `/metrics`, `/health`. Match current output contract.
- **Acceptance gate:** [ ] 3 endpoints match serve goldens; [ ] Prometheus text passes a parser; [ ] no FastAPI/async dep added.
- **Size:** M · **Status:** TODO

### T5.3 — Telegram + approval routing
- **Depends on:** all M2 · **Read:** `lib/helpers/telegram.sh`, `approval.sh`
- **Do:** port bindings + approval routing. Network calls behind a thin client, mockable.
- **Acceptance gate:** [ ] wire/unwire + approval flows match goldens with a mocked client.
- **Size:** M · **Status:** TODO

### T5.4 — trace / audit / drift / budget / policy
- **Depends on:** all M2 · **Read:** `lib/helpers/{trace,audit,drift,budget,policy,security}.sh`
- **Do:** port to `core/` modules; pure logic, store-backed. Split per concern if large.
- **Acceptance gate:** [ ] each module unit-tested; [ ] cost/budget numbers match goldens.
- **Size:** L · **Status:** TODO

### T5.5 — Install/bootstrap update
- **Depends on:** M5 mostly done, T4.8 (auth) · **Read:** `install.sh` (esp. reworked **Step 6 "Model authentication"**), `lib/commands/install.sh`, `uninstall.sh`, `Formula/`
- **Do:** install path installs the Python tool (uv/pipx) while keeping the **Bash
  bootstrap** thin. Preserve the new Step 6 model-auth flow (detect existing
  profiles, warn when all disabled, run the chooser when none) — now calling the
  ported `docket auth`. Update Homebrew formula. Do **not** rewrite bootstrap in Python.
- **Acceptance gate:** [ ] clean-machine install yields a working `docket`; [ ] Step 6 model-auth flow preserved; [ ] uninstall reverses it.
- **Size:** M · **Status:** TODO

### T5.6 — `wire-local-provider` → `docket models provider add`
- **Depends on:** all M2 (T2.4 `register_provider`), T4.4 (`models`) · **Read:** `scripts/wire-local-provider.sh`
- **Do:** port the local OpenAI-compatible provider registration (ping endpoint,
  `openclaw config set models.providers.<name>` with baseUrl + api +
  zero-cost model + contextWindow) into a real subcommand using the ACL's
  `register_provider`. Keep it idempotent; print the role-split commands as today.
  Decide: replace the standalone script, or keep a thin Bash shim delegating to it.
- **Acceptance gate:** [ ] registering a fake endpoint matches the script's resulting `models.providers` config; [ ] idempotent re-run is a no-op; [ ] only the ACL writes provider config.
- **Size:** M · **Status:** TODO

---

# M6 — Cutover

### T6.1 — Flip dispatcher default to Python
- **Depends on:** M3+M4+M5 all DONE · **Do:** registry contains all commands; verify every command routes to Python; all goldens green on the Python path.
- **Acceptance gate:** [ ] 0 commands fall through to Bash; [ ] full golden suite green.
- **Size:** S · **Status:** TODO

### T6.2 — Delete Bash `lib/`, collapse `bin/docket`
- **Depends on:** T6.1 · **Do:** remove `lib/commands/**`, `lib/helpers/**`, `lib/core/**` (Bash); `bin/docket` becomes the thin entry/shim. Keep install bootstrap.
- **Acceptance gate:** [ ] goldens still green post-deletion; [ ] no dead `source` refs; [ ] repo has no `lib/**/*.sh` except install helpers.
- **Size:** M · **Status:** TODO

### T6.3 — Swap CI
- **Depends on:** T6.2 · **Do:** drop shellcheck for `lib/` (keep for install shim); make pytest + golden + ruff + mypy the required gates; keep metrics-sync + macOS matrix.
- **Acceptance gate:** [ ] CI green; [ ] required checks updated.
- **Size:** S · **Status:** TODO

### T6.4 — Tests to pytest
- **Depends on:** T6.2 · **Parallel-safe with:** T6.3 · **Do:** replace `tests/unit/*.sh` with pytest equivalents; keep goldens as the e2e contract.
- **Acceptance gate:** [ ] coverage ≥ the old helper assertion breadth; [ ] goldens retained.
- **Size:** L · **Status:** TODO

### T6.5 — Docs + release
- **Depends on:** T6.2 · **Do:** update `README.md`, `CLAUDE.md`, `CHANGELOG.md`, `docs/` to reflect Python; run `scripts/metrics.sh --check`; tag a minor release.
- **Acceptance gate:** [ ] docs describe Python architecture + ACL; [ ] metrics gate green; [ ] release tagged.
- **Size:** M · **Status:** TODO

---

## Roll-up checklist (definition of done for the whole migration)
- [ ] M0 goldens green and required on `develop`.
- [ ] M2 landed: store + ACL live, 136 heredocs and 30 openclaw.json touch points (+ auth-profiles + provider config) collapsed.
- [ ] All 33 commands route to Python at byte-parity.
- [ ] `lib/**/*.sh` removed except install bootstrap; `bin/docket` is a thin entry point.
- [ ] CI = ruff + mypy + pytest + goldens; metrics + macOS matrix retained.
- [ ] OpenClaw knowledge lives only in `edges/adapters/openclaw.py`.
- [ ] README/CLAUDE.md/CHANGELOG updated; minor release tagged.
