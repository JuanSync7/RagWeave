<!-- @summary
Security services: API key auth, JWT/OIDC bearer token validation, RBAC, tenant identity, quota management, and secrets handling.
@end-summary -->

# platform/security

## Overview

This package provides all authentication, authorization, and tenancy services for the API layer.

## Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `auth.py` | API key + JWT/OIDC bearer token request authentication | `Principal`, `authenticate_request` |
| `api_key_store.py` | Persistent API key lifecycle (create/revoke/lookup), JSON-file backed with SHA-256 hashing | `create_api_key`, `list_api_keys`, `revoke_api_key`, `lookup_api_key` |
| `quota_store.py` | Per-tenant quota storage and enforcement, JSON-file backed | `get_quota`, `set_quota`, `delete_quota`, `check_quota` |
| `rbac.py` | Role-based access control helpers | `require_role` |
| `tenancy.py` | Tenant identity helpers and request context | `TenantContext`, `get_tenant_id` |
| `secrets.py` | Secrets loading helpers for API key resolution | (loader functions) |
| `__init__.py` | Package facade | re-exports from `auth.py` |

## Auth Modes

1. **API keys** — static JSON config (`RAG_AUTH_API_KEYS_JSON`) or managed file store (`RAG_AUTH_API_KEYS_STORE_PATH`)
2. **HS256 JWT** — local shared secret (`RAG_AUTH_JWT_HS256_SECRET`)
3. **OIDC bearer tokens** — issuer/audience/JWKS validation (`RAG_AUTH_OIDC_*`)

Set `RAG_AUTH_API_KEYS_REQUIRED=true` to enforce authentication on all endpoints. Admin endpoints always require an `admin` role regardless.

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `RAG_AUTH_API_KEYS_REQUIRED` | `false` | Enforce auth on all endpoints |
| `RAG_AUTH_API_KEYS_JSON` | `{}` | Static API key map |
| `RAG_AUTH_API_KEYS_STORE_PATH` | `.runtime/security/api_keys.json` | Managed key store path |
| `RAG_AUTH_JWT_ENABLED` | `false` | Enable HS256 JWT validation |
| `RAG_AUTH_OIDC_ENABLED` | `false` | Enable OIDC bearer token validation |
| `RAG_DEFAULT_TENANT_ID` | `default` | Default tenant when auth is disabled |
