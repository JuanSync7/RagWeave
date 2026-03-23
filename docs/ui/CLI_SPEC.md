# CLI Interface Specification

**AION Knowledge Management Platform**
Version: 1.0 | Status: Initial Specification | Domain: CLI Interface

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-13 | AI Assistant | Initial specification covering all CLI entry points and shared infrastructure |

> **Document intent:** This is a normative requirements/specification document for the CLI interface layer.
> The RAG system exposes three CLI entry points — a local interactive CLI, a remote HTTP-based CLI client, and a standalone ingestion CLI — all sharing a common infrastructure layer.
> For server API behavior, see `SERVER_API_SPEC.md`. For retrieval pipeline behavior, see `RETRIEVAL_SPEC.md`.
> For platform-level auth/quotas/observability, see `BACKEND_PLATFORM_SPEC.md`. For web console behavior, see `WEB_CONSOLE_SPEC.md`.

---

## 1. Scope & Definitions

### 1.1 Problem Statement

The RAG system has approximately 1,300 lines of CLI code spread across three entry points and four shared infrastructure modules. Despite a CLI/UI parity principle established in the web console specification, no formal CLI specification exists to enforce that parity or to define the behavioral contracts of the CLI layer. Without this specification, drift between the CLI and web console surfaces is inevitable, and new contributors have no authoritative reference for CLI behavior.

### 1.2 Scope

This specification defines requirements for the **CLI interface layer** of the RAG system. The boundary is:

- **Entry point:** User invokes one of the three CLI programs (`cli.py`, `server/cli_client.py`, or `ingest.py`).
- **Exit point:** User receives formatted terminal output (query results, ingestion status, error messages, or interactive prompts).

Everything between these points is in scope, including REPL lifecycle, command dispatch, input handling, output formatting, authentication (remote mode), and streaming display.

### 1.3 Terminology

| Term | Definition |
|------|-----------|
| **Local CLI** | The unified interactive CLI (`cli.py`) that loads models locally and accesses RAGChain directly without a server |
| **Remote CLI** | The HTTP-based CLI client (`server/cli_client.py`) that connects to a running FastAPI server for all operations |
| **Ingestion CLI** | The standalone ingestion CLI (`ingest.py`) for batch pipeline execution without interactive REPL |
| **REPL** | Read-Eval-Print Loop — the interactive command loop used by both Local CLI and Remote CLI |
| **Slash Command** | A user command prefixed with `/` (e.g., `/help`, `/sources`, `/preset`) dispatched through the shared command runtime |
| **Preset** | A named, saved configuration of query parameters (model, source filters, heading filters, retrieval settings) that can be loaded and applied |
| **Command Catalog** | The unified registry of available slash commands, shared between CLI and web console surfaces |
| **Mode** | One of the two REPL operating modes: **query** (send questions to the retrieval pipeline) or **ingest** (run document ingestion) |
| **Live-Filtering Menu** | An interactive command picker triggered by typing `/` that filters available commands as the user types |
| **SSE** | Server-Sent Events — the streaming protocol used by the Remote CLI to receive generation tokens from the API server |

### 1.4 Requirement Priority Levels

This document uses RFC 2119 language:

- **MUST** — Absolute requirement. The system is non-conformant without it.
- **SHOULD** — Recommended. May be omitted only with documented justification.
- **MAY** — Optional. Included at the implementor's discretion.

### 1.5 Requirement Format

Each requirement follows this structure:

> **REQ-xxx** | Priority: MUST/SHOULD/MAY
> **Description:** What the system shall do.
> **Rationale:** Why this requirement exists.
> **Acceptance Criteria:** How to verify conformance.

Requirements are grouped by section with the following ID ranges:

| Section | ID Range | Component |
|---------|----------|-----------|
| 3 | REQ-1xx | Shared CLI Infrastructure |
| 4 | REQ-2xx | Local CLI (cli.py) |
| 5 | REQ-3xx | Remote CLI (cli_client.py) |
| 6 | REQ-4xx | Ingestion CLI (ingest.py) |
| 7 | REQ-5xx | CLI/UI Parity |
| 8 | REQ-9xx | Non-Functional Requirements |

### 1.6 Assumptions & Constraints

