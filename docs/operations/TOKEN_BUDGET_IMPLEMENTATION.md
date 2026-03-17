# Token Budget Tracker — Implementation Guide

**AION Knowledge Management Platform**
Version: 1.0 | Status: Draft | Domain: Platform / Observability

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-13 | AI Assistant | Initial implementation guide |

This document provides a phased implementation plan and detailed code appendix for the token budget tracker specified in `TOKEN_BUDGET_SPEC.md`. Every task references the requirements it satisfies.

---

# Part A: Task-Oriented Overview

## Phase 1 — Core Module & Configuration

Foundation work: define data structures, configuration, token estimation, and model capability discovery. These are the building blocks consumed by all downstream tasks.

### Task 1.1: Define Data Structures

**Description:** Create typed data structures for model capabilities and token budget snapshots that serve as the contract between the core module and all consumers (API, console, CLI).

**Requirements Covered:** REQ-204, REQ-205

**Dependencies:** None — new module.

**Complexity:** S

**Subtasks:**
1. Create a `ModelCapabilities` dataclass with fields: `model_name`, `context_length`, `family`, `parameter_size`, `quantization_level`, `stale`
2. Create a `TokenBudgetSnapshot` dataclass with fields: `input_tokens`, `context_length`, `output_reservation`, `usage_percent`, `model_name`, `breakdown` (optional dict)
3. Create a `TokenBreakdown` dataclass with fields: `system_prompt`, `memory_context`, `retrieval_chunks`, `user_query`, `template_overhead`
4. Export all types from the module's public facade

---

### Task 1.2: Add Configuration Settings

**Description:** Add all token budget configuration parameters to the centralized settings module, loaded from environment variables with documented defaults.

**Requirements Covered:** REQ-903

**Dependencies:** None.

**Complexity:** S

**Subtasks:**
1. Add `TOKEN_BUDGET_DEFAULT_CONTEXT_LENGTH` (env: `RAG_TOKEN_BUDGET_DEFAULT_CONTEXT_LENGTH`, default: `2048`)
2. Add `TOKEN_BUDGET_CHARS_PER_TOKEN` (env: `RAG_TOKEN_BUDGET_CHARS_PER_TOKEN`, default: `4`)
3. Add `TOKEN_BUDGET_WARN_PERCENT` (env: `RAG_TOKEN_BUDGET_WARN_PERCENT`, default: `70`)
4. Add `TOKEN_BUDGET_CRITICAL_PERCENT` (env: `RAG_TOKEN_BUDGET_CRITICAL_PERCENT`, default: `90`)

---

### Task 1.3: Implement Token Estimation

**Description:** Create a configurable token estimation function that uses the character-based heuristic with a tunable chars-per-token ratio. This replaces the existing hardcoded 4:1 estimation.

**Requirements Covered:** REQ-203, REQ-206, REQ-901

**Dependencies:** Task 1.2

**Complexity:** S

**Subtasks:**
1. Implement `estimate_tokens(text: str | None) -> int` that divides character count by the configured ratio
2. Handle `None` and empty string inputs gracefully (return 0)
3. Update the existing memory module's `estimate_token_count()` to delegate to the new function for consistency

**Testing Strategy:** Unit test with known inputs at different ratios (4:1, 3:1). Verify `None`/empty handling.

---

### Task 1.4: Implement Model Capability Discovery

**Description:** Create a capability fetcher that queries the LLM backend's model info endpoint, extracts context window size using the architecture family, caches the result, and falls back to a default when the backend is unreachable.

**Requirements Covered:** REQ-101, REQ-102, REQ-103, REQ-104, REQ-105, REQ-902, REQ-904

**Dependencies:** Task 1.1, Task 1.2

**Complexity:** M

