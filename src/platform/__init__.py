# @summary
# Platform layer for cross-cutting services (security, limits, cache, memory, observability, reliability).
# Exports: (package)
# Deps: (none)
# @end-summary
"""Platform layer for cross-cutting services."""

# --- Auto-generated re-exports (fix_encapsulation.py) ---
from src.platform.cli_interactive import (
    get_input_with_menu,
    setup_tab_completion,
)
from src.platform.command_catalog import (
    MODE_CONSOLE_INGEST,
    MODE_CONSOLE_QUERY,
    MODE_SERVER_CLI,
    get_command_spec,
    list_command_specs,
    to_payload,
)
from src.platform.command_runtime import dispatch_slash_command
from src.platform.metrics import (
    CACHE_HITS,
    CACHE_MISSES,
    INFLIGHT_REQUESTS,
    MEMORY_OP_MS,
    MEMORY_SUMMARY_TRIGGERS,
    OVERLOAD_REJECTS,
    PIPELINE_STAGE_MS,
    RATE_LIMIT_REJECTS,
    REQUESTS_TOTAL,
    REQUEST_LATENCY_MS,
    render_metrics,
)
from src.platform.timing import (
    TimingPool,
    measure_ms,
)
from src.platform.validation import (
    validate_alpha,
    validate_documents_dir,
    validate_filter_value,
    validate_positive_int,
)
