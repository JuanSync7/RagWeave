# Token Budget Tracker Specification

**AION Knowledge Management Platform**
Version: 1.0 | Status: Draft | Domain: Platform / Observability

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-13 | AI Assistant | Initial specification |

> **Document intent:** This is a normative requirements/specification document for the token budget tracker subsystem.
> For the implementation plan, see `TOKEN_BUDGET_IMPLEMENTATION.md`.
> For related console UX, see `WEB_CONSOLE_SPEC.md`. For CLI display, see `CLI_SPEC.md`.

---

## 1. Scope & Definitions

### 1.1 Problem Statement

The RAG system sends multi-component prompts (system prompt, memory context, retrieved chunks, user query) to an LLM with a finite context window. Users have no visibility into how much of that window each interaction consumes. When context usage is high, generation quality degrades or the LLM silently truncates input — but users see no warning. Without a budget indicator, users cannot make informed decisions about when to compact a conversation, reduce retrieval depth, or switch to a larger model.

### 1.2 Scope

This specification defines requirements for the **token budget tracker** subsystem. The boundary is:

- **Entry point:** The system starts up and queries the LLM backend for model capabilities; a user submits a query that produces an LLM prompt.
- **Exit point:** The estimated token count and context window usage percentage are displayed to the user in the web console status bar or CLI output line.

Everything between these points is in scope: model capability discovery, token estimation, budget calculation, API exposure, and display rendering in both console and CLI interfaces.

### 1.3 Terminology

| Term | Definition |
|------|-----------|
| **Context Window** | The maximum number of tokens an LLM can process in a single request (input + output combined) |
| **Token Budget** | The remaining capacity in the context window after accounting for all prompt components and the output reservation |
| **Input Tokens** | The estimated total tokens consumed by all prompt components sent to the LLM (system prompt, memory context, retrieved chunks, user query, template overhead) |
| **Output Reservation** | The maximum number of tokens reserved for generation output (`GENERATION_MAX_TOKENS`), which reduces the available input budget |
| **Context Usage** | The ratio of estimated input tokens to the effective input budget, expressed as a percentage |
| **Model Capabilities** | Metadata about the active LLM model including context window size, architecture family, and parameter count — fetched from the backend provider |
| **Token Estimation** | A lightweight heuristic that approximates token count from character length without loading a full tokenizer |

### 1.4 Requirement Priority Levels

This document uses RFC 2119 language:

- **MUST** — Absolute requirement. The system is non-conformant without it.
- **SHOULD** — Recommended. May be omitted only with documented justification.
- **MAY** — Optional. Included at the implementor's discretion.

### 1.5 Requirement Format

> **REQ-xxx** | Priority: MUST/SHOULD/MAY
> **Description:** What the system shall do.
> **Rationale:** Why this requirement exists.
> **Acceptance Criteria:** How to verify conformance.

Requirements are grouped by section with the following ID ranges:

| Section | ID Range | Component |
|---------|----------|-----------|
| Section 3 | REQ-1xx | Model Capability Discovery |
| Section 4 | REQ-2xx | Token Estimation & Budget Calculation |
| Section 5 | REQ-3xx | API Endpoint |
| Section 6 | REQ-4xx | Web Console Display |
| Section 7 | REQ-5xx | CLI Display |
| Section 9 | REQ-9xx | Non-Functional Requirements |

### 1.6 Assumptions & Constraints

| ID | Assumption / Constraint | Impact if Violated |
|----|------------------------|--------------------|
| A-1 | The LLM backend exposes a model-info endpoint that returns context window size (e.g., Ollama `/api/show`) | System falls back to a configurable default context window size |
| A-2 | Token estimation does not require loading a tokenizer library (e.g., tiktoken, sentencepiece) | If a tokenizer is loaded, startup time and memory constraints may be violated |
| A-3 | The 4-characters-per-token heuristic is accurate within ±20% for the target model family | If accuracy degrades beyond ±20%, the display may mislead users about available budget |
| A-4 | Context window size is static for a given model — it does not change between requests | If the backend dynamically adjusts context window (e.g., via `num_ctx` override), cached capabilities become stale |

### 1.7 Design Principles

