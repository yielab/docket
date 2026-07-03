# Workflow Integration Specification

**Version**: 1.1.0
**Status**: Complete
**Last Updated**: 2026-07-02

## Purpose

This specification defines how docket manages Lobster workflows — deterministic YAML pipelines
stored per agent that allow repeatable, token-efficient execution of multi-step tasks.

## Scope

This specification covers:

- Creating a workflow template (`docket workflow <id> create <name>`)
- Listing an agent's workflows (`docket workflow <id> list`)
- Displaying a workflow (`docket workflow <id> show <name>`)
- Deleting a workflow (`docket workflow <id> delete <name>`)
- Validating a workflow's YAML structure (`docket workflow <id> validate <name>`)
- Planning a workflow run without executing it (`docket workflow <id> plan <name>`)
- The on-disk location and structure of workflow files

This specification does NOT cover:

- The Lobster execution engine itself (owned by OpenClaw)
- Cross-agent orchestration (see team-coordination.spec.md)

## Requirements

### Workflow storage

1. Workflows **MUST** live under the agent's workspace at
   `~/.openclaw/workspaces/projects/<id>/workflows/<name>.lobster.yml`.
2. `create` **MUST** write only the `.lobster.yml` extension. `list`, `validate`, and `plan`
   **MUST** also recognize a `.lobster.yaml` file if present (either extension is a valid
   on-disk workflow, but new files are always written as `.lobster.yml`). `show` and `delete`
   look up `.lobster.yml` only — a workflow that exists solely as `.lobster.yaml` will not be
   found by `show`/`delete`. This asymmetry is a known inconsistency (documented here as
   current behavior, not fixed by this pass — a fix would need to add the same fallback used
   by `validate`/`plan`/`list` to `show`/`delete`).
3. The `workflows/` directory **MUST** be created on demand if absent.
4. File permissions **MUST** follow the project convention (700 dirs, 600 files).

### Create (docket workflow create)

1. **MUST** generate a valid Lobster YAML template named after the provided workflow name.
2. If a workflow of the same name already exists, **MUST** warn and leave the existing file
   untouched, without creating a new one. This is **not** an error condition — the command
   still exits `0`.
3. **SHOULD** include commented placeholders for steps so the file is editable immediately.

### List / Show / Delete

1. `list` **MUST** enumerate all workflows defined for the agent (matching either extension —
   see Workflow storage above).
2. `show` **MUST** print the raw YAML of the named workflow.
3. `delete` **MUST** remove the named workflow file and confirm removal; it **SHOULD** prompt
   for confirmation on an interactive terminal and skip the prompt (still deleting) when stdin
   is not a TTY.
4. `show` and `delete` **MUST** report "not found" and exit non-zero when the named workflow
   does not exist.

### Validate (docket workflow validate)

1. `validate` **MUST** parse the workflow YAML and report any structural errors.
2. **MUST** check that required top-level Lobster fields (`name`, `steps`) are present.
3. **MUST** check that every step has an `id` and a `type`, that step ids are unique, that
   each step's `type` is a known Lobster step type, and that each type's required fields are
   present.
4. **MUST NOT** execute any workflow steps.
5. **SHOULD** report a success message on a valid workflow (no fixed literal wording required).

### Plan (docket workflow plan, alias `dry-run`)

1. `plan` **MUST** display the workflow steps in execution order without running them,
   annotated with each step's id and type.
2. **MUST NOT** invoke the daemon or consume tokens. **MUST NOT** estimate or display a token
   cost — docket has no way to price an unexecuted Lobster step, and this spec follows the
   project's no-unfalsifiable-cost-claims discipline (see CLAUDE.md's cost-guardrails note).
3. **MUST** state explicitly in its output that docket does not execute the workflow — the
   Lobster daemon does.

### Naming

1. Workflow names **MUST** be slugified to a filesystem-safe form.
2. The `name` argument **MUST** be required for `create`, `show`, `delete`, `validate`, and
   `plan`/`dry-run`.