| ID | Assumption / Constraint | Impact if Violated |
|----|------------------------|--------------------|
| A-1 | The shared command catalog (`src/platform/command_catalog.py`) is the single source of truth for available commands across CLI and web console | Command drift between surfaces; parity violations become undetectable |
| A-2 | The Local CLI loads embedding, reranking, and generation models into the same process | Startup latency increases; memory footprint is bounded by model sizes |
| A-3 | The Remote CLI assumes a running FastAPI server is reachable over HTTP | All operations fail if the server is unavailable; graceful degradation is required |
| A-4 | Terminal environment supports ANSI escape codes for colored output | Output degrades to unformatted text in terminals without ANSI support |
| A-5 | Python readline or equivalent is available for tab completion | Tab completion silently degrades to no-op if readline is unavailable |

### 1.7 Design Principles

| Principle | Description |
|-----------|-------------|
| **CLI/UI Parity** | Every user-facing feature available in the CLI MUST be available in the web console and vice versa; the two surfaces are clients of one product |
| **Backend-Driven Commands** | The command catalog is defined once in shared infrastructure; CLI and console adapters consume it without duplicating definitions |
| **Progressive Information** | Default output is concise; detailed output (debug traces, raw scores, full metadata) is available on demand via flags or commands |
| **Consistent Formatting** | All CLI output follows the same ANSI color scheme, badge system, and layout conventions regardless of entry point |

### 1.8 Out of Scope

- Retrieval pipeline internals (see `RETRIEVAL_SPEC.md`)
- Server API endpoint contracts (see `SERVER_API_SPEC.md`)
- Web console UI behavior (see `WEB_CONSOLE_SPEC.md`)
- Model loading and inference behavior
- Ingestion pipeline internals (see `RAG_embedding_pipeline_spec.md`)

---

## 2. System Overview

### 2.1 Architecture Diagram

```
User Terminal
    │
    ├──────────────────────┬──────────────────────┐
    │                      │                      │
    ▼                      ▼                      ▼
┌──────────────┐  ┌────────────────┐  ┌───────────────┐
│ [1] LOCAL    │  │ [2] REMOTE     │  │ [3] INGESTION │
│     CLI      │  │     CLI        │  │     CLI       │
│  (cli.py)    │  │ (cli_client.py)│  │  (ingest.py)  │
│              │  │                │  │               │
│  REPL Mode   │  │  REPL Mode    │  │  Batch Mode   │
│  query/ingest│  │  query only   │  │  ingest only  │
└──────┬───────┘  └───────┬────────┘  └───────┬───────┘
       │                  │                    │
       ▼                  │                    │
┌──────────────────────────────────────────────────────┐
│ SHARED CLI INFRASTRUCTURE                            │
│                                                      │
│  ┌──────────────────┐  ┌──────────────────────────┐  │
│  │ command_catalog   │  │ cli_interactive          │  │
│  │ (command registry │  │ (input handling, menus,  │  │
│  │  shared w/ web)   │  │  tab completion)         │  │
│  └──────────────────┘  └──────────────────────────┘  │
│                                                      │
│  ┌──────────────────┐  ┌──────────────────────────┐  │
│  │ command_runtime   │  │ cli_log_formatting       │  │
│  │ (slash command    │  │ (ANSI colors, badges,    │  │
│  │  dispatch)        │  │  styled output)          │  │
│  └──────────────────┘  └──────────────────────────┘  │
└──────────────────────────────────────────────────────┘
       │                  │
       ▼                  ▼
┌──────────────┐  ┌────────────────┐
│ RAGChain     │  │ FastAPI Server │
│ (direct)     │  │ (HTTP/SSE)     │
└──────────────┘  └────────────────┘
```

### 2.2 Entry Point Summary

| Entry Point | File | Backend | Interactive | Model Loading | Primary Use Case |
|-------------|------|---------|-------------|---------------|-----------------|
| Local CLI | `cli.py` | Direct RAGChain | Yes (REPL) | Yes (in-process) | Development, local querying, ingestion |
| Remote CLI | `server/cli_client.py` | HTTP to FastAPI | Yes (REPL) | No | Production querying against running server |
| Ingestion CLI | `ingest.py` | Direct pipeline | No (batch) | Partial (embeddings) | CI/CD ingestion, batch document processing |

---

## 3. Shared CLI Infrastructure (REQ-1xx)

### REQ-101 — Shared Command Catalog