| Principle | Description |
|-----------|-------------|
| **Observability over precision** | A rough-but-visible token count is more useful than no count at all. The display is an estimate, clearly labeled as such, not a precise tokenizer output. |
| **Zero-cost when idle** | Model capability discovery happens once at startup and is cached. Token estimation uses arithmetic only — no model loading, no network calls per request. |
| **Graceful degradation** | If the LLM backend is unreachable or the model info endpoint is unsupported, the system falls back to a configured default rather than failing. |
| **Interface parity** | Both web console and CLI display the same information using the same calculation logic. No business rules are duplicated in interface layers. |

### 1.8 Out of Scope

The following are explicitly **not covered** by this specification:

- Precise tokenizer integration (tiktoken, sentencepiece, HuggingFace tokenizers)
- Automatic actions triggered by high context usage (auto-compact, auto-truncate)
- Per-turn token breakdown (showing tokens per prompt component)
- Token usage tracking for billing or quota enforcement
- Embedding model token limits (only generation model context window is tracked)
- Output token counting (only input token estimation is in scope; output tokens are a fixed reservation)

---

## 2. System Overview

### 2.1 Architecture Diagram

```
                    ┌─────────────────────────────┐
                    │   LLM Backend (Ollama)       │
                    │   GET /api/show              │
                    └──────────────┬──────────────┘
                                   │  context_length,
                                   │  family, params
                                   ▼
┌──────────────────────────────────────────────────────────┐
│ [1] MODEL CAPABILITY DISCOVERY                           │
│     Fetch model metadata on startup, cache it.           │
│     Extract context window size from model info.         │
│     Fall back to default if unavailable.                 │
└──────────────────────────┬───────────────────────────────┘
                           │  ModelCapabilities
                           ▼
┌──────────────────────────────────────────────────────────┐
│ [2] TOKEN ESTIMATION & BUDGET CALCULATION                │
│     Sum estimated tokens for each prompt component:      │
│     system prompt + memory + chunks + query + overhead.  │
│     Compute usage % = input_tokens / effective_budget.   │
└──────────────────────────┬───────────────────────────────┘
                           │  TokenBudgetSnapshot
                           ▼
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
┌──────────────────────┐  ┌──────────────────────┐
│ [3a] CONSOLE DISPLAY │  │ [3b] CLI DISPLAY     │
│     Status bar at    │  │     Right-aligned    │
│     bottom-right     │  │     line after       │
│     of web console   │  │     query response   │
└──────────────────────┘  └──────────────────────┘
```

### 2.2 Data Flow Summary

| Stage | Input | Output |
|-------|-------|--------|
| Model Capability Discovery | Model name + LLM backend URL | `ModelCapabilities` (context_length, family, parameter_size) |
| Token Estimation | Prompt components (system prompt, memory context, chunks, query) + ModelCapabilities | `TokenBudgetSnapshot` (input_tokens, context_length, output_reservation, usage_percent) |
| Console Display | `TokenBudgetSnapshot` via API | Rendered status bar element |
| CLI Display | `TokenBudgetSnapshot` computed locally or fetched via API | Formatted terminal line |

---

## 3. Model Capability Discovery

> **REQ-101** | Priority: MUST
> **Description:** The system MUST fetch the active generation model's context window size from the LLM backend on startup. The context window size is extracted from the model info response using the model's architecture family to locate the correct field (e.g., `{family}.context_length`).
> **Rationale:** Different models have different context window sizes (e.g., 32,768 for qwen2.5:3b, 128,000 for llama3.1:70b). Hardcoding a single value would produce incorrect usage percentages when the model changes.
> **Acceptance Criteria:** Given a running Ollama instance with `qwen2.5:3b` loaded, the system extracts `context_length = 32768` from the model info response. Given a model with family `llama`, the system looks for `llama.context_length`.

> **REQ-102** | Priority: MUST
> **Description:** The system MUST cache model capabilities after the initial fetch. Subsequent token budget calculations MUST use the cached value without making additional network calls to the LLM backend.
> **Rationale:** Calling `/api/show` on every request would add ~50–200ms of latency and create unnecessary load on the LLM backend. Model capabilities do not change between requests.
> **Acceptance Criteria:** After startup, zero additional calls are made to the model info endpoint during normal query processing. A second call to the budget calculator returns in <1ms.

