# LiteLLM Integration — Specification Summary

**Companion spec**: `docs/llm/LITELLM_SPEC.md`
**Spec version / date**: Active · 2026-03-19
**Summary purpose**: Concise digest of the companion spec — covers intent, scope, structure, and key decisions without duplicating requirement-level detail.
**See also**: `docs/llm/LITELLM_INTEGRATION.md` (implementation guide) · `docs/llm/README.md`

---

## 1) Generic System Overview

### Purpose

A platform that calls large language models for multiple purposes — query rewriting, document reranking, metadata generation, image analysis, and answer generation — needs a stable, unified interface to those models. Without one, each call site must know which model provider to use and how to talk to it, which means switching providers, adjusting retry behaviour, or adding fallback logic requires touching many modules. This system solves that by sitting between all application code and all model providers as a single indirection layer: callers express what they need (a fast model, a vision-capable model, a reasoning model) and the layer decides how to fulfill that need.

### How It Works

At process startup, the layer is initialised once: it reads configuration, constructs a routing component that knows which model provider to call for each named role, and registers itself as a singleton that all modules will use for the lifetime of the process.

When a caller needs a model response, it passes a logical role name (an alias such as "fast" or "vision") plus a prompt to the facade. The facade validates the request and hands it to the internal router. The router looks up the alias, selects the configured model entry for it, and dispatches the call to the appropriate upstream provider.

If the call fails due to a transient condition — a rate-limit response, a brief network error, a server-side error — the router retries automatically, up to a configured limit, with increasing delay between attempts. If all retry attempts for the primary entry fail, the router walks down an ordered fallback chain, trying alternative provider/model combinations until one succeeds or the chain is exhausted.

When a successful response is received, the facade normalises it to a common structure, attaches token counts, and returns it to the caller. A telemetry event is emitted for every call — whether successful, retried, or failed — capturing timing, token usage, alias, and outcome.

### Tunable Knobs

Operators can choose between a minimal configuration mode (one model handles all roles, configured entirely through environment variables) and a full routing configuration mode (a structured file that assigns distinct model entries to each role, with per-alias fallback chains and timeout overrides). The retry limit, backoff behaviour, and per-alias request timeout are all adjustable. A token budget can be set per alias to reject oversized requests before they are dispatched. Optional cost-tracking is available when pricing data is supplied.

### Design Rationale

Centralising all model calls in one place lets the platform evolve its provider relationships without touching call sites. The single-initialisation pattern avoids per-request connection overhead. Alias-based routing separates the caller's intent from the provider decision, which is what makes provider changes purely a configuration concern. Graceful degradation — returning a partial result rather than failing an entire pipeline — reflects the principle that partial results have more value than hard failures when the degraded path is safe.

### Boundary Semantics

Entry point: any application module that needs a model response invokes the facade with an alias and a prompt. The facade owns everything from alias resolution through provider dispatch and response normalisation. Exit point: the caller receives a normalised response object containing the model output and token counts, or a structured error object if all providers failed. The facade does not own prompt construction, vector embedding pipelines, or deployment infrastructure — those are separate concerns handled by other subsystems.

---

## 2) Scope and Boundaries

**Entry point**: Any application module requesting a model completion (text, JSON-mode, vision, or streaming) using a logical alias.

**Exit point**: A normalised response object returned to the caller, containing the model output and token metadata; or a structured error object when all providers fail.

**In scope:**
- Single facade module as the sole LLM call surface for the platform
- Named alias system mapping roles to provider/model entries
- Simple mode (environment variable configuration) and router config mode (YAML file)
- Backward compatibility with legacy provider-specific environment variables
- Retry logic with configurable limits and exponential backoff
- Per-alias fallback chains
- Structured error propagation on exhausted retries and fallbacks
- Per-call telemetry (latency, token counts, alias, provider, outcome)
- Per-alias aggregate metrics
- Token counting in every response
- Configurable token budget per alias
- Optional cumulative cost tracking with external pricing data
- Availability check method per alias
- Hot-reload of router configuration without process restart

**Out of scope:**
- Upstream provider APIs themselves
- Prompt construction (owned by callers)
- Vector embedding pipelines (covered by the Embedding Pipeline spec)
- Container and deployment infrastructure (covered by the Podman spec)
- Non-HTTP providers

---

## 3) Architecture / Pipeline Overview

```
  Application Modules
  (query rewrite · rerank · metadata · vision · generate)
          |
          |  alias + prompt
          v
  LLM Provider  [singleton facade]
  resolve alias → validate → dispatch
          |
          v
  Internal Router
  load balancing · retry · fallback chain
          |
    +-----+-----+-----+
    v     v     v     v
  Provider A  Provider B  Provider C  ...
  (any HTTP-based model provider)
          |
          v
  Normalised response → caller
  Telemetry event → observability
```

**Stage summary:**

| Step | What happens |
|------|-------------|
| 1 | Caller requests completion using a logical alias |
| 2 | Facade validates the request and resolves the alias |
| 3 | Router selects the concrete model entry for the alias |
| 4 | Router dispatches the call; retries on transient failure |
| 5 | If all entries fail, the Router tries the fallback chain |
| 6 | Response is normalised and returned to the caller |
| 7 | Telemetry event is emitted (latency, tokens, provider, alias) |

---

## 4) Requirement Framework

Requirements use `FR-xxx` prefixed IDs. Priority keywords follow RFC 2119: **MUST** (mandatory), **SHOULD** (recommended), **MAY** (optional).

