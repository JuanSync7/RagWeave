# Retrieval Query Pipeline — Design Document

| Field | Value |
|-------|-------|
| **Document** | Retrieval Query Pipeline Design Document |
| **Version** | 1.2 |
| **Status** | Draft |
| **Spec Reference** | `RETRIEVAL_QUERY_SPEC.md` v1.2 (REQ-101–REQ-403, REQ-1001–REQ-1008) |
| **Companion Documents** | `RETRIEVAL_QUERY_SPEC.md`, `RETRIEVAL_QUERY_IMPLEMENTATION.md`, `RETRIEVAL_SPEC_SUMMARY.md` |
| **Created** | 2026-03-11 |
| **Last Updated** | 2026-03-23 |

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-03-11 | Initial draft — 5 phases, 17 tasks covering core pipeline through security |
| 1.1 | 2026-03-13 | Added Phase 6 (conversation memory) covering REQ-1001–1008, updated dependency graph and mapping |
| 1.2 | 2026-03-23 | Renamed from Implementation Guide to Design Document; added Contract/Pattern annotations to Part B; added companion document references |
| 1.3 | 2026-03-25 | Split from RETRIEVAL_DESIGN.md; now covers query-side tasks only (Tasks 1.1, 1.4, 2.3, 3.4, 4.1–4.3, 5.1–5.2, 6.1–6.4) |

> **Document Intent.** This document provides a technical design with task decomposition
> and contract-grade code appendix for the retrieval pipeline specified in
> `RETRIEVAL_QUERY_SPEC.md` / `RETRIEVAL_GENERATION_SPEC.md`. Every task references the
> requirements it satisfies. Part B contract entries are consumed verbatim by the companion
> implementation plan (`RETRIEVAL_QUERY_IMPLEMENTATION.md`).

---

# Part A: Task-Oriented Overview

## Phase 1 — Core Pipeline Hardening

Foundation work: guardrails, validation, and resilience. These tasks make the pipeline safe before adding new capabilities.

### Task 1.1: Pre-Retrieval Guardrail Layer

**Description:** Build a guardrail module that sits between query processing and retrieval. It validates inputs, detects injection, classifies risk, and optionally filters PII from the query.

**Requirements Covered:** REQ-201, REQ-202, REQ-203, REQ-204, REQ-205, REQ-903

**Dependencies:** None — this is a new module.

**Complexity:** M

**Subtasks:**

1. Define a `GuardrailResult` data structure (pass/reject, risk level, sanitized query, PII detections)
2. Implement input validation (query length, parameter ranges, filter sanitization)
3. Load injection patterns from external YAML config file
4. Implement risk classifier with externalized keyword taxonomy
5. Implement conditional PII filtering (gated on `EXTERNAL_LLM_MODE` config flag)
6. Wire into the pipeline between query processing and retrieval

---

### Task 1.4: Input Validation at System Boundaries

**Description:** Add validation for all external inputs that flow into the retrieval pipeline: search parameters, metadata filters, and query content.

**Requirements Covered:** REQ-201, REQ-903

**Dependencies:** None. Can be implemented within Task 1.1 or as a standalone utility.

**Complexity:** S

**Subtasks:**

1. Define valid ranges for `alpha` (0.0–1.0), `search_limit` (1–100), `rerank_top_k` (1–50)
2. Sanitize metadata filter values (prevent Weaviate query language injection)
3. Validate query length (min/max configurable)
4. Return structured error responses for invalid inputs (not exceptions)

---

### Task 2.3: Risk Classification

**Description:** Implement deterministic keyword-based risk classification for queries. HIGH risk queries trigger additional verification in the post-generation guardrail.

**Requirements Covered:** REQ-203, REQ-705, REQ-903

**Dependencies:** None — standalone classifier.

**Complexity:** S

**Subtasks:**

1. Define risk taxonomy (HIGH/MEDIUM/LOW keyword lists) in external config file
2. Implement classifier: scan query for keyword matches, return highest matching level
3. Attach risk level to pipeline state for downstream use
4. Ensure taxonomy config is reloadable on restart

---

### Task 3.4: Multi-Turn Context / Coreference Resolution

**Description:** Add conversation history tracking and coreference resolution to the query processing stage. Enable follow-up queries that reference prior turns.

**Requirements Covered:** REQ-103

**Dependencies:** None, but integrates with Task 2.2 (pipeline state must carry conversation history).

**Complexity:** M

**Subtasks:**

