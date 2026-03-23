# Web Console — Implementation Guide

**AION Knowledge Management Platform**
Version: 2.0 | Status: Draft | Domain: Web Console (Dual-Console Architecture)

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 2.0 | 2026-03-13 | AI Assistant | Rewrite for dual-console architecture (User Console + Admin Console) per WEB_CONSOLE_SPEC.md v2.0 |
| 1.0 | 2026-03-13 | AI Assistant | Initial implementation guide for single-console architecture |

> **Document intent:** This file is a phased implementation plan tied to `WEB_CONSOLE_SPEC.md` v2.0.
> The v2.0 spec introduces a dual-console architecture: a **User Console** (modern chat interface at `/console`)
> and an **Admin Console** (tabbed debug/operations interface at `/console/admin`), both served from a shared
> backend infrastructure with unified slash commands, presets, and conversation management.
> For as-built behavior, see `server/console/README.md`.

---

# Part A: Task-Oriented Overview

## Phase 1 — Shared Backend Infrastructure

> Builds the shared foundation that both the User Console and Admin Console depend on.

### Task 1.1: Console Route Module and Dual Static Asset Serving

**Description:** Build the console backend route module that serves two separate console UIs from the same router — the User Console at `/console` and the Admin Console at `/console/admin` — each with its own static assets, while sharing a common set of API endpoints.

**Requirements Covered:** REQ-101, REQ-102, REQ-903

**Dependencies:** None

**Complexity:** M

**Subtasks:**

1. Create a dual-console router factory that registers all shared API endpoints under `/console` and mounts both UI entry points
2. Serve the User Console HTML entry point at `GET /console`
3. Serve the Admin Console HTML entry point at `GET /console/admin`
4. Serve User Console static assets at `GET /console/static/user/{path}`
5. Serve Admin Console static assets at `GET /console/static/admin/{path}`
6. Serve shared static assets (common CSS, shared JS modules) at `GET /console/static/shared/{path}`
7. Wire the console router into the main application using the router factory pattern

**Risks:** Path overlap between `/console` (User Console entry) and `/console/admin` (Admin Console entry) requires careful route ordering; test both paths under prefix-based reverse proxies.

---

### Task 1.2: Console Envelope and Error Semantics

**Description:** Implement the console-specific response envelope and error helpers used by all console API endpoints. Both consoles consume the same envelope format.

**Requirements Covered:** REQ-103, REQ-104

**Dependencies:** None

**Complexity:** S

**Subtasks:**

1. Define `ConsoleEnvelope` model: `ok`, `request_id`, `data`, `error`
2. Implement `console_ok()` helper that builds success envelopes with request ID
3. Implement `console_err()` helper that builds error envelopes with code, message, details
4. Define error code constants for common failures (auth, not found, rate limit, upstream timeout)
5. Ensure all console endpoints return the envelope format consistently

---

### Task 1.3: Health and Log Endpoints

**Description:** Build console-specific health aggregation and log snapshot endpoints used by both consoles.

**Requirements Covered:** REQ-305, REQ-306, REQ-307

**Dependencies:** Task 1.1, Task 1.2

**Complexity:** M

**Subtasks:**

1. Implement `GET /console/health` that aggregates API health, workflow engine status, worker availability, and generation model reachability
2. Implement `GET /console/logs` that returns recent log entries from available log files with severity filtering
3. Return health and log responses in the console envelope format
4. Include component-level status indicators for frontend rendering
5. Support auto-refresh with configurable interval and exponential backoff on failure

---

### Task 1.4: Query Endpoint (Streaming + Non-Streaming)

**Description:** Build the console query endpoint that supports both streaming SSE and non-streaming JSON modes. The User Console uses streaming by default for chat; the Admin Console uses non-streaming with full debug payloads.

**Requirements Covered:** REQ-201, REQ-205, REQ-206, REQ-302, REQ-303, REQ-401

**Dependencies:** Task 1.1, Task 1.2

**Complexity:** L

**Subtasks:**

1. Define `ConsoleQueryRequest` schema with all query parameters plus `stream` toggle and `debug` flag
2. Implement streaming mode: dispatch to workflow, emit retrieval completion event, stream generation tokens, emit final result event
3. Implement non-streaming mode: dispatch to workflow, return complete result in console envelope
4. When `debug=true`, include stage timings, raw retrieval scores, and source metadata in the response
5. Pass `conversation_id` and `memory_enabled` through to the core query dispatch
6. Return `conversation_id` in the response for continuity
7. Apply rate limiting and overload protection using shared middleware

**Risks:** SSE error handling during mid-stream failures requires special event types; mitigate by defining a structured error event format.

---

### Task 1.5: Ingestion Endpoint

**Description:** Build the console ingestion endpoint that triggers ingestion runs with configurable options. Primarily used by the Admin Console but accessible from both.

**Requirements Covered:** REQ-308, REQ-309

**Dependencies:** Task 1.1, Task 1.2

**Complexity:** M

**Subtasks:**

1. Define `ConsoleIngestionRequest` schema with mode, target path, and pipeline options
2. Implement ingestion dispatch with progress tracking
3. Support advanced options: document parsing mode, vision controls, verbose stage logging
4. Return ingestion result in the console envelope format with status badges

---

### Task 1.6: Admin Endpoints with RBAC

**Description:** Build console-specific admin endpoints for key and quota management with role-based access control. These endpoints are gated by RBAC and only accessible from the Admin Console.