> **REQ-103** | Priority: MUST
> **Description:** The system MUST fall back to a configurable default context window size if the LLM backend is unreachable or the model info response does not contain a context length field. The default MUST be configurable via environment variable.
> **Rationale:** The system must not crash or refuse to display a budget indicator merely because Ollama was temporarily unreachable during startup. A conservative default (e.g., 2048) ensures the percentage is still directionally useful.
> **Acceptance Criteria:** Given an unreachable Ollama instance, the system uses the configured default (e.g., `RAG_TOKEN_BUDGET_DEFAULT_CONTEXT_LENGTH=2048`). Given a model whose info response lacks a context_length field, the same default is used. No exception is raised.

> **REQ-104** | Priority: SHOULD
> **Description:** The system SHOULD expose a mechanism to re-fetch model capabilities without restarting the application, to handle cases where the operator switches to a different model at runtime.
> **Rationale:** Operators may hot-swap models (e.g., from `qwen2.5:3b` to `qwen2.5:14b`) by changing the `OLLAMA_MODEL` config. Without a refresh mechanism, the cached context_length would be stale until restart.
> **Acceptance Criteria:** A refresh function or API call triggers a new fetch from the LLM backend and updates the cached capabilities. The next token budget calculation uses the updated context_length.

> **REQ-105** | Priority: SHOULD
> **Description:** The system SHOULD extract and cache additional model metadata beyond context_length: architecture family, parameter count, and quantization level.
> **Rationale:** This metadata is useful for display purposes (showing model name and size alongside token count) and for future use (e.g., adjusting token estimation heuristics per model family).
> **Acceptance Criteria:** For `qwen2.5:3b`, the cached capabilities include `family="qwen2"`, `parameter_size="3.1B"`, `quantization_level="Q4_K_M"` in addition to `context_length=32768`.

---

## 4. Token Estimation & Budget Calculation

> **REQ-201** | Priority: MUST
> **Description:** The system MUST estimate the total input token count by summing token estimates for each prompt component: system prompt, memory context (summary + recent turns), retrieved context chunks, user query, and template formatting overhead.
> **Rationale:** The token budget is only useful if it reflects the actual prompt composition sent to the LLM. Missing any component would underestimate usage and give users a false sense of remaining capacity.
> **Acceptance Criteria:** Given a prompt with system prompt (800 chars), memory context (2000 chars), 5 retrieved chunks (2500 chars total), user query (200 chars), and template overhead (200 chars), the estimated input tokens equal `(800+2000+2500+200+200) / 4 = 1425`. Each component's contribution is individually calculable.

> **REQ-202** | Priority: MUST
> **Description:** The system MUST calculate the effective input budget as `context_length - output_reservation`, where `output_reservation` equals the configured `GENERATION_MAX_TOKENS`. The context usage percentage MUST be computed as `(input_tokens / effective_input_budget) * 100`.
> **Rationale:** The context window is shared between input and output. If the output reservation is not subtracted, the system would underestimate usage and the model could truncate input or fail mid-generation.
> **Acceptance Criteria:** Given `context_length=32768`, `GENERATION_MAX_TOKENS=1024`, and `input_tokens=1425`: effective budget = 31744, usage = 4.5%. Given `input_tokens=30000`: usage = 94.5%.

> **REQ-203** | Priority: MUST
> **Description:** The system MUST use a character-based heuristic for token estimation that does not require loading a tokenizer library. The default ratio MUST be configurable via environment variable.
> **Rationale:** Loading tiktoken or sentencepiece adds ~200ms startup time and ~50MB memory. The 4-characters-per-token heuristic is sufficient for a budget indicator that is clearly labeled as an estimate.
> **Acceptance Criteria:** Token estimation for a 1000-character English string returns 250 tokens at the default 4:1 ratio. Changing the environment variable to a 3:1 ratio returns 333 tokens for the same input. No external tokenizer library is imported.

