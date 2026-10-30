# Configuration Document Format Specification

**Version**: 2.7.0
**Status**: Implemented
**Last Updated**: 2026-10-30

## Purpose

This specification defines the **configuration document envelope**: the `kind:`/`name:` pair
every docket-native configuration file starts with, and the single entry point,
`load_document`, that reads one such file, resolves its kind, and dispatches to the parser that
owns that kind's real structure. `docket pod validate` is the one command that checks every
kind of file in a directory in one pass.

## Scope

This specification covers:

- The envelope: every configuration document starts with `kind:` (one of `role`, `pipeline`,
  `policy`, `pod`, `provider`, `exporter`, `channel`, `mcp-server`, `autonomy`, `prompt`,
  `routine`) and `name:`; `load_document(path)` reads the file, resolves its kind, and dispatches to the existing
  parser for that kind
- One authored form per kind (`role`, `pipeline`, `policy`, `pod`): the short form. A file with a
  canonical key (a role's `modelClass`, a policy's `applies_to`, a pipeline step's `id:`) is
  refused naming the short-form key to write; the canonical shape is the in-memory model and the
  persisted JSON, never an authored file
- Files with no `kind:` key: such a file still loads when its location (or the caller) names a
  kind, with no advisory; when neither does, it is refused
- `ConfigDocError`: the one error shape every kind's validation failure is reported through,
  and its `<file>:<line> <field>: <message> (valid: ...; did you mean "...")` rendering
- `docket pod validate [dir|file]`: validates every document under a directory (or one file),
  printing one line per file, invalid files first, exit 1 when any file is invalid
- The `prompt` kind: a Markdown file (YAML front matter, then the body) read by
  `teams/prompts.py`, the one place a prompt is parsed
- The `routine` kind: a pod's standing order to enqueue a task on a schedule, parsed by its own
  model, `RoutineDocument` (see "The `routine` kind")
- The ten parsers this dispatches to unchanged: `from_wire` (with the role file loader) for
  `role`, `load_pipeline` for `pipeline`, `validate_policy` for `policy`, the pod manifest key
  set for `pod`, `load_provider_document` for `provider`, `load_exporter_document` for
  `exporter`, `load_channel_document` for `channel` and `load_mcp_server_document` for
  `mcp-server`, `load_autonomy_document` for `autonomy`, `load_prompt_file` for `prompt`. `provider` and `autonomy` have no published
  schema (canonical form only); `exporter`,
  `channel`, `mcp-server` and `prompt` each have a published schema generated directly from
  their own canonical model, since none has a separate short form to refine against
- The published `docs/contracts/config-v1/{role,pipeline,policy,pod,exporter,channel,mcp-server,
  prompt,routine}.schema.json` JSON Schemas, generated from the short-form models that also refine a short-form
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
- Refusing a kind-less file whose location or caller names its kind: nothing does
- Re-implementing any parser's own structural rules (required fields, closed enums, etc.):
  those stay with the parser that owns them; this spec only covers how a document's kind is
  resolved and how a failure from any of them is reported uniformly
- The meaning of the pod manifest keys beyond the closed key set (see pod-blueprints.spec.md)

## Requirements

### The envelope

1. `KINDS` **MUST** be the closed tuple `("role", "pipeline", "policy", "pod", "provider",
   "exporter", "channel", "mcp-server", "autonomy", "prompt", "routine")`, in that order. An `autonomy` document is
   `name`, an optional `description` and `rows`: a mapping from each escalation kind (`approval`,
   `consult`, `input`, `gate`, `check_changed`, `wait`) to a mapping from each level (`L3`, `L4`, `L5`) to
   `{policy, onExpiry}`, where `policy` is `person`, `recommendation`, `deny`, `fail` or `machine` and
   `onExpiry` is `deny` or `block`. Every kind and every level **MUST** be present (eighteen cells)
   and any other key is an unknown-key error. The built-in document is
   `templates/autonomy/default.yaml`; it is the table of operator-loop.spec.md "Escalations"
   item 12 and the only one the runtime reads. An `mcp-server` document is `name`,
   `command`, `args`, `env`, `timeout`, `access` (`read`|`write`|`send`, the server's declared kind;
   the key is not `kind` because `kind:` is the envelope), `tools` and `lifetime` (`call`|`hop`); any other key (an
   `isolate:` key, for instance) is an unknown-key error, because every stdio server starts in
   the turn's jail. It lives under a recipe's `mcp-servers/`, which `discover_config_paths`
   lists after `policies/`. A `prompt` document is a Markdown file, not YAML (the `prompt`
   requirements below), and lives under a repository's `prompts/<layer>/`. A `routine` document
   lives under `routines/` (the `routine` kind below).
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
   - `autonomy` -> `load_autonomy_document(path)`; a raised `AutonomyError` is mapped the same
     way. It has no short-form model and no published schema.
   - `prompt` -> `load_prompt_file(path)`; a raised `PromptError` is mapped the same way,
     keeping its line and field. Any `.md` file is a `prompt` by its suffix (no other kind is
     Markdown), and a `.yaml`/`.json` file that declares `kind: prompt` is refused, naming
     the `kind` line.
2. A parser's own exception or non-empty error string **MUST** be surfaced as a
   `ConfigDocError` naming the file and the parser's own message; this spec does not change what
   any of the ten parsers accepts or rejects.
3. Applying a directory (its `pod.yaml` manifest and each role file), `docket pod update
   <file>`, `docket pod validate`, `docket pod plan --pipeline` and the pipeline file a `docket
   run` is given **MUST** all read the stand-alone file through `load_document` (through
   `validate_path` for the two `pod` commands that validate) rather than their own direct parse
   call: one parse path for every command that reads a stand-alone configuration file.
   `docket init` validates a repository's `.docket/` directory with `validate_directory` before
   it provisions anything.

### Files without `kind:`

1. A document with no top-level `kind:` key **MUST** still load. `load_document`
   **MUST** resolve its kind first from location (a file directly under a `roles/`, `policies/`,
   `mcp-servers/`, `pipelines/` or `routines/` directory, or named `pipeline.yaml`/`pipeline.yml` or
   `pod.yaml`/`pod.yml`) and only then from the caller's own `kind=` argument, when location
   does not resolve one. A document that fails its kind's parser **MUST** report that parser's own
   error, refined by the kind's model (requirement 3 of "Published schemas").
2. Neither location nor a caller-stated kind resolving one **MUST** raise `ConfigDocError`
   (field `kind`) naming every value in `KINDS`: an unresolvable file is treated the same as an
   unknown-kind one.
3. `docket pod validate` **MUST** report a document loaded this way exactly as it reports one that
   declares its kind: the success line only, no advisory.
4. A role or policy document carrying a canonical key (a role's `modelClass`, `deniedTools`,
   `gateContract`, `soulTemplate`, `agentsTemplate`; a policy's `id`, `applies_to`, `hook`,
   `action`, `match`) **MUST** raise `ConfigDocError` with the message
   `roles.canonical_key_refusal` / `policy.canonical_key_refusal` renders, before its kind's parser
   runs and without model refinement, so the message names the short-form key to write. A
   pipeline step written with an `id:` key is refused the same way by `load_pipeline`
   (`PipelineLoadResult.canonical`). The error is a `CanonicalFormError`
   (`kernel.errors.CanonicalFormRefused`): a command that applies or runs the file refuses it as
   written and exits 2 -- `docket pod update <file|dir>` and `docket init`, `docket run
   --pipeline`, `docket pod set pipeline` -- while `docket pod validate` reports it like any
   invalid file (exit 1, "`docket pod validate`").

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
   pipeline by location) and under `routines/` (a routine by location), every `*.md` file directly under `prompts/` or under one of its layer
   directories (`prompts/<layer>/*.md`, after the pipelines), plus a `pipeline.yaml`/`pipeline.yml` and a `pod.yaml`/`pod.yml`
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
5. Given a directory it **MUST** also check its references and its inputs: every role named
   in `pod.yaml`'s `members` with a major (`implementer@3`) **MUST** resolve to a role of that major
   among the directory's own roles or the pod's registry, and every `${name}` input a prompt
   declares **MUST** be one its layer's consumer supplies (`identity`: the template variables a
   role's identity text is rendered with; `task` and `hop`: none). Each failure is one line
   naming the file and the reference or input, and the exit code is `1`.

