# Configuration Document Format Specification

**Version**: 1.12.0
**Status**: Implemented
**Last Updated**: 2026-10-23

## Purpose

This specification defines the **configuration document envelope**: the `kind:`/`name:` pair
every docket-native configuration file starts with, and the single entry point,
`load_document`, that reads one such file, resolves its kind, and dispatches to the parser that
owns that kind's real structure. `docket pod validate` is the one command that checks every
kind of file in a directory in one pass.

## Scope

This specification covers:

- The envelope: every configuration document starts with `kind:` (one of `role`, `pipeline`,
  `policy`, `pod`, `provider`, `exporter`, `channel`, `mcp-server`) and `name:`;
  `load_document(path)` reads the file, resolves its kind, and dispatches to the existing
  parser for that kind
- Files with no `kind:` key: a canonical-form file still loads when its location (or the caller)
  names a kind, and is marked `deprecated=True` so `docket pod validate` can advise adding the
  key; a short-form file without `kind:` is refused
- `ConfigDocError`: the one error shape every kind's validation failure is reported through,
  and its `<file>:<line> <field>: <message> (valid: ...; did you mean "...")` rendering
- `docket pod validate [dir|file]`: validates every document under a directory (or one file),
  printing one line per file, invalid files first, exit 1 when any file is invalid
- The eight parsers this dispatches to unchanged: `from_wire` (with the role file loader) for
  `role`, `load_pipeline` for `pipeline`, `validate_policy` for `policy`, the pod manifest key
  set for `pod`, `load_provider_document` for `provider`, `load_exporter_document` for
  `exporter`, `load_channel_document` for `channel` and `load_mcp_server_document` for
  `mcp-server`. `provider` has no published schema (canonical form only); `exporter`,
  `channel` and `mcp-server` each have a published schema generated directly from their own
  canonical model, since none has a separate short form to refine against