**Subtasks:**
1. Implement `fetch_model_capabilities(model_name, base_url) -> ModelCapabilities` that calls the LLM backend's model info endpoint via HTTP
2. Parse the response: extract `details.family`, `details.parameter_size`, `details.quantization_level`, and `model_info["{family}.context_length"]`
3. Implement fallback: on any exception or missing field, return a `ModelCapabilities` with the default context length and `stale=True`
4. Implement module-level caching: store the result after first fetch, return cached on subsequent calls
5. Implement `refresh_capabilities()` to re-fetch and update the cache
6. Log an INFO message on fetch: model name, context length, source ("fetched" or "default fallback")

**Risks:** LLM backend response format may vary between providers → mitigate by defensive parsing with fallback at every extraction step.

**Testing Strategy:** Unit test with mocked HTTP responses (success, timeout, malformed JSON). Verify caching behavior.

---

### Task 1.5: Implement Budget Calculator

**Description:** Create the budget calculation function that accepts prompt component texts and produces a `TokenBudgetSnapshot` with usage percentage and optional per-component breakdown.

**Requirements Covered:** REQ-201, REQ-202, REQ-204, REQ-205, REQ-206

**Dependencies:** Task 1.1, Task 1.3, Task 1.4

**Complexity:** S

**Subtasks:**
1. Implement `calculate_budget(system_prompt, memory_context, chunks, query, template_overhead_chars) -> TokenBudgetSnapshot`
2. Estimate tokens for each component individually, sum for `input_tokens`
3. Compute `effective_budget = context_length - output_reservation`
4. Compute `usage_percent = (input_tokens / effective_budget) * 100`, clamped to 0.0–100.0
5. Populate the `breakdown` field with per-component counts

---

## Phase 2 — API Endpoint & Server Integration

Expose the token budget data via HTTP so the web console and remote CLI can consume it.

### Task 2.1: Add Server Request/Response Schemas

**Description:** Define Pydantic request and response models for the token budget endpoint, following the existing console envelope pattern.

**Requirements Covered:** REQ-301, REQ-303

**Dependencies:** Task 1.1

**Complexity:** S

**Subtasks:**
1. Add `TokenBudgetResponse` model with fields matching the GET response schema from the spec
2. Add `TokenBudgetRequest` model with optional fields: `system_prompt`, `memory_context`, `chunks`, `query`
3. Add `TokenBudgetCalculationResponse` extending the response with `input_tokens`, `usage_percent`, `breakdown`

---

### Task 2.2: Add Console Route

**Description:** Add `GET` and `POST /console/token-budget` endpoints to the console router, returning cached model capabilities and optionally computing a budget snapshot.

**Requirements Covered:** REQ-301, REQ-302, REQ-303, REQ-304

**Dependencies:** Task 1.4, Task 1.5, Task 2.1

**Complexity:** M

**Subtasks:**
1. Add `GET /console/token-budget` handler that returns cached `ModelCapabilities` wrapped in `ConsoleEnvelope`
2. Add `POST /console/token-budget` handler that accepts prompt component text, calls the budget calculator, and returns `TokenBudgetSnapshot` wrapped in `ConsoleEnvelope`
3. Include `stale` boolean in both responses
4. Initialize model capability discovery during server startup (in the console router factory or app lifespan)
5. Follow existing auth pattern (same middleware as other console endpoints)

**Risks:** Capability fetch during startup could delay server readiness if Ollama is slow → mitigate with a short timeout (3s) on the initial fetch.

---

## Phase 3 — Web Console Display

Add the status bar to the web console that shows token count and usage percentage.

### Task 3.1: Add Status Bar HTML & CSS

**Description:** Add a fixed-position status bar element at the bottom-right of the console page with appropriate styling for normal, warning, and critical states.

**Requirements Covered:** REQ-401, REQ-403, REQ-405

**Dependencies:** None (HTML/CSS only).

**Complexity:** S

**Subtasks:**
1. Add a `<div id="tokenBudgetBar">` element to the console HTML, positioned `fixed` at bottom-right
2. Style with `position: fixed; bottom: 12px; right: 16px;` using the existing design system colors
3. Add CSS classes for warning (`.token-warn`) and critical (`.token-crit`) states using `var(--warn)` and `var(--err)`
4. Set initial content to `tokens: unknown`

