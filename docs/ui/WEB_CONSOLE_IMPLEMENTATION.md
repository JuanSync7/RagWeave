# Web Console User Console — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the User Console as a modern chat interface at `/console`, converting the design mockup (`task-4-1-preview.html`) into production TypeScript/HTML/CSS served by the existing FastAPI backend.

**Architecture:** The User Console is a single-page application served as static assets from `server/console/static/user/`. It communicates with the existing `/console/*` API endpoints (query, conversations, commands, health) using the `ConsoleEnvelope` response pattern. The existing admin console at `server/console/static/console.html` is preserved and will later move to `/console/admin`. The backend route factory (`create_console_router`) is extended to serve both entry points.

**Tech Stack:** TypeScript (ES2021), vanilla CSS with custom properties (theming), marked.js (Markdown), DOMPurify (sanitization), SSE for streaming. No framework — matches the existing admin console's vanilla TS approach.

**Spec:** `docs/ui/WEB_CONSOLE_SPEC.md` v2.0
**Design:** `docs/ui/WEB_CONSOLE_DESIGN.md` v3.0
**Visual Reference:** `docs/ui/task-4-1-preview.html`

---

## File Structure

### Contracts (Phase 0)

| File | Action | Purpose |
|------|--------|---------|
| `server/console/web/src/types.ts` | CREATE | Shared TypeScript types for User Console |
| `server/console/web/src/api-client.ts` | CREATE | API client with typed methods for all console endpoints |

### Source (Phase B — implementations)

| File | Action | Purpose |
|------|--------|---------|
| `server/console/static/user/index.html` | CREATE | User Console HTML entry point with full markup |
| `server/console/static/user/styles.css` | CREATE | User Console CSS (extracted from task-4-1-preview.html) |
| `server/console/web/src/user-console.ts` | CREATE | User Console application logic (compiled to user-main.js) |
| `server/console/static/user/user-main.js` | CREATE (build output) | Compiled JS from user-console.ts |
| `server/console/routes.py` | MODIFY | Add `/console` → User Console, keep existing as admin |
| `server/console/services.py` | MODIFY | Add User Console static path constants |

### Tests (Phase A)

| File | Action | Purpose |
|------|--------|---------|
| `tests/ui/test_user_console_api_client.py` | CREATE | API client contract tests |
| `tests/ui/test_user_console_routes.py` | CREATE | Route serving and dual-console routing tests |
| `tests/ui/test_user_console_rendering.py` | CREATE | HTML structure and accessibility tests |

---

## Dependency Graph

```
Phase 0: Contracts
  0-1: types.ts ─────────────────────────────────────────────┐
  0-2: api-client.ts ◄── 0-1 ───────────────────────────────┤
                                                              │
  ══════════════════ [REVIEW GATE] ══════════════════════════ │
                                                              │
Phase A: Tests (all parallel, isolated from Phase B)          │
  A-1: test_user_console_routes.py ──────────────────────────┤
  A-2: test_user_console_api_client.py ◄── 0-1, 0-2 ────────┤
  A-3: test_user_console_rendering.py ───────────────────────┤
                                                              │
Phase B: Implementation                                       │
  B-1: routes.py + services.py ◄── A-1 ─────────────────────┤
  B-2: index.html + styles.css ◄── B-1, A-3 ────────────────┤ [CRITICAL]
  B-3: user-console.ts ◄── B-2, 0-2, A-2 ──────────────────┤ [CRITICAL]
  B-4: Build + integration ◄── B-3 ──────────────────────────┘
```

---

## Task-to-Requirement Mapping

| Task | Phase 0 | Phase A Test | Phase B Source | Requirements |
|------|---------|-------------|---------------|-------------|
| B-1: Dual routing | types.ts | test_routes.py | routes.py, services.py | REQ-101, REQ-903 |
| B-2: HTML + CSS shell | — | test_rendering.py | index.html, styles.css | REQ-201, REQ-202, REQ-203, REQ-211, REQ-217, REQ-904 |
| B-3: App logic | types.ts, api-client.ts | test_api_client.py | user-console.ts | REQ-204–REQ-210, REQ-213–REQ-216, REQ-401–REQ-404, REQ-902, REQ-905 |
| B-4: Build + integration | — | all | all | REQ-901 |

---

## Phase 0 — Contract Definitions

