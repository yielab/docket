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

You can expect an initial acknowledgement within a few days. Once a fix is ready, the advisory
will be published with credit to the reporter (unless you prefer to remain anonymous).

## Scope and Current Posture

rack manages autonomous agents that can execute commands. Be aware of the current security
model when assessing risk:

- By default, agent-level safety constraints are **instruction-based** (written into each
  agent's prompt), not technically enforced.
- Enforced tool-approval gates, Telegram approval routing, and Docker workspace isolation are
  available **opt-in** via `rack gates enable` / `rack gates isolate on` (or
  `rack install --gates`) — see
  [`specs/functional/security-gates.spec.md`](specs/functional/security-gates.spec.md)
  (Status: Implemented, opt-in; on-by-default deferred). `rack doctor` and
  `rack gates status` report the current posture.
- Run rack and its agents only in environments you trust, and review agent output before
  acting on it.

See [docs/SECURITY-SIMPLE.md](docs/SECURITY-SIMPLE.md) for the full security model.
