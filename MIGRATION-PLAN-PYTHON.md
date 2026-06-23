# Migration Plan — Bash → Modern Python (architecture-led, right-sized)

> Companion to ARCHITECTURE-AUDIT.md. docket is a **thin wrapper/orchestrator over
> OpenClaw**. This plan optimizes for three things in tension — *evolvable*,
> *scalable*, *clear/maintainable* — while explicitly **refusing to
> overengineer**. Strategy: strangler fig, with golden tests as the parity net.

---

## 0. The one architectural insight that drives everything

Measured today: **30 files reference `openclaw.json` / `OPENCLAW`** and there are
**136 `python3` heredocs** doing JSON. And OpenClaw's surface is *more* than that
one file — recent commits added `docket auth` (reads OpenClaw's
`auth-profiles.json`; "OpenClaw owns the credential format") and
`wire-local-provider.sh` (writes `models.providers.*` via `openclaw config set`).
So docket already speaks to **three OpenClaw-owned surfaces** (config, auth
profiles, provider registration), and that knowledge is **smeared across the
codebase.** For a wrapper, that is the #1 evolvability risk: when OpenClaw changes
a flag, a file, or a credential shape, you edit dozens of files.

So the single boundary worth building is an **Anti-Corruption Layer (ACL)**: one
adapter owns *all* knowledge of OpenClaw (its CLI, `openclaw.json`,
`auth-profiles.json`, and provider config), and translates to/from docket's own
domain models. Nothing else in the app may import or know the OpenClaw format.
This is not extra ceremony — it *removes* the duplication that exists today.
(The `auth` command is itself the build-vs-wrap thesis in miniature: docket does
*not* own credentials — it delegates to OpenClaw and just fronts the UX.) It is the difference between a wrapper that evolves
and one that ossifies.

Everything else in this plan is deliberately minimal.

---

## 1. Architecture: "thin wrapper, one hard boundary, three layers"

```
┌─────────────────────────────────────────────────────────┐
│ cli/   Typer commands — parse args, format output.       │  no business logic
├─────────────────────────────────────────────────────────┤
│ core/  domain models (Pydantic) + services:              │  pure, unit-tested
│        lifecycle, budget, policy, sync, drift            │  no Typer, no subprocess
├─────────────────────────────────────────────────────────┤
│ edges/ store/json_store.py   adapters/openclaw.py (ACL)  │  the only I/O
│        adapters/system.py (systemctl/docker/git)         │
└─────────────────────────────────────────────────────────┘
        dependency rule → arrows point DOWN only
        cli → core → edges.  core never imports cli or subprocess.
```

This is **light hexagonal** (ports & adapters), applied once, where it pays:
- `core/` is testable with zero I/O — inject a fake store/adapter.
- `adapters/openclaw.py` is the ACL: the *only* place OpenClaw's shape lives.
- The CLI is a dumb shell over `core/` — easy to add commands as the tool grows.

