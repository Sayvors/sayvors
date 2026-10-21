# LLM gateway

Every model generation call goes through `app/modules/llm/gateway.py`. It is
the only public door to a provider: resolution, provider selection, the budget
gate and metering live there, so a feature module cannot accidentally ship a
call that skips any of them.

## Layering

```
feature modules                     analytics, assistant, review_engine,
                                    channels, posts, profile, admin, rag
        │
        ▼
app/modules/llm/gateway.py          public interface: complete / stream
        │                           + resolve_model / ensure_usable /
        │                             resolve_tenant_model
        ▼
app/modules/llm/providers/          registry, catalog, transport
        ├── registry.py             provider instances, admin overlays
        ├── base.py                 LLMRequest / LLMResponse / budget + metering
        ├── openai_compatible.py    OpenAI, Groq, Grok, Kimi, DeepSeek, OpenRouter, Ollama
        └── gemini.py               Google Gemini
```

The dependency direction is one-way: `features → llm.gateway`. Providers are
internal to `app/modules/llm/`; `tests/test_llm_gateway_boundary.py` enforces
that no other package imports `LLMRequest`, `LLMProvider`,
`get_provider_for_model`, or `llm.service._resolve_model`.

Curation reads are exempt: listing tenant models and probing a provider key
(`list_tenant_models`, `resolve_provider_key`) touch configuration, not
generation, and are allowed from admin/channel code.

## Public interface

```python
from app.modules.llm.gateway import LLMMessage, complete

resp = await complete(
    model=model_id,                       # catalog id, e.g. "groq:oss-120b"
    messages=[LLMMessage(role="user", content=prompt)],
    system_prompt=SYSTEM_PROMPT,
    temperature=0.2,
    max_tokens=800,
    tenant_id=tenant_id,                  # None = system call, never gated
    purpose="review_engine.generate",     # required
    channel_id=channel_id,                # optional attribution
)
text = resp.content
```

* `model` is always the **catalog** id. The gateway resolves it to the
  provider's own model name; callers never do the lookup themselves.
* `purpose` is keyword-only and has no default. An LLM call nobody can
  attribute is a cost nobody budgeted for.
* `tenant_id` scopes the budget. Pass the tenant for any call the customer can
  trigger; pass `None` only for admin probes and genuinely system-wide work.
* Errors surface as `ProviderError` with the provider's HTTP status; feature
  modules already translate that into their own fallback or HTTP response.

Streaming:

```python
from app.modules.llm.gateway import LLMMessage, stream

async for chunk in stream(
    model=model_id,
    messages=messages,
    tenant_id=tenant_id,
    purpose="assistant.chat",
):
    yield chunk
```

`stream` records one usage event when the stream ends, including the
`cancelled` status when the client disconnects mid-reply.

Other exports: `resolve_model()` returns a `ResolvedModel(model_id, api_model,
provider)`; `ensure_usable()` additionally fails when the provider has no key
or is disabled (used by the databank agent to fall back across candidates);
`resolve_tenant_model(db, preferred=None)` returns the tenant's single enabled
model id and raises `ValueError` when the admin has enabled none.

## Budget and metering

| Path | Pre-authorization | Settlement | Usage event |
|---|---|---|---|
| `complete()` | reserves `RESERVE_CENTS` inside `provider.complete` | refunds `reserve − actual` using the provider's token counts | yes, with real usage |
| `stream()` | reserves `RESERVE_CENTS` before the first chunk | refunds `reserve − estimated cost` in `finally` | yes, prompt + completion **estimated** at 4 chars/token |

The authoritative budget gate is the gateway. Before it existed, the LLM chat
router reserved and settled around the same `provider.complete` call, which
charged the real cost twice. The router now performs a read-only balance check
for the friendly HTTP 402 and leaves the charge to the gateway.

Streamed responses do not carry token usage from any provider, so the gateway
estimates both sides from characters and settles once. A provider failure
refunds the reservation; a client disconnect still charges for the text that
was delivered and records the event as `cancelled`. When the upstreams start
reporting stream usage (`stream_options={"include_usage": true}` for
OpenAI-compatible providers), only this estimator needs to change.

## What stays in the feature module

| Concern | Owner | Example |
|---|---|---|
| Prompt and system message | Feature | Review engine's response policy |
| Temperature / token cap | Feature | `max_tokens=160` for a dashboard headline |
| Model choice | Feature or tenant | `resolve_tenant_model(db)` |
| Fallback behaviour | Feature | Heuristic enrichment on provider failure |
| Delivery | Channel | Voice note vs text; SSE vs JSON |

The gateway owns only the mechanics every call must share.

## Adding a caller

1. Import `LLMMessage` and `complete` (or `stream`) from
   `app.modules.llm.gateway`.
2. Pick the model id — usually `resolve_tenant_model(db)`, or a fixed catalog
   id for a specialised job.
3. Pass a dotted `purpose` (`analytics.enrichment`, `posts.ai_draft`, …).
4. Pass `tenant_id` whenever the call is attributable to a tenant.
5. Handle `ProviderError` the way the feature needs — degrade, retry or fail
   loudly. Never swallow it without a log.

Do not import `llm.providers.*` and do not build an `LLMRequest`. The boundary
test will fail if you do.

## Extraction checklist

The module is already a self-contained package behind one interface. Before it
can become its own service:

- [x] One public entry point (`gateway.complete` / `gateway.stream`).
- [x] Plain-data request/response types re-exported across the boundary.
- [x] No feature module imports provider internals (enforced by test).
- [x] Budget and metering happen inside the boundary for `complete` and
      `stream` (streamed costs estimated at 4 chars/token).
- [ ] Exact streamed settlement (needs upstream usage reporting; the estimator
      is the only code to replace).
- [ ] Metering table owned by a platform module instead of `llm.usage`.
