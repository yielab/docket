# Security Policy

## Supported Versions

rack is a personal R&D project under active development. Security fixes are applied to the
`main` branch only; there are no long-term support branches.

| Version | Supported |
| ------- | --------- |
| `main`  | ✅        |
| older tags | ❌     |

## Reporting a Vulnerability

If you find a security issue in rack itself (for example, command injection, unsafe handling
of API keys, or path traversal in workspace handling), please report it privately rather than
opening a public issue.

- **Preferred:** open a [private security advisory](https://github.com/santiagoyie/rack-cli/security/advisories/new) on this repository.
- **Alternative:** email the maintainer at `yie.worker@gmail.com` with the subject `rack security`.

Please include:

- A description of the issue and its impact
- Steps to reproduce (a minimal command sequence is ideal)
- The rack commit/version and your OS / Bash version

**Disclosure timeline.** You can expect an initial acknowledgement within a few days. I aim to
ship a fix or a documented mitigation within **90 days** of a valid report; the advisory is then
published with credit to the reporter (unless you prefer to remain anonymous). If a report is
being actively exploited, please say so and I will prioritize it.

## Threat model: what runs with what privileges

rack itself is a configuration and reporting tool. The thing that holds privilege is the
**OpenClaw daemon and the agents it runs** — they can execute commands on the host. rack:

- writes config (`~/.openclaw/openclaw.json`, per-workspace `.rack-meta.json`) and reads cost
  and health data;
- runs as your user; it does **not** require or request root for normal operation;
- enforces `700` on workspace dirs and `600` on files, and keeps secrets out of `argv`
  (values flow via stdin/env/inside-Python, never as process arguments — no `/proc` leakage).

**The approval-gate model.** By default, agent-level safety constraints are *instruction-based*
(written into each agent's `SOUL.md` prompt) — they are guidance, not enforcement. Enforced
tool-approval gates are **opt-in**: `rack gates enable` installs a curated allowlist and routes
dangerous operations (e.g. `rm`, `git push`, `docker stop`) through an approval step with a
fail-closed default (`askFallback: deny`). `rack gates isolate on` additionally confines tool
execution to a per-agent Docker sandbox. Enable them with `rack install --gates`, or later with
`rack gates enable`. `rack doctor` and `rack gates status` report the live posture. See
[`specs/functional/security-gates.spec.md`](specs/functional/security-gates.spec.md)
(Status: Implemented, opt-in; on-by-default deferred pending headless approval routing).

## Where you run rack matters: homelab vs. public VPS

> **Homelab / trusted single-user machine — relatively safe.** You are the only operator, the
> blast radius is your own box, and instruction-level constraints plus human review are usually
> proportionate. Budget caps and session isolation are the features doing the most work here.
>
> **Public VPS / shared / internet-exposed host — treat as dangerous.** An autonomous agent
> with exec access on an exposed host is a serious liability. **Enable enforced gates and Docker
> isolation** (`rack install --gates` + `rack gates isolate on`), use the `keyring` secret
> backend, restrict the OpenClaw daemon's network exposure, and never run with broad ambient
> credentials. The instruction-level defaults are *not* sufficient here.

## Secret storage

API keys are stored via a pluggable backend (`RACK_SECRETS_BACKEND`):

- `file` (default) — a `0600`-permissioned JSON file at rest;
- `keyring` — the OS keyring (libsecret), with no plaintext key values at rest (rack keeps only
  a names-only index). Prefer this on any shared or exposed host.

## What rack does NOT protect against

rack is honest about its limits. It does **not**:

- sandbox or contain the OpenClaw daemon or models themselves — if OpenClaw or a model is
  compromised, rack's config cannot save you;
- defend against a malicious or prompt-injected agent when gates are **disabled** (the default);
- audit or vet the code your agents write or the third-party tools/MCP servers they invoke;
- encrypt data at rest beyond the `0600`/keyring options above, or protect against an attacker
  who already has your user account or root;
- guarantee budget caps are instantaneous — they pause on the next reported usage tick, so a
  single in-flight call can overshoot.

Run rack and its agents only in environments you trust, enable enforced gates on anything
exposed, and review agent output before acting on it.

See [docs/SECURITY-SIMPLE.md](docs/SECURITY-SIMPLE.md) for the full security model.