1. Define a conversation buffer (last N turns, configurable)
2. Thread conversation history through the pipeline state
3. Modify the query reformulation prompt to include recent conversation context
4. Implement coreference resolution: detect pronouns/references and resolve against prior turns
5. Optionally persist conversation state (JSON file or in-memory with TTL)

---

## Phase 4 — Performance & Observability

Make the pipeline fast and debuggable.

### Task 4.1: Connection Pooling for Vector Database

**Description:** Replace per-query connection creation with a persistent connection pool. Add health checks on startup.

**Requirements Covered:** REQ-307

**Dependencies:** None.

**Complexity:** S

**Subtasks:**

1. Create a connection pool manager (singleton or module-level)
2. Support external vector database via URL configuration (not just embedded)
3. Implement startup health check (fail-fast if DB is unreachable)
4. Implement periodic liveness checks during operation
5. Handle connection failures with reconnection logic

---

### Task 4.2: Embedding Cache (LRU)

**Description:** Add an LRU cache around the query embedding function. Identical queries return cached embeddings without recomputation.

**Requirements Covered:** REQ-306

**Dependencies:** None.

**Complexity:** S

**Subtasks:**

1. Wrap the embed_query function with an LRU cache (configurable max size)
2. Use the raw query string as cache key (normalize whitespace)
3. Ensure cache is thread-safe if concurrent queries are supported
4. Add cache hit/miss metrics for observability (REQ-802)
5. Externalize cache size to config (REQ-903)

---

### Task 4.3: Query Result Cache (TTL)

**Description:** Cache full pipeline responses keyed by `(processed_query, filters)` with a configurable TTL. Cache hits bypass all downstream stages.

**Requirements Covered:** REQ-308

**Dependencies:** None, but should be placed early in the pipeline (after query processing, before retrieval).

**Complexity:** S

**Subtasks:**

1. Define cache key: normalized `(processed_query, source_filter, heading_filter, alpha)` tuple
2. Implement TTL-based cache (dict + timestamps, or `cachetools.TTLCache`)
3. On cache hit, return cached response immediately
4. On cache miss, proceed through pipeline and store result
5. Add cache bypass flag for debugging
6. Externalize TTL and max cache size to config (REQ-903)

---

## Phase 5 — Security

Harden the pipeline against data leakage and injection.

### Task 5.1: Externalize Injection Patterns

**Description:** Move hardcoded injection detection patterns to an external config file. Patterns are loaded at startup and applied during pre-retrieval guardrail processing.

**Requirements Covered:** REQ-202, REQ-903

**Dependencies:** Task 1.1 (pre-retrieval guardrail — this is a subtask of 1.1, broken out for clarity).

**Complexity:** S

**Subtasks:**

1. Create a YAML/JSON config file for injection patterns
2. Migrate existing hardcoded patterns to the config file
3. Load patterns at startup, compile to regex
4. Log pattern count on load for verification
5. Document the pattern format for maintainers

---

### Task 5.2: Pre-Retrieval PII Filtering

**Description:** Detect and redact PII from user queries before they are sent to external LLM APIs. Conditional on `EXTERNAL_LLM_MODE` configuration flag.

**Requirements Covered:** REQ-204

**Dependencies:** Task 1.1 (pre-retrieval guardrail — this is a subtask of 1.1, broken out for clarity).

**Complexity:** M

**Subtasks:**

1. Implement regex-based PII detection (email, phone, SSN/employee ID patterns)
2. Implement NER-based person name detection (optional, using existing entity extraction or a lightweight model)
3. Replace detected PII with typed placeholders (`[PERSON]`, `[EMAIL]`, `[PHONE]`)
4. Preserve original query internally (for retrieval against local DB — PII is fine locally)
5. Only activate when `EXTERNAL_LLM_MODE=true` in config
6. Log PII detection events (count, types) without logging the actual PII values

---

## Phase 6 — Conversation Memory

Persistent multi-turn conversation support with tenant isolation, sliding window context, rolling summaries, and lifecycle management.

### Task 6.1: Conversation Memory Provider

**Description:** Build a tenant-scoped conversation memory provider that persists turns and summaries in a dedicated data store with TTL-based expiration.

**Requirements Covered:** REQ-1001, REQ-1007

**Dependencies:** None — standalone module.

**Complexity:** M

**Subtasks:**

