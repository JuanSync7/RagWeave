# LiteLLM Integration — Specification

**Status**: Active
**Date**: 2026-03-19
**Companion doc**: `docs/llm/LITELLM_INTEGRATION.md` (implementation guide)

---

## 1. Scope & Definitions

### 1.1 Problem Statement

The RAG platform must call large language models for multiple purposes — query rewriting,
document reranking, metadata generation, vision analysis, and answer generation. Without a
unified abstraction layer:

- Each call site hard-codes a specific provider API (Ollama, OpenAI, Anthropic, etc.).
- Switching providers requires changes across multiple modules.
- Fallback behaviour, retry logic, and token accounting are duplicated or absent.
- There is no single place to configure which model handles which task.

A unified LLM provider layer eliminates these problems by decoupling callers from providers.

### 1.2 Boundary

**Entry point**: Any application module that needs to invoke an LLM (completion, vision,
embedding, or structured output).

**Exit point**: The response returned by the upstream provider, normalised to a common
response schema and handed back to the caller.

The spec covers the abstraction layer only. It does not cover:

- The upstream provider APIs themselves (Ollama, OpenAI, etc.).
- Prompt construction — callers own their prompts.
- Vector embedding pipelines — covered by the Embedding Pipeline spec.
- Container/deployment infrastructure — covered by `PODMAN_SPEC.md`.

### 1.3 Terminology

| Term | Definition |
|------|-----------|
| **LLM Provider** | The singleton facade module that all callers use to make LLM requests. |
| **Router** | The in-process component (wrapping `litellm.Router`) that resolves aliases, manages fallback chains, and dispatches calls to upstream providers. |
| **Alias** | A logical name for a model role (e.g. `"default"`, `"vision"`). Callers use aliases; the Router maps them to concrete models. |
| **Provider** | An upstream LLM service (e.g. Ollama, OpenAI, Anthropic, Azure OpenAI). |
| **Fallback chain** | An ordered list of provider/model entries tried in sequence when the primary entry fails. |
| **Simple mode** | Configuration via environment variables only; one model handles all aliases. |
| **Router config mode** | Configuration via a YAML file; each alias has its own model list and fallback chain. |
| **Token budget** | A per-request upper bound on prompt + completion tokens. |

### 1.4 Requirement ID Convention

Functional requirements use `FR-xxx` prefixed IDs, grouped by section:

| Prefix range | Section |
|---|---|
| FR-1xx | Provider Abstraction |
| FR-2xx | Configuration |
| FR-3xx | Reliability & Fallback |
| FR-4xx | Observability |
| FR-5xx | Cost & Token Management |
| NFR-9xx | Non-Functional Requirements |

Priority levels follow RFC 2119: **MUST** (mandatory), **SHOULD** (recommended),
**MAY** (optional).

### 1.5 Design Principles

- **Decouple callers from providers**: No call site imports a provider SDK directly. All LLM
  calls go through the LLM Provider facade.
- **Fail gracefully**: A provider outage must degrade to a fallback or a structured error, not
  an unhandled exception.
- **Configuration over code**: Switching providers, adjusting model assignments, and tuning
  retry behaviour must require only configuration changes.
- **Single initialisation**: The Router is constructed once at process startup. No per-request
  initialisation overhead.

### 1.6 Assumptions & Constraints

| Assumption | Impact if violated |
|---|---|
| At least one LLM provider is reachable at startup | Requests will fail; the system logs an error but does not crash |
| Python 3.10+ runtime | LiteLLM SDK compatibility requirement |
| Providers are HTTP-based (REST or compatible) | Non-HTTP providers are out of scope |
| The application is single-process (or each process owns its own Router instance) | Multi-process deployments each need their own singleton; shared state is not supported |

---

## 2. System Overview

