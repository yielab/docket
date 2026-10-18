# ADR 0028 (D-64): context in layers, and a budget that counts new tokens

**Question:** four steps of a sibling project, dispatched through Tack on 2026-10-18, stopped
on `AGENT_LOOP_TOKEN_BUDGET=100000` in three cases out of four, and the fourth (a critic) lost
a finished verdict. No single request was large. What must docket change so that a step sends
the model what it needs once, and the budget counts what is really spent, **without raising any
limit**?

**Where decided:** 2026-10-18, by the maintainer, from a measured brief reviewed against the
code (`develop` at `5dda9d37`). Answers recorded in "Decisions taken".

## Evidence (measured 2026-10-18, 03:38-03:41Z, four steps, 369,263 counted tokens)

| Where the counted tokens went | Share |
| --- | --- |
| old tool results re-sent on every call | 64 % |
| system prompt, tool schemas and task, repeated on every call | 25 % |
| old assistant text and tool arguments | 8 % |
| output | 3 % |

- The largest single request was 25,806 tokens. The budget sums every call of the step with
  cache reads at full weight: `core/llm.py::TokenUsage.total_tokens` is `input + output`, and
  `cached_tokens` is a subset of `input`.
- A finished answer that crosses the budget is discarded:
  `_TurnState.call_backend_and_handle_response` checks the budget before it accepts a reply
  with no tool calls. The critic ended `finish_reason=stop`, 1,292 tokens over.
- `glob` has no character cap, prints absolute paths and sorts by mtime
  (`edges/adapters/toolbox.py::glob_files`); one `glob **/*` returned 41,964 characters, 78 %
  of them the repeated checkout prefix, and was re-sent four times (84 % of its step). `read`
  returns the whole file up to 30,000 characters by default; a 12,475-character generated file
  was 26 % of another step. `fetch` reads up to 200,000 bytes with no `_truncate`, and is
  offered with an empty domain allowlist (seven refused calls).
- The critic re-read the note the researcher had just written and re-sent it nine times
  (about 30,000 tokens): `_implementer_diff_probe` hands `files_changed`/`diff_ref` to the next
  hop for the `implementer` role only, and `diff_ref` is a branch name, not content.
- The critic had 0 % cache hits over 11 calls (70-82 % on the other providers): nothing in
  `src/` marks `cache_control`. The project roots sit in the live contract, in the middle of
  the system prompt (`core/identity.py::compose_system_prompt`), and HEARTBEAT.md, whose
  dispatch block changes per task, is composed after it, so no prefix survives between tasks.
- Without a registered `max_output_tokens` neither the prospective budget check nor the
  request-fit check runs (`prospective_budget_error` returns early; `preflight_request` traces
  `unknown_window`). The bytes-per-token estimate was 1.8x short on text full of paths and
  UUIDs (13,462 estimated, 23,692 measured).
- The pod's dollar estimate charges cache reads twice (`core/utils.py::estimate_cost_usd`
  prices all `input` and then `cache_read` again).
- Each member's files contradict the live contract: AGENTS.md tells the agent to read and
  write HEARTBEAT.md and `memory/`, which the contract forbids; MEMORY.md says "Fill on first
  run" but is read-only in a pod task, so it is never filled; SOUL.md and TOOLS.md name the
  source checkout instead of the task worktree; SOUL asks for `<promise>DONE</promise>`, which
  nothing reads.
- The memory pipeline exists and is unwired in pod tasks: daily logs under `memory/` are
  distilled into MEMORY.md only by `pod reset`, and nothing writes a daily log from a task.

## The decision, on one screen

1. **Context is composed in layers, stable first, each with one owner.**

   | Layer | Owner | In the request |
   | --- | --- | --- |
   | SOUL.md: role, limits, output contract | archetype template | system, no paths, no task data |
   | AGENTS.md (member): method and tool strategy | archetype template | system, never contradicts the contract |
   | Live contract | docket | system, **without project roots** |
   | Repository instructions and skills | the repository | system, framed untrusted, capped |
   | Pod memory | docket (point 7) | system tail, framed untrusted, capped; absent when empty |
   | Tools | docket | the `tools` parameter only; TOOLS.md is no longer composed |
   | HEARTBEAT.md | docket | never in a pod task |
   | Task message | dispatch | the task, the brief once, the checkout roots, a derived repository map, what the previous step delivered |

   TOOLS.md is dropped from the prompt rather than generated: the tool schemas already travel
   in every request, filtered to the effective set, so a generated TOOLS.md would repeat them.
   Usage rules live in each tool's description; resources already arrive as
   `DOCKET_PORT_BASE`/`DOCKET_SCRATCH_DIR`.

2. **The budget counts new tokens.** Counted = `input - cache_read + output` (cache writes are
   part of input and count). A reply with no tool calls that crosses the budget is accepted: it
   is already paid. A model with no registered output bound gets
   `config.DEFAULT_MAX_OUTPUT_TOKENS` as its reserve, so the prospective check runs. After the
   first call of a turn the input estimate is scaled by `max(1, measured / estimated)`. A task's
   `maxTokens` uses the same count. `max_iterations` and `max_tool_calls` still bound a runaway
   loop whose input is all cache reads. The dollar estimate stops charging cache reads twice.

