# Agent Loop Specification

**Version**: 2.0.0
**Status**: Implemented and live. `DocketDriver` (resolved by `default_driver()`) runs every
production turn through `run_agent_turn`, which narrows tools by role, composes the system prompt,
compacts history, and gates every tool call through `dispatch_tool` until a typed stop fires.
**Last Updated**: 2026-10-22

## Purpose

docket owns the agent turn loop (D-19), so every governance primitive (the gated tool registry, the
`pre_tool_call` policy hook, the approval store, the argument-aware command classifier, the
hash-chained audit log, durable session history) acts *inside* a turn, not only between turns.
This specification defines that loop: compose context, call the model, gate and execute every
requested tool call through the single chokepoint, feed results back, and repeat until one of a
fixed set of deliberate stop conditions fires. It also defines `DocketDriver`, the one shipped
implementation of the `RuntimeDriver` port, which runs that loop with no daemon underneath.

## Scope

This specification covers:

- `run_agent_turn`: message composition, the single tool-execution path, the stop-condition
  contract, truncation handling, and per-iteration session durability
- `DocketDriver`: how the five-method `RuntimeDriver` port (`run_turn`, `list_sessions`,
  `read_new_turns`, `usage`, `capabilities`) is implemented on top of the loop, including the
  tool-containment root resolution and the `capabilities()` honesty contract
- That `run_agent_turn` narrows its tool registry by role (`registry_for_role`) and composes a
  system prompt (`compose_agent_prompt`) once per turn, and what each does to the messages sent to
  the backend and persisted to session history
- The live trigger and adapter for `compact_session`: ordering, non-recursion, measured usage
  accounting, failure behavior, and privacy-safe trace payloads
- The optional trace coordinate used when one task-wide trace stream spans several independently
  persisted step histories
- Per-request endpoint fit, the cumulative measured-token preflight, and the one-shot, tool-free
  terminal-response reservation
- Request-fit convergence, so a durable suffix or prefix is never summarized repeatedly without
  intervening growth
- The typed stops: consecutive tool denials, run cancellation, `approval_unavailable`,
  `approval_parked`, and `no_progress`
- The output shape of the `glob`, `grep` and `read` built-ins and the condition under which
  `fetch` is registered

This specification does NOT cover:

- The chat-completion wire protocol or the `ChatBackend` port
- The tool registry, the gate, or the chokepoint itself; this spec depends only on
  `dispatch_tool`'s documented contract (`security-gates.spec.md`)
- The archetype schema, `deniedTools` data, and `registry_for_role`'s own contract — see
  `role-archetypes.spec.md`'s "Per-role tool sets"
- The identity file layout itself (`SOUL.md`, `WORKFLOW_AUTO.md`) — see
  `workspace-structure.spec.md`; this spec covers only that the loop composes and injects the result
- Durable session storage and compaction planning internals (`session-history.spec.md`); this spec
  owns only their live-loop integration
- The docket-native fleet registry; see `agent-lifecycle.spec.md`
- Turning measured token usage into a dollar figure — `cost_usd` is `0.0` on every result this
  driver produces; see `cost-tracking.spec.md`
- The trace store's record shape, redaction, subscriber seam, retention window, and event-type
  vocabulary (`trace-store.spec.md`); this spec requires only that the loop emits certain events
  at certain points (requirements 16, 17, 30, 37, 49, 54, 71)
- The observability export pipeline that `DocketDriver.run_turn` starts and flushes
  (`observability-export.spec.md`)

## Requirements

### Single execution path

1. Every tool call a turn's model response requests **MUST** be dispatched exclusively through
   `dispatch_tool`. The loop **MUST NOT** import the built-in tool handler module or invoke a
   `Tool.handler` directly.
2. A tool call that cannot be evaluated (unknown tool, unparseable arguments, missing required
   arguments) **MUST** be refused via the same `dispatch_tool` path, never silently dropped or
   executed anyway.

### Truncation safety

3. A response whose `finish_reason` indicates truncation (`ChatResponse.truncated`) **MUST NOT**
   have any of its tool calls dispatched, regardless of whether the truncation happened
   mid-argument or mid-prose.
4. A truncated response's assistant message **MUST NOT** be persisted to session history —
   persisting it would risk storing an assistant `tool_calls` entry with no answering `tool`
   message, which session history's atomic-unit contract forbids.
5. A turn that stops due to truncation **MUST** report `stop_reason="truncated"` and `ok=False`.

### Stop conditions

6. The loop **MUST** stop with `stop_reason="final_message"` and `ok=True` when a response carries
   no tool calls. This **MUST** be the only stop reason for which `ok` is `True`.
7. The loop **MUST** stop with `stop_reason="max_iterations"` once the configured maximum number of
   model round-trips would be exceeded, without making a further model call.
8. The loop **MUST** stop with `stop_reason="max_tool_calls"` once the configured maximum number of
   dispatched tool calls is reached or would be exceeded. A single response's tool-call batch
   **MUST** be dispatched wholly or not at all — never partially — so a batch that would push the
   total over the cap is refused in full before any call in it runs.
9. The loop **MUST** stop with `stop_reason="timeout"` once the configured wall-clock budget for
   the whole turn has elapsed, checked between iterations. Each request's own timeout is the
   smaller of `request_timeout_s` and the wall-clock budget left.
10. The loop **MUST** stop with `stop_reason="token_budget"` once the turn's cumulative *counted*
    token usage exceeds the configured budget. Counted tokens are `TokenUsage.counted_tokens`:
    `input_tokens - cached_tokens + output_tokens` (a cache read is never counted; a cache write is
    part of the input and is). The figure is the endpoint's reported usage (`TokenUsage`, real
    counts) and **MUST NOT** be computed from the bytes-per-token estimate used for compaction. A
    response that carries no tool calls is the exception: it is already paid, so it is persisted
    and returned `ok` even when it crosses the budget (requirement 55 refuses only a response with
    tool calls).
11. A backend failure (`ChatResponse.ok=False`) **MUST** stop the loop with
    `stop_reason="backend_error"` and the backend's own `failure_kind`, without raising.
12. `AgentLoopResult.failure_kind` **MUST** be `None` if and only if `ok` is `True`.

### Durability

13. The incoming user message **MUST** be persisted after the pre-turn compaction check and before
    the first task-completion model call. The compaction summarizer is the sole model call allowed
    before that append; if it fails, the incoming message is not accepted into durable history.
14. Each iteration that dispatches tool calls **MUST** persist the assistant message and every tool
    result answering it in one call to `append_messages` — never split across two calls, which
    could leave an orphaned `tool_calls` entry durable if the process died between them.
15. A turn **MUST NOT** write session history through any path other than
    `append_messages`/`load_messages`.

### Tracing

16. Every tool call actually dispatched **MUST** emit a `tool_call` trace event before it runs and a
    `tool_result` trace event after it.
17. A turn that dispatches no tool calls **MUST NOT** emit either event type. See requirement 71 for
    the `llm_call` event every backend request emits.

### `DocketDriver` (`RuntimeDriver` conformance)

