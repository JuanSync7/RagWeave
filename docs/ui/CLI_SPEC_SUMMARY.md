# CLI Interface Specification — Summary

## 1) Generic System Overview

### Purpose

The CLI interface layer provides human operators and developers with terminal-based access to the knowledge management platform. It serves two distinct populations: developers who need direct, low-latency access to the retrieval and ingestion pipeline from their local machine, and operators who interact with a deployed server from a remote terminal. Without a unified CLI layer, each population would need bespoke tooling, and behavioral consistency with the web console would be impossible to enforce.

### How It Works

The system exposes three entry points from a shared terminal environment. The first is a fully interactive, locally-executing client that loads all necessary models into the process at startup, then enters a read-eval-print loop where the user can issue natural-language queries or switch to an ingestion mode for batch document processing. Queries are streamed token-by-token as the generation stage produces output; ingestion commands display per-document progress and a final summary.

The second entry point is a thin, interactive client that delegates all computation to a remote server over HTTP. It starts near-instantly, presents an identical command-line interface to the user, and receives generated tokens via a streaming protocol as the server produces them. Authentication is handled at connection time via credentials passed through flags, environment variables, or a configuration file.

The third entry point is a non-interactive batch runner for document ingestion. It accepts input paths, processes documents through the full pipeline, and exits with a structured status code indicating success, partial failure, or total failure. It is designed for automation environments where no terminal interaction is possible.

All three entry points share a common infrastructure layer: a unified command registry that defines every available slash command once, a dispatch runtime that routes `/`-prefixed input to registered handlers, a consistent visual formatting module for colored terminal output, and a tab-completion subsystem that derives candidates from the shared registry.

### Tunable Knobs

Operators can configure the server endpoint for the remote client, allowing redirection to different environments without restarting. Model paths and selection for the local client are externally configurable, enabling model swaps without code changes. Ingestion behavior — including batch size, chunking strategy, and storage endpoint — is tunable via flags or environment variables. Output verbosity can be toggled on a per-session basis to switch between detailed metadata display and clean answer-only output. Color themes and preset storage paths are configurable for environment-specific preferences.

### Design Rationale

The parity constraint — requiring that every feature available in the terminal is also available in the web console — drove the decision to define commands in a single shared registry rather than per-surface. This eliminates an entire class of drift bugs at the cost of a small abstraction layer. The split between a local client and a remote client reflects the tension between developer convenience (local, model-loaded, offline-capable) and production access (no local resources required, server-delegated). Rather than collapsing both into one mode, the spec treats them as two clients of the same product with the same user experience but different backends.

### Boundary Semantics

Entry point: the user invokes one of the three programs from a terminal. The system receives user input (natural-language queries, slash commands, file paths for ingestion). Exit point: the user receives formatted terminal output — streamed answer tokens, structured metadata, progress indicators, error messages, or ingestion summaries. The CLI layer owns everything between those two points: input parsing, command dispatch, backend communication, streaming display, and output formatting. Retrieval pipeline internals, server API contracts, model inference, and web console behavior are explicitly outside this layer's boundary.

---

## 2) Header

| Field | Value |
|-------|-------|
| Companion spec | `CLI_SPEC.md` |
| Spec version | 1.0 |
| Spec date | 2026-03-13 |
| Summary purpose | Concise digest of scope, structure, and key decisions — not a replacement for the spec |
| See also | `SERVER_API_SPEC.md`, `WEB_CONSOLE_SPEC.md`, `RETRIEVAL_QUERY_SPEC.md`, `RETRIEVAL_GENERATION_SPEC.md`, `PLATFORM_SERVICES_SPEC.md`, `INGESTION_PIPELINE_SPEC.md` |

---

## 3) Scope and Boundaries

**Entry point:** User invokes one of the three CLI programs from a terminal.

**Exit point:** User receives formatted terminal output (query results, ingestion status, error messages, or interactive prompts).

**In scope:**

- REPL lifecycle management for interactive clients
- Command dispatch through the shared command registry
- Input handling, tab completion, and live-filtering menus
- Output formatting using the shared ANSI color and badge system
- Streaming display of generated tokens (both local and remote)
- Preset management (save, load, apply named parameter sets)
- Source and heading filter state within a session
- Authentication for the remote client (API key, bearer token)
- Ingestion batch execution with progress reporting and exit codes
- CLI/UI parity enforcement and shared schema contracts