### Task 0-1: TypeScript Types (`server/console/web/src/types.ts`)

- [ ] Create `types.ts` with the following type definitions:

```typescript
// -- Console Envelope --
export type ConsoleEnvelope<T = Record<string, unknown>> = {
  ok: boolean;
  request_id?: string;
  data?: T;
  error?: { code: string; message: string; details?: string };
};

// -- Messages --
export type MessageRole = "user" | "assistant";

export type CitationSource = {
  filename: string;
  section: string;
  score: number;
  chunk_text: string;
  source_uri?: string;
};

export type ChatMessage = {
  id: string;
  role: MessageRole;
  content: string;
  citations?: CitationSource[];
  timestamp_ms: number;
  is_streaming?: boolean;
};

// -- Conversations --
export type ConversationMeta = {
  conversation_id: string;
  title?: string;
  updated_at_ms?: number;
  message_count?: number;
};

export type ConversationTurn = {
  role: MessageRole;
  content: string;
  timestamp_ms?: number;
};

// -- Query --
export type QueryParams = {
  query: string;
  search_limit?: number;
  rerank_top_k?: number;
  stream?: boolean;
  conversation_id?: string;
  memory_enabled?: boolean;
  context_attachments?: ContextAttachment[];
};

export type QueryResult = {
  score?: number;
  text?: string;
  metadata?: Record<string, unknown>;
};

export type StreamEventData = {
  token?: string;
  message?: string;
  results?: QueryResult[];
  context_usage_pct?: number;
  context_breakdown?: ContextBreakdown;
};

export type ContextBreakdown = {
  memory_tokens?: number;
  chunk_tokens?: number;
  query_tokens?: number;
  system_tokens?: number;
};

// -- Commands --
export type SlashCommand = {
  name: string;
  description: string;
  args_hint?: string;
  intent?: string;
  category?: string;
};

export type CommandResult = {
  intent?: string;
  action?: string;
  message?: string;
  data?: Record<string, unknown>;
};

// -- Context Attachments --
export type ContextAttachment = {
  type: "file" | "web" | "kb";
  label: string;
  data?: string;
  uri?: string;
};

// -- Settings --
export type UserSettings = {
  theme: "dark" | "light" | "system";
  preset: string;
  search_limit: number;
  rerank_top_k: number;
  streaming: boolean;
  show_citations: boolean;
  api_endpoint?: string;
  auth_token?: string;
};

// -- Health --
export type HealthSummary = {
  status: string;
  temporal_connected?: boolean;
  worker_available?: boolean;
  ollama_reachable?: boolean;
};

// -- Sidebar --
export type SidebarNavItem = "conversations" | "projects" | "search" | "customize";
```

### Task 0-2: API Client (`server/console/web/src/api-client.ts`)

- [ ] Create `api-client.ts` that imports from `types.ts`:

