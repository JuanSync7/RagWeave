# Web Console Specification

**AION Knowledge Management Platform**
Version: 2.0 | Status: Implemented Baseline | Domain: Web Console

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-13 | AI Assistant | Initial specification reverse-engineered from implemented web console |
| 2.0 | 2026-03-13 | AI Assistant | Dual-console architecture: User Console (`/console`) and Admin Console (`/console/admin`). Reorganized requirement sections. Added Change Parity principle. Expanded from 30 to 48 requirements. |

> **Document intent:** This is a normative requirements/specification document for the web console UI.
> For the design document, see `WEB_CONSOLE_DESIGN.md`.
> For the implementation plan, see `WEB_CONSOLE_IMPLEMENTATION.md`.
> For the API server layer, see `SERVER_API_SPEC.md`. For as-built behavior, see `server/console/README.md`.

---

## 1. Scope & Definitions

### 1.1 Problem Statement

The RAG system serves two distinct audiences through its browser interface: (1) end users who need a clean, modern chat experience for asking questions and receiving answers, and (2) operators/developers who need full diagnostic controls, ingestion management, health monitoring, and administrative actions. A single console cannot serve both audiences well — end users are overwhelmed by debug output, and operators need controls that would clutter a chat UI. The dual-console architecture provides each audience with a purpose-built interface backed by the same infrastructure.

### 1.2 Scope

This specification defines requirements for the **dual web console** of the RAG system. The boundary is:

- **Entry point:** A user or operator opens either console URL in a browser.
- **Exit point:** The user completes a query workflow with visible feedback, or the operator completes an operational workflow (query with diagnostics, ingestion, health check, admin action) with traceable results.

Everything between these points is in scope, including shared infrastructure (serving, auth, envelope, slash commands, presets), User Console layout and chat UI, Admin Console tabbed layout and panels, and conversation management shared between both consoles.

### 1.3 Terminology

| Term | Definition |
|------|-----------|
| **User Console** | The browser-based chat interface served at `/console`, designed for end users seeking answers via a modern conversational UI |
| **Admin Console** | The browser-based operator interface served at `/console/admin`, designed for operators and developers requiring full diagnostic and administrative capabilities |
| **Console** | Collective term for both User Console and Admin Console |
| **Mode Tab** | A top-level UI section in the Admin Console (Query, Ingestion, Health, Admin) that groups related actions |
| **Slash Command** | A `/command` input pattern that triggers a predefined action (e.g., `/help`, `/sources`, `/reset`), available in both consoles |
| **Preset** | A saved configuration of query or ingestion options (e.g., "fast", "quality", "debug") that can be applied with one click or selected from a dropdown |
| **Console Envelope** | The standardized response wrapper for console endpoints, containing `ok`, `request_id`, `data`, and `error` fields |
| **Streaming Token** | An incremental text fragment delivered via SSE during answer generation |
| **Conversation Pane** | The sidebar UI component in either console that displays conversation list and enables multi-turn chat |
| **Message Bubble** | A styled container in the User Console chat thread that displays a single message, aligned right for user messages and left for assistant messages |
| **Source Citation Card** | A collapsible UI element below an assistant message in the User Console showing filename, section, and relevance badge for a retrieved source |

### 1.4 Requirement Priority Levels

This document uses RFC 2119 language:

- **MUST** — Absolute requirement.
- **SHOULD** — Recommended.
- **MAY** — Optional.

### 1.5 Requirement Format

> **REQ-xxx** | Priority: MUST/SHOULD/MAY
> **Description:** What the system shall do.
> **Rationale:** Why this requirement exists.
> **Acceptance Criteria:** How to verify conformance.

| Section | ID Range | Component |
|---------|----------|-----------|
| 3 | REQ-1xx | Shared Infrastructure |
| 4 | REQ-2xx | User Console |
| 5 | REQ-3xx | Admin Console |
| 6 | REQ-4xx | Conversation Management |
| 7 | REQ-9xx | Non-Functional Requirements |

### 1.6 Assumptions & Constraints

| ID | Assumption / Constraint | Impact if Violated |
|----|------------------------|--------------------|
| A-1 | Both consoles are served as static assets by the API server | Consoles require a separate hosting solution if decoupled |
| A-2 | Both consoles communicate with the API server via the same origin (no additional CORS setup) | Cross-origin deployment requires explicit CORS configuration |
| A-3 | Console endpoints use the standard console envelope for all responses | Mixed response formats require per-endpoint error handling in the frontend |
| A-4 | The shared slash-command catalog is maintained server-side and served to both consoles | Command duplication between CLI and consoles leads to drift |
| A-5 | Both consoles share the same conversation backend and API routes | Conversation state is fragmented if backends diverge |

### 1.7 Design Principles

| Principle | Description |
|-----------|-------------|
| **Audience Separation** | The User Console is designed for end users seeking answers; the Admin Console is designed for operators and developers diagnosing and managing the system |
| **CLI/UI Parity** | Every user-facing capability available in the CLI MUST be available in both consoles, and vice versa |
| **Change Parity** | Whenever a new feature is implemented, it MUST be reflected in BOTH the User Console and the Admin Console (and the CLI). This ensures no console falls behind. Interface-specific features MUST be explicitly documented as intentionally scoped to one surface. |
| **Backend-Driven Behavior** | Both consoles render and dispatch; all business logic and command semantics live server-side |
| **Progressive Disclosure** | Advanced options are hidden by default and revealed on demand (Admin Console surfaces more by default than User Console) |

