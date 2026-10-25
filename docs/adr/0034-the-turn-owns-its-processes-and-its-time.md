# ADR 0034 (D-74): the turn owns its processes and its time; the network stays a tool

**Question:** a docket agent runs every tool call synchronously inside its hop. Does that, with the
turn's timeouts and the closed network, leave the agent unable to do the work a coding team does
(long test suites, a dev server under test, reading documentation, waiting on CI)? How do Claude
Code, Codex, OpenHands, Gemini CLI and Cline handle the same three things?

**Where decided:** 2026-10-25, by the maintainer, after a code reading, one recorded real run and
two probes on the live path. Cards P52-9 to P52-12 on `TODO.md`, and a fourth recipe on P52-6;
the analysis itself is internal.

## What was found

| Fact | Evidence |
| --- | --- |
| A real task (build, then review and risk in parallel) took about 3 min; `prepare` ran `npm ci` in 21 s; each `bash` of tests took 1 to 11 s. No limit fired. | the recorded trace of the 2026-10-24 run on `fab-dev` |
| In that run the model asked `bash` for `timeout: 600` and `timeout: 900` inside a 300 s turn, and docket accepted both: `_bash_handler` honours the argument without a ceiling. | `hops/application/builtin_tools.py:272` |
| The turn's wall clock is checked only between iterations; a tool in flight is never interrupted. A tool that overruns ends the turn with `failure_kind: timeout`, which is retryable, so the whole hop runs again with the same message. | `agent/loop_budget.py:135`, `agent/loop.py` module docstring, `hops/application/runner.py:42` |
| `claimedAt` is refreshed when a hop persists and before a retry, never during a tool; the crash sweep fails a claim at a fixed 1800 s while the resume lease is turn + verify timeout. | `tasks/application/record.py:585`, `queue.py:360`, `lifecycle.py:102` and `:159` |
| `nohup npm run dev > dev.log 2>&1 &` is classified `allow`, jailed or not. The child outlives the call: `run_bash` returned in 0.02 s and the process was still alive after the Python process exited. Docket has no handle on it, audits no exit, and kills nothing at the end of the turn or the task. | `classify_command` run on four shapes; `run_bash` probe with the real adapters, isolation off (not repeated under the jail) |
| `fetch` is GET-only, exact host, 15 s (60 s ceiling), 200 KB, and returns the raw HTML; `cut_output` then keeps the head. Against the local endpoint's 2,500-char cap the model sees the `<head>` element. No web search exists. | `platform/fetch.py`, `kernel/text.py:35` |
| `prepare` already plays the role of Codex cloud's setup phase (network for the install, cached by lockfile), and the `verify` gate already has its own timeout for a long suite. | `teams/workspace/prepare.py`, `hops/gates/post_hop.py:137` |

How the others do it, read on 2026-10-25 (sources in the internal analysis): Claude Code bounds
`Bash` at 2 min by default and 10 min at most, runs a command in the background with a completion
notice, converts a fetched page to markdown and has a search tool; Codex cloud gives the setup
phase the network and the agent none unless a domain-and-method allowlist is set; OpenHands returns
control after a soft timeout with the choice to wait, write input or kill; Gemini CLI returns the
background PIDs; Cline lets the agent proceed while a server runs and reads its new output. All
five agree: short commands with an explicit ceiling, a background mode with a handle, the install
network apart from the agent's, and web text destilled before the model sees it.

## Decision

1. **A tool's clock fits inside the turn's.** `bash`'s `timeout` is clamped to the turn's remaining
   wall clock, the model is told so when the clamp cut a command, and a running tool keeps the
   task's claim fresh, so one long command is never swept from under a live dispatcher. The
   stale-claim sweep never fires below the resume lease.
2. **A background process belongs to the turn that started it.** `bash` may start a process in the
   background and gets a handle; two tools read its output and stop it, both through
   `dispatch_tool`; every process still alive when the turn ends is killed and its exit traced.
   A trailing `&` in a plain command asks, jailed or not: it is the one shape that escapes the
   turn today.
3. **`fetch` returns text.** An HTML response is converted to plain text in docket's own process
   with the standard library before the cap applies; JSON and plain text pass unchanged. The
   allowlist, the deadline, the size cap and the redirect guard do not move. A result over the cap
   is kept whole and read back with `read`, which P52-8 gives every tool.
4. **Search is a server the operator declares, not a built-in.** A recipe shows the shape: cheap
   read-only researchers in a `parallel` group, `FETCH_ALLOWED_DOMAINS` for the hosts they may
   read, and an MCP search server declared `--kind read`, a self-hosted SearXNG first (no vendor,
   no key) and a hosted API through the same command when the operator prefers one. Search
   results are the cheap step (a title, a URL and two lines each); the page is the expensive one,
   so a kept page is read by window and searched with `grep` (P52-8), never read whole.
5. **A wait on a machine is an escalation, built when a run needs it.** The record and the
   `resolve` of ADR 0032 can carry a `wait` kind that a sweep resolves by probing; the card stays
   blocked until a recorded run shows a task failing or re-polling on CI or a deploy.

## Not doing

| Proposal | Why not |
| --- | --- |
| Raising the default turn or tool timeouts | No limit fired in the recorded run; a larger default hides the overrun instead of bounding it. |
| Opening the network by default | The posture is the same as Codex cloud's and is what docket sells; what limits the agent is the shape of `fetch`'s result, not the allowlist. |
| A PTY, `write_stdin` or interactive sessions | No recorded need; the two tools cover a server under test and a watcher. |
| A process that outlives its turn or is shared across hops | It would be state no hop owns and no audit closes; a long-lived service belongs to `prepare` or to the operator. |
| Wildcard or suffix entries in `FETCH_ALLOWED_DOMAINS` | Widens egress silently; an operator lists the hosts. |
| A native web-search tool | Rents a vendor; an MCP server declared read-only is the same capability under the same gate. |

## Deferred, with triggers

- **A tool-caused wall-clock stop made non-retryable.** With the clamp, a retry of a hop whose
  first attempt died on a clamped command most likely repeats the command. Trigger: a recorded
  `hop_retry` whose previous attempt's last tool result carries the clamp marker.
- **Background processes under the Docker backend.** The first card refuses `background` there
  (`docker kill` by container name already exists for the timeout path). Trigger: a pod on the
  Docker backend that asks for one.
- **A `wait` escalation** (decision 5): P52-12, blocked on a recorded run.
- **`fetchMode: ask` on the pod.** `FETCH_ALLOWED_DOMAINS` is one process-wide list, exact by
  host, so a researcher that finds its answer on an unlisted host can only report that it could
  not read it. With `ask`, a `fetch` off the list becomes an ordinary escalation (`approve_once`,
  `approve_task`; denied by `whenNobody` when nobody is there) instead of a refusal in the
  handler; the list stays the boundary and a person widens it per task, as the `no-egress` recipe
  already asks on every `fetch`. Neither wildcards nor a per-pod list that widens the global one.
  Trigger: the first recorded `web-research` run in which a `fetch` is refused as
  `fetch_not_allowed`.
- **A built-in `search` over a configurable JSON endpoint** (SearXNG's `format=json`), the shape
  `fetch` has: no process to spawn, a fixed compact result format. Trigger: a recorded run where the
  stdio search server's per-turn start-up is a measurable share of the hop.
