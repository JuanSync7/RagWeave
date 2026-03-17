<!-- @summary
Shared server-common schemas and utility helpers used by API and adapters.
@end-summary -->

# server/common

## Overview

This package contains reusable server-side building blocks:

- `schemas.py`: common API envelope models shared by endpoints and exception handlers.
- `utils.py`: request-id and envelope helper functions used by API handlers.

This keeps `server/api.py` focused on route logic rather than repeated helper code.