---

### Task 3.2: Add Token Budget TypeScript Logic

**Description:** Add client-side logic to fetch model capabilities on page load, update the status bar after each query, and apply color thresholds.

**Requirements Covered:** REQ-401, REQ-402, REQ-403, REQ-404, REQ-405

**Dependencies:** Task 2.2, Task 3.1

**Complexity:** M

**Subtasks:**
1. Add `TokenBudgetInfo` type definition matching the API response
2. Add `fetchTokenBudget()` async function that calls `GET /console/token-budget` and caches the result
3. Add `updateTokenBudgetDisplay(inputTokens: number)` function that computes usage percentage and updates the status bar text and color class
4. Call `fetchTokenBudget()` in `initializeConsoleUi()` to pre-populate on page load
5. After each query response (both streaming and non-streaming), estimate input tokens from the query text and call `updateTokenBudgetDisplay()`
6. Apply color thresholds: default below warning, `.token-warn` at ≥70%, `.token-crit` at ≥90%
7. Handle fetch failures gracefully: display `tokens: unknown`, no thrown errors
8. Compile TypeScript and copy output to static assets directory

**Testing Strategy:** Manual testing: submit queries, verify display updates. Test with Ollama stopped to verify fallback.

---

## Phase 4 — CLI Display

Add token budget display to both local and remote CLI after each query response.

### Task 4.1: Add Token Budget Display to Local CLI

**Description:** After each query response in the local CLI REPL, display a right-aligned token budget summary line with ANSI color based on usage thresholds.

**Requirements Covered:** REQ-501, REQ-503, REQ-504, REQ-902

**Dependencies:** Task 1.4, Task 1.5

**Complexity:** S

**Subtasks:**
1. Import the token budget module in the CLI entry point
2. Initialize model capability discovery at startup (after model loading completes)
3. After `display_results()`, call `calculate_budget()` with the prompt components used for the last query
4. Implement `_print_token_budget(snapshot)` that formats the right-aligned line: `[~{input_tokens} / {context_length} tokens · {usage_percent}%]`
5. Use `os.get_terminal_size(fallback=(80, 24))` for terminal width; right-pad with spaces
6. Apply ANSI colors: DIM below warning, B_YELLOW at ≥70%, B_RED at ≥90%
7. Wrap in try/except to catch any error and display `[tokens: unknown]` in DIM

---

### Task 4.2: Add Token Budget Display to Remote CLI

**Description:** After each query response in the remote CLI, fetch model capabilities from the server API and display the same token budget summary line.

**Requirements Covered:** REQ-502, REQ-503, REQ-504

**Dependencies:** Task 2.2, Task 4.1

**Complexity:** S

**Subtasks:**
1. Add a function to fetch model capabilities from `GET /console/token-budget` (reusing the existing HTTP helper pattern)
2. Cache the response for the session duration
3. After each query response, estimate input tokens locally using the same char-based heuristic
4. Reuse the same `_print_token_budget()` display formatting as the local CLI (extract to a shared helper if needed)
5. Handle fetch failures gracefully: display `[tokens: unknown]`

---

## Task Dependency Graph