### Published schemas

1. `RoleDocument`, `PipelineDocument`, `PolicyDocument` and `PodDocument` **MUST** be
   `pydantic.BaseModel` subclasses (`extra="forbid"`) describing exactly the short-form fields
   the role, pipeline and policy normalizers (and the pod manifest) accept, plus `kind`/`name`.
   They are used for two things only, schema generation and the error refinement in
   Requirement 3 below, and are never a second loader; the normalizers remain the only place a
   document is actually parsed. `ExporterSpec`, `ChannelSpec` and `McpServerDocument` are
   registered for schema generation alongside them, as is `PromptDocument` (the `prompt` kind's
   front matter): none is a short-form model in this
   sense: each is its own kind's only, canonical, parsed shape, so none is ever subject to
   Requirement 3's short-form ambiguity check.
2. The schema generator script **MUST** render `docs/contracts/config-v1/
   {role,pipeline,policy,pod,exporter,channel,mcp-server,prompt,routine}.schema.json` from each model's
   `model_json_schema()`, with a `$schema`, `$id`
   (`https://docket.dev/schemas/config-v1/<kind>.schema.json`) and `title`, and write a
   byte-identical copy of each to the schemas directory shipped inside the installed package.
   `--check` **MUST** exit `1` when any of the eighteen files is stale.