**Requirements Covered:** REQ-310, REQ-311, REQ-312, REQ-313, REQ-314, REQ-315, REQ-316, REQ-317

**Dependencies:** Task 1.1, Task 1.2

**Complexity:** L

**Subtasks:**

1. Implement auth middleware that validates API keys and resolves roles (admin, operator, viewer)
2. Implement `GET /console/admin/keys` and `POST /console/admin/keys` for key listing and creation
3. Implement `POST /console/admin/keys/{key_id}/revoke` for key revocation
4. Implement `GET /console/admin/quotas` and `POST /console/admin/quotas/{tenant_id}` for quota management
5. Enforce RBAC at the endpoint level (server-side, not just frontend gating)
6. Return admin responses in the console envelope format
7. Log all admin actions with operator identity for audit trail

**Testing Strategy:** Test RBAC enforcement by calling admin endpoints with viewer/operator/admin-scoped keys and verifying correct 403 rejections.

---

## Phase 2 — Slash Commands and Presets

> Shared between all surfaces: CLI, User Console, and Admin Console.

### Task 2.1: Shared Slash-Command Catalog and Server-Side Dispatch

**Description:** Build the shared slash-command catalog that serves command metadata to CLI, User Console, and Admin Console, and implement the server-side dispatch endpoint.

**Requirements Covered:** REQ-107, REQ-108, REQ-207, REQ-208

**Dependencies:** Task 1.1

**Complexity:** M

**Subtasks:**

1. Define the command catalog module with command name, description, mode (query/ingest), surface scope (cli/user/admin/all), and handler mapping
2. Implement `GET /console/commands?mode=query|ingest&surface=user|admin` that returns available commands with descriptions
3. Implement `POST /console/command` that receives `{mode, command, arg, state}` and dispatches to the handler
4. Return normalized response: `{intent, action, data, message}`
5. Ensure the same catalog module is consumed by CLI command registration
6. Support autocomplete hints for command arguments

**Testing Strategy:** Parity tests that verify CLI `/help`, User Console commands, and Admin Console commands all return their expected subset from the same catalog.

---

### Task 2.2: Preset Management (Shared Built-In + Custom Per Console)

**Description:** Implement preset management with shared built-in presets and per-console custom presets. Both consoles share the same built-in set but store custom presets independently.

**Requirements Covered:** REQ-109, REQ-110

**Dependencies:** Task 1.1

**Complexity:** M

**Subtasks:**

1. Define preset schema: `{id, mode, name, console, query_options?, ingestion_options?}` where `console` is `user` or `admin`
2. Define built-in presets: "fast" (low search limit, low rerank), "quality" (high search limit, high rerank), "debug" (verbose, no update mode)
3. Implement local storage persistence for custom presets scoped by console type
4. Built-in presets are immutable and always available in both consoles
5. Implement preset picker in query and ingestion forms for each console
6. Applying a preset populates the form with saved values

---

## Phase 3 — Admin Console UI

> Preserves and extends current console functionality as the Admin Console at `/console/admin`.

### Task 3.1: Admin Console Shell and Tab Navigation

**Description:** Build the Admin Console UI shell with tabbed navigation (Query, Ingestion, Health, Admin), status bar, and notification system. This carries forward the existing console design.

**Requirements Covered:** REQ-301, REQ-302

**Dependencies:** Task 1.1

**Complexity:** M

**Subtasks:**

1. Build the single-page app shell with tab navigation (Query, Ingestion, Health, Admin)
2. Implement status bar showing API endpoint, connection status, auth context, and console type indicator
3. Implement notification system for success, error, and loading states
4. Implement tab state preservation (switching tabs does not reset input state)
5. Add API disconnection detection with visual indicator
6. Add visual distinction from User Console (different header color/branding)

---

### Task 3.2: Admin Query Panel (Full Debug: Stage Timings, Raw Scores, Source Viewer)

**Description:** Build the Admin Console query panel with full debug output including stage timings, raw retrieval scores, and source document viewer. This is the power-user query interface.

**Requirements Covered:** REQ-302, REQ-303, REQ-304

**Dependencies:** Task 3.1, Task 1.4

**Complexity:** L

**Subtasks:**

1. Build query input form with text area and collapsible advanced options
2. Implement non-streaming result display with complete response payload
3. Implement stage timing display (table or timeline) after query completion
4. Implement raw retrieval score table with per-chunk scores, filenames, and sections
5. Implement source document viewer (click a chunk to see full document context with highlight)
6. Wire preset picker and slash-command input helper
7. Optional streaming toggle for real-time output when debug is not needed

**Risks:** Stage timing and raw score data can be large; implement collapsible sections to avoid UI overload.

---

### Task 3.3: Admin Ingestion, Health, and Admin Panels

**Description:** Build the remaining Admin Console panel UIs for ingestion, health/logs, and admin management.

**Requirements Covered:** REQ-305, REQ-306, REQ-307, REQ-308, REQ-309, REQ-310, REQ-311, REQ-312, REQ-313, REQ-314, REQ-315, REQ-316, REQ-317

**Dependencies:** Task 3.1, Task 1.3, Task 1.5, Task 1.6

**Complexity:** L

**Subtasks:**

1. Build ingestion panel with form, mode selector, and status display with pipeline stage progress
2. Build health panel with component status cards and auto-refresh with backoff
3. Build log snapshot viewer with severity filter, timestamp display, and log search
4. Build admin panel with key list/create/revoke and quota list/set/delete interfaces
5. Implement confirmation dialogs for destructive admin actions with reason text
6. Gate admin panel visibility based on backend RBAC role check response
7. Display admin audit log of recent admin actions