```
Phase 1 (Core Module & Configuration)
├── Task 1.1: Data Structures ──────────────────────────┐
├── Task 1.2: Configuration Settings ───────────────────┤
├── Task 1.3: Token Estimation ◄── Task 1.2 ────────────┤
├── Task 1.4: Model Capability Discovery ◄── 1.1, 1.2 ──┤  [CRITICAL]
└── Task 1.5: Budget Calculator ◄── 1.1, 1.3, 1.4 ──────┤  [CRITICAL]
                                                         │
Phase 2 (API & Server)                                   │
├── Task 2.1: Server Schemas ◄── Task 1.1 ───────────────┤
└── Task 2.2: Console Route ◄── 1.4, 1.5, 2.1 ──────────┤  [CRITICAL]
                                                         │
Phase 3 (Web Console)                                    │
├── Task 3.1: Status Bar HTML/CSS ───────────────────────┤
└── Task 3.2: TypeScript Logic ◄── 2.2, 3.1 ─────────────┤  [CRITICAL]
                                                         │
Phase 4 (CLI)                                            │
├── Task 4.1: Local CLI Display ◄── 1.4, 1.5 ────────────┘
└── Task 4.2: Remote CLI Display ◄── 2.2, 4.1

Critical path: 1.1 → 1.4 → 1.5 → 2.2 → 3.2
```

---

## Task-to-Requirement Mapping

| Task | Requirements Covered |
|------|---------------------|
| 1.1 Data Structures | REQ-204, REQ-205 |
| 1.2 Configuration Settings | REQ-903 |
| 1.3 Token Estimation | REQ-203, REQ-206, REQ-901 |
| 1.4 Model Capability Discovery | REQ-101, REQ-102, REQ-103, REQ-104, REQ-105, REQ-902, REQ-904 |
| 1.5 Budget Calculator | REQ-201, REQ-202, REQ-204, REQ-205, REQ-206 |
| 2.1 Server Schemas | REQ-301, REQ-303 |
| 2.2 Console Route | REQ-301, REQ-302, REQ-303, REQ-304 |
| 3.1 Status Bar HTML/CSS | REQ-401, REQ-403, REQ-405 |
| 3.2 TypeScript Logic | REQ-401, REQ-402, REQ-403, REQ-404, REQ-405 |
| 4.1 Local CLI Display | REQ-501, REQ-503, REQ-504, REQ-902 |
| 4.2 Remote CLI Display | REQ-502, REQ-503, REQ-504 |

All 28 requirements from the spec are covered.

---

# Part B: Code Appendix

## B.1: Token Budget Data Structures

Typed data structures serving as the contract between the core module and all consumers. Supports Task 1.1.

**Tasks:** Task 1.1
**Requirements:** REQ-204, REQ-205

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelCapabilities:
    """Cached metadata about the active generation model."""

    model_name: str
    context_length: int
    family: str = ""
    parameter_size: str = ""
    quantization_level: str = ""
    stale: bool = False


@dataclass(frozen=True)
class TokenBreakdown:
    """Per-component token counts for the prompt."""

    system_prompt: int = 0
    memory_context: int = 0
    retrieval_chunks: int = 0
    user_query: int = 0
    template_overhead: int = 0

    def total(self) -> int:
        return (
            self.system_prompt
            + self.memory_context
            + self.retrieval_chunks
            + self.user_query
            + self.template_overhead
        )


@dataclass(frozen=True)
class TokenBudgetSnapshot:
    """Complete budget state for display in console and CLI."""

    input_tokens: int
    context_length: int
    output_reservation: int
    usage_percent: float
    model_name: str
    breakdown: TokenBreakdown | None = None
```

**Key design decisions:**
- Frozen dataclasses: snapshots are immutable values, not mutable state
- `TokenBreakdown` is a separate dataclass (not a raw dict) for type safety and IDE support
- `breakdown` is optional to support the phased rollout (Phase 1 can omit it)

---

## B.2: Model Capability Discovery

Fetches model metadata from the LLM backend, caches it, and falls back to defaults. Supports Task 1.4.

**Tasks:** Task 1.4
**Requirements:** REQ-101, REQ-102, REQ-103, REQ-104, REQ-105, REQ-902, REQ-904

```python
from __future__ import annotations

import json
import logging
from urllib.request import Request, urlopen
from urllib.error import URLError

# These would be imported from config.settings and schemas
# from config.settings import (
#     OLLAMA_BASE_URL, OLLAMA_MODEL, TOKEN_BUDGET_DEFAULT_CONTEXT_LENGTH,
# )
# from .schemas import ModelCapabilities

