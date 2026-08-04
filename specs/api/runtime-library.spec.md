# Runtime Library (`docket-runtime`) Contract Specification

**Version**: 1.0.0
**Status**: Implemented (packaging + boundary test; NOT yet published to any index)
**Last Updated**: 2026-08-03

## Purpose

ROADMAP Phase 21 (decision D-20) answers what docket is for two products: **(a)** the factory
that builds agentic products — Phase 19 finished this — and **(b)** the runtime those products
ship on. *If every product is agentic, the runtime is the common part of every product*, so the
factory's highest-value output is not agent-written code, it is a **reusable substrate**: one
gated tool chokepoint, one policy engine, one approval store, one hash-chained audit log, instead
of every product team reinventing guardrails badly.

Decision D-21 asks whether to split that substrate into an embeddable library. The answer is
**yes, but packaging only** (P21-1). This specification defines exactly what that split shipped:
a separately buildable/installable distribution, `docket-runtime`, packaged from the same source
tree as the `docket` control plane with **zero files moved or duplicated** — and the versioning
policy a consumer embedding it may rely on.

**What this is not.** This is not a new API design, not a plugin system, not extension points,
and not a rewrite. Every module `docket-runtime` ships is the identical file the `docket` control
plane already builds from (see "Packaging mechanism" below); the only new artifact is a second
`pyproject.toml` that selects a subset of them, plus the test that pins the boundary.

## Scope

This specification covers:

- The packaging mechanism: how `docket-runtime` is built from `src/docket/` with no source moved
  or duplicated, and exactly which files it ships
- The dependency contract: `docket-runtime` depends on exactly `pydantic` and `filelock`
- The versioning policy: what a consumer embedding this library may rely on across a version
  bump, and what is explicitly not promised
- The boundary test (`tests/python/test_runtime_package_boundary.py`) and what it does and does not
  prove
- Known, deliberate degradation points where a shipped module has a lazy, guarded reference to
  control-plane-only code that is not part of this distribution

This specification does NOT cover:

- The `docket` control-plane distribution itself, its CLI, or its dependency set — see
  `cli-interface.spec.md` and the package's own `pyproject.toml`
- The runtime's own internal behavior (the chat port, the tool gate, the policy engine, the
  approval store, the audit chain, the turn loop) — each already has its own spec
  (`agent-loop.spec.md`, `security-gates.spec.md`, `audit.spec.md`, `session-history.spec.md`,
  `role-archetypes.spec.md`) and this document does not restate their contracts
- Publishing `docket-runtime` to PyPI or any other index — not done by this card, see Status above
- Any hosted-runtime concern D-20 explicitly ruled out of scope for the substrate: multi-tenancy,
  authn/authz for external callers, queues/workers, streaming, per-customer quota. An embedding
  product owns its own serving layer; this library is the gated loop inside it, nothing more

## Packaging mechanism

`packages/docket-runtime/pyproject.toml` is a second, independent build configuration in this
same repository. It uses hatchling's `force-include` to map specific files already living under
`src/docket/` straight into a wheel at the identical `docket.*` import path the control plane
uses — so `import docket.core.llm` resolves the same way whether a consumer installed the full
`docket` package or only `docket-runtime`. **No file moves and no file is duplicated in the
repository**; the two distributions are two different *views* over one source tree, built from
one commit.

**Why the same `docket.*` namespace, not a new top-level package.** Every shipped file
cross-imports the others via `docket.core.X` / `docket.edges.X`, and several are imported the
same way by `core/dispatch.py` and `cli/` in the control plane. Renaming the import path (e.g. to
`docket_runtime.llm`) would be a restructure — D-21 explicitly forbids that for this card. Keeping
the namespace identical is what makes this genuinely "packaging only".

**Consequence, stated plainly:** because both distributions ship files at the same path inside the
`docket` package, installing `docket-runtime` and the full `docket` control plane into the *same*
environment is not a supported configuration — the products this library targets embed
`docket-runtime` alone, per D-20's "an embedding product owns its own serving layer" framing, not
alongside the CLI.

### The shipped file set