---

## Phase 4 — User Console UI

> New modern chat interface served at `/console`.

### Task 4.1: User Console Shell, Sidebar, and Chat Layout

**Description:** Build the User Console shell with a sidebar for conversation management and a main chat area. The layout follows a modern messaging-app pattern: sidebar on the left, chat thread in the center.

**Requirements Covered:** REQ-201, REQ-202, REQ-203

**Dependencies:** Task 1.1

**Complexity:** M

**Subtasks:**

1. Build the single-page app shell with sidebar + main content layout
2. Implement collapsible sidebar with conversation list, new-chat button, and settings access
3. Implement main chat area with scrollable message thread and pinned input bar at bottom
4. Add header bar with current conversation title, model indicator, and connection status
5. Implement smooth sidebar toggle animation for small viewports
6. Add visual branding distinct from Admin Console

---

### Task 4.2: Chat Thread with Message Bubbles and Streaming

**Description:** Build the chat thread renderer with user/assistant message bubbles and real-time streaming token display for assistant responses.

**Requirements Covered:** REQ-204, REQ-205, REQ-206

**Dependencies:** Task 4.1, Task 1.4

**Complexity:** L

**Subtasks:**

1. Implement message bubble components with user (right-aligned) and assistant (left-aligned) styling
2. Implement streaming token renderer that appends tokens to the active assistant bubble in real-time
3. Display typing indicator while waiting for first token
4. Implement markdown rendering within message bubbles (code blocks, lists, bold/italic)
5. Auto-scroll to bottom on new messages with manual scroll override detection
6. Handle streaming errors gracefully (show error inline in the assistant bubble)
7. Support message copy-to-clipboard action

**Risks:** Streaming renderer must handle partial tokens, markdown boundary splits, and reconnection gracefully.

---

### Task 4.3: Source Citation Cards and Input Bar

**Description:** Build the source citation display and the chat input bar with slash-command support.

**Requirements Covered:** REQ-207, REQ-208, REQ-209, REQ-210

**Dependencies:** Task 4.2

**Complexity:** M

**Subtasks:**

1. Implement citation card component showing source filename, section, and relevance indicator
2. Display citation cards below the assistant message that referenced them
3. Implement expandable citation detail (click to see source chunk text)
4. Build chat input bar with multi-line text area, send button, and keyboard submit (Enter/Shift+Enter)
5. Implement slash-command autocomplete dropdown triggered by `/` prefix in input bar
6. Show command descriptions in autocomplete and execute on selection

---

### Task 4.4: Settings Panel and Theme System

**Description:** Build the User Console settings panel accessible from the sidebar, and implement theme support (light/dark/system).

**Requirements Covered:** REQ-211, REQ-212, REQ-904

**Dependencies:** Task 4.1

**Complexity:** M

**Subtasks:**

1. Build settings panel as a slide-over or modal accessible from sidebar
2. Implement query parameter controls (search limit, rerank top-k, streaming toggle)
3. Implement theme selector (light, dark, system-follows-OS)
4. Persist settings in local storage scoped to User Console
5. Apply theme via CSS custom properties for instant switching without page reload
6. Include preset picker in settings for default query configuration

---

### Task 4.5: Responsive Layout and Mobile Support

**Description:** Make the User Console responsive across desktop, tablet, and mobile viewports.

**Requirements Covered:** REQ-213, REQ-901

**Dependencies:** Task 4.1, Task 4.2, Task 4.3

**Complexity:** M

**Subtasks:**

1. Define breakpoints: desktop (>1024px sidebar visible), tablet (768-1024px sidebar overlay), mobile (<768px sidebar hidden by default)
2. Implement responsive sidebar behavior (persistent on desktop, overlay on tablet, drawer on mobile)
3. Ensure chat input bar remains pinned at bottom across all viewports
4. Optimize citation cards for narrow viewports (stack vertically)
5. Test touch interactions for mobile (swipe to open sidebar, tap to expand citations)

---

## Phase 5 — Conversation Management

> Shared between both consoles with console-specific presentation.

### Task 5.1: Conversation Pane (Sidebar in User Console, Panel in Admin Console)

**Description:** Build conversation management that appears as a sidebar list in the User Console and as a collapsible panel in the Admin Console Query tab.

**Requirements Covered:** REQ-401, REQ-402, REQ-403

**Dependencies:** Task 4.1, Task 3.2

**Complexity:** M

**Subtasks:**

1. Build shared conversation API client (`GET /console/conversations`, `POST /console/conversations/new`, `GET /console/conversations/{id}/history`)
2. Implement User Console conversation list in sidebar with title, message count, timestamp, and active indicator
3. Implement Admin Console conversation list as a collapsible side panel in the Query tab
4. Implement new conversation creation with auto-generated title from first message
5. Implement conversation selection that loads history and sets the active conversation ID
6. Implement compact button that triggers server-side summary compaction
7. Pass `conversation_id` and `memory_enabled` on all query submissions from both consoles

---

### Task 5.2: Cross-Console Conversation Continuity

**Description:** Enable conversations started in one console to be continued in the other, preserving full turn history.

**Requirements Covered:** REQ-404

**Dependencies:** Task 5.1

**Complexity:** M

**Subtasks:**