### 1.8 Out of Scope

- Offline mode (both consoles require a live API connection)
- API endpoint schemas and error handling (see `SERVER_API_SPEC.md`)
- Native mobile applications (the User Console is responsive for mobile browsers; native apps are out of scope)

---

## 2. System Overview

### 2.1 Architecture Diagram

```
User (Browser)                    Operator (Browser)
    |                                  |
    v                                  v
+---------------------+     +-------------------------+
| [1a] USER CONSOLE   |     | [1b] ADMIN CONSOLE      |
|     /console         |     |     /console/admin       |
|                     |     |                         |
|  Sidebar | Chat     |     |  Mode tabs: Query,      |
|  thread  | Input    |     |  Ingestion, Health,     |
|  bar     |          |     |  Admin                  |
+----------+----------+     +------------+------------+
           |                             |
           +----------+  +--------------+
                      |  |
                      v  v
       +-------------------------------+
       | [2] SHARED CONSOLE BACKEND    |
       |     /console/* endpoints      |
       |     Slash-command dispatch    |
       |     Preset management        |
       |     Conversation management  |
       |     Auth & envelope          |
       |     Static asset serving     |
       +-------------------------------+
                      |
                      v
       +-------------------------------+
       | [3] CORE API                  |
       |     /query, /admin, /health,  |
       |     /conversations/*          |
       +-------------------------------+
```

### 2.2 Data Flow Summary

| Surface | Console Endpoint | Core API Endpoint | Data |
|---------|-----------------|-------------------|------|
| User Console: Chat | `POST /console/query` | `POST /query` (stream) | Query text, preset → streaming tokens + citations |
| Admin Console: Query | `POST /console/query` | `POST /query` (stream) | Query text, full options → streaming tokens + results + stage timings + chunk scores |
| Admin Console: Ingestion | `POST /console/ingest` | Internal dispatch | Target path, options → progress/status |
| Admin Console: Health | `GET /console/health` | `GET /health` + probes | → aggregated health status |
| Admin Console: Admin | `POST /console/admin/*` | `POST /admin/*` | Key/quota operations → confirmation |
| Both: Commands | `POST /console/command` | N/A (server-side dispatch) | Command + args → action response |
| Both: Conversations | `GET/POST /console/conversations/*` | `GET/POST /conversations/*` | Conversation CRUD + history |
| Both: Presets | `GET /console/presets` | N/A (server-side catalog) | Preset list + custom preset CRUD |

---

## 3. Shared Infrastructure

> **REQ-101** | Priority: MUST
> **Description:** Both consoles MUST be served as static assets by the API server. The User Console MUST be served at `/console`. The Admin Console MUST be served at `/console/admin`. All console HTML, JavaScript, and CSS MUST be served from the same origin as the API.
> **Rationale:** Same-origin serving eliminates CORS complexity and enables cookie-based authentication. Well-known URL paths provide predictable access.
> **Acceptance Criteria:** Navigating to `/console` loads the User Console. Navigating to `/console/admin` loads the Admin Console. All assets are served from the API server origin.

> **REQ-102** | Priority: MUST
> **Description:** All console endpoints MUST use the standardized console envelope format containing `ok`, `request_id`, `data`, and `error` fields. Both consoles MUST consume the same envelope format.
> **Rationale:** A standardized envelope enables shared error handling and response parsing across both consoles.
> **Acceptance Criteria:** Every `/console/*` endpoint returns a response in the envelope format. Both consoles parse and render errors using the same envelope structure.

> **REQ-103** | Priority: MUST
> **Description:** Both consoles MUST support authentication via the same mechanism (API key or token). The Admin Console MUST enforce admin-role authentication for admin-only operations. The User Console MUST support user-level authentication.
> **Rationale:** Shared authentication ensures users can transition between consoles without re-authenticating while maintaining role-based access boundaries.
> **Acceptance Criteria:** A valid user token works in both consoles. Admin operations in the Admin Console require admin role. Non-admin users accessing admin endpoints receive 403.

> **REQ-104** | Priority: MUST
> **Description:** Both consoles MUST support a slash-command system where typing `/` in an input field shows available commands with descriptions. Commands MUST be served from a shared server-side catalog.
> **Rationale:** Slash commands provide a discoverable, consistent command surface shared between CLI and both consoles. Server-side catalog ensures consistency.
> **Acceptance Criteria:** Typing `/` in either console shows a list of available commands with descriptions. Selecting a command triggers the associated action. The command list is fetched from the server.

> **REQ-105** | Priority: MUST
> **Description:** The slash-command catalog MUST be shared between the CLI, User Console, and Admin Console. Adding a command to the catalog MUST make it available in all three interfaces.
> **Rationale:** Separate command implementations for each interface create drift. A shared catalog enforces parity.
> **Acceptance Criteria:** A command added to the server-side catalog appears in CLI `/help` output, User Console command picker, and Admin Console command picker.

