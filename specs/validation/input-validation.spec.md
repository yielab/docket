# Input Validation Specification

**Version**: 2.0.0
**Status**: Implemented for project/pod ids, model ids, command verbs and arguments, credential
values and `AgentMeta`. Three gaps in what reaches those checks are recorded under the rules they
affect (flat `docket init --from` entries; an over-long directory name given to `docket init`).
**Last Updated**: 2026-10-22

## Purpose

This specification defines the input validation rules that docket enforces on what an operator,
an HTTP caller or a spec file hands it, so that data stays well formed, a bad id never reaches a
filesystem path, and a refusal is an ordinary error rather than a crash.

Validation is domain logic: it raises a typed error (or returns a warning list) and never prints.
The command layer turns a refusal into one error line and a non-zero exit; the HTTP layer turns it
into a `400`. Every side effect on docket-owned JSON goes through one atomic writer.

## Rules

### 1. Project / pod id

**Field**: project id, the id of a pod (`docket init`'s pod, the `name` of `POST /pods`, the
`<project>` segment of an HTTP route).
**Used By**: `docket init` (the id is the slug of the name, or of the directory name), the
blueprint entries of `docket init --from`, `POST /pods`, and every HTTP route that takes a project
path segment.

**Rules**:
- **MUST** be non-empty.
- **MUST** be at most 64 characters.
- **MUST** match `^[a-z0-9]+(?:-[a-z0-9]+)*$`: lowercase alphanumeric segments joined by a single
  hyphen, with no leading, trailing or consecutive hyphen. This is exactly the set the slug
  function can emit from a display name (`slugify`: lowercase, every run of other characters
  becomes one hyphen, strip hyphens at both ends).
- **MUST** be unique for creation. Uniqueness is enforced at each creation site, not by the id
  check: `docket init` refuses when a project or pod directory of that id exists, and pod
  provisioning raises `PodAlreadyExistsError` (`POST /pods` answers `409`, or `200` with
  `created: false` when `ensure` is set).
- No id is reserved; there is no reserved-word list.

**Enforcement**: `validate_project_id` returns the id unchanged or raises `ProjectIdError` naming
the rule. Pod provisioning (`provision_pod`) calls it first, before the per-project lock and
before any workspace path is built. A blueprint entry of `docket init --from` reports the error,
skips the entry and makes the command exit 1; `POST /pods` answers `400`. Every other HTTP route
with a project path segment calls it right after authentication and answers `400 {"error": ...}`.

A `docket init --from` entry **without** a `blueprint` field provisions a single flat agent, and
its `id` is not checked by this rule.

### 2. Model id

**Field**: model.
**Used By**: `docket setup model set <role|default> <provider/model>`; `docket init --from` flat
entries carry a `model` through the same check but keep the value as given when it fails (below).

**Rules**:
- **MUST** be a well-formed `provider/model` id matching `^[a-z0-9_-]+/[A-Za-z0-9._:/-]+$`
  (for example `anthropic/claude-sonnet-4-6`). There are no model aliases.
- A well-formed id docket does not know is **accepted** with a warning. For a local provider there
  is no warning (a local endpoint is priced at $0). For a marketplace provider the warning says
  the per-model price is not tracked and cost shows as `n/a (bring your own)`. Otherwise the
  warning says the model is not in the pricing table and cost shows as `n/a`.
- A malformed id **MUST** be rejected with a hard error that names the id, asks for a full
  `provider/model` id and lists the current role policy. `docket setup model set` prints it as one
  error and exits 1.
- A bare word, a tier name (`economy`/`standard`/`premium`) or an alias such as `claude-sonnet-4`
  is malformed and rejected like any other.
- docket does not check that the provider serves the model; an unknown model fails when a turn
  first uses it.

```bash
docket setup model set implementer anthropic/claude-sonnet-4-5   # accepted
docket setup model set implementer gpt-5                         # rejected: no provider/ prefix
```