Each requirement entry includes: a description, a rationale explaining why the requirement exists, and an acceptance criterion specifying how conformance is verified.

**Totals:** 14 MUST · 10 SHOULD · 1 MAY (25 requirements total)

---

## 5) Functional Requirement Domains

| Family | ID Range | Coverage |
|--------|----------|----------|
| **Provider Abstraction** | FR-100s | Single facade entry point, singleton lifecycle, named alias system, supported call types (text, JSON, vision, streaming), availability check |
| **Configuration** | FR-200s | Simple mode via environment variables, router config mode via YAML, backward compatibility with legacy environment variables, startup validation with actionable errors, per-alias timeout overrides |
| **Reliability and Fallback** | FR-300s | Transient-failure retry, per-alias fallback chains, structured error on exhaustion, exponential backoff with jitter, graceful pipeline degradation |
| **Observability** | FR-400s | Per-call telemetry events, exclusion of prompt content from telemetry, per-alias aggregate metrics, fallback event logging with reason |
| **Cost and Token Management** | FR-500s | Token counts in every response, configurable token budget per alias, optional cumulative cost tracking |

---

## 6) Non-Functional and Security Themes

**Performance:**
- The provider layer must add negligible overhead to each call, excluding network time
- The routing component must initialise quickly at process startup

**Concurrency:**
- The singleton router must be thread-safe; concurrent calls must not corrupt internal state

**Stability:**
- The public API surface must remain stable; internal implementation details must not be exposed to callers
- Hot-reload allows configuration updates without process restart

**Security / Data Protection:**
- Raw prompt and completion text must never appear in telemetry events or logs — only metadata (token counts, latency, alias, model, status) is emitted
- This constraint protects against user data and retrieved document content leaking through observability infrastructure

---

## 7) Design Principles

- **Decouple callers from providers** — no call site imports a provider SDK directly; all LLM calls go through the facade
- **Fail gracefully** — provider outages degrade to a fallback or a structured error, not an unhandled exception
- **Configuration over code** — switching providers, adjusting model assignments, and tuning retry behaviour require only configuration changes
- **Single initialisation** — the router is constructed once at process startup; no per-request initialisation overhead

---

## 8) Key Decisions

- **Alias-based routing over direct model naming**: callers express intent ("I need a vision-capable model") rather than naming a specific model, which isolates provider decisions in configuration.
- **Two configuration modes, not one**: simple mode (environment variables) keeps local development frictionless; router config mode (structured file) supports production deployments with per-role model assignments and fallback chains.
- **Backward compatibility required**: the layer must accept legacy provider-specific environment variables so existing deployments are unaffected by the introduction of the abstraction layer.
- **Structured errors, not bare exceptions**: exhausted retries and fallbacks produce typed error objects with alias, providers attempted, and failure reason — callers can distinguish provider failure from application error.
- **Telemetry excludes content**: prompt and completion text are never logged; only metadata is emitted to prevent data leakage through observability infrastructure.

---

## 9) Acceptance and Evaluation

The spec defines acceptance criteria for every requirement. Verification approaches include:

- **Import audit** — codebase scan for provider SDK imports outside the facade module
- **Singleton verification** — process-level check that the accessor returns the same object instance across calls
- **Alias routing tests** — each named alias routes to its configured model; model reassignment takes effect without code changes
- **Retry and fallback simulation** — error injection tests verify retry counts, backoff intervals, and fallback chain traversal
- **Structured error verification** — exhausted retries return typed errors with required fields populated; no bare exceptions propagate
- **Telemetry audit** — log inspection confirms no prompt or completion text appears in emitted events
- **Performance benchmark** — layer overhead measured across a high call volume; initialisation time bounded
- **Concurrency test** — concurrent load test verifies no data races or corrupted responses under parallel calls

No separate evaluation or feedback framework section is defined in the spec.

---

## 10) External Dependencies

| Dependency | Role | Notes |
|-----------|------|-------|
| HTTP-based LLM providers (Ollama, OpenAI, Anthropic, Azure, etc.) | **Required** — upstream model fulfillment | At least one must be reachable at startup; the spec covers the abstraction layer only, not the providers themselves |
| Legacy provider environment variables | **Required for backward compat** | Must be honoured when newer variables are absent |
| YAML router config file | **Required in router config mode** | Path set via environment variable; optional in simple mode |
| External pricing data | **Optional** | Required only for cumulative cost tracking (FR-503); omitting it suppresses cost fields |

**Runtime assumptions:** Python 3.10+ runtime; single-process deployment or each process owns its own singleton (shared state across processes is not supported).

---

## 11) Companion Documents

| Document | Relationship |
|---------|-------------|
| `docs/llm/LITELLM_SPEC.md` | Companion specification — authoritative requirements source; this summary is aligned to it |
| `docs/llm/LITELLM_INTEGRATION.md` | Implementation guide — describes how the spec is realised in code |
| `docs/llm/README.md` | Directory overview |

This summary is a navigational digest. For requirement-level detail, acceptance criteria values, or the traceability matrix, consult the companion spec directly.

---

## 12) Sync Status

| Field | Value |
|-------|-------|
| Spec version | Active · 2026-03-19 |
| Summary written | 2026-04-10 |
| Aligned to | `docs/llm/LITELLM_SPEC.md` (full document, all sections) |
| Next update trigger | Spec version bump or requirement section addition/removal |
