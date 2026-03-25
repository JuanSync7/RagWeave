# Colang 2.0 Design Guide

## Part A — Colang 2.0 Design Principles

### Syntax Reference

Colang 2.0 (NeMo Guardrails ≥0.21.0) uses a Python-like syntax. Key constructs:

```colang
# Flow definition
flow my_flow_name
  # statements...

# Await an action (calls Python @action() function)
$result = await action_name(param=$variable)

# Bot response
await bot say "message"
await bot say $dynamic_variable

# Conditional branching
if $result.field == False
  await bot say "blocked"
  abort
else if $result.other_field == True
  $var = $result.value

# Variables
$my_var = "value"
$my_var = $result.field
```

### Configuration

The config file MUST include `colang_version: "2.x"`:

```yaml
colang_version: "2.x"

models:
  - type: main
    engine: ollama
    model: ${RAG_OLLAMA_MODEL:-qwen2.5:3b}
    parameters:
      base_url: ${RAG_OLLAMA_URL:-http://localhost:11434}
```

### Naming Conventions

| Pattern | Type | Registration | Behavior |
|---------|------|-------------|----------|
| `flow input rails *` | Input rail | Must be listed in `config.yml` `rails.input.flows` | Runs before generation; `abort` blocks the query |
| `flow output rails *` | Output rail | Must be listed in `config.yml` `rails.output.flows` | Runs after generation; `abort` blocks the response |
| `flow handle *` | Dialog flow | Auto-discovered from `.co` files | Standalone; matches by intent |
| `flow user said *` | Intent matcher | Auto-discovered from `.co` files | Defines user intent patterns |

### When to Use Colang vs Python

| Use Case | Colang | Python |
|----------|--------|--------|
| Declarative policy decisions (block/allow) | ✓ | |
| Dialog routing (greeting, farewell, feedback) | ✓ | |
| Message templates | ✓ | |
| Heavy compute (ML inference, parallel execution) | | ✓ |
| External API calls | | ✓ |
| Complex data transformations | | ✓ |
| Rate limiting with session state | | ✓ |

### Action Return Contract

All actions return **dicts**. Colang flows extract fields via dot notation:

```colang
$result = await check_query_length(query=$user_message)
if $result.valid == False
  await bot say $result.reason
  abort
```

For actions that modify `$bot_message`, use a temp variable:

```colang
$mod = await prepend_hedge(answer=$bot_message)
$bot_message = $mod.answer
```

### Common Pitfalls

1. **Flow ordering matters.** Input/output rails execute in the order registered in `config.yml`. Put fast deterministic checks first, heavy compute last.

2. **`abort` only stops the current rail pipeline**, not the entire request. Use it to prevent retrieval (input rails) or block a response (output rails).

3. **Non-aborting input rails** cannot send bot messages — the message is lost because the pipeline continues. Use context variables instead:
   ```colang
   # Set context var in input rail
   $sensitive_disclaimer = $result.disclaimer
   # Read it in output rail
   if $sensitive_disclaimer
     $mod = await prepend_text(text=$sensitive_disclaimer, answer=$bot_message)
     $bot_message = $mod.answer
   ```

4. **`execute` is Colang 1.0 syntax.** Use `await` in Colang 2.0.

5. **`colang_version: "2.x"` is required** in config.yml. Without it, the parser defaults to 1.0 and 2.0 syntax will fail.

### Testing Strategies

- **Unit test actions** in isolation — no NeMo runtime needed. Import directly from `config.guardrails.actions`.
- **Integration test flows** by parsing with `RailsConfig.from_path()` — verifies syntax without running.
- **E2E tests** use `runtime.generate_async()` — requires NeMo + Ollama running.

---

## Part B — Project Implementation Guide

### File Layout

```
config/guardrails/
├── config.yml            # NeMo runtime config + flow registration
├── actions.py            # Python action wrappers (NeMo auto-discovers)
├── input_rails.co        # Query validation flows (5 flows)
├── conversation.co       # Dialog management flows (10 flows)
├── output_rails.co       # Response quality flows (7 flows)
├── safety.co             # Security enforcement flows (4 flows)
└── dialog_patterns.co    # RAG dialog patterns (7 flows)
```

### How to Add a New Input Rail

1. Add the flow to the appropriate `.co` file:
   ```colang
   flow input rails check my_new_check
     $result = await my_new_action(query=$user_message)
     if $result.blocked == True
       await bot say "Blocked reason."
       abort
   ```

2. Add the action to `config/guardrails/actions.py`:
   ```python
   @action()
   @_fail_open({"blocked": False})
   async def my_new_action(query: str) -> dict:
       # Your check logic here
       return {"blocked": False}
   ```

3. Register the flow in `config/guardrails/config.yml`:
   ```yaml
   rails:
     input:
       flows:
         - input rails check my_new_check  # Add in desired order
   ```

### How to Add a New Dialog Flow

Dialog flows don't need registration — NeMo auto-discovers them:

1. Add intent matcher and handler to a `.co` file:
   ```colang
   flow user asked my_question
     user said "my trigger phrase"

   flow handle my_question
     user asked my_question
     await bot say "My response."
   ```

### Execution Order

```
NeMo generate_async() [single call]
    │
    ├── Input Rails (Colang, in registered order):
    │   ├── check query length / language / clarity / abuse
    │   ├── check exfiltration / role boundary / jailbreak escalation
    │   ├── check sensitive topic (sets $sensitive_disclaimer)
    │   ├── check off topic / ambiguity
    │   └── run python input rails ← InputRailExecutor + RailMergeGate
    │
    ├── Generation:
    │   └── rag_retrieve_and_generate() ← RAG pipeline
    │
    └── Output Rails (Colang, in registered order):
        ├── run python output rails ← OutputRailExecutor
        ├── prepend disclaimer (if $sensitive_disclaimer set)
        ├── check no results / confidence / citations / length / scope
```

### Configuration Reference

All configuration is via existing `RAG_NEMO_*` environment variables. No new env vars were added. See `config/settings.py` lines 397-475 for the full list.

### Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| `SyntaxError` on startup | Colang syntax error in `.co` file | Check for `execute` (should be `await`), missing `colang_version: "2.x"` |
| Actions not found | `actions.py` not in config directory | Verify `config/guardrails/actions.py` exists |
| Flow not executing | Not registered in `config.yml` | Add flow name to `rails.input.flows` or `rails.output.flows` |
| Import errors | NeMo not installed | Actions use conditional import; set `RAG_NEMO_ENABLED=false` to skip |
| `langchain_core` error in tests | langsmith plugin conflict | Ensure `tests/guardrails/conftest.py` exists with ghost module cleanup |
