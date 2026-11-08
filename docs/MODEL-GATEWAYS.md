# Models, gateways, and coding harnesses

Docket separates three things that are easy to conflate:

- **Coding harness:** Codex, Claude Code, or OpenCode reads this repository's instructions and
  performs development work.
- **Docket model policy:** role-to-model ids chosen by `docket setup model`.
- **Model gateway:** the HTTP endpoint Docket's own turn loop calls.

Changing the coding harness does not change Docket's model policy. OpenRouter and Vercel AI Gateway
are gateway choices, not coding harnesses.

The repository bridge only standardizes instructions, skills, and the bounded snapshot. It does
not route Codex, Claude Code, or OpenCode's own inference through a gateway. Each harness owns that
user-level provider configuration, and its credentials must remain outside the repository.
The gateway setup below is specifically for Docket's runtime.

## Quick setup

OpenRouter has a built-in endpoint mapping. `provider add` reads the key from `OPENROUTER_API_KEY`
or a hidden prompt (`--credential <key>` passes it on the command line), probes `/models`, stores
the key and applies the provider's preset:

```bash
docket setup provider add openrouter
```

For experiments on free models, `docket setup model preset openrouter-free` sends the stable
`openrouter/free` router id. The selected underlying model and availability can change between
calls, so this preset is not a deterministic production baseline.

Vercel AI Gateway also has a built-in mapping:

```bash
docket setup provider add ai-gateway
```

Docket model ids add one routing prefix. For example,
`ai-gateway/anthropic/claude-sonnet-4.6` becomes
`anthropic/claude-sonnet-4.6` on the Vercel wire; similarly,
`openrouter/openrouter/free` becomes `openrouter/free` on OpenRouter. A
`VERCEL_OIDC_TOKEN` is accepted as the AI Gateway fallback credential, although the long-lived
gateway API key is the straightforward local setup.

To mix gateways by policy role, apply one baseline preset and then override named policy roles:

```bash
docket setup provider add openrouter --no-preset
docket setup provider add ai-gateway --no-preset
docket setup model preset openrouter
docket setup model set implementer ai-gateway/anthropic/claude-sonnet-4.6
```

The names `docket setup model set` takes are role names (`lead`, `implementer`, `reviewer` and the
other roles `docket pod roles` lists) or `default`. Applying another preset later replaces the
selection of every named role and the default.

Stored keys are read directly by Docket's model client. Provider environment variables override
the central store for one process, and `DOCKET_LLM_BASE_URL` / `DOCKET_LLM_API_KEY` override every
model at once. Avoid the global override when testing two providers simultaneously; it also makes
the selected endpoint's context/output limits unknown.

## Other OpenAI-compatible endpoints

The `openai-chat` dialect, the default, is a non-streaming `POST /chat/completions` request with
OpenAI function-tool shapes. Every provider — built-in or your own — is a `kind: provider` document
(`models.catalog.ProviderSpec`; see `docs/CONFIGURATION.md` §3.1 and
`specs/functional/model-profiles.spec.md` "Provider catalog"): `name`, `dialect`, `baseUrl`,
`auth` (`bearer`/`header`/`none` plus credential names, never values), optional `headers` for a
static header a gateway requires, and `models[]` with each id's optional declared
`contextWindow`/`maxTokens`. Register a local or other compatible endpoint with the document, or the shortcut:

```bash
docket setup provider add my-provider https://example.invalid/v1 \
  --model creator/model-id --ctx 200000 --max-tokens 8192
docket setup model set implementer my-provider/creator/model-id
```

The exact registered model receives those declared limits in the loop's preflight. A limit you
do not declare is taken from the provider's own `/models` body when it publishes one (recorded
in `provider-models.json` at `provider add` and once a day by `docket start --dispatch`), else it
is unknown; `docket setup provider show <name>` names each limit's source. A second
`provider add` for the same name replaces its document (an unset field inherits from a built-in of
the same name). `docket setup provider export <name> [<file>]` prints (or writes) any provider —
built-in or your own — back out as that same document, which doubles as a starting point for a
gateway close to an existing one, or as a way to version-control your own catalog.

