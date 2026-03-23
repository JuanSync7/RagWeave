# NVIDIA OpenShell Integration — Implementation Guide

> Phased rollout plan for sandboxing the RAG stack with OpenShell.

## Prerequisites

- Docker 24+ with Docker Compose v2
- Linux host with kernel 5.13+ (Landlock LSM support)
- NVIDIA Container Toolkit (for GPU access in Phase 3)
- Access to NVIDIA Container Registry (`nvcr.io`)

---

## Phase 1: POC — Sandboxed RAG Worker (Weeks 1-3)

### Objective

Run the existing Temporal worker inside OpenShell with a deny-by-default policy. Validate that all existing workflows pass with no functional regression and measure latency overhead.

### 1.1 Install OpenShell

```bash
# Pull the OpenShell container image
docker pull nvcr.io/nvidia/openshell:latest

# Verify Landlock support on host kernel
cat /sys/kernel/security/landlock/abi_version
# Expected: 3 or higher
```

### 1.2 Create Directory Structure

```bash
mkdir -p RAG/openshell/policies
```

### 1.3 Create Workspace Configuration

Create `RAG/openshell/workspace.yaml` — defines the sandboxed workloads:

```yaml
# openshell/workspace.yaml
apiVersion: openshell.nvidia.com/v1
kind: Workspace
metadata:
  name: rag-stack
spec:
  sandboxes:
    - name: rag-worker
      image: rag-worker:latest  # Built from docker/Dockerfile.runtime
      policy: /etc/openshell/policies/rag-worker.yaml
      command: >
        sh -lc '
        WORKER_WV_DIR="/tmp/rag-weaviate-$$HOSTNAME" &&
        if [ -d "/seed_weaviate" ] && [ ! -d "$$WORKER_WV_DIR" ]; then
          cp -a /seed_weaviate "$$WORKER_WV_DIR";
        fi &&
        export RAG_WEAVIATE_DATA_DIR="$$WORKER_WV_DIR" &&
        python -m server.worker
        '
      replicas: 1
      resources:
        gpu: optional
```

### 1.4 Write RAG Worker Policy

Create `RAG/openshell/policies/rag-worker.yaml` — see `openshell/policies/rag-worker.yaml` for the full policy file.

### 1.5 Add OpenShell to Docker Compose

Add the following service to `docker-compose.yml`:

```yaml
openshell:
  profiles: ["sandbox"]
  image: nvcr.io/nvidia/openshell:latest
  container_name: rag-openshell
  privileged: true
  volumes:
    - ./openshell/policies:/etc/openshell/policies:ro
    - ./openshell/workspace.yaml:/etc/openshell/workspace.yaml:ro
    - ${RAG_MODEL_ROOT:-./models}:/models:ro
    - ./.weaviate_data:/seed_weaviate:ro
  environment:
    - OPENSHELL_POLICY_DIR=/etc/openshell/policies
    - OPENSHELL_AUDIT_EXPORT_PROMETHEUS=true
    - OPENSHELL_AUDIT_PROMETHEUS_PORT=9102
  ports:
    - "9102:9102"
  depends_on:
    - temporal
    - rag-redis
  restart: unless-stopped
  extra_hosts:
    - "host.docker.internal:host-gateway"
```

### 1.6 Start in Audit-Only Mode

```bash
# Start infrastructure + OpenShell
docker compose --profile workers --profile sandbox up -d

# Monitor audit logs for violations (no blocking yet)
docker logs -f rag-openshell 2>&1 | grep "VIOLATION"
```

### 1.7 Iterative Policy Tightening

1. Run with `enforcement: audit_only` in the policy for 1-2 weeks
2. Analyze violation logs to discover legitimate access patterns
3. Add missing allowlist entries
4. Switch to `enforcement: deny` when violations stabilize to zero

### 1.8 Validate

```bash
# Run existing test suite against sandboxed worker
pytest tests/ingest/ tests/ -v

# Compare latency (check Prometheus dashboard)
# Metric: rag_pipeline_stage_ms histogram
# Acceptance: < 5% overhead vs non-sandboxed baseline
```

### Success Criteria

