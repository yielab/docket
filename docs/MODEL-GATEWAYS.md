# Models, gateways, and coding harnesses

Docket separates three things that are easy to conflate:

- **Coding harness:** Codex, Claude Code, or OpenCode reads this repository's instructions and
  performs development work.
- **Docket model policy:** role-to-model ids chosen by `docket models`.
- **Model gateway:** the HTTP endpoint Docket's own turn loop calls.

Changing the coding harness does not change Docket's model policy. OpenRouter and Vercel AI Gateway
are gateway choices, not coding harnesses.

The repository bridge only standardizes instructions, skills, and the bounded snapshot. It does
not route Codex, Claude Code, or OpenCode's own inference through a gateway. Each harness owns that
user-level provider configuration, and its credentials must remain outside the repository.
The gateway setup below is specifically for Docket's runtime.

## Quick setup

OpenRouter has a built-in endpoint mapping:

```bash
docket keys add OPENROUTER_API_KEY
docket models preset openrouter
```

For zero-cost experiments, `docket models preset openrouter-free` sends the stable
`openrouter/free` router id. The selected underlying model and availability can change between
calls, so this preset is not a deterministic production baseline.

Vercel AI Gateway also has a built-in mapping:

```bash
docket keys add AI_GATEWAY_API_KEY
docket models preset ai-gateway
```

Docket model ids add one routing prefix. For example,
`ai-gateway/anthropic/claude-sonnet-4.6` becomes
`anthropic/claude-sonnet-4.6` on the Vercel wire; similarly,
`openrouter/openrouter/free` becomes `openrouter/free` on OpenRouter. A
`VERCEL_OIDC_TOKEN` is accepted as the AI Gateway fallback credential, although the long-lived
gateway API key is the straightforward local setup.

To mix gateways by policy role, apply one baseline preset and then override named policy roles:

```bash
docket keys add OPENROUTER_API_KEY
docket keys add AI_GATEWAY_API_KEY
docket models preset openrouter
docket models set programmer ai-gateway/anthropic/claude-sonnet-4.6
```

Use policy names such as `manager` and `programmer`, not pod labels such as Lead and Implementer.
Applying another preset later replaces all seven policy-role selections; explicitly pinned agents
remain pinned until `docket profile <id> default`.

Stored keys are read directly by Docket's model client. Provider environment variables override
the central store for one process, and `DOCKET_LLM_BASE_URL` / `DOCKET_LLM_API_KEY` override every
model at once. Avoid the global override when testing two providers simultaneously; it also makes
the selected endpoint's context/output limits unknown.

## Other OpenAI-compatible endpoints

The shipped wire is a non-streaming `POST /chat/completions` request with OpenAI function-tool
shapes. Register a local or other compatible endpoint explicitly:

```bash
docket models provider add my-provider https://example.invalid/v1 \
  --model creator/model-id --ctx 200000 --max-tokens 8192
docket models set programmer my-provider/creator/model-id
```

The exact registered model receives those context/output limits in the loop's preflight. A second
`provider add` for the same name currently replaces the provider block; multi-model catalog import
is not implemented.

Compatibility does not mean feature parity. Docket currently:

- sends non-streaming Chat Completions and ordinary function tools;
- records prompt/completion and cache-read tokens it understands;
- does not send Responses API fields, gateway routing/provider options, or vendor-specific headers;
- does not discover remote model catalogs or prices;
- performs its own retry policy outside any gateway-internal retry/failover, but does not yet honor
  `Retry-After` delays or expose provider-routing options.

Choose a model only after representative evals for the actual tool schemas and tasks. A model id
being available does not prove reliable tool use. Keep live remote canaries opt-in with an explicit
request/cost budget; the default suite uses deterministic HTTP fakes and no credentials.

Official references: [OpenRouter Chat Completions](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion),
[OpenRouter free router](https://openrouter.ai/docs/guides/routing/routers/free-router),
[Vercel AI Gateway REST API](https://vercel.com/docs/ai-gateway/openai-compat/rest-api),
[Vercel authentication](https://vercel.com/docs/ai-gateway/authentication-and-byok), and
[OpenAI model-selection guidance](https://developers.openai.com/api/docs/guides/latest-model).