1. Ensure conversation storage is console-agnostic (no console-type field in conversation records)
2. Both consoles fetch from the same conversation list endpoint
3. Verify that a conversation started in the User Console renders correctly in the Admin Console query panel (and vice versa)
4. Handle display differences gracefully (Admin Console shows debug data only for turns that included it)

---

## Phase 6 — Parity Verification and Polish

> Ensures consistency across all three interfaces and final quality.

### Task 6.1: CLI/UI/Console Parity Verification (3-Way)

**Description:** Verify and enforce feature parity across CLI, User Console, and Admin Console. All three must expose the same user-facing capabilities (with interface-appropriate presentation).

**Requirements Covered:** REQ-105, REQ-106

**Dependencies:** Task 2.1, Task 3.2, Task 4.2, Task 5.1

**Complexity:** M

**Subtasks:**

1. Enumerate all user-facing features in the CLI (query parameters, commands, settings)
2. Enumerate all user-facing features in the User Console
3. Enumerate all user-facing features in the Admin Console
4. Identify gaps and implement missing features in the lagging interface
5. Verify shared schema/catalog modules are the single source of truth for all three interfaces
6. Add a 3-way parity test that compares CLI, User Console, and Admin Console capabilities

**Testing Strategy:** Automated parity test that asserts all three interfaces expose the same commands, parameters, and options (modulo intentionally interface-specific features documented as such).

---

### Task 6.2: Change Parity Process and Checklist

**Description:** Establish the process and checklist that ensures future changes maintain parity across all surfaces.

**Requirements Covered:** REQ-111

**Dependencies:** Task 6.1

**Complexity:** S

**Subtasks:**

1. Document the change parity checklist in the engineering guide
2. Define the rule: any user-facing feature added to one surface must be reflected in all others in the same change set (or explicitly marked interface-specific with justification)
3. Add a CI check that flags PRs modifying CLI commands without corresponding console updates (and vice versa)
4. Include parity review as a required PR review step for console/CLI changes

---

### Task 6.3: Keyboard Shortcuts and Accessibility

**Description:** Implement keyboard shortcuts for common actions and ensure accessibility compliance across both consoles.

**Requirements Covered:** REQ-905, REQ-902

**Dependencies:** Task 4.2, Task 3.2

**Complexity:** S

**Subtasks:**

1. Define keyboard shortcut map: `Ctrl+Enter` (send), `Ctrl+N` (new conversation), `Ctrl+K` (command palette), `Escape` (close panels)
2. Implement keyboard shortcut handler shared between both consoles
3. Display shortcut hints in UI (tooltips, settings panel)
4. Ensure all interactive elements are keyboard-navigable (tab order, focus management)
5. Add ARIA labels and roles for screen reader compatibility
6. Implement focus trap in modals and slide-over panels

---

## Task Dependency Graph

```
Phase 1 (Shared Backend Infrastructure)
├── Task 1.1: Dual Console Route Module ────────────────────────────────┐
├── Task 1.2: Console Envelope ─────────────────────────────────────────┤
├── Task 1.3: Health and Log Endpoints ◄── Task 1.1, 1.2 ──────────────┤
├── Task 1.4: Query Endpoint (Stream) ◄── Task 1.1, 1.2 ───────────────┤ [CRITICAL]
├── Task 1.5: Ingestion Endpoint ◄── Task 1.1, 1.2 ────────────────────┤
└── Task 1.6: Admin Endpoints + RBAC ◄── Task 1.1, 1.2 ────────────────┤
                                                                         │
Phase 2 (Commands and Presets)                                           │
├── Task 2.1: Slash-Command Catalog ◄── Task 1.1 ──────────────────────┤
└── Task 2.2: Preset Management ◄── Task 1.1 ──────────────────────────┤
                                                                         │
Phase 3 (Admin Console UI)                                               │
├── Task 3.1: Admin Shell and Tabs ◄── Task 1.1 ───────────────────────┤
├── Task 3.2: Admin Query Panel ◄── Task 3.1, 1.4 ─────────────────────┤ [CRITICAL]
└── Task 3.3: Admin Ingest/Health/Admin ◄── Task 3.1, 1.3, 1.5, 1.6 ──┤
                                                                         │
Phase 4 (User Console UI)                                                │
├── Task 4.1: User Shell + Sidebar ◄── Task 1.1 ───────────────────────┤
├── Task 4.2: Chat Thread + Streaming ◄── Task 4.1, 1.4 ───────────────┤ [CRITICAL]
├── Task 4.3: Citations + Input Bar ◄── Task 4.2 ──────────────────────┤
├── Task 4.4: Settings + Themes ◄── Task 4.1 ──────────────────────────┤
└── Task 4.5: Responsive Layout ◄── Task 4.1, 4.2, 4.3 ───────────────┤
                                                                         │
Phase 5 (Conversation Management)                                        │
├── Task 5.1: Conversation Pane ◄── Task 4.1, 3.2 ─────────────────────┤ [CRITICAL]
└── Task 5.2: Cross-Console Continuity ◄── Task 5.1 ───────────────────┤
                                                                         │
Phase 6 (Parity and Polish)                                              │
├── Task 6.1: 3-Way Parity Verification ◄── Task 2.1, 3.2, 4.2, 5.1 ──┤
├── Task 6.2: Change Parity Process ◄── Task 6.1 ──────────────────────┤
└── Task 6.3: Keyboard Shortcuts ◄── Task 4.2, 3.2 ────────────────────┘

Critical path: Task 1.1 → Task 1.4 → Task 4.2 → Task 5.1 → Task 6.1
```

