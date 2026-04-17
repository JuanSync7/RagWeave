# Token Budget Tracker — Specification Summary

## 1) Generic System Overview

### Purpose

The token budget tracker gives users and operators continuous visibility into how much of a language model's context window is being consumed by each interaction. Without this system, users have no way to know when context usage is approaching the model's limit — a condition that causes silent input truncation and degraded generation quality. The tracker exists to surface this information as a lightweight, always-visible status signal so users can make informed decisions before quality degrades.

### How It Works

The system operates in two phases: a one-time startup phase and a per-query calculation phase.

At startup, the system queries the active language model's backend for metadata about the model's capabilities — specifically its context window size, architecture family, and parameter count. This metadata is cached in memory for the lifetime of the process. If the backend is unreachable or returns incomplete data, the system substitutes a configurable default context window size and marks the cached capabilities as stale.

On each query, the system estimates the total number of tokens consumed by the prompt. It does this by summing character-length estimates across each prompt component — system prompt, conversation memory, retrieved context chunks, user query, and template formatting — and applying a fixed character-to-token ratio. This arithmetic-only estimation requires no external library and completes in sub-millisecond time. The resulting token count is divided by the effective input budget (context window minus output reservation) to produce a usage percentage.

The calculated snapshot — total estimated tokens, context window size, output reservation, usage percentage, and model name — is made available through two channels. A server-side API endpoint serves the web console in the browser, which renders a persistent status bar at the bottom of the page. The local command-line interface computes the snapshot directly from the same estimation logic and renders a right-aligned summary line after each query response. A remote command-line client fetches the snapshot from the server endpoint instead. Both interfaces apply the same color-coded thresholds — a neutral display at low usage, an amber warning at moderate usage, and a red alert at high usage.

Optional extensions allow the endpoint to accept raw prompt component text and return per-component token breakdowns, and allow operators to trigger a re-fetch of model capabilities at runtime without restarting.

### Tunable Knobs

Four dimensions are operator-configurable via environment variables:

- **Default context window** — the fallback size used when the model backend is unavailable. Controls how conservative the budget estimate is when the true window size cannot be determined.
- **Character-to-token ratio** — the conversion factor applied during estimation. Operators serving non-English content or models with different tokenization behavior can tune this for better accuracy.
- **Warning threshold** — the usage percentage at which the display shifts from neutral to amber. Adjustable for workflows that tolerate higher context density.
- **Critical threshold** — the usage percentage at which the display shifts to red. Adjustable for workflows that require earlier intervention.

All four parameters have documented defaults and take effect on the next startup or refresh cycle.

### Design Rationale

The core design constraint is that token estimation must add zero meaningful latency to the query path. This rules out exact tokenizer libraries, which carry startup and per-call costs. The character-based heuristic is a deliberate trade-off: directional accuracy in exchange for arithmetic simplicity. The system labels its output as an estimate to set appropriate expectations.

Caching model capabilities at startup follows the same principle — the model's context window does not change between requests, so there is no reason to re-fetch it. Graceful fallback to a default ensures the budget indicator remains functional even when the backend is temporarily unavailable; a rough indicator is more useful than no indicator.

Interface parity is a structural requirement: both the web console and command-line client display the same information derived from the same calculation logic. Business rules are not duplicated in interface layers — interfaces are consumers of the shared snapshot.

### Boundary Semantics

Entry point: the system is triggered at application startup (to fetch model capabilities) and again on each completed query (to calculate the current budget snapshot). It receives the model name and backend URL at startup, and raw prompt component text on each query.

Exit point: the system produces a structured snapshot delivered either via an HTTP endpoint (for browser and remote clients) or as a direct Python function return (for the local command-line client). Responsibility ends at the snapshot — rendering decisions (layout, color, fallback text) belong to the consuming interface.

State maintained: model capabilities are cached in memory across requests. The snapshot is not persisted; it is computed and delivered on demand.

---

## 2) Document Header

| Field | Value |
|-------|-------|
| **Companion spec** | `TOKEN_BUDGET_SPEC.md` |
| **Spec version** | 1.0 (Draft) |
| **Summary purpose** | Concise digest of intent, scope, structure, and key decisions |
| **Domain** | Platform / Observability |
| **See also** | `WEB_CONSOLE_SPEC.md`, `CLI_SPEC.md`, `SERVER_API_SPEC.md`, `TOKEN_BUDGET_IMPLEMENTATION.md` |