```typescript
import type {
  ConsoleEnvelope,
  ConversationMeta,
  ConversationTurn,
  SlashCommand,
  CommandResult,
  QueryParams,
  StreamEventData,
  HealthSummary,
} from "./types";

export class ConsoleApiClient {
  private baseUrl: string;
  private authHeaders: () => Record<string, string>;

  constructor(baseUrl: string, authHeaders: () => Record<string, string>) {
    this.baseUrl = baseUrl;
    this.authHeaders = authHeaders;
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<ConsoleEnvelope<T>> {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...this.authHeaders(),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    return resp.json();
  }

  // -- Health --
  async getHealth(): Promise<ConsoleEnvelope<HealthSummary>> {
    return this.request("GET", "/console/health");
  }

  // -- Conversations --
  async listConversations(
    limit?: number,
  ): Promise<ConsoleEnvelope<{ conversations: ConversationMeta[] }>> {
    const q = limit ? `?limit=${limit}` : "";
    return this.request("GET", `/console/conversations${q}`);
  }

  async createConversation(
    title?: string,
  ): Promise<ConsoleEnvelope<{ conversation_id: string }>> {
    return this.request("POST", "/console/conversations/new", { title });
  }

  async getConversationHistory(
    id: string,
    limit?: number,
  ): Promise<ConsoleEnvelope<{ turns: ConversationTurn[]; conversation_id: string }>> {
    const q = limit ? `?limit=${limit}` : "";
    return this.request("GET", `/console/conversations/${id}/history${q}`);
  }

  async compactConversation(
    id: string,
  ): Promise<ConsoleEnvelope<{ summary: string }>> {
    return this.request("POST", `/console/conversations/${id}/compact`, {});
  }

  async deleteConversation(id: string): Promise<ConsoleEnvelope<unknown>> {
    return this.request("DELETE", `/console/conversations/${id}`, undefined);
  }

  // -- Commands --
  async getCommands(
    mode?: string,
    surface?: string,
  ): Promise<SlashCommand[]> {
    const params = new URLSearchParams();
    if (mode) params.set("mode", mode);
    if (surface) params.set("surface", surface);
    const resp = await fetch(
      `${this.baseUrl}/console/commands?${params}`,
      { headers: this.authHeaders() },
    );
    return resp.json();
  }

  async executeCommand(
    mode: string,
    command: string,
    arg?: string,
    state?: Record<string, unknown>,
  ): Promise<ConsoleEnvelope<CommandResult>> {
    return this.request("POST", "/console/command", {
      mode,
      command,
      arg: arg ?? "",
      state: state ?? {},
    });
  }

  // -- Query (non-streaming) --
  async query(params: QueryParams): Promise<ConsoleEnvelope<unknown>> {
    return this.request("POST", "/console/query", {
      ...params,
      stream: false,
    });
  }

  // -- Query (streaming via SSE) --
  streamQuery(
    params: QueryParams,
    callbacks: {
      onToken: (token: string) => void;
      onResult: (data: StreamEventData) => void;
      onError: (error: string) => void;
      onDone: () => void;
    },
  ): AbortController {
    const controller = new AbortController();
    const url = `${this.baseUrl}/console/query`;

    fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...this.authHeaders(),
      },
      body: JSON.stringify({ ...params, stream: true }),
      signal: controller.signal,
    })
      .then((resp) => {
        if (!resp.ok || !resp.body) {
          callbacks.onError(`HTTP ${resp.status}`);
          return;
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        const processChunk = ({
          done,
          value,
        }: ReadableStreamReadResult<Uint8Array>): Promise<void> | void => {
          if (done) {
            callbacks.onDone();
            return;
          }
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              try {
                const data: StreamEventData = JSON.parse(line.slice(6));
                if (data.token) callbacks.onToken(data.token);
                if (data.results) callbacks.onResult(data);
              } catch {
                // skip malformed lines
              }
            }
          }
          return reader.read().then(processChunk);
        };

        return reader.read().then(processChunk);
      })
      .catch((err) => {
        if (err.name !== "AbortError") {
          callbacks.onError(String(err));
        }
      });

    return controller;
  }
}
```

**Review gate:** Phase 0 contracts must be human-reviewed before proceeding to Phase A/B.

---

## Phase A — Tests (Isolated from Implementation)

**Agent isolation contract:** The test agent receives ONLY:
1. The spec requirements (REQ numbers + acceptance criteria)
2. The contract files from Phase 0 (types.ts, api-client.ts)
3. The task description from the design document

**Must NOT receive:** Any implementation code, any code appendix patterns from the design doc, any source files beyond Phase 0 stubs.

### Task A-1: Route Serving Tests (`tests/ui/test_user_console_routes.py`)

**Agent input (ONLY these):**
- REQ-101: Both consoles served at `/console` and `/console/admin`; all assets same-origin
- REQ-903: Configuration without code changes; configuration endpoint
- Existing route factory signature from `server/console/routes.py` (lines 59-67)

**Must NOT receive:** task-4-1-preview.html, user-console.ts, index.html source

**Files:**
- Create: `tests/ui/test_user_console_routes.py`

**Test cases:**
- [ ] REQ-101: `GET /console` returns 200 with HTML content-type
- [ ] REQ-101: `GET /console/admin` returns 200 with HTML content-type (existing admin)
- [ ] REQ-101: `GET /console/static/user/styles.css` returns 200 with CSS content-type
- [ ] REQ-101: `GET /console/static/user/user-main.js` returns 200 with JS content-type
- [ ] REQ-101: Path traversal `GET /console/static/user/../../etc/passwd` returns 404 or 400
- [ ] REQ-903: Both consoles served from same origin (no cross-origin headers)

**Pytest command:** `pytest tests/ui/test_user_console_routes.py -v` (expect FAIL — routes not yet modified)

---

