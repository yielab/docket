# P46-5 step 3: the `environ` sites outside `config.py` (decision table)

Input: `uv run python scripts/maint/measure_kernel_adoption.py environ --list` at BASE 36867d97:
95 sites, 61 in `config.py` (they leave with it: `Home.from_environ` is the one reader and
`kernel/` is not scanned), **34 elsewhere**, decided below. The integrator applies this in stage 3.
Nothing under `src/` was edited.

## The rule applied

`config.py` read every tunable **once, at import**, and `Home` carries those. The 34 sites left are
different: each reads the environment **live, at call time**, and about 130 test lines
(`monkeypatch.setenv`) depend on seeing a change within the same process. Turning such a read into a
`Home` field would snapshot it when the process default is first built, so a test that sets the
variable afterwards would silently stop working. Therefore:

- **Home field**: the value is a tunable `Home` already owns (or should), and no test toggles it live.
- **stays**: the process environment is the input (an entry point, or the edge adapter whose job
  is to read it). The site is listed in the final `environ` baseline.
- **stays, to system.py**: a live read in `core/`, which should not read the environment at all
  (layer rule: side effects live in `edges/`). It moves behind one `edges/adapters/system.py`
  helper; the helper is the single remaining site.

## Table

| # | file:function | variable | decision | field / reason |
|---|---|---|---|---|
| 1 | `cli/_contract.py:50 next_step` | `DOCKET_NO_HINTS` | stays | CLI presentation toggle; 6 test lines set it live |
| 2 | `cli/_pod.py:201 _pod_name` | whole `os.environ` to `resolve_pod(env=)` | stays, consolidate | entry point; `resolve_pod` is already pure (takes `env`, `cwd`) |
| 3 | `cli/_pod_config.py:44 _pod_name` | same | stays, consolidate | same |
| 4 | `cli/_pod_config.py:52 _scope_pod` | same | stays, consolidate | same |
| 5 | `cli/_run.py:335 cmd_run` | same | stays, consolidate | same |
| 6 | `cli/_status.py:430 cmd_status` | same | stays, consolidate | same |
| 7 | `cli/_task.py:59 _pod_name` | same | stays, consolidate | same |
| 8 | `cli/_task.py:67 _resolve` | `DOCKET_POD` | stays | CLI scope fallback; 8 test lines set it live |
| 9 | `cli/_setup.py:101 _shell_name` | `SHELL` | stays | which shell the operator runs, for the completion hint; pure process fact |
| 10 | `cli/_setup_model.py:202 _supply_credential` | the credential's own env name | stays | operator input to `setup provider add`; the name comes from the provider document, so it is data, not a field |
| 11 | `cli/_setup_notify.py:167 _resolve_token` | `_TOKEN_NAME` (`TELEGRAM_BOT_TOKEN`) | stays | same: operator input at the command |
| 12 | `core/exporter.py:500 resolve_credentials` | credential env names | stays, to system.py | `core/` must not read the environment; same helper as 14, 15, 16 |
| 13 | `core/identity.py:281 resolve_static_context_budget` | `CONTEXT_TOKEN_BUDGET` | **Home field** | `context_token_budget_override: int \| None` already exists. Replace the whole test with `current_home().context_token_budget_override is not None`. The second branch (`CONTEXT_TOKEN_BUDGET != CONTEXT_TOKEN_BUDGET_DEFAULT`) existed only so a test could monkeypatch the constant; the 4 test lines that do (`test_identity.py`, `test_role_tools_and_identity.py`) become `Home(root, context_token_budget_override=N)`. This is the one site that is a pure duplicate of a `Home` field. |
| 14 | `core/provider.py:391 resolve_credential` | `DOCKET_LLM_API_KEY` | stays, to system.py | live; 15 test lines set it |
| 15 | `core/provider.py:397 resolve_credential` | credential env names | stays, to system.py | dynamic name |
| 16 | `core/provider.py:710 model_readiness` | credential env names | stays, to system.py | dynamic name |
| 17 | `core/trace.py:158 _stored_secret_values` | every credential-shaped variable | stays, to system.py | redaction must see a key exported after startup; move the loop to `system.py::credential_env_values(names, suffixes)` and keep the redaction regexes in `trace.py` |
| 18 | `edges/adapters/llm.py:640 resolve_endpoint` | `DOCKET_LLM_BASE_URL` | stays | edge adapter; the operator's endpoint escape hatch; 16 test lines set it live |
| 19 | `edges/adapters/llm.py:641 resolve_endpoint` | `DOCKET_LLM_API_KEY` | stays | edge adapter, same function |
| 20 | `edges/adapters/llm.py:664 resolve_endpoint` | derived `<PREFIX>_API_KEY` | stays | edge adapter; dynamic name |
| 21 | `edges/adapters/system.py:54 _which` | `PATH` | stays | it is the PATH lookup |
| 22 | `edges/adapters/system.py:71 desktop_notifications_available` | `DISPLAY` | stays | probe of the session |
| 23 | `edges/adapters/system.py:71 desktop_notifications_available` | `WAYLAND_DISPLAY` | stays | same line, same probe |
| 24 | `edges/adapters/system.py:178 landlock_available` | `DOCKET_SANDBOX_PROBE` | stays | test seam read live (5 test lines); a field would defeat `pytest-without-sandbox.sh` |
| 25 | `edges/adapters/system.py:191 seatbelt_available` | `DOCKET_SANDBOX_PROBE` | stays | same |
| 26 | `edges/adapters/system.py:218 sandbox_availability` | `DOCKET_SANDBOX_BACKEND` | stays | operator override read live; **69 test lines** set it, a field would break all of them |
| 27 | `edges/adapters/system.py:302 _trusted_git_env` | whole environment as the child's base | stays | building a child process environment is the adapter's job |
| 28 | `edges/adapters/system.py:679 git_identity_env` | `_GIT_IDENTITY_VARS` (read) | stays | same |
| 29 | `edges/adapters/system.py:679 git_identity_env` | `_GIT_IDENTITY_VARS` (index) | stays | same line |
| 30 | `edges/adapters/system.py:843 task_environment` | whole environment minus names | stays | child environment |
| 31 | `edges/adapters/system.py:897 jailed_env` | `PATH` | stays | child environment of the jail |
| 32 | `edges/adapters/system.py:1632 _pin_env` | whole environment as base | stays | child environment |
| 33 | `serve.py:1924 run_serve` | `DOCKET_SERVE_TOKEN` | stays | process entry of `docket start`, read once; a secret, so not a `Home` field (a frozen dataclass prints in reprs and tracebacks) |
| 34 | `ui.py:44 is_plain` | `NO_COLOR` | stays | presentation; read with `isatty()` |

