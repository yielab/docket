# rack Roadmap

This roadmap takes rack from a polished single-user CLI to a hardened, portable, and
operable tool — sequenced so that each phase is independently shippable and raises the bar
on **security → reliability → portability → operability → product**.

Status legend: ✅ done · 🚧 in progress · 🗓️ planned

The numbered phases are ordered by leverage. Earlier phases unblock later ones.

---

## Phase 0 — Security hardening (must precede a public "use this" recommendation) — ✅ complete

> Agents execute commands and rack manages provider keys. Security is the difference between
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
  - ✅ **Gate status is visible** — `rack doctor` reports the exec-approval policy
    (`security`/`ask`/`askFallback`, per-agent allowlist counts) and an `openclaw security audit`
    summary with any critical findings.
  - ✅ **State files hardened** — `rack install` and `rack doctor` ensure `openclaw.json` /
    `secrets.json` are `600` (a writable config lets another local user rewrite tool/auth policy).
  - ✅ **Enforcement (opt-in)** — `rack gates enable` (or `rack install --gates`) writes
    conservative exec-approval defaults (`security: allowlist`, `ask: on-miss`,
    `askFallback: deny`) and seeds each agent a curated safe-bin allowlist, so dangerous /
    non-allowlisted commands (`rm`, `dd`, `docker`, …) prompt and — absent an approver — are
    denied (fail-closed). Idempotent, non-clobbering, reversible (`rack gates disable`).
    Opt-in until approval routing lands so fail-closed is answerable. Test P5-7.
  - ✅ **Approval routing** — `rack gates enable` also writes `approvals.exec`
    (`enabled, mode: session`) so each agent's gated prompts reach its own channel, answerable
    with `/approve <id> allow-once|deny`; `session` mode avoids the cross-agent leakage a shared
    global target list would cause. Surfaced in `rack doctor` / `rack gates status`. Test P5-8.
  - ✅ **Workspace isolation (opt-in)** — `rack gates isolate on` (Docker-gated) sets
    `agents.defaults.sandbox` (`mode: non-main, scope: agent, workspaceAccess: rw`) so non-main
    session tool execution runs in a per-agent container with only the workspace mounted.
    Reversible (`isolate off`); surfaced in doctor/status. Test P5-9.
  - 🗓️ **Default-on flip (deliberately deferred)** — enforcement and isolation ship **opt-in** by
    design: `session`-mode routing only answers prompts during an interactive session, so a
    headless/cron-triggered agent could be denied with no approver. Flipping `rack install` to
    on-by-default waits on explicit per-agent `targets` for headless approval delivery (needs the
    daemon to express per-agent routing without a shared global target list). Tracked, not blocking.
- ✅ **Scoped secret distribution** — `rack keys` now syncs only the provider key an agent's
  configured model needs (an `anthropic/…` agent gets `ANTHROPIC_API_KEY`, not every key);
  non-provider/custom secrets are still shared. Writes are atomic and preserve user-authored
  `.env` lines. Covered by a least-privilege regression test (P5-4).
- ✅ **Key rotation & age hygiene** — `rack keys rotate <KEY>` replaces an existing
  credential (and re-syncs scoped), lifecycle timestamps are tracked in a 0600
  `secrets.meta.json` sidecar, and `rack doctor` flags keys older than the rotation
  threshold (default 90 days, `RACK_KEY_MAX_AGE_DAYS`). Covered by regression test P5-5.
- ✅ **Secrets backend abstraction** — `rack keys` now goes through a pluggable backend
  (`lib/helpers/secrets.sh`): `file` (default, 0600 `secrets.json`) or `keyring`
  (`RACK_SECRETS_BACKEND=keyring`, libsecret) where values live in the OS keyring and
  `secrets.json` keeps a names-only index (no plaintext at rest). Values never cross a process
  boundary as argv; `rack doctor` reports the active backend and warns on plaintext-at-rest.
  File-backend behaviour is byte-equivalent to before; keyring round-trip validated (P5-10).
  macOS `security` / Vault backends are a documented follow-up.

## Phase 1 — Write-safety & reliability — ✅ complete

> One crash mid-write should never corrupt an agent or the shared daemon config.

- ✅ **Atomic writes everywhere** — `json_atomic_write` (validate stdin → rolling `.bak` →
  tmp → `os.replace` → 0600) now backs `meta_set`, `upsert_binding`, `remove_binding`,
  `remove_agent_config`, and `oc_set`. A failed producer can no longer truncate the target
  (invalid/empty JSON is refused, original left intact). Test P6-1.
- ✅ **Cross-process locking** — `with_rack_lock` takes an exclusive `flock` on
  `$OPENCLAW_DIR/.rack.lock` around each leaf writer (spanning read-modify-write), so two
  concurrent `rack` invocations can't lose an update. Only leaf writers are wrapped, so the
  lock never nests/deadlocks; degrades to unlocked if `flock` is unavailable (e.g. macOS).
- ✅ **Loud-on-corruption reads** — `meta_get` / `oc_get` now warn clearly to stderr when a
  state file exists but won't parse (instead of silently returning the default), while still
  returning the default so the command stays alive.

