# ADR 0021 (D-56): workspace isolation is opt-in again

**Question:** ADR 0020 §1 turned workspace isolation on by default: a `DOCKET_HOME` with no
recorded choice jails every `bash` call and refuses the turn when no backend is usable. The first
CI run on hosts without a sandbox showed what that costs. Should a fresh install require a
sandbox before it can run one turn?

**Where decided:** 2026-10-06, by the operator, after the CI run for `c5419841` failed on macOS.
No phase: the decision changes one default and the documentation of the feature.

**Evidence:**

| Fact | Locator |
| --- | --- |
| A stock macOS runner has neither bwrap nor docker; bwrap does not exist on macOS | CI run for `c5419841`, jobs `macos` and `release-journey (macos)` |
| With the default on, every turn on such a host was refused: 40 driver tests and the release journey's governed turn | `edges/adapters/docket_runtime.py::_resolve_sandbox` |
| The quick start never named a sandbox as a requirement, so a newcomer met the refusal on the first dispatch | `docs/QUICK-START-DOCKET.md` before `19ef610b` |
| The workaround (`docket gates isolate off`) had to be added to the release journey and to every fixture that wanted no jail | `scripts/release_journey.py` (`19ef610b`), `tests/conftest.py::record_isolation_off` |

## Decision

1. **Isolation is opt-in.** No recorded choice means off: tools run on the host, as they did
   before ADR 0020, and no backend is probed. `docket gates isolate on` turns it on and succeeds
   only when bwrap or docker is usable; `isolate off` records an explicit off. Both are audited.
   `gates status` and `doctor` read `off (default)`, `on` or `off (explicit)`.
2. **Once on, it still fails closed.** A turn with isolation on and no usable backend is refused
   before any model call and audited (`isolation.refused`). Opt-in changes who chooses, not what
   "on" means.
3. **The requirement is documented with the feature.** `docs/SECURITY-SIMPLE.md` "Workspace
   isolation (opt-in)" names the backend per host (bubblewrap on Linux, Docker on Linux or macOS),
   the Docker image's needs, what the jail covers and what it does not. The quick start lists the
   sandbox as optional.

Everything else ADR 0020 decided stands: bwrap before docker, the jail's writable git dirs with
read-only hooks and config, `network none` (still refused with isolation off), stdio MCP servers
jailed while isolation is on, file-tool symlink confinement, `pre_input` on `fetch`, docket's
credentials stripped from task processes, one sweep worker per pod.

## What this reverses

| Earlier decision | Now |
| --- | --- |
| ADR 0020 §1: isolation on by default; `isolate off` is the opt-out | Reversed: off by default; `isolate on` is the opt-in. |

## Test discipline

- The default is pinned by a driver test that runs a turn with no recorded choice and fails if a
  backend is probed, and by `gates status`, `doctor` and the data-layer tests reading
  `off (default)`.
- A test that turns isolation on stubs `sandbox_availability` or skips with a named reason; the
  suite must pass under `scripts/maint/pytest-without-sandbox.sh`.