3. When a document fails its kind's real parser (the role loader, `load_pipeline`,
   `validate_policy`, the pod manifest key check), `load_document` **MUST** attempt
   `model_validate` against that kind's model before raising; on a `pydantic.ValidationError`,
   the raised `ConfigDocError`'s `field` and, for a closed-vocabulary field, `valid` **MUST**
   come from the model's own error instead of the parser's plain message. There is no form to
   guess: every authored `role`, `pipeline`, `policy` and `pod` document is its short form; `exporter`,
   `channel`, `mcp-server` and `prompt` are never refined by a model. A `routine` is parsed by its
   model alone (`RoutineDocument`), so the `ConfigDocError` it raises already names the model's
   field.
4. These schemas are a generated, pinned artifact for external editors and validators, not a
   second validation path: `docket pod validate`/`load_document` **MUST** continue to dispatch to
   each kind's own parser as the sole authority for whether a document is valid.

### The `routine` kind

1. A routine **MUST** be a YAML or JSON document of `RoutineDocument` (`extra="forbid"`): `kind`
   (`routine`), `name` (`^[a-z0-9][a-z0-9._-]*$`), an optional `description`, `schedule` (a
   5-field cron expression or `@every <N><s|m|h>`; `HH:MM` and any other string are refused),
   `tz` (an IANA zone name known to the system, default `UTC`), `task`, `catchUp` (`skip`|`once`,
   default `skip`), `overlap` (`skip`|`queue`, default `skip`) and `enabled` (default `true`).
   `task` is `description` (required, not blank), `pipeline` (a task pipeline name), `variables`
   (a mapping of non-empty names to string values) and `priority` (`high`|`normal`|`low`, default
   `normal`); any other key is an unknown-key error.
2. `load_document` of a routine **MUST** return a `Document` of kind `routine`, and a failure
   **MUST** be a `ConfigDocError` whose `field` is the first failing model field (`schedule`,
   `tz`, `task.description`, ...). What a routine does at run time is pod-dispatch.spec.md
   "Routines".

### The `prompt` kind

1. A prompt **MUST** be a file of YAML front matter (between a first line `---` and the next line
   that is exactly `---`) followed by a Markdown body. The front matter's keys are closed
   (`PromptDocument`, `extra="forbid"`): `kind` (`prompt`), `name` (lowercase letters, digits and
   hyphens, starting with a letter), `version` (semver, `MAJOR.MINOR.PATCH`), `layer`
   (`identity`, `task` or `hop`), `for` (a role name), `modelClass` (`cheap`, `strong` or `any`;
   `any` when absent), `inputs` (a mapping from a variable name to its type: `string`, `text`,
   `int`, `bool` or `list`), `output` (a schema name, one of `OUTPUT_SCHEMAS`: `handoff/v1`;
   absent for a prompt that produces none), `tests` (a relative path beside the prompt, never
   absolute and never containing `..`) and an optional `description`. `kind`, `name`, `version`,
   `layer` and `for` are required. A file with no front matter, or whose front matter is not a
   mapping, is refused.
2. The body is the prompt's text. `text` **MUST** be the body with its trailing newlines removed,
   so a prompt file ends like any other text file and its text is the same bytes a Python literal
   held. Placeholders are `${name}`; `$$` is a literal dollar sign.
3. A placeholder naming a variable that is not a key of `inputs`, and a malformed placeholder,
   **MUST** be a load error whose message names the file and the file's line (front matter lines
   counted), such as `<file>:<line> undeclared variable ${x}`. A prompt with an unknown `output`
   is refused naming the `output` line. The parser **MUST NOT** accept a front matter key it does
   not know.
4. `load_document` of a prompt **MUST** return a `Document` of kind `prompt` whose `doc` is the
   front matter mapping. `docket pod validate` **MUST** report an invalid prompt like any other
   invalid file (exit 1, the file named, with its line).