---

## Task-to-Requirement Mapping

| Task | Requirements Covered |
|------|---------------------|
| **Phase 1: Shared Backend Infrastructure** | |
| 1.1 Dual Console Route Module | REQ-101, REQ-102, REQ-903 |
| 1.2 Console Envelope | REQ-103, REQ-104 |
| 1.3 Health and Log Endpoints | REQ-305, REQ-306, REQ-307 |
| 1.4 Query Endpoint (Streaming) | REQ-201, REQ-205, REQ-206, REQ-302, REQ-303, REQ-401 |
| 1.5 Ingestion Endpoint | REQ-308, REQ-309 |
| 1.6 Admin Endpoints + RBAC | REQ-310, REQ-311, REQ-312, REQ-313, REQ-314, REQ-315, REQ-316, REQ-317 |
| **Phase 2: Commands and Presets** | |
| 2.1 Slash-Command Catalog | REQ-107, REQ-108, REQ-207, REQ-208 |
| 2.2 Preset Management | REQ-109, REQ-110 |
| **Phase 3: Admin Console UI** | |
| 3.1 Admin Shell and Tabs | REQ-301, REQ-302 |
| 3.2 Admin Query Panel | REQ-302, REQ-303, REQ-304 |
| 3.3 Admin Ingest/Health/Admin UIs | REQ-305 – REQ-317 |
| **Phase 4: User Console UI** | |
| 4.1 User Shell + Sidebar | REQ-201, REQ-202, REQ-203 |
| 4.2 Chat Thread + Streaming | REQ-204, REQ-205, REQ-206 |
| 4.3 Citations + Input Bar | REQ-207, REQ-208, REQ-209, REQ-210 |
| 4.4 Settings + Themes | REQ-211, REQ-212, REQ-904 |
| 4.5 Responsive Layout | REQ-213, REQ-901 |
| **Phase 5: Conversation Management** | |
| 5.1 Conversation Pane | REQ-401, REQ-402, REQ-403 |
| 5.2 Cross-Console Continuity | REQ-404 |
| **Phase 6: Parity and Polish** | |
| 6.1 3-Way Parity Verification | REQ-105, REQ-106 |
| 6.2 Change Parity Process | REQ-111 |
| 6.3 Keyboard Shortcuts | REQ-902, REQ-905 |

---

# Part B: Code Appendix

## B.1: Dual Console Route Factory

This snippet shows the dual-console router factory that serves both the User Console and Admin Console from the same router, sharing API endpoints.

**Tasks:** Task 1.1
**Requirements:** REQ-101, REQ-102

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


USER_CONSOLE_STATIC_DIR = Path(__file__).parent / "static" / "user"
ADMIN_CONSOLE_STATIC_DIR = Path(__file__).parent / "static" / "admin"
SHARED_STATIC_DIR = Path(__file__).parent / "static" / "shared"


def create_console_router(
    *,
    get_workflow_client: Callable,
    logger: Any,
    enforce_rate_limit: Callable,
    acquire_request_slot: Callable,
    release_request_slot: Callable,
    console_ok: Callable,
    console_err: Callable,
    rbac_guard: Callable,
):
    """Build the dual-console router with injected dependencies.

    Serves two independent UIs from one router:
      - User Console at GET /console (modern chat interface)
      - Admin Console at GET /console/admin (tabbed debug/ops interface)

    All API endpoints are shared under /console/* and use the same
    envelope format and auth middleware.
    """
    router = create_api_router(prefix="/console", tags=["console"])

    # ── User Console entry point ──

    @router.get("")
    async def user_console_page():
        """Serve the User Console HTML entry point."""
        html_path = USER_CONSOLE_STATIC_DIR / "index.html"
        return file_response(html_path, media_type="text/html")

    # ── Admin Console entry point ──

    @router.get("/admin")
    async def admin_console_page():
        """Serve the Admin Console HTML entry point."""
        html_path = ADMIN_CONSOLE_STATIC_DIR / "index.html"
        return file_response(html_path, media_type="text/html")

    # ── Static asset routes (per-console and shared) ──

    @router.get("/static/user/{asset_path:path}")
    async def user_console_static(asset_path: str):
        """Serve User Console static assets."""
        full_path = USER_CONSOLE_STATIC_DIR / asset_path
        if not full_path.exists() or not full_path.is_file():
            raise not_found_error(f"Asset not found: {asset_path}")
        return file_response(full_path)

    @router.get("/static/admin/{asset_path:path}")
    async def admin_console_static(asset_path: str):
        """Serve Admin Console static assets."""
        full_path = ADMIN_CONSOLE_STATIC_DIR / asset_path
        if not full_path.exists() or not full_path.is_file():
            raise not_found_error(f"Asset not found: {asset_path}")
        return file_response(full_path)

    @router.get("/static/shared/{asset_path:path}")
    async def shared_console_static(asset_path: str):
        """Serve shared static assets (CSS variables, common JS)."""
        full_path = SHARED_STATIC_DIR / asset_path
        if not full_path.exists() or not full_path.is_file():
            raise not_found_error(f"Asset not found: {asset_path}")
        return file_response(full_path)

    # ── Shared API endpoints ──

    @router.get("/health")
    async def console_health(request):
        health = await aggregate_health(get_workflow_client)
        return console_ok(request, health)

    @router.get("/commands")
    async def console_commands(mode: str = "query", surface: str = "all"):
        from src.platform.command_catalog import get_commands
        commands = get_commands(mode, surface=surface)
        return [{"name": c.name, "description": c.description} for c in commands]

    # ── Admin-only endpoints (RBAC-gated) ──

    @router.get("/admin/keys")
    async def admin_list_keys(request):
        rbac_guard(request, role="admin")
        keys = await list_api_keys()
        return console_ok(request, {"keys": keys})

    return router