```
  ┌──────────────────────────────────────────────────────┐
  │                   Application Modules                │
  │  (query rewrite, rerank, metadata, vision, generate) │
  └────────────────────┬─────────────────────────────────┘
                       │  alias + prompt
                       ▼
  ┌──────────────────────────────────────────────────────┐
  │              LLM Provider (singleton)                │
  │   resolve alias → validate → call Router             │
  └────────────────────┬─────────────────────────────────┘
                       │
                       ▼
  ┌──────────────────────────────────────────────────────┐
  │                 litellm.Router                       │
  │   load balancing · retry · fallback chain            │
  └────┬──────────────┬──────────────┬───────────────────┘
       │              │              │
       ▼              ▼              ▼
  ┌────────┐    ┌────────┐    ┌────────────┐
  │ Ollama │    │ OpenAI │    │ Anthropic  │  (any provider)
  └────────┘    └────────┘    └────────────┘
```

**Data flow summary:**

| Step | Description |
|------|-------------|
| 1 | Caller requests completion using a logical alias (e.g. `"vision"`) |
| 2 | LLM Provider validates the request and resolves the alias |
| 3 | Router selects the concrete model entry for the alias |
| 4 | Router dispatches the call; retries on transient failure |
| 5 | If all entries for the alias fail, the Router tries the fallback chain |
| 6 | Response is normalised and returned to the caller |
| 7 | Telemetry event is emitted (latency, tokens, provider, alias) |

---

## 3. Provider Abstraction (FR-1xx)

> **FR-101** | Priority: MUST
>
> **Description:** The system MUST provide a single facade module as the sole entry point for
> all LLM calls. Application modules MUST NOT import provider SDKs (Ollama, OpenAI, Anthropic,
> etc.) directly.
>
> **Rationale:** Centralising LLM calls in one module allows provider changes, retry logic, and
> observability to be updated in one place without touching every call site.
>
> **Acceptance Criteria:** A grep across the codebase for provider SDK imports outside the LLM
> provider module returns no results.

---

> **FR-102** | Priority: MUST
>
> **Description:** The LLM Provider facade MUST be a singleton — instantiated once at process
> startup and reused for all subsequent calls within that process.
>
> **Rationale:** The Router initialises connection pools and loads configuration. Per-request
> initialisation would add unacceptable overhead and waste resources.
>
> **Acceptance Criteria:** Calling the provider accessor function twice in the same process
> returns the same object instance. No new Router is created after startup.

---

> **FR-103** | Priority: MUST
>
> **Description:** The system MUST support at least the following named aliases: `default`,
> `vision`, `query`, `smart`, `fast`. Each alias represents a model role, not a specific model.
>
> **Rationale:** Callers specify intent ("I need a fast model for query rewriting") rather than
> a concrete model name. This allows model assignments to change via configuration without
> caller changes.
>
> **Acceptance Criteria:** A call made with each of the five aliases routes to the configured
> model for that alias. Changing the model assignment in configuration changes routing without
> code changes.

---

> **FR-104** | Priority: MUST
>
> **Description:** The system MUST support at minimum: standard text completion, JSON-mode
> completion, vision (image + text) completion, and streaming completion. All call types MUST
> use the same alias-based routing.
>
> **Rationale:** Multiple pipeline stages require different call types. A unified interface
> removes the need for stage-specific provider code.
>
> **Acceptance Criteria:** Each call type (text, JSON, vision, streaming) executes successfully
> against a configured provider when called through the facade.

---

> **FR-105** | Priority: SHOULD
>
> **Description:** The system SHOULD support an availability check method that returns whether
> the provider for a given alias is reachable, without making a full inference call.
>
> **Rationale:** Pipeline stages can skip LLM-dependent work gracefully when the provider is
> temporarily unreachable, rather than failing the entire pipeline.
>
> **Acceptance Criteria:** The availability check returns a boolean result within a configurable
> timeout. A positive result correlates with successful subsequent calls to the same alias.

---

## 4. Configuration (FR-2xx)

> **FR-201** | Priority: MUST
>
> **Description:** The system MUST support a **simple mode** where all configuration is
> provided via environment variables and all aliases map to a single model/provider.
>
> **Rationale:** Simple deployments (local development, single-provider installations) must not
> require a YAML config file.
>
> **Acceptance Criteria:** Setting `RAG_LLM_MODEL`, `RAG_LLM_API_BASE`, and optionally
> `RAG_LLM_API_KEY` is sufficient to start the system and serve all aliases.

