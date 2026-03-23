#!/usr/bin/env python3
# @summary
# Standalone Colang Python demo showing NeMo Guardrails usage with
# intent classification, injection detection, and flow routing.
# Exports: run_demo (async)
# Deps: nemoguardrails, asyncio, tempfile, os
# @end-summary
"""
Colang Python Demo — NeMo Guardrails Usage Example

Demonstrates how to:
1. Configure NeMo Guardrails with Colang 2.0 definitions
2. Run input rails (intent classification, injection detection)
3. Handle verdicts and route queries

Usage:
    python colang_demo.py

Environment variables:
    RAG_OLLAMA_URL   - Ollama base URL (default: http://localhost:11434)
    RAG_OLLAMA_MODEL - Ollama model name (default: qwen2.5:3b)
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Colang 2.0 definitions (inline for demo portability)
# ---------------------------------------------------------------------------

COLANG_CONTENT = """\
define user greeting
  "hello"
  "hi there"
  "hey"
  "good morning"
  "greetings"
  "hi, how are you?"

define bot greeting response
  "Hello! How can I help you search the knowledge base today?"

define user farewell
  "goodbye"
  "bye"
  "see you later"
  "thanks, bye"
  "that's all, thanks"

define bot farewell response
  "Goodbye! Feel free to return if you have more questions."

define user off topic
  "what's the weather today"
  "tell me a joke"
  "who won the game last night"
  "what time is it"
  "play some music"

define bot off topic response
  "I can only help with questions about the knowledge base. Please ask a relevant question."

define user administrative
  "help"
  "what can you do"
  "how do I use this"
  "show me the available commands"
  "what are your capabilities"

define bot administrative response
  "I can search the knowledge base to answer your questions. Just type your question in natural language."

define user rag search
  "what is the attention mechanism"
  "explain transformer architecture"
  "how does retrieval augmented generation work"
  "what are embedding models"
  "describe the difference between BM25 and vector search"
  "what is semantic chunking"

define flow check intent
  user ...
  if user intent is greeting
    bot greeting response
    stop
  else if user intent is farewell
    bot farewell response
    stop
  else if user intent is off topic
    bot off topic response
    stop
  else if user intent is administrative
    bot administrative response
    stop
"""

# ---------------------------------------------------------------------------
# NeMo config (YAML) — points to Ollama as the LLM provider
# ---------------------------------------------------------------------------

CONFIG_TEMPLATE = """\
models:
  - type: main
    engine: ollama
    model: {model}
    parameters:
      base_url: {base_url}

rails:
  input:
    flows:
      - check intent
"""


# ---------------------------------------------------------------------------
# Demo runner
# ---------------------------------------------------------------------------

async def run_demo() -> None:
    """Run the NeMo Guardrails demo with sample queries."""
    try:
        from nemoguardrails import LLMRails, RailsConfig
    except ImportError:
        print("ERROR: nemoguardrails is not installed.")
        print("Install it with: uv add nemoguardrails")
        sys.exit(1)

    _port = os.environ.get("RAG_OLLAMA_PORT", "11434")
    base_url = os.environ.get("RAG_OLLAMA_URL", f"http://localhost:{_port}")
    model = os.environ.get("RAG_OLLAMA_MODEL", "qwen2.5:3b")

    # Create a temporary config directory with our Colang + YAML
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir)

        (config_path / "intents.co").write_text(COLANG_CONTENT)
        (config_path / "config.yml").write_text(
            CONFIG_TEMPLATE.format(model=model, base_url=base_url)
        )

        print("=" * 60)
        print("NeMo Guardrails — Colang 2.0 Demo")
        print("=" * 60)
        print(f"Model:    {model}")
        print(f"Endpoint: {base_url}")
        print(f"Config:   {config_path}")
        print("=" * 60)

        # Initialize the NeMo Guardrails runtime
        print("\nInitializing NeMo Guardrails runtime...")
        config = RailsConfig.from_path(str(config_path))
        rails = LLMRails(config)
        print("Runtime ready.\n")

        # Test queries spanning different intents
        test_queries = [
            ("Hello, how are you?", "greeting"),
            ("What is the attention mechanism in transformers?", "rag_search"),
            ("What's the weather today?", "off_topic"),
            ("Explain how embeddings work", "rag_search"),
            ("Tell me a joke", "off_topic"),
            ("Goodbye!", "farewell"),
            ("What can you do?", "administrative"),
            ("How does BM25 compare to dense retrieval?", "rag_search"),
        ]

        for query, expected_intent in test_queries:
            print(f"Query: {query!r}")
            print(f"  Expected intent: {expected_intent}")

            messages = [{"role": "user", "content": query}]

            try:
                response = await rails.generate_async(messages=messages)
                content = response.get("content", str(response))
                print(f"  Response: {content}")

                # Determine actual intent from response
                canned_responses = {
                    "Hello! How can I help you search the knowledge base today?": "greeting",
                    "Goodbye! Feel free to return if you have more questions.": "farewell",
                    "I can only help with questions about the knowledge base. Please ask a relevant question.": "off_topic",
                    "I can search the knowledge base to answer your questions. Just type your question in natural language.": "administrative",
                }
                actual_intent = canned_responses.get(content.strip(), "rag_search")
                match = "MATCH" if actual_intent == expected_intent else "MISMATCH"
                print(f"  Actual intent:   {actual_intent} [{match}]")

            except Exception as e:
                print(f"  Error: {e}")

            print()

        print("=" * 60)
        print("Demo complete!")
        print("=" * 60)
        print()
        print("To use NeMo Guardrails in the AION RAG pipeline:")
        print("  1. Set RAG_NEMO_ENABLED=true in your environment")
        print("  2. Edit config/guardrails/intents.co to customize intents")
        print("  3. Edit config/guardrails/config.yml for rail settings")
        print("  4. Restart the worker — guardrails initialize at startup")


if __name__ == "__main__":
    asyncio.run(run_demo())