> **REQ-204** | Priority: MUST
> **Description:** The system MUST produce a snapshot data structure containing at minimum: `input_tokens` (estimated), `context_length` (from model capabilities), `output_reservation` (from config), `usage_percent` (computed), and `model_name` (active model identifier).
> **Rationale:** Both the web console and CLI need these fields to render the display. A structured snapshot ensures both interfaces receive consistent data.
> **Acceptance Criteria:** The snapshot structure contains all five fields. `usage_percent` is a float between 0.0 and 100.0. `input_tokens` and `context_length` are positive integers.

> **REQ-205** | Priority: SHOULD
> **Description:** The system SHOULD include per-component token breakdowns in the snapshot: system prompt tokens, memory context tokens, retrieval chunk tokens, user query tokens, and template overhead tokens.
> **Rationale:** Per-component breakdowns help operators understand which prompt section is consuming the most budget, enabling targeted optimization (e.g., reducing retrieval depth vs. compacting conversation memory).
> **Acceptance Criteria:** The snapshot includes a breakdown mapping (e.g., `{"system_prompt": 200, "memory_context": 500, "retrieval_chunks": 625, "user_query": 50, "template_overhead": 50}`). The sum of components equals `input_tokens`.

> **REQ-206** | Priority: SHOULD
> **Description:** The system SHOULD accept prompt component text as input (not require the caller to pre-estimate tokens). The estimation function SHOULD accept individual text segments and handle None/empty values gracefully.
> **Rationale:** Callers should not need to know the token estimation internals. Passing raw text keeps the interface clean and allows the estimator to be upgraded without changing callers.
> **Acceptance Criteria:** Passing `memory_context=None` and `chunks=[]` produces a valid snapshot with those components contributing zero tokens. Passing `query=""` contributes zero query tokens.

---

## 5. API Endpoint

> **REQ-301** | Priority: MUST
> **Description:** The system MUST expose an HTTP endpoint that returns the current model capabilities (context window size, model name, architecture family) so that the web console can render the token budget display. The endpoint MUST follow the existing console envelope response format.
> **Rationale:** The web console runs in the browser and cannot call Ollama directly. It needs a server-side endpoint to fetch model capabilities for the denominator of the usage calculation.
> **Acceptance Criteria:** `GET /console/token-budget` returns a JSON response with `ok: true` and `data` containing `context_length`, `model_name`, `output_reservation`, and `family`. The response uses the `ConsoleEnvelope` wrapper.

> **REQ-302** | Priority: MUST
> **Description:** The API endpoint MUST return cached model capabilities and MUST NOT make a blocking call to the LLM backend on each request.
> **Rationale:** The endpoint will be polled by the web console. Each call must be fast and must not amplify load on the LLM backend.
> **Acceptance Criteria:** The endpoint returns within 10ms. Zero calls to the LLM backend's model info endpoint occur during request handling.

> **REQ-303** | Priority: SHOULD
> **Description:** The API endpoint SHOULD accept an optional request body containing prompt component text (system prompt, memory context, chunks, query) and return the computed `TokenBudgetSnapshot` including estimated input tokens and usage percentage.
> **Rationale:** This allows the web console to request a full budget calculation server-side, maintaining interface parity — the same calculation logic serves both the console and CLI.
> **Acceptance Criteria:** `POST /console/token-budget` with `{"query": "What is RAG?", "memory_context": "...", "chunks": ["...", "..."]}` returns a snapshot with `input_tokens`, `usage_percent`, and per-component breakdown.

> **REQ-304** | Priority: SHOULD
> **Description:** The API endpoint SHOULD include a `stale` boolean field indicating whether the cached model capabilities may be outdated (e.g., if the initial fetch failed and the system is using defaults).
> **Rationale:** The web console can use this flag to visually indicate that the displayed context window size is a fallback default, not the actual model's capability.
> **Acceptance Criteria:** When model capabilities were fetched successfully, `stale=false`. When the system is using the default fallback, `stale=true`.

---

## 6. Web Console Display

> **REQ-401** | Priority: MUST
> **Description:** The web console MUST display a persistent status bar element at the bottom-right of the page showing the estimated token count, total context window size, and usage percentage. The format MUST be: `~{input_tokens} / {context_length} tokens ({usage_percent}%)`.
> **Rationale:** Users need persistent visibility into context window usage to make informed decisions about compacting conversations or adjusting query parameters. Bottom-right placement follows the convention of status indicators in IDEs and terminals.
> **Acceptance Criteria:** A `<div>` element is visible at the bottom-right of the console page. After a query that produces 1,247 estimated input tokens against a 32,768 context window, the element displays `~1,247 / 32,768 tokens (3.9%)`. The element is visible across all console tabs.