5. The loader (`teams/prompts.py`) **MUST** return, for a prompt it resolves, a `LoadedPrompt`:
   `name`, `version`, `layer`, `scope`, `text` and `sha256`, the SHA-256 (hex) of `text` as UTF-8,
   before any substitution. A shipped prompt (`templates/prompts/<layer>/<name>.md`, found through
   `kernel/templates.py`, so an installed wheel finds it) has scope `shipped`; its file's `layer`
   **MUST** equal its directory. A role's own text (a pod overlay's `hopInstruction` or
   `soulTemplate`) that differs from the shipped prompt of the same name and layer **MUST** resolve
   to scope `pod`, with the role's version as its `MAJOR.0.0`; the same text as the shipped prompt
   resolves to the shipped one. A shipped prompt that does not parse is a defect that fails the
   test suite, never a silent fallback.
6. Substitution **MUST** be strict (`prompts.substitute`): a variable the caller does not supply
   raises `PromptError`, never a literal `${typo}`. `role_schema.render` is this function with its
   error mapped to `ArchetypeError`.
7. A prompt **MAY** exist once per `modelClass`. A variant is a file `<name>.<class>.md` (or
   `<name>.<class>@<version>.md`) whose front matter declares `modelClass: <class>`; the file name
   is a convention and the front matter decides. `resolve_prompt` takes the resolved model's class
   (`cheap`, `strong` or none) and, in each scope in order, **MUST** prefer a file declaring that
   class over a file declaring `any`, whatever their versions; a file declaring another class is
   never offered. With no class, only `any` files are offered, so a document that declares no
   `modelClass` resolves exactly as before. The class of a model is `cheap` for the `economy` rank
   anchor, `strong` for the `standard` and `premium` anchors and none for any other model
   (`model_selection.model_class_of`): a class is never guessed from a model id. A repository
   scope offers `<name>.<class>.md` before `<name>.md` at the base commit.
8. A prompt's `tests` file is YAML, `cases:` a non-empty list of `{name?, input, assert}`: `input`
   is the user message, and `assert` is a non-empty list of one-key mappings drawn from exactly:
   `contains: <text>` (the reply text includes it), `matchesSchema: <mapping>` (the reply text is a
   JSON document that satisfies the mapping, a JSON Schema subset: `type`, `properties`,
   `required`, `items`, `enum`), `calledHandoff: <bool>` (whether the reply's tool calls include
   one named `handoff`) and `underTokens: <int>` (the reply's output tokens as the endpoint
   reported them, the reply text's estimate when it reported none, are below the number). Any other
   key is refused naming the file and the case. `docket pod test` sends each case as one exchange:
   the prompt's text as the system message, `input` as the user message, and, when the prompt
   declares `output: handoff/v1`, the `handoff` tool a turn without a verdict gate is offered: the
   same name, description and `handoff/v1` parameters (`kernel/handoff.py`). The tests file is
   never written by a test run, and the result is `pass` only when every assertion of every case
   holds.

### Scopes, references and the lockfile

1. Roles, prompts, pipelines, skills and MCP servers **MUST** resolve through one order, nearest
   first, and the first scope that holds a name wins: the repository's `.docket/`, the pod overlay
   (`Home.pod_config_dir`), the operator's `config/`, then what ships (`Home.scopes`). Roles read the
   pod overlay's `roles/` and the operator's `config/roles/`, then the built-in and starter
   archetypes; an MCP server read for a pod is the pod's before the operator's. The repository
   entry is read at turn time only for the text kinds: a prompt (and a skill) is read from the
   task's base commit through `teams/workspace/repo_view.py` and never from the writable
   worktree, and with no base commit the repository entry is skipped. Roles, pipelines and MCP
   servers enter from a repository only through `docket pod update`, an operator command.
2. A reference is `<name>[@<major>]` for a role, or `prompt:<layer>/<name>[@<major>]` for a prompt.
   The loader **MUST** resolve a prompt reference to the newest file of that major across the
   scopes' files named `<name>.md` or `<name>@<version>.md` (a repository, read from a base commit,
   offers `<name>.md` only), and **MUST** refuse a reference no file satisfies naming the
   reference. Without a major the newest file wins. A role's `version` is an integer and is
   the major a role reference names.
3. `docket pod update <directory>` **MUST** write the directory's authored files into the pod
   overlay: each role as `roles/<name>.<ext>` with the file its `instructions` names beside it
   (a copy of the source bytes, never a regenerated document), each prompt as
   `prompts/<layer>/<file>`, and the pipelines, skills, policies and plugins as before. There is
   no applied `roles.json`; an `update` **MUST** leave none behind.