> **REQ-106** | Priority: MUST
> **Description:** Command execution from either console MUST be dispatched through a unified server-side endpoint that receives the command name, arguments, source console (user/admin), and current UI state, and returns a normalized response with intent, action, data, and message.
> **Rationale:** Centralizing command dispatch on the server keeps both frontends as thin renderers and prevents business logic duplication.
> **Acceptance Criteria:** All console commands are dispatched through a single endpoint. The response includes structured action instructions that the frontend renders. The `source` parameter distinguishes User Console from Admin Console.

> **REQ-107** | Priority: MUST
> **Description:** Both consoles MUST support named presets for query options. Built-in presets (e.g., "fast", "quality", "debug") MUST be immutable. Users MUST be able to save, load, and delete custom presets persisted in browser local storage.
> **Rationale:** Presets eliminate repetitive option configuration and enable quick switching between common usage patterns.
> **Acceptance Criteria:** Built-in presets are available in both consoles and cannot be deleted. Custom presets are saved to and loaded from local storage. Applying a preset populates the relevant form/selector with preset values.

> **REQ-108** | Priority: MUST
> **Description:** Every user-facing setting, command, and operational state available in the CLI MUST be available in both web consoles, and vice versa, in the same change set.
> **Rationale:** Users should not need to switch interfaces to access features. Interface-specific features create confusion and support burden.
> **Acceptance Criteria:** A feature checklist comparing CLI, User Console, and Admin Console capabilities shows 100% parity for user-facing features. Hidden maintenance/debug commands may be interface-specific but must be documented as such.

> **REQ-109** | Priority: MUST
> **Description:** Shared interaction contracts (request/response schemas, command metadata, configuration options) MUST be defined in a single source of truth consumed by CLI, User Console, and Admin Console adapters.
> **Rationale:** Duplicate schema definitions across interfaces drift over time. A single source of truth enforces consistency.
> **Acceptance Criteria:** All three interfaces import from the same schema/metadata modules. Adding a new query parameter to the shared schema makes it available in all interfaces without separate implementation.

> **REQ-110** | Priority: MUST
> **Description:** Whenever a new feature is implemented for any console or the CLI, it MUST be reflected in BOTH the User Console and the Admin Console (and the CLI) within the same change set. Features intentionally scoped to a single surface MUST be explicitly documented with rationale in the feature's design record.
> **Rationale:** Without Change Parity enforcement, one console inevitably falls behind, creating a fragmented user experience and increasing maintenance burden.
> **Acceptance Criteria:** Pull requests that add user-facing features include implementation or explicit deferral documentation for all three surfaces. A parity checklist is part of the change review process.

> **REQ-111** | Priority: SHOULD
> **Description:** Both consoles SHOULD display reusable notification and loading-state components for feedback during async operations.
> **Rationale:** Silent async operations confuse users who cannot tell if their action was submitted, in progress, or failed.
> **Acceptance Criteria:** Submitting a query shows a loading indicator. Completion shows a success notification. Errors show an error notification with the error code and message.

---

## 4. User Console

> **REQ-201** | Priority: MUST
> **Description:** The User Console MUST provide a modern chat-style layout with three primary zones: a sidebar (left), a main chat thread area (center), and an input bar (bottom).
> **Rationale:** Chat-style interfaces are the established paradigm for conversational AI (Claude, ChatGPT). Users expect this layout for natural interaction.
> **Acceptance Criteria:** The User Console renders with a left sidebar, center chat area, and bottom input bar. The layout is visually clean and modern with no exposed debug or diagnostic elements.

> **REQ-202** | Priority: MUST
> **Description:** The User Console sidebar MUST contain: a brand header with a collapse toggle button (inside the sidebar itself), a "New Chat" button displaying a `+` icon, a primary navigation rail with at minimum four items — **Conversations**, **Projects**, **Search**, and **Customize** — each represented by an icon and a text label. Each navigation item MUST switch the sidebar content area to its corresponding panel. The Settings action MUST appear in the sidebar footer. Each conversation entry in the Conversations panel MUST show the conversation title and a timestamp.
> **Rationale:** A structured navigation rail makes the sidebar a first-class feature surface rather than just a conversation list. Dedicated Project, Search, and Customize sections provide discoverability for features that would otherwise require navigating to separate panels.
> **Acceptance Criteria:** All four nav items are visible and clickable. Clicking each switches the sidebar content panel accordingly. Clicking "New Chat" creates a new conversation. The settings footer opens the settings panel. Icon and label are both visible in expanded state; only the icon is visible in collapsed (icon-rail) state.

> **REQ-203** | Priority: MUST
> **Description:** The User Console main area MUST render a chat thread with message bubbles. User messages MUST appear as right-aligned bubbles. Assistant messages MUST appear as left-aligned bubbles. Each bubble MUST display the message text and a timestamp.
> **Rationale:** Directional message bubbles are the universal visual language for chat interfaces and provide clear attribution.
> **Acceptance Criteria:** User messages render right-aligned. Assistant messages render left-aligned. Both include timestamps. The chat thread auto-scrolls to the most recent message.