## Phase 2 — Release engineering & CI rigor — 🚧 mostly complete

> Cheap, high-signal credibility — both for adoption and as an engineering artifact.

- ✅ **Versioning** — a `VERSION` file, `rack --version` / `-V`, and a `CHANGELOG.md`
  (Keep a Changelog). The first cut tag is `v0.1.0` (test P6-2 keeps them in sync).
- ✅ **Release workflow** — `.github/workflows/release.yml` builds a checksummed tarball and
  cuts a GitHub Release on a `v*` tag (guards that the tag matches `VERSION`; uses the
  pre-installed `gh` CLI, no third-party action). 🗓️ Homebrew tap / `nix` / `apt` remain stretch.
- ✅ **Stronger CI** — spec validation is now **blocking**, a **shellcheck** gate (`-S error`,
  verified clean) runs on every push, and unit tests run under a throwaway `HOME`. Integration
  tests need the `openclaw` daemon + `systemctl`, so they stay local (documented in the workflow).
- 🗓️ **Bash/OS matrix** — Bash 4.x/5.x + a macOS runner; folded into Phase 3 (portability),
  where the `service_ctl` abstraction and GNU-ism removal make a green macOS run achievable.

## Phase 3 — Portability — 🚧 mostly complete

> macOS is a large share of the dev-tool audience; today rack is Linux-only.

- ✅ **Service abstraction** — `service_ctl` / `service_manager` / `service_hint` (service.sh)
  now own every gateway call and user-facing hint; the ~20 scattered `systemctl --user`
  references collapsed to one place. On systemd, behaviour is unchanged; off systemd it degrades
  cleanly (no crash, platform-appropriate guidance). Overridable via `RACK_SERVICE_MANAGER`. P7-1.
- ✅ **Remove GNU-isms** — `find -printf` → `newest_file`; GNU `sed -i` → `portable_sed_i`;
  `readlink -f` bootstrap → a portable symlink-follow loop; portable `file_mtime`/`file_size`/
  `file_mode` wrappers (GNU vs BSD `stat`). Bash < 4 now fails fast with a clear message. P7-1.
- 🚧 **CI matrix** — a macOS job runs the unit suite under brewed Bash 4+ (informational /
  `continue-on-error` until reliably green); promote to a required gate once proven. A real
  end-to-end macOS run also needs the OpenClaw daemon's own launchd support.

## Phase 4 — Operability & observability — 🚧 mostly complete

> What "enterprise-grade" actually means day to day.

- ✅ **Audit log** — every mutating op (`keys.add/remove/rotate`, `gates.enable/disable/isolate`,
  `profile.model/budget`, `scope.set/reset`, `agent.add/delete`) appends a who/when/what JSON line
  to `$OPENCLAW_DIR/audit.log` (0600); secret values are never logged. View with `rack audit [N]`
  / `rack audit --json` (`RACK_NO_AUDIT=1` opts out). Test P8-1.
- 🚧 **`--json` on read commands** — `rack list --json`, `rack cost --json`, and
  `rack info <id> --json` ship (batched Python passes). Only `doctor --json` remains (lower value:
  `snapshot` already emits machine system state). P8-2 / P9-2 / P10-2.
- ✅ **Performance: incremental cost index** — `_aggregate_cost` caches per-session-file totals
  in `.cost-index.json` keyed by (mtime, size); unchanged files are read from cache, so `cost`/
  budget checks are O(changed files), not O(all history). Self-healing (stale entries dropped),
  `RACK_NO_COST_INDEX=1` forces full recompute. P9-1. 🗓️ remaining: batch the human
  `list` / `doctor` per-field reads the same way `list --json` already does.
- ✅ **Metrics** — `rack serve` now exposes `/metrics` (Prometheus: `rack_agents_total`,
  `rack_agent_cost_usd`, `rack_agent_turns_total`, `rack_cost_usd_total`, `rack_gateway_up`)
  and `/health` alongside `/status.json`, refreshed on the same interval. P10-1.

## Phase 5 — MLOps depth (the differentiating story)

> Turn the existing cost/routing primitives into a real, data-driven LLMOps control plane.

- ✅ **Real eval harness** — six specialist-role evals (programmer, reviewer, tester,
  knowledge, security, manager), each with two modes: a fast structural check (always, no
  LLM, verifies the SOUL.md contract) and a live golden-task check (`RACK_EVAL_LIVE=1`,
  invokes `openclaw agent --local --json`, records pass/fail + cost + tokens to
  `tests/evals/results/YYYY-MM-DD.jsonl`). `rack eval [--live] [--tier <t>] [--role <r>]
  [--recommend]` drives the harness; `rack eval --recommend` and `rack doctor` (section 16)
  surface per-role tier suggestions from stored results. Infrastructure failures (quota,
  auth, timeout) are SKIP, not FAIL — evals stay non-blocking in CI.
- ✅ **Cost history** — `rack cost --history [id] [--days N] [--json]` shows a daily per-agent
  cost/turn/token series (bucketed by session timestamp), cached in `.cost-history.json` by the
  same (mtime, size) signatures as the cost index, with a simple regression flag (a day >2× its
  trailing 3-day average). P11-1. (Latency isn't in the session schema — a `latency_ms` field on
  OpenClaw session events would let this extend to latency without changing the rack side.)