- [ ] All Temporal workflows pass with deny-by-default policy active
- [ ] Latency overhead < 5% on `rag_pipeline_stage_ms`
- [ ] Zero audit violations in production traffic pattern
- [ ] Policy YAML committed to version control and reviewed

---

## Phase 2: Deep Agent Sandboxing (Weeks 4-5)

### Objective

Run the LangGraph deep agent inside OpenShell with tool-level network controls and human-in-the-loop gates.

### 2.1 Create Deep Agent Policy

Create `langchain-deep-agent/openshell/policies/deep-agent.yaml` — see the policy file for full content.

Key policy decisions:
- Network restricted to: `api.anthropic.com:443`, `api.tavily.com:443`, `en.wikipedia.org:443`, `rag-api:8000`
- Filesystem: read-only to `/app`, write only to `/tmp`
- Iteration backstop: 12 (above app-level 10, catches runaway loops)
- Human approval required for any request to admin endpoints

### 2.2 Create Deep Agent Workspace

Create `langchain-deep-agent/openshell/workspace.yaml`:

```yaml
apiVersion: openshell.nvidia.com/v1
kind: Workspace
metadata:
  name: deep-agent
spec:
  sandboxes:
    - name: deep-agent
      image: deep-agent:latest
      policy: /etc/openshell/policies/deep-agent.yaml
      command: python -m agent.main
      replicas: 1
```

### 2.3 Validate

Test each route under sandbox:

```bash
# Test all four routes from config.yaml
python -m agent.main --query "What does our internal documentation say about auth?" # rag route
python -m agent.main --query "Research the latest developments in quantum computing" # research route
python -m agent.main --query "What is the capital of France?" # quick_answer route
python -m agent.main --query "Calculate 2^256" # tool_use route
```

Verify unauthorized network access is blocked:

```bash
# This should be blocked and logged by OpenShell
# (simulate by temporarily adding a tool that tries to reach an unauthorized host)
```

### Success Criteria

- [ ] All four routes (rag, research, quick_answer, tool_use) function identically
- [ ] Unauthorized network access attempts are logged and blocked
- [ ] Admin tool calls trigger human-in-the-loop approval
- [ ] Iteration backstop correctly terminates runaway loops (test with `max_iterations: 15`)

---

## Phase 3: Privacy Router Integration (Weeks 6-8)

### Objective

Deploy Nemotron locally and configure data-classification-based inference routing.

### 3.1 Deploy Nemotron

```bash
# Requires NVIDIA GPU with 24+ GB VRAM
# Option A: Via Ollama
ollama pull nemotron-mini

# Option B: Via NVIDIA NGC
docker pull nvcr.io/nvidia/nemotron-mini:latest
```

### 3.2 Configure Privacy Router Policy

Add inference routing rules to `RAG/openshell/policies/privacy-router.yaml`:

```yaml
apiVersion: openshell.nvidia.com/v1
kind: InferencePolicy
metadata:
  name: rag-privacy-router
spec:
  rules:
    - name: pii-local-routing
      match:
        content_contains_pii: true
      action:
        route_to: local
        model: nemotron-mini
        reason: "PII detected — routing to local inference"

    - name: healthcare-tenant-local
      match:
        tenant_id_pattern: "healthcare-*"
      action:
        route_to: local
        model: nemotron-mini
        reason: "Healthcare tenant — data residency requirement"

    - name: default-upstream
      match:
        default: true
      action:
        route_to: upstream
        reason: "No sensitive data detected — routing to configured LLM provider"

  local_inference:
    endpoint: http://host.docker.internal:11434
    model: nemotron-mini
    timeout_seconds: 120
```

### 3.3 Composition with LiteLLM Router

The existing `config/llm_router.yaml` does not change. OpenShell intercepts outbound inference API calls at the network level:

```
Agent code → LiteLLM Router (alias resolution) → Network layer
                                                    ↓
                                          OpenShell Privacy Router
                                                    ↓
                                    ┌───────────────┴───────────────┐
                                    ▼                               ▼
                             Local Nemotron                   Cloud API
                          (PII/regulated data)          (general queries)
```

### 3.4 Validate