logger = logging.getLogger("rag.token_budget")

_cached_capabilities: ModelCapabilities | None = None


def fetch_model_capabilities(
    model_name: str,
    base_url: str,
    default_context_length: int,
) -> ModelCapabilities:
    """Fetch model info from the LLM backend and extract context window size."""
    try:
        payload = json.dumps({"name": model_name}).encode("utf-8")
        req = Request(
            f"{base_url.rstrip('/')}/api/show",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        details = data.get("details", {})
        family = details.get("family", "")
        model_info = data.get("model_info", {})

        # Context length is stored under "{family}.context_length"
        context_length = None
        if family:
            context_length = model_info.get(f"{family}.context_length")
        # Fallback: scan all keys ending with ".context_length"
        if context_length is None:
            for key, val in model_info.items():
                if key.endswith(".context_length") and isinstance(val, (int, float)):
                    context_length = int(val)
                    break

        if context_length is None or context_length <= 0:
            logger.warning(
                "No context_length found for model %s; using default %d",
                model_name, default_context_length,
            )
            context_length = default_context_length
            stale = True
        else:
            stale = False

        caps = ModelCapabilities(
            model_name=model_name,
            context_length=int(context_length),
            family=family,
            parameter_size=details.get("parameter_size", ""),
            quantization_level=details.get("quantization_level", ""),
            stale=stale,
        )
        logger.info(
            "Token budget: %s context_length=%d (%s)",
            model_name, caps.context_length,
            "fetched" if not stale else "default fallback",
        )
        return caps

    except (URLError, OSError, json.JSONDecodeError, KeyError) as exc:
        logger.warning("Failed to fetch model capabilities: %s", exc)
        return ModelCapabilities(
            model_name=model_name,
            context_length=default_context_length,
            stale=True,
        )


def get_capabilities() -> ModelCapabilities:
    """Return cached model capabilities, fetching on first call."""
    global _cached_capabilities
    if _cached_capabilities is None:
        _cached_capabilities = fetch_model_capabilities(
            model_name=OLLAMA_MODEL,
            base_url=OLLAMA_BASE_URL,
            default_context_length=TOKEN_BUDGET_DEFAULT_CONTEXT_LENGTH,
        )
    return _cached_capabilities


def refresh_capabilities() -> ModelCapabilities:
    """Re-fetch model capabilities and update the cache."""
    global _cached_capabilities
    _cached_capabilities = fetch_model_capabilities(
        model_name=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        default_context_length=TOKEN_BUDGET_DEFAULT_CONTEXT_LENGTH,
    )
    return _cached_capabilities
```

**Key design decisions:**
- Module-level `_cached_capabilities` with lazy init: zero cost until first access, cached forever after
- Defensive parsing: family-based key lookup with fallback scan of all `*.context_length` keys
- 5-second timeout on the HTTP call to avoid blocking startup
- Every exception path returns a valid `ModelCapabilities` with `stale=True` — never raises

---

## B.3: Budget Calculator

Accepts prompt component text and produces a `TokenBudgetSnapshot`. Supports Task 1.3 and Task 1.5.

**Tasks:** Task 1.3, Task 1.5
**Requirements:** REQ-201, REQ-202, REQ-203, REQ-205, REQ-206

```python
from __future__ import annotations

# from config.settings import TOKEN_BUDGET_CHARS_PER_TOKEN, GENERATION_MAX_TOKENS
# from .schemas import ModelCapabilities, TokenBreakdown, TokenBudgetSnapshot


def estimate_tokens(text: str | None, chars_per_token: int = 4) -> int:
    """Estimate token count from character length using configurable ratio."""
    if not text:
        return 0
    return max(1, len(text) // chars_per_token)


def calculate_budget(
    capabilities: ModelCapabilities,
    *,
    system_prompt: str | None = None,
    memory_context: str | None = None,
    chunks: list[str] | None = None,
    query: str | None = None,
    template_overhead_chars: int = 200,
    chars_per_token: int = 4,
    output_reservation: int = 1024,
) -> TokenBudgetSnapshot:
    """Compute token budget snapshot from prompt components."""
    cpt = max(1, chars_per_token)

    sp_tokens = estimate_tokens(system_prompt, cpt)
    mem_tokens = estimate_tokens(memory_context, cpt)
    chunk_tokens = sum(estimate_tokens(c, cpt) for c in (chunks or []))
    query_tokens = estimate_tokens(query, cpt)
    overhead_tokens = max(0, template_overhead_chars // cpt)

    input_tokens = sp_tokens + mem_tokens + chunk_tokens + query_tokens + overhead_tokens

    effective_budget = max(1, capabilities.context_length - output_reservation)
    usage_percent = min(100.0, max(0.0, (input_tokens / effective_budget) * 100))

    breakdown = TokenBreakdown(
        system_prompt=sp_tokens,
        memory_context=mem_tokens,
        retrieval_chunks=chunk_tokens,
        user_query=query_tokens,
        template_overhead=overhead_tokens,
    )

    return TokenBudgetSnapshot(
        input_tokens=input_tokens,
        context_length=capabilities.context_length,
        output_reservation=output_reservation,
        usage_percent=round(usage_percent, 1),
        model_name=capabilities.model_name,
        breakdown=breakdown,
    )
```

**Key design decisions:**
- All prompt components are optional (`None` → 0 tokens): callers pass what they have
- `chars_per_token` passed explicitly rather than reading config at call time: allows different callers to use different ratios
- `usage_percent` clamped to 0.0–100.0 and rounded to 1 decimal place for clean display
- `effective_budget` floor of 1 prevents division-by-zero edge case

---

## B.4: Console Route

HTTP endpoint handler for the token budget API. Supports Task 2.2.

**Tasks:** Task 2.1, Task 2.2
**Requirements:** REQ-301, REQ-302, REQ-303, REQ-304

```python
from __future__ import annotations

# In the console router factory, alongside other routes:

# @router.get("/console/token-budget")
async def get_token_budget():
    """Return cached model capabilities for the token budget display."""
    caps = get_capabilities()  # from token_budget module — cached, <1ms
    return ConsoleEnvelope(
        ok=True,
        request_id=generate_request_id(),
        data={
            "model_name": caps.model_name,
            "context_length": caps.context_length,
            "output_reservation": GENERATION_MAX_TOKENS,
            "family": caps.family,
            "parameter_size": caps.parameter_size,
            "stale": caps.stale,
        },
    )


# @router.post("/console/token-budget")
async def post_token_budget(body: TokenBudgetRequest):
    """Compute token budget from prompt components."""
    caps = get_capabilities()
    snapshot = calculate_budget(
        caps,
        system_prompt=body.system_prompt,
        memory_context=body.memory_context,
        chunks=body.chunks or [],
        query=body.query,
        chars_per_token=TOKEN_BUDGET_CHARS_PER_TOKEN,
        output_reservation=GENERATION_MAX_TOKENS,
    )
    breakdown = None
    if snapshot.breakdown:
        breakdown = {
            "system_prompt": snapshot.breakdown.system_prompt,
            "memory_context": snapshot.breakdown.memory_context,
            "retrieval_chunks": snapshot.breakdown.retrieval_chunks,
            "user_query": snapshot.breakdown.user_query,
            "template_overhead": snapshot.breakdown.template_overhead,
        }
    return ConsoleEnvelope(
        ok=True,
        request_id=generate_request_id(),
        data={
            "model_name": snapshot.model_name,
            "context_length": snapshot.context_length,
            "output_reservation": snapshot.output_reservation,
            "input_tokens": snapshot.input_tokens,
            "usage_percent": snapshot.usage_percent,
            "breakdown": breakdown,
            "stale": caps.stale,
        },
    )
```

**Key design decisions:**
- GET returns cached capabilities only (no computation) — fast and safe for polling
- POST does the full calculation server-side — maintains interface parity
- Both handlers use `ConsoleEnvelope` wrapper for consistency with existing endpoints
- `get_capabilities()` is called (not awaited) because it returns cached data; no async I/O

---

## B.5: Web Console Status Bar

Client-side TypeScript for the token budget display. Supports Task 3.1 and Task 3.2.

**Tasks:** Task 3.1, Task 3.2
**Requirements:** REQ-401, REQ-402, REQ-403, REQ-404, REQ-405

```html
<!-- Added to console.html, before closing </body> tag -->
<div id="tokenBudgetBar"
     style="position:fixed;bottom:12px;right:16px;
            font-size:12px;color:var(--muted);
            font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
            background:var(--card);border:1px solid var(--border);
            border-radius:8px;padding:4px 10px;z-index:900;">
  tokens: unknown
</div>
```

```typescript
// Added to main.ts

type TokenBudgetInfo = {
    model_name: string;
    context_length: number;
    output_reservation: number;
    family?: string;
    parameter_size?: string;
    stale?: boolean;
};

let cachedTokenBudget: TokenBudgetInfo | null = null;

async function fetchTokenBudget(): Promise<void> {
    try {
        const payload = await api("GET", "/console/token-budget");
        const data = (payload.data as JsonObject) || {};
        cachedTokenBudget = {
            model_name: String(data.model_name || ""),
            context_length: Number(data.context_length) || 0,
            output_reservation: Number(data.output_reservation) || 0,
            family: String(data.family || ""),
            parameter_size: String(data.parameter_size || ""),
            stale: Boolean(data.stale),
        };
        updateTokenBudgetDisplay(0);
    } catch {
        updateTokenBudgetDisplay(-1);  // -1 signals unknown
    }
}

function updateTokenBudgetDisplay(inputTokens: number): void {
    const bar = document.getElementById("tokenBudgetBar");
    if (!bar) return;

    if (!cachedTokenBudget || cachedTokenBudget.context_length <= 0 || inputTokens < 0) {
        bar.textContent = "tokens: unknown";
        bar.style.color = "var(--muted)";
        return;
    }

    const ctx = cachedTokenBudget.context_length;
    const effective = ctx - cachedTokenBudget.output_reservation;
    const pct = effective > 0 ? (inputTokens / effective) * 100 : 0;
    const pctStr = pct.toFixed(1);

    bar.textContent = `~${inputTokens.toLocaleString()} / ${ctx.toLocaleString()} tokens (${pctStr}%)`;

    // Color thresholds (configurable via config, hardcoded client-side for now)
    if (pct >= 90) {
        bar.style.color = "var(--err)";
    } else if (pct >= 70) {
        bar.style.color = "var(--warn)";
    } else {
        bar.style.color = "var(--muted)";
    }
}

function estimateInputTokens(queryText: string): number {
    // Client-side estimate using 4 chars/token heuristic
    // Matches the server-side default ratio
    const charsPerToken = 4;
    const systemPromptEstimate = 200;  // fixed overhead
    const templateOverhead = 50;
    const queryTokens = Math.max(1, Math.floor(queryText.length / charsPerToken));
    // Memory + chunks are unknown client-side; use 0 (conservative underestimate)
    // The server-side POST endpoint provides accurate calculation if needed
    return systemPromptEstimate + queryTokens + templateOverhead;
}

// In initializeConsoleUi(), add:
// void fetchTokenBudget();

// After each query response completes, add:
// updateTokenBudgetDisplay(estimateInputTokens(queryText));
```

**Key design decisions:**
- Client-side estimation is an underestimate (missing memory + chunks) but directionally useful
- Color thresholds use existing CSS variables (`--warn`, `--err`) for consistency
- `fetchTokenBudget()` is fire-and-forget on page load — non-blocking
- Fetch failure silently shows "tokens: unknown" — no error toast or console spam

---

## B.6: CLI Token Budget Display

Right-aligned ANSI-styled budget line for both local and remote CLI. Supports Task 4.1 and Task 4.2.

**Tasks:** Task 4.1, Task 4.2
**Requirements:** REQ-501, REQ-502, REQ-503, REQ-504

```python
from __future__ import annotations

import os

# ANSI color constants (already defined in CLI modules)
# RESET, DIM, B_YELLOW, B_RED


def format_token_budget_line(
    input_tokens: int,
    context_length: int,
    usage_percent: float,
    warn_percent: float = 70.0,
    critical_percent: float = 90.0,
) -> str:
    """Format a right-aligned token budget line with ANSI color."""
    label = f"[~{input_tokens:,} / {context_length:,} tokens · {usage_percent:.1f}%]"

    if usage_percent >= critical_percent:
        styled = f"{B_RED}{label}{RESET}"
    elif usage_percent >= warn_percent:
        styled = f"{B_YELLOW}{label}{RESET}"
    else:
        styled = f"{DIM}{label}{RESET}"

    try:
        width = os.get_terminal_size(fallback=(80, 24)).columns
    except (ValueError, OSError):
        width = 80

    padding = max(0, width - len(label))
    return " " * padding + styled


def print_token_budget(snapshot) -> None:
    """Print the token budget line. Safe to call with None (shows unknown)."""
    if snapshot is None:
        try:
            width = os.get_terminal_size(fallback=(80, 24)).columns
        except (ValueError, OSError):
            width = 80
        label = "[tokens: unknown]"
        padding = max(0, width - len(label))
        print(" " * padding + f"{DIM}{label}{RESET}")
        return

    print(format_token_budget_line(
        input_tokens=snapshot.input_tokens,
        context_length=snapshot.context_length,
        usage_percent=snapshot.usage_percent,
    ))


# Usage in the REPL loop (cli.py), after display_results():
#
# try:
#     caps = get_capabilities()
#     snapshot = calculate_budget(
#         caps,
#         system_prompt=_SYSTEM_PROMPT,
#         memory_context=memory_ctx,
#         chunks=context_chunks,
#         query=query_text,
#     )
# except Exception:
#     snapshot = None
# print_token_budget(snapshot)
```

**Key design decisions:**
- `format_token_budget_line` is a pure function (testable): takes values, returns string
- `print_token_budget` handles `None` gracefully with the fallback display
- Terminal width detection uses `os.get_terminal_size()` with fallback to 80
- ANSI escape codes are excluded from width calculation (only `label` length counts)
- This function can be shared between local and remote CLI via a common module

---

## B.7: Configuration Reference

All token budget configuration parameters, added to the centralized settings module.

**Tasks:** Task 1.2
**Requirements:** REQ-903

```python
# Added to config/settings.py

# --- Token budget ---
TOKEN_BUDGET_DEFAULT_CONTEXT_LENGTH = int(
    os.environ.get("RAG_TOKEN_BUDGET_DEFAULT_CONTEXT_LENGTH", "2048")
)
TOKEN_BUDGET_CHARS_PER_TOKEN = int(
    os.environ.get("RAG_TOKEN_BUDGET_CHARS_PER_TOKEN", "4")
)
TOKEN_BUDGET_WARN_PERCENT = float(
    os.environ.get("RAG_TOKEN_BUDGET_WARN_PERCENT", "70")
)
TOKEN_BUDGET_CRITICAL_PERCENT = float(
    os.environ.get("RAG_TOKEN_BUDGET_CRITICAL_PERCENT", "90")
)
```

**Key design decisions:**
- Follows the existing `config/settings.py` pattern: `os.environ.get()` with string default, cast to type
- All env var names prefixed with `RAG_` for consistency with the rest of the config
- `CHARS_PER_TOKEN` is an integer (not float) because the heuristic uses integer division
- Thresholds are floats to allow fine-grained tuning (e.g., 72.5%)
