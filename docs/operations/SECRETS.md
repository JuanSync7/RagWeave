# Secrets Management

## Contract
- Runtime secrets must be loaded via environment variables or `*_FILE`.
- Local `.env` is for development only and must not contain production credentials.

## Required Secrets
- `RAG_AUTH_JWT_HS256_SECRET`
- `LANGFUSE_SECRET_KEY`
- `LANGFUSE_NEXTAUTH_SECRET`
- `LANGFUSE_ENCRYPTION_KEY`

## Rotation
- Rotate API keys and JWT secret every 90 days.
- On rotation, restart `rag-api` and `rag-worker` services.
- Validate with `/health` and one authenticated query.

