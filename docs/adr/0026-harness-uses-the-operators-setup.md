# ADR 0026 (D-62): harness contract 1.2 runs on the operator's own docket setup

**Question:** Tack, which runs docket through `docket exec` as one of its agent harnesses, is
removing its own model-provider layer: it will hold no model API key, endpoint or model catalog,
and every harness it runs must use the login and configuration the operator gave that harness
with the harness's own tools. For docket that is `docket setup`: the provider catalog
(`docket-providers.json`), the credential store or keyring, and the model registry
(`docket-models.json`). Harness mode cannot use any of it today. ADR 0001 decision 7 requires
`DOCKET_LLM_BASE_URL` and refuses without it; decision 8 makes `DOCKET_HOME` a caller-owned home,
so the operator's setup under the default home is invisible to the run; `--model` is required; and
a caller has no machine-readable way to learn which models docket can reach or whether its setup
can serve a run at all. Should harness mode read the operator's setup, and how, without giving up
what decisions 7 and 8 protect?

**Where decided:** 2026-10-13, by the maintainer, as a brief for harness contract 1.2 shipped in
docket 0.2.0-beta.5.

**Decision:**

1. **A third wire contract, `1.2.0`, opt-in with `--contract 1.2`.** Contracts 1.0 and 1.1 are
   unchanged, `DOCKET_LLM_BASE_URL` requirement included: everything below applies only to a run
   that selected 1.2. The 1.2 shapes are the 1.1 shapes stamped `v: "1.2.0"`, with one more field
   on the result: `model.source`, `"explicit"` or `"setup default"`. A docket that predates 1.2
   refuses `--contract 1.2` as a usage error (exit 2) before preflight, so a caller can probe for
   it without spending anything (decision 6).

2. **The endpoint comes from the setup home.** Amends ADR 0001 decision 7 for contract 1.2. When
   `DOCKET_LLM_BASE_URL` is unset, the run resolves its endpoint and credential the way
   interactive docket does: the built-in provider catalog overridden by the operator's global
   catalog, the credential named by the provider's `auth.credentials`. It reads that setup from
   the **setup home**: `DOCKET_SETUP_HOME` when set, otherwise the default home
   (`~/.docket`). Decision 8 stands: run state stays in the caller-owned `DOCKET_HOME`, which
   must still not be the default home. `DOCKET_LLM_BASE_URL`/`DOCKET_LLM_API_KEY` still win when
   set, so a stub server or a test keeps working exactly as under 1.1.

3. **The setup home is read, never written, and only three files of it.** The run reads
   `docket-providers.json`, `docket-models.json` and `secrets.json`, with a plain read that takes
   no lock and never recovers from a backup (`edges/store.py::read_json_readonly`): the normal
   reader takes a per-directory lock, which creates a file. It never reads pods, policies,
   traces, workspaces, sessions or the audit log there, and never writes there. A caller that
   sandboxes docket exposes exactly those three files read-only.

4. **A model the operator chose, never one docket picked.** Without `--model`, the run uses the
   model the setup registry assigns to its `--role` (`roles.<role>`), then the registry's
   `default`. Built-in rank anchors are not a choice anyone made, so they never select a model
   here: a registry that names neither is a refusal (exit 2, before any network call) that says
   how to set one (`docket setup model set <role> PROVIDER/ID`). Every write `docket setup`
   makes (`provider add`, `model preset`, `model set`) records both keys, so an operator who ran
   it is covered.

5. **A credential that cannot be read is a refusal.** A provider with `auth.type` other than
   `none` must resolve a credential: from the environment under one of its names, from
   `secrets.json`'s value, or from the OS keyring when `secrets.json` holds only the index (an
   empty value, which is how the keyring backend stores it). A missing credential or a keyring
   lookup that fails (no `secret-tool`, no D-Bus session, as inside most sandboxes) refuses with
   a sentence naming the provider and the credential name, never the value, and saying how to
   use the environment or the file backend instead. No request is ever sent unauthenticated.
   The resolved value joins docket's trace redaction set and its name joins the set stripped
   from every child process's environment, as `DOCKET_LLM_API_KEY` does today.

6. **One offline, machine-readable answer: `docket setup harness --json`.** A new read-only noun
   under `setup` (ADR 0022's rule: nouns under `setup` are singular and named for what they do;
   no new top-level command). It reads the setup home exactly as decision 3 says, makes no network
   call, prints no secret value, and reports `ready`, `reason`, the default model per role, the
   models of every provider whose credential resolves or that needs none, and each provider's
   name, base URL and credential source (`env`, `store`, `keyring` or `none`). Its shape is part
   of contract 1.2 (`specs/api/harness-mode.spec.md`).

7. **Not under 1.2 yet:** `--recipe` (a recipe run resolves several roles' models through the
   caller's home and the pod pipeline; it stays a 1.1 feature until a measured need asks for it).

**Why this does not undo decision 7's reason.** Decision 7 refused a stored credential because
the caller, not docket, held the operator's credential and was accountable for spending it. Under
1.2 the caller holds none: the operator configured docket with docket's own commands, and the run
spends only on a model the operator recorded (decision 4). The hole decision 7 closed (a hosted
gateway's built-in base URL resolving with no configuration) stays closed, because a provider is
used only with a credential the operator stored, and a model only when the operator named it.

**Consequences:** `core/setup_home.py` holds the read-only view; `core/provider.py`'s catalog
merge and `edges/adapters/llm.py`'s endpoint builder are factored so the view reuses them instead
of re-implementing them. `docket exec --contract 1.2` builds its driver with a backend for the
endpoint it resolved before the first turn. The residual risk is stated: the harness process can
read the three setup files, including `secrets.json`'s values under the file backend; a caller
that cannot accept that runs the keyring backend or exports the credential in its environment.
