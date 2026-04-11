# @summary
# Security helpers package (auth, RBAC, tenancy, secrets, key/quota stores).
# Exports: (package)
# Deps: (none)
# @end-summary
"""Security helpers for auth, RBAC, tenancy, and secrets."""

# --- Auto-generated re-exports (fix_encapsulation.py) ---
from src.platform.security.api_key_store import (
    create_api_key,
    list_api_keys,
    revoke_api_key,
)
from src.platform.security.auth import (
    Principal,
    authenticate_request,
)
from src.platform.security.quota_store import (
    delete_tenant_quota,
    get_tenant_quota,
    list_quotas,
    set_tenant_quota,
)
from src.platform.security.rbac import require_role
from src.platform.security.tenancy import resolve_tenant_id