> **REQ-101** | Priority: MUST
> **Description:** All CLI entry points MUST consume the command catalog from `src/platform/command_catalog.py`. The command catalog is the single source of truth for available slash commands, their arguments, descriptions, and groupings. The same catalog instance MUST be consumed by the web console.
> **Rationale:** The CLI/UI parity principle requires a single command registry. Duplicating command definitions across surfaces leads to drift and inconsistent behavior.
> **Acceptance Criteria:**
> - Both Local CLI and Remote CLI load commands exclusively from the shared catalog.
> - Adding a command to the catalog makes it available in both CLIs and the web console without additional per-surface code (beyond adapter rendering).
> - No CLI entry point defines commands outside the shared catalog (except interface-specific debug commands, which MUST be explicitly documented as such).

### REQ-102 — Slash Command Dispatch

> **REQ-102** | Priority: MUST
> **Description:** Slash commands entered by the user MUST be dispatched through the shared command runtime (`src/platform/command_runtime.py`). The runtime MUST resolve the command name against the catalog, validate arguments, and invoke the registered handler.
> **Rationale:** Centralizing dispatch ensures consistent argument validation, error handling, and handler invocation across all CLI surfaces.
> **Acceptance Criteria:**
> - Input beginning with `/` is routed to the command runtime.
> - Unknown commands produce a clear error message listing similar available commands.
> - Argument validation errors are displayed before handler invocation.

### REQ-103 — Preset Support

> **REQ-103** | Priority: MUST
> **Description:** The CLI MUST support loading, saving, and applying presets. A preset is a named collection of query parameters (model selection, source filters, heading filters, retrieval settings) that can be persisted and recalled across sessions.
> **Rationale:** Presets reduce repetitive configuration for users who regularly query with specific parameter combinations.
> **Acceptance Criteria:**
> - `/preset save <name>` persists the current parameter state.
> - `/preset load <name>` restores a previously saved parameter state.
> - `/preset list` displays all available presets.
> - Presets persist across REPL sessions (stored on disk).
> - Preset format is the same whether created from CLI or web console.

### REQ-104 — Tab Completion

> **REQ-104** | Priority: SHOULD
> **Description:** The REPL SHOULD provide tab completion for slash commands and their arguments. Completion candidates MUST be derived from the shared command catalog.
> **Rationale:** Tab completion improves discoverability and reduces input errors in the terminal.
> **Acceptance Criteria:**
> - Pressing Tab after `/` lists all available commands.
> - Pressing Tab after a partial command name completes it or shows matching candidates.
> - Pressing Tab after a command name offers argument completions where applicable (e.g., preset names, source names).
> - Tab completion degrades gracefully (no-op) if readline is unavailable.

### REQ-105 — Consistent ANSI-Colored Output

> **REQ-105** | Priority: MUST
> **Description:** All CLI output MUST use the shared formatting module (`src/platform/cli_log_formatting.py`) for ANSI colors, badges, and styled text. Output formatting MUST be consistent across all three CLI entry points.
> **Rationale:** Consistent visual language reduces cognitive load and makes output scannable.
> **Acceptance Criteria:**
> - Error messages use a consistent color and badge (e.g., red with `[ERROR]` badge).
> - Success messages use a consistent color and badge (e.g., green with `[OK]` badge).
> - Informational output uses a consistent color (e.g., cyan or default).
> - Section headers, separators, and emphasis are rendered uniformly.
> - Output degrades to plain text (no ANSI codes) when the terminal does not support ANSI or when output is piped to a file.

### REQ-106 — Input Validation and Error Display

> **REQ-106** | Priority: MUST
> **Description:** All user input MUST be validated before processing. Validation errors MUST be displayed inline in the REPL with actionable guidance. The system MUST NOT crash or produce a stack trace for invalid user input.
> **Rationale:** A production CLI must handle all foreseeable input gracefully without exposing internals.
> **Acceptance Criteria:**
> - Empty input is silently ignored (new prompt displayed).
> - Malformed slash commands display an error with usage hint.
> - Invalid argument values display the expected format or valid options.
> - No user input causes an unhandled exception to reach the terminal.

---

## 4. Local CLI — cli.py (REQ-2xx)

### REQ-201 — Interactive REPL with Mode Switching

