# Wave 99 worker packets — Phase 40, sub-wave B (D-58, ADR 0023)

Coordinator: the session that ran Wave 98 on 2026-10-12. **Base commit: the commit that opened
Wave 99 on `develop`** (`git log -1 --format=%h -- .agents/handoffs/wave-99-worker-packets.md`),
which carries the Wave 98 rollup. One card, one worker, one isolated worktree each; merge order
P40-11, P40-9, P40-4, P40-10, P40-6. The card (`python3
.agents/skills/docket-roadmap/scripts/card_packet.py P40-<N>`) is the contract; this file is the
map. Symbols were located at the base and drift; re-locate every one with `rg -n` before editing.

| Card | Worker | Owning spec bump | Shared-file note |
| --- | --- | --- | --- |
| P40-11 | Haiku | none | `core/audit.py`: the `mkdir` in `audit_log` only |
| P40-9 | Haiku | `serve-read-api.spec.md` 3.5.0 | `serve.py`: the agent-row builder only |
| P40-4 | Haiku | `audit.spec.md` 2.14.0, `telegram-integration.spec.md` 2.7.0 | none |
| P40-10 | Haiku | `security-gates.spec.md` 0.41.0 | P40-6 holds 0.40.0 of the same spec; the integrator orders the changelog |
| P40-6 | Sonnet | `security-gates.spec.md` 0.40.0 | none |

## 0. Rules for every worker

**Exactly §0 of [wave-98-worker-packets.md](wave-98-worker-packets.md)**, with `w99` in place of
`w98` in the worktree and branch names and the base commit above. Read that section and your own
packet below only.

## P40-11 — 0700 directories (Haiku)

- `edges/store.py::_copy_backup` already chmods the `.bak` to 0600 (shipped in the phase-open
  commit); confirm with a test and do not change it. The open part is directory modes.
- Live path: `core/audit.py::audit_log` (`logf.parent.mkdir`), `core/trace.py` (the
  `tracefile.parent.mkdir` in the writer and the `project_dir.mkdir` in the per-project path
  helper), `cli/_agents.py` (`_cfg.PROJECTS_DIR.mkdir` and the workspace `ws.mkdir`/`memory`
  mkdirs). Each docket-created directory ends 0700 whatever the umask; an existing directory's
  mode is tightened only if docket created it in the same call (never chmod a codebase).
- Tests: unit tests per touched module under a permissive umask (`os.umask(0o002)` in a fixture,
  restored after), oracle `oct(st.st_mode & 0o777)`.

## P40-9 — `/status.json` stops publishing chat ids (Haiku)

- Live path: `serve.py`, the per-agent row builder that returns `"bindings":
  fleet.agent_bindings(agent_id)` (used by `build_status`, the unauthenticated `GET
  /status.json`). Check every other caller of that builder (`rg -n` its name) and whether an
  authenticated route serves the same rows; drop `bindings` only from the unauthenticated payload
  (or drop `peerId` and keep the channel names, whichever the spec states more simply). Bump
  `SERVE_API_VERSION` only if the spec's versioning rule says a removed field requires it.
- Spec: `specs/data/serve-read-api.spec.md` 3.5.0 (the `GET /status.json` schema and changelog).
- Tests: the serve read-API tests (`tests/unit/test_serve__read_api.py` and neighbours); RED is a
  `peerId` in the unauthenticated body.

## P40-4 — bound audit volume from caller-controlled inputs (Haiku)

- Live path: `core/approval.py` `approval_grant` and `approval_deny` (they put `actor=` and
  `reason=` into the trace payload and the audit detail; cap both at 512 characters with a
  visible `…` marker before either use); `core/telegram.py` (`handle_message` audits
  `telegram.unauthorized` per message; `poll_once` loops the batch). Coalesce to one
  `telegram.unauthorized` entry per chat id per `poll_once` batch, carrying the count; the
  per-message reply is unchanged.
- Specs: `audit.spec.md` 2.14.0 (the cap), `telegram-integration.spec.md` 2.7.0 (the coalescing).
- Tests: `tests/unit/core/test_approval.py`, `tests/unit/core/test_telegram.py` (or the
  existing Telegram poll tests; find them with `rg -n poll_once tests`). Oracle: audit line
  length and count in the isolated home.

## P40-10 — a real `fetch` deadline and a timeout clamp (Haiku)

- Live path: `edges/adapters/fetch.py::fetch_url` (the `resp.read(FETCH_MAX_RESPONSE_BYTES + 1)`
  single read; replace with a chunked read against a `time.monotonic()` deadline of the
  effective timeout, keeping the byte cap and every existing return); the clamp goes in
  `fetch_url` too (`effective_timeout = min(..., FETCH_TIMEOUT_MAX_S)`), with one new constant
  in `config.py` beside `FETCH_TIMEOUT_S` (state the bound in the spec). Leave
  `core/tools.py` alone unless the clamp cannot live in `fetch_url`.
- Do not touch the `refusal="fetch_not_allowed"` return (Wave 98) or the redirect handler.
- Spec: `security-gates.spec.md` 0.41.0 ("Network egress and the `fetch` tool").
- Tests: a drip server (a real socket: integration lane, `tests/integration/`, with `SUBJECT`)
  for the deadline; the clamp as a unit test in `tests/unit/edges/adapters/test_fetch.py`.

## P40-6 — the docket process is non-dumpable (Sonnet)

- Change: one helper in `edges/adapters/system.py` (e.g. `make_non_dumpable()`) calling
  `prctl(PR_SET_DUMPABLE, 0)` through `ctypes` on Linux, a no-op elsewhere and on any failure
  (never raise). Call it at `cli/_exec.py::run_exec` entry, `cli/_service.py::cmd_start`, and
  where `edges/adapters/docket_runtime.py::DocketDriver` first runs a turn (`run_turn`), before
  any task process is spawned. `core/` stays free of the call (layering).
- The flag resets across `execve`, so children stay debuggable; it makes this process's
  `/proc/<pid>/environ` and `mem` root-owned. Check nothing in docket reads another docket
  process's `/proc` entries (e.g. `stop` reading a serve pid's cmdline): `rg -n '/proc/' src`.
- **The test must not call the helper inside the pytest process** (it would change pytest's own
  dumpability for the rest of the run). Integration lane: a subprocess runs Python that calls the
  helper, seeds a fake key in its env, starts a child that reads `/proc/<ppid>/environ`; RED on
  the base is the child reading the key, GREEN is `PermissionError`/empty. Skip off Linux.
- Spec: `security-gates.spec.md` 0.40.0 ("Credentials in task processes").