18. `run_turn` **MUST** map the loop's result onto `TurnResult` using the existing `FailureKind`
    vocabulary, carrying the loop's `stop_reason`, `usage`, `retry_after_s`, `model` and
    `provider`, and **MUST NOT** raise for an ordinary failure: missing or malformed agent metadata
    returns `TurnResult(ok=False, failure_kind="invalid_output")`, and a model with no resolvable
    endpoint returns `TurnResult(ok=False, failure_kind="daemon_error")`. The one deliberate
    exception is `DispatchError` for a deterministic caller misconfiguration: a refused isolation
    or network posture, a pod `mcpServers` setting naming a server absent from the catalog, or
    refused task restrictions.
19. `run_turn`'s `cost_usd` **MUST** always be `0.0`. Real token counts are recorded (folded into
    the session's measured usage), but this driver **MUST NOT** convert them into a dollar figure.
20. `run_turn`'s tool-containment root **MUST** be resolved with the precedence: an explicit task
    worktree directory, then the agent's codebase, then its work directory, then its bare docket
    workspace directory.
23. `capabilities().reports_cost_usd` **MUST** be `False`.
24. `capabilities().supports_sessions` **MUST** be `True`, and `list_sessions`/`read_new_turns`/
    `usage` **MUST** read docket's own durable session storage, never a daemon session log.
25. `list_sessions` **MUST** scope its results to sessions whose key belongs to the requested agent
    id.

### Per-role tool narrowing

26. `run_agent_turn` **MUST** narrow the *registry* it was given via
    `registry_for_role(registry, ctx.role, ctx.project)` exactly once per turn, before the first
    `ChatBackend.complete` call — not per iteration, since a role's tool set does not change
    mid-turn. Every use of the registry for the rest of the turn (advertising tool specs to the
    model, `dispatch_tool`) **MUST** use the narrowed result.
27. A tool call requesting a name the role's archetype denies **MUST** be refused by
    `dispatch_tool` as an unknown tool — the same refusal path an unrelated hallucinated tool name
    takes — never a distinct "forbidden for your role" code path. The model is not advertised the
    tool, and if a call for it arrives anyway, the registry genuinely does not contain it.
