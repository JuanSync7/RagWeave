# NeMo Guardrails Configuration

This directory contains the NeMo Guardrails configuration for the RAG pipeline.

## File Layout

| File | Purpose |
|------|---------|
| `config.yml` | NeMo runtime config: model settings, rail flow registration, detection thresholds |
| `actions.py` | Python action wrappers — auto-discovered by NeMo at startup |
| `input_rails.co` | Colang 2.0 input rail flows (query validation, Python executor bridge) |
| `conversation.co` | Dialog management flows (greetings, farewells, follow-ups, off-topic) |
| `output_rails.co` | Output rail flows (citations, confidence, length, scope, Python executor bridge) |
| `safety.co` | Security enforcement flows (exfiltration, role boundary, jailbreak escalation) |
| `dialog_patterns.co` | RAG dialog patterns (disambiguation, scope explanation, feedback) |

## NeMo Conventions

- **`config.yml`** must include `colang_version: "2.x"` for Colang 2.0 parsing
- **`actions.py`** is auto-discovered by NeMo — any `@action()`-decorated function is available to Colang flows
- **`.co` files** are auto-discovered — all files in this directory with `.co` extension are parsed
- **Rail flows** (named `input rails *` / `output rails *`) must be registered in `config.yml` to execute
- **Dialog flows** (any other name) are auto-matched by NeMo's intent engine

## Adding a New Flow

See `docs/guardrails/COLANG_DESIGN_GUIDE.md` for step-by-step instructions.
