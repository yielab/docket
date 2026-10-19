# ADR 0029 (D-65): a prepared checkout, models from the provider, and a check the change cannot define

**Question:** a sibling project (Fabulada, through Tack, 2026-10-19) found four things in one
onboarding. A task's worktree has no dependencies, so every check of a Node project fails before
it looks at the change. The provider catalog is a fixed list, and a model outside it runs with
no context window, no price and a 4,096-token output cap. A team's check runs files the change
itself can edit. And one approval per repository is overwritten by the next team. What does
docket change?

**Where decided:** 2026-10-19, by the maintainer, from the investigation below (`develop` at
`cd75351d`). The per-step token limit needs no change: Tack decided on 2026-10-19 (its ADR 0086
decision 5) that every run it sends carries a limit, and docket already gives each step what is
left of a task's `maxTokens`; `AGENT_LOOP_TOKEN_BUDGET` stays as it is, for a task that comes with
none.

## The decision, on one screen

1. **docket prepares the worktree it makes.** When it provisions a task's worktree, docket runs
   one install command before the first hop:
   - The command comes from the lockfile at the worktree's root (`package-lock.json` → `npm ci`,
     `pnpm-lock.yaml` → `pnpm install --frozen-lockfile`, `yarn.lock` → `yarn install --immutable`,
     `uv.lock` → `uv sync --frozen`, `poetry.lock` → `poetry install`, `Cargo.lock` → `cargo fetch`).
   - A team replaces it or turns it off with `prepare:` in its directory. A task can carry its own
     `prepare` (Tack sends the project's), which wins.
   - It runs inside the jail **with network for that phase only**. The hops then have the pod's
     `network`.
   - What one lockfile installs is kept once per codebase and lockfile hash and linked into each
     task's worktree. The second task with the same lockfile prepares in seconds.
   - The command is part of the reviewed set of the team directory (it runs on this machine), and
     a task's own `prepare` is shown in the task before it runs.
   - A failed install fails the task with `failureKind: "prepare"` and the command's output, before
     any hop spends a token.

2. **Models come from the provider, never from a list in docket.** `provider add` and a periodic
   refresh read the provider's `/models`. A model's context window and output cap come from what
   the provider publishes there (Anthropic publishes `max_input_tokens` and `max_tokens`). The
   shipped provider templates keep only connection data: URL, dialect and credential name. A value
   the provider does not publish is shown as **unknown**, never filled in: no silent 4,096 output
   cap. Prices are not needed for limits, which are in tokens.

3. **A check is never defined by the change it checks.** A team's gate is quick feedback for the
   agent; the verifier, which reads its configuration from the base commit, is what a merge trusts.
   - Every team has **protected paths**: by default lockfiles, manifests (`package.json`,
     `pyproject.toml`, `Cargo.toml`), the configuration of lint, type and test tools,
     `.docket/`, `prill.yaml` and CI workflows. `protects:` in the team directory adds to them.
   - When a task's diff touches a protected path, the task is marked `check_changed`, names the
     paths, and never finishes lights-out: it waits for a person, whatever the pod's profile.
   - The reviewed digest covers the **contents**, at the base commit, of every repository file a
     reviewed command names (a script, a config file), not only the command's text. Merging a
     changed script asks for review again.

4. **Approvals are kept per repository and team, as a set.** `reviewed-repos.json` keeps, for each
   (codebase, pod), every digest a person approved. Applying one team no longer overwrites another
   team's approval, and returning to an approved set asks nothing.

## Decisions taken (2026-10-19)

- docket, not Tack and not the onboarding skill, prepares the worktree docket makes; Tack stops
  making a second copy for a docket run (Tack ADR 0086).
- No fixed model lists; values the provider does not publish are said to be unknown.
- The change cannot define its own check; protected paths send it to a person.
- Approvals per repository and team, kept as a set.

## What this does not do

- Change the per-step token limit or `budgetUsd`: a task's `maxTokens` already bounds its steps (see
  "Where decided").
- Build container images per project, or guess an install without a lockfile.
- Restore protected files from the base commit before a gate runs: a legitimate change to a
  manifest (a new dependency) would then be checked against the old one. It is sent to a person
  instead.

## Evidence (2026-10-19)

- **No preparation anywhere.** `_ensure_task_worktree` → `provision_task_worktree`
  (`core/pod_provisioning.py`) runs `git worktree add -b docket/<pod>/<task-id>` from `baseRef`
  and nothing else; `node_modules` appears only in skip lists (`repo_map.py`, `toolbox.py`). A
  gate runs in that worktree, jailed, with the pod's network (`dispatch.py` `_gate_cwd`,
  `docket_runtime.py` `effective_network`). Measured in a fresh worktree of Fabulada:
  `Cannot find package 'eslint'`, `Cannot find module 'vitest/config'`, and `tsc` 7.0.2 from the
  machine against the project's 5.9.3.
- **The trigger D-63 named.** D-63 (ADR 0027) deferred a "warm workspace" with a trigger, after
  measuring `npm ci` 6.5 s and a build 15.5 s per worktree (829 MB). Fabulada's first code run
  through a team is that trigger: without it no check of a Node project can pass.
- **Fixed catalog.** `templates/providers/01-anthropic.yaml` lists Claude 4.x models with
  `pricesAsOf 2026-06-11`; `/models` is probed only to warn about extra models
  (`core/provider.py`). A step `model:` is checked for its provider only (`models_policy.py`
  `resolve_step_model`); an unknown id gets no context window and an output cap of 4,096
  (`llm.py` `endpoint_from_spec`, `config.py`).
- **The check runs what the change wrote.** `reviewed_repos.py` hashes the sorted
  `(kind, name, command)` strings; a gate such as `npx eslint` reads `eslint.config.mjs` and
  `package.json` from the task's worktree, which the agent edits.
- **One approval per repository.** `reviewed_repos.py` stores one entry per codebase and
  overwrites it; `audit.log` shows fab-dev's and fabulada's approvals 0.3 s apart, the second
  replacing the first. The 2026-10-19 apply that asked no code was not a bypass: its five
  commands had the digest approved on 2026-10-18 (`8b951b9ae5cbe3a9`, audit seq 76).
