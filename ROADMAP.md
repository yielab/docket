# docket Roadmap

This roadmap takes docket from a polished single-user CLI to a hardened, portable, and
operable tool — sequenced so that each phase is independently shippable and raises the bar
on **security → reliability → portability → operability → product**.

Status legend: ✅ done · 🚧 in progress · 🗓️ planned

The numbered phases are ordered by leverage. Earlier phases unblock later ones.

---

## Tracked decisions (not yet scheduled)

- 🗓️ **Project rename (deferred).** "docket" collides with Ruby Docket, is a generic word, and is
  hard to search. The decision is to **keep "docket" for now but anchor it to "OpenClaw" on every
  public surface** (README first line, repo description, social preview), so a later rename to a
  searchable, namespace-clean name (candidates: `clawfleet`, `docketctl`, `openclaw-docket`) stays
  low-cost. Revisit before any wide public launch. Touch points a rename must update: binary
  name, `install.sh`/`uninstall.sh` paths, Homebrew `Formula/`, docs, and the metrics script.
- 🗓️ **OpenClaw version-pinned CI.** Install the latest OpenClaw weekly, run the integration
  suite, and open an auto-issue on schema break. Until then [COMPATIBILITY.md](COMPATIBILITY.md)
  reflects manual verification.

---

## Phase 0 — Security hardening (must precede a public "use this" recommendation) — ✅ complete

> Agents execute commands and docket manages provider keys. Security is the difference between
> "personal experiment" and "tool I'd run on a real machine."
>
> **Status: complete.** Every item below is shipped and tested. Two capabilities (exec-approval
> enforcement and Docker isolation) ship **opt-in** by deliberate design — see the default-on
> note under tool-approval gates for why on-by-default waits on per-agent headless routing.

- ✅ **Eliminate code-injection in `keys.sh`** — all secret values now pass through the
  environment/argv into Python, never interpolated into source. Covered by an injection
  regression test (P5-3) that feeds a hostile value and asserts it is stored as data.
- 🚧 **Tool-approval gates** — implement [`specs/functional/security-gates.spec.md`](specs/functional/security-gates.spec.md)
  on the daemon's native exec-approval + audit primitives.
  - ✅ **Gate status is visible** — `docket doctor` reports the exec-approval policy
    (`security`/`ask`/`askFallback`, per-agent allowlist counts) and an `openclaw security audit`
    summary with any critical findings.
  - ✅ **State files hardened** — `docket install` and `docket doctor` ensure `openclaw.json` /
    `secrets.json` are `600` (a writable config lets another local user rewrite tool/auth policy).
  - ✅ **Enforcement (opt-in)** — `docket gates enable` (or `docket install --gates`) writes
    conservative exec-approval defaults (`security: allowlist`, `ask: on-miss`,
    `askFallback: deny`) and seeds each agent a curated safe-bin allowlist, so dangerous /
    non-allowlisted commands (`rm`, `dd`, `docker`, …) prompt and — absent an approver — are
    denied (fail-closed). Idempotent, non-clobbering, reversible (`docket gates disable`).
    Opt-in until approval routing lands so fail-closed is answerable. Test P5-7.
  - ✅ **Approval routing** — `docket gates enable` also writes `approvals.exec`
    (`enabled, mode: session`) so each agent's gated prompts reach its own channel, answerable
    with `/approve <id> allow-once|deny`; `session` mode avoids the cross-agent leakage a shared
    global target list would cause. Surfaced in `docket doctor` / `docket gates status`. Test P5-8.
  - ✅ **Workspace isolation (opt-in)** — `docket gates isolate on` (Docker-gated) sets
    `agents.defaults.sandbox` (`mode: non-main, scope: agent, workspaceAccess: rw`) so non-main
    session tool execution runs in a per-agent container with only the workspace mounted.
    Reversible (`isolate off`); surfaced in doctor/status. Test P5-9.
  - 🗓️ **Default-on flip (deliberately deferred)** — enforcement and isolation ship **opt-in** by
    design: `session`-mode routing only answers prompts during an interactive session, so a
    headless/cron-triggered agent could be denied with no approver. Flipping `docket install` to
    on-by-default waits on explicit per-agent `targets` for headless approval delivery (needs the
    daemon to express per-agent routing without a shared global target list). Tracked, not blocking.
- ✅ **Scoped secret distribution** — `docket keys` now syncs only the provider key an agent's
  configured model needs (an `anthropic/…` agent gets `ANTHROPIC_API_KEY`, not every key);
  non-provider/custom secrets are still shared. Writes are atomic and preserve user-authored
  `.env` lines. Covered by a least-privilege regression test (P5-4).