> **REQ-201** | Priority: MUST
> **Description:** The Local CLI MUST provide an interactive REPL that supports two operating modes: **query** mode (default) and **ingest** mode. The user MUST be able to switch between modes using a slash command (e.g., `/mode ingest`, `/mode query`).
> **Rationale:** A single entry point with mode switching avoids requiring users to restart the CLI to switch between querying and ingesting.
> **Acceptance Criteria:**
> - The REPL starts in query mode by default.
> - `/mode ingest` switches to ingest mode; the prompt changes to reflect the active mode.
> - `/mode query` switches back to query mode.
> - Mode-specific commands are only available in the relevant mode.
> - The current mode is visible in the prompt at all times.

### REQ-202 — Direct Model Loading and RAGChain Access

> **REQ-202** | Priority: MUST
> **Description:** The Local CLI MUST load embedding, reranking, and generation models directly into the process and construct a RAGChain instance for query execution. Model loading MUST occur at startup (or on first use) and models MUST remain loaded for the REPL session lifetime.
> **Rationale:** Direct model access eliminates the need for a running server, enabling offline development and local experimentation.
> **Acceptance Criteria:**
> - Models are loaded once and reused across queries within the same session.
> - The user is informed of model loading progress (model names, load times).
> - Model loading failures produce clear error messages identifying which model failed and why.

### REQ-203 — Styled Landing Page

> **REQ-203** | Priority: SHOULD
> **Description:** On startup, the Local CLI SHOULD display a styled landing page showing system information: loaded models, active configuration, available document sources, and key commands.
> **Rationale:** A landing page orients the user and confirms that the system initialized correctly.
> **Acceptance Criteria:**
> - The landing page displays the active embedding model, generation model, and reranker.
> - The landing page displays the number of indexed documents or sources available.
> - The landing page lists key slash commands for discoverability.
> - The landing page is rendered using the shared formatting module (REQ-105).

### REQ-204 — Live-Filtering Command Menu

> **REQ-204** | Priority: SHOULD
> **Description:** When the user types `/` alone and presses Enter (or pauses), the CLI SHOULD display an interactive, live-filtering menu of available commands. As the user continues typing after `/`, the menu SHOULD filter to matching commands in real time.
> **Rationale:** Live filtering improves command discoverability beyond static `/help` output, especially for users unfamiliar with available commands.
> **Acceptance Criteria:**
> - Typing `/` followed by Enter displays all available commands grouped by category.
> - Typing `/so` filters to commands starting with "so" (e.g., `/sources`).
> - The menu displays command name, arguments summary, and brief description.
> - Selecting a command from the menu executes it or pre-fills the input line.

### REQ-205 — Query Execution with Streaming Output

> **REQ-205** | Priority: MUST
> **Description:** In query mode, the Local CLI MUST accept natural-language queries and execute them against the RAGChain. Generated answers MUST be streamed token-by-token to the terminal as they are produced.
> **Rationale:** Streaming output provides immediate feedback and reduces perceived latency for long-running generation.
> **Acceptance Criteria:**
> - Tokens appear in the terminal as they are generated, not buffered until completion.
> - The query prompt is clearly separated from the answer output.
> - Generation can be interrupted by the user (e.g., Ctrl+C) without crashing the REPL.
> - After generation completes, the REPL returns to the prompt.

### REQ-206 — Ingestion Execution with Progress Display

> **REQ-206** | Priority: MUST
> **Description:** In ingest mode, the Local CLI MUST accept ingestion commands and display progress as documents are processed. Progress MUST include document count, current stage, and elapsed time.
> **Rationale:** Ingestion can be long-running; progress display prevents the user from assuming the process is hung.
> **Acceptance Criteria:**
> - A progress indicator shows the number of documents processed out of total.
> - The current pipeline stage (loading, chunking, embedding, storing) is displayed.
> - Elapsed time is shown and updated during processing.
> - Errors for individual documents are reported without halting the entire pipeline.

### REQ-207 — Source and Heading Filter Support

> **REQ-207** | Priority: MUST
> **Description:** The Local CLI MUST support filtering queries by source and by heading. Filters MUST be settable via slash commands (e.g., `/sources`, `/headings`) and persist across queries within the session until explicitly changed or cleared.
> **Rationale:** Filtering narrows retrieval scope, improving relevance when the user knows which documents are pertinent.
> **Acceptance Criteria:**
> - `/sources <filter>` sets a source filter that constrains retrieval to matching sources.
> - `/headings <filter>` sets a heading filter that constrains retrieval to matching headings.
> - Active filters are displayed in the prompt or via a status command.
> - Filters persist across queries until cleared with `/sources clear` or `/headings clear`.

