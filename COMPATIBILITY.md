# Compatibility

docket has no external daemon dependency. Its compatibility surface is the **model endpoint**
docket's own turn loop talks to, the optional MCP servers it can gate like a built-in tool, and two
configuration-scoped adapters for the separately built `docket-runtime` package. This document
records what docket is verified against and how breaks are tracked. See the README's
[Compatibility](README.md#compatibility) section for the short version.

## Support matrix

| docket-cli | Model endpoint | MCP | Notes |
|------------|-----------------|-----|-------|
| 0.2.x | Non-streaming OpenAI-compatible `/chat/completions` (function tools) | stdio servers, optional `[mcp]` extra | Hermetic wire coverage for OpenRouter/Vercel and explicitly registered compatible endpoints; no live-provider CI |

- **Model endpoint.** `edges/adapters/llm.py` is the one module that knows the
  chat-completions wire format, built on stdlib `urllib` — no vendor SDK is pulled in. Any
  endpoint that speaks Docket's non-streaming OpenAI-compatible `/chat/completions` and function
  tool shapes can be used. OpenRouter and Vercel AI Gateway have built-in base URLs and central-key
  resolution. Register another hosted or local llama.cpp / vLLM / LM Studio endpoint with
  `docket models provider add`; the process-wide `DOCKET_LLM_BASE_URL` /
  `DOCKET_LLM_API_KEY` override remains useful for a temporary single endpoint.
- **Tool calling.** An endpoint that does not implement tool calling still runs text-only
  turns; anything that requires a tool fails cleanly (a typed, non-`ok` response) rather than
  silently.
- **Deliberate limits.** Streaming, Responses API payloads, vendor routing options, remote catalog
  discovery, and live price synchronization are not part of the current adapter. See
  [the gateway guide](docs/MODEL-GATEWAYS.md) for setup and test boundaries.
- **MCP.** `docket mcp servers add` points at any MCP stdio server; its tools are gated
  through the exact same chokepoint as a built-in, namespaced `mcp__<server>__<tool>`.
  Requires the optional `[mcp]` extra (`pip install 'docket[mcp]'` or `uv sync --extra mcp`);
  without it, `docket mcp` commands print an actionable missing-SDK message instead of a bare
  import error.

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

A2A is not used because these configurations integrate with Docket in process. OTLP is not used
because JSONL trace records preserve project, session, role, call, and decision identity. See the
[compact adapter example](examples/runtime_adapters.py) for the machine-readable boundary and lazy
constructors. Neither framework is a dependency of the base `docket-runtime` installation.

## Platform

- **Python 3.11+** — required; the runtime for all docket logic.
- **Linux** — primary, CI-gated (`python`/`floors`/`golden`/`shell` jobs in
  `.github/workflows/ci.yml`).
- **macOS** — supported on a best-effort basis; the `macos` CI job runs the full pytest suite
  and a launcher smoke test, but is `continue-on-error: true` — a macOS-only failure does not
  block a merge today.
- **Bash 4.0+** — required only for the `bin/docket` launcher shim (locates a Python
  interpreter and execs `python -m docket "$@"`). Not required if you invoke `python -m docket`
  directly. macOS ships Bash 3.2; install a newer one via Homebrew if you use the shim.
- No `systemd` (or any other service manager) dependency. Earlier versions restarted an
  external daemon's gateway service after config changes; that daemon no longer exists, and
  `edges/adapters/system.py`'s `restart_gateway`/`gateway_active` are honest no-op stubs kept
  only so old call sites don't need individual rewrites.

## Policy

- **Model-endpoint changes.** Providers occasionally change response shapes or error codes.
  `edges/adapters/llm.py` treats a documented set of HTTP statuses (`408/409/425/429/5xx`) as
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