**Why this scales the way docket actually scales.** "Scale" here is NOT
throughput (it's a single-host CLI). It's: more *commands*, more *agents*, more
*contributors*. The three-layer split addresses exactly those — Typer sub-apps
absorb command growth, the store handles agent-count growth, and types + tests
absorb contributor growth. We do **not** design for QPS we'll never see.

---

## 2. Anti-overengineering guardrails (the "we will NOT" list)

Equally important as what we build. For a wrapper this size, these are wrong:

| We will NOT | Because |
|---|---|
| Use a DI/IoC framework | Plain constructor/function args are enough at this size |
| Build a plugin system or `AbstractBackend` | There is exactly **one** backend (OpenClaw). One concrete ACL behind a thin `Protocol` — no speculative generality |
| Use FastAPI/uvicorn for `serve` | It's **94 lines / 3 endpoints**. Use stdlib `http.server` + `prometheus_client`. No async stack for a metrics scrape |
| Go async | The CLI is synchronous; blocking subprocess calls are correct and simpler |
| Add an ORM / database | JSON files modeled by Pydantic *are* the store |
| Event sourcing / message bus / CQRS | No. It's a CLI that edits two JSON files |
| Deep package nesting / DDD ceremony | Keep it flat: `cli/ core/ edges/`. Split a module only when it actually hurts |
| Abstract before the second caller exists | Rule of three. Port to parity first, generalize later |

The target is **boring, typed, obvious Python** — not a framework showcase.

## 3. Stack (minimal, modern, justified)

| Concern | Choice | Note |
|---|---|---|
| Language / packaging | Python 3.11+, `uv`, `pyproject.toml` | one entry point `docket = docket.cli:app` |
| CLI | **Typer** | type-hinted subcommands map 1:1 to today's `cmd_*` |
| Models / validation | **Pydantic v2** | replaces hand-rolled `AGENT_SCHEMA`; add `schema_version` for migrations |
| Output | **Rich** | colors/tables (was `output.sh`) |
| Locking | `filelock` | was `flock` |
| HTTP/metrics | stdlib `http.server` + `prometheus_client` | **not** FastAPI |
| Tests | **pytest** + golden/contract tests | parity net |
| Lint/format/types | **ruff** + **mypy** | was shellcheck |
| Dist | `uv tool`/pipx; binary only on demand | PyInstaller only if zero-dep is required |

## 4. Package layout (flat on purpose)

```
src/docket/
├── cli/            # Typer app + one module per command group
├── core/
│   ├── models.py   # Pydantic: AgentMeta, Binding, Budget…  (+ schema_version)
│   ├── lifecycle.py budget.py policy.py sync.py drift.py
├── edges/
│   ├── store.py            # atomic write + filelock + .bak  (was json.sh)
│   ├── adapters/openclaw.py   # THE ACL — only file that knows openclaw.json + CLI
│   └── adapters/system.py     # typed systemctl/docker/git wrappers
├── serve.py        # stdlib http.server, 3 endpoints
├── config.py       # paths + settings (env-overridable, as today)
└── ui.py           # Rich helpers, picker
tests/  bin/docket(shim during migration)
```

---

## 5. Phased migration (each phase ships; nothing breaks)

- **P0 — Contract freeze.** Turn `specs/` + `cli-json-shapes.spec.md` into golden
  tests against the *current Bash* CLI (stdout/JSON/exit code). The acceptance
  gate for every later phase.
- **P1 — Skeleton + dispatcher seam.** `pyproject`, Typer app, CI (ruff/mypy/
  pytest). `bin/docket` becomes a dispatcher: ported command → Python, else Bash.
  Zero behavior change. This is the strangler seam.
- **P2 — Data layer + the ACL (highest value).** Pydantic models, `store.py`,
  and `adapters/openclaw.py`. Collapse the 136 heredocs **and** the OpenClaw
  surfaces (30 `openclaw.json` touch points + `auth-profiles.json` + provider
  config) into these two modules. Route Bash through them.
  *Stop-and-be-happy point:* even before commands move, the smell is gone.
- **P3 — Read-only commands** (`list`, `info`, `cost`, `doctor`, `scope show`).
  Easiest goldens, builds confidence.
- **P4 — Writer commands** (`add`, `delete`, `profile`, `models`, `keys`,
  `maintain`, `edit`). Exercise store + sync + service restart.
- **P5 — Edges & extras.** `adapters/system.py`; `serve.sh` → `serve.py` (stdlib);
  telegram/approval/trace/audit. Defer `experimental/` — port last or drop.
- **P6 — Cutover.** Delete `lib/**/*.sh`, collapse `bin/docket` to the entry
  point, swap shell tests for pytest, drop shellcheck except the install shim.

Effort note: P0–P2 are the real work and de-risk everything. P3–P5 are mechanical
and parallelizable per command (33 commands total). You can pause after P2
indefinitely and already be in a far better place.

---

## 6. Branch roadmap & merge strategy

**Branch:** `python-core`, cut from `develop`. Long-lived *integration* branch,
**rebased on `develop` frequently** to avoid drift. Feature work lands on
short-lived `pc/<topic>` branches that PR into `python-core`.

**Merge philosophy — incremental, behind the seam.** Because P1 installs a
dispatcher, the Python core can ride alongside Bash with **no behavior change**.
So we merge to `develop` in *two safe waves* rather than one terrifying big-bang:

```
develop ──●──────────────────●────────────────────────●──▶  (main via release)
          │ M1 merge          │ M2 merge                │ M6 merge
          │ (seam, no-op)      │ (data layer+ACL live)    │ (cutover)
python-core ─●──●──●──●──●──●──●──●──●──●──●──●──●──●──●──●
            M0 M1   M2        M3   M4      M5         M6
```

### Milestones (each = a PR with a hard merge gate)

| # | Milestone | Merge target | Gate to merge |
|---|---|---|---|
| M0 | Golden/contract tests of current Bash CLI | **develop** directly | Goldens green on current code (pure addition, zero risk) |
| M1 | Python skeleton + dispatcher seam (0 cmds routed) | **develop** | `docket` behaves identically; CI green; ruff/mypy clean |
| M2 | `store.py` + Pydantic models + `openclaw.py` ACL; Bash routed through them | **develop** | All goldens green **+** concurrency/locking tests **+** ACL is the only openclaw.json reader |
| M3 | Read-only commands on Python path | python-core | Per-command goldens byte-parity |
| M4 | Writer commands on Python path | python-core | Goldens + dual-source sync tests |
| M5 | `serve.py`, system adapter, telegram/trace/audit | python-core | Goldens + metrics endpoint contract test |
| M6 | Cutover: delete Bash, collapse shim, swap CI | **develop → main** | 100% commands on Python; goldens green; Bash `lib/` removed |

### Rules that keep the branch healthy
- **Rebase `python-core` on `develop` at least weekly** (the Bash side keeps
  moving — drift is the #1 long-lived-branch killer).
- **Every milestone is independently revertable** — the dispatcher means flipping
  a command back to Bash is a one-line change.
- **Goldens are the contract.** A command is "ported" only at byte-parity. Refactor
  for elegance *after* cutover, never during a port.
- **No scope creep.** New *features* land on `develop` in Bash (or wait for the
  Python core); `python-core` only *re-implements* existing behavior until M6.
- **Definition of done for the whole effort:** M6 merged, `lib/**/*.sh` deleted,
  `bin/docket` is a thin entry point, README/CLAUDE.md updated, install shim still
  Bash. Tag a minor release.

### If you prefer one branch, one merge
Possible but not recommended: keep everything on `python-core` and do a single
P6 merge. Higher review risk and worse drift. The two-wave approach (M1, M2 land
early behind the seam) gives the same isolation with far less merge pain.

---

## 7. What this buys you, against the three goals

- **Evolvable:** OpenClaw churn touches *one* file (ACL), not 29. Pydantic
  `schema_version` gives a real migration path. Golden tests make refactors safe.
- **Scalable (the dimensions that apply):** command growth → Typer sub-apps;
  agent growth → one store; contributor growth → types + fast mocked tests.
- **Clear & maintainable, not overengineered:** three layers, one boundary, no
  framework theatre, boring typed Python. The "we will NOT" list is the guardrail.
```
