# ROADMAP changelog (archived)

The decision/phase changelog that lived at the end of `ROADMAP.md`. It has two parts:

- **`## Entries since the archive`** — the live decision log. New entries go here, newest first.
- **`### Changelog`** — the archived block, byte-identical to what `ROADMAP.md` carried on
  2026-09-11 and covered by `manifest.json`. **Never edit inside it**; the hash check would fail.

Release notes for users stay in the root `CHANGELOG.md`.

## Entries since the archive

- **2026-09-11 (Phase 25 activated / W29-C7 and Wave 30 deferred) — the maintainer chose to make
  the repository maintainable before publishing it further.** Wave 31 is the active board; W29-C7
  (publish the provenance-complete beta, close Phase 23) keeps its 2026-09-07 publication approval
  and changes only in ordering, and Wave 30 (harness mode) waits because W31-C1 moves every test
  file it would own. The same day, `scripts/maint/split_board.py` archived 49 closed board and
  phase sections into `docs/cycles-ended/` byte for byte with a SHA-256 manifest, cutting `TODO.md`
  from 4,946 to ~1,070 lines and `ROADMAP.md` from 3,637 to ~810, so the live files carry only
  active and planned work.


### Changelog

- **2026-09-11 (Phase 25 planned / D-36 recorded / test-framework 2.13.0) — the repository is
  scheduled to become maintainable by a person, with the agent's own checks fenced into a budgeted
  lane.** The maintainability audit (`internal-docs/maintainability-audit-2026-09-11.md`, working
  tree at `0d3720a`) measured an 8 min 12 s default suite whose 15 slowest tests are all
  release/evidence/adapter checks, 35 files (8,313 lines) verifying prose, release artifacts or the
  agent's hook scripts, `serve` tested across 19 files, 89 archaeology hits in comments and
  docstrings, a 4,628-line board with the active wave at line 1642, and three functions over 500
  lines. D-36 rules on lanes, naming, a ratcheted comment linter, generated reference docs and a
  board archive; Wave 31 is nine cards on the board with W31-C0–C3 ordered before Wave 30 because
  C1 moves every test file. `specs/test-framework.md` 2.13.0 states the lane contract and says
  plainly which parts are enforced today (none until W31-C2). `AGENTS.md`, `CONTRIBUTING.md`, the
  three skills and local `CLAUDE.md` were aligned in the same change so no standing document
  contradicts the target. Two analysis scripts (`scripts/maint/test_inventory.py`,
  `comment_lint.py`) exist and W31-C0 commits them.