> **REQ-402** | Priority: MUST
> **Description:** The web console MUST update the token budget display after each query response completes (both streaming and non-streaming).
> **Rationale:** Context usage changes with each interaction as memory context grows. A stale indicator would defeat the purpose.
> **Acceptance Criteria:** After submitting a query and receiving a response, the token count display updates to reflect the new estimated input tokens. Two consecutive queries show different token counts if the memory context changed.

> **REQ-403** | Priority: SHOULD
> **Description:** The web console SHOULD visually indicate warning and critical usage thresholds using color changes. At ≥70% usage the display SHOULD turn amber/warning color. At ≥90% usage it SHOULD turn red/critical color.
> **Rationale:** Color coding provides instant visual feedback about urgency. Users may not notice a percentage number changing, but a red indicator is hard to miss.
> **Acceptance Criteria:** Below 70% usage, the display uses the default muted color. At 72% usage, the display turns amber (CSS `var(--warn)`). At 91% usage, the display turns red (CSS `var(--err)`).

> **REQ-404** | Priority: SHOULD
> **Description:** The web console SHOULD fetch model capabilities on page load and cache them client-side for the duration of the session, so the context window denominator is available before the first query.
> **Rationale:** Without pre-fetching, the status bar would show "unknown" until the first query completes. Pre-fetching gives immediate context even before interaction.
> **Acceptance Criteria:** On page load, the console calls the token budget API endpoint. The status bar displays `~0 / 32,768 tokens (0.0%)` before any query is submitted.

> **REQ-405** | Priority: MUST
> **Description:** The web console MUST display a graceful fallback when model capabilities are unavailable. The fallback display MUST be `tokens: unknown` rather than an error or empty element.
> **Rationale:** The status bar must not show broken UI when Ollama is down or the API endpoint is unreachable.
> **Acceptance Criteria:** When the token budget API returns an error or the fetch fails, the status bar displays `tokens: unknown`. No JavaScript error is thrown.

---

## 7. CLI Display

> **REQ-501** | Priority: MUST
> **Description:** The local CLI MUST display a token budget summary line after each query response. The line MUST be right-aligned to the terminal width and formatted as: `[~{input_tokens} / {context_length} tokens · {usage_percent}%]`.
> **Rationale:** CLI users need the same budget visibility as console users. Right-alignment separates the budget indicator from query results, making it a non-intrusive status line.
> **Acceptance Criteria:** After a query completes in the local CLI, a line appears showing `[~1,247 / 32,768 tokens · 3.9%]` right-aligned to the current terminal width. The line uses dim ANSI styling to avoid visual competition with query results.

> **REQ-502** | Priority: MUST
> **Description:** The remote CLI client MUST display the same token budget summary as the local CLI. The remote client MUST fetch model capabilities and (when available) the budget snapshot from the server API.
> **Rationale:** Interface parity requires both CLI variants to show the same information. The remote client cannot call Ollama directly, so it must use the server endpoint.
> **Acceptance Criteria:** After a query in the remote CLI, the token budget line matches the format of the local CLI. The data comes from the server API, not a local Ollama call.

> **REQ-503** | Priority: SHOULD
> **Description:** The CLI SHOULD apply ANSI color to the token budget line based on usage thresholds: default/dim below 70%, yellow/amber at ≥70%, red at ≥90%.
> **Rationale:** Color coding in the terminal matches the web console behavior and provides instant visual urgency cues.
> **Acceptance Criteria:** At 45% usage, the line is rendered in dim ANSI color. At 75% usage, the line is rendered in yellow. At 92% usage, the line is rendered in red.

> **REQ-504** | Priority: MUST
> **Description:** The CLI MUST display a graceful fallback when model capabilities are unavailable. The fallback MUST be `[tokens: unknown]` rather than a traceback or missing output.
> **Rationale:** If Ollama is down, the CLI must not crash or omit the status line entirely.
> **Acceptance Criteria:** When the LLM backend is unreachable, the CLI displays `[tokens: unknown]` in dim ANSI styling after each query response. No exception is raised.

