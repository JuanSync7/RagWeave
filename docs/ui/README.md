<!-- @summary
UI and console documentation: CLI spec/implementation, web console spec/design/implementation (User Console + Admin Console), and token budget spec/implementation.
@end-summary -->

# docs/ui

## Overview

Engineering documentation for the CLI client and web console interfaces.

## Files

| File | Purpose |
| --- | --- |
| `CLI_SPEC.md` | CLI client specification |
| `CLI_IMPLEMENTATION.md` | CLI client implementation guide |
| `WEB_CONSOLE_SPEC.md` | Web console specification (User Console at `/console` + Admin Console at `/console/admin`) |
| `WEB_CONSOLE_DESIGN.md` | Web console design document (task decomposition, component contracts) |
| `WEB_CONSOLE_IMPLEMENTATION.md` | Web console implementation guide |
| `TOKEN_BUDGET_SPEC.md` | Token budget specification (counting, context window display) |
| `TOKEN_BUDGET_IMPLEMENTATION.md` | Token budget implementation guide |
| `task-4-1-preview.html` | Visual reference for User Console UI design (Task 4.1 preview mockup) |

## Console URLs

| URL | Interface |
| --- | --- |
| `http://localhost:8000/console` | **User Console** — modern chat interface for end users |
| `http://localhost:8000/console/admin` | **Admin Console** — tabbed debug/ops interface for operators |
