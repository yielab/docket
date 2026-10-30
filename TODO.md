# TODO — active task board

> **This is docket's single standing TODO file.** It holds the executable cards for whatever phase is
> currently active in [ROADMAP.md](ROADMAP.md). Do **not** create per-phase task files — when a phase
> finishes, clear its cards (the phase record stays in ROADMAP) and append the next phase's cards here.
>
> **History lives elsewhere.** Every closed wave and phase section that used to sit in this file is
> archived verbatim in [docs/cycles-ended/](docs/cycles-ended/README.md) (`todo-waves.md`, with a
> SHA-256 manifest). This file holds only the usage rules, the active section and planned sections.
> Do not mine the archive for work.
>
> ---
>
> **Scheduling rule:** schedule by **file contention**, not phase number. Cards that edit the same
> files run one after the other, and work that would touch the same files twice belongs to one card.
> Parallel lanes are allowed only when they share no file, spec, persisted state or live environment;
> finishing a card well matters more than running two at once.
>
> **NO ACTIVE WAVE.** Phases 52 to 54 (D-73 to D-76, ADRs 0033 to 0035 and the 0011 amendment) closed
> 2026-10-29; their sections are archived and what they leave open is under "Phases 52 and 53" and
> "Phase 54" in the follow-ups below. **Planned: Phase 55** (D-77,
> [ADR 0036](docs/adr/0036-a-pod-works-outward.md)): a pod works outward, on its own schedule; twelve
> cards P55-1..P55-12 over four waves, cut by file ownership. **Wave 1 merged 2026-10-30** (P55-1, P55-5,
> P55-7, P55-11); Wave 2 (P55-3, P55-6) is next.
> Phase 51 closed 2026-10-25 (D-72, [ADR 0032](docs/adr/0032-one-escalation-record-and-one-resolve.md));
> its loose ends are under "Escalations". The integration branch is `develop`. A new phase starts from a
> measured trigger or a maintainer request.

## How work runs on this board (read before claiming a card)

1. **One card is one worker run.** Its steps are ordered; each step ends green and committed. A run
   that does not finish parks at its last green commit and the card's Status names what is left; the
   next run continues the same card. A card is never split into sub-cards to make it fit.
2. **Claim.** Set Status to `IN-PROGRESS (@who)`; one owner per card. The worker gets a worktree made
   by hand from the integration branch's current head (`git worktree add -b <branch>
   .claude/worktrees/<card> <sha>`), and its own `DOCKET_HOME` and temp directory in the scratchpad.
3. **Read bounded.** `python3 .agents/skills/docket-roadmap/scripts/card_packet.py <CARD-ID>`, then
   the card's own read list. Never all of `ROADMAP.md`, `TODO.md`, `CLAUDE.md` or a spec directory.
   A task worktree has no `internal-docs/` (gitignored); a card needs only itself and tracked files.
4. **The layer rule** is ADR 0030's table, enforced by `tests/architecture/`: the contexts are layered
   `platform < governance < agent < models < observability < pipeline < teams < sandbox < operator <
   tasks < hops` and a context imports only those below it; `kernel` imports nothing outside itself;
   a `domain/` is pure; only `interfaces/` talks to the user; `bootstrap.py` is the only module that
   names a concrete adapter. Two invariants never move: every tool call passes `dispatch_tool`
   (`agent/tools/registry.py`), and docket-owned JSON is written only by `platform/store.py`.
5. **The testing budget, the same for every card.**
   1. Per commit: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run
      pytest --co -q` (about 10 s). No test runs.
   2. While iterating: only the tests of what the step changed, by path, each under `timeout 120`.
   3. The card's gate, as the card names it, in a few minutes.
   4. A pure move or rename adds no test: `pytest --co` and `tests/architecture` are its check. A
      behaviour change adds a failing test first, placed by lane (`specs/test-framework.md`).
   5. After each merge the integrator runs the default suite once, in parallel (`uv run pytest -n auto
      --dist loadfile -q --tb=line -p no:cacheprovider > <file>`, about 85 s), reads only the `FAILED`
      lines, fixes by cause and re-runs `--lf`. Never a second full run for the same merge. What
      each check costs, measured, is in `.agents/skills/docket-spec-work/references/validation.md`.
   6. Goldens, the agent lane, `scripts/maint/pytest-without-sandbox.sh`, the escape matrix,
      `validate-specs.sh`, the generated-docs checks and the real run: once, at
      the phase close. The agent lane (about 5 min) runs on a committed tree: its release check
      refuses any uncommitted path.
   7. **Stop rule:** a check that fails again after one fix stops the step. Park with the failing line
      and the hypothesis. No third attempt, no "until green", no background process or polling, no
      `git stash` (a WIP commit sets work aside).
   8. **A script is a means, not a deliverable.** A one-shot script (planner, path rewriter,
      converter) exists to save effort on the card's goal. Write it once, run it, review its output,
      and finish by hand whatever it did not cover. If it is wrong after one fix, stop improving it
      and do the remainder by bounded edits. Polishing, generalizing or testing a throwaway script is
      out of scope; it is never committed unless the card says so.
6. **Baselines only shrink.** A baseline file is rewritten (`--write`) only after the violations are
   gone, and its diff is deletions only. A new guard is trusted only after it was seen failing on a
   planted case.
7. **No behaviour change** unless the card says so: the HTTP API 6 tests, the CLI goldens and the
   `docket_runtime` facade stay byte for byte. **No re-export or shim:** a replaced name is
   deleted in the same change, with no alias or compatibility reader.
8. **Central files are integrator-owned:** `TODO.md`, `ROADMAP.md`, `README.md` metric counts and
   `CHANGELOG.md`. A worker reports what shipped; it does not edit them.
9. **Commits:** `Type: description`, ASCII only, a detailed body, no AI or assistant attribution.
   Scrub `/home/<user>` paths and real names from every diff.

