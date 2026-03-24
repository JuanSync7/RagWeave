# LiteLLM Multi-Tenant Cost Tracking

**Status:** Not yet implemented — placeholders in code mark the two required changes.

**Why this matters:** The current setup uses a single SQLite file inside the container.
This is fine for a single-server dev environment, but breaks when:
- Running multiple API replicas (each has its own disconnected SQLite)
- You need per-user cost/token reporting for billing or quotas

---

## Current state

LiteLLM writes `~/.litellm/litellm.db` (SQLite) inside the `rag-api` container.
All requests from all end-users are lumped together with no per-user attribution.

---

## Required changes

### 1. Switch LiteLLM to PostgreSQL (`docker-compose.yml`)

Add `DATABASE_URL` to the `rag-api` environment block.
You can reuse the existing `rag-temporal-db` Postgres instance or add a dedicated one.

```yaml
# docker-compose.yml — rag-api environment
- DATABASE_URL=postgresql://litellm:litellm@rag-postgres:5432/litellm
```

LiteLLM auto-migrates its schema on first start when `DATABASE_URL` is set.

> See the `TODO(multi-tenant)` comment in `docker-compose.yml`.

---

### 2. Pass `user` tag on every LiteLLM call (`src/platform/llm/provider.py`)

LiteLLM records spend per `user` key. Thread the authenticated user's ID
through to `_base_kwargs`:

```python
# provider.py — _base_kwargs
def _base_kwargs(
    self, model_alias: str = "default", user_id: str | None = None, **overrides: Any
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "model": model_alias,
        "max_tokens": self.config.max_tokens,
        "temperature": self.config.temperature,
    }
    if user_id:
        kwargs["user"] = user_id   # LiteLLM uses this for per-user spend tracking
    kwargs.update(overrides)
    return kwargs
```

All callers (`generate`, `generate_stream`, `agenerate`, `agenerate_stream`)
pass `user_id` through from the `Principal.subject` resolved by `authenticate_request`.

> See the `TODO(multi-tenant)` comment in `src/platform/llm/provider.py`.

---

### 3. Thread `user_id` from route handlers to the provider

In `server/routes/query.py`, the `principal` object is already available:

```python
# Current
for token in _stream_llm(processed_query, context_texts, scores, ...):
    ...

# After change
for token in _stream_llm(processed_query, context_texts, scores, ..., user_id=principal.subject):
    ...
```

Update `_stream_llm` and `_stream_llm`'s call to `provider.generate_stream`
to forward `user_id`.

---

## Querying spend data

Once PostgreSQL and user tagging are in place, LiteLLM exposes a `/spend` API
(if running LiteLLM Proxy), or you can query the `litellmspendlogs` table directly:

```sql
SELECT user, SUM(total_tokens) AS tokens, SUM(spend) AS cost_usd
FROM litellmspendlogs
GROUP BY user
ORDER BY cost_usd DESC;
```

---

## Checklist

- [x] Add `DATABASE_URL` to `docker-compose.yml` (rag-api environment)
- [x] Create Postgres database and user for LiteLLM (`rag-postgres` service)
- [ ] Add `user_id` parameter to `LLMProvider._base_kwargs`
- [ ] Update `generate`, `generate_stream`, `agenerate`, `agenerate_stream` signatures
- [ ] Thread `principal.subject` through from all route handlers
- [ ] Verify spend logs are written to Postgres after a test query