> **REQ-204** | Priority: MUST
> **Description:** The User Console input bar MUST provide a text input field with a send button. The input bar MUST also include a preset selector (dropdown or chip) for selecting query presets. The input bar MAY include an optional source filter chip for restricting retrieval to specific document sources.
> **Rationale:** The input bar is the primary interaction point. Preset selection and source filtering must be accessible without navigating away from the input.
> **Acceptance Criteria:** Text can be entered and submitted via the send button or Enter key. The preset selector shows available presets. Selecting a preset applies its configuration to the next query. The source filter chip, if present, restricts the query scope.

> **REQ-205** | Priority: MUST
> **Description:** The User Console MUST display a loading indicator (typing dots animation or spinner) in the assistant bubble area while retrieval and generation are in progress.
> **Rationale:** Users need visual feedback that the system is processing their query to avoid confusion and duplicate submissions.
> **Acceptance Criteria:** After submitting a query, a typing indicator appears in the position where the assistant response will render. The indicator is replaced by the streaming response once tokens begin arriving.

> **REQ-206** | Priority: MUST
> **Description:** The User Console MUST support streaming token display where generation output appears incrementally within the assistant message bubble as SSE events arrive.
> **Rationale:** Streaming display provides immediate feedback and significantly reduces perceived latency, matching the experience of modern AI chat interfaces.
> **Acceptance Criteria:** Generation tokens appear in the assistant bubble as they arrive. The full answer is assembled after streaming completes. Streaming errors display an error message within the bubble.

> **REQ-207** | Priority: MUST
> **Description:** The User Console MUST display source citations as collapsible cards below each assistant answer. Each card MUST show the source filename, section name (if available), and a relevance badge (e.g., "High", "Medium"). Cards MUST be collapsed by default.
> **Rationale:** Users need transparency about answer sources without the visual noise of full chunk displays. Collapsible cards balance transparency with clean UX.
> **Acceptance Criteria:** After an answer completes, source citation cards appear below the assistant bubble. Each card shows filename, section, and relevance badge. Cards expand on click to show a text preview. Cards are collapsed by default.

> **REQ-208** | Priority: MUST
> **Description:** The User Console MUST support slash commands from the input bar. At minimum, the following commands MUST be available: `/help` (show available commands), `/new-chat` (start a new conversation), `/history` (show conversation history), `/compact` (compact current conversation).
> **Rationale:** Slash commands provide keyboard-driven power-user access to common actions without requiring mouse navigation.
> **Acceptance Criteria:** Typing `/` in the input bar shows a command autocomplete menu. Each listed command is functional. The listed commands include at minimum `/help`, `/new-chat`, `/history`, and `/compact`.

> **REQ-209** | Priority: MUST
> **Description:** The User Console settings panel (accessed from the sidebar gear icon) MUST provide controls for: API endpoint URL, authentication token input, and theme toggle (light/dark mode).
> **Rationale:** Users need to configure their connection and personalize the interface without editing files or using developer tools.
> **Acceptance Criteria:** The settings panel opens from the sidebar gear icon. API endpoint and auth token fields are present and functional. Theme toggle switches between light and dark mode. Settings persist across browser sessions (local storage).

> **REQ-210** | Priority: MUST
> **Description:** The User Console MUST NOT display raw stage timing breakdowns, rerank scores, debug output, chunk-level relevance scores, or any diagnostic information intended for operators. The interface MUST remain clean and user-focused.
> **Rationale:** Debug output confuses end users and clutters the chat interface. Diagnostic information belongs exclusively in the Admin Console.
> **Acceptance Criteria:** No stage timings, raw scores, or debug logs are visible anywhere in the User Console. The query response rendering includes only the answer text and source citation cards.

> **REQ-211** | Priority: MUST
> **Description:** The User Console MUST be responsive and render correctly on desktop, tablet, and mobile screen sizes. The sidebar MUST collapse to a hamburger menu on narrow viewports.
> **Rationale:** End users may access the console from various devices. A responsive layout ensures usability across screen sizes.
> **Acceptance Criteria:** The layout adapts to viewport widths from 320px to 2560px. The sidebar collapses to a hamburger menu below 768px. Chat bubbles and input bar remain usable on mobile viewports.

> **REQ-212** | Priority: SHOULD
> **Description:** The User Console SHOULD support a source document viewer that displays the full content of a retrieved source document when a citation card is expanded and a "View Full Document" link is clicked.
> **Rationale:** Seeing the full document context around a cited source helps users verify answer grounding without leaving the console.
> **Acceptance Criteria:** Expanded citation cards include a "View Full Document" link. Clicking the link opens a modal or side panel showing the full document content with the relevant section highlighted.

> **REQ-213** | Priority: SHOULD
> **Description:** The User Console SHOULD display a status bar or subtle indicator showing the current connection status (connected/disconnected) and the active API endpoint.
> **Rationale:** Users need awareness of connection state to understand when queries may fail, without the visual weight of a full operator status bar.
> **Acceptance Criteria:** A connection indicator is visible (e.g., a small dot or subtle text). Disconnection is reflected within 5 seconds. The active endpoint is visible on hover or in a tooltip.

