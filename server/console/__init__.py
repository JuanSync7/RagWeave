# @summary
# Console module exports route builder and console service helpers.
# Exports: create_console_router
# Deps: server.console.routes
# @end-summary
"""Console package exports."""

from server.console.routes import create_console_router

__all__ = ["create_console_router"]