---

> **FR-202** | Priority: MUST
>
> **Description:** The system MUST support a **router config mode** where a YAML file specifies
> per-alias model lists, fallback chains, and provider parameters. The YAML config path is set
> via a single environment variable.
>
> **Rationale:** Production deployments require distinct models per task (vision vs. fast text),
> per-provider API keys, and fallback chains. These cannot be expressed via flat env vars.
>
> **Acceptance Criteria:** Setting `RAG_LLM_ROUTER_CONFIG=<path>` causes the Router to load
> alias definitions from the YAML file. Per-alias model overrides take effect without code
> changes.

---

> **FR-203** | Priority: MUST
>
> **Description:** The system MUST maintain backward compatibility with legacy Ollama-specific
> environment variables (`RAG_OLLAMA_MODEL`, `RAG_OLLAMA_URL`). When these are set and no
> newer variables are present, they MUST be used as the provider configuration.
>
> **Rationale:** Existing deployments must continue to work without configuration changes after
> the LiteLLM layer is introduced.
>
> **Acceptance Criteria:** A deployment using only legacy Ollama variables starts and serves
> requests identically to the pre-LiteLLM behaviour.

---

> **FR-204** | Priority: MUST
>
> **Description:** The system MUST validate configuration at startup and fail fast with a
> clear, actionable error message if required configuration is absent or contradictory.
>
> **Rationale:** Silent misconfiguration causes hard-to-diagnose failures at request time.
> Failing at startup surfaces the problem immediately.
>
> **Acceptance Criteria:** Starting with no LLM configuration variables set produces an error
> message that names the missing variable(s). Starting with contradictory settings (e.g. router
> config path pointing to a non-existent file) produces an error that identifies the conflict.

---

> **FR-205** | Priority: SHOULD
>
> **Description:** The system SHOULD support per-alias timeout overrides in the router config
> YAML. If no per-alias override is set, a global default timeout MUST apply.
>
> **Rationale:** Vision calls and large context calls inherently take longer than fast text
> calls. A single global timeout either blocks vision calls unnecessarily or allows fast calls
> to hang too long.
>
> **Acceptance Criteria:** A request to the `vision` alias uses the `vision`-specific timeout
> if configured. A request to an alias with no timeout override uses the global default.

---

## 5. Reliability & Fallback (FR-3xx)

> **FR-301** | Priority: MUST
>
> **Description:** The system MUST retry transient provider failures (network errors, HTTP 429,
> HTTP 5xx) up to a configurable maximum retry count before treating a call as failed.
>
> **Rationale:** Transient provider errors (rate limits, brief outages) should not propagate as
> failures to the caller when a retry would succeed.
>
> **Acceptance Criteria:** A simulated HTTP 429 response is retried up to the configured limit.
> After exhausting retries, a structured error is returned (not an unhandled exception).

---

> **FR-302** | Priority: MUST
>
> **Description:** The system MUST support per-alias fallback chains: an ordered list of
> alternative model/provider entries tried in sequence when the primary entry fails after
> retries.
>
> **Rationale:** A fallback from a fine-tuned local model to a cloud model (or vice versa)
> provides resilience against provider-specific outages without operator intervention.
>
> **Acceptance Criteria:** When the primary provider for an alias is unavailable, the Router
> automatically tries the next entry in the fallback chain and returns a successful response
> if that entry is reachable.

---

> **FR-303** | Priority: MUST
>
> **Description:** When a call fails all retry attempts and all fallback chain entries are
> exhausted, the system MUST return a structured error object to the caller. The error MUST
> include the alias used, the provider(s) attempted, and the failure reason.
>
> **Rationale:** Callers must be able to distinguish provider failures from application errors
> and take appropriate action (e.g. return a degraded response, log an alert).
>
> **Acceptance Criteria:** Exhausting all retries and fallbacks returns an exception or error
> object with alias, providers attempted, and reason populated. No bare Python exceptions
> propagate to callers.

