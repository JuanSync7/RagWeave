# CLI Interface — Implementation Guide

**AION Knowledge Management Platform**
Version: 1.0 | Status: Initial Draft | Domain: CLI Interface

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-13 | AI Assistant | Initial draft — 5 phases, 17 tasks covering shared infrastructure through parity and polish |

> **Document intent:** This file is a phased implementation plan tied to `CLI_SPEC.md`.
> It is not the source of truth for current runtime behavior.
> For as-built behavior, refer to the source files directly: `cli.py`, `server/cli_client.py`, `ingest.py`, and `src/platform/`.

This document provides a phased implementation plan and detailed code appendix for the CLI interface layer specified in `CLI_SPEC.md`. The specification defines 29 requirements across six sections (REQ-101 through REQ-904). Every task below references the requirements it satisfies.

---

# Part A: Task-Oriented Overview

## Phase 1 — Shared CLI Infrastructure

Foundation layer: command registry, dispatch, interactive input, and output formatting. These modules are consumed by all three CLI entry points and shared with the web console.

### Task 1.1: Command Catalog Module

**Description:** Implement the shared command catalog in `src/platform/command_catalog.py`. The catalog is the single source of truth for all slash commands available across CLI and web console. Each command entry defines the command name, argument schema, description, grouping/category, and handler reference. Both CLI entry points and the web console adapter import from this module; no surface defines its own command list.

**Requirements Covered:** REQ-101, REQ-501, REQ-502

**Dependencies:** None — this is the foundational module.

**Complexity:** M

**Subtasks:**

1. Define a `CommandEntry` dataclass with fields: name, description, arguments (list of argument descriptors), category, handler callable, availability (local/remote/both)
2. Implement a `CommandCatalog` registry class with `register`, `get`, `list_all`, `list_by_category`, and `search` methods
3. Register all existing slash commands (`/help`, `/sources`, `/headings`, `/preset`, `/mode`, `/verbose`, `/new`, `/clear`, `/history`, `/server`, `/quit`)
4. Add an availability field so commands can declare whether they work in local mode, remote mode, or both
5. Ensure the web console adapter can import and enumerate the same catalog without duplicating definitions
6. Add unit tests verifying catalog integrity (no duplicate names, all required fields populated)

---

### Task 1.2: Command Runtime and Dispatch

**Description:** Implement the command runtime in `src/platform/command_runtime.py`. The runtime parses user input beginning with `/`, resolves the command name against the catalog, validates arguments, and invokes the registered handler. Unknown commands produce a helpful error listing similar available commands.

**Requirements Covered:** REQ-102, REQ-106

**Dependencies:** Task 1.1 (command catalog)

**Complexity:** M

**Subtasks:**

1. Implement input parsing: split the `/command arg1 arg2` input into command name and argument list
2. Implement command resolution against the catalog with exact match and prefix match fallback
3. Implement fuzzy matching for unknown commands (Levenshtein distance or prefix-based) to suggest alternatives
4. Implement argument validation against the command's declared argument schema
5. Invoke the handler with parsed arguments; catch and format handler exceptions as user-facing errors
6. Ensure no unhandled exception reaches the terminal for any user input (REQ-106)

---

### Task 1.3: CLI Interactive Input and Tab Completion

**Description:** Implement the interactive input module in `src/platform/cli_interactive.py`. This module handles prompt rendering, readline-based tab completion, and the live-filtering command menu. Tab completion candidates are derived from the shared command catalog.

**Requirements Covered:** REQ-104, REQ-204

**Dependencies:** Task 1.1 (command catalog)

**Complexity:** M

**Subtasks:**

1. Configure Python `readline` with a custom completer function
2. Implement tab completion for slash command names: pressing Tab after `/` lists all commands; pressing Tab after a partial name completes or shows candidates
3. Implement tab completion for command arguments where applicable (preset names from disk, source names from index metadata)
4. Implement the live-filtering command menu: typing `/` alone and pressing Enter displays all commands grouped by category; continued typing filters the list
5. Add graceful degradation: if `readline` is unavailable, tab completion is silently disabled (no crash, no error)
6. Render the prompt with current mode indicator (e.g., `[query]>` or `[ingest]>`)

---

### Task 1.4: CLI Log Formatting and Output Styling

**Description:** Implement the shared formatting module in `src/platform/cli_log_formatting.py`. All CLI output (errors, success messages, section headers, badges, separators) flows through this module to ensure consistent ANSI-colored terminal output across all three entry points.

**Requirements Covered:** REQ-105

**Dependencies:** None — standalone utility module.

**Complexity:** S

**Subtasks:**

1. Define a color palette: error (red), success (green), info (cyan), warning (yellow), muted (gray), emphasis (bold white)
2. Implement badge functions: `error_badge("[ERROR]")`, `ok_badge("[OK]")`, `info_badge("[INFO]")`, `warn_badge("[WARN]")`
3. Implement structural formatting: section headers, horizontal separators, indented blocks, key-value pair alignment
4. Implement ANSI detection: check `sys.stdout.isatty()` and `TERM` environment variable; disable ANSI codes when output is piped or terminal does not support them
5. Ensure all three entry points import formatting from this module (no inline ANSI escape sequences elsewhere)

---

## Phase 2 — Local CLI (cli.py)

