# NVIDIA OpenShell Integration — Specification

> Secure sandboxed execution for autonomous AI agents in the RAG stack.

## 1. Overview

### 1.1 What Is OpenShell?

NVIDIA OpenShell is an open-source (Apache 2.0) runtime environment for executing autonomous AI agents inside secure, sandboxed environments with kernel-level isolation. Released at GTC in March 2026, it provides a deny-by-default security model that prevents agents from accessing anything not explicitly allowed — regardless of what happens inside the agent process.

**Repository:** [github.com/NVIDIA/OpenShell](https://github.com/NVIDIA/OpenShell)
**Documentation:** [docs.nvidia.com/openshell](https://docs.nvidia.com/openshell/latest/index.html)
**License:** Apache 2.0

### 1.2 Why This Document Exists

Our RAG stack runs multiple autonomous components — Temporal workers processing user queries with GPU models, an MCP adapter exposing admin operations, and a LangGraph deep agent executing multi-step research with external tools. These components currently run in standard Docker containers with application-level guardrails only. This specification evaluates OpenShell as a kernel-level security layer to harden the stack against prompt injection, credential leakage, unauthorized network access, and data exfiltration.

---

## 2. Three-Layer Security Architecture

OpenShell implements three distinct security layers, each addressing a different class of risk:

### 2.1 Layer 1 — Deny-by-Default Sandbox

**Technology:** Linux Landlock LSM (Linux Security Module)

Creates ephemeral execution environments where agent-generated code runs in restricted spaces. Everything is blocked unless explicitly allowed in a YAML policy file.

| Dimension | What It Controls |
|-----------|-----------------|
| Filesystem | Which paths agents can read/write (per-process granularity) |
| Network | Which hosts/ports agents can connect to (allowlist only) |
| Process | Which binaries can be executed, whether `exec` is permitted |

**Key property:** These restrictions are enforced at the kernel level. Even if the agent process is fully compromised (e.g., via prompt injection leading to arbitrary code execution), the attacker inherits the sandbox constraints — they cannot access paths, hosts, or syscalls not in the policy.

### 2.2 Layer 2 — Out-of-Process Policy Engine

**Critical architectural innovation:** Policy enforcement runs in a separate process, outside the agent's address space. The agent cannot access or modify its own constraints, even if fully compromised.

The policy engine enforces constraints across four domains:

1. **Filesystem isolation** — Controls which files/directories agents can access
2. **Network policies** — Restricts outbound connections to approved destinations
3. **Process restrictions** — Blocks privilege escalation and dangerous syscalls
4. **Inference routing** — Directs model API calls to controlled backends

Policies are declared as YAML files with:
- **Static sections** (filesystem, process) — locked at sandbox creation
- **Dynamic sections** (network, inference) — can be hot-reloaded without sandbox restart

**Comparison to current in-process guardrails:**

| Aspect | NeMo Guardrails (current) | OpenShell Policy Engine |
|--------|--------------------------|------------------------|
| Runs in | Same process as agent | Separate process |
| Agent can bypass | Theoretically yes (same address space) | No (separate address space) |
| Enforcement level | Application (Python) | Kernel (Landlock LSM) |
| Scope | LLM input/output filtering | Filesystem, network, process, inference |

### 2.3 Layer 3 — Privacy Router

Intercepts inference API calls and makes routing decisions based on data classification:

- **Sensitive data** (PII, regulated content, tenant-specific) → routed to local models (Nemotron) that never leave the infrastructure
- **General queries** → routed to frontier models (Claude, GPT) via cloud APIs

**Composition with existing LiteLLM Router:**

```
Application code → LiteLLM Router (alias resolution, load balancing)
                 → OpenShell Privacy Router (data classification)
                 → Local Nemotron | Cloud API
```

The LiteLLM Router continues handling operational routing. OpenShell operates at the network interception layer below it.

---

## 3. What OpenShell Does for Each Component

### 3.1 Temporal Workers (`server/worker.py`)

**Current state:** Workers run in Docker containers (`containers/Dockerfile.runtime`) with access to mounted volumes (`/models:ro`, `/seed_weaviate:ro`), outbound network to Temporal, Redis, Ollama, and Langfuse. No kernel-level restrictions exist — the worker process can access any path in the container and reach any network host.

**With OpenShell:**

| Resource | Access | Policy Rule |
|----------|--------|-------------|
| `/app` (application code) | Read-only | Filesystem allow |
| `/models/baai/bge-m3`, `/models/baai/bge-reranker-v2-m3` | Read-only | Filesystem allow |
| `/tmp/rag-weaviate-$HOSTNAME` | Read-write | Filesystem allow |
| `temporal:7233` | TCP | Network allow |
| `rag-redis:6379` | TCP | Network allow |
| `host.docker.internal:11435` (Ollama) | TCP | Network allow |
| Everything else | Denied | Default deny |

**Impact:** If a prompt injection causes the worker to execute unintended code, that code cannot:
- Read other tenants' Weaviate data (each worker has its own data directory)
- Reach external hosts for data exfiltration
- Execute arbitrary binaries
- Access credentials on the filesystem

### 3.2 MCP Adapter (`server/mcp_adapter.py`)

**Current state:** The adapter runs over stdio transport, makes HTTP calls to the FastAPI backend. Admin tools (`admin_create_api_key`, `admin_revoke_api_key`, `admin_list_api_keys`, `admin_set_tenant_quota`, `admin_delete_tenant_quota`) are gated by an environment variable (`RAG_MCP_ENABLE_ADMIN_TOOLS`) but have no human approval step.

**With OpenShell:**

| Enhancement | Description |
|-------------|-------------|
| Network restriction | Only `rag-api:8000` allowed — cannot reach any other service |
| Human-in-the-loop | Admin tool calls (`admin_*`) require human approval before execution |
| Credential injection | `RAG_MCP_API_KEY` and `RAG_MCP_BEARER_TOKEN` injected ephemerally — never on filesystem |
| Approval timeout | 120-second window for human approval, then denied by default |

### 3.3 Deep Agent (`langchain-deep-agent/agent/graph.py`)

**Current state:** The LangGraph agent executes a planner loop (up to `max_iterations: 10`) with external tool calls to Tavily web search, Wikipedia, and a calculator. It sends all queries to Anthropic's cloud API (`claude-opus-4-6` for planner, `claude-haiku-4-5-20251001` for router). No network restrictions — the agent can reach any host.

**With OpenShell:**

| Resource | Access | Policy Rule |
|----------|--------|-------------|
| `api.anthropic.com:443` | HTTPS | Network allow |
| `api.tavily.com:443` | HTTPS | Network allow |
| `en.wikipedia.org:443` | HTTPS | Network allow |
| `rag-api:8000` | HTTP | Network allow |
| Agent code `/app` | Read-only | Filesystem allow |
| Everything else | Denied | Default deny |

**Additional protections:**
- Iteration limit enforced at policy level (12) as a backstop to the app-level `max_iterations: 10`
- Privacy Router can route queries containing PII to local Nemotron instead of Anthropic cloud
- Admin tool calls on the RAG backend trigger human-in-the-loop approval

### 3.4 Credential Management (All Components)

**Current state:** Secrets are passed as environment variables in `docker-compose.yml`:

| Secret | Current Location |
|--------|-----------------|
| `POSTGRES_PASSWORD` | `docker-compose.yml` line 24 (plaintext: `temporal`) |
| `LANGFUSE_SECRET_KEY` | Env var passthrough |
| `LANGFUSE_PUBLIC_KEY` | Env var passthrough |
| `RAG_MCP_API_KEY` | Env var in adapter process |
| `RAG_MCP_BEARER_TOKEN` | Env var in adapter process |
| `LANGFUSE_REDIS_AUTH` | Env var (default: `myredissecret`) |
| `LANGFUSE_ENCRYPTION_KEY` | Env var (default: all zeros) |
| `GRAFANA_ADMIN_PASSWORD` | Env var (default: `admin`) |
| `MINIO_ROOT_PASSWORD` | Env var (default: `miniosecret`) |

These are visible via `docker inspect`, readable from `/proc/*/environ` inside containers, and stored in Docker's layer cache.

**With OpenShell:**

OpenShell's credential manager uses named provider bundles that inject secrets as ephemeral environment variables at runtime. Credentials never appear on the container filesystem, in Docker layer caches, or in `docker inspect` output.

---

## 4. Business Justification — Why IT/Company Needs This

### 4.1 Compliance & Regulatory

**SOC 2 / ISO 27001:** Audits require demonstrable access controls. Currently, our evidence is "Docker containers with application-level auth" — this is weak evidence. OpenShell provides:
- Kernel-level enforcement with YAML policies (reviewable, version-controlled)
- Full audit trails of every file access, network connection, and process creation
- Out-of-process policy enforcement (tamper-resistant)

**Data Residency:** The Privacy Router provides provable data routing for regulated workloads:
- Healthcare tenant data (`tenant_id: healthcare-*`) can be policy-mandated to route to local Nemotron
- PII detected by NeMo Guardrails can be automatically redirected away from cloud APIs
- Routing decisions are logged in the audit trail for compliance evidence

**GDPR / Data Protection:** The deny-by-default model ensures agents cannot access data outside their explicit allowlist — this is a stronger position than "we configured our app not to" for data protection inquiries.

### 4.2 Security Posture

**Multi-tenant isolation:** The current stack trusts application-level tenant isolation (`src/platform/security/auth.py`). A prompt injection that escapes the LLM sandbox could access:
- Another tenant's data in Redis (conversation memory)
- Another tenant's vectors in Weaviate (embedded mode, shared data directory)
- Outbound network for data exfiltration

OpenShell adds kernel-level barriers: each worker's Weaviate data directory (`/tmp/rag-weaviate-$HOSTNAME`) is the only writable path, and network access is limited to known services.

**Credential security:** Environment variables containing secrets are readable by any process in the container. OpenShell's ephemeral credential injection eliminates this attack surface.

**Admin operation safety:** The MCP adapter's admin tools can create/revoke API keys and modify tenant quotas. Currently, the only gate is an environment variable flag (`RAG_MCP_ENABLE_ADMIN_TOOLS`). OpenShell adds mandatory human approval for these operations.

### 4.3 Operational Risk Reduction

**Blast radius bounding:** As agents gain autonomy (10-iteration planner loops, external tool calls, web search), the potential damage from a failure or attack grows. OpenShell bounds the blast radius at the kernel level — a compromised agent cannot do more than the policy allows.

**Audit trail:** Fills the observability gap between:
- Langfuse (LLM-level tracing — what the model said)
- Prometheus (infrastructure metrics — CPU, memory, latency)
- **Missing:** What the agent actually accessed at the OS level

OpenShell's audit exporter provides kernel-level event logs: file accesses, network connections, process creations, credential usage, and policy violations.

**Incident response:** When a security event occurs, the audit trail provides:
- Which files were accessed
- Which network connections were made
- Which credentials were used
- Which policy rules were triggered or violated
- Timeline correlation with Langfuse traces and Prometheus metrics

### 4.4 Insurance & Liability

As autonomous agents operate with increasing authority (creating API keys, modifying quotas, executing web searches), demonstrable security controls reduce liability exposure. OpenShell provides:
- Documented, version-controlled security policies
- Kernel-level enforcement (not "we asked the AI nicely")
- Human-in-the-loop approval for high-stakes operations
- Full audit trails for post-incident analysis

---

## 5. Pros and Cons

### 5.1 Pros

| Advantage | Detail |
|-----------|--------|
| **Defense in depth** | Kernel-level isolation layered on existing NeMo Guardrails and custom guardrails — multiple independent security layers |
| **Agent-agnostic** | Works with Temporal workers, LangGraph agents, and MCP adapters without modifying agent code |
| **Policy as code** | YAML policies are version-controlled, code-reviewable, and CI-testable alongside application code |
| **Hot-reload** | Dynamic policy sections (network, inference routing) can be updated on running sandboxes without restart |
| **Composable privacy routing** | Complements LiteLLM Router at a lower layer — no changes to existing routing config needed |
| **Audit trail** | Fills the gap between Langfuse (LLM tracing) and Prometheus (infra metrics) with security events |
| **Open source** | Apache 2.0 — no licensing cost, full source access, no vendor lock-in on software |
| **Enterprise momentum** | Adobe, Atlassian, Cisco, SAP, Salesforce, Siemens already testing; security vendor partnerships with CrowdStrike, TrendAI |
| **Credential hardening** | Eliminates filesystem-based secret exposure with ephemeral injection model |

### 5.2 Cons

| Risk | Detail | Mitigation |
|------|--------|------------|
| **NVIDIA GPU dependency** | Privacy Router requires NVIDIA GPUs for local Nemotron inference. Current Ollama setup may run on CPU. | Phases 1-2 require no GPU. Privacy Router (Phase 3) is deferrable. |
| **K3s overhead** | OpenShell runs K3s inside Docker — qualitative jump from pure Docker Compose to embedded Kubernetes. | Team training; K3s is lightweight; single-container deployment. |
| **Maturity risk** | Released March 2026 — approximately 2 weeks old. No production track record, sparse community docs. | Start with POC in dev environment; audit-only mode before enforcement. |
| **Performance overhead** | Landlock LSM adds per-syscall overhead. Needs benchmarking. | GPU-bound workloads unlikely impacted; benchmark API path specifically. |
| **Debugging complexity** | Deny-by-default produces cryptic `EACCES` errors. | Audit-only mode for initial discovery; policy development training. |
| **Privileged containers** | K3s requires `privileged: true` or specific capabilities. | Isolate OpenShell on dedicated host; remove Docker socket sharing from Dozzle. |
| **Learning curve** | Landlock, K3s networking, YAML policy schema are new operational surfaces. | Phase 1 POC as team learning exercise; start with permissive policy. |
| **Docker-in-Docker** | K3s inside Docker may conflict with existing Docker socket sharing (Dozzle monitoring). | Dedicated network namespace; evaluate Dozzle alternatives. |

### 5.3 What OpenShell Does NOT Do

- **Does not replace NeMo Guardrails** — OpenShell enforces OS-level constraints; NeMo Guardrails handle LLM input/output content filtering. Both are needed.
- **Does not replace application-level auth** — Tenant isolation in `src/platform/security/auth.py` remains the primary access control. OpenShell adds a kernel-level backstop.
- **Does not replace Langfuse** — Langfuse traces LLM calls and token usage. OpenShell traces OS-level actions. They are complementary.
- **Does not handle model safety** — Prompt injection detection, toxicity filtering, and content moderation are separate concerns.

---

## 6. Security Model — Before and After

### 6.1 Current Model (Permissive Container)

```
┌─────────────────────────────────────────────────┐
│                Docker Container                  │
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │ Agent    │  │ NeMo     │  │ Credentials  │  │
│  │ Process  │──│ Guard-   │  │ (env vars,   │  │
│  │          │  │ rails    │  │  /proc/*/env)│  │
│  └──────────┘  └──────────┘  └──────────────┘  │
│       │ (same address space)       │             │
│       │ Full filesystem access     │             │
│       │ Full network access        │             │
│       │ Full process spawning      │             │
└───────│────────────────────────────│─────────────┘
        ▼                            ▼
   Any host/port              docker inspect
```

### 6.2 Target Model (Deny-by-Default with OpenShell)

```
┌─────────────────────────────────────────────────────────┐
│                    OpenShell Container                    │
│  ┌────────────────────────────────┐                      │
│  │     Policy Engine (OOP)        │ ← separate process   │
│  │  ┌────────┐  ┌─────────────┐  │                      │
│  │  │ YAML   │  │ Audit Log   │  │                      │
│  │  │ Policy │  │ Exporter    │  │                      │
│  │  └────────┘  └─────────────┘  │                      │
│  └────────────────────────────────┘                      │
│           │ enforces                                     │
│  ┌────────▼───────────────────────┐                      │
│  │  Landlock Sandbox              │                      │
│  │  ┌──────────┐  ┌──────────┐   │                      │
│  │  │ Agent    │  │ NeMo     │   │                      │
│  │  │ Process  │  │ Guard-   │   │                      │
│  │  │          │  │ rails    │   │                      │
│  │  └──────────┘  └──────────┘   │                      │
│  │  Filesystem: allowlist only   │                      │
│  │  Network: allowlist only      │                      │
│  │  Process: allowlist only      │                      │
│  │  Credentials: ephemeral only  │                      │
│  └────────────────────────────────┘                      │
│                                                          │
│  ┌────────────────────────────────┐                      │
│  │     Privacy Router             │                      │
│  │  PII → Local Nemotron          │                      │
│  │  General → Cloud API           │                      │
│  └────────────────────────────────┘                      │
└──────────────────────────────────────────────────────────┘
```

### 6.3 Surface-by-Surface Comparison

| Attack Surface | Before (Permissive) | After (OpenShell) |
|---------------|--------------------|--------------------|
| **Filesystem** | Docker volumes, `:ro` on some mounts. Worker writes anywhere in container. | Landlock LSM per-process rules. Only explicitly allowed paths accessible. |
| **Network** | Docker network — all containers can reach each other and external hosts. | Per-sandbox allowlist. Worker reaches Temporal, Redis, Ollama only. |
| **Process** | No restrictions. Any binary can be executed. | Binary allowlist + exec denial. Python only. |
| **Credentials** | Env vars visible in `/proc/*/environ` and `docker inspect`. | Ephemeral injection. No filesystem presence. Not in inspect output. |
| **LLM routing** | Application-level (LiteLLM Router). All data goes to configured provider. | Privacy Router with data classification. PII routed to local models. |
| **Guardrails** | In-process (NeMo, custom). Same address space as agent. | Out-of-process policy engine. Separate address space, tamper-resistant. |
| **Audit** | Application logging (Langfuse). Traces LLM calls only. | Kernel-level syscall audit. Every file, network, process event logged. |

---

## 7. Cost and Resource Impact

### 7.1 Compute Requirements

| Component | Additional CPU | Additional RAM | GPU |
|-----------|---------------|----------------|-----|
| K3s control plane | 1-2 cores | 1-2 GB | None |
| Policy Engine | 0.5 core | 256 MB | None |
| Landlock overhead | Negligible | Negligible | None |
| Audit log collector | 0.5 core | 512 MB | None |
| **Subtotal (Phases 1-2)** | **~2-3 cores** | **~2-3 GB** | **None** |
| Privacy Router + Nemotron | 2-4 cores | 8-16 GB | 24-48 GB VRAM |
| **Subtotal (Phase 3+)** | **+2-4 cores** | **+8-16 GB** | **NVIDIA A10/L4/A100** |

### 7.2 Storage Requirements

| Item | Size |
|------|------|
| OpenShell container image | 3-5 GB |
| Nemotron model files (Phase 3) | 15-30 GB |
| Audit logs | 1-5 GB/month |
| K3s etcd data | ~500 MB |

### 7.3 Cost Estimates

| Scenario | Monthly Cost | One-Time Cost |
|----------|-------------|---------------|
| **Cloud — Phases 1-2** (sandbox only) | +$50-100/mo (CPU/RAM) | $0 |
| **Cloud — Phase 3+** (Privacy Router) | +$800-2000/mo (GPU instance, e.g., AWS `g5.2xlarge`) | $0 |
| **On-premises — Phases 1-2** | $0 | $0 |
| **On-premises — Phase 3+** | $0 | $3,000-15,000 (NVIDIA A10/L4/A100) |

### 7.4 Key Takeaway

Phases 1-2 (kernel sandboxing, credential management, audit trails) deliver most of the security value with minimal cost. The Privacy Router (Phase 3) is the expensive component and should be evaluated based on data residency requirements.

---

## 8. Infrastructure Architecture

### 8.1 Runtime Model

OpenShell runs as a K3s (lightweight Kubernetes) cluster inside a single Docker container. This means:

- No separate Kubernetes installation required
- Deploys alongside existing Docker Compose services
- The K3s cluster manages sandbox lifecycle, policy enforcement, and credential injection
- Agent processes run inside Landlock-sandboxed pods within the K3s cluster

### 8.2 Integration with Docker Compose

A new `openshell` service is added to `docker-compose.yml` under a `sandbox` profile:

```yaml
openshell:
  profiles: ["sandbox"]
  image: nvcr.io/nvidia/openshell:latest
  container_name: rag-openshell
  privileged: true  # Required for K3s
  volumes:
    - ./openshell/policies:/etc/openshell/policies:ro
    - ./openshell/workspace.yaml:/etc/openshell/workspace.yaml:ro
    - ${RAG_MODEL_ROOT:-./models}:/models:ro
    - ./.weaviate_data:/seed_weaviate:ro
  environment:
    - OPENSHELL_POLICY_DIR=/etc/openshell/policies
    - OPENSHELL_AUDIT_EXPORT_PROMETHEUS=true
    - OPENSHELL_AUDIT_PROMETHEUS_PORT=9102
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: all
            capabilities: [gpu]
  ports:
    - "9102:9102"  # Audit metrics
  depends_on:
    - temporal
    - rag-redis
  restart: unless-stopped
  extra_hosts:
    - "host.docker.internal:host-gateway"
```

**Profile-based rollout:** Teams can enable OpenShell independently:
```bash
# Without OpenShell (current behavior)
./scripts/compose.sh --profile workers up -d

# With OpenShell
./scripts/compose.sh --profile workers --profile sandbox up -d
```

### 8.3 Observability Integration

OpenShell's audit exporter integrates with the existing monitoring stack:

| System | Integration | Port |
|--------|-------------|------|
| Prometheus | Scrape OpenShell metrics at `:9102/metrics` | 9102 |
| Grafana | Dashboard for policy violations, routing decisions, approval gates | — |
| Langfuse | Correlate audit events with LLM trace IDs | — |
| AlertManager | Alert on policy violation spikes, potential sandbox escapes | — |

**New Prometheus metrics:**
- `openshell_policy_violations_total{policy, rule, action}`
- `openshell_sandbox_syscall_denials_total{sandbox, syscall}`
- `openshell_inference_routes_total{source_model, destination, reason}`
- `openshell_approval_gates_total{gate, outcome}`
- `openshell_credential_access_total{credential, accessor}`

**New alert rules:**
- Policy violation rate spike (>5/min sustained for 2 minutes)
- Sandbox escape attempt (blocked `execve` or `ptrace` syscalls)

---

## 9. Enterprise Context

### 9.1 Industry Adoption

Organizations already testing or deploying OpenShell: Adobe, Atlassian, Amdocs, Box, Cadence, Cisco, Cohesity, CrowdStrike, Dassault Systèmes, IQVIA, Red Hat, SAP, Salesforce, Siemens, ServiceNow, Synopsys.

### 9.2 Security Vendor Partnerships

- **Cisco AI Defense** — Policy integration for enterprise agent networks
- **CrowdStrike** — Threat detection integration with sandbox audit trails
- **TrendAI (Trend Micro)** — Real-time threat monitoring for sandboxed agents
- **Google / Microsoft Security** — Cross-platform policy federation

### 9.3 Ecosystem

- **OpenShell-Community** ([github.com/NVIDIA/OpenShell-Community](https://github.com/NVIDIA/OpenShell-Community)) — Community-contributed skills, sandbox images, integrations
- **NemoClaw** ([github.com/NVIDIA/NemoClaw](https://github.com/NVIDIA/NemoClaw)) — NVIDIA plugin for secure OpenClaw deployment with OpenShell
- **LangChain integration** — Official partnership for agent development platform integration

---

## 10. Migration Strategy

### 10.1 Phased Approach

1. **Audit-only mode** (Weeks 1-2) — Deploy OpenShell, log all violations, do not block anything
2. **Analyze patterns** — Review audit logs to discover all legitimate access patterns
3. **Build allowlist** — Construct YAML policies from observed behavior
4. **Enforcement mode** — Switch from logging to blocking
5. **Emergency fallback** — Keep audit-only mode available via policy hot-reload

### 10.2 Rollback Plan

OpenShell runs as a separate compose profile. Rollback is:
```bash
./scripts/compose.sh --profile workers up -d  # without --profile sandbox
```

No application code changes are required. The only difference is whether agents run inside OpenShell sandboxes or in standard containers.