**Out of scope:**

- Retrieval pipeline internals (see `RETRIEVAL_QUERY_SPEC.md` / `RETRIEVAL_GENERATION_SPEC.md`)
- Server API endpoint contracts (see `SERVER_API_SPEC.md`)
- Web console UI behavior (see `WEB_CONSOLE_SPEC.md`)
- Model loading and inference behavior
- Ingestion pipeline internals (see `INGESTION_PIPELINE_SPEC.md`)

---

## 4) Architecture / Pipeline Overview

```
User Terminal
    |
    +-------------------+-------------------+
    |                   |                   |
    v                   v                   v
+-----------+   +--------------+   +---------------+
| LOCAL     |   | REMOTE       |   | INGESTION     |
| CLI       |   | CLI          |   | CLI           |
|           |   |              |   |               |
| REPL      |   | REPL         |   | Batch mode    |
| query +   |   | query only   |   | ingest only   |
| ingest    |   |              |   |               |
+-----------+   +--------------+   +---------------+
    |                   |                   |
    +-------------------+-------------------+
                        |
    +-------------------------------------------+
    |  SHARED CLI INFRASTRUCTURE                |
    |                                           |
    |  Command Registry   Input Handling        |
    |  (shared w/ web)    (menus, completion)   |
    |                                           |
    |  Command Dispatch   Output Formatting     |
    |  (slash routing)    (ANSI, badges)        |
    +-------------------------------------------+
           |                       |
           v                       v
    +-----------+          +---------------+
    | RAGChain  |          | API Server    |
    | (direct)  |          | (HTTP/SSE)    |
    +-----------+          +---------------+
```

**Entry point summary:**

| Client | Backend | Interactive | Model loading | Primary use |
|--------|---------|-------------|---------------|-------------|
| Local CLI | Direct pipeline | Yes (REPL, query + ingest) | Yes (in-process) | Development, local querying, ingestion |
| Remote CLI | HTTP to server | Yes (REPL, query only) | No | Production querying |
| Ingestion CLI | Direct pipeline | No (batch) | Partial (embeddings) | CI/CD, batch ingestion |

---

## 5) Requirement Framework

- **ID convention:** `REQ-xxx` numeric prefix
- **Priority keywords:** `MUST` (non-conformant without it), `SHOULD` (recommended), `MAY` (optional)
- **Per-requirement structure:** Description + Rationale + Acceptance Criteria
- **Traceability:** Each requirement traced to system-level acceptance criteria (SAC-N)

**ID ranges by component:**

| Range | Component |
|-------|-----------|
| REQ-1xx | Shared CLI Infrastructure |
| REQ-2xx | Local CLI |
| REQ-3xx | Remote CLI |
| REQ-4xx | Ingestion CLI |
| REQ-5xx | CLI/UI Parity |
| REQ-9xx | Non-Functional Requirements |

---

## 6) Functional Requirement Domains

**Shared CLI Infrastructure (REQ-100 to REQ-199)**
Covers the common foundation all three entry points depend on: the unified command registry, slash command dispatch, preset management, tab completion, ANSI output formatting, and input validation. These requirements enforce the constraint that no entry point defines commands or output formatting independently.

**Local CLI (REQ-200 to REQ-299)**
Covers the interactive REPL with dual-mode operation (query and ingest), direct model loading and pipeline access, the styled landing page, live-filtering command menu, streaming query output, ingestion progress display, session-scoped source and heading filters, and result metadata display (scores, sources, timing).

**Remote CLI (REQ-300 to REQ-399)**
Covers the HTTP-based REPL with near-instant startup, API key and bearer token authentication, server-sent event streaming, multi-turn conversation management, and transparent handling of commands that cannot execute in remote mode.

**Ingestion CLI (REQ-400 to REQ-499)**
Covers standalone batch pipeline execution, CLI flag and environment variable configuration with a defined precedence order, and structured progress reporting with a per-document failure log and a summary exit code.

**CLI/UI Parity (REQ-500 to REQ-599)**
Covers the bidirectional feature parity requirement between all CLI entry points and the web console, the mandate that shared contracts live in shared modules, and automated parity test coverage.

---

## 7) Non-Functional and Security Themes

**Performance:**
- Local CLI initialization time (excluding model loading) is bounded by a SHOULD-level target
- Remote CLI startup time is bounded by a MUST-level target (near-instant, no model loading)

