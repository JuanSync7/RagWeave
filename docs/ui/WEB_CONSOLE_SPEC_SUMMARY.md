## 1) Generic System Overview

### Purpose

The dual web console provides two purpose-built browser interfaces for the same underlying retrieval-augmented knowledge platform: one for end users seeking answers through a conversational interface, and one for operators and developers who need diagnostic visibility, ingestion control, and administrative authority. Without a deliberate separation of surfaces, a single interface either overwhelms end users with diagnostic output or deprives operators of the detailed controls they need to manage the system. The dual-console architecture solves this by assigning each audience an interface tailored to their tasks while sharing all backend infrastructure, keeping behavior consistent and maintenance surface minimal.

### How It Works

Both consoles are static browser applications served from the same origin as the backend API. A shared infrastructure layer handles authentication, command dispatch, preset management, conversation management, and response envelope normalization — providing a consistent contract that both frontend surfaces consume.

The **user-facing console** presents a chat-style layout with a collapsible navigation sidebar, a scrollable conversation thread showing message bubbles, and an input bar with command access, preset selection, and context attachment options. When a user submits a query, the input bar dispatches the request to the backend, which streams generation tokens back via a server-sent event channel. Tokens appear incrementally in the assistant bubble. After streaming completes, source citation cards appear below the answer, collapsed by default. The sidebar offers navigation to conversation history, project organization, search, and customization panels. Diagnostic information is deliberately absent from this surface.

The **operator-facing console** presents a tabbed single-page application. The Query tab provides full control over retrieval parameters and displays not only the streamed answer but also stage-by-stage pipeline timings and raw chunk scores. The Ingestion tab provides a form for triggering and monitoring document ingestion runs. The Health tab shows component-level readiness status with auto-refreshing and backoff, and optionally tails live log output. The Admin tab provides key and quota management with role-gated access and confirmation dialogs for destructive actions.

Both consoles share a unified slash-command system. Typing a command prefix in any input field reveals a server-side catalog of commands. The same catalog is also consumed by the command-line interface, ensuring that no command exists in one surface but not the others.

### Tunable Knobs

Operators can configure the target API endpoint and authentication credentials through settings panels or environment configuration, allowing deployment against different backend environments without code changes. Query behavior can be adjusted through named presets — built-in presets cover common patterns (speed-optimized, quality-optimized, diagnostic), while custom presets can be saved and reused per user. The health panel's auto-refresh cadence adjusts automatically based on API reachability, and a configurable interval controls baseline polling. Context window usage tracking can inform when a user should compact or start a fresh conversation. Theme preference (light or dark) is configurable per user and persists across sessions.

### Design Rationale

The separation into two distinct consoles reflects a core insight: diagnostic output is noise to end users and signal to operators. Attempting to hide or reveal elements conditionally within a single interface is fragile — the dual-console approach makes the distinction structural. The decision to share all backend infrastructure (commands, presets, conversations, envelope format) rather than duplicating it ensures that changes propagate to both surfaces uniformly. Change parity is enforced as a principle: any new capability must land in all surfaces simultaneously or be explicitly documented as intentionally scoped. This prevents one console from silently falling behind. The backend-driven command catalog follows the same logic — centralizing command semantics on the server keeps both frontends as thin renderers and eliminates drift between CLI and console behavior.

### Boundary Semantics

Entry point: a browser request to either console URL, initiated by a user or operator. The console loads its static assets from the backend server and establishes a session with the API. Exit point: the console delivers a completed query response with citations (user console) or a completed operational action with status and diagnostic output (operator console), and any resulting state (conversation history, preset updates, admin changes) is persisted server-side. The console is responsible for rendering, input collection, and streaming display; all business logic, retrieval, generation, command semantics, and authorization enforcement live server-side. The console boundary ends where the core API begins.

---

## Web Console Specification — Summary

**Companion spec:** `WEB_CONSOLE_SPEC.md`
**Version aligned to:** 2.0
**Status:** Implemented Baseline
**Domain:** Web Console
**See also:** `WEB_CONSOLE_DESIGN.md`, `WEB_CONSOLE_IMPLEMENTATION.md`, `SERVER_API_SPEC.md`

> This summary is a digest of the companion spec. It captures intent, scope, structure, and key decisions. For requirement-level detail, acceptance criteria, and traceability, see the companion spec.

---

## Scope and Boundaries

**Entry point:** A user or operator opens a console URL in a browser.

**Exit point:** The user completes a query workflow with visible feedback, or the operator completes an operational workflow (query with diagnostics, ingestion, health check, admin action) with traceable results.