## Result

- **Home field:** 1 site (#13), field already present, type `int | None`. No new field.
- **Move behind `system.py` helpers:** 5 sites (#12, #14, #15, #16, #17) become calls to two new
  helpers, `system.env_value(name) -> str` (stripped) and `system.credential_env_values(...)`:
  5 sites removed, 2 added.
- **Consolidate:** #2 to #7 (six `resolve_pod(..., env=os.environ, cwd=Path.cwd())`) become one
  `cli/_contract.py::resolve_pod_here(pod)`: 6 removed, 1 added. Behaviour-neutral; skip it if the
  stage-3 diff is already large.
- **Stays as they are:** 22 sites (#1, #8 to #11, #18 to #34).
- **Count after stage 3:** 34 - 1 - 5 + 2 - 6 + 1 = **25** outside `config.py`: `system.py` 14
  (12 listed plus the two new helpers), `llm.py` 3, `_contract.py` 2, and one each in `_task.py`,
  `_setup.py`, `_setup_model.py`, `_setup_notify.py`, `serve.py`, `ui.py`. Write the baseline with
  `measure_kernel_adoption.py --write` after checking `environ --list`.

## Three live reads still in `config.py` that need a landing place

They are among the 61 `config.py` sites and are not in the 34, but `config.py` cannot move to
`kernel/` while they sit there (they are not template lookups, and `core/` and `cli/` call them):

- `secrets_backend_requested()` reads `DOCKET_SECRETS_BACKEND` (callers: `core/secrets.py` x2,
  `cli/_setup_check.py`, `cli/_setup_model.py`, `cli/_setup_notify.py`). Live by contract.
- `no_trace()` reads `DOCKET_NO_TRACE` (`core/trace.py` x2, `core/dispatch.py` x1).
- `no_export()` reads `DOCKET_NO_EXPORT` (`core/telemetry.py`).

Recommendation: three small functions in `edges/adapters/system.py` next to the other live reads.
The codemod lists all of their callers as `no Home field`, so the call sites are known (see below).
`mkdir_private` (6 callers) has no environment read; it fits `edges/adapters/system.py` or
`kernel/` as it is.

## What the `config-reads` / `repointers` dry run leaves for hand work

Counts are from `adopt_kernel.py config-reads --unmappable` and `repointers --unmappable` at BASE
plus the P46-5 rules. `src/` sites are what `measure_kernel_adoption.py` counts (415); the `tests/`
sites are additional, because `config.py` cannot go while tests still read it.

**`Home` is missing two properties the repointers need:** `core/secrets.py:21-22` builds
`SECRETS_FILE` and `SECRETS_META_FILE` from `DOCKET_HOME` at import, and the old
`repoint_docket_home` patched those two attributes by name. Add `Home.secrets_file`
(`root / "secrets.json"`) and `Home.secrets_meta_file` (`root / "secrets.meta.json"`), make
`secrets.py` read them in the functions, and delete the `_isolate_secrets_files` fixture. Without
this, a test that moves its home keeps writing secrets to the autouse path.

Import-time reads in `src/` (16, each freezes the default home if rewritten naively):

- `core/agent_loop.py:235-241` (7): `LoopConfig` dataclass field defaults. Use
  `field(default_factory=lambda: current_home().<field>)`; the factory runs when a `LoopConfig`
  is built, which is the call-time read.
- `core/identity.py:106`: `budget_tokens: int = CONTEXT_TOKEN_BUDGET_DEFAULT`, a constant that is
  not an environment value (`Home.context_token_budget_default` is `6000`); use a plain `6000`
  module constant or a default factory.
- `cli/_setup_check.py:35-38` (4): module aliases `TEMPLATE_VERSION = _cfg.TEMPLATE_VERSION`, etc.
  Delete the aliases and read `current_home()` where they are used.
- `cli/_setup_notify.py:38`: `_TOKEN_NAME = _cfg.TELEGRAM_BOT_TOKEN_KEY`, a constant (`"TELEGRAM_BOT_TOKEN"`);
  inline it.
- `core/secrets.py:21-22` (2): see above.
- `edges/adapters/toolbox.py:42`: `MAX_OUTPUT_CHARS = _cfg.TOOL_MAX_OUTPUT_CHARS`. Real freeze; read
  `current_home().tool_max_output_chars` where it is used. Check who imports `MAX_OUTPUT_CHARS`.

`src/` names with no `Home` member (25): `mkdir_private` (6), `secrets_backend_requested` (5),
`recipes_dir` (5), `no_trace` (3), `no_export` (1), `config_schemas_dir` (1),
`policy_templates_dir` (1), `CHANNEL_TEMPLATES_DIR`, `EXPORTER_TEMPLATES_DIR`,
`PROVIDER_TEMPLATES_DIR` (1 each). The template ones stay in `config.py` by the card.

`src/` imported by name (1): `edges/adapters/exporters/otlp_http.py:22`
`from docket.config import DISPATCH_RETRY_MAX_WAIT_S`; replace its uses with
`current_home().dispatch_retry_max_wait_s`.

In `tests/` the config rule also rewrites reads of `_cfg.X`; the refusals are mostly
`monkeypatch.setattr(_cfg, "X", v)` (215) which become fields on the test's own `Home`
(`Home(root, tool_max_output_chars=2500)`), and the autouse fixtures in `tests/conftest.py`, which
become one autouse `use_home(Home(tmp_path / "_autouse_docket_home"))`. Each refusal names the
`Home` field to set.

`repointers` leaves 57 helpers (a non-test function that repoints and returns, e.g.
`test_audit_log.py::_seed_pod`, `test_pod_config_settings.py::_seed`) and 10 functions that start
threads. A helper cannot become a `with` block because its effect outlives it: turn each into a
`@contextmanager` that the test enters, or into a fixture. A `ContextVar` does not reach threads
docket starts: wrap the thread's work in `contextvars.copy_context().run`, as `Home.use_home`'s
docstring says.