```

**Key design decisions:**
- Single router factory produces both console entry points, avoiding duplication.
- Static assets are separated into per-console and shared directories for clear ownership.
- Admin endpoints are RBAC-gated at the handler level, not just via frontend visibility.
- The `surface` parameter on `/commands` lets each console request its relevant command subset.

---

## B.2: Shared Slash-Command Catalog

This snippet shows the shared command catalog module consumed by CLI, User Console, and Admin Console.

**Tasks:** Task 2.1
**Requirements:** REQ-107, REQ-108, REQ-207, REQ-208

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Surface = Literal["cli", "user", "admin", "all"]


@dataclass(frozen=True)
class CommandEntry:
    name: str
    description: str
    mode: Literal["query", "ingest", "both"]
    surfaces: frozenset[Surface] = field(default_factory=lambda: frozenset({"all"}))
    hidden: bool = False


COMMAND_CATALOG: list[CommandEntry] = [
    CommandEntry("/help", "Show available commands", "both"),
    CommandEntry("/sources", "List available source documents", "query"),
    CommandEntry("/history", "Show conversation history", "query"),
    CommandEntry("/reset", "Reset conversation context", "query"),
    CommandEntry("/compact", "Compact conversation memory", "query"),
    CommandEntry("/status", "Show ingestion pipeline status", "ingest"),
    CommandEntry("/health", "Show system health summary", "both"),
    CommandEntry("/clear", "Clear the current output", "both"),
    CommandEntry("/debug", "Toggle debug output", "query",
                 surfaces=frozenset({"admin", "cli"})),
    CommandEntry("/theme", "Switch color theme", "both",
                 surfaces=frozenset({"user", "admin"})),
]


def get_commands(
    mode: str,
    *,
    surface: str = "all",
) -> list[CommandEntry]:
    """Return commands available for the given mode and surface.

    Args:
        mode: Filter by command mode ("query", "ingest", or "both").
        surface: Filter by surface ("cli", "user", "admin", or "all").
                 "all" returns commands available on every surface.
    """
    return [
        c for c in COMMAND_CATALOG
        if not c.hidden
        and c.mode in (mode, "both")
        and ("all" in c.surfaces or surface in c.surfaces or surface == "all")
    ]
```

**Key design decisions:**
- `CommandEntry` now includes `surfaces` to scope commands per interface.
- The catalog is the single source of truth; CLI, User Console, and Admin Console all call `get_commands()`.
- `/debug` is scoped to admin and CLI only; `/theme` is scoped to console UIs only.
- Hidden commands support debug/maintenance commands that are interface-specific.

---

## B.3: User Console Chat Component

This snippet shows the User Console chat thread with message bubbles, streaming token renderer, and citation cards.

**Tasks:** Task 4.2, Task 4.3
**Requirements:** REQ-204, REQ-205, REQ-206, REQ-209, REQ-210