**In scope:**
- Shared console infrastructure: static asset serving, authentication, console envelope format, slash-command system (shared catalog), named preset management, notification and loading-state components
- User Console layout, chat thread, message bubbles, source citation cards, streaming display, sidebar navigation (Conversations, Projects, Search, Customize), settings panel, responsive/mobile layout, icon-rail collapsed sidebar, context attachment toolbar, slash-command picker button, context window usage indicator
- Admin Console tabbed layout (Query, Ingestion, Health, Admin), stage timing display, chunk scoring display, ingestion management, health monitoring with auto-refresh, API key and quota management, role-gated admin actions
- Conversation management shared between both consoles: creation, selection, history, multi-turn context, cross-console continuity, manual compaction

**Out of scope:**
- Offline mode (both consoles require a live API connection)
- API endpoint schemas and error handling (covered by `SERVER_API_SPEC.md`)
- Native mobile applications (the User Console is responsive for mobile browsers; native apps are excluded)

---

## Architecture / Pipeline Overview

```
User (Browser)                    Operator (Browser)
    |                                  |
    v                                  v
+---------------------+     +-------------------------+
| USER CONSOLE        |     | ADMIN CONSOLE           |
|   /console          |     |   /console/admin        |
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
       | SHARED CONSOLE BACKEND        |
       |   /console/* endpoints        |
       |   Slash-command dispatch      |
       |   Preset management          |
       |   Conversation management    |
       |   Auth & envelope            |
       |   Static asset serving       |
       +-------------------------------+
                      |
                      v
       +-------------------------------+
       | CORE API                      |
       |   /query, /admin, /health,    |
       |   /conversations/*            |
       +-------------------------------+
```

Key data flows:
- **User Console chat** → console query endpoint → core query (streaming SSE) → tokens + citations
- **Admin Console query** → same endpoint, additional response fields → tokens + timings + chunk scores
- **Admin Console ingestion** → console ingest endpoint → internal pipeline dispatch → progress/status
- **Admin Console health** → console health endpoint → aggregated component status
- **Admin Console admin** → console admin endpoints → key/quota operations
- **Both: commands** → console command endpoint (server-side dispatch)
- **Both: conversations** → shared conversation CRUD endpoints
- **Both: presets** → shared preset catalog (built-ins server-side; custom presets in browser storage)

---

## Requirement Framework

- **ID convention:** `REQ-NNN`, grouped by section/component
- **Priority keywords:** MUST (absolute), SHOULD (recommended), MAY (optional) — RFC 2119
- **Format per requirement:** Description, Rationale, Acceptance Criteria

| Section | ID Range | Component |
|---------|----------|-----------|
| 3 | REQ-1xx | Shared Infrastructure |
| 4 | REQ-2xx | User Console |
| 5 | REQ-3xx | Admin Console |
| 6 | REQ-4xx | Conversation Management |
| 7 | REQ-9xx | Non-Functional Requirements |

**Total: 52 requirements** — 40 MUST, 12 SHOULD, 0 MAY

---

## Functional Requirement Domains

- **Shared Infrastructure (REQ-100 to REQ-111):** Same-origin static asset serving at well-known URLs; standardized console response envelope; unified authentication with role separation; slash-command system backed by a shared server-side catalog; unified command dispatch endpoint; named preset management (built-in and custom); CLI/UI/console feature parity; shared interaction contracts; change parity enforcement; shared notification and loading-state components.

- **User Console (REQ-200 to REQ-217):** Three-zone chat layout (sidebar, thread, input bar); sidebar with four navigation sections and settings footer; message bubble thread with directional alignment and timestamps; input bar with preset selector and optional source filter; loading indicator during generation; streaming token display via server-sent events; collapsible source citation cards with filename, section, and relevance badge; slash-command support with minimum required commands; settings panel for endpoint, auth, and theme; suppression of all diagnostic output; responsive layout with mobile sidebar behavior; icon-rail collapsible sidebar; slash-command picker button; context window usage indicator; context attachment toolbar.

- **Admin Console (REQ-300 to REQ-317):** Tabbed SPA shell with Query, Ingestion, Health, and Admin modes; persistent status bar showing endpoint and auth context; full-parameter query form with advanced options; streaming display; stage timing breakdown; source chunk display with raw and rerank scores; optional source document viewer; ingestion form with target and pipeline options; ingestion run status badges; optional advanced ingestion options; component health panel with auto-refresh and backoff; optional log snapshot; API key and quota management panels; destructive action confirmation with reason; server-enforced role-based access control; optional real-time log tailing.

- **Conversation Management (REQ-400 to REQ-404):** Conversation list and history in both consoles; multi-turn query context via conversation ID and memory flag; shared conversation backend accessible from either console; optional manual compaction.

---

## Non-Functional and Security Themes

