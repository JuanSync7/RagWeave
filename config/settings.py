# @summary
# Centralizes configuration settings for a RAG (Retrieval-Augmented Generation) system.
# Exports: PROJECT_ROOT, DOCUMENTS_DIR, PROCESSED_DIR, EMBEDDING_MODEL_PATH, RERANKER_MODEL_PATH, WEAVIATE_COLLECTION_NAME, HYBRID_SEARCH_ALPHA, SEARCH_LIMIT, RERANK_TOP_K, CHUNK_SIZE, CHUNK_OVERLAP, QUERY_CONFIDENCE_THRESHOLD, MAX_SANITIZATION_ITERATIONS, QUERY_PROCESSING_MODEL, QUERY_MAX_LENGTH, QUERY_PROCESSING_TEMPERATURE, QUERY_LOG_DIR, PROMPTS_DIR, DOMAIN_DESCRIPTION, KG_ENABLED, KG_PATH, SEMANTIC_CHUNKING_ENABLED, GLINER_ENABLED, GENERATION_ENABLED
# Deps: os, pathlib, dotenv
# @end-summary
"""Centralized configuration for the RAG system."""

import os
from pathlib import Path

# --- Project Paths ---
PROJECT_ROOT = Path(__file__).parent.parent
DOCUMENTS_DIR = PROJECT_ROOT / "documents"
PROCESSED_DIR = PROJECT_ROOT / "processed"
RUNTIME_DIR = PROJECT_ROOT / ".runtime"

# --- Model Paths (Local BAAI Models) ---
EMBEDDING_MODEL_PATH = os.environ.get(
    "RAG_EMBEDDING_MODEL",
    os.path.expanduser("~/models/baai/bge-m3"),
)
RERANKER_MODEL_PATH = os.environ.get(
    "RAG_RERANKER_MODEL",
    os.path.expanduser("~/models/baai/bge-reranker-v2-m3"),
)

# --- Weaviate ---
WEAVIATE_COLLECTION_NAME = "RAGDocuments"
# Weaviate embedded mode stores data here
WEAVIATE_DATA_DIR = os.environ.get(
    "RAG_WEAVIATE_DATA_DIR",
    str(PROJECT_ROOT / ".weaviate_data"),
)

# --- Hybrid Search ---
# Alpha: 0.0 = pure BM25, 1.0 = pure vector, 0.5 = balanced
HYBRID_SEARCH_ALPHA = 0.5
SEARCH_LIMIT = 10
RERANK_TOP_K = 5

# --- Document Processing ---
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50

# --- Query Processing (LangGraph) ---
QUERY_CONFIDENCE_THRESHOLD = float(
    os.environ.get("RAG_QUERY_CONFIDENCE_THRESHOLD", "0.6")
)
MAX_SANITIZATION_ITERATIONS = int(
    os.environ.get("RAG_MAX_QUERY_ITERATIONS", "3")
)
QUERY_PROCESSING_MODEL = os.environ.get("RAG_QUERY_MODEL", None)  # defaults to OLLAMA_MODEL (set below)
QUERY_PROCESSING_TEMPERATURE = float(
    os.environ.get("RAG_QUERY_TEMPERATURE", "0.15")
)
QUERY_MAX_LENGTH = int(os.environ.get("RAG_QUERY_MAX_LENGTH", "500"))
QUERY_PROCESSING_TIMEOUT = int(
    os.environ.get("RAG_QUERY_PROCESSING_TIMEOUT", "30")
)
QUERY_LOG_DIR = PROJECT_ROOT / "logs"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
DOMAIN_DESCRIPTION = os.environ.get(
    "RAG_DOMAIN_DESCRIPTION",
    "This knowledge base covers information retrieval, NLP, machine learning, "
    "embeddings, vector search, language models, and related AI/ML topics. "
    "Interpret all acronyms and abbreviations in this domain context.",
)

