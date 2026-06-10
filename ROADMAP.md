# rack Roadmap

This roadmap takes rack from a polished single-user CLI to a hardened, portable, and
operable tool — sequenced so that each phase is independently shippable and raises the bar
on **security → reliability → portability → operability → product**.

Status legend: ✅ done · 🚧 in progress · 🗓️ planned

The numbered phases are ordered by leverage. Earlier phases unblock later ones.

---

## Phase 0 — Security hardening (must precede a public "use this" recommendation)

> Agents execute commands and rack manages provider keys. Security is the difference between
> "personal experiment" and "tool I'd run on a real machine."

- ✅ **Eliminate code-injection in `keys.sh`** — all secret values now pass through the
  environment/argv into Python, never interpolated into source. Covered by an injection
  regression test (P5-3) that feeds a hostile value and asserts it is stored as data.
- 🗓️ **Enforced tool-approval gates** — implement [`specs/functional/security-gates.spec.md`](specs/functional/security-gates.spec.md):
  gate dangerous operations (`rm`, `git push`, `docker stop`) behind approval, with an audit
  trail, and have `rack install` apply them by default.
- ✅ **Scoped secret distribution** — `rack keys` now syncs only the provider key an agent's
  configured model needs (an `anthropic/…` agent gets `ANTHROPIC_API_KEY`, not every key);
  non-provider/custom secrets are still shared. Writes are atomic and preserve user-authored
  `.env` lines. Covered by a least-privilege regression test (P5-4).
- ✅ **Key rotation & age hygiene** — `rack keys rotate <KEY>` replaces an existing
  credential (and re-syncs scoped), lifecycle timestamps are tracked in a 0600
  `secrets.meta.json` sidecar, and `rack doctor` flags keys older than the rotation
  threshold (default 90 days, `RACK_KEY_MAX_AGE_DAYS`). Covered by regression test P5-5.
- 🗓️ **Secrets backend abstraction** — keep the 0600 JSON file as the default, but allow a
  pluggable backend (OS keychain / `libsecret` / Vault) so keys aren't plaintext at rest.

## Phase 1 — Write-safety & reliability

> One crash mid-write should never corrupt an agent or the shared daemon config.

- 🗓️ **Atomic writes everywhere** — extract the proven `oc_set` pattern (tmp → validate →
  `os.replace`, restore-on-corruption) into one `json_write_atomic` helper and route
  `meta_set`, `upsert_binding`, `remove_binding`, and `remove_agent_config` through it.
- 🗓️ **Cross-process locking** — a single `flock` on `~/.openclaw/.rack.lock` around every
  mutating command, so two concurrent `rack` invocations can't lose updates.
- 🗓️ **Loud-on-corruption reads** — replace silent `|| echo "$default"` fallbacks with a
  policy that warns clearly when state is unreadable, even when a default keeps the command
  alive.

## Phase 2 — Release engineering & CI rigor

> Cheap, high-signal credibility — both for adoption and as an engineering artifact.

- 🗓️ **Versioning** — a `VERSION` file, a `rack --version` flag, semver git tags, and a
  `CHANGELOG.md`.
- 🗓️ **Release workflow** — tagged GitHub Releases with a checksummed tarball; a Homebrew tap
  and/or `nix`/`apt` path as a stretch.
- 🗓️ **Stronger CI** — make spec validation blocking (all specs already pass), run the
  integration suite in CI (now hermetic-capable), and add a **shellcheck** gate.
- 🗓️ **Bash/OS matrix** — test against Bash 4.x and 5.x; add a macOS runner.

## Phase 3 — Portability

> macOS is a large share of the dev-tool audience; today rack is Linux-only.

- 🗓️ **Service abstraction** — a `service_ctl` layer over the 11 `systemctl --user` call
  sites (systemd | launchd | foreground), so macOS and WSL work.
- 🗓️ **Remove GNU-isms** — replace `find -printf` and similar GNU-only flags with portable
  equivalents; fail with a clear message on Bash < 4.

## Phase 4 — Operability & observability

> What "enterprise-grade" actually means day to day.

- 🗓️ **`--json` on every read command** (not just `snapshot`) for scriptable, stable output.
- 🗓️ **Audit log** of mutating operations (who/when/what changed an agent, binding, budget).
- 🗓️ **Performance** — batch agent/field reads into single Python calls (kills the
  per-field interpreter-spawn cost on `list`/`doctor`); add an incremental cost index keyed
  by session-file mtime so `cost` is O(changed files), not O(all history).
- 🗓️ **Metrics** — extend `rack serve` with Prometheus-format metrics and a health endpoint.

## Phase 5 — MLOps depth (the differentiating story)

> Turn the existing cost/routing primitives into a real, data-driven LLMOps control plane.

- 🗓️ **Real eval harness** — promote the eval stubs to golden-task evals per specialist role;
  use results to gate model-tier recommendations with data, not vibes.
- 🗓️ **Cost & latency history** — daily per-agent series (`rack cost --history`) built on the
  Phase 4 cost index, with regression alerts.
- 🗓️ **Template/prompt versioning** — stamp SOUL/AGENTS/TOOLS template versions into
  `.rack-meta.json` and surface drift in `rack doctor`.
- 🗓️ **Declarative provisioning** — `rack add --from agent.yaml` so agent fleets are
  reproducible and reviewable in git.

## Phase 6 — Product & community

- 🗓️ **Full manager delegation** — promote the task queue to an enforced state machine with
  locking and schema validation.
- 🗓️ Issue/PR templates, a richer eval-results page, and a short demo (asciinema).

---

### Near-term (next four, concrete)

1. ✅ Fix the `keys.sh` injection (done, tested).
2. ✅ Scope secret distribution to least privilege (done, tested — P5-4).
3. ✅ Key rotation + age hygiene in `doctor` (done, tested — P5-5).
4. 🗓️ `json_write_atomic` + `flock` (Phase 1) — removes the corruption/race failure class.

A deeper internal audit with severities and effort estimates lives in
`internal-docs/ARCHITECTURE-AUDIT.md` (not published).