- The published `docs/contracts/config-v1/{role,pipeline,policy,pod,exporter,channel,mcp-server}.
  schema.json` JSON Schemas, generated from the short-form models that also refine a short-form
  document's `ConfigDocError`, and the `# yaml-language-server:`/`.schemas/` convention
  `docket pod export` writes its short-form output with (see "Published schemas", "Short-form
  export")

This specification does NOT cover:

- The short-form normalizers of role, pipeline, policy and pod (owned by the role, pipeline,
  security and pod-blueprint specs); this spec only describes the short-form *models* used for
  schema generation and error refinement
- Wiring JSON Schema validation into `docket pod validate`'s live path: the published schemas are
  a generated, pinned artifact for external editors/validators, never consulted by
  `load_document` itself
- A published JSON Schema or short-form sugar for `provider`: it has neither
- Refusing a kind-less canonical file: nothing refuses to load one whose kind a location or the
  caller names
- Re-implementing any parser's own structural rules (required fields, closed enums, etc.):
  those stay with the parser that owns them; this spec only covers how a document's kind is
  resolved and how a failure from any of them is reported uniformly
- The meaning of the pod manifest keys beyond the closed key set (see pod-blueprints.spec.md)

## Requirements

### The envelope

1. `KINDS` **MUST** be the closed tuple `("role", "pipeline", "policy", "pod", "provider",
   "exporter", "channel", "mcp-server")`, in that order. An `mcp-server` document is `name`,
   `command`, `args`, `env`, `timeout`, `access` (`read`|`write`, the server's declared kind;
   the key is not `kind` because `kind:` is the envelope) and `tools`; any other key (an
   `isolate:` key, for instance) is an unknown-key error, because every stdio server starts in
   the turn's jail. It lives under a recipe's `mcp-servers/`, which `discover_config_paths`
   lists after `policies/`.
2. A document's `kind:` key, when present, **MUST** be one of `KINDS`; any other value **MUST**
   raise `ConfigDocError` naming every value in `KINDS` and, when one is a close enough match,
   a suggestion.
3. `load_document` **MUST NOT** strip the `kind` (or `name`) key from the returned
   `Document.doc` for `pipeline`, `policy`, `pod`, `provider`, `exporter`, `channel` and
   `mcp-server`: the parser it dispatches to receives the document exactly as parsed. For
   `role`, `Document.doc` is the canonical role mapping the role file loader produces (a short
   form normalized, `kind` removed), the same mapping `docket pod update` validates.
4. `load_document(path)` **MUST** accept JSON as well as YAML (JSON is a YAML subset). An empty
   file **MUST** parse as `{}`, not an error. A file whose top level is not a mapping **MUST**
   raise `ConfigDocError`. A file that cannot be read, or a YAML syntax error, **MUST** raise
   `ConfigDocError` naming the file.

### Dispatch

1. `load_document` **MUST** dispatch each resolved kind to the parser that already owns it,
   and to no other:
   - `role` -> the role file loader (which normalizes the short form, reading the paired
     instructions file) followed by `validate_archetype_dict(name, doc)` (the structure check and
     a dry-run render of both templates); an `ArchetypeError` or a non-empty error list is mapped
     to `ConfigDocError(path, str(exc))`
   - `pipeline` -> `load_pipeline(text)` (the raw file text, not the parsed dict: it does its
     own parse)
   - `policy` -> `validate_policy(path)` (the file path: this parser reads the file itself, JSON
     or YAML, short or canonical form)
   - `pod` -> validated against the pod manifest key set (see "The pod manifest key set"), not
     a full apply plan (which additionally needs a live pod name and registry this stand-alone
     validation path does not have)
   - `provider` -> `load_provider_document(path)`; a raised `ProviderError` is mapped to
     `ConfigDocError(path, str(exc))`. `provider` has no short-form model.
   - `exporter` -> `load_exporter_document(path)`; a raised `ExporterError` is mapped the same
     way. `exporter`'s canonical model (`ExporterSpec`) doubles as its schema-generation model
     (see "Published schemas"), but is never treated as short form for error refinement.
   - `channel` -> `load_channel_document(path)`; a raised `ChannelError` is mapped the same
     way. `channel`'s canonical model (`ChannelSpec`) doubles as its schema-generation model,
     the same shape as `exporter`.
   - `mcp-server` -> `load_mcp_server_document(path)`; a raised `McpServerDocError` is mapped
     the same way. Its canonical model (`McpServerDocument`) doubles as its schema-generation
     model, the same shape as `exporter`.
2. A parser's own exception or non-empty error string **MUST** be surfaced as a
   `ConfigDocError` naming the file and the parser's own message; this spec does not change what
   any of the eight parsers accepts or rejects.
3. Applying a directory (its `pod.yaml` manifest and each role file), `docket pod update
   <file>`, `docket pod validate`, `docket pod plan --pipeline` and the pipeline file a `docket
   run` is given **MUST** all read the stand-alone file through `load_document` (through
   `validate_path` for the two `pod` commands that validate) rather than their own direct parse
   call: one parse path for every command that reads a stand-alone configuration file.
   `docket init` validates a repository's `.docket/` directory with `validate_directory` before
   it provisions anything.

### Files without `kind:`

1. A canonical-form document with no top-level `kind:` key **MUST** still load. `load_document`
   **MUST** resolve its kind first from location (a file directly under a `roles/`, `policies/`,
   `mcp-servers/` or `pipelines/` directory, or named `pipeline.yaml`/`pipeline.yml` or
   `pod.yaml`/`pod.yml`) and only then from the caller's own `kind=` argument, when location
   does not resolve one. The resulting `Document.deprecated` **MUST** be `True`. For a canonical
   role file, `Document.doc` **MUST** equal the mapping that parsing the file as YAML yields. A
   canonical document that fails its kind's parser **MUST** report that parser's own error.
2. Neither location nor a caller-stated kind resolving one **MUST** raise `ConfigDocError`
   (field `kind`) naming every value in `KINDS`: an unresolvable file is treated the same as an
   unknown-kind one.
3. `docket pod validate` **MUST** print one advisory per file it loads this way, on stdout
   before that file's success line: `<file> has no 'kind:'; add 'kind: <k>'`, naming the kind it
   resolved (plain output marks it with `!`). The advisory is informational only: the file is
   still reported valid and the exit status is unaffected.
4. A short-form document (one `_is_short_form` recognises: a role carrying `cannot`, `verdict`,
   `verify`, `approval`, `instructions` or `model`; a policy carrying `appliesTo`, `on`, `when`
   or `then`; every pod manifest) with no `kind:` key **MUST** raise `ConfigDocError` (field
   `kind`) naming every value in `KINDS`, before its kind's parser runs. A missing `kind:` is
   never reported as a failure of the short-form model.

### `ConfigDocError`

1. `ConfigDocError` **MUST** be a `ValueError` subclass carrying `path`, `line` (`0` when
   unknown), `field` (`""` when not applicable), `message`, `valid` (a tuple, `()` when not a
   closed-vocabulary failure), and `suggestion` (`""` when none).
2. Its `str()` **MUST** render `<path>:<line> <field>: <message>` (without the `<field>:` part
   when `field` is empty) and, only when `valid` is non-empty, append ` (valid: <a>, <b>, <c>`
   followed by `; did you mean "<suggestion>"?` only when a suggestion exists, then a closing
   `)`.
3. When the failing field is a top-level YAML key (an unknown `kind`), `line` **MUST** be that
   key's own line number in the source file, not the file's first line; `0` when the line cannot
   be determined (PyYAML missing, or the key not found as a plain top-level mapping key). Every
   other failure reports line `0`.

### `docket pod validate`

1. `docket pod validate [dir|file]` with no argument **MUST** validate the repository's
   configuration directory when it exists: `.docket/` in the current directory, or that pod's
   `.docket/teams/<pod>/` when the pod is inferred from the current directory and the
   repository keeps one; otherwise the current directory. A file argument **MUST** validate
   that one file only.
2. Given a directory, it **MUST** validate every `*.yaml`/`*.yml`/`*.json` file directly under
   `roles/`, `policies/` and `mcp-servers/`, every `*.yaml`/`*.yml` under `pipelines/` (a
   pipeline by location), plus a `pipeline.yaml`/`pipeline.yml` and a `pod.yaml`/`pod.yml`
   directly under the directory, when present, in that order. `discover_config_paths` does not
   look for a provider, exporter or channel document by location; `docket pod validate <file>`
   naming one directly still loads it (`kind: provider`/`exporter`/`channel` is enough).
3. It **MUST** print one line per file: `ok <file> (<kind> <name>)` on stdout for a file that
   loads, or the file's `ConfigDocError` on stderr (plain output prefixes it with `x`), with
   every invalid file printed before every valid file, and **MUST** exit `1` if any file was
   invalid, `0` otherwise. Given a directory it then prints a dimmed one-line summary of what
   the directory brings (roles, policies, members, pipeline, plugins, skills, settings).
4. It **MUST** be one validator for every kind: `validate_path(target, *, kind=None)` returns
   one `PathResult(path, document, error)` per file, invalid first, and is the only function
   `docket pod validate` and `docket pod plan --pipeline` call. A pipeline whose step `model`
   names a provider absent from the catalog **MUST** be invalid there, naming the step, exactly
   as a pipeline structure error is. `kind` is the fallback for a document with no `kind:` key
   and no location that names one (`pod plan --pipeline` passes `pipeline`).

### Published schemas

1. `RoleDocument`, `PipelineDocument`, `PolicyDocument` and `PodDocument` **MUST** be
   `pydantic.BaseModel` subclasses (`extra="forbid"`) describing exactly the short-form fields
   the role, pipeline and policy normalizers (and the pod manifest) accept, plus `kind`/`name`.
   They are used for two things only, schema generation and the error refinement in
   Requirement 3 below, and are never a second loader; the normalizers remain the only place a
   document is actually parsed. `ExporterSpec`, `ChannelSpec` and `McpServerDocument` are
   registered for schema generation alongside them, but none is a short-form model in this
   sense: each is its own kind's only, canonical, parsed shape, so none is ever subject to
   Requirement 3's short-form ambiguity check.
2. The schema generator script **MUST** render `docs/contracts/config-v1/
   {role,pipeline,policy,pod,exporter,channel,mcp-server}.schema.json` from each model's
   `model_json_schema()`, with a `$schema`, `$id`
   (`https://docket.dev/schemas/config-v1/<kind>.schema.json`) and `title`, and write a
   byte-identical copy of each to the schemas directory shipped inside the installed package.
   `--check` **MUST** exit `1` when any of the fourteen files is stale.
3. When a short-form document fails its kind's real parser (the role loader, `load_pipeline`,
   `validate_policy`, the pod manifest key check), `load_document` **MUST** attempt
   `model_validate` against that kind's model before raising; on a `pydantic.ValidationError`,
   the raised `ConfigDocError`'s `field` and, for a closed-vocabulary field, `valid` **MUST**
   come from the model's own error instead of the parser's plain message. A document that does
   not unambiguously look like the short form (a canonical document sharing the same
   `kind:`/`name:` envelope) **MUST NOT** be checked against the model: its `extra="forbid"`
   would otherwise reject every canonical-only field (`modelClass`, `hook`, ...) as unknown
   instead of surfacing the real error. A role looks short-form when it has any of `cannot`,
   `verdict`, `verify`, `approval`, `instructions`, `model`; a policy when it has any of
   `appliesTo`, `on`, `when`, `then`; a pipeline when it declares `kind`; a pod manifest
   always; `exporter`, `channel` and `mcp-server` never.