The full-featured interactive CLI that loads models locally and accesses RAGChain directly. Approximately 900 lines covering REPL lifecycle, query execution, ingestion, and result display.

### Task 2.1: REPL Shell and Mode Switching

**Description:** Implement the interactive REPL in `cli.py` with support for two operating modes: query (default) and ingest. The REPL loop reads input, dispatches slash commands to the command runtime, and routes non-command input to the active mode handler.

**Requirements Covered:** REQ-201, REQ-106

**Dependencies:** Task 1.2 (command runtime), Task 1.3 (interactive input)

**Complexity:** M

**Subtasks:**

1. Implement the main REPL loop with `input()` or readline-based prompt
2. Implement mode state management: current mode stored as enum, switchable via `/mode query` and `/mode ingest`
3. Update the prompt to reflect the active mode (e.g., `[query]>`, `[ingest]>`)
4. Route slash commands to the command runtime; route plain text to the active mode handler
5. Handle empty input silently (re-display prompt)
6. Handle `KeyboardInterrupt` (Ctrl+C) gracefully: cancel current operation but keep the REPL alive
7. Handle `EOFError` (Ctrl+D) as a quit signal

---

### Task 2.2: Landing Page and System Info Display

**Description:** On startup, display a styled landing page showing loaded models, active configuration, available document sources, and key slash commands. The landing page confirms successful initialization and orients the user.

**Requirements Covered:** REQ-203, REQ-202

**Dependencies:** Task 1.4 (formatting)

**Complexity:** S

**Subtasks:**

1. Display the system banner with application name and version
2. Display loaded model information: embedding model name, generation model name, reranker name, with load times
3. Display index statistics: number of indexed documents and available sources
4. Display active configuration: current filters, preset, verbose mode
5. Display a quick-start command reference (`/help`, `/sources`, `/preset`, `/mode`, `/quit`)
6. Use the shared formatting module for all output (badges, colors, separators)

---

### Task 2.3: Query Execution with Streaming Output

**Description:** In query mode, accept natural-language queries and execute them against the local RAGChain. Stream generated tokens to the terminal as they are produced, providing immediate feedback.

**Requirements Covered:** REQ-205, REQ-202

**Dependencies:** Task 2.1 (REPL shell)

**Complexity:** M

**Subtasks:**

1. Accept query text from the REPL input
2. Apply active filters (source, heading) and current preset parameters to the query
3. Invoke RAGChain with streaming callback that prints each token as it arrives (no buffering)
4. Display a clear visual separator between the query prompt and the answer output
5. Handle Ctrl+C during generation: interrupt the stream, display partial output, and return to prompt
6. After generation completes, collect metadata (scores, sources, timings) for result display (Task 2.5)

---

### Task 2.4: Ingestion Integration and Progress Display

**Description:** In ingest mode, accept ingestion commands and run the document processing pipeline with real-time progress display. Show document counts, current pipeline stage, and elapsed time.

**Requirements Covered:** REQ-206

**Dependencies:** Task 2.1 (REPL shell), Task 1.4 (formatting)

**Complexity:** M

**Subtasks:**

1. Accept ingestion paths or commands from the REPL input in ingest mode
2. Invoke the ingestion pipeline with a progress callback
3. Display a progress indicator: `[42/100]` documents processed
4. Display the current pipeline stage (loading, chunking, embedding, storing)
5. Display elapsed time, updated during processing
6. Report individual document errors inline without halting the pipeline
7. Display a final summary: total processed, succeeded, failed, chunks created, total elapsed time

---

### Task 2.5: Result Display (sources, scores, timings)

**Description:** After query execution, display structured metadata: relevance scores of retrieved chunks, source document references, and timing breakdown. Metadata display is toggleable via `/verbose`.

**Requirements Covered:** REQ-208, REQ-207

**Dependencies:** Task 2.3 (query execution)

**Complexity:** S

**Subtasks:**

1. Display retrieved chunks with relevance scores, sorted descending by score
2. Display source document name and section/heading for each chunk
3. Display timing breakdown: total time, retrieval time, reranking time, generation time
4. Display active filters in the result header (source filter, heading filter)
5. Implement `/verbose on|off` toggle to show or hide metadata (default: on)
6. Use the shared formatting module for score coloring (green for high scores, yellow for medium, red for low)

---

## Phase 3 — Remote CLI (cli_client.py)

The HTTP-based CLI client that connects to a running FastAPI server. Thin client with instant startup, SSE streaming, and full command catalog support.

### Task 3.1: HTTP Client and Connection Management

**Description:** Implement the HTTP client in `server/cli_client.py` with connection management, health checking, and the same REPL experience as the Local CLI. The client starts instantly (no model loading) and verifies server connectivity at startup.

**Requirements Covered:** REQ-301, REQ-302, REQ-903

**Dependencies:** Task 1.2 (command runtime), Task 1.3 (interactive input), Task 1.4 (formatting)

**Complexity:** M

**Subtasks:**

1. Implement HTTP client using `requests` or `httpx` with configurable base URL
2. Perform a startup health check (`GET /health`); warn on failure but do not block the REPL
3. Implement the REPL loop, reusing the shared command runtime for slash command dispatch
4. Route non-command input as query requests to the server (`POST /query`)
5. Implement `/server <url>` command to change the target server URL without restarting
6. Implement retry logic with exponential backoff (up to 3 attempts) for transient failures (timeout, HTTP 503)
7. Ensure startup time is under 2 seconds (no model imports, no heavy initialization)