```typescript
// ── Types ──

type MessageRole = "user" | "assistant";

type CitationSource = {
  filename: string;
  section: string;
  score: number;
  chunkText: string;
};

type ChatMessage = {
  id: string;
  role: MessageRole;
  content: string;
  citations?: CitationSource[];
  timestampMs: number;
  isStreaming?: boolean;
};

// ── Streaming Token Renderer ──

class StreamingRenderer {
  private targetElement: HTMLElement;
  private buffer: string = "";
  private animationFrameId: number | null = null;

  constructor(targetElement: HTMLElement) {
    this.targetElement = targetElement;
  }

  appendToken(token: string): void {
    this.buffer += token;
    if (this.animationFrameId === null) {
      this.animationFrameId = requestAnimationFrame(() => this.flush());
    }
  }

  private flush(): void {
    this.targetElement.textContent += this.buffer;
    this.buffer = "";
    this.animationFrameId = null;
    this.autoScroll();
  }

  private autoScroll(): void {
    const container = this.targetElement.closest(".chat-thread");
    if (!container) return;
    const isNearBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight < 80;
    if (isNearBottom) {
      container.scrollTop = container.scrollHeight;
    }
  }

  finalize(): void {
    if (this.buffer) this.flush();
  }
}

// ── Chat Thread Component ──

class ChatThread {
  private messages: ChatMessage[] = [];
  private container: HTMLElement;
  private activeRenderer: StreamingRenderer | null = null;

  constructor(container: HTMLElement) {
    this.container = container;
  }

  addUserMessage(content: string): ChatMessage {
    const msg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content,
      timestampMs: Date.now(),
    };
    this.messages.push(msg);
    this.renderBubble(msg);
    return msg;
  }

  startAssistantStream(): ChatMessage {
    const msg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "assistant",
      content: "",
      timestampMs: Date.now(),
      isStreaming: true,
    };
    this.messages.push(msg);
    const bubble = this.renderBubble(msg);
    const contentEl = bubble.querySelector(".bubble-content") as HTMLElement;
    this.activeRenderer = new StreamingRenderer(contentEl);
    return msg;
  }

  appendStreamToken(token: string): void {
    if (!this.activeRenderer) return;
    this.activeRenderer.appendToken(token);
    const activeMsg = this.messages[this.messages.length - 1];
    activeMsg.content += token;
  }

  finalizeStream(citations?: CitationSource[]): void {
    if (!this.activeRenderer) return;
    this.activeRenderer.finalize();
    this.activeRenderer = null;
    const activeMsg = this.messages[this.messages.length - 1];
    activeMsg.isStreaming = false;
    activeMsg.citations = citations;
    if (citations?.length) {
      this.renderCitations(activeMsg.id, citations);
    }
  }

  private renderBubble(msg: ChatMessage): HTMLElement {
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble chat-bubble--${msg.role}`;
    bubble.dataset.messageId = msg.id;
    bubble.innerHTML = `
      <div class="bubble-content">${msg.content}</div>
      <div class="bubble-meta">
        <time>${new Date(msg.timestampMs).toLocaleTimeString()}</time>
        <button class="copy-btn" title="Copy to clipboard">Copy</button>
      </div>
    `;
    bubble.querySelector(".copy-btn")?.addEventListener("click", () => {
      navigator.clipboard.writeText(msg.content);
    });
    this.container.appendChild(bubble);
    this.container.scrollTop = this.container.scrollHeight;
    return bubble;
  }

  private renderCitations(messageId: string, citations: CitationSource[]): void {
    const bubble = this.container.querySelector(
      `[data-message-id="${messageId}"]`
    );
    if (!bubble) return;
    const citationContainer = document.createElement("div");
    citationContainer.className = "citation-cards";
    for (const cite of citations) {
      const card = document.createElement("div");
      card.className = "citation-card";
      card.innerHTML = `
        <div class="citation-header">
          <span class="citation-filename">${cite.filename}</span>
          <span class="citation-section">${cite.section}</span>
          <span class="citation-score">${(cite.score * 100).toFixed(0)}%</span>
        </div>
        <div class="citation-detail hidden">
          <pre class="citation-chunk">${cite.chunkText}</pre>
        </div>
      `;
      card.querySelector(".citation-header")?.addEventListener("click", () => {
        card.querySelector(".citation-detail")?.classList.toggle("hidden");
      });
      citationContainer.appendChild(card);
    }
    bubble.appendChild(citationContainer);
  }
}
```

**Key design decisions:**
- Streaming uses `requestAnimationFrame` batching to avoid layout thrashing from per-token DOM updates.
- Auto-scroll respects manual scroll position (only scrolls if user is near bottom).
- Citations render as expandable cards below the assistant message, not inline.
- Copy-to-clipboard is per-message for easy sharing.

---

## B.4: User Console Sidebar and Conversation List

This snippet shows the User Console sidebar component with conversation list and management actions.

**Tasks:** Task 4.1, Task 5.1
**Requirements:** REQ-202, REQ-203, REQ-401, REQ-402, REQ-403

```typescript
type ConversationMeta = {
  conversationId: string;
  title: string;
  messageCount: number;
  updatedAtMs: number;
};

type SidebarState = {
  conversations: ConversationMeta[];
  activeConversationId: string | null;
  isCollapsed: boolean;
};

class ConsoleSidebar {
  private state: SidebarState = {
    conversations: [],
    activeConversationId: null,
    isCollapsed: false,
  };

  private container: HTMLElement;
  private apiBase: string;
  private onConversationSelect: (id: string, history: any[]) => void;

  constructor(
    container: HTMLElement,
    apiBase: string,
    onConversationSelect: (id: string, history: any[]) => void
  ) {
    this.container = container;
    this.apiBase = apiBase;
    this.onConversationSelect = onConversationSelect;
    this.render();
  }

  async loadConversations(): Promise<void> {
    const resp = await fetch(`${this.apiBase}/console/conversations`);
    const data = await resp.json();
    this.state.conversations = data.data?.conversations ?? [];
    this.renderConversationList();
  }

