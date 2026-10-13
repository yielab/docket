# Compatibility

docket has no external daemon dependency. Its compatibility surface is the **model endpoint**
docket's own turn loop talks to, the optional MCP servers it can gate like a built-in tool, and two
configuration-scoped adapters for the separately built `docket-runtime` package. This document
records what docket is verified against and how breaks are tracked. See the README's
[Known limits](README.md#known-limits) section for the short version.

## Support matrix

| docket-cli | Model endpoint | MCP | Notes |
|------------|-----------------|-----|-------|
| 0.2.x | Non-streaming OpenAI-compatible `/chat/completions` (function tools) | stdio servers, optional `[mcp]` extra | Hermetic wire coverage for OpenRouter/Vercel and explicitly registered compatible endpoints; no live-provider CI |

- **Model endpoint.** `edges/adapters/llm.py` is the one module that knows the
  chat-completions wire format, built on stdlib `urllib` — no vendor SDK is pulled in. Any
  endpoint that speaks Docket's non-streaming OpenAI-compatible `/chat/completions` and function
  tool shapes can be used. OpenRouter and Vercel AI Gateway have built-in base URLs and central-key
  resolution. Register another hosted or local llama.cpp / vLLM / LM Studio endpoint with
  `docket setup provider add`; the process-wide `DOCKET_LLM_BASE_URL` /
  `DOCKET_LLM_API_KEY` override remains useful for a temporary single endpoint.
- **Tool calling.** An endpoint that does not implement tool calling still runs text-only
  turns; anything that requires a tool fails cleanly (a typed, non-`ok` response) rather than
  silently.
- **Deliberate limits.** Streaming, Responses API payloads, vendor routing options, remote catalog
  discovery, and live price synchronization are not part of the current adapter. See
  [the gateway guide](docs/MODEL-GATEWAYS.md) for setup and test boundaries.
- **MCP.** `docket setup mcp add` points at any MCP stdio server; its tools are gated
  through the exact same chokepoint as a built-in, namespaced `mcp__<server>__<tool>`.
  Requires the optional `[mcp]` extra (`pip install 'docket[mcp]'` or `uv sync --extra mcp`);
  without it, `docket mcp` commands print an actionable missing-SDK message instead of a bare
  import error.

## Harness contract (`docket exec`)

A program that runs docket as an agent harness pins one wire contract with `--contract`; each
version's JSON Schema is committed under `docs/contracts/` and its rules are in
[specs/api/harness-mode.spec.md](specs/api/harness-mode.spec.md).

| Contract | First docket | Endpoint and credential | `--model` | Schema |
| --- | --- | --- | --- | --- |
| `1.0` (default) | 0.2.0-beta.3 | `DOCKET_LLM_BASE_URL` / `DOCKET_LLM_API_KEY` only | required | `harness-v1/` |
| `1.1` | 0.2.0-beta.4 | the same | required | `harness-v1.1/` |
| `1.2` | 0.2.0-beta.5 | the operator's `docket setup` in the setup home, unless `DOCKET_LLM_BASE_URL` is set | optional (the role's setup model) | `harness-v1.2/` |

- **Probing for 1.2, at no cost:** `env -u DOCKET_HOME docket exec --contract 1.2 --workspace .
  --task probe`. 0.2.0-beta.5 and later: exit 2, a `v: "1.2.0"` refused result, `error` `DOCKET_HOME
  is not set; harness mode never runs against the default home`. Earlier builds: exit 2, a
  `v: "1.0.0"` refused result whose `error` begins `--contract must be one of`.
- **Readiness, offline:** `docket setup harness --json` (exit 0 ready, 1 not).
- **What 1.2 reads from the setup home** (`DOCKET_SETUP_HOME`, default `~/.docket`), read-only:
  `docket-providers.json`, `docket-models.json`, `secrets.json`; plus the OS keyring through
  `secret-tool` when `secrets.json` lists a key with an empty value (the keyring backend). A
  sandboxed caller exposes exactly those three files read-only, or exports the credential.

## Embeddable runtime adapters

| Adapter | Installed fixture | Verified boundary |
| --- | --- | --- |
| OpenHands SDK | `openhands-sdk==1.44.1` on Python 3.12 | Standard `Agent` with only translated Docket tools |
| PydanticAI | `pydantic-ai==2.37.0` on Python 3.11 | One sequential `DocketToolset` with only translated Docket tools |

The test matrix builds one wheel and sdist, installs both outside the source checkout, and compares
state bytes, provider-reported usage, tool-call count, stop reason, trace identity, audit-chain
verification, and typed handoff. The compatibility claim applies only when relevant tools are
exclusively Docket-backed. ACP, native/provider tools, plugins/MCP added beside an adapter, and
arbitrary framework configurations are outside the proof. This is not framework-neutral support.

The separate [adoption evidence report](docs/ADOPTION-EVIDENCE.md) publishes the exact-artifact
starter, governance, and recovery fixture results. It is deterministic contract evidence, not live
provider or framework benchmarking.

A2A is not used because these configurations integrate with Docket in process. OTLP is not used
by the adapters because JSONL trace records preserve project, session, role, call, and decision
identity; docket's own trace export (`kind: exporter`) is a separate, operator-enabled
projection of that trace and is not part of this proof. See the
[compact adapter example](examples/runtime_adapters.py) for the machine-readable boundary and lazy
constructors. Neither framework is a dependency of the base `docket-runtime` installation.

## Platform

- **Python 3.11+** — required; the runtime for all docket logic.
- **Linux** — primary, CI-gated (`python`/`floors`/`golden`/`shell` jobs in
  `.github/workflows/ci.yml`).
- **macOS** — supported on a best-effort basis; the `macos` CI job runs the full pytest suite
  and a launcher smoke test, but is `continue-on-error: true` — a macOS-only failure does not
  block a merge today.
- **Bash 3.2+** — the floor for every shell entry point docket ships: the `bin/docket`
  launcher shim (locates a Python interpreter and execs `python -m docket "$@"`), `install.sh`
  and `uninstall.sh`. 3.2 is what macOS still ships, so the stock interpreter is enough and no
  Homebrew Bash is needed. None of these is required if you invoke `python -m docket` directly.
  Pinned by `tests/agent/release/test_public_release_truth.py::test_shipped_shell_surface_runs_on_the_bash_floor`.
- No `systemd` (or any other service manager) dependency.

## Policy

- **Model-endpoint changes.** Providers occasionally change response shapes or error codes.
  `edges/adapters/llm.py` treats a documented set of HTTP statuses (`408/409/425/429/500/502/503/504`) as
  retryable and everything else as a real rejection; a genuinely breaking wire-format change
  is called out in [CHANGELOG.md](CHANGELOG.md).
- **MCP SDK changes.** The `[mcp]` extra pins a floor version, not a ceiling
  (`pyproject.toml`'s `[project.optional-dependencies]`); a breaking SDK release is handled the
  same way — pin and changelog entry.
- **Reporting a break:** open a bug report (`.github/ISSUE_TEMPLATE/bug_report.yml`) with your
  `docket --version`, the model provider/endpoint you're using, and the failing command.

## What this file does not claim

There is no automated compatibility CI against external providers today — the matrix above
reflects the pytest suite (which exercises the adapter against fixtures and a fake endpoint,
not a live third-party API) and manual verification. If that changes, this file is the place
the claim will be recorded.