3. **Tool output has a budget.** `glob` and `grep` print paths relative to the first root, sort
   by path, skip a fixed list of vendored and generated directories (`.git`, `node_modules`,
   `.venv`, `dist`, `build`, `target`, `vendor`, `__pycache__`) and pass through the same
   `_truncate` as every tool. `read` returns a numbered window by default and says how many
   lines remain. `fetch` is truncated like the rest and is not registered while
   `FETCH_ALLOWED_DOMAINS` is empty.

4. **History inside a step does not grow quadratically.** When a request is built, a tool
   result older than the last K results becomes a one-line notice
   (`[read src/x.ts: 340 lines, omitted; read it again if needed]`), and so do large
   `write`/`edit` arguments (`[wrote content/x.md: 8,329 characters]`). The newest result stays
   whole; errors stay short. The projection is deterministic and applied to the request only,
   never to `session.json`, so the prefix before the newest condensed message is byte-identical
   between calls and the provider cache loses only the last K messages. K is chosen with the
   replay bench (measured: K=1 saves 53 %, K=2 39 %).

5. **Between steps, deliver, do not rediscover.** The next hop's message carries what the
   previous hop produced (the diff, including new files, capped) for every role that changed
   the tree, not only the implementer. It does not carry the list of files the previous hop
   read: that invites re-reading.

6. **Order for the cache.** The system prompt and tool schemas are byte-identical between two
   tasks of the same member. Anthropic models get `cache_control` at the end of the stable
   prefix and on the last message, including through a gateway, once one real call (approved by
   the maintainer, it costs money) shows the gateway honours it.

7. **Pod memory, governed.** One `memory.json` per pod, written by `edges/store.py`, read by
   every member, replaces the per-member daily-log pipeline in pod tasks (the old seeding and
   the pod-task distillation are deleted under D-57).
   - A step's result may end with a short memory section. docket parses it into typed entries
     of a closed set: `generated` (a path not worth reading), `command` (a command and its exit
     status), `pitfall`, `convention`. Each entry has a path or command field, one sentence of
     at most 200 characters, and provenance (task id, date, commit). Free imperative text is
     refused.
   - **Acceptance is mixed.** `generated` and `command` entries that docket can verify (the
     path exists at the task's commit; the command's exit status is in the task's trace) are
     accepted automatically. `pitfall` and `convention` entries wait in the inbox until the
     operator approves them. A step that called `fetch` writes nothing automatically.
   - Every entry passes the `pre_input` screen before it is stored. Entries are deduplicated by
     (kind, path or command), capped in number, and rendered into the system tail under the
     same untrusted frame as repository instructions, never in docket's voice. An entry whose
     path no longer exists in the checkout is omitted from the prompt, not deleted.
   - Every change writes a `memory_update` trace event and an audit entry. The operator can
     list, revert one entry and reset the pod's memory under `docket pod`.
   - MEMORY.md stays as the operator's free notes; its "Fill on first run" template goes.

8. **Measurable without reconstruction.** Each `llm_call` carries the request's size by part
   (system, tools, history: tool results, assistant text, user) in bytes and estimated tokens.
   A hop's usage and the task's `byModel` carry `input`, `cached`, `cacheWrite`, `output` and,
   when reported, `reasoning`. The API reports the step budget it enforces (`tokenBudget`). All
   additive inside API 5.

## Decisions taken (2026-10-18)

- Cache reads do not count toward the budget: yes.
- Pod memory is designed and built in this phase, not deferred; scope is the pod, acceptance is
  mixed, and the repository map is derived per task, separately from memory.
- The two paid runs (the gateway `cache_control` check and the final rerun of the four steps)
  are approved; each is announced before it runs.

## What this does not do

- Raise any limit, or add a per-provider tokenizer.
- Parse `.gitignore`: a dependency-free parser is a new component with its own defects; the
  fixed skip list plus the `read` window cover the measured cases.
- Count retried hop attempts into the budget: the measured runs had no `hop_retry`. Trigger: a
  `hop_retry` after a `token_budget` stop in a real run.
- Generate TOOLS.md, or carry the previous hop's read list.
- Commit the measured sessions: they hold a private repository's content. The real sessions
  stay in gitignored `internal-docs/context-replay/`; the committed fixtures are an anonymized,
  shape-preserving derivation (same message structure, sizes, tool names, usage and verdict
  line; every path segment and text replaced by a same-length placeholder).

## Acceptance for the phase

On the replay bench, against today's policy, every step **sends** less than half the input
tokens, none reaches the budget under the new count, and the critic's verdict is kept. Both
numbers are required: the new count alone would pass a "counts less" test without sending one
byte less. A final real run of the same four steps, approved by the maintainer, compares the
evidence table above before and after.