## Interface Contracts

### CLI Command Signatures

```bash
docket workflow <agent-id> create <name>            # Generate a new Lobster template
docket workflow <agent-id> list                     # List the agent's workflows
docket workflow <agent-id> show <name>               # Print a workflow's YAML
docket workflow <agent-id> delete <name>             # Remove a workflow
docket workflow <agent-id> validate <name>           # Check YAML structure; exit 0 if valid
docket workflow <agent-id> plan <name>               # Show step plan without executing
docket workflow <agent-id> dry-run <name>            # Alias for `plan`
```

### Return Codes

The command uses a plain success/failure contract — `0` on success, `1` on any error. There is
no distinct exit code per error kind (agent not found, workflow not found, missing name
argument, invalid YAML all exit `1`); only the printed message distinguishes them. Creating a
workflow that already exists is **not** an error — it warns and exits `0`.

- `0`: Success (including "already exists" on `create`, which warns but does not fail)
- `1`: Any error — agent not found, workflow not found (`show`/`delete`/`validate`/`plan`),
  missing required `name` argument, or invalid Lobster YAML (`validate`/`plan`)

## Examples

### Creating and listing a workflow

```bash
$ docket workflow mywebsite create deploy
Workflow created: /home/user/.openclaw/workspaces/projects/mywebsite/workflows/deploy.lobster.yml

Next steps:
  1. Edit workflow: $EDITOR .../deploy.lobster.yml
  2. Run workflow:  lobster run --workspace ... --workflow deploy

$ docket workflow mywebsite list
Defined workflows:
  ● deploy                   3 steps

Run a workflow:  lobster run --workspace ... --workflow <name>
```

### Validating and planning a workflow

```bash
$ docket workflow mywebsite validate deploy
Workflow 'deploy' is valid

$ docket workflow mywebsite plan deploy
Workflow: deploy
Steps (3):
    1  build                       shell        run: npm run build
    2  test                        shell        run: npm test
    3  deploy                      shell        run: ./deploy.sh

────────────────────────────────────────────────────────────────────
NOTE: docket does not execute this workflow — the Lobster daemon does.
  To execute:  lobster run --workflow deploy
────────────────────────────────────────────────────────────────────
```

### Showing a workflow

```bash
$ docket workflow mywebsite show deploy
name: deploy
steps:
  - id: build
    type: shell
    run: npm run build
```

## Validation

### Pre-conditions

- The target agent **MUST** exist.
- For `create`/`show`/`delete`/`validate`/`plan`, a workflow `name` **MUST** be supplied.

### Post-conditions

- After `create`, a readable `<name>.lobster.yml` **MUST** exist in the agent's `workflows/` dir.
- After `delete`, the named workflow file **MUST NOT** exist.

### Invariants

- Workflow files **MUST** be valid YAML parseable by the Lobster engine.
- A workflow name **MUST** be unique within a single agent.

## Changelog

### Version 1.1.0 (2026-07-02)

- CH-10 spec truth pass: corrected the workflow file extension throughout (`.yaml` → the real
  `.lobster.yml`, noting the `list`/`validate`/`plan` vs `show`/`delete` extension-fallback
  asymmetry); replaced the invented `2`/`3`/`4` return codes with the real plain `0`/`1`
  contract (and noted "already exists" on `create` is not an error); added `validate`/`plan`
  requirement detail matching `core/lobster.py`'s actual checks; removed the `plan`
  "estimated token cost" claim (never implemented, and out of scope per the project's
  no-unfalsifiable-cost-claims discipline); added the `dry-run` alias to the signatures;
  corrected pre/post-conditions and examples to match real output and the `.lobster.yml`
  extension.

### Version 1.0.0 (2026-06-09)

- Initial workflow integration specification
- Defined create/list/show/delete contract and on-disk layout