---

### Task 3.2: Authentication (API Key + Bearer Token)

**Description:** Implement authentication support for the Remote CLI. Credentials are configurable via CLI flags, environment variables, or configuration file, with a clear precedence order.

**Requirements Covered:** REQ-303, REQ-904

**Dependencies:** Task 3.1 (HTTP client)

**Complexity:** S

**Subtasks:**

1. Accept `--api-key <key>` CLI flag for API key authentication
2. Accept `--token <token>` CLI flag for bearer token authentication
3. Read fallback credentials from environment variables (`RAG_API_KEY`, `RAG_BEARER_TOKEN`)
4. Attach credentials to all HTTP requests (API key as header, bearer token as `Authorization: Bearer` header)
5. Ensure credentials are not logged, echoed, or stored in shell history
6. Display clear error messages on authentication failure, identifying which auth method was attempted

---

### Task 3.3: SSE Streaming for Generation Tokens

**Description:** Implement SSE (Server-Sent Events) streaming to receive generation tokens from the API server in real time. Tokens are rendered to the terminal as they arrive, matching the Local CLI's streaming experience.

**Requirements Covered:** REQ-304

**Dependencies:** Task 3.1 (HTTP client)

**Complexity:** M

**Subtasks:**

1. Establish SSE connection for generation requests using `httpx` or `sseclient-py`
2. Parse SSE events: extract token text from `data:` lines
3. Render tokens to the terminal as they arrive (flush after each token)
4. Handle SSE error events: display the error message and return to prompt
5. Handle connection drops (timeout, disconnect) with a message indicating the failure point
6. Handle Ctrl+C: close the SSE connection cleanly and return to prompt
7. Handle the final SSE event containing metadata (sources, scores, timings) for result display

---

### Task 3.4: Conversation Management (multi-turn)

**Description:** Implement multi-turn conversation support in the Remote CLI. Maintain a conversation ID across queries to enable the server to preserve context for follow-up questions.

**Requirements Covered:** REQ-305, REQ-306

**Dependencies:** Task 3.1 (HTTP client)

**Complexity:** S

**Subtasks:**

1. Generate a conversation ID at session start (UUID)
2. Send the conversation ID with each query request
3. Implement `/new` command to start a new conversation (generate new ID)
4. Implement `/clear` command as an alias for `/new`
5. Implement `/history` command to retrieve and display conversation history from the server
6. Display the conversation ID in the landing page or via a `/status` command

---

## Phase 4 — Ingestion CLI (ingest.py)

The standalone batch ingestion CLI for CI/CD pipelines and scheduled jobs. Non-interactive, headless-capable, with structured progress reporting.

### Task 4.1: Standalone Pipeline Execution

**Description:** Implement the standalone ingestion pipeline executor in `ingest.py`. The CLI accepts input paths, processes all documents through the full pipeline, and exits with an appropriate exit code.

**Requirements Covered:** REQ-401

**Dependencies:** None — standalone entry point (uses the ingestion pipeline internally).

**Complexity:** M

**Subtasks:**

1. Implement `main()` entry point with `argparse` for CLI argument parsing
2. Accept `--input <path>` for file or directory input
3. Discover all processable documents at the input path (recursive directory traversal with supported extensions)
4. Invoke the ingestion pipeline for each document (loading, chunking, embedding, storing)
5. Exit with code 0 on full success, 1 on partial failure, 2 on total failure
6. Ensure the process runs headlessly (no TTY required, no interactive prompts)

---

### Task 4.2: CLI Flags and Environment Configuration

**Description:** Implement full configuration support via CLI flags and environment variables. Flags take precedence over environment variables, which take precedence over config file defaults.

**Requirements Covered:** REQ-402, REQ-904

**Dependencies:** Task 4.1 (pipeline execution)

**Complexity:** S

**Subtasks:**

1. Define CLI flags: `--input`, `--chunk-size`, `--embedding-model`, `--vector-store-url`, `--batch-size`, `--config`
2. Implement `--help` with descriptions and default values for all flags
3. Map environment variables: `RAG_INGEST_CHUNK_SIZE`, `RAG_INGEST_EMBEDDING_MODEL`, `RAG_INGEST_VECTOR_STORE_URL`, `RAG_INGEST_BATCH_SIZE`
4. Implement configuration loading from file (YAML/JSON) with the `--config` flag
5. Implement precedence resolution: CLI flag > environment variable > config file > hardcoded default
6. Validate configuration and fail fast with clear error messages for invalid values

---

### Task 4.3: Progress Reporting and Error Summary

**Description:** Implement progress reporting during ingestion and a structured summary upon completion. Individual document failures are logged with paths and reasons; the final summary gives operators a clear picture of ingestion completeness.

**Requirements Covered:** REQ-403, REQ-105

**Dependencies:** Task 4.1 (pipeline execution), Task 1.4 (formatting)

**Complexity:** S

**Subtasks:**

1. Display progress as documents are processed: `[42/100] Processing: path/to/document.pdf`
2. Display the current pipeline stage for each document (loading, chunking, embedding, storing)
3. Log individual document failures inline: `[ERROR] path/to/bad.pdf — reason`
4. On completion, display a structured summary: total documents, succeeded, failed, chunks created, elapsed time
5. List all failed documents with their file paths and failure reasons
6. Use the shared formatting module for consistent badge and color output (when TTY is available)