> **REQ-214** | Priority: SHOULD
> **Description:** The User Console SHOULD display a context window usage indicator that shows the estimated percentage of the LLM's context window consumed by the current conversation (system prompt + memory + retrieved chunks + turn history). The indicator MUST update after each completed turn and MUST surface a warning state when usage exceeds 80%.
> **Rationale:** Users have no visibility into context saturation without this indicator. When context usage is high, generation quality silently degrades. An inline indicator allows users to decide when to compact, reduce retrieval depth, or start a new conversation — without requiring them to understand token mechanics. Ties into the token budget tracker subsystem defined in `TOKEN_BUDGET_SPEC.md`.
> **Acceptance Criteria:** After each completed turn, a context usage percentage (e.g., "42% context used") is visible in the chat header or near the input bar. The indicator shows a warning color at ≥80% and a critical color at ≥95%. The percentage is sourced from the `context_usage_pct` field returned by the query endpoint (see `TOKEN_BUDGET_SPEC.md`). Clicking or hovering the indicator shows a breakdown tooltip (memory, chunks, query).

> **REQ-215** | Priority: SHOULD
> **Description:** The User Console input bar SHOULD include a context attachment toolbar with actions for attaching files to the query context, initiating a web search to add retrieved content to context, and selecting previously ingested documents to include. The toolbar MUST be accessible via a clearly labeled attachment/add-context button adjacent to the text input. Each attached item MUST be visible as a removable chip above the input before sending.
> **Rationale:** Modern RAG users need to augment queries with ad-hoc context (uploaded documents, live web content) beyond the static knowledge base. Providing these actions directly in the input bar follows established UX patterns (Perplexity, Claude, ChatGPT file attachment) and eliminates the need to pre-ingest everything. Web search enrichment allows queries to reference current information.
> **Acceptance Criteria:** An attachment button (paperclip or "+" icon) in the input bar opens a context action menu with at minimum: "Upload file", "Browse web", "Add from knowledge base". Each selected item appears as a dismissible chip above the input. The file upload supports common formats (PDF, DOCX, TXT, MD). Attached items are included in the query context payload sent to the backend. Items can be removed before sending.

> **REQ-217** | Priority: MUST
> **Description:** The User Console sidebar MUST support an **icon-rail collapsed state** (≈56px wide) toggled by a collapse button located inside the sidebar header. In the collapsed state: all text labels MUST be hidden, only icons remain visible, the conversation list and panel content MUST be hidden, and hovering any icon MUST display a tooltip showing the item's label. The collapsed state MUST persist across page reloads (local storage). On tablet and mobile viewports, the sidebar MUST continue to behave as a full-width overlay drawer; the icon-rail mode MUST only apply on desktop (>1024px).
> **Rationale:** Icon-rail sidebars are a standard pattern (VS Code, Slack, Notion) that recovers horizontal space without hiding navigation entirely. Tooltips on hover ensure discoverability is not lost in the collapsed state. Internal placement of the collapse toggle (inside the sidebar) is cleaner than an external toggle and allows the button to remain visible when collapsed.
> **Acceptance Criteria:** Clicking the collapse button shrinks the sidebar to the icon rail. Hovering any icon in collapsed state shows a tooltip with the label. Clicking the collapse button again restores the full sidebar. Collapsed state is persisted in local storage. On viewports ≤1024px, icon-rail mode is not triggered; the sidebar uses overlay behavior.

> **REQ-216** | Priority: MUST
> **Description:** The User Console input bar MUST include a visible "/" button that opens the slash-command menu as a structured visual picker, in addition to the existing keyboard-triggered "/" autocomplete. The picker MUST display commands grouped by category with descriptions, and MUST be navigable by keyboard (arrow keys, Enter to execute, Escape to dismiss) and by mouse/touch.
> **Rationale:** Keyboard-triggered "/" autocomplete (REQ-208) requires users to know the feature exists. A visible "/" button provides discoverability for new users and serves as a secondary entry point on touch devices where typing "/" and immediately getting the menu may be unreliable. The structured grouped display (vs. a flat autocomplete list) improves scanability when the command catalog is large.
> **Acceptance Criteria:** A "/" icon button is visible in the input bar toolbar. Clicking/tapping it opens the command picker panel. Commands are grouped by category (e.g., Conversation, Context, Display). Each entry shows command name and description. Keyboard navigation (↑/↓/Enter/Esc) and mouse/touch selection both work. Selecting a command inserts it into the input (or executes immediately for commands with no arguments). The panel is dismissed by Escape, clicking outside, or after execution.

---

## 5. Admin Console

> **REQ-301** | Priority: MUST
> **Description:** The Admin Console MUST provide a single-page application shell with top-level mode tabs for Query, Ingestion, Health, and Admin workflows.
> **Rationale:** Tab-based navigation enables quick switching between operational workflows without page reloads or context loss.
> **Acceptance Criteria:** All four mode tabs are visible and clickable. Switching tabs preserves state within each tab (e.g., query text is not lost when switching to Health and back).

> **REQ-302** | Priority: MUST
> **Description:** The Admin Console MUST display a status bar showing: the current API endpoint, connection status, and the active authentication context (tenant/principal).
> **Rationale:** Operators need constant awareness of which environment they are targeting to prevent accidental actions on the wrong deployment.
> **Acceptance Criteria:** The status bar is always visible. Disconnection from the API is immediately reflected. Tenant/principal context updates when authentication changes.