A document may also declare a model profile, which says how docket talks to the models behind it.
`profile: hosted` (the default) changes nothing. `profile: local`, the default for a document with
`local: true`, sends shorter tool descriptions, and when a step names a closing tool (the verdict of
a gated step) makes the reply that asks for no tool one more call that must use that tool. The
document can override `toolSurface` (`full` or `minimal`), `descriptions` (`full` or `compact`),
`toolChoice` (`auto` or `forced-on-close`) and `budgets` (`readWindow`, `toolOutput`: shares of the
context window), and declare `sampling: {temperature, topP}`; sampling is sent only when declared,
so an endpoint's own defaults apply otherwise. `docket status` names each member's profile.
`toolSurface: minimal` is applied to every hop: the request offers `bash`, `read`, `glob`, `edit`,
`write` and `verify`, the step's closing tool, the pod's record tools, and any MCP tool or declared
service operation the role's `tools` allow-list (or the step's, when it declares one) names, as
`mcp__<server>__<tool>` or `mcp__<server>` for every tool of that server. A role with no allow-list
is offered no MCP tool or service operation under `minimal`, and a `send` tool still needs the role's
own list. `full` offers every tool the role may hold.
`budgets` set the turn's tool-output cap and `read` window from the model's context window, never
above `DOCKET_TOOL_MAX_OUTPUT_CHARS`.

Compatibility does not mean feature parity. Docket:

- sends non-streaming requests with ordinary function tools: Chat Completions, or Messages for the
  `anthropic-messages` dialect;
- records prompt/completion and cache-read tokens it understands;
- does not send Responses API fields, gateway routing/provider options, or vendor-specific headers
  beyond a document's own `auth.header` and `headers`;
- does not check a model id against a remote catalog: the ids are the ones a document declares (a
  bare `provider add <name> <url>` takes the first id the endpoint advertises), and `/models` supplies
  only the limits it publishes;
- performs its own retry policy outside any gateway-internal retry/failover: a `Retry-After` the
  endpoint names can push a retry's wait past the linear backoff, but the wait is always capped —
  `min(max(2s × attempt, Retry-After), DISPATCH_RETRY_MAX_WAIT_S)`, `DISPATCH_RETRY_MAX_WAIT_S`
  defaulting to 60s — so one large value never stalls a hop indefinitely, and provider-routing
  options are still not exposed.

The built-in `anthropic` document speaks Anthropic's Messages API (`dialect: anthropic-messages`), so
its requests use the prompt cache, and cache reads and writes are counted in the token usage docket
records. Anthropic's OpenAI-compatibility layer is a different path: a model registered by hand
against it has no prompt caching, `strict` is ignored, and system messages are concatenated.
Anthropic documents that layer as intended to test and compare models, not as a production
solution. The built-in `google` document points at Google's Gemini compatibility layer, which Google
documents as beta. Treat that as a convenience for trying docket against a familiar model, not a
production commitment from the vendor. OpenRouter and Vercel AI Gateway still speak `openai-chat`.

Choose a model only after representative evals for the actual tool schemas and tasks. A model id
being available does not prove reliable tool use. Keep live remote canaries opt-in with an explicit
request budget; the default suite uses deterministic HTTP fakes and no credentials.

Official references: [OpenRouter Chat Completions](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion),
[OpenRouter free router](https://openrouter.ai/docs/guides/routing/routers/free-router),
[Vercel AI Gateway REST API](https://vercel.com/docs/ai-gateway/openai-compat/rest-api),
[Vercel authentication](https://vercel.com/docs/ai-gateway/authentication-and-byok), and
[OpenAI model-selection guidance](https://developers.openai.com/api/docs/guides/latest-model).
