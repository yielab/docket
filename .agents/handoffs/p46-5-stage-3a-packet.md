# P46-5 stage 3a: what `src/` needs before the single codemod pass (2026-10-23)

BASE is the `plan/phase-46-structure` head named in your prompt. Every rule in
`.agents/handoffs/wave-120-worker-packets.md` applies (where you work, what you never touch,
rules, gates, return). Read the P46-5 card, not a W120 card:
`sed -n '/^### P46-5 /,/^## ◇ WAVE 120/p' TODO.md`.

Another session owns the `DocketError` catcher at the CLI entry and in the HTTP handler. Do not
edit `__main__.py`, the `cli/__init__.py` entry, or the `except` blocks and error-to-status
mapping of `serve.py`'s request handler. Do not edit `scripts/maint/adopt_kernel.py`,
`scripts/maint/measure_kernel_adoption.py` or their tests.

**Never `--write` the codemod on the real tree.** The integrator runs `config-reads`,
`config-patches` and `repointers` once, after this lane merges. Your job is to leave `src/` so
that pass has nothing in `src/` left to refuse except the template lookups that stay in
`config.py` (`recipes_dir`, `policy_templates_dir`, `PROVIDER_TEMPLATES_DIR`,
`EXPORTER_TEMPLATES_DIR`, `config_schemas_dir`, `config.__file__`).

See the refusals with:
`env -u VIRTUAL_ENV uv run python scripts/maint/adopt_kernel.py --check --unmappable config-reads | grep '^unmappable src/'`

## Why

`config-reads` rewrites `config.NAME` to `current_home().name`. In `src/` it refuses three kinds of
site, and each needs a decision a rule cannot make:

1. **A name with no `Home` field:** `secrets_backend_requested` (5), `no_trace` (3), `no_export`
   (1), `mkdir_private` (3). The secrets store also builds its own `secrets.json` and meta paths
   instead of reading them from `Home`, so `Home` needs `secrets_file` and `secrets_meta_file`.
2. **A read at import time** (module level or a class body), which would freeze the default home:
   `TOOL_MAX_OUTPUT_CHARS`, `TEMPLATE_VERSION`, `TELEGRAM_BOT_TOKEN_KEY`,
   `RUNAWAY_TURNS_THRESHOLD`, `RUNAWAY_COST_THRESHOLD`, `KEY_MAX_AGE_DAYS`, `DOCKET_HOME` (2),
   `CONTEXT_TOKEN_BUDGET_DEFAULT` and the seven `AGENT_LOOP_*` class-body defaults.
3. **A name imported by name** (`HANDOFF_DIFF_MAX_CHARS`, `DISPATCH_RETRY_MAX_WAIT_S`) or **the
   config module handed on as a value**.

And the 34 `environ` sites outside `config.py` have a decision table that has not been applied.

## Work

1. `Home.secrets_file` and `Home.secrets_meta_file`, in the `kernel/home.py` style (an
   `_override` field behind a property, derived from `root`, if that is how the neighbouring
   paths are built). The secrets store reads them through `current_home()`.
   `tests/integration/test_home_parity.py` must still pass; extend it if it lists fields.
2. `secrets_backend_requested`, `no_trace`, `no_export`: each reads the environment **live** on
   purpose (tests toggle it with `monkeypatch.setenv`; read the docstrings). Apply the rule at the
   top of `.agents/handoffs/p46-5-environ-decisions.md`: a live read stays a live read, and a live
   read in `core/` moves behind one `edges/adapters/system.py` helper. Do not make them `Home`
   fields. Move each to its landing place and update every caller. State the landing place of
   each in your report.
3. `mkdir_private`: it is a filesystem helper, not configuration. Move it to the module where the
   other private-file writes live (`edges/store.py`, unless something in `kernel/` must call it,
   in which case `kernel/`) and update callers. Say which and why.
4. Each import-time read: read at call time instead (a class-body default becomes a
   `default_factory` or a `None` sentinel resolved at use; a module constant becomes a lookup in
   the function that uses it). A behaviour test per site class (one for the `AGENT_LOOP_*`
   defaults, one for a module-level one): under `use_home(dataclasses.replace(current_home(),
   ...))` the new value is used. RED first.
5. The two names imported by name and the module handed on as a value: rewrite them so that
   `config-reads` can take them, or take them yourself as `current_home().name`.
6. Apply `.agents/handoffs/p46-5-environ-decisions.md` (34 sites to 25), row by row. Report any
   row you could not apply as written, and why. Then write the `environ` baseline with
   `measure_kernel_adoption.py --write` and report every count that moved.
7. Spec: if `specs/` names where one of these lives (for example the secrets spec names the file
   path or the backend variable), make it say where it lives now. No version bump; the
   integrator bumps.

## Done when

- `adopt_kernel.py --check --unmappable config-reads` shows no `src/` refusal except the template
  lookups listed above. Paste the count before and after.
- `measure_kernel_adoption.py --check` passes after your `--write`; report each moved count.
- Gates: `ruff check .`, `ruff format --check .`, `mypy src`, `uv run pytest`,
  `env -u VIRTUAL_ENV bash tests/golden/run.sh verify-all`, `bash scripts/validate-specs.sh`,
  `scripts/maint/comment_lint.py --check` on touched files. All run with `env -u VIRTUAL_ENV`.
