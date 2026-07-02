# TODO — active task board

> **This is docket's single standing TODO file.** It holds the executable cards for whatever phase is
> currently active in [ROADMAP.md](ROADMAP.md). Do **not** create per-phase task files — when a phase
> finishes, clear its cards (the phase record stays in ROADMAP) and append the next phase's cards here.
>
> *Phase 11 (Competitive differentiation, CD-0…CD-9) is **COMPLETE 2026-06-25** — its durable record
> lives in ROADMAP §5 (Phase 11 section) and the roadmap Changelog. Its board was cleared per the
> convention above.*
>
> ---
>
> ## Active: PHASE 12 — Consolidation & hardening (audit-driven)
>
> Executable board for **PHASE 12** in [ROADMAP.md](ROADMAP.md) (read that section first — rationale,
> explicit **keeps**, and exit criteria). The source of record is
> `internal-docs/architecture-audit.md` (2026-07-02 full-repo audit; **read it before claiming a
> card** — every task below traces to a finding there, with file:line evidence). Each task is
> **self-contained** so a separate agent can claim and complete it independently.
>
> **What we're doing (one paragraph):** eleven phases of feature work landed with the architecture
> *mostly* honest — the audit confirmed the cli→core→edges direction and the ACL boundary hold. This
> phase closes the gaps it found: invariant breaches (store.py bypasses, raw `openclaw` shell-outs,
> UI printing from core), a 4,194-line `cli/__init__.py`, carried features that no longer earn their
> keep (`drift.py`, the legacy `team` queue, drifted hand-written completions, overdue deprecation
> shims, dead templates), specs/docs that drifted from the CLI, and Bash-era scripts still wired into
> CI. **No new features in this phase.** The ROADMAP Phase 12 section lists the audited *keeps* —
> re-read it before cutting anything not named on a card.

## How to use this board (read before claiming a task)

1. **Claim:** set Status → `IN-PROGRESS (@you)`. One agent per task.
2. **Read first (always):** `internal-docs/architecture-audit.md`, ROADMAP.md §2 (Python ground
   truth), §4.5 (architectural principles), the Phase 12 section (esp. the **keeps** list),
   [CLAUDE.md](CLAUDE.md), and the task's own "Read" list.
3. **Layer rule (non-negotiable):** `cli/ → core/ → edges/`, inward only. OpenClaw formats live **only**
   in `edges/adapters/openclaw.py` (the ACL). docket-owned JSON goes **only** through `edges/store.py`
   (JSONL append logs are the one D-12 exemption). Every shell-out goes through `edges/adapters/`.
4. **No-behavior-change rule:** unless the card explicitly removes a user-facing surface, CLI output
   is frozen — the golden suite (`bash tests/golden/run.sh verify-all`) must stay byte-identical.
   Cards that *do* change the surface (CH-4, CH-6, CH-8) say so and require regenerated goldens with
   the diff explained in the PR.
5. **Definition of done (per task):** acceptance criteria pass · a pytest covers it (add/refresh a
   golden case if output changes) · `uv run ruff check . && uv run ruff format --check . && uv run
   mypy src && uv run pytest` green · `bash tests/golden/run.sh verify-all` green · committed
   `Type: description` (no Claude/Co-Authored-By trailer) · public-repo privacy scrubbed (grep the
   diff for real names / `/home/<user>` paths before committing).

**Status legend:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs CH-x)` · `DONE`
**Size:** S ≈ ½ day · M ≈ 1–2 days · L ≈ 3–5 days (split before claiming if L)
**Branch model:** one short-lived `pc/ch-<id>` branch per task → PR into the working branch (`develop`).

---

## Dependency map (what unblocks what)

```text
DONE 2026-07-02 (merged into develop): CH-0, CH-1, CH-2, CH-3, CH-4, CH-5, CH-6, CH-9, CH-13.

Remaining — all unblocked except where noted:
  CH-7  (split cli/__init__.py)              ← unblocked (needed CH-1, CH-4, CH-6 — all merged)
  CH-8  (drift-proof completions)            ← unblocked (needed CH-4, CH-6 — both merged)
  CH-10 (spec/SDD truth pass)                ← unblocked (needed CH-4, CH-5, CH-6 — all merged)
  CH-11 (docs completeness pass)             ← BLOCKED (needs CH-8; CLAUDE.md portion already done)
  CH-12 (changelog verify + cut 0.2.0)       ← unblocked, but do last (wants CH-7/8/10/11 landed too)