---

## 3) Scope and Boundaries

**Entry point:** System startup triggers model capability discovery. A completed user query triggers token budget calculation using the assembled prompt components.

**Exit point:** The estimated token count and context usage percentage are rendered in the web console status bar or as a CLI output line after each query response.

**In scope:**
- Model capability discovery (context window size, architecture family, parameter metadata)
- Character-based token estimation for all prompt components
- Budget calculation (effective input budget, usage percentage)
- HTTP API endpoint for web console and remote CLI access
- Web console status bar display with color-coded thresholds
- Local and remote CLI display with matching color-coded thresholds
- Graceful degradation when the model backend or API is unavailable
- Full externalization of configurable parameters

**Out of scope:**
- Precise tokenizer integration (byte-pair encoding libraries or equivalents)
- Automatic actions triggered by high context usage (auto-compact, auto-truncate)
- Per-turn token breakdown visible to the user
- Token usage tracking for billing or quota enforcement
- Embedding model token limits
- Output token counting (output tokens are a fixed reservation, not tracked dynamically)

---

## 4) Architecture / Pipeline Overview

```
  LLM Backend (model info endpoint)
          │
          │  context_length, family, params
          ▼
  ┌─────────────────────────────────────┐
  │ [1] MODEL CAPABILITY DISCOVERY      │
  │     Fetch once at startup, cache.   │
  │     Fall back to default if needed. │  ← optional: runtime refresh
  └──────────────────┬──────────────────┘
                     │  ModelCapabilities
                     ▼
  ┌─────────────────────────────────────┐
  │ [2] TOKEN ESTIMATION & BUDGET CALC  │
  │     Sum chars across prompt parts.  │
  │     Apply ratio → token estimate.   │
  │     Divide by effective budget.     │
  └────────────┬────────────────────────┘
               │  TokenBudgetSnapshot
       ┌───────┴────────┐
       ▼                ▼
  ┌──────────┐    ┌──────────────┐
  │ [3a]     │    │ [3b]         │
  │ CONSOLE  │    │ CLI DISPLAY  │
  │ STATUS   │    │ Right-aligned│
  │ BAR      │    │ line after   │
  │ (via API)│    │ query output │
  └──────────┘    └──────────────┘
       ↑ also: remote CLI fetches via API
```

Stages 3a and 3b share the same snapshot structure and apply identical color-coding thresholds. Stage 1 runs once at startup; Stage 2 runs on every query. Stage 3 (POST variant) optionally accepts prompt text and returns a server-computed snapshot.

---

## 5) Requirement Framework

Requirements use RFC 2119 priority keywords:

- **MUST** — absolute requirement; system is non-conformant without it (18 requirements)
- **SHOULD** — recommended; may be omitted with documented justification (10 requirements)
- **MAY** — optional at implementor's discretion (0 requirements)

**Total: 28 requirements.**

Each requirement follows the format: description, rationale, and acceptance criteria. Every requirement has all three fields.

**ID convention:** `REQ-{section prefix}{sequence}` where the prefix encodes the component domain.

---

## 6) Functional Requirement Domains

| Domain | ID Range | Coverage |
|--------|----------|----------|
| **Model Capability Discovery** | REQ-1xx | Fetching, caching, and falling back for model context window and metadata |
| **Token Estimation & Budget Calculation** | REQ-2xx | Component summation, effective budget computation, snapshot structure, per-component breakdown |
| **API Endpoint** | REQ-3xx | GET and POST endpoint contract, caching behavior, stale flag |
| **Web Console Display** | REQ-4xx | Status bar rendering, post-query update, color thresholds, pre-fetch on load, graceful fallback |
| **CLI Display** | REQ-5xx | Local and remote CLI line format, color thresholds, graceful fallback |
| **Non-Functional Requirements** | REQ-9xx | Latency limits, graceful degradation coverage, configuration externalization, startup logging |

---

## 7) Non-Functional and Security Themes

- **Performance** — Token estimation is bounded to sub-millisecond execution for large inputs. No network calls, file I/O, or heavy library imports occur in the estimation path. The API endpoint returns cached data and must respond quickly.
- **Graceful degradation** — All five failure scenarios (backend unreachable, API error, missing context field, empty prompt component, terminal width detection failure) have defined fallback behaviors. No scenario may propagate an unhandled exception.
- **Configurability** — All operator-facing parameters (default context window, char-per-token ratio, warning threshold, critical threshold) are externalized to environment variables with documented defaults.
- **Observability** — A startup log line confirms the discovered model and context window size (or flags fallback usage), enabling operators to verify correct configuration without inspecting internal state.