  async createConversation(title?: string): Promise<string> {
    const resp = await fetch(`${this.apiBase}/console/conversations/new`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: title ?? "New conversation" }),
    });
    const data = await resp.json();
    const id = data.data?.conversation_id;
    this.state.activeConversationId = id;
    await this.loadConversations();
    return id;
  }

  async selectConversation(id: string): Promise<void> {
    this.state.activeConversationId = id;
    const resp = await fetch(
      `${this.apiBase}/console/conversations/${id}/history`
    );
    const data = await resp.json();
    const turns = data.data?.turns ?? [];
    this.onConversationSelect(id, turns);
    this.renderConversationList();
  }

  toggle(): void {
    this.state.isCollapsed = !this.state.isCollapsed;
    this.container.classList.toggle("sidebar--collapsed", this.state.isCollapsed);
  }

  getQueryParams(): { conversation_id?: string; memory_enabled: boolean } {
    return {
      conversation_id: this.state.activeConversationId ?? undefined,
      memory_enabled: this.state.activeConversationId !== null,
    };
  }

  private render(): void {
    this.container.innerHTML = `
      <div class="sidebar-header">
        <button class="sidebar-toggle" title="Toggle sidebar">&#9776;</button>
        <button class="new-chat-btn" title="New conversation (Ctrl+N)">+ New Chat</button>
      </div>
      <div class="conversation-list"></div>
      <div class="sidebar-footer">
        <button class="settings-btn" title="Settings">Settings</button>
      </div>
    `;
    this.container
      .querySelector(".sidebar-toggle")
      ?.addEventListener("click", () => this.toggle());
    this.container
      .querySelector(".new-chat-btn")
      ?.addEventListener("click", () => this.createConversation());
  }

  private renderConversationList(): void {
    const listEl = this.container.querySelector(".conversation-list");
    if (!listEl) return;

    const sorted = [...this.state.conversations].sort(
      (a, b) => b.updatedAtMs - a.updatedAtMs
    );

    listEl.innerHTML = sorted
      .map(
        (conv) => `
      <div class="conversation-item ${
        conv.conversationId === this.state.activeConversationId
          ? "conversation-item--active"
          : ""
      }" data-id="${conv.conversationId}">
        <div class="conversation-title">${conv.title}</div>
        <div class="conversation-meta">
          ${conv.messageCount} messages &middot;
          ${new Date(conv.updatedAtMs).toLocaleDateString()}
        </div>
      </div>
    `
      )
      .join("");

    listEl.querySelectorAll(".conversation-item").forEach((item) => {
      item.addEventListener("click", () => {
        const id = (item as HTMLElement).dataset.id;
        if (id) this.selectConversation(id);
      });
    });
  }
}
```

**Key design decisions:**
- Sidebar state is local to the component; conversation data comes from the shared API.
- `getQueryParams()` provides a clean interface for the chat thread to include conversation context.
- Sorted by most-recently-updated for quick access to active conversations.
- Toggle and responsive collapse are handled via CSS class toggling.

---

## B.5: Parity Test Helper

This snippet shows the 3-way parity test helper that verifies feature coverage across CLI, User Console, and Admin Console.

**Tasks:** Task 6.1, Task 6.2
**Requirements:** REQ-105, REQ-106, REQ-111

```python
from __future__ import annotations

import pytest


def _cli_commands(mode: str) -> set[str]:
    """Collect commands registered in the CLI for the given mode."""
    from src.platform.command_catalog import get_commands
    return {c.name for c in get_commands(mode, surface="cli")}


def _console_commands(mode: str, surface: str, client) -> set[str]:
    """Fetch commands from the console API for the given mode and surface."""
    resp = client.get(f"/console/commands?mode={mode}&surface={surface}")
    assert resp.status_code == 200
    return {c["name"] for c in resp.json()}


class TestThreeWayParity:
    """Verify that CLI, User Console, and Admin Console expose
    the same command set (modulo documented interface-specific commands)."""

    # Commands that are intentionally scoped to specific surfaces.
    # Each entry must have a documented justification.
    KNOWN_SURFACE_SPECIFIC = {
        "/debug": {"admin", "cli"},     # Debug output not relevant in user chat
        "/theme": {"user", "admin"},    # Theme switching is UI-only
    }

    @pytest.fixture
    def client(self, app):
        """Test client for the console API."""
        return app.test_client()

    @pytest.mark.parametrize("mode", ["query", "ingest"])
    def test_command_parity(self, client, mode: str):
        cli_cmds = _cli_commands(mode)
        user_cmds = _console_commands(mode, "user", client)
        admin_cmds = _console_commands(mode, "admin", client)

        # Build the universal set (commands that should appear everywhere)
        from src.platform.command_catalog import get_commands
        all_cmds = {c.name for c in get_commands(mode, surface="all")}
        universal = all_cmds - set(self.KNOWN_SURFACE_SPECIFIC.keys())

        # Every universal command must appear in all three surfaces
        for cmd in universal:
            assert cmd in cli_cmds, f"{cmd} missing from CLI ({mode})"
            assert cmd in user_cmds, f"{cmd} missing from User Console ({mode})"
            assert cmd in admin_cmds, f"{cmd} missing from Admin Console ({mode})"

        # Surface-specific commands must appear only where expected
        for cmd, expected_surfaces in self.KNOWN_SURFACE_SPECIFIC.items():
            if cmd not in all_cmds:
                continue  # Command not in this mode
            if "cli" in expected_surfaces:
                assert cmd in cli_cmds, f"{cmd} expected in CLI"
            else:
                assert cmd not in cli_cmds, f"{cmd} should not be in CLI"
            if "user" in expected_surfaces:
                assert cmd in user_cmds, f"{cmd} expected in User Console"
            else:
                assert cmd not in user_cmds, f"{cmd} should not be in User Console"
            if "admin" in expected_surfaces:
                assert cmd in admin_cmds, f"{cmd} expected in Admin Console"
            else:
                assert cmd not in admin_cmds, f"{cmd} should not be in Admin Console"

    def test_query_parameters_parity(self, client):
        """Verify that query parameter schemas match across surfaces."""
        # Both consoles should accept the same query parameters
        # as the CLI query command (minus interface-specific presentation flags)
        from src.platform.query_schemas import QUERY_PARAM_NAMES

        resp = client.get("/console/query/schema")
        assert resp.status_code == 200
        console_params = set(resp.json().get("parameters", {}).keys())

        interface_only = {"stream", "debug"}  # Presentation flags
        shared_params = QUERY_PARAM_NAMES - interface_only

        missing = shared_params - console_params
        assert not missing, f"Console missing query params: {missing}"
```

**Key design decisions:**
- `KNOWN_SURFACE_SPECIFIC` acts as an explicit allowlist for parity exceptions.
- Any new surface-specific command must be added here with justification, making parity gaps visible in code review.
- Both command parity and parameter parity are tested to catch subtle divergences.
- The test uses the same `get_commands()` catalog function that production code uses, ensuring the test is not testing a mock.
