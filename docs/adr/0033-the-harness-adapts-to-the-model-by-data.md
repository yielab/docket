# ADR 0033 (D-73): the harness adapts to the model by data, and pays for context once

**Question:** docket runs the same contract for every model: one tool surface, one description
length, the endpoint's own sampling, no reasoning kept, truncation that keeps the head of a
result, a final call that rewrites the system prompt. A survey of harness engineering (SWE-bench
harness ablations, SWE-Edit, constrained decoding, TokenPilot, governance decay, keepalive
economics) argues that the harness, not the weights, decides most of the spread in success and
in tokens, and that small and hosted models need different things from it. Which of those
techniques does docket already have, which are missing, and which must it refuse?

**Where decided:** 2026-10-25, by the maintainer, after a code audit of the live path against
the survey. Phase 52 on `TODO.md` is the card list. The survey's numbers are its own; nothing
here promises a saving before the replay bench or the live eval measures it.

## What was found in the code

Already in place, and kept:

- **Rules survive compaction by construction.** The system prompt is composed from source every
  turn and never written to history (`agent/loop.py`); a compaction summary is a separate
  message; the request-fit reduction compacts around the task message. The policy is applied in
  `dispatch_tool`, not in prose. This is stronger than re-pinning rules after a summary.
- **Compaction is not periodic:** once at turn start, then only when a request does not fit;
  atomic units; fail-closed (`agent/session_compaction.py`).
- **Skills are lazy** (one index line each, `skill` loads the file), **handoffs are typed**
  (`HandoffArtifact`, `TaskBrief`), **tokens are measured** with cache reads outside the budget
  (`agent/ports.py::TokenUsage.counted_tokens`), **loops are detected** (`_ProgressDetector`),
  and a role or a step can name its model.

Missing, all verified on 2026-10-25:

- `LoopConfig.temperature` has no writer (`hops/application/driver.py`); no `top_p`; the local
  endpoint's 1.0 is inherited. `tool_choice` is always `"auto"`. `reasoning_content` is dropped
  on decode and `ChatMessage` cannot carry it. No per-model profile: a catalog row holds only
  limits and prices.
- `cut_output` keeps the head of a tool result (`kernel/text.py`); a test runner's summary is at
  the tail, so the model re-runs it. No ANSI or repeated-line normalization. The full output is
  not retrievable: the trace keeps a capped copy and no tool reads it.
- The finalization call appends to the system message (`agent/loop_request.py`), so the longest
  request of the turn misses the cached prefix.
- The condensation of old tool results keeps the two newest whole and a contiguous 6,000-char
  window; one large result evicts small ones that are then re-read.
- A command `shlex` cannot parse is an `ask` (`governance/security.py`): the model's syntax error
  becomes a wait for a person.
- `edit` reports only "not found"; a failed `bash` shows stdout and stderr merged, with a hint
  only for exit 126.
- The Lead reads the code and hands the Implementer prose (`TaskBrief.context: list[str]`); the
  Implementer explores again. No cache-hit ratio and no tokens-per-accepted-task figure exists.
- An Implementer's tool schemas are about 5,800 characters; every MCP schema is sent upfront.

## Decision

1. **Adaptation is data, resolved from the provider catalog.** A `ModelProfile` on a catalog
   row (`sampling`, `reasoning`, `toolSurface`, `descriptions`, `toolChoice`, window-derived
   budgets) with two built-in profiles, `hosted` (today's behaviour) and `local` (for rows
   declared `local: true`). No heuristic by model name beyond that. The profile used is recorded
   on the trace, visible in `docket status`.
2. **Context is paid for once.** The prefix of a turn stays byte-identical except at condensation
   batch boundaries: the finalization instruction is a trailing message, never a system rewrite;
   tool results are normalized at ingestion (lossless only: ANSI, carriage-return progress,
   repeated lines) and truncated head+tail; a result over the cap is stored whole under the pod
   cache by content hash and the model is told the path, so the cap can drop without losing
   information. Small results are never condensed before large ones.
3. **The model's error returns to the model.** A parse failure is a refusal with a hint, not an
   approval; a failed `edit` shows the closest lines; a failed `bash` shows stderr first and
   names the known causes (exit 126, 127).
4. **The Lead is the viewer.** The brief carries locators (`path:<file>#L<a>-<b>`); docket, not a
   model, reads those ranges fresh from the worktree into the Implementer's message within the
   role's budget. The pod (cheap read-only Lead, strong Implementer, cheap Reviewer, `parallel`
   groups) already gives what in-turn sub-agents would, except a mid-turn decision to explore;
   that is not built until a measurement shows Implementers still exploring with locators.
5. **Measure before and after.** Every card names its oracle: the replay bench
   (`scripts/maint/context_replay.py`) for bytes and counted tokens, the live eval
   (`scripts/maint/live_eval.py`) for success on the local endpoint, and two new figures the
   phase adds first: cache-hit ratio per `llm_call` and tokens per accepted task. Dollars stay
   estimates.

## Not doing

| Technique | Why not |
| --- | --- |
| Keepalive pings to hold a provider's cache warm | docket has no daemon for it; a turn is capped at 300 s, under the 5-minute TTL; a parked task waits hours. Spending to save, unmeasured. |
| A grammar for `bash` (Lark, tree-sitter) | docket rents protocols; the server constrains a forced tool call (`tool_choice`), and the classifier already parses with `shlex`. |
| Sub-agents spawned inside a turn | Breaks "one hop, one role, one budget", nests `dispatch`, complicates the audit. The pipeline expresses the pattern; see point 4. |
| Replacing timestamps and pids with placeholders at ingestion | Loses information, and those outputs sit at the end of the prefix anyway. |
| Periodic summary compaction | Already avoided; the sawtooth the survey describes is the thing to keep out. |
| Quoting the survey's savings | Tokens are measured, dollars estimated, nothing projected. |

## Deferred, with triggers

- **Reasoning kept inside the turn** (`ChatMessage.reasoning`, resent only within the active
  tool loop): a profile that declares `reasoning: interleaved`.
- **Lifecycle condensation** (a read superseded by a later read or an `edit` of the same file is
  evicted first): the bench still shows re-reads after the artifact store ships.
- **A bounded model escalation** (`escalate: {on: [verify_failed, no_progress], model: strong,
  max: 1}` on a step): the "strong Lead, cheap Implementer" recipe fails `verifyCmd` on a
  measured share of runs.
- **A lazy MCP catalog** (`mcp_describe`): a pod whose MCP schemas exceed its built-in ones.
- **A native Anthropic dialect** (1 h TTL, `cache_control` on tools, signed thinking blocks):
  direct use without the gateway, which caches today.