---

## Phase 5 — Parity and Polish

Cross-cutting concerns: CLI/UI parity verification, preset interoperability, graceful degradation, and startup performance.

### Task 5.1: CLI/UI Parity Verification

**Description:** Verify and enforce feature parity between CLI and web console. Maintain a parity matrix and implement automated parity tests that verify every command in the shared catalog is exercisable from both surfaces.

**Requirements Covered:** REQ-501, REQ-503

**Dependencies:** Task 1.1 (command catalog), all Phase 2 and Phase 3 tasks

**Complexity:** M

**Subtasks:**

1. Create a parity matrix listing every user-facing feature and its availability in CLI and web console
2. Identify and document intentionally interface-specific features (e.g., mouse interactions in console, terminal key bindings in CLI)
3. Implement a parity test that enumerates all commands in the shared catalog and asserts both CLI and console adapters register handlers for each
4. Integrate parity tests into CI to block merges on failure
5. Ensure new commands added to the catalog automatically cause a parity test failure if a handler is missing on either surface

---

### Task 5.2: Preset Support in CLI

**Description:** Implement full preset support across both Local and Remote CLIs. Presets are saved to disk in a format shared with the web console, ensuring interoperability.

**Requirements Covered:** REQ-103, REQ-502

**Dependencies:** Task 1.1 (command catalog), Task 1.2 (command runtime)

**Complexity:** S

**Subtasks:**

1. Implement `/preset save <name>` to persist current parameter state (model, source filters, heading filters, retrieval settings) to a JSON file
2. Implement `/preset load <name>` to restore a saved parameter state
3. Implement `/preset list` to display all available presets with their key settings
4. Ensure preset file format matches the web console's preset format (shared schema)
5. Store presets in a configurable directory (default: `~/.config/aion/presets/`)
6. Add preset name tab completion to the interactive input module

---

### Task 5.3: Graceful Degradation and Error Handling

**Description:** Ensure all CLI entry points handle errors gracefully: no stack traces for user-facing errors, clear messages for configuration problems, and resilient operation under degraded conditions.

**Requirements Covered:** REQ-106, REQ-903, REQ-901, REQ-902, REQ-904

**Dependencies:** All prior tasks.

**Complexity:** M

**Subtasks:**

1. Wrap all REPL iterations in a top-level exception handler that formats unexpected errors as user-friendly messages
2. Handle server unavailability in Remote CLI: display `"Cannot reach server at <url>. Check the server status and try again."` and keep the REPL alive
3. Handle model loading failures in Local CLI: identify which model failed and why, suggest remediation
4. Validate configuration at startup: fail fast with clear messages for missing required values
5. Ensure Local CLI startup (excluding model loading) completes within 10 seconds (REQ-901)
6. Ensure Remote CLI startup completes within 2 seconds (REQ-902)
7. Handle ANSI degradation: plain text output when terminal does not support ANSI or output is piped

---

## Task Dependency Graph

```
Phase 1 (Shared CLI Infrastructure)
├── Task 1.1: Command Catalog Module ──────────────────────────┐
├── Task 1.4: CLI Log Formatting (standalone) ─────────────────┤
│                                                              │
├── Task 1.2: Command Runtime ◄── Task 1.1                    │
└── Task 1.3: CLI Interactive Input ◄── Task 1.1              │
                                                               │
Phase 2 (Local CLI)                                            │
├── Task 2.1: REPL Shell ◄── Task 1.2, 1.3                    │
├── Task 2.2: Landing Page ◄── Task 1.4                       │
├── Task 2.3: Query Execution ◄── Task 2.1                    │
├── Task 2.4: Ingestion Integration ◄── Task 2.1, 1.4         │
└── Task 2.5: Result Display ◄── Task 2.3                     │
                                                               │
Phase 3 (Remote CLI)                                           │
├── Task 3.1: HTTP Client ◄── Task 1.2, 1.3, 1.4             │
├── Task 3.2: Authentication ◄── Task 3.1                     │
├── Task 3.3: SSE Streaming ◄── Task 3.1                      │
└── Task 3.4: Conversation Management ◄── Task 3.1            │
                                                               │
Phase 4 (Ingestion CLI)                                        │
├── Task 4.1: Standalone Pipeline Execution                    │
├── Task 4.2: CLI Flags and Configuration ◄── Task 4.1        │
└── Task 4.3: Progress Reporting ◄── Task 4.1, 1.4            │
                                                               │
Phase 5 (Parity and Polish)                                    │
├── Task 5.1: CLI/UI Parity Verification ◄── Task 1.1, all P2/P3
├── Task 5.2: Preset Support ◄── Task 1.1, 1.2                │
└── Task 5.3: Graceful Degradation ◄── All prior tasks ────────┘
```

---

## Task-to-Requirement Mapping