### REQ-208 — Result Display with Scores, Sources, and Timings

> **REQ-208** | Priority: MUST
> **Description:** After query execution, the Local CLI MUST display the generated answer followed by structured metadata: relevance scores of retrieved chunks, source document references, and timing breakdown (retrieval time, reranking time, generation time).
> **Rationale:** Metadata enables users to assess answer quality and debug retrieval behavior without switching to a separate tool.
> **Acceptance Criteria:**
> - Retrieved chunks are listed with their relevance scores, sorted by score descending.
> - Each chunk shows its source document name and section/heading.
> - Timing breakdown shows at minimum: total time, retrieval time, and generation time.
> - Metadata display can be toggled off for cleaner output (e.g., `/verbose off`).

---

## 5. Remote CLI — cli_client.py (REQ-3xx)

### REQ-301 — HTTP-Based REPL

> **REQ-301** | Priority: MUST
> **Description:** The Remote CLI MUST provide the same REPL experience as the Local CLI (REQ-201) but execute all operations via HTTP requests to a running FastAPI server. The REPL MUST support the same slash commands available from the shared command catalog.
> **Rationale:** The Remote CLI enables querying against a production server without loading models locally, while maintaining the same user experience.
> **Acceptance Criteria:**
> - The REPL prompt, command dispatch, and output formatting are visually identical to the Local CLI.
> - All commands from the shared catalog (REQ-101) are available.
> - Queries are sent as HTTP requests and responses are displayed with the same formatting as the Local CLI.

### REQ-302 — Instant Startup

> **REQ-302** | Priority: MUST
> **Description:** The Remote CLI MUST start and display the REPL prompt without loading any ML models. Startup time MUST be under 2 seconds (see REQ-902).
> **Rationale:** The Remote CLI is a thin client; users expect near-instant readiness since the server handles all heavy computation.
> **Acceptance Criteria:**
> - No model files are loaded or initialized during startup.
> - The REPL prompt appears within 2 seconds of invocation.
> - Connection to the server is verified at startup with a health check; failure produces a warning but does not block the REPL.

### REQ-303 — Authentication Support

> **REQ-303** | Priority: MUST
> **Description:** The Remote CLI MUST support authentication via API key and bearer token. Credentials MUST be configurable via CLI flags, environment variables, or a configuration file. The CLI MUST NOT store credentials in shell history.
> **Rationale:** Production API servers require authentication; the CLI must support the same auth mechanisms as other API clients.
> **Acceptance Criteria:**
> - `--api-key <key>` flag sets API key authentication for the session.
> - `--token <token>` flag sets bearer token authentication for the session.
> - Environment variables (`RAG_API_KEY`, `RAG_BEARER_TOKEN`) are accepted as fallbacks.
> - Credentials passed via flags are not logged or echoed to the terminal.
> - Authentication failures produce a clear error message identifying the auth method attempted.

### REQ-304 — SSE Streaming Support

> **REQ-304** | Priority: MUST
> **Description:** The Remote CLI MUST support Server-Sent Events (SSE) for receiving streamed generation tokens from the API server. Tokens MUST be rendered to the terminal in real time as they arrive.
> **Rationale:** SSE streaming provides the same progressive output experience as the Local CLI's direct streaming (REQ-205).
> **Acceptance Criteria:**
> - The CLI establishes an SSE connection for generation requests.
> - Tokens are displayed as they arrive without buffering.
> - SSE connection errors (timeout, disconnect) are handled gracefully with a message indicating the failure point.
> - The user can interrupt streaming with Ctrl+C.

### REQ-305 — Conversation Management

> **REQ-305** | Priority: SHOULD
> **Description:** The Remote CLI SHOULD support multi-turn conversations with memory. The CLI SHOULD maintain a conversation ID and send it with each query to enable the server to maintain context across turns.
> **Rationale:** Multi-turn conversations enable follow-up questions that reference prior context, matching the web console's conversational capability.
> **Acceptance Criteria:**
> - A conversation ID is generated at session start and sent with each query.
> - `/new` or `/clear` starts a new conversation (new ID).
> - Follow-up queries can reference prior answers (e.g., "what about the second point?").
> - Conversation history is displayed via `/history` command.