4. These schemas are a generated, pinned artifact for external editors and validators, not a
   second validation path: `docket pod validate`/`load_document` **MUST** continue to dispatch to
   each kind's own parser as the sole authority for whether a document is valid.

### Short-form export

1. Every role, policy, or pod-manifest YAML file `docket pod export` writes **MUST** start with
   a `# yaml-language-server: $schema=<relative path>` comment line resolving to that kind's
   schema, copied into the export's own `<directory>/.schemas/` (the role, pipeline, policy and
   pod schemas). A copied bound pipeline file, a copied named pipeline and a written
   `mcp-servers/<name>.yaml` carry no such header: pipelines are written verbatim (see
   pod-blueprints.spec.md, "Pod manifests: export"), never regenerated.
2. `discover_config_paths` and the apply of a directory **MUST NOT** look under `.schemas/`: it
   holds reference schema copies, never a configuration document to load.

## Interface Contracts

### Python API

```text
KINDS: tuple[str, ...]
    # ("role", "pipeline", "policy", "pod", "provider", "exporter", "channel", "mcp-server")

Document                             # frozen dataclass
    kind: str
    name: str            # the document's `name`, else the file stem
    path: Path
    doc: dict[str, Any]
    deprecated: bool     # True when the file had no `kind:` key

ConfigDocError(ValueError)
    path, line, field, message, valid, suggestion

PathResult                           # frozen dataclass
    path: Path
    document: Document | None
    error: ConfigDocError | None

load_document(path, *, kind: str | None = None) -> Document
discover_config_paths(directory: Path) -> list[Path]
validate_directory(directory) -> list[ConfigDocError]
validate_path(target, *, kind: str | None = None) -> list[PathResult]   # invalid first

RoleDocument | PipelineDocument | PolicyDocument | PodDocument  # pydantic
    # models: the short-form schema per kind, source of `docs/contracts/config-v1/
    # <kind>.schema.json` and of a short-form document's refined `ConfigDocError`