**Resilience:**
- The remote client must handle server unavailability without crashing the REPL
- Transient failures trigger bounded retry with backoff before reporting failure
- Streaming interruptions are handled gracefully

**Security:**
- Credentials passed via flags must not be echoed to the terminal or stored in shell history
- Authentication failures produce clear, actionable error messages
- No hardcoded credentials or configuration values

**Configurability:**
- All configuration (server URLs, model paths, parameters, themes, preset paths) must be externalized via environment variables, config files, or CLI flags
- Precedence order is defined: CLI flag > environment variable > config file > default

**Degradation:**
- ANSI output degrades to plain text when the terminal does not support color or output is piped
- Tab completion degrades to a no-op if the readline subsystem is unavailable

---

## 8) Design Principles

| Principle | Summary |
|-----------|---------|
| **CLI/UI Parity** | CLI and web console are two clients of one product; every user-facing feature must be available on both surfaces |
| **Backend-Driven Commands** | Command definitions live once in shared infrastructure; surface adapters consume without duplicating |
| **Progressive Information** | Default output is concise; detailed metadata (scores, timings, debug traces) is available on demand |
| **Consistent Formatting** | All three entry points share a single output formatting module; visual language is uniform across surfaces |

---

## 9) Key Decisions

- **Single command registry shared with the web console** — enforces parity at the definition layer, not just the behavior layer; drift is structurally prevented
- **Three separate entry points rather than one unified CLI** — separates the concerns of local development (models loaded in-process), production access (thin client, server-delegated), and automation (batch, no TTY)
- **Shared preset format between CLI and console** — presets created on one surface must be loadable on the other, requiring a common serialization contract
- **Explicit documentation of interface-specific features** — rather than silently omitting unavailable commands in remote mode, the spec requires a clear message identifying the limitation
- **Defined precedence for configuration** — CLI flag > environment variable > config file > default; this order is normative and applies to all three entry points

---

## 10) Acceptance and Evaluation

The spec defines **12 system-level acceptance criteria (SAC-1 through SAC-12)** covering:

- End-to-end query execution with streaming output (local and remote)
- Command catalog availability across both CLI entry points and parity with console
- Preset round-tripping between CLI and web console
- Ingestion batch execution with correct exit codes and summary output
- Remote CLI resilience to server unavailability
- Tab completion sourced from the shared catalog
- Session-persistent source and heading filters
- Authentication with API key and bearer token
- Startup time benchmarks for both local and remote clients
- Full configuration externalizability

Each acceptance criterion specifies the verification method (manual test or automated test) and maps to one or more requirements. A traceability matrix in the companion spec links every requirement to its acceptance criterion.

---

## 11) External Dependencies

**Required:**
- A running API server is required for Remote CLI operation; all queries fail if the server is unreachable
- The shared command registry module must exist and be importable by all three entry points

**Assumed present:**
- ANSI-capable terminal for full output formatting (degrades gracefully otherwise)
- Readline or equivalent for tab completion (degrades to no-op otherwise)

**Downstream contracts:**
- Retrieval pipeline (query execution) — defined in `RETRIEVAL_QUERY_SPEC.md` / `RETRIEVAL_GENERATION_SPEC.md`
- Ingestion pipeline (batch document processing) — defined in `INGESTION_PIPELINE_SPEC.md`
- Server API (HTTP endpoints consumed by Remote CLI) — defined in `SERVER_API_SPEC.md`
- Platform services (auth, quotas, observability) — defined in `PLATFORM_SERVICES_SPEC.md`
- Web console (parity partner surface) — defined in `WEB_CONSOLE_SPEC.md`

---

## 12) Companion Documents

This summary is a **Layer 2 — Spec Summary** in the documentation hierarchy:

```
Layer 1: Platform Spec          (manual — cross-system overview)
Layer 2: Spec Summary           <- THIS DOCUMENT
Layer 3: Authoritative Spec     <- CLI_SPEC.md (companion)
Layer 4: Implementation Guide   <- write-impl (downstream)
```

This document captures the intent, scope, structure, and key decisions of `CLI_SPEC.md`. It is readable without opening the spec but does not replace it — requirement-level detail, acceptance criteria values, and the traceability matrix live in the companion spec.

---

## 13) Sync Status

| Field | Value |
|-------|-------|
| Aligned to spec version | 1.0 |
| Spec date | 2026-03-13 |
| Summary written | 2026-04-10 |
| Status | In sync |