- **Performance:** Initial load target for both consoles; bundle size minimization with optional code-splitting.
- **Resilience:** Graceful handling of API unavailability — connection status display, control disabling, automatic reconnection with backoff.
- **Configurability:** All console configuration (endpoint, refresh intervals, storage keys) must be externalizable without code changes.
- **Theming:** Light and dark theme support persisted in browser storage (User Console).
- **Keyboard accessibility:** Keyboard shortcuts for common actions in the User Console; no conflicts with browser defaults.
- **Security:** Role-based access control enforced server-side for admin operations; frontend gating is a UX convenience only; destructive actions require confirmation with a logged reason.

---

## Design Principles

| Principle | Summary |
|-----------|---------|
| **Audience Separation** | Each console is purpose-built for its audience — end users get a clean chat interface; operators get full diagnostic and administrative capability |
| **CLI/UI Parity** | Every user-facing capability in the CLI must be present in both consoles, and vice versa |
| **Change Parity** | New features must land in all surfaces in the same change set, or be explicitly documented as intentionally scoped to one surface |
| **Backend-Driven Behavior** | Both consoles render and dispatch; business logic and command semantics live server-side |
| **Progressive Disclosure** | Advanced options are hidden by default; the Admin Console surfaces more by default than the User Console |

---

## Key Decisions

- **Dual-console over conditional UI:** Rather than hiding/showing elements within one interface based on role, the architecture provides structurally separate consoles at distinct URLs. This makes the audience separation explicit and structural rather than fragile.
- **Shared backend for all console concerns:** Authentication, commands, presets, conversations, and envelope format are handled by a shared backend layer consumed by both frontends. This prevents drift and keeps frontends as thin renderers.
- **Server-side command catalog:** The slash-command catalog lives server-side and is served to CLI, User Console, and Admin Console from a single source of truth. Adding a command propagates to all surfaces automatically.
- **Server-side RBAC, not frontend gating:** Admin access control is enforced at the API level. Frontend gating is a UX convenience only. The spec explicitly states that direct API calls must still be rejected without admin role.
- **Streaming via SSE in both consoles:** Both consoles render generation output incrementally. The Admin Console renders the same stream but additionally displays stage timings and chunk scores available in the extended response.
- **Custom presets in browser storage:** Built-in presets are immutable and served from the server; custom presets are persisted locally per user, avoiding a server-side user preference store.

---

## Acceptance, Evaluation, and Feedback

The spec defines a system-level acceptance criteria table covering eleven criteria:

- Dual-console availability at their respective URLs
- End-to-end User Console chat flow (input → streaming → citations)
- All four Admin Console tabs functional
- Streaming reliability or graceful error rendering in both consoles
- Destructive admin actions requiring confirmation
- CLI/UI/Console parity at 100% for user-facing features
- Slash-command consistency across CLI and both consoles
- Multi-turn conversation continuity with cross-console sharing
- Change parity enforcement in pull request review
- User Console cleanliness (no diagnostic output)
- User Console responsive across mobile, tablet, and desktop viewports

No automated evaluation framework is defined in the spec. Acceptance is verified through manual testing against the criteria in the companion spec.

---

## External Dependencies

| Dependency | Type | Notes |
|------------|------|-------|
| Core API server | Required | Both consoles require a live API connection; offline mode is out of scope |
| Console backend endpoints (`/console/*`) | Required | Shared backend layer that both frontends consume |
| Token budget subsystem | Required (for REQ-214) | Context window usage indicator sources data from the query endpoint; see `TOKEN_BUDGET_SPEC.md` |
| Browser local storage | Required | Custom preset storage, theme preference, sidebar collapsed state, settings persistence |
| SSE streaming support | Required | Streaming token display in both consoles depends on server-sent events |
| `SERVER_API_SPEC.md` | Companion doc | API endpoint schemas and error handling are out of scope for this spec; defined there |

---

## Companion Documents

| Document | Role |
|----------|------|
| `WEB_CONSOLE_SPEC.md` | **Companion spec (this summary's source)** — normative requirements, acceptance criteria, traceability matrix |
| `WEB_CONSOLE_DESIGN.md` | Design document — task decomposition, component contracts |
| `WEB_CONSOLE_IMPLEMENTATION.md` | Implementation guide — as-built behavior and engineering detail |
| `SERVER_API_SPEC.md` | API server layer spec — endpoint schemas and error handling |
| `TOKEN_BUDGET_SPEC.md` | Token budget spec — context window counting and display |
| `server/console/README.md` | As-built behavior reference |

This summary is a standalone digest intended for technical stakeholders who need the shape of the spec without reading every requirement. It is not a replacement for the companion spec.

---

## Sync Status

| Field | Value |
|-------|-------|
| Spec version aligned to | 2.0 |
| Summary written | 2026-04-10 |
| Summary status | Current |