The exact set is the `[tool.hatch.build.targets.wheel.force-include]` table in
`packages/docket-runtime/pyproject.toml` — this specification does not repeat it as a second,
driftable copy; `tests/python/test_runtime_package_boundary.py` reads that table directly, so the
test and the shipped wheel can never silently disagree. As of this version it is 23 real modules
(plus 4 `__init__.py` package markers): the chat port and its adapter, the gated tool registry and
its built-in/fetch/sandboxed-exec handlers, the turn loop, the policy engine, the approval store,
the security classifier, the audit and trace modules, the session store and its compaction path
(`core/context.py`, `core/handoff.py`), role/toolset composition (`core/archetypes.py`,
`core/identity.py`, `core/memory.py`'s startup-file contract), the fleet-config reader
(`core/fleet.py`, needed because `core/security.py` imports it unconditionally for the
approval-routing/sandbox-isolation toggles `docket gates` flips), `core/models.py`, `config.py`,
and `edges/store.py`.

**This file list was measured, not copied from the card text.** ROADMAP's P21-1 card named 14
files; walking the real import graph (AST, module-level imports only — see the boundary test's own
docstring for why function-local, guarded imports are excluded from that walk) found 9 more that
are real, non-optional transitive dependencies, plus one (`edges/adapters/fetch.py`) reachable
only through a function call (`core/tools.py`'s `builtin_registry()`), found by actually calling
it in a bare venv rather than by static analysis alone.

### Known, deliberate boundary gaps

Three shipped modules have a **function-local, exception-guarded** reference to a control-plane
module this distribution does not ship. Each was checked against its actual call site, not
assumed safe:

| Shipped module | Guarded reference | Guard | Real effect when absent |
| --- | --- | --- | --- |
| `core/approval.py`'s `_resolve_timeout_as_denied` | `core.dispatch.resolve_waiting_approval` | `contextlib.suppress(Exception)` | A timed-out approval still resolves to denied and audits; the best-effort notification back into pod-dispatch's queue silently no-ops (there is no pod-dispatch queue in an embedding product) |
| `core/trace.py`'s `_stored_secret_values` | `core.secrets.secret_values` | `try/except Exception: return []` | `redact()` still applies its always-on regex patterns; it just does not additionally scrub the exact values of secrets stored in docket's own `docket keys` store, which an embedding product does not have |
| `core/fleet.py`'s `add_local_provider` | `core.provider.local_provider_config` | none — calling this one function raises `ModuleNotFoundError` | Deliberate: this function exists only for `docket models provider add`, a control-plane command; nothing on the runtime's own call path (`agent_loop`/`tools`/`session`/`policy`/`approval`/`security`/`audit`/`trace` + their edges) reaches it |

The first two are proven, not asserted: the smoke test in this card's report exercises
`dispatch_tool`, `redact()`, and `approval_sweep_expired()` in a bare venv with neither
`core/dispatch.py` nor `core/secrets.py` present, and all three complete without error.

## Versioning policy

`docket-runtime` is versioned **independently** of the `docket` control plane distribution,
starting at `0.1.0` — both are pre-1.0 and neither's version number implies anything about the
other's; they happen to be built from the same commit today because P21-1 shipped no dependency
edge from one to the other's *packaging*, only a shared source tree.

**What counts as the public surface.** Per D-21's "packaging only" constraint, this distribution
defines no `__all__`, no facade module, and no re-export layer — that would be new API surface,
which the card forbids designing. The public surface is therefore **every non-underscore-prefixed
name in every module the force-include table ships**, exactly as it already exists. A name whose
own identifier (or its containing module's) starts with `_` is private regardless of where it
sits.

**Semantic versioning, pre-1.0 rules:**

- **Patch** (`0.1.x`): implementation fixes with no change to any public name's signature,
  behavior contract, or presence.
- **Minor** (`0.x.0`): may add new public names (new modules, new functions, new fields), and — as
  is standard for a pre-1.0 package — **may also remove or change a public name**, provided the
  change is called out by name in this spec's Changelog. Pre-1.0 does not promise stability; it
  promises that every break is written down, not silent.
- **Major** (`1.0.0` and beyond, once cut): only after the library has a real embedding consumer
  to break compatibility for (mirrors D-24's standing test — "does a measured need in *this*
  system ask for it", not a calendar date). From `1.0.0` onward, removing or changing a public
  name's signature requires a major bump.

**What is never silently reshaped, at any version:** the shipped file list only grows or shrinks
via an explicit edit to `packages/docket-runtime/pyproject.toml`'s force-include table, which
`tests/python/test_runtime_package_boundary.py` re-validates on every run — so "which files are the
library" cannot drift out from under a consumer between releases without the test noticing.

**What is explicitly NOT promised:**

- Wire-format stability of anything under `edges/adapters/` beyond what its own functional spec
  already documents (e.g. `agent-loop.spec.md` for the OpenAI-compatible chat wire).
- That a function reachable only via one of the guarded references in "Known, deliberate boundary
  gaps" above will keep working — those are explicitly control-plane-only escape hatches.
- Dependency floors beyond `pydantic>=2.1`/`filelock>=3.13` — these are re-measured the same way
  the control plane's floors are (see CLAUDE.md's dependency-floors note); do not raise or lower
  either without re-measuring against a real install.

## Syntax

Building the wheel (from a checkout of this repository):

```bash
cd packages/docket-runtime
uv build --wheel --out-dir /path/to/dist
# -> dist/docket_runtime-<version>-py3-none-any.whl
```

Installing it standalone, into an environment with nothing else from this repository:

```bash
python3 -m venv /path/to/venv
/path/to/venv/bin/pip install /path/to/dist/docket_runtime-<version>-py3-none-any.whl
```

This is the exact command proving the "genuinely standalone" claim in this card's report — a
fresh venv, this one wheel, nothing else from the monorepo. `uv build` (no `--wheel`) additionally
round-trips through an sdist and currently fails, because the force-include paths are relative to
the packaging directory's position inside this monorepo and do not survive an extracted sdist
that lacks the parent tree; `--wheel` builds directly against the source checkout and is the
supported path until/unless a later card publishes this to an index (out of scope here, see
Status).

## Arguments

Not applicable — this is a library, not a command. Each shipped module's own callable surface
(constructors, function signatures) is documented in its own functional spec
(`agent-loop.spec.md`, `security-gates.spec.md`, `session-history.spec.md`, etc.); this
specification does not restate them.

## Options

Not applicable. The one build-time choice is `packages/docket-runtime/pyproject.toml`'s
`force-include` table (which files ship) and `dependencies` list (declared floors) — both are
config, not runtime options.

## Output

A successful install places the shipped modules under `<site-packages>/docket/...`, exactly
mirroring their path inside `src/docket/` in this repository. `import docket` succeeds and reports
`docket.__version__` — the same version string the control-plane distribution's `__init__.py`
carries, since it is the literal same file.

## Return

Not applicable in the CLI-exit-code sense. A build failure (missing force-include source file, or
using `uv build` without `--wheel` — see Syntax) fails the build step with a non-zero exit and a
message naming the missing path; an install failure follows pip's own exit-code convention.

## Validation

- `packages/docket-runtime/pyproject.toml`'s `dependencies` **MUST** list exactly `pydantic` and
  `filelock` (with the same floors the control plane measured) — no third dependency without
  re-measuring the whole slice.
- Every shipped file **MUST NOT** import `docket.cli` (or a submodule), `docket.ui`,
  `docket.serve`, or `docket.__main__`, at any import depth (module scope or inside a function).
- Every shipped file **MUST NOT** contain a **module-level** import of any third-party package
  other than `pydantic`/`filelock`. A function-local, exception-guarded import of another
  third-party package (today: `core/archetypes.py`'s optional `yaml` support) is permitted, since
  it is not paid unless the guarded function is actually called, and is not part of the runtime
  slice's own primary call path.
- The force-include table **MUST NOT** be empty, and every path in it **MUST** resolve to a real
  file — both are asserted directly by the boundary test, not left to a build-time failure to
  surface later.
- Both boundary invariants **MUST** be enforced by
  `tests/python/test_runtime_package_boundary.py`, an AST-based (not line-scanning) guard modelled
  on `test_no_subprocess_in_core.py` / `test_no_openclaw_references.py`.
- A wheel built from `packages/docket-runtime/pyproject.toml` **MUST** install, in a virtual
  environment containing nothing else from this repository, with `pydantic` and `filelock` as the
  only non-transitive dependencies pulled in.

## Examples

### Exercising the real chokepoint standalone

```python
# In a venv where only `pip install docket_runtime-<version>-py3-none-any.whl` has run.
import json, pathlib
from docket.core.tools import builtin_registry, dispatch_tool, ToolContext
from docket.core.llm import ToolCall

registry = builtin_registry()
scratch = pathlib.Path("/tmp/demo")
scratch.mkdir(exist_ok=True)
(scratch / "hello.txt").write_text("hello from docket-runtime standalone\n")

ctx = ToolContext(agent_id="demo-agent", project="demo", roots=(scratch,))
call = ToolCall(id="1", name="read", arguments=json.dumps({"path": str(scratch / "hello.txt")}))
result = dispatch_tool(call, ctx, registry)
# result.ok is True; result.content == "hello from docket-runtime standalone\n"

# The containment gate applies exactly as it does inside the control plane:
outside = ToolCall(id="2", name="read", arguments=json.dumps({"path": "/etc/passwd"}))
denied = dispatch_tool(outside, ctx, registry)
# denied.ok is False -- refused because /etc/passwd resolves outside `ctx.roots`
```

### The security classifier standalone

```python
from docket.core.security import classify_command

classify_command("git status")
# CommandVerdict(action='allow', ...)
classify_command("git push origin production")
# CommandVerdict(action='ask', reason="matches high-risk action class 'prod-deploy': ...", ...)
```

## Changelog

### Version 1.0.0 (2026-08-03)

- Initial specification: `docket-runtime` packaging mechanism (hatchling `force-include` over the
  existing `src/docket/` tree, zero files moved or duplicated), the measured 23-module file set
  (9 more than ROADMAP's P21-1 card text named, all verified real), the three deliberate guarded
  degradation points, the independent semver-pre-1.0 versioning policy, and the AST-based boundary
  test (ROADMAP Phase 21, decision D-21).
