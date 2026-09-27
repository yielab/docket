# ADR 0012 (D-46): the team lives in the repo — agent teams as configuration, your rules, in YAML

**Question:** After Phases 26–29 every layer of a docket team is a document — `kind: role`,
`kind: pipeline`, `kind: policy`, `kind: pod`, `kind: provider` — with one loader, one
`docket validate`, published schemas, short forms, and `docket pod <p> apply|export` proven by a
round trip. Yet the honest sentence is still "the operator configures it per machine", not "the
team commits it and everyone has it": nothing discovers a repository's own `.docket/` directory
at provisioning time, a shipped recipe still needs `init` and then `apply`, `export` needs a path,
and no record says which directory a pod was configured from. The 2026-09-27 repositioning
request ("agent teams as configuration, your rules, in YAML"; implement repository configuration
files properly, to standards and best practices) makes that sentence the product's front door.
What is the shape, and what earns a card?

**Where decided:** 2026-09-27, as Phase 30. **Activation gate:** none (Phase 29 closed at
`8154676`); the integrator confirms batching from function-level contention as usual.

**Evidence** (read at `b75a258`; every locator is a symbol name, re-locate with `rg -n`):

| Fact | Locator |
| --- | --- |
| `<codebase>/.docket/` is already the default of `apply` and `validate`, but nothing reads it at `init` | `cli/_pod.py::_pod_apply_default_dir`; `cli/_validate.py` (default target); `cli/_agents.py::run_init` (no apply step) |
| `export` requires a path and refuses a non-empty one | `cli/_pod.py::_pod_export_cmd` |
| A shipped recipe is applied with two commands and a path into the wheel | `config.py::recipes_dir()` has no consumer; `templates/recipes/*/README.md` |
| A pod records its bound pipeline by sha256 and dispatch verifies it; nothing records the applied directory | `core/pod.py::PodSettings.pipeline`; `core/dispatch.py::_blueprint_pipeline` |
| A pipeline step has `retries`/`timeout`/`instructions` overrides but no `model` | `core/pipeline.py::Step`; `core/dispatch.py::_run_hop_turn` passes the member's meta model |
| `editRights` is written by `to_wire`, read only by `roles list`'s display column; `deniedTools` is what narrows the registry | `core/archetypes.py::RoleArchetype.edit_rights`; `cli/_roles.py` |
| The audit of 2026-09-26 recorded these as the distance between the format and the promise | `internal-docs/positioning-audit-2026-09-26.md` §9.2 items 1 and 5, §10.3 (gitignored) |
| ADR 0008 deferred the manifest with the trigger "a pod reproduced on a second machine"; ADR 0009 shipped apply/export; the discovery half stayed open | `docs/adr/0008-configuration-contract.md` verdict table; `docs/adr/0009-per-pod-configuration-and-portable-teams.md` |

The trigger is an explicit scoped request; no quantitative threshold is invented.

## Decision

**A repository's `.docket/` directory is the team's configuration of record.** `docket init`
discovers it, validates it, provisions the pod and applies it; `docket init --recipe` starts from
a shipped or local recipe the same way; `apply` and `export` default to it; the pod records the
directory and its content digest so `config explain` can say where the team came from and
whether the directory has changed since. Nothing is ever applied without an operator command.

### 1. The directory (the shape `export` already writes)

```text
<repo>/.docket/
  pod.yaml          kind: pod  — members, settings, optional pipeline filename
  roles/*.yaml      kind: role — plus <name>.md with the role's instructions
  pipeline.yaml     kind: pipeline
  policies/*.yaml   kind: policy (JSON still loads)
  plugins/*.py      hashed predicate plugins (ADR 0010)
  .schemas/         published config-v1 schemas, referenced by every file's header
```

Conventions, in the order a newcomer meets them: the directory is `.docket/` next to `.github/`
and `.claude/`, never a second name; every file starts with `kind:` and `name:` and validates with
`docket validate` from the repository root with no argument; short form is what `export` writes
and what the docs show; a credential value never appears (documents carry names; ADR 0011);
`.schemas/` is generated and may be committed so editors autocomplete offline.

### 2. Discovery and application (best practices, each with its reason)