---

## 8. Interface Contracts

### Token Budget API — Inbound (GET)

| Field | Value |
|-------|-------|
| Protocol | HTTP REST (GET) |
| Path | `/console/token-budget` |
| Authentication | Same as other console endpoints (API key or bearer token) |

**Response Schema:**
```json
{
  "ok": true,
  "request_id": "string",
  "data": {
    "model_name": "string — active model identifier (e.g., 'qwen2.5:3b')",
    "context_length": "integer — model's total context window in tokens",
    "output_reservation": "integer — tokens reserved for generation output",
    "family": "string — model architecture family (e.g., 'qwen2')",
    "parameter_size": "string — model size label (e.g., '3.1B')",
    "stale": "boolean — true if capabilities are from fallback defaults"
  }
}
```

### Token Budget API — Inbound (POST, optional)

| Field | Value |
|-------|-------|
| Protocol | HTTP REST (POST) |
| Path | `/console/token-budget` |
| Authentication | Same as other console endpoints |

**Request Schema:**
```json
{
  "system_prompt": "string | null — system prompt text",
  "memory_context": "string | null — memory context text",
  "chunks": ["string — retrieved context chunk text"],
  "query": "string | null — user query text"
}
```

**Response Schema:**
```json
{
  "ok": true,
  "request_id": "string",
  "data": {
    "model_name": "string",
    "context_length": "integer",
    "output_reservation": "integer",
    "input_tokens": "integer — estimated total input tokens",
    "usage_percent": "float — (input_tokens / effective_budget) * 100",
    "breakdown": {
      "system_prompt": "integer",
      "memory_context": "integer",
      "retrieval_chunks": "integer",
      "user_query": "integer",
      "template_overhead": "integer"
    },
    "stale": "boolean"
  }
}
```

---

## 9. Error Taxonomy

| Category | Examples | Severity | Expected Behavior |
|----------|----------|----------|-------------------|
| Transient | Ollama unreachable during capability fetch | Recoverable | Use fallback default context length; mark capabilities as stale |
| Transient | Token budget API endpoint returns HTTP 5xx | Recoverable | Console displays "tokens: unknown"; CLI displays `[tokens: unknown]` |
| Permanent | Model info response missing context_length field | Non-recoverable for discovery | Use fallback default; log warning |
| Partial | Prompt component text is None or empty | Degraded | Contribute zero tokens for that component; continue calculation |

### Fallback Matrix

| Component | Primary Strategy | Fallback Strategy |
|-----------|-----------------|-------------------|
| Model capability discovery | Fetch from LLM backend `/api/show` | Use configurable default context length |
| Token estimation | Character-based heuristic at configured ratio | N/A (heuristic is always available) |
| Web console display | Fetch from `/console/token-budget` API | Display "tokens: unknown" |
| CLI display (local) | Compute locally using token budget module | Display `[tokens: unknown]` |
| CLI display (remote) | Fetch from server API | Display `[tokens: unknown]` |

---

## 10. External Dependencies

### Required Services

| Service | Purpose |
|---------|---------|
| None | Token estimation and budget calculation are self-contained; no external service is required at calculation time |

### Optional Services

| Service | Purpose |
|---------|---------|
| Ollama `/api/show` | Fetches model context window size for accurate budget denominator. If unavailable, system uses configured default. |

### Downstream Dependencies (Outside This System)

| Consumer | Purpose | Interface Contract |
|----------|---------|-------------------|
| Web Console (browser) | Renders token budget status bar | Consumes `GET/POST /console/token-budget` API |
| Remote CLI Client | Displays token budget after queries | Consumes `GET /console/token-budget` API |
| Local CLI | Displays token budget after queries | Calls token budget module directly (Python import) |

---

## 11. Non-Functional Requirements

> **REQ-901** | Priority: MUST
> **Description:** Token estimation MUST complete within 1ms for a prompt of up to 50,000 characters. No external network calls, no file I/O, and no heavy library imports are permitted during estimation.
> **Rationale:** Token estimation runs on every query. Adding latency to the query path would degrade user experience. The heuristic is arithmetic-only by design.
> **Acceptance Criteria:** Benchmarking `estimate_budget()` with a 50,000-character input completes in <1ms. No imports of tiktoken, sentencepiece, or transformers occur in the token budget module.