- ✅ **Key rotation & age hygiene** — `docket keys rotate <KEY>` replaces an existing
  credential (and re-syncs scoped), lifecycle timestamps are tracked in a 0600
  `secrets.meta.json` sidecar, and `docket doctor` flags keys older than the rotation
  threshold (default 90 days, `DOCKET_KEY_MAX_AGE_DAYS`). Covered by regression test P5-5.
- ✅ **Secrets backend abstraction** — `docket keys` now goes through a pluggable backend
  (`lib/helpers/secrets.sh`): `file` (default, 0600 `secrets.json`) or `keyring`
  (`DOCKET_SECRETS_BACKEND=keyring`, libsecret) where values live in the OS keyring and
  `secrets.json` keeps a names-only index (no plaintext at rest). Values never cross a process
  boundary as argv; `docket doctor` reports the active backend and warns on plaintext-at-rest.
  File-backend behaviour is byte-equivalent to before; keyring round-trip validated (P5-10).
  macOS `security` / Vault backends are a documented follow-up.

## Phase 1 — Write-safety & reliability — ✅ complete

> One crash mid-write should never corrupt an agent or the shared daemon config.

- ✅ **Atomic writes everywhere** — `json_atomic_write` (validate stdin → rolling `.bak` →
  tmp → `os.replace` → 0600) now backs `meta_set`, `upsert_binding`, `remove_binding`,
  `remove_agent_config`, and `oc_set`. A failed producer can no longer truncate the target
  (invalid/empty JSON is refused, original left intact). Test P6-1.
- ✅ **Cross-process locking** — `with_docket_lock` takes an exclusive `flock` on
  `$OPENCLAW_DIR/.docket.lock` around each leaf writer (spanning read-modify-write), so two
  concurrent `docket` invocations can't lose an update. Only leaf writers are wrapped, so the
  lock never nests/deadlocks; degrades to unlocked if `flock` is unavailable (e.g. macOS).
- ✅ **Loud-on-corruption reads** — `meta_get` / `oc_get` now warn clearly to stderr when a
  state file exists but won't parse (instead of silently returning the default), while still
  returning the default so the command stays alive.

## Phase 2 — Release engineering & CI rigor — ✅ complete

> Cheap, high-signal credibility — both for adoption and as an engineering artifact.

- ✅ **Versioning** — a `VERSION` file, `docket --version` / `-V`, and a `CHANGELOG.md`
  (Keep a Changelog). The first cut tag is `v0.1.0` (test P6-2 keeps them in sync).
- ✅ **Release workflow** — `.github/workflows/release.yml` builds a checksummed tarball and
  cuts a GitHub Release on a `v*` tag (guards that the tag matches `VERSION`; uses the
  pre-installed `gh` CLI, no third-party action).
- ✅ **Homebrew tap** — `Formula/docket-cli.rb` in the repo root; users install via
  `brew tap yielab/docket-cli https://github.com/yielab/docket && brew install docket-cli`.
  `scripts/update-homebrew-sha.sh` computes + patches the SHA256 before each release tag.
  `install.sh` also upgraded: portable `sed -i`, curl one-liner support, `--prefix` flag.
  🗓️ `nix` / `apt` remain stretch.
- ✅ **Stronger CI** — spec validation is now **blocking**, a **shellcheck** gate (`-S error`,
  verified clean) runs on every push, and unit tests run under a throwaway `HOME`. Integration
  tests need the `openclaw` daemon + `systemctl`, so they stay local (documented in the workflow).
- ✅ **Bash/OS matrix** — macOS runner (brewed Bash 4+, informational gate) shipped in Phase 3.

## Phase 3 — Portability — ✅ complete

> macOS is a large share of the dev-tool audience; today docket is Linux-only.

- ✅ **Service abstraction** — `service_ctl` / `service_manager` / `service_hint` (service.sh)
  now own every gateway call and user-facing hint; the ~20 scattered `systemctl --user`
  references collapsed to one place. On systemd, behaviour is unchanged; off systemd it degrades
  cleanly (no crash, platform-appropriate guidance). Overridable via `DOCKET_SERVICE_MANAGER`. P7-1.
- ✅ **Remove GNU-isms** — `find -printf` → `newest_file`; GNU `sed -i` → `portable_sed_i`;
  `readlink -f` bootstrap → a portable symlink-follow loop; portable `file_mtime`/`file_size`/
  `file_mode` wrappers (GNU vs BSD `stat`). Bash < 4 now fails fast with a clear message. P7-1.
- ✅ **CI matrix** — macOS job added (`.github/workflows/ci.yml`): installs Bash 4+ via brew,
  runs the hermetic unit suite with a throwaway `$HOME`. Ships as `continue-on-error: true`
  (informational) until CI confirms it's reliably green; promote by removing that flag.