1. Define a `ConversationTurn` and `ConversationMeta` data model with tenant, principal, conversation ID, timestamp, and content fields
2. Implement a provider interface with `store_turn`, `get_turns`, `get_meta`, `list_conversations` operations
3. Implement a persistent backend using a key-value store with TTL support
4. Enforce tenant and principal isolation at the provider level (all operations scoped by tenant + principal)
5. Add configurable TTL for automatic conversation expiration
6. Add an in-memory fallback provider for development/offline use

**Risks:** Data store latency on turn persistence could add overhead to every query; mitigate by writing turns asynchronously where possible.

---

### Task 6.2: Sliding Window and Rolling Summary

**Description:** Implement the context assembly strategy that combines a sliding window of recent turns with a rolling summary of older turns.

**Requirements Covered:** REQ-1002, REQ-1003, REQ-1008

**Dependencies:** Task 6.1

**Complexity:** M

**Subtasks:**

1. Implement sliding window extraction (last N turns from conversation history)
2. Implement rolling summary storage and retrieval as a special metadata field on the conversation
3. Implement compaction logic that summarizes turns outside the window into the rolling summary using an LLM call
4. Format the combined context (rolling summary + recent turns) for injection into query processing
5. Externalize window size, compaction threshold, and summary max tokens to configuration

**Risks:** LLM-based compaction can hallucinate or lose key entities; mitigate by preserving entity lists alongside the summary.

---

### Task 6.3: Conversation Lifecycle Operations

**Description:** Implement the API-facing lifecycle operations: create conversation, list conversations, get history, and trigger manual compaction.

**Requirements Covered:** REQ-1004, REQ-1005, REQ-1006

**Dependencies:** Task 6.1, Task 6.2

**Complexity:** M

**Subtasks:**

1. Implement `create_conversation` that generates a stable ID and returns it
2. Implement `list_conversations` that returns metadata for all conversations owned by a tenant/principal
3. Implement `get_history` that returns the full ordered turn list for a conversation
4. Implement `compact_conversation` that triggers rolling summary compaction on demand
5. Wire per-request controls: `memory_enabled`, `memory_turn_window`, `compact_now` flags on query requests
6. Ensure `conversation_id` is returned in every query response when memory is active

**Testing Strategy:** Integration tests verifying create → query → follow-up → list → history → compact lifecycle.

---

### Task 6.4: Memory Context Injection into Query Processing

**Description:** Thread conversation memory context into the query processing stage so that coreference resolution and reformulation benefit from prior turns and the rolling summary.

**Requirements Covered:** REQ-1008, REQ-103

**Dependencies:** Task 6.2, Task 3.4

**Complexity:** S

**Subtasks:**

1. Modify the query processing entry point to accept optional memory context (recent turns + summary)
2. Inject memory context into the reformulation prompt alongside conversation history
3. Ensure memory-disabled queries bypass injection entirely
4. Add metrics for memory context token count and injection latency

---

## Task Dependency Graph

```
Phase 1 (Foundation)
├── Task 1.1: Pre-Retrieval Guardrail
├── Task 1.3: Retry Logic                                     [see RETRIEVAL_GENERATION_DESIGN.md]
├── Task 1.4: Input Validation (can merge into 1.1)
│
Phase 2 (Confidence & Routing)
├── Task 2.3: Risk Classification ◄────Task 1.1
├── Task 2.1: 3-Signal Confidence                             [see RETRIEVAL_GENERATION_DESIGN.md]
│
├── Task 1.2: Post-Generation Guardrail ◄── Task 2.1, 2.3     [see RETRIEVAL_GENERATION_DESIGN.md]
│
└── Task 2.2: Full-Pipeline LangGraph ◄── Task 1.1, 1.2, 2.1  [see RETRIEVAL_GENERATION_DESIGN.md]

Phase 3 (Retrieval Quality)
├── Task 3.1: Document Formatter                              [see RETRIEVAL_GENERATION_DESIGN.md]
├── Task 3.2: Version Conflict Detection ◄── Task 3.1         [see RETRIEVAL_GENERATION_DESIGN.md]
├── Task 3.3: PromptTemplate Integration                      [see RETRIEVAL_GENERATION_DESIGN.md]
└── Task 3.4: Multi-Turn Context

Phase 4 (Performance & Observability)
├── Task 4.1: Connection Pooling
├── Task 4.2: Embedding Cache
├── Task 4.3: Query Result Cache
└── Task 4.4: Observability ◄── All pipeline stages           [see RETRIEVAL_GENERATION_DESIGN.md]

Phase 5 (Security)
├── Task 5.1: Externalize Injection Patterns ◄── Task 1.1
├── Task 5.2: Pre-Retrieval PII Filtering ◄── Task 1.1
└── Task 5.3: Post-Generation PII Filtering ◄── Task 1.2      [see RETRIEVAL_GENERATION_DESIGN.md]

Phase 6 (Conversation Memory)
├── Task 6.1: Conversation Memory Provider ──────────────────────┐
├── Task 6.2: Sliding Window and Rolling Summary ◄── Task 6.1 ──┤
├── Task 6.3: Conversation Lifecycle Operations ◄── Task 6.1,6.2┤
└── Task 6.4: Memory Context Injection ◄── Task 6.2, Task 3.4 ──┘
```