> **REQ-902** | Priority: MUST
> **Description:** The system MUST degrade gracefully when optional components are unavailable:
>
> | Component Unavailable | Degraded Behavior |
> |----------------------|-------------------|
> | Ollama `/api/show` | Use fallback default context length; mark as stale |
> | Token budget API endpoint | Console shows "tokens: unknown" |
> | Terminal width detection | CLI uses a default width of 80 for right-alignment |
>
> The system MUST NOT crash or return an unhandled error when any component is unavailable.
> **Rationale:** The token budget is an informational display, not a critical path component. Its failure must never block query processing.
> **Acceptance Criteria:** Each degradation scenario is tested. No exception propagates to the user. Warning is logged for capability fetch failures.

> **REQ-903** | Priority: MUST
> **Description:** All configurable parameters MUST be externalized to environment variables with documented defaults:
>
> | Parameter | Environment Variable | Default |
> |-----------|---------------------|---------|
> | Default context length | `RAG_TOKEN_BUDGET_DEFAULT_CONTEXT_LENGTH` | `2048` |
> | Chars-per-token ratio | `RAG_TOKEN_BUDGET_CHARS_PER_TOKEN` | `4` |
> | Warning threshold (%) | `RAG_TOKEN_BUDGET_WARN_PERCENT` | `70` |
> | Critical threshold (%) | `RAG_TOKEN_BUDGET_CRITICAL_PERCENT` | `90` |
>
> **Rationale:** Operators must be able to tune estimation accuracy and warning thresholds without code changes. Different model families may warrant different char-per-token ratios.
> **Acceptance Criteria:** Each parameter is loaded from the corresponding environment variable. Missing values use the documented default. Changing `RAG_TOKEN_BUDGET_CHARS_PER_TOKEN=3` produces different token estimates on next startup.

> **REQ-904** | Priority: SHOULD
> **Description:** The token budget module SHOULD log a single INFO-level message on startup indicating the discovered model capabilities (model name, context length, source: "fetched" or "default fallback").
> **Rationale:** This log line helps operators verify that the correct model was detected and aids debugging when the budget display shows unexpected values.
> **Acceptance Criteria:** On startup with Ollama available, the log shows: `Token budget: qwen2.5:3b context_length=32768 (fetched)`. On startup without Ollama, the log shows: `Token budget: context_length=2048 (default fallback)`.

---

## 12. System-Level Acceptance Criteria

| Criterion | Threshold | Related Requirements |
|-----------|-----------|---------------------|
| Token estimation accuracy | Within ±25% of actual tokenizer output for English text | REQ-201, REQ-203 |
| Budget display visible in both interfaces | Console status bar + CLI line present after query | REQ-401, REQ-501, REQ-502 |
| Graceful degradation coverage | All five fallback scenarios pass without crash | REQ-103, REQ-405, REQ-504, REQ-902 |
| No latency regression | Token budget calculation adds <1ms to query path | REQ-901, REQ-302 |
| Configuration externalization | All four parameters configurable via env vars | REQ-903 |

---

## 13. Requirements Traceability Matrix

