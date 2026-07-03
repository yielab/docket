# TODO — active task board

> **This is docket's single standing TODO file.** It holds the executable cards for whatever phase is
> currently active in [ROADMAP.md](ROADMAP.md). Do **not** create per-phase task files — when a phase
> finishes, clear its cards (the phase record stays in ROADMAP) and append the next phase's cards here.
>
> *Phase 11 (Competitive differentiation, CD-0…CD-9) and Phase 12 (Consolidation & hardening,
> CH-0…CH-13) are both **COMPLETE** — their durable records live in ROADMAP.md's Phase 11/12
> sections and the roadmap Changelog. Their boards were cleared per the convention above.*
>
> ---
>
> ## Active: PHASE 13 — Close the differentiation gaps
>
> Executable board for **PHASE 13** in [ROADMAP.md](ROADMAP.md) (read that section first — the
> rationale, explicit **keeps**, and exit criteria). Source of record: the operator chose
> "Tier-1 competitive bets" from `internal-docs/competitive-analysis.md`'s **P1** (pod-level
> runtime-resource isolation), **O2** (deterministic pre-merge verification gate), and **S1**
> (high-risk action classes + a headless approval channel). A 2026-07-02 grounding pass (three
> parallel code investigations, file:line-cited) found Phase 11's own CD-1/CD-2/CD-3/CD-4 cards
> already built most of this the same week the analysis was written. **This phase closes the
> five real residual gaps, it does not rebuild the three features from scratch.** Each card below
> names the exact gap and cites the code that already exists around it.
>
> **What we're doing (one paragraph):** P1 has the data model and allocation logic
> (`core/resources.py`, `AgentMeta` fields) but never reaches the implementer's actual process
> environment (FD-0). O2 already gates the implementer hop on `verifyCmd` (that's CD-2) but has no
> public way to *set* `verifyCmd` (FD-1) and never structurally parses the Tester hop's PASS/FAIL
> (FD-2). S1's CLI/HTTP approval channels already work (`docket approve`, `serve.py`'s webhook) but
> have no high-risk action-class policy (FD-3) and no audit-log trail (FD-4) — closing both is what
> lets the gates-default-on flip actually happen honestly (FD-5), followed by a truth pass on the
> specs/docs that describe all of the above (FD-6, FD-7).

## How to use this board (read before claiming a task)

1. **Claim:** set Status → `IN-PROGRESS (@you)`. One agent per task.
2. **Read first (always):** ROADMAP.md's Phase 13 section (the "why this phase" gap analysis),
   §2 (Python ground truth), §4.5 (architectural principles), [CLAUDE.md](CLAUDE.md), and the
   task's own "Read" list.
3. **Layer rule (non-negotiable):** `cli/ → core/ → edges/`, inward only. OpenClaw formats live **only**
   in `edges/adapters/openclaw.py` (the ACL). docket-owned JSON goes **only** through `edges/store.py`
   (JSONL append logs are the one D-12 exemption). Every shell-out goes through `edges/adapters/`.
   `core/`/`edges/` never import `ui.py` or print (D-3 from Phase 12).
4. **No-behavior-change rule, except where a card says otherwise:** the golden suite
   (`bash tests/golden/run.sh verify-all`) must stay byte-identical unless a card explicitly adds
   new CLI surface (FD-1's `--verify` flag, FD-3's gates visibility command) — those cards say so
   and require regenerated goldens with the diff explained in the PR.
5. **Definition of done (per task):** acceptance criteria pass · a pytest covers it (add/refresh a
   golden case if output changes) · `uv run ruff check . && uv run ruff format --check . && uv run
   mypy src && uv run pytest` green · `bash tests/golden/run.sh verify-all` green · committed
   `Type: description` (no Claude/Co-Authored-By trailer) · public-repo privacy scrubbed (grep the
   diff for real names / `/home/<user>` paths before committing).