### Task A-2: API Client Contract Tests (`tests/ui/test_user_console_api_client.py`)

**Agent input (ONLY these):**
- REQ-102: Envelope format (`ok`, `request_id`, `data`, `error`)
- REQ-401: Conversation management (list, create, select, history)
- REQ-402: Query requests pass `conversation_id` and `memory_enabled`
- REQ-104: Slash command catalog from server
- Phase 0 contracts: `types.ts`, `api-client.ts`

**Must NOT receive:** user-console.ts, index.html, styles.css

**Files:**
- Create: `tests/ui/test_user_console_api_client.py`

**Test cases:**
- [ ] REQ-102: `getHealth()` returns ConsoleEnvelope with `ok` boolean
- [ ] REQ-401: `listConversations()` returns conversations array
- [ ] REQ-401: `createConversation()` returns conversation_id
- [ ] REQ-401: `getConversationHistory()` returns turns array with conversation_id
- [ ] REQ-402: `query()` includes conversation_id and memory_enabled in request body
- [ ] REQ-104: `getCommands("query", "user")` returns array of SlashCommand objects
- [ ] REQ-104: `executeCommand()` returns CommandResult with intent/action/message

**Pytest command:** `pytest tests/ui/test_user_console_api_client.py -v` (expect FAIL — API client not yet wired)

---

### Task A-3: HTML Structure and Rendering Tests (`tests/ui/test_user_console_rendering.py`)

**Agent input (ONLY these):**
- REQ-201: Chat layout with sidebar, chat area, input bar
- REQ-202: Sidebar with brand header, collapse toggle, navigation rail (4 items), settings footer
- REQ-203: Chat thread with user (right) and assistant (left) bubbles with timestamps
- REQ-207: Citation cards (collapsed by default, filename/section/relevance)
- REQ-211: Responsive from 320-2560px, hamburger below 768px
- REQ-217: Icon-rail collapsed state (56px), tooltip on hover, persists in localStorage
- REQ-904: Light/dark theme via CSS custom properties
- REQ-210: No debug output, stage timings, or raw scores visible

**Must NOT receive:** user-console.ts, api-client.ts

**Files:**
- Create: `tests/ui/test_user_console_rendering.py`

**Test cases:**
- [ ] REQ-201: index.html contains elements with classes: `.sidebar`, `.main`, `.message-thread`, `.input-bar`
- [ ] REQ-202: Sidebar has brand header, `.new-chat-btn`, 4 `.sidebar-nav-item` elements, `.settings-btn` footer
- [ ] REQ-202: Each nav item has `data-tooltip` and `data-panel` attributes
- [ ] REQ-203: Message rows have `.msg-row.user` and `.msg-row.assistant` classes
- [ ] REQ-207: Citation cards with `.citation-card`, `.citation-filename`, `.citation-section`, `.relevance-pct`
- [ ] REQ-211: CSS contains `@media (max-width: 1024px)` breakpoint for sidebar
- [ ] REQ-217: CSS contains `.sidebar.collapsed` rules with `width: 56px`
- [ ] REQ-904: CSS contains `[data-theme="light"]` and `[data-theme="dark"]` selectors (or `:root` dark defaults)
- [ ] REQ-210: No elements with classes containing "debug", "timing", "raw-score" in index.html

**Pytest command:** `pytest tests/ui/test_user_console_rendering.py -v` (expect FAIL — files not yet created)

---

## Phase B — Implementation

### Task B-1: Backend Route Extension

**Agent input:** Design Task 1.1 description, Phase A test file `test_user_console_routes.py`, Phase 0 contracts
**Must NOT receive:** test_user_console_api_client.py, test_user_console_rendering.py

**Requirements:** REQ-101, REQ-903

**Files:**
- Modify: `server/console/services.py`
- Modify: `server/console/routes.py`

**Steps:**

- [ ] REQ-101: In `services.py`, add `USER_CONSOLE_DIR` and `USER_CONSOLE_HTML_PATH` constants pointing to `server/console/static/user/`
- [ ] REQ-101: In `services.py`, add `resolve_user_console_static_asset(asset_path)` with same traversal checks as existing `resolve_console_static_asset`
- [ ] REQ-101: In `routes.py`, add `GET /console` route that serves `USER_CONSOLE_HTML_PATH` (User Console entry point)
- [ ] REQ-101: Rename existing `GET /console` route to `GET /console/admin` for admin console (preserve current behavior)
- [ ] REQ-101: Add `GET /console/static/user/{asset_path}` route for User Console static assets
- [ ] REQ-903: User Console HTML loads with `Cache-Control: no-store, max-age=0` (match existing pattern)