---

## 8) Design Principles

| Principle | Description |
|-----------|-------------|
| **Observability over precision** | A rough but visible estimate is more useful than no indicator. Estimation is clearly labeled, not presented as exact. |
| **Zero-cost when idle** | Model capability discovery runs once at startup and is cached. Per-query estimation is arithmetic only — no I/O, no library loading. |
| **Graceful degradation** | Every failure mode has a defined fallback. The system does not block query processing when informational components are unavailable. |
| **Interface parity** | Web console and CLI display identical information from identical calculation logic. No business rules live in interface layers. |

---

## 9) Key Decisions

- **Character-based heuristic over tokenizer library** — Chosen to avoid startup time and memory overhead. Accepted trade-off: estimation accuracy within ±25% for English text, clearly labeled as an estimate.
- **Startup-time caching** — Model capabilities are fetched and cached once rather than per-request. This eliminates per-query latency at the cost of requiring an explicit refresh when the model changes at runtime.
- **Stale flag** — Rather than silently using a fallback default, the API exposes a `stale` boolean so consuming interfaces can communicate uncertainty to the user.
- **Shared calculation module** — Both CLI and web console consume the same estimation logic. The API endpoint and direct Python import are two delivery paths for one implementation, ensuring parity is structural rather than maintained by convention.
- **Three-phase delivery** — The spec structures implementation across three phases: core module and API, interface integration, then enhancements (per-component breakdown, POST endpoint, capability refresh). This allows the core observability loop to ship before optional features.

---

## 10) Acceptance and Evaluation

The spec defines five system-level acceptance criteria:

- Token estimation accuracy within a specified tolerance of actual tokenizer output for English text
- Budget display visible in both web console and CLI interfaces after every query
- All five graceful degradation scenarios pass without crash or unhandled exception
- No measurable latency regression added to the query path by token budget calculation
- All four configurable parameters adjustable via environment variable without code changes

Acceptance criteria are attached to individual requirements (rationale + AC per requirement) and aggregated in the system-level criteria table in the spec. The spec does not define a feedback or evaluation framework beyond these conformance checks.

---

## 11) External Dependencies

**Required services:** None. Token estimation and budget calculation are self-contained.

**Optional services:**

| Service | Purpose | Fallback |
|---------|---------|---------|
| LLM backend model-info endpoint | Fetches accurate context window size for the active model | Configurable default context window; capabilities marked stale |

**Downstream consumers (contracts this system must honor):**

| Consumer | Interface |
|----------|-----------|
| Web console (browser) | `GET /console/token-budget` — model capabilities response |
| Web console (browser) | `POST /console/token-budget` — server-computed budget snapshot (optional) |
| Remote CLI client | `GET /console/token-budget` — model capabilities response |
| Local CLI | Direct Python module import |

---

## 12) Companion Documents

This summary is a digest of `TOKEN_BUDGET_SPEC.md` (Layer 3 Authoritative Spec). It is not a replacement — individual requirement text, acceptance criteria values, and the traceability matrix live in the spec.

| Document | Relationship |
|----------|-------------|
| `TOKEN_BUDGET_SPEC.md` | Source of truth — this summary tracks it |
| `TOKEN_BUDGET_IMPLEMENTATION.md` | Implementation companion to the spec |
| `WEB_CONSOLE_SPEC.md` | Parent surface spec; token budget status bar is a new element within it |
| `CLI_SPEC.md` | Parent surface spec; token budget line extends CLI output format |
| `SERVER_API_SPEC.md` | Defines envelope and auth conventions used by the token budget endpoint |

**Document chain:**
```
TOKEN_BUDGET_SPEC.md  →  TOKEN_BUDGET_SPEC_SUMMARY.md  →  (design doc)  →  TOKEN_BUDGET_IMPLEMENTATION.md
```

---

## 13) Sync Status

| Field | Value |
|-------|-------|
| **Spec version** | 1.0 (Draft) |
| **Spec date** | 2026-03-13 |
| **Summary written** | 2026-04-10 |
| **Summary status** | In sync |