ExporterSpec        # pydantic; exporter's own canonical model, also its schema source
ChannelSpec         # pydantic; channel's own canonical model, also its schema source
McpServerDocument   # pydantic; mcp-server's own canonical model, also its schema source

render(kind: str) -> str      # schema generator: one schema.json's rendered content
main(argv=None) -> int        # schema generator: writes, or --check exits 1 if stale
                              # (its kinds are the seven above; `provider` has no schema)
```

### CLI Command Signature

```text
docket pod validate [dir|file]
```

### The pod manifest key set

`pod.yaml` accepts exactly these top-level keys; any other is an unknown-key error. Their
meaning is owned by pod-blueprints.spec.md; the schema (`PodDocument`) lists the same nine.

| Key | Meaning |
| --- | --- |
| `kind` | always `pod` for a pod manifest |
| `name` | the pod's own name |
| `members` | the roles of the team |
| `settings` | pod settings applied with the manifest |
| `pipeline` | the bound pipeline |
| `description` | optional prose for a listing; read-only, never applied to the pod |
| `exporters` | a list of exporter catalog names this pod's recipe declares; reported by apply and `docket pod recipes`, never applied (never activates an exporter) |
| `prepare` | the install command of a task's worktree |
| `protects` | path globs a task may not change without a person |

### Return Codes

- `0`: every file validated is valid
- `1`: at least one file is invalid (`ConfigDocError`), or the target does not exist

## Examples

Output below is the piped (plain) form.

### An unknown kind

```bash
$ docket pod validate policies/broken.yaml
x policies/broken.yaml:1 kind: unknown kind 'banana' (valid: role, pipeline, policy, pod, provider, exporter, channel, mcp-server)
```

### A directory with one good role and one invalid file

```bash
$ docket pod validate .docket
x .docket/roles/bad.yaml:1 kind: unknown kind 'banana' (valid: role, pipeline, policy, pod, provider, exporter, channel, mcp-server)
ok .docket/roles/good.yaml (role security-vetter)
  roles 2 · policies 0 · members 0 · pipeline none · plugins 0 · skills 0 · settings 0