---

> **FR-304** | Priority: SHOULD
>
> **Description:** The system SHOULD support exponential backoff with jitter between retry
> attempts.
>
> **Rationale:** Uniform retry intervals can amplify load on a recovering provider. Backoff
> with jitter spreads retry bursts.
>
> **Acceptance Criteria:** Retry intervals increase across attempts and vary between concurrent
> requests hitting the same rate-limited provider.

---

> **FR-305** | Priority: SHOULD
>
> **Description:** When the LLM provider is unavailable and an alias has no reachable fallback,
> pipeline stages that depend on that alias SHOULD degrade gracefully (skip the LLM step,
> return a partial result, or use a deterministic fallback) rather than failing the entire
> pipeline.
>
> **Rationale:** Supports the fail-safe design principle — partial results are better than no
> results when the degraded path is safe and well-defined.
>
> **Acceptance Criteria:** Documented degraded behaviour exists for each LLM-dependent pipeline
> stage. The system does not crash when degraded behaviour is triggered.

---

## 6. Observability (FR-4xx)

> **FR-401** | Priority: MUST
>
> **Description:** The system MUST emit a structured telemetry event for every LLM call,
> capturing at minimum: alias used, concrete model/provider selected, call duration (ms),
> prompt token count, completion token count, and success/failure status.
>
> **Rationale:** Operators need per-call visibility to diagnose latency spikes, token budget
> overruns, and provider-specific failure patterns.
>
> **Acceptance Criteria:** Every LLM call produces a log entry or metric event with all six
> fields populated. Failure events include an error category in addition to the standard fields.

---

> **FR-402** | Priority: MUST
>
> **Description:** Telemetry events MUST NOT include raw prompt text or completion text.
> Only metadata (token counts, latency, alias, model, status) is emitted.
>
> **Rationale:** Prompts may contain user data, retrieved document excerpts, or sensitive
> content. Logging prompt text creates a data leakage risk.
>
> **Acceptance Criteria:** Telemetry log entries contain no prompt or completion text fields.
> Token counts and character counts are acceptable; content is not.

---

> **FR-403** | Priority: SHOULD
>
> **Description:** The system SHOULD expose per-alias aggregate metrics (call count, error
> rate, p50/p95 latency, average token usage) suitable for consumption by a metrics system.
>
> **Rationale:** Aggregate metrics enable alerting on degradation (rising error rate, latency
> spike) without per-event log analysis.
>
> **Acceptance Criteria:** Per-alias call count, error rate, and latency percentiles are
> accessible via the application's existing metrics endpoint or structured log stream.

---

> **FR-404** | Priority: SHOULD
>
> **Description:** When a fallback is triggered, the system SHOULD log which provider was
> tried, which fallback was selected, and why the primary provider failed.
>
> **Rationale:** Silent fallbacks make provider health invisible to operators. Explicit fallback
> events enable root-cause analysis and proactive provider monitoring.
>
> **Acceptance Criteria:** A fallback event produces a log entry naming the original provider,
> the fallback provider, and the failure reason (HTTP status, timeout, connection error).

---

## 7. Cost & Token Management (FR-5xx)

> **FR-501** | Priority: MUST
>
> **Description:** The system MUST count prompt and completion tokens for every call and make
> the counts available to the caller in the response object.
>
> **Rationale:** Callers (e.g. the answer generation stage) need token counts to enforce token
> budgets and to emit accurate cost estimates.
>
> **Acceptance Criteria:** The response object for every call includes `prompt_tokens`,
> `completion_tokens`, and `total_tokens` fields. Values match the provider's reported counts
> where available, or are estimated via a tokeniser where the provider does not return counts.

---

> **FR-502** | Priority: SHOULD
>
> **Description:** The system SHOULD support a configurable token budget per alias: a maximum
> total token count (prompt + completion) beyond which the call is rejected before dispatch.
>
> **Rationale:** Prevents runaway token consumption from oversized prompts, protecting cost
> and latency.
>
> **Acceptance Criteria:** A request with a prompt that exceeds the alias token budget is
> rejected with a structured budget-exceeded error before being dispatched to the provider.
> Requests within budget proceed normally.

