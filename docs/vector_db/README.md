<!-- @summary
Vector store subsystem documentation: spec, spec summary, design, implementation plan,
engineering guide, and test docs for the backend-agnostic vector_db subsystem.
@end-summary -->

# docs/vector_db

## Overview

Engineering documentation for the vector store subsystem — the backend-agnostic persistence and search abstraction beneath every embedding-based retrieval flow in RagWeave. Defines a stable `VectorBackend` ABC, a lazy config-driven dispatcher, backend-independent data contracts, and a concrete Weaviate implementation covering both text chunk collections and visual page collections.

Source code lives in `src/vector_db/`. Pipeline code (ingestion + retrieval) imports only from `src.vector_db` — never from backend-specific modules.

## Files

| File | Purpose |
| --- | --- |
| `VECTOR_DB_SPEC.md` | Authoritative requirements baseline (`REQ-VDB-100`–`REQ-VDB-1199`) |
| `VECTOR_DB_SPEC_SUMMARY.md` | Concise summary of the spec — 13-section template with tech-agnostic system overview |
| `VECTOR_DB_DESIGN.md` | Design document — layer model, key decisions, contracts, data flow |
| `VECTOR_DB_IMPLEMENTATION_DOCS.md` | Implementation plan — task DAG, build order, definition of done |
| `VECTOR_DB_ENGINEERING_GUIDE.md` | Post-implementation engineering reference — module-by-module guide, troubleshooting, extension recipes |
| `VECTOR_DB_TEST_DOCS.md` | Test plan — inventory, coverage matrix, fixtures, critical scenarios |