```

### A role file with no `kind:` still loads

```bash
$ docket pod validate .docket/roles/legacy.yaml
! .docket/roles/legacy.yaml has no 'kind:'; add 'kind: role'
ok .docket/roles/legacy.yaml (role legacy)
```

## Validation

### Pre-conditions

- The target path (file or directory) **MUST** exist; a missing target is an error (exit 1),
  not an empty success.

### Post-conditions

- Calling `load_document` twice on the same unmodified file **MUST** return an equal `Document`
  each time (pure, no side effect on disk or in `DOCKET_HOME`).

### Invariants

- For every kind but `role`, `Document.doc` carries whatever top-level keys the source file had,
  including `kind` and `name` when present: `load_document` never mutates the parsed mapping.
- A `Document` returned by `load_document` never has `kind` outside `KINDS`.

## Implementation

- `src/docket/core/config_docs.py`: `KINDS`, `Document`, `ConfigDocError`, `PathResult`,
  `load_document`, `discover_config_paths`, `validate_directory`, `validate_path`, the four
  short-form models, the kind-to-model table, the short-form check and the location-to-kind
  table
- `src/docket/core/pod_apply.py`: the pod manifest key set (`_MANIFEST_KEYS`), `export_pod` and
  its schema headers and `.schemas/` copy, `plan_apply`, `repo_config_dir`
- `src/docket/core/archetypes.py`: `load_role_file`, `from_wire`
- `src/docket/core/pipeline.py`: `load_pipeline`, `normalize_pipeline`
- `src/docket/core/policy.py`: `validate_policy`, `read_policy`, `normalize_policy`
- `src/docket/core/provider.py`: `load_provider_document`, `ProviderError`
- `src/docket/core/exporter.py`: `load_exporter_document`, `ExporterSpec`, `ExporterError`
- `src/docket/core/channel.py`: `load_channel_document`, `ChannelSpec`, `ChannelError`
- `src/docket/core/mcp_tools.py`: `load_mcp_server_document`, `McpServerDocument`,
  `McpServerDocError`
- `src/docket/cli/_pod_config.py`: `docket pod validate`, `pod update`, `pod plan --pipeline`
- `src/docket/cli/_run.py`, `src/docket/cli/_agents.py`: the `docket run` pipeline file read
  and the `docket init` directory validation
- `scripts/gen_config_schemas.py`: the schema generator; `docs/contracts/config-v1/` and
  `src/docket/templates/schemas/` hold the two copies of each schema
