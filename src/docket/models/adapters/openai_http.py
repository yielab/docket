"""OpenAI-compatible chat-completions adapter.

The one shipped implementation of ``agent/ports.py``'s ``ChatBackend`` port, and
the **only** module in docket that knows what a chat-completions request or
response looks like on the wire. Everything above it — the turn loop, the tool
dispatcher, the gates — speaks ``ChatMessage``/``ToolCall``/``ChatResponse``.

**Zero new dependencies, on purpose.** The protocol is an HTTP POST with a JSON
body; stdlib ``urllib`` covers it. Pulling in a vendor SDK to do that would
re-introduce exactly the coupling docket deliberately avoids, and the standing
ban on hand-rolled *per-vendor* clients is not in tension with this: there is
one client here for one open protocol, not one per provider. llama.cpp, vLLM,
LM Studio, OpenAI, Groq, Together and OpenRouter all speak it.

**What this module refuses to do:** decide anything. It does not retry (that
policy lives in ``hops/application/runner.py``, keyed on ``FailureKind``), does not
inspect tool calls (that is the gate's job), and does not raise for endpoint
failures — every ordinary failure comes back as ``ChatResponse(ok=False, ...)``
so the caller stays in control of what happens next.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from docket.agent import ports as _ports
from docket.agent.ports import ChatMessage, ChatResponse, Endpoint, ModelLimits, ToolSpec
from docket.kernel import clock as _clock
from docket.models.adapters.openai_wire import (
    _classify_http_status,
    _retry_after_seconds,
    build_payload,
    decode_response,
    request_part_bytes,
)
from docket.platform import open_same_origin

if TYPE_CHECKING:
    from docket.models.catalog import ProviderSpec
from docket.governance import secrets as _secrets
from docket.models import catalog as _prov

_PROTOCOL_OVERHEAD_TOKENS = 16


class OpenAIChatClient:
    """``ChatBackend`` over an OpenAI-compatible ``/v1/chat/completions``.

    Stateless apart from its ``Endpoint`` — safe to construct per call or hold
    for the life of a loop.
    """

    def __init__(self, endpoint: Endpoint) -> None:
        self.endpoint = endpoint

    @property
    def url(self) -> str:
        return f"{self.endpoint.base_url.rstrip('/')}/chat/completions"

    @property
    def context_window_tokens(self) -> int | None:
        return self.endpoint.context_window_tokens

    @property
    def max_output_tokens(self) -> int | None:
        return self.endpoint.max_output_tokens

    def estimate_input_tokens(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> int:
        """Estimate the exact prospective JSON payload plus HTTP framing.

        The payload is built by the same function transport uses. The fixed
        framing allowance covers request-line/header/tokenizer separators; the
        result remains the documented bytes-per-token estimate, never measured
        model usage.
        """
        payload = build_payload(self.endpoint, messages, tools, max_tokens, temperature)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return max(1, _ports.estimate_tokens(encoded)) + _PROTOCOL_OVERHEAD_TOKENS

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.endpoint.auth_type == "bearer" and self.endpoint.api_key:
            headers["Authorization"] = f"Bearer {self.endpoint.api_key}"
        elif self.endpoint.auth_type == "header" and self.endpoint.api_key:
            headers[self.endpoint.auth_header] = self.endpoint.api_key
        headers.update(self.endpoint.headers)
        return headers

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        """Send one exchange. Never raises for an endpoint or transport failure."""
        start = _clock.monotonic()

        def _elapsed_ms() -> int:
            return int((_clock.monotonic() - start) * 1000)

        if not self.endpoint.base_url:
            return ChatResponse(
                ok=False,
                error="no endpoint configured for this model",
                failure_kind="daemon_error",
                model=self.endpoint.model_id,
                provider=self.endpoint.provider,
                latency_ms=_elapsed_ms(),
            )
        payload = build_payload(self.endpoint, messages, tools, max_tokens, temperature)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8", errors="replace")
        request = urllib.request.Request(
            self.url, data=body, headers=self._headers(), method="POST"
        )
        try:
            with open_same_origin(request, timeout=timeout) as resp:
                raw_body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as ex:
            # The body of an error response is where the useful message lives
            # (an unknown model, a bad key, a context-length overflow); reading
            # it can itself fail on a truncated response, hence the guard.
            try:
                detail = ex.read().decode("utf-8", errors="replace").strip()
            except OSError:
                detail = ""
            failure_kind = _classify_http_status(ex.code)
            retry_after = (
                _retry_after_seconds(ex.headers) if failure_kind == "daemon_error" else None
            )
            return ChatResponse(
                ok=False,
                error=f"HTTP {ex.code} from {self.url}: {detail[:500] or ex.reason}",
                failure_kind=failure_kind,
                retry_after_s=retry_after,
                model=self.endpoint.model_id,
                provider=self.endpoint.provider,
                latency_ms=_elapsed_ms(),
            )
        except TimeoutError:
            return ChatResponse(
                ok=False,
                error=f"timed out after {timeout}s calling {self.url}",
                failure_kind="timeout",
                model=self.endpoint.model_id,
                provider=self.endpoint.provider,
                latency_ms=_elapsed_ms(),
            )
        except urllib.error.URLError as ex:
            # urlopen wraps a socket timeout in URLError on some platforms, so
            # the check above is not sufficient on its own.
            if isinstance(ex.reason, TimeoutError):
                return ChatResponse(
                    ok=False,
                    error=f"timed out after {timeout}s calling {self.url}",
                    failure_kind="timeout",
                    model=self.endpoint.model_id,
                    provider=self.endpoint.provider,
                    latency_ms=_elapsed_ms(),
                )
            return ChatResponse(
                ok=False,
                error=f"cannot reach {self.url}: {ex.reason}",
                failure_kind="daemon_error",
                model=self.endpoint.model_id,
                provider=self.endpoint.provider,
                latency_ms=_elapsed_ms(),
            )
        except OSError as ex:
            return ChatResponse(
                ok=False,
                error=f"cannot reach {self.url}: {ex}",
                failure_kind="daemon_error",
                model=self.endpoint.model_id,
                provider=self.endpoint.provider,
                latency_ms=_elapsed_ms(),
            )

        try:
            data = json.loads(raw_body) if raw_body.strip() else {}
        except json.JSONDecodeError as ex:
            return ChatResponse(
                ok=False,
                error=f"endpoint returned non-JSON ({ex}): {raw_body[:200]}",
                failure_kind="invalid_output",
                model=self.endpoint.model_id,
                provider=self.endpoint.provider,
                latency_ms=_elapsed_ms(),
            )
        if not isinstance(data, dict):
            return ChatResponse(
                ok=False,
                error=f"endpoint returned a {type(data).__name__}, expected an object",
                failure_kind="invalid_output",
                model=self.endpoint.model_id,
                provider=self.endpoint.provider,
                latency_ms=_elapsed_ms(),
            )
        return replace(
            decode_response(data),
            model=self.endpoint.model_id,
            provider=self.endpoint.provider,
            latency_ms=_elapsed_ms(),
            request_bytes=request_part_bytes(payload),
        )


# ── registration probe ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProbeResult:
    """A raw, unclassified probe of a provider's ``/models`` route. ``status`` is ``None``
    only for a transport failure (DNS, refused, timeout) -- classification into a registration
    outcome is ``models/catalog.py::verify_endpoint``'s job, kept pure and out of this module."""

    status: int | None
    transport_error: str = ""
    model_ids: list[str] = field(default_factory=list)
    limits: dict[str, ModelLimits] = field(default_factory=dict)