> **REQ-303** | Priority: MUST
> **Description:** The Admin Console query panel MUST provide an input form for query text and advanced options (source filter, heading filter, alpha, search limit, rerank top-k, fast path, timeout, stage budget overrides).
> **Rationale:** Operators need full control over query parameters to diagnose retrieval behavior and tune results.
> **Acceptance Criteria:** All documented query parameters are available in the form. Advanced options are collapsed by default (progressive disclosure). Input validation prevents invalid submissions.

> **REQ-304** | Priority: MUST
> **Description:** The Admin Console query panel MUST support streaming token display that renders generation output incrementally as SSE events arrive.
> **Rationale:** Streaming display provides immediate feedback and significantly reduces perceived latency.
> **Acceptance Criteria:** Generation tokens appear character-by-character or chunk-by-chunk as they arrive. The full answer is assembled after streaming completes. Streaming errors display an error message.

> **REQ-305** | Priority: MUST
> **Description:** The Admin Console query panel MUST display stage timing information after query completion, showing the duration of each pipeline stage.
> **Rationale:** Stage timings enable operators to identify bottleneck stages and tune budget controls.
> **Acceptance Criteria:** Stage timings are displayed in a structured format (table or timeline) after each query. Each stage shows name, duration, and whether it was budget-limited.

> **REQ-306** | Priority: MUST
> **Description:** The Admin Console query panel MUST display retrieved source chunks with their metadata (filename, section, raw relevance score, rerank score) alongside the generated answer.
> **Rationale:** Operators need to verify that the generated answer is grounded in the retrieved sources and understand scoring behavior.
> **Acceptance Criteria:** Source chunks are displayed with filename, section, relevance score, and rerank score. Chunks are ordered by relevance. Scores are shown as numeric values.

> **REQ-307** | Priority: SHOULD
> **Description:** The Admin Console query panel SHOULD support a source document viewer that displays the full content of a retrieved source document when a chunk is selected.
> **Rationale:** Seeing the full document context around a chunk helps operators verify answer grounding without switching to a file browser.
> **Acceptance Criteria:** Clicking a source chunk opens a view of the full document content with the relevant chunk highlighted.

> **REQ-308** | Priority: MUST
> **Description:** The Admin Console ingestion panel MUST provide a form to trigger ingestion runs with configurable options: target mode (single file, directory, all documents), target path, update mode, and pipeline options (knowledge graph, chunking strategy, export flags).
> **Rationale:** Operators need to trigger ingestion runs from the console without constructing CLI commands.
> **Acceptance Criteria:** All documented ingestion parameters are available in the form. Submission triggers an ingestion run and displays progress or status.

> **REQ-309** | Priority: MUST
> **Description:** The Admin Console ingestion panel MUST display ingestion run status with standardized badges (running, completed, failed) and summary information (documents processed, errors encountered).
> **Rationale:** Operators need visibility into ingestion progress and outcomes to detect and resolve failures.
> **Acceptance Criteria:** An active ingestion run shows a running badge. Completion shows a success badge with summary. Failure shows an error badge with details.

> **REQ-310** | Priority: SHOULD
> **Description:** The Admin Console ingestion panel SHOULD support advanced pipeline options: document parsing mode, vision processing controls, and verbose stage logging.
> **Rationale:** Advanced users need fine-grained control over the ingestion pipeline for debugging and quality tuning.
> **Acceptance Criteria:** Advanced options are available under a collapsible section. Options include parsing mode, vision provider/model, and verbose logging toggles.

> **REQ-311** | Priority: MUST
> **Description:** The Admin Console health panel MUST display component-level readiness status for: API server, workflow engine, worker availability, and generation model reachability.
> **Rationale:** Operators need to know which components are healthy and which are degraded to prioritize troubleshooting.
> **Acceptance Criteria:** Each component shows a clear healthy/degraded/unreachable status indicator. The overall system status is an aggregate of component statuses.

> **REQ-312** | Priority: MUST
> **Description:** The Admin Console health panel MUST support periodic auto-refresh with backoff and a manual refresh button.
> **Rationale:** Operators monitoring a degraded system need updated status without manual page refresh, but auto-refresh should not overwhelm a struggling API.
> **Acceptance Criteria:** Auto-refresh occurs at configurable intervals. If the API is unreachable, the refresh interval increases (backoff). A manual refresh button triggers an immediate check.

> **REQ-313** | Priority: SHOULD
> **Description:** The Admin Console health panel SHOULD include a log snapshot view that displays recent log entries with severity filtering and timestamp display.
> **Rationale:** Correlating health status with recent logs reduces the need to switch to a separate logging tool during troubleshooting.
> **Acceptance Criteria:** The log snapshot shows the most recent log entries. Entries can be filtered by severity (info, warning, error). Entries include timestamps.

> **REQ-314** | Priority: MUST
> **Description:** The Admin Console admin panel MUST provide interfaces for API key management (list active keys, create new key, revoke key) and tenant quota management (list quotas, set quota, delete quota).
> **Rationale:** Self-service key and quota management reduces dependency on manual configuration changes.
> **Acceptance Criteria:** All admin operations are available in the console. Operations require admin role authentication. Non-admin users see a gated/disabled admin panel.