---

> **FR-503** | Priority: MAY
>
> **Description:** The system MAY track cumulative estimated cost per alias and per session
> using provider-specific pricing data supplied in configuration.
>
> **Rationale:** Cost tracking enables usage-based alerting and capacity planning. Pricing
> data is external and subject to change, so this is optional.
>
> **Acceptance Criteria:** When pricing configuration is provided, cumulative cost estimates
> are available in the observability output. When pricing configuration is absent, cost fields
> are omitted (not zero).

---

## 8. Non-Functional Requirements (NFR-9xx)

| ID | Priority | Description | Acceptance Criteria |
|----|----------|-------------|---------------------|
| NFR-901 | MUST | The LLM Provider layer MUST add no more than 50 ms overhead to a provider call, excluding network time. | Benchmark: 1,000 calls through the provider layer vs. direct provider SDK calls; p99 overhead ≤ 50 ms. |
| NFR-902 | MUST | The singleton Router MUST be thread-safe. Concurrent calls from multiple threads MUST not corrupt Router state. | Concurrent load test (10 threads, 100 calls each) produces no data races or corrupted responses. |
| NFR-903 | MUST | Router initialisation MUST complete within 2 seconds on application startup. | Timed startup test: `time.time()` before and after initialisation; delta ≤ 2 s. |
| NFR-904 | SHOULD | The LLM Provider module MUST expose a stable public API. Internal implementation details (Router construction, provider SDK imports) MUST NOT be part of the public interface. | Adding a new provider or changing retry logic requires no changes to call sites. |
| NFR-905 | SHOULD | The system SHOULD support hot-reload of router config (re-reading the YAML and reconstructing the Router) without restarting the process. | Changing the YAML file and triggering a reload causes subsequent calls to use the updated configuration. |

---

## 9. Traceability Matrix

| ID | Priority | Section | Description |
|----|----------|---------|-------------|
| FR-101 | MUST | 3 | Single facade; no direct provider SDK imports in callers |
| FR-102 | MUST | 3 | Singleton LLM Provider |
| FR-103 | MUST | 3 | Named aliases: default, vision, query, smart, fast |
| FR-104 | MUST | 3 | Text, JSON, vision, and streaming call types |
| FR-105 | SHOULD | 3 | Availability check method |
| FR-201 | MUST | 4 | Simple mode via environment variables |
| FR-202 | MUST | 4 | Router config mode via YAML |
| FR-203 | MUST | 4 | Backward compatibility with legacy Ollama env vars |
| FR-204 | MUST | 4 | Startup config validation with actionable errors |
| FR-205 | SHOULD | 4 | Per-alias timeout overrides |
| FR-301 | MUST | 5 | Retry on transient failures |
| FR-302 | MUST | 5 | Per-alias fallback chains |
| FR-303 | MUST | 5 | Structured error on exhausted retries/fallbacks |
| FR-304 | SHOULD | 5 | Exponential backoff with jitter |
| FR-305 | SHOULD | 5 | Graceful degradation when provider unavailable |
| FR-401 | MUST | 6 | Per-call telemetry events |
| FR-402 | MUST | 6 | No raw prompt/completion text in telemetry |
| FR-403 | SHOULD | 6 | Per-alias aggregate metrics |
| FR-404 | SHOULD | 6 | Fallback events logged with reason |
| FR-501 | MUST | 7 | Token counts in every response |
| FR-502 | SHOULD | 7 | Configurable token budget per alias |
| FR-503 | MAY | 7 | Cumulative cost tracking with pricing config |
| NFR-901 | MUST | 8 | ≤50 ms provider layer overhead |
| NFR-902 | MUST | 8 | Thread-safe Router |
| NFR-903 | MUST | 8 | Router init ≤2 s |
| NFR-904 | SHOULD | 8 | Stable public API |
| NFR-905 | SHOULD | 8 | Hot-reload of router config |

**Totals:** MUST: 14 · SHOULD: 10 · MAY: 1