- ✅ **Template/prompt versioning** — `_create_workspace` stamps the current
  `TEMPLATE_VERSION` (config.sh) into each agent's `.rack-meta.json` on `rack add` and
  `rack maintain rebuild`; `rack doctor` flags agents whose stamp is older than (or absent
  versus) the current template and points at `rack maintain <id> rebuild` to regenerate the
  prompts. Bumping the integer after any material template edit makes the drift visible fleet-wide. P11-2.
- ✅ **Declarative provisioning** — `rack add --from <agents.yaml|agents.json>` provisions a
  whole fleet from a spec file (JSON always; YAML when PyYAML is present). A document may be a
  single agent mapping, a list, or `{agents: [...]}`; only `name` is required and the rest reuse
  the interactive defaults. Idempotent (existing agents skipped, so a fleet file is safe to
  re-apply and to keep in git as the source of truth) and restarts the gateway at most once.
  Shares one `_provision_agent` core with interactive `rack add`. Example specs in
  `examples/configs/`. P11-3.

## Phase 6 — Model & provider agnosticism — 🔴 CRITICAL (jumps the queue)

> **Risk being addressed:** rack today has a hard dependency on the Claude API. The model
> whitelist in `lib/helpers/models.sh` **rejects** any non-Anthropic model, the tier →
> model mapping and pricing table in `lib/core/config.sh` are Anthropic-only, and the
> README/templates/help text assume Claude everywhere. A pricing change, outage, regional
> block, or ToS change at a single provider breaks every deployment. rack must be
> **model-agnostic**: any provider the OpenClaw daemon supports — local (free: Ollama,
> llama.cpp, LM Studio) or remote (paid: Anthropic, OpenAI, Google; mixed: OpenRouter) —
> must be first-class, and the chosen model must be **explicit and visible** in every
> command, instruction template, and doc.
>
> Detailed executable tasks: `internal-docs/IMPLEMENTATION-PLAN.md` §PHASE 6 (MA-1 … MA-8).

- 🗓️ **Verify daemon provider surface (MA-1)** — confirm which providers/model-ID formats the
  OpenClaw daemon accepts (`provider/model` strings, local endpoints, base-URL overrides) and
  document the contract rack must target. Everything below builds on this.
- 🗓️ **Data-driven model registry (MA-2)** — replace the hardcoded `VALID_MODELS` whitelist,
  `MODEL_PROFILES`, and `MODEL_PRICING` with a registry file (built-in defaults + user
  override). Unknown-but-well-formed `provider/model` IDs are accepted with a warning, never
  rejected — the daemon is the validator of record.
- 🗓️ **`rack models` command (MA-3)** — list/set the tier→model mapping and default model;
  show provider, price (or **free/local**), and source of each mapping. No more silent defaults.
- 🗓️ **Provider presets incl. free/local (MA-4)** — one-command switch of the whole tier
  mapping: `anthropic` (current default), `openai`, `google`, `openrouter`, `local` (Ollama —
  free, no API key). Free vs paid clearly labeled at selection time.
- 🗓️ **Cost honesty for unknown/local models (MA-5)** — unpriced models report cost as
  `n/a (no pricing data)` instead of $0.00; local models report `$0 (local)`.
- 🗓️ **Provider-agnostic key plumbing (MA-6)** — extend the scoped-key sync + doctor checks to
  all registry providers; local providers require no key and must not warn about one.
- 🗓️ **Neutralize Claude-isms in templates (MA-7)** — agent prompt templates speak in **tiers**
  (economy/standard/premium), not "haiku/sonnet/opus"; provider console URLs become
  provider-resolved; `TEMPLATE_VERSION` bump makes the fleet drift visible.
- 🗓️ **Docs & help truth pass (MA-8)** — README, `docs/`, `help.sh`, and CLAUDE.md state the
  model-agnostic position up front: default models, how to switch, free options, paid options.

## Phase 7 — Product & community

- 🗓️ **Full manager delegation** — promote the task queue to an enforced state machine with
  locking and schema validation.
- 🗓️ Issue/PR templates, a richer eval-results page, and a short demo (asciinema).

---

### Near-term (next four, concrete)

1. 🔴 **Phase 6 — model & provider agnosticism (CRITICAL, do first)** — remove the hard
   Claude-API dependency; registry + `rack models` + local/free presets + honest docs
   (executable tasks: `internal-docs/IMPLEMENTATION-PLAN.md` §PHASE 6).
2. ✅ Phase 0 — security hardening (injection, scoped secrets, rotation/age, gates, backends).
3. ✅ Phase 1 — `json_atomic_write` + `flock` + loud reads (P6-1) — corruption/race class removed.
4. 🗓️ Phase 2 — CI: Bash/OS matrix; versioning is done (`v0.1.0` tagged).

A deeper internal audit with severities and effort estimates lives in
`internal-docs/ARCHITECTURE-AUDIT.md` (not published).