**Status:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs X)` · `PARKED (left: X)` · `DONE`.
**Size:** S ≈ one short run · M ≈ one run · L ≈ one long run that may park once · XL ≈ two cards'
scope in one pass over the same files, parks at least once.
**Branch model (D-52):** card branches base on and merge into the integration branch (`develop`).
`main` moves only
by a fast-forward from `develop` when the maintainer cuts a release. Tags and release jobs originate
from `main`.

## ○ PHASE 55 PLANNED — a pod works outward, on its own schedule (D-77, ADR 0036)

> Planned 2026-10-30 from the maintainer's scoped request of 2026-10-29: pods that do work other than
> code (research, write, report), act outside the machine (send a message, navigate and act on a web
> site, call an external API, another agent or an MCP server), on a schedule or a recurring time,
> with roles that act outward under their own security and escalation, without changing today's
> governance. [ADR 0036](docs/adr/0036-a-pod-works-outward.md) holds the nine findings (three e2e
> probes on a pod with no repository, one browser probe through docket's MCP client, 2026-10-29/30,
> and four read in the code), the twelve decisions and the refusals. The rule every card keeps: **everything new is a capability no
> existing role or pipeline has unless it names it.** Each card's trigger is one measured finding
> or the request itself; no metric or saving is invented. Cards are cut by **file ownership** into
> four waves.

### How a Phase 55 card runs (read before claiming one)

- Spec → failing test → smallest change. Bump the owning spec (MINOR unless the card says MAJOR)
  with `Last Updated` and the `specs/README.md` row in the same commit.
- **Read bounded:** `card_packet.py P55-<n>`, ADR 0036 §"Decision" (the one item the card names),
  the spec section the card names, the files it names. Nothing else; a worktree has no
  `internal-docs/`.
- **The oracle is the e2e lane** (42 s, `tests/e2e/`): every card except P55-2 and P55-12 changes a
  tool's output, the wire, the home layout or the HTTP API, so each runs it. `docs/commands.md` is
  generated: when two cards of a wave change the CLI, the integrator regenerates it at each merge
  instead of merging it. P55-1 adds
  `tests/e2e/test_workdir_pod.py`, the first e2e world on a pod with no repository; later cards add
  their world to that file rather than start a second one.
- **Nothing today's pods see changes** unless the card says so: the default `software` pipeline's
  composed hop messages stay byte-identical (`tests/integration/hops/test_hop_carryover.py::test_small_task_byte_identical_to_pre_cap_behaviour`),
  the HTTP API 6 tests and the CLI goldens stay byte for byte. `send` is a kind no existing role
  names; `lifetime` defaults to `call`; a `wait` step and a routine exist only where someone writes
  one.
- **Every card:** focused tests by path under `timeout 120`; before handoff `ruff`, `mypy src`,
  `pytest --co -q`, `tests/architecture`, `comment_lint.py --check` on touched files. Cards that
  touch a CLI command (P55-2, P55-3, P55-5, P55-7, P55-9, P55-10, P55-11) also run
  `gen_cli_docs.py --check`.
- **Spend by model.** Haiku runs P55-12 and, on any card, the spec and doc edits the card spells
  out; Sonnet runs behaviour in `src/`; no Opus on this phase. A card names at most eight files
  with locators; a worker that needs more parks with the missing locator.
- **Near the 700-line rule:** `governance/policy.py` 658 (P55-8 puts the quota in a new module),
  `teams/identity.py` 659. No function-local import.
- **Integrator seams:** the full default suite once per merge, `--lf` after; the agent lane,
  goldens, `pytest-without-sandbox.sh`, `validate-specs.sh` and one real run at the phase close: a
  workdir pod on the `outward` recipe whose routine fires, whose actor's `send` (an MCP server that
  only logs) parks for a person, and whose `wait` step resumes it.
- Workers in `.claude/worktrees/p55-<n>`, one card per worktree. Delta-only handoff with the
  end-of-work control summary.

### P55-1 — the text a hop reads follows the workspace kind, and the first workdir e2e

**Status:** DONE (2026-10-30; the Lead's workdir text is the prompt `hop/lead-workdir`, not step `instructions`, which would drop `output: handoff/v1`; `when_cwd` falls back to `workDir`; `POD_TEMPLATE_VERSION` 6) · **Size:** M · **Model:** Sonnet (Haiku for the prompt files) · **Kind:**
behaviour + data + spec + e2e

- **Trigger:** ADR 0036 findings 1-2, measured 2026-10-29 on a `content` workdir pod with a scripted
  model: the Lead's hop read "Working directory: the repository root"; its identity named
  "repository" 3×, "code" 2×, "git" 1× (`templates/prompts/identity/lead.md:32-34`); the writer's
  system prompt carried "repository map" and `grep` 2× (`teams/builtin_roles.py:19-35`, inherited
  via `teams/roles.py:363`) and the tools `bash`, `edit`, `process_output`, `process_stop`; the
  `MEMORY.md` seed asks for the codebase README (`teams/agent_memory.py:222-243`). The
  `web-research` Lead gets "plan for the Implementer" (`templates/recipes/web-research/pipeline.yaml:8`,
  `templates/prompts/hop/lead.md:9`). No e2e case dispatches a workdir pod.
- **Goal:**
  1. The hop root line (`hops/application/compose.py`, `rg -n "repository root"`) says "the
     working directory" when the pod is `workdir`; the repository-map section is omitted there.
  2. `templates/prompts/hop/lead.md` and `identity/lead.md` name "the role that follows in the
     pipeline" and "the workspace", not the Implementer, code or git; the built-in `software`
     pipeline's Lead step carries today's Implementer sentence as its `instructions`, so its
     composed message does not change.
  3. The `## Method` block and the `MEMORY.md` seed have a workdir variant chosen by
     `workspaceKind` (`builtin_roles.py:19-35`, `agent_memory.py:222-243`).
  4. The `web-research` recipe's Lead step declares its own instructions.
  5. The writer starter archetype denies `exec` (`builtin_roles.py:170`); `role-archetypes.spec.md:254`
     says what is then true.
  6. `tests/e2e/test_workdir_pod.py` (new): the `content` blueprint on a workdir pod runs a task to
     `done` with no worktree and its output in the working directory; a custom pipeline with a
     `REJECT → draft` route and a `run:` step whose cwd is the working directory; a `baseRef` on a
     workdir pod fails the task `base_ref` before any hop (untested today,
     `teams/workspace/worktree.py:107-111`).
- **Non-goals:** the `send` kind; any change to the Implementer, Reviewer or Tester text; pod
  memory with non-path subjects (deferred); the model pin (P55-2).