## Phase 4 — Operability & observability — ✅ complete

> What "enterprise-grade" actually means day to day.

- ✅ **Audit log** — every mutating op (`keys.add/remove/rotate`, `gates.enable/disable/isolate`,
  `profile.model/budget`, `scope.set/reset`, `agent.add/delete`) appends a who/when/what JSON line
  to `$OPENCLAW_DIR/audit.log` (0600); secret values are never logged. View with `docket audit [N]`
  / `docket audit --json` (`DOCKET_NO_AUDIT=1` opts out). Test P8-1.
- ✅ **`--json` on read commands** — `docket list --json`, `docket cost --json`, `docket info --json`,
  and `docket doctor --json` all ship. `doctor --json` emits a structured health object:
  `{healthy, issues, checks:{openclaw, python3, gateway, agents, drift, budget, runaway,
  keyHygiene, securityGates, templateDrift, …}}`. P8-2 / P9-2 / P10-2 / P8-3.
- ✅ **Performance: incremental cost index** — `_aggregate_cost` caches per-session-file totals
  in `.cost-index.json` keyed by (mtime, size); unchanged files are read from cache, so `cost`/
  budget checks are O(changed files), not O(all history). Self-healing (stale entries dropped),
  `DOCKET_NO_COST_INDEX=1` forces full recompute. P9-1.
- ✅ **Batch human `list`/`doctor` reads** — `_list_meta_batch` + `_list_spec_batch` do a single
  Python pass over all agent metas + config per `docket list` invocation (was 8N+9 spawns for N
  agents, now 2). `_doctor_batch_cost` replaces 2N `meta_get`+`_aggregate_cost` spawns in the
  budget/runaway loops with one pass; arithmetic via `awk` instead of inline `python3 -c`.
- ✅ **Metrics** — `docket serve` now exposes `/metrics` (Prometheus: `docket_agents_total`,
  `docket_agent_cost_usd`, `docket_agent_turns_total`, `docket_cost_usd_total`, `docket_gateway_up`)
  and `/health` alongside `/status.json`, refreshed on the same interval. P10-1.

## Phase 5 — MLOps depth (the differentiating story)

> Turn the existing cost/routing primitives into a real, data-driven LLMOps control plane.

- ✅ **Real eval harness** — six specialist-role evals (programmer, reviewer, tester,
  knowledge, security, manager), each with two modes: a fast structural check (always, no
  LLM, verifies the SOUL.md contract) and a live golden-task check (`DOCKET_EVAL_LIVE=1`,
  invokes `openclaw agent --local --json`, records pass/fail + cost + tokens to
  `tests/evals/results/YYYY-MM-DD.jsonl`). `docket eval [--live] [--tier <t>] [--role <r>]
  [--recommend]` drives the harness; `docket eval --recommend` and `docket doctor` (section 16)
  surface per-role tier suggestions from stored results. Infrastructure failures (quota,
  auth, timeout) are SKIP, not FAIL — evals stay non-blocking in CI.
- ✅ **Cost history** — `docket cost --history [id] [--days N] [--json]` shows a daily per-agent
  cost/turn/token series (bucketed by session timestamp), cached in `.cost-history.json` by the
  same (mtime, size) signatures as the cost index, with a simple regression flag (a day >2× its
  trailing 3-day average). P11-1. (Latency isn't in the session schema — a `latency_ms` field on
  OpenClaw session events would let this extend to latency without changing the docket side.)
- ✅ **Template/prompt versioning** — `_create_workspace` stamps the current
  `TEMPLATE_VERSION` (config.sh) into each agent's `.docket-meta.json` on `docket add` and
  `docket maintain rebuild`; `docket doctor` flags agents whose stamp is older than (or absent
  versus) the current template and points at `docket maintain <id> rebuild` to regenerate the
  prompts. Bumping the integer after any material template edit makes the drift visible fleet-wide. P11-2.
- ✅ **Declarative provisioning** — `docket add --from <agents.yaml|agents.json>` provisions a
  whole fleet from a spec file (JSON always; YAML when PyYAML is present). A document may be a
  single agent mapping, a list, or `{agents: [...]}`; only `name` is required and the rest reuse
  the interactive defaults. Idempotent (existing agents skipped, so a fleet file is safe to
  re-apply and to keep in git as the source of truth) and restarts the gateway at most once.
  Shares one `_provision_agent` core with interactive `docket add`. Example specs in
  `examples/configs/`. P11-3.

## Phase 6 — Model & provider agnosticism — ✅ complete

> Removed the hard Anthropic/Claude API dependency. docket now accepts any provider/model string
> the OpenClaw daemon supports, with a user-editable registry overlay, five provider presets
> (including an OpenRouter free-tier option), honest `n/a` cost reporting for unpriced models,
> scoped key distribution for every provider, and fully tier-neutral agent templates and docs.