In `docket init --from`, a flat entry's `model` is passed through the check and, when the check
raises, the value is stored as written.

### 3. Command verbs and arguments

**Field**: sub-command, option, argument.
**Used By**: every command and command group (`task`, `pod`, `log`, `setup` and its `provider`,
`model`, `sandbox`, `notify`, `export`, `mcp` groups, and the top-level commands).

**Rules**:
- **MUST** be a verb the group declares; an unknown verb or unknown option is a usage error that
  exits 2, before any command body runs.
- Verbs and options are case sensitive: a verb in the wrong case is an unknown verb and exits 2.
- A missing required argument is a usage error that exits 2.
- A typed parameter (an `int`, for instance) that cannot be converted is a usage error (exit 2);
  a bound such as `--count` at least 1 is declared on the parameter.

No command body matches an action word by hand: the verbs and their required arguments are
declared in the command signatures.

### 4. Credentials

**Field**: credential name and value.
**Used By**: `docket setup provider add`, `docket setup provider rotate`.

**Rules**:
- A credential name is never free-typed: it is the name the provider's catalog entry declares
  (`ANTHROPIC_API_KEY`), or, for a custom provider, derived from the provider name by upper-casing,
  turning every run of other characters into `_` and appending `_API_KEY`.
- A credential value **MUST NOT** be empty. With no `--credential` flag and no value in the
  provider's environment variable, a terminal gets a hidden prompt; without a terminal the command
  fails saying the variable is required.
- A value **SHOULD** start with the `credentialPrefix` of the catalog entry that declares the
  credential (the shipped catalog sets one for anthropic `sk-ant-`, openai `sk-`, google `AIza` and
  openrouter `sk-or-`). A mismatch prints `Key format: should start with '<prefix>'` as a warning
  and the value is stored anyway: keys from new providers must stay storable. No minimum length is
  checked, and a credential with no declared prefix is never warned about.

```bash
docket setup provider add anthropic --credential <key>
docket setup provider rotate anthropic
```

### Boundary sanitization

- **Shell injection**: every external call is built as an argument list and never goes through a
  shell, with one deliberate exception. A pod's verify command is an operator-owned string stored
  in `.docket-meta.json` and run through a shell, because real verify pipelines use `&&`, pipes
  and redirects. It is bounded rather than interpreted: `validate_verify_cmd` rejects a NUL byte,
  a newline or carriage return, and a length over 2000 characters, at `docket pod set verify`,
  `--verify` and `POST /pods`; and the run refuses a command that matches a high-risk class. The
  gate and the jail that contain it are specified in `security-gates.spec.md`.
- **JSON escaping**: docket-owned JSON is serialised by the standard library through the one
  atomic writer (file lock, `.bak` rotation, `0600` permissions); no JSON is built by hand.
- **Path traversal**: an agent's file-tool paths are resolved (`..` and symlinks included) and
  must lie under the tool call's allowed roots (the agent's workspace and codebase); a path outside
  every root, or a call with no roots, is refused. A workspace is addressed by a project id that
  passed rule 1.

### Error message conventions

A refusal is one `error` line with an optional hint line, and the command exits 1 (usage errors
exit 2, rule 3). Core code raises `ValueError` subclasses and never prints.

| Validation | Message | Hint |
|------------|---------|------|
| Project id (`ProjectIdError`) | `project id must be non-empty, at most 64 characters, and match ^[a-z0-9]+(?:-[a-z0-9]+)*$ (got: '<id>')` | none |
| Model id | `Invalid model: '<id>'` followed by the role policy | `Use provider/model` |
| Empty credential value | `Value cannot be empty` | none |

## Functions

Every command **MUST** route untrusted input through the matching validator (a typed parameter,
a Pydantic model or a domain helper) before acting on it.