1. **Operator command or nothing.** `docket init`, `docket init --recipe`, and `docket pod <p>
   apply` are the only readers of `.docket/`. Dispatch never re-reads it: an Implementer editing
   `.docket/` in its worktree changes nothing until the operator applies it, exactly as a bound
   pipeline is verified by hash rather than re-read from the operator's path. Repository
   configuration is untrusted input until an operator applies it.
2. **Validate before provisioning, apply after.** `docket init` validates every document under
   `.docket/` (`core.config_docs.validate_directory`) before it creates anything; a validation
   error exits 1 with the file, line and field and provisions nothing. After the pod exists, the
   same plan/apply path `docket pod <p> apply` uses runs, and its `pod.apply` audit entry is
   written. `--no-apply` provisions the pod and skips the directory, printing the command that
   would apply it.
3. **Policies from the repo cannot loosen the operator's.** They land in the pod scope and
   accumulate with global policies under the existing most-restrictive rule (ADR 0009); a
   repository cannot switch a global `block` into `allow`.
4. **Recipes are first-class at creation.** `docket init --recipe <name|dir>` resolves a shipped
   recipe (`templates/recipes/<name>`) or a directory and applies it after provisioning. It is
   mutually exclusive with a present `.docket/`: two sources of record is the ambiguity the
   command refuses, naming both.