- ✅ **Verify daemon provider surface (MA-1)** — 22 providers, 746 models; `provider/model` ID
  format confirmed; no local/Ollama support in daemon (OpenRouter free-tier is the free path).
- ✅ **Data-driven model registry (MA-2)** — `VALID_MODELS` whitelist replaced with regex +
  user overlay at `~/.openclaw/docket-models.json`; unknown-but-valid IDs accepted with warning.
- ✅ **`docket models` command (MA-3)** — list/set tier→model mapping; shows price, provider, source.
- ✅ **Provider presets (MA-4)** — `anthropic` (default), `openai`, `google`, `openrouter`,
  `openrouter-free`; `docket models preset <name>` switches all tiers at once.
- ✅ **Cost honesty (MA-5)** — unpriced models show `n/a`; budget enforcement skipped when unpriced.
- ✅ **Provider-agnostic key plumbing (MA-6)** — scoped sync + `docket doctor` section 13b
  checks provider key coverage for all agents; local providers don't warn about missing keys.
- ✅ **Neutralize Claude-isms in templates (MA-7)** — all agent templates use economy/standard/
  premium tier language; `TEMPLATE_VERSION` bumped to 2 for fleet-wide drift detection.
- ✅ **Docs & help truth pass (MA-8)** — README, `docs/`, `CLAUDE.md`, and `help.sh` describe
  the multi-provider position with `docket models preset` examples and free-tier callout.

## Phase 6b — Tier-less role→model policy — ✅ complete

> Replaced the economy/standard/premium tier ladder with a **role→model policy**: every agent
> role (manager, programmer, reviewer, tester, knowledge, security + project types repo/task)
> maps to the cheapest adequate model, with the WHY visible in `docket models`. Agents record
> intent (`modelSource: policy|pinned`); policy and preset changes re-resolve every
> policy-following agent automatically, so fleet-wide drift is impossible by construction.

- ✅ **Role→model policy map (MA-9)** — `ROLE_MODELS`/`ROLE_WHY` built-ins + `roles:` registry
  overlay; install/add resolve through the policy (no hardcoded model IDs left); tier names
  survive only as deprecated aliases over internal rank anchors (fallback chain preserved).
- ✅ **Policy-following agents + auto re-resolve (MA-10)** — `modelSource` intent in
  `.docket-meta.json` with safe inference for pre-existing agents (divergent model → pinned);
  `docket models set/preset/reset` re-resolve policy followers with one gateway restart and
  audit entries; `docket profile <id> <model|default>` pins/unpins one agent.
- ✅ **Specialists join the meta system (MA-11)** — specialists get `.docket-meta.json`
  (`kind: specialist`, `role`) at install, backfilled by `docket doctor`; `docket list` shows
  model + source + role rationale for the whole taxonomy; `docket delete` guards specialists.
- 🗓️ **Deferred:** `docket models optimize` (eval × cost-history right-sizing per role — needs
  usage history on the new policy first) and per-task dynamic routing (blocked on a daemon
  per-session model-override spike; prompt-level SMART-ROUTING stays dead).

## Phase 7 — Product & community

- ✅ **Full manager delegation** — task queue promoted to an enforced state machine with
  locking and schema validation. States: `pending → in_progress → done | cancelled`;
  `pending → cancelled` also valid. Atomic writes via `with_docket_lock` + `json_atomic_write`.
  New subcommands: `docket team start <id>`, `docket team cancel <id>`.
  Priority validation (high/normal/low only), 500-char description limit, timestamps
  (`startedAt`, `completedAt`) recorded on transitions. `docket team queue --all` shows
  completed/cancelled history.
- ✅ **Issue/PR templates** — `.github/ISSUE_TEMPLATE/` (bug report + feature request, both
  structured YAML forms) and `.github/PULL_REQUEST_TEMPLATE/` with test-plan checklist
  and project conventions (atomic writes, `--json` on reads, tier-neutral language).
- 🗓️ Eval-results page and a short demo (asciinema).

---

### Near-term (remaining open work)

**Phases 0–7 are complete.** All remaining items are explicitly deferred or stretch goals:

1. 🗓️ **Phase 0 remnant** — default-on gates flip (waiting on per-agent headless routing in daemon).
2. 🗓️ **Phase 2 stretch** — nix / apt packaging (Homebrew tap done).
3. 🗓️ **Phase 3 stretch** — promote macOS CI job from informational to required gate (remove `continue-on-error`).
4. 🗓️ **Phase 7 remnant** — eval-results page, asciinema demo.

A deeper internal audit with severities and effort estimates lives in
`internal-docs/ARCHITECTURE-AUDIT.md` (not published).