| Function / model | Validates | Returns |
|------------------|-----------|---------|
| `validate_project_id(project)` | Project/pod id grammar and length | the id, or raises `ProjectIdError` |
| `slugify(name)` | Not a validator: derives an id from a name | the slug |
| `validate_model(model)` | `provider/model` grammar | `(model, warnings)`, or raises `ValueError` |
| `validate_verify_cmd(cmd)` | Verify command: no NUL, no newline, at most 2000 characters | the command, or raises `VerifyCmdError` |
| verb and argument declarations | Verb in the group's set, required arguments present, typed parameters | the command body runs, or exit 2 |
| credential prefix check | Value against the catalog's `credentialPrefix` | `(ok, reason)`; the caller warns on a mismatch |
| `AgentMeta` | The whole `.docket-meta.json` record | a parsed model, or `pydantic.ValidationError` |

`AgentMeta` is the structural validator of an agent's persisted metadata. `kind` and `scope` accept
only `project`; `workspaceKind` accepts `codebase` or `workdir` (default `codebase`); `scope`
defaults to `project`; fields use camelCase aliases and either spelling is accepted on input;
unknown keys are kept on a round trip. Setting one metadata field validates the whole record before
it is written.

## Testing

Validation is covered by the pytest suite (unit, integration and guards lanes):

```bash
uv run pytest
```

- Project id: accepted and rejected ids, `slugify`, a blueprint entry of `init --from` with a
  traversal id (exit 1, nothing provisioned), and `POST /pods` with a traversal name.
- Model id: the unknown-model, local-provider and marketplace-provider warnings.
- `AgentMeta`: camelCase round trip and the field set.
- Verbs: unknown verb, missing argument and bounded-option usage errors exit 2.
- Credentials: add, rotate and remove flows and their audit entries.

Untested: the rejection of a malformed or tier-name model id and its error text; the
`Key format` prefix warning; the verb case-sensitivity rule; the `400` on each project-segment
HTTP route other than `POST /pods`.

## Performance

Validators are in-process regex, type and file-read checks; none calls the network. No latency
budget is specified, and validation results are not cached.

## Implementation

Where the names above live today:

- `src/docket/core/provisioning.py`: `slugify`, `validate_project_id`, `ProjectIdError`
- `src/docket/core/pod_provisioning.py`: `provision_pod`, `PodAlreadyExistsError`, `validate_verify_cmd`, `VerifyCmdError`
- `src/docket/core/models_policy.py`: `validate_model`
- `src/docket/core/models.py`: `AgentMeta`, `AgentKind`, `AgentScope`, `WorkspaceKind`
- `src/docket/core/fleet.py`: `meta_set` (validates the record before writing)
- `src/docket/serve.py`: the project-segment check on every route with a project segment, and `POST /pods`
- `src/docket/cli/_agents.py`: `docket init`, `docket init --from` (blueprint and flat entries)
- `src/docket/cli/_pod.py`: `build_pod_from_blueprint`, `docket pod set verify`
- `src/docket/cli/_setup_model.py`: `docket setup model set`, `docket setup provider add|rotate`, the credential prefix check and name derivation
- `src/docket/cli/__init__.py`: the command and group registry that declares the verbs
- `src/docket/core/provider.py`: the provider catalog (`credentialPrefix`); shipped entries under `src/docket/templates/providers/`
- `src/docket/edges/adapters/system.py`: `run_verify_cmd`, the one shell invocation
- `src/docket/edges/adapters/toolbox.py`: `resolve_within`, the allowed-roots check for file tools
- `src/docket/edges/store.py`: the atomic JSON writer
- Tests: `tests/unit/core/test_provisioning.py`, `tests/integration/test_pod_blueprint_provisioning.py`, `tests/integration/test_serve_pods_endpoint.py`, `tests/integration/test_provider_agnosticism.py`, `tests/integration/test_data_layer.py`, `tests/unit/cli/test__setup_model.py`, `tests/unit/cli/test__task.py`