---

## Task-to-Requirement Mapping

| Task | Requirements Covered |
|------|---------------------|
| 1.1 Pre-Retrieval Guardrail | REQ-201, REQ-202, REQ-203, REQ-204, REQ-205, REQ-903 |
| 1.4 Input Validation | REQ-201, REQ-903 |
| 2.3 Risk Classification | REQ-203, REQ-705, REQ-903 |
| 3.4 Multi-Turn Context | REQ-103 |
| 4.1 Connection Pooling | REQ-307 |
| 4.2 Embedding Cache | REQ-306 |
| 4.3 Query Result Cache | REQ-308 |
| 5.1 Externalize Injection Patterns | REQ-202, REQ-903 |
| 5.2 Pre-Retrieval PII Filtering | REQ-204 |
| 6.1 Conversation Memory Provider | REQ-1001, REQ-1007 |
| 6.2 Sliding Window and Rolling Summary | REQ-1002, REQ-1003, REQ-1008 |
| 6.3 Conversation Lifecycle Operations | REQ-1004, REQ-1005, REQ-1006 |
| 6.4 Memory Context Injection | REQ-1008, REQ-103 |

---

# Part B: Code Appendix

## B.1: Pre-Retrieval Guardrail — Contract

**Tasks:** Task 1.1, Task 1.4, Task 2.3
**Requirements:** REQ-201, REQ-202, REQ-203, REQ-204, REQ-205, REQ-903
**Type:** Contract (exact — copied to implementation plan Phase 0)

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import re
import yaml


