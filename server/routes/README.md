<!-- @summary
Route modules for the FastAPI server, split by API domain (query, admin, system).
@end-summary -->

# server/routes

## Overview

This package contains domain-oriented FastAPI route builders:

- `query.py`: `/query`, `/query/stream`, and `/metrics`.
- `admin.py`: API-key and quota admin endpoints.
- `system.py`: `/health` and `/` service metadata endpoint.

`server/api.py` remains the app entrypoint, lifecycle owner, and console endpoint host.