def _extract_model_ids(raw_body: str) -> list[str]:
    """Best-effort ``{"data": [{"id": ...}, ...]}`` extraction. Any other shape yields no ids
    rather than raising -- this is a suggestion surface, never a hard requirement."""
    try:
        data = json.loads(raw_body) if raw_body.strip() else {}
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    rows = data.get("data")
    if not isinstance(rows, list):
        return []
    return [row["id"] for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str)]


def _positive_int(value: Any) -> int | None:
    """*value* when it is a positive integer, else ``None`` (unknown): absent, null, zero, a
    string, a float and a bool are all unknown."""
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _first_limit(*candidates: Any) -> int | None:
    for candidate in candidates:
        found = _positive_int(candidate)
        if found is not None:
            return found
    return None


def _row_limits(row: dict[str, Any]) -> ModelLimits:
    """One `/models` row's window and output cap, the wire shape told by field presence;
    `meta.n_ctx` is the loaded context, never `n_ctx_train`."""
    meta = row.get("meta")
    top = row.get("top_provider")
    return ModelLimits(
        context_window=_first_limit(
            row.get("max_input_tokens"),
            row.get("context_window"),
            meta.get("n_ctx") if isinstance(meta, dict) else None,
            row.get("context_length"),
        ),
        max_output=_first_limit(
            row.get("max_tokens"),
            top.get("max_completion_tokens") if isinstance(top, dict) else None,
        ),
    )


def _extract_model_limits(raw_body: str) -> dict[str, ModelLimits]:
    """Each advertised id's published limits, ``{}`` for any body that is not a `data` list."""
    try:
        data = json.loads(raw_body) if raw_body.strip() else {}
    except json.JSONDecodeError:
        return {}
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return {}
    return {
        row["id"]: _row_limits(row)
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }


def probe_models(endpoint: Endpoint, timeout: float = 5.0) -> ProbeResult:
    """GET ``<base-url>/models`` with *endpoint*'s own credential headers. Never raises: an
    ``HTTPError`` yields its status and any ids the body still advertises; a transport
    failure (``URLError``, timeout, other ``OSError``) yields ``status=None`` with the error."""
    url = f"{endpoint.base_url.rstrip('/')}/models"
    request = urllib.request.Request(url, headers=OpenAIChatClient(endpoint)._headers())
    try:
        with open_same_origin(request, timeout=timeout) as resp:
            status = resp.status
            raw_body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as ex:
        try:
            raw_body = ex.read().decode("utf-8", errors="replace")
        except OSError:
            raw_body = ""
        return ProbeResult(status=ex.code, model_ids=_extract_model_ids(raw_body))
    except TimeoutError as ex:
        return ProbeResult(status=None, transport_error=str(ex) or "timed out")
    except urllib.error.URLError as ex:
        return ProbeResult(status=None, transport_error=str(ex.reason))
    except OSError as ex:
        return ProbeResult(status=None, transport_error=str(ex))

    if status != 200:
        return ProbeResult(status=status)
    return ProbeResult(
        status=status,
        model_ids=_extract_model_ids(raw_body),
        limits=_extract_model_limits(raw_body),
    )


# ── endpoint resolution ───────────────────────────────────────────────────────


def resolve_endpoint(model: str) -> Endpoint | None:
    """Resolve a ``provider/model-id`` string to a callable endpoint.

    Precedence, highest first:

    1. ``DOCKET_LLM_BASE_URL`` / ``DOCKET_LLM_API_KEY`` — a process-wide
       override that points every model at one endpoint. Exists for local
       development and for tests that want a stub server without touching
       stored config.
    2. The provider catalog entry for ``<provider>`` (``models/catalog.py``'s
       ``load_catalog``) — built-in overridden by the operator's own (global), nearest-wins.
    3. ``DOCKET_LLM_BASE_URL`` alone, only for a provider absent from the catalog (every hosted
       gateway docket knows ships as a built-in catalog document; this step is the one escape
       hatch left for a provider that is neither).

    For a catalog entry, the API key comes from ``models/catalog.py``'s ``resolve_credential``
    (``DOCKET_LLM_API_KEY`` -> environment -> Docket's central key store, per name in
    ``auth.credentials``). For a provider absent from the catalog, the key falls back through
    ``DOCKET_LLM_API_KEY``, then the derived ``<PREFIX>_API_KEY`` environment variable, then the
    same name in the central key store. Returns ``None`` when no base URL can be found, so
    callers report an actionable "no endpoint configured" rather than posting into the void.
    """
    provider, _, model_id = model.partition("/")
    if not model_id:
        provider, model_id = "", model

    env_base = os.environ.get("DOCKET_LLM_BASE_URL", "").strip()
    env_key = os.environ.get("DOCKET_LLM_API_KEY", "").strip()

    spec = None
    if provider and not env_base:
        spec = _prov.load_catalog().get(provider)

    if spec is not None:
        api_key, _source = _prov.resolve_credential(spec)
        return endpoint_from_spec(spec, provider, model_id, api_key)

    # Absent from the catalog: only DOCKET_LLM_BASE_URL can resolve it, deriving the
    # credential's env name from the provider prefix (never a per-provider literal here).
    base_url = env_base
    if not base_url:
        return None

    api_key = env_key
    if not api_key and provider:
        credential_name = f"{provider.upper().replace('-', '_')}_API_KEY"
        api_key = os.environ.get(credential_name, "").strip()
        if not api_key:
            api_key = _secrets.secret_value(credential_name) or ""

    return Endpoint(
        base_url=base_url,
        model_id=model_id,
        api_key=api_key,
        provider=provider,
        context_window_tokens=None,
        max_output_tokens=None,
    )


def endpoint_from_spec(spec: ProviderSpec, provider: str, model_id: str, api_key: str) -> Endpoint:
    """The endpoint catalog entry *spec* (named *provider*) gives *model_id*, with *api_key*
    already resolved; each limit is declared, else observed, else unknown."""

    limits = _prov.resolve_limits(spec, model_id)
    return Endpoint(
        base_url=spec.base_url,
        model_id=model_id,
        api_key=api_key,
        provider=provider,
        context_window_tokens=limits.context_window,
        max_output_tokens=limits.max_output,
        auth_type=spec.auth.type,
        auth_header=spec.auth.header,
        headers=tuple(spec.headers.items()),
    )


_DIALECTS: dict[str, type[OpenAIChatClient]] = {"openai-chat": OpenAIChatClient}


def client_for_endpoint(
    endpoint: Endpoint, dialect: str = "openai-chat"
) -> OpenAIChatClient | None:
    """A client for an already-resolved *endpoint*, or ``None`` when *dialect* has no adapter."""
    client_cls = _DIALECTS.get(dialect)
    return client_cls(endpoint) if client_cls else None


def client_for(model: str) -> OpenAIChatClient | None:
    """Build a client for ``provider/model-id``, or ``None`` if unresolvable or the
    resolved provider's ``dialect`` has no adapter in ``_DIALECTS``."""
    endpoint = resolve_endpoint(model)
    if endpoint is None:
        return None
    dialect = "openai-chat"
    if endpoint.provider:
        spec = _prov.load_catalog().get(endpoint.provider)
        if spec is not None:
            dialect = spec.dialect
    return client_for_endpoint(endpoint, dialect)