| Task | Requirements Covered |
|------|---------------------|
| 1.1 Command Catalog Module | REQ-101, REQ-501, REQ-502 |
| 1.2 Command Runtime and Dispatch | REQ-102, REQ-106 |
| 1.3 CLI Interactive Input and Tab Completion | REQ-104, REQ-204 |
| 1.4 CLI Log Formatting and Output Styling | REQ-105 |
| 2.1 REPL Shell and Mode Switching | REQ-201, REQ-106 |
| 2.2 Landing Page and System Info Display | REQ-203, REQ-202 |
| 2.3 Query Execution with Streaming Output | REQ-205, REQ-202 |
| 2.4 Ingestion Integration and Progress Display | REQ-206 |
| 2.5 Result Display (sources, scores, timings) | REQ-208, REQ-207 |
| 3.1 HTTP Client and Connection Management | REQ-301, REQ-302, REQ-903 |
| 3.2 Authentication (API Key + Bearer Token) | REQ-303, REQ-904 |
| 3.3 SSE Streaming for Generation Tokens | REQ-304 |
| 3.4 Conversation Management (multi-turn) | REQ-305, REQ-306 |
| 4.1 Standalone Pipeline Execution | REQ-401 |
| 4.2 CLI Flags and Environment Configuration | REQ-402, REQ-904 |
| 4.3 Progress Reporting and Error Summary | REQ-403, REQ-105 |
| 5.1 CLI/UI Parity Verification | REQ-501, REQ-503 |
| 5.2 Preset Support in CLI | REQ-103, REQ-502 |
| 5.3 Graceful Degradation and Error Handling | REQ-106, REQ-903, REQ-901, REQ-902, REQ-904 |

---

# Part B: Code Appendix

## B.1 Command Catalog and Registration

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class CommandAvailability(Enum):
    LOCAL_ONLY = "local"
    REMOTE_ONLY = "remote"
    BOTH = "both"


@dataclass
class CommandArgument:
    name: str
    description: str
    required: bool = False
    choices: Optional[list[str]] = None
    default: Optional[str] = None


@dataclass
class CommandEntry:
    name: str                                    # e.g., "help", "sources", "preset"
    description: str                             # One-line description
    category: str                                # Grouping: "navigation", "query", "config", "system"
    handler: Optional[Callable] = None           # Bound at registration time
    arguments: list[CommandArgument] = field(default_factory=list)
    availability: CommandAvailability = CommandAvailability.BOTH
    hidden: bool = False                         # True for debug/maintenance commands


