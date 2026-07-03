# Security Policy

## Supported Versions

docket is a personal R&D project under active development. Security fixes are applied to the
`main` branch only; there are no long-term support branches.

| Version | Supported |
| ------- | --------- |
| `main`  | ✅        |
| older tags | ❌     |

## Reporting a Vulnerability

If you find a security issue in docket itself (for example, command injection, unsafe handling
of API keys, or path traversal in workspace handling), please report it privately rather than
opening a public issue.

- **Preferred:** open a [private security advisory](https://github.com/yielab/docket/security/advisories/new) on this repository.
- **Alternative:** email the maintainer at `info@yielab.com` with the subject `docket security`.

Please include:

- A description of the issue and its impact
- Steps to reproduce (a minimal command sequence is ideal)
- The docket commit/version, your OS, and your Python version (`python3 --version`)

**Disclosure timeline.** You can expect an initial acknowledgement within a few days. I aim to
ship a fix or a documented mitigation within **90 days** of a valid report; the advisory is then
published with credit to the reporter (unless you prefer to remain anonymous). If a report is
being actively exploited, please say so and I will prioritize it.

## Threat model: what runs with what privileges

docket itself is a configuration and reporting tool. The thing that holds privilege is the
**OpenClaw daemon and the agents it runs** — they can execute commands on the host. docket:

- writes config (`~/.openclaw/openclaw.json`, per-workspace `.docket-meta.json`) and reads cost
  and health data;
- runs as your user; it does **not** require or request root for normal operation;
- enforces `700` on workspace dirs and `600` on files, and keeps secrets out of `argv`
  (values flow via stdin/env/inside-Python, never as process arguments — no `/proc` leakage).

**The approval-gate model.** Agent-level safety constraints are *instruction-based* (written
into each agent's `SOUL.md` prompt) — guidance, not enforcement, on their own. On top of that,
`docket install` **enforces tool-approval gates by default** (opt out with `--no-gates`): a
curated allowlist plus an approval step for dangerous operations not on it (e.g. `rm`, `dd`,
`docker`, `systemctl`), with a fail-closed default (`askFallback: deny`). Approvals are
answerable headlessly — `docket approve`/`docket deny` from any shell, or `docket serve`'s
`POST /approvals/<token>` for CI/automation — as well as via Telegram, and every grant/deny is
audit-logged regardless of channel. Note: `git`/`npm` stay on the allowlist for usability (the
daemon can't gate by argument text), so a bare `git push` is not itself blocked by this layer —
see the spec's high-risk-class section. `docket gates isolate on` is a separate, still opt-in
layer that additionally confines tool execution to a per-agent Docker sandbox. Re-apply or
reverse gate config anytime with `docket gates enable`/`docket gates disable`. `docket doctor`
and `docket gates status` report the live posture. See
[`specs/functional/security-gates.spec.md`](specs/functional/security-gates.spec.md)
(Status: Implemented, on by default for new installs).

## Where you run docket matters: homelab vs. public VPS

> **Homelab / trusted single-user machine — relatively safe.** You are the only operator, the
> blast radius is your own box, and instruction-level constraints plus human review are usually
> proportionate. Budget caps and session isolation are the features doing the most work here.
>
> **Public VPS / shared / internet-exposed host — treat as dangerous.** An autonomous agent
> with exec access on an exposed host is a serious liability. Gates are on by default, but also
> **enable Docker workspace isolation** (`docket gates isolate on`), use the `keyring` secret
> backend, restrict the OpenClaw daemon's network exposure, and never run with broad ambient
> credentials. Instruction-level constraints alone are *not* sufficient here — and remember
> `git`/`npm` invocations stay allowlisted even with gates on, so don't rely on gates to catch a
> bad `git push` by itself.

## Secret storage

API keys are stored via a pluggable backend (`DOCKET_SECRETS_BACKEND`):

- `file` (default) — a `0600`-permissioned JSON file at rest;
- `keyring` — the OS keyring (libsecret), with no plaintext key values at rest (docket keeps only
  a names-only index). Prefer this on any shared or exposed host.

## What docket does NOT protect against

docket is honest about its limits. It does **not**:

- sandbox or contain the OpenClaw daemon or models themselves — if OpenClaw or a model is
  compromised, docket's config cannot save you;
- defend against a malicious or prompt-injected agent when gates were explicitly disabled
  (`--no-gates` at install, or `docket gates disable` later), or against a `git`/`npm`
  invocation specifically (allowlisted even with gates on — see the approval-gate model above);
- audit or vet the code your agents write or the third-party tools/MCP servers they invoke;
- encrypt data at rest beyond the `0600`/keyring options above, or protect against an attacker
  who already has your user account or root;
- guarantee budget caps are instantaneous — they pause on the next reported usage tick, so a
  single in-flight call can overshoot.

Run docket and its agents only in environments you trust, enable enforced gates on anything
exposed, and review agent output before acting on it.

See [docs/SECURITY-SIMPLE.md](docs/SECURITY-SIMPLE.md) for the full security model.