# --- Knowledge Graph ---
# Set to False to disable KG query expansion (pure hybrid search only)
KG_ENABLED = os.environ.get("RAG_KG_ENABLED", "true").lower() in ("true", "1", "yes")
KG_PATH = PROJECT_ROOT / ".knowledge_graph.json"
KG_OBSIDIAN_EXPORT_DIR = PROJECT_ROOT / "obsidian_graph"

# --- Semantic Chunking ---
SEMANTIC_CHUNKING_ENABLED = os.environ.get(
    "RAG_SEMANTIC_CHUNKING", "true"
).lower() in ("true", "1", "yes")
SEMANTIC_SIMILARITY_THRESHOLD = float(
    os.environ.get("RAG_SEMANTIC_THRESHOLD", "0.75")
)

# --- GLiNER Entity Extraction ---
GLINER_ENABLED = os.environ.get(
    "RAG_GLINER_ENABLED", "true"
).lower() in ("true", "1", "yes")
GLINER_MODEL_PATH = os.environ.get(
    "RAG_GLINER_MODEL",
    os.path.expanduser("~/models/gliner/gliner_medium-v2.1"),
)
GLINER_ENTITY_LABELS = [
    "technology", "algorithm", "framework", "concept",
    "programming language", "data structure",
]

# --- LLM Generation (Ollama) ---
GENERATION_ENABLED = os.environ.get(
    "RAG_GENERATION_ENABLED", "true"
).lower() in ("true", "1", "yes")
OLLAMA_BASE_URL = os.environ.get("RAG_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("RAG_OLLAMA_MODEL", "qwen2.5:3b")
GENERATION_MAX_TOKENS = int(os.environ.get("RAG_GENERATION_MAX_TOKENS", "1024"))
GENERATION_TEMPERATURE = float(os.environ.get("RAG_GENERATION_TEMPERATURE", "0.3"))

# Resolve forward reference: query processing model defaults to generation model
if QUERY_PROCESSING_MODEL is None:
    QUERY_PROCESSING_MODEL = OLLAMA_MODEL

# --- Reliability / Retry ---
RETRY_PROVIDER = os.environ.get("RAG_RETRY_PROVIDER", "local")
RETRY_MAX_ATTEMPTS = int(os.environ.get("RAG_RETRY_MAX_ATTEMPTS", "3"))
RETRY_INITIAL_BACKOFF_SECONDS = float(
    os.environ.get("RAG_RETRY_INITIAL_BACKOFF_SECONDS", "0.5")
)
RETRY_MAX_BACKOFF_SECONDS = float(
    os.environ.get("RAG_RETRY_MAX_BACKOFF_SECONDS", "5.0")
)
RETRY_BACKOFF_MULTIPLIER = float(
    os.environ.get("RAG_RETRY_BACKOFF_MULTIPLIER", "2.0")
)

# --- Temporal (optional) ---
TEMPORAL_TARGET_HOST = os.environ.get("RAG_TEMPORAL_TARGET_HOST", "localhost:7233")
TEMPORAL_TASK_QUEUE = os.environ.get("RAG_TEMPORAL_TASK_QUEUE", "rag-reliability")

# --- Server ---
RAG_API_PORT = int(os.environ.get("RAG_API_PORT", "8000"))
RAG_API_URL = os.environ.get("RAG_API_URL", "http://localhost:8000")
RAG_WORKER_CONCURRENCY = int(os.environ.get("RAG_WORKER_CONCURRENCY", "4"))

# --- Auth / tenancy ---
AUTH_API_KEYS_REQUIRED = os.environ.get("RAG_AUTH_API_KEYS_REQUIRED", "false").lower() in (
    "true",
    "1",
    "yes",
)
AUTH_API_KEYS_JSON = os.environ.get("RAG_AUTH_API_KEYS_JSON", "{}")
AUTH_JWT_ENABLED = os.environ.get("RAG_AUTH_JWT_ENABLED", "false").lower() in (
    "true",
    "1",
    "yes",
)
AUTH_JWT_HS256_SECRET = os.environ.get("RAG_AUTH_JWT_HS256_SECRET", "")
DEFAULT_TENANT_ID = os.environ.get("RAG_DEFAULT_TENANT_ID", "default")
AUTH_OIDC_ENABLED = os.environ.get("RAG_AUTH_OIDC_ENABLED", "false").lower() in (
    "true",
    "1",
    "yes",
)
AUTH_OIDC_ISSUER = os.environ.get("RAG_AUTH_OIDC_ISSUER", "")
AUTH_OIDC_AUDIENCE = os.environ.get("RAG_AUTH_OIDC_AUDIENCE", "")
AUTH_OIDC_JWKS_URL = os.environ.get("RAG_AUTH_OIDC_JWKS_URL", "")
AUTH_OIDC_ROLES_CLAIM = os.environ.get("RAG_AUTH_OIDC_ROLES_CLAIM", "roles")
AUTH_OIDC_TENANT_CLAIM = os.environ.get("RAG_AUTH_OIDC_TENANT_CLAIM", "tenant_id")
AUTH_OIDC_SUBJECT_CLAIM = os.environ.get("RAG_AUTH_OIDC_SUBJECT_CLAIM", "sub")

# --- Rate limit / quotas ---
RATE_LIMIT_ENABLED = os.environ.get("RAG_RATE_LIMIT_ENABLED", "true").lower() in (
    "true",
    "1",
    "yes",
)
RATE_LIMIT_REQUESTS_PER_MINUTE = int(
    os.environ.get("RAG_RATE_LIMIT_REQUESTS_PER_MINUTE", "60")
)
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("RAG_RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_DEFAULT_TENANT_RPM = int(
    os.environ.get("RAG_RATE_LIMIT_DEFAULT_TENANT_RPM", str(RATE_LIMIT_REQUESTS_PER_MINUTE))
)
RATE_LIMIT_DEFAULT_PROJECT_RPM = int(
    os.environ.get("RAG_RATE_LIMIT_DEFAULT_PROJECT_RPM", str(RATE_LIMIT_REQUESTS_PER_MINUTE))
)

# --- API key + quota persistence ---
AUTH_API_KEYS_STORE_PATH = Path(
    os.environ.get("RAG_AUTH_API_KEYS_STORE_PATH", str(RUNTIME_DIR / "security" / "api_keys.json"))
)
AUTH_QUOTAS_STORE_PATH = Path(
    os.environ.get("RAG_AUTH_QUOTAS_STORE_PATH", str(RUNTIME_DIR / "security" / "quotas.json"))
)

# --- Caching ---
CACHE_ENABLED = os.environ.get("RAG_CACHE_ENABLED", "true").lower() in ("true", "1", "yes")
CACHE_PROVIDER = os.environ.get("RAG_CACHE_PROVIDER", "memory")
CACHE_TTL_SECONDS = int(os.environ.get("RAG_CACHE_TTL_SECONDS", "120"))
CACHE_REDIS_URL = os.environ.get("RAG_CACHE_REDIS_URL", "redis://localhost:6379/0")

# --- Retrieval controls ---
RAG_DEFAULT_FAST_PATH = os.environ.get("RAG_DEFAULT_FAST_PATH", "false").lower() in (
    "true",
    "1",
    "yes",
)
RAG_RETRIEVAL_TIMEOUT_MS = int(os.environ.get("RAG_RETRIEVAL_TIMEOUT_MS", "30000"))
RAG_STAGE_BUDGET_QUERY_PROCESSING_MS = int(
    os.environ.get("RAG_STAGE_BUDGET_QUERY_PROCESSING_MS", "12000")
)
RAG_STAGE_BUDGET_KG_EXPANSION_MS = int(
    os.environ.get("RAG_STAGE_BUDGET_KG_EXPANSION_MS", "1000")
)
RAG_STAGE_BUDGET_EMBEDDING_MS = int(os.environ.get("RAG_STAGE_BUDGET_EMBEDDING_MS", "1500"))
RAG_STAGE_BUDGET_HYBRID_SEARCH_MS = int(
    os.environ.get("RAG_STAGE_BUDGET_HYBRID_SEARCH_MS", "5000")
)
RAG_STAGE_BUDGET_RERANKING_MS = int(os.environ.get("RAG_STAGE_BUDGET_RERANKING_MS", "5000"))
RAG_STAGE_BUDGET_GENERATION_MS = int(os.environ.get("RAG_STAGE_BUDGET_GENERATION_MS", "60000"))

# --- Observability ---
OBSERVABILITY_PROVIDER = os.environ.get("RAG_OBSERVABILITY_PROVIDER", "noop")
OBSERVABILITY_SCHEMA_VERSION = "1.0"

# --- Incremental ingestion ---
INGESTION_MANIFEST_PATH = PROCESSED_DIR / "ingestion_manifest.json"

# --- Ingestion pipeline (LangGraph) ---
RAG_INGESTION_LLM_ENABLED = os.environ.get("RAG_INGESTION_LLM_ENABLED", "true").lower() in (
    "true",
    "1",
    "yes",
)
RAG_INGESTION_LLM_MODEL = os.environ.get("RAG_INGESTION_LLM_MODEL", "qwen2.5:3b")
RAG_INGESTION_LLM_TEMPERATURE = float(os.environ.get("RAG_INGESTION_LLM_TEMPERATURE", "0.1"))
RAG_INGESTION_LLM_TIMEOUT_SECONDS = int(
    os.environ.get("RAG_INGESTION_LLM_TIMEOUT_SECONDS", "45")
)
RAG_INGESTION_LLM_MAX_KEYWORDS = int(os.environ.get("RAG_INGESTION_LLM_MAX_KEYWORDS", "12"))
RAG_INGESTION_EXPORT_EXTENSIONS = os.environ.get(
    "RAG_INGESTION_EXPORT_EXTENSIONS",
    ".txt,.md,.markdown,.rst,.html,.htm",
)
RAG_INGESTION_ENABLE_MULTIMODAL_PROCESSING = os.environ.get(
    "RAG_INGESTION_ENABLE_MULTIMODAL_PROCESSING", "false"
).lower() in ("true", "1", "yes")
RAG_INGESTION_ENABLE_DOCUMENT_REFACTORING = os.environ.get(
    "RAG_INGESTION_ENABLE_DOCUMENT_REFACTORING", "false"
).lower() in ("true", "1", "yes")
RAG_INGESTION_ENABLE_CROSS_REFERENCE_EXTRACTION = os.environ.get(
    "RAG_INGESTION_ENABLE_CROSS_REFERENCE_EXTRACTION", "true"
).lower() in ("true", "1", "yes")
RAG_INGESTION_ENABLE_KNOWLEDGE_GRAPH_EXTRACTION = os.environ.get(
    "RAG_INGESTION_ENABLE_KNOWLEDGE_GRAPH_EXTRACTION", "true"
).lower() in ("true", "1", "yes")
RAG_INGESTION_ENABLE_QUALITY_VALIDATION = os.environ.get(
    "RAG_INGESTION_ENABLE_QUALITY_VALIDATION", "true"
).lower() in ("true", "1", "yes")
RAG_INGESTION_ENABLE_KNOWLEDGE_GRAPH_STORAGE = os.environ.get(
    "RAG_INGESTION_ENABLE_KNOWLEDGE_GRAPH_STORAGE", "true"
).lower() in ("true", "1", "yes")
RAG_INGESTION_VERBOSE_STAGE_LOGS = os.environ.get(
    "RAG_INGESTION_VERBOSE_STAGE_LOGS", "false"
).lower() in ("true", "1", "yes")
RAG_INGESTION_PERSIST_REFACTOR_MIRROR = os.environ.get(
    "RAG_INGESTION_PERSIST_REFACTOR_MIRROR", "true"
).lower() in ("true", "1", "yes")
RAG_INGESTION_MIRROR_DIR = PROCESSED_DIR / "refactor_mirror"