```bash
# Test PII routing — should route to local Nemotron
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Find records for patient John Smith SSN 123-45-6789"}'

# Check audit log for routing decision
docker logs rag-openshell 2>&1 | grep "inference_route"
# Expected: route_to=local, reason="PII detected"

# Test general query — should route to cloud
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the architecture of the ingestion pipeline?"}'

# Check audit log
# Expected: route_to=upstream, reason="No sensitive data detected"
```

### Success Criteria

- [ ] PII-containing queries route to local Nemotron
- [ ] Tenant-specific queries (healthcare) route to local
- [ ] General queries route to cloud providers (no change)
- [ ] All routing decisions logged in audit trail
- [ ] Nemotron response quality acceptable for sandboxed queries

---

## Phase 4: Credential Management & MCP Hardening (Weeks 9-10)

### Objective

Migrate all secrets from environment variables to OpenShell's credential injection model. Add human-in-the-loop approval for MCP admin operations.

### 4.1 Inventory Current Secrets

Secrets currently in `docker-compose.yml` environment blocks:

| Secret | Service | Current Default |
|--------|---------|----------------|
| `POSTGRES_PASSWORD` | temporal-db | `temporal` |
| `LANGFUSE_SECRET_KEY` | rag-api, rag-worker | (passthrough) |
| `LANGFUSE_PUBLIC_KEY` | rag-api, rag-worker | (passthrough) |
| `RAG_MCP_API_KEY` | mcp-adapter | (passthrough) |
| `RAG_MCP_BEARER_TOKEN` | mcp-adapter | (passthrough) |
| `LANGFUSE_REDIS_AUTH` | langfuse-redis | `myredissecret` |
| `LANGFUSE_ENCRYPTION_KEY` | langfuse-web/worker | `0000...0000` |
| `GRAFANA_ADMIN_PASSWORD` | grafana | `admin` |
| `MINIO_ROOT_PASSWORD` | langfuse-minio | `miniosecret` |
| `LANGFUSE_POSTGRES_PASSWORD` | langfuse-postgres | `postgres` |

### 4.2 Migrate to OpenShell Credential Store

Add credential definitions to sandbox policies:

```yaml
credentials:
  inject:
    - name: LANGFUSE_SECRET_KEY
      source: vault://rag/langfuse-secret
    - name: LANGFUSE_PUBLIC_KEY
      source: vault://rag/langfuse-public
    - name: RAG_MCP_API_KEY
      source: vault://rag/mcp-api-key
    - name: RAG_MCP_BEARER_TOKEN
      source: vault://rag/mcp-bearer-token
  filesystem_leakage: deny
```

### 4.3 Create MCP Adapter Policy

Create `RAG/openshell/policies/mcp-adapter.yaml` with:
- Network: only `rag-api:8000` allowed
- Human-in-the-loop for `admin_*` tool calls (120-second approval window)
- Credential injection for API key and bearer token

### 4.4 Remove Plaintext Secrets

After validating credential injection works:
1. Remove hardcoded passwords from `docker-compose.yml` environment blocks
2. Replace with references to OpenShell credential store
3. Verify with `docker inspect rag-openshell` — no secrets visible

### Success Criteria

- [ ] No secrets visible in `docker inspect` output
- [ ] No secrets in container filesystem (`/proc/*/environ` check)
- [ ] MCP admin tools require human approval before execution
- [ ] All existing functionality works with injected credentials
- [ ] Credential access events appear in audit trail

---

## Phase 5: Production Hardening & Observability (Weeks 11-13)

### Objective

Full monitoring integration, load testing, and operational readiness.

### 5.1 Prometheus Integration

Add scrape target to `ops/prometheus/prometheus.yml`:

```yaml
scrape_configs:
  # ... existing targets ...

  - job_name: "openshell-audit"
    metrics_path: /metrics
    static_configs:
      - targets: ["openshell:9102"]
```

### 5.2 Alert Rules

Add to `ops/prometheus/alerts.yml`:

```yaml
groups:
  - name: openshell
    rules:
      - alert: OpenShellPolicyViolationSpike
        expr: rate(openshell_policy_violations_total[5m]) > 5
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "High rate of OpenShell policy violations ({{ $value }}/s)"
          description: "More than 5 policy violations per second sustained for 2 minutes. Possible attack or misconfigured policy."

      - alert: OpenShellSandboxEscapeAttempt
        expr: openshell_sandbox_syscall_denials_total{syscall=~"execve|ptrace|mount"} > 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Potential sandbox escape attempt detected"
          description: "Blocked dangerous syscall {{ $labels.syscall }} in sandbox {{ $labels.sandbox }}."

      - alert: OpenShellApprovalGateTimeout
        expr: increase(openshell_approval_gates_total{outcome="timeout"}[15m]) > 3
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "Multiple approval gate timeouts"
          description: "{{ $value }} approval gates timed out in 15 minutes. Check if human reviewers are available."
```

### 5.3 Grafana Dashboard

Create `ops/grafana/dashboards/openshell.json` with panels for:

1. **Policy Violations** — Time series of `openshell_policy_violations_total` by policy and rule
2. **Inference Routing** — Pie chart of `openshell_inference_routes_total` by destination (local vs upstream)
3. **Approval Gates** — Bar chart of `openshell_approval_gates_total` by outcome (approved/denied/timeout)
4. **Credential Access** — Table of recent `openshell_credential_access_total` events
5. **Syscall Denials** — Heatmap of `openshell_sandbox_syscall_denials_total` by syscall type

### 5.4 Langfuse Trace Correlation

Correlate OpenShell audit events with Langfuse LLM traces:

1. OpenShell audit logs include inference request IDs
2. Create a Langfuse custom event for each Privacy Router routing decision
3. Link via the parent trace ID so the full path is visible:
   `User query → Guardrail check → Privacy Router decision → LLM response`

### 5.5 Load Testing

```bash
# Run load test against sandboxed stack
# Compare with non-sandboxed baseline

# Tool: locust, k6, or wrk
# Target: POST /query endpoint
# Load: ramp to 60 req/min (current rate limit)
# Duration: 30 minutes sustained
# Metrics to compare:
#   - p50, p95, p99 latency
#   - Error rate
#   - OpenShell policy violation count (should be zero)
```

### 5.6 Runbooks

Create operational runbooks in `docs/openshell/runbooks/`:

1. **Policy Update Procedure** — How to modify, test, and deploy policy changes
2. **Incident Response** — How to investigate policy violations and potential breaches
3. **Emergency Fallback** — How to disable OpenShell and revert to standard containers
4. **Debugging Guide** — How to diagnose `EACCES` errors and Landlock denials
5. **Credential Rotation** — How to rotate secrets in the OpenShell credential store

### Success Criteria

- [ ] Prometheus scrapes OpenShell metrics successfully
- [ ] Grafana dashboard shows all five panel types
- [ ] Alert rules fire correctly on simulated violations
- [ ] Langfuse traces include Privacy Router routing decisions
- [ ] Load test passes at 60 req/min with < 5% latency overhead
- [ ] All five runbooks written and reviewed
- [ ] End-to-end observability: query → sandbox enforcement → LLM response → audit trail

---

## File Summary

### New Files Created

| File | Purpose |
|------|---------|
| `RAG/openshell/workspace.yaml` | OpenShell workspace definition for RAG stack |
| `RAG/openshell/policies/rag-worker.yaml` | Sandbox policy for Temporal worker |
| `RAG/openshell/policies/mcp-adapter.yaml` | Sandbox policy for MCP adapter |
| `RAG/openshell/policies/privacy-router.yaml` | Inference routing rules |
| `RAG/docs/openshell/specification.md` | This specification document |
| `RAG/docs/openshell/implementation-guide.md` | This implementation guide |
| `langchain-deep-agent/openshell/workspace.yaml` | OpenShell workspace for deep agent |
| `langchain-deep-agent/openshell/policies/deep-agent.yaml` | Sandbox policy for LangGraph agent |

### Files Modified

| File | Change |
|------|--------|
| `RAG/docker-compose.yml` | Add `openshell` service under `sandbox` profile |
| `RAG/ops/prometheus/prometheus.yml` | Add OpenShell scrape target |
| `RAG/ops/prometheus/alerts.yml` | Add sandbox violation and escape alerts |

### Rollback

```bash
# Disable OpenShell — no application code changes needed
docker compose --profile workers up -d  # omit --profile sandbox

# Re-enable
docker compose --profile workers --profile sandbox up -d
```
