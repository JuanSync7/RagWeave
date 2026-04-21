<!-- @summary
TypeScript source files for the operator console and user console browser UIs. Compiled by `tsc` and emitted as ES modules into `../static/`.
@end-summary -->

# server/console/web/src

Source TypeScript for both console surfaces. Each file compiles 1-to-1 to a `.js` file in `../static/` (relative to `web/`, as configured in `tsconfig.json`). There is no bundling step — the emitted modules are loaded directly by the browser.

## Contents

| Path | Purpose |
| --- | --- |
| `main.ts` | Operator console logic — tab switching, auth headers, fetch helper, conversation management, markdown rendering, rerank table, timing display, slash commands, and admin actions |
| `user-console.ts` | User console logic — sidebar navigation, streaming SSE chat, slash autocomplete, command picker, citation cards, context window indicator, settings panel, and attachment toolbar |
| `types.ts` | Shared TypeScript type definitions used by both consoles — API envelope, conversation types, query/stream types, slash command types, settings, and health summary |
| `vendor.d.ts` | Ambient module declarations for `marked` and `dompurify` — fallback stubs used before `npm install` runs; superseded by the real package types once `node_modules/` exists |
