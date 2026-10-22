# Configuration Document Format Specification

**Version**: 1.11.0
**Status**: Implemented
**Last Updated**: 2026-10-18

## Purpose

This specification defines the **configuration document envelope**: the `kind:`/`name:` pair
every docket-native configuration file (a role archetype, a pipeline, a policy, or a pod
manifest) starts with, and the single entry point, `core/config_docs.py::load_document`, that
reads one such file, resolves its kind, and dispatches to the parser that already owns that
kind's real structure. Before this spec, a role, a pipeline, a policy and the Phase 27 pod
manifest were told apart only by which directory a file lived in or which command read it —
each command that read one called a different parser directly, and nothing said what a given file *was*
short of trying to parse it as one specific thing and seeing whether that failed. `docket
pod validate` is the one command that checks every kind of file in a directory in one pass.

## Scope

This specification covers:

- The envelope: every configuration document starts with `kind:` (one of `role`, `pipeline`,
  `policy`, `pod`, `provider`, `exporter`, `channel`) and `name:`; `load_document(path)` reads
  the file, resolves its kind, and dispatches to the existing parser for that kind
- The deprecation path for a file with no `kind:` key: it still loads, through the same
  location-based (or caller-stated) inference the pre-v1 world used implicitly, and is marked
  `deprecated=True`
- `ConfigDocError`: the one error shape every kind's validation failure is reported through,
  and its `file:line field: message (valid: ...; did you mean "...")` rendering
- `docket pod validate [dir|file]`: validates every document under a directory (or one file) and
  the pod manifest, printing one line per file, invalid files first, exit 1 on the first
  invalid file found
- The seven parsers this dispatches to unchanged: `core.archetypes.from_wire`,
  `core.pipeline.load_pipeline`, `core.policy.validate_policy`, `core.pod_apply`'s pod
  manifest key set, (ADR 0011) `core.provider.load_provider_document` for `provider`,
  (ADR 0014) `core.exporter.load_exporter_document` for `exporter`, and (ADR 0016)
  `core.channel.load_channel_document` for `channel` — `provider` has no published schema
  (canonical form only); `exporter` and `channel` each have a published schema generated
  directly from their own canonical model, since neither has a separate short form to refine
  against (see "Published schemas" below)
- The published `docs/contracts/config-v1/{role,pipeline,policy,pod,exporter,channel}.
  schema.json` JSON Schemas, generated from the same short-form Pydantic models that refine a
  short-form document's `ConfigDocError`, and the `# yaml-language-server:`/`.schemas/`
  convention `core.pod_apply.export_pod` writes its short-form output with (see "Published
  schemas", "Short-form export")

This specification does NOT cover:

- Short forms / sugar for any of the four kinds (role, pipeline, policy, pod short-hand
  normalizers) — a separate, later card per kind; this spec only describes the short-form
  *models* used for schema generation and error refinement, not the normalizers themselves
- Wiring JSON Schema validation into `docket pod validate`'s live path — the published schemas are
  a generated, pinned artifact for external editors/validators, never consulted by
  `load_document` itself
- A published JSON Schema or short-form sugar for `provider` — it has neither (see above)
- Removing or warning-then-erroring the pre-v1 (kind-less) format outright — the deprecation
  note is informational only; nothing currently refuses to load a kind-less file
- Re-implementing any of the four existing parsers' own structural rules (required fields,
  closed enums, etc.) — those stay exactly where they already live; this spec only covers how a
  document's kind is resolved and how a failure from any of them is reported uniformly

## Requirements

### The envelope