```

Suggested remaining order: **CH-7 (unblocks nothing further but is the highest-conflict-risk file,
do it before more hands touch cli/__init__.py) → CH-8 → CH-10 (parallel with CH-8) → CH-11 → CH-12.**

---

### CH-0 — Quick truth & dead-file sweep (zero-risk lies and orphans)

- **Depends on:** — *(do first; cheap)* · **Parallel-safe with:** everything
- **Read:** audit §2 ("Wrong in docs" + "Internally contradictory") and §4 ("Cosmetic"); `CLAUDE.md`, `README.md`, `src/docket/templates/`, `scripts/render-hero.py`.
- **Why:** these are documented-but-false claims and files with zero references — each is a 1-line fix with no design decision, and every day they stay they mislead agents reading the docs (this file's own audit trail started from CLAUDE.md being wrong).
- **Do:**
  1. `CLAUDE.md:183` — the "Team coordination" bullet claims **`docket team status` shows specialist health**; that subcommand was removed (`specs/functional/team-coordination.spec.md:114`). Rewrite the bullet to the real surface (`delegate/queue/start/done/cancel`) **and** add "(scheduled for retirement — see D-11/CH-4)" so CH-4 doesn't get forgotten. Do not describe features that don't exist.
  2. Test counts: `CLAUDE.md:63` and `:120` say **416**; `README.md:431` and `:437` say **694**. Actual at audit time: **688** (`grep -rc "def test_" tests/python/ | awk -F: '{s+=$2} END {print s}'`). Recount at edit time and set all four to the real number. (CH-9 re-arms the automatic guard; this is the manual truth fix.)
  3. Delete the three dead template files (zero references verified by the audit — re-verify with grep before deleting): `src/docket/templates/SOUL-error-handling.md`, `src/docket/templates/status-awareness.md`, `src/docket/templates/bug-fix-pipeline.lobster.yml`. Note: `workflow create` writes an **inline** template; install/pod provisioning write SOUL/AGENTS inline — these files ship in the wheel for nothing.
  4. `scripts/render-hero.py:9` — references `internal-docs/COST-FEATURE-AUDIT.md`, which does not exist. Point the comment at the real positioning source (`internal-docs/competitive-analysis.md`) or delete the sentence.
  5. `src/docket/cli/__init__.py:3865` (cmd_eval docstring) + `CLAUDE.md:76` — say eval runs "stubs"; `_eval.py` is a real harness shelling to `tests/evals/*.eval.sh` with real exit codes. Reword to "non-blocking specialist-role evals".
  6. `specs/functional/agent-lifecycle.spec.md:5` — stale `2024-01-20` Last-Updated date (siblings are 2026). Set to the date of your edit.
- **Out of scope:** any code behavior change; the full docs pass (CH-11); the spec contract fixes (CH-10).
- **Deliverables:** edited CLAUDE.md/README/spec date/py-docstring; 3 files deleted; a pytest asserting the deleted templates are not referenced anywhere under `src/` (guards against re-orphaning).
- **Acceptance gate:** [ ] no grep hit for `team status` in CLAUDE.md; [ ] all four test-count mentions equal the real count; [ ] the 3 template files are gone and the wheel builds (`uv build` or the packaging test passes); [ ] no dangling `COST-FEATURE-AUDIT` reference; [ ] suite + goldens green (byte-identical — nothing here touches output).
- **Size:** S · **Status:** DONE — merged into develop 2026-07-02.

---

### CH-1 — Enforce the store.py single-writer rule (D-12)

- **Depends on:** — · **Parallel-safe with:** CH-2/CH-3 *(coordinate with CH-4/CH-7: they edit the same `cli/__init__.py`; if CH-4 lands first, its task-list writer sites vanish)*
- **Read:** audit §1 ("store.py bypass"); `src/docket/edges/store.py` (the `_atomic_write` + filelock + `.bak` + 0600 chokepoint, docstring lines 1-6); the violating sites listed below; ROADMAP §6 **D-12**.
- **Why:** store.py's docstring claims ALL docket-owned JSON goes through it, but the tmp-write→replace→chmod dance is hand-copied 8+ times with varying rigor — several copies **omit the filelock and `.bak` rotation**, so a concurrent invocation can corrupt exactly the files the chokepoint exists to protect. The correct pattern already exists in-tree (`cli/_doctor.py:532`, `cli/_install.py:301,367`).
- **Do:**
  1. Route through `store.write_json` (deleting the local atomic-write copies):
     `cli/__init__.py:720` (new-agent `.docket-meta.json`) · `cli/__init__.py:1646` (memory index) ·
     `cli/__init__.py:2228,2256` (secrets store + meta sidecar) · `cli/__init__.py:3021,3027`
     (manager task list — **skip if CH-4 already deleted `team`**) · `cli/_pod.py:210` (pod-member
     meta) · `core/models_policy.py:335` (`docket-models.json` — its hand-rolled `:306` "atomic
     update" comment goes away) · `core/approval.py:82` · `core/utils.py:186,283`.
     (`core/drift.py:125` is deleted wholesale by CH-5 — don't port it.)
  2. **Exemption (per D-12):** `core/trace.py` and `core/audit.py` append JSONL — leave them, but
     name the exemption explicitly in the store.py docstring ("append-only JSONL logs write
     directly; everything else goes through write_json") and fix the trace/audit docstrings to
     cite D-12 instead of asserting their own right to bypass.
  3. Update the CLAUDE.md "Never write JSON by hand" convention line and ROADMAP §3 to state the
     rule + exemption in one sentence.
  4. Add a **guard test**: a pytest that greps `src/docket` for `write_text(` calls whose argument
     contains `json.dumps` outside `edges/store.py` (+ the two exempt modules) and fails listing
     the offenders. This is what keeps the rule true after the phase.
- **Out of scope:** changing any file format or path; touching `openclaw.json` writes (ACL-owned, already correct); performance work.
- **Deliverables:** all listed sites on `store.write_json`; deleted local atomic-write helpers; docstring + CLAUDE.md rule text; the guard pytest.
- **Acceptance gate:** [x] guard test passes (zero offenders) and is in the suite; [x] every migrated file keeps 0600 perms (existing perms tests still green); [x] no behavior change (goldens byte-identical); [x] `uv run pytest` + mypy + ruff green.
- **Size:** M · **Status:** DONE — merged into develop 2026-07-02. `core/drift.py` was subsequently deleted whole by CH-5 (its guard-test exclusion is now moot); `cli/__init__.py`'s manager-task-list write site was subsequently deleted whole by CH-4 (the migration became moot when the code was removed — resolved at merge time).

---

### CH-2 — Move `openclaw` binary shell-outs behind the ACL

- **Depends on:** — · **Parallel-safe with:** CH-1/CH-3
- **Read:** audit §1 ("Raw `openclaw` binary shell-outs"); `src/docket/edges/adapters/openclaw.py` (it already shells the binary internally — e.g. `:270,:517,:552` — so the pattern exists); the violating sites below.
- **Why:** knowing the `openclaw agents add …` / `openclaw models auth …` command grammar IS OpenClaw coupling; the ACL exists to hold all of it. Worst offender: `core/utils.py:47` puts a raw `subprocess.run` in the *pure* core layer, which ROADMAP §3 forbids outright ("core has no subprocess").
- **Do:**
  1. Add typed ACL wrappers (mirror the existing internal call style, degrade gracefully when the
     binary is missing like `system.py` does): `openclaw_version()`, `agents_add(id, workspace, …)`,
     `auth_setup_token()`, `auth_paste_token(…)`, `onboard()`.
  2. Re-point the callers: `core/utils.py:47` (`openclaw --version`) · `cli/__init__.py:729`
     (`openclaw agents add`) · `cli/__init__.py:~2582,~2597` (`openclaw models auth setup-token` /
     `paste-token`) · `cli/_install.py:81` (`--version`), `:94` (`onboard`).
  3. The non-openclaw shell-outs flagged by the audit (`_eval.py` bash, `_trace.py` tail, `$EDITOR`
     at `cli/__init__.py:3509`, `_install.py:56` python version) are **in scope only for a decision
     note**: either wrap them in `edges/adapters/system.py` or add one sentence to ROADMAP §3
     scoping the invariant to `openclaw|git|docker|systemctl`. Pick one; don't leave it implicit.
  4. Add a **guard test**: grep `src/docket` for `subprocess`/`"openclaw"` co-occurrence outside
     `edges/` and fail listing offenders.
- **Out of scope:** changing what the shell-outs do; retrying/error-handling redesign; new openclaw features.
- **Deliverables:** ACL wrappers + re-pointed callers; the scoping decision recorded; guard pytest; unit tests for each wrapper (mock the subprocess like existing ACL tests).
- **Acceptance gate:** [ ] zero `openclaw` subprocess calls outside `edges/` (guard test green); [ ] `core/` has zero `subprocess` imports; [ ] behavior unchanged (goldens byte-identical); [ ] suite green.
- **Size:** M · **Status:** DONE — merged into develop 2026-07-02. Scoping decision: the shell-out invariant is scoped to `openclaw|git|docker|systemctl` (recorded as ROADMAP D-13); the other flagged one-offs (`_eval.py`, `_trace.py`, `$EDITOR`, `_install.py` python-version check) were left as-is — CLI-only, no OpenClaw/daemon coupling to remove.

---

### CH-3 — Get UI printing out of `core/` and `edges/`

- **Depends on:** — · **Parallel-safe with:** CH-1/CH-2
- **Read:** audit §1 ("core→presentation violation"); `src/docket/core/provider.py` (`:19` imports `docket.ui`; ~20 `console.print` calls at `:57-112`, including literal CLI hints at `:92`); `src/docket/edges/adapters/system.py` (`:19` ui import; `restart_gateway` prints at `:135-145`); whichever `cli/` command invokes the provider flow (grep callers of `provider.`).
- **Why:** ROADMAP §2 states "core has no knowledge of terminals"; `provider.py` is a CLI command flow misfiled in core. Every violation here makes the layer rule aspirational instead of enforced.
- **Do:**
  1. **provider.py:** split it — pure registration/validation logic (building the provider config,
     talking to the ACL) stays in `core/provider.py`; the interactive flow + all Rich output moves
     to a new `cli/_provider.py` (or into the command that hosts it today). Core functions return
     data/result objects; cli renders them. Output strings stay **byte-identical** (goldens are the
     net).
  2. **system.py `restart_gateway()`:** return a typed result (e.g. `RestartResult(status, detail)`)
     instead of printing; the ~dozen cli call sites render it via `ui.*` with the same wording.
     Alternative if the fan-out is too noisy: keep one thin `cli/`-side helper that calls the edge
     function and prints. Either way, `edges/` loses its `ui` import.
  3. Add a **guard test**: no `from docket import ui` / `import docket.ui` under `src/docket/core/`
     or `src/docket/edges/`.
- **Out of scope:** changing any message text (frozen by goldens); redesigning the provider feature.
- **Deliverables:** split provider modules; typed restart result + rendered call sites; guard pytest.
- **Acceptance gate:** [ ] guard test green (zero ui imports in core/edges); [ ] goldens byte-identical; [ ] mypy strict green (the new result type is typed, not `Any`); [ ] suite green.
- **Size:** M · **Status:** DONE — merged into develop 2026-07-02. `core/provider.py` split into a pure `ProviderRegistration`-returning function + new `cli/_provider.py` for the interactive/printing flow; `system.restart_gateway()` returns a typed `RestartResult`, rendered by callers.

---

### CH-4 — Retire `docket team` (D-11) — one delegation system, not two

- **Depends on:** — *(land before CH-7/CH-8/CH-10/CH-11)* · **Parallel-safe with:** CH-6
- **Read:** ROADMAP §6 **D-11**; audit §3 item 3; `cli/__init__.py:2968-3199` (`cmd_team` + `_team_delegate/_team_queue/_team_transition/_team_help_text/_ensure_task_list` + its private `_atomic_write_json`); `core/dispatch.py` (the **pod** queue — per-Lead `TASK_LIST.json`, real dispatch, already store.py-clean); `src/docket/__main__.py` (`_ALIASES`/`_REMOVED` maps — the removal pattern to copy); `specs/functional/team-coordination.spec.md`.
- **Why:** `team` is a second, manual task queue (`workspaces/manager/TASK_LIST.json`) whose tasks are **never executed** — states are hand-transitioned, there is no dispatcher. Pods own delegation with real execution (`docket pod <p> delegate/queue/dispatch`), and the opt-in org Portfolio Manager owns the cross-pod view. Carrying both queues confuses every doc and agent that touches delegation.
- **Do:**
  1. Delete the `team` command block and helpers from `cli/__init__.py`; add `team` to the
     `_REMOVED` map in `__main__.py` with a notice that maps each subcommand to its replacement
     (`team delegate "<t>"` → `docket pod <project> delegate "<t>"`; `team queue` →
     `docket pod <project> queue`; org-wide view → the Portfolio Manager, `docket install
     --portfolio`). Exit 1, like the other removed commands.
  2. Leave any existing `workspaces/manager/TASK_LIST.json` on disk untouched (operator data);
     mention it in the notice text ("your old queue file is preserved at …").
  3. Purge `team` from: `cli/_completions.py` (both shells), `cli/_help.py`,
     `core/provider.py:106-115` (the stale "docket team status/delegate/queue" guidance — reword
     to pod commands; coordinate with CH-3 which moves this code), any `docs/` snippets that CH-11
     hasn't reached yet only if trivially greppable (CH-11 does the full docs pass).
  4. Mark `specs/functional/team-coordination.spec.md` **Status: Retired** with a one-paragraph
     pointer to the pod delegation spec/reality (CH-10 finishes the spec normalization).
  5. Tests: delete team tests; add a removed-command test (`team` exits 1 with the mapping text);
     regenerate the help/completions goldens (this card intentionally changes output — explain the
     diff in the PR).
- **Out of scope:** touching `core/dispatch.py` / pod delegation; deleting the org manager *agent* (it stays, transitional per CLAUDE.md); the Portfolio Manager.
- **Deliverables:** command removed + `_REMOVED` notice; purged references; spec marked Retired; tests + regenerated goldens; ~231 LOC net deletion.
- **Acceptance gate:** [ ] `docket team delegate "x"` exits 1 with the pod mapping in the message; [ ] zero live `team` references in completions/help/provider output; [ ] pod delegate/queue/dispatch untouched (their tests green); [ ] suite + regenerated goldens green.
- **Size:** M · **Status:** DONE — merged into develop 2026-07-02 (16-case golden suite, `team_queue.golden` removed).

---

### CH-5 — Delete `core/drift.py` (role-drift detection)

- **Depends on:** — · **Parallel-safe with:** everything *(tiny serve.py touch — trivial rebase)*
- **Read:** audit §3 item 1; `core/drift.py` (190 LOC); its **only** import site `serve.py:261` (used at `:268` inside the opt-in `--dispatch` sweep); `config.py:29-36` (`BASELINE_WINDOW`/`DRIFT_THRESHOLD`/`DRIFT_COOLDOWN` — check each knob's other users before removing; `METRICS_WINDOW` is used by `_metrics.py`, **keep it**); `cli/_trace.py:35` (`drift_alert` render color).
- **Why:** a 190-LOC statistical engine whose output is a `drift_alert` trace event feeding a Telegram notification its own docstring admits was never implemented; it needs role-tagged trace data that ingestion mostly labels `agent_role: "unknown"`, so it almost never has input. One caller, zero user-facing output. *(Note: this is the **role-success-rate** drift engine — NOT the meta↔openclaw config-drift check in `doctor`/`sync.py`, which stays.)*
- **Do:** delete `core/drift.py`; remove the import + call from `serve.py`; remove the three drift-only config knobs (+ their env-var docs if any); keep the `drift_alert` color entry in `_trace.py:35` so historical trace files still render; delete drift tests; grep `docs/`+`specs/` for role-drift promises and strip them (the observability spec may reference it — coordinate with CH-10).
- **Out of scope:** `doctor`'s config-drift check; `sync.py`; `_metrics.py`; trace ingestion.
- **Deliverables:** module + knobs + wiring + tests deleted; ~190 LOC + 4 config lines gone; a note in the PR pointing at the audit finding.
- **Acceptance gate:** [ ] no `core.drift` import anywhere; [ ] `serve --dispatch` sweep still runs (its other duties intact, tests green); [ ] historical traces with `drift_alert` events still render in `trace` output; [ ] suite green.
- **Size:** S · **Status:** DONE — merged into develop 2026-07-02.

---

### CH-6 — Remove the deprecated tier/`profiles:` shims (D-2 exit, targeted at 0.2.0)

- **Depends on:** — *(land before CH-7/CH-8/CH-10/CH-11; release note in CH-12)* · **Parallel-safe with:** CH-4
- **Read:** ROADMAP §6 **D-2** ("keep shims one release, then remove" — 0.1.0 shipped 2026-06-10 with the shims; this is the "then remove"); `core/models_policy.py` (`TIER_ANCHORS` :12-16, `MODEL_ALIASES`, the 3-hop tier→alias→anchor resolution in `validate_model`, legacy `profiles:` registry key reads at `:157,:330`); `__main__.py` (`tier`→`profile` alias); audit §3 item 6.
- **Why:** the deprecation window D-2 defined has elapsed. The double vocabulary (tier names + roles, `profiles:` + `roles:`) is exactly the kind of historical patch this phase exists to collect, and the completions/docs still advertising `tier` prove shims rot outward.
- **Do:**
  1. Remove user-facing tier vocabulary: the `tier` command alias, tier names accepted as model
     args, deprecation-warning paths. **Check first** whether the internal rank anchors also serve
     as the model **fallback chain** (CLAUDE.md:182 says they do) — if so, keep the internal
     anchor table under a non-user-facing name and remove only the user-facing alias resolution.
  2. Remove the legacy `profiles:` registry key: on load, if a user registry contains `profiles:`
     but no equivalent `roles:`, **migrate it once** (write back via store.py, warn what happened);
     afterwards ignore the key. Give `docket doctor` a check for leftover `profiles:` keys.
  3. Strip tier/`profiles:` from `_completions.py` (or leave for CH-8 if it lands first — whoever
     is second rebases), `_help.py`, and any error-message suggestions.
  4. This is a **breaking change** for anyone scripting tier names: it must be in the 0.2.0
     changelog section (CH-12) under Removed, with the migration one-liner.
- **Out of scope:** the role→model policy itself (`roles:`, presets, pins — all stay); `MODEL_PRICING` (kept per audit; only the tier vocabulary goes).
- **Deliverables:** shims removed; one-shot `profiles:`→`roles:` migration + doctor check + tests (registry with legacy key migrates once, idempotent re-run, unknown keys untouched); regenerated goldens where output changes.
- **Acceptance gate:** [ ] `docket profile <id> premium` (a tier name) fails with a helpful model-id message; [ ] a legacy `profiles:` registry migrates once and works; [ ] fallback chain still resolves (its tests green); [ ] suite + goldens green.
- **Size:** M · **Status:** DONE — merged into develop 2026-07-02. Internal rank anchors preserved privately as `_RANK_ANCHORS` (still back the model fallback chain); tier names now hard-error instead of resolving; `profiles:` migrates once to `roles:` with a `docket doctor` check for residual keys.

---

### CH-7 — Split the `cli/__init__.py` god-module

- **Depends on:** **CH-1, CH-4, CH-6 landed** *(they delete/rewrite chunks of this file — splitting first would force triple rebases)* · **Parallel-safe with:** CH-9/CH-13 · **UNBLOCKED 2026-07-02 — CH-1, CH-4, CH-6 all merged.**
- **Read:** audit §1 ("Structural smells"); `cli/__init__.py` (4,194 lines, 32% of the codebase); the existing split-out pattern (`cli/_pod.py`, `_gates.py`, `_install.py`, `_doctor.py` … — registration stays in `__init__.py`, implementation lives in `_<group>.py`).
- **Why:** the file mixes agent CRUD, keys/secrets, context/memory, workflows, cost, and gateway registration; dozens of mid-function deferred imports exist only because the module is too big to import cleanly. Every future card pays a merge-conflict tax on this file until it's split.
- **Do:** mechanical extraction, **zero behavior change**, in reviewable stages (one commit per module):
  1. `cli/_keys.py` — `keys` + `auth` commands + the secrets-store helpers (post-CH-1 they call store.py).
  2. `cli/_context.py` — the `context` group (6 subcommands, around `__init__.py:1439`) + memory-index helpers.
  3. `cli/_workflow.py` — the `workflow` group (~`:3207-3370`) incl. the inline template + validate/plan wiring to `core/lobster.py`.
  4. `cli/_cost.py` — `cost` (+ `--history` machinery).
  5. `cli/_agents.py` — the add/info/delete/maintain workspace-creation helpers if what remains still exceeds ~1,500 lines; otherwise leave CRUD in `__init__.py` and stop.
  Preserve command registration order (help output order is golden-pinned). Promote the deferred
  mid-function imports to module top level in each new file. No renames of public functions that
  tests import.
- **Out of scope:** any logic change; renaming commands; touching `core/`.
- **Deliverables:** 4–5 new `_*.py` modules; `cli/__init__.py` ≤ ~1,500 lines; one commit per extraction; imports normalized.
- **Acceptance gate:** [ ] goldens **byte-identical** (this is the whole point of doing it after the surface changes); [ ] `cli/__init__.py` ≤ ~1,500 lines; [ ] no deferred imports left that exist purely for load-order reasons (document any that must stay); [ ] mypy strict + suite green.
- **Size:** L *(split by stage — each extraction is independently landable)* · **Status:** TODO

---

### CH-8 — Drift-proof shell completions

- **Depends on:** CH-4 + CH-6 *(they change the command surface — do this after so it's done once)* · **Parallel-safe with:** CH-10/CH-11 · **UNBLOCKED 2026-07-02 — CH-4, CH-6 merged.**
- **Read:** audit §3 item 7; `cli/_completions.py` (171 LOC of hand-maintained bash/zsh string literals — already advertising `team`, `tier`, legacy `profile` semantics); the Typer docs on shell completion; `tests/golden/` (completions goldens exist); the 0.1.0-era changelog claim that completions were "drift-guarded" (the guard died with the Bash tree).
- **Why:** hand-written completions have already drifted — they advertise commands this phase removes. A completion script that lies is worse than none.
- **Do:** pick ONE (record the choice in the PR):
  - **(a) Generate:** derive the command/subcommand tables from the Typer `app` registry at
    runtime (walk `app.registered_commands`/groups), keeping the custom agent-id completion
    (reads live workspace ids) as-is. The emitted script shape may change → regenerate goldens.
  - **(b) Guard:** keep the literals but add a pytest that walks the Typer registry and fails if
    the advertised command/subcommand set ≠ the registered set (the old Bash suite had exactly
    this; it was lost in the port).
  Option (a) preferred (deletes the maintenance burden instead of alarming on it); (b) is
  acceptable if (a) fights Typer's internals. Either way: remove `team`/`tier` entries and add
  the Phase-11 commands the literals never learned (`policies`, `approve`, `deny`, `metrics`, …).
- **Out of scope:** fish/powershell support; changing the `completions` command interface.
- **Deliverables:** generated-or-guarded completions; stale entries gone; regenerated goldens; the drift-guard test in the suite.
- **Acceptance gate:** [ ] completions advertise exactly the live command set (test-enforced); [ ] `eval "$(docket completions bash)"` works in a smoke check; [ ] suite + goldens green.
- **Size:** M · **Status:** TODO

---

### CH-9 — Fix or retire the Bash-era scripts; re-arm the CI drift guard

- **Depends on:** — · **Parallel-safe with:** everything
- **Read:** audit §4 ("Cleanup now"); `scripts/spec-coverage.sh` (reads live commands from `lib/core/router.sh` — `lib/` was deleted at M6; `:29` and the case-arm greps can never work); `scripts/metrics.sh` (`:23-25` count `lib/commands/*.sh` → silently 0; billed as "single source of truth"); `.github/workflows/ci.yml:81,84` (the `|| true` masking the breakage); `pull_request_template.md:24`; `scripts/validate-specs.sh` (verify whether it still works against the current spec layout while you're in there).
- **Why:** the README-numbers drift guard is the mechanism that was supposed to prevent half the doc rot this phase is cleaning up — it went blind at the Bash cutover and nobody noticed because CI swallowed the failure with `|| true`. Re-arming it is what makes CH-0's manual count fix *stay* true.
- **Do:**
  1. **`metrics.sh` → rewrite for the Python tree** (or port to a small Python script under
     `scripts/`): tests = pytest collect count (`uv run pytest --collect-only -q | tail`), LOC =
     `src/docket/**/*.py`, commands = the Typer registry (e.g. a tiny
     `python -c "from docket.cli import app; …"` — count registered top-level commands), specs =
     `specs/**/*.spec.md`. Keep `--json` and `--check`; `--check` diffs the README's quoted
     numbers against the tree and **exits 1** on drift.
  2. **CI:** drop the `|| true` on the coverage step; make `metrics --check` a real failing gate.
  3. **`spec-coverage.sh` → retire or rewrite.** The honest v2: compare the Typer registry against
     `docs/commands.md` section headings and `specs/functional/*.spec.md` coverage, exit 1 listing
     gaps (this becomes the mechanical guard for CH-10/CH-11's work). If that's too much for this
     card, **delete the script** + its CI step and file the guard as part of CH-11's acceptance —
     a dead lint that always "passes" is worse than none.
  4. Update `pull_request_template.md:24` to whatever survives.
- **Out of scope:** the README numbers themselves (CH-0 fixes them; your `--check` then enforces); golden/eval harnesses (they work).
- **Deliverables:** working metrics script + failing CI gate; spec-coverage rewritten-or-deleted; ci.yml + PR template updated; a test or CI run proving the gate actually fails on a planted drift.
- **Acceptance gate:** [ ] `scripts/metrics.sh --check` (or successor) exits 0 on the true tree and 1 when a README number is perturbed; [ ] no CI step references `lib/`; [ ] no `|| true` on guard steps; [ ] CI green on the PR itself.
- **Size:** M · **Status:** DONE — merged into develop 2026-07-02. `scripts/metrics.sh` replaced by `scripts/metrics.py` (counts LOC/tests/commands/specs from the live Python tree + Typer registry, `--check` fails CI on drift); `spec-coverage.sh` deleted outright rather than rewritten (a rewrite would immediately red-flag CH-11's not-yet-done docs.md gaps — filed as a CH-11 follow-up instead of landing a day-one-red gate); `ci.yml`'s `|| true` removed.

---

### CH-10 — Spec (SDD) truth pass — specs become current-state contracts

- **Depends on:** CH-4 + CH-6 landed (surface final); CH-5 for observability references · **Parallel-safe with:** CH-8/CH-11 · **UNBLOCKED 2026-07-02 — CH-4, CH-5, CH-6 all merged.**
- **Read:** audit §2; every file under `specs/functional/` and `specs/data/`; the convention the specs already half-follow (Status line, Last-Updated, requirements, return codes).
- **Why:** a spec that documents a filename that doesn't exist (`deploy.yaml` vs `.lobster.yml`), exit codes no command returns, and state strings no file contains is worse than no spec — an agent implementing against it produces wrong code with full confidence. The user directive for this phase: specs must be **solid current-state contracts, not historical patches**.
- **Do:**
  1. **Contract fixes (spec follows code — v0.x documents reality, per the D-10 precedent):**
     - `workflow-integration.spec.md`: `<name>.yaml` → `<name>.lobster.yml` everywhere (req 1 :33,
       examples :97,:108,:122); Return Codes table (:83-88) → what the code does (`typer.Exit(1)`
       for not-found/exists/missing-name — `cli/__init__.py:3261,3266,3294`). Confirm
       `validate`/`plan` are specced (they are, :53-64 — leave).
     - `team-coordination.spec.md`: after CH-4 → **Status: Retired**, one paragraph pointing to pod
       delegation + the Portfolio Manager; keep the historical requirements below a fold or delete
       them (pick one convention and apply it to any other retired spec).
     - The `done`→`complete` state string (:53,:88): dead with CH-4 for team, but grep
       `specs/` + `docs/commands.md:538` for the same claim about **pod** queue states and align
       with `core/dispatch.py`'s real state set (`pending/in_progress/done/failed/blocked` — verify
       in source).
  2. **Status-line audit:** re-verify every spec's `Status:` against code (the audit found these
     accurate: security-gates "Implemented, opt-in", eval, model-profiles, agent-lifecycle,
     api-keys, audit, cost-tracking, session-scoping, telegram-integration, workspace-structure —
     spot-check anyway; anything CH-4/5/6 changed gets updated).
  3. **De-noise:** move "Removed X on date"-style narrative out of requirement bodies into a short
     `## Changelog` block at the bottom of each spec (or delete when git history suffices).
     Requirements sections describe the present tense only. Fix remaining stale Last-Updated dates.
  4. **Observability spec:** strip role-drift promises (CH-5 deleted the engine); `trace`/`metrics`
     requirements stay (they shipped).
  5. Keep `specs/data/serve-read-api.spec.md` (CD-8) and `docket-meta.spec.md` pinned to reality —
     they're recent; verify, don't rewrite.
- **Out of scope:** writing specs for features that never had one (only fix what exists — a new-spec backlog item goes to §7 if you find a gap worth naming); docs/ (CH-11).
- **Deliverables:** corrected spec set; one consistent retired-spec convention; a PR table listing every spec → what changed (accuracy audit trail).
- **Acceptance gate:** [ ] zero spec claims contradicted by code for: file paths/extensions, exit codes, state strings, command surfaces (grep-verified per spec in the PR table); [ ] every Status/Last-Updated line current; [ ] no requirement body narrates history; [ ] suite green (specs aren't executable, but `validate-specs.sh`/CH-9's guard must pass if present).
- **Size:** M · **Status:** TODO

---

### CH-11 — Documentation completeness pass (`docs/commands.md` first)

- **Depends on:** CH-4 + CH-6 + CH-8 landed (surface + completions final) · **Parallel-safe with:** CH-10
- **Read:** audit §2 ("Missing from docs"); `docs/commands.md` (bills itself the complete reference); `src/docket/__main__.py` (`_ALIASES`/`_REMOVED` — the true alias table); `uv run python -m docket --help` + each group's `--help` (the ground truth to document); `CLAUDE.md`; `docs/README.md` (index).
- **Why:** 8 real commands have no section in the self-described complete reference; `keys` alone has 7 subcommands and `context` 6. Users (and agents — see CLAUDE.md's own stale team line) navigate by these docs.
- **Do:**
  1. **`docs/commands.md`:** add full sections (usage, subcommands, flags, one example each) for
     **`keys`, `auth`, `gates`, `audit`, `eval`, `snapshot`, `completions`, `context`**; document
     `workflow validate` + `workflow plan`; add the missing flags on existing sections
     (`cost --json/--history/--days N`, `doctor --json/--fix` — and fix the "non-destructive
     (read-only)" claim at :967, `install --yes`, `wire --channel`, `snapshot -o/--output`,
     `audit [N] --json`); rebuild the alias table (:1054-1065) from `__main__.py` post-CH-4/CH-6
     (add `telegram→wire`, `key/secret→keys`, `security→gates`, `evals→eval`, `export→snapshot`,
     `completion→completions`, `policy→policies`; fix the wrong `memory→context` row — `memory` is
     a removed-command notice, list it under a "Removed commands" note instead).
  2. **`CLAUDE.md`:** *(NOTE 2026-07-02 — already done directly against the local file after the
     CH-0..CH-6 merge, since `CLAUDE.md` is gitignored and no CH-branch's edit to it could survive
     a merge: the team bullet, test/LOC/spec counts, the D-12/D-13/no-UI-in-core conventions, the
     `_pod.py`/`_provider.py` module list, and the Manager/pod TASK_LIST section are all current.
     Skip re-doing these; spot-check instead.)*
  3. **Cross-file sweep:** `docs/README.md` index rows for anything added; grep all of `docs/` for
     `docket team`, tier names, and `profiles:` and update survivors; `docs/troubleshooting.md` +
     `QUICK-START` + `WORKFLOW-GUIDE` + `AGENT-TEAMS` spot-checked against the final surface
     (the audit found them broadly consistent — this is a verify, not a rewrite).
  4. CH-9 deleted `spec-coverage.sh` rather than rewriting it as a coverage guard (see CH-9's note)
     specifically because it would have immediately red-flagged the gaps this card exists to close
     — so there is no automated guard to run yet. Consider authoring one as part of this card's
     acceptance once the gaps below are closed, so it stays closed.
- **Out of scope:** README positioning (done in CD-9; don't churn it); specs (CH-10); new tutorials.
- **Deliverables:** complete commands.md; swept docs/; optionally a coverage guard (see item 4).
- **Acceptance gate:** [ ] every live top-level command has a commands.md section; [ ] every alias in `__main__.py` is in the table and nothing else is; [ ] zero `docket team`/tier references outside historical ROADMAP/CHANGELOG sections; [ ] doctor no longer described as read-only; [ ] suite green.
- **Size:** L *(mostly writing; split by file if two agents want it)* · **Status:** BLOCKED (needs CH-8)

---

### CH-12 — Changelog verification + cut 0.2.0

- **Depends on:** CH-4, CH-5, CH-6 landed (the removals must be real before they're released) · **Do last** · **UNBLOCKED 2026-07-02 — CH-4, CH-5, CH-6 all merged** (still reasonable to do last, after CH-7/8/10/11 so the changelog reflects the full phase).
- **Read:** `CHANGELOG.md` (the Unreleased section was restructured + backfilled with Phases 10–11 on 2026-07-02 — verify it against what actually landed, don't re-do it); `VERSION`, `pyproject.toml:7`; the Keep-a-Changelog format the file declares.
- **Why:** a versioned package whose changelog told the truth up to 0.1.0 and then went silent through its two biggest feature waves (pods, Phase 11) reads as abandoned. 0.2.0 is the natural release to carry both the features and this phase's removals.
- **Do:**
  1. Verify the backfilled Unreleased section against the tree (every claim shippable; no feature
     described that a CH-card then removed — e.g. `team` must appear under **Removed**, not
     survive in an Added bullet).
  2. Add the Phase 12 entries: Removed — `docket team` (with the pod mapping), tier names +
     `profiles:` registry key (with the auto-migration note), role-drift detection; Changed —
     store.py single-writer enforcement, ACL-wrapped openclaw calls, cli module split (internal,
     one line); Fixed — CI drift guard re-armed, docs/spec truth fixes (one line each, not a saga).
  3. Cut `## [0.2.0] - <date>` from Unreleased; bump `VERSION` + `pyproject.toml`; update the
     compare links at the bottom; tag checklist in the PR (`git tag v0.2.0` — **ask the operator
     before pushing the tag**; memory says pending GitHub release steps exist).
- **Out of scope:** publishing/announcing; the pending GitHub hygiene steps (secret scanning, branch protection — operator-owned).
- **Deliverables:** verified + completed changelog; 0.2.0 cut; version bumped; tag checklist.
- **Acceptance gate:** [ ] every 0.2.0 bullet corresponds to landed code (spot-check evidence in PR); [ ] removals are under Removed with migration notes; [ ] `docket --version` reports 0.2.0; [ ] suite green.
- **Size:** S · **Status:** BLOCKED (needs CH-4, CH-5, CH-6)

---

### CH-13 — Local test-harness hygiene (gitignored; no PR — local task)

- **Depends on:** — · **Parallel-safe with:** everything · **⚠ operator-machine task; nothing here is in the public repo**
- **Read:** audit §4 ("Rename leftovers" + "Scrubbed-repo leaks"); the **gitignored** `smoke-test/` directory (`.gitignore:36`).
- **Why:** the audit verified the public-repo scrub holds for all *tracked* files — but the gitignored smoke-test harness hardcodes an absolute developer-machine repo path (a pre-rename one at that) and a live pod name in `run.sh`, and its anonymization sed map by construction enumerates every real value it exists to hide. That's one `git add -f` (or one .gitignore edit) away from publishing the exact list the scrub protects. *(This card deliberately names no values.)*
- **Do:**
  1. `smoke-test/run.sh`: derive `ROOT` from the script's own location (`$(cd "$(dirname "$0")/.." && pwd)`) instead of the hardcoded absolute path; take the live pod name from an env var (`DOCKET_SMOKE_POD`, no default that names a real project).
  2. Move the anonymization map **outside the repo directory** (e.g. `~/.config/docket-dev/anonymize.sed`) and point the harness at it via env var with that default; keep a `smoke-test/anonymize.sed.example` with only placeholder patterns if a template helps.
  3. Sanity check: `git status --ignored` + `git grep` for the harness filenames confirm nothing sensitive is tracked; re-run the smoke test to confirm the harness still works.
- **Out of scope:** committing anything from smoke-test/ (it stays gitignored); changing what the smoke test covers.
- **Deliverables:** portable run.sh; externalized map; a line in the operator's private notes (not the repo) recording the new map location.
- **Acceptance gate:** [ ] no absolute home path or real project name in any file under smoke-test/ (the .example contains placeholders only); [ ] the harness runs green; [ ] `git status` clean, nothing new tracked.
- **Size:** S · **Status:** DONE — 2026-07-02. Real map moved to `~/.config/docket-dev/anonymize.sed` (chmod 600); `run.sh` derives `ROOT` from its own location and reads `DOCKET_SMOKE_POD`/`DOCKET_SMOKE_ANONYMIZE_SED`; `smoke-test/anonymize.sed.example` added with placeholder-only patterns.

---

## Roll-up checklist (Phase 12 definition of done — mirrors ROADMAP exit criteria)

- [x] CH-0 — stale claims fixed, dead templates gone, dangling pointers removed. *(DONE 2026-07-02)*
- [x] CH-1 — zero docket-owned JSON writes outside store.py (JSONL logs exempt per D-12); guard test in suite. *(DONE 2026-07-02 — the `core/drift.py` and manager-task-list exemptions both resolved by CH-5/CH-4's subsequent deletions)*
- [x] CH-2 — zero `openclaw` shell-outs outside the ACL; `core/` has no subprocess; guard test in suite. *(DONE 2026-07-02)*
- [x] CH-3 — zero `ui` imports in `core/`/`edges/`; guard test in suite. *(DONE 2026-07-02)*
- [x] CH-4 — `team` retired with a removed-command notice mapping to pods; one delegation system. *(DONE 2026-07-02)*
- [x] CH-5 — `core/drift.py` + its config knobs deleted; serve sweep intact. *(DONE 2026-07-02)*
- [x] CH-6 — tier/`profiles:` shims removed; one-shot registry migration ships. *(DONE 2026-07-02)*
- [ ] CH-7 — `cli/__init__.py` ≤ ~1,500 lines; goldens byte-identical through the split. *(unblocked, not started)*
- [ ] CH-8 — completions generated from (or test-locked to) the Typer registry. *(unblocked, not started)*
- [x] CH-9 — metrics/spec-coverage scripts fixed or retired; CI drift guard fails on real drift (no `|| true`). *(DONE 2026-07-02 — `spec-coverage.sh` deleted, not rewritten; see CH-11 follow-up)*
- [ ] CH-10 — every spec is a current-state contract (paths, exit codes, states, Status lines all code-true). *(unblocked, not started)*
- [ ] CH-11 — docs/commands.md covers every live command, flag, and alias; CLAUDE.md matches the tree. *(CLAUDE.md portion DONE 2026-07-02 directly, gitignored so no CH-branch could carry it; docs/commands.md gaps still open — BLOCKED on CH-8)*
- [ ] CH-12 — changelog verified through Phases 10–12; **0.2.0 cut** and version bumped. *(unblocked, not started)*
- [x] CH-13 — local harness portable; no real values on disk inside the repo dir. *(DONE 2026-07-02)*
- [x] Full suite green throughout: ruff + format + mypy strict + pytest + goldens. *(confirmed green after every merge, incl. the re-armed `scripts/metrics.py --check` drift guard)*

**Progress note (2026-07-02):** 8 of 14 cards landed via parallel worktree-isolated agents (CH-0,
CH-1, CH-2, CH-3, CH-4, CH-5, CH-6, CH-9), merged into `develop` one at a time with the full gate
re-run after each merge. Two real merge conflicts occurred (`cli/__init__.py` and
`core/provider.py` on CH-4; `core/models_policy.py`'s store-import alias on CH-6) and were resolved
by hand — see commits `4ac3f7c` and `d9d8f57`. `CLAUDE.md` is gitignored and untracked, so it was
synced directly on the local checkout after all merges rather than through any branch. Remaining:
CH-7, CH-8, CH-10, CH-11, CH-12 — all now unblocked except CH-11 (needs CH-8).

**Explicitly NOT in this phase (audited keeps — see ROADMAP Phase 12):** the serve read API +
`/metrics` + scheduled/webhook dispatch (CD-6/8), Lobster validate/plan (CD-7), audit log, approval
store, opt-in gates, `resources.py`, dual-source sync, the ACL, and the policy/models_policy/provider
trio. The gates default-on flip stays a separate post-phase decision.