28. `run_agent_turn` **MUST NOT** contain a branch on a specific role's name (e.g.
    `if ctx.role == "reviewer"`) to decide what to narrow — the denylist is data on the archetype
    (see `role-archetypes.spec.md`'s "Per-role tool sets"), and `registry_for_role` is the single,
    generic function consuming it. The built-in tool set this requirement narrows is `read`,
    `write`, `edit`, `glob`, `grep`, `bash`, `skill`, `consult`, and `fetch` (when registered,
    requirement 83). A role's `deniedTools` may name any of them, and a denied tool follows the
    same not-advertised refusal path as any other.

### System prompt composition

29. `run_agent_turn` **MUST** compose a system prompt via
    `compose_agent_prompt(ctx.agent_id, project_roots=ctx.roots, ...)` once per turn and, when
    non-empty, prepend it as a `system`-role message ahead of the turn's history and incoming user
    message. An empty result (no workspace, no identity files, no `agent_id`) **MUST NOT** add an
    empty `system` message.
30. The composed system prompt **MUST** be built as follows.

    **Layers and order.** Sections run stable first, each joined by a `---` separator: the agent's
    `SOUL.md`; the operator-owned `INSTRUCTIONS.md`; the member's own `AGENTS.md` (its method and
    tool strategy, projected without its generated `## Session Startup` section); one
    authoritative runtime projection of docket's generated startup contract; the project
    instructions; the skills index; `MEMORY.md`; and the pod's accepted memory last. An absent or
    empty source composes no section.

    **`INSTRUCTIONS.md`.** Docket **MUST NOT** write, regenerate, or quarantine `INSTRUCTIONS.md` at
    any point (provisioning, `docket pod update`, `docket setup --fix`): it is the durable home for
    operator instructions because nothing on this path ever overwrites it.

    **Project instructions.** The pod setting `projectInstructions` names relative paths inside the
    codebase root. When it is unset and the first project root holds an `AGENTS.md` file, that
    file **MUST** compose by default, exactly as an explicitly named file does: screened, capped
    and reported the same way, under the same `projectInstructions` name. An explicit
    `projectInstructions` list **MUST** replace the default entirely, never add to it. Only the
    first root's `AGENTS.md` is ever a default. `project_instruction_files(settings, root)`
    **MUST** be the single function that resolves the effective files and their source
    (`"set"`/`"default"`/`""`), used by both this composition and the `docket pod show` report.
    Each path is resolved against the first of `project_roots` and, unlike `INSTRUCTIONS.md`, is
    never trusted: it **MUST** be screened through the `pre_input` policy hook (`trusted=False`,
    the calling pod's policies included) before it reaches the composed text, the same screen an
    untrusted MCP tool description gets. A `block`/`require_approval` verdict replaces that file's
    content with an audited one-line marker (`identity.project_instructions_blocked`) naming the
    file and the policy; `warn`/`redact` still compose it (audited,
    `identity.project_instructions_warn`); a path with no file composes to a visible
    `[... <path> not found ...]` line, never an error. The `projectInstructions` setting refuses
    an absolute, home-relative, or `..`-containing path when it is set.

    **Base-commit source.** When the turn runs in a task worktree whose task record carries a
    `baseCommit`, the git dirs docket recorded for it, and a worktree directory equal to the turn's
    own, the codebase's `AGENTS.md`, every `projectInstructions` file and the codebase-scope skills
    (`.docket/skills/`, both the index and the `skill` tool's reads) **MUST** be read from the blob
    at `baseCommit` through host-side git on those recorded dirs, never from the worktree: an
    Implementer that rewrites `AGENTS.md` or a skill changes nothing the next hop is told. A path
    absent at `baseCommit` is absent (the not-found marker, no skill), whatever the worktree holds.
    `RepoView` is the injected reader; the composition never shells out. The bytes each view served
    are recorded as `RepoView.composed`, a mapping from repository-relative path to the sha256 of
    those bytes, and returned on `TurnResult.repo_files`. Without a task worktree, a `baseCommit`
    or recorded git dirs, these files are read from the filesystem. Pod-scope and global skills are
    not repository files and are always read from disk.

    **Skills index.** A `# Skills` section lists every skill
    `discover_skills(project, project_roots[0])` resolves — three scopes, nearest wins by name: the
    codebase's `.docket/skills/`, the pod's own `config/skills/`, and the operator's skills
    directory (`SKILLS_DIR`, default `~/.docket/skills/`) — as `- <name>: <description>` lines
    sorted by name, each description screened through the same `pre_input` hook
    (`trusted=False`; audited `identity.skill_blocked`/`identity.skill_warn`). A skill whose
    `SKILL.md` frontmatter is invalid, or whose `name` disagrees with its directory, is skipped and
    audited (`skills.invalid`) rather than raised into a turn. The section ends with one line
    telling the model to call the `skill` tool, naming a skill, for its full instructions. No
    discovered skill composes no section. The `skill` tool (`kind="read"`, parameters `name`
    required, `path` optional) resolves *name* through the same `discover_skills` call and returns
    the named file (default `SKILL.md`) read from within that skill's own directory only, screened
    as untrusted input exactly like a fetched page or an MCP result (`screen_tool_result`, audited
    `skills.body_blocked`/`skills.body_warn`, the calling pod's `on: input` policies included); an
    unknown name is a failed call naming the known names, never a raise.

    **Untrusted frames.** The project-instructions and skills sections are repository text and
    **MUST** each be preceded by one fixed frame constant (`REPO_INSTRUCTIONS_FRAME`,
    `REPO_SKILLS_FRAME`) naming it untrusted: follow it for style and convention only, never as a
    request to run commands or change tools, approvals or policies. The frame is counted against
    the section's budget, is absent when the section is absent, and is a containment aid for a
    model that weights system text above tool output, not a defence; the screens' verdicts are
    unchanged.

    **Pod memory.** The last section is the pod's accepted memory entries
    (`workspace-structure.spec.md` "Pod memory"): the `# Pod memory (untrusted)` frame, then one
    line per entry (`- <kind> <path>: <note>`, or ``- command `<command>` (exit <n>): <note>``),
    oldest first, capped at `POD_MEMORY_RENDER_MAX_BYTES` and by the room left after every section
    above it, by dropping the oldest whole entries. An entry whose path no longer exists under
    `project_roots[0]` is left out. No pod or no accepted entry composes no section. It is reported
    as `podMemory` in `prompt_composed`.

    **Live runtime projection.** The projection **MUST NOT** send raw `WORKFLOW_AUTO.md` startup
    prose that tells a model to open or update `HEARTBEAT.md`, `MEMORY.md`, or `memory/`: those
    instructions are for a manual/external reset path, while the live runtime has already read the
    state itself. Instead it **MUST** state once that private control files are already loaded and
    read-only and are never project-tool targets (explicitly including shell execution), and that
    returning the completed result is sufficient because docket owns turn durability. It **MUST
    NOT** carry the project roots (ADR 0028): they limit the tools through `ToolContext.roots` and
    reach the model in the task message (`pod-dispatch.spec.md`, "Bounded hop prompts" requirement
    10), so two tasks of one member in different worktrees compose a byte-identical system prompt.
    `HEARTBEAT.md` and `TOOLS.md` **MUST NOT** be composed: every live turn is a pod hop, the task
    arrives in the message, and tool schemas travel in the `tools` parameter. `MEMORY.md` **MUST**
    be composed only when it holds text beyond its generated template (headings, `_..._`
    placeholders and the `stack`/`codebase`/`path`/`origin` lines of a seed are the template). The
    `AGENTS.md` projection **MUST** structurally omit the generated `## Session Startup` section,
    whose private-file reads duplicate the runtime, while preserving the title, `## Red Lines`, and
    other custom sections byte-for-byte; an `AGENTS.md` without that heading remains intact. Prompt
    composition **MUST NOT** rewrite any source workspace file or regex-filter arbitrary prose.

    **Static-context budget.** The composed prompt **MUST** fit a resolved static-context budget,
    preserve higher priorities first, and mark any truncation or omission visibly rather than
    silently growing an endpoint's context or dropping state. `resolve_static_context_budget`
    **MUST** resolve, in order: (a) an explicit `CONTEXT_TOKEN_BUDGET` override — the environment
    variable, or a resolved value that differs from `CONTEXT_TOKEN_BUDGET_DEFAULT` — always wins
    unchanged (`budgetSource: "env"`); (b) otherwise, when the turn has a positive resolved model
    context window, a documented share of that window after reserving the output-token budget and
    a fixed tool-schema allowance (`resolve_window_share_tokens`, `WINDOW_SHARE`,
    `TOOL_SCHEMA_RESERVE_TOKENS`), floored at `CONTEXT_TOKEN_BUDGET_DEFAULT` (`"window"` when above
    the floor); (c) absent or non-positive window information **MUST** resolve to
    `CONTEXT_TOKEN_BUDGET_DEFAULT` (`"default"`).

    **Section fitting.** The runtime contract is never truncated, and `MEMORY.md` **MUST NOT** be
    crowded out by the leading sections. Each leading section is middle-truncated (head and tail
    kept, a `[... <name> truncated: <n> bytes omitted ...]` marker between) to at most half of the
    room the sections before it left: `SOUL.md` to half the budget, `INSTRUCTIONS.md` to half of
    what `SOUL.md` left, `AGENTS.md` to half of what `INSTRUCTIONS.md` left, project instructions
    (after their frame) to half of what `AGENTS.md` left, and the skills index (after its frame) to
    half of what project instructions left. Each reports its own `full`/`truncated`/`omitted`
    `PromptSectionReport` under its own name (`SOUL.md`, `INSTRUCTIONS.md`, `AGENTS.md`,
    `projectInstructions`, `skills`), never merged into another's. When fitting the
    private-workspace sections after them, a section that does not fit **MUST NOT** stop
    composition of the sections behind it: that section, and every later one that also does not
    fit, each still receive their own one-line `[... <name> omitted: <n> bytes omitted ...]` marker
    (or a truncation marker, for one that partially fits).

    **`prompt_composed`.** `run_agent_turn` **MUST** emit exactly one `prompt_composed` trace event
    per composition that reports at least one section, listing every section attempted — `SOUL.md`,
    `INSTRUCTIONS.md`, `AGENTS.md`, `projectInstructions`, `skills`, `MEMORY.md` when it holds
    content, and `podMemory` — with the bytes included and a `full`/`truncated`/`omitted` status
    per section, plus the resolved `budgetTokens` and its `budgetSource` (`env`/`window`/`default`).
    An agent with no identity, startup or private files composes no system message and emits no
    `prompt_composed` event. This budget is an estimate like every other bytes-per-token figure —
    never a measured token count, and never reused to bound `AGENT_LOOP_TOKEN_BUDGET`'s separate,
    measured-usage cumulative turn budget.
31. The composed system prompt **MUST NOT** be persisted to session history through
    `append_messages` — it is recomposed fresh on every call to `run_agent_turn`, so refreshed
    private workspace state (requirement 30) is reflected on the very next turn rather than frozen
    into a stored message.

### Live session compaction

32. Before loading replay history or appending the incoming message, `run_agent_turn` **MUST** call
    `compact_session` with the role's history budget (or the explicit test/operator override). The
    compaction check and any required summary completion **MUST** finish before the first
    task-completion `ChatBackend.complete` call.
33. The live summarizer **MUST** be one direct, tool-free call through the `ChatBackend` instance
    already supplied to `run_agent_turn`. It **MUST NOT** call `run_agent_turn`, advertise tools,
    resolve another backend, or persist its prompt/output as a conversation. This structural path,
    together with `compact_session`'s re-entry guard, is the explicit recursion barrier.
34. The summarizer runner **MUST** receive a deterministic session key distinct from the target key
    (`<session_key>:compaction`). No summarizer messages are persisted under that isolated key or
    the target key; only the resulting compacted summary is written to the target on success.
35. The summarizer response's endpoint-reported `TokenUsage` **MUST** be added to both the returned
    turn usage and the target session's measured usage. These measured values **MUST NOT** drive
    compaction; before/after window sizes remain named estimates from `estimate_tokens`.
36. A not-ok/timeout, truncated, empty, or tool-requesting summarizer response **MUST** abort the
    turn with `stop_reason="compaction_failed"`, preserve the prior message history byte-for-byte,
    and make no task-completion backend call. This invalid-summary classification **MUST** take
    precedence when that same response's measured usage also crosses the cumulative turn budget;
    endpoint-reported usage, when non-zero, is still recorded as usage metadata and does not alter
    the preserved messages. A truncated partial summary **MUST NEVER** become durable history.
37. Every pre-turn compaction check **MUST** emit one `session_compaction` trace event with status
    `no_op`, `succeeded`, or `failed`; before/after message counts; before/after estimated tokens;
    and groups summarized. The payload **MUST NOT** contain raw history, prompts, summaries, or
    measured token counts mislabeled as estimates.
38. A live compaction **MAY** make multiple bounded summary completions. Every completion **MUST**
    stay on the same non-recursive, tool-free adapter; its endpoint-reported usage **MUST** be
    accumulated into turn/session measured usage, and its timeout **MUST** be capped by the turn's
    remaining wall-clock budget at call time.
39. The compaction trace payload **MUST** additionally report summary-round count and the maximum
    estimated prompt tokens sent in any round. It **MUST NOT** include any prompt or summary text.

### History and trace identity

40. `run_agent_turn`'s `session_key` **MUST** remain the sole coordinate for durable history,
    compaction, summarizer-key derivation, and measured session usage. Optional `trace_project` and
    `trace_session_key` values **MUST** select only the trace directory/stream; when omitted they
    **MUST** default to `ctx.project` (then `ctx.agent_id`) and `session_key`. An optional
    `trace_task_id` **MUST** be stamped on every trace event the loop writes and nothing else.
41. Every `prompt_composed`, `session_compaction`, `request_fit`, `budget_warning`, `llm_call`,
    `tool_call`, and `tool_result` event produced inside the loop **MUST** use the resolved trace
    coordinate. No trace helper may cause messages or usage to be loaded from or appended to that
    trace coordinate.
42. `DocketDriver.run_turn` **MUST** pass its `session_key` to `ToolContext` and the loop as the
    durable-history identity, and **MUST** forward optional keyword-only `trace_project`,
    `trace_session_key` and `trace_task_id` values to the loop. The `RuntimeDriver` port and its
    canonical fake **MUST** accept `trace_project` and `trace_session_key`; a caller that omits them
    gets the defaults of requirement 40. A `trace_task_id` passed as a value (not `None`) also marks
    the turn as a pod dispatch hop, so a `consult` parks that task. A `model` keyword, when given, wins over the
    agent's configured model for this call only and is never written back to `.docket-meta.json`.
43. `DocketDriver.list_sessions(agent_id)` **MUST** enumerate every durable key with the
    `agent:<agent-id>:` prefix, including base scoped sessions and step-scoped dispatch histories. A
    trace-only task key is not a durable session and **MUST NOT** be fabricated by session
    enumeration.

### Per-request endpoint fit

44. The endpoint's limits **MUST** reach the live client as declared > observed > unknown per limit
    (`model-profiles.spec.md` "Provider catalog" 9): the stored provider's exact model entry's
    positive `contextWindow`/`maxTokens` first, else what the provider's `/models` published and
    `provider-models.json` recorded. Selection **MUST** match the exact model id, not merely the
    provider. A process-wide `DOCKET_LLM_BASE_URL` override **MUST NOT** inherit stored limits from
    the provider it replaces; its window and output cap are unknown. An explicit `LoopConfig`
    value wins over the backend's own reported limit.
45. Before every task or compaction `ChatBackend.complete` call whose context window is known, the
    loop **MUST** estimate the complete prospective input — messages, tool-call metadata,
    advertised tool schemas, model/protocol framing — and add the output reserve. The shipped
    OpenAI-compatible backend **MUST** estimate from the same payload builder used for transport.
    This bytes/`CONTEXT_BYTES_PER_TOKEN` figure **MUST** be labelled an estimate and **MUST NOT** be
    folded into measured `TokenUsage`.
46. The output reserve is the configured or endpoint-registered maximum output; when there is none
    it **MUST** be `DEFAULT_MAX_OUTPUT_TOKENS`, so every known-window request is checked against a
    positive reserve. That reserve is budget arithmetic only: an endpoint whose output cap is
    unknown (neither declared nor observed) is sent no `max_tokens`, so the provider's own default
    applies and is reported as unknown, never as `DEFAULT_MAX_OUTPUT_TOKENS`. A known cap, declared
    or observed, is sent as `max_tokens`. When the cap is known, the reserve used for the budget
    check and the `max_tokens` sent are both the smaller of the cap and what the turn budget leaves
    after the estimated input (`token_budget` minus counted tokens minus the estimate), so a cap
    larger than the remaining budget never refuses a request by itself; only when fewer than
    `MIN_OUTPUT_TOKENS` (256) would be left does the full cap stay and the budget check refuse. The
    window check keeps the full cap. When the window is unknown, the loop **MUST** send the request
    unchecked and expose that no registered-window guarantee was applied; it **MUST NOT** invent a
    model/window table.
46a. After the first measured call of a turn, every input estimate used by the window check and the
    cumulative budget check **MUST** be scaled by `max(1, measured_input / estimated_input)` of the
    latest call that reported input tokens, so an under-counting estimator converges on the
    endpoint's own count and never shrinks below the raw estimate. The scaled figure is still an
    estimate: it **MUST NOT** be folded into `TokenUsage`.
47. When a task request is estimated over-window, the loop **MUST** invoke the durable, fail-closed
    session compactor with a smaller target, preserve complete assistant-tool/result atomic units,
    reload the accepted messages, and retry the estimate before transport. Every compactor
    completion is subject to the same request preflight with tools disabled.
48. If every eligible range is locally irreducible or the accepted summary plus output reserve
    still exceeds the registered window, the loop **MUST** make no task HTTP call and return
    `stop_reason="context_fit"`, `failure_kind="invalid_output"`, and an actionable error
    containing the estimated request, registered window, and output reserve. A failed, timed-out,
    truncated, empty, or tool-requesting summarizer instead **MUST** retain requirement 36's
    `compaction_failed` outcome and original failure kind, abort immediately, and never try another
    range. Already-durable history remains valid and no tool call/result unit is split.
49. Every prospective completion **MUST** emit a privacy-safe `request_fit` trace event containing
    its purpose (`task` or `compaction`), status (`fits`, `failed`, or `unknown_window`), estimated
    input, output reserve, registered window (or null), and an explicit estimate marker. It **MUST
    NOT** contain messages, prompts, tool arguments/results, or measured usage.

### Terminal response reservation

50. Every task and compaction completion **MUST** be preflighted against the cumulative turn budget
    before transport. The comparison **MUST** add counted usage (requirement 10) from prior
    completions to the prospective request-input estimate and the output reserve of requirement 46.
    Estimates **MUST NOT** be added to `TokenUsage`.
51. When a normal tool-enabled task request would exceed that prospective cumulative bound, the
    loop **MUST** make at most one finalization attempt. That request **MUST** explicitly ask for a
    truthful terminal response from work already completed, advertise no tools, preserve the
    current durable representation of the complete task and whole assistant/tool-result atomic
    units, and itself pass both the per-request context-window check and the cumulative
    turn-budget check before transport. This cumulative decision **MUST** be made on the complete
    current request before request-fit compaction; when it selects finalization, no raw
    current-turn unit may first be replaced by a summary merely to fit an ordinary round that the
    remaining turn budget cannot fund. If the complete request initially fits the cumulative
    budget and requirement 47 accepts a whole-unit durable summary to satisfy the endpoint window,
    later summary usage may still select finalization; that request **MUST** use the exact
    reloaded durable summary, never a stale pre-compaction snapshot. In both branches atomic units
    are preserved: raw units when budget selects finalization first, or the accepted durable
    replacement when window-fit compaction was selected first.
52. If the tool-free finalization request fails the endpoint-window check, it **MUST** return
    `stop_reason="context_fit"`; a context-window failure is never reported as cumulative spend. If
    the request fits that window but cannot fit the cumulative turn budget, the loop **MUST**
    return `stop_reason="token_budget"` and `failure_kind="invalid_output"` without another backend
    call. Its error **MUST** report the configured budget, measured usage, prospective input
    estimate, output reserve, and remaining measured budget without exposing message content.
53. A finalization response carrying any tool call **MUST NOT** dispatch or persist that call and
    **MUST** terminate with `stop_reason="token_budget"` and `failure_kind="invalid_output"`. A
    tool-free, non-truncated response is persisted normally and remains the sole successful
    `final_message` outcome. Backend failure, truncation, and timeout keep their fail-closed
    outcomes; none causes a second finalization attempt. A truncated ordinary or finalization
    response persists only its non-zero endpoint-reported usage metadata — never its assistant
    content or tool calls.
54. Entering or refusing finalization **MUST** emit one privacy-safe `budget_warning` event on the
    resolved trace coordinate. Its payload **MUST** distinguish the action/status and include the
    configured budget, prior measured usage, remaining measured tokens, normal/finalization input
    estimates, output reserve, and an explicit estimate marker. It **MUST NOT** contain messages,
    prompts, tool arguments, tool results, or model output.
55. After the backend-error and truncation checks keep their more specific outcomes, a successful,
    non-truncated response that carries tool calls and whose counted usage crosses the hard
    cumulative limit **MUST NOT** dispatch or persist tool calls from that response and **MUST**
    return the `token_budget` failure. Previous complete durable units remain intact. The same
    response without tool calls is persisted and returned as the `final_message` outcome.
56. Within one task request-fit evaluation, an accepted compaction of the current-turn suffix or
    historical prefix **MUST** be followed by exactly one reload and task-fit recheck, and that same
    logical segment revision **MUST NOT** be selected for compaction again. Segment revision
    identity **MUST** be private and content-derived: if a concurrent durable append changes a
    suffix between selection, locked compaction, reload, and the next fit check, the new revision
    remains eligible rather than being falsely marked irreducible. Only the newly appended,
    unprotected tail may be selected next; the already-accepted summary prefix **MUST NOT** re-enter
    its prompt. The other, still-untried segment remains eligible, and `compact_session` keeps its
    bounded internal hierarchical rounds. The outer convergence-attempt cap **MUST** be fixed when
    the evaluation starts so continuous appends cannot move it indefinitely. Before accepting either
    a fit result or a prospective cumulative-budget decision, the loop **MUST** compare the durable
    revision immediately after that preflight with the revision whose messages were estimated; a
    changed revision **MUST** be reloaded and preflighted under the same fixed cap, never
    transported stale. The current task anchor **MUST** keep its durable identity across those
    reloads rather than be rediscovered by matching text, so an appended user message with
    identical content remains part of the new suffix and cannot turn the original task or an
    accepted summary into historical prefix. The guarantee ends at that post-preflight revision
    check: an append completed afterward remains durable for a later turn but is not promised into
    the already-validated in-flight request. If no untried segment can reduce an oversized request,
    the loop **MUST** return `context_fit` locally without another summarizer or task transport. A
    later completed tool result starts a new request-fit evaluation. A failed compaction is not
    accepted progress and **MUST** abort under requirements 36 and 48 before another segment is
    attempted. This convergence guard **MUST NOT** add public fields to `request_fit` or expose
    revision fingerprints in traces.

### Consecutive tool denials

57. A denied, non-executed tool result **MUST** increment one per-turn consecutive-denial counter;
    an allowed, executed tool result (including an executed handler failure) **MUST** reset it.
    Other results neither increment nor reset it.
58. The default `max_consecutive_tool_denials` **MUST** be three, from
    `AGENT_LOOP_MAX_CONSECUTIVE_TOOL_DENIALS`, independently of `max_tool_calls`.
59. A model response's tool-call batch **MUST** keep the all-dispatched-or-none preflight. After
    dispatch, the complete assistant message and every answering tool result plus measured usage
    **MUST** be appended atomically before evaluating the consecutive-denial stop.
60. Once the configured consecutive-denial limit is reached, the loop **MUST** stop locally with
    `stop_reason="tool_denials"`, `failure_kind="invalid_output"`, and no further backend call. Its
    bounded actionable error **MUST** contain only the consecutive count and ordered denial kinds,
    never tool arguments, approval tokens, refusal reasons, or private values.
61. Each denied `tool_result` trace **MUST** include its stable `denialKind`; allowed/executed
    trace payloads **MUST NOT** invent a denial kind. When the dispatched `ToolResult` carries a
    non-empty `policy_id` or `reason`, the trace payload **MUST** include the matching
    `policyId`/`reason` field; either is omitted, not emitted empty, when the result carries none.

### Run cancellation

62. A pod-dispatch run's `RunCancellationSignal` **MUST** reach the production driver and every
    parallel worker as one optional `ToolContext.cancellation_check` callback. The callback reads
    persisted state and records first observation; a caller that supplies no callback **MUST** get
    unchanged turn behavior.
63. The loop **MUST** check cancellation before every compaction, ordinary task, and terminal
    finalization transport and immediately after each transport returns. A request already blocking
    may finish, but a post-request response **MUST NOT** be accepted, persisted, or allowed to start
    a tool. Endpoint-reported measured usage may still be durably accounted through the
    empty-message usage append; no raw response content may be retained.
64. A cancelled compaction response **MUST** fail closed before its summary changes durable
    history. The loop **MUST NOT** start the following task transport. Existing complete history
    units remain unchanged; only measured usage allowed by requirement 63 may alter the session
    record.
65. The loop **MUST** check immediately before each `dispatch_tool` call and immediately after an
    already-running handler returns. Cancellation before a handler begins produces a non-executed
    `ToolResult` with `denial_kind="run_cancelled"`. For every handler except `bash`, cancellation
    does not interrupt one already running (D-30): a Python handler runs to completion once
    dispatched. The `bash` handler (`run_bash`) accepts the same callback, polls it while the
    command runs, and on cancellation kills the process group and returns a complete cancelled
    outcome — see `security-gates.spec.md`'s cooperative-cancellation clauses.
66. Cancellation during a multi-call response **MUST** persist one complete assistant/tool-result
    unit: every call already admitted keeps its complete result and every remaining call receives
    `REFUSED [run_cancelled]: run cancellation requested before execution`. No later handler or
    backend request starts, no tool-call id is orphaned, and only actually admitted handlers count
    in `tool_calls_executed`.
67. Every cooperative stop **MUST** return `ok=False`, `stop_reason="run_cancelled"`, and
    `failure_kind="run_cancelled"`. `DocketDriver` **MUST** preserve that typed outcome in
    `TurnResult`, and dispatch retry logic **MUST NOT** classify it as transient.
68. A cancellation check immediately after an approval wait **MUST** prevent the handler even when
    a concurrent grant won. If the approval is still pending when cancellation wins, docket
    conditionally denies it through the single-winner approval transition; it never overwrites a
    grant/deny that already committed.
69. Cancellation checks **MUST NOT** split durable assistant/tool units or add raw cancellation
    content to traces. The `tool_call`/`tool_result` events identify admitted and explicitly
    cancelled call ids through their existing bounded fields.

### The approval_unavailable stop

70. A dispatched result whose `denial_kind == "approval_unavailable"` (`ToolContext.approval_mode ==
    "refuse"` on an `ask` verdict; see `security-gates.spec.md`) **MUST** stop the turn on its own,
    independently of `max_consecutive_tool_denials` — one such result is sufficient. The stop
    **MUST** occur only after requirement 59's complete-batch persistence (the assistant message,
    every answering tool result, and measured usage), never before. The loop **MUST** return
    `stop_reason="approval_unavailable"` and `failure_kind="invalid_output"`, make no further
    backend request, and its actionable error **MUST** name the tool, the call id, the policy id,
    and the reason from the first such result in the batch. `approval_unavailable_error()` is the
    single renderer of that error string (quoted `key=value` pairs), because `TurnResult` carries no
    structured field for them. A `gate_denied` or `invalid_call` result in the same or a later batch
    **MUST NOT** be made terminal by this requirement — both remain recoverable and bounded only by
    `max_consecutive_tool_denials` (requirements 57-60), exactly as under `approval_mode == "wait"`.

### The `llm_call` event

71. Every `ChatBackend.complete` call the loop makes — each ordinary task or finalization request
    and each summarizer request — **MUST** emit exactly one `llm_call` trace event, recorded before
    that call's own early-return handling runs. The event's `duration_ms` **MUST** equal the
    response's `latency_ms`; its payload **MUST** carry `model`, `provider`, `ok`, `finishReason`,
    `failureKind`, `inputTokens`, `outputTokens`, and `cachedTokens`, plus `iteration` for an
    ordinary task request or `purpose: "compaction"` for the summarizer's call. It carries
    `cacheWriteTokens` only when that count is positive, and `request` (per-part `bytes` and
    `estTokens`) only when the adapter reported request bytes. It **MUST NOT** carry a `cost_usd`
    value. Both call sites **MUST** also pass the exact `messages` sent for that call, so the payload
    **MAY** additionally carry `inputMessages`, `outputMessages`, `systemInstructions` and
    `systemInstructionsSha256` per `trace-store.spec.md`'s "Captured content" section — present only
    for the content classes an enabled exporter has been granted, and absent entirely when nothing
    is granted. Likewise every `tool_result` event **MUST** be given the text fed back to the model,
    recorded as `text` only while `toolResults` is granted (`trace-store.spec.md` requirement 27).

### `DocketDriver` observability export wiring

72. `DocketDriver.run_turn` **MUST** start the observability export pipeline before the turn, as
    `observability-export.spec.md` requirements 55-56 state.
73. `DocketDriver.run_turn` **MUST** flush the pipeline and write export health in a `finally`
    covering every return path, as `observability-export.spec.md` requirement 55 states. Export
    health is a side effect, never part of the returned `TurnResult`.
74. A hung export destination **MUST NOT** make `run_turn` take meaningfully longer than
    `EXPORT_FLUSH_TIMEOUT_S` beyond the turn's own time, as `observability-export.spec.md`'s
    invariants state.

### The approval_parked stop

75. A dispatched result whose `denial_kind == "approval_parked"` (`ToolContext.approval_mode ==
    "park"` on an `ask` verdict with no matching pre-grant; see `security-gates.spec.md`'s "Parked
    calls and single-use pre-grants") **MUST** stop the turn on its own, exactly as requirement 70
    stops it for `approval_unavailable`: independently of `max_consecutive_tool_denials`, only after
    that batch's complete-batch persistence, with no further backend request. The loop **MUST**
    return `stop_reason="approval_parked"` and `failure_kind="invalid_output"`, and its actionable
    error **MUST** name the tool, the call id, the policy id, the reason, and the created approval's
    token from the first such result in the batch. `approval_parked_error()` is the single renderer
    of that error string (the same quoted `key=value` shape `approval_unavailable_error()` uses,
    plus `approval_token`), so a consumer parses one format. A `gate_denied` or `invalid_call`
    result elsewhere in the batch **MUST NOT** be made terminal by this requirement.

### The no_progress stop (ADR 0019)

77. After each round of tool calls the loop **MUST** compute a round fingerprint: the set of
    `(tool name, canonical JSON of the parsed arguments with sorted keys, ok, sha256 of the tool
    output text)` over that round's calls. Denied and refused results count like any other, since
    their text is part of the digest. A round with no tool calls never counts.
78. The loop **MUST** keep the fingerprints seen in the turn and count consecutive rounds whose
    fingerprint was already seen; any new fingerprint resets the count. When the count reaches
    `LoopConfig.no_progress_rounds` the loop **MUST** stop with `stop_reason="no_progress"`,
    `ok=False` and `failure_kind="invalid_output"`, after the round's atomic persistence, with no
    further backend call; its error **MUST** name the repeated tool(s). The approval and denial
    stops (requirements 57-60, 70, 75) take precedence within the same round.
79. `no_progress_rounds` **MUST** default to `AGENT_LOOP_NO_PROGRESS_ROUNDS` (3, overridable through
    the environment variable of the same name); `0` **MUST** disable the check. Detection is per
    turn only, never across turns.

### Built-in tool output (ADR 0028)

80. `glob` and `grep` **MUST** print each match as a path relative to the first allowed root that
    contains it, never with the root prefix. Matches **MUST** be sorted by that printed path. A
    match under a directory, between the searched base and the match, named in `SKIPPED_DIRS`
    (`.git`, `node_modules`, `.venv`, `dist`, `build`, `target`, `vendor`, `__pycache__`) **MUST**
    be omitted.
81. `read` without a `limit` **MUST** return at most `READ_DEFAULT_LINES` (400) lines and stop before
    the numbered window passes `READ_DEFAULT_CHARS` (6,000) characters (at least one line is always
    returned), starting at `offset` (line 1 when absent); an explicit `limit` is honoured as given.
    Every returned line **MUST** be prefixed with its 1-indexed line number, then a tab. When lines
    remain after the returned window, the result **MUST** end with
    `[lines F-L of M; call read with offset=L+1 for more]`, where F and L are the first and last
    returned line numbers and M is the file's line count. The numbers are presentation only: text
    copied from the window without them **MUST** match the file for `edit`.
82. `glob`, `grep`, `read` and `fetch` results **MUST** pass through the same announced truncation
    as every other built-in, bounded by `DOCKET_TOOL_MAX_OUTPUT_CHARS`
    (`[truncated: <n> more characters]`). A result cut by that limit **MUST NOT** be
    indistinguishable from a complete one.
83. `builtin_registry()` **MUST** register `fetch` only while `FETCH_ALLOWED_DOMAINS` is non-empty,
    read when the registry is built. With an empty allowlist `fetch` **MUST NOT** appear in
    `specs()`, so the model is not offered it, and a call naming it is refused as an unknown tool
    like any other unregistered name.

### Request projection

84. Every task request, its preflight and the finalization request **MUST** project the durable
    history through `condense_history` (`session-history.spec.md` requirements 29-31), behind the
    composed system prompt, so the fit check measures what is sent. The projection **MUST NOT** be
    written back: `session.json` and the compaction candidates are built from the stored messages,
    and the newest `HISTORY_KEEP_FULL_RESULTS` tool results of the request stay whole, with older
    ones while they fit `HISTORY_FULL_RESULTS_CHARS`.

Requirement numbers 21, 22 and 76 are unused; the numbers above are cited by tests and code.

## Interface Contracts

### The turn loop

```python
StopReason = Literal[
    "final_message", "max_iterations", "max_tool_calls",
    "timeout", "token_budget", "truncated", "backend_error", "compaction_failed", "context_fit",
    "tool_denials", "run_cancelled", "approval_unavailable", "approval_parked", "no_progress",
]

MIN_OUTPUT_TOKENS = 256

class LoopConfig:                              # frozen
    max_iterations: int         # default AGENT_LOOP_MAX_ITERATIONS
    max_tool_calls: int         # default AGENT_LOOP_MAX_TOOL_CALLS
    max_consecutive_tool_denials: int # default AGENT_LOOP_MAX_CONSECUTIVE_TOOL_DENIALS
    no_progress_rounds: int     # default AGENT_LOOP_NO_PROGRESS_ROUNDS; 0 disables
    wall_clock_timeout_s: float # default AGENT_LOOP_WALL_CLOCK_TIMEOUT_S
    token_budget: int           # default AGENT_LOOP_TOKEN_BUDGET
    request_timeout_s: int      # default AGENT_LOOP_REQUEST_TIMEOUT_S
    max_tokens: int | None = None
    temperature: float | None = None
    history_budget_tokens: int | None = None # None resolves through budget_for_role
    summary_input_budget_tokens: int | None = None # None follows resolved history budget
    context_window_tokens: int | None = None # selected endpoint's registered input+output window

class AgentLoopResult:
    ok: bool
    output: str
    stop_reason: StopReason
    iterations: int
    tool_calls_executed: int
    usage: TokenUsage
    error: str
    failure_kind: FailureKind | None
    raw: dict[str, Any]
    retry_after_s: float | None   # from the backend's Retry-After, when it sent one
    model: str                    # the last response's resolved model
    provider: str                 # the last response's resolved provider

def run_agent_turn(
    backend: ChatBackend,
    registry: ToolRegistry,
    ctx: ToolContext,
    session_key: str,
    message: str,
    *,
    config: LoopConfig | None = None,
    clock: Callable[[], float] = time.monotonic,
    trace_project: str | None = None,     # defaults to ctx.project, then ctx.agent_id; traces only
    trace_session_key: str | None = None, # defaults to session_key; traces only
    trace_task_id: str = "",              # stamped on every trace event; traces only
) -> AgentLoopResult: ...

def approval_unavailable_error(result: ToolResult) -> str: ...
def approval_parked_error(result: ToolResult) -> str: ...
```

`ChatResponse` (the `ChatBackend` port's return type) carries the fields requirement 71's
`llm_call` event reads: `model: str`, `provider: str` (both from the resolved `Endpoint`),
`latency_ms: int` (wall-clock time around the backend request, `0` on a response no request was
sent for), and `request_bytes: dict[str, int]`.

### The driver

```python
class DocketDriver:                            # implements RuntimeDriver
    backend_factory: Callable[[str], ChatBackend | None]   # default: client_for
    registry_factory: Callable[[], ToolRegistry]            # default: builtin_registry
    mcp_loader: Callable[..., list[Any]]
    # called as mcp_loader(registry, role, project, launch=...); the default folds the
    # configured MCP servers (narrowed to the pod's mcpServers) in through load_mcp_tools,
    # before run_agent_turn narrows by role -- see mcp-client.spec.md

    def run_turn(
        self, agent_id, session_key, message, timeout=300, env=None, *, on_spawn=None,
        trace_project=None, trace_session_key=None, trace_task_id=None, model=None,
    ) -> TurnResult: ...
    def list_sessions(self, agent_id) -> list[SessionSummary]: ...
    def read_new_turns(self, agent_id, session_id, offset) -> SessionSlice: ...
    def usage(self, agent_id) -> UsageReport: ...
    def capabilities(self) -> DriverCapabilities: ...

def default_driver() -> DocketDriver: ...
```

`on_spawn` is ignored: the loop makes HTTP calls in-process and backs onto no OS process.

### Tunables

```text
AGENT_LOOP_MAX_ITERATIONS                default 20
AGENT_LOOP_MAX_TOOL_CALLS                default 40
AGENT_LOOP_MAX_CONSECUTIVE_TOOL_DENIALS  default 3
AGENT_LOOP_NO_PROGRESS_ROUNDS            default 3
AGENT_LOOP_WALL_CLOCK_TIMEOUT_S          default 300
AGENT_LOOP_TOKEN_BUDGET                  default 100000
AGENT_LOOP_REQUEST_TIMEOUT_S             default 120
DEFAULT_MAX_OUTPUT_TOKENS                4096 (constant)
CONTEXT_TOKEN_BUDGET_DEFAULT             6000 (constant; CONTEXT_TOKEN_BUDGET overrides)
POD_MEMORY_RENDER_MAX_BYTES              3000 (constant)
```

The seven `AGENT_LOOP_*` values are environment-overridable under the same names.
`DocketDriver.run_turn`'s own `timeout` argument overrides `wall_clock_timeout_s` directly — it is
the per-hop budget the dispatcher resolves, not a second, independently tuned number.

### Return values

- `AgentLoopResult.ok is True` **MUST** imply `stop_reason == "final_message"` and
  `failure_kind is None`.
- `TurnResult.cost_usd` from `DocketDriver.run_turn` **MUST** always equal `0.0`.

## Examples

### A turn with one tool call

```python
ctx = ToolContext(agent_id="demo", role="implementer", project="demo", roots=(workspace,))
result = run_agent_turn(backend, builtin_registry(), ctx, "agent:demo:default", "read notes.md")
# result.ok, result.output, result.usage.counted_tokens, result.tool_calls_executed
```

### A confused model that never stops requesting tools

Given a backend that always replies with another tool call, `run_agent_turn` with
`LoopConfig(max_iterations=20)` (the default) makes at most 20 model calls total, then returns
`AgentLoopResult(ok=False, stop_reason="max_iterations", failure_kind="invalid_output")` — never an
unbounded loop.

### A truncated reply carrying a tool call

```python
# response.truncated is True and response.message.tool_calls is non-empty
result = run_agent_turn(backend, registry, ctx, session_key, "go")
# result.ok is False; result.stop_reason == "truncated"; result.tool_calls_executed == 0
# load_messages(session_key) contains no trace of the truncated reply
```

### `DocketDriver` root resolution

Given an Implementer whose hop is handed a pipeline root under its own `tasks/` directory, a `read`
tool call resolves against that task worktree, not the codebase — the task worktree wins.

### A Reviewer cannot dispatch a write

```python
ctx = ToolContext(agent_id="rev-1", role="reviewer", project="demo", roots=(workspace,))
result = run_agent_turn(backend, builtin_registry(), ctx, "agent:rev-1:default", "edit it")
# the model was never advertised "write"/"edit"/"bash" (registry_for_role narrowed them out);
# if it requests one anyway, dispatch_tool's tool_result answers
# "REFUSED [invalid_call]: unknown tool ..."
# result.ok can still be True — the turn completes normally, just without that call executing
```

### The system prompt reaches the model

```python
# ws/SOUL.md exists, ws/WORKFLOW_AUTO.md exists
result = run_agent_turn(backend, registry, ctx, session_key, "hello")
# backend.complete's first call's messages[0].role == "system"
# that message's content folds in SOUL.md and the runtime projection of the
# startup contract -- never WORKFLOW_AUTO.md's raw prose (requirement 30)
# load_messages(session_key) contains no "system"-role message afterward
```

## Validation

### Pre-conditions

- `run_agent_turn` **MUST** be given a `ToolContext` whose `roots` already reflects the correct
  containment boundary for this call — the loop itself never inspects or widens it.
- `DocketDriver.run_turn` **MUST** be given an `agent_id` with a readable `.docket-meta.json` to
  succeed; a missing or malformed one is a defined failure (`failure_kind="invalid_output"`), not a
  precondition violation that raises.

### Post-conditions

- After a turn that stops with `stop_reason="final_message"`, `load_messages` for that session key
  **MUST** end with the final assistant message.
- After a turn that stops with `stop_reason="truncated"` or `stop_reason="max_tool_calls"`
  (batch-rejected case), `load_messages` **MUST NOT** contain any message from the rejected
  exchange.
- After any turn that dispatches at least one tool call, the session's trace file **MUST** contain
  exactly one `tool_call` and one `tool_result` event per dispatched call, in that order.
- When trace coordinates differ from the history coordinate, messages and measured usage **MUST**
  exist only under `session_key`, while loop trace events **MUST** exist only under
  `<trace_project>/<trace_session_key>`.

### Invariants

- Nothing outside the chokepoint's own internals **MUST** ever call a `Tool.handler` directly; the
  turn loop in particular never does.
- `DocketDriver.run_turn`'s `cost_usd` **MUST** be `0.0` on every call, regardless of how much token
  usage the turn recorded.
- Two agents **MUST NOT** be able to see each other's sessions through
  `DocketDriver.list_sessions`.
- A role's denied tool names **MUST NOT** be reachable through `dispatch_tool` for that role's turn
  — proven at the dispatch level (an "unknown tool" refusal), never merely by inspecting
  `RoleArchetype.denied_tools` or a `ToolRegistry`'s name set.
- The system prompt `run_agent_turn` composes **MUST NOT** appear in `load_messages`'s stored
  history for that session.

## Implementation

- `src/docket/core/agent_loop.py`: `run_agent_turn`, `LoopConfig`, `AgentLoopResult`,
  `StopReason`, `MIN_OUTPUT_TOKENS`, `approval_unavailable_error`, `approval_parked_error`; the
  `prompt_composed`, `session_compaction`, `request_fit`, `budget_warning`, `llm_call`,
  `tool_call` and `tool_result` emitters
- `src/docket/edges/adapters/docket_runtime.py`: `DocketDriver`, `default_driver`, the default
  `mcp_loader`, root resolution, the base-commit `RepoView` construction, the export start/flush
- `src/docket/core/runtime_driver.py`: `RuntimeDriver`, `TurnResult`, `DriverCapabilities`,
  `SessionSummary`, `SessionSlice`, `UsageReport`
- `tests/fakes.py`: `FakeDriver`, the port's canonical fake
- `src/docket/core/identity.py`: `compose_agent_prompt`, `compose_system_prompt`,
  `project_instruction_files`, `resolve_static_context_budget`, `memory_has_content`,
  `PromptSectionReport`, `REPO_INSTRUCTIONS_FRAME`, `REPO_SKILLS_FRAME`, `POD_MEMORY_FRAME`
- `src/docket/core/context.py`: `resolve_window_share_tokens`, `WINDOW_SHARE`,
  `TOOL_SCHEMA_RESERVE_TOKENS`, `estimate_tokens`, `budget_for_role`
- `src/docket/core/session.py`: `append_messages`, `load_messages`, `compact_session`,
  `condense_history`
- `src/docket/core/archetypes.py`: `registry_for_role`
- `src/docket/core/tools.py`: `dispatch_tool`, `ToolContext`, `ToolResult`, `builtin_registry`,
  `screen_tool_result`, the `skill`, `consult` and `fetch` tools
- `src/docket/edges/adapters/toolbox.py`: `SKIPPED_DIRS`, `READ_DEFAULT_LINES`,
  `READ_DEFAULT_CHARS`, `read_file`, `glob_files`, `grep_files`, `run_bash`, the output truncation
- `src/docket/core/skills.py`: `discover_skills`
- `src/docket/core/repo_view.py`: `RepoView`
- `src/docket/edges/adapters/system.py`: `git_read_blob`, `git_list_tree_dirs`
- `src/docket/core/pod_memory.py`: `render_entries`
- `src/docket/core/pod.py`: `PodSettings` (`projectInstructions`, `mcpServers`)
- `src/docket/core/pod_report.py`: the `docket pod show` report of project instructions
- `src/docket/core/llm.py`: `ChatBackend`, `ChatResponse`, `TokenUsage`, `FailureKind`, `Endpoint`
- `src/docket/edges/adapters/llm.py`: `client_for`, `resolve_endpoint`, `endpoint_from_spec`
- `src/docket/core/provider.py`: `resolve_limits`
- `src/docket/core/runs.py`: `RunCancellationSignal`, `current_cancellation_signal`
- `src/docket/core/dispatch.py`: `DispatchError`, the hop retry classification
- `src/docket/core/mcp_tools.py`: `load_mcp_tools`
- `src/docket/core/trace.py`: `trace_event`
- `src/docket/core/telemetry.py`: `start`, `flush`, `health`, `capture_classes`
- `src/docket/config.py`: `AGENT_LOOP_*`, `DEFAULT_MAX_OUTPUT_TOKENS`, `CONTEXT_TOKEN_BUDGET`,
  `CONTEXT_TOKEN_BUDGET_DEFAULT`, `CONTEXT_BYTES_PER_TOKEN`, `POD_MEMORY_RENDER_MAX_BYTES`,
  `SKILLS_DIR`, `TOOL_MAX_OUTPUT_CHARS`, `FETCH_ALLOWED_DOMAINS`, `EXPORT_FLUSH_TIMEOUT_S`,
  `EXPORTERS_HEALTH_FILE`, `HISTORY_KEEP_FULL_RESULTS`, `HISTORY_FULL_RESULTS_CHARS`