**Pytest command:** `pytest tests/ui/test_user_console_routes.py -v` (expect ALL PASS)

**Commit:** `feat(console): add dual-console routing — User Console at /console, Admin at /console/admin`

---

### Task B-2: HTML and CSS (User Console Shell)

**Agent input:** Design Tasks 4.1, 4.4, 4.5, 4.8 descriptions, Phase A test file `test_user_console_rendering.py`, visual reference `task-4-1-preview.html`
**Must NOT receive:** test_user_console_routes.py, test_user_console_api_client.py

**Requirements:** REQ-201, REQ-202, REQ-203, REQ-204, REQ-207, REQ-210, REQ-211, REQ-217, REQ-904

**Files:**
- Create: `server/console/static/user/index.html`
- Create: `server/console/static/user/styles.css`

**Steps:**

- [ ] REQ-904: Extract CSS custom properties from `task-4-1-preview.html` into `styles.css` — both `:root` (dark) and `[data-theme="light"]` variable sets
- [ ] REQ-201: Build `index.html` with app shell structure: `.app-shell` > `.sidebar` + `.main`
- [ ] REQ-202: Build sidebar structure: `.sidebar-header` (brand + collapse btn), `.sidebar-top-actions` (new chat), `.sidebar-nav` (4 items with `data-tooltip` and `data-panel`), `.sidebar-panel` containers (conversations, projects, search, customize), `.sidebar-footer` (settings)
- [ ] REQ-217: Add `.sidebar.collapsed` CSS rules: `width: 56px`, hide labels, hide panel content, CSS `::after` tooltips
- [ ] REQ-203: Build `.main` > `.chat-header` + `.message-thread` + `.input-bar` structure
- [ ] REQ-203: Add message bubble markup: `.msg-row.user` (right-aligned) and `.msg-row.assistant` (left-aligned) with avatars, bubbles, meta timestamps
- [ ] REQ-207: Add citation card markup: `.citations` > `.citation-card` with header (icon, filename, section, relevance bar, chevron) and collapsible body
- [ ] REQ-204: Build input bar: `.input-wrap` with toolbar (+, / buttons), textarea, send button; `.slash-dropdown` for autocomplete; `.attach-popover`, `.web-input-panel`, `.kb-panel`, `.cmd-picker` for overlays
- [ ] REQ-211: Add responsive CSS: `@media (max-width: 1024px)` for sidebar overlay, `@media (max-width: 600px)` for mobile bubbles, `@media (max-width: 480px)` for hiding badges
- [ ] REQ-904: Build settings panel overlay: theme selector (dark/light/system), preset picker, search limit + rerank sliders, streaming + citations toggles
- [ ] REQ-210: Verify NO debug, timing, or raw-score elements in markup
- [ ] Add CDN script tags: `marked.js`, `DOMPurify`
- [ ] Add `<script src="user-main.js"></script>` at bottom

**Pytest command:** `pytest tests/ui/test_user_console_rendering.py -v` (expect ALL PASS)

**Commit:** `feat(console): add User Console HTML shell and CSS theme system`

---

### Task B-3: Application Logic (User Console TypeScript)

**Agent input:** Design Tasks 4.2, 4.3, 4.6, 4.7, 5.1 descriptions, Phase A test file `test_user_console_api_client.py`, Phase 0 contracts (types.ts, api-client.ts)
**Must NOT receive:** test_user_console_routes.py, test_user_console_rendering.py

**Requirements:** REQ-204, REQ-205, REQ-206, REQ-207, REQ-208, REQ-209, REQ-213, REQ-214, REQ-215, REQ-216, REQ-401, REQ-402, REQ-404, REQ-902, REQ-905

**Files:**
- Create: `server/console/web/src/user-console.ts`

**Steps:**