- **2026-09-11 (Phase 24 planned / D-35 recorded / D-14 corrected) — harness mode has a corrected
  ADR and an executable five-card wave, and the decision table no longer misnames the shipped
  driver.** The 2026-09-08 draft of `docs/adr/0001-harness-mode.md` was audited claim by claim
  against `main` at `4032133` (`internal-docs/harness-mode-audit.md`). Its "what is true today"
  table held, including the finding that §6's D-14 row still said the one shipped driver was the
  retired external runtime; that row now names `DocketDriver` and dates the correction. Four of the
  ADR's twelve decisions described as existing something the code does not do: `run_bash` blocks in
  `communicate(timeout)` with every child in its own session and never reads
  `ToolContext.cancellation_check`, so neither `SIGTERM` nor `docket runs cancel` reaches an
  in-flight command (the same defect Tack's ADR cites to mark Claude Code `cancel: Advisory`); a
  gated tool call waits up to `TOOL_APPROVAL_TIMEOUT` and then the loop continues rather than
  stopping; `TurnResult` carries no usage; and the driver refuses a turn without a
  `.docket-meta.json`, so "never provisioned" needed to say what *is* written. A fifth decision
  contradicted `cli-interface.spec.md`'s flat exit-code convention. The ADR was rewritten to state
  each of those honestly, to amend D-30 in exactly one named place (a subprocess group may be
  killed; a thread or HTTP request may not), and to reuse `core/runs.py` as both run token and
  cancellation channel so that "no new store" is literal. Phase 24 is **planned, not active**: Wave
  30's cards W30-C1…C5 are on the board in `TODO.md`, and the activation gate is W29-C7 closing
  Phase 23. Three of the five cards are seams with value independent of the harness, and they
  start together; the subcommand is the fan-in, not the first card.

- **2026-09-07 (release pipeline) - the `v0.2.0-beta.2` publish failure is fixed, and a second,
  quieter release blocker was found behind it.** Run `34144421202` built, verified and attested the
  artifacts, then died on its last step with `failed to run git: fatal: not a git repository`. The
  cause is the property the pipeline is designed around: `publish` never checks out source, so
  `gh` had no remote to infer a repository from. `gh release create` now passes
  `--repo "$GITHUB_REPOSITORY"`, and a new guard asserts both halves of that pairing - no checkout
  step in `publish`, and an explicitly named repository in the release call.

  The second blocker: `Formula/docket-cli.rb` pinned `7ca506cf...4766c` under the comment "exact
  digest reported by the immutable GitHub release asset", but no such release ever existed and the
  digest matches nothing. Measured at tag commit `892209f`: the wheel is byte-identical between a
  developer machine and the release runner (`a5c0b60d...a44f` both times), but the sdist - which
  `docket-v<version>.tar.gz` copies - is not; local builds give `1c6a284f...5774`, the runner gave
  `00a4321e...a99d`, and the pin is a third value. A Homebrew pin therefore **cannot** be computed
  before the release, which contradicted `scripts/update-homebrew-sha.sh`'s own closing instruction
  to "commit the updated formula before cutting the release tag" - the script downloads the asset
  *from* the release. Script and formula prose corrected;
  `test_formula_digest_matches_the_published_release_asset` reads the published `.sha256` sidecar,
  skips while the release is absent, and fails the moment the pin is stale (seen red against the
  real `v0.2.0-beta.1` asset). `depends_on "bash"` was also dropped from the formula - it existed
  only for the Bash 4.0 floor removed the same day.

  **Published, on the operator's explicit approval.** `on: push: tags` runs the workflow from the
  tagged ref, so the fix had to reach the tag: `v0.2.0-beta.2` was moved from `892209f` to
  `40d86e3` (the old tag had produced no release and no assets, so nothing could have consumed
  it). Run `34170325367` is green - build and publish both - and the release now carries all six
  assets: wheel, sdist, versioned tarball, its `.sha256`, `SHA256SUMS`, and the SPDX SBOM, with
  build provenance attested. The published sdist digest is `9f48ba44...6a955`, a **fourth**
  distinct value for the one tagged commit, which is the reproducibility finding above stated as
  a fact rather than a prediction. The formula pin was then refreshed from that published asset;
  the guard was seen red against the stale pin first.

  **Follow-up worth a card, not a patch:** the sdist is not byte-reproducible off the release
  runner. Every consumer that must pin it - the Homebrew formula today, anything verifying a
  rebuild tomorrow - inherits that. A `SOURCE_DATE_EPOCH`-style fix would make the pin computable
  before the tag and close the ordering awkwardness the update script has to document.

- **2026-09-07 (advisory macOS lane) - all eight macOS-only suite failures are fixed, and the
  Bash floor the project actually needs is now 3.2 rather than 4.0.** Four distinct causes, none of
  them a product defect on Linux. (1) `scripts/validate-specs.sh` opened with `declare -A`, which
  Bash 3.2 rejects outright, so the CI-blocking validator printed nothing and
  `test_metrics_script.py::TestCheckReadmeUnit::test_spec_count_matches_the_blocking_validator`
  could not read a spec total; it now uses a `case` function, and `grep -P` became `grep -E`
  because BSD grep has no PCRE mode and the trailing `|| true` had been turning that rejection
  into a silently empty cross-reference check. (2) `install.sh` demanded Bash 4.0+ - a leftover
  from the Bash `lib/` that M6 removed - while using no Bash 4 construct at all, so it refused the
  stock macOS interpreter for the documented `curl ... | bash` install and failed both
  `test_release_artifacts.py` installer cases; the floor is now 3.2. `uninstall.sh`'s
  `${CONFIRM,,}` was the same class of defect, aborting with `bad substitution` at the prompt.
  (3) `test_workflow_smoke.py`'s `/proc/self/cwd` case asserted that a Linux-only escape executes;
  the classifier half now runs everywhere and the execution half only where `/proc/self/cwd`
  exists. (4) The four adapter timeouts were a bound, not a hang: one out-of-checkout subprocess
  measures 6.8s cold and 4.1s warm on Linux, and the cold cases alone exceeded 45s on the macOS
  runner, so both files now share `SUBPROCESS_TIMEOUT_S = 300`.

  Evidence, not inference: `scripts/validate-specs.sh`, `install.sh`, `uninstall.sh` and
  `bin/docket` were run under a real `bash:3.2.57(1)-release` container. Before the change the
  validator died at line 19 with empty stdout (exactly the CI message) and `install.sh` printed
  the exact `Bash 4.0+ required (found 3.2.57(1)-release)` string CI reported; after it, the
  validator reports the same 27 specs / 0 errors it does under GNU bash, and the installer's
  fixture-driven verified and tampered-checksum paths reproduce their expected outcomes. Three new
  guards in `test_public_release_truth.py` pin the shell surface against Bash 4 syntax and
  `grep -P`, the installer preflight against a Bash 4 floor, and COMPATIBILITY.md against both;
  each was seen red on planted drift before being restored. Full suite 2,539 passed / 5 skipped,
  ruff, format, strict mypy, 18 goldens, spec validator and the README metrics guard all green.
  The `macos` CI job remains `continue-on-error: true` - flipping it is a separate decision.

- **2026-09-03 (W29-C6 accepted) — the reproducible adoption baseline is published and its clean
  builder is verified without moving the baseline.** RED `82a3239`, GREEN `033bb4b`, and canonical
  builder fix `f789bc6` bind source `82a3239` to wheel SHA-256 `0fe67120…67fce`, eight scenario
  groups, nine attempts, five completions, and four retained failures. The public report keeps
  dollars unavailable and labels deterministic fixtures as contract—not model-quality—evidence.
  Hosted CI run `33812881329` at `37e91a8` passes every blocking job plus both Linux/macOS
  artifact-installed release journeys; its clean Python and dependency-floor lanes reproduce the
  unchanged artifact. The advisory macOS full suite retains eight unrelated portability failures,
  with no C6 baseline or journey failure. C6 is closed; C7 is now blocked only on explicit
  version/tag publication approval.

- **2026-09-02 (Wave 29 bounded triage / activation) — adoption work is now tied to five measured
  gaps rather than a feature wishlist.** At exact `main` commit `de08206`, repository measurement
  found zero extractable starters and zero benchmark/baseline files; a deterministic store fixture
  reproduced `JSONDecodeError` from a corrupt primary despite a valid `.bak`; project policy lacked
  deprecation/governance/succession truth; and public beta `v0.2.0-beta.1` exposed only its legacy
  tarball and checksum. Thirty-one existing policy, crash-resume, and release-contract tests pass,
  and current release workflow code already owns wheel/sdist, checksums, SPDX SBOM, protected
  publication, and provenance. D-34 therefore activates C1/C2/C3/C5 as disjoint lanes, gates C4 on
  recovery+harness, gates C6 on starter+scenarios, and reserves C7 for an explicitly approved
  version/tag publication and Phase 23 closure. No new telemetry, A2A, adapter, hosted provider,
  leaderboard, or savings claim was scheduled.

- **2026-09-02 (Wave 28 C4 accepted / Wave 28 closed) — portable governance is proven for two
  exact, Docket-only external-runtime configurations.** RED `3294f58`, typed terminal-usage bridge
  `b1c9f44`, and public/example truth `739b1ca` close the shared wheel/sdist matrix: 37 focused tests
  pass, including the repeated eight-case parity oracle, and the full suite passes 2,485 tests with
  five contract-labelled skips (2,490 collected). Ruff/format, root plus pinned-adapter strict mypy,
  24 specs, 18 goldens, ShellCheck, metrics, reproducible assets, deterministic smoke, public-doc
  checks, diff hygiene, and the scoped privacy scan pass. Exact implementation SHA `739b1ca70dc2`
  passes blocking Python and dependency-floor jobs and artifact-installed release journeys on both
  Ubuntu and macOS in Actions run `33652365412`. The public claim remains limited to OpenHands SDK
  Agent `1.44.1` and PydanticAI `2.37.0` with exclusively Docket-backed relevant tools; ACP,
  native/provider tools, adjacent plugins/MCP, and arbitrary configurations are unproven. A2A adds
  no value to these in-process paths, and paired JSONL trace identity did not justify OTLP. No
  credential, subscription, port-8081 canary, or external publication was required. The board is
  clear; Wave 29 requires its own bounded activation pass.

- **2026-09-01 (Wave 28 C2+C3 accepted) — the same Docket execution envelope now governs two
  concrete external-runtime configurations.** OpenHands RED `071a744`, GREEN `c7d6a59`, and typed
  boundary follow-up `fbb4084` prove nine wheel/sdist cases against the standard SDK Agent `1.44.1`
  on Python 3.12 with no default, ACP, MCP, plugin, bash, or file-editor bypass. PydanticAI RED
  `648dec5` and GREEN `a6c9197` prove seven wheel/sdist cases against a sequential custom toolset on
  PydanticAI `2.37.0` and Python 3.11 with no native or runtime-added toolset. Oracle correction
  `be61ab1` preserves C1's broad `decision="deny"` plus specific `denialKind` trace contract. Both
  adapters report provider usage before dispatch, enforce Docket's lower budget before mutation,
  preserve approval/policy/audit/trace identity, and return the shared typed handoff; the 13-case
  shared C1/fixture/package group, Ruff/format, adapter strict mypy, 24 specs, synchronized 2,478-
  test metrics, and cleanup all pass. W28-C4 is now ready; it still owns the repeated merged parity
  matrix, final spec/public claims, full suite/goldens/smoke/privacy gates, and Wave 28 closure.

- **2026-09-01 (Wave 28 C1 accepted) — external adapters now share one bounded Docket execution
  envelope instead of reimplementing governance.** RED commit `9f6a79c` and GREEN commit `d2e1b33`
  prove artifact-installed reported-token/tool-call preflight, exact call lifecycle, sole-
  chokepoint dispatch, paired trace identity, typed terminal handoff, and isolated concurrent
  approval stubs. Commit `2e37361` freezes the common seven-scenario oracle plus disjoint exact
  dependency graphs for OpenHands SDK `1.44.1` on Python 3.12 and PydanticAI `2.37.0` on Python
  3.11, without adding either framework to `docket-runtime`. Closure passes 2,457 tests with five
  contract-labelled skips, Ruff/format, strict mypy, 24 specs, 18 goldens, synchronized metrics,
  frozen-lock resolution, the deterministic smoke, and `git diff --check`. W28-C2 and W28-C3 are
  now independent ready lanes; W28-C4 still waits for both adapter proofs.

- **2026-09-01 (Wave 28 bounded triage / activation) — adapter choice and evidence are now
  executable, without adding product code.** D-32 selects the standard OpenHands SDK Agent with an
  explicit Docket-only tool map and PydanticAI with a custom toolset; OpenHands ACP is rejected
  because its subprocess owns tools and execution. D-33 freezes one credential-free,
  artifact-installed scenario table and the missing shared execution envelope: reported-token and
  tool-call budgets before mutation, sole-chokepoint dispatch, paired trace identity, existing audit
  semantics, and typed handoff. W28-C1 is ready; C2/C3 are disjoint parallel lanes after C1; C4 is
  the central parity/claim closure. No A2A or OTLP card was activated, and local port 8081 remains an
  optional canary rather than a CI or subscription requirement.

- **2026-09-01 (Wave 27 C2 accepted / Wave 27 closed) — the public repository now has a compact,
  reproducible front door.** Commit `d9e914a` reduces the README from 773 lines / 6,873 words to 280
  lines / 1,858 words, leads with the product boundary and shipped features, and routes deep command,
  security, compatibility, embedding, and roadmap detail to their owners. Seven stale/manual PNGs
  and the old one-off renderer are replaced by three referenced, anonymized terminal assets rendered
  and render-contract-verified by one script. Closure passes the 2,452-test collection (2,447
  passed, five contract-labelled skips), Ruff/format, strict mypy, ShellCheck, 24 specs, 18 goldens,
  synchronized metrics, locked all-extras sync, deterministic smoke, and the exact-wheel release
  journey. The active board is clear; Wave 28 requires bounded adapter/fixture triage before
  activation. Follow-up commits `fc07656` and `07e32c9` correct CI-discovered portability mistakes:
  dependency floors do not install dev-only Pillow, and generated assets carry one SHA-256 source
  fingerprint instead of comparing host-dependent compression/rasterization. Exact-SHA run
  33471779283 passes every blocking job and both OS artifact journeys; the advisory macOS full suite
  is back to its four pre-existing portability failures with no public-doc or asset failure.

- **2026-09-01 (Wave 27 C1 accepted) — the supported optional MCP graph no longer ships the open
  high-severity cryptography advisory.** Commit `a78d342` upgrades the locked transitive package
  from 49.0.0 to 50.0.1, beyond CVE-2026-69247 / GHSA-g6cj-pr64-35w5's `>=44,<50` range, without
  adding a direct dependency or changing the MCP SDK. The existing optional-surface smoke now guards
  the advisory range. Exact-SHA CI passes Python, dependency floors, ShellCheck/specs, 18 goldens,
  and both OS release journeys; GitHub marks Dependabot alert 1 fixed rather than dismissed. W27-C2
  is now the sole in-progress public-front-door refresh.

- **2026-08-31 (Wave 26 C11 accepted / Wave 26 closed) — the public release story now matches the
  executable product from immutable artifact to governed turn.** RED commit `dcce5b2` locks the
  install, provider, first-turn, runtime-embedding, known-limit, and stale-claim contracts; GREEN
  commit `f9a4086` reconciles the landing page, quickstart, provider, command, compatibility,
  security, installation, example, and spec-index surfaces. The artifact-only route and runtime
  example pass without checkout imports. Closure passes the 2,451-test collection (2,446 passed,
  five contract-labelled skips), Ruff/format, strict mypy over 74 source files, ShellCheck, 24
  specs, 18 goldens, synchronized metrics, dependency-floor artifact checks, deterministic smoke,
  and the exact-wheel release journey. The active board is clear; Wave 27 remains trigger-driven
  triage, not executable work.

- **2026-08-31 (Wave 26 C4 accepted) — the exact installable artifact now reaches a governed first
  turn on Linux and macOS.** RED commit `f8f897e` defines three artifact-installed release-journey
  contracts; implementation commit `6c52df7` builds and installs the exact wheel in an isolated
  venv outside the checkout, rejects source leakage, configures the public provider, initializes a
  project, executes one governed tool effect, and verifies measured usage plus durable
  task/run/session/trace/audit evidence. The blocking GitHub Actions matrix passes on Ubuntu and
  macOS, alongside 2,445 tests with five contract-labelled skips, Ruff/format, strict mypy over 74
  source files, workflow YAML, dependency-floor artifacts, 24 specs, 18 goldens, metrics, and
  deterministic smoke. C11 is now the sole ready, integrator-only Wave 26 truth pass.

- **2026-08-31 (Wave 26 C3 accepted) — tagged release artifacts are immutable and verified before
  installation or publication.** The release workflow builds and clean-installs the exact wheel and
  sdist, emits SHA-256 verification data and an SPDX SBOM, requests build provenance, and separates
  protected publication from artifact construction (`0251972`, `5bb106a`). The remote installer
  rejects tampered bytes before extraction, while Homebrew uses the same versioned asset with a real
  checksum and Apache-2.0 metadata. Preserved diagnosis showed the earlier smoke failure was caused
  by invoking `.venv/bin/python` without adding that venv to child `PATH`; the documented canonical
  `uv run python` command completes the approval/resume workflow. Commit-level closure passes 2,442 tests with five
  contract-labelled skips, Ruff/format, strict mypy over 74 source files, ShellCheck, workflow YAML,
  24 specs, 18 goldens, metrics, clean dependency-floor artifact installs, tamper rejection, and
  canonical deterministic smoke. C4 is now ready; C11 waits only on C4.

- **2026-08-31 (Wave 26 C0 accepted) — `main` is now the single public/default release
  lineage.** The maintainer authorized promotion of the current `platform` history. GitHub already
  identified `main` as default; the preflight proved `platform` was a strict 300-commit
  fast-forward with no `main`-only commits. Both refs were synchronized without force push or
  history rewrite. D-31 records that tags/releases originate from `main`; C3 now owns immutable
  tagged artifacts and the remaining mutable installer/formula inputs.

- **2026-08-31 (Wave 26 C10b accepted) — owned runs now stop cooperatively at every unstarted
  model, approval-continuation, and tool-handler boundary.** The persisted C10a signal now reaches
  `DocketDriver`, `run_agent_turn`, approval waits, and `dispatch_tool` (`3244fb2`, `d6eca09`). A
  response already in flight may finish, but cancellation discards it before the next side effect;
  an already-running handler completes its atomic unit while the unstarted batch remainder receives
  explicit `run_cancelled` results. Concurrent approval winners are preserved and cancellation is
  terminal/non-retryable. The four barrier races pass 50/50 repetitions; the committed closure
  passes 2,429 tests with five contract-labelled skips, Ruff/format, strict mypy over 74 source
  files, 24 specs, 18 goldens, metrics, the standalone runtime artifact boundary, and deterministic
  smoke. C10c is now ready.

- **2026-08-31 (Wave 26 C10a accepted) — cancellation requests are persisted truthfully across
  processes before an executor claims full stop.** The run id now identifies a typed signal whose
  additive lifecycle distinguishes request, observation, and stop; queued work stops atomically,
  running work stays nonterminal until `execute` returns, and one conditional registry transition
  resolves cancellation against terminal completion (`0d24f7a`, `dc69142`). Repeated requests do
  not re-signal or re-audit, malformed data fails closed, and unknown/legacy fields survive. The
  committed closure passes 2,424 tests with five contract-labelled skips, Ruff/format, strict mypy
  over 74 source files, 24 specs, 18 goldens, metrics, and deterministic smoke. C10b is now ready.

- **2026-08-31 (Wave 26 C5/C7/C9 accepted) — runtime distribution ownership and the remaining
  approval/conversation transitions are atomic.** `docket-runtime` now owns only
  `docket_runtime/`, rebuilds wheel and sdist outside the checkout, survives either coexistence
  uninstall direction, and exposes one versioned gated-tool facade (`cabad9e`, `55ef80b`). Approval
  resolution conditionally changes pending state once before the sole winner emits trace/audit
  (`7babf67`). Conversation writers and hop touches share one validated locked mutation boundary
  without schema growth or fabricated records (`790f578`). The committed-tree closure passes 2,416
  tests with five contract-labelled skips, Ruff/format, strict mypy over 74 source files, 24 specs,
  18 goldens, metrics, artifact ownership/floor checks, and deterministic smoke.

- **2026-08-30 (Wave 26 C2/C6/C8 accepted) — three isolated Terra lanes landed canonical
  packaging and atomic audit/resource transitions.** The root wheel and sdist now install the
  canonical `docket` executable from outside the checkout with aligned metadata and clean uninstall
  behavior (`2d3e713`). Audit rotation, head lookup, append/flush/close/permissions, and readers are
  one bounded inter-process transition with typed best-effort results and failure rollback
  (`4493874`, `6e6cfd3`). Pod provisioning serializes same-project attempts, allocates different
  projects atomically, and removes only attempt-owned rollback state (`f9c9fd5`). Integrated gates
  pass with 2,404 tests and five contract-labelled skips, Ruff/format, strict mypy, 24 specs, and
  18 goldens. C3 now waits only on C0, C4 waits only on C3, and C5 is ready under D-28.

- **2026-08-30 (Wave 26 W26-C1 accepted) — clean setup now reaches a governed turn through a
  resolvable provider.** Provider registration is fail-closed, unresolved presets cannot persist,
  first-project bootstrap validates the selected endpoint/model without exposing credentials, and
  coding-tool subscriptions are not treated as runtime API credentials. A provider-only fleet no
  longer bypasses foundation setup. The preserved keyless `127.0.0.1:8081` canary at
  `/tmp/docket-w26-c1-live-smoke-pa9AyI` completed the five-hop workflow, gated write, approval
  pause/resume, verification, and clean 11-record audit chain at zero cost. The deterministic
  closure gates pass with 2,391 tests and five contract-labelled skips, Ruff/format, strict mypy,
  24 specs, 18 goldens, metrics, and smoke. W26-C4 now waits only on C2 and C3.

- **2026-08-30 (Wave 25 integrated and closed) — the complete attributed tree landed at `6b925f0`
  and Phase 23 / Wave 26 activated.** The integration commit owns all 45 runtime, spec, test,
  documentation, skill, and handoff paths. Its closure gates passed with 2,377 tests and five
  contract-labelled skips, Ruff, format, strict mypy, 24 specs, 18 goldens, metrics, and the
  deterministic five-hop smoke. The active marker changed once; W26-C1, C2, and C6–C10 are ready,
  while C0 and dependency-bound cards remain blocked. The transition also added a focused snapshot
  regression so a completed prior wave cannot hide the newly active ready pool.

- **2026-08-30 (Wave 25 W25-C7 accepted) — the un-scripted memory-maintenance canary completed
  without violating the private-context boundary.** The preserved world
  `/tmp/docket-w25-c7-live-L8nkOm` distilled private decisions, repaired the isolated Git worktree,
  passed public and hidden acceptance, persisted five typed hops with `approve`/`pass`, exercised
  three in-turn approvals plus pipeline approval, and passed the durable trace/session privacy
  oracle and audit verification. Post-canary full deterministic gates pass. Wave 25 now has only
  dirty-tree integration and commit-level revalidation remaining before Phase 23 activation.

- **2026-08-30 (Wave 25 W25-C11) — configured verdict markers are placement-tolerant but
  ambiguity-intolerant.** The generic executor scans complete output line-by-line, accepts one
  distinct normalized marker wherever it appears, collapses identical repeats, and fails closed on
  absence, conflicts, or prose-only mentions. The normalized artifact verdict is reused on crash
  resume instead of reinterpreting model prose. Pipeline Format 2.2.0, Pod Dispatch 6.5.0, the full
  suite, and deterministic smoke pass; W25-C7 is ready for exactly one fresh serial live acceptance.

- **2026-08-30 (planning, no product code) — the CTO/OSS audit became Phase 23 rather than a generic
  feature backlog.** D-25 positions Docket as a governed single-host coding-agent runtime first and
  requires two enforcement-equivalent adapters before any framework-neutral claim. D-26 makes
  clean-install-to-first-governed-turn the release blocker; D-27 defines external-runtime
  governance as removal of native bypasses; D-28 permits the narrow runtime-package correction
  D-21 needs; D-29 records isolated multi-agent delivery and compact handoffs. W25-C11 owns the
  measured Reviewer-marker defect blocking W25-C7. Wave 26 is fully scoped but blocked behind Wave
  25/dirty-tree reconciliation; Waves 27–29 remain trigger-gated in the durable plan.

- **2026-08-19 (wave 24) — a realistic memory-backed Git canary found and closed three product
  defects hidden by the one-line/flat-workspace smoke.** The live scenario starts from two
  intentional checkout regressions in a committed repository, distills superseding private
  decisions, repairs the Implementer's isolated worktree, and validates four public regressions
  plus hidden behavioral/AST acceptance. Preserved failed runs exposed private-state completion
  ambiguity and opaque approvals, a model-corrupted `10_000`→`1_000` invariant, and Tester reading
  the untouched origin. Runtime context now releases completed turns; approvals show the redacted
  call; sparse `- [exact]` records validate normative literals fail-closed; downstream roots are
  accepted only from a registered same-pod Implementer. The final run
  `/tmp/docket-live-memory-w24-k` passed every gate without raised limits or scripted replies.

- **2026-08-19 (wave 23) — the full workflow now runs against the real local model, and the
  repeated run fixed what the deterministic proof could not see.**
  `scripts/smoke_workflow.py --live-model` discovers and registers the Qwen served at
  `127.0.0.1:8081`, uses no credential or
  scripted reply, preserves normal production guardrails, and completed the five-role tool/gate/
  approval/resume workflow in multiple fresh temporary worlds. A second pre-fix run exposed a real
  context defect: the Lead exhausted 20 iterations searching for HEARTBEAT/MEMORY because the
  injected startup contract required those files while the model neither received them nor could
  safely read the private workspace through project tools. `system_prompt_for_agent` now injects
  fresh HEARTBEAT/AGENTS/TOOLS/MEMORY by priority under `CONTEXT_TOKEN_BUDGET`, marks truncation,
  and closes with an explicit already-loaded/read-only handoff; roots remain unchanged and system
  context is not persisted. The final canary reduced the Lead from 16 turns/45,639 input tokens to
  7 turns/18,395 tokens (about 60% less measured input) without raising a limit. The opt-in live
  pytest, ordinary 2,233-test suite (5 expected skips), 18 goldens, 24 specs, Ruff, format, mypy
  and metrics passed.

- **2026-08-19 (wave 22) — one command now proves the product composes end to end.**
  `uv run python scripts/smoke_workflow.py` provisions a full agentic-product pod and drives a
  real CLI → OpenAI-compatible loopback HTTP → `DocketDriver` → agent loop → governed `write`
  tool path. Its five-step custom pipeline exercises mechanical and Reviewer/Tester verdict gates,
  deliberately pauses at a human approval, grants it through the CLI, and proves exact-position
  resume to `done`. It validates the artifact plus typed handoffs, five isolated step histories,
  atomic tool-call/result persistence, endpoint-measured usage, traces, audit-chain verification,
  and two successful run records. The endpoint is deterministic and local; no real credential or
  non-loopback network is used. A pytest subprocess wrapper makes the composition proof part of the
  2,230-test suite; all static/spec/golden/metrics gates passed.

- **2026-08-19 (wave 21) — the clean runtime break is now reflected in every current contract.**
  Product source, ordinary docs/tests, golden fixtures, and normative spec sections no longer
  teach a deleted daemon, adapter, binary, or home directory as a live boundary. The golden suite
  now seeds `.docket`; JSON/API documentation was checked against live producers (including a
  corrected `doctor --json` `modelConfig.invalid` shape); and a source-tree guard keeps retired
  coupling out of `src/docket`. Explicit names remain only where they are evidence: durable
  changelogs, roadmap/TODO history, and older spec changelog entries. All 2,229 tests passed with
  four environment skips; Ruff, format, mypy, 18 goldens, 24-spec validation, and metrics passed.

- **2026-08-05 (wave 19) — running a real pod against a real endpoint found three defects in one
  session, and 2,209 tests had caught none of them.** The local environment gained a llama.cpp
  endpoint (`127.0.0.1:8081`, 16k context) and a second real pod, **Adapta**. The first dispatch
  failed, and the reason was not the model. **(1)** An Implementer with a git worktree is gated
  against that worktree *alone*, but `SOUL.md` — its system prompt — and `WORKFLOW_AUTO.md` — the
  contract it re-reads after every context reset — both named the **origin checkout**, while
  `TOOLS.md` named the worktree. Every read came back `resolves outside the allowed roots`, the
  model retried other spellings, and the turn died on the token budget having executed **zero**
  tool calls. Nothing raised, so nothing went red. Fixed at the single point all three files are
  written, with a new test that pins the *property* (the advertised path is inside
  `_resolve_roots()`) rather than any path string, and with `docket doctor`'s contract heal — the
  same defect's second writer — fixed alongside. **(2)** The tool-output ceiling was a bare
  `30_000` literal in `toolbox.py`. It is a *context* bound, so its usable value is a function of
  the endpoint, and docket had no way to express that: at 30k, two results alone overflow a 16k
  window. Now `config.py`-owned and resolved per call. **(3) — found, not fixed:**
  `plan_compaction`/`compact_session` exist, are tested, are documented as automatic, and are
  **called from nowhere in `src/`**. Every hop of a dispatch shares one session key, so the reviewer
  hop receives the lead's and implementer's full raw history on top of the compiled
  `HandoffArtifact` — the handoff budget bounds the message, not the history — and the endpoint
  refuses the prompt at 19,827 tokens.

  **A fifth, found by using the product rather than reading it:** the README advertised
  "conversational dispatch — message the Lead directly" over Telegram. No such path exists; prose
  is refused with an "unrecognized command" reply. Two neighbouring claims were also false (a gated
  action "pings the wired group" — nothing is ever pushed; and a setup snippet using `docket serve`
  when the poll loop needs `--telegram`). **The functional spec was correct throughout**, requiring
  "exactly four verbs" and that anything else be treated as unrecognized — so unlike the
  unwired-machinery family this was *prose drifting from a right spec*, and nothing compares the
  two. Corrected across README/commands/quick-start; the inbound-only property and
  `/delegate`-returns-a-task-id are now spec requirements pinned by an AST guard rather than
  implicit.

  **A fourth, found while documenting the Tack integration:** `GET /traces/<project>?since=` —
  the route an external plan-of-record polls — replayed on any project with more than one session.
  `export_lines` concatenates session files in sorted *filename* order and a session id is a uuid,
  so the stream is not chronological, while the cursor anchored on the page's last line and counted
  a trailing same-second run. On the real `adapta` project a resume replayed 36 of 47 events. The
  page is now sorted by ts before anchoring: resume returns 0, and events arrive in time order
  across sessions. Wave 16's "no replay" check had been correct but not general — that project had
  one session file at the time. **A verification is a claim about the state it ran against**;
  re-running it against a richer state is what made the general case visible.

  **This is the third instance of one shape** (MCP tools, W17-1; sandbox, W18-3; now compaction):
  built, tested, never wired to the default path, with documentation asserting it works. Both false
  claims were corrected the same day rather than held pending a fix, moving the `docket help` golden
  by exactly one line. The lesson worth keeping is narrower than "test more": **all three were
  invisible to unit tests and immediately visible to one real run.** A small-context endpoint is a
  better integration test than a large one, because it makes context bugs fail loudly instead of
  silently costing tokens.

- **2026-08-05 — the local environment was rebuilt, and the suite leak was worse than assumed.**
  `docket` on PATH is an editable install resolving to `src/docket`, so the installed CLI already
  follows this branch. But `~/.docket` held **no real state at all** — 67 registered agents, every
  one a test fixture name, and two workspace directories that were both empty. `docket doctor`
  reported 14 pods "in sync" while `docket list` reported none; that mismatch is what exposed it.
  **This is the third recorded occurrence of the suite leaking into the developer's real
  `DOCKET_HOME`**, and the first where it had displaced the entire environment rather than adding to
  it. Backed up, wiped, rebuilt: org specialists + a real `docket-dev` pod on this repo, isolation
  enabled (and now actually consulted, per W18-3), all three isolation layers verified as real
  artifacts rather than declarations. Phase 22's routes were exercised end to end against a live
  `docket serve` — including the `pre_input` gate firing on the HTTP path and a cursor poll
  returning exactly one new event with no replay. **The single remaining gap is a model endpoint**:
  no key, no local runtime, so a dispatch cannot complete — it fails cleanly naming the missing
  credential, which `docket doctor` reports as its only critical issues.
- **2026-08-05 (wave 18) — two security claims were false; both are now true.** Opened against one
  *reproduced* defect: the audit log's hash chain restarted at `seq=1` on rotation with a single
  backup generation, so flooding past two rotations erased history while `docket audit verify`
  still reported a clean chain. Rotation now carries the prior generation's final `seq`+hash forward
  as a continuation claim, so a predecessor that cannot be produced is reported as a break.
  **The wave's larger find came from the card running alongside it.** A claims audit against the
  tree found `docket gates isolate on` did *nothing to a live turn*: the flag persisted, the
  bwrap/docker path was implemented and tested, and `run_turn` never set `ToolContext.sandbox`, so
  every tool call ran unsandboxed regardless of the setting — **the same shape as the MCP gap wave 17
  closed, but in a security control the README advertised three times.** Now wired, failing closed as
  a **turn-level refusal** (audited) rather than the per-call downgrade that would have re-created
  the original silence. **Process note worth keeping:** the README was corrected to admit the
  capability did not work *before* the fix landed, then corrected again after — a false security
  claim gets fixed the day it is found, not the day the code catches up. Also corrected: `--no-gates`
  never disabled the tool-call gate; it skips approval *routing* only.
- **2026-08-05 (wave 17) — the MCP wire, docket's oldest recorded limit, closed.** Two cards. The
  wire itself was one injection seam; **making it safe was the card.** Role narrowing removes
  literal `denied_tools` names, and a namespaced `mcp__<server>__<tool>` can never match one — so a
  naive load hands a Reviewer `mcp__fs__write_file` and silently voids the "structurally unable to
  write" guarantee the README leads with, **with no test failing.** Denials are now enforced by
  *capability*: `core/mcp_tools.py` already registered every adapted tool `kind="write"` (nothing can
  prove a remote tool read-only), so `registry_for_role` strips the kinds a role's denied names
  imply. **The integrator found the answer's own hole**: the kind set was derived by looking each
  denied name up *in the registry being narrowed*, which makes the denial conditional on that
  built-in being present — and `registry_factory` exists to inject narrower registries. Latent, not
  live, but the same failure mode through a different door; fixed with a static map so the denial
  depends only on the role's data. **The generalizable rule: when a capability can arrive under a
  name you do not control, deny the capability, never the name.** Honest residue: a read-only role
  gets zero MCP tools rather than a narrowed subset, and there is no listing cache (~0.6s per
  configured stdio server per turn, measured; zero servers ~0.004ms). Card 2 gave every config
  constant one owner — `config.py`'s `METRICS_WINDOW` turned out to have **no reader at all**.
- **2026-08-04 (wave 16) — Phase 22 shipped: the control-plane write API.** Six cards, two rounds,
  four agents. `POST /tasks/<project>` (enqueue, honouring the `pre_input` gate exactly as the CLI
  does), `GET /tasks/<project>`, `GET /traces/<project>?since=` (cursor'd), the approval `channel`
  label validated against a closed set `core/approval.py` owns, `POST /pods`, and trace retention.
  **Scheduling:** five of six cards touched `serve.py`, so ownership was split by HTTP *method* —
  zero code conflicts, and the single conflict was the spec changelog the roll-up rule already
  predicts, resolved by keeping both entries rather than picking one.
  **Four defects were found in review rather than by the suite**, and the pattern in each is worth
  more than the fix: a cursor that split on the last colon *of a timestamp* (safe for minted
  cursors, broken for the hand-supplied form the docstring advertised — the existing test covered
  only the variant that worked); a wiring comment that was **false when written**, caught because
  the comment was tested rather than trusted (`sweep_all`'s synthetic `session_end` carries a fresh
  timestamp, so terminating a trace *resets* its age, which means retention runs from session end,
  not last activity); a `/metrics` durability caveat that a card in the *same wave* made false
  (trace-derived counters had no history gap only because traces were never deleted); and a doc
  pointer left behind by the P22-5 refactor. Full per-card record in TODO.md.
- **2026-08-04 (wave 15) — the last legacy sweep, and one real bug.** Four cards; full per-card
  record in TODO.md. **The bug: `TELEGRAM_REQUEST_TIMEOUT_S` was documented, env-overridable and
  wired to nothing.** The adapter fell back to a hardcoded 35s socket timeout, so the env var did
  nothing — and raising `TELEGRAM_POLL_TIMEOUT_S` above 35, which Telegram permits, would put the
  socket timeout *below* the poll wait and make every empty long-poll read as a local failure. That
  is precisely what the constant's own comment warned about: **the invariant was written down and
  never enforced.** Now resolved in `core/` and threaded through, clamping to poll + 10s with a
  warning on violation (following `MCP_CLIENT_MAX_TIMEOUT_S`'s precedent, since this is not a
  security decision), proven red before green.
  **`docket eval` and `tests/evals/` removed outright, no replacement — record this alongside D-11
  and D-16.** The harness could not run: it shelled out to the deleted daemon and **skipped silently**
  rather than failing, so it read as coverage while doing nothing, and CONTRIBUTING and README both
  cited it as a real gate. Repair was rejected on evidence, not preference: no CLI entry point runs a
  single agent turn (`run_turn` is reached only from pod dispatch and distillation), so repointing it
  meant inventing surface against a private port; and three of the six scripts assume the
  pre-Phase-10 global `programmer`/`reviewer`/`tester` roles that `doctor` now flags as legacy debt.
  Removed coherently — module, command, doctor advisory, spec (per the retire-by-deletion
  convention), every doc/CI reference — with a removed-command notice exiting 1, matching
  `workflow`/`team`. **Commands 37 -> 36 and specs 25 -> 24 as a result; both counts falling is the
  work landing, not drift.**
  **The test suite is now named for what it tests**, not which card built it: 94 of 104 files
  renamed via `git mv` (`test_m4_wave1.py` -> `test_profile_scope_models.py`, and so on), with the
  29 references outside `tests/` repointed from the rename map git itself recorded.
  **Two guards proved themselves on unrelated work**, which is the useful kind of evidence:
  `test_no_openclaw_references.py` failed CL-J's first draft of the removed-command notice (a live
  string, not a comment), and CL-G found `test_store_writer.py` silently exempting `core/drift.py`, a
  module deleted long ago — its own docstring had said to remove the entry once that happened.
  Also reported and deliberately not fixed: `METRICS_WINDOW` is declared in `config.py` while
  `cli/_metrics.py` keeps an independent `os.environ.get` copy — a drift risk rather than a silent
  failure. Housekeeping: 52 stale agent worktrees pruned, 114 fully-merged card branches deleted.
- **2026-08-04 (wave 14) — the cleanup wave.** Six cards in two rounds re-trued every document,
  deleted the dead code the Phase 19 removal left behind, and stripped the changelog that had grown
  inside the source comments. Net ~2,900 lines removed. Full per-card record in TODO.md.
  **The largest deletion was ceremony:** `restart_gateway()` had been a documented no-op since
  P19-7b, and ~15 call sites across `cli/` still called it and rendered a result for a restart that
  never happened. **The most valuable half was not the archaeology** (`Phase 1X` 204→3, `P19-`
  163→1, `D-1X` 57→0 in `src/`) but the comments that had become **false** — four modules still
  claimed `pre_tool_call` "stays daemon-gated" and that "docket is not inside a turn to intercept a
  tool call", which is precisely the belief Phase 19 existed to falsify.
  **Three real defects surfaced.** (1) **MCP tools are not reachable in a live turn**:
  `load_mcp_tools` is never called and `DocketDriver.registry_factory` defaults to
  `builtin_registry`. Configuring a server registers and gates it; the last wire is absent. README
  and `docs/commands.md` overclaimed it — `mcp-client.spec.md` had it right all along, so the docs
  were the outlier. Note the consequence for planning: *"browser support is just an MCP config"* has
  been used more than once here to justify **not** building something, and it is only true once that
  wire exists. (2) `NOTICE` declared the project MIT-licensed while LICENSE, the CHANGELOG relicense
  entry and the README badge all say Apache 2.0. (3) All four `examples/configs/*-agent-meta.json`
  failed `AgentMeta` validation outright, and `agents.yaml` silently dropped two of its three entries
  through `docket add --from` — silent partial success being the worst failure mode an example has.
  **A refusal worth recording:** CL-C was briefed to standardise the version on `0.2.0-beta.17` and
  **declined**, having verified that value exists nowhere in the tree or the tags — the integrator's
  premise was wrong, and the agent checked rather than complied. Two other AST-flagged "dead"
  functions were likewise kept after being identified as pydantic `model_validator`s.
  **Deliberately left, not carded:** `tests/evals/` is entirely coupled to the deleted daemon
  (`$HOME/.openclaw/workspaces/<role>`, `openclaw agent --local --json`) and survives only because
  it **skips silently** when the binary is absent. Re-pointing it at docket's own driver is a
  redesign; decide whether the harness is worth keeping first.
- **2026-08-04 (wave 13) — THE BOARD IS CLEAR.** Phases 19, 20 and 21 are all closed; nothing is
  scheduled. **P20-2 shipped** the guardrail + loop metrics: four families on the existing Prometheus
  surface (`docket_tool_calls_total{decision}`, `docket_policy_hits_total{policy_id,hook,action}`,
  `docket_approvals_total{channel,outcome}`, `docket_turn_duration_seconds` as a quantile-less
  summary), **no new endpoint and no new dependency**. Every number is recomputed from durable
  records at scrape time rather than held in a counter store — `docket serve` is not long-lived, so
  in-memory counters would zero on restart and a persisted set would be a second source of truth free
  to drift from disk. Its one `core/tools.py` change is confined to how the audit *detail* is
  formatted (`policy_id`/`policy_action` as structured fields instead of free text); the gate itself
  is untouched. Two limits are documented rather than implied: audit-log rotation costs the
  approval/policy counters their history (P20-3's deferred retention scope), and scrape cost was
  **measured** at ~60ms against a 5MB audit log plus a 927KB trace corpus, not asserted.
  **P20-4 was a phantom card** — dispatched, and the agent found the gap already closed by W-4
  (`7e9ddab`, 2026-07-30) with tests and a spec entry; zero commits. It had been recorded as open in
  Phase 20's gap list *the same day* W-4 closed it, then promoted into a card, then **kept over
  OpenTelemetry in D-24's prioritization pass on a premise nobody re-checked**. The lesson is on the
  card: a gap list is a claim about the tree and decays like any other — re-verify one before
  scheduling work against it. Tree at close: **2,081 tests**, 18/18 goldens, 25 specs / 0 warnings,
  37 commands, ~26,700 lines, `ruff` + `mypy --strict` (73 files) clean.
  Separately, the **README was re-trued** for the post-daemon world (it still described docket as a
  wrapper around an external OpenClaw daemon, with an ACL, `openclaw.json`, a daemon-owned approval
  prompt docket could not audit, and "recorded dollar spend"); `docs/commands.md`,
  `COMPATIBILITY.md`, `CONTRIBUTING.md` and four `docs/` files carry the same debt and are **not yet
  carded**.
- **2026-07-31 (planning, no code)** — **The goal was stated — *a factory for agentic products* — and
  it settled four open decisions and opened a fifth.** **D-20 ANSWERED: both, in an order** — factory
  first, embeddable substrate second, on the reasoning that *if every product is agentic, the runtime
  is the common part of every product*, so the factory's highest-value output is a reusable substrate
  rather than agent-written code. The answer explicitly **excludes the hosted-SaaS half** (multi-tenancy,
  authn for external callers, queues, streaming, per-customer quota): the substrate is a **library a
  product embeds**, and the product owns its serving layer. **D-21 confirmed YES** but constrained to
  *packaging only*. **D-22 CUT** — stay project-scoped; the tenant axis is a real bet, not a free cut,
  and the expensive-to-retrofit warning stays on the record. **D-23 re-scoped** — ship the `fetch`
  tool, defer the egress lockdown, and **say the true thing in the docs**: egress is open, `fetch` is
  the inspectable path, the `python3`/`node`/`git clone` escape hatches are named. **D-24 NEW — the
  prioritization ruling**, which re-scored Phases 20 and 21 against §4.5's test (*does a measured need
  in **this** system ask for it*, not *is this best practice for someone*) and **cut roughly half,
  including the integrator's own recommendations from hours earlier**: **OpenTelemetry (P20-1) CUT** —
  correct at platform scale, wrong at one host and one operator with JSONL traces and six Prometheus
  metrics already shipped; **streaming (P21-2) and the tenant axis (P21-3) CUT** — both only served
  the hosted-runtime reading D-20 rejected; fleet trace query (P20-3), egress lockdown and the
  build-agent profile (P21-4) **deferred with named triggers**; browser automation **never to be
  built** (it is an MCP config). Added one **XS** card, **P21-5**, after verifying that the factory's
  scaffolding primitive **already exists** — `core/blueprints.py` ships `software`/`research`/
  `content`/`ops` as declarative data, so an `agentic-product` pod shape is a **row in a registry, not
  new machinery**. Waves re-sequenced: **P19-6 pulled forward into wave 10** (four cards in parallel
  with a function-level ownership map), wave 11 is the removal spine P19-7 -> P19-8, wave 12 is the
  substrate P21-1 -> P21-5, wave 13 is what survives of Phase 20. Docs only — no code changed;
  `metrics.py --check` and `validate-specs.sh` re-run green (2,026 tests, 24 specs).
- **2026-07-30 (wave 5)** — **PHASE 16 COMPLETE** (W-1…W-8) and 5 more cards merged, taking the
  tree to **1,600 tests**. W-5 replaced raw-text hop concatenation with a typed `HandoffArtifact`,
  which **unblocks Phase 17's C-1** and therefore opens Phase 17. W-4 shipped cron scheduling,
  webhook→pipeline variables, `--follow`, and the `runs.cancel` audit entry; G-4b closed the
  `models.*` audit gap G-4 named two waves earlier; CL-2 closed the dead-code register's
  non-dispatch half; L-4 answered its spike with dated evidence and no code. **The register's
  remaining rows are now closed**: the `AgentRunResult` alias and its ~76 call sites,
  `dispatch_all_pods`, the last `print()` in `core/`, two zero-caller ACL functions, and
  `core/sync.py`'s dead-module status — with an AST test pinning that no `print(` survives in
  `core/` or `edges/`. Deliberately kept rows carry dated in-code reasons rather than silent
  decisions. Full record, including what was narrowed: the `☑ Wave 5 shipped` block in the Phase 16
  section.
- **2026-07-30 (waves 3–4)** — **11 Platformization cards merged onto `platform`**, taking the tree
  from 1,112 → **1,512 tests**, 18 → 20 specs, 35 → 37 commands. Phase 16's exit criteria are met
  (W-1/W-2/W-3/W-6/W-7/W-8); Phase 18 is done but for its two daemon-gated spikes (L-1/L-2/L-3/L-6);
  Phase 15 is 4 of 6 (G-1/G-4/G-5/G-6). **D-16 executed:** `core/lobster.py`, `cli/_workflow.py`,
  their tests and `workflow-integration.spec.md` are deleted — `docket workflow` is a removed-command
  notice, and docket now lints only the one pipeline dialect it actually executes. **D-14 executed:**
  the RuntimeDriver port ships with exactly one driver, per the decision. Cancellation works for the
  first time because W-2 fixed its root cause (`agent_run` had no process group to kill). Full
  record, including what was narrowed: the `☑ Waves 3–4 shipped` block in the Phase 16 section.
  Two process lessons are recorded in §8: an index/roll-up table edited by parallel branches must be
  **regenerated from ground truth, never side-picked**, and `scripts/metrics.py --check` was found
  **failing open** — a CI-blocking guard that reported success while verifying nothing.
- **2026-07-30 (later same day)** — **PHASE 14 COMPLETE.** All 8 cards R-1…R-8 landed on
  `platform` (1,112 tests, 18 goldens, full suite green). R-8 (the spec/docs truth pass) rewrote
  `pod-dispatch.spec.md` to v2.0.0 for the full v2 state machine (locked claims, crash resume,
  retries, independent timeouts, bounded Reviewer rework, real budget auto-pause, bounded hop
  prompts) and trued up five more specs it touched along the way — `docket-meta.spec.md`,
  `serve-read-api.spec.md`, `cli-json-shapes.spec.md`, `audit.spec.md`, `cli-interface.spec.md` —
  several of which had drift unrelated to R-1…R-7 (a stale `apiVersion` example, a phantom `type`
  JSON field, a mis-shaped `docket snapshot`/`/metrics` schema, two missing audit action
  families) caught and fixed while reconciling `specs/README.md`'s status table against every
  spec's real header. Also corrected TODO.md's own board: R-6 had shipped correctly (worktree cwd
  resolution, verify-command validation, `pod.set-verify` audit logging — all test-covered) but
  its card's status line and acceptance boxes had been left at `TODO` since an earlier merge,
  contradicted by the roll-up checklist's own (also duplicated) entries; de-duplicated that
  checklist and reconciled it to one honest set of DONE marks. Verified — and did **not**
  re-touch — three guidance/docs bugs the R-8 card listed as candidates, confirmed already fixed
  by earlier cards: `cli/_provider.py`'s two dead-end strings and the eval-harness JSON-shape
  drift (both Phase 18 L-2), and the duplicated `openclaw-gateway.service` constant (also L-2).
  Two issues found but explicitly **not fixed** (outside this card's docs/specs/tests-only
  scope, reported instead): a leftover git merge-conflict marker inside `serve.py`'s module
  docstring from the R-3 merge (cosmetic, no behavior effect), and a precedence-order mismatch in
  `config.py`'s comment describing how the serve-wide dispatch timeout knobs interact with a
  pod's own Lead-meta timeouts. While reconciling the Status line above, also added "DONE —
  pulled forward" notes to three cards from later phases that had already shipped on `platform`
  with no Phase 14 dependency (Phase 15's G-6, Phase 17's C-4, Phase 18's L-2) alongside Phase
  15's G-4, which already carried one — none of the four are new work, only overdue
  bookkeeping so this document stops contradicting the tree. Full record: the Phase 14 section's
  `☑ Phase 14 shipped` block above; execution trail: TODO.md's R-1…R-8 cards (kept until Phase
  15's board overwrites them, per convention).
- **2026-07-30** — **Platformization program added (Phases 14–18) on the new `platform` branch.**
  Driven by the 2026-07-29 agent-platform audit (`internal-docs/agent-platform-audit-and-build-plan.md`,
  four parallel code-grounded passes): docket measured against eight agent-platform pillars scored
  0–2/5 each — no MCP, no gateway, lint-only workflows, a dispatch lane with a queue race / no
  `running` state / no retries, three governance organs built but unwired (approval store, policy
  engine, `resolve_command_action`), auto-pause never ported from Bash, and a closed 4-role
  software-only pod archetype. Added: Phase 14 (dispatch hardening, ACTIVE, board in TODO.md),
  Phase 15 (governance wired), Phase 16 (declarative orchestration + role archetypes/blueprints for
  diverse objectives), Phase 17 (context compiler + memory distillation), Phase 18 (RuntimeDriver
  port + MCP + wrapped-gateway spike); decisions D-14…D-18; §4.5 amended per D-14/D-15 (RuntimeDriver
  port supersedes the AbstractBackend ban's letter, "not in the execution path" retired). Specs
  restructured the same day: statuses trued to code, retired/legacy content cleaned (see the spec
  refactor commit on `platform`).
- **2026-07-30** — **Phase 15 G-4 (Audit v2) shipped, pulled forward on `pc/g-4`** — the one
  governance card with no Phase 14 dispatch-lane dependency. Recording coverage went from ~1/6
  of the spec to the full list minus `models.*`/`runs.cancel` (keys/profile/scope/agent/pod/
  persona all now audit-logged); added a `seq`+`prev_hash` SHA-256 hash chain and `docket audit
  verify`; timestamps moved to millisecond resolution; added size-capped rotation
  (`AUDIT_LOG_MAX_BYTES`, single-generation `audit.log.1`); removed the `DOCKET_NO_AUDIT` kill
  switch entirely (chose removal over a TTY-confirm gate to keep `core/audit.py` process-free);
  `core/trace.py`'s suppressed-write honesty bug fixed (`trace_event` now returns
  `"written"/"rejected"/"suppressed"` instead of a dishonest `True`). See audit.spec.md v2.0.0.
- **2026-07-03** — **Cut and tagged `v0.2.0-beta.1`** — folded Phase 13 (FD-0…FD-7) into
  CHANGELOG's previously-blank-since-drafting 0.2.0 entry; trimmed README.md (492→361 lines:
  cut the redundant Command Reference and Engineering sections down to short pointers at
  `docs/commands.md`/`CONTRIBUTING.md`, pulled two screenshots — `gates.png`/`doctor.png` — that
  showed pre-0.2.0 "gates inactive" output contradicting the new gates-on-by-default default);
  consolidated repeated before/after + token-savings narrative across `docs/DOCKET.md`
  (821→731 lines) and `docs/QUICK-START-DOCKET.md` (454→307 lines); merged three separate
  troubleshooting sections (`WORKFLOW-GUIDE.md`, `QUICK-START-DOCKET.md`, and
  `docs/troubleshooting.md` itself) into one canonical `troubleshooting.md`. **Versioning
  correction:** the operator clarified every release from this project must carry a SemVer
  `-beta.N` pre-release suffix while it stays beta software — corrected the in-flight plain
  `0.2.0` cut to `0.2.0-beta.1` (VERSION, `pyproject.toml`, `__version__`, `uv.lock`, CHANGELOG
  header + compare links) rather than reusing `0.1.0-beta.*`, since `v0.1.0` is already tagged
  and a `0.1.0-beta.N` would sort *before* it in SemVer precedence. `.github/workflows/release.yml`
  updated to mark the GitHub Release as a pre-release whenever the tag contains a `-` (so this
  and future beta tags don't show as "Latest release").
- **2026-07-02 (later same day)** — **PHASE 13 COMPLETE.** All 8 FD-cards landed and merged into
  `develop` (795 tests green). Execution: FD-0…FD-4 ran as a first parallel wave of 5
  worktree-isolated agents; FD-5/FD-6 ran as a second wave of 2 once the first wave landed; FD-7
  was done directly (solo, small docs-only card). Two real merge conflicts resolved by hand: test
  fixtures in `core/dispatch.py` needed widening to FD-0's 5-arg `Runner` signature after FD-2
  merged first; `security-gates.spec.md` had a genuine content conflict between FD-5 and FD-6
  (both independently wrote a "High-risk action classes" section) — resolved by keeping the more
  detailed version and combining both Changelog entries. One design correction made mid-phase,
  before merging: FD-3's first implementation excluded `git`/`npm` entirely from the exec
  allowlist to force high-risk invocations to always ask; caught during review that the daemon's
  binary-only gating would have also blocked benign invocations (`git status`, `npm test`) —
  presented to the operator as a real tradeoff, who chose to narrow the fix rather than accept the
  full exclusion. Per-argument enforcement for prod-deploy's `git`/`npm` overlap is now an
  explicit, tracked backlog item. TODO.md's board is now spent and awaiting the next phase.
- **2026-07-02 (later same day)** — **Added PHASE 13 — Close the differentiation gaps** (FD-0…FD-7),
  scoped after the operator chose "Tier-1 competitive bets" from `internal-docs/competitive-analysis.md`.
  A grounding pass (three parallel code investigations) found the analysis's framing had gone stale:
  Phase 11's own CD-1 (port/scratch allocation), CD-2 (verify-cmd gate), and CD-3/CD-4 (approval
  store + CLI/HTTP channels) already built most of what P1/O2/S1 asked for, the same week the
  analysis was written. Rescoped to the five real residual gaps instead of rebuilding: env-injection
  for pod resources (FD-0), a public way to set `verifyCmd` (FD-1), a structural Tester PASS/FAIL
  gate (FD-2), a high-risk action-class always-approve policy (FD-3), audit-log parity for approval
  channels (FD-4), plus the spec truth pass and gates-default-on flip those unblock (FD-5) and a
  docs/positioning pass (FD-7). Board in TODO.md.
- **2026-07-02** — **Marked PHASE 11 complete** (CD-0…CD-9 all DONE 2026-06-25, suite green at 693;
  durable record added to the Phase 11 section, TODO board cleared per convention) and **added
  PHASE 12 — Consolidation & hardening** (CH-0…CH-13), driven by `internal-docs/architecture-audit.md`
  (2026-07-02: four parallel audit passes — architecture invariants, docs↔code sync, feature value,
  dead code/hardcoded data). Verified findings baked into the plan: store.py bypassed by
  `.docket-meta.json`/registry writes (atomic-write logic hand-copied 8+×), raw `openclaw` shell-outs
  outside the ACL, `core/provider.py` printing UI from the domain layer, `cli/__init__.py` at 4,194
  lines, `core/drift.py` with one caller feeding an unimplemented notification, the legacy `team`
  queue duplicating pod dispatch with no dispatcher, drifted hand-written completions, overdue D-2
  deprecation shims, 3 dead templates, 8 commands missing from docs/commands.md, spec/code mismatches
  (workflow extension + exit codes, team done-state), contradictory test counts (416/694 vs actual
  688), and the Bash-era `scripts/spec-coverage.sh`/`metrics.sh` still in CI while counting the
  deleted `lib/` tree. Decisions D-11 (retire `team` → pods) and D-12 (store.py single-writer rule,
  JSONL logs exempt) added. Explicit keeps recorded so the phase doesn't over-cut: the CD-6/7/8
  differentiators, ACL/store/sync, audit+approval, `resources.py`, and the policy/models_policy/
  provider trio (naming collision, not duplication).
- **2026-07-02 (later same day)** — **PHASE 12 COMPLETE.** All 14 CH-cards landed and merged
  into `develop`; `docket` 0.2.0 cut (CHANGELOG + VERSION + pyproject.toml + uv.lock +
  `__version__`; not tagged — operator step). Execution notes: 9 cards ran via parallel
  worktree-isolated agents on the first pass; a second wave (CH-7/CH-8/CH-10) was interrupted
  by an infrastructure session-limit error before any commits landed (cleanly recovered — CH-10
  was then done directly, CH-7/CH-8 re-ran successfully once the limit reset); CH-11 landed
  solo; CH-12 was done directly. Three real merge conflicts resolved by hand (`cli/__init__.py`
  together with `core/provider.py` on CH-4; a store-import alias in `core/models_policy.py` on
  CH-6). The
  README-numbers drift guard (re-armed by CH-9) caught real drift three times as later cards
  added tests/files — confirming it works. One negotiated deviation from the original exit
  criteria: `cli/__init__.py` landed at 1,702 lines (target ≤1,500) — CH-7's Do-list named 5
  extraction targets and no more; no 6th stage was invented to force the number down further.
  `CLAUDE.md` (gitignored/untracked) was synced directly on the local checkout throughout,
  since no git branch could carry an edit to it. TODO.md's board is now spent and awaiting the
  next phase.
- **2026-06-25** — **Added PHASE 11 — Competitive differentiation**, and marked Phase 10 complete in
  the status header. Driven by `internal-docs/competitive-analysis.md`: a deep-research pass (12
  sources, load-bearing claims re-fetched and confirmed verbatim) + a **GitHub-verified** sweep of the
  OpenClaw-native ecosystem. Findings: the space is bifurcated into monitoring dashboards
  (`builderz-labs/mission-control` ~5.4k★, `abhi1693/openclaw-mission-control` ~4.1k★, several
  `openclaw-dashboard`s) and setup scripts (`shenhao-stu/openclaw-agents` ~445★); the only true CLI
  lifecycle+governance peer is `oguzhnatly/fleet` (~13★, Bash, no pods/cost-policy/isolation). The
  broader field treats three things as unsolved — runtime-resource isolation, anti-fragile shared
  context, and a real HITL/audit spine — and docket already owns the second. Phase 11 cards CD-0…CD-9
  double down on the trio and close the two visible gaps (no dashboard-feed API; gates opt-in /
  Telegram-only). Backlog gained explicit deferrals: own web UI, microVM/gVisor isolation, multi-host,
  cross-runtime adapters. The deferred "Phase 0 gates default-on flip" is now sequenced under CD-4.
- **2026-06-24** — **Repointed stale `lib/` references to the Python layout.** Converted the
  now-dead clickable `lib/commands/*.sh`, `lib/helpers/*.sh`, `lib/core/*.sh`, and
  `tests/test-lifecycle.sh` markdown links (deleted in the M6 Bash→Python cutover) to plain text
  and annotated each with its current `src/docket/` location (`cli/` Typer commands, `core/`
  domain, `edges/` I/O incl. the ACL + `store.py`; tests now pytest under `tests/python/` + the
  golden suite). Historical phase content and plan meaning unchanged — only file pointers corrected.
- **2026-06-23** — **Consolidation + PHASE 10 added.** Folded the three standalone planning docs into
  this roadmap and removed them: `ARCHITECTURE-AUDIT.md` (language verdict — *migrate to Python* —
  executed by M6; build-vs-wrap + the language reasoning survive in §4.5/§0), `MIGRATION-PLAN-PYTHON.md`
  and `MIGRATION-TASKS.md` (the Bash→Python strangler-fig plan + task board — fully shipped; recorded in
  §0). Refreshed the stale Bash ground-truth (§2) and conventions (§3) to the Python three-layer/ACL
  reality; added §0 (completed migration) and §4.5 (durable architectural principles + anti-overengineering
  guardrails). **Added PHASE 10 — Agent architecture (pods)** (AA-0 … AA-9): fixes the three structural
  defects in the agent model — (A) "two doers" split between project agent and shared programmer, (B)
  shared specialist singletons break the session-key isolation guarantee, (C) "delegation" is instruction-only
  with no runtime. Plan: make **scope** a first-class axis (org vs project), reclassify the six specialists
  (security/knowledge → org; programmer/reviewer/tester → project-scoped pod roles; manager → per-pod Lead +
  optional org Portfolio Manager), provision each project as an isolated **pod** sharing one session key, and
  gate runtime dispatch behind a daemon-capability spike (AA-0). Executable cards in
  [TODO.md](TODO.md); rationale in `internal-docs/agent-structure-analysis.md`.
- **2026-06-22** — **PHASE 9 complete** (CDD-1 … CDD-6) *(pre-migration Bash paths below; the schema/validation/doctor logic now lives in `src/docket/core/` + `src/docket/cli/`)*: `lib/core/schema.sh` declares the full
  `.docket-meta.json` field set once (name/type/enum/sync-class); `meta_set` validates every write
  against it (unknown field → error, type mismatch → error, enum violation → error); `docket doctor`
  now diffs all `synced` fields (model + sessionKey) not just model, and `--fix` re-syncs from
  `.docket-meta.json`; phantom `{success,data,error,version}` envelope removed from spec, real per-
  command shapes documented in `specs/data/cli-json-shapes.spec.md`; `scripts/spec-coverage.sh`
  rewritten as a mechanical linter (router.sh case arms vs cli-interface.spec.md headings, exits 1
  on mismatch); spec de-staled — gates/audit/eval/models/completions/telegram/trace/metrics/
  policies/approve/deny added, profile tier-as-arg corrected to model-id/`default`, reset/repair
  stale "Used By" entries removed. 17 new unit tests; 325 total, all green.
- **2026-06-22** — Added **PHASE 9 — Contract integrity / de-ceremony** (CDD-1 … CDD-6), from a
  Contract-/Schema-Driven-Development audit. Scope-corrected the generic web-CDD brief to docket's
  reality: no OpenAPI/DB/codegen exist (so the "dead codegen loop" and "migration rigor" pillars
  are N/A by construction), so the audit targets docket's three real contracts — the markdown
  specs, the dual-source `.docket-meta.json` ↔ `openclaw.json` config, and the `--json`/HTTP
  shapes. Verified findings: the spec's `{success,data,error,version}` JSON envelope is emitted by
  **zero** commands (cli-interface.spec.md:340 vs no `"success"` in lib/commands/); `docket doctor`
  drift checks **only** `model` (doctor.sh:187-197/515-526) so budget/paused/modelSource drift
  silently; `_meta_set` does no type/enum validation; `spec-coverage.sh` scores presence not
  contract conformance; `gates`/`audit`/`eval`/`models`/`completions` are missing from the spec
  registry and `reset`/`repair` linger as live in input-validation.spec.md. Decisions D-9/D-10
  added. (This consolidated doc is now the roadmap.)
- **2026-06-22** — Added **PHASE 8 — Agent observability, guardrails & drift (HITL)** (OBS-0 …
  OBS-12), derived from the durable-trace / gated-destructive-action / guardrailed-untrusted-input /
  self-surfacing-drift spec (goals G1–G5) and an audit of the current cost, gates, Telegram, serve,
  task-queue and test subsystems. Key finding baked into the plan: **docket is not in the agent
  execution path** (the OpenClaw daemon executes tool calls), so the phase is sequenced
  observability (pure docket, ships first) → policy engine (pure, testable) → enforcement+HITL
  (the only hard daemon dependency, isolated) → drift. Collisions resolved: spec's `docket audit`
  → `docket trace export` (existing `audit` = operator-mutation log kept); `$DOCKET_HOME` aliased
  to `OPENCLAW_DIR`; per-run `session_id` derivation deferred to the OBS-0 spike. Spec open
  questions Q1–Q3 resolved as decisions D-6…D-8. Non-goals (no OTel/Prometheus/DB, no ML v1, no
  RBAC, filesystem-is-the-store) recorded as hard guardrails.
- **2026-06-12** — **PHASE 6b complete** (MA-9 ✅ MA-10 ✅ MA-11 ✅): `ROLE_MODELS`/`ROLE_WHY`
  policy in config.sh with registry `roles:` overlay (legacy `profiles:` still re-derives);
  `docket models` shows ROLE|MODEL|PRICE|SOURCE|WHY and `set <role>` / presets / reset all
  auto re-resolve policy-followers (`reapply_role_policy`, pins untouched, one restart,
  audit-logged); `.docket-meta.json` gains `kind` + `modelSource` (policy|pinned) with lazy
  inference for pre-existing agents (model ≠ policy → pinned, so nothing silently
  downgrades); `docket profile` is now pin/`default` semantics and covers specialists;
  install.sh resolves specialists through the policy and stamps their meta; doctor
  backfills taxonomy metadata; delete guards specialists; tier names everywhere are
  deprecated aliases with warnings; templates tier-neutral (TEMPLATE_VERSION=3); eval
  recommendations rephrased to role-policy actions; README/CLAUDE.md/docs/commands.md
  (incl. new `### models` section)/QUICK-START/DOCKET.md/WORKFLOW-GUIDE updated.
  Tests: 241 unit (18 new MA-9/MA-10) + 63 integration, all green.
- **2026-06-11** — Added PHASE 6b — Tier-less role→model policy (MA-9 … MA-11): unified
  agent/model architecture decided with user — tiers removed from UX (deprecated aliases
  only); global-only role→model policy map with per-role WHY, defaults picked for token
  efficiency (manager/reviewer/tester/knowledge/task on the cheap class, programmer/
  security/repo on the strong class, opus-class = explicit pin); agents store intent
  (`modelSource: policy|pinned`) and `docket models set/preset` auto re-resolves
  policy-followers; specialists join the `.docket-meta.json` system (`kind`/`role`, one
  taxonomy in `docket list`). Deferred: `docket models optimize` (eval × cost-history
  right-sizing, later phase) and per-task dynamic routing (needs daemon spike). Closes
  the install.sh hardcoded-specialist-models and model-drift gaps left open by Phase 6.
- **2026-06-11** — Added PHASE 6 — Model & provider agnosticism (MA-1 … MA-8, 🔴 critical):
  remove the hard Claude-API dependency; model registry, `docket models` command, provider
  presets incl. free/local, cost honesty, key plumbing, template + docs neutralization.
  (Phase 6 of this roadmap; the former "Product & community" is Phase 7.)
  Claude-dependency inventory verified against source this date.
- **2026-06-08** — Initial executable plan derived from the v2 product plan and source review. `agents.list` confirmed against live `~/.openclaw/openclaw.json`.