class RiskLevel(Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class GuardrailAction(Enum):
    PASS = "pass"
    REJECT = "reject"


@dataclass
class GuardrailResult:
    action: GuardrailAction
    risk_level: RiskLevel
    sanitized_query: str
    rejection_reason: Optional[str] = None      # Internal log only
    user_message: Optional[str] = None           # User-safe message
    pii_detections: list[dict] = field(default_factory=list)


class PreRetrievalGuardrail:
    def __init__(self, config_path: str = "config/guardrails.yaml"):
        with open(config_path) as f:
            config = yaml.safe_load(f)

        self.max_query_length = config.get("max_query_length", 500)
        self.min_query_length = config.get("min_query_length", 2)
        self.injection_patterns = [
            re.compile(p, re.IGNORECASE)
            for p in config.get("injection_patterns", [])
        ]
        self.risk_taxonomy = config.get("risk_taxonomy", {})
        self.param_ranges = config.get("parameter_ranges", {
            "alpha": {"min": 0.0, "max": 1.0},
            "search_limit": {"min": 1, "max": 100},
            "rerank_top_k": {"min": 1, "max": 50},
        })
        self.external_llm_mode = config.get("external_llm_mode", False)

    def validate(
        self,
        query: str,
        alpha: float = 0.5,
        search_limit: int = 10,
        rerank_top_k: int = 5,
        source_filter: Optional[str] = None,
        heading_filter: Optional[str] = None,
    ) -> GuardrailResult:
        # 1. Length validation
        if len(query.strip()) < self.min_query_length:
            return GuardrailResult(
                action=GuardrailAction.REJECT,
                risk_level=RiskLevel.LOW,
                sanitized_query=query,
                rejection_reason="Query too short",
                user_message="Please provide a more detailed query.",
            )

        if len(query) > self.max_query_length:
            return GuardrailResult(
                action=GuardrailAction.REJECT,
                risk_level=RiskLevel.LOW,
                sanitized_query=query,
                rejection_reason=f"Query exceeds {self.max_query_length} chars",
                user_message="Your query is too long. Please shorten it.",
            )

        # 2. Parameter range validation
        param_errors = self._validate_params(alpha, search_limit, rerank_top_k)
        if param_errors:
            return GuardrailResult(
                action=GuardrailAction.REJECT,
                risk_level=RiskLevel.LOW,
                sanitized_query=query,
                rejection_reason=f"Invalid parameters: {param_errors}",
                user_message="Invalid search parameters provided.",
            )

        # 3. Injection detection
        for pattern in self.injection_patterns:
            if pattern.search(query):
                return GuardrailResult(
                    action=GuardrailAction.REJECT,
                    risk_level=RiskLevel.LOW,
                    sanitized_query=query,
                    rejection_reason="Injection pattern detected",
                    user_message="Your query could not be processed.",
                )

        # 4. Risk classification
        risk_level = self._classify_risk(query)

        # 5. PII filtering (conditional)
        sanitized_query = query
        pii_detections = []
        if self.external_llm_mode:
            sanitized_query, pii_detections = self._filter_pii(query)

        return GuardrailResult(
            action=GuardrailAction.PASS,
            risk_level=risk_level,
            sanitized_query=sanitized_query,
            pii_detections=pii_detections,
        )

    def _validate_params(
        self, alpha: float, search_limit: int, rerank_top_k: int
    ) -> list[str]:
        errors = []
        ranges = self.param_ranges
        if not (ranges["alpha"]["min"] <= alpha <= ranges["alpha"]["max"]):
            errors.append(f"alpha must be {ranges['alpha']['min']}-{ranges['alpha']['max']}")
        if not (ranges["search_limit"]["min"] <= search_limit <= ranges["search_limit"]["max"]):
            errors.append(f"search_limit must be {ranges['search_limit']['min']}-{ranges['search_limit']['max']}")
        if not (ranges["rerank_top_k"]["min"] <= rerank_top_k <= ranges["rerank_top_k"]["max"]):
            errors.append(f"rerank_top_k must be {ranges['rerank_top_k']['min']}-{ranges['rerank_top_k']['max']}")
        return errors

    def _classify_risk(self, query: str) -> RiskLevel:
        query_lower = query.lower()
        for keyword in self.risk_taxonomy.get("HIGH", []):
            if keyword in query_lower:
                return RiskLevel.HIGH
        for keyword in self.risk_taxonomy.get("MEDIUM", []):
            if keyword in query_lower:
                return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _filter_pii(self, query: str) -> tuple[str, list[dict]]:
        detections = []
        filtered = query

        # Email
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        for match in re.finditer(email_pattern, filtered):
            detections.append({"type": "EMAIL", "position": match.span()})
        filtered = re.sub(email_pattern, "[EMAIL]", filtered)

        # Phone (basic international patterns)
        phone_pattern = r'\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b'
        for match in re.finditer(phone_pattern, filtered):
            detections.append({"type": "PHONE", "position": match.span()})
        filtered = re.sub(phone_pattern, "[PHONE]", filtered)

        # Employee ID (alphanumeric patterns like EMP-12345, E12345)
        emp_pattern = r'\b(?:EMP[-.]?\d{4,8}|E\d{5,8})\b'
        for match in re.finditer(emp_pattern, filtered, re.IGNORECASE):
            detections.append({"type": "EMPLOYEE_ID", "position": match.span()})
        filtered = re.sub(emp_pattern, "[EMPLOYEE_ID]", filtered, flags=re.IGNORECASE)

        return filtered, detections
```

---

## B.2: Risk Classification Config — Contract

**Tasks:** Task 2.3, Task 5.1
**Requirements:** REQ-203, REQ-202, REQ-903
**Type:** Contract (exact — copied to implementation plan Phase 0)

```yaml
# config/guardrails.yaml

max_query_length: 500
min_query_length: 2
external_llm_mode: false

parameter_ranges:
  alpha:
    min: 0.0
    max: 1.0
  search_limit:
    min: 1
    max: 100
  rerank_top_k:
    min: 1
    max: 50

risk_taxonomy:
  HIGH:
    # Electrical
    - "voltage"
    - "current"
    - "power domain"
    - "supply rail"
    - "vdd"
    - "vss"
    # Timing
    - "timing constraint"
    - "setup time"
    - "hold time"
    - "clock frequency"
    - "propagation delay"
    - "skew"
    - "jitter"
    # Safety/Compliance
    - "iso26262"
    - "do-254"
    - "safety"
    - "compliance"
    - "functional safety"
    - "hazard"
    - "fault"
    - "asil"
    # Critical specs
    - "threshold"
    - "limit"
    - "maximum"
    - "minimum"
    - "specification"
    - "temperature range"
    - "operating condition"
  MEDIUM:
    - "procedure"
    - "guideline"
    - "checklist"
    - "review"
    - "signoff"
    - "flow"
    - "methodology"
    - "constraint file"
    - "sdc"
    - "upf"

injection_patterns:
  - "ignore.*(all|previous|prior|above).*instructions"
  - "you are now"
  - "^system:\\s"
  - "<\\/?[a-z]+>"
  - "\\[INST\\]"
  - "forget.*(everything|all|previous)"
  - "(sudo|admin|root)\\s+(access|mode|command)"
  - "disregard.*prompt"
  - "override.*safety"
```

---

## B.8: Embedding Cache — Pattern

**Tasks:** Task 4.2
**Requirements:** REQ-306
**Type:** Pattern (illustrative — shows approach, not exact contract)

```python
from functools import lru_cache
from typing import Protocol


class EmbeddingModel(Protocol):
    def embed_query(self, text: str) -> list[float]: ...


class CachedEmbeddings:
    """LRU-cached wrapper around any embedding model."""

    def __init__(self, model: EmbeddingModel, cache_size: int = 256):
        self._model = model
        self._cache_size = cache_size
        # Create a bound cached function
        self._cached_embed = lru_cache(maxsize=cache_size)(self._embed)

    def embed_query(self, text: str) -> list[float]:
        # Normalize whitespace for consistent cache keys
        normalized = " ".join(text.split())
        return self._cached_embed(normalized)

    def _embed(self, text: str) -> tuple[float, ...]:
        """Internal — returns tuple for hashability (lru_cache requirement)."""
        result = self._model.embed_query(text)
        return tuple(result)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Documents are not cached — typically one-time ingestion."""
        return self._model.embed_documents(texts)

    @property
    def cache_info(self):
        return self._cached_embed.cache_info()

    def clear_cache(self):
        self._cached_embed.cache_clear()
```

---

## B.9: Query Result Cache — Pattern

**Tasks:** Task 4.3
**Requirements:** REQ-308
**Type:** Pattern (illustrative — shows approach, not exact contract)

```python
import time
import hashlib
from dataclasses import dataclass
from typing import Optional, Any


@dataclass
class CacheEntry:
    response: Any
    timestamp: float
    query_key: str


class QueryResultCache:
    """TTL-based cache for full pipeline responses."""

    def __init__(self, ttl_seconds: int = 300, max_size: int = 100):
        self._cache: dict[str, CacheEntry] = {}
        self._ttl = ttl_seconds
        self._max_size = max_size

    def get(
        self,
        processed_query: str,
        source_filter: Optional[str] = None,
        heading_filter: Optional[str] = None,
        alpha: float = 0.5,
    ) -> Optional[Any]:
        key = self._make_key(processed_query, source_filter, heading_filter, alpha)
        entry = self._cache.get(key)

        if entry is None:
            return None

        if time.time() - entry.timestamp > self._ttl:
            del self._cache[key]
            return None

        return entry.response

    def put(
        self,
        response: Any,
        processed_query: str,
        source_filter: Optional[str] = None,
        heading_filter: Optional[str] = None,
        alpha: float = 0.5,
    ) -> None:
        # Evict oldest if at capacity
        if len(self._cache) >= self._max_size:
            oldest_key = min(self._cache, key=lambda k: self._cache[k].timestamp)
            del self._cache[oldest_key]

        key = self._make_key(processed_query, source_filter, heading_filter, alpha)
        self._cache[key] = CacheEntry(
            response=response,
            timestamp=time.time(),
            query_key=key,
        )

    def _make_key(
        self,
        query: str,
        source_filter: Optional[str],
        heading_filter: Optional[str],
        alpha: float,
    ) -> str:
        normalized_query = " ".join(query.lower().split())
        raw = f"{normalized_query}|{source_filter}|{heading_filter}|{alpha}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def clear(self) -> None:
        self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)
```

---

## B.10: Connection Pool Manager — Pattern

**Tasks:** Task 4.1
**Requirements:** REQ-307
**Type:** Pattern (illustrative — shows approach, not exact contract)

```python
import logging
from typing import Optional
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class VectorDBPool:
    """Persistent connection pool for the vector database."""

    def __init__(
        self,
        db_url: Optional[str] = None,
        data_path: str = ".weaviate_data",
        health_check_interval: int = 60,
    ):
        self._db_url = db_url
        self._data_path = data_path
        self._client = None
        self._health_check_interval = health_check_interval

    def connect(self) -> None:
        """Initialize the connection. Call once at startup."""
        if self._db_url:
            # External vector DB
            self._client = self._connect_external(self._db_url)
        else:
            # Embedded vector DB
            self._client = self._connect_embedded(self._data_path)

        # Fail-fast health check
        if not self._health_check():
            raise ConnectionError("Vector database health check failed on startup.")

        logger.info("Vector database connection established.")

    def get_client(self):
        """Return the persistent client. Reconnect if needed."""
        if self._client is None:
            self.connect()

        if not self._health_check():
            logger.warning("Vector database connection lost. Reconnecting...")
            self.connect()

        return self._client

    def close(self) -> None:
        """Close the connection pool."""
        if self._client is not None:
            self._client.close()
            self._client = None
            logger.info("Vector database connection closed.")

    def _health_check(self) -> bool:
        """Check if the vector database is reachable."""
        try:
            self._client.is_ready()
            return True
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    def _connect_external(self, url: str):
        """Connect to an external vector database instance."""
        import weaviate
        return weaviate.connect_to_custom(
            http_host=url.split("://")[1].split(":")[0],
            http_port=int(url.split(":")[-1]),
            http_secure=url.startswith("https"),
        )

    def _connect_embedded(self, data_path: str):
        """Connect to an embedded vector database instance."""
        import weaviate
        return weaviate.connect_to_embedded(
            persistence_data_path=data_path
        )
```

---

## B.14: Multi-Turn Conversation State — Pattern

**Tasks:** Task 3.4
**Requirements:** REQ-103
**Type:** Pattern (illustrative — shows coreference approach, superseded by B.15 for persistent memory)

```python
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ConversationTurn:
    query: str
    processed_query: str
    answer: Optional[str]


@dataclass
class ConversationState:
    turns: list[ConversationTurn] = field(default_factory=list)
    max_turns: int = 5

    def add_turn(self, query: str, processed_query: str, answer: Optional[str] = None):
        self.turns.append(ConversationTurn(
            query=query,
            processed_query=processed_query,
            answer=answer,
        ))
        # Keep only last N turns
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns:]

    def get_context_for_reformulation(self) -> str:
        """Format recent turns as context for the query reformulator."""
        if not self.turns:
            return ""

        lines = ["Recent conversation context:"]
        for i, turn in enumerate(self.turns[-3:], 1):  # Last 3 turns
            lines.append(f"  Turn {i}:")
            lines.append(f"    User: {turn.query}")
            if turn.answer:
                # Truncate long answers
                answer_preview = turn.answer[:200] + "..." if len(turn.answer) > 200 else turn.answer
                lines.append(f"    Assistant: {answer_preview}")

        return "\n".join(lines)

    def resolve_coreferences(self, query: str) -> str:
        """
        Basic coreference resolution against recent conversation context.

        Detects pronouns and references that likely refer to prior turns.
        For production, consider using a dedicated coreference resolution model.
        """
        if not self.turns:
            return query

        # Patterns that suggest a follow-up question
        followup_indicators = [
            "tell me more",
            "what about",
            "how about",
            "and the",
            "what else",
            "can you elaborate",
            "more details",
            "expand on",
        ]

        query_lower = query.lower()
        is_followup = any(indicator in query_lower for indicator in followup_indicators)

        # Check for pronoun-heavy queries with little context
        pronoun_heavy = query_lower.strip().startswith(("it ", "its ", "that ", "this ", "they ", "those "))

        if is_followup or pronoun_heavy:
            # Prepend context from the last turn
            last_turn = self.turns[-1]
            context_prefix = f"Regarding '{last_turn.processed_query}': "
            return context_prefix + query

        return query
```

---

## B.15: Conversation Memory Provider — Contract

This snippet shows a tenant-scoped conversation memory provider with sliding window extraction, rolling summary support, and TTL-based expiration.

**Tasks:** Task 6.1, Task 6.2
**Requirements:** REQ-1001, REQ-1002, REQ-1003, REQ-1007
**Type:** Contract (exact — copied to implementation plan Phase 0)

```python
from dataclasses import dataclass, field
from typing import Optional, Protocol
import time


@dataclass
class ConversationTurn:
    role: str
    content: str
    timestamp_ms: int
    query_id: str = ""


@dataclass
class ConversationMeta:
    conversation_id: str
    tenant_id: str
    subject: str
    project_id: str = ""
    title: str = ""
    created_at_ms: int = 0
    updated_at_ms: int = 0
    message_count: int = 0
    summary: dict = field(default_factory=dict)


class MemoryProvider(Protocol):
    """Interface for conversation memory storage."""

    def store_turn(
        self, tenant_id: str, conversation_id: str, turn: ConversationTurn
    ) -> None: ...

    def get_turns(
        self, tenant_id: str, conversation_id: str, limit: Optional[int] = None
    ) -> list[ConversationTurn]: ...

    def get_meta(
        self, tenant_id: str, conversation_id: str
    ) -> Optional[ConversationMeta]: ...

    def list_conversations(
        self, tenant_id: str, subject: str
    ) -> list[ConversationMeta]: ...

    def store_summary(
        self, tenant_id: str, conversation_id: str, summary: dict
    ) -> None: ...


def assemble_memory_context(
    provider: MemoryProvider,
    tenant_id: str,
    conversation_id: str,
    window_size: int = 5,
) -> str:
    """Assemble sliding window + rolling summary into query processing context."""
    meta = provider.get_meta(tenant_id, conversation_id)
    if meta is None:
        return ""

    recent_turns = provider.get_turns(tenant_id, conversation_id, limit=window_size)
    parts = []

    if meta.summary and meta.summary.get("text"):
        parts.append(f"Conversation summary: {meta.summary['text']}")

    for turn in recent_turns:
        parts.append(f"{turn.role}: {turn.content}")

    return "\n".join(parts)
```

**Key design decisions:**
- Provider interface enables swapping storage backends without changing callers.
- Sliding window is extracted at read time, not write time, so window size can be overridden per request.
- Rolling summary is stored as metadata on the conversation, not as a separate entity.

---

## B.16: Conversation Lifecycle Operations — Pattern

This snippet shows the API-facing lifecycle operations for conversation management.

**Tasks:** Task 6.3
**Requirements:** REQ-1004, REQ-1005, REQ-1006
**Type:** Pattern (illustrative — shows service layer approach)

```python
from dataclasses import dataclass
from typing import Optional
from uuid import uuid4
import time


@dataclass
class CreateConversationResult:
    conversation_id: str
    tenant_id: str
    title: str


class ConversationService:
    """Manages conversation lifecycle for a tenant and principal."""

    def __init__(self, provider: MemoryProvider, default_window: int = 5):
        self._provider = provider
        self._default_window = default_window

    def create(
        self,
        tenant_id: str,
        subject: str,
        title: str = "New conversation",
        conversation_id: Optional[str] = None,
    ) -> CreateConversationResult:
        cid = conversation_id or f"conv-{uuid4().hex[:16]}"
        now_ms = int(time.time() * 1000)
        meta = ConversationMeta(
            conversation_id=cid,
            tenant_id=tenant_id,
            subject=subject,
            title=title,
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
        )
        self._provider.store_meta(tenant_id, cid, meta)
        return CreateConversationResult(
            conversation_id=cid, tenant_id=tenant_id, title=title
        )

    def list_for_principal(
        self, tenant_id: str, subject: str
    ) -> list[ConversationMeta]:
        return self._provider.list_conversations(tenant_id, subject)

    def get_history(
        self, tenant_id: str, conversation_id: str
    ) -> list[ConversationTurn]:
        return self._provider.get_turns(tenant_id, conversation_id)

    def compact(self, tenant_id: str, conversation_id: str) -> dict:
        """Trigger rolling summary compaction for the conversation."""
        turns = self._provider.get_turns(tenant_id, conversation_id)
        if len(turns) <= self._default_window:
            return {"compacted": False, "reason": "Not enough turns to compact"}

        older_turns = turns[: -self._default_window]
        summary_text = self._summarize_turns(older_turns)
        self._provider.store_summary(
            tenant_id, conversation_id, {"text": summary_text}
        )
        return {"compacted": True, "turns_summarized": len(older_turns)}

    def _summarize_turns(self, turns: list[ConversationTurn]) -> str:
        """Summarize older turns into a condensed rolling summary."""
        # Production: call LLM for summarization
        # Fallback: concatenate key content
        content = "\n".join(f"{t.role}: {t.content[:200]}" for t in turns)
        return content[:2000]
```

**Key design decisions:**
- Service layer wraps the provider to keep route handlers thin.
- Compaction is a separate explicit operation, not automatic, to give operators control.
- Conversation ID is returned on creation and echoed on every subsequent query response.

---

## Document Chain

```
RETRIEVAL_QUERY_SPEC.md ─► RETRIEVAL_QUERY_DESIGN.md ─► RETRIEVAL_QUERY_IMPLEMENTATION.md
```