5. **The pod knows where it came from.** `apply` records `configSource` (the absolute directory)
   and `configDigest` (sha256 over the sorted relative paths and bytes of every applied file) in
   the pod's settings; both are written only by `apply`, never by `config set`. `docket config
   explain <agent>` prints the source and `drift: yes|no` by recomputing the digest; `pod <p>
   export` with no path writes `<codebase>/.docket/` and refuses a non-empty one without
   `--force`, as today.
6. **Per-step model is data.** A pipeline step may declare `model: cheap|strong|<provider/id>`;
   it wins for that hop only, is never persisted to the agent's meta, and `plan` prints it. A
   pinned agent stays pinned in its meta (the README promise "never re-resolved behind your
   back" is about persisted state), and a step override is the operator's own declaration in a
   hash-bound file.
7. **One field says it.** `editRights` is retired from the canonical role form: `from_wire`
   accepts and drops it (existing overlays keep loading), `to_wire` stops writing it, `roles
   list` drops the column, `docket validate` prints a `note:` for a file that still carries it.

### 3. What this ADR does not do

No automatic apply on dispatch or on `git pull` (rule 1). No `.docket/` discovery for org
specialists or flat agents. No multi-pod repositories (`pod.yaml` names one pod; a monorepo with
two pods keeps two directories under a path the operator passes explicitly). No `docket apply` at
the top level: `init` and `pod <p> apply` are the two moments a team is applied. No merge or
three-way reconciliation: `apply` stays additive and idempotent (ADR 0009); removal stays
explicit. No DAG, expressions or includes (ADR 0010 stands).

## Rules this ADR amends

| Document, rule | Today | After |
| --- | --- | --- |
| pod-blueprints "Pod manifests: apply" | `apply` reads `<dir>` (default `<codebase>/.docket/`) on an existing pod | unchanged, plus: `docket init` validates and applies a present `.docket/` (or `--recipe`) after provisioning; `apply` records `configSource`/`configDigest` (P30-1, P30-2) |
| pod-blueprints "Pod manifests: export" 1, 3 | `export <dir>` requires a path | `<dir>` defaults to `<codebase>/.docket/`; the non-empty refusal stands (P30-2) |
| cli-interface `docket init` | flags `--pod`, `--with`, `--blueprint`, `--codebase`, `--name`, `--from` | plus `--recipe <name|dir>` and `--no-apply`; the readiness rule stands (P30-1) |
| cli-interface `docket config explain` | no configuration source | prints `configSource`, `configDigest` and `drift` (P30-2) |
| pipeline-format "Steps", "Short form" | `retries`, `timeout`, `instructions` per step | plus `model` (P30-3) |
| pod-dispatch hop execution | the hop's model is the member's meta model | a step `model` wins for that hop only (P30-3) |
| model-profiles resolution | policy → pin | step override (per hop, unpersisted) above both (P30-3) |
| role-archetypes wire format | `editRights` is a canonical field | accepted and dropped on read; not written; `note:` on validate (P30-4) |

Rules that stand: ADR 0008's "one writer per setting"; ADR 0009's additive, idempotent `apply` and
most-restrictive policy accumulation; ADR 0010's cuts; ADR 0011's credentials by name; D-24's
single operator.

## Verdict table

| Item | Verdict | Card | Reason |
| --- | --- | --- | --- |
| `docket init` discovers, validates and applies `.docket/`; `--recipe`; `--no-apply` | **DO** | P30-1 | the sentence the front door needs |
| `configSource`/`configDigest`, `explain` drift, `export` default | **DO** | P30-2 | the record half of "configuration of record" |
| `model:` per pipeline step | **DO** | P30-3 | §9.2 item 5; small, data, `plan` shows it |
| Retire `editRights` | **DO** | P30-4 | §10.3; one field says it |
| Refreshed assets from one real run, with the docket wordmark | **DO** (integrator) | P30-5 | the README shows, not lists |
| README v3 on the tagline; prose tests rebuilt from it; docs | **DO** (integrator) | P30-6 | D-37 |
| Auto-apply on dispatch or pull | **CUT** | — | an agent could rewrite its own rules |
| Multi-pod repositories, top-level `docket apply`, reconciliation/prune | **DEFER** | — | **Trigger:** a monorepo with two pods, or an operator asking to prune twice |
| User blueprints as `kind: blueprint` | **DEFER** (unchanged) | — | a recipe at `init --recipe` covers the shape; ADR 0008's rule of three |

## Test discipline

One RED behavioural test per card in the module's `SUBJECT` file; a negative case only for a
fail-closed property (P30-1: an invalid `.docket/` provisions nothing; P30-2: `export` refuses a
non-empty default without `--force`). The round trip (`init --recipe secure-build` → `export` →
`init` on a second `DOCKET_HOME` from that export → `config explain --json` agrees) is the phase's
integration proof, owned by P30-2's integration test. Goldens change only where CLI surface
changes (`init` help, `roles list`, completions) and each card lists the lines.

## Waves (proposed; the integrator confirms from function-level contention)

| Wave | Cards | Hot file and function ownership |
| --- | --- | --- |
| 50 | P30-1 ∥ P30-2 ∥ P30-3 ∥ P30-4 | `cli/_agents.py::run_init` + `_parse_add_args`, `core/pod_apply.py::resolve_recipe` (new) → P30-1; `core/pod.py::PodSettings` (two fields), `core/pod_apply.py::apply` + `::directory_digest` (new), `cli/_pod.py::_pod_export_cmd`, `cli/_config.py` → P30-2; `core/pipeline.py::Step` + `normalize_pipeline`, `core/orchestrator.py::PlannedUnit`, `core/dispatch.py::_run_hop_turn`, `core/runtime_driver.py::RuntimeDriver.run_turn`, `edges/adapters/docket_runtime.py::run_turn`, `cli/_pipeline.py` (plan render) → P30-3; `core/archetypes.py` (`edit_rights`), `cli/_roles.py`, `cli/__init__.py` (roles help line), `core/config_docs.py::_load_role` (the `note:`), schemas → P30-4 |
| 51 | P30-5, then P30-6 (integrator) | `scripts/render-doc-assets.py`, `scripts/maint/capture-doc-journey.sh`, `docs/assets/`; then `README.md`, `tests/agent/{truth,release}`, `pyproject.toml`, `mkdocs.yml`, `docs/CONFIGURATION.md`, `docs/QUICK-START-DOCKET.md` |

Pre-assigned spec versions: pod-blueprints 1.11.0 (P30-1), 1.12.0 (P30-2); cli-interface 1.45.0
(P30-1), 1.46.0 (P30-2), 1.47.0 (P30-4); pipeline-format 2.10.0, pod-dispatch 6.22.0,
model-profiles 2.16.0 (P30-3); role-archetypes 1.19.0 (P30-4).

## Consequences

- The honest sentence after Phase 30: *a team is a directory in the repository; `docket init`
  reads it, `docket validate` checks it, `export` writes it back, and `config explain` says which
  one a pod runs and whether it has drifted.* Before it, the sentence stops at "applied per
  machine with a path".
- The README leads with that sentence (P30-6) and shows it (P30-5), and the prose tests are
  rebuilt from the new README rather than carried forward.
