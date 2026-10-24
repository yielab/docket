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
      --dist loadfile -q --tb=line -p no:cacheprovider > <file>`, about 40 s), reads only the `FAILED`
      lines, fixes by cause and re-runs `--lf`. Never a second full run for the same merge.
   6. Goldens, the agent lane, `scripts/maint/pytest-without-sandbox.sh`, the escape matrix,
      `validate-specs.sh`, `metrics.py --check`, the generated-docs checks and the real run: once, at
      the phase close.
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
   `docket_runtime` facade stay byte for byte. **Nothing is kept for the past** (D-57): no alias,
   re-export, shim or compatibility reader; a replaced name is deleted in the same change.
8. **Central files are integrator-owned:** `TODO.md`, `ROADMAP.md`, `README.md` metric counts and
   `CHANGELOG.md`. A worker reports what shipped; it does not edit them.
9. **Commits:** `Type: description`, ASCII only, a detailed body, no AI or assistant attribution.
   Scrub `/home/<user>` paths and real names from every diff.

**Status:** `TODO` · `IN-PROGRESS (@who)` · `BLOCKED (needs X)` · `PARKED (left: X)` · `DONE`.
**Size:** S ≈ one short run · M ≈ one run · L ≈ one long run that may park once.
**Branch model (D-52):** card branches base on and merge into the integration branch (`develop`;
Phases 46-47 run on `plan/phase-46-structure` until the maintainer integrates it). `main` moves only
by a fast-forward from `develop` when the maintainer cuts a release. Tags and release jobs originate
from `main`.

## ◇ PHASE 47 — CLOSE-OUT (active): meet the acceptance ADR 0030 states, take the moment, close

> **Where it stands (2026-10-24, `plan/phase-46-structure` at `d1fa3d30`).** Wave 1 (P47-1..P47-9,
> archived) shipped ports for git, processes, the jail, the tracer and the tool gate; `agent` as the
> turn engine; a task's `status` in one transition table with one writer; the gate decisions as pure
> functions; one owner per test helper; and the layers contract (import baseline 748 -> 65 lines).
> P47-7 (tests by context) is done on its branch and not merged. The close-out finishes the
> structure, folds in the configuration findings of the 2026-10-24 comparison and the rest of the
> test audit, so the code is moved once and the tests are rewritten once.
>
> ADR 0030 §"Phase acceptance", clause by clause, measured at `d1fa3d30`:
>
> | Clause | Now | Closed by |
> | --- | --- | --- |
> | No upward import between contexts | 62 module pairs, plus 2 named `agent` exceptions | P47-11 |
> | Function-local `docket` imports: 0 | 19 | P47-11 |
> | Largest module ≤ 700 lines; `status` writers 1; no `cli/`, `core/`, `edges/`, `serve.py` | met | — |
> | No patch on another module's private alias | not measured (37 cross-module patch targets) | P47-13 |
> | Unit tests at their mirror path; integration under `integration/<context>/` | on branch `p47-7-test-layout` | P47-10 |
> | `docket_runtime` from `agent/` + `kernel/` with no build hook | the hook computes the closure from the import graph (52 files), as the P47-3 run decided | P47-14 amends the clause |
> | HTTP API 6, goldens, runtime boundary tests unchanged; live traces identical | not run since the last merge | P47-14 |

**Order, by file contention:**

```text
P47-10 ─► P47-11 ─► P47-12 ─► P47-13 ─► P47-14 close
M-1 ─────────────────┘   (M-1 must finish before P47-12; it runs beside P47-10 or P47-11)
```

- P47-10 goes first: it moves every integration test file the later cards edit.
- P47-11 moves modules between contexts; `move.py` carries their mirrored tests and the dotted names
  in specs. P47-12 then changes configuration behaviour in modules that already sit where they stay.
- P47-13 rewrites the tests last, once every patch target and helper has stopped moving.
- P47-14 runs the full gates, the goldens and the real run once, after all code has settled.
- M-1 only runs commands through the policy path and commits a data file; P47-12 turns it into a test.

### P47-10 — integrate P47-7 and make every document cite the test paths that exist

**Status:** DONE (2026-10-24: merge `f5e86413`, citations `f662d2f1`; 47 stale paths fixed, parallel run: one failure, a guard over its 2 s time ceiling under load, which passes alone) · **Size:** S · **Owner:** integrator (not a docket task) · **Kind:** M

- **Trigger (measured 2026-10-24):** branch `p47-7-test-layout` (last green `261c245c`, 30 commits on
  `d1fa3d30`) moved the 134 integration files into `tests/integration/<context>/` and split the 11
  files over 800 lines; it is not merged. Its worker reported about 17 specs, `docs/adr/*.md` and
  `SSD-WORKFLOW.md` citing the old flat `tests/integration/test_*.py` paths, and stale test counts in
  `CONTRIBUTING.md`. Before the merge, 8 cited test paths already do not exist.
- **Steps:**
  1. `git merge --no-ff p47-7-test-layout`; one parallel default run (budget item 5.5).
  2. A one-shot script maps each old path to its new one from the move commits (`git log
     --name-status --diff-filter=R d1fa3d30..p47-7-test-layout`) and rewrites the citations in
     `specs/`, `docs/` (not `docs/cycles-ended/`, which is byte-preserved history), `CONTRIBUTING.md`
     and `SSD-WORKFLOW.md`. A citation to a file the card split points at the file that now holds the
     cited test. Delete the script in the same commit.
  3. `CONTRIBUTING.md` counts from `uv run python scripts/metrics.py`.
- **Acceptance:** `rg -o --no-filename "tests/[A-Za-z0-9_/]+\.py" specs docs CONTRIBUTING.md
  SSD-WORKFLOW.md --glob '!docs/cycles-ended/**' | sort -u` lists only files that exist;
  `bash scripts/validate-specs.sh` passes; the parallel run is green.
- **Non-goals:** test content; spec versions (a path-only edit does not bump one).

### P47-11 — the context structure: each module where its data lives, no upward or local import, no shim

**Status:** IN-PROGRESS (@sonnet, branch `p47-11-layers` from `f662d2f1`) · **Size:** L · **Model:** Sonnet, one run (may park once) · **Kind:** M + T
(judgment on a computed plan)

- **Trigger (measured at `d1fa3d30`):** ADR 0030 §"Phase acceptance" requires no upward import between
  contexts and no function-local `docket` import. Now: 62 upward module-pair imports, 19 function-local
  imports, 45 imports of another context's private (`_name`) names over 25 module pairs, and four shims
  that D-57 forbids.
- **Why move modules instead of fixing edges one by one (measured 2026-10-24).** The 62 upward imports
  point at only 21 modules, and the largest groups are modules that use another context's private
  names: `pipeline/application/executor.py` imports privates of `hops.application.record` (5),
  `hops.gates.post_hop` (4), `hops.gates.pre_hop` (4) and `hops.application.runner` (2);
  `pipeline/application/steps.py` those of `compose` (3), `record` (3), `post_hop` (3), `pre_hop` (2)
  and `runner` (1). A module that needs another context's private names lives in the wrong context. A
  what-if planner that reassigns whole modules, keeping `LAYERS` fixed, takes the upward count from 62
  to 7 with 21 moves. So the card computes the plan, reviews each move, executes it with the existing
  codemod, and spends judgment only on what remains.
- **Read:** ADR 0030 (the table, §"After Phase 46", §"Phase acceptance"); `scripts/maint/refactor/move.py`
  (its docstring is the `refactor/target-map.toml` schema: `[[module]]` and `[[definition]]` moves, with
  imports, `setattr` targets, `SUBJECT`, mirrored unit tests and dotted names in specs and docs
  rewritten); `scripts/maint/refactor/hoist_imports.py` (docstring); `kernel/ports.py` (the port idiom);
  `tests/architecture/test_import_contracts.py`.
- **Steps (one commit per step, or per destination context in step 3; gate after each):**
  1. **The planner.** Write `scripts/maint/refactor/plan_layers.py` (deleted at the close with the other
     refactor tools). It builds the module import graph of `src/docket` (top-level and function-local
     `from docket.X import y`, with `y` resolved to a submodule when it is one), takes `LAYERS` from
     `tests/architecture/test_import_contracts.py`, counts upward imports, and greedily applies the
     single whole-module reassignment that removes the most, until none helps. It prints the moves with
     their gain, the upward imports left with the names that cross, the cross-context private-name
     imports, and the exact minimal layer order for the moved tree (a DP over the 2^11 subsets of
     contexts). Same tree, same output. Run it on the merged tree.
  2. **The review.** Accept a proposed move when the module reads or writes the destination context's
     data, or uses its private names, and the move does not split a coherent group in the source.
     Reject it when the module is cross-cutting infrastructure or the optimiser only exploits the order.
     Write the accepted moves to `refactor/target-map.toml` with a one-line reason each. Preliminary
     verdicts from the 2026-10-24 run, to confirm or overturn with evidence:

     | Proposed move | Verdict | Why |
     | --- | --- | --- |
     | `pipeline.application.executor`, `.steps` -> `hops.application` | accept | they drive hops through its private record, gates and runner |
     | `tasks.application.sweep`, `.answers`, `.interruptions` -> `hops.application` | likely accept | they drive dispatch; `sweep` imports executor privates |
     | `governance.profile` -> `hops` | likely accept | it gathers gate facts; the decision already lives in `hops/domain/gate_decisions.py` |
     | `hops.application.record` -> `tasks.application` | likely accept | it persists a hop's result onto the task (6 importers, 9 private names) |
     | `agent.tools.builtin_tools` -> `hops.application` | accept if the default tool set stays identical | the default tool set is composition, not the engine; removes the 2 named `agent` exceptions; `teams.report`'s counts and the registry tests are the oracle |
     | `models.selection` -> `teams` | judge | alternative: receive role data, as P47-5 did for `pipeline/domain/plan.py` |
     | `teams.report` -> `hops` | judge | |
     | `observability.trace` -> `governance` | reject | infrastructure; move `redact` (a secrets rule) to `governance.secrets` as a definition move, or use the `Tracer` port |
     | `hops.workspace.{worktree,prepare,repo_view,skills}` -> `teams` | likely reject | splits `hops.workspace`; fix the importers instead |
     | `tasks.application.corrections` -> `governance`; `governance.network_posture`, `.review` -> `teams`; `teams.apply.plan`, `.write` -> `hops` | judge | one edge each; prefer a definition move |

  3. **Execute.** `uv run python scripts/maint/refactor/move.py --dry-run`, then the real run, then
     `--check` (a second run changes nothing). One commit per destination context.
  4. **What remains**, per edge: (a) a type or constant moves to `kernel` or to the lower context;
     (b) a function on the lower context's data moves there (`[[definition]]`); (c) behaviour the higher
     context supplies becomes a parameter, or a port in the lower context bound in `bootstrap.py`. Then
     rename each private name still imported across contexts to a public one, with a one-shot script
     (the definition, `from M import _x`, `M._x`, `setattr(M, "_x", ...)`; refuse when the public name
     exists).
  5. **Local imports.** `hoist_imports.py --dry-run`, then the real run: it proves each hoist by
     importing every module in a fresh interpreter, and what it keeps as `cycle` is fixed as in step 4.
  6. **Shims and duplicates.** Callers use the real names (`task_token_budget` from
     `hops/domain/gate_decisions.py`, `kernel.brief.TaskBrief`, `enqueue_task_once`); delete the
     `pre_hop._task_token_budget` alias, the `TaskBrief` re-export at `kernel/operator_contract.py:18`
     and `enqueue_task` (one test call left). `_credential_sources` (`bootstrap.py:57`,
     `packages/docket-runtime/src/docket_runtime/_bind.py:22`) gets one home both import.
     `resolve_endpoint` (models logic at `models/adapters/openai_http.py:339`) moves to
     `models/application`, which removes the kept-rule edges `models.provider_lifecycle ->
     models.adapters.openai_http` and `models.adapters.openai_http -> governance.secrets`.
  7. **Re-plan.** Run the planner again and record its output, before and after, in the last commit's
     body. If the exact minimal order differs from `LAYERS` with strictly fewer upward imports, stop and
     report it: changing `LAYERS` is the maintainer's decision.
- **Rules:** never a function-local, lazy or re-export import to make an edge vanish. No behaviour
  change. A move that changes an owner a spec names updates that spec's prose in the same commit
  (`move.py` rewrites dotted names, not sentences). An edge that needs a decision parks with a report,
  and the run continues with the next. `tests/guards/test_runtime_closure.py` pins the runtime's file
  list: a moved module the runtime imports updates its expected path, and the count must not grow.
- **Tests:** no new behavioural test (these are moves); `move.py` carries the mirrored unit tests, and a
  patch on a moved name follows the binding the module under test reads.
- **Non-goals:** facades (optional under ADR 0030); any behaviour change; the Telegram edge
  (`operator.adapters.telegram -> interfaces.telegram.client`, pinned by Telegram spec 2.4.0).
- **Acceptance:** the import baseline holds only the Telegram line, plus any edge named with its reason;
  `local_imports_baseline.txt` is 0, or each remaining line is a named real cycle; the planner reports no
  cross-context private-name import; `rg -n "_task_token_budget|TaskBrief as TaskBrief|def
  enqueue_task\b" src packages` finds nothing and `rg -n "def _credential_sources" src packages` finds
  one definition; `cycle_largest` recorded before and after; baseline diffs are deletions only.
- **Gate:** per step `uv run pytest tests/architecture tests/guards -q`, `pytest --co`, and `uv run python
  -c "import docket.bootstrap, docket.interfaces.cli.app, docket.interfaces.http.server"`; at the end,
  one parallel default run, then `--lf` only.

### P47-12 — configuration: one authored form, no setting that silently does nothing, policies on the parsed command

**Status:** TODO after P47-11 (M-1 done) · **Size:** L · **Model:** Sonnet, one run · **Kind:** B (named
behaviour changes) + T

- **Trigger:** the maintainer's request (2026-10-24) to fold the configuration findings of the 2026-10-24
  comparison into this refactor, on these measured facts:
  - Three kinds have two authored forms plus a mix: `teams/roles.py` (`normalize_role`, `load_role_file`,
    which refuses a mix), `pipeline/domain/spec.py` (`normalize_pipeline`), `governance/policy.py`
    (`normalize_policy`: "short form, canonical, or a mix"). `teams/config_docs.py` guesses which one a
    person wrote. D-57 keeps nothing for the past.
  - `maxReworkCycles` is accepted and ignored when a pipeline is bound (`pipeline/application/steps.py`
    around line 126, which P47-11 may move; `docs/CONFIGURATION.md`'s row says "Ignored when you bind a
    pipeline").
  - A command policy matches a regular expression over the raw text (`when.matches`;
    `templates/policies/block-destructive.yaml` is one expression), while `governance/security.py`
    already splits a command into segments, unwraps wrappers and resolves redirect targets for
    `classify_command`. The other predicates (`tool`, `path`, `branch`, `plugin`, `anyOf`) are already
    structured. M-1's corpus (`tests/fixtures/policy-corpus/corpus.yaml`) records what passes today.
- **Steps (one commit each):**
  1. **One authored form.** An authored file (role, pipeline, policy, and whatever a `pod.yaml` embeds)
     is read only in its `kind:` short form; the canonical form is the in-memory model and the JSON that
     `platform/store.py` persists, never read from an authored file. First list every reader that accepts
     a canonical document from a file and mark it authored or persisted. Delete the canonical and mixed
     paths for authored files and `config_docs`' form guessing; a canonical document is refused with a
     message naming the short-form key to use. Convert every authored canonical document under
     `src/docket/templates/`, `tests/fixtures/` and the tests with a one-shot script built on the existing
     inverse functions (the `export` direction), then delete the script. Update `pipeline-format.spec.md`
     ("Short form"), the role and policy specs, `docs/contracts/config-v1/*.schema.json` and
     `docs/CONFIGURATION.md` §3.4-3.6.
  2. **No silent setting.** `docket pod set maxReworkCycles` on a pod with a bound pipeline, and a
     `pod.yaml` that declares both `settings.maxReworkCycles` and `pipeline`, are refused (exit 2) with a
     message naming the pipeline's own `on: {<label>: {goto, max}}`; `config explain` shows where the
     bound comes from. Update the spec section that owns pod settings and the CONFIGURATION row.
  3. **A `command` predicate, scoped by M-1's measurement** (corpus merged `7a7b31af`; the integrator's
     summary of what passed, by class, is quoted here because a worktree has no `internal-docs/`):
     - **Class A, fix:** text the segment parser already normalizes. Option before the verb (`kubectl
       -n prod apply`, `terraform -chdir=x apply`, `helm -n prod upgrade`; this also defeats the
       classifier's `secret-access` class), quoting (`"rm" -rf`, `r''m`, `s""tripe`), long and short
       flags (`rm --recursive`, `git push -f`, `+ref`, `--all`, `HEAD:refs/heads/x`), wrappers (`env`,
       `xargs`, `find -delete`), write targets by other programs (`ln -sf`, `install`, `dd`, `rsync`,
       `perl -pi`, `tee -a /etc/passwd`), and programs the policies do not name (`git clean -fdx`,
       `git reset --hard`, `tofu`, `podman`, `flyctl`, `vercel`, `gh release`, `cargo publish`,
       `twine upload`, `aws secretsmanager`/`ssm put-parameter`, `openssl genpkey`, `gpg
       --full-generate-key`, `passwd`, `pkill`, `truncate`, `mke2fs`).
     - **Class B, do not chase:** opaque code in an allowlisted interpreter with isolation off
       (`python3 -c` with string concatenation, `node -e`, `perl -e`, a script written then run,
       `base64 -d | sh`). No parser fixes it; the jail is its containment and the isolation default is
       a maintainer decision (ROADMAP §7.1). Record it as a known limit in the security spec and
       `docs/SECURITY-SIMPLE.md`.
     - **Class C, partial:** `secret-pii-redact` gains fixed patterns for `ghp_`/`github_pat_` tokens,
       `AKIA` key ids, `*_PASSWORD=`, JWTs, `-----BEGIN ... PRIVATE KEY-----` blocks and `Bearer`
       headers. `prompt-injection` stays a phrase tripwire; its description says so, and paraphrases
       are recorded as a known limit.

     RED first: add an `expected` column to the corpus (`asked`/`denied`/`redacted` for class A and the
     six patterns; today's outcome plus `limit: <reason>` for B and C rows not fixed) and a table test
     over it (unit lane, `tests/unit/governance/test_policy__corpus.py`) that drives
     `governance.gate.evaluate_tool_call` for tool rows and `policy_eval_detail` for screen rows (the
     invocation is in the corpus header). Then expose the classifier's segment parser as one public
     function in `governance/security.py`, make the high-risk class detection skip options before the
     verb, and add `when.command` with `program` (names), `args` (any of these arguments, short and
     long spellings) and `writes` (path globs of redirect and write targets), evaluated on every
     segment after unwrapping. `matches` stays for text with no structure (SQL). Rewrite the baseline
     policies in `src/docket/templates/policies/` with it. Bump the policy and security-gates specs,
     update `policy.schema.json`, regenerate `docs/recipes.md` (`scripts/gen_recipe_docs.py`).
- **Named behaviour changes:** an authored canonical document is refused; `maxReworkCycles` with a bound
  pipeline is refused; the baseline policies catch M-1's class A rows; the classifier asks for a high-risk
verb behind options; the redaction screen covers six more secret shapes. CLI output changes for those cases;
  P47-14 regenerates the affected goldens with the diff explained line by line.
- **Non-goals:** parallel steps or fan-out (a new feature; its trigger stays in the follow-ups); new
  kinds; channel, exporter, mcp-server and provider documents (check each has one form; list any that
  does not).
- **Acceptance:** a canonical role, pipeline or policy file exits 2 with the message; the two refusals
  are tested; the corpus table is green, every class A row is asked or denied, no row's outcome got weaker,
and every row left allowed carries a `limit:` reason that the security spec names; `rg -n "is unambiguously short
  form" src` finds nothing.
- **Gate:** the unit tests of `governance`, `teams/roles`, `pipeline/domain` and the config documents;
  `tests/architecture`; `pytest --co`; at the end, one parallel default run, then `--lf` only.

### P47-13 — the tests: one name per helper, no test imports another, no private-alias patch, no I/O in unit, configuration through `Home`

**Status:** TODO after P47-12 · **Size:** L · **Model:** Sonnet, one run (may park once) · **Kind:** M

- **Trigger (measured):**
  - ADR 0030 §"Phase acceptance" requires no patch on another module's private alias;
    `monkeypatch_cross_module_targets` is 37 at `d1fa3d30` (`analyze.py --metrics`), not yet split into
    private and public. Among them, P47-5 named the gate fact sources `_pod_settings`, `_trace_locked`,
    `pod_recorded_cost`, `pod_gating_cost` and `pod_full_roster` (19 patches).
  - P47-6 kept non-identical helper variants under numeric suffixes: `seed_pod_2..4`, `write_meta_2..4`,
    `meta_2` (`tests/support/pods.py`), `post_2/3`, `get_2` (`tests/support/http.py`), `hermetic_2..6`.
  - Test files import helpers from other test files (re-measure with `rg -n "^from
    tests\.(unit|integration|agent)" tests`).
  - The ratchets P47-7 recorded in `tests/guards/suite_shape_baseline.txt`: five unit files do real I/O
    (`test_client` for Telegram, `test_fetch`, `test_progress`, `test_plan`,
    `test_sweep__scheduled_and_webhook_dispatch`); `setenv` in 55 files; `in result.output` on a command
    that has `--json` in 18 files. ADR 0030 point 4: a test owns its `Home(tmp_path)`.
- **Goal:** each helper has one name that says what it does (variants that differ get names that say
  how; identical ones fold); no test module imports another (the helper moves to `tests/support/`); a
  patch on another module's `_name` becomes a fake bound through its port (`<port>.use(fake)`) or a patch
  on the public binding the module under test reads, with a small port in the owning context for the
  cost and settings reads the gates use; unit files do no real I/O (a fake from `tests/support/fakes.py`,
  or the file moves to `integration/<context>/`); `setenv` stays only in the tests of environment parsing
  (an explicit list), the rest configure through `Home`; a command with `--json` is asserted on its
  parsed JSON.
- **Steps (one commit each):** (1) measure and list; (2) rename and fold helpers with a one-shot script,
  deleted in the last commit; (3) move cross-test helpers to `tests/support/`; (4) the private-alias
  patches; (5) unit I/O; (6) `setenv` to `Home`; (7) `--json` asserts; (8) a guard in
  `tests/guards/test_suite_shape.py` refuses a `monkeypatch.setattr` or `mock.patch` on another module's
  `_name`, seen failing on a plant, and the three ratchets fall to 0 or each remaining entry is named
  with its reason.
- **Non-goals:** what a test asserts; test speed (the parallel suite takes about 40 s).
- **Acceptance:** no `_<digit>` helper name in `tests/support/`; no `from tests.(unit|integration|agent)`
  import; the private-alias guard and the three ratchets at 0 or named; collected test ids unchanged
  except tests that moved path.
- **Gate:** `uv run pytest tests/guards -q`, `pytest --co`, and the files each step touched; at the end,
  one parallel default run, then `--lf` only.

### P47-14 — close Phase 47

**Status:** TODO after P47-13 · **Size:** M · **Owner:** integrator (not a docket task) · **Kind:** close

- **Steps:**
  1. Amend ADR 0030 §"Phase acceptance": the `docket_runtime` clause becomes what the P47-3 run decided
     (the build hook computes the closure from the facade's import graph; the runtime boundary test is
     the oracle), with the reason (the boundary test requires the runtime to own no `docket/` path and
     import no `docket` module, so the gate implementations ship rewritten).
  2. The full gates, once: the parallel default suite, `scripts/maint/pytest-without-sandbox.sh -q`, the
     escape matrix, `bash tests/golden/run.sh verify-all` (P47-12's named changes regenerated with the
     diff explained line by line), `uv run pytest tests/agent`, `bash scripts/validate-specs.sh`,
     `uv run python scripts/metrics.py --check`, `gen_cli_docs.py --check`, `gen_recipe_docs.py --check`,
     `comment_lint.py --check` on the files Phase 47 touched.
  3. The real run on `fab-dev`, compared with `internal-docs/baselines/phase-46/after/dispatch`: same
     hop order, event types and transitions.
  4. Delete the refactor tools: `scripts/maint/refactor/` (`analyze.py`, `move.py`, `hoist_imports.py`,
     `plan_layers.py`, `docket-rules.toml`), `refactor/target-map.toml`, `scripts/maint/refactor_gate.sh`,
     `tests/guards/test_refactor_*.py`, `tests/guards/fixtures/refactor/`, and every reference to them
     (`rg -n "refactor_gate|maint/refactor|target-map"`). `tests/architecture/` is the durable record.
  5. Archive this section, add the Phase 47 row to the ROADMAP phase table, update its Status, write the
     `CHANGELOG.md` entry, and align `CONTRIBUTING.md`'s definition of done with ROADMAP §4.
  6. Ask the maintainer to integrate `plan/phase-46-structure` into `develop` and push; the `no-sandbox`
     CI job runs for the first time then (ROADMAP §7.1).
- **Acceptance:** every clause of ADR 0030 §"Phase acceptance" is true, each named with its evidence in
  the close commit's body.

### M-1 — does a rephrased command pass the baseline policies?

**Status:** DONE (2026-10-24: `d27ba3e8`, merge `7a7b31af`; 310 rows; findings by class folded into P47-12 step 3) · **Size:** S · **Model:** Sonnet · **Kind:**
measurement (no `src/` change)

- **Trigger:** the maintainer's request (2026-10-24) to plan from the comparison in
  `internal-docs/strategy/competitive-and-yaml-2026-10-24.md`. Governance is docket's lead claim, and the
  baseline policies match regular expressions over the command text
  (`src/docket/templates/policies/block-destructive.yaml` is one long expression). A bypass has not been
  demonstrated; an estimate does not schedule a fix, a measurement does.
- **Goal:** for each policy in `src/docket/templates/policies/`, try at least five commands with the same
  effect and different text (quoting, variables, `env`/`command` prefixes, `xargs`, `find -delete`,
  here-docs, `base64 -d | sh`, `python -c`, `perl -e`, a script written then run) through the real path a
  tool call takes (`dispatch_tool`: role denials, then `classify_command`, then the policies), in a
  throwaway `DOCKET_HOME`, with isolation off and then on. Record per command the outcome (allowed,
  asked, denied) and the layer that decided.
- **Output:** `tests/fixtures/policy-corpus/corpus.yaml`, one row per command (`policy`, `command`,
  `effect`, `isolation`, `outcome`, `layer`), committed as data; P47-12 turns it into its table test. The
  worker's report lists every command allowed by all layers with a destructive effect, the policy it
  should have matched, and why it did not; the integrator files it in `internal-docs/audits/`.
- **Non-goals:** changing a policy, the classifier or the jail (P47-12 does that).
- **Acceptance:** every baseline policy has at least five rows, each with its deciding layer; `git diff
  --stat src/` is empty.

## ◇ FOLLOW-UPS WITH TRIGGERS (not cards; triage when a trigger fires)

> Re-checked against the code on 2026-10-24; paths are current. Removed as no longer true: notification
> dedup is persisted (`operator/notify.py`), the `kind:`-less canonical-document advisory is gone, and
> `_create_workspace` no longer exists. Decisions that belong to the maintainer are in ROADMAP §7.1.

**Fired, waiting for a maintainer go (the measurement spends hosted-model tokens).**

- **The implementer sends 0.65 of what the backend counts** (Phase 45 real runs on `fab-dev`,
  2026-10-20: 14 and 13 calls, largest request about 7,000 estimated tokens; reviewer 0.62, tester 0.80
  and 0.90). The Phase 44 trigger ("a real implementer run with its grants declared that still sends
  over half") fired. Next: on a real run, measure which calls repeat before cutting anything.

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

**Configuration (2026-10-24 comparison; the form, `maxReworkCycles` and policy findings are P47-12).**

- **Pipelines are linear with routing; the reference documents no parallel branch or fan-out.**
  Trigger: a real task that needs fan-out (check `pipeline-format.spec.md` first).
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

**Architecture and packaging.**

- **The runtime closure grows with any facade on a context the runtime imports** (measured in P47-8:
  agent 52 -> 75, teams 52 -> 157, governance 52 -> 101, observability 52 -> 60 files). Trigger: a
  proposed facade on one of them.
- **`FailureKind` enumerates only the four kinds the task state writes**; hop and gate kinds stay plain
  strings (pod-dispatch spec item 9). Trigger: the next change to those kinds.

**Tests.**

- A worker's `monkeypatch.undo()` once undid the autouse home isolation and wrote into the real
  `~/.docket`; the fixture guards `setattr`, not `undo`. Trigger: a second leak.