### REQ-306 — Full Command Catalog Availability

> **REQ-306** | Priority: MUST
> **Description:** The Remote CLI MUST make all commands from the shared command catalog (REQ-101) available to the user. Commands that require local resources (e.g., direct model access) MUST either delegate to the server or display a clear message that the command is not available in remote mode.
> **Rationale:** Users should not need to remember which commands work in which CLI mode; the system should handle the distinction transparently.
> **Acceptance Criteria:**
> - All catalog commands appear in `/help` output.
> - Commands that cannot execute in remote mode display a message: "This command is not available in remote mode. Use the local CLI for this operation."
> - No command silently fails or produces misleading output due to the remote context.

---

## 6. Ingestion CLI — ingest.py (REQ-4xx)

### REQ-401 — Standalone Ingestion Pipeline Execution

> **REQ-401** | Priority: MUST
> **Description:** The Ingestion CLI MUST execute the document ingestion pipeline as a standalone batch process without requiring an interactive REPL or a running server. It MUST accept input paths (files or directories) and process all documents through the full pipeline (loading, chunking, embedding, storing).
> **Rationale:** Batch ingestion is required for CI/CD pipelines, scheduled jobs, and initial corpus loading where interactive operation is impractical.
> **Acceptance Criteria:**
> - `python ingest.py --input <path>` processes all documents at the given path.
> - The process exits with code 0 on success and non-zero on failure.
> - The process can run headlessly (no TTY required) for CI/CD environments.

### REQ-402 — Configuration via CLI Flags and Environment Variables

> **REQ-402** | Priority: MUST
> **Description:** The Ingestion CLI MUST accept configuration through CLI flags and environment variables. CLI flags MUST take precedence over environment variables, which MUST take precedence over configuration file defaults.
> **Rationale:** External configurability is required for deployment automation and environment-specific overrides.
> **Acceptance Criteria:**
> - Key parameters are configurable: input path, chunk size, embedding model, vector store endpoint, batch size.
> - `--help` displays all available flags with descriptions and defaults.
> - Environment variable names follow the pattern `RAG_INGEST_<PARAM>` (e.g., `RAG_INGEST_CHUNK_SIZE`).
> - Precedence order: CLI flag > environment variable > config file > default.

### REQ-403 — Progress Reporting and Error Summary

> **REQ-403** | Priority: MUST
> **Description:** The Ingestion CLI MUST report progress during execution and display a summary upon completion. The summary MUST include: total documents processed, documents succeeded, documents failed, total chunks created, and elapsed time. Individual document failures MUST be logged with the document path and error reason.
> **Rationale:** Operators need to verify ingestion completeness and identify failures for remediation.
> **Acceptance Criteria:**
> - Progress output shows documents processed as a count (e.g., `[42/100]`).
> - The final summary is printed to stdout on completion.
> - Failed documents are listed with their file paths and failure reasons.
> - The exit code reflects whether any failures occurred (0 = all succeeded, 1 = partial failure, 2 = total failure).

---

## 7. CLI/UI Parity (REQ-5xx)

### REQ-501 — Feature Parity Requirement

> **REQ-501** | Priority: MUST
> **Description:** Every user-facing feature available in any CLI entry point MUST have a corresponding capability in the web console, and every user-facing feature in the web console MUST have a corresponding capability in at least one CLI entry point. Features that are intentionally interface-specific (e.g., mouse-based interactions in the console, terminal-specific key bindings in the CLI) MUST be explicitly documented as such in this specification.
> **Rationale:** The CLI/UI parity principle from `CLAUDE.md` treats CLI and web console as two clients of one product surface. Undocumented feature gaps erode user trust and create maintenance burden.
> **Acceptance Criteria:**
> - A parity matrix is maintained listing every user-facing feature and its availability in CLI and web console.
> - New features added to either surface include the corresponding implementation in the other surface within the same change set, or are explicitly marked as interface-specific with justification.
> - Parity violations are tracked as defects.

### REQ-502 — Shared Schemas as Single Source of Truth

