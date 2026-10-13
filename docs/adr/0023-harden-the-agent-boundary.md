# ADR 0023 (D-58): harden the agent boundary after the 2026-10-12 security audit

**Question:** a five-lane security audit on 2026-10-12 (plan and evidence in the gitignored
`internal-docs/security-audit-2026-10-12.md`) ran docket against a hostile repository on the
local model and found, beyond the defects fixed in the same session, a set of open weaknesses in
the places where an attacker's text or configuration reaches a decision: a cloned repository's
`.docket/` is applied by `docket init` with no confirmation and can execute code on the host; an
unjailed task process can read docket's exported credentials from `/proc`; repository text is
composed into the system prompt with the operator's authority and no untrusted frame; several
state changes carry no audit entry, and a handful of lower-severity gaps (redirect handling on
authenticated requests, an unauthenticated endpoint that publishes the Telegram allowlist, the
`fetch` deadline, directory modes, supply-chain pinning). How should docket respond, and which
of these is a straight fix versus a behaviour change that needs the maintainer's sign-off?

**Where decided:** 2026-10-12, planning at the maintainer's request after the audit. The
maintainer asked for the findings to be scheduled as a phase that multiple Sonnet/Haiku agents
can implement.

**Decision:**

1. **The contained defects are already fixed** and ship in the commit that opens the phase:
   the newline command-separator bypass, the `git -c … push` regex, the approval-token
   path traversal, the bwrap jail masking `DOCKET_HOME`, the store symlink and exclusive-temp
   hardening, the Telegram poison-update wedge, the control-plane JSON body guard, trace
   redaction of env-sourced and bare vendor tokens, `docket init` installing the baseline
   policies, the pod-scoped `on: input` policies reaching every screen, and the skill-body
   screen. Specs bumped: security-gates 0.38.0, trace-store 1.7.0, mcp-client 1.10.0, agent-loop
   1.33.0, telegram-integration 2.6.0. These are not re-scheduled.

2. **Phase 40 schedules the open items** as independently shippable cards (TODO.md), each citing
   the audit finding it closes. The phase does not bundle unrelated behaviour.

3. **One item is a behaviour change that narrows ADR 0012, so it is gated on a maintainer
   decision, D-59 (§6):** making `docket init` / `docket pod apply` refuse or confirm before it
   applies a cloned repository's `.docket/` when the plan carries anything executable (plugins,
   an unjailed MCP server, a `run:`/verify command, `allowCommands`, `approvalMode`,
   `deniedTools`, `mcpServers`) or loosens a built-in role's denials. ADR 0012's "operator
   command or nothing" is working as designed; `git clone && docket init` makes the repository
   author the effective operator, which is the gap. **D-59 was answered the same day
   ([ADR 0024](0024-one-execution-envelope.md) §6):** the commands a repository brings need the
   operator's OK once, remembered until they change, with `--accept <code>` for scripts; P40-5
   and P40-13 ship it.

4. **The isolation-default and broad argument-path-containment questions stay out of this
   phase.** They are the documented "the gate is a gate, not a sandbox" boundary (ADR 0020,
   ADR 0021 / D-56). Phase 40 does ship the one clear confidentiality fix that does not depend on
   that debate: making the docket process non-dumpable so a same-uid unjailed child cannot read
   its `/proc/<pid>/environ` (P40-6). Whether to reverse D-56 again, or add argument-path
   containment for allowlisted interpreters and file utilities, is a separate measured decision.

5. **Model susceptibility is not a docket defect.** Whether a model obeys an injected
   instruction cannot be fixed here; Phase 40 judges only the containment around it — what the
   agent can do after it obeys, and whether the untrusted text is framed as untrusted (P40-7).
   The shipped `prompt-injection` regex is treated as an audit signal, not a defence.

**Consequences:** the audit's open findings have an owner and a test each; the one ADR-0012-
narrowing change waits for D-59; the structural isolation debate is named and deferred, not
silently resolved. The phase is planned, not active: a coordinator activates a wave with the
`ACTIVE BOARD` banner and the conflict graph when work starts (board contract). `CHANGELOG.md`
records each card's user-visible change as it merges.