- [ ] REQ-902: Initialize `ConsoleApiClient` with base URL and auth headers from localStorage
- [ ] REQ-902: Implement connection status polling: `getHealth()` on interval, update `.status-chip` with connected/disconnected state, backoff on failure
- [ ] REQ-401: Implement conversation management: `loadConversations()` → render in sidebar `.conv-list`; `createConversation()` on new-chat click; `selectConversation()` loads history into `.message-thread`
- [ ] REQ-402: Track `activeConversationId` state; pass `conversation_id` + `memory_enabled` on all query submissions
- [ ] REQ-205: Implement typing indicator: show `.typing-indicator` after submit, hide when first token arrives
- [ ] REQ-206: Implement streaming renderer: `streamQuery()` with `onToken` → append to active bubble, `onResult` → render citations, `onDone` → finalize. Use `requestAnimationFrame` batching.
- [ ] REQ-206: Implement Markdown rendering in bubbles using `marked.parse()` + `DOMPurify.sanitize()`
- [ ] REQ-203: Implement auto-scroll: scroll to bottom on new message unless user has scrolled up (near-bottom detection < 80px)
- [ ] REQ-203: Implement scroll-to-bottom FAB: `.scroll-fab` visible when not near bottom
- [ ] REQ-207: Implement citation rendering: after stream finalizes, render `.citation-card` elements with relevance bar fill width; click to expand/collapse body
- [ ] REQ-207: Implement copy-to-clipboard: `.msg-action-btn` click copies bubble text content
- [ ] REQ-208: Implement slash-command autocomplete: on `/` keystroke in input, show `.slash-dropdown` with filtered commands from `getCommands("query", "user")`; arrow key navigation; Enter to select; Esc to dismiss
- [ ] REQ-216: Implement command picker panel: "/" toolbar button opens `.cmd-picker` with grouped commands; keyboard + mouse navigation
- [ ] REQ-215: Implement attachment toolbar: "+" button toggles `.attach-popover`; file upload via hidden `<input type="file">`; web URL panel; KB selection panel. Attached items render as `.attach-chip` above input.
- [ ] REQ-904: Implement theme system: `setTheme(val)` applies `data-theme` attribute to `<html>`; persist to `localStorage`; `matchMedia` listener for system theme
- [ ] REQ-209: Implement settings panel: open/close overlay; load/save settings from `localStorage`; apply preset values to sliders
- [ ] REQ-214: Implement context window indicator: update `.ctx-chip` after each completed turn from `context_usage_pct`; three visual states (normal/warn/crit); hover tooltip with breakdown
- [ ] REQ-217: Implement sidebar collapse: toggle `.collapsed` class; persist to `localStorage`; restore on load; suppress on mobile
- [ ] REQ-211: Implement responsive sidebar: `openSidebar()`/`closeSidebar()` for mobile overlay with backdrop; touch swipe-to-open; resize listener
- [ ] REQ-905: Implement keyboard shortcuts: Enter to send, Shift+Enter for newline, Escape to close panels
- [ ] REQ-404: Implement compact button: in context tooltip critical state, click triggers `compactConversation()` API call

**Pytest command:** `pytest tests/ui/test_user_console_api_client.py -v` (expect ALL PASS)

**Commit:** `feat(console): implement User Console application logic with streaming chat`

---

### Task B-4: Build and Integration

**Agent input:** All Phase A tests, all Phase B source files
**Must NOT receive:** N/A (integration task)

**Requirements:** REQ-901

**Files:**
- Modify: `server/console/web/tsconfig.json` (add user-console entry)
- Modify: `server/console/web/package.json` (add build:user script)
- Create: `server/console/static/user/user-main.js` (build output)

**Steps:**

- [ ] REQ-901: Add `user-console.ts` to TypeScript build configuration
- [ ] REQ-901: Build `user-main.js` output to `server/console/static/user/`
- [ ] Run all Phase A tests: `pytest tests/ui/ -v` (expect ALL PASS)
- [ ] Manual smoke test: start server, navigate to `/console`, verify chat flow end-to-end
- [ ] Verify `/console/admin` still serves the existing admin console

**Commit:** `feat(console): complete User Console build pipeline and integration`

---

## Execution Handoff

Plan complete. Three execution phases:

**Phase 0:** Implement contracts (`types.ts`, `api-client.ts`) in this session (human review before proceeding).

**Phase A:** Dispatch one test agent per task in parallel. Each receives ONLY its listed 'Agent input'.

**Phase B:** Dispatch implementation agents following the dependency graph: B-1 → B-2 → B-3 → B-4. Each receives ONLY its task + test file + contracts.

**Ready to start with Phase 0?**