> **REQ-502** | Priority: MUST
> **Description:** All interaction contracts shared between CLI and web console (command definitions, request/response schemas, configuration models) MUST be defined in shared Python modules consumed by both surfaces. Neither surface MAY define its own version of a shared contract.
> **Rationale:** Duplicate contract definitions inevitably diverge. A single source of truth eliminates an entire class of parity bugs.
> **Acceptance Criteria:**
> - Command definitions live exclusively in `src/platform/command_catalog.py`.
> - Request/response schemas used by both surfaces are defined in shared schema modules.
> - Static analysis or import tracing can verify that no CLI module or console module defines a redundant schema.

### REQ-503 — Parity Test Coverage

> **REQ-503** | Priority: SHOULD
> **Description:** The test suite SHOULD include parity tests that verify feature equivalence between CLI and web console. At minimum, parity tests SHOULD verify that every command in the shared catalog is exercisable from both surfaces.
> **Rationale:** Automated parity tests catch drift earlier than manual review.
> **Acceptance Criteria:**
> - A test enumerates all commands in the shared catalog and asserts that both CLI and console adapters register handlers for each.
> - Parity tests run in CI and block merges on failure.
> - New commands added to the catalog automatically cause a parity test failure if a handler is missing on either surface.

---

## 8. Non-Functional Requirements (REQ-9xx)

### REQ-901 — Local CLI Startup Time

> **REQ-901** | Priority: SHOULD
> **Description:** The Local CLI SHOULD display the REPL prompt within 10 seconds of invocation, excluding model loading time. Model loading time is reported separately and is not subject to this SLO.
> **Rationale:** Fast startup ensures developer productivity; model loading is inherently slow but decoupled from CLI initialization.
> **Acceptance Criteria:**
> - CLI initialization (import, configuration loading, prompt rendering) completes within 10 seconds.
> - Model loading time is measured and displayed separately.
> - If model loading exceeds 60 seconds, a progress indicator is shown.

### REQ-902 — Remote CLI Startup Time

> **REQ-902** | Priority: MUST
> **Description:** The Remote CLI MUST display the REPL prompt within 2 seconds of invocation.
> **Rationale:** The Remote CLI loads no models and should start almost instantly.
> **Acceptance Criteria:**
> - Time from invocation to prompt display is under 2 seconds on a system meeting minimum requirements.
> - Startup time is measurable via `time python server/cli_client.py --health-only` or equivalent.

### REQ-903 — Graceful API Unavailability Handling

> **REQ-903** | Priority: MUST
> **Description:** The Remote CLI MUST handle API server unavailability gracefully. When the server is unreachable, the CLI MUST display a clear error message and allow the user to retry or reconfigure the server URL without restarting the CLI.
> **Rationale:** Network interruptions and server restarts are normal in production; the CLI must not crash or require a restart when the server is temporarily unavailable.
> **Acceptance Criteria:**
> - Connection failures display: "Cannot reach server at <url>. Check the server status and try again."
> - The user can change the server URL via `/server <url>` without restarting.
> - Transient failures (timeout, 503) prompt retry with exponential backoff up to 3 attempts before reporting failure.
> - The REPL remains functional after a failed request; the user can issue new commands.

### REQ-904 — Configuration Externalization

> **REQ-904** | Priority: MUST
> **Description:** All CLI configuration (server URLs, model paths, default parameters, color themes, preset storage paths) MUST be externalizable via environment variables, configuration files, or CLI flags. No configuration value MAY be hardcoded as the only option.
> **Rationale:** Hardcoded configuration prevents deployment flexibility and forces code changes for environment-specific settings.
> **Acceptance Criteria:**
> - Every configurable parameter has a documented environment variable, config file key, and/or CLI flag.
> - Default values are documented and reasonable for local development.
> - Configuration precedence is: CLI flag > environment variable > config file > default.

---

## 9. System-Level Acceptance Criteria