**Status legend:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs FD-x)` · `DONE`
**Size:** S ≈ ½ day · M ≈ 1–2 days · L ≈ 3–5 days (split before claiming if L)
**Branch model:** one short-lived `pc/fd-<id>` branch per task → PR into the working branch (`develop`).

---

## Dependency map (what unblocks what)

```text
FD-0, FD-1, FD-2, FD-3, FD-4, FD-5, FD-6 — DONE, all merged into develop 2026-07-02.
  (FD-3 was narrowed before merge — git/npm stay allowlisted, per-argument
  enforcement deferred to backlog. FD-5/FD-6 had one real conflict in
  security-gates.spec.md, resolved by hand.)

FD-7 (docs/positioning pass) ── depends on FD-0..FD-5 — UNBLOCKED, last card in Phase 13
```

---

### FD-0 — Inject pod resources into the implementer's process environment (completes P1)

- **Depends on:** — · **Parallel-safe with:** FD-1, FD-3, FD-4 · **Shares a file with FD-2** (`core/dispatch.py`) — sequence the two merges, don't leave both branches open indefinitely.
- **Read:** `core/models.py:75-80` (`AgentMeta.port_range_start/count`, `scratch_dir`); `core/resources.py` (full — `allocate_pod_ports`/`free_pod_ports`); `core/dispatch.py` (`dispatch_task`, how it calls `_oc.agent_run` — currently `(agent_id, session_key, message, timeout)` with no resource params); `edges/adapters/openclaw.py`'s `agent_run` (~L939-999, the `_sp.run(cmd, capture_output=True, text=True, timeout=...)` call has **no `env=` kwarg today**); `cli/_pod.py:95-125` (`_member_tools`, where port/scratch values are currently only written as TOOLS.md prose); `tests/python/test_cd1_resources.py`.
- **Why:** the allocation and persistence half of pod-level resource isolation (CD-1) is real — each pod really does get disjoint ports and a scratch dir. But nothing makes that binding *enforceable*: an implementer subprocess only ever sees its assigned port range/scratch dir as text in TOOLS.md, which it can ignore, misread, or the agent can simply not follow. Isolation that depends on the agent reading and obeying prose isn't isolation.
- **Do:**
  1. Add an optional `env: dict[str, str] | None` param to `agent_run` in `edges/adapters/openclaw.py`; when set, pass `env={**os.environ, **env}` to the `_sp.run` call instead of inheriting the parent env unmodified.
  2. In `core/dispatch.py`, when a hop targets an implementer with allocated resources (`AgentMeta.port_range_start` is not `None`), build `{"DOCKET_PORT_BASE": str(port_range_start), "DOCKET_PORT_COUNT": str(port_range_count), "DOCKET_SCRATCH_DIR": scratch_dir}` and pass it through to `agent_run`. Leave non-implementer hops and implementers without allocated resources unaffected (no `env` override — today's behavior).
  3. Keep the existing TOOLS.md prose (`_pod.py:95-125`) — reword it to state these are also real environment variables the process can rely on, not just documentation.
  4. Tests: assert the subprocess-invocation call captures the expected env vars with correct values when resources are allocated; assert no override happens for a task-type agent or an implementer with no allocation.
- **Out of scope:** a real disposable DB/cache namespace (stays a naming convention — no docket-owned DB engine to provision against, per the Phase 13 explicit keeps); giving reviewer/tester roles pod resources.
- **Deliverables:** `agent_run` env-injection support; dispatch wiring for implementer hops; tests.
- **Acceptance gate:** [ ] an implementer subprocess's real environment contains `DOCKET_PORT_BASE`/`DOCKET_PORT_COUNT`/`DOCKET_SCRATCH_DIR` when resources are allocated · [ ] no env override for agents without allocated resources · [ ] suite + goldens green.
- **Size:** M · **Status:** DONE — merged into develop 2026-07-02 (branch commit `2253b46`). Auto-merged cleanly against FD-2 (merged first) at the file level; the two cards' shared `Runner` type-alias widening left FD-2's local test fixtures on the old 4-arg signature, fixed in a small follow-up commit right after the merge.

---

### FD-1 — TOOLS.md verify-command field + public `--verify` flag (completes O2a)

- **Depends on:** — · **Parallel-safe with:** everything.
- **Read:** `cli/_pod.py:95-125` (`_member_tools`, the TOOLS.md generator — currently has no verify-command line); `cli/_pod.py:649-661` (`_parse_add_args`, where a new flag would be parsed); `core/models.py:80` (`AgentMeta.verify_cmd`, alias `verifyCmd`); `specs/data/docket-meta.spec.md:74` (**already documents** a `--verify` flag / `meta_set` path that doesn't actually exist as public CLI today — this card must make that claim true); `cli/__init__.py:1600-1602` (the internal `meta-set` debug command — today's only real setter).
- **Why:** CD-2's mechanical gate (`dispatch.py` running `verifyCmd` via `run_verify_cmd` and hard-failing on non-zero) is real and already shipped — but nothing public lets an operator *set* the one field that triggers it. The spec already promises a flag; today only an internal debug command can set it.
- **Do:**
  1. Add a `--verify "<cmd>"` option to `docket pod <project> add` (implementer member creation) that writes `verify_cmd` into the new member's `.docket-meta.json`.
  2. Add a small setter for existing members — keep it in the pod command group (e.g. `docket pod <project> set-verify <member-id> "<cmd>"`), not a new top-level command.
  3. Extend `_member_tools()` to include the configured verify command in TOOLS.md prose when set, so the implementer can see what gate its work must pass.
  4. Verify `specs/data/docket-meta.spec.md:74`'s existing claim is now accurate; fix wording only if still off after the flag lands.
  5. Tests: CLI arg parsing for `--verify` and `set-verify`, meta written correctly, TOOLS.md content includes the command when set and omits it when not.
- **Out of scope:** changing what `run_verify_cmd` itself does (CD-2's mechanics are correct as-is); gating reviewer/tester hops (that's FD-2).
- **Deliverables:** `--verify` flag on pod add; `set-verify` subcommand; updated TOOLS.md generator; tests; spec fix if needed.
- **Acceptance gate:** [ ] `docket pod <p> add --verify "<cmd>"` sets `verifyCmd` on the new member · [ ] `set-verify` updates it on an existing member · [ ] TOOLS.md reflects the configured command · [ ] suite + goldens green (new golden case if `pod add --help`/TOOLS.md output changes).
- **Size:** S · **Status:** DONE — merged into develop 2026-07-02 (branch commit `45db2b9`). Conflicted with the README test-count line only (both branches bumped it independently); resolved to the actual merged tree's count. `_pod.py` TOOLS.md changes auto-merged cleanly against FD-0.

---

### FD-2 — Structural Tester PASS/FAIL gate in dispatch (completes O2b)

- **Depends on:** — · **Parallel-safe with:** FD-1, FD-3, FD-4 · **Shares a file with FD-0** (`core/dispatch.py`) — sequence merges.
- **Read:** `core/dispatch.py` in full (`PIPELINE_ORDER`, the per-hop execution loop, `_apply_result`, the existing `verifyCmd` gate at ~L272-300 as the pattern to mirror); `cli/_pod.py:39` (`_ROLE_PURPOSE["tester"]`); `cli/_pod.py:85-91` (Tester SOUL.md body: "report a binary PASS/FAIL with evidence... do not read or critique the implementation"); `tests/python/test_dispatch.py`; `tests/python/test_cd2_verify.py` (the fixture pattern — `TestDispatchVerifyGate` — to extend for tester parsing).
- **Why:** the Tester role's entire documented contract is a binary PASS/FAIL report, but dispatch never reads hop content — only the adapter-level `run_res.ok` (did the subprocess call succeed) gates pipeline advancement. A Tester agent that writes "FAIL" in its response today still lets the pipeline proceed to `done`, because nothing parses what it said.
- **Do:**
  1. After a tester hop's `run_res.ok` is true, parse the returned message text for a PASS/FAIL marker using a simple, documented convention (e.g. first line matching `^(PASS|FAIL)\b`, case-insensitive).
  2. If the marker is `FAIL` or absent/unparseable, set `result.status="failed"` with a distinct reason string (mirror the `verification_failed` trace-event naming CD-2 already established) instead of letting the pipeline advance to `done`.
  3. Pods with no tester member are unaffected — this only gates pipelines that actually include a tester hop.
  4. Tests: PASS advances normally; FAIL blocks with the correct status + trace event; unparseable tester output blocks with a distinct reason (don't conflate with FAIL); pods without a tester keep today's behavior exactly.
- **Out of scope:** reviewer-hop gating (the reviewer's signal is already a real adapter-level `ok`, not a text convention needing parsing — no gap found there); redefining the Tester's SOUL.md prose beyond stating the marker convention it must follow.
- **Deliverables:** tester-output parser; dispatch gate wiring; new trace event; tests.
- **Acceptance gate:** [ ] a tester hop reporting FAIL blocks pipeline advancement with a distinct status/trace reason · [ ] unparseable tester output also blocks, distinguishably from FAIL · [ ] PASS and no-tester-in-pod cases unaffected · [ ] suite green.
- **Size:** M · **Status:** DONE — merged into develop 2026-07-02 (branch commit `1312ca0`), first of the wave to merge, clean (no conflicts against the then-empty develop delta).

---

### FD-3 — High-risk action-class always-approve policy (completes S1a)

- **Depends on:** — · **Parallel-safe with:** everything.
- **Read:** `core/security.py` in full (`SAFE_BINS`, `resolve_safe_bin_paths`, `build_exec_approvals`, `apply_approval_routing`); `specs/functional/security-gates.spec.md`; `core/approval.py` (`approval_create`, the shape a routed-to-approval action produces); `cli/_gates.py` (the `enable` flow, where a new policy layer would be applied).
- **Why:** today's gating is a flat binary allowlist — a command either matches `SAFE_BINS` or it doesn't. There is no concept of an *action class* above that: a `git push --force` or `docker stop` on a prod-tagged container is exactly the kind of consequential action that should never be silently auto-approved just because the binary itself is generally allowlisted.
- **Do:**
  1. Define a small, explicit, documented `HIGH_RISK_PATTERNS` list in `core/security.py` — glob/regex command patterns for money-movement, prod-deploy, and secret-access action classes. Keep the seed list intentionally small and named — this is a policy foundation, not exhaustive coverage.
  2. Wire it into `build_exec_approvals` (or a sibling function) so any command matching a high-risk pattern is always routed to `ask` (approval-required), **regardless of `SAFE_BINS` membership** — allowlist status must never bypass a high-risk match.
  3. Add read-only visibility — a way to list the currently-enforced high-risk patterns (e.g. `docket gates` output, or a `docket gates classes` subcommand). Configurability (user-editable pattern list) is explicitly deferred, not required here.
  4. Tests: a high-risk pattern match forces `ask` even when the binary is separately allowlisted; a non-matching allowlisted command is unaffected; `gates enable`/`isolate` still function.
- **Out of scope:** making the pattern list user-configurable via a config file (ship a sane built-in default; a config override is a natural follow-up card, not required here); changing the allowlist mechanism itself.
- **Deliverables:** `HIGH_RISK_PATTERNS` + always-ask wiring; visibility command/output; tests.
- **Acceptance gate:** [ ] a high-risk-matching command always routes to approval even if its binary is allowlisted · [ ] non-matching allowlisted commands unaffected · [ ] the enforced pattern list is visible via the CLI · [ ] suite green.
- **Size:** M · **Status:** DONE — merged into develop 2026-07-02 (branch commit `4a47c44`, amended from the original `0ddee9b`). **Narrowed before merge:** the subagent's original implementation excluded `git`/`npm` entirely from the seeded allowlist to force high-risk invocations to always ask; caught via user review that the daemon's binary-only gating means this also blocks every benign invocation (`git status`, `npm test`). Re-scoped in-place: `HIGH_RISK_PATTERNS`/`docket gates classes` ship as documented policy, but `git`/`npm` stay allowlisted — per-argument enforcement for allowlisted bins is now an explicit deferred backlog item, not silently claimed as enforced. money-movement/secret-access classes (no allowlist overlap) are fully enforced today.

---

### FD-4 — Audit-log parity for approval grant/deny across all channels (completes S1b)

- **Depends on:** — · **Parallel-safe with:** everything.
- **Read:** `core/approval.py` (`approval_grant`/`approval_deny`, ~L136-169, the existing `_emit_trace` calls); `core/audit.py` in full (`audit_log` shape: `{ts, user, pid, action, detail}`); `_gates.py:153` (an existing `audit_log("gates.enable", ...)` call — the pattern to match); `cli/_approve.py`, `cli/_deny.py`, `serve.py`'s `POST /approvals/<token>` handler (~L332-368), and wherever a Telegram-triggered grant/deny path calls into `approval_grant`/`approval_deny` — locate and thread a channel tag through all three.
- **Why:** `docket approve`/`docket deny` (CLI), the HTTP webhook (`serve.py`), and Telegram all already work end-to-end — but `approval_grant`/`approval_deny` only emit trace events, never call `audit_log()`. `docket audit` has zero record of who approved what, through which channel, unlike `gates enable/disable` which already does this correctly.
- **Do:**
  1. Add `audit_log("approval.grant", f"token={token} project={project} channel={channel}")` / the `deny` equivalent inside `approval_grant`/`approval_deny`.
  2. Thread a `channel` argument through every call site: `cli/_approve.py`/`cli/_deny.py` pass `"cli"`, `serve.py`'s handler passes `"http"`, the Telegram path passes `"telegram"`.
  3. Tests: grant/deny via each of the three call sites produces both the existing trace event (unchanged) and a new audit-log line carrying the correct channel tag.
- **Out of scope:** redesigning the trace mechanism itself; changing `approval_create`'s record shape.
- **Deliverables:** `audit_log` calls in `approval_grant`/`approval_deny`; channel threading through CLI/HTTP/Telegram call sites; tests.
- **Acceptance gate:** [ ] every grant/deny, from any channel, produces an audit-log entry with a correct channel tag · [ ] existing trace-event behavior unchanged · [ ] suite green.
- **Size:** S · **Status:** DONE — merged into develop 2026-07-02 (branch commit `0894a4f`), clean. No production Telegram call site for `approval_grant`/`approval_deny` was found to exist yet (confirmed: `approval_create` has zero production callers today) — `channel="telegram"` is ready for whenever that path is wired up.

---

### FD-5 — `security-gates.spec.md` truth pass + gates-default-on flip

- **Depends on:** FD-3, FD-4 landed (the spec's own stated blocking condition — headless routing + an audit trail — must actually be true before the spec can say so) · **Do after FD-3/FD-4 merge.**
- **Read:** `specs/functional/security-gates.spec.md` in full, especially its "Implementation status" callout deferring on-by-default pending "per-agent headless approval routing"; `cli/_install.py` (the current `--gates` opt-in flag and its default); `CLAUDE.md`'s security bullet; `docs/SECURITY-SIMPLE.md`.
- **Why:** the spec explicitly defers gates-default-on because session-mode (Telegram) delivery "only answers prompts during an interactive session" and default-on "could deny an unattended agent with no approver." But the CLI (`docket approve`/`deny`, list-pending) and HTTP (`serve.py`'s webhook) channels already work headlessly today, and after FD-3/FD-4 land, every approval decision is audit-logged and money-movement/secret-access actions always route to approval. The spec's own blocking condition (headless routing) is met — leaving it un-flipped is exactly the kind of doc/code drift Phase 12 fixed once already. **Note on FD-3's actual scope (narrowed during review):** don't claim high-risk enforcement is complete for `git`/`npm` — those stay allowlisted because the daemon's exec-gate can't tell `git push origin main` apart from `git status` at the binary-path level; only money-movement/secret-access (no allowlist overlap) are fully enforced today. State this honestly rather than overclaiming — it doesn't block the flip, since gates-default-on was never conditioned on prod-deploy git/npm enforcement specifically, only on headless routing existing.
- **Do:**
  1. Update `security-gates.spec.md`: document the CLI/HTTP approval channels as real and headless-capable (not "Telegram is the intended channel"); document the high-risk action-class policy (FD-3) accurately (money-movement/secret-access fully enforced; prod-deploy's git/npm overlap is policy-documented but not daemon-enforced, a deferred backlog item) and audit-log parity (FD-4); change the on-by-default status line from deferred to current, with the reasoning above.
  2. Flip `docket install`'s gates flag default from opt-in to on; keep an explicit `--no-gates` escape hatch.
  3. Update `docs/SECURITY-SIMPLE.md`, `CLAUDE.md`'s security bullet, and README (if it states gates are opt-in) to match.
  4. Tests: `docket install` with no flags produces a gates-enabled state; `--no-gates` still opts out; update any existing gates tests that assumed opt-in-by-default.
- **Out of scope:** retroactively enabling gates on already-installed fleets (this only changes the default for new installs); any change to the gates mechanism itself beyond the default.
- **Deliverables:** updated spec; flipped install default; updated docs; tests.
- **Acceptance gate:** [ ] spec accurately describes all real approval channels and states the on-by-default condition is met · [ ] `docket install` defaults to gates-on · [ ] `--no-gates` still works · [ ] suite + goldens green (new golden case for changed `install --help`/output if any).
- **Size:** M · **Status:** DONE — merged into develop 2026-07-02 (branch commit `4996595`). Real conflict with FD-6 in `security-gates.spec.md` (both branches independently wrote a "High-risk action classes" requirements section) — resolved by hand: kept FD-6's more detailed section, removed the duplicate, combined both branches' Changelog entries into one, merged the Examples section to keep both the docker-stop note and the `gates classes` output example.

---

### FD-6 — Spec/data truth pass for fields touched this phase

- **Depends on:** FD-0, FD-1, FD-2, FD-3, FD-4 landed · **Parallel-safe with:** FD-7.
- **Read:** `specs/data/docket-meta.spec.md` (`verifyCmd`, `portRangeStart/Count`, `scratchDir` fields); any `specs/functional/*.spec.md` covering dispatch/pod pipeline behavior; `specs/acceptance/user-stories.md`.
- **Why:** CH-10 (Phase 12) made every spec a current-state contract as of 2026-07-02. This phase changes real, user-visible behavior (env injection, a new `--verify` flag, a tester enforcement gate, a high-risk approval policy) — specs need to reflect it immediately, not drift again the way `security-gates.spec.md` itself did.
- **Do:**
  1. Update `docket-meta.spec.md` for the now-real `--verify` flag and env-injection behavior (FD-0/FD-1).
  2. Add or update a dispatch-behavior spec section documenting the tester PASS/FAIL gate and hop-failure semantics (FD-2) — CH-10's research found no spec currently owns the dispatch state machine directly; add one if still true.
  3. Document the high-risk action-class policy (FD-3) in the appropriate functional spec — accurately: money-movement/secret-access classes are fully enforced (no allowlist overlap); prod-deploy's `git`/`npm` overlap is documented policy but not daemon-enforced (deferred, tracked as backlog), since the daemon's allowlist can't gate by argument text. Don't overclaim this as "always blocks."
  4. Bump each touched spec's version header per the existing convention.
- **Out of scope:** a full spec audit (CH-10 already did that broadly; this is targeted to what FD-0…FD-4 changed).
- **Deliverables:** updated specs with correct version headers.
- **Acceptance gate:** [ ] every field/flag/behavior FD-0..FD-4 added is documented in the relevant spec · [ ] version headers bumped · [ ] `validate-specs.sh` (or equivalent) passes.
- **Size:** S · **Status:** DONE — merged into develop 2026-07-02 (branch commit `0838522`). Added `specs/functional/pod-dispatch.spec.md` (new — no prior spec owned the dispatch state machine, confirmed still true from Phase 12's research). Updated `docket-meta.spec.md` and `cli-interface.spec.md`. Its `security-gates.spec.md` edit was later reconciled with FD-5's during that merge (see FD-5's note).

---

### FD-7 — Docs/positioning pass — claim the closed gaps

- **Depends on:** FD-0 through FD-5 landed · **Parallel-safe with:** FD-6.
- **Read:** README.md's positioning section; `docs/SECURITY-SIMPLE.md`; `internal-docs/competitive-analysis.md` (the source doc whose Tier-1 framing went stale this phase — correct it so a future session doesn't re-discover this same substrate as "missing").
- **Why:** docket now has env-level pod resource isolation, a verification gate that actually enforces tester PASS/FAIL, and secure-by-default governance — the P1/O2/S1 differentiation claims are true now, not aspirational. The analysis doc itself should record that its Tier-1 recommendations are closed, so it doesn't mislead a future planning pass the way it partially did this one (see Phase 13's ROADMAP section).
- **Do:**
  1. Update `internal-docs/competitive-analysis.md`'s Tier-1 section with a "Status: closed 2026-07-02, see ROADMAP Phase 13" note per bet — don't rewrite the historical research itself.
  2. Update README.md/docs positioning to claim env-level pod isolation, tester-enforced verification, and secure-by-default governance, where each is now accurate.
  3. Run `scripts/metrics.py --check` to confirm no README numbers drifted from the added tests/files.
- **Out of scope:** a full docs sweep (CH-11 already did that broadly in Phase 12); new marketing copy beyond factual claims already true in the tree.
- **Deliverables:** corrected competitive-analysis.md; updated positioning copy; drift guard green.
- **Acceptance gate:** [ ] competitive-analysis.md records the Tier-1 bets as closed · [ ] positioning copy matches shipped behavior · [ ] `scripts/metrics.py --check` green.
- **Size:** S · **Status:** TODO

---

## Roll-up checklist (Phase 13 definition of done — mirrors ROADMAP exit criteria)

- [x] FD-0 — implementer subprocess env contains its real allocated port range + scratch dir. *(DONE 2026-07-02)*
- [x] FD-1 — `verifyCmd` settable via a public CLI flag, documented in TOOLS.md. *(DONE 2026-07-02)*
- [x] FD-2 — a tester hop reporting FAIL (or unparseable) blocks pipeline advancement. *(DONE 2026-07-02)*
- [~] FD-3 — a defined high-risk action-class list always routes to approval regardless of allowlist. *(DONE 2026-07-02 — narrowed: fully true for money-movement/secret-access; prod-deploy's git/npm overlap stays allowlisted, deferred to backlog per the daemon's binary-only gating limit)*
- [x] FD-4 — every approval grant/deny, any channel, writes an audit-log entry. *(DONE 2026-07-02)*
- [x] FD-5 — `security-gates.spec.md` reflects the real channel set; `docket install` gates default flips to on. *(DONE 2026-07-02)*
- [x] FD-6 — specs/data truth pass for every field/behavior this phase touched. *(DONE 2026-07-02)*
- [ ] FD-7 — docs/positioning claim the closed gaps; competitive-analysis.md corrected.
- [ ] Full suite green throughout: ruff + format + mypy strict + pytest + goldens.