> **REQ-315** | Priority: MUST
> **Description:** Destructive admin actions (key revocation, quota deletion) MUST require explicit confirmation with a reason text before execution.
> **Rationale:** Accidental key revocation or quota deletion can disrupt active tenants. Confirmation with reason provides a friction gate and audit trail.
> **Acceptance Criteria:** Clicking "revoke" or "delete" shows a confirmation dialog requiring reason text. The action is not executed until confirmed. The reason is logged for audit.

> **REQ-316** | Priority: MUST
> **Description:** Admin actions MUST be gated by role-based access control enforced at the API level. The Admin Console MUST NOT rely solely on frontend UI gating.
> **Rationale:** Frontend-only gating can be bypassed. Server-side RBAC enforcement is the security boundary; frontend gating is a UX convenience.
> **Acceptance Criteria:** A non-admin user who bypasses frontend gating (e.g., via direct API call) receives a 403 response. Admin endpoints are not accessible without admin role.

> **REQ-317** | Priority: SHOULD
> **Description:** The Admin Console SHOULD support verbose log tailing for real-time observation of system behavior during ingestion runs or query debugging.
> **Rationale:** Operators debugging pipeline issues need real-time log output to correlate behavior with specific stages.
> **Acceptance Criteria:** A log tail view is available in the Health panel. Log entries stream in real-time via SSE or polling. Entries can be filtered by component and severity.

---

## 6. Conversation Management

> **REQ-401** | Priority: MUST
> **Description:** Both consoles MUST support conversation management. The User Console MUST display conversations in the sidebar. The Admin Console MUST include a conversation pane in the query panel. Both MUST enable creating new conversations, selecting existing conversations, and viewing conversation history.
> **Rationale:** Multi-turn interaction requires conversation lifecycle management directly within the UI, regardless of which console is being used.
> **Acceptance Criteria:** Both consoles show a list of conversations with titles and message counts. Creating a new conversation starts a fresh context. Selecting an existing conversation loads its history.

> **REQ-402** | Priority: MUST
> **Description:** Query requests from either console MUST pass `conversation_id` and `memory_enabled` parameters to the backend so that conversation memory is applied to multi-turn queries.
> **Rationale:** Without conversation context in queries, follow-up questions are treated as independent, breaking multi-turn coherence.
> **Acceptance Criteria:** Queries submitted from either console include the active conversation ID. The response includes the conversation ID for continuity. Memory can be toggled on/off per query.

> **REQ-403** | Priority: MUST
> **Description:** Both consoles MUST share the same conversation backend. A conversation started in the User Console MUST be accessible from the Admin Console, and vice versa.
> **Rationale:** Users and operators may need to switch between consoles during a session. Conversation continuity across consoles prevents loss of context.
> **Acceptance Criteria:** A conversation created in the User Console appears in the Admin Console conversation list. Loading that conversation in the Admin Console shows the same history. New messages added from either console appear in both.

> **REQ-404** | Priority: SHOULD
> **Description:** Both consoles SHOULD support manual compaction of the active conversation, triggering a rolling summary generation to reduce memory usage.
> **Rationale:** Long conversations may need compaction to keep context token usage manageable.
> **Acceptance Criteria:** A "compact" action is available for the active conversation in both consoles (via `/compact` command or UI button). Compaction triggers the server-side summary generation. The conversation continues functioning after compaction.

---

## 7. Non-Functional Requirements

> **REQ-901** | Priority: SHOULD
> **Description:** Both consoles SHOULD load and become interactive within 3 seconds on a standard connection. Initial asset bundle sizes SHOULD be minimized.
> **Rationale:** Slow-loading interfaces are abandoned. Both consoles must be responsive to maintain adoption.
> **Acceptance Criteria:** Initial page load completes within 3 seconds on a 10 Mbps connection. JavaScript bundles are not excessively large. Code-splitting MAY be used to load Admin Console features on demand.

> **REQ-902** | Priority: MUST
> **Description:** Both consoles MUST handle API unavailability gracefully by displaying connection status, disabling interactive controls, and retrying connection with backoff.
> **Rationale:** Users and operators may have a console open when the API goes down. Unhandled disconnection produces confusing errors or frozen UI.
> **Acceptance Criteria:** API disconnection is detected and displayed within 5 seconds. Interactive controls are disabled during disconnection. Reconnection is attempted automatically with increasing intervals.

> **REQ-903** | Priority: MUST
> **Description:** All console configuration (API endpoint, refresh intervals, preset storage key) MUST be configurable without code changes.
> **Rationale:** Different deployments may use different API endpoints or UI preferences.
> **Acceptance Criteria:** Configuration is loaded from environment or a discoverable configuration endpoint. Changes take effect on page reload. The User Console settings panel provides runtime overrides for user-facing settings.

> **REQ-904** | Priority: MUST
> **Description:** The User Console MUST support light and dark themes. Theme selection MUST persist across browser sessions.
> **Rationale:** Users expect theme customization in modern chat interfaces.
> **Acceptance Criteria:** A theme toggle is available in the settings panel. Selecting a theme applies it immediately. The selection persists in local storage and is restored on reload.