- **Spec:** `pod-blueprints.spec.md` (MINOR: what a workdir pod's hops read),
  `pod-dispatch.spec.md` "Bounded hop prompts" (MINOR), `role-archetypes.spec.md` (MINOR: writer
  `exec`, Method variant).
- **Change:** `hops/application/compose.py`; `teams/builtin_roles.py`; `teams/agent_memory.py`;
  `templates/prompts/hop/lead.md`; `templates/prompts/identity/lead.md`;
  `templates/recipes/web-research/pipeline.yaml`; `tests/e2e/test_workdir_pod.py` (new).
- **Acceptance (RED first):**
  - `test_workdir_pod.py`: the Lead's first request on a workdir pod contains "working directory"
    and not "repository root", "Implementer" or "repository map"; the writer's tools exclude
    `bash`; the task is `done` with `worktree: null`; the `run:` step's `command_step` payload has
    `exit: 0`; the `baseRef` task has `failureKind: base_ref`. Oracle: the fake model's recorded
    requests and `docket task show --json`.
  - The `software` pipeline's composed hop messages are byte-identical before and after
    (`test_hop_carryover.py::test_small_task_byte_identical_to_pre_cap_behaviour`, CLI goldens
    `verify-all` 9/9).
  - `pod validate` on the `web-research` recipe passes; its Lead request contains no "Implementer"
    (`tests/integration/teams/`).
- **Gate:** focused files, then the e2e lane (42 s), goldens for the CLI cases that render a prompt.
- **Contention:** Wave 1. `builtin_roles.py` and `role-archetypes.spec.md` are continued by P55-3
  (Wave 2) and P55-2 (Wave 3).

### P55-2 — a custom role pins its model like a built-in one

**Status:** TODO (after P55-3, shares `role-archetypes.spec.md`) · **Size:** S · **Model:** Sonnet ·
**Kind:** behaviour + spec

- **Trigger:** ADR 0036 finding 7: `teams/model_selection.py:432` keeps `role.<name>` only when
  `name in ROLE_CLASS`, so `docket setup model set role.actor <id>` is dropped silently, while
  `role-archetypes.spec.md:553` tells the operator to use that command and `teams/roles.py:328`
  points to the step's `model:` instead.
- **Goal:** `setup model set role.<name>` accepts any role the registry knows (built-in, starter,
  operator or pod overlay) and refuses an unknown one by name; `model_selection.py:181,220` resolve
  a custom role's pin before its `modelClass`. The spec sentence and the `roles.py:328` hint agree
  with the code.
- **Non-goals:** per-role USD budgets; a model id on the role document itself.
- **Spec:** `role-archetypes.spec.md` (PATCH: the sentence at :553 made true), `model-profiles.spec.md`
  if it lists the `role.` keys (PATCH).
- **Change:** `teams/model_selection.py`; `teams/roles.py:328` (the hint); the two spec sentences.
- **Acceptance (RED first):** `tests/unit/teams/test_model_selection*.py`: `set role.actor X` is kept
  and resolves for a pod whose overlay defines `actor`; `set role.nobody X` exits non-zero naming the
  role; a built-in role's pin is unchanged. CLI golden for the refusal.
- **Gate:** the unit file, `gen_cli_docs.py --check`, goldens.
- **Contention:** Wave 3.

### P55-3 — `send`: a fourth tool kind for actions outside the machine, held only by a role that names it

**Status:** TODO · ready, P55-5 merged 2026-10-30; shares `kernel/mcp.py` and `mcp_tools.py` · **Size:** L ·
**Model:** Sonnet (Haiku for the recipe files) · **Kind:** behaviour + spec + data

- **Trigger:** ADR 0036 finding 3: `ToolKind = Literal["read", "write", "exec"]`
  (`agent/tools/registry.py:37`); `McpServerConfig.kind` is `read | write`, default `write`
  (`kernel/mcp.py:33`); a role narrows by capability only (`teams/roles.py:205-217`) and the pod's
  `deniedTools` refuses non-built-in names (`teams/pod_settings.py:337-358`). On the 2026-10-29
  probe the only lever that stopped a draft leaving the pod was a policy `ask` on one tool name.
- **Goal (ADR 0036 decision 2):**
  1. `send` joins `ToolKind` and the server `kind` enum; `docket setup mcp add --kind send`. A
     `send` tool acts outside the machine: sends a message, submits a form, posts, books, pays, or
     asks another agent to.
  2. A `send` tool reaches a role only when the role's `tools` allow-list names it
     (`mcp__<server>__<tool>` or the server); `cannot: [send]` is accepted and redundant.
     `BUILTIN_TOOL_KINDS` gains no `send` entry: no built-in tool acts outside the machine.
  3. The check at `docket pod update` / `pod validate`: a role whose allow-list names a `send` tool
     and that still holds `fetch` or a tool of a `read` MCP server is refused by name with the rule
     in the message; a step's `tools` may narrow a role to satisfy it.
  4. `templates/recipes/outward/` (`pod.yaml` with `workspaceKind: workdir`, `pipeline.yaml`,
     `roles/actor.yaml` + `.md`, a policy `ask` on every `send`, `README.md`): researcher → writer
     → critic (verdict APPROVE/REJECT, one rework) → actor. The README shows three server shapes,
     each declared twice where it both reads and acts: a mailbox (`read`) and its sender (`send`); a
     page reader (`read`) and a browser that clicks (`send`, `lifetime: hop`, P55-5); an agent
     reached through an MCP server (`read` when it informs, `send` when it acts).
- **Non-goals:** the audit row and the approval view (P55-4); the quota (P55-8); any change to `write`'s semantics;
  a new `EscalationKind`; shipping any third-party MCP server.
- **Spec:** `mcp-client.spec.md` (MAJOR: the `kind` enum; Requirement 32 text), `role-archetypes.spec.md`
  (MINOR: `send` opt-in and the read/act separation), `security-gates.spec.md` (MINOR: the capability
  table), `pod-blueprints.spec.md` (PATCH: the recipe listed).
- **Change:** `agent/tools/registry.py:37`; `kernel/mcp.py`; `agent/tools/mcp_tools.py:145-151`;
  `teams/roles.py` (narrowing and the check); `teams/pod_settings.py:337-358`;
  `interfaces/cli/commands/mcp.py`; `templates/recipes/outward/**` (data).
- **Acceptance (RED first):**
  - `tests/unit/teams/test_role_tools_and_identity.py`: a role with no allow-list offered a `send`
    MCP tool does not see it; a role naming it does; `cannot: [write]` leaves a `send` tool alone.
  - `tests/integration/agent/tools/`: one fake MCP command registered `--kind read` and `--kind send`
    makes two servers whose tools carry their kinds.
  - `pod validate` on a role that names a `send` tool and `fetch` exits non-zero naming the role and
    both tools; the `outward` recipe validates.
  - e2e (`test_workdir_pod.py`): a world on the `outward` recipe with a fake MCP server that logs
    each action: the actor's `send` call parks `waiting_approval`, `approve_once` resumes it to
    `done`, the server's log holds exactly one action, and the researcher's requests never offer
    the `send` tool.
  - A pod with no `send` server is unchanged: the HTTP API 6 tests and CLI goldens are byte for byte.
- **Gate:** the unit and integration files, the e2e lane, `gen_cli_docs.py --check`, goldens.
- **Contention:** Wave 2. `gate.py` is untouched here; P55-4 owns it.

### P55-4 — the approver sees exactly what leaves; every kept or forwarded copy stays redacted

**Status:** TODO (after P55-3 and P55-6) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec
+ HTTP API (additive)

- **Trigger:** ADR 0036 finding 4, measured 2026-10-29 with a draft message parked for approval: the
  inbox showed the call with both e-mail addresses as `[REDACTED]`. The redaction is by text pattern
  (`governance/secrets.py:140-164`): it hides credentials and e-mail addresses wherever they appear
  and shows a phone number, a chat handle, a name or a customer id in full, so it hides a mail
  recipient and shows a chat recipient. The summary is cut at 1,000 characters
  (`governance/gate.py:195`), so a long form or API body is approved half read. The full call is
  never kept (`governance/approval.py:242-248` stores the redacted `action`; `gate.py:182` the
  digest). The audit log held no row for the call once allowed (`gate.py:136-167`). The maintainer
  chose option B on 2026-10-30: draw the line by place, not by kind of data.
- **Goal (ADR 0036 decision 3):**
  1. `secrets.redact(text, personal=True)` keeps today's behaviour; `personal=False` applies only
     the credential patterns and the stored secret values (`secrets.py:140-164`: split the e-mail
     pattern out of the credential list).
  2. For a call whose tool is of kind `send` and whose decision is `ask`, `gate.py` hands
     `approval_create` the whole rendered call redacted with `personal=False`, uncut; it is stored as
     `call` in the approval record (`approvals/`, mode 700, `approval.py:218-262`). Every other
     approval is created exactly as today.
  3. `approval.py::set_state` (`:170`), the one place a pending approval becomes terminal, removes
     `call` in the same locked write, whether granted, denied or expired; a settled record never
     holds it.
  4. `docket task show <escalation>` (`interfaces/cli/commands/task.py:221,376`) prints the `call`
     of a pending `send` approval under "What leaves"; new route `GET /escalations/<id>`
     (`interfaces/http/routes/escalations.py`, `routes/table.py:34-48`) answers the one
     `EscalationView` with `call` added. `GET /escalations`, `GET /inbox`, `docket inbox`,
     notifications (`operator/notify.py`), Telegram (`interfaces/telegram/bot.py`) and the MCP
     `inbox` tool keep the redacted `prompt` and never carry `call`.
  5. Every `send` call writes `tool.send` to the audit log (tool, decision, policy, the redacted
     summary) whatever the decision; other kinds keep today's rule.
  6. `operator/render.py:32` titles a `send` approval "action leaves the pod".
- **Non-goals:** recognizing more personal data by pattern; any change to non-`send` approvals, the
  trace or the export; keeping `call` after settlement; a new escalation kind or option.
- **Spec:** `security-gates.spec.md` (MINOR: the approval of a `send`), `audit.spec.md` (MINOR:
  `tool.send`), `operator-loop.spec.md` (MINOR: what each view shows), `operator-api.spec.md` (MINOR:
  `GET /escalations/<id>` and the `call` field).
- **Change:** `governance/secrets.py:140-164,187`; `governance/gate.py:136-167,195`;
  `governance/approval.py:170,218-262`; `interfaces/cli/commands/task.py:221,376`;
  `interfaces/http/routes/escalations.py`; `interfaces/http/routes/table.py`; `operator/render.py:32`.
- **Acceptance (RED first):**
  - `tests/unit/governance/test_secrets*.py`: `redact("token=sk-abc… to ana@example.com +57 300 1234567",
    personal=False)` hides the token and keeps the address and the phone; the default call is
    byte-identical to today.
  - `tests/unit/governance/test_gate*.py`: an `ask` on a `send` call of 3,000 characters stores a
    `call` of 3,000 characters with no credential in it; an `ask` on `bash` stores no `call`; an
    allowed `send` writes `tool.send`; an allowed `write` writes nothing (today's rule pinned).
  - `tests/unit/governance/test_approval*.py`: grant, deny and expiry each leave a record with no
    `call`.
  - e2e (`test_workdir_pod.py`, the `outward` world, a `send` whose arguments hold an address, a
    phone and an `Authorization` header): `task show <escalation>` and `GET /escalations/<id>` show
    the address and the phone and not the header; `inbox --peek`, `GET /escalations` and the trace
    show neither the address nor the header; after `approve_once` the approval file has no `call`;
    the audit log verifies and holds one `tool.send`.
  - The HTTP API 6 tests are byte for byte except the added route.
- **Gate:** the unit files, the e2e lane, `validate-specs.sh`.
- **Contention:** Wave 3. `gate.py` is continued by P55-8 and `secrets.py` read by P55-10 (Wave 4);
  `task.py` and `table.py` are touched by no other Wave 3 card.

### P55-5 — an MCP server may live for the hop (`lifetime: call | hop`)

**Status:** DONE (2026-10-30; the maintainer's browser probe under `--lifetime hop` is still to run) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** ADR 0036 finding 5, measured 2026-10-30 with Playwright MCP 0.0.83 through
  `agent/tools/mcp_client.py::call_remote_tool` against a Chrome on `--cdp-endpoint`: the page
  navigated in call 1 was open in call 2 (same URL, `ref=e3`), and a click on `e3` in call 3 answered
  "Ref e3 not found in the current page snapshot"; `mcp_client.py:9-17` spawns one subprocess per
  exchange, so any server that keeps state between calls loses it. The spec's Playwright example
  (`mcp-client.spec.md:422-449`) cannot work as written.
- **Goal (ADR 0036 decision 4):**
  1. `McpServerConfig.lifetime: Literal["call", "hop"] = "call"` (`kernel/mcp.py`); `docket setup mcp
     add --lifetime hop`.
  2. For a `hop` server, the first call of a hop opens one stdio session that answers the hop's
     calls; it is closed where `agent/tools/builtins/background.py::stop_all` stops the hop's
     processes, traced like them; a server that dies mid-hop is restarted on the next call and the
     model is told its state is gone.
  3. The jail, the per-call timeout and the `pre_input` screening apply unchanged per call.
  4. The spec's Playwright example declares `--lifetime hop` and `--cdp-endpoint` and says the
     browser itself runs outside docket.
- **Non-goals:** `lifetime: task`, HTTP/SSE transport (both deferred); any change for `call`
  servers (today's path byte for byte).
- **Spec:** `mcp-client.spec.md` (MINOR: `lifetime`; the Playwright example; the per-exchange
  isolation requirement reworded to "per call unless `hop`").
- **Change:** `kernel/mcp.py`; `agent/tools/mcp_client.py`; `agent/tools/mcp_tools.py` (the loader
  hands a `hop` server its session); `agent/tools/builtins/background.py::stop_all` or the hop end
  that calls it; `interfaces/cli/commands/mcp.py`.
- **Acceptance (RED first):** `tests/integration/agent/tools/test_mcp_lifetime.py` (new) with a fake
  stdio server that counts its calls: under `call`, two calls each see count 1; under `hop`, they see
  1 then 2, the next hop sees 1, and the trace holds one stop event per `hop` server at hop end; a
  killed `hop` server's next call reports the restart. Oracle: the fake server's counter and the
  trace. The maintainer re-runs the browser probe (snapshot → click by ref) under `--lifetime hop`
  as the card's live evidence.
- **Gate:** the integration file, the e2e lane, `gen_cli_docs.py --check`.
- **Contention:** Wave 1. `kernel/mcp.py` and `mcp_tools.py` are continued by P55-3 (Wave 2).

### P55-6 — a `wait` step: the task sleeps until a time or an event (absorbs P52-12)

**Status:** TODO · ready, P55-7 merged 2026-10-30; shares `executor.py` · **Size:** L · **Model:** Sonnet · **Kind:**
behaviour + spec + contract

- **Trigger:** ADR 0036 finding 6: no `wait` step (`pipeline/domain/step.py:88-136`), no
  `notBefore` (`tasks/domain/task.py:211-228`); the only event wait is an external gate polled once
  after a hop (`pipeline-format.spec.md:219-230`); a parked task waits for days and survives
  restarts (measured 2026-10-29: `waiting_approval` → `pending` → `done` across two `docket run`
  invocations). The request names flows whose next step runs days after the previous one, or when
  something outside happens.
- **Goal (ADR 0036 decision 5):**
  1. A step `- <id>: {wait: "<duration>", until: {run: "<cmd>", every: "<duration>"}, on: {timeout:
     ...}}`: `wait` alone is a timer; with `until`, the probe runs on the sweep tick at `every` and
     settles the step when it exits 0; the timer is the probe's ceiling and routes on `timeout` or,
     with no route, blocks the task `wait_expired`.
  2. The step creates an `Escalation` of kind `wait` (`kernel/operator_contract.py:255`), `policy`
     `machine`, settled by `tasks/application/escalation_sweep.py::sweep_escalations`; it never
     appears under "needs you", `GET /escalations` lists it, `POST /escalations/<id>` with
     `optionId: resume` settles it early.
  3. The autonomy document gains a `wait` row identical at L3/L4/L5.
  4. The `operator-v2` contract stays: a new kind value is additive; the spec says a client ignores
     unknown kinds; Tack's maintainer is told in the handoff.
- **Non-goals:** a routine (P55-9); task-to-task dependencies; waiting inside a turn (ADR 0034).
- **Spec:** `pipeline-format.spec.md` (MINOR: the step), `pod-dispatch.spec.md` (MINOR: the pause),
  `operator-loop.spec.md` (MINOR: area 11, kind `wait`), `operator-api.spec.md` (MINOR),
  `config-format.spec.md` (PATCH: the autonomy row).
- **Change:** `pipeline/domain/step.py`; `hops/application/executor.py`;
  `kernel/operator_contract.py:255`; `tasks/application/escalation_sweep.py`;
  `tasks/application/escalations.py:90`; `templates/autonomy/default.yaml`; `operator/render.py:32`;
  `operator/inbox.py` (not under needs-you).
- **Acceptance (RED first):**
  - `tests/unit/pipeline/domain/test_step*.py`: the step parses; `wait` without a duration is a
    validation error naming the step.
  - `tests/integration/tasks/dispatch/`: a pipeline `writer → wait 1s → critic` leaves the task
    waiting with a `wait` escalation after the writer, and a sweep after the time runs the critic to
    `done`; with `until`, a probe that fails twice then passes resumes on the third tick; a timer that
    expires with no route blocks `wait_expired`.
  - e2e (`test_workdir_pod.py`): the same across two `docket run` invocations and one `docket start`
    tick; `inbox --peek --json` lists the wait under `escalations` and not `needsYou`.
  - API 6 tests byte for byte except the added kind in the enum fixture.
- **Gate:** the unit and integration files, the e2e lane.
- **Contention:** Wave 2. `operator/render.py` and `operator-loop.spec.md` are continued by P55-4,
  `pod-dispatch.spec.md` by P55-9 (Wave 3).

### P55-7 — variables belong to the task, and `when.var` compares as text

**Status:** DONE (2026-10-30) · **Size:** S · **Model:** Sonnet · **Kind:** behaviour + spec + defect

- **Trigger:** ADR 0036 finding 6: pipeline variables come per dispatch run
  (`interfaces/http/routes/dispatch.py:36,60`; the sweep passes none, `server.py:96-102`;
  `hops/application/sweep.py:49-130`), so `when.var` cannot branch per task, and a routine (P55-9)
  has nowhere to put its task's inputs; `hops/application/executor.py:217` compares the raw value
  with a `str` where `pod-dispatch.spec.md:1333` says text, so a webhook integer never matches.
- **Goal (ADR 0036 decision 6):** `TaskRecord.variables: dict[str, str]` (`tasks/domain/task.py:211-228`),
  set by `POST /tasks/<pod>` (`variables`, string values, `400` otherwise) and `task add --var k=v`,
  merged over the run's variables at claim (`sweep.py:69`); `executor.py:217` compares `str(actual)`.
- **Non-goals:** variables in a `run:` step's env beyond today's; a schedule.
- **Spec:** `operator-api.spec.md` (MINOR: the field), `cli-interface.spec.md` (MINOR: `--var`).
  `pod-dispatch.spec.md:1333` already says text; the code is made to agree.
- **Change:** `tasks/domain/task.py`; `tasks/domain/request.py`; `interfaces/http/routes/task_create.py`;
  `interfaces/cli/commands/task.py`; `hops/application/sweep.py`; `hops/application/executor.py:217`.
- **Acceptance (RED first):** `tests/unit/hops/application/test_executor*.py`: `when: {var: n, is:
  "3"}` with `n=3` (int) matches; `tests/integration/interfaces/http/`: `POST /tasks` with
  `variables: {tier: "gold"}` shows on `GET /tasks/<pod>/<id>`, and a pipeline step `when: {var:
  tier, is: gold}` runs for that task and is skipped for one without it; `task add --var` the same by
  CLI. API 6 tests unchanged for bodies without the field.
- **Gate:** the unit and integration files, the e2e lane (the HTTP API changed), `gen_cli_docs.py
  --check`.
- **Contention:** Wave 1. `executor.py` is continued by P55-6 (Wave 2); the task record by P55-9.

### P55-8 — a quota on `send`: N actions per pod per window, counted when they run

**Status:** TODO (after P55-4) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec

- **Trigger:** ADR 0036 decision 7 and the request (an action that leaves the machine needs a
  ceiling a pod cannot talk its way past); no stateful rule exists (`governance/policy.py:34-63`,
  searched for rate, quota, count). The card's measured evidence is its own e2e world; it ships after
  P55-4 so the count rides on the always-written `tool.send` row.
- **Goal:** a policy clause `limit: {kind: send, count: <n>, per: hour | day}` (or `tool:` for one
  tool), scoped to the pod; a counter under the home's state directory written by
  `platform/store.py` and incremented after a `send` executes; a call over the limit is blocked with
  the count and the window in the refusal, audited `tool.send` with `decision: block`. Lives in a new
  `governance/quota.py` (`policy.py` is at 658 lines).
- **Non-goals:** quotas on other kinds; a global quota; a view beyond `docket status`.
- **Spec:** `security-gates.spec.md` (MINOR), `config-format.spec.md` (MINOR: the clause),
  `audit.spec.md` (PATCH).
- **Change:** `governance/quota.py` (new); `governance/policy.py` (the clause parsed);
  `governance/gate.py` (the check and the increment); `kernel/home.py` (the state path);
  `interfaces/cli/commands/status.py` (the count).
- **Acceptance (RED first):** `tests/unit/governance/test_quota.py`: two actions under `count: 2` run,
  the third is blocked naming `2/2 per day`; a refused action does not count; the window rolls. e2e
  (the `outward` world): the third `send` of a task is refused and audited; `docket status` shows the
  pod's `send 2/2 today`.
- **Gate:** the unit file, the e2e lane, `validate-specs.sh`.
- **Contention:** Wave 4.

### P55-9 — routines: a pod creates its own tasks on a schedule

**Status:** TODO (after P55-6 and P55-7) · **Size:** L · **Model:** Sonnet · **Kind:** behaviour +
spec + data

- **Trigger:** the request ("on schedules or at recurring times") and ADR 0036 finding 6: `docket pod
  set schedule` holds one entry per pod, UTC only, and `check_schedules` only calls `dispatch_pod`
  on the queue that exists (`interfaces/http/sweeps.py:22,46-59`; `pipeline/application/schedule.py:15-25,114,156`);
  nothing creates a task when it is due. What exists to reuse: the cron and `@every` parsers
  (`schedule.py:55,114`), the service tick (`interfaces/http/server.py:192-203`, every
  `--interval` seconds, 30 by default), `enqueue_task_once` with `idempotency_key`
  (`tasks/application/queue.py:126`), the four configuration scopes of ADR 0035 and task
  `variables` (P55-7).
- **Goal (ADR 0036 decision 8):**
  1. A `kind: routine` document, authored in the team's configuration like a pipeline
     (`routines/<name>.yaml`, resolved through the ADR 0035 scopes, applied by `pod update`):
     `name`, `schedule` (5-field cron or `@every`), `tz` (IANA, default `UTC`), `task:
     {description, pipeline?, variables?, priority?}`, `catchUp: skip | once` (default `skip`),
     `overlap: skip | queue` (default `skip`), `enabled` (default `true`). The kind joins
     `teams/config_docs.py`'s table with `templates/schemas/routine.schema.json`.
  2. `tasks/application/routines.py::fire_due(now)`: for each pod's routines, the due slots since
     the last one fired, computed in `tz` (`zoneinfo`) with the existing parsers; `catchUp: skip`
     fires only the latest due slot, `once` fires one for all missed; `overlap: skip` fires nothing
     while a task of the same routine is not terminal. Each fire is `enqueue_task_once(...,
     channel="routine", idempotency_key="routine:<name>:<slot ISO>")`, already audited as
     `task.enqueue`; the last fired slot is persisted by `platform/store.py` under the home's state
     directory; a skip is a trace event with its reason.
  3. `interfaces/http/sweeps.py` calls it on the same tick as `check_schedules`, so routines fire
     under `docket start --dispatch`; `docket run` does not fire them, and the spec says so.
  4. `docket pod routine list` (name, schedule, tz, next slot, last fired, enabled).
- **Non-goals:** changing `pod set schedule`; calendars or holidays; precision below the service
  tick; routines that depend on one another; firing without the service.
- **Spec:** `pod-dispatch.spec.md` (MINOR: a "Routines" section beside "Schedule configuration and
  doctor visibility", :709), `config-format.spec.md` (MINOR: the kind), `cli-interface.spec.md`
  (MINOR: `pod routine list`).
- **Change:** `tasks/domain/routine.py` (new, the parsed record); `tasks/application/routines.py`
  (new); `teams/config_docs.py` (the kind); `templates/schemas/routine.schema.json` (new);
  `interfaces/http/sweeps.py`; `interfaces/cli/commands/pod_settings.py` (or a new
  `pod_routines.py` if it would cross 700 lines); `kernel/home.py` (the state path).
- **Acceptance (RED first):**
  - `tests/unit/tasks/application/test_routines.py`: `0 9 * * 1-5` in `America/Bogota` is due at
    14:00Z on a weekday and not on Saturday; in `Europe/Madrid` the slot stays 09:00 local across the
    DST change; three missed slots fire one task under `once` and only the latest under `skip`;
    `overlap: skip` fires nothing while the previous task is `running` or `waiting_*`.
  - `tests/integration/tasks/`: `fire_due` called twice for one slot creates one task; after the
    state file is reloaded nothing is fired again; the task carries the routine's `variables` and
    `pipeline`.
  - e2e (`test_workdir_pod.py`): `docket start --dispatch --interval 1` with an `@every` routine on
    a workdir pod creates its task and runs it to `done`; `pod routine list` shows the last fired
    slot. Oracle: the task record (`channel: routine`, its idempotency key) and the audit row.
- **Gate:** the unit and integration files, the e2e lane, `gen_cli_docs.py --check`.
- **Contention:** Wave 3. Owns `sweeps.py`, `config_docs.py` and `pod-dispatch.spec.md` in its wave.

### P55-10 — an external API is an MCP server whose credentials come from the secret store

**Status:** TODO (after P55-3 and P55-4) · **Size:** S · **Model:** Sonnet · **Kind:** behaviour +
spec

- **Trigger:** the request ("interacting with external APIs is another case") and ADR 0036 finding 9:
  an MCP server's credentials are plain values in `mcp-servers.json` (`teams/mcp_servers.py:78,100-101`)
  handed to the subprocess as written (`agent/tools/mcp_client.py:81`); `fetch` sends a GET with
  only a `User-Agent` header (`platform/fetch.py:275`), so an API that needs a token or a write is
  out of its reach by design. Values in docket's secret store are already scrubbed from traces
  (`governance/secrets.py:172-185`), so a credential that comes from the store is hidden for free.
- **Goal (ADR 0036 decision 11):**
  1. An MCP server's `env` value may be `secret:<name>`; `docket setup mcp add --secret
     VAR=<name>` writes that reference, never the value. A literal value still loads, and
     `docket setup` warns about it once, naming the server and the variable.
  2. The reference is resolved where a turn loads its servers
     (`hops/application/driver_support.py:92-105`, before `load_mcp_tools`) through
     `governance/secrets.py::secret_value`; an unknown name refuses that server for the turn,
     reported like any unavailable server, with the variable named and the value never printed.
  3. The `outward` recipe's README shows an API through an OpenAPI-to-MCP bridge or a small wrapper,
     declared twice: its GET operations `--kind read`, its writes `--kind send`, split with the
     server's `tools` list, the token as `--secret`.
- **Non-goals:** a native HTTP tool with methods, headers or bodies (the request is a `send` or a
  `read` through an MCP server); headers on `fetch`; OAuth flows or token refresh (the wrapping
  server's job); per-pod secret stores.
- **Spec:** `mcp-client.spec.md` (MINOR: `secret:` references), `api-keys.spec.md` (MINOR: a stored
  secret consumed by an MCP server).
- **Change:** `kernel/mcp.py` (the reference shape); `teams/mcp_servers.py`;
  `hops/application/driver_support.py`; `interfaces/cli/commands/mcp.py`;
  `interfaces/cli/commands/setup*.py` (the warning; `rg -n "def .*doctor|def .*report"`);
  `templates/recipes/outward/README.md`.
- **Acceptance (RED first):**
  - `tests/integration/agent/tools/`: a fake stdio server that echoes its environment, configured
    `env: {API_TOKEN: secret:crm}` with `crm` in the store, sees the stored value; `mcp-servers.json`
    holds `secret:crm` and not the value; the turn's trace holds neither the value nor
    `[REDACTED]`-free leaks of it (the redaction oracle already used by `tests/unit/governance/`).
  - The same server with an unknown secret is reported unavailable for the turn naming
    `API_TOKEN`; the other servers of the pod still load.
  - `setup mcp add --secret API_TOKEN=crm` writes the reference (CLI golden); a server with a literal
    `*_TOKEN` value makes `docket setup` warn once.
- **Gate:** the integration file, the e2e lane (the home's MCP document changed), `gen_cli_docs.py
  --check`, goldens.
- **Contention:** Wave 4. Continues `kernel/mcp.py` and `interfaces/cli/commands/mcp.py` after
  P55-3 and P55-5, and reads `secrets.py` after P55-4 changes it; shares no file with P55-8.

### P55-11 — a pod widens the machine's network only with the operator's recorded yes

**Status:** DONE (2026-10-30; e2e world in `tests/e2e/test_workdir_pod.py`, ran on Landlock) · **Size:** M · **Model:** Sonnet · **Kind:** behaviour + spec (MAJOR on one rule)

- **Trigger:** ADR 0036 finding 8: `teams/pod_settings.py::effective_network` (`:513-530`) returns
  `none` whenever the machine's recorded mode is `none`, so a pod's `network: open` never widens it
  (`security-gates.spec.md:1086-1093`, "a pod's `network` can only narrow it"). Since `docket init`
  turns isolation on where it is detected (D-67) and the jail's network defaults to `none`, an
  outward pod's MCP servers, which run inside the jail, cannot reach a host. The only workaround
  is to open the whole machine and pin every code pod to `none`, which makes a new pod open by
  default. The maintainer chose 2026-10-30: a pod widens only with the operator's recorded yes.
- **Goal (ADR 0036 decision 12):**
  1. `docket pod set network open --widen` on a machine whose recorded mode is `none` prints what
     opens ("this pod's `bash`, `run:` steps, checks and MCP servers can reach any host"), asks
     `[y/N]` through `interfaces/cli/commands/contract.py::confirm` (`--yes` for scripts), and on yes
     records `networkGrant: {at, by}` in the pod's settings through `platform/store.py`, audited
     `pod.network_widen` with the pod and the scope it overrides.
  2. `effective_network` returns `("open", "pod-grant")` when the machine says `none` and the pod
     holds a grant; every other case is unchanged, including fail-closed on unreadable settings.
  3. `pod set network none`, or `pod set network open` without `--widen`, removes the grant
     (audited `pod.network_narrow`).
  4. Only that operator command writes the grant: `pod update` and `POST /pods/<p>/apply` ignore a
     `networkGrant` key in a repository's `.docket/` and report it as skipped
     (`teams/apply/review.py:161-172` already lists a repository's `network: open` as a run item the
     operator must accept; the grant is never one).
  5. `docket setup` (the health report) and `docket status` name each pod running with a grant.
- **Non-goals:** per-host rules inside the jail (the jail is all or nothing); changing the machine's
  default; widening with isolation off (nothing to widen); a grant per task.
- **Spec:** `security-gates.spec.md` (MAJOR: item 7's "a pod's `network` can only narrow it" gains
  the recorded-grant exception, with its prompt, audit and the commands that cannot write it).
- **Change:** `teams/pod_settings.py:168,361,513-530`; `interfaces/cli/commands/pod.py:327`
  (`cmd_set`, the flag and the prompt); `teams/apply/review.py:161-172`; the health-report and
  status lines (`rg -n "networkEnforced|network" src/docket/interfaces/cli/commands/setup*.py
  src/docket/interfaces/cli/commands/status.py`).
- **Acceptance (RED first):**
  - `tests/unit/teams/test_pod_settings*.py`: machine `none` + pod `open` → `("none", "global")`
    (today, pinned); machine `none` + pod grant → `("open", "pod-grant")`; machine `none` + grant +
    unreadable settings → `none`; pod `none` + grant cannot exist (setting `none` removes it).
  - `tests/integration/interfaces/cli/`: `pod set network open --widen` answered `n` writes nothing
    and no audit row; answered `y` writes the grant and `pod.network_widen`; `pod set network none`
    removes it and audits `pod.network_narrow`.
  - `tests/integration/teams/`: a repository `.docket/` carrying `networkGrant` applied by `pod
    update` leaves no grant and reports the key skipped.
  - e2e (`test_workdir_pod.py`, isolation on where the backend exists, skipped otherwise like
    `test_jailed_turn.py`): with the machine at `none`, a `run:` step that reaches a local HTTP
    server fails; after `--widen --yes` it succeeds; a second pod on the same machine still fails.
- **Gate:** the unit and integration files, the e2e lane, `gen_cli_docs.py --check`, goldens, the
  escape matrix (`tests/integration/sandbox/test_escape_matrix.py`) because the jail's network input
  changes.
- **Contention:** Wave 1. Owns `teams/pod_settings.py` before P55-3 (Wave 2) and
  `security-gates.spec.md` before P55-3, P55-4 and P55-8.

### P55-12 — the docs say what shipped

**Status:** TODO (at the close) · **Size:** S · **Model:** Haiku · **Kind:** docs

- **Trigger:** README D-37: when work changes what is true, the sentence changes in the same phase.
  Today the README and `docs/DOCKET.md` describe code teams only; `docs/recipes.md` lacks `outward`;
  nothing describes routines, `wait` steps or the `send` kind.
- **Goal:** one README sentence under the tagline: a pod runs a code team or another kind of team
  (research, content, outward work), on demand or on a schedule, under the same gate;
  `docs/DOCKET.md` and `docs/AGENT-TEAMS.md` describe a workdir pod, routines and `wait` steps;
  `docs/recipes.md` lists `outward` with its four server shapes (message, browser, external API,
  agent) and the `secret:` reference;
  `docs/SECURITY-SIMPLE.md` gains the `send` sentences (held only by a role that names it, always
  audited, approved by a person who sees the whole call while every kept copy stays redacted,
  under a quota) and the perimeter sentence for an agent
  reached as a tool. No count, no saving, no named third-party site.
- **Non-goals:** any spec text (each card owns its own); a landing page.
- **Change:** `README.md`; `docs/DOCKET.md`; `docs/AGENT-TEAMS.md`; `docs/recipes.md`;
  `docs/SECURITY-SIMPLE.md`.
- **Acceptance:** the agent-lane README tests pass on the committed tree; `gen_cli_docs.py --check`
  and `validate-specs.sh` pass.
- **Gate:** the agent lane once, at the close, by the integrator.
- **Contention:** Wave 4, after every other card merged.

### Wave table (schedule by file contention)

| Wave | Cards | Boundary |
| --- | --- | --- |
| 1 | P55-1 · P55-5 · P55-7 · P55-11 | prompts, compose, memory seed and the e2e file · the MCP client and `kernel/mcp.py` · the task record, `task_create.py`, `sweep.py`, `executor.py:217` · `effective_network`, `pod.py::cmd_set`, `apply/review.py`, `security-gates.spec.md` (the e2e world lands after P55-1 creates the file) |
| 2 | P55-3 · P55-6 | continues `kernel/mcp.py`, `mcp_tools.py` (after P55-5), owns `roles.py`, `pod_settings.py`, `registry.py`, the recipe · continues `executor.py` (after P55-7), owns `step.py`, `operator_contract.py`, `escalation_sweep.py`, `render.py` |
| 3 | P55-2 · P55-4 · P55-9 | `model_selection.py` and `role-archetypes.spec.md` (after P55-3) · `gate.py`, `secrets.py`, `trace.py`, `render.py` (after P55-6) · `routines.py`, `config_docs.py`, `sweeps.py`, `pod-dispatch.spec.md` (after P55-6 and P55-7) |
| 4 | P55-8 · P55-10 · P55-12 | `quota.py` (new), `gate.py`, `policy.py`, `status.py` (after P55-4) · `kernel/mcp.py`, `mcp_servers.py`, `driver_support.py`, the MCP and setup CLI (after P55-3, P55-5) · docs, after every merge |

## ◇ FOLLOW-UPS WITH TRIGGERS (not cards; triage when a trigger fires)

> Re-checked against the code on 2026-10-24; paths are current. Removed as no longer true: notification
> dedup is persisted (`operator/notify.py`), the `kind:`-less canonical-document advisory is gone, and
> `_create_workspace` no longer exists. Decisions that belong to the maintainer are in ROADMAP §7.1.

**Toolchain read grants (dropped from Phase 48).** A sibling project's gates failed with exit 126 under the
jail until each toolchain under `$HOME` (`~/.nvm`, `~/.pyenv`, `~/.cargo`) was granted by hand with
`docket setup sandbox read add`. Trigger: a second pod whose first jailed gate fails that way. Next:
`docket setup` proposes the grants for the toolchains it finds.

**Phase 55 Wave 1 (merged 2026-10-30).** Loose ends, none a card yet; the first three belong to the Wave 2 and 4 cards
that already own the files.
- *`lifetime` in the document form.* `teams/mcp_servers.py` (`McpServerDocument`, `to_config`),
  `templates/schemas/mcp-server.schema.json` and the config docs do not carry `lifetime`, so a recipe cannot declare a
  `hop` server. Belongs to P55-3.
- *Specs that lag.* `trace-store.spec.md` items 30-32 say every `process_*` payload carries `pgid`; MCP events carry
  none. `audit.spec.md` (~line 77) omits `pod.network_widen` / `pod.network_narrow`. P55-12 or the next card that
  edits either spec.
- *Required variables supplied by tasks.* `dispatch_pod`'s up-front check refuses a `required` pipeline variable that
  only tasks supply. P55-9 (routines) meets it first.
- *Smaller.* `docket task cancel` does not kill a `hop` MCP session directly (it closes at hop end); a top-level
  `networkGrant` in `pod.yaml` is an unknown-key error, not a skip (only under `settings`).
- *Flakes under load, seen once each and passing alone:* `test_run.py::TestForegroundApprovalPrompt` (two tests),
  `test_consult_wait.py::TestAnsweredInPlace::test_an_option_answer_goes_back_to_the_model_in_the_same_turn`,
  `test_end_to_end.py` approval-mode tests. A second failure of the same test is its trigger.
- *Live evidence owed.* The maintainer's browser probe (snapshot, click by ref) under `--lifetime hop` for P55-5.

**Phase 54 (closed 2026-10-29).** Two items wait for their triggers.
- *Dated model ids.* The native `/models` lists `claude-haiku-4-5-20251001`, and the probe matches ids
  exactly, so `claude-haiku-4-5` never gets an observed output cap and a call without a declared
  `--max-tokens` fails by design. Trigger: a second operator who meets that refusal. Next: the probe
  matches a catalog id to the dated id that starts with it.
- *Names.* `openai_http.py` and `OpenAIChatClient` hold both wires and still carry the first one's name;
  ADR 0011, ADR 0014 and two specs quote them. Trigger: a third dialect or the next edit of either module.

**Outward work (ADR 0036, deferred with triggers; the cards are Phase 55).**

- **HTTP/SSE MCP transport** (`mcp-client.spec.md:50`). Trigger: the first real pod whose connector
  exists only hosted.
- **A per-pod `fetch` allowlist** (`kernel/home.py:278`, one list for the machine). Trigger: two pods
  on one machine that need different hosts.
- **`lifetime: task` for an MCP server.** Trigger: a recorded run in which a following hop needed the
  previous hop's session.
- **A structured-output gate** (a result that must match a schema). Trigger: a recorded run whose
  critic approved a malformed list.
- **Pod memory with non-path subjects** (`workspace-structure.spec.md:158-169`: a subject is a
  repository path; a workdir pod's "the client prefers a formal tone" has no home). Trigger: a recorded
  workdir run whose Lead repeats a correction a person already made.

**Fired, waiting for a maintainer go (the measurement spends hosted-model tokens).**

- **The implementer sends 0.65 of what the backend counts** (Phase 45 real runs on `fab-dev`,
  2026-10-20: 14 and 13 calls, largest request about 7,000 estimated tokens; reviewer 0.62, tester 0.80
  and 0.90). The Phase 44 trigger ("a real implementer run with its grants declared that still sends
  over half") fired. Next: P52-1 measures which calls repeat on the recorded traces (no live run
  needed); P53-4 (which absorbed P52-5) acts on the figure.

**Model adaptation and context (ADR 0033, deferred with triggers; the cards are Phase 52).**

- **Reasoning kept inside the turn** (`ChatMessage.reasoning`, resent only in the active tool
  loop; `reasoning_content` is dropped today in `models/adapters/openai_wire.py::decode_response`).
  Trigger: a profile that declares `reasoning: interleaved`.
- **Lifecycle condensation** (a `read` superseded by a later `read` or an `edit` of the same file
  is evicted first, in batches aligned to steps). Trigger: after P52-2 (which absorbed P52-8), the bench `--repeats`
  still shows re-reads on the recorded implementer steps.
- **A bounded model escalation** on a step (`escalate: {on: [verify_failed, no_progress], model:
  strong, max: 1}`), audited. Trigger: the `strong-plan-cheap-edit` recipe (P52-6) fails
  `verifyCmd` on a measured share of real runs.
- **A lazy MCP catalog** (`mcp_describe(server, tool)`, the tool list kept stable within a turn).
  Trigger: a pod whose MCP schemas exceed its built-in ones (`request_part_bytes["tools"]`).
- **A native Anthropic dialect** (1 h TTL, `cache_control` on tools, signed thinking blocks; the
  provider note already defers it). Trigger: direct use without the gateway, which caches today.

**Escalations (left at the Phase 51 close, 2026-10-25; ADR 0032).**

- **Approval, gate and `check_changed` follow-ups still run inside `resolve`** (`approval_grant`
  and the task-grant audit in `tasks/application/escalations.py`), not on the claim path; P51-6
  stopped at PARTIAL because deferring them breaks `approved_ready`, which reads pregrants and
  `gateOverridePipelineIndex`, and P51-9's "Also" list named the move. Trigger: a change to
  `approved_ready` or to the claim path.
- **Settled escalations written before P51-11 stay in the flat `escalations/` directory**; no
  migration is written. A scan of the live directory still opens them (`platform/store.py::list_escalations`
  reads the flat folder for `pending` and unfiltered scans). Trigger: an operator whose pre-P51-11
  records slow the inbox; then move them under `settled/` once.
- **`GET /escalations?since=` reads every settled file** (`operator/inbox.py::escalation_views`
  calls `list_escalations(since_seq=...)` with no state, so `settled/` is scanned on each poll).
  Trigger: a poller whose `settled/` directory is large; then index by `seq` or bound the scan.
- **docket follows an enclosing git repository when a pod path is not itself one**
  (`platform/git.py::git_is_repo` answers `rev-parse --git-dir`, true anywhere inside a work tree),
  so it would prepare and branch the enclosing repository. Only the live-eval and smoke worlds
  refuse that today (`specs/test-framework.md`). Trigger: a pod registered on a subdirectory or
  a nested path that is not a repo.
- **`scripts/render-doc-assets.py:275` prints a made-up approval token** (`token=apr-...`) and the
  `waiting_approval` line, shapes Phase 51 removed. Trigger: the maintainer re-captures the README
  assets (a classifier-refused step); then render the escalation id and `waiting_input`.

**Test suite under load (found at the Phase 47 close, 2026-10-24; each passes alone).**

- **Timing flakes seen once each:**
  `test_retries_and_timeouts.py::TestRetryDoesNotTripStaleClaimSweep`, and the foreground approval
  deny test (its fake approval timeout was raised from 5 s to 60 s, `1a704359`). Trigger: a second
  failure of the same test. Then replace its wall-clock wait with an event.
- **Docstring budget:** `comment_lint.py` counts 209 long definition docstrings at the close against 205
  on `develop` (most moved or renamed code). Trigger: the next card that edits one of those modules
  trims its own.
- **Two contract files set the merge run's floor** (measured 2026-10-28, `--durations=0`):
  `tests/contracts/test_a2a_http.py` 60 s and `test_escalation_http.py` 35 s of the 84 s run. Each
  test's function-scoped `parked` fixture runs a real `docket run` and starts a service (about 3 s
  of setup per test), and `--dist loadfile` keeps a file on one worker. Trigger: the merge run
  passes 120 s, or a card adds a test to either file. Then share one parked world per module for
  the read-only tests.

**Runtime and dispatch (from real runs).**

- **A refused task is resumed on every 30 s sweep tick** (`dispatch_refused` is in
  `RESUMABLE_FAILURE_KINDS`, `tasks/domain/state.py`; operator-api §6 by design). Trigger: the audit log
  fills with one task's refusals, or a second operator asks. Then resume only when the cause changed.
- **A parked turn is paid twice**: the resumed hop re-sends the whole prompt (4,157 input tokens before
  the park, 8,181 after; 100,573 in the 2026-10-18 joint run). Trigger: a third run that parks on the
  same shape. Then weigh resuming the session over re-running the hop (operator-loop §2 item 6).
- **A hop refused before any call records an empty model** (`hop_finished.model == ""`, a `""` key in
  `usage.byModel`). Trigger: a reader of `byModel` that trips on it.
- **Provider rows lag the models in use:** Anthropic advertises dated ids while the template rows use
  aliases (limits stay `unknown`), and no row prices `claude-sonnet-5-5` or `claude-opus-5-5`
  (`task show` prints `cost: -`). Trigger: a run on an alias id whose window matters, or an operator
  asking for the estimate.
- **Hop language drift:** a resumed step once wrote its report in another language, which became the
  next handoff. Trigger: a second occurrence; then a pod `language` setting.
- **The Lead plans with the codebase path while the Implementer is rooted in the task worktree**
  (`tool.refused` on `read`). Trigger: reproduce with a local-model dispatch in a worktree pod.
- **The prospective budget check ignores cache reads**, so a heavily cached step is refused early.
  Trigger: a real run refused with room left. `glob`/`grep` walk vendored trees before filtering;
  measure before changing.
- **A task's `network: none` cuts the agent turn only**; `verifyCmd` and `run:` steps keep the pod's
  posture (stated in the spec).
- **Cancel over HTTP reports `cancelled` once the stop is requested**; the task stays `running` until
  the executor notices. The slow-stub cancel path has no test.
- **Not examined:** each Phase 45 run's trace carries two `approval_denied` events beside its park.
- **Real-Docker tests exceed their duration ceiling under load** (`test_network_lockdown`,
  `test_sandboxed_exec`, the escape matrix's docker cases): they pass alone. A flake, measured
  2026-10-14.

**Workspace and checks.**

- **`docket setup` without `--fix` writes:** its report re-seeds `WORKFLOW_AUTO.md`
  (`interfaces/cli/commands/setup_check.py`). A check that writes is a defect. Trigger: the next edit
  of that file.
- **A file a check reaches only through `make` or `npm run` is protected only through the default
  files it reads**, and **a gitignored file is invisible to the check**. Trigger: a real gate whose
  script lives behind a target, or a repository that ignores a file its gate reads.
- **Prepare:** only `node_modules` is cached (`.venv` is not relocatable); `node_modules/.cache` is
  read-only in the jail; eviction can break a running task's link (resume prepares again); prepare is
  not cancellable (bounded by `PREPARE_TIMEOUT_S`); `hops/workspace/prepare.py::linked_entries` accepts
  any cache entry, not only the task's codebase. Trigger: a real run that hits one of them.
- **Shell keywords are classified as binaries when unjailed** (`for`, `do`, `done`, `if`, `then`,
  `while` ask in `governance/security`). Trigger: an operator without isolation reports it.

**Configuration.**

- **A tool deny per team member** (a read-only researcher): `tool_profile` is prose, the only denial is
  the pod-wide `deniedTools`. Trigger: a recipe or pod that needs one member without write tools.
- **Delete the old-layout reader** (`kernel/layout.py::is_legacy` and the legacy branches of `Home`).
  Trigger: the next minor release. First move what still seeds or reads an old-layout home:
  `tests/support/home.py` and `pods.py`, `benchmarks/harness.py`, `benchmarks/scenarios/run.py`, the
  adoption benchmark tests, and the old paths named in `scripts/gen_cli_docs.py`,
  `scripts/render-doc-assets.py` and `docs/commands.md`.
- **Parallel tasks in a pod:** ADR 0027 point 10 holds the trigger; a card would add a
  `maxParallelTasks` pod setting and a bounded pool in dispatch.
- **A team's skills:** `hops/workspace/skills.py` reads only `<codebase>/.docket/skills`; a repository
  keeping `teams/<pod>/` has no per-team skills scope.

**Channels, inbox and the HTTP API.**

- **`docket start`'s periodic notify flush ignores `FlushReport.error`** (`interfaces/http/server.py:200`).
- **Enabling the `email` channel checks nothing**; with no `to`, `from` or `smtpHost`, every delivery
  fails into the health record. Trigger: an operator enables it.
- **Pending memory entries show in `docket inbox` but not in `GET /inbox`, MCP `inbox`, notifications or
  Telegram `/status`.** Needs an operator-v1 inbox contract bump.
- **`GET /pods` (the list) was not checked** for the invalid-settings failure fixed on `/pods/<p>`.
- **`POST /pods/<p>/apply` with every item skipped writes no `pod.apply` audit entry.**
- **The corrections cursor needs `+` percent-encoded in `since`**; a pod whose Lead was removed but
  whose ledger remains answers `404`.
- **The `openhands` and `pydantic_ai` adapters never pass `cache_write_tokens`**
  (`packages/docket-runtime/src/docket_runtime/adapters/`). Trigger: someone reads that usage.

**Prompts and pod state.**

- `hops/application/compose.py::_resolve_hop_instructions` still opens "You are the Implementer..."
  (SOUL says it); recipe roles using `${codebaseOrConfigured}` render a path; `repo_map.SKIPPED_DIRS`
  mirrors `toolbox.SKIPPED_DIRS` (pinned by an equality test); pod read routes do not carry
  `tokenBudget`; the condensation notice carries the call's full path.
- **Every member of a pod shares the base session key `agent:<pod>:<key>`** (`teams/pod.py`); no turn
  reads it today. Trigger: a turn that does.
- **Three readers of the implementer's codebase** (`rg -n "def _pod_codebase|def _codebase|def
  task_diff" src`); one helper when next touched.
- **`memory_update` has no structural telemetry key**; members stamped `POD_TEMPLATE_VERSION` 4 show stale
  to `pod update` by text comparison; `scripts/smoke_workflow.py`'s memory scenario needs a live run.

**Phases 52 and 53 (closed 2026-10-29).** Triaged the same day: the brief redaction, the prompt `tests` file, a role's
unknown tool name, `pod test`'s handoff spec, the live-run key lookup and the stale docs were fixed; what stays waits
for its trigger.

- **P52-12, a wait on a machine is an escalation.** Absorbed by P55-6 (ADR 0036 decision 5): a `wait` step is
  an escalation of kind `wait` the sweep settles on time or on a probe; the wait on a machine is one case of it.
- **P53-4 goal 3, the Lead's locators read into the Implementer's message.** Measured on three recorded smoke tasks
  (two local Qwen, one Haiku, `context_replay.py --repeats`): the Implementer read 1/1, 1/1 and 2/4 files the Lead had
  read, but all except one were files it then edited, whose exact text `edit` needs; "not edited after" was 0, 0 and
  1 file (682 bytes). Trigger: "not edited after" reaching 30 % of the Implementer's reads on recorded tasks of a real
  pod (the smoke repository has three files).
- **The model class comes only from the rank anchors** (`economy` is `cheap`, `standard` and `premium` are `strong`),
  so a non-anchor model such as the local Qwen resolves `any` and no `<name>.<class>.md` variant acts for it. No
  shipped prompt has a variant. Trigger: a variant written for a non-anchor model.
- **Structured `task` intake** exists on `POST /tasks/<pod>` only; the CLI, MCP and Tack's runner do not send it.
  Trigger: Tack adopting it.
- **Decided, not open:** P52-2's bench oracle is "no step worse than the recorded request, and prefix stability not
  worse", met on the fixture (sent 0.25 to 0.66 of the baseline per step; stable 8/10, 3/4, 5/7, 6/7). The "+0.3 %
  to +3 %" was against the pre-P52-2 `condense_history`, which the bench's `phase44` policy now calls live, so it is no
  longer reproducible; the small-result rule stays. The re-ask, finalization and closing texts
  (`hops/application/runner.py`, `agent/loop_request.py`) are the harness's protocol, versioned with the code and the
  agent-loop spec, not role prompts. `smoke_workflow.py` calls an interpreter running a script (`PYTHONPATH=src python3
  x.py`) opaque on purpose: it can read any file, so the private-path check fails closed; `VAR=x` alone is parsed.

**Architecture and packaging.**

- **The runtime closure grows with any facade on a context the runtime imports** (measured in P47-8:
  agent 52 -> 75, teams 52 -> 157, governance 52 -> 101, observability 52 -> 60 files). Trigger: a
  proposed facade on one of them.
- **`FailureKind` enumerates only the four kinds the task state writes**; hop and gate kinds stay plain
  strings (pod-dispatch spec item 9). Trigger: the next change to those kinds.

**Tests.**

- A worker's `monkeypatch.undo()` once undid the autouse home isolation and wrote into the real
  `~/.docket`; the fixture guards `setattr`, not `undo`. Trigger: a second leak.
