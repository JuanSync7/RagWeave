<!-- @summary
HTML shell and stylesheet for the end-user chat console. Provides the full single-page application layout — sidebar, message thread, input bar, settings panel, and context window indicator.
@end-summary -->

# server/console/static/user

Static assets for the user-facing RagWeave chat UI, served at `/console/user/`. The page is a single-page application: `index.html` defines all DOM structure and `styles.css` supplies the full visual design including dark/light themes, responsive layout, and component styles.

The compiled JavaScript (`user-console.js`) is loaded from the parent `static/` directory and handles all runtime logic.

## Contents

| Path | Purpose |
| --- | --- |
| `index.html` | SPA shell — sidebar navigation, message thread, input bar with attachment toolbar, settings panel overlay, slash-command dropdown, and command picker |
| `styles.css` | Full UI stylesheet — CSS custom properties for theming (dark/light/system), sidebar layout, message bubbles, citation cards, context window indicator, and responsive breakpoints |