1. `core.config_docs.KINDS` **MUST** be the closed tuple `("role", "pipeline", "policy",
   "pod", "provider", "exporter", "channel", "mcp-server")`, in that order — the four kinds Phase 27/pre-27
   already have real parsers for, plus `provider` (ADR 0011,
   `core.provider.load_provider_document`), `exporter` (ADR 0014,
   `core.exporter.load_exporter_document`) and `channel` (ADR 0016,
   `core.channel.load_channel_document`), plus `mcp-server` (ADR 0019 §5,
   `core.mcp_tools.load_mcp_server_document`). An `mcp-server` document is `name`, `command`,
   `args`, `env`, `timeout`, `access` (`read`|`write`, the server's declared kind; the key is not
   `kind` because `kind:` is the envelope) and `tools` (an `isolate:` key is an unknown-key error: every stdio server starts in the turn's jail); it lives under a recipe's `mcp-servers/`,
   which `discover_config_paths` lists after `policies/`.
2. A document's `kind:` key, when present, **MUST** be one of `KINDS`; any other value **MUST**
   raise `ConfigDocError` naming every value in `KINDS` and, when one is close enough
   (`difflib.get_close_matches`), a suggestion.
3. `load_document` **MUST NOT** strip the `kind` (or `name`) key from the returned `Document.doc`
   — the parser it dispatches to receives the document exactly as parsed. A parser that
   forbids extra top-level keys (for example `core.pipeline.PipelineSpec`'s `extra="forbid"`)
   rejecting a `kind`/`name` key it does not yet declare is a known, accepted gap this card
   does not close — that is the short-form/normalizer cards' work, not this envelope's.
4. `load_document(path)` **MUST** accept JSON as well as YAML (JSON is a valid YAML subset;
   the same guarded `import yaml` pattern `core/pipeline.py::_load_yaml_text` and
   `core/archetypes.py::parse_yaml_file` already use). An empty file **MUST** parse as `{}`,
   not an error. A file whose top level is not a mapping **MUST** raise `ConfigDocError`.

### Dispatch

1. `load_document` **MUST** dispatch each resolved kind to the parser that already owns it,
   and to no other:
   - `role` → `core.archetypes.from_wire(name, doc)`
   - `pipeline` → `core.pipeline.load_pipeline(text)` (the raw file text, not the parsed dict —
     `load_pipeline` does its own parse)
   - `policy` → `core.policy.validate_policy(path)` (the file path — this parser reads the file
     itself; on this branch it reads JSON, matching `core/policy.py`'s current format)
   - `pod` → validated against `core.pod_apply`'s own manifest key set (`_MANIFEST_KEYS`, which
     this spec's Interface Contracts extend with `kind` and `name`), not a full `plan_apply`
     (which additionally needs a live pod name and registry this stand-alone validation path
     does not have)
   - `provider` → `core.provider.load_provider_document(path)`; a raised `ProviderError` is
     mapped to `ConfigDocError(path, str(exc))`, the same refinement the `role` arm applies to
     an `ArchetypeError`. `provider` has no short-form model (canonical form only).
   - `exporter` → `core.exporter.load_exporter_document(path)`; a raised `ExporterError` is
     mapped to `ConfigDocError(path, str(exc))` the same way. `exporter`'s canonical model
     (`ExporterSpec`) doubles as its schema-generation model (see "Published schemas" below),
     but it is still not treated as short form for refinement purposes — `_is_short_form`
     never matches `exporter`, so a canonical document's own extra fields are never rejected by
     a would-be short-form check the way Requirement 3 of "Published schemas" warns against.
   - `channel` → `core.channel.load_channel_document(path)`; a raised `ChannelError` is mapped
     to `ConfigDocError(path, str(exc))` the same way. `channel`'s canonical model
     (`ChannelSpec`) doubles as its schema-generation model, the same shape as `exporter`;
     `_is_short_form` never matches `channel` either.
2. A parser's own exception or non-empty error string **MUST** be surfaced as a
   `ConfigDocError` naming the file and the parser's own message; this spec does not change what
   any of the six parsers accepts or rejects.
3. `core/pod_apply.py::plan_apply`'s manifest read and `_plan_roles`'s per-file role read,
   `docket pod update <file>`, `docket pod validate` and `docket pod plan --pipeline` **MUST** all
   call `load_document` (through `validate_path` for the last two) rather than their own prior
   direct parse call — one parse path for every command that reads a stand-alone configuration
   file.

### Files without `kind:` (deprecation)

1. A document with no top-level `kind:` key **MUST** still load. `load_document` **MUST**
   resolve its kind first from location — a file directly under a `roles/` or `policies/`
   directory, or named `pipeline.yaml`/`pipeline.yml` or `pod.yaml`/`pod.yml` — and only then
   from the caller's own `kind=` argument to `load_document`, when location does not resolve
   one. The resulting `Document.deprecated` **MUST** be `True`, and `Document.doc` **MUST** be
   byte-identical (same dict) to what the kind's own pre-envelope standalone parser
   (`core.archetypes.parse_yaml_file` for a role) would have returned for the same text.
2. Neither location nor a caller-stated kind resolving one **MUST** raise `ConfigDocError`
   naming every value in `KINDS` — an unresolvable file is treated the same as an unknown-kind
   one.
3. `docket pod validate` **MUST** print one note per file it loads through this deprecation path:
   `note: <file> has no 'kind:' -- add 'kind: <k>' (files without it stop loading one release
   after v1)`, naming the kind it resolved. This is advisory only — the file still loads and is
   still reported `ok`.

### `ConfigDocError`

1. `ConfigDocError` **MUST** be a `ValueError` subclass carrying `path`, `line` (`0` when
   unknown), `field` (`""` when not applicable), `message`, `valid` (a tuple, `()` when not a
   closed-vocabulary failure), and `suggestion` (`""` when none).
2. Its `str()` **MUST** render `<path>:<line> <field>: <message>` and, only when `valid` is
   non-empty, append ` (valid: <a>, <b>, <c>` followed by `; did you mean "<suggestion>"?` only
   when a suggestion exists, then a closing `)`.
3. When the failing field is a top-level YAML key (for example `kind`), `line` **MUST** be that
   key's own line number in the source file (via PyYAML's `yaml.compose` node marks), not the
   file's first line or the parser's own (unrelated) line convention; `0` when the line cannot
   be determined (PyYAML missing, or the key not found as a plain top-level mapping key).

### `docket pod validate`

1. `docket pod validate [dir|file]` **MUST** default to `<cwd>/.docket` when that directory exists,
   else the current directory, when no argument is given; a file argument **MUST** validate
   that one file only.
2. Given a directory, it **MUST** validate every `*.yaml`/`*.yml`/`*.json` file directly under
   `roles/`, `policies/` and `mcp-servers/`, every `*.yaml`/`*.yml` under `pipelines/` (a
   pipeline by location), plus a `pipeline.yaml`/`pipeline.yml` and a `pod.yaml`/`pod.yml`
   directly under the directory, when present. `discover_config_paths` does not look for a
   provider, exporter or channel document by location — `docket pod validate <file>` naming one
   directly still loads it (`kind: provider`/`exporter`/`channel` is enough; `load_document`
   needs no directory convention to resolve any of the three).
3. It **MUST** print one line per file — `ok <file> (<kind> <name>)` on stdout for a file that
   loads, or its `ConfigDocError` on stderr — with every invalid file printed before every valid file, and **MUST**
   exit `1` if any file was invalid, `0` otherwise.
4. It **MUST** be one validator for every kind: `core.config_docs.validate_path(target, *,
   kind=None)` returns one `PathResult(path, document, error)` per file, invalid first, and is
   the only function `docket pod validate` and `docket pod plan --pipeline` call. A pipeline
   whose step `model` names a provider absent from the catalog **MUST** be invalid there, naming
   the step, exactly as a pipeline structure error is. `kind` is the fallback for a document
   with no `kind:` key and no location that names one (`pod plan --pipeline` passes `pipeline`).

### Published schemas

1. `core.config_docs.RoleDocument`, `PipelineDocument`, `PolicyDocument`, `PodDocument`
   **MUST** be `pydantic.BaseModel` subclasses (`extra="forbid"`) describing exactly the
   short-form fields `core.archetypes.normalize_role`/`core.pipeline.normalize_pipeline`/
   `core.policy.normalize_policy` accept, plus `kind`/`name`. They are used for two things
   only — schema generation and the error refinement in Requirement 3 below — and are never a
   second loader; the normalizers remain the only place a document is actually parsed.
   `core.exporter.ExporterSpec` and `core.channel.ChannelSpec` are registered in
   `_MODEL_FOR_KIND` alongside them for schema generation, but neither is a short-form model
   in this sense — each is its own kind's only, canonical, parsed shape (ADR 0014, ADR 0016),
   so neither is ever subject to Requirement 3's short-form ambiguity check.
2. `scripts/gen_config_schemas.py` **MUST** render `docs/contracts/config-v1/
   {role,pipeline,policy,pod,exporter,channel}.schema.json` from each model's
   `model_json_schema()`, with a `$schema`, `$id`
   (`https://docket.dev/schemas/config-v1/<kind>.schema.json`) and `title`, and write a
   byte-identical copy of each to `src/docket/templates/schemas/`, shipped inside the
   installed package. `--check` **MUST** exit `1` when any of the twelve files is stale.
3. When a short-form document fails its kind's real parser (`from_wire`, `load_pipeline`,
   `validate_policy`, the pod manifest key check), `load_document` **MUST** attempt
   `model_validate` against that kind's model before raising; on a `pydantic.ValidationError`,
   the raised `ConfigDocError`'s `field` and, for a closed-vocabulary field, `valid` **MUST**
   come from the model's own error instead of the parser's plain message. A document that does
   not unambiguously look like the short form (a canonical document sharing the same
   `kind:`/`name:` envelope) **MUST NOT** be checked against the model — its `extra="forbid"`
   would otherwise reject every canonical-only field (`modelClass`, `hook`, ...) as unknown
   instead of surfacing the real error.
4. These schemas are a generated, pinned artifact for external editors and validators, not a
   second validation path: `docket pod validate`/`load_document` **MUST** continue to dispatch to
   each kind's own parser as the sole authority for whether a document is valid.

### Short-form export

1. Every role, policy, or pod-manifest YAML file `core.pod_apply.export_pod` writes **MUST**
   start with a `# yaml-language-server: $schema=<relative path>` comment line resolving to
   that kind's schema, copied into the export's own `<directory>/.schemas/` alongside the four
   files it writes. A copied bound pipeline file is exempt — it is written verbatim (see
   pod-blueprints.spec.md, "Pod manifests: export"), never regenerated, so it carries no header
   this spec would need to add.
2. `discover_config_paths` and `plan_apply` **MUST NOT** look under `.schemas/` — it holds
   reference schema copies, never a configuration document to load.

## Interface Contracts

### Python API

```text
core.config_docs.KINDS: tuple[str, ...]
    # ("role", "pipeline", "policy", "pod", "provider", "exporter", "channel")

core.config_docs.Document                             # frozen dataclass
    kind: str
    name: str
    path: Path
    doc: dict[str, Any]
    deprecated: bool

core.config_docs.ConfigDocError(ValueError)
    path, line, field, message, valid, suggestion

core.config_docs.load_document(path, *, kind: str | None = None) -> Document
core.config_docs.discover_config_paths(directory: Path) -> list[Path]
core.config_docs.validate_directory(directory) -> list[ConfigDocError]

core.config_docs.RoleDocument | PipelineDocument | PolicyDocument | PodDocument  # pydantic
    # models: the short-form schema per kind, source of `docs/contracts/config-v1/
    # <kind>.schema.json` and of a short-form document's refined `ConfigDocError`

core.exporter.ExporterSpec   # pydantic; exporter's own canonical model, also its schema source
core.channel.ChannelSpec     # pydantic; channel's own canonical model, also its schema source

scripts.gen_config_schemas.render(kind: str) -> str      # one schema.json's rendered content
scripts.gen_config_schemas.main(argv=None) -> int        # writes, or --check exits 1 if stale
```

### CLI Command Signature

```text
docket pod validate [dir|file]
```

### The pod manifest key set (extends `core.pod_apply._MANIFEST_KEYS`)

| Key | Meaning |
| --- | --- |
| `members` | pre-existing (Phase 27) |
| `settings` | pre-existing (Phase 27) |
| `pipeline` | pre-existing (Phase 27) |
| `kind` | this spec — always `pod` for a pod manifest |
| `name` | this spec — the pod's own name |
| `description` | P31-1 (ADR 0013 §1 rule 2) — optional prose for a listing; read-only, never applied to the pod |
| `exporters` | P32-8 (ADR 0014 rule 7) — a list of `core.exporter.load_catalog()` names this pod's recipe declares; reported by `apply`/`recipes show`, never applied (never activates an exporter) |

### Return Codes

- `0`: every file validated is valid
- `1`: at least one file is invalid (`ConfigDocError`), or the target does not exist

## Examples

### An unknown kind

```bash
$ docket pod validate policies/broken.yaml
policies/broken.yaml:1 kind: unknown kind 'banana' (valid: role, pipeline, policy, pod, provider, exporter, channel)
```

### A directory with one good role and one invalid file

```bash
$ docket pod validate .docket
roles/bad.yaml:1 kind: unknown kind 'banana' (valid: role, pipeline, policy, pod, provider, exporter, channel)
ok roles/good.yaml (role security-vetter)
```

### A role file with no `kind:` still loads

```bash
$ docket pod validate roles/legacy.yaml
note: roles/legacy.yaml has no 'kind:' -- add 'kind: role' (files without it stop loading one release after v1)
ok roles/legacy.yaml (role legacy)
```

## Validation

### Pre-conditions

- The target path (file or directory) **MUST** exist; a missing target is an error, not an
  empty success.

### Post-conditions

- Calling `load_document` twice on the same unmodified file **MUST** return an equal `Document`
  each time (pure, no side effect on disk or in `~/.docket`).

### Invariants

- `Document.doc` always carries whatever top-level keys the source file had, including `kind`
  and `name` when present — `load_document` never mutates the parsed mapping.
- A `Document` returned by `load_document` never has `kind` outside `KINDS`.
