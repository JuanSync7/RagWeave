<!-- @summary
Compiled browser assets for the operator console and user console UIs. Contains the HTML entry points, TypeScript-compiled JavaScript modules, and the user-facing subdirectory.
@end-summary -->

# server/console/static

Browser-ready assets served by the console server. The TypeScript sources live in `../web/src/` and are compiled into this directory. The operator console (`console.html` + `main.js`) and the user console (`user/`) are kept at separate paths so the server can route them independently.

## Contents

| Path | Purpose |
| --- | --- |
| `console.html` | Operator console HTML entry point — tabbed UI for query, ingest, health, and admin |
| `main.js` | Compiled operator console logic — typed fetch helpers, tab management, conversation management, markdown rendering, and timing display |
| `types.js` | Compiled shared type stubs (no runtime exports; TypeScript-only) |
| `user-console.js` | Compiled user console logic — sidebar, streaming chat, slash commands, settings, and citation rendering |
| `user/` | User-facing console: HTML shell and CSS for the chat UI |