class CommandCatalog:
    """Single source of truth for all slash commands.

    Shared between CLI (local + remote) and web console.
    See REQ-101, REQ-501.
    """

    def __init__(self):
        self._commands: dict[str, CommandEntry] = {}

    def register(self, entry: CommandEntry) -> None:
        if entry.name in self._commands:
            raise ValueError(f"Duplicate command registration: /{entry.name}")
        self._commands[entry.name] = entry

    def get(self, name: str) -> Optional[CommandEntry]:
        return self._commands.get(name)

    def list_all(self, include_hidden: bool = False) -> list[CommandEntry]:
        return [
            cmd for cmd in self._commands.values()
            if include_hidden or not cmd.hidden
        ]

    def list_by_category(self, category: str) -> list[CommandEntry]:
        return [
            cmd for cmd in self._commands.values()
            if cmd.category == category and not cmd.hidden
        ]

    def search(self, prefix: str) -> list[CommandEntry]:
        """Return commands whose names start with the given prefix."""
        return [
            cmd for cmd in self._commands.values()
            if cmd.name.startswith(prefix) and not cmd.hidden
        ]

    def suggest(self, name: str, max_results: int = 3) -> list[str]:
        """Suggest similar command names for typo correction."""
        scored = []
        for cmd_name in self._commands:
            dist = _levenshtein(name, cmd_name)
            if dist <= max(len(name) // 2, 2):
                scored.append((dist, cmd_name))
        scored.sort()
        return [name for _, name in scored[:max_results]]

    @property
    def names(self) -> list[str]:
        return list(self._commands.keys())


def _levenshtein(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]


# --- Global catalog instance ---

catalog = CommandCatalog()


def register_core_commands() -> None:
    """Register all built-in slash commands."""
    catalog.register(CommandEntry(
        name="help",
        description="Show available commands and usage",
        category="system",
        arguments=[CommandArgument("command", "Command to get help for", required=False)],
    ))
    catalog.register(CommandEntry(
        name="sources",
        description="Set or clear source filter for retrieval",
        category="query",
        arguments=[
            CommandArgument("filter", "Source name or 'clear'", required=False),
        ],
    ))
    catalog.register(CommandEntry(
        name="headings",
        description="Set or clear heading filter for retrieval",
        category="query",
        arguments=[
            CommandArgument("filter", "Heading text or 'clear'", required=False),
        ],
    ))
    catalog.register(CommandEntry(
        name="preset",
        description="Manage query parameter presets",
        category="config",
        arguments=[
            CommandArgument("action", "save|load|list", required=True, choices=["save", "load", "list"]),
            CommandArgument("name", "Preset name", required=False),
        ],
    ))
    catalog.register(CommandEntry(
        name="mode",
        description="Switch between query and ingest modes",
        category="system",
        arguments=[
            CommandArgument("mode", "query|ingest", required=True, choices=["query", "ingest"]),
        ],
        availability=CommandAvailability.LOCAL_ONLY,
    ))
    catalog.register(CommandEntry(
        name="verbose",
        description="Toggle detailed metadata display",
        category="config",
        arguments=[
            CommandArgument("state", "on|off", required=False, choices=["on", "off"]),
        ],
    ))
    catalog.register(CommandEntry(
        name="new",
        description="Start a new conversation",
        category="navigation",
    ))
    catalog.register(CommandEntry(
        name="clear",
        description="Clear conversation history",
        category="navigation",
    ))
    catalog.register(CommandEntry(
        name="history",
        description="Display conversation history",
        category="navigation",
    ))
    catalog.register(CommandEntry(
        name="server",
        description="View or change the API server URL",
        category="config",
        arguments=[
            CommandArgument("url", "New server URL", required=False),
        ],
        availability=CommandAvailability.REMOTE_ONLY,
    ))
    catalog.register(CommandEntry(
        name="quit",
        description="Exit the CLI",
        category="system",
    ))
```

---

## B.2 REPL Shell with Mode Switching

```python
import sys
from enum import Enum

from src.platform.command_catalog import catalog, CommandAvailability
from src.platform.command_runtime import dispatch_command
from src.platform.cli_interactive import setup_readline, get_prompt
from src.platform.cli_log_formatting import (
    print_error, print_info, print_separator, format_landing_page,
)


class ReplMode(Enum):
    QUERY = "query"
    INGEST = "ingest"


class LocalREPL:
    """Interactive REPL for the Local CLI.

    Supports mode switching between query and ingest.
    See REQ-201, REQ-203, REQ-205, REQ-206.
    """

    def __init__(self, rag_chain, ingestion_pipeline, config: dict):
        self.rag_chain = rag_chain
        self.ingestion_pipeline = ingestion_pipeline
        self.config = config
        self.mode = ReplMode.QUERY
        self.verbose = True
        self.source_filter: str | None = None
        self.heading_filter: str | None = None
        self.running = True

    def start(self) -> None:
        setup_readline(catalog)
        self._display_landing_page()
        self._run_loop()

    def _display_landing_page(self) -> None:
        """Show system info on startup (REQ-203)."""
        format_landing_page(
            embedding_model=self.config.get("embedding_model", "unknown"),
            generation_model=self.config.get("generation_model", "unknown"),
            reranker_model=self.config.get("reranker_model", "unknown"),
            doc_count=self.config.get("doc_count", 0),
            source_count=self.config.get("source_count", 0),
        )

    def _run_loop(self) -> None:
        while self.running:
            try:
                prompt = get_prompt(self.mode.value, self.source_filter)
                user_input = input(prompt).strip()

                if not user_input:
                    continue

                if user_input.startswith("/"):
                    self._handle_command(user_input)
                elif self.mode == ReplMode.QUERY:
                    self._handle_query(user_input)
                elif self.mode == ReplMode.INGEST:
                    self._handle_ingest(user_input)

            except KeyboardInterrupt:
                print()  # Newline after ^C
                print_info("Press Ctrl+D or type /quit to exit.")
                continue
            except EOFError:
                print()
                self.running = False

    def _handle_command(self, raw_input: str) -> None:
        """Dispatch slash command through the shared runtime (REQ-102)."""
        command_name = raw_input.lstrip("/").split()[0]
        args = raw_input.lstrip("/").split()[1:]

        # Check availability
        entry = catalog.get(command_name)
        if entry and entry.availability == CommandAvailability.REMOTE_ONLY:
            print_error(
                f"/{command_name} is only available in remote mode. "
                "Start the remote CLI (cli_client.py) for this command."
            )
            return

        # Built-in mode switching
        if command_name == "mode" and args:
            self._switch_mode(args[0])
            return

        if command_name == "quit":
            self.running = False
            return

        dispatch_command(command_name, args, context=self)

    def _switch_mode(self, target: str) -> None:
        try:
            new_mode = ReplMode(target.lower())
            self.mode = new_mode
            print_info(f"Switched to {new_mode.value} mode.")
        except ValueError:
            print_error(f"Unknown mode: {target}. Use 'query' or 'ingest'.")

    def _handle_query(self, query_text: str) -> None:
        """Execute query with streaming output (REQ-205)."""
        print_separator()
        try:
            result = self.rag_chain.query(
                query=query_text,
                source_filter=self.source_filter,
                heading_filter=self.heading_filter,
                stream_callback=lambda token: print(token, end="", flush=True),
            )
            print()  # Newline after streamed output
            print_separator()

            if self.verbose:
                self._display_results(result)

        except KeyboardInterrupt:
            print("\n")
            print_info("Generation interrupted.")

    def _handle_ingest(self, ingest_input: str) -> None:
        """Execute ingestion with progress display (REQ-206)."""
        import time
        start_time = time.time()
        print_info(f"Starting ingestion: {ingest_input}")

        def progress_callback(current: int, total: int, stage: str, doc_path: str):
            elapsed = time.time() - start_time
            print(
                f"\r[{current}/{total}] {stage}: {doc_path} "
                f"({elapsed:.1f}s elapsed)",
                end="", flush=True,
            )

        try:
            summary = self.ingestion_pipeline.run(
                input_path=ingest_input,
                progress_callback=progress_callback,
            )
            print()  # Newline after progress line
            self._display_ingest_summary(summary)
        except KeyboardInterrupt:
            print("\n")
            print_info("Ingestion interrupted.")

    def _display_results(self, result) -> None:
        """Display scores, sources, and timings (REQ-208)."""
        from src.platform.cli_log_formatting import (
            format_score, format_timing, format_source_ref,
        )

        print_info("Retrieved chunks:")
        for i, chunk in enumerate(result.chunks, 1):
            score_str = format_score(chunk.score)
            source_str = format_source_ref(chunk.source, chunk.heading)
            print(f"  {i}. [{score_str}] {source_str}")

        print()
        print_info("Timings:")
        format_timing("Retrieval", result.retrieval_time_ms)
        format_timing("Reranking", result.rerank_time_ms)
        format_timing("Generation", result.generation_time_ms)
        format_timing("Total", result.total_time_ms)

    def _display_ingest_summary(self, summary) -> None:
        from src.platform.cli_log_formatting import print_ok
        print_separator()
        print_ok(f"Ingestion complete: {summary.succeeded}/{summary.total} documents")
        print_info(f"  Chunks created: {summary.chunks_created}")
        print_info(f"  Elapsed time:   {summary.elapsed_seconds:.1f}s")
        if summary.failed > 0:
            print_error(f"  Failed: {summary.failed} documents")
            for failure in summary.failures:
                print_error(f"    - {failure.path}: {failure.reason}")
```

---

## B.3 HTTP Client with SSE Streaming

```python
import sys
import uuid
from typing import Optional

import httpx

from src.platform.command_catalog import catalog, CommandAvailability
from src.platform.command_runtime import dispatch_command
from src.platform.cli_interactive import setup_readline, get_prompt
from src.platform.cli_log_formatting import (
    print_error, print_info, print_ok, print_separator, print_warning,
)


class RemoteCLI:
    """HTTP-based CLI client with SSE streaming.

    Thin client — no model loading. Instant startup.
    See REQ-301, REQ-302, REQ-303, REQ-304, REQ-305.
    """

    MAX_RETRIES = 3
    BACKOFF_BASE = 1.0  # seconds

    def __init__(
        self,
        server_url: str = "http://localhost:8000",
        api_key: Optional[str] = None,
        bearer_token: Optional[str] = None,
    ):
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.bearer_token = bearer_token
        self.conversation_id = str(uuid.uuid4())
        self.running = True
        self.client = httpx.Client(timeout=30.0)

    def start(self) -> None:
        setup_readline(catalog)
        self._health_check()
        print_ok(f"Connected to {self.server_url}")
        print_info(f"Conversation: {self.conversation_id[:8]}...")
        self._run_loop()

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def _health_check(self) -> None:
        """Verify server connectivity at startup (REQ-302)."""
        try:
            resp = self.client.get(
                f"{self.server_url}/health",
                headers=self._build_headers(),
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            print_warning(
                f"Cannot reach server at {self.server_url}. "
                f"Check the server status and try again. ({e})"
            )

    def _run_loop(self) -> None:
        while self.running:
            try:
                prompt = get_prompt("remote", source_filter=None)
                user_input = input(prompt).strip()

                if not user_input:
                    continue

                if user_input.startswith("/"):
                    self._handle_command(user_input)
                else:
                    self._handle_query(user_input)

            except KeyboardInterrupt:
                print()
                print_info("Press Ctrl+D or type /quit to exit.")
                continue
            except EOFError:
                print()
                self.running = False

    def _handle_command(self, raw_input: str) -> None:
        command_name = raw_input.lstrip("/").split()[0]
        args = raw_input.lstrip("/").split()[1:]

        entry = catalog.get(command_name)
        if entry and entry.availability == CommandAvailability.LOCAL_ONLY:
            print_error(
                f"/{command_name} is not available in remote mode. "
                "Use the local CLI for this operation."
            )
            return

        if command_name == "quit":
            self.running = False
            return

        if command_name == "new" or command_name == "clear":
            self.conversation_id = str(uuid.uuid4())
            print_ok(f"New conversation: {self.conversation_id[:8]}...")
            return

        if command_name == "server" and args:
            self.server_url = args[0].rstrip("/")
            print_ok(f"Server URL changed to {self.server_url}")
            self._health_check()
            return

        dispatch_command(command_name, args, context=self)

    def _handle_query(self, query_text: str) -> None:
        """Send query and stream response via SSE (REQ-304)."""
        print_separator()
        payload = {
            "query": query_text,
            "conversation_id": self.conversation_id,
            "stream": True,
        }

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                self._stream_sse_response(payload)
                return
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    print_error("Authentication failed. Check your API key or token.")
                    return
                if e.response.status_code == 503 and attempt < self.MAX_RETRIES:
                    wait = self.BACKOFF_BASE * (2 ** (attempt - 1))
                    print_warning(f"Server unavailable, retrying in {wait:.0f}s...")
                    import time
                    time.sleep(wait)
                    continue
                print_error(f"Server error: {e.response.status_code}")
                return
            except httpx.TimeoutException:
                if attempt < self.MAX_RETRIES:
                    wait = self.BACKOFF_BASE * (2 ** (attempt - 1))
                    print_warning(f"Request timed out, retrying in {wait:.0f}s...")
                    import time
                    time.sleep(wait)
                    continue
                print_error(
                    f"Cannot reach server at {self.server_url}. "
                    "Check the server status and try again."
                )
                return
            except httpx.ConnectError:
                print_error(
                    f"Cannot reach server at {self.server_url}. "
                    "Check the server status and try again."
                )
                return

    def _stream_sse_response(self, payload: dict) -> None:
        """Establish SSE connection and render tokens in real time."""
        with self.client.stream(
            "POST",
            f"{self.server_url}/query/stream",
            json=payload,
            headers=self._build_headers(),
        ) as response:
            response.raise_for_status()
            buffer = ""

            for line in response.iter_lines():
                if not line:
                    continue

                if line.startswith("data: "):
                    data = line[6:]

                    if data == "[DONE]":
                        print()
                        break

                    # Parse SSE data — could be a token or metadata
                    import json
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        # Plain text token
                        print(data, end="", flush=True)
                        continue

                    if "token" in event:
                        print(event["token"], end="", flush=True)
                    elif "metadata" in event:
                        print()
                        print_separator()
                        self._display_metadata(event["metadata"])

                elif line.startswith("event: error"):
                    print_error("Server reported a streaming error.")
                    break

    def _display_metadata(self, metadata: dict) -> None:
        """Display result metadata from SSE final event."""
        from src.platform.cli_log_formatting import format_score, format_timing

        chunks = metadata.get("chunks", [])
        if chunks:
            print_info("Retrieved chunks:")
            for i, chunk in enumerate(chunks, 1):
                score = format_score(chunk.get("score", 0.0))
                source = chunk.get("source", "unknown")
                heading = chunk.get("heading", "")
                label = f"{source} > {heading}" if heading else source
                print(f"  {i}. [{score}] {label}")
            print()

        timings = metadata.get("timings", {})
        if timings:
            print_info("Timings:")
            for stage, ms in timings.items():
                format_timing(stage.capitalize(), ms)
```

---

## B.4 CLI/UI Parity Test

```python
"""Parity test: verify every command in the shared catalog has handlers
registered in both the CLI adapter and the web console adapter.

See REQ-501, REQ-503.
"""

import pytest

from src.platform.command_catalog import catalog, register_core_commands, CommandAvailability


# Simulated adapter registries — in production, these would be imported
# from the actual CLI and console adapter modules.

def get_cli_registered_commands() -> set[str]:
    """Return the set of command names registered in the CLI adapter."""
    from cli import CLI_COMMAND_HANDLERS  # noqa: F401
    return set(CLI_COMMAND_HANDLERS.keys())


def get_console_registered_commands() -> set[str]:
    """Return the set of command names registered in the web console adapter."""
    from server.console.command_handlers import CONSOLE_COMMAND_HANDLERS  # noqa: F401
    return set(CONSOLE_COMMAND_HANDLERS.keys())


@pytest.fixture(autouse=True)
def _setup_catalog():
    """Ensure the catalog is populated before tests run."""
    register_core_commands()


class TestCommandParity:
    """Automated parity verification between CLI and web console."""

    def test_all_catalog_commands_have_cli_handler(self):
        """Every non-remote-only command in the catalog must have a CLI handler."""
        catalog_commands = {
            cmd.name for cmd in catalog.list_all(include_hidden=True)
            if cmd.availability != CommandAvailability.REMOTE_ONLY
        }
        cli_commands = get_cli_registered_commands()

        missing = catalog_commands - cli_commands
        assert not missing, (
            f"Commands in catalog but missing CLI handler: {missing}. "
            "Register handlers in cli.py or mark as REMOTE_ONLY."
        )

    def test_all_catalog_commands_have_console_handler(self):
        """Every non-local-only command in the catalog must have a console handler."""
        catalog_commands = {
            cmd.name for cmd in catalog.list_all(include_hidden=True)
            if cmd.availability != CommandAvailability.LOCAL_ONLY
        }
        console_commands = get_console_registered_commands()

        missing = catalog_commands - console_commands
        assert not missing, (
            f"Commands in catalog but missing console handler: {missing}. "
            "Register handlers in console adapter or mark as LOCAL_ONLY."
        )

    def test_no_orphan_cli_handlers(self):
        """CLI must not define handlers for commands not in the catalog."""
        catalog_names = {cmd.name for cmd in catalog.list_all(include_hidden=True)}
        cli_commands = get_cli_registered_commands()

        orphans = cli_commands - catalog_names
        assert not orphans, (
            f"CLI defines handlers for commands not in catalog: {orphans}. "
            "Register these in the shared catalog or remove the handlers."
        )

    def test_no_orphan_console_handlers(self):
        """Console must not define handlers for commands not in the catalog."""
        catalog_names = {cmd.name for cmd in catalog.list_all(include_hidden=True)}
        console_commands = get_console_registered_commands()

        orphans = console_commands - catalog_names
        assert not orphans, (
            f"Console defines handlers for commands not in catalog: {orphans}. "
            "Register these in the shared catalog or remove the handlers."
        )

    def test_catalog_completeness_against_spec(self):
        """Verify the catalog has the minimum expected command set from CLI_SPEC.md."""
        expected = {
            "help", "sources", "headings", "preset", "mode",
            "verbose", "new", "clear", "history", "server", "quit",
        }
        actual = {cmd.name for cmd in catalog.list_all(include_hidden=True)}

        missing = expected - actual
        assert not missing, (
            f"Expected commands from CLI_SPEC.md missing from catalog: {missing}"
        )

    def test_availability_annotations_present(self):
        """Every command must declare its availability (local/remote/both)."""
        for cmd in catalog.list_all(include_hidden=True):
            assert cmd.availability is not None, (
                f"Command /{cmd.name} has no availability annotation"
            )
            assert isinstance(cmd.availability, CommandAvailability), (
                f"Command /{cmd.name} availability is not a CommandAvailability enum"
            )
```