4. The same update **MUST** write `applied.lock`, a JSON object `{"items": [...]}` in the overlay
   directory, one item per file it applied, sorted by `kind` then `name`, each `{kind, name,
   version, scope, path, applied, sha256}`: `path` is the source file's absolute path, `scope` is
   `repository` for a directory named `.docket`, `shipped` for a shipped recipe and `operator`
   otherwise, `applied` is the overlay file relative to the overlay (empty for an item with no
   copy there: the manifest, the bound pipeline and an MCP server), and `sha256` is the hex
   digest of the item's bytes (a role's file followed by its instructions file; a skill's
   files in path order). The recorded `configDigest` **MUST** be the sha256 of the lock file's
   bytes, so one source answers drift.
5. `docket pod show` **MUST** report drift `yes` when the recorded source directory still
   exists and its lock differs from the recorded digest, or when any applied overlay file no
   longer hashes to its item's `sha256`; `no` otherwise, and unknown when there is nothing to compare.
   A pod whose overlay still holds a `roles.json` from an earlier release and no lock **MUST** be
   reported as needing `docket pod update`.

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
    # ("role", "pipeline", "policy", "pod", "provider", "exporter", "channel", "mcp-server",
    #  "autonomy")

Document                             # frozen dataclass
    kind: str
    name: str            # the document's `name`, else the file stem
    path: Path
    doc: dict[str, Any]

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

parse_reference(text) -> Reference                      # teams/prompts.py: name, kind, layer, major
resolve_prompt(layer, name, *, project="", view=None, major=None) -> LoadedPrompt
                              # teams/prompts.py: the first scope that holds it, newest of major
source_items(directory) -> tuple[LockItem, ...]         # teams/apply/lock.py: the lock to write
source_digest(directory) -> str                         # what `configDigest` records

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
x policies/broken.yaml:1 kind: unknown kind 'banana' (valid: role, pipeline, policy, pod, provider, exporter, channel, mcp-server, autonomy)
```

### A directory with one good role and one invalid file

```bash
$ docket pod validate .docket
x .docket/roles/bad.yaml:1 kind: unknown kind 'banana' (valid: role, pipeline, policy, pod, provider, exporter, channel, mcp-server, autonomy)
ok .docket/roles/good.yaml (role security-vetter)
  roles 2 · policies 0 · members 0 · pipeline none · plugins 0 · skills 0 · settings 0
```

### A role file with no `kind:` under `roles/` loads without a note

```bash
$ docket pod validate .docket/roles/custom.yaml
ok .docket/roles/custom.yaml (role custom)
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

- `src/docket/teams/config_docs.py`: `KINDS`, `Document`, `ConfigDocError`, `PathResult`,
  `load_document`, `discover_config_paths`, `validate_directory`, `validate_path`, the four
  short-form models, the kind-to-model table and the location-to-kind table
- `src/docket/teams/apply/plan.py`: the pod manifest key set (`_MANIFEST_KEYS`), `export_pod` and
  its schema headers and `.schemas/` copy, `plan_apply`, `repo_config_dir`
- `src/docket/teams/roles.py`: `load_role_file`, `from_wire`
- `src/docket/teams/prompt_tests.py`: `load_cases`, `run_cases`, `PromptCase`, `Assertion`
- `src/docket/teams/prompts.py`: `load_prompt_file`, `parse_prompt`, `PromptDocument`, `PromptError`,
  `LoadedPrompt`, `shipped_prompt`, `role_prompt`, `substitute`, `OUTPUT_SCHEMAS`; the shipped prompts are
  `src/docket/templates/prompts/`
- `src/docket/pipeline/domain/spec.py`: `load_pipeline`, `normalize_pipeline`
- `src/docket/governance/policy.py`: `validate_policy`, `read_policy`, `normalize_policy`
- `src/docket/models/catalog.py`: `load_provider_document`, `ProviderError`
- `src/docket/observability/exporter.py`: `load_exporter_document`, `ExporterSpec`, `ExporterError`
- `src/docket/operator/channel.py`: `load_channel_document`, `ChannelSpec`, `ChannelError`
- `src/docket/teams/autonomy.py`: `load_autonomy_document`, `AutonomyDocument`, `AutonomyError`
- `src/docket/agent/tools/mcp_tools.py`: `load_mcp_server_document`, `McpServerDocument`,
  `McpServerDocError`
- `src/docket/interfaces/cli/commands/pod_config.py`: `docket pod validate`, `pod update`, `pod plan --pipeline`
- `src/docket/interfaces/cli/commands/run.py`, `src/docket/interfaces/cli/commands/agents.py`: the `docket run` pipeline file read
  and the `docket init` directory validation
- `scripts/gen_config_schemas.py`: the schema generator; `docs/contracts/config-v1/` and
  `src/docket/templates/schemas/` hold the two copies of each schema