> **REQ-905** | Priority: SHOULD
> **Description:** The User Console SHOULD support keyboard shortcuts for common actions: Enter to send, Shift+Enter for newline, Ctrl+K or Cmd+K to start a new chat, Escape to close panels.
> **Rationale:** Power users expect keyboard-driven interaction for efficiency.
> **Acceptance Criteria:** Documented keyboard shortcuts are functional. Shortcuts do not conflict with browser defaults. A shortcut reference is available via `/help` or a keyboard icon.

---

## 8. System-Level Acceptance Criteria

| Criterion | Threshold | Related Requirements |
|-----------|-----------|---------------------|
| Dual-console availability | Both consoles load and are functional at their respective URLs | REQ-101 |
| User Console chat flow | End-to-end query from input bar to streamed answer with citations | REQ-201, REQ-203, REQ-206, REQ-207 |
| Admin Console tab coverage | All 4 modes functional | REQ-301, REQ-303, REQ-308, REQ-311, REQ-314 |
| Streaming reliability | Token stream renders correctly in both consoles or shows error | REQ-206, REQ-304, REQ-902 |
| Admin safety | Destructive actions require confirmation | REQ-315, REQ-316 |
| CLI/UI/Console parity | 100% user-facing feature coverage across CLI, User Console, and Admin Console | REQ-108, REQ-109, REQ-110 |
| Slash-command consistency | Shared catalog serves CLI and both consoles | REQ-104, REQ-105 |
| Conversation continuity | Multi-turn queries maintain context; conversations shared between consoles | REQ-401, REQ-402, REQ-403 |
| Change Parity enforcement | New features reflected in all surfaces or explicitly documented as scoped | REQ-110 |
| User Console cleanliness | No debug output, raw scores, or stage timings visible | REQ-210 |
| Responsive User Console | User Console usable on mobile, tablet, and desktop viewports | REQ-211 |

---

## 9. Requirements Traceability Matrix

| REQ ID | Section | Priority | Component |
|--------|---------|----------|-----------|
| REQ-101 | 3 | MUST | Shared Infrastructure |
| REQ-102 | 3 | MUST | Shared Infrastructure |
| REQ-103 | 3 | MUST | Shared Infrastructure |
| REQ-104 | 3 | MUST | Shared Infrastructure |
| REQ-105 | 3 | MUST | Shared Infrastructure |
| REQ-106 | 3 | MUST | Shared Infrastructure |
| REQ-107 | 3 | MUST | Shared Infrastructure |
| REQ-108 | 3 | MUST | Shared Infrastructure |
| REQ-109 | 3 | MUST | Shared Infrastructure |
| REQ-110 | 3 | MUST | Shared Infrastructure |
| REQ-111 | 3 | SHOULD | Shared Infrastructure |
| REQ-201 | 4 | MUST | User Console |
| REQ-202 | 4 | MUST | User Console |
| REQ-203 | 4 | MUST | User Console |
| REQ-204 | 4 | MUST | User Console |
| REQ-205 | 4 | MUST | User Console |
| REQ-206 | 4 | MUST | User Console |
| REQ-207 | 4 | MUST | User Console |
| REQ-208 | 4 | MUST | User Console |
| REQ-209 | 4 | MUST | User Console |
| REQ-210 | 4 | MUST | User Console |
| REQ-211 | 4 | MUST | User Console |
| REQ-212 | 4 | SHOULD | User Console |
| REQ-213 | 4 | SHOULD | User Console |
| REQ-214 | 4 | SHOULD | User Console |
| REQ-215 | 4 | SHOULD | User Console |
| REQ-216 | 4 | MUST | User Console |
| REQ-217 | 4 | MUST | User Console |
| REQ-301 | 5 | MUST | Admin Console |
| REQ-302 | 5 | MUST | Admin Console |
| REQ-303 | 5 | MUST | Admin Console |
| REQ-304 | 5 | MUST | Admin Console |
| REQ-305 | 5 | MUST | Admin Console |
| REQ-306 | 5 | MUST | Admin Console |
| REQ-307 | 5 | SHOULD | Admin Console |
| REQ-308 | 5 | MUST | Admin Console |
| REQ-309 | 5 | MUST | Admin Console |
| REQ-310 | 5 | SHOULD | Admin Console |
| REQ-311 | 5 | MUST | Admin Console |
| REQ-312 | 5 | MUST | Admin Console |
| REQ-313 | 5 | SHOULD | Admin Console |
| REQ-314 | 5 | MUST | Admin Console |
| REQ-315 | 5 | MUST | Admin Console |
| REQ-316 | 5 | MUST | Admin Console |
| REQ-317 | 5 | SHOULD | Admin Console |
| REQ-401 | 6 | MUST | Conversation Management |
| REQ-402 | 6 | MUST | Conversation Management |
| REQ-403 | 6 | MUST | Conversation Management |
| REQ-404 | 6 | SHOULD | Conversation Management |
| REQ-901 | 7 | SHOULD | Non-Functional |
| REQ-902 | 7 | MUST | Non-Functional |
| REQ-903 | 7 | MUST | Non-Functional |
| REQ-904 | 7 | MUST | Non-Functional |
| REQ-905 | 7 | SHOULD | Non-Functional |

**Total Requirements: 52**

- MUST: 40
- SHOULD: 12
- MAY: 0
