<!-- @summary
Web console module for dual-console UX: User Console at /console, Admin Console at /console/admin.
Routes, service helpers, and UI asset handling for both surfaces.
@end-summary -->

# server/console

## Overview

This package owns the dual web console backend:

- `routes.py`: all `/console/*` FastAPI endpoints.
- `services.py`: shared console helpers (health probe, logs tail, source rendering, static UI path resolution).
- `static/user/index.html`: User Console (modern chat interface) served at `/console`.
- `static/console.html`: Admin Console (tabbed debug/ops interface) served at `/console/admin`.
- `web/src/user-console.ts`: TypeScript source for the User Console.
- `web/src/main.ts`: TypeScript source for the Admin Console.
- `web/tsconfig.json` + `web/package.json`: TypeScript build config.

## Console URLs

| URL | Interface | Purpose |
|-----|-----------|---------|
| `http://localhost:8000/console` | **User Console** | Modern chat interface for end users |
| `http://localhost:8000/console/admin` | **Admin Console** | Tabbed debug/ops interface for operators |

## Build TypeScript UI

```bash
npm --prefix server/console/web install
npm --prefix server/console/web run build
```

Build output is emitted to `server/console/static/main.js` and served via
`GET /console/static/{asset_path}`.

Equivalent root shortcuts:

```bash
make console-install && make console-build
# or
npm run console:install && npm run console:build
```

## CLI/UI Parity Rule

Console UI changes should track the same shared product contract as `cli.py` and
`server/cli_client.py`. New user-facing options should be added through shared
schemas/metadata first, then surfaced in both CLI and UI adapters.

The shared slash-command contract now lives in `src/platform/command_catalog.py`
and is served to the web UI through `GET /console/commands?mode=query|ingest`.
This keeps `/` command names/descriptions consistent across:

- terminal `cli.py`,
- terminal `server/cli_client.py`,
- web console slash-command helper inputs.

Command intent dispatch for web console now uses:

- `POST /console/command` with `{mode, command, arg, state}`
- response includes normalized `{intent, action, data, message}` payload

This allows the frontend to remain a renderer/adapter while command semantics
stay centralized in backend logic.

## Conversation UX

The Query tab includes a left chat pane with:

- conversation list (`GET /console/conversations`),
- create new chat (`POST /console/conversations/new`),
- turn history (`GET /console/conversations/{id}/history`),
- manual compact (`POST /console/conversations/{id}/compact`).

Query requests pass `conversation_id` and `memory_enabled` so the backend can
apply tenant-persistent memory and return `conversation_id` on each response.

## TypeScript Scalability Guidance

For long-term UI growth, TypeScript is recommended (type-safe payloads, easier
refactors, and better editor/tooling support). Keep current HTML/JS for speed
while scope is small, then migrate incrementally:

1. introduce a typed frontend build (`ui/` with TS + lightweight framework),
2. generate/derive API types from server schemas where possible,
3. preserve `/console` and `/console/admin` route behavior while swapping static asset build output.