| ID | Criterion | Verification Method | Requirement(s) |
|----|-----------|--------------------|--------------------|
| SAC-1 | User can start Local CLI and execute a query with streamed output | Manual test: start `cli.py`, enter query, observe streaming tokens | REQ-201, REQ-202, REQ-205 |
| SAC-2 | User can start Remote CLI and execute a query against a running server | Manual test: start server, start `cli_client.py`, enter query | REQ-301, REQ-302, REQ-304 |
| SAC-3 | All shared catalog commands are available in both Local and Remote CLIs | Automated test: enumerate catalog, assert handler registration in both | REQ-101, REQ-306, REQ-503 |
| SAC-4 | Presets created in CLI can be loaded in web console and vice versa | Manual test: save preset in CLI, load in console; reverse | REQ-103, REQ-502 |
| SAC-5 | Ingestion CLI processes a document directory and reports summary | Automated test: run `ingest.py --input test_docs/`, verify exit code and summary | REQ-401, REQ-403 |
| SAC-6 | Remote CLI handles server unavailability without crashing | Manual test: stop server, attempt query in Remote CLI, verify error message and REPL recovery | REQ-903 |
| SAC-7 | Tab completion offers commands from the shared catalog | Manual test: type `/` + Tab in REPL, verify command suggestions | REQ-104 |
| SAC-8 | Source and heading filters persist across queries | Manual test: set filter, run two queries, verify both are filtered | REQ-207 |
| SAC-9 | Authentication works with API key and bearer token | Automated test: start server with auth, connect Remote CLI with `--api-key`, verify query succeeds | REQ-303 |
| SAC-10 | Local CLI startup is under 10 seconds (excluding model load) | Automated benchmark: measure time to first prompt | REQ-901 |
| SAC-11 | Remote CLI startup is under 2 seconds | Automated benchmark: measure time to first prompt | REQ-902 |
| SAC-12 | All configuration is externalizable | Review: verify every config parameter has env var / flag / file support | REQ-904 |

---

## 10. Requirements Traceability Matrix

| Requirement | Section | Priority | Component | Depends On | Verified By |
|-------------|---------|----------|-----------|------------|-------------|
| REQ-101 | 3 | MUST | Shared Infrastructure | — | SAC-3 |
| REQ-102 | 3 | MUST | Shared Infrastructure | REQ-101 | SAC-3 |
| REQ-103 | 3 | MUST | Shared Infrastructure | REQ-101 | SAC-4 |
| REQ-104 | 3 | SHOULD | Shared Infrastructure | REQ-101 | SAC-7 |
| REQ-105 | 3 | MUST | Shared Infrastructure | — | SAC-1, SAC-2 |
| REQ-106 | 3 | MUST | Shared Infrastructure | — | SAC-1, SAC-2 |
| REQ-201 | 4 | MUST | Local CLI | REQ-101, REQ-102 | SAC-1 |
| REQ-202 | 4 | MUST | Local CLI | — | SAC-1 |
| REQ-203 | 4 | SHOULD | Local CLI | REQ-105 | SAC-1 |
| REQ-204 | 4 | SHOULD | Local CLI | REQ-101 | SAC-7 |
| REQ-205 | 4 | MUST | Local CLI | REQ-202 | SAC-1 |
| REQ-206 | 4 | MUST | Local CLI | REQ-105 | SAC-5 |
| REQ-207 | 4 | MUST | Local CLI | — | SAC-8 |
| REQ-208 | 4 | MUST | Local CLI | REQ-205 | SAC-1 |
| REQ-301 | 5 | MUST | Remote CLI | REQ-101, REQ-102 | SAC-2 |
| REQ-302 | 5 | MUST | Remote CLI | — | SAC-11 |
| REQ-303 | 5 | MUST | Remote CLI | — | SAC-9 |
| REQ-304 | 5 | MUST | Remote CLI | — | SAC-2 |
| REQ-305 | 5 | SHOULD | Remote CLI | REQ-301 | SAC-2 |
| REQ-306 | 5 | MUST | Remote CLI | REQ-101 | SAC-3 |
| REQ-401 | 6 | MUST | Ingestion CLI | — | SAC-5 |
| REQ-402 | 6 | MUST | Ingestion CLI | — | SAC-5 |
| REQ-403 | 6 | MUST | Ingestion CLI | — | SAC-5 |
| REQ-501 | 7 | MUST | Parity | REQ-101 | SAC-3, SAC-4 |
| REQ-502 | 7 | MUST | Parity | REQ-101 | SAC-4 |
| REQ-503 | 7 | SHOULD | Parity | REQ-501 | SAC-3 |
| REQ-901 | 8 | SHOULD | Non-Functional | — | SAC-10 |
| REQ-902 | 8 | MUST | Non-Functional | — | SAC-11 |
| REQ-903 | 8 | MUST | Non-Functional | — | SAC-6 |
| REQ-904 | 8 | MUST | Non-Functional | — | SAC-12 |