| REQ ID | Section | Priority | Component |
|--------|---------|----------|-----------|
| REQ-101 | 3 | MUST | Model Capability Discovery |
| REQ-102 | 3 | MUST | Model Capability Discovery |
| REQ-103 | 3 | MUST | Model Capability Discovery |
| REQ-104 | 3 | SHOULD | Model Capability Discovery |
| REQ-105 | 3 | SHOULD | Model Capability Discovery |
| REQ-201 | 4 | MUST | Token Estimation & Budget Calculation |
| REQ-202 | 4 | MUST | Token Estimation & Budget Calculation |
| REQ-203 | 4 | MUST | Token Estimation & Budget Calculation |
| REQ-204 | 4 | MUST | Token Estimation & Budget Calculation |
| REQ-205 | 4 | SHOULD | Token Estimation & Budget Calculation |
| REQ-206 | 4 | SHOULD | Token Estimation & Budget Calculation |
| REQ-301 | 5 | MUST | API Endpoint |
| REQ-302 | 5 | MUST | API Endpoint |
| REQ-303 | 5 | SHOULD | API Endpoint |
| REQ-304 | 5 | SHOULD | API Endpoint |
| REQ-401 | 6 | MUST | Web Console Display |
| REQ-402 | 6 | MUST | Web Console Display |
| REQ-403 | 6 | SHOULD | Web Console Display |
| REQ-404 | 6 | SHOULD | Web Console Display |
| REQ-405 | 6 | MUST | Web Console Display |
| REQ-501 | 7 | MUST | CLI Display |
| REQ-502 | 7 | MUST | CLI Display |
| REQ-503 | 7 | SHOULD | CLI Display |
| REQ-504 | 7 | MUST | CLI Display |
| REQ-901 | 11 | MUST | Non-Functional |
| REQ-902 | 11 | MUST | Non-Functional |
| REQ-903 | 11 | MUST | Non-Functional |
| REQ-904 | 11 | SHOULD | Non-Functional |

**Total Requirements: 28**
- MUST: 18
- SHOULD: 10
- MAY: 0

---

## Appendix A. Glossary

| Term | Definition |
|------|-----------|
| BPE | Byte Pair Encoding — the tokenization algorithm used by most LLMs. Splits text into subword tokens. |
| Context length | The maximum number of tokens a model can process in a single request, including both input and generated output. |
| num_ctx | Ollama parameter that overrides the model's default context window size at runtime. |
| Token | The atomic unit of text processed by an LLM. Roughly 4 characters or 0.75 words in English. |
| Heuristic | An estimation rule-of-thumb (e.g., 4 characters ≈ 1 token) used instead of exact tokenizer computation. |
| Stale | A flag indicating that cached model capabilities may not reflect the currently loaded model. |

---

## Appendix B. Document References

| Document | Purpose |
|----------|---------|
| `WEB_CONSOLE_SPEC.md` | Defines the web console architecture; token budget display is a new status bar element within this surface |
| `WEB_CONSOLE_IMPLEMENTATION.md` | Implementation guide for the web console; token budget display integrates into the existing console HTML/TS |
| `CLI_SPEC.md` | Defines CLI requirements; token budget display extends the CLI output format |
| `CLI_IMPLEMENTATION.md` | Implementation guide for the CLI; token budget display integrates into the REPL loop |
| `SERVER_API_SPEC.md` | Defines API endpoint patterns; the token budget endpoint follows the same envelope and auth conventions |
| `TOKEN_BUDGET_IMPLEMENTATION.md` | Companion implementation guide for this specification |

---

## Appendix C. Implementation Phasing

### Phase 1 — Core Module & API

**Objective:** Deliver the token budget module and API endpoint.

| Scope | Requirements |
|-------|-------------|
| Model capability discovery | REQ-101, REQ-102, REQ-103 |
| Token estimation & budget calculation | REQ-201, REQ-202, REQ-203, REQ-204 |
| API endpoint | REQ-301, REQ-302 |
| Configuration | REQ-903 |
| Graceful degradation | REQ-902 |

**Success criteria:** `GET /console/token-budget` returns valid model capabilities. Token estimation produces correct results for test inputs.

### Phase 2 — Interface Integration

**Objective:** Display token budget in both web console and CLI.

| Scope | Requirements |
|-------|-------------|
| Web console status bar | REQ-401, REQ-402, REQ-405 |
| CLI display (local + remote) | REQ-501, REQ-502, REQ-504 |
| Color thresholds | REQ-403, REQ-503 |
| Console pre-fetch | REQ-404 |

**Success criteria:** Token budget is visible in both interfaces after every query. Fallback displays work when Ollama is unreachable.

### Phase 3 — Enhancements

**Objective:** Add per-component breakdown, model metadata, and refresh capability.

| Scope | Requirements |
|-------|-------------|
| Per-component breakdown | REQ-205, REQ-206 |
| Additional model metadata | REQ-105 |
| POST endpoint for server-side calculation | REQ-303, REQ-304 |
| Capability refresh | REQ-104 |
| Observability | REQ-904 |

**Success criteria:** POST endpoint returns per-component breakdown. Capability refresh updates cached values without restart.
